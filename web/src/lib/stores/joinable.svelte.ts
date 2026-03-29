/**
 * Reactive trigger for re-fetching the joinable races count.
 * Call invalidate() after join/leave actions to update the navbar badge.
 */

let refreshKey = $state(0);

export const joinableStore = {
  get refreshKey() {
    return refreshKey;
  },
  invalidate() {
    refreshKey++;
  },
};
