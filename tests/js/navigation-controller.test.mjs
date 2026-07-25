import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {createSpecialNavigationModel} = require("../../debripod/static/js/navigation-controller.js");

function origin(label = "Albums") {
  return {
    current: {kind: "metalist", label, level: "albums", value: ""},
    selectionIndex: 7,
    scrollTop: 128,
    history: [{kind: "metatop", label: "Library"}],
    search: {q: "test", results: [{id: 1}]},
  };
}

test("ordinary -> now playing -> queue unwinds finitely", () => {
  const nav = createSpecialNavigationModel();
  nav.open("now_playing", origin());
  nav.open("queue");
  assert.deepEqual(nav.snapshot().stack.map((entry) => entry.kind), ["now_playing", "queue"]);
  assert.equal(nav.back().kind, "special");
  assert.equal(nav.snapshot().stack.at(-1).kind, "now_playing");
  const result = nav.back();
  assert.equal(result.kind, "origin");
  assert.equal(result.origin.selectionIndex, 7);
  assert.deepEqual(nav.snapshot().stack, []);
  assert.equal(nav.snapshot().origin, null);
});

test("ordinary -> now playing -> history unwinds finitely", () => {
  const nav = createSpecialNavigationModel();
  nav.open("now_playing", origin("Songs"));
  nav.open("history");
  assert.equal(nav.back().entry.kind, "now_playing");
  assert.equal(nav.back().origin.current.label, "Songs");
});

test("opening the active special page does not duplicate it", () => {
  const nav = createSpecialNavigationModel();
  nav.open("queue", origin());
  nav.open("queue");
  assert.deepEqual(nav.snapshot().stack.map((entry) => entry.kind), ["queue"]);
});

test("jump clears both stack and origin", () => {
  const nav = createSpecialNavigationModel();
  nav.open("now_playing", origin());
  nav.open("queue");
  nav.clear();
  assert.deepEqual(nav.snapshot().stack, []);
  assert.equal(nav.snapshot().origin, null);
});
