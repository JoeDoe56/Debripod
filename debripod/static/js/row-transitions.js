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

  return {TRANSITION_DURATION_MS:TRANSITION_DURATION_MS, CASCADE_STEP_MS:CASCADE_STEP_MS, spawnDelayMs:spawnDelayMs, planRowMutation:planRowMutation};
});
