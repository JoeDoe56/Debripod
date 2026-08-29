import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);

class ControlledWorker {
  static instances = [];

  constructor() {
    this.messages = [];
    this.onmessage = null;
    ControlledWorker.instances.push(this);
  }

  postMessage(message) {
    this.messages.push(message);
  }

  deliver(message) {
    this.onmessage({data: message});
  }
}

globalThis.Worker = ControlledWorker;
globalThis.DebriPod = {};
const {SearchResultsModel, createState} = require("../../debripod/static/js/search-results-model.js");

function result(index) {
  return {
    result_id: `result-${index}`,
    rank_score: 3000 - index,
    search_blob: `result ${index}`,
    filter_values: {sources: ["Library"], types: ["Songs"], indexers: [], media: ["music"]},
  };
}

test("a stale 1000-row worker reply cannot overwrite a newer 2000-row reply", () => {
  const model = new SearchResultsModel(createState());
  const worker = ControlledWorker.instances.at(-1);
  model.reset("synthetic", "search-1");

  model.ingestSource({event: "source", search_id: "search-1", provider_group: "library", source_id: "library", results: Array.from({length: 1000}, (_, index) => result(index))});
  const first = worker.messages.at(-1);
  model.ingestSource({event: "source", search_id: "search-1", provider_group: "local_index", source_id: "local_index", results: Array.from({length: 1000}, (_, index) => result(index + 1000))});
  const second = worker.messages.at(-1);

  worker.deliver({type: "result", requestId: second.requestId, ids: Array.from({length: 2000}, (_, index) => `result-${index}`)});
  assert.equal(model.state.visibleIds.length, 2000);
  worker.deliver({type: "result", requestId: first.requestId, ids: Array.from({length: 1000}, (_, index) => `result-${index}`)});
  assert.equal(model.state.visibleIds.length, 2000);
  assert.equal(model.state.allResults.length, 2000);
});

test("stale server events are ignored and done is authoritative", () => {
  const model = new SearchResultsModel(createState());
  model.reset("new query", "");
  model.setSearchId("new-search");

  assert.equal(model.ingestSource({event: "source", search_id: "old-search", provider_group: "library", source_id: "library", results: [result(1)]}), false);
  assert.equal(model.state.allResults.length, 0);

  const authoritative = [result(7), result(3)];
  assert.equal(model.ingestFinal({event: "done", search_id: "new-search", results: authoritative, provider_status: []}), true);
  assert.deepEqual(model.state.allResults.map((item) => item.result_id), ["result-7", "result-3"]);
  assert.equal(model.state.resultById.size, 2);
});

test("30000 canonical rows remain logical while filters only change visible IDs", async () => {
  const model = new SearchResultsModel(createState(), {disableWorker: true});
  model.reset("synthetic", "large-search");
  const rows = Array.from({length: 30000}, (_, index) => ({
    ...result(index),
    filter_values: {
      sources: [index % 2 ? "Torrents" : "Local Index"],
      types: ["Torrent"],
      indexers: [index % 2 ? "Knaben" : "DMM"],
      media: ["video"],
    },
  }));
  model.ingestFinal({event: "done", search_id: "large-search", results: rows, provider_status: []});

  const waitFor = async (predicate) => {
    const deadline = Date.now() + 5000;
    while (!predicate()) {
      if (Date.now() > deadline) assert.fail("timed out waiting for logical filter update");
      await new Promise(resolve => setTimeout(resolve, 5));
    }
  };
  await waitFor(() => model.state.visibleIds.length === 30000);
  assert.equal(model.state.allResults.length, 30000);
  assert.equal(model.state.resultById.size, 30000);
  assert.equal(model.resultRows().length, 30000);

  model.applyFilters("source:Torrents indexer:Knaben");
  await waitFor(() => model.state.visibleIds.length === 15000);
  assert.equal(model.state.allResults.length, 30000);
  assert.equal(model.state.resultById.size, 30000);

  model.clearFilters();
  await waitFor(() => model.state.visibleIds.length === 30000);
  assert.equal(model.resultRows().length, 30000);
});
