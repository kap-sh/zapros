# Browser

Zapros supports browser runtimes through **Pyodide** and uses the browser's native **Fetch API** under the hood when the client is created in a browser environment or when `AsyncPyodideHandler` is explicitly specified.

## Try it out in your browser

You can try Zapros in your browser's developer tools console. For a better experience, go to [PlayCode](https://playcode.io/python-template), add the `zapros>=0.8.0` package, and use the IDE to write and run your code.

Zapros automatically detects when it's running in a browser environment and uses the appropriate handler, so you can simply create a client and make requests as you normally would:

```python
import zapros

async with zapros.AsyncClient() as client:
  # make a request to a CORS-free endpoint
  response = await client.get("https://httpbin.org/get")
  print(response.json)
```

Note that using `await` at the top level is supported in Pyodide.

You can also explicitly specify the `AsyncPyodideHandler` if you prefer:

```python
from zapros import AsyncClient, AsyncPyodideHandler

async with AsyncClient(handler=AsyncPyodideHandler()) as client:
  response = await client.get("https://httpbin.org/get")
  print(response.json)
```

Note that some built-in features won't work in a browser environment, such as [caching](caching.md) and [cassettes](cassettes.md), since they rely on file system access. We're actively working on bringing these features to the browser as well, so stay tuned!