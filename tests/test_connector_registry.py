import unittest
from collections.abc import AsyncIterator

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.connectors.registry import ConnectorRegistry
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

