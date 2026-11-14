#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite connection and schema of the ledger."""
import os
import sqlite3

# Local imports
from cquota import config
from cquota import projects

# Raised whenever the parser starts reading something new out of the transcripts.
PARSER_VERSION = 2
REREAD_VERSION = 1
LAUNCH_VERSION = 2

# Directory a session was launched from: where its own transcript first answered,
# or, for a session known only through its agents, where the first of them did.
LAUNCH_DIRECTORY = """
SELECT cwd FROM responses
WHERE session_id = ? AND cwd != ''
ORDER BY kind != 'session', timestamp LIMIT 1
"""

# One row per API response. The first session to record a response keeps it:
# a resumed session copies the earlier history into its own transcript.
SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path            TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    offset          INTEGER NOT NULL,
    first_timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responses (
    message_id            TEXT NOT NULL,
    request_id            TEXT NOT NULL,
    session_id            TEXT NOT NULL,
    agent_id              TEXT,
    kind                  TEXT NOT NULL,
    cwd                   TEXT NOT NULL,
    project               TEXT NOT NULL,
    model                 TEXT NOT NULL,
    timestamp             TEXT NOT NULL,
    entrypoint            TEXT,
    git_branch            TEXT,
    input_tokens          INTEGER NOT NULL,
    output_tokens         INTEGER NOT NULL,
    cache_write_5m_tokens INTEGER NOT NULL,
    cache_write_1h_tokens INTEGER NOT NULL,
    cache_read_tokens     INTEGER NOT NULL,
    thinking_tokens       INTEGER NOT NULL,
    web_search_requests   INTEGER NOT NULL,
    web_fetch_requests    INTEGER NOT NULL,
    PRIMARY KEY (message_id, request_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    custom_title TEXT,
    ai_title     TEXT
);

CREATE TABLE IF NOT EXISTS limits (
    timestamp       INTEGER NOT NULL,
    window          TEXT NOT NULL,
    used_percentage REAL NOT NULL,
    resets_at       INTEGER NOT NULL,
    session_id      TEXT,
    project         TEXT
);

CREATE INDEX IF NOT EXISTS responses_session ON responses (session_id);
CREATE INDEX IF NOT EXISTS responses_project ON responses (project);
CREATE INDEX IF NOT EXISTS responses_timestamp ON responses (timestamp);
"""


def get_connection() -> sqlite3.Connection:
    """Open the ledger, creating its directory on first use."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    connection = sqlite3.connect(config.DB_PATH, timeout=config.BUSY_TIMEOUT)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def get_launch_directory(connection: sqlite3.Connection, session_id: str) -> str | None:
    row = connection.execute(LAUNCH_DIRECTORY, (session_id,)).fetchone()
    return row[0] if row else None


def reassign_projects(connection: sqlite3.Connection) -> None:
    """Give every response the project of its session, the directory the session was launched from."""
    session_ids = [row[0] for row in connection.execute("SELECT DISTINCT session_id FROM responses")]
    for session_id in session_ids:
        launch_directory = get_launch_directory(connection, session_id)
        if launch_directory is None:
            continue
        project = projects.resolve_project(launch_directory)
        connection.execute("UPDATE responses SET project = ? WHERE session_id = ?", (project, session_id))


def create_tables(connection: sqlite3.Connection) -> None:
    """Create the schema and bring a ledger written by an older version up to date."""
    connection.executescript(SCHEMA)
    stored_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if stored_version >= PARSER_VERSION:
        return
    with connection:
        if stored_version < REREAD_VERSION:
            connection.execute("UPDATE files SET offset = 0")
        if stored_version < LAUNCH_VERSION:
            reassign_projects(connection)
        connection.execute(f"PRAGMA user_version = {PARSER_VERSION}")


def main():
    pass


if __name__ == "__main__":
    main()
