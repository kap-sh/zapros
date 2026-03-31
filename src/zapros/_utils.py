from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zapros._base_pool import PoolKey
    from zapros._models import Request

DEFAULT_PORTS = {
    "http": "80",
    "https": "443",
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


def get_pool_key(
    request: Request,
    target_scheme: str,
    target_host: str,
    target_port: int,
) -> tuple[PoolKey, bool]:
    proxy_context = request.context.get("network", {}).get("proxy")
    proxy_url_value = proxy_context.get("url") if proxy_context else None

    if proxy_url_value is None:
        return ((target_scheme, target_host, target_port), False)

    from pywhatwgurl import URL

    proxy_url = URL(proxy_url_value) if isinstance(proxy_url_value, str) else proxy_url_value
    proxy_scheme = proxy_url.protocol[:-1]
    proxy_host = proxy_url.hostname
    proxy_port = int(proxy_url.port) if proxy_url.port != "" else (443 if proxy_scheme == "https" else 80)

    is_target_https = target_scheme in ("https", "wss")

    if is_target_https:
        return ((proxy_scheme, proxy_host, proxy_port, target_scheme, target_host, target_port), False)
    else:
        return ((proxy_scheme, proxy_host, proxy_port), True)
