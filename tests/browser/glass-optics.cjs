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
    // The wheel glass is rasterized into a canvas that is itself transformed
    // by the CSS perspective. Verify the live render supplies the same pivot
    // and perspective to the backdrop projection uniform; this guards against
    // refraction becoming a texture glued to the rotating wheel.
    const projection=await page.evaluate(()=>{
      const renderer=window.__liquidGLRenderers__.wheel;
      const lens=renderer.lenses.find(item=>item.el.classList.contains('wheelGlassRing')) || renderer.lenses[0];
      const source=renderer._sourceCssRect || {left:0,top:0,width:innerWidth,height:innerHeight};
      const pivot=lens.options.tiltProjection();
      const calls=[];
      const original=renderer.gl.uniform4f.bind(renderer.gl);
      renderer.gl.uniform4f=function(location,a,b,c,d){
        if(location===renderer.u.tiltProjection) calls.push([a,b,c,d]);
        return original(location,a,b,c,d);
      };
      lens.tiltX=8; lens.tiltY=-6;
      renderer.render({timestamp:performance.now()});
      renderer.gl.uniform4f=original;
      return {pivot,source,calls,last:calls[calls.length-1]};
    });
    assert.ok(projection.last,'wheel render must bind a tilt projection');
    assert.ok(Math.abs(projection.last[0] - (projection.pivot.x-projection.source.left)/projection.source.width)<0.002);
    assert.ok(Math.abs(projection.last[1] - (projection.pivot.y-projection.source.top)/projection.source.height)<0.002);
    assert.equal(projection.last[2],900);
    assert.equal(projection.last[3],1);
    await require('./wheel-projection-checks.cjs')(page);
    await page.screenshot({path:path.join(output,'testing-glass-wallpaper.png')});
    const corners=await page.evaluate(()=>{
      const r=window.__liquidGLRenderers__.main;
      const lens=r.lenses.find(l=>l.el.id==='libList');
      r.render();
      const gl=r.gl, rect=lens.rectPx, dpr=r._dpr;
      const pixel=(x,y)=>{
        const rgba=new Uint8Array(4);
        gl.readPixels(Math.floor((rect.left+x)*dpr),Math.floor(r.canvas.height-(rect.top+y)*dpr),1,1,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
        return [...rgba];
      };
      const coverage=()=>{
        const size=Math.ceil(lens.radiusCss*dpr),data=new Uint8Array(size*size*4);
        gl.readPixels(Math.floor(rect.left*dpr),Math.floor(r.canvas.height-(rect.top+lens.radiusCss)*dpr),size,size,gl.RGBA,gl.UNSIGNED_BYTE,data);
        return data.reduce((sum,value,i)=>sum+(i%4===3?value:0),0);
      };
      const result={power:lens.cornerPower,radius:lens.radiusCss,outer:pixel(.5,.5),smooth:pixel(7,7),center:pixel(rect.width/2,rect.height/2),
        wheelPowers:window.__liquidGLRenderers__.wheel.lenses.map(l=>l.cornerPower),smoothCoverage:coverage()};
      const oldPower=lens.el.style.getPropertyValue('--liquid-corner-power');
      lens.el.style.setProperty('--liquid-corner-power','2'); lens.updateMetrics(); r.render(); result.roundCoverage=coverage();
      if(oldPower)lens.el.style.setProperty('--liquid-corner-power',oldPower);
      else lens.el.style.removeProperty('--liquid-corner-power');
      lens.updateMetrics(); r.render();
      return result;
    });
    assert.equal(corners.power,2.25,'glass renders the same continuous corner as its CSS surface');
    assert.equal(corners.outer[3],0,'continuous corner still rejects pixels outside its silhouette');
    assert.ok(corners.smooth[3]>240,JSON.stringify(corners));
    assert.ok(corners.smoothCoverage>corners.roundCoverage+600,JSON.stringify(corners));
    assert.ok(corners.center[3]>240,'center normal remains finite');
    assert.ok(corners.wheelPowers.every(power=>power===2),'wheel silhouettes stay circular');

    const contact=await page.evaluate(()=>{
      const r=Object.values(window.__liquidGLRenderers__)[0], lens=r.lenses[0], rect=lens.rectPx;
      // A list row or wheel hit region may stop bubbling while it arbitrates
      // the gesture.  The glass contact listener must still see the stream.
      const child=document.createElement('button');
      child.type='button'; child.style.cssText='position:absolute;left:0;top:0;width:1px;height:1px;opacity:0';
      lens.el.appendChild(child);
      child.addEventListener('pointerdown',event=>event.stopPropagation());
      let now=performance.now();
      child.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:rect.left+rect.width/2,clientY:rect.top+rect.height/2,pointerId:19,buttons:1}));
      for(let i=0;i<8;i++) r._lensContact(lens,now+=64);
      const pressed={...lens._opticalContact};
      // Pointer capture changes the event target, but coordinates continue to
      // drive the highlight toward the user's finger.
      lens.el.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:rect.left+rect.width*.8,clientY:rect.top+rect.height*.25,pointerId:19,buttons:1}));
      for(let i=0;i<4;i++) r._lensContact(lens,now+=64);
      const moved={...lens._opticalContact};
      lens.el.dispatchEvent(new PointerEvent('pointercancel',{bubbles:true,pointerId:19}));
      for(let i=0;i<8;i++) r._lensContact(lens,now+=64);
      child.remove();
      return {pressed,moved,released:lens._opticalContact.press};
    });
    assert.equal(contact.pressed.press,1,'touch highlight reaches its pressed state');
    assert.ok(Math.abs(contact.pressed.x-0.5)<0.01 && Math.abs(contact.pressed.y-0.5)<0.01);
    assert.ok(Math.abs(contact.moved.x-.8)<0.02 && Math.abs(contact.moved.y-.75)<0.02,'captured pointer keeps the highlight under the finger');
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
