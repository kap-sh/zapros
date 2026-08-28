# Testing & Mocking

How to test code that uses Zapros without hitting the network: **mocks** (WireMock-style request matching with canned responses), **cassettes** (record/replay real interactions to JSON), and **matchers** (the request predicates both of them use).

Imports:

```python
from zapros.mock import Mock, MockMiddleware, MockRouter, mock_http
from zapros.matchers import path, method, host, header, query, json, and_, or_, not_, Matcher
from zapros import CassetteMiddleware, CassetteMode, ModifierRouter, UnhandledRequestError
```

## Mocking

### Preferred: inject `MockMiddleware` into the client

```python
from zapros import AsyncClient, Response
from zapros.mock import Mock, MockMiddleware, MockRouter
from zapros.matchers import path

router = MockRouter()
router.add(Mock.given(path("/api")).respond(Response(status=200, json={"ok": True})))

async with AsyncClient(handler=MockMiddleware(router)) as client:
    response = await client.get("https://api.example.com/api")
    assert response.json == {"ok": True}
# leaving the `with` block calls router.verify() then router.reset()
```

Sync is identical with `Client` and no `await`. `MockMiddleware()` with no router creates one — reach it via `middleware.router`.

Behaviour:

- Unmatched request → `ValueError("No mock matched request: GET /path")`. To let unmatched requests through to a real handler instead: `MockMiddleware(router, next_handler=AsyncStdNetworkHandler())` (kwarg is `next_handler`).
- Closing the middleware (client context exit) runs `router.verify()` — raises `AssertionError` from `__exit__` if any `expect`/`once`/`never` is unmet — then `router.reset()`. Call them manually if you don't use a `with` block.
- The response returned by a mock gets `response.request` set to the matched request.

Typical pytest fixture:

```python
import pytest, zapros
from zapros.mock import MockMiddleware, MockRouter


@pytest.fixture
def mock_client():
    middleware = MockMiddleware()
    with zapros.Client(middleware) as client:
        yield client, middleware.router


def test_users(mock_client):
    client, router = mock_client
    router.add(Mock.given(path("/users")).respond(zapros.Response(200, json=[])))
    assert client.get("https://example.com/users").status == 200
```

### Fallback: `mock_http()` when you can't reach the client

Globally patches `StdNetworkHandler.handle` / `AsyncStdNetworkHandler.ahandle` for the duration of the block and yields a `MockRouter`. Use only for code that builds its own client internally (e.g. third-party libraries).

```python
from zapros.mock import Mock, mock_http

with mock_http() as router:
    router.add(Mock.given(path("/api")).respond(Response(status=200)))
    result = third_party_function()   # its internal zapros client is intercepted
# verify() runs on clean exit; reset() runs always
```

### Building a `Mock`

Fluent builder; every method returns the mock.

```python
mock = (
    Mock.given(path("/users"))          # first matcher (Mock() alone matches every request)
    .and_(method("POST"))               # additional matchers, all must match
    .respond(Response(201, json={"id": 1}))
    .once()                             # expectation, see below
    .name("create-user")                # used in assertion error messages
)
router.add(mock)                        # or mock.mount(router)
```

Responses — pick one:

- `.respond(Response(...))` — a fixed `Response` object (`Response(status, headers=, json=|text=|content=)`). Note: `respond()` takes a `Response`, not `status=`/`text=` kwargs.
- `.callback(fn)` — `fn(request: Request) -> Response`, computed per call.
- `.callback(SomeError)` or `.callback(SomeError("msg"))` — raise an exception class/instance instead of responding (simulate connection errors, timeouts, etc.).
- Neither → `Response(status=200)` with empty body.

```python
def handler(req):
    return Response(404) if req.url.pathname == "/missing" else Response(200)

router.add(Mock.given(method("GET")).callback(handler))
router.add(Mock.given(path("/flaky")).callback(ConnectionError("boom")))
```

### Expectations and call inspection

Set an expected count and it's checked by `verify()`:

- `.expect(n)` — exactly `n` calls
- `.once()` — exactly 1
- `.never()` — 0 calls (fails if hit)

Post-hoc inspection (doesn't affect matching):

```python
mock.called                 # bool
mock.call_count             # int
mock.calls                  # list[Request] in order
mock.assert_called()
mock.assert_not_called()
mock.assert_called_once()
mock.calls[0].method / .url / .headers / .body
```

### Dispatch order and sequences

`MockRouter` tries mocks in **registration order** and uses the first whose matchers all pass. A mock with `expect(n)`/`once()` stops matching once it has been called `n` times (`never()` never exhausts — it stays active so it can fail), so registering several mocks for the same path yields a sequence:

```python
router.add(Mock.given(path("/api")).respond(Response(200)).once())
router.add(Mock.given(path("/api")).respond(Response(500)).once())
# 1st GET /api -> 200, 2nd -> 500, 3rd -> ValueError (nothing left to match)
```

Put more specific mocks before catch-alls (`Mock()` with no matcher matches everything).

## Matchers

All matchers implement `Matcher` (`match(request: Request) -> bool`) and are used by mocks and cassette modifiers.

| Matcher | Semantics |
|---------|-----------|
| `path("/users")` | exact `url.pathname` equality |
| `path(re.compile(r"/user/.*"))` | `pattern.match(pathname)` (anchored at start) |
| `method("post")` | case-insensitive |
| `host("api.example.com")` | exact `url.hostname` |
| `header("authorization", "Bearer x")` | header present and value equal (name case-insensitive) |
| `query(page="2", limit="10")` | every given key present with equal value; extra params ignored |
| `json(lambda body: body["name"] == "x")` | request body parsed as JSON and passed to the predicate |

Combine with `and_(a, b, ...)`, `or_(a, b, ...)`, `not_(a)`, or chain fluently — every matcher (including custom ones) has `.method()`, `.path()`, `.host()`, `.header()`, `.query()`, `.json()`, `.and_()`, `.or_()`:

```python
matcher = path("/api/users").method("POST").header("content-type", "application/json")
matcher = or_(path("/health"), path("/status"))
matcher = not_(method("POST"))
```

Custom matcher:

```python
from zapros.matchers import Matcher


class PathPrefix(Matcher):
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def match(self, request: Request) -> bool:
        return request.url.pathname.startswith(self._prefix)


Mock.given(PathPrefix("/api/v1").method("GET"))
```

## Cassettes (record / replay)

`CassetteMiddleware` wraps a real handler, records request/response pairs to `<cassette_dir>/<cassette_name>.json`, and replays them on later runs.

```python
from zapros import AsyncClient, AsyncStdNetworkHandler, CassetteMiddleware, CassetteMode

handler = CassetteMiddleware(
    AsyncStdNetworkHandler(),          # next handler (sync: StdNetworkHandler())
    cassette_name="github_api",        # default "default"
    cassette_dir="cassettes",          # default
    mode=CassetteMode.ONCE,            # default; see modes
    allow_playback_repeats=False,      # default
    router=None,                       # ModifierRouter for redaction, see below
)

async with AsyncClient(handler=handler) as client:
    response = await client.get("https://api.github.com/users/octocat")
```

### Modes

| `CassetteMode` | Cassette exists | Matched request | Unmatched request |
|----------------|-----------------|-----------------|-------------------|
| `ONCE` (default) | no → record (identical requests within the run are replayed) | replay | error |
| `NEW_EPISODES` | — | replay | hit network, append |
| `ALL` | discarded at init | hit network, record | hit network, record |
| `NONE` | — | replay | error (`UnhandledRequestError`) |

- `NONE` is the CI mode: guarantees no network. The next handler is never invoked, but it must still be a real handler — `CassetteMiddleware(None, ...)` raises `AsyncSyncMismatchError` on the first request. Pass `MockMiddleware()` (or the usual network handler) as a placeholder.
- If `mode=` is omitted, it's read from `ZAPROS_CASSETTE_MODE` (`all`, `new_episodes`, `once`, `none`, case-insensitive; invalid → `ValueError` at init). Explicit `mode=` wins; neither set → `once`. This lets the same test code record locally (`ZAPROS_CASSETTE_MODE=all pytest`) and replay in CI (`=none`).

### Matching and repeats

- Match key = **method + normalized URL** (query params sorted, so `?a=1&b=2` == `?b=2&a=1`). Headers and bodies are **not** part of the key.
- Each recorded interaction plays back **once**; a second identical request raises `UnhandledRequestError`. Set `allow_playback_repeats=True` to replay the same entry repeatedly.

### Modifiers (redaction / normalization)

A `ModifierRouter` applies matcher-selected transforms before recording. Use it to strip tokens from URLs, normalize dynamic segments, or drop sensitive response headers. `map_network_request` only changes what is used as the cassette key — the request actually sent over the network is untouched.

```python
from zapros import CassetteMiddleware, CassetteMode, ModifierRouter, Request, Response, URL
from zapros.matchers import path

router = ModifierRouter()


def strip_query(req: Request) -> Request:                # runs before the request becomes the cassette key
    url = URL(req.url.href)
    url.search = ""
    return Request(url, req.method)


def redact(resp: Response) -> Response:                  # runs before the response is saved
    headers = resp.headers.copy()                        # Headers: case-insensitive
    if "set-cookie" in headers:
        del headers["set-cookie"]
    return Response(status=resp.status, headers=headers, content=resp.read())


router.modifier(path("/api")).map_network_request(strip_query)
router.modifier(path("/login")).map_network_response(redact)

handler = CassetteMiddleware(network_handler, router=router, mode=CassetteMode.ALL, cassette_name="test")
```

### File format

JSON list of `{"request": {"method", "uri"}, "response": {"status", "headers", "body"}}`. Body encoding depends on response `content-type`: JSON (`application/json`, `*/*+json`) is inlined as a JSON value; `text/*` as a string (decoded with the charset, default utf-8); anything else as base64. Commit cassettes to the repo so CI can replay.

## Choosing an approach

- Unit tests of your own code → `MockMiddleware` + matchers; assert on `mock.calls` for outgoing-request shape.
- Code that constructs its own client → `mock_http()`.
- Integration tests against a real API you can't fake easily → cassettes, recorded once with `ALL`/`ONCE`, replayed with `NONE` in CI, with modifiers redacting secrets.
- Simulating network failures → `Mock.callback(SomeException)`.

## Quick Checklist

- `Mock.respond()` takes a `Response` object; `Mock()` with no `given()` matches everything.
- Mocks match in registration order; exhausted (`once`/`expect`) mocks are skipped.
- Expectations are verified when the client/`mock_http` block exits — a failing `verify()` raises from `__exit__`.
- Unmatched mock request → `ValueError` unless `next_handler=` is given.
- Cassette key is method + sorted-query URL only; playback is single-use unless `allow_playback_repeats=True`.
- Set `ZAPROS_CASSETTE_MODE=none` in CI to guarantee zero network access.
