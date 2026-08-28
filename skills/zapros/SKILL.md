---
name: zapros
description: Best-practice guide for writing Python code with the Zapros HTTP client (AsyncClient / Client). Use whenever code imports `zapros` or the user mentions Zapros — sending HTTP requests (query params, JSON/form/multipart bodies, streaming), reading responses, configuring clients, testing code that uses Zapros (MockMiddleware, mock_http, cassettes, matchers), writing custom middleware or handlers, or migrating from httpx/requests to Zapros.
---

# Zapros

Zapros is a modern, extensible Python HTTP client with a sync API (`Client`) and an async API (`AsyncClient`) that mirror each other. Requests flow through a chain of middlewares ending in a transport handler; that chain is the extension point for everything (retries, caching, cookies, mocking, cassettes, custom behaviour).

This skill is an opinionated guide to doing things the right way. The full API surface lives in the docs at https://zapros.dev — link there for options this skill doesn't cover.

## Rules that apply everywhere

- Import only from the top-level `zapros` package (plus `zapros.mock` and `zapros.matchers`). Never import from private `zapros._*` modules.
- Match the user's mode. Async code uses `AsyncClient` and the `a*`/`async_*` method variants (`aread`, `async_iter_bytes`, `aclose`); sync code uses `Client` and the plain names. Mixing them raises `AsyncSyncMismatchError`.
- Always open clients with `async with AsyncClient() as client:` / `with Client() as client:`, and wrap `client.stream(...)` in a context manager too.
- Prefer a built-in middleware or handler over custom code; check https://zapros.dev before writing your own.
- Prefer `MockMiddleware` injected into the client over `mock_http()` global patching in tests.
- When unsure about an exact signature, read the installed source: `python -c "import zapros, os; print(os.path.dirname(zapros.__file__))"`.

## Minimal example

```python
from zapros import AsyncClient

async with AsyncClient(base_url="https://api.example.com/v1/") as client:
    response = await client.get("users", params={"page": "1"})
    response.status          # 200
    response.json            # parsed body (property)
```

## References

Load only the file relevant to the task:

| Task | Read |
|------|------|
| Making requests, bodies, headers, URLs, reading/streaming responses, client configuration | [references/sending-requests.md](references/sending-requests.md) |
| Testing code that uses Zapros: mocks, expectations, cassettes, matchers | [references/testing-mocking.md](references/testing-mocking.md) |
| Writing middleware, response ownership, composing handler chains, per-request handler override | [references/handlers-extending.md](references/handlers-extending.md) |

Not covered by references — go straight to the docs: WebSockets (https://zapros.dev/websockets), authentication (https://zapros.dev/authentication), retries/redirects/cookies/caching middleware options (https://zapros.dev/retries and siblings), ASGI/browser/Rust transports (https://zapros.dev/asgi, /browser, /rust), migrating from httpx (https://zapros.dev/httpx-alternative).
