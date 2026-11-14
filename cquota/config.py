#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paths and tunables of the ledger."""
import json
import os

# Paths
HOME_DIR = os.path.expanduser("~")
CLAUDE_CONFIG_DIR = os.getenv("CLAUDE_CONFIG_DIR", os.path.join(HOME_DIR, ".claude"))
PROJECTS_DIR = os.path.realpath(os.path.join(CLAUDE_CONFIG_DIR, "projects"))
XDG_DATA_HOME = os.getenv("XDG_DATA_HOME", os.path.join(HOME_DIR, ".local", "share"))
DATA_DIR = os.getenv("CQUOTA_DATA_DIR", os.path.join(XDG_DATA_HOME, "cquota"))
DB_PATH = os.path.join(DATA_DIR, "ledger.db")

# The plugin manifest is the one place the version is written
MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), ".claude-plugin", "plugin.json"
)

# Ingest
WORKERS = min(8, os.cpu_count() or 1)
POOL_THRESHOLD = 16
BUSY_TIMEOUT = 30


def read_version() -> str:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)["version"]


def main():
    pass


if __name__ == "__main__":
    main()
