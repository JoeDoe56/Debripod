// Live browser integration: decoded queue, history events, one audio output, transport ramps.
const fs=require('fs'),assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async()=>{const b=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL || 'msedge',args:['--autoplay-policy=no-user-gesture-required']});try{
 const p=await b.newPage();await p.setContent('<audio id="audioMain"></audio><div id="npBufferedFill"></div>');
 await p.evaluate(()=>{
  window.state={preloadEnabled:true,gaplessEnabled:true,playlist:['one','two','three'].map(rel=>({root:{id:'test'},rel,media:'audio'})),playIndex:0,playbackSession:{}};
  window.apiGet=async()=>({title:'track'});window.nextIndexPeek=()=>state.playIndex+1<state.playlist.length?state.playIndex+1:null;
  window.currentPlaybackNavContext=()=>({kind:'metalist'});window.events=[];window.npSeek=null;window.npSeekDragging=false;window.seekMode=false;
  for(const n of ['wireAudio','buildPlaybackSessionUpdate','loadVisualizerAnalysisForTrack','finishVisualizerTrackTransition','updateNowPlayingDisplay','updateMediaSession','syncMediaSessionControls','lastfmOnTrack','syncMediaSessionPosition','renderInfoPillLabels','updateVisualizerState','ensureVisualizerFrameLoop','scheduleVisualizerFrame','lastfmMaybeScrobble'])window[n]=()=>{};
  window.playbackMaybePost=(...args)=>events.push([args[2],args.at(-1)]);window.playNext=()=>events.push(['done']);
 });
 for(const name of ['gapless-audio','media-audio-graph','playback-transport','playback-loader'])await p.addScriptTag({content:fs.readFileSync('debripod/static/js/'+name+'.js','utf8')});
 await p.evaluate(async()=>{const g=DebriPod.gaplessAudio;g.decode=async()=>{g.supported();const ctx=g.testing.getContext();const buffer=ctx.createBuffer(1,ctx.sampleRate*.25,ctx.sampleRate);buffer.getChannelData(0).fill(.2);return buffer;};await startGaplessAudioFromItem(state.playlist[0],state.playlist,0,false,0);});
 await p.waitForTimeout(1200);
 const result=await p.evaluate(()=>({events,now:state.now.rel,active:activeAudio.__gapless,native:document.querySelector('audio').getAttribute('src'),cache:gaplessBufferCache.size}));console.log(result);
 assert.equal(result.now,'three');assert.equal(result.active,true);assert.equal(result.native,null);assert.ok(result.cache<=2);assert.equal(result.events.filter(e=>e[1]==='start').length,3);
 await p.evaluate(async()=>{stopGaplessPlayback();state.playlist=[{root:{id:'test'},rel:'long',media:'audio'}];state.playIndex=0;DebriPod.gaplessAudio.decode=async()=>{const ctx=DebriPod.gaplessAudio.testing.getContext();return ctx.createBuffer(1,ctx.sampleRate*3,ctx.sampleRate);};await startGaplessAudioFromItem(state.playlist[0],state.playlist,0,false,0);});
 await p.waitForTimeout(100);await p.evaluate(()=>DebriPod.playbackTransport.pause(activeAudio));await p.waitForTimeout(320);
 assert.equal(await p.evaluate(()=>activeAudio.paused),true);
 await p.evaluate(()=>DebriPod.playbackTransport.resume(activeAudio));await p.waitForTimeout(350);
 const resume=await p.evaluate(()=>({paused:activeAudio.paused,rate:activeAudio.playbackRate,time:activeAudio.currentTime}));console.log(resume);assert.equal(resume.paused,false);assert.equal(resume.rate,1);assert.ok(resume.time>.2);
 console.log('Live browser loader: three tracks, history, single output, pause/resume verified');
 }finally{await b.close();}})().catch(e=>{console.error(e);process.exit(1)});
