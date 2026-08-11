"""Command line interface for bounded validation and HAR evidence workflows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .harness import HarnessConfig, ValidationHarness, render_json, render_markdown
from .toolkit import (
    CaptureConfig,
    analyze_har,
    approve_evidence,
    capture_artifact_paths,
    capture_manual,
    evidence_records,
    extract_fixture,
    import_har,
    ingest_evidence,
    load_source,
    sanitize_har,
    scan_artifact,
)


def _write(path: Path | None, value: object) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Safe anonymous HAR validation toolkit")
    root.add_argument("--registry", type=Path, default=Path("data/coverage/sources.json"))
    commands = root.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="launch a bounded visible browser capture")
    capture.add_argument("--source", required=True)
    capture.add_argument("--label", required=True)
    capture.add_argument("--workspace", type=Path, default=Path(".sled-validation"))
    capture.add_argument("--dry-run", action="store_true")
    capture.add_argument("--browser", choices=("chromium", "msedge", "chrome"), default="chromium")
    capture.add_argument(
        "--request-policy",
        choices=("observe", "first-party", "full"),
        default="full",
        help="controlled diagnosis: logging only, first-party enforcement, or full policy",
    )
    capture.add_argument(
        "--persistent-profile",
        action="store_true",
        help="use a clean source/label profile below .sled-validation instead of an ephemeral context",
    )
    capture.add_argument("--page-load-timeout", type=int, default=30)
    capture.add_argument("--action-timeout", type=int, default=30)
    capture.add_argument("--max-capture-duration", type=int, default=900)
    import_command = commands.add_parser(
        "import-har", help="copy, inventory, sanitize, and scan a manual HAR"
    )
    import_command.add_argument("--source", required=True)
    import_command.add_argument("--input", type=Path, required=True)
    import_command.add_argument("--workspace", type=Path, default=Path(".sled-validation"))
    sanitize = commands.add_parser("sanitize", help="sanitize a raw HAR without overwriting it")
    sanitize.add_argument("input", type=Path)
    sanitize.add_argument("output", type=Path)
    sanitize.add_argument("--source", required=True)
    sanitize.add_argument("--max-body-bytes", type=int, default=256_000)
    scan = commands.add_parser("scan", help="scan an artifact for sensitive values")
    scan.add_argument("artifact", type=Path)
    scan.add_argument("--output", type=Path)
    analyze = commands.add_parser("analyze", help="analyze a sanitized request contract")
    analyze.add_argument("artifact", type=Path)
    analyze.add_argument("--output", type=Path)
    report = commands.add_parser("report", help="generate compact capability evidence")
    report.add_argument("artifact", type=Path)
    report.add_argument("--analysis", type=Path, required=True)
    report.add_argument("--source", required=True)
    report.add_argument("--capture-id", required=True)
    report.add_argument("--output", type=Path)
    fixture = commands.add_parser(
        "extract-fixture", help="extract a reviewed minimal fixture candidate"
    )
    fixture.add_argument("artifact", type=Path)
    fixture.add_argument("output", type=Path)
    fixture.add_argument("--approved", action="store_true")
    approve = commands.add_parser("approve", help="record explicit reviewer approval")
    approve.add_argument("evidence", type=Path)
    approve.add_argument("findings", type=Path)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--capability", action="append", required=True)
    approve.add_argument("--output", type=Path, required=True)
    ingest = commands.add_parser("ingest", help="ingest approved evidence into coverage registry")
    ingest.add_argument("approval", type=Path)
    ingest.add_argument("--confirm", action="store_true")
    ingest.add_argument("--dry-run", action="store_true")
    return root


def _legacy_main(argv: list[str]) -> int:
    """Retain the PR #48 bounded-validator interface for existing automation."""
    legacy = argparse.ArgumentParser(description="Bounded anonymous public-source validator")
    legacy.add_argument("--source", action="append", required=True)
    legacy.add_argument("--registry", type=Path, default=Path("data/coverage/sources.json"))
    legacy.add_argument("--dry-run", action="store_true")
    legacy.add_argument("--request-budget", type=int, default=3)
    legacy.add_argument("--timeout", type=float, default=10)
    legacy.add_argument("--max-pages", type=int, default=1)
    legacy.add_argument("--max-results", type=int, default=10)
    legacy.add_argument("--rate-limit", type=float, default=1)
    legacy.add_argument("--retries", type=int, default=1)
    legacy.add_argument("--json-output", type=Path)
    legacy.add_argument("--markdown-output", type=Path)
    args = legacy.parse_args(argv)
    records = json.loads(args.registry.read_text())
    sources = records["sources"] if isinstance(records, dict) else records
    by_id = {item["source_id"]: item for item in sources}
    missing = sorted(set(args.source) - by_id.keys())
    if missing:
        legacy.error("unknown source ID(s): " + ", ".join(missing))
    config = HarnessConfig(
        args.request_budget,
        args.timeout,
        args.max_pages,
        args.max_results,
        args.rate_limit,
        args.retries,
        dry_run=args.dry_run,
    )
    results = [ValidationHarness(config).validate(by_id[source_id]) for source_id in args.source]
    json_text, markdown_text = render_json(results), render_markdown(results)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json_text)
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_text)
    if not args.json_output and not args.markdown_output:
        print(json_text, end="")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--source" in argv and not any(
        command in argv
        for command in (
            "capture",
            "sanitize",
            "scan",
            "analyze",
            "report",
            "extract-fixture",
            "approve",
            "ingest",
            "import-har",
        )
    ):
        return _legacy_main(argv)
    args = parser().parse_args(argv)
    try:
        if args.command == "capture":
            source = load_source(args.registry, args.source)
            config = CaptureConfig.from_registry(
                source,
                args.label,
                args.workspace,
                browser=args.browser,
                request_policy_mode=args.request_policy,
                profile_directory=(
                    args.workspace / "profiles" / args.source / args.label
                    if args.persistent_profile
                    else None
                ),
                navigation_timeout=args.page_load_timeout,
                action_timeout=args.action_timeout,
                max_duration=args.max_capture_duration,
            )
            config.validate(Path.cwd())
            if args.dry_run:
                _write(
                    None,
                    {
                        "dry_run": True,
                        "source_id": source["source_id"],
                        "starting_url": config.starting_url,
                        "allowed_hosts": config.allowed_hosts,
                        "browser": {
                            "requested_channel": config.browser,
                            "resolved_channel": (
                                "bundled-chromium" if config.browser == "chromium" else config.browser
                            ),
                            "version": "not launched during dry-run",
                            "headless": False,
                            "profile_type": (
                                "persistent" if config.profile_directory else "ephemeral"
                            ),
                            "request_policy_mode": config.request_policy_mode,
                        },
                        "maximum_capture_duration": config.max_duration,
                        "conditional_post_rules": [
                            {
                                "purpose": rule.purpose,
                                "hosts": rule.hosts,
                                "path_pattern": rule.path_pattern,
                            }
                            for rule in config.request_rules
                        ],
                        "prohibited_actions": "login, registration, upload, bid submission, mutation, CAPTCHA bypass",
                        "raw_output": str(config.output_directory / "raw" / f"{config.label}.har"),
                        "raw_har_warning": "Never commit raw HAR files.",
                    },
                )
            else:
                raw_har = capture_manual(config, Path.cwd())
                _write(None, capture_artifact_paths(config, raw_har))
        elif args.command == "import-har":
            load_source(args.registry, args.source)
            _write(None, import_har(args.input, args.workspace, args.source, Path.cwd()))
        elif args.command == "sanitize":
            _write(
                None,
                sanitize_har(
                    args.input, args.output, source_id=args.source, max_body=args.max_body_bytes
                ),
            )
        elif args.command == "scan":
            findings = [vars(x) for x in scan_artifact(args.artifact)]
            _write(args.output, findings)
            return 2 if any(x["severity"] == "high" for x in findings) else 0
        elif args.command == "analyze":
            _write(args.output, analyze_har(args.artifact))
        elif args.command == "report":
            source = load_source(args.registry, args.source)
            analysis = json.loads(args.analysis.read_text())
            audit = json.loads(
                args.artifact.with_suffix(args.artifact.suffix + ".audit.json").read_text()
            )
            _write(
                args.output,
                evidence_records(
                    analysis, audit["metadata"], str(args.artifact), source, args.capture_id
                ),
            )
        elif args.command == "extract-fixture":
            _write(None, extract_fixture(args.artifact, args.output, approved=args.approved))
        elif args.command == "approve":
            records = json.loads(args.evidence.read_text())
            findings = []
            from .toolkit import Finding

            findings = [Finding(**x) for x in json.loads(args.findings.read_text())]
            _write(
                args.output,
                approve_evidence(records, args.reviewer, set(args.capability), findings),
            )
        elif args.command == "ingest":
            _write(
                None,
                ingest_evidence(
                    json.loads(args.approval.read_text()),
                    args.registry,
                    confirm=args.confirm,
                    dry_run=args.dry_run,
                ),
            )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"validation error: {type(exc).__name__}: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
