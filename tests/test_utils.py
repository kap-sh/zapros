from pywhatwgurl import URL

from zapros._models import Request
from zapros._utils import get_pool_key


def _request(url: str, proxy: str) -> Request:
    return Request(URL(url), "GET", context={"network": {"proxy": {"url": proxy}}})


def test_pool_key_for_socks5_proxy_includes_plain_http_target() -> None:
    key_a, full_url_a = get_pool_key(_request("http://a.example/", "socks5://proxy.local:1080"))
    key_b, full_url_b = get_pool_key(_request("http://b.example/", "socks5://proxy.local:1080"))

    assert key_a == ("socks5", "proxy.local", 1080, "http", "a.example", 80)
    assert key_a != key_b
    # A SOCKS5 tunnel talks to the origin directly, so the request line is not in absolute form.
    assert not full_url_a
    assert not full_url_b


def test_pool_key_for_http_proxy_shares_connections_between_plain_http_targets() -> None:
    key_a, full_url_a = get_pool_key(_request("http://a.example/", "http://proxy.local:8080"))
    key_b, _ = get_pool_key(_request("http://b.example/", "http://proxy.local:8080"))

    assert key_a == key_b == ("http", "proxy.local", 8080)
    assert full_url_a
