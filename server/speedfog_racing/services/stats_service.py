"""Stats computation: ELO ratings and behavioral traits."""

from statistics import median
from typing import Any

K_FACTOR = 32
STARTING_ELO = 1500.0
MIN_RACES_FOR_DISPLAY = 3
DOMINANT_TRAIT_THRESHOLD = 40


def compute_elo_deltas(
    players: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute ELO rating changes for all players in a race.

    Each player dict must have: user_id, elo, igt_ms, finished (bool).
    Players with finished=False are treated as abandoned (S=0 against finishers).
    Returns a dict mapping user_id to delta (float).
    """
    n = len(players)
    if n < 2:
        return {p["user_id"]: 0.0 for p in players}

    finisher_igts = [p["igt_ms"] for p in players if p["finished"]]
    if finisher_igts:
        ref_time = median(finisher_igts) * 0.3
    else:
        ref_time = 1.0  # Avoid division by zero; all abandoned

    deltas: dict[str, float] = {p["user_id"]: 0.0 for p in players}

    for i in range(n):
        for j in range(i + 1, n):
            a, b = players[i], players[j]
            ea = 1.0 / (1.0 + 10.0 ** ((b["elo"] - a["elo"]) / 400.0))
            eb = 1.0 - ea

            sa, sb = _actual_scores(a, b, ref_time)

            deltas[a["user_id"]] += K_FACTOR * (sa - ea)
            deltas[b["user_id"]] += K_FACTOR * (sb - eb)

    for uid in deltas:
        deltas[uid] /= n - 1

    return deltas


def _actual_scores(a: dict[str, Any], b: dict[str, Any], ref_time: float) -> tuple[float, float]:
    """Compute actual scores for a pair with margin of victory."""
    a_fin, b_fin = a["finished"], b["finished"]

    if a_fin and b_fin:
        gap = abs(a["igt_ms"] - b["igt_ms"])
        margin = min(gap / ref_time, 1.0) if ref_time > 0 else 0.0
        if a["igt_ms"] <= b["igt_ms"]:
            return 0.5 + 0.5 * margin, 0.5 - 0.5 * margin
        else:
            return 0.5 - 0.5 * margin, 0.5 + 0.5 * margin
    elif a_fin and not b_fin:
        return 1.0, 0.0
    elif not a_fin and b_fin:
        return 0.0, 1.0
    else:
        return 0.5, 0.5
