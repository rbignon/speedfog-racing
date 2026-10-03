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

## 3. Check the known signatures

`tools/audit_signatures.py` runs the patterns we already know over the same
bundle, deterministically, so they are never missed whatever the analyst
finds:

```
python3 tools/audit_signatures.py --bundle ~/src/speedfog-audit/2026-09-30 \
  --logs qualifier.log --identities ~/.speedfog-audit/2026-09-30.identities.json
```

It writes `~/.speedfog-audit/<bundle>.signatures.md` and `.json` (never inside
the bundle). `--scope all` lists every run instead of the targets;
`--player NAME` (pseudonym or Twitch login) lists every run of one player, to
re-check the history of a confirmed cheater.

The logs are optional and only feed S3. Export them on the server over the
review window:

```
journalctl -u speedfog-racing --since "2026-09-23 08:00" --until "2026-10-08 08:00" \
  -o short-iso > qualifier.log
```

Zone query lines in the older format name neither the player nor the IGT.
S3 then times the runner's entry into the zone by its `event_flag` line, on
the server clock, and lists a warp that several runners in the zone could
have made instead of attributing it.

| signature                 | what it flags                                                                                      | strength                                                                                        |
| ------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| S1 `deaths_stop`          | 2+ deaths in a node, then no death over 10+ layers and 3+ major bosses, against expected deaths    | strong p < 0.001 with the tail's major bosses at the 20th percentile or faster, medium p < 0.01 |
| S2 `impossible_traversal` | a first, clean traversal under the fastest other run through the same gates against the same boss  | medium < 0.85 x floor, strong < 0.75 x (50+)                                                    |
| S3 `grace_warp`           | (logs) a grace warp to an unvisited node, or into the node entered less than 120 s before          | strong; medium, info at the node's most used in-zone grace shared with others                   |
| S4 `save_restore`         | a game restart that brings the in-game time back down, with the erased time and its rank effect    | medium if the rank changes, else info; weak under 60 s                                          |
| S5 `layer_jump`           | a fog skipping layers (sequence break or lost messages), a position change into an unvisited node  | medium or weak; strong or medium                                                                |
| S6 `fresh_account`        | an account created around the race, at most 2 runs, top-quarter finish                             | weak (context)                                                                                  |
| S7 `platform`             | playoff cutoff never applied, organizer racing their own event, in-game time faster than the clock | medium, info, strong                                                                            |
| S8 `debug_flags`          | cheat-tool flags reported by the mod                                                               | strong                                                                                          |

A deathless tail at an ordinary pace is what a good run looks like, so S1 is
strong only when the major bosses after the struggle also fall fast, against
the same bosses in other runs. With fewer than 10 such clears to compare, the
pace is unknown and the finding stays medium; a no-death cheat played at an
ordinary pace reads medium too.

S2 skips the first node a run enters from the start when the start node
carries deaths, both as a finding and as a reference. Such deaths mean the
record before the run's first entry is unreliable. One known cause is a fog
crossed before the race start, which the mod does not report: the recorded
entry is then a second pass, with the boss already dead. Deaths at the start
are rare (29 of about 12,700 runs by 2026-10-02, training sessions included).

In-zone grace queries in a node mostly name one and the same grace for every
runner. S3 turns an in-zone warp into info when another runner warps to that
grace in that node too, and no other grace of the node draws more runners
there. Disqualified runs vouch for no grace. The count spans every race and
seed where the node appears, and ignores which entrance the runner came
through: a node whose entrances each have their own nearby grace keeps the
less used one at medium. One honest runner warping to the same grace hides a
warp at info when no grace of the node draws more runners, and two cheaters on
one grace hide each other in a node where nobody else warps.

The report lists the players with strong findings in several signatures
first, then by their number of strong findings, then of medium ones. Within a
strength, findings come by signature (a cheat tool or a warp first, then
timings no other run reaches, then erased time, then context), each gravest
first: lowest S1 probability, lowest S2 ratio, largest S4 erased time. It
ends with base rates: how many history runs fire each signature, which tells
how much a finding is worth. Both reports use the same pseudonyms: read the
analyst's findings next to the signatures, a lead present in both first.

## 4. Read the report

The report names players by pseudonym. The identities file maps them back to
Twitch accounts. Then check the leads against what the data cannot show:
VODs, and the server logs for rejected messages and reload detections.

Mod connection log lines (`journalctl -u speedfog-racing` on the server)
carry `race=<race id> participant=<participant id>` for a race and
`training=<session id>` for a solo session, so grepping a participant id keeps
one player's lines. Lines written before authentication (mod version, auth
timeout or rejection) name only the race; the `Mod connected: race=...,
participant=...` line links a connection to its player. `event_flag` and
`zone_query` lines carry the `message_id` and the IGT, which ties each one to
its `zone_history` entry. A resolved or unresolved zone query also gives the
`grace` the mod reported (a grace warp) and the `map_id`. A quit-out reload
gives neither, since the server keeps the current zone.

Gaps in the `message_id` sequence are normal. The mod numbers fog traversals
and zone queries with one counter, and only messages that changed the
recorded zone leave a `zone_history` entry. A zone query that resolves to the
zone the player is already in, or to no zone, leaves a log line only. Some
gaps leave no line at all: a zone query or flag from a player who is not
playing, a zone query outside a running race, a message sent before the run's
first status update, the second flag of a shared entrance, and an id the mod
drops when it resends an undelivered flag under a new one.

Lines in the older format name only the race and carry no `message_id`. A
player's `event_flag` lines there are found through their `igt_ms`. Their
`zone_query` lines carry no IGT and can only be matched by time.
