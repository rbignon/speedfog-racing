"""Cross-language parity guard for weapon-combo aggregation.

The Python mirror (``daily_points_service._aggregate_weapon_combos``) must
produce the same output as the TS reference (``web/src/lib/weapons.ts``'s
``aggregateAllCombos``) for the shared fixture. The TS side asserts the same
``input`` -> ``expected`` mapping in
``web/src/lib/__tests__/weapons.test.ts``. Editing one side without the other
breaks this test.
"""

from __future__ import annotations

import json
from pathlib import Path

from speedfog_racing.services.daily_points_service import _aggregate_weapon_combos

_FIXTURE = (
    Path(__file__).resolve().parents[2] / "web/src/lib/__tests__/fixtures/weapon-combos-parity.json"
)


def test_aggregation_matches_ts_reference():
    fixture = json.loads(_FIXTURE.read_text())
    # The TS reference aggregates one zone history; the Python mirror takes a
    # list of histories, so wrap the single fixture history.
    assert _aggregate_weapon_combos([fixture["input"]]) == fixture["expected"]
