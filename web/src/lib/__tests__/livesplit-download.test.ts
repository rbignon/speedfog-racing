import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({
  fetchLiveSplitCategory: vi.fn(),
  fetchSpeedrunSeed: vi.fn(),
}));
vi.mock("$lib/livesplit", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/livesplit")>()),
  downloadLss: vi.fn(),
  seedLssFile: vi.fn(),
}));

import { fetchLiveSplitCategory, fetchSpeedrunSeed } from "$lib/api";
import { downloadLss, seedLssFile } from "$lib/livesplit";
import {
  downloadCategorySplits,
  downloadSeedSplits,
} from "$lib/livesplit-download";

function category(totalLayers: number | null) {
  return {
    category: "standard@12",
    category_name: "Standard",
    total_layers: totalLayers,
    wr: null,
    pb: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("downloadCategorySplits", () => {
  it("prefers the page's own layer count over the endpoint's", async () => {
    vi.mocked(fetchLiveSplitCategory).mockResolvedValue(category(10));
    await downloadCategorySplits("standard@12", 12);
    const file = vi.mocked(downloadLss).mock.calls[0][0];
    expect(file.segmentNames).toHaveLength(12);
  });

  it("falls back to the endpoint's count when the page has none", async () => {
    vi.mocked(fetchLiveSplitCategory).mockResolvedValue(category(10));
    await downloadCategorySplits("standard", null);
    const file = vi.mocked(downloadLss).mock.calls[0][0];
    expect(file.segmentNames).toHaveLength(10);
  });

  it("rejects when neither side knows the layer count", async () => {
    vi.mocked(fetchLiveSplitCategory).mockResolvedValue(category(null));
    await expect(downloadCategorySplits("standard", null)).rejects.toThrow(
      /layer/i,
    );
    expect(downloadLss).not.toHaveBeenCalled();
  });
});

describe("downloadSeedSplits", () => {
  const seed = { seed_number: "abc" } as never;

  it("builds the file for the viewer, whose run is the PB", async () => {
    vi.mocked(fetchSpeedrunSeed).mockResolvedValue(seed);
    const file = { seedNumber: "abc" } as never;
    vi.mocked(seedLssFile).mockReturnValue(file);
    await downloadSeedSplits("abc", "u1");
    expect(seedLssFile).toHaveBeenCalledWith(seed, "u1");
    expect(downloadLss).toHaveBeenCalledWith(file);
  });

  it("rejects while the seed's map is not public", async () => {
    vi.mocked(fetchSpeedrunSeed).mockResolvedValue(seed);
    vi.mocked(seedLssFile).mockReturnValue(null);
    await expect(downloadSeedSplits("abc", null)).rejects.toThrow(
      "This seed's map is not public yet.",
    );
    expect(downloadLss).not.toHaveBeenCalled();
  });
});
