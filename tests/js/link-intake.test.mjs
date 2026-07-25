import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {classifyLinkIntake, parseDeepLinks} = require("../../debripod/static/js/link-intake.js");

test("classifies magnets only when an info hash exists", () => {
  assert.equal(classifyLinkIntake("magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"), "magnet");
  assert.equal(classifyLinkIntake("magnet:?dn=missing-hash"), "query");
});

test("passes every HTTP or HTTPS link to yt-dlp inspection", () => {
  assert.equal(classifyLinkIntake("https://example.invalid/media/1"), "ytdlp_url");
  assert.equal(classifyLinkIntake("http://localhost/video"), "ytdlp_url");
  assert.equal(classifyLinkIntake("ftp://example.invalid/file"), "query");
});

test("ordinary text remains a query", () => {
  assert.equal(classifyLinkIntake("artist album"), "query");
});

test("deep links preserve exact task and intake values", () => {
  assert.deepEqual(parseDeepLinks("?task=0&intake=https%3A%2F%2Fexample.com%2Fv"), {
    task: "0",
    intake: "https://example.com/v",
  });
});
