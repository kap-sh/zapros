# URLs

Zapros uses [pywhatwgurl](https://github.com/pywhatwgurl/pywhatwgurl)'s `URL` class, which is fully WHATWG URL Standard compatible.

## Basic Usage

```python
from zapros import URL

url = URL("https://api.example.com/users")
```

## URL Properties

```python
url = URL(
    "https://api.example.com:8080/users?page=1#section"
)

print(url.protocol)  # "https:"
print(url.hostname)  # "api.example.com"
print(url.port)  # "8080"
print(url.pathname)  # "/users"
print(url.search)  # "?page=1"
print(url.hash)  # "#section"
```

## Query Parameters

```python
url = URL("https://api.example.com/search")

url.search_params["q"] = "python"
url.search_params["limit"] = "10"

print(url.to_string())
```

## Using with Requests

```python
from zapros import AsyncClient, URL

url = URL("https://api.example.com/users")
url.search_params["page"] = "1"

async with AsyncClient() as client:
    response = await client.get(url.to_string())
```
