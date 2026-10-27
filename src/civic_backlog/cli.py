import argparse
import json
import sys
from . import __version__
from .ingest import ingest, list_snapshots, read_manifest, snapshot, connect
from .model import InputError
from .analysis import analyze
from .demo import generate, run_demo
from .fetch import fetch_snapshot
from .exports import export_report
from .dashboard import serve
from .benchmark import benchmark


def main():
    parser = argparse.ArgumentParser(prog="civic", description="Snapshot-based civic backlog analysis")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    command = commands.add_parser("ingest", help="Import a bounded local JSON/CSV snapshot")
    command.add_argument("input")
    command.add_argument("--manifest", required=True)
    command.add_argument("--db", required=True)
    command.add_argument("--skip-invalid", action="store_true")
    command = commands.add_parser("snapshots", help="List up to 100 snapshot identities")
    command.add_argument("--db", required=True)
    command = commands.add_parser("info", help="Show snapshot provenance and quality counts")
    command.add_argument("--db", required=True)
    command.add_argument("--snapshot", required=True)
    command = commands.add_parser("analyze", help="Compute explicit-denominator metrics for one snapshot")
    command.add_argument("--db", required=True)
    command.add_argument("--snapshot", required=True)
    command.add_argument("--allow-partial", action="store_true")
    command = commands.add_parser("generate", help="Write a fresh synthetic fixture")
    command.add_argument("--out", required=True)
    commands.add_parser("demo", help="Verify a temporary synthetic import and analysis")
    command = commands.add_parser("fetch", help="Capture a bounded one-agency NYC311 cohort")
    command.add_argument("--out", required=True)
    command.add_argument("--start", required=True, help="Inclusive creation date, YYYY-MM-DD")
    command.add_argument("--end", required=True, help="Exclusive creation date, YYYY-MM-DD")
    command.add_argument("--agency", required=True)
    command.add_argument("--max-rows", type=int, default=20000)
    command.add_argument("--page-size", type=int, default=1000)
    command = commands.add_parser("export", help="Write an exclusive aggregate JSON/CSV report")
    command.add_argument("--db", required=True)
    command.add_argument("--snapshot", required=True)
    command.add_argument("--out", required=True)
    command.add_argument("--format", choices=("json", "csv"), required=True)
    command.add_argument("--allow-partial", action="store_true")
    command = commands.add_parser("serve", help="View one aggregate snapshot on loopback")
    command.add_argument("--db", required=True)
    command.add_argument("--snapshot", required=True)
    command.add_argument("--port", type=int, default=0)
    command.add_argument("--allow-partial", action="store_true")
    command = commands.add_parser("benchmark", help="Measure a bounded synthetic import/query workload")
    command.add_argument("--rows", type=int, default=1000)
    command.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    try:
        if args.command == "serve":
            serve(args.db, args.snapshot, port=args.port, allow_partial=args.allow_partial)
            return
        elif args.command == "benchmark":
            result = benchmark(args.rows, args.repeats)
        elif args.command == "ingest":
            result = ingest(args.input, read_manifest(args.manifest), args.db, skip_invalid=args.skip_invalid)
        elif args.command == "snapshots":
            result = list_snapshots(args.db)
        elif args.command == "info":
            connection = connect(args.db, read_only=True)
            try: result = snapshot(connection, args.snapshot)
            finally: connection.close()
        elif args.command == "analyze":
            result = analyze(args.db, args.snapshot, allow_partial=args.allow_partial)
        elif args.command == "generate":
            result = generate(args.out)
        elif args.command == "demo":
            result = run_demo()
        elif args.command == "fetch":
            result = fetch_snapshot(args.out, args.start, args.end, args.agency, row_limit=args.max_rows, page_size=args.page_size)
        elif args.command == "export":
            result = export_report(args.db, args.snapshot, args.out, args.format, allow_partial=args.allow_partial)
        else:
            parser.print_help(); return
        print(json.dumps(result, indent=2, allow_nan=False))
    except InputError as error:
        print(f"civic: {error}", file=sys.stderr); raise SystemExit(2) from None
    except (OSError, ValueError):
        print("civic: operation_failed", file=sys.stderr); raise SystemExit(2) from None


if __name__ == "__main__": main()
