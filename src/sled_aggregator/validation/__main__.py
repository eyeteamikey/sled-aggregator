import argparse
import json
from pathlib import Path

from .harness import HarnessConfig, ValidationHarness, render_json, render_markdown


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bounded anonymous public-source validator")
    parser.add_argument("--source", action="append", required=True, help="Explicit registered source ID")
    parser.add_argument("--registry", type=Path, default=Path("data/coverage/sources.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--request-budget", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--rate-limit", type=float, default=1)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args(argv)
    records = json.loads(args.registry.read_text())
    sources = records["sources"] if isinstance(records, dict) else records
    by_id = {item["source_id"]: item for item in sources}
    missing = sorted(set(args.source) - by_id.keys())
    if missing:
        parser.error("unknown source ID(s): " + ", ".join(missing))
    config = HarnessConfig(args.request_budget, args.timeout, args.max_pages, args.max_results,
                           args.rate_limit, args.retries, dry_run=args.dry_run)
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


if __name__ == "__main__":
    raise SystemExit(main())
