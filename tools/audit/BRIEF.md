# Brief

You are auditing the integrity of runs on SpeedFog Racing, a competitive
Elden Ring randomizer platform. The organizers want to know whether any run
under review (`is_target` in the data) shows signs of cheating or of breaking
the rules, in the broad sense: anything that gives a runner an advantage that
the rules, or the spirit of a fair race, do not allow. No earlier finding is
given to you on purpose. Form your own hypotheses from the data.

## Materials and limits

- This folder only: `DATA_DICTIONARY.md`, `manifest.json` and `data/`. Do not
  read, list or search anything outside this folder, and do not use the
  network.
- Read `DATA_DICTIONARY.md` before anything else. Several fields are easy to
  misread, and a wrong reading produces anomalies that do not exist.
- Put the code you write in `scripts/` and any intermediate output in `work/`,
  so the analysis can be rerun and checked.

## How to work

- Use the history (runs that are not under review) for baselines: compare
  each run with the rest of its race, with the same zones in other seeds, and
  with the same player's past.
- Treat every anomaly as a hypothesis. Before reporting it, check that your
  own processing did not produce it, and look for innocent explanations in
  the data.
- Report every lead you judge worth a look, including weak ones, and say how
  strong each is. Do not stop at the first suspect you find.

## Deliverable

Write `REPORT.md`, in English:

1. A short summary: which runs or players deserve a closer look, in order of
   concern.
2. One section per finding: the player and the race, what is abnormal, the
   evidence with figures, the innocent explanations you checked and what came
   of them, your confidence (high, medium, low), the effect on the results if
   the run is not legitimate, and what would confirm or clear it (for example a
   VOD moment to watch, or data the platform does not keep).
3. What you checked that came back clean.
4. The limits of the analysis, and the data the platform should record to make
   the next audit easier.
