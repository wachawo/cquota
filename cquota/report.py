#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate the ledger by project, session, day or model."""
import json
import os
import sqlite3
from datetime import datetime, timedelta

# Local imports
from cquota import db
from cquota import prices
from cquota import projects

# Report grouping -> SQL expression. Days follow the local timezone.
GROUP_EXPRESSIONS = {
    "project": "project",
    "session": "session_id",
    "day":     "date(timestamp, 'localtime')",
    "model":   "model",
}
TOKEN_COLUMNS = tuple(prices.PRICED_COLUMNS)
LABEL_WIDTH = 50
SESSION_ID_WIDTH = 8
TOTAL_LABEL = "TOTAL"
UNKNOWN_LABEL = "(unknown)"
NO_VALUE = "-"
UNPRICED_MARK = "*"
DAY_FORMAT = "%Y-%m-%d"
CUSTOM_SOURCE = "custom"
WEEKDAY_LABELS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def build_filter(period: dict, project: str | None) -> tuple[str, list]:
    """WHERE clause for a period and a project path substring.

    A period is either a moment to start from, or an inclusive range of local days.
    """
    since = period.get("since_day")
    until = period.get("until_day")
    conditions = []
    parameters = []
    if period.get("since_timestamp"):
        conditions.append("timestamp >= ?")
        parameters.append(period["since_timestamp"])
    if period.get("until_timestamp"):
        conditions.append("timestamp < ?")
        parameters.append(period["until_timestamp"])
    if since:
        conditions.append("date(timestamp, 'localtime') >= ?")
        parameters.append(since)
    if until:
        conditions.append("date(timestamp, 'localtime') <= ?")
        parameters.append(until)
    if project:
        conditions.append("instr(project, ?) > 0")
        parameters.append(project)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return where, parameters


def fetch_usage(connection: sqlite3.Connection, expression: str, where: str, parameters: list) -> list:
    sums = ", ".join(f"sum({column})" for column in TOKEN_COLUMNS)
    query = f"SELECT {expression}, model, {sums} FROM responses {where} GROUP BY 1, 2"
    return connection.execute(query, parameters).fetchall()


def fetch_session_counts(connection: sqlite3.Connection, expression: str, where: str, parameters: list) -> dict:
    query = f"SELECT {expression}, count(DISTINCT session_id) FROM responses {where} GROUP BY 1"
    counts = dict(connection.execute(query, parameters).fetchall())
    total_query = f"SELECT count(DISTINCT session_id) FROM responses {where}"
    counts[TOTAL_LABEL] = connection.execute(total_query, parameters).fetchone()[0]
    return counts


def fetch_session_labels(connection: sqlite3.Connection, where: str, parameters: list) -> dict:
    """Label every session with its short id, its project and its title."""
    query = (
        "SELECT session_id, project, sum(output_tokens), custom_title, ai_title "
        f"FROM responses LEFT JOIN sessions USING (session_id) {where} GROUP BY 1, 2 ORDER BY 3"
    )
    labels = {}
    for session_id, project, output_tokens, custom_title, ai_title in connection.execute(query, parameters):
        title = custom_title or ai_title or ""
        project_name = os.path.basename(project) or UNKNOWN_LABEL
        prefix = f"{session_id[:SESSION_ID_WIDTH]} {project_name} - "
        labels[session_id] = prefix + title[:max(LABEL_WIDTH - len(prefix), 0)]
    return labels


def fetch_day_costs(connection: sqlite3.Connection, expression: str, where: str, parameters: list) -> dict:
    """API-equivalent cost of every group on every local day, and of all groups together."""
    sums = ", ".join(f"sum({column})" for column in TOKEN_COLUMNS)
    day_expression = GROUP_EXPRESSIONS["day"]
    query = f"SELECT {expression}, {day_expression}, model, {sums} FROM responses {where} GROUP BY 1, 2, 3"
    costs = {}
    for key, day, model, *token_sums in connection.execute(query, parameters):
        cost = prices.get_cost(model, dict(zip(TOKEN_COLUMNS, token_sums))) or 0.0
        for group in (key, TOTAL_LABEL):
            costs[(group, day)] = costs.get((group, day), 0.0) + cost
    return costs


def create_entry() -> dict:
    entry = {column: 0 for column in TOKEN_COLUMNS}
    entry["cost"] = 0.0
    entry["unpriced_models"] = set()
    return entry


def fold_usage(rows: list) -> dict:
    """Fold per-model sums into one entry per group plus a grand total."""
    entries = {TOTAL_LABEL: create_entry()}
    for key, model, *sums in rows:
        usage = dict(zip(TOKEN_COLUMNS, sums))
        cost = prices.get_cost(model, usage)
        for entry in (entries.setdefault(key, create_entry()), entries[TOTAL_LABEL]):
            for column in TOKEN_COLUMNS:
                entry[column] += usage[column]
            if cost is None:
                entry["unpriced_models"].add(model)
            else:
                entry["cost"] += cost
    return entries


def format_tokens(value: int) -> str:
    for threshold, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= threshold:
            return f"{value / threshold:.2f}{suffix}"
    return str(value)


def build_row(label: str, key: str | None, sessions: int, entry: dict, total_cost: float,
              limit_used: float | None) -> dict:
    """One report row: tokens, cost, its share of the period and of the subscription limit."""
    share = entry["cost"] / total_cost * 100 if total_cost > 0 else 0.0
    row = {"key": key, "label": label, "sessions": sessions}
    for column in TOKEN_COLUMNS:
        row[column] = entry[column]
    row["api_usd"] = round(entry["cost"], 2)
    row["share_percent"] = round(share, 2)
    row["limit_percent"] = None if limit_used is None else round(limit_used * share / 100, 2)
    row["unpriced_models"] = sorted(entry["unpriced_models"])
    return row


def build_rows(entries: dict, labels: dict, session_counts: dict, by: str, limit: int,
               period_cost: float, limit_used: float | None) -> tuple[list[dict], dict]:
    """Order the groups, days by the calendar and everything else by cost, and total them.

    Shares are taken of the whole period, so a report narrowed to one project
    still says what part of the period that project is.
    """
    total = entries.pop(TOTAL_LABEL)
    if by == "day":
        ordered = sorted(entries.items())
        ordered = ordered[-limit:] if limit > 0 else ordered
    else:
        ordered = sorted(entries.items(), key=lambda item: item[1]["cost"], reverse=True)
        ordered = ordered[:limit] if limit > 0 else ordered
    rows = []
    for key, entry in ordered:
        label = labels.get(key) or key or UNKNOWN_LABEL
        rows.append(build_row(label, key, session_counts.get(key, 0), entry, period_cost, limit_used))
    total_label = f"{TOTAL_LABEL} ({len(entries)} rows)"
    total_row = build_row(total_label, None, session_counts[TOTAL_LABEL], total, period_cost, limit_used)
    return rows, total_row


def list_period_days(period: dict) -> list[str]:
    """Local days a period touches, the first to the last."""
    first_day = datetime.strptime(period.get("first_day") or period["since_day"], DAY_FORMAT)
    last_day = datetime.strptime(period.get("last_day") or period["until_day"], DAY_FORMAT)
    day_count = (last_day - first_day).days + 1
    return [(first_day + timedelta(days=offset)).strftime(DAY_FORMAT) for offset in range(day_count)]


def build_day_percents(group: str | None, days: list[str], day_costs: dict, period_cost: float) -> list:
    """Share of the period one group spent on each day, None for a day without usage."""
    percents = []
    for day in days:
        cost = day_costs.get((group, day))
        if cost is None:
            percents.append(None)
        else:
            percents.append(round(cost / period_cost * 100, 2) if period_cost > 0 else 0.0)
    return percents


def build_report_data(by: str, period: dict, windows: dict, project: str | None, limit: int,
                      full_paths: bool, weekly: bool = False) -> dict:
    """Collect the report as plain data, ready for a table or for JSON.

    The share of the subscription limit comes from the reading of the period
    when it is a weekly window with one, where the two cover the same usage.
    Any other period is priced at the rate of the current week, in percent of
    one weekly limit, so a long period can come to more than 100.
    """
    connection = db.get_connection()
    db.create_tables(connection)
    expression = GROUP_EXPRESSIONS[by]
    where, parameters = build_filter(period, project)
    entries = fold_usage(fetch_usage(connection, expression, where, parameters))
    session_counts = fetch_session_counts(connection, expression, where, parameters)
    labels = fetch_session_labels(connection, where, parameters) if by == "session" else {}
    if by == "project" and not full_paths:
        labels = projects.shorten_projects(list(entries))
    period_where, period_parameters = build_filter(period, None)
    period_usage = fold_usage(fetch_usage(connection, "1", period_where, period_parameters))
    day_costs = fetch_day_costs(connection, expression, where, parameters) if weekly else {}
    connection.close()
    period_cost = period_usage[TOTAL_LABEL]["cost"]
    limit_used = period.get("limit_used")
    if limit_used is None and period.get("limit_rate"):
        limit_used = round(period_cost / period["limit_rate"], 2)
        period = {**period, "limit_estimate": limit_used}
    rows, total_row = build_rows(entries, labels, session_counts, by, limit, period_cost, limit_used)
    data = {"by": by, "period": period, "project": project, "limits": windows, "rows": rows, "total": total_row}
    if weekly:
        data["days"] = list_period_days(period)
        for row in rows:
            row["day_percents"] = build_day_percents(row["key"], data["days"], day_costs, period_cost)
        total_row["day_percents"] = build_day_percents(TOTAL_LABEL, data["days"], day_costs, period_cost)
    return data


def get_label_width(labels: list[str]) -> int:
    """Width of the first column: its longest label, up to LABEL_WIDTH."""
    return min(max(len(label) for label in labels), LABEL_WIDTH)


def format_row(row: dict, show_usd: bool, label_width: int) -> str:
    cache_write = row["cache_write_5m_tokens"] + row["cache_write_1h_tokens"]
    limit_text = NO_VALUE
    if row["limit_percent"] is not None:
        limit_text = f"{row['limit_percent']:.{2 if row['limit_percent'] < 100 else 1}f}%"
    line = (
        f"{row['label'][-label_width:]:<{label_width}} {row['sessions']:>5d} "
        f"{format_tokens(row['input_tokens']):>8} {format_tokens(row['output_tokens']):>8} "
        f"{format_tokens(cache_write):>8} {format_tokens(row['cache_read_tokens']):>8} "
        f"{row['share_percent']:>6.1f}%"
    )
    for percent in row.get("day_percents", ()):
        line += f" {NO_VALUE:>4}" if percent is None else f" {percent:>3.0f}%"
    line += f" {limit_text:>7}"
    if show_usd:
        line += f" {row['api_usd']:>10.2f}"
    return line + (UNPRICED_MARK if row["unpriced_models"] else "")


def format_period(period: dict) -> str:
    if period.get("since_local"):
        until = period.get("until_local") or "now"
        return f"Period: {period['since_local']} to {until} ({period['source']})"
    if period.get("since_day") or period.get("until_day"):
        text = f"Period: {period.get('since_day') or 'start'} to {period.get('until_day') or 'now'}"
        return text if period["source"] == CUSTOM_SOURCE else f"{text} ({period['source']})"
    return "Period: all history"


def format_limits(windows: dict) -> list[str]:
    if not windows:
        return ["Limit: no current reading, the status line records one after the first reply of a session"]
    lines = []
    for window in windows.values():
        text = f"Limit: {window['label']} window {window['used_percentage']:.1f}% used as of {window['as_of']}"
        if window["estimated_percentage"] is not None:
            text += f", about {window['estimated_percentage']:.1f}% now"
        lines.append(f"{text}, resets {window['resets_at']}")
    return lines


def render_table(data: dict, show_usd: bool) -> str:
    title = data["by"].upper()
    label_width = get_label_width([title, data["total"]["label"]] + [row["label"] for row in data["rows"]])
    header = (
        f"{title:<{label_width}} {'SESS':>5} {'INPUT':>8} {'OUTPUT':>8} "
        f"{'CACHE W':>8} {'CACHE R':>8} {'SHARE':>7}"
    )
    for day in data.get("days", ()):
        header += f" {WEEKDAY_LABELS[datetime.strptime(day, DAY_FORMAT).weekday()]:>4}"
    header += f" {'LIMIT':>7}"
    if show_usd:
        header += f" {'API USD':>10}"
    lines = [format_period(data["period"])] + format_limits(data["limits"])
    if data["period"].get("until_local") and data["period"].get("limit_used") is not None:
        lines.append(f"Limit of that week: {data['period']['limit_used']:.1f}% used")
    if data["period"].get("limit_estimate") is not None:
        estimate = data["period"]["limit_estimate"]
        lines.append(f"Limit of this period: about {estimate:.1f}% of a weekly limit, at the rate of the current week")
    lines.extend(["", header])
    for row in data["rows"]:
        lines.append(format_row(row, show_usd, label_width))
    lines.append(format_row(data["total"], show_usd, label_width))
    if data["total"]["unpriced_models"]:
        missing = ", ".join(data["total"]["unpriced_models"])
        lines.append(f"{UNPRICED_MARK} shares exclude models without a price in prices.json: {missing}")
    return "\n".join(lines) + "\n"


def render_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main():
    pass


if __name__ == "__main__":
    main()
