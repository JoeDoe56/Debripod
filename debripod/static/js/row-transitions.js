/* Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818 */
(function(root, factory){
  const api = factory();
  if(typeof module === "object" && module.exports) module.exports = api;
  if(root){
    root.DebriPod = root.DebriPod || {};
    root.DebriPod.rowTransitions = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function(){
  "use strict";
  const TRANSITION_DURATION_MS = 220;
  const CASCADE_STEP_MS = 28;
  const CASCADE_MAX_DELAY_MS = 280;

  function spawnDelayMs(index, options){
    if(options && options.reducedMotion) return 0;
    return Math.min(CASCADE_MAX_DELAY_MS, Math.max(0, Number(index) || 0) * CASCADE_STEP_MS);
  }

  function planRowMutation(previous, next, identity, selectedIdentity, options){
    const oldItems = Array.isArray(previous) ? previous : [];
    const newItems = Array.isArray(next) ? next : [];
    const keyOf = typeof identity === "function" ? identity : function(item, index){ return String(index); };
    const oldMap = new Map(oldItems.map((item, index)=>[String(keyOf(item, index)), {item:item, index:index}]));
    const nextMap = new Map(newItems.map((item, index)=>[String(keyOf(item, index)), {item:item, index:index}]));
    const retained = [];
    const inserted = [];
    const removed = [];
    nextMap.forEach((row, key)=>{
      if(oldMap.has(key)) retained.push({key:key, oldIndex:oldMap.get(key).index, newIndex:row.index, item:row.item});
      else inserted.push({key:key, newIndex:row.index, item:row.item});
    });
    oldMap.forEach((row, key)=>{
      if(!nextMap.has(key)) removed.push({key:key, oldIndex:row.index, item:row.item});
    });
    const selectedKey = String(selectedIdentity == null ? "" : selectedIdentity);
    const selectionIndex = nextMap.has(selectedKey) ? nextMap.get(selectedKey).index : -1;
    const reduced = !!(options && options.reducedMotion);
    return {retained:retained, inserted:inserted, removed:removed, selectionIndex:selectionIndex, animate:!reduced};
  }

  function shouldAnimateListMutation(previousCount, nextCount, changedRows, options){
    const opts = options || {};
    // A page transition animates only the rows that are actually rendered;
    // logical dataset size must not suppress the visible transition.
    if(opts.reason === "page load") return true;
    return Number(previousCount || 0) <= 500 && Number(nextCount || 0) <= 500 && Number(changedRows || 0) <= 100;
  }

  function isNonVirtualInfoView(kind){
    const value = String(kind || "");
    return value === "roots" || value === "libinfo" || value === "media_information" || value === "youtube_comments" ||
      value === "settings" || value === "performance" || value.indexOf("settings") === 0 || value.indexOf("setup") === 0 ||
      value.indexOf("account") === 0 || value.indexOf("libinfo") === 0 || value.indexOf("libui") === 0 ||
      value.indexOf("libadvanced") === 0 || value.indexOf("libbinds") === 0 || value.indexOf("libdatabase") === 0 ||
      value.indexOf("ui_settings") === 0 || value.indexOf("range_editor") === 0;
  }

  function adaptiveOverscanRows(viewportHeight, rowHeight, velocityPxPerMs){
    const height = Math.max(1, Number(viewportHeight) || 1);
    const row = Math.max(1, Number(rowHeight) || 1);
    const viewportRows = Math.max(1, Math.ceil(height / row));
    const velocity = Math.abs(Number(velocityPxPerMs) || 0);
    const velocityRows = Math.min(12, Math.ceil((velocity * 100) / row));
    const base = Math.min(4, Math.max(2, Math.ceil(viewportRows * 0.25)));
    return Math.min(16, base + velocityRows);
  }

  return {
    TRANSITION_DURATION_MS:TRANSITION_DURATION_MS,
    CASCADE_STEP_MS:CASCADE_STEP_MS,
    spawnDelayMs:spawnDelayMs,
    planRowMutation:planRowMutation,
    shouldAnimateListMutation:shouldAnimateListMutation,
    isNonVirtualInfoView:isNonVirtualInfoView,
    adaptiveOverscanRows:adaptiveOverscanRows,
  };
});
