//! Race item equip load effect: the max equip load rate that brings the
//! player's current load to a set share of the max, and where the weight of
//! each equipped item lives. The shell reads the equipped items and their
//! weights, then writes the rate into the effect's SpEffect row before
//! applying it.

/// Number of ChrAsm equipment slots (`equipment_param_ids`).
pub const EQUIP_SLOTS: usize = 22;

/// The equipment param a slot's item weight is read from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EquipParam {
    Weapon,
    Protector,
    Accessory,
}

/// The param and row holding the weight of the item in ChrAsm slot `slot`
/// (fromsoftware-rs `ChrAsmSlot` order: 6 weapons, 6 arrows and bolts, 4
/// armor pieces, an unused slot, 5 talismans), or `None` for an empty slot
/// or one left out of the load. A weapon id carries its upgrade level in the
/// last two digits; the row (base weapon plus affinity) drops it. Arrows and
/// bolts are left out: their param weight is not a load weight (10 for plain
/// Arrows).
pub fn weight_row(slot: usize, param_id: i32) -> Option<(EquipParam, u32)> {
    let id = u32::try_from(param_id).ok()?;
    match slot {
        0..=5 => Some((EquipParam::Weapon, id - id % 100)),
        12..=15 => Some((EquipParam::Protector, id)),
        17..=21 => Some((EquipParam::Accessory, id)),
        _ => None,
    }
}

/// The max equip load rate that puts `current` at `load_pct` percent of
/// `max`. 1.0 (no change) when the load already reaches that share, or when
/// a value is not a positive finite number (an unreadable or naked
/// character).
pub fn load_rate(current: f32, max: f32, load_pct: u8) -> f32 {
    let usable = |v: f32| v.is_finite() && v > 0.0;
    if !(usable(current) && usable(max)) || load_pct == 0 {
        return 1.0;
    }
    (current / (max * f32::from(load_pct) / 100.0)).min(1.0)
}

/// The max load to compute a new rate from. An active effect points at its
/// SpEffect row, so the max read while one runs already includes the rate
/// written last: when `max` is that `(base, rate)` product, the base;
/// otherwise (no effect running, or the max changed since) `max` itself. A
/// max that changes while an effect runs (a talisman swap) is taken as read,
/// so the new rate comes out too high and weakens that effect: rare, and
/// never heavier than intended.
pub fn base_max(max: f32, last: Option<(f32, f32)>) -> f32 {
    match last {
        Some((base, rate)) if (max - base * rate).abs() <= max.abs() * 1e-3 => base,
        _ => max,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rate_brings_the_load_to_the_share() {
        let rate = load_rate(32.0, 49.8, 97);
        assert!((32.0 / (49.8 * rate) - 0.97).abs() < 1e-4);
        assert!((load_rate(10.0, 50.0, 50) - 0.4).abs() < 1e-6);
    }

    #[test]
    fn load_already_at_the_share_is_left_alone() {
        assert_eq!(load_rate(49.0, 50.0, 97), 1.0);
        assert_eq!(load_rate(60.0, 50.0, 97), 1.0);
    }

    #[test]
    fn missing_values_change_nothing() {
        assert_eq!(load_rate(0.0, 50.0, 97), 1.0);
        assert_eq!(load_rate(10.0, 0.0, 97), 1.0);
        assert_eq!(load_rate(f32::NAN, 50.0, 97), 1.0);
        assert_eq!(load_rate(10.0, f32::INFINITY, 97), 1.0);
        assert_eq!(load_rate(10.0, 50.0, 0), 1.0);
    }

    #[test]
    fn a_running_effect_is_seen_through_to_its_base() {
        let rate = load_rate(32.0, 49.8, 97);
        let running = 49.8 * rate;
        assert_eq!(base_max(running, Some((49.8, rate))), 49.8);
        // A second hit while it runs computes the same rate, not 1.0.
        let again = load_rate(32.0, base_max(running, Some((49.8, rate))), 97);
        assert!((again - rate).abs() < 1e-6);
    }

    #[test]
    fn an_ended_or_changed_max_is_taken_as_read() {
        let rate = load_rate(32.0, 49.8, 97);
        assert_eq!(base_max(49.8, Some((49.8, rate))), 49.8);
        assert_eq!(base_max(60.0, Some((49.8, rate))), 60.0);
        assert_eq!(base_max(49.8, None), 49.8);
    }

    #[test]
    fn weapon_rows_drop_the_upgrade_level() {
        // Longsword +12 (base 2000000), Heavy Longsword +5 (affinity 100).
        assert_eq!(
            weight_row(1, 2_000_012),
            Some((EquipParam::Weapon, 2_000_000))
        );
        assert_eq!(
            weight_row(4, 2_000_105),
            Some((EquipParam::Weapon, 2_000_100))
        );
        // Arrows and bolts are not counted.
        assert_eq!(weight_row(6, 50_000_000), None);
        assert_eq!(weight_row(11, 52_000_000), None);
    }

    #[test]
    fn armor_talismans_and_empty_slots() {
        assert_eq!(
            weight_row(13, 40_100),
            Some((EquipParam::Protector, 40_100))
        );
        assert_eq!(weight_row(20, 1_000), Some((EquipParam::Accessory, 1_000)));
        assert_eq!(weight_row(17, -1), None);
        assert_eq!(weight_row(16, 0), None);
        assert_eq!(weight_row(EQUIP_SLOTS, 1_000), None);
    }
}
