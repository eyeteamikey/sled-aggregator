import unittest
from collections.abc import AsyncIterator

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.connectors.registry import ConnectorRegistry, connector_registry
from sled_aggregator.domain.models import RawOpportunity


class ExampleConnector(BaseConnector):
    platform_family = "Example"
    jurisdictions = ("Example State",)

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        if False:
            yield


class UnsafeConnector(ExampleConnector):
    platform_family = "unsafe"
    public_read_only = False


class ConnectorRegistryTests(unittest.TestCase):
    def test_webprocure_connector_is_registered(self) -> None:
        connector = connector_registry.get("webprocure/proactis")
        self.assertEqual(connector.platform_family, "webprocure/proactis")
        self.assertEqual(connector.jurisdictions, ("Connecticut", "Missouri", "Rhode Island"))

    def test_infotech_connector_and_aliases_are_registered(self) -> None:
        from sled_aggregator.connectors.infotech import InfotechBidExpressConnector

        for key in ("infotech/bid-express", "infotech/bidx", "bid-express", "bidx"):
            self.assertIs(connector_registry.get(key), InfotechBidExpressConnector)

    def test_periscope_connector_is_registered(self) -> None:
        connector = connector_registry.get("periscope/buyspeed")
        self.assertEqual(connector.platform_family, "periscope/buyspeed")
        self.assertIn("U.S. Virgin Islands", connector.jurisdictions)

    def test_peoplesoft_connector_and_aliases_are_registered(self) -> None:
        from sled_aggregator.connectors.peoplesoft import PeopleSoftSourcingConnector

        for key in (
            "oracle/peoplesoft-sourcing",
            "peoplesoft",
            "peoplesoft/supplier-portal",
            "california/cal-eprocure",
        ):
            self.assertIs(connector_registry.get(key), PeopleSoftSourcingConnector)

    def test_registers_and_describes_connector(self) -> None:
        registry = ConnectorRegistry()
        registry.register(ExampleConnector)
        self.assertIs(registry.get("example"), ExampleConnector)
        self.assertEqual(registry.describe()[0]["jurisdictions"], ["Example State"])

    def test_rejects_duplicate_connector(self) -> None:
        registry = ConnectorRegistry()
        registry.register(ExampleConnector)
        with self.assertRaises(ValueError):
            registry.register(ExampleConnector)

    def test_rejects_non_read_only_connector(self) -> None:
        registry = ConnectorRegistry()
        with self.assertRaises(ValueError):
            registry.register(UnsafeConnector)


if __name__ == "__main__":
    unittest.main()
