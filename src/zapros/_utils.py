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


def get_host_header_value(host: str, scheme: str, port: str) -> str:
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

    if is_target_https:
        return ((proxy_scheme, proxy_host, proxy_port, target_scheme, target_host, target_port), False)
    else:
        return ((proxy_scheme, proxy_host, proxy_port), True)
