#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Incremental, idempotent ingest of transcripts into the ledger."""
import logging
import multiprocessing
import os
import sqlite3
import time

# Local imports
from cquota import config
from cquota import db
from cquota import projects
from cquota import transcripts

logger = logging.getLogger(__name__)

# A later line of the same response replaces the counts only when it reports more
# output; the session, project and agent of the first record are kept.
UPSERT_RESPONSE = """
INSERT INTO responses (
    message_id, request_id, session_id, agent_id, kind, cwd, project, model, timestamp,
    entrypoint, git_branch, input_tokens, output_tokens, cache_write_5m_tokens,
    cache_write_1h_tokens, cache_read_tokens, thinking_tokens, web_search_requests,
    web_fetch_requests
) VALUES (
    :message_id, :request_id, :session_id, :agent_id, :kind, :cwd, :project, :model, :timestamp,
    :entrypoint, :git_branch, :input_tokens, :output_tokens, :cache_write_5m_tokens,
    :cache_write_1h_tokens, :cache_read_tokens, :thinking_tokens, :web_search_requests,
    :web_fetch_requests
)
ON CONFLICT (message_id, request_id) DO UPDATE SET
    input_tokens          = excluded.input_tokens,
    output_tokens         = excluded.output_tokens,
    cache_write_5m_tokens = excluded.cache_write_5m_tokens,
    cache_write_1h_tokens = excluded.cache_write_1h_tokens,
    cache_read_tokens     = excluded.cache_read_tokens,
    thinking_tokens       = excluded.thinking_tokens,
    web_search_requests   = excluded.web_search_requests,
    web_fetch_requests    = excluded.web_fetch_requests
WHERE excluded.output_tokens > responses.output_tokens
"""

UPSERT_FILE = """
INSERT INTO files (path, session_id, kind, offset, first_timestamp)
VALUES (:path, :session_id, :kind, :offset, :first_timestamp)
ON CONFLICT (path) DO UPDATE SET
    offset = excluded.offset,
    first_timestamp = CASE WHEN files.first_timestamp = ''
                           THEN excluded.first_timestamp ELSE files.first_timestamp END
"""


UPSERT_SESSION = """
INSERT INTO sessions (session_id, custom_title, ai_title)
VALUES (:session_id, :custom_title, :ai_title)
ON CONFLICT (session_id) DO UPDATE SET
    custom_title = coalesce(excluded.custom_title, sessions.custom_title),
    ai_title     = coalesce(excluded.ai_title, sessions.ai_title)
"""


def get_known_files(connection: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    cursor = connection.execute("SELECT path, offset, first_timestamp FROM files")
    return {path: (offset, first_timestamp) for path, offset, first_timestamp in cursor}


def get_file_size(path: str) -> int:
    """Size of a transcript, zero when it was cleaned up since it was listed."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def select_pending_files(known_files: dict, paths: list[str]) -> list[tuple[str, int]]:
    """Pick the transcripts that grew, each with the offset to resume from."""
    pending = []
    for path in paths:
        size = get_file_size(path)
        offset = known_files.get(path, (0, ""))[0]
        if size < offset:
            # The file was rewritten; rereading it whole is safe, rows are keyed.
            offset = 0
        if size > offset:
            pending.append((path, offset))
    return pending


def scan_file(task: tuple[str, int]) -> dict | None:
    path, offset = task
    relative_path = os.path.relpath(path, config.PROJECTS_DIR)
    try:
        rows, titles, new_offset = transcripts.read_new_rows(path, offset)
        modified_at = os.path.getmtime(path)
    except OSError as exc:
        logger.warning(f"Skipped {path}: {type(exc).__name__}: {str(exc)}")
        return None
    timestamps = [row["timestamp"] for row in rows if row["timestamp"]]
    return {
        "path":            path,
        "session_id":      transcripts.get_session_id(relative_path),
        "kind":            transcripts.get_file_kind(relative_path),
        "agent_id":        transcripts.get_agent_id(path),
        "rows":            rows,
        "custom_title":    titles.get("custom_title"),
        "ai_title":        titles.get("ai_title"),
        "offset":          new_offset,
        "first_timestamp": min(timestamps) if timestamps else "",
        "modified_at":     modified_at,
    }


def scan_files(pending: list[tuple[str, int]]) -> list[dict]:
    if len(pending) < config.POOL_THRESHOLD:
        results = [scan_file(task) for task in pending]
    else:
        with multiprocessing.Pool(config.WORKERS) as pool:
            results = pool.map(scan_file, pending, chunksize=16)
    return [result for result in results if result is not None]


def order_results(results: list[dict], known_files: dict) -> list[dict]:
    """Oldest session first, so a response copied by a resume stays with its original session."""
    def get_order_key(result: dict) -> tuple[str, float]:
        stored_timestamp = known_files.get(result["path"], (0, ""))[1]
        return (stored_timestamp or result["first_timestamp"], result["modified_at"])
    return sorted(results, key=get_order_key)


def store_result(connection: sqlite3.Connection, result: dict) -> None:
    """Write the rows of one transcript and advance its offset in a single transaction.

    Every row takes the project of its session: the directory the session was
    launched from, which for a session seen for the first time is where its
    earliest response in this transcript was given.
    """
    launch_directory = db.get_launch_directory(connection, result["session_id"])
    if launch_directory is None:
        located_rows = [row for row in result["rows"] if row["cwd"]]
        earliest_row = min(located_rows, key=lambda row: row["timestamp"], default=None)
        launch_directory = earliest_row["cwd"] if earliest_row else ""
    project = projects.resolve_project(launch_directory)
    rows = []
    for row in result["rows"]:
        stored_row = dict(row)
        stored_row["session_id"] = result["session_id"]
        stored_row["kind"] = result["kind"]
        stored_row["agent_id"] = row["agent_id"] or result["agent_id"]
        stored_row["project"] = project
        rows.append(stored_row)
    with connection:
        connection.executemany(UPSERT_RESPONSE, rows)
        if result["custom_title"] or result["ai_title"]:
            connection.execute(UPSERT_SESSION, result)
        connection.execute(UPSERT_FILE, result)


def count_responses(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT count(*) FROM responses").fetchone()[0]


def run_ingest() -> dict:
    """Read everything appended to the transcripts since the previous run."""
    start_time = time.monotonic()
    connection = db.get_connection()
    db.create_tables(connection)
    known_files = get_known_files(connection)
    paths = transcripts.list_transcripts(config.PROJECTS_DIR)
    pending = select_pending_files(known_files, paths)
    results = order_results(scan_files(pending), known_files)
    responses_before = count_responses(connection)
    for result in results:
        store_result(connection, result)
    responses_after = count_responses(connection)
    connection.close()
    return {
        "files_total":     len(paths),
        "files_read":      len(results),
        "responses_new":   responses_after - responses_before,
        "responses_total": responses_after,
        "seconds":         time.monotonic() - start_time,
    }


def main():
    pass


if __name__ == "__main__":
    main()
