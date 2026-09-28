const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||'msedge'});try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.setContent('<ul id="libList"></ul>');
  await page.evaluate(()=>{
    window.state={sel:0,smartPlaylistCreate:{editing:false,editValue:'',submitting:false}};
    window.submissions=[];window.renders=0;
    window.appendExpandedSubRow=()=>{};window.prepareGlassPill=(el,text)=>el.textContent=text;window.setGlassText=(el,text)=>el.textContent=text;
    window.beginSmartPlaylistCreateEdit=()=>{state.smartPlaylistCreate.editing=true;renderList();};
    window.submitSmartPlaylistCreate=name=>submissions.push(name);
  });
  const source=fs.readFileSync('debripod/static/js/list-view.js','utf8').replace(/\r\n/g,'\n');
  const row=source.slice(source.indexOf('      // Special inline input rows'),source.indexOf('      const labelWrap = document.createElement("span");',source.indexOf('      // Special inline input rows')));
  const focus=source.slice(source.indexOf('    if(editInputToFocus){'),source.indexOf('    try{\n      refreshSelectedHScrollText();',source.indexOf('    if(editInputToFocus){')));
  await page.addScriptTag({content:`function renderList(){if(++renders>10)throw new Error('recursive input rendering');libList.replaceChildren();const itemsLayer=libList;let editInputToFocus=null;for(const i of [0]){const it={kind:'smart_playlist_create',label:'Create smart playlist'},isSel=true,li=document.createElement('li');${row}}${focus}}renderList();`});
  assert.deepEqual(errors,[]);
  await page.locator('li').click();await page.locator('input').fill('Mixed media');
  await page.locator('input').press('Enter');
  assert.deepEqual(await page.evaluate(()=>submissions),['Mixed media']);
  assert.ok(await page.evaluate(()=>renders)<5);
  assert.deepEqual(errors,[]);console.log('Smart playlist editor: click, focus, typing and Enter submit without recursive rendering');
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exit(1);});
