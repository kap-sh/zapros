---
title: Matchers
description: Match HTTP requests by path, method, headers, query parameters, and body content.
---

# Matchers

Matchers inspect parts of HTTP requests (method, path, headers, etc.) and return `True` if the request matches. They're used by both the [mocking system](/mocking) and [cassette modifiers](/cassettes#modifiers).

All matchers implement the `Matcher` protocol with a `match(request: Request) -> bool` method.

## Path

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import path

matcher = path("/health")

request = Request(URL("https://api.example.com/health"), "GET")
assert matcher.match(request) == True

request = Request(URL("https://api.example.com/other"), "GET")
assert matcher.match(request) == False
```

You can also use regex-based matching:

```python
import re
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import path

matcher = path(re.compile("/user/.*"))

request = Request(URL("https://api.example.com/user/123"), "GET")
assert matcher.match(request) == True

request = Request(URL("https://api.example.com/other"), "GET")
assert matcher.match(request) == False
```

## Method

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import method

matcher = method("POST")

request = Request(URL("https://api.example.com/"), "POST")
assert matcher.match(request) == True

request = Request(URL("https://api.example.com/"), "GET")
assert matcher.match(request) == False
```

Method matching is **case-insensitive**.

## Host

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import host

matcher = host("api.example.com")

request = Request(URL("https://api.example.com/path"), "GET")
assert matcher.match(request) == True

request = Request(URL("https://other.example.com/path"), "GET")
assert matcher.match(request) == False
```

## Headers

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import header

matcher = header("authorization", "Bearer token")

request = Request(
    URL("https://api.example.com/"),
    "GET",
    headers={"authorization": "Bearer token"},
)
assert matcher.match(request) == True

request = Request(
    URL("https://api.example.com/"),
    "GET",
    headers={"authorization": "Bearer other"},
)
assert matcher.match(request) == False
```

## Query Parameters

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import query

matcher = query(page="2", limit="10")

request = Request(
    URL("https://api.example.com/items?page=2&limit=10"),
    "GET",
)
assert matcher.match(request) == True

request = Request(
    URL("https://api.example.com/items?page=1&limit=10"),
    "GET",
)
assert matcher.match(request) == False
```

## JSON Body

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import json

matcher = json(lambda body: body["name"] == "test")

request = Request(
    URL("https://api.example.com/items"),
    "POST",
    body=b'{"name": "test"}',
)
assert matcher.match(request) == True

request = Request(
    URL("https://api.example.com/items"),
    "POST",
    body=b'{"name": "other"}',
)
assert matcher.match(request) == False
```

The function receives the parsed JSON body.

## Combining Matchers

Matchers can be combined using logical helpers.

### AND

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import and_, method, path

matcher = and_(method("GET"), path("/health"))

request = Request(URL("https://api.example.com/health"), "GET")
assert matcher.match(request) == True

request = Request(URL("https://api.example.com/health"), "POST")
assert matcher.match(request) == False
```

### OR

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import or_, path

matcher = or_(path("/health"), path("/status"))

request = Request(URL("https://api.example.com/health"), "GET")
assert matcher.match(request) == True

request = Request(URL("https://api.example.com/status"), "GET")
assert matcher.match(request) == True

request = Request(URL("https://api.example.com/other"), "GET")
assert matcher.match(request) == False
```

### NOT

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import method, not_

matcher = not_(method("POST"))

request = Request(URL("https://api.example.com/"), "GET")
assert matcher.match(request) == True

request = Request(URL("https://api.example.com/"), "POST")
assert matcher.match(request) == False
```

## Fluent API

Matchers can also be chained fluently:

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import path

matcher = (
    path("/api/users")
    .method("POST")
    .header("content-type", "application/json")
)

request = Request(
    URL("https://api.example.com/api/users"),
    "POST",
    headers={"content-type": "application/json"},
)
assert matcher.match(request) == True
```

## Custom Matchers

Any class with a `match(self, request: Request) -> bool` method satisfies the `Matcher` protocol:

```python
from pywhatwgurl import URL
from zapros import Request
from zapros.matchers import Matcher


class PathPrefixMatcher(Matcher):
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def match(self, request: Request) -> bool:
        return request.url.pathname.startswith(self._prefix)


matcher = PathPrefixMatcher("/api/v1")

request = Request(URL("https://api.example.com/api/v1/users"), "GET")
assert matcher.match(request) == True

request = Request(URL("https://api.example.com/api/v2/users"), "GET")
assert matcher.match(request) == False
```

Custom matchers inherit the fluent chaining API (`.method()`, `.path()`, `.header()`, etc.) from the `Matcher` protocol:

```python
matcher = PathPrefixMatcher("/api/v1").method("GET")
```
