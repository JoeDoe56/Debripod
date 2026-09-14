(function(root){
  "use strict";

  const DURATION_MS = 260;
  const SLOW_RATE_RATIO = 0.25;
  const states = new WeakMap();

  function number(value, fallback){
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function clamp01(value){ return Math.max(0, Math.min(1, number(value, 0))); }
  function clock(){
    try{ if(root.performance && typeof root.performance.now === "function") return root.performance.now(); }catch(error){}
    return Date.now();
  }

  function graph(){
    try{ return root.DebriPod && root.DebriPod.mediaAudioGraph; }catch(error){ return null; }
  }

  function transportLevel(media, value, immediate){
    const api = graph();
    try{ return !!(api && api.setTransportLevel && api.setTransportLevel(media, clamp01(value), !!immediate)); }catch(error){ return false; }
  }

  function notifyVisualizer(){
    try{ if(typeof root.updateVisualizerState === "function") root.updateVisualizerState(); }catch(error){}
    try{ if(typeof root.ensureVisualizerFrameLoop === "function") root.ensureVisualizerFrameLoop(); }catch(error){}
    try{ if(typeof root.scheduleVisualizerFrame === "function") root.scheduleVisualizerFrame(0); }catch(error){}
  }

  function restorePitch(media, state){
    if(!media || !state || !state.pitchCaptured) return;
    ["preservesPitch", "webkitPreservesPitch", "mozPreservesPitch"].forEach((key)=>{
      if(Object.prototype.hasOwnProperty.call(state.pitchValues, key)){
        try{ media[key] = state.pitchValues[key]; }catch(error){}
      }
    });
    state.pitchCaptured = false;
  }

  function disablePitch(media, state){
    if(!media || !state) return;
    if(!state.pitchCaptured){
      state.pitchValues = {};
      ["preservesPitch", "webkitPreservesPitch", "mozPreservesPitch"].forEach((key)=>{
        try{
          if(key in media){ state.pitchValues[key] = media[key]; media[key] = false; }
        }catch(error){}
      });
      state.pitchCaptured = true;
    }else{
      ["preservesPitch", "webkitPreservesPitch", "mozPreservesPitch"].forEach((key)=>{ try{ if(key in media) media[key] = false; }catch(error){} });
    }
  }

  function setRate(media, value){
    try{ if(media && Number.isFinite(Number(value))) media.playbackRate = Number(value); }catch(error){}
  }

  function cancelTimer(state){
    if(!state || state.timer == null) return;
    try{
      clearTimeout(state.timer);
    }catch(error){}
    state.timer = null;
  }

  function finish(media, state){
    if(!media || !state || states.get(media) !== state) return;
    cancelTimer(state);
    state.level = state.targetPaused ? 0 : 1;
    transportLevel(media, state.level, true);
    if(state.targetPaused){
      setRate(media, state.slowRate);
      try{ media.pause(); }catch(error){}
      state.intendedPaused = true;
    }else{
      setRate(media, state.baseRate);
      state.intendedPaused = false;
      restorePitch(media, state);
      states.delete(media);
    }
    state.phase = state.targetPaused ? "paused" : "normal";
    notifyVisualizer();
  }

  function tick(media, state, timestamp, generation){
    if(states.get(media) !== state || (generation != null && state.generation !== generation)) return;
    const elapsed = Math.max(0, number(timestamp, clock()) - state.startedAt);
    const progress = clamp01(elapsed / DURATION_MS);
    const eased = progress * progress * (3 - 2 * progress);
    const fromLevel = state.startLevel;
    const fromRate = state.startRate;
    state.level = state.targetPaused ? fromLevel * (1 - eased) : fromLevel + (1 - fromLevel) * eased;
    setRate(media, fromRate + (state.targetPaused ? state.slowRate - fromRate : state.baseRate - fromRate) * eased);
    transportLevel(media, state.level);
    if(progress >= 1){ finish(media, state); return; }
    // Timers continue the short envelope when rAF is throttled by an iOS
    // background Media Session callback.
    const expectedGeneration = state.generation;
    state.timer = setTimeout(()=>tick(media, state, clock(), expectedGeneration), 16);
  }

  function makeState(media, targetPaused){
    const rotationStartTime = visualizerTime(media);
    const state = states.get(media) || {
      phase:"normal", level:targetPaused ? 1 : 0, targetPaused:false, intendedPaused:false,
      baseRate:Math.max(0.05, number(media && media.playbackRate, 1)), slowRate:1,
      startLevel:targetPaused ? 1 : 0, startRate:1, startedAt:0, timer:null,
      pitchCaptured:false, pitchValues:{}, generation:0
    };
    if(!states.has(media)) states.set(media, state);
    const wasPaused = !!state.intendedPaused;
    state.targetPaused = !!targetPaused;
    state.generation = Number(state.generation || 0) + 1;
    state.baseRate = Math.max(0.05, number(state.baseRate || media && media.playbackRate, 1));
    state.slowRate = Math.max(0.05, state.baseRate * SLOW_RATE_RATIO);
    state.startLevel = clamp01(state.level);
    state.startRate = Math.max(0.05, number(media && media.playbackRate, state.targetPaused ? state.baseRate : state.slowRate));
    if(!targetPaused && !wasPaused && state.startLevel < 0.999) state.startRate = state.slowRate;
    state.startedAt = clock();
    state.rotationStartTime = rotationStartTime;
    state.rotationWaiting = !targetPaused && !!media.paused;
    state.phase = targetPaused ? "slowing" : "speeding";
    state.intendedPaused = !!targetPaused;
    disablePitch(media, state);
    cancelTimer(state);
    if(!targetPaused){
      transportLevel(media, state.startLevel, true);
      setRate(media, state.startRate);
    }
    notifyVisualizer();
    return state;
  }

  function pause(media){
    if(!media) return false;
    const state = states.get(media);
    if(state && state.intendedPaused) return true;
    if(media.paused && !state) return false;
    const next = makeState(media, true);
    tick(media, next, next.startedAt);
    return true;
  }

  function resume(media){
    if(!media) return false;
    const state = states.get(media);
    if(state && !state.intendedPaused && !media.paused) return false;
    const next = makeState(media, false);
    const generation = next.generation;
    let result = null;
    try{ result = media.play ? media.play() : null; }catch(error){ cancel(media); return false; }
    if(result && typeof result.then === "function"){
      result.then(()=>{
        if(states.get(media) !== next || next.generation !== generation) return;
        next.startedAt = clock();
        next.rotationWaiting = false;
        tick(media, next, next.startedAt, generation);
      }).catch(()=>{ if(states.get(media) === next && next.generation === generation) cancel(media); });
    }else{
      next.startedAt = clock();
      next.rotationWaiting = false;
      tick(media, next, next.startedAt, generation);
    }
    return true;
  }

  function toggle(media){
    if(!media) return false;
    return isPaused(media) ? resume(media) || playDirect(media) : pause(media);
  }

  function playDirect(media){
    try{ const result = media.play ? media.play() : null; if(result && result.catch) result.catch(()=>{}); return true; }catch(error){ return false; }
  }

  function cancel(media){
    if(!media) return false;
    const state = states.get(media);
    if(!state) return false;
    state.generation = Number(state.generation || 0) + 1;
    cancelTimer(state);
    const api = graph();
    try{ if(api && api.resetTransportLevel) api.resetTransportLevel(media); }catch(error){}
    setRate(media, state.baseRate || 1);
    restorePitch(media, state);
    states.delete(media);
    return true;
  }

  function visualizerLevel(media){
    const state = states.get(media);
    return state && (state.phase !== "normal" || state.intendedPaused) ? clamp01(state.level) : null;
  }

  function visualizerTime(media){
    const state = states.get(media);
    const actual = number(media && media.currentTime, 0);
    if(!state || state.phase === "paused") return actual;
    if(state.rotationWaiting) return state.rotationStartTime;
    const t = clamp01((clock() - state.startedAt) / DURATION_MS);
    // Integral of the exact smoothstep used by the audio rate ramp. Reading
    // this at render time avoids coarse media.currentTime updates on iOS.
    const integratedEase = t * t * t - 0.5 * t * t * t * t;
    const targetRate = state.targetPaused ? state.slowRate : state.baseRate;
    const distance = (DURATION_MS / 1000) * (state.startRate * t + (targetRate - state.startRate) * integratedEase);
    return Math.min(number(media && media.duration, Infinity), state.rotationStartTime + distance);
  }

  function isPaused(media){
    const state = states.get(media);
    return state ? !!state.intendedPaused : !!(media && media.paused);
  }

  const api = {pause, resume, toggle, cancel, isPaused, visualizerLevel, visualizerTime, duration:DURATION_MS, testing:{states, tick, constants:{DURATION_MS, SLOW_RATE_RATIO}}};
  root.DebriPod = root.DebriPod || {};
  root.DebriPod.playbackTransport = api;
})(window);
