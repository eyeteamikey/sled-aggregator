import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

from sled_aggregator.documents.types import DownloadFailure, FailureKind

Resolver = Callable[[str], list[str]]
_AMBIGUOUS_IP = re.compile(r"^(?:0x[0-9a-f]+|0[0-7]+|\d+)$", re.I)
_METADATA_HOSTS = {"metadata.google.internal", "metadata.azure.internal"}


def _resolve(host: str) -> list[str]:
    return list({item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})


class DownloadPolicy:
    """Validates every URL and DNS answer; httpx cannot pin the checked answer."""

    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...] = (),
        allowed_ports: tuple[int, ...] = (80, 443),
        resolver: Resolver = _resolve,
        allow_http_downgrade: bool = False,
    ) -> None:
        self.allowed_hosts = tuple(host.casefold().rstrip(".") for host in allowed_hosts)
        self.allowed_ports = allowed_ports
        self.resolver = resolver
        self.allow_http_downgrade = allow_http_downgrade

    def validate(
        self, url: str, *, original_host: str | None = None, previous_scheme: str | None = None
    ) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DownloadFailure(FailureKind.UNSAFE_URL, "unsupported document URL")
        if parsed.username or parsed.password:
            raise DownloadFailure(FailureKind.UNSAFE_URL, "credentials in document URL")
        host = parsed.hostname.casefold().rstrip(".")
        if host == "localhost" or host.endswith(".localhost") or host in _METADATA_HOSTS:
            raise DownloadFailure(FailureKind.UNSAFE_URL, "blocked document host")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in self.allowed_ports:
            raise DownloadFailure(FailureKind.UNSAFE_URL, "blocked document port")
        if previous_scheme == "https" and parsed.scheme == "http" and not self.allow_http_downgrade:
            raise DownloadFailure(FailureKind.UNSAFE_URL, "HTTPS downgrade blocked")
        if original_host and host != original_host and not self._host_allowed(host):
            raise DownloadFailure(FailureKind.UNSAFE_URL, "cross-host redirect blocked")
        if self.allowed_hosts and not self._host_allowed(host):
            raise DownloadFailure(FailureKind.UNSAFE_URL, "document host is not allowlisted")
        if _AMBIGUOUS_IP.fullmatch(host):
            raise DownloadFailure(FailureKind.UNSAFE_URL, "ambiguous IP encoding blocked")
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            try:
                addresses = self.resolver(host)
            except OSError as exc:
                raise DownloadFailure(
                    FailureKind.TRANSIENT, "document host resolution failed"
                ) from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            mapped = getattr(ip, "ipv4_mapped", None)
            if mapped:
                ip = mapped
            if not ip.is_global:
                raise DownloadFailure(FailureKind.UNSAFE_URL, "non-public document address blocked")
        return host

    def _host_allowed(self, host: str) -> bool:
        return any(
            host == allowed or host.endswith("." + allowed) for allowed in self.allowed_hosts
        )
