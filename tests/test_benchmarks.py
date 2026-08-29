from collections.abc import Iterator

import pytest

from zapros import Client, Response
from zapros._constants import CHUNK_SIZE
from zapros._decoders import ByteChunker


@pytest.fixture(scope="session")
def body() -> bytes:
    return b"x" * (4 * 1024 * 1024)


@pytest.fixture(scope="session")
def body_chunks(body: bytes) -> list[bytes]:
    socket_sized_inbound_pease_size = 64 * 1024
    return [body[i : i + socket_sized_inbound_pease_size] for i in range(0, len(body), socket_sized_inbound_pease_size)]


@pytest.fixture(
    scope="session",
    params=[
        pytest.param(1024, id="1KiB"),
        pytest.param(CHUNK_SIZE // 2, id="8KiB"),
        pytest.param(CHUNK_SIZE, id="16KiB"),
        pytest.param(64 * 1024, id="64KiB"),
        pytest.param(1024 * 1024, id="1MiB"),
        pytest.param(4 * 1024 * 1024, id="4MiB"),
        pytest.param(8 * 1024 * 1024, id="8MiB"),
    ],
)
def single_feed_body(request: pytest.FixtureRequest, body: bytes) -> bytes:
    return body[: request.param]


@pytest.mark.benchmark
def test_bench_bytechunker_stream(body_chunks: list[bytes], body: bytes) -> None:
    chunker = ByteChunker(CHUNK_SIZE)
    total = sum(len(chunk) for piece in body_chunks for chunk in chunker.feed(piece))
    total += len(chunker.flush())
    assert total == len(body)


@pytest.mark.benchmark
def test_bench_bytechunker_single_feed(single_feed_body: bytes) -> None:
    chunker = ByteChunker(CHUNK_SIZE)
    total = sum(len(c) for c in chunker.feed(single_feed_body)) + len(chunker.flush())
    assert total == len(single_feed_body)


@pytest.mark.benchmark
def test_bench_iter_bytes_identity_e2e(body_chunks: list[bytes], body: bytes) -> None:
    response = Response(200, content=iter(body_chunks))
    assert sum(len(c) for c in response.iter_bytes()) == len(body)


@pytest.fixture(scope="session")
def client() -> Iterator[Client]:
    with Client() as instance:
        yield instance


@pytest.mark.benchmark
@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://sqs.eu-west-1.amazonaws.com/", id="short"),
        pytest.param(
            "https://sqs.eu-west-1.amazonaws.com/000000000000/my-queue/some/deeper/path",
            id="long-path",
        ),
        pytest.param(
            "https://sqs.eu-west-1.amazonaws.com/q?Action=ReceiveMessage&Version=2012-11-05",
            id="query",
        ),
        pytest.param("http://127.0.0.1:4566/000000000000/my-queue", id="ip-literal"),
    ],
)
def test_bench_merge_url(client: Client, url: str) -> None:
    client._merge_url(url)
