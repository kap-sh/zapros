import glob

from pytest_pyodide import run_in_pyodide
from pytest_pyodide.decorator import copy_files_to_pyodide

wheels = glob.glob("dist/*.whl")
if not wheels:
    raise FileNotFoundError("No wheel found in dist/. Run 'uv build' first.")
WHEEL_PATH = wheels[0]


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
def test_import_zapros(selenium):
    import zapros

    assert hasattr(zapros, "__version__")


@copy_files_to_pyodide(file_list=[(WHEEL_PATH, "/tmp/zapros.whl")], install_wheels=True)
@run_in_pyodide
def test_basic_get(selenium):
    from zapros import Client

    with Client() as client:
        response = client.get("https://httpbin.org/get")
        assert response.status == 200
