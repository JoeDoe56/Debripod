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
  // Rows are laid out in their final position in one paint.  Keeping a row
  // transition layer around here used to make page changes look like a
  // cascade and, worse, let the selected glass drift while the list was
  // being replaced.
  const TRANSITION_DURATION_MS = 0;
  const CASCADE_STEP_MS = 0;
  const CASCADE_MAX_DELAY_MS = 0;

  function spawnDelayMs(index, options){
    return 0;
  }

  function planRowMutation(previous, next, identity, selectedIdentity, options){
    const oldItems = Array.isArray(previous) ? previous : [];
    const newItems = Array.isArray(next) ? next : [];
    const keyOf = typeof identity === "function" ? identity : function(item, index){ return String(index); };
    // Duplicate identities are disambiguated by occurrence so a repeated key
    // maps to the same row before and after, never to the last duplicate.
    const keyed = function(items){
      const seen = new Map();
      return items.map(function(item, index){
        const base = String(keyOf(item, index));
        const count = seen.get(base) || 0;
        seen.set(base, count + 1);
        return [count ? base + "#" + count : base, {item:item, index:index}];
      });
    };
    const oldMap = new Map(keyed(oldItems));
    const nextMap = new Map(keyed(newItems));
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
    let selectedKey = String(selectedIdentity == null ? "" : selectedIdentity);
    const selectedOld = options && Number.isInteger(options.selectedIndex) ? options.selectedIndex : -1;
    if(selectedOld >= 0){
      for(const [key, row] of oldMap){ if(row.index === selectedOld){ selectedKey = key; break; } }
    }
    const selectionIndex = nextMap.has(selectedKey) ? nextMap.get(selectedKey).index : -1;
    return {retained:retained, inserted:inserted, removed:removed, selectionIndex:selectionIndex, animate:false};
  }

  function shouldAnimateListMutation(previousCount, nextCount, changedRows, options){
    return false;
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
