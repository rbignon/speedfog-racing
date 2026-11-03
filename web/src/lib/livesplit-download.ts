import { fetchLiveSplitCategory, fetchSpeedrunSeed } from "$lib/api";
import { categoryLssFile, downloadLss, seedLssFile } from "$lib/livesplit";

/** Download the seed file of a played seed. `viewerId` picks the PB run. */
export async function downloadSeedSplits(
  seedNumber: string,
  viewerId: string | null,
): Promise<void> {
  const seed = await fetchSpeedrunSeed(seedNumber);
  const file = seedLssFile(seed, viewerId);
  if (!file) throw new Error("This seed's map is not public yet.");
  downloadLss(file);
}

/** Download the category file. `totalLayers` is the page's own layer count
 * when it has one; the endpoint's is the fallback. */
export async function downloadCategorySplits(
  category: string,
  totalLayers: number | null,
): Promise<void> {
  const info = await fetchLiveSplitCategory(category);
  const layers = totalLayers ?? info.total_layers;
  if (layers === null) {
    throw new Error("This category's layer count is not known yet.");
  }
  const layerEntries = (
    r: { layer_entry_igts: Record<string, number> } | null,
  ) => r?.layer_entry_igts ?? null;
  downloadLss(
    categoryLssFile(
      info.category,
      info.category_name,
      layers,
      layerEntries(info.wr),
      layerEntries(info.pb),
    ),
  );
}
