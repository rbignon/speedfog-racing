//! A relay take's world in the receiver's game: what to give and raise, from
//! the state the take carries and the receiver's game read at apply time,
//! then the writes paced over frames. The shell reads the game on its worker
//! thread (the held items, the param rows, the grace flags) and hands the
//! reads here (`plan`); the plan's writes are made on the game thread, a
//! bounded batch per frame (`ApplyRun`), until they are done, the deadline
//! passes, a loading screen comes, or the take is no longer applying. Also
//! the layout of the stat write. Pure: nothing here reads or writes the game,
//! or logs.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

use super::item_inventory::category_nibble;
use super::protocol::CharacterState;
use super::relay_items::{missing_items, stats_plausible, transferable_items, PARAM_MASK};

/// An apply's writes stop this long after it was asked, whatever is left:
/// under the machine's `relay::APPLY_ABANDON`, so the answer always comes
/// before the machine gives the apply up, and the take still fits the
/// server's 30 s.
pub const APPLY_DEADLINE: Duration = Duration::from_secs(15);
/// Most writes (gives and flag raises) of an apply in one frame. A take of a
/// few hundred writes is done in well under a second at 60 fps; the most a
/// state can carry (4000 items and 1000 grace flags) takes about 5 s at
/// 60 fps and 11 s at 30, inside `APPLY_DEADLINE`.
pub const APPLY_WRITES_PER_FRAME: usize = 16;

/// Offset of the level from the first attribute (vigor) in the stats the
/// shell writes (libeldenring `CharacterStats`: eight `i32` attributes,
/// twelve bytes the game uses otherwise, then the level, the runes held and
/// the rune memory).
const STATS_LEVEL_OFFSET: usize = 0x2C;
/// Offset of the runes held from vigor.
const STATS_RUNES_OFFSET: usize = 0x30;

/// The `i32` writes of a stat write, as `(offset from vigor, value)`: the
/// eight attributes in the wire order (vigor to arcane, the game's order),
/// then the level, then the runes held. Nothing else of the structure is
/// written: its padding and the rune memory after the runes stay as the game
/// has them. `None` when a value does not fit an `i32` (never a plausible
/// state's).
pub fn stat_writes(attributes: [u32; 8], level: u32, runes: u32) -> Option<[(usize, i32); 10]> {
    let mut writes = [(0, 0); 10];
    for (i, (slot, &value)) in writes.iter_mut().zip(&attributes).enumerate() {
        *slot = (i * std::mem::size_of::<i32>(), i32::try_from(value).ok()?);
    }
    writes[8] = (STATS_LEVEL_OFFSET, i32::try_from(level).ok()?);
    writes[9] = (STATS_RUNES_OFFSET, i32::try_from(runes).ok()?);
    Some(writes)
}

/// Whether the stats read where a stat write goes (`None`: unreadable or
/// negative, `relay_capture::stats_from_game`) look like a character's, by
/// the rule a capture judges them with (`relay_items::stats_plausible`): a
/// chain that no longer lands on a loaded character's stats must not be
/// written through.
pub fn stats_in_place(read: Option<([u32; 8], u32, u32)>) -> bool {
    read.is_some_and(|(attributes, level, runes)| {
        stats_plausible(&CharacterState {
            attributes,
            level,
            runes,
            items: Vec::new(),
            grace_flags: Vec::new(),
        })
    })
}

/// Weapon id layout: the upgrade level is the last two digits.
const WEAPON_LEVEL_DIV: u32 = 100;

/// The row ids of the item param tables a give is checked against, read from
/// the game's params by the shell (the goods rows are the goods types the
/// transfer rule already reads). A table that did not read is empty: nothing
/// of its category is given.
#[derive(Debug, Default)]
pub struct ItemRows {
    /// `EquipParamWeapon`: row id (a weapon id without its upgrade level:
    /// base plus affinity) to its `reinforceTypeId`.
    pub weapons: HashMap<u32, i16>,
    /// `ReinforceParamWeapon` row ids: a weapon at upgrade level `n` reads
    /// the row `reinforceTypeId + n`.
    pub reinforce: HashSet<u32>,
    /// `EquipParamProtector` row ids.
    pub protectors: HashSet<u32>,
    /// `EquipParamAccessory` row ids.
    pub accessories: HashSet<u32>,
    /// `EquipParamGem` row ids.
    pub gems: HashSet<u32>,
}

/// Whether an item id has its rows in the game's params.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RowCheck {
    /// It has: it may be given.
    Listed,
    /// No row of its table names it (or its category has no table).
    NoRow,
    /// A weapon whose upgrade level has no reinforcement row (a somber weapon
    /// above +10, a level its reinforcement type does not have).
    NoLevel,
}

impl ItemRows {
    /// Whether `item_id` (with its category nibble) has its rows: a weapon's
    /// row without its upgrade level and the reinforcement row of that level,
    /// any other item's row at its param id (`goods`: the goods types read,
    /// by param id).
    pub fn check(&self, item_id: u32, goods: &HashMap<u32, u8>) -> RowCheck {
        let listed = |found: bool| {
            if found {
                RowCheck::Listed
            } else {
                RowCheck::NoRow
            }
        };
        let param = item_id & PARAM_MASK;
        match category_nibble(item_id) {
            0x0 => {
                let level = item_id % WEAPON_LEVEL_DIV;
                let Some(&reinforce_type) = self.weapons.get(&(item_id - level)) else {
                    return RowCheck::NoRow;
                };
                // A negative type names no reinforcement row at any level.
                let reinforce_row = u32::try_from(reinforce_type)
                    .ok()
                    .and_then(|first| first.checked_add(level));
                if reinforce_row.is_some_and(|row| self.reinforce.contains(&row)) {
                    RowCheck::Listed
                } else {
                    RowCheck::NoLevel
                }
            }
            0x1 => listed(self.protectors.contains(&param)),
            0x2 => listed(self.accessories.contains(&param)),
            0x4 => listed(goods.contains_key(&param)),
            0x8 => listed(self.gems.contains(&param)),
            _ => RowCheck::NoRow,
        }
    }
}

/// One write of an apply, in the order they are made: the items, then the
/// boss defeat flags, then the grace flags, then the armor, kept last so a
/// give this mod never made before cannot hold up the rest.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApplyStep {
    /// Give one of this item (id with its nibble): a weapon, a talisman, a
    /// goods or an ash of war.
    Item(u32),
    /// Raise this boss defeat flag.
    Defeat(u32),
    /// Raise this grace flag.
    Grace(u32),
    /// Give one of this armor piece (id with its nibble).
    Armor(u32),
}

impl ApplyStep {
    /// The item id or flag the step writes.
    pub fn target(self) -> u32 {
        match self {
            ApplyStep::Item(id)
            | ApplyStep::Defeat(id)
            | ApplyStep::Grace(id)
            | ApplyStep::Armor(id) => id,
        }
    }
}

/// What a plan found, for its log line.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct PlanCounts {
    /// Item ids the state carries.
    pub offered: usize,
    /// Distinct ones the transfer rule refuses (`relay_items::is_transferable`).
    pub refused: usize,
    /// Whether the held inventory read: without it nothing is given.
    pub inventory_read: bool,
    /// Ids the receiver lacks (`relay_items::missing_items`, a weapon base
    /// once): the transferable ones it holds already, or other copies of a
    /// weapon base given once, are the difference.
    pub missing: usize,
    /// Lacking ids with no param row, never given.
    pub no_row: usize,
    /// Lacking weapons with no reinforcement row at their level, never given.
    pub no_level: usize,
    /// Gives planned, armor apart.
    pub items: usize,
    /// Armor gives planned.
    pub armor: usize,
    /// Boss defeat flags planned.
    pub defeats: usize,
    /// Grace flags planned.
    pub graces: usize,
    /// Grace flags of the state that are no grace of this game, never set.
    pub not_grace: usize,
}

/// The writes of an apply, in order, and what was left out.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ApplyPlan {
    pub steps: Vec<ApplyStep>,
    pub counts: PlanCounts,
    /// The lacking item ids left out for want of a row (`no_row` and
    /// `no_level`), sorted.
    pub unlisted: Vec<u32>,
    /// The state's grace flags that are no grace of this game, sorted.
    pub not_graces: Vec<u32>,
}

/// The writes of a take's world. `items` and `grace_flags` are the state's
/// (none without a state); `held` the item ids the receiver holds, read now
/// (`None`: the inventory did not read, and nothing is given); `goods` and
/// `rows` the param rows read; `defeat_flags` the boss defeat flags to raise
/// (the machine kept only the seed's bosses); `graces` this game's grace
/// flags, sorted. An id is given only when the transfer rule passes it on
/// the receiver's side, the receiver lacks it and its rows exist; a grace
/// flag is raised only when it is one of `graces`. Each write comes once.
pub fn plan(
    items: &[u32],
    held: Option<&[u32]>,
    goods: &HashMap<u32, u8>,
    rows: &ItemRows,
    defeat_flags: &[u32],
    grace_flags: &[u32],
    graces: &[u32],
) -> ApplyPlan {
    let goods_type = |id: u32| goods.get(&id).copied();
    let mut distinct = items.to_vec();
    distinct.sort_unstable();
    distinct.dedup();
    let transferable = transferable_items(distinct.iter().copied(), goods_type).len();
    let mut counts = PlanCounts {
        offered: items.len(),
        refused: distinct.len() - transferable,
        inventory_read: held.is_some(),
        ..PlanCounts::default()
    };
    let missing = held.map_or_else(Vec::new, |held| missing_items(items, held, goods_type));
    counts.missing = missing.len();
    let mut steps = Vec::new();
    let mut armor = Vec::new();
    let mut unlisted = Vec::new();
    for id in missing {
        match rows.check(id, goods) {
            RowCheck::Listed if category_nibble(id) == 0x1 => armor.push(ApplyStep::Armor(id)),
            RowCheck::Listed => steps.push(ApplyStep::Item(id)),
            RowCheck::NoRow => {
                counts.no_row += 1;
                unlisted.push(id);
            }
            RowCheck::NoLevel => {
                counts.no_level += 1;
                unlisted.push(id);
            }
        }
    }
    counts.items = steps.len();
    counts.armor = armor.len();

    let mut defeats = defeat_flags.to_vec();
    defeats.sort_unstable();
    defeats.dedup();
    counts.defeats = defeats.len();
    steps.extend(defeats.into_iter().map(ApplyStep::Defeat));

    let mut state_graces = grace_flags.to_vec();
    state_graces.sort_unstable();
    state_graces.dedup();
    let (lit, not_graces): (Vec<u32>, Vec<u32>) = state_graces
        .into_iter()
        .partition(|flag| graces.binary_search(flag).is_ok());
    counts.graces = lit.len();
    counts.not_grace = not_graces.len();
    steps.extend(lit.into_iter().map(ApplyStep::Grace));

    steps.extend(armor);
    ApplyPlan {
        steps,
        counts,
        unlisted,
        not_graces,
    }
}

/// Why an apply's writes ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApplyEnd {
    /// Every write of the plan was made (a failed one included).
    Complete,
    /// `APPLY_DEADLINE` passed first.
    Deadline,
    /// A frame since the ask read another map or none (a loading screen:
    /// quit-out, death, warp), or the map was unreadable at the ask.
    MapChanged,
    /// The take is no longer applying (given up, replaced, abandoned).
    NotWanted,
}

/// The writes made, by kind.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct Written {
    pub items: usize,
    pub items_failed: usize,
    pub defeats: usize,
    pub defeats_failed: usize,
    pub graces: usize,
    pub graces_failed: usize,
    pub armor: usize,
    pub armor_failed: usize,
}

impl Written {
    fn count(&mut self, step: ApplyStep, made: bool) {
        let (done, failed) = match step {
            ApplyStep::Item(_) => (&mut self.items, &mut self.items_failed),
            ApplyStep::Defeat(_) => (&mut self.defeats, &mut self.defeats_failed),
            ApplyStep::Grace(_) => (&mut self.graces, &mut self.graces_failed),
            ApplyStep::Armor(_) => (&mut self.armor, &mut self.armor_failed),
        };
        if made {
            *done += 1;
        } else {
            *failed += 1;
        }
    }
}

/// An apply from its ask to the end of its writes: it watches the loaded map
/// of every frame from the ask (the plan's reads included), then, once
/// planned, writes a bounded batch per frame. Once ended it never writes
/// again.
pub struct ApplyRun {
    handoff_id: String,
    generation: u64,
    map: Option<u32>,
    asked_at: Instant,
    interrupted: bool,
    steps: Option<Vec<ApplyStep>>,
    next: usize,
    written: Written,
    failed: Vec<u32>,
    ended: Option<ApplyEnd>,
}

impl std::fmt::Debug for ApplyRun {
    /// The identity and progress only: a plan's steps can run to thousands.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ApplyRun")
            .field("handoff_id", &self.handoff_id)
            .field("generation", &self.generation)
            .field("steps", &self.steps.as_ref().map(Vec::len))
            .field("next", &self.next)
            .finish()
    }
}

impl ApplyRun {
    /// The apply asked at `asked_at` for the take `handoff_id`, with the
    /// machine's `generation`, on a frame whose loaded map was `map` (none:
    /// nothing will be written).
    pub fn new(handoff_id: String, generation: u64, map: Option<u32>, asked_at: Instant) -> Self {
        Self {
            handoff_id,
            generation,
            map,
            asked_at,
            interrupted: map.is_none(),
            steps: None,
            next: 0,
            written: Written::default(),
            failed: Vec::new(),
            ended: None,
        }
    }

    pub fn handoff_id(&self) -> &str {
        &self.handoff_id
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn asked_at(&self) -> Instant {
        self.asked_at
    }

    /// A loaded map read since the ask (each frame's, and one right after a
    /// batch): another map or none ends the writes for good, even back on
    /// the ask's map.
    pub fn observe(&mut self, map: Option<u32>) {
        if map.is_none() || map != self.map {
            self.interrupted = true;
        }
    }

    /// The plan's writes arrived.
    pub fn set_plan(&mut self, steps: Vec<ApplyStep>) {
        self.steps = Some(steps);
    }

    pub fn is_planned(&self) -> bool {
        self.steps.is_some()
    }

    /// One frame's writes through `write` (true when the write was made),
    /// `wanted` whether the machine still waits for this apply's take. The
    /// end is checked before the batch (a load seen, not wanted, the
    /// deadline) and after it (nothing left). `None`: more to write, or not
    /// planned yet (nothing written). A step counts as gone before its write
    /// is tried, so a write that panicked is never tried again.
    pub fn write_frame(
        &mut self,
        wanted: bool,
        now: Instant,
        mut write: impl FnMut(ApplyStep) -> bool,
    ) -> Option<ApplyEnd> {
        if self.ended.is_some() {
            return self.ended;
        }
        let steps = self.steps.as_ref()?;
        let stop = if self.interrupted {
            Some(ApplyEnd::MapChanged)
        } else if !wanted {
            Some(ApplyEnd::NotWanted)
        } else if now.saturating_duration_since(self.asked_at) >= APPLY_DEADLINE {
            Some(ApplyEnd::Deadline)
        } else {
            None
        };
        if stop.is_none() {
            let batch_end = steps.len().min(self.next + APPLY_WRITES_PER_FRAME);
            while self.next < batch_end {
                let step = steps[self.next];
                self.next += 1;
                let made = write(step);
                self.written.count(step, made);
                if !made {
                    self.failed.push(step.target());
                }
            }
        }
        self.ended = stop.or((self.next >= steps.len()).then_some(ApplyEnd::Complete));
        self.ended
    }

    /// The writes made so far.
    pub fn written(&self) -> Written {
        self.written
    }

    /// The item ids and flags whose write failed, in order.
    pub fn failed(&self) -> &[u32] {
        &self.failed
    }

    /// Writes of the plan not made.
    pub fn left(&self) -> usize {
        self.steps
            .as_ref()
            .map_or(0, |steps| steps.len().saturating_sub(self.next))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::relay::{APPLY_ABANDON, CHAPEL_MAP_ID};

    const ARMOR: u32 = 0x1000_0000;
    const TALISMAN: u32 = 0x2000_0000;
    const GOODS: u32 = 0x4000_0000;
    const GEM: u32 = 0x8000_0000;

    /// A standard weapon (Longsword, plain and Heavy rows) and a somber one.
    const LONGSWORD: u32 = 2_000_000;
    const SOMBER: u32 = 3_000_000;
    const BOSS: u32 = 10_000_800;

    fn rows() -> ItemRows {
        ItemRows {
            weapons: [(LONGSWORD, 0), (LONGSWORD + 100, 100), (SOMBER, 2200)]
                .into_iter()
                .collect(),
            reinforce: (0..=25).chain(100..=125).chain(2200..=2210).collect(),
            protectors: [40_000, 40_100].into_iter().collect(),
            accessories: [1000, 1010].into_iter().collect(),
            gems: [10_000].into_iter().collect(),
        }
    }

    /// Goods types: a sorcery, a spirit ash and a key item.
    fn goods() -> HashMap<u32, u8> {
        [(4000, 5), (200_000, 7), (8000, 1)].into_iter().collect()
    }

    fn ms(n: u64) -> Duration {
        Duration::from_millis(n)
    }

    #[test]
    fn a_stat_write_touches_only_the_attributes_level_and_runes() {
        // libeldenring `CharacterStats` from vigor: the attributes at
        // 0x00..0x20, three u32 the game uses otherwise at 0x20..0x2C, then
        // the level, the runes held and the rune memory at 0x34.
        let attributes = [40, 20, 30, 18, 16, 9, 7, 12];
        let writes = stat_writes(attributes, 73, 12_345).expect("fits an i32");
        let mut offsets: Vec<usize> = writes.iter().map(|&(offset, _)| offset).collect();
        for &offset in &offsets {
            assert_eq!(offset % 4, 0, "{offset:#x} aligned");
            assert!(
                !(0x20..0x2C).contains(&offset),
                "{offset:#x} in the padding"
            );
            assert!(offset + 4 <= 0x34, "{offset:#x} reaches the rune memory");
        }
        offsets.sort_unstable();
        offsets.dedup();
        assert_eq!(offsets.len(), 10, "each field written once");
        // The attributes go in the wire order, which is the game's.
        for (i, &value) in attributes.iter().enumerate() {
            assert_eq!(writes[i], (4 * i, value as i32));
        }
        assert_eq!(writes[8].1, 73);
        assert_eq!(writes[9].1, 12_345);
        assert!(writes[8].0 < writes[9].0, "the level before the runes");
    }

    #[test]
    fn a_stat_past_an_i32_is_not_written() {
        let attributes = [10; 8];
        assert!(stat_writes(attributes, 1, i32::MAX as u32).is_some());
        assert_eq!(stat_writes(attributes, 1, i32::MAX as u32 + 1), None);
        assert_eq!(stat_writes(attributes, u32::MAX, 0), None);
        let mut big = attributes;
        big[7] = 1 << 31;
        assert_eq!(stat_writes(big, 1, 0), None);
    }

    #[test]
    fn stats_are_written_only_over_a_characters() {
        assert!(stats_in_place(Some((
            [40, 20, 30, 18, 16, 9, 7, 12],
            73,
            0
        ))));
        // Zeroed or shifted memory: no character's stats.
        assert!(!stats_in_place(Some(([0; 8], 0, 0))));
        assert!(!stats_in_place(Some((
            [40, 20, 30, 18, 16, 9, 7, 12],
            74,
            0
        ))));
        assert!(!stats_in_place(Some(([1_000; 8], 7_921, 0))));
        assert!(!stats_in_place(None));
    }

    #[test]
    fn a_weapon_is_checked_without_its_level_and_at_its_level() {
        let rows = rows();
        let goods = goods();
        for (id, want) in [
            (LONGSWORD, RowCheck::Listed),
            (LONGSWORD + 25, RowCheck::Listed),
            (LONGSWORD + 107, RowCheck::Listed),
            // A somber weapon stops at +10.
            (SOMBER + 10, RowCheck::Listed),
            (SOMBER + 11, RowCheck::NoLevel),
            (SOMBER + 25, RowCheck::NoLevel),
            // No Keen row for this base, no row for another base.
            (LONGSWORD + 200, RowCheck::NoRow),
            (2_010_000, RowCheck::NoRow),
        ] {
            assert_eq!(rows.check(id, &goods), want, "{id}");
        }
        // A reinforcement type below 0 has no level row.
        let mut odd = ItemRows::default();
        odd.weapons.insert(LONGSWORD, -1);
        odd.reinforce.insert(0);
        assert_eq!(odd.check(LONGSWORD + 1, &goods), RowCheck::NoLevel);
    }

    #[test]
    fn other_items_are_checked_at_their_param_id_in_their_table() {
        let rows = rows();
        let goods = goods();
        for (id, want) in [
            (ARMOR | 40_000, RowCheck::Listed),
            (ARMOR | 40_200, RowCheck::NoRow),
            (TALISMAN | 1010, RowCheck::Listed),
            (TALISMAN | 40_000, RowCheck::NoRow),
            (GOODS | 4000, RowCheck::Listed),
            (GOODS | 4100, RowCheck::NoRow),
            (GEM | 10_000, RowCheck::Listed),
            (GEM | 1000, RowCheck::NoRow),
            // Another table's row with the same param id is not it.
            (GEM | 40_000, RowCheck::NoRow),
            // A category with no table.
            (0x3000_0000 | 1000, RowCheck::NoRow),
            (u32::MAX, RowCheck::NoRow),
        ] {
            assert_eq!(rows.check(id, &goods), want, "{id:#x}");
        }
        // A table that did not read gives nothing of its category.
        assert_eq!(
            ItemRows::default().check(TALISMAN | 1010, &goods),
            RowCheck::NoRow
        );
    }

    #[test]
    fn the_writes_come_items_then_bosses_then_graces_then_armor() {
        let items = [
            GEM | 10_000,
            ARMOR | 40_100,
            GOODS | 4000,
            LONGSWORD + 107,
            LONGSWORD + 3,
            TALISMAN | 1000,
            ARMOR | 40_000,
        ];
        let plan = plan(
            &items,
            Some(&[]),
            &goods(),
            &rows(),
            &[BOSS, 10_010_800, BOSS],
            &[76_101, 71_190, 76_101],
            &[71_190, 76_101, 76_200],
        );
        assert_eq!(
            plan.steps,
            [
                // Heavy +7 and plain +3: given bare at +7.
                ApplyStep::Item(LONGSWORD + 7),
                ApplyStep::Item(TALISMAN | 1000),
                ApplyStep::Item(GOODS | 4000),
                ApplyStep::Item(GEM | 10_000),
                ApplyStep::Defeat(BOSS),
                ApplyStep::Defeat(10_010_800),
                ApplyStep::Grace(71_190),
                ApplyStep::Grace(76_101),
                ApplyStep::Armor(ARMOR | 40_000),
                ApplyStep::Armor(ARMOR | 40_100),
            ]
        );
        assert_eq!(
            plan.counts,
            PlanCounts {
                offered: 7,
                refused: 0,
                inventory_read: true,
                missing: 6,
                no_row: 0,
                no_level: 0,
                items: 4,
                armor: 2,
                defeats: 2,
                graces: 2,
                not_grace: 0,
            }
        );
    }

    #[test]
    fn a_tampered_state_only_reaches_the_game_through_both_checks() {
        let items = [
            // A key item, an unknown category, ammunition: the transfer rule.
            GOODS | 8000,
            0x3000_0001,
            50_000_000,
            // A talisman and a gem with no row, a somber weapon at +25, a
            // goods with no type: the rows.
            TALISMAN | 9999,
            GEM | 1,
            SOMBER + 25,
            GOODS | 4100,
            // Fine.
            TALISMAN | 1010,
        ];
        let plan = plan(&items, Some(&[]), &goods(), &rows(), &[], &[], &[]);
        assert_eq!(plan.steps, [ApplyStep::Item(TALISMAN | 1010)]);
        assert_eq!(plan.unlisted, [SOMBER + 25, TALISMAN | 9999, GEM | 1]);
        let counts = plan.counts;
        assert_eq!(
            (
                counts.refused,
                counts.missing,
                counts.no_row,
                counts.no_level
            ),
            (4, 4, 2, 1)
        );
    }

    #[test]
    fn a_second_apply_gives_nothing_it_already_gave() {
        let items = [
            LONGSWORD + 107,
            TALISMAN | 1000,
            ARMOR | 40_000,
            GEM | 10_000,
        ];
        let first = plan(
            &items,
            Some(&[]),
            &goods(),
            &rows(),
            &[BOSS],
            &[71_190],
            &[71_190],
        );
        assert_eq!(first.counts.items + first.counts.armor, 4);
        // The first apply's gives are in the inventory read by the second
        // (the weapon landed at another level, as the auto-upgrade does).
        let held = [
            LONGSWORD + 25,
            TALISMAN | 1000,
            ARMOR | 40_000,
            GEM | 10_000,
        ];
        let again = plan(
            &items,
            Some(&held),
            &goods(),
            &rows(),
            &[BOSS],
            &[71_190],
            &[71_190],
        );
        assert_eq!(
            again.steps,
            [ApplyStep::Defeat(BOSS), ApplyStep::Grace(71_190)],
            "flags raised again are harmless"
        );
        assert_eq!(again.counts.missing, 0);
    }

    #[test]
    fn an_unreadable_inventory_gives_nothing_and_still_raises_the_flags() {
        let plan = plan(
            &[TALISMAN | 1000, ARMOR | 40_000],
            None,
            &goods(),
            &rows(),
            &[BOSS],
            &[71_190],
            &[71_190],
        );
        assert_eq!(
            plan.steps,
            [ApplyStep::Defeat(BOSS), ApplyStep::Grace(71_190)]
        );
        assert!(!plan.counts.inventory_read);
        assert_eq!((plan.counts.offered, plan.counts.missing), (2, 0));
    }

    #[test]
    fn a_grace_flag_that_is_no_grace_is_skipped_and_counted() {
        let plan = plan(
            &[],
            Some(&[]),
            &goods(),
            &rows(),
            &[],
            &[1_050_290_500, 76_101, 71_190, 76_101],
            &[71_190, 76_101],
        );
        assert_eq!(
            plan.steps,
            [ApplyStep::Grace(71_190), ApplyStep::Grace(76_101)]
        );
        assert_eq!(plan.not_graces, [1_050_290_500]);
        assert_eq!((plan.counts.graces, plan.counts.not_grace), (2, 1));
        // No grace table read: no grace is raised.
        let none = super::plan(&[], Some(&[]), &goods(), &rows(), &[], &[71_190], &[]);
        assert!(none.steps.is_empty());
        assert_eq!(none.counts.not_grace, 1);
    }

    /// A run of `n` grace writes asked at `t0` at the Chapel, planned.
    fn run_of(n: u32, t0: Instant) -> ApplyRun {
        let mut run = ApplyRun::new("h1".to_string(), 7, Some(CHAPEL_MAP_ID), t0);
        run.set_plan((0..n).map(|i| ApplyStep::Grace(71_000 + i)).collect());
        run
    }

    #[test]
    fn no_frame_writes_more_than_the_batch() {
        let t0 = Instant::now();
        let mut run = run_of(40, t0);
        let mut frames = Vec::new();
        for frame in 1..=5u64 {
            let mut writes = 0;
            let end = run.write_frame(true, t0 + ms(16 * frame), |_| {
                writes += 1;
                true
            });
            frames.push((writes, end));
        }
        assert_eq!(
            frames,
            [
                (APPLY_WRITES_PER_FRAME, None),
                (APPLY_WRITES_PER_FRAME, None),
                (40 - 2 * APPLY_WRITES_PER_FRAME, Some(ApplyEnd::Complete)),
                // Ended: nothing more is ever written.
                (0, Some(ApplyEnd::Complete)),
                (0, Some(ApplyEnd::Complete)),
            ]
        );
        assert_eq!(run.written().graces, 40);
        assert_eq!(run.left(), 0);
    }

    #[test]
    fn the_writes_follow_the_plan_and_count_their_failures() {
        let t0 = Instant::now();
        let mut run = ApplyRun::new("h1".to_string(), 7, Some(CHAPEL_MAP_ID), t0);
        let steps = vec![
            ApplyStep::Item(TALISMAN | 1000),
            ApplyStep::Item(GEM | 10_000),
            ApplyStep::Defeat(BOSS),
            ApplyStep::Grace(71_190),
            ApplyStep::Armor(ARMOR | 40_000),
        ];
        run.set_plan(steps.clone());
        let mut seen = Vec::new();
        let end = run.write_frame(true, t0 + ms(20), |step| {
            seen.push(step);
            // The gem and the boss flag fail; the run goes on.
            !matches!(step, ApplyStep::Item(id) if id == GEM | 10_000)
                && step != ApplyStep::Defeat(BOSS)
        });
        assert_eq!(end, Some(ApplyEnd::Complete));
        assert_eq!(seen, steps);
        assert_eq!(
            run.written(),
            Written {
                items: 1,
                items_failed: 1,
                defeats: 0,
                defeats_failed: 1,
                graces: 1,
                graces_failed: 0,
                armor: 1,
                armor_failed: 0,
            }
        );
        assert_eq!(run.failed(), [GEM | 10_000, BOSS]);
    }

    #[test]
    fn a_write_that_panicked_is_never_made_again() {
        // The shell's frame catches a panic and goes on with the next frame:
        // a give that may have happened must not be given twice.
        let t0 = Instant::now();
        let mut run = run_of(5, t0);
        let caught = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            run.write_frame(true, t0 + ms(16), |step| {
                assert_ne!(step, ApplyStep::Grace(71_002), "the frame panicked");
                true
            })
        }));
        assert!(caught.is_err());
        let mut seen = Vec::new();
        let end = run.write_frame(true, t0 + ms(32), |step| {
            seen.push(step);
            true
        });
        assert_eq!(end, Some(ApplyEnd::Complete));
        assert_eq!(seen, [ApplyStep::Grace(71_003), ApplyStep::Grace(71_004)]);
    }

    #[test]
    fn nothing_is_written_before_the_plan() {
        let t0 = Instant::now();
        let mut run = ApplyRun::new("h1".to_string(), 7, Some(CHAPEL_MAP_ID), t0);
        let mut writes = 0;
        for frame in 1..=3u64 {
            assert_eq!(
                run.write_frame(true, t0 + ms(16 * frame), |_| {
                    writes += 1;
                    true
                }),
                None
            );
        }
        assert_eq!(writes, 0);
        assert!(!run.is_planned());
        // An empty plan is complete at once.
        run.set_plan(Vec::new());
        assert_eq!(
            run.write_frame(true, t0 + ms(64), |_| panic!("nothing to write")),
            Some(ApplyEnd::Complete)
        );
    }

    #[test]
    fn a_loading_screen_stops_the_writes_for_good() {
        let t0 = Instant::now();
        // During the writes: the map goes away, then comes back.
        let mut run = run_of(40, t0);
        run.observe(Some(CHAPEL_MAP_ID));
        assert_eq!(run.write_frame(true, t0 + ms(16), |_| true), None);
        run.observe(None);
        run.observe(Some(CHAPEL_MAP_ID));
        assert_eq!(
            run.write_frame(true, t0 + ms(32), |_| panic!("written after a load")),
            Some(ApplyEnd::MapChanged)
        );
        assert_eq!(run.written().graces, APPLY_WRITES_PER_FRAME);
        assert_eq!(run.left(), 40 - APPLY_WRITES_PER_FRAME);

        // While the plan was read: nothing is ever written.
        let mut run = ApplyRun::new("h1".to_string(), 7, Some(CHAPEL_MAP_ID), t0);
        run.observe(Some(0x3C2C_2400));
        run.observe(Some(CHAPEL_MAP_ID));
        run.set_plan(vec![ApplyStep::Grace(71_190)]);
        assert_eq!(
            run.write_frame(true, t0 + ms(16), |_| panic!("written after a load")),
            Some(ApplyEnd::MapChanged)
        );

        // No map at the ask: nothing to compare with, nothing written.
        let mut run = ApplyRun::new("h1".to_string(), 7, None, t0);
        run.set_plan(vec![ApplyStep::Grace(71_190)]);
        assert_eq!(
            run.write_frame(true, t0 + ms(16), |_| panic!("written with no map")),
            Some(ApplyEnd::MapChanged)
        );
    }

    #[test]
    fn the_writes_stop_at_the_deadline() {
        let t0 = Instant::now();
        let mut run = run_of(40, t0);
        assert_eq!(
            run.write_frame(true, t0 + APPLY_DEADLINE - ms(1), |_| true),
            None
        );
        assert_eq!(
            run.write_frame(true, t0 + APPLY_DEADLINE, |_| panic!("written late")),
            Some(ApplyEnd::Deadline)
        );
        assert_eq!(run.left(), 40 - APPLY_WRITES_PER_FRAME);
        // The deadline answers before the machine gives the apply up.
        assert!(APPLY_DEADLINE < APPLY_ABANDON);
    }

    #[test]
    fn a_take_no_longer_applying_stops_the_writes() {
        let t0 = Instant::now();
        let mut run = run_of(40, t0);
        assert_eq!(run.write_frame(true, t0 + ms(16), |_| true), None);
        assert_eq!(
            run.write_frame(false, t0 + ms(32), |_| panic!("written for nobody")),
            Some(ApplyEnd::NotWanted)
        );
        // The end holds even if the take were wanted again.
        assert_eq!(
            run.write_frame(true, t0 + ms(48), |_| panic!("written after the end")),
            Some(ApplyEnd::NotWanted)
        );
    }
}
