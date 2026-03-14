---
outline: deep
---

# Overview

::: warning
Zapros is a newborn project and may contain bugs. Please report any issues you encounter on [GitHub](https://github.com/kap-sh/zapros/issues).
:::

Zapros is a **modern and extensible** Python HTTP client. It implements HTTP semantics as defined in [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110) and ships a rich ecosystem of plugins to make developers' lives easier.

## The Sans-IO Design

Most HTTP clients couple two very different concerns together:

| Concern | Examples |
|---|---|
| **HTTP semantics** | Constructing requests, managing headers, decoding `Content-Encoding`, encoding body formats (JSON, form, multipart) |
| **Transport** | DNS, TCP, TLS, connection pooling, HTTP/1.1, HTTP/2, and HTTP/3 framing |

Zapros separates these entirely. `AsyncClient` and `Client` only deal with **semantics** — preparing raw bytes ready to be sent and parsing raw bytes received from the network into a `Response` object. The handler is responsible for the rest: opening sockets, managing connections, and speaking the wire protocol.

## Built-In Implementation

Zapros ships with a built-in HTTP/1.1 handler for both async and sync Python, covering the most necessary functionality out of the box — no extra dependencies required.

::: tip Need more?
Zapros also provides a handler powered by Rust's [reqwest](https://docs.rs/reqwest) under the hood, bringing HTTP/2, HTTP/3, and connection pooling with zero extra configuration. Or swap in any third-party handler of your choice — without changing a single line of client code.
:::

## Why Sans-IO?

- **Powerful features on top of any transport** — caching, retries, mocking, cassettes, and other Zapros plugins work regardless of the low-level implementation you choose.
- A **clean semantics implementation** that lives separately from the transport layer.
- **No transport lock-in** — swap the handler to change the underlying transport; no client code needs to change.
- **Identical requests** regardless of which handler you use. If the underlying library already handles some HTTP semantics, Zapros disables those features to avoid double-handling.

