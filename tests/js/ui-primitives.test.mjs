import assert from "node:assert/strict";
import test from "node:test";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const primitives = require("../../debripod/static/js/ui-primitives.js");

test("normalizes numeric settings against their actual range", () => {
  assert.equal(primitives.normalize(50, 0, 100), .5);
  assert.equal(primitives.normalize(-4, 0, 100), 0);
  assert.equal(primitives.normalize(700, 100, 600), 1);
  assert.deepEqual(primitives.normalizeSetting(150, {min:100, max:200, step:1}), {value:150, min:100, max:200, progress:.5, step:1});
});

test("uses the requested SF Symbols semantic names", () => {
  assert.equal(primitives.symbolDescriptor("next").name, "forward.end.alt.fill");
  assert.equal(primitives.symbolDescriptor("prev").name, "backward.end.alt.fill");
  assert.equal(primitives.symbolDescriptor("like", false).name, "heart");
  assert.equal(primitives.symbolDescriptor("like", true).name, "heart.fill");
  assert.equal(primitives.symbolDescriptor("play", true).name, "playpause.fill");
});

test("strong foreground is bounded at twice the configured opacity", () => {
  assert.equal(primitives.foregroundOpacity(.35, 2), .7);
  assert.equal(primitives.foregroundOpacity(.7, 2), 1);
});
