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
 * Format a future datetime as a relative or absolute label.
 * Returns "In 2h", "Tomorrow at 8:00 PM", or "Feb 18 at 8:00 PM".
 */
export function formatScheduledTime(dateString: string): string {
  const date = new Date(dateString);
  const now = Date.now();
  const diffMs = date.getTime() - now;

  if (diffMs <= 0) return "Now";

  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "In <1m";
  if (minutes < 60) return `In ${minutes}m`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `In ${hours}h`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
