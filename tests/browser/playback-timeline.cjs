// Run with Playwright available, or set PLAYWRIGHT_MODULE to its installed path.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async()=>{
  const browser = await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try{
    for(const scenario of ['gapless','spaced','skip','seek']){
      const page=await browser.newPage();
      await page.evaluate(()=>{
        window.testContext=new OfflineAudioContext(1,24000,48000);
        window.AudioContext=function(){return window.testContext;};
      });
      await page.addScriptTag({content:fs.readFileSync('debripod/static/js/gapless-audio.js','utf8')});
      const result=await page.evaluate(async scenario=>{
        const ctx=window.testContext,api=window.DebriPod.gaplessAudio;
        const make=(n,value)=>{const b=ctx.createBuffer(1,n,48000);b.getChannelData(0).fill(value);return b;};
        const item=rel=>({root:{id:'test'},rel});
        const first=make(4800,.25),second=make(4800,-.5);
        api.start(item('one'),first,item('two'),second,{gap:scenario==='spaced'?.12:0});
        if(scenario==='skip')api.start(item('two'),second,null,null,{gap:0});
        if(scenario==='seek')api.seek(.05);
        const rendered=await ctx.startRendering();
        const data=Array.from(rendered.getChannelData(0));
        return {data};
      },scenario);
      const start=1200,cut=scenario==='seek'?3600:6000;
      const secondStart=scenario==='spaced'?11760:cut;
      if(scenario==='skip'){
        assert.ok(result.data.slice(start,start+4800).every(v=>v===-.5),'skip has one incoming source with no overlap');
      }else{
        assert.ok(result.data.slice(start,cut).every(v=>v===.25),`${scenario}: outgoing samples remain intact`);
        assert.ok(result.data.slice(cut,secondStart).every(v=>v===0),`${scenario}: intentional gap is silent`);
        assert.ok(result.data.slice(secondStart,secondStart+4800).every(v=>v===-.5),`${scenario}: incoming samples remain intact`);
        assert.equal(result.data[cut-1],.25);
        assert.equal(result.data[secondStart],-.5);
      }
      console.log(`${scenario}: OfflineAudioContext samples passed`);
      await page.close();
    }
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
