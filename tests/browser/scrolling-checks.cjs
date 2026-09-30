const assert=require('node:assert/strict');

module.exports=async function checkScrolling(page,touch,drag,wheel){
  const root=await page.evaluate(()=>[...document.querySelectorAll('#libList .dpRowSecondary')].every(el=>getComputedStyle(el).display==='none'));
  assert.equal(root,true,'Library root has one line per row');
  await page.evaluate(()=>{
    state.current={kind:'metalist',level:'songs',label:'Songs',root:{id:'__all__'}};
    resetList(Array.from({length:10000},(_,i)=>({kind:'track',media:'audio',root_id:i%2?'fixture':'other',rel:`song-${i}.flac`,label:`Song ${i}`,secondary:`Song ${i} · Artist · Artist`,track_number:i+1})));
    setSelectionFast(3);
  });
  await page.waitForTimeout(500);
  assert.ok(await page.locator('#libList .ipodItem').count()<60,'large Songs view stays virtualized');
  assert.equal(await page.locator('#libList .dpRowSecondary').first().textContent(),'Artist');
  assert.equal(await page.evaluate(()=>state.items.some(item=>item.kind==='random')),false);
  const box=await page.locator('#libList').boundingBox();
  const anchor=await page.evaluate(()=>{
    const list=libList.getBoundingClientRect(),row=libList.querySelector('.sel').getBoundingClientRect();
    return row.top+row.height/2-list.top;
  });
  const x=box.x+box.width*.65,y=box.y+box.height*.78;
  await touch('touchStart',x,y);
  await touch('touchMove',x,y-30);
  await page.waitForTimeout(250);
  assert.equal(await page.evaluate(()=>DebriPod.listScroll.isDirectScrolling()),true,'stationary held finger must retain scroll ownership');
  assert.equal(await page.evaluate(()=>getComputedStyle(document.getElementById('libListSelectedGlass')).visibility),'hidden');
  assert.equal(await page.evaluate(()=>[...libList.querySelectorAll('.dpRowPrimary,.dpRowSecondary')].some(el=>el.style.clipPath)),false,'hidden glass leaves no native text holes');
  for(let step=1;step<=10;step++){await touch('touchMove',x,y-30-step*16);await page.waitForTimeout(12);}
  await touch('touchEnd');
  await page.waitForFunction(()=>!DebriPod.listScroll.isDirectScrolling());
  await page.waitForTimeout(400);
  const settled=await page.evaluate(()=>{
    const list=libList.getBoundingClientRect(),row=libList.querySelector('.sel').getBoundingClientRect();
    return {anchor:row.top+row.height/2-list.top,index:state.sel,top:libList.scrollTop,height:row.height,visible:getComputedStyle(document.getElementById('libListSelectedGlass')).visibility};
  });
  assert.ok(settled.index>3,'finger scrolling selects the new row beneath the screen anchor');
  assert.ok(Math.abs(settled.anchor-anchor)<=settled.height/2+2,JSON.stringify({anchor,settled}));
  assert.notEqual(settled.visible,'hidden');
  // Repeated wheel updates are coalesced without losing detents or rebuilding the full list.
  const fast=await page.evaluate(async()=>{
    const start=state.sel,frames=[];let last=performance.now();
    for(let i=0;i<12;i++){
      queueSelectionStep("scroll_forward");queueSelectionStep("scroll_forward");queueSelectionStep("scroll_forward");
      await new Promise(requestAnimationFrame);const now=performance.now();frames.push(now-last);last=now;
    }
    await new Promise(resolve=>setTimeout(resolve,180));
    return {steps:state.sel-start,rows:libList.querySelectorAll('.ipodItem').length,visible:getComputedStyle(document.getElementById('libListSelectedGlass')).visibility,frames};
  });
  await page.waitForFunction(()=>libList._dpScrollAnimTarget==null && !listSelectionMotion.rapidInput,{},{timeout:5000}).catch(async error=>{
    console.log('Scroll timeout',await page.evaluate(()=>({top:libList.scrollTop,target:libList._dpScrollAnimTarget,frame:libList._dpScrollAnimFrame,scroll:DebriPod.listScroll.phase(),motion:listSelectionMotion,scheduler:DebriPod.frameScheduler.stats()})));throw error;
  });
  await page.waitForFunction(()=>getComputedStyle(document.getElementById("libListSelectedGlass")).visibility!=="hidden");
  fast.visible=await page.evaluate(()=>getComputedStyle(document.getElementById("libListSelectedGlass")).visibility);
  assert.equal(fast.steps,36,'wheel batching preserves every detent');
  assert.ok(fast.rows<60);
  assert.notEqual(fast.visible,'hidden');
  // Exercise actual pointer arbitration and selectItem with a distant cached Songs row.
  await page.evaluate(()=>{
    window._scrollTest={startAudioFromItem,random:Math.random,forceFullscreenOn,started:[],fullscreen:0};
    startAudioFromItem=async(item,queue,index)=>_scrollTest.started.push({rel:item.rel,root:item.root.id,index,count:queue.length,valid:queue.every(it=>!!it.root?.id)});
    Math.random=()=>.99999;
    forceFullscreenOn=()=>{_scrollTest.fullscreen++;};
  });
  const cx=wheel.x+wheel.width/2,cy=wheel.y+wheel.height/2;
  try{
    await drag(cx,cy+wheel.height*.39,cx,cy);
    await page.waitForFunction(()=>_scrollTest.started.length===1);
    const played=await page.evaluate(()=>_scrollTest.started[0]);
    assert.equal(played.rel,'song-9999.flac');assert.equal(played.index,9999);
    assert.equal(played.count,10000);assert.equal(played.valid,true);
    assert.ok(await page.locator('#libList .ipodItem').count()<60);
    await drag(cx,cy-wheel.height*.39,cx,cy);
    assert.equal(await page.evaluate(()=>_scrollTest.fullscreen),1);
  }finally{
    await page.evaluate(()=>{startAudioFromItem=_scrollTest.startAudioFromItem;Math.random=_scrollTest.random;forceFullscreenOn=_scrollTest.forceFullscreenOn;delete window._scrollTest;});
  }
  console.log('Scrolling stress:',JSON.stringify({settled,fast}));
};
