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
from datetime import datetime, timezone
from uuid import UUID
from app.database import SessionLocal
from app.core.logger import get_logger
from app.agents.chat_agent import ChatAgent, ChatResponse
from app.repositories.chat import ChatRepository
from app.repositories.session_to_agent import SessionToAgentRepository
from app.services.workflow_execution import WorkflowExecutionService
from app.core.security import decrypt_api_key
from app.models.schemas.chat import TransferReasonType
from app.models.chat_history import ChatHistory
from app.models.session_to_agent import SessionStatus, SessionToAgent
from app.models.agent import Agent
from app.models.user import UserGroup
from app.services.yance_turn_authority import revalidate_auto_send
from app.services.message_delivery import deliver_to_customer
from app.services.yance_turn_authority import build_auto_send_authority, context_revision, reconcile_workflow_own_revision

logger = get_logger(__name__)


def latest_workflow_source_id(db, session_id):
    """Capture the incoming turn BEFORE workflow generation starts."""
    return (db.query(ChatHistory.id)
            .filter(ChatHistory.session_id == session_id,
                    ChatHistory.message_type == "user")
            .order_by(ChatHistory.id.desc()).limit(1).scalar())


async def deliver_workflow_auto_message(db, active_session, *,
                                         session_id, org_id, agent_id, customer_id,
                                         message, source_message_id, generation_revision,
                                         attributes=None,
                                         transfer_to_human=False, end_chat=False,
                                         request_rating=False, existing_message=None,
                                         terminal_transfer=None):
    """One workflow chat-response seam; control/form events remain elsewhere."""
    if not source_message_id or not generation_revision:
        logger.warning("No generation authority for workflow automatic chat_response")
        return None
    row_attrs = {"ai_auto_pending": True, **(attributes or {"workflow_execution": True})}
    terminal = row_attrs.get("workflow_terminal_control")
    if (transfer_to_human or end_chat) and terminal is None:
        terminal = (
            {"kind": "transfer", "state": "pending",
             "transfer": terminal_transfer or {
                 "message": message, "transfer_reason": None,
                 "transfer_description": None, "transfer_group_id": None}}
            if transfer_to_human else
            {"kind": "end_chat", "state": "pending"})
        row_attrs["workflow_terminal_control"] = terminal
    # Existing row is a crash-before-precommit child, not a second send.
    # Bind its terminal intent before its first Web delivery attempt.
    if (existing_message is not None and terminal is not None
            and not (existing_message.attributes or {}).get("workflow_terminal_control")):
        ChatRepository(db).update_message_attributes(
            existing_message.id, {"workflow_terminal_control": terminal})
        db.refresh(existing_message)
    bot = existing_message or ChatRepository(db).create_message({
        "message": message, "message_type": "bot",
        "session_id": session_id, "organization_id": org_id,
        "agent_id": agent_id, "customer_id": customer_id,
        "attributes": row_attrs,
    })
    snapshot = build_auto_send_authority(
        db, active_session, organization_id=org_id, agent_id=agent_id,
        source_message_id=source_message_id, bot_message_id=bot.id,
        context_revision_at_generation=generation_revision)
    delivery = await deliver_to_customer(db, active_session, {
        "message": message, "type": "chat_response", "session_id": session_id,
        "message_id": bot.id, "transfer_to_human": transfer_to_human,
        "end_chat": end_chat, "request_rating": request_rating,
        "shopify_output": None, "_ai_auto_authority": snapshot,
    })
    if delivery is not None and delivery.ok and terminal is not None:
        await apply_pending_workflow_terminal_control(db, active_session, bot.id)
        db.expire_all()
    return delivery


class WorkflowChatService:
    """Service for handling workflow-based chat processing"""
    
    def __init__(self, db):
        self.db = db
        self.chat_repo = ChatRepository(db)
        self.session_repo = SessionToAgentRepository(db)
        self.workflow_service = WorkflowExecutionService(db)
    
    async def handle_workflow_chat(
        self,
        active_session,
        message: str,
        session_id: str,
        org_id: str,
        customer_id: str,
        session: dict,
        sio,
        namespace: str = '/widget',
        source: str = None
    ) -> ChatResponse:
        """
        Handle chat processing for workflow-enabled agents
        
        Args:
            active_session: The active session object
            message: User message
            session_id: Session ID
            org_id: Organization ID
            customer_id: Customer ID
            session: Session data containing agent and AI config
            sio: SocketIO instance for emitting events
            namespace: SocketIO namespace
            
        Returns:
            ChatResponse: The response from workflow execution
        """
        
        # Store user message in chat history
        source_message = self.chat_repo.create_message({
            "message": message,
            "message_type": "user",
            "session_id": session_id,
            "organization_id": org_id,
            "agent_id": session['agent_id'],
            "customer_id": customer_id,
        })
        
        # Capture the generation revision BEFORE workflow execution.
        generation_revision = context_revision(self.db, active_session)
        # Execute workflow
        workflow_result = await self.workflow_service.execute_workflow(
            session_id=session_id,
            user_message=message,
            workflow_id=active_session.workflow_id,
            current_node_id=active_session.current_node_id,
            workflow_state=active_session.workflow_state,
            api_key=decrypt_api_key(session['ai_config'].encrypted_api_key),
            model_name=session['ai_config'].model_name,
            model_type=session['ai_config'].model_type,
            base_url=(session['ai_config'].settings or {}).get('base_url'),
            fallback_model_name=(session['ai_config'].settings or {}).get('fallback_model_name'),
            reasoning_strength=(session['ai_config'].settings or {}).get('reasoning_strength'),
            org_id=org_id,
            agent_id=session['agent_id'],
            customer_id=customer_id,
            source=source
        )
        
        # Workflow node progression can advance session.updated_at.
        # Reconcile only when the logical message identity stayed unchanged.
        generation_revision = reconcile_workflow_own_revision(
            self.db, active_session, generation_revision)
        if workflow_result.success:
            return await self._handle_successful_workflow(
                workflow_result, active_session, session_id, org_id, 
                customer_id, session, sio, namespace, source_message.id,
                generation_revision
            )
        else:
            return await self._handle_failed_workflow(
                workflow_result, session_id, org_id, session, customer_id,
                active_session, source_message.id, generation_revision
            )
    
    async def _handle_successful_workflow(
        self, 
        workflow_result, 
        active_session, 
        session_id: str, 
        org_id: str, 
        customer_id: str, 
        session: dict, 
        sio, 
        namespace: str,
        source_message_id: int,
        generation_revision: str,
    ) -> ChatResponse:
        """Handle successful workflow execution"""
        

        
        current_revision = generation_revision
        # Handle intermediate messages from MESSAGE nodes during automatic execution
        if workflow_result.intermediate_messages:
            current_revision, completed = await self._handle_intermediate_messages(
                workflow_result.intermediate_messages, session_id, org_id,
                session, customer_id, active_session, sio, namespace,
                source_message_id, current_revision, workflow_result
            )
            if not completed:
                # The interrupted intermediate has its durable sending row
                # and subsequent machine work stored as continuation metadata
                # ON THAT ROW. No later bot intent may poison its revision.
                return None
        
        # Check if this is a form node that needs to display a form
        if workflow_result.form_data:
            await self._handle_form_display(workflow_result, session_id, sio, namespace)
            return None  # Don't send a regular chat response for form display
        
        # Create ChatResponse object from workflow result
        response = ChatResponse(
            message=workflow_result.message,
            transfer_to_human=workflow_result.transfer_to_human,
            transfer_reason=None,
            transfer_description=None,
            end_chat=workflow_result.end_chat,
            request_rating=workflow_result.request_rating,
            create_ticket=False
        )
        
        # Handle transfer to human if requested by workflow LLM
        if workflow_result.transfer_to_human:
            response.transfer_reason = (TransferReasonType(workflow_result.transfer_reason)
                                        if workflow_result.transfer_reason else None)
            response.transfer_description = workflow_result.transfer_description
            # Transfer mutates session.status; never do it before commitment.
            # The widget completes the human-control transfer ONLY after the
            # canonical machine chat text succeeds through the final send gate.
            response = await self._handle_workflow_transfer(
                workflow_result, session_id, org_id, session, customer_id,
                response, prepare_only=True)
            response._workflow_transfer_pending = workflow_transfer_spec(workflow_result)
        
        # Handle end chat if requested by workflow
        if workflow_result.end_chat and workflow_result.request_rating:
            # Preserve existing rating copy; _handle_end_chat mutates CLOSED,
            # so it cannot run before the legitimate final reply is delivered.
            response.message += WORKFLOW_RATING_COPY
        
        # Only store message if there's actual content
        if workflow_result.message:
            self._store_workflow_response(
                response, session_id, org_id, session, customer_id, 
                active_session, workflow_result, source_message_id,
                current_revision
            )
        
        return response
    
    async def _handle_intermediate_messages(
        self, intermediate_messages, session_id: str, org_id: str,
        session: dict, customer_id: str, active_session, sio,
        namespace: str, source_message_id: int, generation_revision: str,
        workflow_result=None,
    ):
        """Persist each MESSAGE and defer its successors until ACK/commit."""
        current_revision = generation_revision
        for index, intermediate_message in enumerate(intermediate_messages):
            tail = [{"kind": "intermediate", "message": m}
                    for m in intermediate_messages[index + 1:]]
            final = workflow_final_spec(workflow_result) if workflow_result else None
            if final:
                tail.append(final)
            revision_parts = current_revision.split(":", 2) if current_revision else []
            previous_bot_id = (int(revision_parts[0]) if
                               len(revision_parts) == 3 and revision_parts[1] == "bot"
                               else None)
            delivery = await deliver_workflow_auto_message(
                self.db, active_session, session_id=session_id,
                org_id=org_id, agent_id=session['agent_id'],
                customer_id=customer_id, message=intermediate_message,
                source_message_id=source_message_id,
                generation_revision=current_revision,
                attributes={
                    "workflow_execution": True,
                    "workflow_id": str(active_session.workflow_id),
                    "intermediate_message": True, "message_node": True,
                    "workflow_deferred_tail": tail,
                    "workflow_continuation_from": previous_bot_id,
                })
            if delivery is None or not delivery.ok:
                logger.info("Workflow MESSAGE deferred/denied: %s",
                            delivery.reason if delivery is not None else "missing_authority")
                return current_revision, False
            current_revision = context_revision(self.db, active_session)
        return current_revision, True

    async def _handle_form_display(self, workflow_result, session_id: str, sio, namespace: str):
        """Handle form display for form nodes"""
        
        logger.info(f"Form data detected: {workflow_result.form_data}")
        logger.info("Emitting display_form event")
        
        # Emit form display to client
        await sio.emit('display_form', {
            'form_data': workflow_result.form_data,
            'session_id': session_id
        }, room=session_id, namespace=namespace)
        
        logger.info("Form display event emitted successfully")
    
    async def _handle_workflow_transfer(
        self, 
        workflow_result, 
        session_id: str, 
        org_id: str, 
        session: dict, 
        customer_id: str, 
        response: ChatResponse,
        prepare_only: bool = False,
        control_only: bool = False,
    ) -> ChatResponse:
        """Prepare canonical machine text, or apply post-commit human control."""
        
        logger.info(f"Workflow LLM requested transfer to human for session {session_id}")

        if not workflow_result.transfer_group_id:
            logger.warning(
                f"No transfer_group_id provided for workflow transfer in session {session_id}; "
                "falling back to the agent's default group")

        chat_agent = await ChatAgent.create_async(
            api_key=decrypt_api_key(session['ai_config'].encrypted_api_key),
            model_name=session['ai_config'].model_name,
            model_type=session['ai_config'].model_type,
            base_url=(session['ai_config'].settings or {}).get('base_url'),
            fallback_model_name=(session['ai_config'].settings or {}).get('fallback_model_name'),
            reasoning_strength=(session['ai_config'].settings or {}).get('reasoning_strength'),
            org_id=org_id,
            agent_id=session['agent_id'],
            customer_id=customer_id,
            session_id=session_id
        )

        try:
            # Create ChatResponse object with transfer details from workflow
            llm_response = ChatResponse(
                message=workflow_result.message,
                transfer_to_human=True,
                transfer_reason=TransferReasonType(workflow_result.transfer_reason) if workflow_result.transfer_reason else None,
                transfer_description=workflow_result.transfer_description,
                end_chat=False,
                request_rating=False,
                create_ticket=False
            )

            # A missing group id is passed through rather than short-circuited:
            # the transfer path then falls back to the agent's own default
            # group, as a plain agent transfer does. Setting the status alone
            # left group_id NULL, and an inbox matches on user_id or group_id —
            # so the handover was invisible to every agent it was meant for.
            transfer_response = await chat_agent.handle_workflow_transfer(
                session_id=session_id,
                org_id=org_id,
                agent_id=session['agent_id'],
                customer_id=customer_id,
                transfer_group_id=workflow_result.transfer_group_id,
                db=self.db,
                chat_repo=self.chat_repo,
                llm_response=llm_response,
                persist_response=False,
                defer_control=prepare_only,
                control_only=control_only,
            )

            if control_only:
                logger.info("Workflow transfer control applied after machine ACK: %s", session_id)
            else:
                logger.info("Workflow transfer chat text generated without control: %s", session_id)
            return transfer_response
        except ValueError as e:
            # The agent has no groups at all, so there is nobody to route to.
            # Mark it transferred anyway — an admin can still see and claim it.
            logger.error(
                f"Workflow transfer for session {session_id} could not be routed to a group: {e}")
            if not prepare_only:
                self.session_repo.update_session_status(session_id, "TRANSFERRED")
            return response
        finally:
            await chat_agent.safe_cleanup_mcp_tools()
    
    async def _handle_workflow_end_chat(
        self, 
        response: ChatResponse, 
        session_id: str, 
        org_id: str, 
        session: dict, 
        customer_id: str
    ) -> ChatResponse:
        """Handle end chat requested by workflow"""
        
        logger.info(f"Workflow requested end chat for session {session_id}")
        
        # Create a ChatAgent instance to use the _handle_end_chat method
        chat_agent = await ChatAgent.create_async(
            api_key=decrypt_api_key(session['ai_config'].encrypted_api_key),
            model_name=session['ai_config'].model_name,
            model_type=session['ai_config'].model_type,
            base_url=(session['ai_config'].settings or {}).get('base_url'),
            fallback_model_name=(session['ai_config'].settings or {}).get('fallback_model_name'),
            reasoning_strength=(session['ai_config'].settings or {}).get('reasoning_strength'),
            org_id=org_id,
            agent_id=session['agent_id'],
            customer_id=customer_id,
            session_id=session_id
        )
        
        try:
            # Handle end chat using the agent's method with rating from response
            # The response.request_rating value comes from the workflow execution config
            return await chat_agent._handle_end_chat(response, session_id, self.db, response.request_rating)
        finally:
            await chat_agent.safe_cleanup_mcp_tools()
    
    async def complete_transfer_after_delivery(self, spec, session_id, org_id, session, customer_id):
        """Only issue human transfer CONTROL after the machine text was committed."""
        from types import SimpleNamespace
        transfer = SimpleNamespace(**spec)
        return await self._handle_workflow_transfer(
            transfer, session_id, org_id, session, customer_id,
            ChatResponse(message=transfer.message, transfer_to_human=True,
                         transfer_reason=None, transfer_description=None,
                         end_chat=False, request_rating=False, create_ticket=False),
            control_only=True,
        )

    def _store_workflow_response(
        self, response: ChatResponse, session_id: str, org_id: str,
        session: dict, customer_id: str, active_session, workflow_result,
        source_message_id: int,
        generation_revision: str,
    ):
        """Persist once; widget_chat delivers the exact row with final recheck."""
        stored = self.chat_repo.create_message({
            "message": response.message, "message_type": "bot",
            "session_id": session_id, "organization_id": org_id,
            "agent_id": session['agent_id'], "customer_id": customer_id,
            "attributes": {
                "workflow_execution": True,
                "ai_auto_pending": True,
                "workflow_id": str(active_session.workflow_id),
                "current_node_id": str(workflow_result.next_node_id) if workflow_result.next_node_id else None,
                "transfer_to_human": response.transfer_to_human,
                "end_chat": response.end_chat,
                "request_rating": response.request_rating,
                # Durable on the SAME canonical bot row before any Web ACK.
                # The post-ACK session transition and this marker commit atomically.
                "workflow_terminal_control": workflow_terminal_intent(
                    workflow_result),
                # A normally completed intermediate already owns this
                # successor; reconnect must never recreate the final.
                "workflow_continuation_from": (
                    int(generation_revision.split(":", 2)[0]) if
                    generation_revision and
                    generation_revision.split(":", 2)[1:2] == ["bot"] else None),
            }
        })
        response._stored_message_id = stored.id
        response._workflow_terminal_intent = workflow_terminal_intent(workflow_result)
        if source_message_id:
            response._auto_authority_snapshot = build_auto_send_authority(
                self.db, active_session, organization_id=org_id,
                agent_id=session['agent_id'],
                source_message_id=source_message_id,
                bot_message_id=stored.id,
                context_revision_at_generation=generation_revision)
        return stored

    async def _handle_failed_workflow(
        self, workflow_result, session_id: str, org_id: str,
        session: dict, customer_id: str, active_session, source_message_id: int,
        generation_revision: str,
    ) -> ChatResponse:
        """Failure fallback is still machine-owned and must pass the gate."""
        logger.error(f"Workflow execution failed: {workflow_result.error}")
        response = ChatResponse(
            message=workflow_result.message or "I apologize, but I'm having trouble processing your request right now.",
            transfer_to_human=False, transfer_reason=None,
            transfer_description=None, end_chat=False,
            request_rating=False, create_ticket=False)
        stored = self.chat_repo.create_message({
            "message": response.message, "message_type": "bot",
            "session_id": session_id, "organization_id": org_id,
            "agent_id": session['agent_id'], "customer_id": customer_id,
            "attributes": {
                "workflow_execution": True, "ai_auto_pending": True,
                "workflow_error": workflow_result.error,
                "transfer_to_human": False, "end_chat": False, "request_rating": False,
            }
        })
        response._stored_message_id = stored.id
        if source_message_id:
            response._auto_authority_snapshot = build_auto_send_authority(
                self.db, active_session, organization_id=org_id,
                agent_id=session['agent_id'], source_message_id=source_message_id,
                bot_message_id=stored.id,
                context_revision_at_generation=generation_revision)
        return response


WORKFLOW_RATING_COPY = ("\n\nThank you for chatting with us! Would you please take a moment "
                        "to rate your experience? Your feedback helps us improve our service.")


def workflow_transfer_spec(result):
    return {
        "message": result.message,
        "transfer_reason": getattr(result, "transfer_reason", None),
        "transfer_description": getattr(result, "transfer_description", None),
        "transfer_group_id": (str(result.transfer_group_id)
                              if getattr(result, "transfer_group_id", None) else None),
    }


def workflow_terminal_intent(result):
    """Bounded terminal intent on ChatHistory, never a separate outbox."""
    if getattr(result, "transfer_to_human", False):
        return {"kind": "transfer", "state": "pending",
                "transfer": workflow_transfer_spec(result)}
    if getattr(result, "end_chat", False):
        return {"kind": "end_chat", "state": "pending"}
    return None


async def apply_pending_workflow_terminal_control(db, active_session, message_id):
    """Atomically apply the one terminal control after a canonical Web ACK.

    Use the existing SessionToAgent and ChatHistory owners under the same PG
    row locks as AI_AUTO. On crash before commit nothing changes; on crash
    after commit the applied marker makes recovery a no-op. Never infer an
    ACK from a rendered/history row.
    """
    with SessionLocal() as locked_db:
        bot = (locked_db.query(ChatHistory)
               .filter(ChatHistory.id == message_id,
                       ChatHistory.session_id == active_session.session_id,
                       ChatHistory.message_type == "bot")
               .first())
        if bot is None:
            return False
        attrs = bot.attributes or {}
        control = attrs.get("workflow_terminal_control")
        if not isinstance(control, dict) or control.get("state") != "pending":
            return False
        delivery = attrs.get("provider_delivery") or {}
        authority = attrs.get("ai_auto_authority")
        if (delivery.get("state") != "succeeded"
                or delivery.get("channel") != "web"
                or not isinstance(authority, dict)
                or control.get("kind") not in {"transfer", "end_chat"}):
            return False
        payload = {"message_id": bot.id, "message": bot.message}
        denial = revalidate_auto_send(
            locked_db, authority, payload, terminal_control=True)
        if denial:
            logger.info("Workflow terminal control denied: %s", denial)
            return False
        # revalidate_auto_send holds the canonical session + agent row locks.
        session = locked_db.query(SessionToAgent).filter(
            SessionToAgent.session_id == active_session.session_id).first()
        agent = locked_db.query(Agent).filter(Agent.id == session.agent_id).first()
        kind = control["kind"]
        group_id = None
        if kind == "transfer":
            spec = control.get("transfer") or {}
            requested = spec.get("transfer_group_id")
            if requested is not None:
                try:
                    group_id = UUID(str(requested))
                except (TypeError, ValueError, AttributeError):
                    logger.warning("Workflow transfer group invalid; terminal control denied")
                    return False
            else:
                # Preserve the existing first-agent-group fallback, but do
                # not silently try a different group after scope rejection.
                groups = getattr(agent, "groups", None) or []
                group_id = groups[0].id if groups else None
            if group_id is None:
                logger.warning("Workflow transfer has no qualified target group")
                return False
            # UUID/FK existence alone cannot establish tenant authorization.
            # Lock the existing UserGroup owner IN this canonical control
            # transaction and qualify against the freshly locked session org.
            group = (locked_db.query(UserGroup)
                     .filter(UserGroup.id == group_id,
                             UserGroup.organization_id == session.organization_id)
                     .with_for_update().first())
            if group is None:
                logger.warning("Workflow transfer group missing or foreign; denied")
                return False
            group_id = group.id
            session.status = SessionStatus.TRANSFERRED
            session.group_id = group_id
            session.transfer_reason = spec.get("transfer_reason") or "KNOWLEDGE_GAP"
            session.transfer_description = (
                spec.get("transfer_description") or "Transfer requested by workflow")
        else:
            session.status = SessionStatus.CLOSED
            session.closed_at = datetime.now(timezone.utc)
        # This marker is committed with the SAME transaction as the status,
        # including group/reason for a human handoff.
        bot.attributes = {**attrs, "workflow_terminal_control": {
            **control, "state": "applied",
            "applied_at": datetime.now(timezone.utc).isoformat()}}
        locked_db.commit()
        # Existing ChatterMate human-routing notification is best-effort;
        # canonical handoff/group membership already committed atomically.
        # Replays cannot send it twice because the control marker is applied.
        if kind == "transfer" and group_id is not None:
            try:
                from app.models.user import User, user_groups
                from app.services.notifications import (
                    notify_chat_event, ChatNotificationEvent)
                with SessionLocal() as notice_db:
                    # Re-qualify both group and recipient tenant after commit.
                    # Never disclose session metadata to a foreign group/member.
                    users = (notice_db.query(User)
                             .join(user_groups, user_groups.c.user_id == User.id)
                             .join(UserGroup, UserGroup.id == user_groups.c.group_id)
                             .filter(UserGroup.id == group_id,
                                     UserGroup.organization_id == session.organization_id,
                                     User.organization_id == session.organization_id,
                                     User.is_active.is_(True)).all())
                    if not users:
                        return True
                    await notify_chat_event(
                        db=notice_db,
                        user_ids=[u.id for u in users],
                        event=ChatNotificationEvent.CHAT_TRANSFER,
                        title="New Chat Transfer",
                        message="A chat has been transferred to your group via workflow.",
                        metadata={"session_id": str(active_session.session_id),
                                  "transfer_reason": session.transfer_reason,
                                  "transfer_description": session.transfer_description})
            except Exception:
                logger.exception("Workflow handoff notification failed after durable control")
        return True


async def resume_pending_workflow_terminal_controls(db, active_session):
    """Recover ACK-success/post-ACK-crash terminal controls without resending."""
    rows = (db.query(ChatHistory)
            .filter(ChatHistory.session_id == active_session.session_id,
                    ChatHistory.message_type == "bot")
            .order_by(ChatHistory.id.desc()).limit(100).all())
    applied = 0
    for bot in reversed(rows):
        attrs = bot.attributes or {}
        control = attrs.get("workflow_terminal_control") or {}
        if (control.get("state") == "pending"
                and (attrs.get("provider_delivery") or {}).get("state") == "succeeded"):
            if await apply_pending_workflow_terminal_control(
                    db, active_session, bot.id):
                applied += 1
                db.expire_all()
    return applied


def workflow_final_spec(result):
    if not result.message:
        return None
    return {
        "kind": "final",
        "message": (result.message + (WORKFLOW_RATING_COPY if
                   result.end_chat and result.request_rating else "")),
        "end_chat": bool(result.end_chat),
        "request_rating": bool(result.request_rating),
        "transfer_to_human": bool(result.transfer_to_human),
        "transfer": (workflow_transfer_spec(result)
                     if result.transfer_to_human else None),
    }


async def resume_deferred_workflow_messages(db, active_session):
    """Continue after a Web sending ACK recovery, never before it.

    The preceding canonical intermediate row stores the bounded continuation.
    Each successor row records its parent ID, avoiding a second queue/outbox.
    A newer inbound, human takeover, permission change or closed session
    blocks the continuation; individual sends still use final revalidation.
    """
    if active_session.status != SessionStatus.OPEN or active_session.user_id is not None:
        return 0
    from app.models.agent import Agent
    agent = db.query(Agent).filter(Agent.id == active_session.agent_id).first()
    if agent is None or not agent.ai_replies_enabled:
        return 0
    service = WorkflowChatService(db)
    completed = 0
    rows = (db.query(ChatHistory)
            .filter(ChatHistory.session_id == active_session.session_id,
                    ChatHistory.message_type == "bot")
            .order_by(ChatHistory.id.desc()).limit(100).all())
    for parent in reversed(rows):
        data = parent.attributes or {}
        tail = data.get("workflow_deferred_tail") or []
        if not tail or (data.get("provider_delivery") or {}).get("state") != "succeeded":
            continue
        authority = data.get("ai_auto_authority") or {}
        source_id = authority.get("source_message_id")
        if not source_id:
            continue
        latest_inbound = (db.query(ChatHistory.id)
                          .filter(ChatHistory.session_id == active_session.session_id,
                                  ChatHistory.message_type == "user")
                          .order_by(ChatHistory.id.desc()).limit(1).scalar())
        if latest_inbound != source_id:
            continue  # Old generation may never restart after new inbound.
        followups = (db.query(ChatHistory)
                     .filter(ChatHistory.session_id == active_session.session_id,
                             ChatHistory.message_type == "bot")
                     .order_by(ChatHistory.id.desc()).limit(100).all())
        existing = next((bot for bot in followups
                         if (bot.attributes or {}).get("workflow_continuation_from") == parent.id),
                        None)
        item = tail[0]
        if existing is not None:
            # Already committed or precommitted children are never recreated.
            # A bot intent persisted just BEFORE Web precommit can still be
            # resumed on the SAME canonical row without a second message.
            old_state = ((existing.attributes or {}).get("provider_delivery") or {}).get("state")
            if old_state is not None:
                continue
        remaining = tail[1:]
        attrs = {"workflow_execution": True,
                 "workflow_continuation_from": parent.id,
                 "workflow_deferred_tail": remaining,
                 "intermediate_message": item["kind"] == "intermediate",
                 "message_node": item["kind"] == "intermediate",
                 "end_chat": item.get("end_chat", False),
                 "transfer_to_human": item.get("transfer_to_human", False),
                 "workflow_terminal_control": (
                     {"kind": "transfer", "state": "pending",
                      "transfer": item.get("transfer")}
                     if item.get("transfer_to_human") else
                     {"kind": "end_chat", "state": "pending"}
                     if item.get("end_chat") else None)}
        revision = context_revision(
            db, active_session,
            ignore_bot_message_id=existing.id if existing is not None else None)
        result = await deliver_workflow_auto_message(
            db, active_session, session_id=str(active_session.session_id),
            org_id=active_session.organization_id, agent_id=active_session.agent_id,
            customer_id=getattr(parent, "customer_id", None), message=item["message"],
            source_message_id=source_id, generation_revision=revision,
            attributes=attrs, existing_message=existing,
            end_chat=item.get("end_chat", False),
            request_rating=item.get("request_rating", False),
            transfer_to_human=item.get("transfer_to_human", False))
        if result is None or not result.ok:
            break  # Child 'sending' carries its own tail for next reconnect.
        completed += 1
        # The newly persisted canonical child owns its post-ACK terminal
        # control, including recovery if ACK succeeded just before a crash.
        db.expire_all()
        terminal_child = (db.query(ChatHistory)
            .filter(ChatHistory.session_id == active_session.session_id,
                    ChatHistory.message_type == "bot")
            .order_by(ChatHistory.id.desc()).limit(100).all())
        committed_child = next((row for row in terminal_child if
            (row.attributes or {}).get("workflow_continuation_from") == parent.id), None)
        if committed_child is not None:
            await apply_pending_workflow_terminal_control(
                db, active_session, committed_child.id)
            # The control committed in a separate canonical transaction.
            db.expire_all()
        # A newly completed intermediate may itself have a next tail. The
        # next reconnect/history request can advance it without new owners.
    return completed


def _workflow_session_for_transfer(db, active_session):
    """Resolve existing agent/AI configuration only for deferred handoff."""
    from app.repositories.agent import AgentRepository
    from app.repositories.ai_config import AIConfigRepository
    agent = AgentRepository(db).get_agent(active_session.agent_id)
    config = AIConfigRepository(db).get_active_config(active_session.organization_id)
    return {"agent_id": active_session.agent_id, "ai_config": config}
