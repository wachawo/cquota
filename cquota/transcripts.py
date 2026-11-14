#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Locate Claude Code transcripts and read token usage out of them."""
import json
import os

TRANSCRIPT_SUFFIX = ".jsonl"
AGENT_PREFIX = "agent-"
SYNTHETIC_MODEL = "<synthetic>"
# Cheap substring checks that spare json.loads on lines carrying no usage.
USAGE_MARK = b'"usage"'
ASSISTANT_MARK = b"assistant"
TITLE_MARK = b'-title"'
# Record type -> (ledger column, record field)
TITLE_FIELDS = {
    "custom-title": ("custom_title", "customTitle"),
    "ai-title":     ("ai_title", "aiTitle"),
}


def list_transcripts(projects_dir: str) -> list[str]:
    paths = []
    for root, dirs, files in os.walk(projects_dir):
        for name in files:
            if name.endswith(TRANSCRIPT_SUFFIX):
                paths.append(os.path.join(root, name))
    return paths


def get_file_kind(relative_path: str) -> str:
    """Tell the main session transcript from subagent and workflow agent ones."""
    parts = relative_path.split(os.sep)
    if "workflows" in parts:
        return "workflow"
    if "subagents" in parts:
        return "subagent"
    return "session"


def get_session_id(relative_path: str) -> str:
    """Session a transcript belongs to: its own name, or the directory of its parent session."""
    parts = relative_path.split(os.sep)
    if len(parts) <= 2:
        return parts[-1][:-len(TRANSCRIPT_SUFFIX)]
    return parts[1]


def get_agent_id(path: str) -> str | None:
    name = os.path.basename(path)[:-len(TRANSCRIPT_SUFFIX)]
    if name.startswith(AGENT_PREFIX):
        return name[len(AGENT_PREFIX):]
    return None


def build_row(record: dict) -> dict | None:
    """Turn an assistant record into a ledger row, or None when it carries no real usage."""
    message = record.get("message")
    if record.get("type") != "assistant" or not isinstance(message, dict):
        return None
    usage = message.get("usage")
    model = message.get("model")
    message_id = message.get("id")
    if not isinstance(usage, dict) or not message_id or not model or model == SYNTHETIC_MODEL:
        return None
    cache_creation = usage.get("cache_creation") or {}
    output_details = usage.get("output_tokens_details") or {}
    server_tools = usage.get("server_tool_use") or {}
    cache_write = usage.get("cache_creation_input_tokens") or 0
    cache_write_1h = cache_creation.get("ephemeral_1h_input_tokens") or 0
    return {
        "message_id":            message_id,
        "request_id":            record.get("requestId") or record.get("uuid") or "",
        "agent_id":              record.get("agentId"),
        "cwd":                   record.get("cwd") or "",
        "model":                 model,
        "timestamp":             record.get("timestamp") or "",
        "entrypoint":            record.get("entrypoint"),
        "git_branch":            record.get("gitBranch"),
        "input_tokens":          usage.get("input_tokens") or 0,
        "output_tokens":         usage.get("output_tokens") or 0,
        "cache_write_5m_tokens": max(cache_write - cache_write_1h, 0),
        "cache_write_1h_tokens": cache_write_1h,
        "cache_read_tokens":     usage.get("cache_read_input_tokens") or 0,
        "thinking_tokens":       output_details.get("thinking_tokens") or 0,
        "web_search_requests":   server_tools.get("web_search_requests") or 0,
        "web_fetch_requests":    server_tools.get("web_fetch_requests") or 0,
    }


def parse_usage_line(line: bytes) -> dict | None:
    if USAGE_MARK not in line or ASSISTANT_MARK not in line:
        return None
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    return build_row(record)


def parse_title_line(line: bytes) -> tuple[str, str] | None:
    """Return the title column and the title a line sets, or None for any other line."""
    if TITLE_MARK not in line:
        return None
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    title_field = TITLE_FIELDS.get(record.get("type"))
    if title_field is None or not record.get(title_field[1]):
        return None
    return title_field[0], record[title_field[1]]


def read_new_rows(path: str, offset: int) -> tuple[list[dict], dict, int]:
    """Read complete lines appended after offset: usage rows, session titles, the new offset.

    One API response is written as several lines sharing the same ids, the last
    of them carrying the final output count, so the largest one is kept.
    """
    rows = {}
    titles = {}
    with open(path, "rb") as handle:
        handle.seek(offset)
        for line in handle:
            if not line.endswith(b"\n"):
                break
            offset += len(line)
            title = parse_title_line(line)
            if title is not None:
                titles[title[0]] = title[1]
                continue
            row = parse_usage_line(line)
            if row is None:
                continue
            key = (row["message_id"], row["request_id"])
            previous = rows.get(key)
            if previous is None or row["output_tokens"] > previous["output_tokens"]:
                rows[key] = row
    return list(rows.values()), titles, offset


def main():
    pass


if __name__ == "__main__":
    main()
