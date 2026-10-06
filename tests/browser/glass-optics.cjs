/* Native-picker and optical regression checks against local, deterministic data.
 * NODE_PATH must point to an existing Playwright + pngjs installation. */
const {chromium} = require('playwright');
const {PNG} = require('pngjs');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = path.resolve(__dirname, '../..');
const output = path.join(base, '.pytest_cache');
fs.mkdirSync(output, {recursive:true});
const png = new PNG({width:480,height:800});
for(let y=0;y<800;y++) for(let x=0;x<480;x++){
  const i=(y*480+x)*4, stripe=(Math.floor(x/24)+Math.floor(y/24))%2;
  png.data[i]=Math.round(x/480*220)+15;
  png.data[i+1]=Math.round(y/800*190)+20;
  png.data[i+2]=stripe?190:50; png.data[i+3]=255;
}
const wallpaper = PNG.sync.write(png);
function api(url){
  if(url.pathname==='/api/bootstrap') return {ok:true,asset_version:'testing-glass',device_settings_user_id:'glass-test',ui_defaults:{visualizer:true}};
  if(url.pathname==='/api/library/config') return {ok:true,roots:[{id:'fixture',name:'Fixture library',mode:'metadata'}],aggregate_root:{id:'__all__',name:'Library',mode:'metadata'}};
  if(url.pathname==='/api/setup/status') return {ok:true,complete:true,required:false};
  if(url.pathname==='/api/settings') return {ok:true,settings:{},connections:{},tools:{},device_settings_user_id:'glass-test'};
  return {ok:true,items:[],categories:[],tasks:[],now:null,queue:[],history:[],roots:[],settings:{}};
}
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.startsWith('/api/')){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(api(url)));return;}
  const relative=url.pathname==='/'?'debripod/static/shell.html':url.pathname.startsWith('/static/')?'debripod'+url.pathname:url.pathname.slice(1);
  const file=path.resolve(base,relative);
  if(!file.startsWith(base+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
  const types={'.js':'text/javascript','.css':'text/css','.html':'text/html','.png':'image/png','.svg':'image/svg+xml'};
  res.setHeader('Content-Type',types[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,channel:process.env.DEBRIPOD_TEST_BROWSER||'msedge'});
  const page=await browser.newPage({viewport:{width:430,height:932},deviceScaleFactor:3,isMobile:true,hasTouch:true});
  const errors=[],gpuErrors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',msg=>{if(/INVALID_|shader failed|framebuffer unavailable/i.test(msg.text()))gpuErrors.push(msg.text());});
  const url=`http://127.0.0.1:${server.address().port}`;
  try{
    await page.goto(url);
    await page.waitForFunction(()=>window.liquidGlassReady && window.DebriPod?.wallpaper && typeof viewLibUiSettings==='function');
    await page.evaluate(()=>DebriPod.wallpaper.ready);
    await page.evaluate(()=>viewLibUiSettings(true));
    await page.waitForFunction(()=>state.items.some(row=>row.action==='upload_test_wallpaper'));
    const chooserPromise=page.waitForEvent('filechooser');
    await page.evaluate(()=>handleLibUiAction('upload_test_wallpaper'));
    const chooser=await chooserPromise;
    assert.equal(await chooser.element().getAttribute('accept'),'image/*');
    assert.equal(await chooser.element().getAttribute('capture'),null);
    await chooser.setFiles({name:'comparison.png',mimeType:'image/png',buffer:wallpaper});
    await page.waitForFunction(()=>DebriPod.wallpaper.active() && !visualizerEnabled);
    await page.waitForTimeout(200);
    const wheelShapes=await page.evaluate(()=>['wheel','wheelGlassRing','btnCenter','wheelCenterGlass'].map(id=>({id,corner:getComputedStyle(document.getElementById(id)).getPropertyValue('corner-shape')})));
    for(const shape of wheelShapes) assert.ok(['round','superellipse(1)',''].includes(shape.corner),shape.id+' must not inherit the global squircle shadow');
    const initial=await page.evaluate(()=>{
      const renderers=Object.values(window.__liquidGLRenderers__);
      const rows=renderers.map(r=>({key:r.rendererKey,wallpaper:r._wallpaperActive,backend:r.debugState().opticalBackend,
        source:r._sourceUploadRevision,prepares:r._opticalPrepareCount,error:r.gl.getError(),width:r.canvas.width}));
      for(let i=0;i<20;i++) renderLiquidGlassNow();
      return {rows,after:renderers.map(r=>({source:r._sourceUploadRevision,prepares:r._opticalPrepareCount,error:r.gl.getError()}))};
    });
    assert.equal(initial.rows.length,2);
    initial.rows.forEach((row,i)=>{
      assert.equal(row.wallpaper,true);
      assert.equal(row.backend,'shared-mip');
      assert.equal(row.width,645,'keeps the 1.5x backing scale on a 3x display');
      assert.equal(row.error,0);
      assert.equal(initial.after[i].error,0);
      assert.equal(initial.after[i].source,row.source,'static wallpaper is not re-uploaded');
      assert.equal(initial.after[i].prepares,row.prepares,'static optics reuse the prepared backdrop');
    });
    await page.screenshot({path:path.join(output,'testing-glass-wallpaper.png')});
    const contact=await page.evaluate(()=>{
      const r=Object.values(window.__liquidGLRenderers__)[0], lens=r.lenses[0], rect=lens.rectPx;
      let now=performance.now();
      window.dispatchEvent(new PointerEvent('pointerdown',{clientX:rect.left+rect.width/2,clientY:rect.top+rect.height/2}));
      for(let i=0;i<8;i++) r._lensContact(lens,now+=64);
      const pressed={...lens._opticalContact};
      window.dispatchEvent(new PointerEvent('pointercancel'));
      for(let i=0;i<8;i++) r._lensContact(lens,now+=64);
      return {pressed,released:lens._opticalContact.press};
    });
    assert.equal(contact.pressed.press,1,'touch highlight reaches its pressed state');
    assert.ok(Math.abs(contact.pressed.x-0.5)<0.01 && Math.abs(contact.pressed.y-0.5)<0.01);
    assert.equal(contact.released,0,'cancelled touch fully releases its highlight');
    // Bad input leaves the applied image and setting intact.
    assert.equal(await page.evaluate(()=>DebriPod.wallpaper.upload(new File(['bad'],'broken.png',{type:'image/png'}))),false);
    assert.equal(await page.evaluate(()=>DebriPod.wallpaper.active()),true);
    await page.reload();
    await page.waitForFunction(()=>window.liquidGlassReady && window.DebriPod?.wallpaper);
    await page.evaluate(()=>DebriPod.wallpaper.ready);
    assert.equal(await page.evaluate(()=>DebriPod.wallpaper.active() && !visualizerEnabled),true,'restores until the visualizer is enabled');
    await page.evaluate(()=>setVisualizerEnabled(true));
    assert.equal(await page.evaluate(()=>DebriPod.wallpaper.active()),false);
    await page.evaluate(()=>setVisualizerEnabled(false));
    assert.equal(await page.evaluate(()=>DebriPod.wallpaper.active()),false);
    await page.reload();
    await page.waitForFunction(()=>window.liquidGlassReady && window.DebriPod?.wallpaper);
    await page.evaluate(()=>DebriPod.wallpaper.ready);
    assert.equal(await page.evaluate(()=>DebriPod.wallpaper.active()),false,'deleted wallpaper cannot return on reload');
    // Compile and draw the actual bounded-kernel fallback with LOD unavailable.
    const fallback=await browser.newPage({viewport:{width:800,height:600}});
    await fallback.addInitScript(()=>{
      const original=WebGLRenderingContext.prototype.getExtension;
      WebGLRenderingContext.prototype.getExtension=function(name){return name==='EXT_shader_texture_lod'?null:original.call(this,name);};
    });
    await fallback.goto(url+'/tests/fixtures/liquid_gl_signed_material_harness.html');
    await fallback.waitForFunction(()=>window.__liquidGLRenderers__ && Object.keys(window.__liquidGLRenderers__).length===8);
    const samples=await fallback.evaluate(()=>Object.values(window.__liquidGLRenderers__).map(r=>{
      r.render(); const lens=r.lenses[0],p=lens.rectPx,d=r._dpr;
      const color=new Uint8Array(4);r.gl.readPixels(Math.round((p.left+p.width/2)*d),Math.round(r.canvas.height-(p.top+p.height/2)*d),1,1,r.gl.RGBA,r.gl.UNSIGNED_BYTE,color);
      return {backend:r.debugState().opticalBackend,error:r.gl.getError(),color:Array.from(color)};
    }));
    samples.forEach(row=>{assert.equal(row.backend,'bounded-kernel');assert.equal(row.error,0);assert.ok(row.color[3]>240,'glass must remain opaque over an opaque backdrop');});
    assert.ok(samples[0].color.slice(0,3).every(v=>v<12),'dark endpoint');
    assert.ok(samples[6].color.slice(0,3).every(v=>v>240),'light endpoint');
    await fallback.screenshot({path:path.join(output,'testing-glass-fallback.png')});
    await fallback.close();
    assert.deepEqual(errors,[]);assert.deepEqual(gpuErrors,[]);
    console.log(JSON.stringify({ok:true,initial,samples,screenshots:output},null,2));
  }catch(error){await page.screenshot({path:path.join(output,'testing-glass-failure.png')});console.error({errors,gpuErrors});throw error;}
  finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
