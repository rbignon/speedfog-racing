/**
 * Layout decisions for `ChatSidebar`.
 *
 * Pure logic kept out of the component so the rules can be unit-tested
 * directly. The component renders whatever this helper returns.
 *
 * Mirrors the public-channel access matrix in the "Chat System" section
 * of `docs/PROTOCOL.md`. The frontend is not authoritative on access;
 * the server enforces the same matrix and silently drops sends or
 * history loads that violate it. This helper only chooses what to
 * display.
 */

export type PublicAccess = "locked" | "readable";

export type ChatTab = "participants" | "public";

export interface ChatSidebarInputs {
  publicAccess: PublicAccess;
  participantsAccess: boolean;
  /** When true the participants tab is hidden even if the viewer has
   * access (Daily Seeds use this to keep the UI single-pane). The
   * publicAccess lock still applies. */
  showPublicOnly?: boolean;
  /** Active tab as decided by the parent. We may override it (forcing
   * "public") when participants is unavailable. */
  activeTab: ChatTab;
}

export interface ChatSidebarLayout {
  /** Whether to render the two-tab bar. False yields a single "Chat" pane. */
  showTabs: boolean;
  /** Tab the user is effectively viewing after access constraints. */
  effectiveTab: ChatTab;
  /** True when the active pane should render the locked empty state
   * (no messages, no input) instead of the chat panel. */
  showLockedPane: boolean;
  /** True when the public tab in the tab bar is shown but disabled. */
  publicTabDisabled: boolean;
}

export function chatSidebarLayout(
  inputs: ChatSidebarInputs,
): ChatSidebarLayout {
  const showTabs = inputs.participantsAccess && !inputs.showPublicOnly;

  // Without the participants tab the only meaningful active tab is "public".
  const effectiveTab: ChatTab = showTabs ? inputs.activeTab : "public";

  const publicLocked = inputs.publicAccess === "locked";
  const showLockedPane = effectiveTab === "public" && publicLocked;
  const publicTabDisabled = showTabs && publicLocked;

  return { showTabs, effectiveTab, showLockedPane, publicTabDisabled };
}
