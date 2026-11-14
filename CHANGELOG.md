# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `cquota completion bash` and `cquota completion zsh` print a completion
  script for commands, options and their values.
- README: how to put `cquota` on the `PATH` outside Claude Code sessions.

### Changed

- `cquota` without a command runs `report`, and takes its options, instead
  of failing with a usage error.

## [0.0.3] - 2026-11-14

### Changed

- The first column of the report is as wide as its longest label, up to 50
  characters, instead of always 50, so the table fits a narrow window.
- `/cquota:report` shows the top 10 rows unless asked for all of them.

## [0.0.2] - 2026-11-14

### Added

- `cquota report --weekly`: one column per local day before `LIMIT`,
  headed by the weekday, with the share of the period the row spent on that
  day. It covers the last 7 days, or the days of the week given with
  `--week`; the JSON output carries `days` and `day_percents`.

### Changed

- `LIMIT` is filled for every period while the current week has a limit
  reading: a period without a reading of its own is priced at the rate of the
  current week, in percent of one weekly limit.
- `report --week` takes a number of weeks back, so any earlier week can be
  reported: `0` or `this` is the current week, `1` or `last` the one before
  it. `current` and `previous` are still accepted.

### Fixed

- A calendar week on the far side of a clock change started an hour late;
  weeks are now stepped between local midnights.

## [0.0.1] - 2026-11-14

### Added

- Ledger: an SQLite database holding one row per API response, with input,
  output, cache write (5 minute and 1 hour), cache read and thinking tokens,
  the model, the session, the agent and the project.
- Incremental `cquota ingest`: reads only what was appended to the
  transcripts since the previous run, covers subagent and workflow agent
  transcripts, and counts every response once across streaming duplicates
  and resumed sessions.
- Project attribution by the directory a session was launched from, so a
  session that moved between directories is one project; a git worktree
  counts as its main repository.
- `cquota report`: usage by project, session, day or model over the
  current subscription week, the previous one, a range of days or the whole
  history, with a project filter and a total over every row.
- Report rows carry their share of the period and their share of the weekly
  subscription limit; sessions are shown with their titles and projects by
  the name of their directory, `--full-paths` shows the paths.
- `--json` for the report as data, `--usd` for the API-equivalent cost from
  the dated list prices in `prices.json` as the last column.
- `cquota statusline`: a status line command that shows the 5 hour and
  7 day subscription windows and stores every new reading.
- `cquota limits`: the current windows, each with the moment its reading
  was true, an estimate of the percentage by now and a split by project.
- Claude Code plugin: the repository is its own marketplace, hooks run the
  ingest in the background after every turn and subagent and at both ends of
  a session, and `/cquota:report` prints the report inside a session.
- `cquota --version`.
