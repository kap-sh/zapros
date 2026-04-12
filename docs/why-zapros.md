---
navbar: false
sidebar: false
---

# Why I built a new HTTP client after working on HTTPX

## A bit of history

In 2022, I built a small experimental HTTP client called [aioreq](https://github.com/karpetrosyan/aioreq). It was async-only, zero-dependency, and mostly an educational project.

A few months later, I joined the [HTTPX](https://www.python-httpx.org/) (encode) team and became one of the maintainers, working on both HTTPX and httpcore (its underlying engine). That’s where I gained real experience and started to see the bigger picture behind HTTP clients.

I also built tools on top of HTTPX, like [hishel](https://hishel.com), a caching layer that ended up getting some real adoption.

## The problem

Over time, HTTPX development slowed down. Reviews and releases became infrequent, and I gradually stepped away.

httpcore, which is more critical (it *is* the engine), had unresolved issues that directly affected users.

So I built `httpx-aiohttp` - an adapter that swaps out httpcore for aiohttp while keeping HTTPX’s API intact. The OpenAI and Anthropic Python SDKs both adopted it in production.

## The core issue

Most HTTP clients mix two very different concerns:

* **HTTP protocol logic** (cookies, redirects, headers, caching - RFC-level behavior)
* **Transport layer** (TCP, TLS, DNS, HTTP/1.1 vs HTTP/2, etc.)

This leads to questions like:

* “Does this client support HTTP/2?”
* “Does it have DNS caching?”
* “Can I swap the TLS backend?”

or statements like:

* “This HTTP client is slow”
* “This HTTP client’s connection pooling sucks”

These are *transport* questions - but they’re tightly coupled to the client itself.

## How Zapros is designed differently

I built [Zapros](https://zapros.dev) around a strict separation:

* A **pure HTTP layer** that implements the protocol
* A pluggable **transport layer** responsible only for sending/receiving bytes

This means:

* The HTTP layer stays focused on protocol correctness: cookies, redirects, headers, caching.
* Transport concerns - connection pooling, TLS, DNS, HTTP/2 - live in one place and can be swapped or improved independently.
* Testing is straightforward: mock the transport, not the client.
* The transport can be replaced entirely - including with a WASM-compatible one for browser environments.

## Current state

Zapros is at v0.6.0 - usable and under active development. The core API is stable; some advanced features are still being added. Feedback welcome.