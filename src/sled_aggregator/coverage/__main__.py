import argparse
import json
from pathlib import Path

from .core import build_report, render, validate


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
    args = parser.parse_args(argv)
    issues = validate()
    errors = [x for x in issues if x.severity == "error"]
    if args.command == "validate":
        for issue in issues:
            print(json.dumps(issue.as_dict(), sort_keys=True))
        print(f"valid: 56 jurisdictions; {len(issues)} warning(s); {len(errors)} error(s)")
        return bool(errors)
    if errors:
        for issue in errors:
            print(json.dumps(issue.as_dict(), sort_keys=True))
        return 1
    result = build_report(getattr(args, "as_of", None))
    if args.command == "gaps":
        content = json.dumps(result["gap_analysis"], indent=2, sort_keys=True) + "\n"
    elif args.command == "recommend":
        content = json.dumps(result["prioritized_recommendations"], indent=2, sort_keys=True) + "\n"
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
