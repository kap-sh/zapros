from __future__ import annotations

import json
from pathlib import Path

import pytest
from pywhatwgurl import URL

from zapros import (
    Client,
    Cassette,
    CassetteMiddleware,
    UnhandledRequestError,
)
from zapros._handlers._mock import Mock
from zapros._models import Response
from zapros.matchers import path
from zapros.mock import (
    MockMiddleware,
    MockRouter,
)


def test_records_interaction_to_file(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/record")).respond(Response(status=200, text="recorded")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        response = client.get(
            "http://example.com/record",
        )

    assert response.status == 200
    cassette_file = tmp_path / "test.json"
    assert cassette_file.exists()
    data = json.loads(cassette_file.read_text())
    assert len(data) == 1
    assert data[0]["request"]["method"] == "GET"
    assert data[0]["request"]["uri"] == "http://example.com/record"
    assert data[0]["response"]["status"] == 200
    assert data[0]["response"]["body"] == "recorded"


def test_replays_from_cassette_without_hitting_network(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/replay")).respond(Response(status=200, text="from cassette")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    record_handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=record_handler) as client:
        client.get(
            "http://example.com/replay",
        )

    replay_cassette = Cassette()
    replay_handler = CassetteMiddleware(
        replay_cassette,
        MockMiddleware(router=MockRouter()),
        mode="none",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=replay_handler) as client:
        response = client.get(
            "http://example.com/replay",
        )
        text = response.text

    assert response.status == 200
    assert text == "from cassette"


def test_mode_once_records_when_no_cassette(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/once")).respond(Response(status=200, text="once-recorded")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="once",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        client.get(
            "http://example.com/once",
        )

    assert (tmp_path / "test.json").exists()
    data = json.loads((tmp_path / "test.json").read_text())
    assert len(data) == 1
    assert data[0]["response"]["body"] == "once-recorded"


def test_mode_once_does_not_record_when_cassette_exists(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/existing")).respond(Response(status=200, text="cached")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    first_handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="once",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=first_handler) as client:
        client.get(
            "http://example.com/existing",
        )

    router2 = MockRouter()
    Mock.given(path("/new-path")).respond(Response(status=200, text="new")).mount(router2)
    mock_handler2 = MockMiddleware(router=router2)

    cassette2 = Cassette()
    second_handler = CassetteMiddleware(
        cassette2,
        mock_handler2,
        mode="once",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=second_handler) as client:
        with pytest.raises(UnhandledRequestError):
            client.get(
                "http://example.com/new-path",
            )


def test_mode_none_raises_for_unmatched_request(
    tmp_path: Path,
) -> None:
    cassette = Cassette()
    handler = CassetteMiddleware(
        cassette,
        MockMiddleware(router=MockRouter()),
        mode="none",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        with pytest.raises(UnhandledRequestError):
            client.get(
                "http://example.com/missing",
            )


def test_mode_none_replays_matched_request(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/match")).respond(Response(status=200, text="matched")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    record_handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=record_handler) as client:
        client.get(
            "http://example.com/match",
        )

    replay_cassette = Cassette()
    replay_handler = CassetteMiddleware(
        replay_cassette,
        MockMiddleware(router=MockRouter()),
        mode="none",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=replay_handler) as client:
        response = client.get(
            "http://example.com/match",
        )
        text = response.text

    assert response.status == 200
    assert text == "matched"


def test_mode_new_episodes_replays_existing_and_records_new(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/old-path")).respond(Response(status=200, text="old-cached")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    record_handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=record_handler) as client:
        client.get(
            "http://example.com/old-path",
        )

    router2 = MockRouter()
    Mock.given(path("/new-path")).respond(Response(status=201, text="new-recorded")).mount(router2)
    mock_handler2 = MockMiddleware(router=router2)

    cassette2 = Cassette()
    new_episodes_handler = CassetteMiddleware(
        cassette2,
        mock_handler2,
        mode="new_episodes",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=new_episodes_handler) as client:
        old_response = client.get(
            "http://example.com/old-path",
        )
        old_text = old_response.text

        new_response = client.get(
            "http://example.com/new-path",
        )
        new_text = new_response.text

    assert old_response.status == 200
    assert old_text == "old-cached"
    assert new_response.status == 201
    assert new_text == "new-recorded"

    data = json.loads((tmp_path / "test.json").read_text())
    assert len(data) == 2


def test_mode_all_always_hits_network(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/path")).respond(Response(status=200, text="cached")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    first_handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=first_handler) as client:
        client.get(
            "http://example.com/path",
        )

    router2 = MockRouter()
    Mock.given(path("/path")).respond(Response(status=201, text="fresh")).mount(router2)
    mock_handler2 = MockMiddleware(router=router2)

    cassette2 = Cassette()
    second_handler = CassetteMiddleware(
        cassette2,
        mock_handler2,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=second_handler) as client:
        response = client.get(
            "http://example.com/path",
        )
        text = response.text

    assert response.status == 201
    assert text == "fresh"

    data = json.loads((tmp_path / "test.json").read_text())
    assert len(data) == 2


def test_playback_marks_played_back(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/once-only")).respond(Response(status=200, text="once")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    record_handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=record_handler) as client:
        client.get(
            "http://example.com/once-only",
        )

    replay_cassette = Cassette()
    replay_handler = CassetteMiddleware(
        replay_cassette,
        MockMiddleware(router=MockRouter()),
        mode="none",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=replay_handler) as client:
        client.get(
            "http://example.com/once-only",
        )
        with pytest.raises(UnhandledRequestError):
            client.get(
                "http://example.com/once-only",
            )


def test_allow_playback_repeats(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/repeatable")).respond(Response(status=200, text="repeat")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    record_handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=record_handler) as client:
        client.get(
            "http://example.com/repeatable",
        )

    replay_cassette = Cassette(allow_playback_repeats=True)
    replay_handler = CassetteMiddleware(
        replay_cassette,
        MockMiddleware(router=MockRouter()),
        mode="none",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=replay_handler) as client:
        r1 = client.get(
            "http://example.com/repeatable",
        )
        r2 = client.get(
            "http://example.com/repeatable",
        )
        t1 = r1.text
        t2 = r2.text

    assert r1.status == 200
    assert r2.status == 200
    assert t1 == "repeat"
    assert t2 == "repeat"


def test_modifier_transforms_cassette_request_key(
    tmp_path: Path,
) -> None:
    from zapros import (
        Request as ZaprosRequest,
    )

    router = MockRouter()
    Mock.given(path("/api")).respond(Response(status=200, text="ok")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()

    def strip_query(
        req: ZaprosRequest,
    ) -> ZaprosRequest:
        new_url = URL(req.url.to_string())
        new_url.search = ""
        return ZaprosRequest(new_url, req.method)

    cassette.modifier(path("/api")).map_network_request(strip_query)
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        client.get(
            "http://example.com/api?token=secret123",
        )

    data = json.loads((tmp_path / "test.json").read_text())
    assert data[0]["request"]["uri"] == "http://example.com/api"


def test_modifier_transforms_network_response(
    tmp_path: Path,
) -> None:
    from zapros import Response

    router = MockRouter()
    Mock.given(path("/transform")).respond(Response(status=200, text="original")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    cassette.modifier(path("/transform")).map_network_response(
        lambda resp: Response(
            status=999,
            headers=dict(resp.headers),
            content=resp.iter_raw(),
        )
    )
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        response = client.get(
            "http://example.com/transform",
        )

    assert response.status == 999

    data = json.loads((tmp_path / "test.json").read_text())
    assert data[0]["response"]["status"] == 999


def test_url_query_param_normalization(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/search")).respond(Response(status=200, text="normalized")).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    record_handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=record_handler) as client:
        client.get(
            "http://example.com/search?a=1&b=2",
        )

    replay_cassette = Cassette()
    replay_handler = CassetteMiddleware(
        replay_cassette,
        MockMiddleware(router=MockRouter()),
        mode="none",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=replay_handler) as client:
        response = client.get(
            "http://example.com/search?b=2&a=1",
        )
        text = response.text

    assert response.status == 200
    assert text == "normalized"


def test_json_body_stored_as_object(
    tmp_path: Path,
) -> None:
    router = MockRouter()
    Mock.given(path("/api/user")).respond(
        Response(
            status=200,
            json={"id": 123, "name": "John", "active": True},
        )
    ).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        response = client.get(
            "http://example.com/api/user",
        )
        body = response.json

    assert response.status == 200
    assert body == {"id": 123, "name": "John", "active": True}

    data = json.loads((tmp_path / "test.json").read_text())
    assert len(data) == 1
    assert data[0]["response"]["body"] == {"id": 123, "name": "John", "active": True}
    assert isinstance(data[0]["response"]["body"], dict)


def test_binary_body_stored_as_base64(
    tmp_path: Path,
) -> None:
    import base64

    from zapros import Response

    binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    router = MockRouter()
    Mock.given(path("/image")).callback(
        lambda _: Response(
            status=200,
            headers={"content-type": "image/png"},
            content=binary_data,
        )
    ).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        response = client.get(
            "http://example.com/image",
        )
        body = response.read()

    assert response.status == 200
    assert body == binary_data

    data = json.loads((tmp_path / "test.json").read_text())
    assert len(data) == 1
    assert data[0]["response"]["body"] == base64.b64encode(binary_data).decode("ascii")
    assert isinstance(data[0]["response"]["body"], str)


def test_compressed_json_stored_decompressed(
    tmp_path: Path,
) -> None:
    import gzip

    from zapros import Response

    json_obj = {"login": "octocat", "id": 583231, "type": "User"}
    json_bytes = json.dumps(json_obj).encode("utf-8")
    compressed = gzip.compress(json_bytes)

    router = MockRouter()
    Mock.given(path("/api/user")).callback(
        lambda _: Response(
            status=200,
            headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
            },
            content=compressed,
        )
    ).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        response = client.get(
            "http://example.com/api/user",
        )
        body = response.json

    assert response.status == 200
    assert body == json_obj

    data = json.loads((tmp_path / "test.json").read_text())
    assert len(data) == 1
    assert data[0]["response"]["body"] == json_obj
    assert isinstance(data[0]["response"]["body"], dict)
    assert "content-encoding" not in data[0]["response"]["headers"]


def test_compressed_text_stored_decompressed(
    tmp_path: Path,
) -> None:
    import gzip

    from zapros import Response

    text_content = "Hello, World! This is compressed text."
    compressed = gzip.compress(text_content.encode("utf-8"))

    router = MockRouter()
    Mock.given(path("/text")).callback(
        lambda _: Response(
            status=200,
            headers={
                "content-type": "text/plain",
                "content-encoding": "gzip",
            },
            content=compressed,
        )
    ).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        response = client.get(
            "http://example.com/text",
        )
        body = response.text

    assert response.status == 200
    assert body == text_content

    data = json.loads((tmp_path / "test.json").read_text())
    assert len(data) == 1
    assert data[0]["response"]["body"] == text_content
    assert isinstance(data[0]["response"]["body"], str)
    assert "content-encoding" not in data[0]["response"]["headers"]


def test_compressed_binary_stored_decompressed(
    tmp_path: Path,
) -> None:
    import base64
    import gzip

    from zapros import Response

    binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    compressed = gzip.compress(binary_data)

    router = MockRouter()
    Mock.given(path("/image")).callback(
        lambda _: Response(
            status=200,
            headers={
                "content-type": "image/png",
                "content-encoding": "gzip",
            },
            content=compressed,
        )
    ).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        response = client.get(
            "http://example.com/image",
        )
        body = response.read()

    assert response.status == 200
    assert body == binary_data

    data = json.loads((tmp_path / "test.json").read_text())
    assert len(data) == 1
    assert data[0]["response"]["body"] == base64.b64encode(binary_data).decode("ascii")
    assert "content-encoding" not in data[0]["response"]["headers"]


def test_empty_body_stored_as_null(
    tmp_path: Path,
) -> None:
    from zapros import Response

    router = MockRouter()
    Mock.given(path("/empty")).callback(
        lambda req: Response(
            status=204,
            headers={},
            content=None,
        )
    ).mount(router)
    mock_handler = MockMiddleware(router=router)

    cassette = Cassette()
    handler = CassetteMiddleware(
        cassette,
        mock_handler,
        mode="all",
        cassette_dir=str(tmp_path),
        cassette_name="test",
    )

    with Client(handler=handler) as client:
        response = client.get(
            "http://example.com/empty",
        )

    assert response.status == 204

    data = json.loads((tmp_path / "test.json").read_text())
    assert len(data) == 1
    assert data[0]["response"]["body"] is None
