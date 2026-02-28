/**
 * Copy text to clipboard with fallback for non-secure contexts (e.g. LAN IP over HTTP).
 * Uses navigator.clipboard when available, falls back to execCommand('copy').
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Secure context required — fall through to fallback
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  try {
    textarea.select();
    return document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }
}
