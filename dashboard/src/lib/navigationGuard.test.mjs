import assert from "node:assert/strict";
import { retireDrafts, saveBeforeLeaving, summarizeDrafts } from "./navigationGuard.js";
let status = { dirty: true, saving: false };
assert.equal(await saveBeforeLeaving(async () => { status = { dirty: false, saving: false }; }, () => status), true);
status = { dirty: true, saving: false };
assert.equal(await saveBeforeLeaving(async () => {}, () => status), false, "A swallowed save error must retain the draft");
assert.equal(await saveBeforeLeaving(async () => { throw new Error("Failed"); }, () => status), false);
status = { dirty: true, saving: true };
let called = false;
assert.equal(await saveBeforeLeaving(() => { called = true; }, () => status), false);
assert.equal(called, false, "Do not start another save while saving");

const drafts = new Map([
  ["channel-config", { dirty: true, saving: false, onSave: () => {} }],
  ["nested-schedule", { dirty: false, saving: false, onSave: () => {} }],
]);
assert.equal(summarizeDrafts(drafts.values()).dirty, true, "A clean child must not replace a dirty parent");
drafts.delete("nested-schedule");
assert.equal(summarizeDrafts(drafts.values()).dirty, true, "Unmounting a child must retain the parent draft");
drafts.set("nested-schedule", { dirty: true, saving: true, onSave: () => {} });
assert.equal(summarizeDrafts(drafts.values()).saving, true, "Any saving child blocks navigation");
drafts.set("nested-schedule", { dirty: true, saving: false, onSave: () => {} });
assert.equal(await saveBeforeLeaving(async () => { drafts.get("channel-config").dirty = false; }, () => summarizeDrafts(drafts.values())), false, "A partial save must keep the remaining draft on screen");
drafts.set("composer", { dirty: true, saving: false });
assert.equal(summarizeDrafts(drafts.values()).canSave, false, "A publication-only draft must not offer Save");
const retiredIds = new Set();
retireDrafts(drafts, retiredIds);
assert.equal(summarizeDrafts(drafts.values()).dirty, false, "Confirmed departure clears outgoing drafts before lazy cleanup");
assert.equal(retiredIds.has("nested-schedule"), true, "Outgoing IDs stay retired until their effects unmount");
assert.equal(retiredIds.has("new-ticket-module"), false, "A new module can register immediately");
console.log("Navigation guard: 12 cases passed");
