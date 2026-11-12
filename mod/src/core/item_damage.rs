//! Damage curve of the race items that hurt (Red Shell, Banana).
//!
//! With h = 100 * hp / max_hp: at or above `floor + base` the hit costs `base`% of
//! max; at or above `floor + tail` it lands exactly on `floor`% of max; below that
//! it costs `tail`% of max. At least 1 HP always remains. HP above the max (a
//! max just lowered, the HP not lowered to it yet) counts as the max.

/// New HP after one damaging item.
pub fn damaged_hp(hp: i32, max_hp: i32, base_pct: u8, floor_pct: u8, tail_pct: u8) -> i32 {
    if max_hp <= 0 || hp <= 0 {
        return hp;
    }
    let (hp64, max) = (hp.min(max_hp) as i64, max_hp as i64);
    let (base, floor, tail) = (base_pct as i64, floor_pct as i64, tail_pct as i64);
    // h >= x  <=>  100 * hp >= x * max
    let at_least = |pct: i64| hp64 * 100 >= pct * max;
    let new_hp = if at_least(floor + base) {
        hp64 - max * base / 100
    } else if at_least(floor + tail) {
        max * floor / 100
    } else {
        hp64 - max * tail / 100
    };
    new_hp.clamp(1, hp64) as i32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn red_shell_series_from_full() {
        let mut hp = 1000;
        let mut series = vec![hp];
        for _ in 0..9 {
            hp = damaged_hp(hp, 1000, 20, 20, 5);
            series.push(hp);
        }
        assert_eq!(series, [1000, 800, 600, 400, 200, 150, 100, 50, 1, 1]);
    }

    #[test]
    fn banana_lands_on_the_floor() {
        assert_eq!(damaged_hp(270, 1000, 10, 20, 5), 200);
        assert_eq!(damaged_hp(300, 1000, 10, 20, 5), 200);
        assert_eq!(damaged_hp(310, 1000, 10, 20, 5), 210);
    }

    #[test]
    fn damage_never_kills() {
        assert_eq!(damaged_hp(1, 1000, 20, 20, 5), 1);
        assert_eq!(damaged_hp(30, 1000, 20, 20, 5), 1);
    }

    #[test]
    fn uses_the_given_max() {
        // Blue Shell halved the max: full bar of 500 loses 20% of 500.
        assert_eq!(damaged_hp(500, 500, 20, 20, 5), 400);
    }

    #[test]
    fn hp_above_a_just_lowered_max_counts_as_a_full_bar() {
        // A Blue Shell just halved the max; the game has not lowered the HP
        // to it yet.
        assert_eq!(damaged_hp(1000, 500, 20, 20, 5), 400);
        assert_eq!(damaged_hp(1000, 500, 10, 20, 5), 450);
    }

    #[test]
    fn unreadable_values_are_untouched() {
        assert_eq!(damaged_hp(500, 0, 20, 20, 5), 500);
        assert_eq!(damaged_hp(0, 1000, 20, 20, 5), 0);
    }
}
