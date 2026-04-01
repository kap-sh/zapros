import pytest
from pywhatwgurl import URL

from zapros import Request, Response
from zapros._handlers._mock import Mock as ZaprosMock, MockMiddleware, MockRouter
from zapros._handlers._proxy import ProxyMiddleware



def test_http_proxy_lowercase(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is not None
    assert str(proxy_url) == "http://proxy.local:8080/"



def test_http_proxy_uppercase(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.local:8080")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is not None
    assert str(proxy_url) == "http://proxy.local:8080/"



def test_https_proxy_lowercase(monkeypatch):
    monkeypatch.setenv("https_proxy", "http://proxy.local:8080")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("https://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is not None
    assert str(proxy_url) == "http://proxy.local:8080/"



def test_https_proxy_uppercase(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.local:8080")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("https://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is not None
    assert str(proxy_url) == "http://proxy.local:8080/"



def test_all_proxy_uppercase(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "http://proxy.local:8080")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is not None
    assert str(proxy_url) == "http://proxy.local:8080/"



def test_all_proxy_lowercase(monkeypatch):
    monkeypatch.setenv("all_proxy", "http://proxy.local:8080")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is not None
    assert str(proxy_url) == "http://proxy.local:8080/"



def test_scheme_specific_proxy_overrides_all_proxy(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "http://all-proxy.local:8080")
    monkeypatch.setenv("http_proxy", "http://http-proxy.local:8080")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is not None
    assert str(proxy_url) == "http://http-proxy.local:8080/"



def test_no_proxy_env(monkeypatch):
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {})
    assert proxy_url == {}



def test_no_proxy_exact_match(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")
    monkeypatch.setenv("NO_PROXY", "example.com")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is None



def test_no_proxy_lowercase(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")
    monkeypatch.setenv("no_proxy", "example.com")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is None



def test_no_proxy_wildcard(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")
    monkeypatch.setenv("NO_PROXY", "*")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is None



def test_no_proxy_subdomain_match(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")
    monkeypatch.setenv("NO_PROXY", ".example.com")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://sub.example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is None



def test_no_proxy_multiple_entries(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,example.com")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is None



def test_no_proxy_no_match(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")
    monkeypatch.setenv("NO_PROXY", "other.com,another.com")

    router = MockRouter()
    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert proxy_url is not None
    assert str(proxy_url) == "http://proxy.local:8080/"



def test_proxy_already_set_in_context(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")

    router = MockRouter()
    mock = ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    proxy_handler = ProxyMiddleware(handler)

    request = Request(URL("http://example.com/path"), "GET")
    request.context["network"] = {"proxy": {"url": URL("http://custom-proxy.local:9090")}}

    response = proxy_handler.handle(request)

    assert response.status == 200
    proxy_url = request.context.get("network", {}).get("proxy", {}).get("url")
    assert str(proxy_url) == "http://custom-proxy.local:9090/"
    mock.verify()
