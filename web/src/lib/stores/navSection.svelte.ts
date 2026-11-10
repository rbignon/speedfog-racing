/**
 * Lets a page claim the navbar's Speedrun item when its path alone does not
 * say it belongs there: a speedrun or Set Seed race lives under /race, a
 * ranked solo session under /training. The page sets it while it shows such
 * a run and clears it when it goes away.
 */

let speedrun = $state(false);

export const navSection = {
  get speedrun() {
    return speedrun;
  },
  set speedrun(value: boolean) {
    speedrun = value;
  },
};
