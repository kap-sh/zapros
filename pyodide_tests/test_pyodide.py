import glob

from pytest_pyodide import run_in_pyodide
from pytest_pyodide.decorator import copy_files_to_pyodide

wheels = glob.glob("dist/*.whl")
if not wheels:
    raise FileNotFoundError("No wheel found in dist/. Run 'uv build' first.")
WHEEL_PATH = wheels[0]


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
def test_smoke(selenium):
    import zapros  # noqa: F401  just test that it imports without error


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
async def test_basic_get(selenium):
    from zapros import AsyncClient

    async with AsyncClient() as client:
        response = await client.get("https://httpbin.org/get")
        assert response.status == 200
