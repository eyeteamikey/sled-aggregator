import re
from pathlib import PurePath
from urllib.parse import unquote

from sled_aggregator.documents.types import FailureKind


def detect_media_type(prefix: bytes, *, filename: str | None = None) -> str:
    if prefix.startswith(b"%PDF-"):
        return "application/pdf"
    if prefix.startswith(b"PK\x03\x04"):
        return "application/zip"
    if prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/x-ole-storage"
    if prefix.startswith(b"{\\rtf"):
        return "application/rtf"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    text = prefix.lstrip().lower()
    if text.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "text/html"
    if text.startswith((b"<?xml", b"<rss", b"<feed")):
        return "application/xml"
    if b"\x00" not in prefix:
        if filename and PurePath(filename).suffix.casefold() == ".csv":
            return "text/csv"
        return "text/plain"
    return "application/octet-stream"


def classify_html(prefix: bytes) -> FailureKind | None:
    text = re.sub(r"\s+", " ", prefix.decode("utf-8", "replace").casefold())
    patterns = (
        (
            FailureKind.CAPTCHA,
            ("recaptcha", "hcaptcha", "captcha", "cf-chl-", "cloudflare challenge"),
        ),
        (
            FailureKind.REGISTRATION_REQUIRED,
            ("registration required", "register to respond", "respond now"),
        ),
        (
            FailureKind.LOGIN_REQUIRED,
            ("supplier sign in", "supplier login", "session expired", 'name="password"'),
        ),
        (FailureKind.RESTRICTED, ("access denied", "permission denied", "not authorized")),
        (FailureKind.NOT_FOUND, ("page not found", "404 not found")),
        (FailureKind.TRANSIENT, ("maintenance", "service unavailable", "temporarily unavailable")),
    )
    return next((kind for kind, words in patterns if any(word in text for word in words)), None)


def safe_filename(header: str | None, *, maximum: int = 255) -> str | None:
    if not header:
        return None
    extended = re.search(r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", header, re.I)
    regular = re.search(r'filename\s*=\s*(?:"([^"]*)"|([^;]+))', header, re.I)
    raw = (
        unquote(extended.group(1).strip().strip('"'))
        if extended
        else ((regular.group(1) or regular.group(2)).strip() if regular else "")
    )
    value = re.sub(r"[\x00-\x1f\x7f/\\]", "_", raw).strip(" .")
    if value in {"", ".", ".."}:
        return None
    return value[:maximum]
