(function(global){
  "use strict";
  let records = [];

  function selectedSet(value){ return new Set(Array.isArray(value) ? value.map(String) : []); }
  function intersects(values, selected){
    if(!selected.size) return true;
    for(const value of (values || [])) if(selected.has(String(value))) return true;
    return false;
  }
  function filterRecords(source, message){
    const filters = message && message.filters || {};
    const sources = selectedSet(filters.sources), types = selectedSet(filters.types);
    const indexers = selectedSet(filters.indexers), media = selectedSet(filters.media);
    const words = String(message && message.text || "").toLowerCase().trim().split(/\s+/).filter(Boolean);
    return (source || []).filter(record=>
      intersects(record.sources, sources) && intersects(record.types, types) &&
      intersects(record.indexers, indexers) && intersects(record.media, media) &&
      words.every(word=>String(record.search_blob || "").includes(word))
    ).sort((a,b)=>Number(b.rank_score || 0) - Number(a.rank_score || 0) || String(a.id).localeCompare(String(b.id))).map(record=>record.id);
  }

  if(global && typeof global.postMessage === "function" && typeof global.document === "undefined"){
    global.onmessage = function(event){
      const message = event && event.data || {};
      if(message.type === "init") records = Array.isArray(message.records) ? message.records.slice() : [];
      if(message.type === "init" || message.type === "filter") global.postMessage({type:"result", requestId:message.requestId || "", ids:filterRecords(records, message)});
    };
  }
  if(typeof module !== "undefined" && module.exports) module.exports = {filterRecords:filterRecords};
  if(global) global.DebriPodSearchWorker = {filterRecords:filterRecords};
})(typeof self !== "undefined" ? self : globalThis);
