#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Name the project of a session by the directory it was launched from."""
import functools
import os

# Worktrees Claude Code creates itself, recognisable after they are removed from disk
CLAUDE_WORKTREE_MARKER = "/.claude/worktrees/"
WORKTREE_MARKER = "/.git/worktrees/"
GITDIR_PREFIX = "gitdir:"


def read_main_repository(git_file: str, fallback: str) -> str:
    """Follow the gitdir pointer of a linked worktree back to its main repository."""
    try:
        with open(git_file, "r", encoding="utf-8") as handle:
            pointer = handle.read().strip()
    except OSError:
        return fallback
    gitdir = pointer.removeprefix(GITDIR_PREFIX).strip()
    if WORKTREE_MARKER in gitdir:
        return gitdir.split(WORKTREE_MARKER)[0]
    return fallback


@functools.lru_cache(maxsize=None)
def resolve_project(launch_directory: str) -> str:
    """Project of a session: the directory it was launched from.

    The one exception is a git worktree, which is another checkout of the same
    project and is reported as its main repository.
    """
    if CLAUDE_WORKTREE_MARKER in launch_directory:
        return launch_directory.split(CLAUDE_WORKTREE_MARKER)[0]
    git_path = os.path.join(launch_directory, ".git")
    if os.path.isfile(git_path):
        return read_main_repository(git_path, launch_directory)
    return launch_directory


def shorten_projects(paths: list[str]) -> dict[str, str]:
    """Name every project by its directory, adding the parent where two would read the same."""
    names = {path: os.path.basename(path) for path in paths if path}
    name_counts = {}
    for name in names.values():
        name_counts[name] = name_counts.get(name, 0) + 1
    for path, name in names.items():
        if name_counts[name] > 1:
            names[path] = os.path.join(os.path.basename(os.path.dirname(path)), name)
    return names


def main():
    pass


if __name__ == "__main__":
    main()
