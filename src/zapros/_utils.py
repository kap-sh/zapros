from __future__ import annotations

from typing import TYPE_CHECKING

from pywhatwgurl import URL

if TYPE_CHECKING:
    from zapros._base_pool import PoolKey
    from zapros._models import Request

DEFAULT_PORTS = {
    "http": "80",
    "https": "443",
    "ws": "80",
    "wss": "443",
    "socks5": "1080",
    "socks5h": "1080",
}


def get_host_header_value(url: URL) -> str:
    host, scheme, port = url.hostname, url.protocol[:-1], url.port
    default_port = DEFAULT_PORTS.get(scheme.lower())
    if port == "" or port == default_port:
        return host
    return f"{host}:{port}"


def get_authority_value(host: str, port: str) -> str:
    if port == "":
        return host
    return f"{host}:{port}"


def get_port_or_default(url: URL) -> int:
    if url.port != "":
        return int(url.port)

    port = DEFAULT_PORTS.get(url.protocol[:-1])
    if port is None:
        raise ValueError(f"Unknown default port for protocol {url.protocol}")
    return int(port)


def get_pool_key(request: Request) -> tuple[PoolKey, bool]:
    target_scheme = request.url.protocol[:-1]
    target_host = request.url.hostname
    target_port = get_port_or_default(request.url)

    proxy_context = request.context.get("network", {}).get("proxy")
    proxy_url_value = proxy_context.get("url") if proxy_context else None

    if proxy_url_value is None:
        return ((target_scheme, target_host, target_port), False)

    proxy_url = URL(proxy_url_value) if isinstance(proxy_url_value, str) else proxy_url_value
    proxy_scheme = proxy_url.protocol[:-1]
    proxy_host = proxy_url.hostname
    proxy_port = get_port_or_default(proxy_url)

    is_target_https = target_scheme in ("https", "wss")
    # A SOCKS5 connection is a tunnel to one target as well, whatever the target's scheme.
    is_tunnel = is_target_https or proxy_scheme in ("socks5", "socks5h")

    if is_tunnel:
        # A tunnel is bound to the identity it was opened with: the proxy credentials are
        # sent once, and the TLS session is verified against one server hostname.
        return (
            (
                proxy_scheme,
                proxy_host,
                proxy_port,
                target_scheme,
                target_host,
                target_port,
                proxy_url.username,
                proxy_url.password,
                proxy_context.get("server_hostname") if proxy_context else None,
            ),
            False,
        )
    else:
        return ((proxy_scheme, proxy_host, proxy_port), True)
