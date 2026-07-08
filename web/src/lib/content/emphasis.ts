export interface TextSegment {
  text: string;
  bold: boolean;
}

/**
 * Splits a content string on `**` markers into plain/bold segments, so
 * catalog text can carry emphasis without HTML injection or a markdown
 * dependency. Markers are expected balanced (enforced by the catalog
 * invariant tests); a dangling marker is rendered literally.
 */
export function parseEmphasis(text: string): TextSegment[] {
  const parts = text.split("**");
  if (parts.length % 2 === 0) {
    const dangling = parts.pop() ?? "";
    parts[parts.length - 1] += "**" + dangling;
  }
  return parts
    .map((part, i) => ({ text: part, bold: i % 2 === 1 }))
    .filter((segment) => segment.text.length > 0);
}
