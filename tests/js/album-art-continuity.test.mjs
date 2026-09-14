import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

function harness(){
  const calls = [];
  const canvas = {dataset:{}, classList:{toggle:(...args)=>calls.push(args)}};
  const context = {
    window:{addEventListener(){}}, document:{getElementById:()=>canvas},
    npArt:canvas, performance:{now:()=>1},
    requestAnimationFrame:()=>1, cancelAnimationFrame:()=>calls.push('cancel'),
    sampleThemeFromArt:()=>calls.push('theme'),
  };
  vm.createContext(context);
  const ui = fs.readFileSync(new URL('../../debripod/static/js/now-playing-ui.js', import.meta.url), 'utf8');
  vm.runInContext(ui.slice(0, ui.indexOf('var npControlMode')), context);
  vm.runInContext(fs.readFileSync(new URL('../../debripod/static/js/album-art-texture.js', import.meta.url), 'utf8'), context);
  context.setPlaybackPillMetadata = ()=>calls.push('metadata');
  context.showStaticNowPlayingArt = src=>calls.push(['image',src]);
  return {context,calls};
}

test('identical content with different track URLs leaves artwork untouched', async()=>{
  const {context:c,calls} = harness();
  await c.updateNowPlayingDisplay({art:'/art/one.flac',artIdentity:'sha1:same'});
  calls.length = 0;
  await c.updateNowPlayingDisplay({art:'/art/two.flac',artIdentity:'sha1:same'}, '', {animateArt:true});
  assert.deepEqual(calls,['metadata']);
  assert.equal(c.currentNowPlayingArtSrc(),'/art/one.flac');
});

test('repeated URL does not interrupt a running artwork fade',()=>{
  const {context:c,calls} = harness();
  c.npArtTextureState.currentSrc = '/same';
  c.npArtTextureState.fadeActive = true;
  c.npArtTextureState.frame = 7;
  c.setNowPlayingArtTexture('/same');
  assert.equal(c.npArtTextureState.fadeActive,true);
  assert.equal(c.npArtTextureState.frame,7);
  assert.deepEqual(calls,[]);
});

test('late image callbacks cannot replace newer artwork',()=>{
  const {context:c,calls} = harness();
  const pending = [];
  c.ensureNowPlayingArtTexture = ()=>true;
  c.loadNowPlayingArtImage = (src,ready)=>pending.push({src,ready});
  c.uploadNowPlayingArtTexture = ()=>calls.push('upload');
  c.npArtTextureState.currentSrc = '/old';
  c.setNowPlayingArtTexture('/slow', {animate:true});
  c.setNowPlayingArtTexture('/new');
  calls.length = 0;
  pending[0].ready({});
  assert.equal(c.npArtTextureState.currentSrc,'/new');
  assert.deepEqual(calls,[]);
});
