import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  TRANSITION_DURATION_MS,
  CASCADE_STEP_MS,
  spawnDelayMs,
  planRowMutation,
  shouldAnimateListMutation,
  isNonVirtualInfoView,
  adaptiveOverscanRows,
} = require("../../debripod/static/js/row-transitions.js");

test("keyed replacement identifies retained, inserted, removed, and selection", () => {
  const plan = planRowMutation(
    [{key: "a"}, {key: "b"}, {key: "c"}],
    [{key: "a"}, {key: "x"}, {key: "c"}],
    (item) => item.key,
    "c",
  );
  assert.deepEqual(plan.retained.map((row) => row.key), ["a", "c"]);
  assert.deepEqual(plan.inserted.map((row) => row.key), ["x"]);
  assert.deepEqual(plan.removed.map((row) => row.key), ["b"]);
  assert.equal(plan.selectionIndex, 2);
});

test("row transition duration matches path and info pills", () => {
  assert.equal(TRANSITION_DURATION_MS, 220);
});

test("new rows cascade from top to bottom", () => {
  assert.equal(spawnDelayMs(0), 0);
  assert.equal(spawnDelayMs(1), CASCADE_STEP_MS);
  assert.ok(spawnDelayMs(12) > spawnDelayMs(4));
  assert.equal(spawnDelayMs(4, {reducedMotion: true}), 0);
});

test("reduced motion bypasses intermediate animation state", () => {
  const plan = planRowMutation([], [{key: "a"}], (item) => item.key, "", {reducedMotion: true});
  assert.equal(plan.animate, false);
});

test("page transitions animate rendered rows even for a 2100-item logical dataset", () => {
  assert.equal(shouldAnimateListMutation(2100, 2100, 2100, {reason: "page load"}), true);
  assert.equal(shouldAnimateListMutation(2100, 2100, 2100, {reason: "queue refresh"}), false);
  assert.equal(shouldAnimateListMutation(32, 2, 32, {reason: "page load"}), true);
});

test("virtualization policy excludes root and info pages but accepts arbitrary library subpages", () => {
  for(const kind of ["roots", "libinfo", "media_information", "settings_library", "account_profile", "range_editor_input"]){
    assert.equal(isNonVirtualInfoView(kind), true, kind);
  }
  for(const kind of ["albums", "folders", "custom_library_subpage", "Queue", "History"]){
    assert.equal(isNonVirtualInfoView(kind), false, kind);
  }
});

test("adaptive overscan stays small at rest and bounded at scroll velocity", () => {
  const idle = adaptiveOverscanRows(560, 56, 0);
  assert.ok(idle >= 2 && idle <= 4);
  assert.ok(adaptiveOverscanRows(560, 56, 0.01) <= 16);
  assert.ok(adaptiveOverscanRows(560, 56, 99) >= 15);
});
