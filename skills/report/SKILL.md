---
name: report
description: Show how many tokens the Claude Code subscription spent, by project folder, session, day or model, with the API-equivalent cost. Use when the user asks where their tokens or usage went, what a project or a session cost, or for a usage report.
argument-hint: "[--by project|session|day|model] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--sessions] [--week N|this|last] [--weekly] [--all] [--project TEXT] [--full-paths] [--usd] [--json] [--limit N]"
---

# Usage report

Run these two commands with the Bash tool, in this order:

```bash
cquota ingest --quiet
```

```bash
cquota report $ARGUMENTS
```

The first brings the ledger up to date, the second prints the table. When the
user gave no options, pick them from what they asked: `--by session` for
sessions, `--project TEXT` for one project, `--since` and `--until` for a
period (local days, inclusive), `--week last` for last week, `--week N` for
the week N weeks back, `--weekly` for a breakdown by day of the last 7 days
(of that week when combined with `--week`; never with `--since`, `--until` or
`--all`), `--all` for the whole history. With no hint
at all, run it without options: projects over the current subscription week.

Unless the user asked for every row or gave `--limit` themselves, add
`--limit 10`: the total still covers all rows, and the table stays short
enough to read in a conversation.

The limit line gives the last real reading with its time and, after "about",
an estimate for now; keep the two apart when you summarise.

`SHARE` is the part of the period a row accounts for, `LIMIT` the part of the
weekly subscription limit it used; `LIMIT` is an estimate, and for a period
other than a recorded subscription week it is priced at the rate of the
current week, so it can exceed 100%. With `--weekly`
the weekday columns split `SHARE` between the days of the period, and `-`
is a day without usage.

Show the table exactly as printed, in a code block, then add at most two
sentences on what stands out. Do not recompute or round the figures.

When the user asks about the subscription limits or how much of the 5 hour or
7 day window a project used, run `cquota limits` instead of the report
and show its output the same way. Its split by project is an estimate, say so.

Add `--usd` only when the user asks about cost or money. Its `API USD` column
is what the same usage would cost at the list prices of the API; a subscription is not billed per token, so present it as an
equivalent, not as money spent.
