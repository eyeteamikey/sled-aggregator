import argparse
import json
from pathlib import Path

from .core import (
    build_report,
    closeout_plan,
    generated_reports,
    render,
    report_drift,
    validate,
    write_generated_reports,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline nationwide SLED coverage audit")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    report = sub.add_parser("report")
    report.add_argument("--format", choices=("json", "csv", "markdown"), default="markdown")
    report.add_argument("--output", type=Path)
    report.add_argument("--as-of")
    sub.add_parser("gaps")
    sub.add_parser("recommend")
    sub.add_parser("metrics")
    for name in (
        "status",
        "matrix",
        "missing",
        "blocked",
        "documents",
        "queue",
        "closeout",
        "validation-tasks",
    ):
        sub.add_parser(name)
    regenerate = sub.add_parser("regenerate")
    regenerate.add_argument("--output", type=Path)
    check = sub.add_parser("check-reports")
    check.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    issues = validate()
    errors = [x for x in issues if x.severity == "error"]
    if args.command == "validate":
        for issue in issues:
            print(json.dumps(issue.as_dict(), sort_keys=True))
        print(f"valid: 56 jurisdictions; {len(issues)} warning(s); {len(errors)} error(s)")
        return bool(errors)
    if args.command == "regenerate":
        write_generated_reports(args.output)
        print("generated authoritative coverage reports")
        return 0
    if args.command == "check-reports":
        drift = report_drift(args.output)
        for name in drift:
            print(name)
        print(f"report drift: {len(drift)} file(s)")
        return bool(drift)
    if errors:
        for issue in errors:
            print(json.dumps(issue.as_dict(), sort_keys=True))
        return 1
    result = build_report(getattr(args, "as_of", None))
    if args.command in {"gaps", "missing"}:
        content = json.dumps(result["gap_analysis"], indent=2, sort_keys=True) + "\n"
        if args.command == "missing":
            content = generated_reports(result)["missing-coverage.md"]
    elif args.command == "metrics":
        from .validation_metrics import derive_metrics
        content = json.dumps(derive_metrics(), indent=2, sort_keys=True) + "\n"
    elif args.command in {"recommend", "queue"}:
        content = json.dumps(result["prioritized_recommendations"], indent=2, sort_keys=True) + "\n"
    elif args.command == "matrix":
        content = generated_reports(result)["capability-matrix.md"]
    elif args.command == "blocked":
        content = generated_reports(result)["blocked-sources.md"]
    elif args.command == "documents":
        content = generated_reports(result)["document-pipeline-readiness.md"]
    elif args.command == "status":
        content = json.dumps(result["summary"], indent=2, sort_keys=True) + "\n"
    elif args.command == "closeout":
        content = json.dumps(closeout_plan(result), indent=2, sort_keys=True) + "\n"
    elif args.command == "validation-tasks":
        content = json.dumps(
            closeout_plan(result)["validation_tasks"], indent=2, sort_keys=True
        ) + "\n"
    else:
        content = render(result, args.format)
    output = getattr(args, "output", None)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
