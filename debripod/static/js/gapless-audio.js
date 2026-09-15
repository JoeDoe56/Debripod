(function(root){
  "use strict";

  // A media element is decoded by the browser on its own clock.  That makes
  // two elements inherently racy at a track boundary.  This small adapter
  // decodes finite audio into AudioBuffers and schedules both sources on one
  // AudioContext clock.  The regular media-element loader remains the
  // fallback for browsers without Web Audio or for streams that cannot be
  // decoded.
  let context = null;
  let output = null;
  let volume = 1;
  let session = null;
  let token = 0;

  function number(v, fallback){ const n = Number(v); return Number.isFinite(n) ? n : fallback; }
  function keyFor(item){ return String(item && item.root && item.root.id || "") + "\u0000" + String(item && item.rel || ""); }
  function getContext(){
    if(context) return context;
    const C = root.AudioContext || root.webkitAudioContext;
    if(!C) return null;
    try{ context = new C(); }catch(e){ context = null; }
    if(context){ try{ output = context.createGain(); output.gain.value = volume; output.connect(context.destination); }catch(e){ output = null; } }
    return context;
  }
  function supported(){ return !!(getContext() && output && typeof context.decodeAudioData === "function"); }
  function resumeContext(){
    const ctx = getContext();
    if(!ctx || typeof ctx.resume !== "function") return Promise.resolve(false);
    if(ctx.state === "suspended") return Promise.resolve(ctx.resume()).then(()=>true).catch(()=>false);
    return Promise.resolve(ctx.state !== "closed");
  }
  function sourceUrl(item){
    if(!item || !item.root || !item.rel) return "";
    const enc = (String(item.rel).split("\\").join("/").split("/").map(encodeURIComponent).join("/"));
    return "/stream/" + encodeURIComponent(item.root.id) + "/" + enc;
  }
  async function decode(item, signal){
    const ctx = getContext();
    if(!ctx || !root.fetch) throw new Error("gapless audio unavailable");
    const response = await root.fetch(sourceUrl(item), signal ? {signal} : undefined);
    if(!response || !response.ok) throw new Error("audio buffer request failed");
    const data = await response.arrayBuffer();
    // Safari only supports the callback form for some decoded formats.
    return await new Promise((resolve, reject)=>{
      let result;
      try{ result = ctx.decodeAudioData(data, resolve, reject); }catch(e){ reject(e); }
      if(result && typeof result.then === "function") result.then(resolve, reject);
    });
  }
  function stopSource(s){ try{ if(s) s.stop(); }catch(e){} try{ if(s) s.disconnect(); }catch(e){} }
  function currentPosition(now){
    if(!session) return 0;
    if(!session.playing) return session.offset;
    return Math.max(0, Math.min(session.duration, session.offset + (number(now, context ? context.currentTime : 0) - session.startedAt)));
  }
  function promote(next){
    if(!session || !next) return;
    session.current = next.item;
    session.key = next.key;
    session.buffer = next.buffer;
    session.duration = number(next.buffer && next.buffer.duration, 0);
    session.offset = 0;
    session.startedAt = next.when;
    session.source = next.source;
    session.next = null;
    try{ if(typeof session.onBoundary === "function") session.onBoundary(session.current); }catch(e){}
  }
  function scheduleNext(item, buffer){
    if(!session || !context || !output || !buffer || !item) return false;
    const when = session.startedAt + Math.max(0, session.duration - session.offset);
    let src = null;
    try{
      src = context.createBufferSource(); src.buffer = buffer; src.connect(output);
      src.onended = ()=>{
        // The current source's ended event is the handoff point. The next
        // source has already been scheduled on the same clock, so promoting
        // the session here only changes bookkeeping and never starts audio.
        if(session && session.source === src && session.next) promote(session.next);
      };
      src.start(when, 0);
    }catch(e){ stopSource(src); return false; }
    session.next = {item, key:keyFor(item), buffer, source:src, when};
    return true;
  }
  function start(item, buffer, nextItem, nextBuffer, options){
    const ctx = getContext();
    if(!ctx || !output || !buffer) return false;
    stop();
    const opts = options || {};
    const offset = Math.max(0, Math.min(number(buffer.duration, 0), number(opts.offset, 0)));
    const when = number(ctx.currentTime, 0) + 0.025;
    let src = null;
    try{
      src = ctx.createBufferSource(); src.buffer = buffer; src.connect(output);
      src.start(when, offset);
    }catch(e){ stopSource(src); return false; }
    session = {current:item, key:keyFor(item), buffer, duration:number(buffer.duration,0), offset, startedAt:when, source:src, next:null, playing:true, onBoundary:opts.onBoundary || null, onEnded:opts.onEnded || null};
    src.onended = ()=>{
      if(!session || session.source !== src) return;
      if(session.next){ promote(session.next); return; }
      session.playing = false; session.offset = session.duration;
      try{ if(typeof session.onEnded === "function") session.onEnded(session.current); }catch(e){}
    };
    if(nextItem && nextBuffer) scheduleNext(nextItem, nextBuffer);
    return true;
  }
  function stop(){
    if(session){ stopSource(session.source); if(session.next) stopSource(session.next.source); }
    session = null;
  }
  function pause(){
    if(!session || !session.playing) return false;
    session.offset = currentPosition(); session.playing = false; stopSource(session.source); if(session.next) stopSource(session.next.source); session.next = null; return true;
  }
  function resume(){
    if(!session || session.playing) return false;
    const item = session.current, key = session.key, duration = session.duration, offset = session.offset;
    // The current buffer is retained on the session by callers through
    // resumeBuffer; if unavailable, a subsequent regular media load wins.
    const buffer = session.buffer;
    if(!buffer) return false;
    const when = number(context.currentTime,0) + 0.025;
    let src = null;
    try{ src=context.createBufferSource();src.buffer=buffer;src.connect(output);src.start(when,offset); }catch(e){ stopSource(src); return false; }
    session.source=src;session.startedAt=when;session.playing=true;session.key=key;session.duration=duration;
    src.onended=()=>{if(session&&session.source===src){session.playing=false;session.offset=session.duration;try{if(session.onEnded)session.onEnded(session.current)}catch(e){}}};
    return true;
  }
  function seek(offset){
    if(!session || !session.buffer) return false;
    session.offset=Math.max(0,Math.min(session.duration,number(offset,0)));
    if(session.playing) return resumeAfterSeek();
    return true;
  }
  function resumeAfterSeek(){
    const wasPlaying=session.playing; const item=session.current, buffer=session.buffer, off=session.offset;
    stopSource(session.source); if(session.next) stopSource(session.next.source); session.next=null; session.playing=false;
    if(!wasPlaying) return true;
    return resumeWith(item,buffer,off);
  }
  function resumeWith(item,buffer,off){
    const when=number(context.currentTime,0)+0.025; let src=null;
    try{src=context.createBufferSource();src.buffer=buffer;src.connect(output);src.start(when,off)}catch(e){stopSource(src);return false}
    session.source=src;session.startedAt=when;session.offset=off;session.playing=true;
    src.onended=()=>{if(session&&session.source===src){session.playing=false;session.offset=session.duration;try{if(session.onEnded)session.onEnded(session.current)}catch(e){}}}; return true;
  }
  function takePrestarted(item){
    if(!session || session.key !== keyFor(item)) return false;
    // The boundary callback promotes the already-running source before the
    // loader updates metadata.  Taking the current source therefore never
    // restarts it or creates an overlap.
    return true;
  }
  function setVolume(v){ volume=Math.max(0,Math.min(1,number(v,1))); try{if(output) output.gain.value=volume}catch(e){} return volume; }
  function snapshot(){
    if(!session) return null;
    const position=currentPosition(); return {key:session.key,item:session.current,position,duration:session.duration,playing:!!session.playing};
  }
  root.DebriPod = root.DebriPod || {};
  try{
    if(root.document) root.document.addEventListener("visibilitychange", ()=>{ if(!root.document.hidden) resumeContext(); });
    root.addEventListener("pageshow", resumeContext);
  }catch(e){}
  root.DebriPod.gaplessAudio = {supported,decode,start,stop,pause,resume,resumeContext,seek,scheduleNext,takePrestarted,setVolume,snapshot,sourceUrl,testing:{getContext:()=>context,getSession:()=>session,keyFor}};
})(window);
