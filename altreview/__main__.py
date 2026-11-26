"""Run with python -m altreview."""
import argparse
import json
from pathlib import Path

from . import capture, demo, storage
from .facts import summary
from .report import html_report


def main():
    parser = argparse.ArgumentParser(description="Capture image accessibility evidence from one page.")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Inspect a public URL")
    scan.add_argument("url")
    scan.add_argument("--captures", type=int, default=12)
    sub.add_parser("demo", help="Run a self-contained demonstration")
    export = sub.add_parser("export", help="Export a saved scan as self-contained HTML")
    export.add_argument("scan", type=Path)
    export.add_argument("output", type=Path)
    sub.add_parser("benchmark", help="Run the pinned W3C image-name regression fixtures")
    args = parser.parse_args()
    if args.command == "benchmark":
        from .benchmark import evaluate
        print(json.dumps(evaluate(), indent=2))
    elif args.command == "export":
        args.output.write_text(html_report(storage.load(args.scan)), encoding="utf-8")
        print(args.output)
    else:
        run = capture.scan(args.url, args.captures) if args.command == "scan" else capture.scan(markup=demo.page(), capture_limit=12)
        print(json.dumps(summary(run), indent=2))
        print(storage.run_directory(run) / "scan.json")
        for row in run["images"]:
            for finding in row["findings"]:
                print(row["id"], finding["check"], finding["summary"])


if __name__ == "__main__":
    main()
