from dataclasses import dataclass, field

from sled_aggregator.connectors.base import BaseConnector


@dataclass
class ConnectorRegistry:
    _connectors: dict[str, type[BaseConnector]] = field(default_factory=dict)

    def register(self, connector: type[BaseConnector]) -> None:
        name = connector.platform_family.strip().lower()
        if not name:
            raise ValueError("connector platform_family must not be blank")
        if name in self._connectors:
            raise ValueError(f"connector already registered: {name}")
        if not connector.public_read_only:
            raise ValueError("connectors must be public and read-only")
        self._connectors[name] = connector

    def register_alias(self, alias: str, connector: type[BaseConnector]) -> None:
        """Register an explicit family alias with the same safety checks as a connector."""
        name = alias.strip().lower()
        if not name:
            raise ValueError("connector alias must not be blank")
        if name in self._connectors:
            raise ValueError(f"connector already registered: {name}")
        if not connector.public_read_only:
            raise ValueError("connectors must be public and read-only")
        self._connectors[name] = connector

    def get(self, platform_family: str) -> type[BaseConnector]:
        key = platform_family.strip().lower()
        try:
            return self._connectors[key]
        except KeyError as exc:
            raise KeyError(f"unknown connector: {platform_family}") from exc

    def describe(self) -> list[dict[str, object]]:
        return [
            {
                "platform_family": name,
                "jurisdictions": list(connector.jurisdictions),
                "public_read_only": connector.public_read_only,
            }
            for name, connector in sorted(self._connectors.items())
        ]


connector_registry = ConnectorRegistry()

# Production connector registration lives here so API discovery works without
# requiring application startup side effects.
from sled_aggregator.connectors.eva import EVAConnector  # noqa: E402
from sled_aggregator.connectors.infotech import InfotechBidExpressConnector  # noqa: E402
from sled_aggregator.connectors.peoplesoft import PeopleSoftSourcingConnector  # noqa: E402
from sled_aggregator.connectors.periscope import PeriscopeBuySpeedConnector  # noqa: E402
from sled_aggregator.connectors.webprocure import WebProcureConnector  # noqa: E402

connector_registry.register(WebProcureConnector)
connector_registry.register(PeriscopeBuySpeedConnector)
connector_registry.register(InfotechBidExpressConnector)
connector_registry.register(PeopleSoftSourcingConnector)
connector_registry.register(EVAConnector)
for _alias in ("infotech/bidx", "bid-express", "bidx"):
    connector_registry.register_alias(_alias, InfotechBidExpressConnector)
for _alias in ("peoplesoft", "peoplesoft/supplier-portal", "california/cal-eprocure"):
    connector_registry.register_alias(_alias, PeopleSoftSourcingConnector)
for _alias in ("eva", "virginia-business-opportunities", "cgi/eva"):
    connector_registry.register_alias(_alias, EVAConnector)
