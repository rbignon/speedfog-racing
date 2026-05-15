import { describe, expect, it, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import SurveyBanner from "$lib/components/SurveyBanner.svelte";

const STORAGE_KEY = "speedfog_survey_banner_dismissed";

describe("SurveyBanner", () => {
  beforeEach(() => {
    localStorage.removeItem(STORAGE_KEY);
  });

  it("hides the banner and persists the flag after dismiss is clicked", async () => {
    const { container } = render(SurveyBanner);
    const banner = container.querySelector('[data-testid="survey-banner"]');
    expect(banner).not.toBeNull();

    const closeBtn = container.querySelector(
      ".survey-banner-close",
    ) as HTMLButtonElement;
    await fireEvent.click(closeBtn);

    expect(container.querySelector('[data-testid="survey-banner"]')).toBeNull();
    expect(localStorage.getItem(STORAGE_KEY)).toBe("1");
  });

  it("renders nothing when the dismissed flag is already set", () => {
    localStorage.setItem(STORAGE_KEY, "1");
    const { container } = render(SurveyBanner);
    expect(container.querySelector('[data-testid="survey-banner"]')).toBeNull();
  });

  it("dismisses the banner when the survey link is clicked", async () => {
    const { container } = render(SurveyBanner);
    const link = container.querySelector(
      ".survey-banner a.btn-primary",
    ) as HTMLAnchorElement;
    expect(link).not.toBeNull();

    // Prevent jsdom from trying to navigate when the click bubbles.
    link.addEventListener("click", (e) => e.preventDefault());
    await fireEvent.click(link);

    expect(container.querySelector('[data-testid="survey-banner"]')).toBeNull();
    expect(localStorage.getItem(STORAGE_KEY)).toBe("1");
  });
});
