"""Pure, network-free URL validation and canonicalization for document identity."""

from ipaddress import ip_address
from posixpath import normpath
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UnsafeDocumentUrl(ValueError):
    pass


_TRANSIENT_PARAMETERS = frozenset({"jsessionid", "phpsessid", "session", "sessionid", "sid"})


def canonicalize_document_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeDocumentUrl("malformed URL") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise UnsafeDocumentUrl("only HTTP(S) URLs with a host are supported")
    if parts.username is not None or parts.password is not None:
        raise UnsafeDocumentUrl("embedded credentials are prohibited")
    hostname = parts.hostname.lower().rstrip(".")
    if hostname in {"localhost", "metadata.google.internal"}:
        raise UnsafeDocumentUrl("local and metadata hosts are prohibited")
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise UnsafeDocumentUrl("non-public literal IP address is prohibited")
    default_port = (parts.scheme.lower() == "http" and port == 80) or (
        parts.scheme.lower() == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = normpath(parts.path or "/")
    if parts.path.endswith("/") and not path.endswith("/"):
        path += "/"
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRANSIENT_PARAMETERS
    )
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))
