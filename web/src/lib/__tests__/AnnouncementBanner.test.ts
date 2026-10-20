import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import AnnouncementBanner from "$lib/components/AnnouncementBanner.svelte";

const BANNER = '[data-testid="announcement-banner"]';

beforeEach(() => {
  localStorage.clear();
});

describe("AnnouncementBanner", () => {
  it("dismissing hides the banner and survives a remount", async () => {
    const first = render(AnnouncementBanner, { text: "Notice A", url: null });
    await fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(first.container.querySelector(BANNER)).toBeNull();
    first.unmount();

    const second = render(AnnouncementBanner, { text: "Notice A", url: null });
    expect(second.container.querySelector(BANNER)).toBeNull();
  });

  it("a different message reappears after an older one was dismissed", async () => {
    const first = render(AnnouncementBanner, { text: "Notice A", url: null });
    await fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    first.unmount();

    const second = render(AnnouncementBanner, { text: "Notice B", url: null });
    expect(second.container.querySelector(BANNER)).not.toBeNull();
  });

  it("a configured label replaces Read more, which is the fallback", () => {
    const custom = render(AnnouncementBanner, {
      text: "Notice",
      url: "/help",
      linkText: "What to do",
    });
    expect(screen.getByRole("link", { name: "What to do" })).not.toBeNull();
    expect(screen.queryByRole("link", { name: "Read more" })).toBeNull();
    custom.unmount();

    render(AnnouncementBanner, {
      text: "Notice",
      url: "/help",
      linkText: null,
    });
    expect(screen.getByRole("link", { name: "Read more" })).not.toBeNull();
  });
});
