/* Run with NODE_PATH pointing to an existing Playwright installation.
 * Uses deterministic API fixtures; never touches the user's library/accounts. */
const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {PNG} = require('pngjs');
const base = path.resolve(__dirname, '../..');
const output = path.join(base, '.pytest_cache');
const types={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.ttf':'font/ttf','.woff2':'font/woff2','.png':'image/png','.html':'text/html'};
const calls=[];
function api(url){
  if(url.pathname==='/api/bootstrap') return {ok:true,asset_version:'redesign-smoke',device_settings_user_id:'smoke',ui_defaults:{visualizer:false}};
  if(url.pathname==='/api/library/config') return {ok:true,roots:[{id:'fixture',name:'Fixture library',mode:'metadata'}],aggregate_root:{id:'__all__',name:'Library',mode:'metadata'}};
  if(url.pathname==='/api/setup/status') return {ok:true,complete:true,required:false};
  if(url.pathname==='/api/settings') return {ok:true,settings:{},connections:{},tools:{},device_settings_user_id:'smoke'};
  if(url.pathname==='/api/lyrics') return {ok:true,lyrics:{syncedLyrics:['[00:00]First line','[00:03]A line above the artwork','[00:07]Following the playback clock',...Array.from({length:27},(_,i)=>`[${String(Math.floor((10+i*3)/60)).padStart(2,'0')}:${String((10+i*3)%60).padStart(2,'0')}]Another lyric line ${i+4}`)].join('\n')}};
  if(url.pathname==='/api/auth/status') return {ok:true,logged_in:false,username:'Fixture'};
  if(url.pathname==='/api/library/metadata') return {ok:true,items:[],categories:[]};
  return {ok:true,items:[],tasks:[],now:null,queue:[],history:[],roots:[],settings:{}};
}
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/fixture-art.svg'){
    res.setHeader('Content-Type','image/svg+xml');
    res.end('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600"><defs><linearGradient id="a" x2="1" y2="1"><stop stop-color="#214758"/><stop offset="1" stop-color="#a55536"/></linearGradient></defs><rect width="600" height="600" fill="url(#a)"/><circle cx="360" cy="230" r="160" fill="#d1a279"/><path d="M0 520 280 210 600 500v100H0" fill="#283437"/></svg>');return;
  }
  if(url.pathname.startsWith('/api/')){calls.push(url.pathname);res.setHeader('Content-Type','application/json');res.end(JSON.stringify(api(url)));return;}
  const file=url.pathname==='/' ? path.join(base,'debripod/static/shell.html') : path.join(base,url.pathname.startsWith('/icons/') && !url.pathname.endsWith('.svg')?'debripod/static'+url.pathname:url.pathname.startsWith('/static/')?'debripod'+url.pathname:url.pathname);
  if(!file.startsWith(base+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',types[path.extname(file)]||'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,channel:process.env.DEBRIPOD_TEST_BROWSER || 'msedge'});
  const page=await browser.newPage({viewport:{width:430,height:932},deviceScaleFactor:3,isMobile:true,hasTouch:true});
  const errors=[];const missing=[];
  const cdp=await page.context().newCDPSession(page);
  const touch=async(type,x,y)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:type==='touchEnd'||type==='touchCancel'?[]:[{x,y}],modifiers:0});
  async function drag(x,y,toX,toY){
    await touch('touchStart',x,y);
    for(let step=1;step<=12;step++){await touch('touchMove',x+(toX-x)*step/12,y+(toY-y)*step/12);await page.waitForTimeout(12);}
    await touch('touchEnd');
    await page.waitForTimeout(350);
  }
  page.on('pageerror',error=>errors.push(error.message));
  page.on('response',response=>{if(response.status()===404&&/\.(png|svg|ttf|woff2|css|js)(\?|$)/.test(response.url()))missing.push(response.url());});
  try{
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.waitForFunction(()=>window.state&&state.items.length>5&&document.querySelector('.dpStandardRow'));
    await page.evaluate(()=>document.fonts.ready);
    await page.screenshot({path:path.join(output,'redesign-library.png')});
    const before=await page.locator('#libList').boundingBox();
    const wheel=await page.locator('#wheel').boundingBox();
    const cx=wheel.x+wheel.width/2,cy=wheel.y+wheel.height/2;
    await drag(cx+wheel.width*.39,cy,cx-wheel.width*.05,cy);
    assert.equal(await page.evaluate(()=>DebriPod.rowSystem.isPanelOpen()),true,'right wheel pull opens the panel');
    const after=await page.locator('#libList').boundingBox();
    assert.ok(after.width<before.width-50,'panel must reclaim list width');
    const panel=await page.locator('.dpContextPanel').boundingBox();
    assert.ok(after.x+after.width<=panel.x+1,'panel must not overlay list');
    await page.screenshot({path:path.join(output,'redesign-panel.png')});
    await drag(cx,cy,cx+wheel.width*.39,cy);
    assert.equal(await page.evaluate(()=>DebriPod.rowSystem.isPanelOpen()),false,'center to right closes the panel');
    const selectionBefore=await page.evaluate(()=>state.sel);
    await drag(cx+wheel.width*.23,cy,cx,cy+wheel.width*.03);
    assert.equal(await page.evaluate(()=>DebriPod.rowSystem.isPanelOpen()),true,'short inner Next Track pull opens the panel');
    assert.equal(await page.evaluate(()=>state.sel),selectionBefore,'edge pull does not also scroll the list');
    await drag(cx,cy,cx+wheel.width*.39,cy);
    const initial=await page.evaluate(()=>({height:document.querySelector('.dpStandardRow').getBoundingClientRect().height,font:getComputedStyle(document.querySelector('.dpStandardRow')).fontFamily,pills:[...document.querySelectorAll('.dpStandardRow .ipodPills')].filter(x=>getComputedStyle(x).display!=='none').length}));
    assert.equal(initial.pills,0);assert.match(initial.font,/Host Grotesk/);
    await require('./scrolling-checks.cjs')(page,touch,drag,wheel);
    await page.evaluate(()=>{
      DebriPod.rowSystem.setPanelOpen(false);
      state.current={kind:'metalist',label:'Album',level:'tracks'};
      resetList([{kind:'track',media:'audio',rel:'one.flac',root:{id:'fixture'},label:'A long recording title that should fade smoothly as the panel claims space',artist:'Example artist',album:'Example album',track_number:1,bitrate:1411,bit_depth:24,sample_rate:96000,duration:245},
        {kind:'track',media:'audio',rel:'two.mp3',root:{id:'fixture'},label:'Second recording',track_number:2,bitrate:128,duration:192},
        {kind:'movie',media:'video',rel:'film.mp4',root:{id:'fixture'},label:'A film',duration:7200,position:3600}]);
    });
    await page.waitForTimeout(300);
    await page.screenshot({path:path.join(output,'redesign-media.png')});
    assert.equal(await page.locator('.dpStandardRow').count(),3);
    const sparse=await page.evaluate(()=>{
      const row=libList.querySelectorAll('.dpStandardRow')[1],primary=row.querySelector('.dpRowPrimary');
      const a=row.getBoundingClientRect(),b=primary.getBoundingClientRect();
      return {offset:Math.abs(a.top+a.height/2-b.top-b.height/2),secondary:getComputedStyle(row.querySelector('.dpRowSecondary')).display,menuWeight:getComputedStyle(document.querySelector('.menuWord')).fontWeight};
    });
    assert.ok(sparse.offset<1,'rows without secondary information center their primary line');
    assert.equal(sparse.secondary,'none');assert.equal(sparse.menuWeight,'800');

    const rowChecks=await page.evaluate(()=>{
      const row=document.querySelector('.dpStandardRow.sel');
      const parts=['.dpRowPrimary','.dpRowSecondary','.dpRowIconArea'].map(s=>row.querySelector(s));
      const before=parts.map(el=>el.getBoundingClientRect().y);
      row.style.setProperty('--dp-selected-content-offset-y','13px');
      const movement=parts.map((el,i)=>el.getBoundingClientRect().y-before[i]);
      row.style.removeProperty('--dp-selected-content-offset-y');
      return {movement,base:uiSettings.textOpacity,colors:parts.map(el=>getComputedStyle(el).color),secondaryOpacity:getComputedStyle(parts[1]).opacity};
    });
    assert.equal(rowChecks.base,.4);
    assert.deepEqual(rowChecks.movement,[13,13,13],'all selected row content moves together');
    assert.ok(rowChecks.colors.every(color=>color==='rgba(255, 255, 255, 0.8)'),JSON.stringify(rowChecks));
    assert.equal(rowChecks.secondaryOpacity,'1','secondary text retains full stronger foreground alpha');
    const refraction=await page.evaluate(()=>{
      const api=DebriPod.rowRefraction;
      const neighbor=document.querySelectorAll('.dpStandardRow')[1];
      const rect=neighbor.getBoundingClientRect();
      const lens={left:rect.left,top:rect.top-5,width:rect.width,height:55};
      const primary=neighbor.querySelector('.dpRowPrimary');
      const oldMask=primary.style.maskImage;
      const source=api.prepare(lens,22);
      const path=primary.style.clipPath;
      const moved=api.prepare({...lens,top:lens.top+1},22);
      const pixels=source.canvas.getContext('2d').getImageData(0,0,source.canvas.width,source.canvas.height).data;
      const result={hasText:pixels.some((value,index)=>index%4===3&&value>0),stableTexture:source.revision===moved.revision,nativePath:CSS.supports('clip-path',path)&&path.startsWith('path(evenodd'),maskUnchanged:primary.style.maskImage===oldMask};
      api.clear();
      return result;
    });
    assert.deepEqual(refraction,{hasText:true,stableTexture:true,nativePath:true,maskUnchanged:true},'text refraction retains a stable texture and synchronous native cutout');
    await page.evaluate(()=>{window.testActions=[];DebriPod.mediaActions.executeWheelAction=(action)=>window.testActions.push(action);});
    await touch('touchStart',cx,cy);await page.waitForTimeout(380);
    assert.equal(await page.locator('#wheel.wheelActionMode').count(),1,'hold transforms the wheel');
    await touch('touchMove',cx,cy-wheel.width*.36);
    assert.equal(await page.locator('.wlTop.uiSelectedStateActive').count(),1,'drag selects Like');
    await page.evaluate(()=>updateWheelLabels());
    assert.equal(await page.locator('.wlTop .wheelIcon').getAttribute('data-sf-symbol'),'heart','playback updates preserve the active action overlay');
    await page.screenshot({path:path.join(output,'redesign-action.png')});
    await touch('touchMove',cx,cy);await touch('touchEnd');
    assert.deepEqual(await page.evaluate(()=>window.testActions),[],'dead-zone release cancels');
    await touch('touchStart',cx,cy);await page.waitForTimeout(380);
    await touch('touchMove',cx+wheel.width*.36,cy);await touch('touchEnd');
    assert.deepEqual(await page.evaluate(()=>window.testActions),['play_next'],'release commits one action');
    assert.equal(await page.locator('#wheel.wheelActionMode').count(),0);
    await page.evaluate(()=>{
      state.now={rootId:'fixture',rel:'one.flac',media:'audio'};
      state.nowMeta={title:'Example recording',artist:'Example artist',album:'Example album',duration:245,art:'/fixture-art.svg'};
      showNowPlaying(true,{immediate:true});
      setNowPlayingArtSrc('/fixture-art.svg',{animate:false});
    });
    await page.waitForTimeout(300);
    const art=page.locator('#nowPlaying');
    const artworkBefore=await art.boundingBox();
    const sharpRegion={x:artworkBefore.x+artworkBefore.width*.72,y:artworkBefore.y+artworkBefore.height*.22,width:artworkBefore.width*.2,height:artworkBefore.height*.55};
    const sharpBefore=PNG.sync.read(await page.screenshot({clip:sharpRegion}));
    await drag(cx-wheel.width*.39,cy,cx+wheel.width*.05,cy);
    await page.waitForFunction(()=>document.querySelector('.npLyrics[data-mode="synced"]'));
    await page.waitForTimeout(300);
    await page.screenshot({path:path.join(output,'redesign-lyrics.png')});
    const sharpAfter=PNG.sync.read(await page.screenshot({clip:sharpRegion}));
    const rightPixelDifference=sharpAfter.data.reduce((total,value,index)=>total+(index%4===3?0:Math.abs(value-sharpBefore.data[index])),0)/(sharpAfter.width*sharpAfter.height*3);
    assert.ok(rightPixelDifference<1,'lyrics leave the right cover sharp and unchanged; mean difference '+rightPixelDifference);
    assert.equal(await page.locator('.npLyricLine').count(),30);
    assert.deepEqual(await art.boundingBox(),artworkBefore,'lyrics preserve artwork geometry');
    assert.equal(await page.locator('.npLyricLine.isActive').evaluate(el=>getComputedStyle(el).color),'rgba(255, 255, 255, 0.8)');
    await page.evaluate(()=>{window.lyricSeek=null;window.originalLyricSeek=DebriPod.gaplessAudio.seek;DebriPod.gaplessAudio.seek=time=>{window.lyricSeek=time;return true;};});
    await page.locator('.npLyricLine').nth(1).click();
    assert.equal(await page.evaluate(()=>window.lyricSeek),3,'clicking a lyric seeks to its timestamp');
    await page.evaluate(()=>{DebriPod.gaplessAudio.seek=window.originalLyricSeek;setPlaybackPillsPinned(false);});
    await page.touchscreen.tap(artworkBefore.x+artworkBefore.width*.85,artworkBefore.y+artworkBefore.height*.55);
    await page.waitForTimeout(650);
    assert.equal(await page.evaluate(()=>playbackPillsPinned),true,'unblurred artwork pins pills');
    await page.touchscreen.tap(artworkBefore.x+artworkBefore.width*.85,artworkBefore.y+artworkBefore.height*.55);
    await page.waitForTimeout(650);
    assert.equal(await page.evaluate(()=>playbackPillsPinned),false,'unblurred artwork unpins pills');
    await page.evaluate(()=>{wheelMedia().currentTime=40;DebriPod.lyrics.updatePosition();});
    await page.waitForTimeout(650);
    const centered=await page.locator('.npLyricsLines').evaluate(el=>el.scrollTop);
    assert.ok(centered>100,'playback centers a later lyric');
    const lyricsBounds=await page.locator('.npLyricsLines').boundingBox();
    await page.mouse.move(lyricsBounds.x+lyricsBounds.width/2,lyricsBounds.y+lyricsBounds.height/2);
    await page.mouse.wheel(0,25);
    await page.waitForTimeout(900);
    assert.ok(Math.abs(await page.locator('.npLyricsLines').evaluate(el=>el.scrollTop)-centered)<2,'small native lyric scroll recenters the visible active line');
    await page.mouse.wheel(0,600);
    await page.waitForTimeout(900);
    const browsed=await page.locator('.npLyricsLines').evaluate(el=>el.scrollTop);
    assert.ok(browsed>centered+200,'native wheel scroll can browse away from the active line');
    await page.evaluate(()=>{wheelMedia().currentTime=43;DebriPod.lyrics.updatePosition();});
    await page.waitForTimeout(650);
    assert.ok(Math.abs(await page.locator('.npLyricsLines').evaluate(el=>el.scrollTop)-browsed)<2,'offscreen active line does not pull manual browsing back');
    await drag(cx,cy,cx-wheel.width*.39,cy);
    assert.equal(await page.evaluate(()=>DebriPod.lyrics.isOpen()),false,'reverse left gesture dismisses lyrics');
    await page.evaluate(async()=>{showNowPlaying(false,{immediate:true});await viewLibAdvancedCategory('text',false);});
    await page.waitForTimeout(300);
    await page.screenshot({path:path.join(output,'redesign-settings.png')});
    assert.ok(await page.getByText('Text Opacity',{exact:true}).count());
    await page.evaluate(async()=>{state.sel=0;await selectItem();adjustRangeEditor(5);});
    await page.waitForTimeout(350);
    const feedback=await page.evaluate(()=>({ring:Number(document.querySelector('.dpStandardRow .uiRing').style.getPropertyValue('--ui-ring-progress')),fill:parseFloat(document.querySelector('#npProgressFill').style.width)/100,text:document.querySelector('#npCur').textContent,value:activeRangeEditor().rangeValue,color:getComputedStyle(document.querySelector('#npCur')).color,opacity:getComputedStyle(document.querySelector('#infoPill')).opacity,barRatio:document.querySelector('#npProgressFill').getBoundingClientRect().width/document.querySelector('#npProgressFill').parentElement.getBoundingClientRect().width}));
    assert.ok(Math.abs(feedback.ring-feedback.fill)<.001,'ring and precise bar agree');
    assert.equal(Number(feedback.text),feedback.value);
    assert.equal(feedback.opacity,'1');
    assert.ok(Math.abs(feedback.barRatio-feedback.ring)<.01,'rendered meter agrees with ring');
    await page.screenshot({path:path.join(output,'redesign-adjusting.png')});
    await page.evaluate(()=>openRangeEditorKeyboard());
    await page.locator('.dpRowEditing input').fill('0.63');
    const typed=await page.evaluate(()=>({value:activeRangeEditor().rangeValue,ring:Number(document.querySelector('.dpStandardRow .uiRing').style.getPropertyValue('--ui-ring-progress')),text:document.querySelector('#npCur').textContent}));
    assert.deepEqual(typed,{value:.63,ring:.63,text:'0.63'});
    await page.locator('.dpRowEditing input').press('Enter');
    await page.waitForFunction(()=>!activeRangeEditor());
    assert.equal(await page.evaluate(()=>uiSettings.textOpacity),.63,'numeric keyboard commit persists the new value');
    const frameTiming=await page.evaluate(()=>new Promise(resolve=>{
      const intervals=[];let previous=0;let started=0;
      DebriPod.rowSystem.setPanelOpen(true);
      function frame(now){
        if(!started)started=now;
        if(previous)intervals.push(now-previous);
        previous=now;
        if(now-started<650)return requestAnimationFrame(frame);
        intervals.sort((a,b)=>a-b);
        resolve({samples:intervals.length,medianMs:intervals[Math.floor(intervals.length*.5)],p95Ms:intervals[Math.floor(intervals.length*.95)]});
      }
      requestAnimationFrame(frame);
    }));
    const collectionWrite=await page.evaluate(async()=>{
      DebriPod.rowSystem.setPanelOpen(false);
      const playlistItems=[{media:'audio',root_id:'fixture',rel:'one.flac'},{media:'audio',root_id:'fixture',rel:'two.flac'}];
      await viewMediaPlaylistAdd({playlistItems});
      const original=apiPost;let sent;
      apiPost=async(url,body)=>{sent={url,body};return {ok:true,json:{ok:true}};};
      try{await addCurrentNowPlayingTrackToPlaylist('playlist.m3u8');}finally{apiPost=original;}
      return sent;
    });
    assert.deepEqual(collectionWrite.body.tracks,['one.flac','two.flac'],'playlist picker submits the complete collection');
    assert.equal(await page.locator('.wheelLabel:not([hidden]) .wheelIcon:not([hidden])').count(),3,'playlist picker restores the ordinary wheel overlay');
    assert.equal(await page.locator('.wlTop .menuWord').isVisible(),true,'normal top button says MENU');
    await page.evaluate(()=>viewLibInfo(false));
    await page.waitForTimeout(300);
    await page.screenshot({path:path.join(output,'redesign-info.png')});
    assert.equal(await page.locator('.dpStandardRow:not(:has(.dpRowIconArea .uiSymbol))').count(),0,'Info rows have meaningful symbols');
    for(const width of [390,768]){
      await page.setViewportSize({width,height:900});
      await page.evaluate(()=>DebriPod.rowSystem.setPanelOpen(true));
      await page.waitForTimeout(350);
      await page.screenshot({path:path.join(output,`redesign-${width}.png`)});
      assert.ok((await page.locator('#libList').boundingBox()).width>70);
    }
    assert.deepEqual(errors,[],'browser runtime errors');
    assert.deepEqual(missing,[],'missing UI assets');
    console.log(JSON.stringify({ok:true,initial,iphoneWidths:{before:before.width,after:after.width},feedback,frameTiming,apiRequests:calls.length,screenshots:output},null,2));
  }catch(error){
    console.error(JSON.stringify({errors,missing,body:await page.locator('body').innerText()},null,2));
    await page.screenshot({path:path.join(output,'redesign-failure.png')});
    throw error;
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
