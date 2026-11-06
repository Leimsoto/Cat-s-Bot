/** Suspense can retain outgoing effects while the next lazy module is loading. */
export function retireDrafts(registry, retiredIds) {
  for (const id of registry.keys()) retiredIds.add(id);
  registry.clear();
}
export function summarizeDrafts(entries) {
  const drafts = [...entries];
  return {
    dirty: drafts.some((draft) => draft.dirty),
    saving: drafts.some((draft) => draft.saving),
    canSave: drafts.filter((draft) => draft.dirty).every((draft) => typeof draft.onSave === "function"),
  };
}
/** Wait for the module's committed save state; legacy handlers may swallow errors. */
export async function saveBeforeLeaving(save, readStatus) {
  if (readStatus().saving || typeof save !== "function") return false;
  try {
    await save();
    for (let frame = 0; frame < 25; frame += 1) {
      await new Promise((resolve) => setTimeout(resolve, 20));
      const status = readStatus();
      if (!status.dirty && !status.saving) return true;
    }
  } catch {
    // Keep the draft and the current panel when saving fails.
  }
  return false;
}
