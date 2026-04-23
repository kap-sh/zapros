from pytest_pyodide import run_in_pyodide


@run_in_pyodide(packages=["zapros"])
def test_import_zapros(selenium):
    import zapros

    assert hasattr(zapros, "__version__")


@run_in_pyodide(packages=["zapros"])
def test_basic_get(selenium):
    from zapros import Client

    with Client() as client:
        response = client.get("https://httpbin.org/get")
        assert response.status == 200
