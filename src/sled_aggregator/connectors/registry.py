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

    def inventory(self) -> list[dict[str, object]]:
        """Return canonical connectors and aliases without duplicating registry data."""
        grouped: dict[type[BaseConnector], list[str]] = {}
        for name, connector in self._connectors.items():
            grouped.setdefault(connector, []).append(name)
        return [
            {
                "canonical_name": connector.platform_family,
                "aliases": sorted(name for name in names if name != connector.platform_family),
                "implementation_module": connector.__module__,
                "jurisdictions": list(connector.jurisdictions),
                "public_read_only": connector.public_read_only,
            }
            for connector, names in sorted(
                grouped.items(), key=lambda item: item[0].platform_family
            )
        ]


connector_registry = ConnectorRegistry()

# Production connector registration lives here so API discovery works without
# requiring application startup side effects.
from sled_aggregator.connectors.bidnet_direct import BidNetDirectConnector  # noqa: E402
from sled_aggregator.connectors.cgi_advantage_vss import (  # noqa: E402
    CGIAdvantageVSSConnector,
)
from sled_aggregator.connectors.euna_bonfire import BonfireProcurementConnector  # noqa: E402
from sled_aggregator.connectors.euna_ionwave import EunaIonWaveConnector  # noqa: E402
from sled_aggregator.connectors.euna_openbids_demandstar import (  # noqa: E402
    EunaOpenBidsDemandStarConnector,
)
from sled_aggregator.connectors.eva import EVAConnector  # noqa: E402
from sled_aggregator.connectors.georgia_gpr import GeorgiaGPRConnector  # noqa: E402
from sled_aggregator.connectors.infotech import InfotechBidExpressConnector  # noqa: E402
from sled_aggregator.connectors.jaggaer_sciquest import JaggaerSciQuestConnector  # noqa: E402
from sled_aggregator.connectors.maryland_emma import MarylandEMMAConnector  # noqa: E402
from sled_aggregator.connectors.opengov_procurement import (  # noqa: E402
    OpenGovProcurementConnector,
)
from sled_aggregator.connectors.pennsylvania_emarketplace import (  # noqa: E402
    PennsylvaniaEMarketplaceConnector,
)
from sled_aggregator.connectors.peoplesoft import PeopleSoftSourcingConnector  # noqa: E402
from sled_aggregator.connectors.periscope import PeriscopeBuySpeedConnector  # noqa: E402
from sled_aggregator.connectors.planetbids import PlanetBidsConnector  # noqa: E402
from sled_aggregator.connectors.public_purchase import PublicPurchaseConnector  # noqa: E402
from sled_aggregator.connectors.rhode_island_rivip import RIVIPExternalConnector  # noqa: E402
from sled_aggregator.connectors.texas_esbd import TexasESBDConnector  # noqa: E402
from sled_aggregator.connectors.webprocure import WebProcureConnector  # noqa: E402

connector_registry.register(WebProcureConnector)
connector_registry.register(PeriscopeBuySpeedConnector)
connector_registry.register(InfotechBidExpressConnector)
connector_registry.register(PeopleSoftSourcingConnector)
connector_registry.register(EVAConnector)
connector_registry.register(TexasESBDConnector)
connector_registry.register(PennsylvaniaEMarketplaceConnector)
connector_registry.register(CGIAdvantageVSSConnector)
connector_registry.register(JaggaerSciQuestConnector)
connector_registry.register(OpenGovProcurementConnector)
connector_registry.register(BonfireProcurementConnector)
connector_registry.register(EunaIonWaveConnector)
connector_registry.register(EunaOpenBidsDemandStarConnector)
connector_registry.register(PlanetBidsConnector)
connector_registry.register(MarylandEMMAConnector)
connector_registry.register(GeorgiaGPRConnector)
connector_registry.register(BidNetDirectConnector)
connector_registry.register(PublicPurchaseConnector)
connector_registry.register(RIVIPExternalConnector)
for _alias in ("infotech/bidx", "bid-express", "bidx"):
    connector_registry.register_alias(_alias, InfotechBidExpressConnector)
for _alias in ("peoplesoft", "peoplesoft/supplier-portal", "california/cal-eprocure"):
    connector_registry.register_alias(_alias, PeopleSoftSourcingConnector)
for _alias in ("eva", "virginia-business-opportunities", "cgi/eva"):
    connector_registry.register_alias(_alias, EVAConnector)
for _alias in ("esbd", "texas-esbd", "texas-smartbuy-esbd"):
    connector_registry.register_alias(_alias, TexasESBDConnector)
for _alias in ("pa-emarketplace", "pennsylvania-emarketplace", "pa/emarketplace"):
    connector_registry.register_alias(_alias, PennsylvaniaEMarketplaceConnector)
for _alias in (
    "cgi/vss",
    "cgi-advantage",
    "cgi-advantage-vss",
    "advantage-vss",
    "maine/vss",
    "michigan/sigma-vss",
    "colorado/vss",
):
    connector_registry.register_alias(_alias, CGIAdvantageVSSConnector)
for _alias in (
    "jaggaer",
    "sciquest",
    "jaggaer-sciquest",
    "jaggaer/sourcing",
    "sciquest-sourcing",
    "jaggaer-public-event",
):
    connector_registry.register_alias(_alias, JaggaerSciQuestConnector)
for _alias in (
    "opengov",
    "opengov-procurement",
    "procurenow",
    "procurenow/opengov",
    "opengov-procurenow",
):
    connector_registry.register_alias(_alias, OpenGovProcurementConnector)
for _alias in (
    "bonfire",
    "bonfirehub",
    "euna-bonfire",
    "euna-procurement-bonfire",
    "bonfire-interactive",
):
    connector_registry.register_alias(_alias, BonfireProcurementConnector)

for _alias in (
    "ionwave",
    "ion-wave",
    "ionwave-technologies",
    "euna-ionwave",
    "euna-procurement-ionwave",
    "iwt",
):
    connector_registry.register_alias(_alias, EunaIonWaveConnector)

for _alias in (
    "demandstar",
    "demand-star",
    "euna-demandstar",
    "euna-openbids",
    "openbids",
    "euna/openbids",
    "euna-procurement-demandstar",
):
    connector_registry.register_alias(_alias, EunaOpenBidsDemandStarConnector)

for _alias in (
    "planet-bids",
    "planetbids-portal",
    "planetbids-vendor-portal",
    "pb-system",
    "pbsystem",
):
    connector_registry.register_alias(_alias, PlanetBidsConnector)

for _alias in (
    "maryland-emma",
    "emma-maryland",
    "emaryland-marketplace",
    "emaryland-marketplace-advantage",
    "md-emma",
):
    connector_registry.register_alias(_alias, MarylandEMMAConnector)

for _alias in (
    "georgia-gpr",
    "ga-gpr",
    "georgia-procurement-registry",
    "ga-procurement-registry",
    "gpr-georgia",
):
    connector_registry.register_alias(_alias, GeorgiaGPRConnector)

for _alias in (
    "bidnet",
    "bid-net-direct",
    "bidnetdirect",
    "bidnet-regional-purchasing-group",
):
    connector_registry.register_alias(_alias, BidNetDirectConnector)

for _alias in (
    "publicpurchase",
    "public-purchase-portal",
    "public-purchase-gems",
    "the-public-group-public-purchase",
):
    connector_registry.register_alias(_alias, PublicPurchaseConnector)

for _alias in (
    "ri-rivip-external",
    "rhode-island-rivip",
    "rivip-external",
    "ri-external-solicitations",
    "rhode-island-external-solicitations",
):
    connector_registry.register_alias(_alias, RIVIPExternalConnector)
