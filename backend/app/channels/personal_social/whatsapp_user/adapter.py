"""Baileys pipe transport, without independent CRM, database, or message engine."""
from __future__ import annotations
import asyncio
import base64
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, AsyncIterator, Mapping
from ..base import (PersonalSocialTransportAdapter, AccountIdentity, TransportHealth,
                    TransportReceipt, TransportSessionStatus)

HERE = Path(__file__).resolve().parent
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
JID_RE = re.compile(r"^(?:[0-9]{6,20}@(s\.whatsapp\.net|lid)|[0-9]{5,20}(?:-[0-9]{5,20})?@g\.us)$")
CHANNEL = "whatsapp-personal"

class WhatsAppUserTransport(PersonalSocialTransportAdapter):
    """Caller must bridge emitted events into ChatterMate canonical persistence."""
    def __init__(self, account_id: str, *, private_root: str | Path | None = None,
                 node_executable: str | Path | None = None, command_timeout: float = 30.0):
        if not ACCOUNT_RE.fullmatch(account_id):
            raise ValueError("INVALID_ACCOUNT_ID")
        self.account_id = account_id
        local = os.environ.get("LOCALAPPDATA")
        if private_root is None and not local:
            raise ValueError("LOCALAPPDATA_REQUIRED")
        root = Path(private_root or (Path(local) / "Yance" / "personal-whatsapp-auth"))
        if not root.is_absolute():
            raise ValueError("ABSOLUTE_PRIVATE_ROOT_REQUIRED")
        self.private_root = root.resolve()
        self.node = str(node_executable or shutil.which("node") or "")
        if not self.node:
            raise RuntimeError("PRIVATE_NODE_RUNTIME_UNAVAILABLE")
        self.command_timeout = command_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._sequence = 0
        self._writer_lock = asyncio.Lock()
        self._started_lock = asyncio.Lock()
        self._inbound: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._events: asyncio.Queue = asyncio.Queue(maxsize=128)
        self._state = TransportSessionStatus.DISCONNECTED
        self._reason: str | None = None
        self._user: Mapping[str, Any] | None = None
        self._booted = asyncio.Event()

    async def _start(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WINDOWS_DPAPI_RUNTIME_REQUIRED")
        async with self._started_lock:
            if self._proc and self._proc.returncode is None:
                return
            self._booted.clear()
            self._proc = await asyncio.create_subprocess_exec(
                self.node, str(HERE / "runner.mjs"), self.account_id, str(self.private_root),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, cwd=str(HERE),
                limit=24 * 1024 * 1024)
            self._reader_task = asyncio.create_task(self._pump(), name=f"wa-personal:{self.account_id}")
            try:
                await asyncio.wait_for(self._booted.wait(), 15)
            except Exception:
                await self.close()
                raise
            if self._proc.returncode is not None or self._state is TransportSessionStatus.ERROR:
                await self.close()
                raise RuntimeError(self._reason or "BAILEYS_BOOT_FAILED")

    async def _pump(self) -> None:
        try:
            while self._proc and self._proc.stdout:
                data = await self._proc.stdout.readline()
                if not data:
                    break
                if len(data) > 24 * 1024 * 1024:
                    self._state = TransportSessionStatus.ERROR
                    self._reason = "BRIDGE_FRAME_TOO_LARGE"
                    break
                try:
                    row = json.loads(data)
                except (ValueError, UnicodeError):
                    self._state = TransportSessionStatus.ERROR
                    self._reason = "BRIDGE_FRAME_INVALID"
                    break
                if row.get("replyTo") is not None:
                    future = self._pending.pop(row["replyTo"], None)
                    if future and not future.done():
                        if row.get("ok"):
                            future.set_result(row.get("result"))
                        else:
                            future.set_exception(RuntimeError(row.get("error", {}).get("code", "TRANSPORT_ERROR")))
                    continue
                event = row.get("event")
                if event == "boot":
                    self._booted.set()
                elif event == "fatal":
                    self._state = TransportSessionStatus.ERROR
                    self._reason = str(row.get("reasonCode") or "BAILEYS_FATAL")
                    self._booted.set()
                elif event == "health":
                    try:
                        self._state = TransportSessionStatus(row["status"])
                    except (KeyError, ValueError):
                        self._state = TransportSessionStatus.ERROR
                    self._reason = row.get("reasonCode")
                    if self._state is not TransportSessionStatus.CONNECTED:
                        self._user = None
                elif event == "identity":
                    self._user = row.get("user")
                if event == "inbound":
                    if self._inbound.full():
                        self._state = TransportSessionStatus.ERROR
                        self._reason = "CANONICAL_INBOUND_CONSUMER_BACKPRESSURE"
                        break
                    self._inbound.put_nowait(row)
                else:
                    if self._events.full():
                        self._state = TransportSessionStatus.ERROR
                        self._reason = "AUTH_EVENT_CONSUMER_BACKPRESSURE"
                        break
                    self._events.put_nowait(row)
        finally:
            self._booted.set()
            if self._state is not TransportSessionStatus.ERROR:
                self._state = TransportSessionStatus.DEGRADED
                self._reason = "BRIDGE_PROCESS_EXITED"
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError(self._reason))
            self._pending.clear()
            if self._proc and self._proc.returncode is None:
                self._proc.kill()

    async def _call(self, op: str, payload: Any = None) -> Any:
        await self._start()
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("BAILEYS_BRIDGE_NOT_STARTED")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        async with self._writer_lock:
            self._sequence += 1
            key = self._sequence
            self._pending[key] = future
            frame = {"id": key, "op": op}
            if payload is not None:
                frame["payload"] = payload
            encoded = (json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            if len(encoded) > 24 * 1024 * 1024:
                self._pending.pop(key, None)
                raise ValueError("BRIDGE_COMMAND_TOO_LARGE")
            self._proc.stdin.write(encoded)
            await self._proc.stdin.drain()
        try:
            return await asyncio.wait_for(future, self.command_timeout)
        finally:
            self._pending.pop(key, None)

    async def connect(self) -> None:
        # No auto login; caller controls live user QR flow.
        await self._call("connect")
    async def disconnect(self) -> None:
        if self._proc and self._proc.returncode is None:
            await self._call("disconnect")
        self._state = TransportSessionStatus.DISCONNECTED
        self._user = None
    async def reconnect(self) -> None:
        await self._call("reconnect")
    async def cancel_login(self) -> None:
        await self._call("cancel")
    async def logout(self) -> None:
        """Explicit logout; a transient disconnect retains encrypted Signal keys."""
        await self._call("logout")
    async def rotate_auth_key(self) -> None:
        await self._call("rotateKey")
    async def close(self) -> None:
        proc = self._proc
        if not proc:
            return
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        if self._reader_task and self._reader_task is not asyncio.current_task():
            await asyncio.gather(self._reader_task, return_exceptions=True)
        self._proc = None
        self._state = TransportSessionStatus.DISCONNECTED
        self._user = None
    async def session_status(self) -> TransportSessionStatus:
        if not self._proc or self._proc.returncode is not None:
            return TransportSessionStatus.DISCONNECTED
        return self._state
    async def receive_inbound(self) -> AsyncIterator[Mapping[str, Any]]:
        while True:
            item = await self._inbound.get()
            if self._state is TransportSessionStatus.ERROR:
                raise RuntimeError(self._reason or "WHATSAPP_INBOUND_UNAVAILABLE")
            yield item
    async def auth_events(self) -> AsyncIterator[Mapping[str, Any]]:
        """QR only from actual library event, with expiry/cancel semantics."""
        while True:
            yield await self._events.get()
    async def send_outbound(self, payload: Mapping[str, Any]) -> TransportReceipt:
        data = dict(payload)
        if isinstance(data.get("data"), bytes):
            data["data"] = base64.b64encode(data["data"]).decode("ascii")
        row = await self._call("send", data)
        return TransportReceipt(message_id=row["messageId"], status=row["status"],
                                provider_message_id=row["providerMessageId"],
                                metadata={"provider":CHANNEL})
    async def receipt(self, provider_message_id: str) -> TransportReceipt:
        row = await self._call("receipt", provider_message_id)
        return TransportReceipt(message_id=row["messageId"],status=row["status"],
                                provider_message_id=row["providerMessageId"])
    async def media(self, media_ref: str) -> bytes:
        row = await self._call("media", media_ref)
        return base64.b64decode(row["data"], validate=True)
    async def backfill(self, cursor: str | None = None) -> AsyncIterator[Mapping[str, Any]]:
        raise NotImplementedError("CANONICAL_BACKFILL_BRIDGE_NOT_AUTHORIZED")
        yield {}  # pragma: no cover
    async def account_identity(self) -> AccountIdentity:
        if self._state is not TransportSessionStatus.CONNECTED or not self._user:
            raise RuntimeError("PERSONAL_ACCOUNT_NOT_VERIFIED")
        return AccountIdentity(provider=CHANNEL,account_id=self.account_id,
                               display_name=str(self._user.get("name") or ""),
                               metadata={"jid":self._user["jid"]})
    async def route(self, target: Mapping[str, Any]) -> Mapping[str, Any]:
        jid = target.get("external_conversation_id", "")
        if not isinstance(jid, str) or not JID_RE.fullmatch(jid):
            raise ValueError("INVALID_CANONICAL_JID")
        return {"provider_channel":CHANNEL, "external_account_id":self.account_id,
                "external_conversation_id":jid}
    async def error(self) -> Mapping[str, Any] | None:
        return {"reasonCode":self._reason} if self._reason else None
    async def health(self) -> TransportHealth:
        status = await self.session_status()
        return TransportHealth(status=status, detail=self._reason,
                               metadata={"provider":CHANNEL,"verified":status is TransportSessionStatus.CONNECTED})
