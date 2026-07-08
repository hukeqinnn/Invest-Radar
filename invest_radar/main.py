from __future__ import annotations

import argparse
import sys

from .config import DEFAULT_CONFIG, load_config
from .crawler import llm_config_from_app, process_item, run, summarize_existing_with_llm
from .llm_summary import list_openai_models
from .store import connect, init_db, latest_items


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to sources.toml",
    )
    parser = argparse.ArgumentParser(prog="invest-radar", parents=[parent])

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "run",
        parents=[parent],
        help="Fetch RSS sources, summarize, and write daily report",
    )
    subparsers.add_parser(
        "init-db",
        parents=[parent],
        help="Initialize local SQLite database",
    )

    latest = subparsers.add_parser(
        "latest",
        parents=[parent],
        help="Print latest stored items",
    )
    latest.add_argument("--limit", type=int, default=10)

    llm_backfill = subparsers.add_parser(
        "llm-backfill",
        parents=[parent],
        help="Manually summarize existing transcripts with LLM",
    )
    llm_backfill.add_argument("--limit", type=int, default=1)

    process_item_parser = subparsers.add_parser(
        "process-item",
        parents=[parent],
        help="Download, transcribe, summarize, and report one stored item",
    )
    process_item_parser.add_argument("--id", type=int, required=True, help="Stored item id")

    subparsers.add_parser(
        "list-models",
        parents=[parent],
        help="List OpenAI models visible to the saved API key",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"
    config = load_config(args.config)

    if command == "init-db":
        conn = connect(config.settings.database)
        init_db(conn)
        conn.close()
        print(f"Initialized database: {config.settings.database}")
        return 0

    if command == "latest":
        conn = connect(config.settings.database)
        init_db(conn)
        for row in latest_items(conn, args.limit):
            print(f"{row['first_seen_at']} | {row['source_name']} | {row['title']}")
        conn.close()
        return 0

    if command == "llm-backfill":
        result = summarize_existing_with_llm(config, limit=args.limit)
        print(f"LLM summarized items: {result.summarized_count}")
        for path in result.summary_paths:
            print(f"Summary: {path}")
        if result.errors:
            print("Errors:")
            for error in result.errors:
                print(f"- {error}")
            return 1
        return 0

    if command == "list-models":
        models = list_openai_models(llm_config_from_app(config))
        for model in models:
            print(model)
        return 0

    if command == "process-item":
        result = process_item(config, args.id)
        print(f"Transcribed items: {result.transcribed_count}")
        print(f"LLM summarized items: {result.llm_summarized_count}")
        print(f"Summarized items: {result.summarized_count}")
        print(f"Report: {result.report_path}")
        if result.errors:
            print("Errors:")
            for error in result.errors:
                print(f"- {error}")
            return 1
        return 0

    if command == "run":
        result = run(config)
        print(f"New items: {result.new_count}")
        print(f"Transcribed items: {result.transcribed_count}")
        print(f"LLM summarized items: {result.llm_summarized_count}")
        print(f"Summarized items: {result.summarized_count}")
        print(f"Report: {result.report_path}")
        if result.errors:
            print("Errors:")
            for error in result.errors:
                print(f"- {error}")
            return 1
        return 0

    parser.error(f"Unknown command: {command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
