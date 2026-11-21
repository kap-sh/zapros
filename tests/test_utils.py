from pywhatwgurl import URL

from zapros._models import Request
from zapros._utils import get_pool_key


def _request(url: str, proxy: str) -> Request:
    return Request(URL(url), "GET", context={"network": {"proxy": {"url": proxy}}})


def test_pool_key_for_socks5_proxy_includes_plain_http_target() -> None:
    key_a, full_url_a = get_pool_key(_request("http://a.example/", "socks5://proxy.local:1080"))
    key_b, full_url_b = get_pool_key(_request("http://b.example/", "socks5://proxy.local:1080"))

    assert key_a == ("socks5", "proxy.local", 1080, "http", "a.example", 80, "", "", None)
    assert key_a != key_b
    # A SOCKS5 tunnel talks to the origin directly, so the request line is not in absolute form.
    assert not full_url_a
    assert not full_url_b


def test_pool_key_for_http_proxy_shares_connections_between_plain_http_targets() -> None:
    key_a, full_url_a = get_pool_key(_request("http://a.example/", "http://proxy.local:8080"))
    key_b, _ = get_pool_key(_request("http://b.example/", "http://proxy.local:8080"))

    assert key_a == key_b == ("http", "proxy.local", 8080)
    assert full_url_a


def test_pool_key_for_tunnel_includes_proxy_credentials() -> None:
    tunnels = (
        ("http://a.example/", "socks5://{}proxy.local:1080"),
        ("https://a.example/", "http://{}proxy.local:8080"),
    )
    for target, proxy in tunnels:
        userinfos = ("", "alice:pw1@", "alice:pw2@", "bob:pw1@")
        keys = {get_pool_key(_request(target, proxy.format(userinfo)))[0] for userinfo in userinfos}

        assert len(keys) == 4


def test_pool_key_for_tunnel_includes_server_hostname_override() -> None:
    request = _request("https://a.example/", "http://proxy.local:8080")
    overridden = Request(
        URL("https://a.example/"),
        "GET",
        context={"network": {"proxy": {"url": "http://proxy.local:8080", "server_hostname": "localhost"}}},
    )

    assert get_pool_key(request)[0] != get_pool_key(overridden)[0]
