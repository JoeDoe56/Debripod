import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

function harness(){
  const source = fs.readFileSync(new URL('../../debripod/static/js/playback-sync.js',import.meta.url),'utf8');
  const frames=[],timers=new Map(),classes=new Set();let id=0,suspended=0;
  const c={state:{},libList:{style:{}},nowPlaying:{style:{display:'none'},classList:{contains:k=>classes.has(k),add:k=>classes.add(k),remove:k=>classes.delete(k)}},
    npPageFadeTimer:null,npPageFadeToken:0,playbackPillsPinned:false,volBarTimer:null,
    requestAnimationFrame:fn=>frames.push(fn),setTimeout:(fn,ms)=>{timers.set(++id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),
    suspendListRenderingForNowPlaying:()=>suspended++};
  for(const name of ['layoutNowPlayingToLibList','resetNowPlayingLayout','updateVisualizerState','scheduleLiquidGlassSnapshot','scheduleLiquidGlassRender','setHeader','cancelSeekMode','setInfoPillControlMode','restoreListRenderingAfterNowPlaying','hidePlaybackPillsImmediate'])c[name]=()=>{};
  vm.runInNewContext(source.slice(source.indexOf('  var npPageFadeTarget'),source.indexOf('  function syncWheelZoneHeight')),c);
  return {c,timers,frames,suspended:()=>suspended,flushFrames:()=>{while(frames.length)frames.shift()();},finish:()=>{for(const [id,t]of [...timers]){timers.delete(id);t.fn();}}};
}

test('enter keeps underlying list until fade completes and repeated show preserves animation',()=>{
  const h=harness();h.c.showNowPlaying(true);h.flushFrames();
  assert.equal(h.suspended(),0);
  const token=h.c.npPageFadeToken;h.c.showNowPlaying(true);
  assert.equal(h.c.npPageFadeToken,token);
  h.finish();assert.equal(h.suspended(),1);
});

test('reversing an entering fade prevents stale suspension; repeated hide does not restart',()=>{
  const h=harness();h.c.showNowPlaying(true);h.flushFrames();h.c.showNowPlaying(false);
  const token=h.c.npPageFadeToken;h.c.showNowPlaying(false);
  assert.equal(h.c.npPageFadeToken,token);
  h.finish();assert.equal(h.suspended(),0);assert.equal(h.c.nowPlaying.style.display,'none');
});
