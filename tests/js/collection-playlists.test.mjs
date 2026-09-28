import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function fixture(){
  const state={current:{root:{id:'__all__'}},items:[],roots:[]};
  const calls=[];
  const ctx=vm.createContext({state,Map,Set,console,window:{},showNowPlaying(){},
    resetList(rows){state.items=rows;},reportUiStatus(message){throw new Error(message);},
    async setView(view){state.current=view;await view.load();},
    async apiGet(){return {ok:true,entries:[{url:'https://one.test/a',title:'A'},{url:'https://one.test/b',title:'B'}]};},
    async loadConfig(){return {roots:[{id:'real-root',name:'Media'}]};},
    async apiPost(url,payload){calls.push({url,payload});return {ok:true,json:{ok:true,rel:'new.m3u8'}};},
    async viewMetaList(){},renderList(){},updateWheelLabels(){},document:{getElementById(){return null;}}});
  vm.runInContext(fs.readFileSync('debripod/static/js/search-tasks-ui.js','utf8'),ctx);
  return {ctx,state,calls};
}

test('collection menus preserve item selection and apply one quality target to every item',async()=>{
  const {ctx,state}=fixture();
  await ctx.viewYtdlpResultDirectory({title:'Playlist',canonical_url:'https://one.test/list'},true);
  const target=state.current._searchResult;
  assert.deepEqual(Array.from(state.items,x=>x.label),['Select items','Selected quality','Stream selected','Download selected']);
  await ctx.viewYtdlpCollectionPage(target,'items',true);
  state.items[2].onToggle();state.items[3].onToggle();
  await ctx.viewYtdlpCollectionPage(target,'quality',true);
  state.items.find(x=>x.label==='Audio Only').onToggle();
  assert.ok(Array.from(target.selected.values()).every(x=>x.media==='audio'));
  state.items.find(x=>x.label==='720p').onToggle();
  assert.ok(Array.from(target.selected.values()).every(x=>x.media==='video'));
  assert.deepEqual(Array.from(target.selected.values(),x=>[x.source_url,x.quality_target]),[['https://one.test/a','720p'],['https://one.test/b','720p']]);
  await ctx.viewYtdlpCollectionPage(target,'items',true);
  assert.equal(state.items.filter(x=>x.selected).length,2);
  state.items[2].onToggle();assert.equal(target.selected.size,1);
});

test('audio collections remain audio when their quality target is best available',()=>{
  const {ctx}=fixture();
  const item=ctx.ytdlpCollectionSelection({url:'https://sound.test/song',media:'audio'},'best');
  assert.equal(item.media,'audio');assert.equal(item.quality_target,'audio');
});

test('smart playlist creation resolves aggregate Library to a real configured root',async()=>{
  const {ctx,state,calls}=fixture();
  const source=fs.readFileSync('debripod/static/js/playback-sync.js','utf8');
  vm.runInContext(source.slice(source.indexOf('  async function playlistCreationRoot()'),source.indexOf('  function isSmartPlaylistRel')),ctx);
  state.current={root:{id:'__all__'}};
  await ctx.submitSmartPlaylistCreate('Mixed');
  assert.equal(calls.length,1);assert.equal(calls[0].payload.root_id,'real-root');
  assert.equal(calls[0].payload.name,'Mixed');assert.equal(state.smartPlaylistCreate.submitting,false);
});
