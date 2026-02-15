# Browser

Zapros supports browser runtimes through **Pyodide** and uses the browser's native **Fetch API** under the hood if the client was created in a browser environment or `AsyncPyodideHandler` is explicitly specified.

## Usage

```python
from zapros import Client

client = Client()
response = await client.get("https://api.example.com/data")
```

The `AsyncPyodideHandler` handles all the network I/O using the browser's Fetch API, supporting:

- All standard HTTP methods
- Request headers and bodies
- Response streaming
- Timeouts (total, connect, read, write)
- AbortController for request cancellation

