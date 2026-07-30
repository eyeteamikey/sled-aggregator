import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OcrOutput:
    text: str
    confidence: float | None = None


class OcrProvider(Protocol):
    @property
    def available(self) -> bool: ...
    @property
    def version(self) -> str | None: ...
    def recognize(self, image: Path, *, language: str, timeout: int) -> OcrOutput: ...


class TesseractOcrProvider:
    """Optional CLI adapter. Arguments are fixed and shell interpolation is never used."""

    @property
    def available(self) -> bool:
        return shutil.which("tesseract") is not None

    @property
    def version(self) -> str | None:
        if not self.available:
            return None
        result = subprocess.run(
            ["tesseract", "--version"], capture_output=True, text=True, timeout=5, check=False
        )
        return result.stdout.splitlines()[0][:100] if result.stdout else None

    def recognize(self, image: Path, *, language: str, timeout: int) -> OcrOutput:
        if not self.available:
            raise RuntimeError("Tesseract OCR is unavailable")
        result = subprocess.run(
            ["tesseract", str(image), "stdout", "-l", language],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Tesseract OCR failed")
        return OcrOutput(result.stdout)


@dataclass(frozen=True, slots=True)
class OcrDecision:
    decision: str
    meaningful_characters: int
    word_count: int
    replacement_ratio: float


class OcrDecisionPolicy:
    def __init__(
        self, *, minimum_characters: int, minimum_words: int, maximum_replacement_ratio: float
    ) -> None:
        self.minimum_characters = minimum_characters
        self.minimum_words = minimum_words
        self.maximum_replacement_ratio = maximum_replacement_ratio

    def decide(
        self, text: str, *, has_substantial_image: bool, is_blank: bool = False
    ) -> OcrDecision:
        meaningful = sum(char.isalnum() for char in text)
        words = len(text.split())
        ratio = text.count("\ufffd") / max(len(text), 1)
        usable = (
            meaningful >= self.minimum_characters
            and words >= self.minimum_words
            and ratio <= self.maximum_replacement_ratio
        )
        if usable:
            decision = "native_text"
        elif is_blank or (not text.strip() and not has_substantial_image):
            decision = "blank"
        elif has_substantial_image:
            decision = "OCR_required"
        else:
            decision = "failed"
        return OcrDecision(decision, meaningful, words, ratio)
