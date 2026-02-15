from dataclasses import dataclass, field


@dataclass
class MockResponse:
    status: int = 200
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""


class MockResponseBuilder:
    def __init__(self, mock: MockResponse) -> None:
        self._mock = mock

    def with_status(self, status: int) -> "MockResponseBuilder":
        self._mock.status = status
        return self

    def with_body(self, body: bytes | str) -> "MockResponseBuilder":
        if isinstance(body, str):
            body = body.encode()
        self._mock.body = body
        return self

    def with_header(self, name: str, value: str) -> "MockResponseBuilder":
        self._mock.headers.append(
            (
                name,
                value,
            )
        )
        return self


class MockBuilder:
    def __init__(
        self,
        server: "BaseMock",
        node_id: str,
    ) -> None:
        self._server = server
        self._node_id = node_id

    def on(self, method: str, path: str) -> MockResponseBuilder:
        mock = self._server.register_mock(
            self._node_id,
            method.upper(),
            path,
        )
        return MockResponseBuilder(mock)


class BaseMock:
    def register_mock(
        self,
        node_id: str,
        method: str,
        path: str,
    ) -> MockResponse: ...
