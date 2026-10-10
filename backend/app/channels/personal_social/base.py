"""Transport-only interface for personal social account adapters."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Mapping

class TransportSessionStatus(str, Enum):
    DISCONNECTED="disconnected"; CONNECTING="connecting"; CONNECTED="connected"; DEGRADED="degraded"; ERROR="error"

@dataclass(frozen=True)
class AccountIdentity:
    provider: str
    account_id: str
    display_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class TransportReceipt:
    message_id: str
    status: str
    provider_message_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class TransportHealth:
    status: TransportSessionStatus
    detail: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

class PersonalSocialTransportAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None: ...
    @abstractmethod
    async def disconnect(self) -> None: ...
    @abstractmethod
    async def reconnect(self) -> None: ...
    @abstractmethod
    async def session_status(self) -> TransportSessionStatus: ...
    @abstractmethod
    async def receive_inbound(self) -> AsyncIterator[Mapping[str, Any]]: ...
    @abstractmethod
    async def send_outbound(self, payload: Mapping[str, Any]) -> TransportReceipt: ...
    @abstractmethod
    async def receipt(self, provider_message_id: str) -> TransportReceipt: ...
    @abstractmethod
    async def media(self, media_ref: str) -> bytes: ...
    @abstractmethod
    async def backfill(self, cursor: str | None = None) -> AsyncIterator[Mapping[str, Any]]: ...
    @abstractmethod
    async def account_identity(self) -> AccountIdentity: ...
    @abstractmethod
    async def route(self, target: Mapping[str, Any]) -> Mapping[str, Any]: ...
    @abstractmethod
    async def error(self) -> Mapping[str, Any] | None: ...
    @abstractmethod
    async def health(self) -> TransportHealth: ...
