from dataclasses import dataclass
from enum import IntEnum
from typing import Literal


class CloseCode(IntEnum):
    NORMAL = 1000
    """Normal closure: the purpose of the connection has been fulfilled."""

    GOING_AWAY = 1001
    """Endpoint is going away (e.g. client navigating away, app exiting)."""

    PROTOCOL_ERROR = 1002
    """Peer violated the WebSocket protocol."""

    UNSUPPORTED_DATA = 1003
    """Peer sent a type of data this endpoint cannot accept
    (e.g. a binary message to a text-only endpoint)."""

    ABNORMAL = 1006
    """Reserved. MUST NOT be sent on the wire. Used locally to indicate the
    connection closed without a proper close frame."""

    INVALID_FRAME_PAYLOAD_DATA = 1007
    """Peer sent message data inconsistent with the message type
    (e.g. non-UTF-8 bytes inside a text message)."""

    POLICY_VIOLATION = 1008
    """Peer sent a message that violates this endpoint's policy. Generic code
    when no more specific code applies."""

    MESSAGE_TOO_BIG = 1009
    """Peer sent a message too big for this endpoint to process."""


@dataclass(frozen=True, slots=True)
class TextMessage:
    data: str
    kind: Literal["text"] = "text"


@dataclass(frozen=True, slots=True)
class BinaryMessage:
    data: bytes
    kind: Literal["binary"] = "binary"


@dataclass(frozen=True, slots=True)
class PingMessage:
    data: bytes = b""
    kind: Literal["ping"] = "ping"


@dataclass(frozen=True, slots=True)
class PongMessage:
    data: bytes = b""
    kind: Literal["pong"] = "pong"


@dataclass(frozen=True, slots=True)
class CloseMessage:
    """A close frame received from the peer.

    Receiving this does NOT mean the connection is unusable yet — the underlying
    transport may still be open until `close()` is called. Mirrors the behavior of
    reqwest-websocket's `Message::Close` variant: the close is surfaced as a
    regular stream item, and iteration terminates naturally afterwards.
    """

    code: int = CloseCode.NORMAL
    reason: str | None = None
    kind: Literal["close"] = "close"


# Tagged union — discriminate via `kind` or with `isinstance` / `match`.
Message = TextMessage | BinaryMessage | PingMessage | PongMessage | CloseMessage


@dataclass(frozen=True, slots=True)
class PerMessageDeflateExtension:
    """Represents the negotiated parameters of the permessage-deflate extension.

    This is only relevant if the extension was negotiated during the handshake.
    """

    client_no_context_takeover: bool = False
    server_no_context_takeover: bool = False
    client_max_window_bits: int = 15
    server_max_window_bits: int = 15
