const assert = require('node:assert/strict');

/*
 * Exercises the complete right-panel handoff in the real shell.  The first
 * contact opens the panel and crosses the wheel centre; only the subsequent
 * circular movement should scroll the panel.  A fresh contact then resumes
 * ordinary wheel selection.
 */
module.exports = async function checkPanelWheel(page, touch, drag, wheel){
  await page.evaluate(()=>{
    DebriPod.rowSystem.setPanelOpen(false, {immediate:true});
    state.current={kind:'metalist',level:'tracks',label:'Wheel panel test'};
    resetList(Array.from({length:42},(_,i)=>({
      kind:'track', media:'audio', root_id:'fixture', rel:`panel-${i}.flac`,
      label:`Panel track ${i}`, artist:'Example artist', album:'Example album',
      track_number:i+1, duration:245, bitrate:1411, bit_depth:24,
      sample_rate:96000, codec:'FLAC', quality_label:'Lossless',
      year:2024, file_size:987654321, source:'Fixture', provider:'Fixture provider',
      description:'A long description that makes the contextual panel overflow.'
    })));
    setSelectionFast(4);
  });
  await page.waitForTimeout(350);

  const initialSelection=await page.evaluate(()=>state.sel);
  const wheelBox=await page.locator('#wheel').boundingBox();
  assert.ok(wheelBox,'wheel should be measurable');
  const cx=wheelBox.x+wheelBox.width/2, cy=wheelBox.y+wheelBox.height/2;
  const panelInner=page.locator('.dpContextPanelInner');
  await page.evaluate(()=>DebriPod.rowSystem.setPanelOpen(true,{immediate:true}));
  await page.waitForTimeout(80);
  const overflow=await panelInner.evaluate(el=>({height:el.clientHeight,scrollHeight:el.scrollHeight,top:el.scrollTop}));
  assert.ok(overflow.scrollHeight>overflow.height+10,JSON.stringify(overflow));
  await page.evaluate(()=>{
    DebriPod.rowSystem.setPanelOpen(false,{immediate:true});
    document.querySelector('.dpContextPanelInner').scrollTop=0;
  });

  // Open at the centre, then cross to the left and rotate around that side.
  await touch('touchStart',cx+wheelBox.width*.39,cy);
  await touch('touchMove',cx+wheelBox.width*.20,cy);
  await touch('touchMove',cx,cy);
  await touch('touchMove',cx-wheelBox.width*.05,cy);
  await touch('touchMove',cx-wheelBox.width*.12,cy-wheelBox.width*.12);
  await page.waitForTimeout(100);
  const handedOff=await page.evaluate(()=>({
    state:DebriPod.wheelInteraction.state(), panelOpen:DebriPod.rowSystem.isPanelOpen(),
    panelTop:document.querySelector('.dpContextPanelInner').scrollTop, selection:state.sel
  }));
  assert.equal(handedOff.state,'right_panel_scroll_gesture');
  assert.equal(handedOff.panelOpen,true);
  assert.ok(handedOff.panelTop>0,JSON.stringify(handedOff));
  assert.equal(handedOff.selection,initialSelection,'panel handoff must not move list selection');
  await touch('touchEnd');
  await page.waitForTimeout(100);
  assert.equal(await page.evaluate(()=>DebriPod.wheelInteraction.isActive()),false);

  // The next contact is an ordinary circular wheel gesture.  It must update
  // the list selection instead of continuing to scroll the panel.
  const beforeNext=await page.evaluate(()=>state.sel);
  const radius=wheelBox.width*.20;
  const points=[];
  for(let i=0;i<=12;i++){
    const angle=(-90+i*5)*Math.PI/180;
    points.push([cx+Math.cos(angle)*radius,cy+Math.sin(angle)*radius]);
  }
  await touch('touchStart',points[0][0],points[0][1]);
  for(const [x,y] of points.slice(1)) await touch('touchMove',x,y);
  await touch('touchEnd');
  await page.waitForTimeout(500);
  const afterNext=await page.evaluate(()=>({selection:state.sel,panelTop:document.querySelector('.dpContextPanelInner').scrollTop}));
  assert.ok(afterNext.selection!==beforeNext,'next wheel contact should resume list scrolling');
  assert.ok(afterNext.panelTop>=handedOff.panelTop,'list wheel must not reverse panel scroll');

  // A right pull while already open never emits a close/reopen animation.
  const animationBefore=await page.evaluate(()=>document.querySelector('.dpContextPanel').getAnimations().length);
  await drag(cx+wheelBox.width*.39,cy,cx+wheelBox.width*.20,cy);
  const alreadyOpen=await page.evaluate(()=>({open:DebriPod.rowSystem.isPanelOpen(),animations:document.querySelector('.dpContextPanel').getAnimations().length}));
  assert.equal(alreadyOpen.open,true);
  assert.ok(alreadyOpen.animations<=animationBefore+1,'already-open right pull should not restart panel animation');
};
