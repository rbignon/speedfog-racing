<script lang="ts">
  import type { User } from "$lib/api";
  import { rewards } from "$lib/stores/rewards.svelte";

  interface Props {
    user: User;
    showAvatar?: boolean;
    showBadge?: boolean;
  }

  let { user, showAvatar = false, showBadge = false }: Props = $props();

  let displayName = $derived(user.twitch_display_name || user.twitch_username);

  // Resolve the template (null when default/unset/missing). null means "fall
  // back to the surrounding context's color" (e.g. status color in the
  // leaderboard, default body text everywhere else).
  let template = $derived.by(() => {
    const id = user.equipped_name_template_id;
    if (!id || id === "default") return null;
    return rewards.lookupTemplate(id);
  });

  let badge = $derived(
    showBadge ? rewards.lookupBadge(user.equipped_badge_id ?? null) : null,
  );

  let nameStyle = $derived.by(() => {
    const parts: string[] = [];
    if (template?.gradient) {
      parts.push(
        `background: linear-gradient(90deg, ${template.gradient[0]}, ${template.gradient[1]});`,
        "-webkit-background-clip: text;",
        "background-clip: text;",
        "color: transparent;",
        // Italic glyphs slant past the text bounding box, so the gradient
        // would clip the last letter without this padding.
        "padding-inline-end: 0.1em;",
      );
    } else if (template?.color) {
      parts.push(`color: ${template.color};`);
    }
    if (template?.name_css) {
      parts.push(template.name_css);
    }
    return parts.join(" ");
  });

  let nameStyleKind = $derived(
    template?.gradient ? "gradient" : template?.color ? "solid" : "inherit",
  );
</script>

<a href="/user/{user.twitch_username}" class="user-link">
  {#if showAvatar && user.twitch_avatar_url}
    <img src={user.twitch_avatar_url} alt="" class="user-link-avatar" />
  {/if}
  <span class="user-link-name" data-name-style={nameStyleKind} style={nameStyle}
    >{displayName}</span
  >
  {#if badge}
    <img
      src="/badges/{badge.icon_filename}"
      alt={badge.name}
      title={badge.name}
      class="user-link-badge"
    />
  {/if}
</a>

<style>
  .user-link {
    color: inherit;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }

  .user-link:hover .user-link-name {
    text-decoration: underline;
  }

  .user-link-avatar {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    object-fit: cover;
  }

  .user-link-badge {
    width: 18px;
    height: 18px;
    flex-shrink: 0;
  }
</style>
