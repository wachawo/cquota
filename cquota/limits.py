#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subscription limit windows: readings from the status line and their split by project."""
import sqlite3
import time
from datetime import datetime, timedelta, timezone

# Local imports
from cquota import db
from cquota import projects
from cquota import report

# Window key in the status line payload -> (label, length in seconds)
WINDOWS = {
    "five_hour": ("5h", 5 * 3600),
    "seven_day": ("7d", 7 * 86400),
}
WEEK_WINDOW = "seven_day"
# Name of a week on the command line -> how many weeks back it is
WEEK_ALIASES = {"this": 0, "current": 0, "last": 1, "previous": 1}
WEEK_NAMES = ("current", "previous")
# Weeks back a report may ask for: ten years, far past any ledger
WEEK_LIMIT = 520
RECENT_DAYS = 7
# Readings of one window may report its reset a few seconds apart.
RESET_TOLERANCE = 60
FULL_LIMIT = 100.0
LEDGER_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"
LEDGER_SECONDS_FORMAT = "%Y-%m-%dT%H:%M:%S"
LEDGER_SECONDS_LENGTH = 19
LOCAL_TIME_FORMAT = "%Y-%m-%d %H:%M"
NO_DATA_LINE = "limits unknown"
PROJECT_LIMIT = 10
PROJECT_WIDTH = 58

INSERT_READING = """
INSERT INTO limits (timestamp, window, used_percentage, resets_at, session_id, project)
VALUES (:timestamp, :window, :used_percentage, :resets_at, :session_id, :project)
"""

REFRESH_READING = "UPDATE limits SET timestamp = ?, session_id = ?, project = ? WHERE rowid = ?"

LATEST_READINGS = """
SELECT rowid, window, used_percentage, resets_at, timestamp, session_id FROM limits
WHERE rowid IN (SELECT max(rowid) FROM limits GROUP BY window)
"""

FINAL_READING = """
SELECT used_percentage FROM limits
WHERE window = ? AND abs(resets_at - ?) <= ?
ORDER BY rowid DESC LIMIT 1
"""

LAST_RESPONSE = "SELECT max(timestamp) FROM responses WHERE session_id = ? AND timestamp <= ?"


def format_ledger_timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime(LEDGER_TIMESTAMP_FORMAT)


def format_local_time(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime(LOCAL_TIME_FORMAT)


def format_local_day(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime(report.DAY_FORMAT)


def get_latest_readings(connection: sqlite3.Connection) -> dict[str, dict]:
    readings = {}
    for rowid, window, used_percentage, resets_at, timestamp, session_id in connection.execute(LATEST_READINGS):
        readings[window] = {
            "rowid": rowid, "used_percentage": used_percentage, "resets_at": resets_at,
            "timestamp": timestamp, "session_id": session_id,
        }
    return readings


def get_active_readings(connection: sqlite3.Connection) -> dict[str, dict]:
    """Latest reading of every window that has not reset yet."""
    now = time.time()
    readings = get_latest_readings(connection)
    return {window: reading for window, reading in readings.items() if reading["resets_at"] > now}


def get_reading_time(connection: sqlite3.Connection, session_id: str | None, recorded_at: float) -> float:
    """Moment a reading describes: the last API response its session had received.

    A session learns the limit from its API responses, so an idle one keeps
    showing the percentage of its last response however much later it is asked.
    """
    parameters = (session_id, format_ledger_timestamp(recorded_at))
    last_response = connection.execute(LAST_RESPONSE, parameters).fetchone()[0]
    if not last_response:
        return recorded_at
    parsed = datetime.strptime(last_response[:LEDGER_SECONDS_LENGTH], LEDGER_SECONDS_FORMAT)
    return parsed.replace(tzinfo=timezone.utc).timestamp()


def store_reading(connection: sqlite3.Connection, window: str, state: dict, payload: dict,
                  latest: dict | None) -> None:
    """Record one window of a status line payload unless it is older than what is stored.

    Within a window the percentage only grows, so a lower one comes from a
    session that has not heard from the API lately and is dropped. An equal one
    refreshes the stored reading when its session is the more recent of the two.
    """
    now = int(time.time())
    used_percentage = state["used_percentage"]
    resets_at = int(state["resets_at"])
    session_id = payload.get("session_id")
    workspace = payload.get("workspace") or {}
    project = projects.resolve_project(workspace.get("project_dir") or payload.get("cwd") or "")
    same_window = latest is not None and abs(latest["resets_at"] - resets_at) <= RESET_TOLERANCE
    if same_window and used_percentage < latest["used_percentage"]:
        return
    if same_window and used_percentage == latest["used_percentage"]:
        stored_time = get_reading_time(connection, latest["session_id"], latest["timestamp"])
        if get_reading_time(connection, session_id, now) > stored_time:
            connection.execute(REFRESH_READING, (now, session_id, project, latest["rowid"]))
        return
    connection.execute(INSERT_READING, {
        "timestamp": now, "window": window, "used_percentage": used_percentage,
        "resets_at": resets_at, "session_id": session_id, "project": project,
    })


def store_readings(connection: sqlite3.Connection, payload: dict) -> None:
    rate_limits = payload.get("rate_limits") or {}
    latest = get_latest_readings(connection)
    with connection:
        for window in WINDOWS:
            state = rate_limits.get(window)
            if not isinstance(state, dict) or state.get("used_percentage") is None or not state.get("resets_at"):
                continue
            store_reading(connection, window, state, payload, latest.get(window))


def render_status_line(readings: dict[str, dict]) -> str:
    parts = []
    for window, (label, length) in WINDOWS.items():
        if window in readings:
            parts.append(f"{label} {readings[window]['used_percentage']:.0f}%")
    return " - ".join(parts) if parts else NO_DATA_LINE


def run_status_line(payload: dict) -> str:
    """Store the limits a status line payload carries and return the line to show."""
    connection = db.get_connection()
    db.create_tables(connection)
    store_readings(connection, payload)
    readings = get_active_readings(connection)
    connection.close()
    return render_status_line(readings)


def get_cost(connection: sqlite3.Connection, since: float, until: float | None) -> float:
    """API-equivalent cost recorded on this machine between two moments."""
    where = "WHERE timestamp >= ?"
    parameters = [format_ledger_timestamp(since)]
    if until is not None:
        where += " AND timestamp <= ?"
        parameters.append(format_ledger_timestamp(until + 1))
    usage = report.fold_usage(report.fetch_usage(connection, "1", where, parameters))
    return usage[report.TOTAL_LABEL]["cost"]


def get_limit_rate(cost: float, used_percentage: float) -> float | None:
    """API-equivalent cost that one percent of a window stood for, when both are known."""
    if cost <= 0 or used_percentage <= 0:
        return None
    return round(cost / used_percentage, 4)


def describe_window(connection: sqlite3.Connection, window: str, reading: dict) -> dict:
    """A reading with the moment it describes and an estimate of the percentage by now.

    The estimate scales the reading by how much the cost recorded in the window
    grew since that moment. It is absent when nothing was recorded before it.
    """
    label, length = WINDOWS[window]
    window_start = reading["resets_at"] - length
    reading_time = get_reading_time(connection, reading["session_id"], reading["timestamp"])
    cost_then = get_cost(connection, window_start, reading_time)
    cost_now = get_cost(connection, window_start, None)
    estimate = None
    if cost_then > 0:
        estimate = round(min(reading["used_percentage"] * cost_now / cost_then, FULL_LIMIT), 1)
    return {
        "label":                label,
        "used_percentage":      reading["used_percentage"],
        "as_of":                format_local_time(reading_time),
        "estimated_percentage": estimate,
        "resets_at":            format_local_time(reading["resets_at"]),
        "window_start":         window_start,
        "usd_per_percent":      get_limit_rate(cost_now, estimate or reading["used_percentage"]),
    }


def describe_windows(connection: sqlite3.Connection, readings: dict[str, dict]) -> dict:
    return {window: describe_window(connection, window, readings[window]) for window in WINDOWS if window in readings}


def get_final_reading(connection: sqlite3.Connection, resets_at: float) -> float | None:
    """Last used percentage recorded for the weekly window that reset at the given moment."""
    row = connection.execute(FINAL_READING, (WEEK_WINDOW, resets_at, RESET_TOLERANCE)).fetchone()
    return row[0] if row else None


def format_week_source(weeks_ago: int, kind: str) -> str:
    if weeks_ago < len(WEEK_NAMES):
        return f"{WEEK_NAMES[weeks_ago]} {kind}"
    return f"{kind} {weeks_ago} weeks ago"


def get_week_bounds(window_start: float | None, weeks_ago: int) -> tuple[float, float | None]:
    """Start and end of the week a number of weeks back, the end absent for the current one.

    A subscription week is a fixed length of time counted from its window
    start; a calendar week runs between local midnights on Monday.
    """
    if window_start is not None:
        week_length = WINDOWS[WEEK_WINDOW][1]
        start = window_start - weeks_ago * week_length
        until = start + week_length
    else:
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        monday = midnight - timedelta(days=midnight.weekday(), weeks=weeks_ago)
        start = monday.timestamp()
        until = (monday + timedelta(weeks=1)).timestamp()
    return start, until if weeks_ago > 0 else None


def get_week_state(weeks_ago: int) -> tuple[dict, dict]:
    """The week a number of weeks back as a report period, and the current limit windows.

    A week is the weekly subscription window when its reading is known, so the
    report and the limit cover the same usage; otherwise the calendar week
    from Monday. The period carries the used percentage of its window when
    there is one: for the current week the estimate by now, else the reading.
    """
    connection = db.get_connection()
    db.create_tables(connection)
    windows = describe_windows(connection, get_active_readings(connection))
    week_window = windows.get(WEEK_WINDOW)
    kind = "subscription week" if week_window else "calendar week"
    start, until = get_week_bounds(week_window["window_start"] if week_window else None, weeks_ago)
    period = {"source": format_week_source(weeks_ago, kind), "limit_used": None}
    if week_window and until is None:
        period["limit_used"] = week_window["estimated_percentage"] or week_window["used_percentage"]
    if week_window and until is not None:
        period["limit_used"] = get_final_reading(connection, until)
    connection.close()
    if until is not None:
        period["until_timestamp"] = format_ledger_timestamp(until)
        period["until_local"] = format_local_time(until)
    period["since_timestamp"] = format_ledger_timestamp(start)
    period["since_local"] = format_local_time(start)
    period["first_day"] = format_local_day(start)
    period["last_day"] = format_local_day(time.time() if until is None else until - 1)
    return period, windows


def add_limit_rate(period: dict, windows: dict) -> dict:
    """Give a period without a limit reading the rate of the current week to estimate one with."""
    if period.get("limit_used") is None and WEEK_WINDOW in windows:
        period["limit_rate"] = windows[WEEK_WINDOW]["usd_per_percent"]
    return period


def get_recent_period() -> dict:
    """The last seven local days, today included, as a report period."""
    today = datetime.now()
    first_day = today - timedelta(days=RECENT_DAYS - 1)
    return {
        "source":    f"last {RECENT_DAYS} days",
        "since_day": first_day.strftime(report.DAY_FORMAT),
        "until_day": today.strftime(report.DAY_FORMAT),
    }


def format_window(window: dict) -> str:
    """One window in words: the reading, when it was true, the estimate by now, the reset."""
    text = f"{window['label']} window {window['used_percentage']:.1f}% used as of {window['as_of']}"
    if window["estimated_percentage"] is not None:
        text += f", about {window['estimated_percentage']:.1f}% now"
    return f"{text}, resets {window['resets_at']}"


def render_window(connection: sqlite3.Connection, window: dict, full_paths: bool, show_usd: bool) -> list[str]:
    """Split the used share of one window between projects by their API-equivalent cost."""
    lines = [format_window(window)]
    used_percentage = window["estimated_percentage"] or window["used_percentage"]
    where = "WHERE timestamp >= ?"
    parameters = [format_ledger_timestamp(window["window_start"])]
    entries = report.fold_usage(report.fetch_usage(connection, "project", where, parameters))
    total_cost = entries.pop(report.TOTAL_LABEL)["cost"]
    if total_cost <= 0:
        lines.append("  no usage recorded on this machine in this window")
        return lines
    header = f"  {'PROJECT':<{PROJECT_WIDTH}} {'WINDOW %':>9}"
    lines.append(header + (f" {'API USD':>10}" if show_usd else ""))
    ordered = sorted(entries.items(), key=lambda item: item[1]["cost"], reverse=True)
    names = {} if full_paths else projects.shorten_projects(list(entries))
    for project, entry in ordered[:PROJECT_LIMIT]:
        share = used_percentage * entry["cost"] / total_cost
        project_label = (names.get(project) or project or report.UNKNOWN_LABEL)[-PROJECT_WIDTH:]
        line = f"  {project_label:<{PROJECT_WIDTH}} {share:>8.1f}%"
        lines.append(line + (f" {entry['cost']:>10.2f}" if show_usd else ""))
    return lines


def build_limits_report(full_paths: bool, show_usd: bool) -> str:
    connection = db.get_connection()
    db.create_tables(connection)
    windows = describe_windows(connection, get_active_readings(connection))
    lines = []
    for window in windows.values():
        lines.extend(render_window(connection, window, full_paths, show_usd))
        lines.append("")
    connection.close()
    if not lines:
        return "No current limit reading. The status line records one after the first reply of a session.\n"
    lines.append("Both the figure for now and the split are estimates from the API-equivalent cost on this machine.")
    return "\n".join(lines) + "\n"


def main():
    pass


if __name__ == "__main__":
    main()
