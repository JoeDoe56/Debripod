(function(root){
  "use strict";
  let context=null, output=null, analyser=null, session=null, volume=1, transportLevel=1, rate=1;
  let recovering=null;
  const listeners=new Map();
  const number=(v,f)=>Number.isFinite(Number(v))?Number(v):f;
  const keyFor=item=>String(item && item.root && item.root.id || "")+"\u0000"+String(item && item.rel || "");
  function emit(name){ for(const fn of listeners.get(name)||[]) {try{fn({type:name,target:media});}catch(e){}} }
  function getContext(){
    if(context && context.state !== "closed") return context;
    const C=root.AudioContext || root.webkitAudioContext;
    if(!C) return null;
    try{
      context=new C();output=context.createGain();output.gain.value=volume*transportLevel;
      if(context.createAnalyser){analyser=context.createAnalyser();analyser.fftSize=256;analyser.connect(output);}
      output.connect(context.destination);
      if(context.addEventListener)context.addEventListener("statechange",()=>{
        if(session && session.playing && ["interrupted","suspended"].includes(context.state))resumeContext();
      });
    }catch(e){context=null;output=null;}
    return context;
  }
  function supported(){return !!(getContext() && output && context.decodeAudioData);}
  function resumeContext(){
    const ctx=getContext();
    if(!ctx)return Promise.resolve(false);
    if(ctx.state === "running")return Promise.resolve(true);
    if(recovering)return recovering;
    try{recovering=Promise.resolve(ctx.resume()).then(()=>ctx.state === "running").catch(()=>false).finally(()=>{recovering=null;});}
    catch(e){return Promise.resolve(false);}
    return recovering;
  }
  function sourceUrl(item){return item && item.root && item.rel ? "/stream/"+encodeURIComponent(item.root.id)+"/"+String(item.rel).split("\\").join("/").split("/").map(encodeURIComponent).join("/") : "";}
  async function decode(item,signal){
    const ctx=getContext();
    if(!ctx)throw new Error("Web Audio unavailable");
    const response=await root.fetch(sourceUrl(item),signal?{signal}:undefined);
    if(!response.ok)throw new Error("Audio request failed");
    const bytes=await response.arrayBuffer();
    return new Promise((resolve,reject)=>{
      try{const pending=ctx.decodeAudioData(bytes,resolve,reject);if(pending && pending.then)pending.then(resolve,reject);}catch(e){reject(e);}
    });
  }
  function dispose(source,when){
    if(!source)return;
    source.onended=null;
    try{source.stop(when);}catch(e){}
    // A scheduled stop must remain connected until its last sample plays.
    if(when != null && context && when>context.currentTime){
      source.onended=()=>{try{source.disconnect();}catch(e){}};
    }else try{source.disconnect();}catch(e){}
  }
  function position(at){
    if(!session)return 0;
    if(!session.playing)return session.offset;
    return Math.max(0,Math.min(session.duration,session.offset+Math.max(0,number(at,context.currentTime)-session.startedAt)*session.rate));
  }
  function promote(next){
    if(!session || session.next !== next)return;
    const finished={item:session.current,duration:session.duration};
    session.current=next.item;session.key=next.key;session.buffer=next.buffer;
    session.duration=next.buffer.duration;session.offset=0;session.startedAt=next.when;
    session.source=next.source;session.rate=rate;session.next=null;
    try{if(session.onBoundary)session.onBoundary(next.item,finished);}catch(e){}
  }
  function syncBoundary(){
    if(session && session.playing && session.next && context.currentTime>=session.next.when)promote(session.next);
  }
  function ended(source){
    if(!session || !session.playing || session.source!==source)return;
    if(session.next){
      const next=session.next;
      const delay=Math.max(0,(next.when-context.currentTime)*1000);
      if(delay)setTimeout(()=>{if(session && session.playing && session.source===source)promote(next);},delay);
      else promote(next);
    }else{
      session.offset=session.duration;session.playing=false;
      try{if(session.onEnded)session.onEnded(session.current);}catch(e){}
    }
  }
  function makeSource(buffer,when,offset,sourceRate){
    const source=context.createBufferSource();source.buffer=buffer;
    if(source.playbackRate)source.playbackRate.value=sourceRate;
    source.connect(analyser || output);source.onended=()=>ended(source);
    source.start(when,offset);return source;
  }
  function scheduleNext(item,buffer){
    if(!session || !buffer || !item)return false;
    const retained={item,buffer};
    if(session.next)dispose(session.next.source);
    session.next=null;
    if(!session.playing){session.pausedNext=retained;return true;}
    const when=session.startedAt+(session.duration-session.offset)/session.rate+session.gap;
    if(when<context.currentTime)return false;
    try{session.next={item,key:keyFor(item),buffer,when,source:makeSource(buffer,when,0,rate)};return true;}catch(e){return false;}
  }
  function setGap(value){if(session){session.gap=Math.max(0,number(value,0));const next=session.next;if(next)scheduleNext(next.item,next.buffer);}}
  function cancelNext(){
    if(!session)return;
    if(session.next)dispose(session.next.source);
    session.next=null;session.pausedNext=null;
  }
  function start(item,buffer,nextItem,nextBuffer,options){
    if(!getContext() || !output || !buffer)return false;
    const opts=options || {}, old=session;
    // On a skip the outgoing source stops at precisely the incoming source's
    // scheduled boundary, even if the JS call is between rendering quanta.
    const cut=context.currentTime+0.025;
    const when=cut+(old && old.playing?Math.max(0,number(opts.gap,0)):0);
    const offset=Math.max(0,Math.min(buffer.duration,number(opts.offset,0)));
    let source;
    try{source=makeSource(buffer,when,offset,rate);}catch(e){return false;}
    if(old){dispose(old.source,cut);if(old.next)dispose(old.next.source);}
    session={current:item,key:keyFor(item),buffer,duration:buffer.duration,offset,startedAt:when,source,rate,playing:true,next:null,pausedNext:null,gap:Math.max(0,number(opts.gap,0)),onBoundary:opts.onBoundary,onEnded:opts.onEnded};
    if(nextItem && nextBuffer)scheduleNext(nextItem,nextBuffer);
    emit("play");return true;
  }
  function stop(){const old=session;session=null;if(old){dispose(old.source);if(old.next)dispose(old.next.source);}rate=1;transportLevel=1;applyGain();}
  function pause(){
    syncBoundary();if(!session || !session.playing)return false;
    session.offset=position();session.playing=false;
    dispose(session.source);session.source=null;
    if(session.next){session.pausedNext={item:session.next.item,buffer:session.next.buffer};dispose(session.next.source);session.next=null;}
    emit("pause");return true;
  }
  function resume(){
    if(!session || session.playing)return false;
    session.startedAt=context.currentTime+0.025;session.rate=rate;
    session.source=makeSource(session.buffer,session.startedAt,session.offset,rate);session.playing=true;
    const next=session.pausedNext;session.pausedNext=null;if(next)scheduleNext(next.item,next.buffer);
    emit("play");return true;
  }
  function seek(value){
    syncBoundary();if(!session)return false;
    const next=session.next || session.pausedNext;
    const target=Math.max(0,Math.min(session.duration,number(value,0)));
    if(session.playing){
      const when=context.currentTime+0.025;
      const source=makeSource(session.buffer,when,target,rate);
      dispose(session.source,when);if(session.next)dispose(session.next.source);
      session.source=source;session.startedAt=when;
    }
    session.offset=target;session.next=null;
    if(next)scheduleNext(next.item,next.buffer);
    emit("seeked");return true;
  }
  function setRate(value){
    syncBoundary();const nextRate=Math.max(.05,number(value,1));
    if(session && session.playing){
      const next=session.next;
      session.offset=position();session.startedAt=Math.max(session.startedAt,context.currentTime);session.rate=nextRate;
      if(session.source && session.source.playbackRate)session.source.playbackRate.value=nextRate;
      rate=nextRate;if(next)scheduleNext(next.item,next.buffer);
    }else{rate=nextRate;if(session)session.rate=rate;}
  }
  function applyGain(){if(output)output.gain.value=volume*transportLevel;}
  function setVolume(value){volume=Math.max(0,Math.min(1,number(value,1)));applyGain();return volume;}
  function setTransportLevel(value){transportLevel=Math.max(0,Math.min(1,number(value,1)));applyGain();return true;}
  function snapshot(){syncBoundary();return session?{key:session.key,item:session.current,position:position(),duration:session.duration,playing:session.playing}:null;}
  function takePrestarted(item){syncBoundary();return !!(session && session.key===keyFor(item));}
  function getFrequencyData(){if(!analyser)return null;const data=new Uint8Array(analyser.frequencyBinCount);analyser.getByteFrequencyData(data);return data;}
  function getRms(){if(!analyser)return 0;const data=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(data);return Math.sqrt(data.reduce((sum,v)=>sum+v*v,0)/data.length);}
  const media={__gapless:true,muted:false,preservesPitch:false,
    get currentTime(){return snapshot()?.position || 0;},set currentTime(v){seek(v);},
    get duration(){return session?.duration || 0;},get paused(){return !session?.playing;},get ended(){return !!session && !session.playing && session.offset>=session.duration;},
    get playbackRate(){return rate;},set playbackRate(v){setRate(v);},
    get volume(){return volume;},set volume(v){setVolume(v);},
    get src(){return session?sourceUrl(session.current):"";},get currentSrc(){return this.src;},
    get readyState(){return session?4:0;},get buffered(){return {length:session?1:0,start:()=>0,end:()=>session?.duration || 0};},
    play:async()=>{if(!await resumeContext())throw new Error("Audio output is suspended");if(resume())await new Promise(resolve=>setTimeout(resolve,25));},pause,
    addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);},
    removeEventListener:(name,fn)=>listeners.get(name)?.delete(fn),
    setTransportLevel,getFrequencyData,getRms,
    removeAttribute(){},load(){},tick:()=>emit("timeupdate")
  };
  root.DebriPod=root.DebriPod || {};
  root.DebriPod.gaplessAudio={supported,decode,start,stop,pause,resume,resumeContext,seek,scheduleNext,cancelNext,setGap,takePrestarted,setVolume,snapshot,sourceUrl,media,testing:{getContext:()=>context,getSession:()=>session,keyFor}};
  try{root.document?.addEventListener("visibilitychange",()=>{if(!root.document.hidden && session?.playing)resumeContext();});root.addEventListener("pageshow",()=>{if(session?.playing)resumeContext();});}catch(e){}
})(window);
