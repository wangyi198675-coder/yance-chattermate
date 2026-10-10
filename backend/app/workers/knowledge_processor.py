"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import asyncio
import signal
from contextlib import suppress
from app.database import SessionLocal
from app.repositories.knowledge_queue import KnowledgeQueueRepository
from app.repositories.knowledge import KnowledgeRepository
from app.knowledge.knowledge_base import KnowledgeManager
from app.knowledge import page_editor
from app.services import knowledge_vector_links
from app.models.knowledge_queue import QueueStatus, ProcessingStage
from app.core.logger import get_logger
import os
from app.core.processor import PROCESSOR_STATUS
from datetime import datetime
from app.models.notification import Notification, NotificationType
from app.services.user import send_fcm_notification
from urllib.parse import urlparse, unquote

logger = get_logger(__name__)

# Knowledge ingestion is not proven replay-safe at every interruption point.
# Interrupted work therefore fails closed instead of being blindly requeued.
INTERRUPTED_CANCELLED_REASON = "knowledge_worker_interrupted:cancelled"
INTERRUPTED_STALE_REASON = "knowledge_worker_interrupted:stale_processing"
DEFAULT_STALE_PROCESSING_SECONDS = int(os.environ.get("KNOWLEDGE_STALE_PROCESSING_SECONDS", "900"))
DEFAULT_DRAIN_TIMEOUT_SECONDS = float(os.environ.get("KNOWLEDGE_DRAIN_TIMEOUT_SECONDS", "30"))


def get_user_friendly_filename(source: str, source_type: str) -> str:
    """Extract a user-friendly filename from the source URL or path"""
    try:
        if source_type in ('website', 'sitemap'):
            # For websites/sitemaps, just return the domain
            parsed = urlparse(source)
            return parsed.netloc or source
        
        # For files (PDF, etc.), extract filename from URL or path
        if source.startswith('http'):
            # Parse URL to get the path
            parsed = urlparse(source)
            path = parsed.path
            
            # Extract filename from path
            if path:
                # Get the last part of the path (filename)
                filename = path.split('/')[-1]
                # URL decode the filename to handle encoded characters like %20
                filename = unquote(filename)
                # Remove query parameters if any
                filename = filename.split('?')[0]
                if filename:
                    return filename
            
            # Fallback to domain if no filename found
            return parsed.netloc or source
        else:
            # For local file paths, just get the basename
            return os.path.basename(source)
            
    except Exception as e:
        logger.warning(f"Error extracting filename from {source}: {e}")
        return source


def _sync_vector_agent_links(db, queue_item) -> None:
    """Point the ingested chunks at every agent the source is linked to.

    Ingestion writes ``filters.agent_id`` from the queue row's single optional
    ``agent_id``, so a run queued without one leaves every chunk with an empty
    list. Retrieval matches on that filter, so the source is invisible to the
    agent while the dashboard still shows it as linked — the failure that left
    two production sources unreadable until the links were rebuilt by hand.

    The relational links are the authority, so re-derive from them. Idempotent,
    and non-fatal: the content is already ingested, and losing the run over a
    filter refresh would be worse than the stale filter.
    """
    try:
        knowledge_repo = KnowledgeRepository(db)
        sources = knowledge_repo.get_by_sources(
            queue_item.organization_id, [queue_item.source]
        )
        if not sources:
            return

        # An org can hold more than one knowledge row for the same URL, and they
        # share one set of vector chunks (keyed on the source name). Sync the
        # union of their links once, rather than per row where the last write
        # would drop the other rows' agents.
        agent_ids = sorted({
            agent_id
            for knowledge in sources
            for agent_id in page_editor.agent_ids_for(knowledge)
        })
        knowledge_vector_links.sync_agent_ids(db, sources[0], agent_ids)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(
            f"Could not refresh vector agent filters for {queue_item.source} "
            f"(non-fatal, content was ingested): {e}"
        )


def recover_stale_processing(older_than_seconds: int = DEFAULT_STALE_PROCESSING_SECONDS) -> int:
    """Fail stale PROCESSING rows in the existing knowledge queue authority.

    We deliberately do not requeue here: ingestion may already have produced
    side effects when a previous process died, and replay safety has not been
    proven for every stage. The next operator/user action can retry explicitly.
    """
    with SessionLocal() as db:
        repo = KnowledgeQueueRepository(db)
        recovered = repo.fail_stale_processing(
            older_than_seconds=older_than_seconds,
            reason=INTERRUPTED_STALE_REASON,
        )
    if recovered:
        logger.warning(f"Failed {recovered} stale knowledge PROCESSING item(s) closed")
    return recovered


async def process_queue_item(queue_item_id: int):
    """Process a single queue item"""
    with SessionLocal() as db:
        try:
            queue_repo = KnowledgeQueueRepository(db)
            queue_item = queue_repo.get_by_id(queue_item_id)

            if not queue_item:
                logger.error(f"Queue item {queue_item_id} not found")
                return

            # Get knowledge manager instance
            knowledge = KnowledgeManager(
                org_id=queue_item.organization_id,
                agent_id=queue_item.agent_id
            )

            # Process if status is pending
            if queue_item.status == QueueStatus.PENDING:
                # Update to processing
                queue_item.status = QueueStatus.PROCESSING
                queue_item.processing_stage = ProcessingStage.NOT_STARTED
                queue_item.progress_percentage = 0.0
                db.commit()

                await knowledge.process_knowledge(queue_item)

                _sync_vector_agent_links(db, queue_item)

                # Create notification for successful processing
                user_friendly_name = get_user_friendly_filename(queue_item.source, queue_item.source_type)
                notification = Notification(
                    user_id=queue_item.user_id,
                    type=NotificationType.KNOWLEDGE_PROCESSED,
                    title="Knowledge Processing Complete",
                    message=f"Successfully processed {user_friendly_name}",
                    # The column is notification_metadata; the old metadata=
                    # kwarg silently shadowed Base.metadata and stored nothing.
                    notification_metadata={"queue_id": queue_item.id}
                )
                db.add(notification)
                db.commit()

                # Send FCM notification
                await send_fcm_notification(queue_item.user_id, notification, db)

                # Auto-draft FAQs from the new source for orgs using the help
                # center. Fully non-fatal — even an import failure of the FAQ
                # stack must not flip an already-successful run to FAILED.
                try:
                    from app.services.faq_generation import maybe_enqueue_auto_faq_job
                    maybe_enqueue_auto_faq_job(db, queue_item)
                except Exception as faq_hook_err:
                    logger.error(f"Auto FAQ hook unavailable (non-fatal): {faq_hook_err}")

            queue_item.status = QueueStatus.COMPLETED
            db.commit()

        except asyncio.CancelledError:
            # asyncio.CancelledError is a BaseException on Python 3.12, so the
            # generic Exception handler below cannot settle interrupted work.
            logger.warning(f"Knowledge queue item {queue_item_id} cancelled; failing closed")
            try:
                db.rollback()
            except Exception:
                pass
            try:
                current = queue_repo.get_by_id(queue_item_id)
                if current and current.status == QueueStatus.PROCESSING:
                    current.status = QueueStatus.FAILED
                    current.error = INTERRUPTED_CANCELLED_REASON
                    db.commit()
            except Exception as settle_err:
                logger.error(
                    f"Could not settle cancelled knowledge queue item {queue_item_id}: {settle_err}"
                )
            raise

        except Exception as e:
            logger.error(f"Error processing queue item {queue_item_id}: {str(e)}")
            try:
                queue_item.status = QueueStatus.FAILED
                # Persist the reason so the UI can show why it failed.
                queue_item.error = str(e)

                # Create notification for failed processing
                user_friendly_name = get_user_friendly_filename(queue_item.source, queue_item.source_type)
                notification = Notification(
                    user_id=queue_item.user_id,
                    type=NotificationType.KNOWLEDGE_FAILED,
                    title="Knowledge Processing Failed",
                    message=f"Failed to process {user_friendly_name}: {str(e)}",
                    notification_metadata={"queue_id": queue_item.id}
                )
                db.add(notification)
                db.commit()

                # Send FCM notification for failure
                await send_fcm_notification(queue_item.user_id, notification, db)
            except Exception as notify_err:
                logger.error(f"Error creating failure notification: {notify_err}")

            raise


async def run_processor(stop_event: asyncio.Event | None = None):
    """Single processor pass using the existing knowledge queue as authority."""
    if stop_event is not None and stop_event.is_set():
        return

    try:
        PROCESSOR_STATUS["is_running"] = True
        PROCESSOR_STATUS["error"] = None

        # Get pending items with proper connection handling.
        with SessionLocal() as db:
            queue_repo = KnowledgeQueueRepository(db)
            pending_items = queue_repo.get_pending()
            pending_item_ids = [item.id for item in pending_items] if pending_items else []

        # A stop that arrives after the read but before scheduling must not start
        # new PENDING work. Tasks waiting on the semaphore re-check as well.
        if stop_event is not None and stop_event.is_set():
            return

        if pending_item_ids:
            semaphore = asyncio.Semaphore(2)

            async def process_with_semaphore(item_id):
                if stop_event is not None and stop_event.is_set():
                    return
                async with semaphore:
                    if stop_event is not None and stop_event.is_set():
                        return
                    await process_queue_item(item_id)

            await asyncio.gather(*[process_with_semaphore(item_id) for item_id in pending_item_ids])

        PROCESSOR_STATUS["last_run"] = datetime.utcnow().isoformat()

    except Exception as e:
        logger.error(f"Error in knowledge processor: {str(e)}")
        PROCESSOR_STATUS["error"] = str(e)
        raise

    finally:
        PROCESSOR_STATUS["is_running"] = False


async def run_processor_loop(
    stop_event: asyncio.Event,
    poll_interval: float = 60,
    drain_timeout: float = DEFAULT_DRAIN_TIMEOUT_SECONDS,
):
    """Stop claiming, drain current work for a bound, then cancel fail-closed."""
    recover_stale_processing()
    while not stop_event.is_set():
        current_pass = asyncio.create_task(run_processor(stop_event=stop_event))
        stop_waiter = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait(
            {current_pass, stop_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if current_pass in done:
            stop_waiter.cancel()
            with suppress(asyncio.CancelledError):
                await stop_waiter
            try:
                await current_pass
            except Exception as e:
                logger.error(f"Error in knowledge processor loop: {e}")
            if stop_event.is_set():
                return
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                return
            except asyncio.TimeoutError:
                continue

        # Shutdown arrived while a pass is active. Let current work finish up to
        # the configured bound; then cancellation flows into process_queue_item,
        # which deterministically settles PROCESSING as FAILED.
        try:
            await asyncio.wait_for(asyncio.shield(current_pass), timeout=drain_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Knowledge worker drain exceeded {drain_timeout}s; cancelling active work fail-closed"
            )
            current_pass.cancel()
            with suppress(asyncio.CancelledError):
                await current_pass
        except Exception as e:
            logger.error(f"Error while draining knowledge processor: {e}")
        finally:
            if not stop_waiter.done():
                stop_waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await stop_waiter
        return


def _install_stop_handlers(stop_event: asyncio.Event) -> None:
    """Translate native process signals into the worker-local stop Event."""
    loop = asyncio.get_running_loop()

    def request_stop(signal_name: str) -> None:
        if not stop_event.is_set():
            logger.info(f"Knowledge processor received {signal_name}; beginning bounded drain")
            stop_event.set()

    signal_names = ["SIGINT", "SIGTERM"]
    if hasattr(signal, "SIGBREAK"):
        signal_names.append("SIGBREAK")

    for name in signal_names:
        sig = getattr(signal, name)
        try:
            loop.add_signal_handler(sig, request_stop, name)
        except (NotImplementedError, RuntimeError):
            try:
                signal.signal(
                    sig,
                    lambda _signum, _frame, signal_name=name: loop.call_soon_threadsafe(
                        request_stop, signal_name
                    ),
                )
            except (OSError, ValueError):
                logger.debug(f"Signal {name} is not installable on this runtime")


# Main entry point for running as a standalone service
if __name__ == "__main__":
    logger.info("Starting knowledge processor service")

    async def main():
        """Run knowledge with bounded shutdown; keep the existing FAQ companion."""
        stop_event = asyncio.Event()
        _install_stop_handlers(stop_event)

        faq_task = None
        try:
            from app.workers.faq_processor import run_faq_processor_loop
            faq_task = asyncio.create_task(run_faq_processor_loop())
        except Exception as e:
            logger.error(f"FAQ processor unavailable, running knowledge only: {e}")

        try:
            await run_processor_loop(stop_event)
        finally:
            stop_event.set()
            if faq_task is not None:
                faq_task.cancel()
                with suppress(asyncio.CancelledError):
                    await faq_task

    asyncio.run(main())
