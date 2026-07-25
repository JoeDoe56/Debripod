import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {createPlaybackQueueController, normalizeQueueItem} = require("../../debripod/static/js/playback-queue.js");

const audio = (rel) => normalizeQueueItem({media: "audio", root_id: "music", rel, source: "library"});
const video = (rel) => normalizeQueueItem({media: "video", root_id: "video", rel, source: "library"});

test("Play Next inserts immediately after current item", () => {
  const queue = createPlaybackQueueController();
  queue.replaceFromPlayableList([audio("a.mp3"), audio("b.mp3")], audio("a.mp3"));
  queue.insertNext(video("next.mkv"));
  assert.deepEqual(queue.state.items.map((item) => item.rel), ["a.mp3", "next.mkv", "b.mp3"]);
  assert.equal(queue.state.index, 0);
});

test("Play After appends to the final index", () => {
  const queue = createPlaybackQueueController();
  queue.replaceFromPlayableList([audio("a.mp3"), audio("b.mp3")], audio("a.mp3"));
  queue.append(video("after.mkv"));
  assert.deepEqual(queue.state.items.map((item) => item.rel), ["a.mp3", "b.mp3", "after.mkv"]);
});

test("next and previous dispatch mixed media through one play callback", async () => {
  const played = [];
  const queue = createPlaybackQueueController({}, (item) => played.push(item.media));
  queue.replaceFromPlayableList([audio("a.mp3"), video("b.mkv")], audio("a.mp3"));
  await queue.next();
  await queue.previous();
  assert.deepEqual(played, ["video", "audio"]);
});

test("serialization preserves canonical index and shuffle fields", () => {
  const queue = createPlaybackQueueController();
  queue.replaceFromPlayableList([audio("a.mp3"), video("b.mkv")], video("b.mkv"));
  const saved = queue.serializeForPlaybackSession();
  assert.equal(saved.queueIndex, 1);
  assert.equal(saved.queue[1].media, "video");
});
