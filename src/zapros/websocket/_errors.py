from zapros._errors import ZaprosError
from zapros.websocket._types import CloseCode


class WebsocketError(ZaprosError):
    """Base class for all WebSocket errors."""

    pass


class ConnectionClosed(WebsocketError):
    """Raised when an event is requested on a closed connection."""

    def __init__(
        self,
        code: CloseCode | int,
        reason: str | None = None,
    ):
        self.code = code
        self.reason = reason
        super().__init__(
            f"WebSocket connection closed with code {code}" + (f" and reason: {reason!r}" if reason else "")
        )
