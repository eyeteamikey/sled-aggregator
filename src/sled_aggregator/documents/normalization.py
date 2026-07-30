import re
import unicodedata

from sled_aggregator.documents.extraction_types import ExtractionResult


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\x00", ""))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(c for c in value if c in "\n\t" or unicodedata.category(c) != "Cc")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class ExtractionNormalizer:
    def normalize(self, result: ExtractionResult, *, max_characters: int) -> ExtractionResult:
        cursor = 0
        pieces = []
        for sequence, block in enumerate(result.blocks):
            block.sequence = sequence
            block.normalized_text = normalize_text(block.raw_text)
            if not block.normalized_text:
                continue
            if cursor + len(block.normalized_text) > max_characters:
                result.warnings.append("maximum extracted character limit reached")
                result.state = result.state.COMPLETED_WITH_WARNINGS
                break
            block.character_start = cursor
            block.character_end = cursor + len(block.normalized_text)
            pieces.append(block.normalized_text)
            cursor = block.character_end + 2
        result.blocks = [block for block in result.blocks if block.normalized_text][: len(pieces)]
        result.full_text = "\n\n".join(pieces)
        return result
