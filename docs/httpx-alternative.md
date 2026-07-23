---
navbar: false
sidebar: false
aside: false
---

# The HTTPX alternative

[HTTPX](https://www.python-httpx.org/) is no longer maintained. The Pydantic team forked it into httpx2 to keep the API alive.

I went a different way. I used to maintain HTTPX, and for a while I was its most active developer. After a few years in that codebase I had a fairly precise idea of what worked and what didn't, and forking it wasn't going to fix the parts that didn't. So I wrote a new client instead.

That's Zapros.

## What has been changed from HTTPX

### The client does less

`httpx.Client` comes with a lot built in, and none of it comes out. If you use `httpx.Client`, you use its redirect handling, its retries, its everything. Replacing one of those implementations, or tuning it past the knobs it happens to expose, means reaching into internals.

Zapros ships a deliberately dumb client that does almost nothing on its own. Redirects, retries, cookies, and the rest are [middleware](/handlers). Turn them on when you need them, and bring your own implementation when the built-in one doesn't fit. Zapros gives you implementations; it doesn't make you use them.

### One library, not two

HTTPX keeps its I/O in a separate package, httpcore. The separation reads well on paper. In practice it means code duplicated across the boundary, a version matrix to keep compatible, and two packages on PyPI instead of one.

Zapros keeps the same conceptual separation, minus the second package.

### A transport layer built for it

Both clients abstract the transport. Zapros was built around that abstraction from the first commit rather than growing into it later, which makes it fit better.

Along with the ASGI handler that HTTPX also has, Zapros ships:

* an [`AsyncPyodideHandler`](/browser) for WASM, so the same code runs in the browser
* an [`AsyncPyreqwestHandler`](/rust) built on Rust's [reqwest](https://docs.rs/reqwest), for when performance matters

### WebSockets, built in

Zapros includes a [WebSocket client](/websockets) built on the sans-IO [wsproto](https://python-hyper.org/projects/wsproto/) library. The handshake goes through your normal client, so auth, cookies, retries, and custom handlers all apply.

### More batteries, still no obligation

HTTPX leaves several core features to third-party libraries:

| Feature | HTTPX | Zapros |
|---|---|---|
| Mocking | respx, pytest-httpx | [built in](/mocking) |
| Caching | hishel (same author as Zapros) | [built in](/caching) |
| Cassettes | vcrpy | [built in](/cassettes) |

Zapros has all three out of the box, and none of them are mandatory. The built-in ones should fit most of the time. When they don't, swap in something else.

See the [documentation](/) for the rest.
