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
