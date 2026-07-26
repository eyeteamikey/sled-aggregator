import hashlib
import re

from sled_aggregator.domain.models import CanonicalOpportunity, RawOpportunity


class OpportunityNormalizer:
    def normalize(self, raw: RawOpportunity) -> CanonicalOpportunity:
        key_material = "|".join(
            (
                self._slug(raw.source.platform_family),
                self._slug(raw.source.jurisdiction),
                self._slug(raw.source.source_id),
            )
        )
        canonical_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
        return CanonicalOpportunity(
            canonical_key=canonical_key,
            source=raw.source,
            title=self._clean(raw.title),
            agency=self._clean(raw.agency),
            description=self._clean(raw.description) if raw.description else None,
            solicitation_number=(
                self._clean(raw.solicitation_number) if raw.solicitation_number else None
            ),
            status=raw.status,
            posted_at=raw.posted_at,
            due_at=raw.due_at,
            categories=sorted({self._clean(item) for item in raw.categories if item.strip()}),
            raw_payload=raw.raw_payload,
        )

    @staticmethod
    def _clean(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
