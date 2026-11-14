#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Command-line entry point of the ledger."""
import argparse
import json
import logging
import sys

# Local imports
from cquota import config
from cquota import ingest
from cquota import limits
from cquota import report

LOGGING = {
    "handlers": [
        logging.StreamHandler(),
    ],
    "format":  "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s) %(message)s",
    "level":   logging.INFO,
    "datefmt": "%Y-%m-%d %H:%M:%S",
}
logging.basicConfig(**LOGGING)
logger = logging.getLogger(__name__)


def run_ingest_command(arguments: argparse.Namespace) -> None:
    if arguments.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    summary = ingest.run_ingest()
    logger.info(
        f"Read {summary['files_read']} of {summary['files_total']} transcripts, "
        f"{summary['responses_new']} new responses, {summary['responses_total']} in {config.DB_PATH} "
        f"({summary['seconds']:.2f})"
    )


def parse_week(text: str) -> int:
    """How many weeks back a --week value is: a number, or a name of the last two weeks."""
    if text in limits.WEEK_ALIASES:
        return limits.WEEK_ALIASES[text]
    if text.isascii() and text.isdigit() and int(text) <= limits.WEEK_LIMIT:
        return int(text)
    names = ", ".join(limits.WEEK_ALIASES)
    raise argparse.ArgumentTypeError(f"invalid week: '{text}' (weeks back from 0 to {limits.WEEK_LIMIT}, or one of {names})")


def run_report_command(arguments: argparse.Namespace) -> None:
    if arguments.weekly and (arguments.since or arguments.until or arguments.all):
        sys.exit("cquota report: error: --weekly covers one week, not --since, --until or --all")
    period, windows = limits.get_week_state(arguments.week or 0)
    if arguments.since or arguments.until:
        period = {"source": report.CUSTOM_SOURCE, "since_day": arguments.since, "until_day": arguments.until}
    elif arguments.all:
        period = {"source": "all"}
    elif arguments.weekly and arguments.week is None:
        period = limits.get_recent_period()
    period = limits.add_limit_rate(period, windows)
    by = "session" if arguments.sessions else arguments.by
    data = report.build_report_data(
        by, period, windows, arguments.project, arguments.limit, arguments.full_paths, arguments.weekly
    )
    if arguments.json or arguments.format == "json":
        sys.stdout.write(report.render_json(data))
    else:
        sys.stdout.write(report.render_table(data, arguments.usd))


def run_statusline_command(arguments: argparse.Namespace) -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    sys.stdout.write(limits.run_status_line(payload) + "\n")


def run_limits_command(arguments: argparse.Namespace) -> None:
    sys.stdout.write(limits.build_limits_report(arguments.full_paths, arguments.usd))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cquota",
        description="A local ledger of the tokens a Claude Code subscription spends.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"cquota {config.read_version()}")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser(
        "ingest", help="read what was appended to the transcripts since the previous run"
    )
    ingest_parser.add_argument("--quiet", action="store_true", help="log warnings only, for hooks")
    ingest_parser.set_defaults(handler=run_ingest_command)
    report_parser = commands.add_parser("report", help="show what was spent, grouped one way")
    report_parser.add_argument("--by", choices=sorted(report.GROUP_EXPRESSIONS), default="project")
    report_parser.add_argument("--since", metavar="YYYY-MM-DD", help="first local day to include")
    report_parser.add_argument("--until", metavar="YYYY-MM-DD", help="last local day to include")
    report_parser.add_argument("--project", metavar="TEXT", help="only projects whose path contains TEXT")
    report_parser.add_argument("--sessions", action="store_true", help="group by session, same as --by session")
    report_parser.add_argument(
        "--week", type=parse_week, metavar="N",
        help="subscription week to cover, as weeks back: 0 or this (default), 1 or last, 2 and so on",
    )
    report_parser.add_argument(
        "--weekly", action="store_true",
        help="add a column per day with its share of the period; covers the last 7 days unless --week is given",
    )
    report_parser.add_argument("--full-paths", action="store_true", help="show projects by full path")
    report_parser.add_argument("--usd", action="store_true", help="add the API-equivalent cost as the last column")
    report_parser.add_argument("--all", action="store_true", help="the whole history instead of a week")
    report_parser.add_argument("--format", choices=("table", "json"), default="table")
    report_parser.add_argument("--json", action="store_true", help="same as --format json")
    report_parser.add_argument("--limit", type=int, default=20, help="rows to show, 0 for all; the total covers all")
    report_parser.set_defaults(handler=run_report_command)
    statusline_parser = commands.add_parser(
        "statusline", help="status line command: record the subscription limits and print them"
    )
    statusline_parser.set_defaults(handler=run_statusline_command)
    limits_parser = commands.add_parser(
        "limits", help="show the current limit windows and their split by project"
    )
    limits_parser.add_argument("--full-paths", action="store_true", help="show projects by full path")
    limits_parser.add_argument("--usd", action="store_true", help="add the API-equivalent cost as the last column")
    limits_parser.set_defaults(handler=run_limits_command)
    return parser


def main():
    arguments = build_parser().parse_args()
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
