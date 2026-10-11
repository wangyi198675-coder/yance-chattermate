"""W397 personal Telegram MTProto transport. No native CRM, credential or delivery authority.

Reuses the V21 GramJS client mechanics (legacy main 5c31f8b, telegramAdapter.js)
through an isolated JSON-lines worker. Session custody is injected from the
*existing* canonical encrypted credential owner; there is no disk session file.
Not wired into native ChannelAccount routes until W362 grants route write access.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from typing import Any, AsyncIterator, Mapping, Protocol

from ..base import (
    AccountIdentity, PersonalSocialTransportAdapter,
    TransportHealth, TransportReceipt, TransportSessionStatus,
)

_STOP = object()
_MAX_MEDIA = 16 * 1024 * 1024
_MAX_LINE = 24 * 1024 * 1024


class TelegramPersonalError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SessionCustody(Protocol):
    """Implemented by native encrypted ChannelAccount credentials, not by W397."""
    async def load_session(self, organization_id: str, account_id: str) -> str: ...
    async def save_session(self, organization_id: str, account_id: str, session: str) -> None: ...
    async def clear_session(self, organization_id: str, account_id: str) -> None: ...


class Worker(Protocol):
    async def start(self) -> None: ...
    async def call(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def events(self) -> AsyncIterator[Mapping[str, Any]]: ...
    async def close(self) -> None: ...


class GramJSWorker:
    """One OS process per account. Stdout is protocol-only; stderr is suppressed.

    The executable must be supplied by the audited private Windows runtime.
    Never fall back silently to an unapproved global Node executable.
    """
    def __init__(self, node_executable: str, *, script: Path | None = None):
        self.node_executable = node_executable
        self.script = script or Path(__file__).with_name("worker.cjs")
        self.proc: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._events: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._sequence = 0
        self._read_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.proc is not None:
            raise TelegramPersonalError("WORKER_ALREADY_STARTED")
        executable = Path(self.node_executable)
        if not executable.is_file() or not self.script.is_file():
            raise TelegramPersonalError("PRIVATE_NODE_RUNTIME_MISSING")
        self.proc = await asyncio.create_subprocess_exec(
            str(executable), str(self.script),
            cwd=str(self.script.parent),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=_MAX_LINE,
        )
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            assert self.proc is not None and self.proc.stdout is not None
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                if len(line) > _MAX_LINE:
                    raise TelegramPersonalError("WORKER_FRAME_TOO_LARGE")
                frame = json.loads(line)
                if not isinstance(frame, dict):
                    raise TelegramPersonalError("WORKER_FRAME_INVALID")
                if "id" in frame:
                    future = self._pending.pop(frame["id"], None)
                    if future and not future.done():
                        if frame.get("ok") is True:
                            future.set_result(frame.get("result") or {})
                        else:
                            # Worker intentionally sends error *codes*, not OTPs, phone, or session.
                            future.set_exception(TelegramPersonalError(
                                str(frame.get("error_code") or "WORKER_OPERATION_FAILED")))
                elif "event" in frame:
                    self._events.put_nowait(frame)
        except (ValueError, asyncio.QueueFull, json.JSONDecodeError, TelegramPersonalError):
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(TelegramPersonalError("WORKER_TERMINATED_UNCERTAIN"))
            self._pending.clear()
            try:
                self._events.put_nowait({"event": "disconnected"})
            except asyncio.QueueFull:
                pass

    async def call(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.proc or self.proc.returncode is not None or not self.proc.stdin:
            raise TelegramPersonalError("WORKER_NOT_RUNNING")
        self._sequence += 1
        sequence = self._sequence
        future = asyncio.get_running_loop().create_future()
        self._pending[sequence] = future
        try:
            encoded = (json.dumps({"id": sequence, "method": method, "params": dict(params)},
                                  separators=(",", ":")) + "\n").encode("utf-8")
            if len(encoded) > _MAX_LINE:
                raise TelegramPersonalError("WORKER_FRAME_TOO_LARGE")
            self.proc.stdin.write(encoded)
            await self.proc.stdin.drain()
            # Timeout is fail-closed for ambiguous sends; never auto-retry.
            return await asyncio.wait_for(future, timeout=5 if method == "status" else 45)
        finally:
            self._pending.pop(sequence, None)

    async def events(self) -> AsyncIterator[Mapping[str, Any]]:
        while True:
            value = await self._events.get()
            yield value
            if value.get("event") == "disconnected":
                return

    async def close(self) -> None:
        proc = self.proc
        if not proc:
            return
        try:
            await asyncio.wait_for(self.call("disconnect", {}), timeout=5)
        except (TelegramPersonalError, asyncio.TimeoutError):
            pass
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        if self._read_task:
            await asyncio.gather(self._read_task, return_exceptions=True)
        self.proc = None


class TelegramUserAdapter(PersonalSocialTransportAdapter):
    """Transport-only. Caller maps events to native account/conversation/history/file."""
    def __init__(self, *, organization_id: str, channel_account_id: str,
                 api_id: int, api_hash: str, custody: SessionCustody,
                 node_executable: str | None = None, worker_factory=None,
                 expected_user_id: str | None = None):
        if not organization_id or not channel_account_id:
            raise TelegramPersonalError("ACCOUNT_SCOPE_REQUIRED")
        if type(api_id) is not int or api_id <= 0 or not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash or ""):
            raise TelegramPersonalError("TELEGRAM_APP_CREDENTIALS_REQUIRED")
        if custody is None:
            raise TelegramPersonalError("ENCRYPTED_CUSTODY_REQUIRED")
        self.organization_id = str(organization_id)
        self.channel_account_id = str(channel_account_id)
        self._expected_user_id = str(expected_user_id) if expected_user_id else None
        self._api_id = api_id
        self._api_hash = api_hash
        self._custody = custody
        if worker_factory is None and not node_executable:
            raise TelegramPersonalError("PRIVATE_NODE_RUNTIME_MISSING")
        self._worker_factory = worker_factory or (lambda: GramJSWorker(node_executable))
        self._worker: Worker | None = None
        self._events_task: asyncio.Task | None = None
        self._inbound: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._login: asyncio.Queue = asyncio.Queue(maxsize=16)
        self._status = TransportSessionStatus.DISCONNECTED
        self._identity: AccountIdentity | None = None
        self._last_error: str | None = None
        self._generation = 0

    def _scope(self, payload: Mapping[str, Any]) -> None:
        if (str(payload.get("organization_id")) != self.organization_id
                or str(payload.get("channel_account_id")) != self.channel_account_id):
            raise TelegramPersonalError("ACCOUNT_SCOPE_MISMATCH")

    async def connect(self) -> None:
        if self._worker is not None:
            raise TelegramPersonalError("ALREADY_ACTIVE")
        session = await self._custody.load_session(self.organization_id, self.channel_account_id)
        self._status = TransportSessionStatus.CONNECTING
        self._generation += 1
        generation = self._generation
        worker = self._worker_factory()
        self._worker = worker
        try:
            await worker.start()
            self._events_task = asyncio.create_task(self._consume(worker, generation))
            result = await worker.call("connect", {
                "api_id": self._api_id, "api_hash": self._api_hash,
                "session": session or "",
            })
            if result.get("authorized") is False:
                # MTProto socket can be open while user authorization is absent.
                # Never represent this as a Connected ChannelAccount.
                self._status = TransportSessionStatus.CONNECTING
        except Exception:
            self._status = TransportSessionStatus.ERROR
            self._last_error = "TELEGRAM_CONNECT_FAILED"
            await self.disconnect()
            raise

    async def _consume(self, worker: Worker, generation: int) -> None:
        try:
            async for event in worker.events():
                if generation != self._generation:
                    return
                kind = event.get("event")
                if kind == "authenticated":
                    secret = event.get("session")
                    if not isinstance(secret, str) or not secret:
                        raise TelegramPersonalError("SESSION_EXPORT_MISSING")
                    user = event.get("user") or {}
                    if not user.get("id"):
                        raise TelegramPersonalError("ACCOUNT_IDENTITY_MISSING")
                    if self._expected_user_id and str(user["id"]) != self._expected_user_id:
                        raise TelegramPersonalError("ACCOUNT_IDENTITY_MISMATCH")
                    await self._custody.save_session(self.organization_id, self.channel_account_id, secret)
                    self._identity = AccountIdentity("telegram", str(user["id"]),
                                                     user.get("name"), {"kind": "personal-mtproto"})
                    self._last_error = None
                    self._status = TransportSessionStatus.CONNECTED
                    self._login.put_nowait({"step": "connected"})
                elif kind == "challenge":
                    # The URI is a genuine GramJS callback, never a synthetic QR.
                    self._login.put_nowait({"step": event.get("step"), "qr_uri": event.get("qr_uri"),
                                            "hint": event.get("hint")})
                elif kind == "message":
                    value = event.get("message") or {}
                    if not isinstance(value, dict):
                        continue
                    # Canonical persistence belongs to ChannelConversation/ChatHistory.
                    self._inbound.put_nowait({
                        **value,
                        "organization_id": self.organization_id,
                        "channel_account_id": self.channel_account_id,
                        "provider": "telegram", "account_kind": "personal",
                        "is_customer_turn": value.get("from_me") is not True,
                    })
                elif kind == "error":
                    self._last_error = str(event.get("code") or "TELEGRAM_PROVIDER_ERROR")
                    self._status = TransportSessionStatus.DEGRADED
                elif kind == "disconnected":
                    self._status = TransportSessionStatus.DISCONNECTED
                    break
        except Exception as exc:
            self._last_error = getattr(exc, "code", "INBOUND_OR_CUSTODY_FAILURE")
            self._status = TransportSessionStatus.ERROR
            # Unpersisted inbound is NEVER reported as a canonical committed message.
            await worker.close()
        finally:
            try:
                self._inbound.put_nowait(_STOP)
            except asyncio.QueueFull:
                pass

    async def begin_qr_login(self, *, interactive_authorized: bool = False) -> None:
        if not interactive_authorized:
            raise TelegramPersonalError("INTERACTIVE_AUTHORIZATION_REQUIRED")
        if not self._worker:
            await self.connect()
        assert self._worker is not None
        await self._worker.call("start_qr", {})

    async def begin_phone_login(self, phone: str, *, interactive_authorized: bool = False) -> None:
        if not interactive_authorized:
            raise TelegramPersonalError("INTERACTIVE_AUTHORIZATION_REQUIRED")
        if not re.fullmatch(r"^\+[1-9][0-9]{6,14}$", phone):
            raise TelegramPersonalError("PHONE_FORMAT_INVALID")
        if not self._worker:
            await self.connect()
        assert self._worker is not None
        await self._worker.call("start_phone", {"phone": phone})

    async def submit_code(self, code: str, *, interactive_authorized: bool = False) -> None:
        if not interactive_authorized or not re.fullmatch(r"[0-9]{4,8}", code):
            raise TelegramPersonalError("INTERACTIVE_CODE_REQUIRED")
        await self._required().call("submit_code", {"code": code})

    async def submit_password(self, password: str, *, interactive_authorized: bool = False) -> None:
        if not interactive_authorized or not password:
            raise TelegramPersonalError("INTERACTIVE_PASSWORD_REQUIRED")
        await self._required().call("submit_password", {"password": password})

    async def next_login_challenge(self) -> Mapping[str, Any]:
        return await self._login.get()

    def _required(self) -> Worker:
        if not self._worker:
            raise TelegramPersonalError("TELEGRAM_NOT_CONNECTED")
        return self._worker

    async def disconnect(self) -> None:
        self._generation += 1
        worker, task = self._worker, self._events_task
        self._worker = None
        self._events_task = None
        self._status = TransportSessionStatus.DISCONNECTED
        self._identity = None
        if worker:
            await worker.close()
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            self._inbound.put_nowait(_STOP)
        except asyncio.QueueFull:
            pass

    async def logout(self, *, interactive_authorized: bool = False) -> None:
        if not interactive_authorized:
            raise TelegramPersonalError("INTERACTIVE_AUTHORIZATION_REQUIRED")
        await self._required().call("logout", {})
        await self._custody.clear_session(self.organization_id, self.channel_account_id)
        await self.disconnect()

    async def reconnect(self) -> None:
        await self.disconnect()
        self._inbound = asyncio.Queue(maxsize=512)
        await self.connect()

    async def session_status(self) -> TransportSessionStatus:
        return (await self.health()).status

    async def receive_inbound(self) -> AsyncIterator[Mapping[str, Any]]:
        while True:
            value = await self._inbound.get()
            if value is _STOP:
                return
            yield value

    async def send_outbound(self, payload: Mapping[str, Any]) -> TransportReceipt:
        self._scope(payload)
        if self._status != TransportSessionStatus.CONNECTED:
            raise TelegramPersonalError("TELEGRAM_NOT_AUTHORIZED")
        target = str(payload.get("external_conversation_id") or "")
        if not target or target.startswith("bot:"):
            raise TelegramPersonalError("PERSONAL_TARGET_REQUIRED")
        text = payload.get("text")
        media = payload.get("media_bytes")
        if media is None and (not isinstance(text, str) or not text):
            raise TelegramPersonalError("EMPTY_OUTBOUND")
        params: dict[str, Any] = {"peer": target}
        if media is not None:
            if not isinstance(media, bytes) or not 0 < len(media) <= _MAX_MEDIA:
                raise TelegramPersonalError("MEDIA_SIZE_INVALID")
            params.update(media_base64=base64.b64encode(media).decode("ascii"),
                          filename=str(payload.get("filename") or "attachment"),
                          caption=str(text or ""))
            method = "send_media"
        else:
            params["text"] = text
            method = "send_text"
        # An uncertain provider outcome MUST be reconciled by native message_delivery.
        try:
            result = await self._required().call(method, params)
        except (Exception, asyncio.CancelledError):
            self._status = TransportSessionStatus.DEGRADED
            self._last_error = "PROVIDER_SEND_OUTCOME_UNCERTAIN"
            raise
        mid = str(result.get("id") or "")
        if not mid:
            raise TelegramPersonalError("SEND_ACK_MISSING")
        # Telegram ids are per chat; native provider identity is account+peer+id.
        provider_id = f"{target}:{mid}"
        return TransportReceipt(
            message_id=str(payload.get("client_send_intent_id") or provider_id),
            status="accepted", provider_message_id=provider_id,
            metadata={"provider": "telegram", "account_kind": "personal",
                      "external_conversation_id": target,
                      "channel_account_id": self.channel_account_id},
        )

    async def receipt(self, provider_message_id: str) -> TransportReceipt:
        # MTProto send ACK != receiver delivery/read; no invented confirmation.
        return TransportReceipt(message_id=provider_message_id, status="unknown",
                                provider_message_id=provider_message_id)

    async def media(self, media_ref: str) -> bytes:
        peer, sep, message_id = media_ref.partition(":")
        if not sep or not peer or not message_id:
            raise TelegramPersonalError("MEDIA_REFERENCE_INVALID")
        response = await self._required().call("download_media", {"peer": peer, "message_id": message_id})
        data = base64.b64decode(str(response.get("base64") or ""), validate=True)
        if not 0 < len(data) <= _MAX_MEDIA:
            raise TelegramPersonalError("MEDIA_SIZE_INVALID")
        return data

    async def discover_dialogs(self, *, limit: int = 100) -> list[Mapping[str, Any]]:
        if not isinstance(limit, int) or not 1 <= limit <= 2000:
            raise TelegramPersonalError("DIALOG_LIMIT_INVALID")
        result = await self._required().call("dialogs", {"limit": limit})
        return [{**row, "organization_id": self.organization_id,
                 "channel_account_id": self.channel_account_id,
                 "provider": "telegram", "account_kind": "personal"}
                for row in result.get("dialogs", [])]

    async def backfill(self, cursor: str | None = None) -> AsyncIterator[Mapping[str, Any]]:
        if not cursor:
            raise TelegramPersonalError("BACKFILL_CURSOR_REQUIRED")
        try:
            scope = json.loads(cursor)
        except (TypeError, ValueError) as exc:
            raise TelegramPersonalError("BACKFILL_CURSOR_INVALID") from exc
        self._scope(scope)
        peer = str(scope.get("external_conversation_id") or "")
        if not peer:
            raise TelegramPersonalError("BACKFILL_TARGET_REQUIRED")
        offset = int(scope.get("offset_id") or 0)
        result = await self._required().call("backfill", {"peer": peer, "offset_id": offset, "limit": 100})
        for message in result.get("messages", []):
            remote_id = str(message.get("remote_message_id") or "")
            # Caller commits this cursor only AFTER canonical ChatHistory write.
            next_cursor = json.dumps({"organization_id": self.organization_id,
                "channel_account_id": self.channel_account_id,
                "external_conversation_id": peer, "offset_id": int(remote_id)},
                separators=(",", ":")) if remote_id.isdecimal() else None
            yield {**message, "organization_id": self.organization_id,
                   "channel_account_id": self.channel_account_id,
                   "provider": "telegram", "account_kind": "personal",
                   "next_cursor": next_cursor}

    async def account_identity(self) -> AccountIdentity:
        if not self._identity:
            raise TelegramPersonalError("IDENTITY_NOT_VERIFIED")
        return self._identity

    async def route(self, target: Mapping[str, Any]) -> Mapping[str, Any]:
        self._scope(target)
        peer = str(target.get("external_conversation_id") or "").strip()
        if not peer or peer.startswith("bot:"):
            raise TelegramPersonalError("PERSONAL_TARGET_REQUIRED")
        return {"organization_id": self.organization_id,
                "channel_account_id": self.channel_account_id,
                "provider": "telegram", "account_kind": "personal",
                "external_conversation_id": peer}

    async def error(self) -> Mapping[str, Any] | None:
        return {"code": self._last_error} if self._last_error else None

    async def health(self) -> TransportHealth:
        if self._status == TransportSessionStatus.CONNECTED:
            try:
                result = await self._required().call("status", {})
                if result.get("connected") is not True or result.get("authorized") is not True:
                    self._status = TransportSessionStatus.DEGRADED
                    self._last_error = "PROVIDER_AUTHORIZATION_LOST"
            except Exception:
                self._status = TransportSessionStatus.DEGRADED
                self._last_error = "PROVIDER_HEALTH_UNVERIFIED"
        return TransportHealth(self._status, self._last_error, {"account_kind": "personal"})
