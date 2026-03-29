/**
 * Format a datetime string as a relative time label.
 * Returns "just now", "5m ago", "2h ago", "3d ago", or a short date like "Jan 15".
 */
export function timeAgo(dateString: string): string {
  const date = new Date(dateString);
  const now = Date.now();
  const seconds = Math.floor((now - date.getTime()) / 1000);

  if (seconds < 60) return "just now";

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;

  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Pick the best date to represent a race: started_at > scheduled_at > created_at.
 */
export function raceDisplayDate(race: {
  started_at: string | null;
  scheduled_at: string | null;
  created_at: string;
  status: string;
}): string {
  if (race.started_at) return timeAgo(race.started_at);
  if (race.scheduled_at && race.status === "setup")
    return formatScheduledTime(race.scheduled_at);
  return timeAgo(race.created_at);
}

/**
 * Format a future datetime as a relative or absolute label.
 * Returns "In 2h", "Tomorrow at 8:00 PM", or "Feb 18 at 8:00 PM".
 */
export function formatScheduledTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();

  if (date.getTime() - now.getTime() <= 0) return "Now";

  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const isTomorrow =
    date.getFullYear() === tomorrow.getFullYear() &&
    date.getMonth() === tomorrow.getMonth() &&
    date.getDate() === tomorrow.getDate();

  const timeStr = date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });

  if (isToday) return `Today, ${timeStr}`;
  if (isTomorrow) return `Tomorrow, ${timeStr}`;

  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
