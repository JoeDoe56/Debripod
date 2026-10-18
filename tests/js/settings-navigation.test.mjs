import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const settings = fs.readFileSync("debripod/static/js/settings-ui.js", "utf8");
const lists = fs.readFileSync("debripod/static/js/list-view.js", "utf8");

function functionSource(source, name) {
  const match = source.match(new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n  \\}`));
  assert.ok(match, `${name} is available`);
  return match[0];
}

test("glass quality cycles every preset and stays in advanced glass settings", async () => {
  const levels = ["auto", "superfluid", "glass", "lite", "frost", "static"];
  const destinations = [];
  let saves = 0;
  let invalidations = 0;
  const root = {uiSettings: {GLASS_QUALITY_LEVELS: levels}, glass: {instance: {invalidate: () => invalidations++}}};
  const context = {
    state: {}, uiSettings: {glassQuality: "auto"}, window: {DebriPod: root}, DebriPod: root,
    saveUiSettings: () => saves++,
    viewLibAdvancedCategory: async (category, push) => destinations.push([category, push]),
    viewLibUiSettings: () => assert.fail("glass quality must not open Visualizer"),
  };
  vm.runInNewContext(functionSource(settings, "handleLibUiAction"), context);
  for (const expected of [...levels.slice(1), "auto"]) {
    assert.equal(await context.handleLibUiAction("cycle_glass_quality"), true);
    assert.equal(context.uiSettings.glassQuality, expected);
  }
  assert.deepEqual(destinations, levels.map(() => ["glass", false]));
  assert.equal(saves, levels.length);
  assert.equal(invalidations, levels.length);
});

function navigationFixture(current) {
  const scrollWrites = [];
  let scrollTop = 430;
  const list = {
    get scrollTop() { return scrollTop; },
    set scrollTop(value) { scrollWrites.push(value); scrollTop = value; },
  };
  const root = {listScroll: {cancel() {}}};
  const context = {
    state: {current, history: [], sel: 9, items: [], pageAnchorOffset: 72, pageAnchorBottomSlack: 84},
    libList: list, DebriPod: root, window: {DebriPod: root}, performance: {now: () => 0},
    selectedRowViewportY: () => 137, cancelLibListScroll() {}, setHeader() {},
    virtualItemIdentity: (item) => item.action || item.key || item.label,
    replaceListItems(items, options) {
      assert.equal(options.preserveEntryAnchor, true, "refresh must not schedule selection scrolling");
      context.state.items = items;
      context.state.sel = options.selectionIndex;
    },
  };
  vm.runInNewContext(["settingsViewIdentity", "snapshotListState", "resetList", "setView"].map(name => functionSource(lists, name)).join("\n"), context);
  return {context, scrollWrites};
}

const settingsViews = [
  {kind: "libadvancedcategory", advancedCategory: "glass"},
  {kind: "libadvancedcategory", advancedCategory: "animations"},
  {kind: "libadvancedcategory", advancedCategory: "system"},
  {kind: "libuisettings", label: "Visualizer"},
  {kind: "settings_category", category: "playback"},
  {kind: "settings_category", category: "services"},
  {kind: "settings_category", category: "downloads"},
  {kind: "settings_torrent_sources"},
  {kind: "account_settings"},
  {kind: "settings_library"},
];

for (const descriptor of settingsViews) {
  test(`settings refresh preserves selection, scroll and spacers: ${JSON.stringify(descriptor)}`, async () => {
    const {context, scrollWrites} = navigationFixture({...descriptor});
    const items = Array.from({length: 20}, (_, i) => ({key: `setting-${i}`}));
    await context.setView({...descriptor, load: async () => context.resetList(items)}, false);
    assert.equal(context.state.sel, 9);
    assert.equal(context.libList.scrollTop, 430);
    assert.equal(context.state.pageAnchorOffset, 72);
    assert.equal(context.state.pageAnchorBottomSlack, 84);
    assert.ok(scrollWrites.every(value => value === 430), "refresh must never reset scroll to zero");
    assert.equal(context.state.history.length, 0);
    // A subsequent edit must use the latest position, rather than the first snapshot.
    context.state.sel = 13;
    context.libList.scrollTop = 650;
    await context.setView({...descriptor, load: async () => context.resetList(items)}, false);
    assert.equal(context.state.sel, 13);
    assert.equal(context.libList.scrollTop, 650);
  });
}

test("returning from a text editor restores and consumes the parent's position", async () => {
  const parent = {kind: "settings_category", category: "services", savedSel: 12, savedScroll: 615,
    savedPageAnchorOffset: 42, savedPageAnchorBottomSlack: 60};
  const {context} = navigationFixture({kind: "settings_editor"});
  context.state.history.push({kind: "libinfo"}, parent);
  const items = Array.from({length: 20}, (_, i) => ({key: `setting-${i}`}));
  await context.setView({kind: parent.kind, category: parent.category, load: async () => context.resetList(items)}, false);
  assert.equal(context.state.sel, 12);
  assert.equal(context.libList.scrollTop, 615);
  assert.equal(context.state.pageAnchorOffset, 42);
  assert.equal(context.state.history.length, 1);
});

test("settings Back restores its saved position even when the child has a different anchor", () => {
  const {context} = navigationFixture({kind: "libadvancedcategory", advancedCategory: "glass", savedSel: 8,
    savedScroll: 370, savedPageAnchorOffset: 20, savedPageAnchorBottomSlack: 52});
  context.resetList(Array.from({length: 15}, (_, i) => ({key: `setting-${i}`})));
  assert.equal(context.state.sel, 8);
  assert.equal(context.libList.scrollTop, 370);
  assert.equal(context.state.pageAnchorOffset, 20);
});

test("refresh clamps selection when settings rows disappear", async () => {
  const {context} = navigationFixture({kind: "settings_library"});
  await context.setView({kind: "settings_library", load: async () => context.resetList([{key: "add"}])}, false);
  assert.equal(context.state.sel, 0);
});

test("new settings categories and ordinary library pages do not inherit refresh positions", async () => {
  const {context} = navigationFixture({kind: "libadvancedcategory", advancedCategory: "glass"});
  const other = {kind: "libadvancedcategory", advancedCategory: "animations", load: async () => {}};
  await context.setView(other, true);
  assert.equal(other.savedScroll, undefined);
  assert.equal(other.entryAnchorY, 137);
  assert.equal(context.state.history.length, 1);
  const library = {kind: "metalist", label: "Albums", load: async () => {}};
  context.state.current = {...library};
  await context.setView(library, false);
  assert.equal(library.savedSel, undefined);
  assert.equal(context.settingsViewIdentity(library), "");
});
