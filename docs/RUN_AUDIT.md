# Run audit

How to review a batch of runs (typically an event's qualifier, at its close)
for cheating or rule breaking, with an LLM analyst that starts from the data
alone.

## Why an isolated analyst

An analyst that already knows what earlier audits found looks for the same
things again and gives them too much weight. The analyst session therefore
gets a self-contained bundle and nothing else: no repository, no project
memory, no earlier report. The bundle's data dictionary explains what the
fields mean and how the platform produces them; it says nothing about what to
look for.

## 1. Export the bundle

```
cd server && uv run python ../tools/audit_extract.py \
    --since 2026-09-23T08:00:00Z --event season-one \
    --out ~/src/speedfog-audit/2026-09-30
```

`tools/audit_extract.py` (usage and rules in its docstring) reads the
database in one read-only transaction. It writes:

- `data/`: users, races, participations, solo sessions, seeds, pools,
  casters, events and signups as JSON Lines, the chat of the races under
  review, and the weapon catalogue;
- `DATA_DICTIONARY.md` and `BRIEF.md`, copied from `tools/audit/`;
- `manifest.json`: the export time, the latest activity found in the
  database, the review window and the row counts.

Check `latest_activity` in the manifest first: a restored dump can be older
than it looks, because a local server running on it keeps creating dailies
and chat rows.

Races under review are those started at or after `--since`, plus every race
attached to `--event`. Everything else is exported as history, which the
analyst needs for baselines (each player's past runs, each zone's past clear
times).

Names are pseudonymized by default (`player_0001` is the oldest account): a
name can prime an analyst. The replacement also covers race names, custom
rules, chat messages and event configs, for the exact logins and display
names it knows, and Twitch account ids become a rank. The mapping back to
real names goes to `~/.speedfog-audit/<bundle name>.identities.json`. The
script refuses a bundle or mapping path inside the repository, a mapping in
the bundle or in the folder around it, and a bundle directory that is not new
or empty.

## 2. Run the analyst in isolation

Start the session in the bundle folder, which must sit outside this
repository and outside any folder holding a `CLAUDE.md`. Claude Code keys its
auto-memory by project path, so a new folder starts with an empty memory.

- `claude --bare` also skips auto-memory and `CLAUDE.md` discovery
  altogether, but it authenticates only through `ANTHROPIC_API_KEY` (or an
  `apiKeyHelper`), not through a subscription login.
- `claude --safe-mode` starts without `CLAUDE.md`, skills, plugins, hooks and
  MCP servers; unlike `--bare`, its help sets no condition on how the session
  authenticates. Without either flag, the user-level `~/.claude/CLAUDE.md`
  loads.
- `--restricted` confines the file tools to the working directory and ignores
  the user, project and local settings files. It also removes the tools that
  run commands unless `--tools` names them, and the analysis needs a shell to
  run its scripts. A shell command is not confined to the folder, so the
  analyst's transcript is worth a glance afterwards to check that it stayed
  there.
- `--tools` limits the built-in tools to what the analysis needs (reading,
  writing its scripts and report, running them), without web access. MCP
  servers are not built-in tools: `--strict-mcp-config` (with no
  `--mcp-config`) keeps them out, if the session was not started in safe
  mode.

The launch in use keeps safe mode and the usual tools:

```
cd ~/src/speedfog-audit/2026-09-30
claude -p "Your task is described in BRIEF.md in this folder. Read it, then carry it out completely." \
    --safe-mode --permission-mode auto
```

Checked on 2026-09-30: a session started this way has no auto-memory index and
no `CLAUDE.md` content, and its working directory is the bundle. A one-line
prompt asking the session what its context holds is a cheap check before each
run.

The analyst follows `BRIEF.md` and writes `REPORT.md` in the bundle, with its
scripts in `scripts/`.

## 3. Read the report

The report names players by pseudonym. The identities file maps them back to
Twitch accounts. Then check the leads against what the data cannot show:
VODs, and the server logs for rejected messages and reload detections.
