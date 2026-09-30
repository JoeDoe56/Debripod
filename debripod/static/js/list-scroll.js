(function(root, factory){
  const api = factory(root);
  if(typeof module !== "undefined" && module.exports) module.exports = api;
  const host = root || (typeof globalThis !== "undefined" ? globalThis : {});
  host.DebriPod = host.DebriPod || {};
  host.DebriPod.listScrollFactory = api;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this), function(root){
  "use strict";

  const PHASES = Object.freeze({IDLE:"idle", DIRECT:"direct", MOMENTUM:"momentum"});

  function defaultNow(){
    try{
      if(root && root.performance && typeof root.performance.now === "function") return root.performance.now();
    }catch(e){}
    return Date.now();
  }

  /**
   * Owns the short lifecycle around native list scrolling. It deliberately
   * does not write scrollTop or selection: the list view remains the only
   * owner of those values. Consumers can hide expensive selected-row glass
   * while active and restore it once the native scroll stream settles.
   */
  function createListScrollController(options){
    const opts = options || {};
    const now = typeof opts.now === "function" ? opts.now : defaultNow;
    const setTimer = typeof opts.setTimeout === "function" ? opts.setTimeout : setTimeout;
    const clearTimer = typeof opts.clearTimeout === "function" ? opts.clearTimeout : clearTimeout;
    const settleDelay = Math.max(40, Number(opts.settleDelay == null ? 140 : opts.settleDelay));
    const listeners = new Set();
    let phase = PHASES.IDLE;
    let settleTimer = 0;
    let lastTop = null;
    let lastTimestamp = 0;
    let velocity = 0;
    let snapshot = null;
    let generation = 0;

    function emit(reason, extra){
      const event = Object.assign({
        active: phase !== PHASES.IDLE,
        phase,
        reason: String(reason || "state"),
        top: lastTop,
        velocity,
        generation
      }, extra || {});
      listeners.forEach((listener)=>{
        try{ listener(event); }catch(e){}
      });
      return event;
    }

    function clearSettleTimer(){
      if(settleTimer){
        clearTimer(settleTimer);
        settleTimer = 0;
      }
    }

    function scheduleSettle(){
      clearSettleTimer();
      const token = generation;
      settleTimer = setTimer(()=>{
        settleTimer = 0;
        if(token !== generation || phase === PHASES.IDLE) return;
        settle("scroll-settled");
      }, settleDelay);
    }

    function capture(meta){
      try{ return typeof opts.capture === "function" ? opts.capture(meta || {}) : null; }catch(e){ return null; }
    }

    function beginDirect(meta){
      const wasIdle = phase === PHASES.IDLE;
      if(wasIdle){
        generation += 1;
        snapshot = capture(meta);
        velocity = 0;
        lastTimestamp = now();
      }
      clearSettleTimer();
      phase = PHASES.DIRECT;
      if(meta && Number.isFinite(Number(meta.top))) lastTop = Number(meta.top);
      if(typeof opts.cancelProgrammatic === "function"){
        try{ opts.cancelProgrammatic(meta || {}); }catch(e){}
      }
      if(wasIdle) emit("scroll-start", {snapshot});
      return snapshot;
    }

    function onScroll(top, meta){
      const info = meta || {};
      if(info.programmatic) return false;
      const value = Number(top);
      const stamp = Number.isFinite(Number(info.time)) ? Number(info.time) : now();
      if(phase === PHASES.IDLE) beginDirect(Object.assign({}, info, {top:value}));
      const previous = lastTop;
      const elapsed = lastTimestamp ? Math.max(1, stamp - lastTimestamp) : 1;
      if(Number.isFinite(value) && Number.isFinite(previous)) velocity = (value - previous) / elapsed;
      if(Number.isFinite(value)) lastTop = value;
      lastTimestamp = stamp;
      if(phase === PHASES.DIRECT && info.inputActive === false) phase = PHASES.MOMENTUM;
      if(!info.inputActive) scheduleSettle();
      return true;
    }

    function endDirect(meta){
      if(phase === PHASES.IDLE) return false;
      phase = PHASES.MOMENTUM;
      if(meta && Number.isFinite(Number(meta.top))) lastTop = Number(meta.top);
      emit("input-end", {snapshot});
      scheduleSettle();
      return true;
    }

    function settle(reason){
      if(phase === PHASES.IDLE) return false;
      clearSettleTimer();
      const previous = snapshot;
      phase = PHASES.IDLE;
      snapshot = null;
      velocity = 0;
      emit(reason || "scroll-settled", {snapshot:previous});
      return true;
    }

    function cancel(reason){
      clearSettleTimer();
      generation += 1;
      const wasActive = phase !== PHASES.IDLE;
      const previous = snapshot;
      phase = PHASES.IDLE;
      snapshot = null;
      velocity = 0;
      if(wasActive) emit(reason || "scroll-cancelled", {snapshot:previous, cancelled:true});
      return wasActive;
    }

    function subscribe(listener){
      if(typeof listener !== "function") return ()=>{};
      listeners.add(listener);
      return ()=>listeners.delete(listener);
    }

    return {
      PHASES,
      beginDirect,
      onScroll,
      endDirect,
      settle,
      cancel,
      subscribe,
      isDirectScrolling:()=>phase !== PHASES.IDLE,
      phase:()=>phase,
      snapshot:()=>snapshot,
      velocity:()=>velocity
    };
  }

  return {PHASES, createListScrollController};
});
