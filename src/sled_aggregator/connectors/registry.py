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

