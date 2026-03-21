# Query Parameters

Pass query parameters to the `params` argument. Zapros URL-encodes the values and appends them to the URL before sending the request. Special characters and spaces are percent-encoded automatically.

```python
from zapros import URLSearchParams

# plain mapping
params={"q": "hello world", "page": "1"}

# list value for repeated keys
params={"status": ["active", "pending"], "page": "1"}

# list of pairs
params=[["q", "hello world"], ["page", "1"]]

# URLSearchParams
params=URLSearchParams("q=hello+world&page=1")

# pre-encoded string
params="q=hello+world&page=1"
```

::: code-group

```python [Async]
from zapros import AsyncClient

async with AsyncClient() as client:
    response = await client.get(
        "https://httpbin.org/get",
        params={
            "q": "hello world",
            "page": "1",
        },
    )
    # Sends: GET /get?q=hello+world&page=1
```

```python [Sync]
from zapros import Client

with Client() as client:
    response = client.get(
        "https://httpbin.org/get",
        params={
            "q": "hello world",
            "page": "1",
        },
    )
    # Sends: GET /get?q=hello+world&page=1
```

:::

## Parameter Priority

When query parameters come from multiple sources, they are merged in this order (lowest to highest priority):

1. `default_params` set on the client
2. Query parameters in the URL string passed to `url=`
3. Parameters in the `params=` argument

Duplicate keys are overwritten by higher priority sources:

::: code-group

```python [Async]
async with AsyncClient(
    default_params={"version": "1"}
) as client:
    response = await client.get(
        "https://api.example.com/search?lang=en",
        params={"q": "zapros"},
    )
# Sends: GET /search?version=1&lang=en&q=zapros
```

```python [Sync]
with Client(default_params={"version": "1"}) as client:
    response = client.get(
        "https://api.example.com/search?lang=en",
        params={"q": "zapros"},
    )
# Sends: GET /search?version=1&lang=en&q=zapros
```

:::

When the same key appears in multiple sources, the highest priority value wins:

::: code-group

```python [Async]
response = await client.get(
    "https://api.example.com/items?tag=python",
    params={"tag": "http"},
)
# Sends: GET /items?tag=http
```

```python [Sync]
response = client.get(
    "https://api.example.com/items?tag=python",
    params={"tag": "http"},
)
# Sends: GET /items?tag=http
```

:::

## Using URL Objects

Zapros uses the `URL` class from [pywhatwgurl](https://github.com/pywhatwgurl/pywhatwgurl). You can build URLs with query parameters:

```python
from zapros import URL

url = URL("https://api.example.com/search")
url.search_params["q"] = "zapros"
url.search_params["limit"] = "10"

print(url)
```

Pass URL objects to requests by converting them to strings:

::: code-group

```python [Async]
from zapros import AsyncClient, URL

url = URL("https://api.example.com/users")
url.search_params["page"] = "2"

async with AsyncClient() as client:
    response = await client.get(url)
```

```python [Sync]
from zapros import Client, URL

url = URL("https://api.example.com/users")
url.search_params["page"] = "2"

with Client() as client:
    response = client.get(url)
```

:::
