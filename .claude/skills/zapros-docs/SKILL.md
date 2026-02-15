---
name: zapros-docs
description: Write and edit documentation for the Zapros Python HTTP client. Use when adding or updating pages in the Zapros VitePress docs site at docs/, updating the sidebar in docs/.vitepress/config.mts, or writing code examples for Zapros usage.
---

# Zapros Docs

The docs site is a VitePress project in `docs/`. Pages are Markdown files; navigation is configured in `docs/.vitepress/config.mts`.

## Public API only

All code examples must import from the top-level `zapros` package. Never import from private submodules.

```python
# correct
from zapros import (
    AsyncClient,
    Client,
    Multipart,
    Part,
    AsyncStream,
    Stream,
)

# wrong — private modules
from zapros._multipart import (
    Multipart,
    Part,
)
from zapros._models import (
    AsyncStream,
    Stream,
)
```

## No mocking in examples

Never use mocking in documentation code examples. Use imaginary real APIs instead:

```python
# correct — imaginary real API
from zapros import AsyncClient

async with AsyncClient() as client:
    response = await client.get(
        "https://api.example.com/users",
    )

# wrong — mock examples
from zapros.mock import (
    MockHandler,
    MockRouter,
    given,
    path,
)
```

## Heading separators

Don't use `---` before headings (e.g., `---` before `##`) as it creates unnecessary blank lines in the rendered output.

## Page structure

Each page is a single Markdown file in `docs/`. Use `:::code-group` to show sync and async variants side by side:

````markdown
::: code-group

```python [Async]
async with AsyncClient() as client:
    response = await client.get("https://httpbin.org/get")
```

```python [Sync]
with Client() as client:
    response = client.get("https://httpbin.org/get")
```

:::
````

## Adding a page

1. Create `docs/<slug>.md`
2. Add it to the appropriate sidebar group in `docs/.vitepress/config.mts`:

```ts
{ text: "Page title", link: "/<slug>" }
```
