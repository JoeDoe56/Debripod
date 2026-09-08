import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {createPlaybackQueueController, normalizeQueueItem, randomEligibleIndexes} = require("../../debripod/static/js/playback-queue.js");

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

test("queue projections retain filemeta fields used by now playing", () => {
  const item = normalizeQueueItem({
    media: "audio", root_id: "music", rel: "album/song.flac", label: "filename.flac",
    title: "Song", artist: "Artist", album: "Album", genre: "Rock",
    duration: 123, tech: "FLAC 24-bit", art: "/art/music/album/song.flac?v=7"
  });
  assert.equal(item.title, "Song");
  assert.equal(item.album, "Album");
  assert.equal(item.genre, "Rock");
  assert.equal(item.duration, 123);
  assert.equal(item.tech, "FLAC 24-bit");
  assert.equal(item.art, "/art/music/album/song.flac?v=7");
});

test("shuffle projection is a complete fresh mapping and disabling restores canonical order", () => {
  const queue = createPlaybackQueueController();
  const items = Array.from({length: 2100}, (_value, index) => audio("track-" + index + ".flac"));
  queue.replaceFromPlayableList(items, items[777]);
  const originalRandom = Math.random;
  let seed = 0;
  try{
    Math.random = () => ((seed++ % 7) + 1) / 8;
    queue.setShuffle(true);
    const first = queue.orderedIndexes();
    assert.equal(first.length, 2100);
    assert.equal(new Set(first).size, 2100);
    assert.equal(first[0], queue.state.index);
    assert.deepEqual(queue.orderedItems().map((item) => item.rel), first.map((index) => items[index].rel));

    const prior = first.slice();
    queue.setShuffle(true);
    assert.equal(queue.orderedIndexes().length, 2100);
    assert.notDeepEqual(queue.orderedIndexes(), prior);

    queue.setShuffle(false);
    assert.deepEqual(queue.orderedIndexes(), Array.from({length:2100}, (_value, index) => index));
    assert.deepEqual(queue.orderedItems().map((item) => item.rel), items.map((item) => item.rel));
  }finally{
    Math.random = originalRandom;
  }
});

test("restoring a malformed shuffle order rebuilds instead of replaying duplicates", () => {
  const queue = createPlaybackQueueController();
  const items = [audio("a.flac"), audio("b.flac"), audio("c.flac")];
  queue.restoreFromPlaybackSession({
    queue: items,
    queueIndex: 0,
    shuffle: true,
    shuffleOrder: [0, 0, 1],
  });
  assert.deepEqual(queue.orderedIndexes().slice().sort((a, b) => a - b), [0, 1, 2]);
});

test("random selection uses the full logical item list, not rendered rows", () => {
  const items = [
    {kind: "random"},
    {kind: "liked_category"},
    ...Array.from({length: 2100}, (_value, index) => ({kind: "track", rel: "track-" + index})),
    {kind: "info"},
  ];
  const eligible = randomEligibleIndexes(items);
  assert.equal(eligible.length, 2100);
  assert.equal(eligible[0], 2);
  assert.equal(eligible[eligible.length - 1], 2101);
  assert.equal(new Set(eligible).size, 2100);
});
