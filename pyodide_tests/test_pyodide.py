import glob

import pytest
from pytest_pyodide import run_in_pyodide
from pytest_pyodide.decorator import copy_files_to_pyodide

wheels = glob.glob("dist/*.whl")
if not wheels:
    raise FileNotFoundError("No wheel found in dist/. Run 'uv build' first.")
WHEEL_PATH = wheels[0]

# TODO: try to deduplicate these tests and use the ones in test_handlers/test_async_basic.py instead


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
def test_smoke(selenium):
    import zapros  # noqa: F401  just test that it imports without error


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_basic(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.get(f"{mock_server_url}/echo")
        assert response.status == 201
        assert "GET /echo HTTP/1.1" in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_json_body(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server_url}/echo",
            json={"key": "value", "num": 42},
        )
        assert response.status == 201
        assert "POST /echo HTTP/1.1" in response.text
        assert "content-type: application/json" in response.text
        assert '{"key":"value","num":42}' in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_json_nested(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server_url}/echo",
            json={"user": {"name": "alice", "age": 30}, "tags": ["a", "b"]},
        )
        assert response.status == 201
        assert '{"user":{"name":"alice","age":30},"tags":["a","b"]}' in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_form_body(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server_url}/echo",
            form={"username": "alice", "password": "secret"},
        )
        assert response.status == 201
        assert "content-type: application/x-www-form-urlencoded" in response.text
        assert "username=alice&password=secret" in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_form_url_encoding(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server_url}/echo",
            form={"message": "hello world"},
        )
        assert response.status == 201
        assert "message=hello+world" in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_bytes_body(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server_url}/echo",
            body=b"raw binary data",
        )
        assert response.status == 201
        assert "raw binary data" in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_query_params(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.get(
            f"{mock_server_url}/echo",
            params={"q": "hello", "page": "1"},
        )
        assert response.status == 201
        assert "GET /echo HTTP/1.1" in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_custom_headers(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.get(
            f"{mock_server_url}/echo",
            headers={
                "X-Custom-Header": "my-value",
                "Authorization": "Bearer token123",
            },
        )
        assert response.status == 201
        assert "x-custom-header: my-value" in response.text
        assert "authorization: Bearer token123" in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_put_method(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.put(
            f"{mock_server_url}/echo",
            json={"name": "updated"},
        )
        assert response.status == 201
        assert "PUT /echo HTTP/1.1" in response.text
        assert '{"name":"updated"}' in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_delete_method(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.request("DELETE", f"{mock_server_url}/echo")
        assert response.status == 201
        assert "DELETE /echo HTTP/1.1" in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_response_status(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.get(f"{mock_server_url}/echo")
        assert response.status == 201


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_stream_context_manager(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        async with client.stream("GET", f"{mock_server_url}/echo") as response:
            assert response.status == 201
            await response.aread()
            assert "GET /echo HTTP/1.1" in response.text


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_stream_iter_bytes(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        async with client.stream("GET", f"{mock_server_url}/echo") as response:
            chunks = []
            async for chunk in response.async_iter_bytes():
                chunks.append(chunk)
            assert response.status == 201
            assert b"GET /echo HTTP/1.1" in b"".join(chunks)


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_stream_json_body(selenium, mock_server_url):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{mock_server_url}/echo",
            json={"stream": True},
        ) as response:
            await response.aread()
            assert response.status == 201
            assert '{"stream":true}' in response.text


@pytest.mark.xfail(reason="browser fetch auto-decodes gzip, raw bytes aren't exposed")
@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_gzip_raw_bytes_unchanged(selenium, mock_server_url):
    import gzip

    from zapros import AsyncClient

    original = "hello from the server"

    async with AsyncClient() as client:
        async with client.stream("GET", f"{mock_server_url}/gzip", params={"data": original}) as response:
            chunks = []
            async for chunk in response.async_iter_raw():
                chunks.append(chunk)

    assert b"".join(chunks) == gzip.compress(original.encode())
