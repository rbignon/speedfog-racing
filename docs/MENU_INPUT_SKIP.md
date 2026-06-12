# Menu Input Skip Removal

How the racing mod restores instant menuing by removing the input delay Elden
Ring 1.12 added to "prevent accidental skips" in yes/no confirmation boxes and
conversation menus.

## Why

1.12 added a short window after a menu dialog opens during which confirm is
ignored. For competitive speedrunning this slows menuing that was instant on
1.11. The mod removes it uniformly for every player, so it is fair (no
per-player asymmetry) and applied unconditionally at startup (no toggle).

## Mechanism

Each dialog template stores a confirm threshold (~0.32 s); a per-frame
accumulator must reach it before confirm is accepted. The threshold is written
by a tiny setter at dialog-template creation. On 1.11 that setter was an inert
stub (`mov rax,rcx; ret`), leaving the threshold at 0, so confirm was instant.
1.12 filled in the body so it stores ~0.32 s.

The mod reverts the setter to the 1.11 stub at runtime. Patching the setter
(rather than individual call sites) removes the delay for all callers at once
and is independent of struct offsets.

## How it is applied

`eldenring::menu_input_patch::install()` runs once from `RaceTracker::new`,
right after the warp hook. It:

1. locates the setter by an AOB scan over the live `eldenring.exe` image
   (`eldenring::scan::scan_unique`, backed by the pure matcher in `core::aob`),
   requiring exactly one match;
2. overwrites the setter's 4-byte prologue with `48 8B C1 C3`
   (`mov rax,rcx; ret`) via `eldenring::scan::patch_bytes` (flip the page to
   RWX, write, restore protection, flush the instruction cache).

AOB (call rel32 and field disp8 wildcarded):

```
40 53 48 83 EC 20 48 8B D9 E8 ?? ?? ?? ?? F3 0F 11 43 ?? 48 8B C3 48 83 C4 20 5B C3
```

The setter runs at dialog-template creation, so a single startup patch affects
every dialog opened afterward. There is no per-frame cost.

## Failure and version behavior

The patch fails safe: if the module info is unavailable, the AOB is not found,
the match is not unique, or the memory write fails, it logs and the mod
continues without patching (the delay simply remains). On builds without the
delay (e.g. 1.11) the AOB does not match, so the patch is a no-op. If a future
build changes the setter shape so the AOB no longer matches, re-derive it (see
Maintenance below).

## Maintenance: re-deriving the AOB after a game update

`SETTER_PATTERN` in `mod/src/eldenring/menu_input_patch.rs` is a byte signature,
so a game update that recompiles the setter can break it. The symptom is the log
line `menu-input patch: setter not found` while the delay is clearly present in
game. To recover, locate the setter on the new executable and regenerate the
pattern with the bundled tool:

```
uv run tools/find_menu_input_setter.py path/to/eldenring.exe
```

It prints a ready-to-paste `SETTER_PATTERN`; drop it into `menu_input_patch.rs`
and run `cargo fmt`. The executable must be the decrypted / unpacked image (e.g.
a memory dump, or a build with the anti-tamper layer stripped); the live retail
exe is packed and will not scan correctly.

The tool finds the setter two independent ways and requires them to agree:

- Method A (AOB): the same byte signature the mod embeds. It matches only builds
  that actually have the delay, so it correctly reports "not found" on 1.11 and
  pre-1.12 builds, which is a useful sanity check.
- Method B (semantic): scans small `.pdata` functions for the setter's shape, a
  `T* set(T* this) { this->field = getter(); return this; }` whose getter entry
  is an obfuscation `jmp` trampoline. Being register, offset, and byte agnostic,
  it still finds the setter after the exact bytes drift, and rebuilds the AOB
  from what it found (wildcarding the call displacement and the field offset).

`--patch stub` (recommended) or `--patch nop` additionally writes a statically
patched copy of the exe, handy for isolating the behavior outside the mod.
