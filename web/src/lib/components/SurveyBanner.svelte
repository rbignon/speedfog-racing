<script lang="ts">
  const STORAGE_KEY = "speedfog_survey_banner_dismissed";
  const SURVEY_URL = "https://forms.gle/H9Y969Y6YsddRgeb6";

  let dismissed = $state(
    typeof localStorage !== "undefined" &&
      localStorage.getItem(STORAGE_KEY) === "1",
  );

  function dismiss() {
    dismissed = true;
    localStorage.setItem(STORAGE_KEY, "1");
  }
</script>

{#if !dismissed}
  <div class="survey-banner" data-testid="survey-banner">
    <span class="survey-banner-icon">&#128221;</span>
    <p class="survey-banner-text">
      Help shape SpeedFog. Take the 2-minute survey to share your feedback.
    </p>
    <a
      class="btn btn-primary"
      href={SURVEY_URL}
      target="_blank"
      rel="noopener noreferrer"
      onclick={dismiss}
    >
      Open survey
    </a>
    <button class="survey-banner-close" onclick={dismiss} aria-label="Dismiss"
      >&times;</button
    >
  </div>
{/if}

<style>
  .survey-banner {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    border-left: 3px solid var(--color-info);
    border-radius: var(--radius-sm);
    margin-bottom: 1rem;
  }

  .survey-banner-icon {
    font-size: 1.25rem;
  }

  .survey-banner-text {
    flex: 1;
    margin: 0;
    color: var(--color-text);
  }

  .survey-banner-close {
    background: none;
    border: none;
    font-size: 1.5rem;
    line-height: 1;
    color: var(--color-text-secondary);
    cursor: pointer;
    padding: 0 0.25rem;
  }

  .survey-banner-close:hover {
    color: var(--color-text);
  }
</style>
