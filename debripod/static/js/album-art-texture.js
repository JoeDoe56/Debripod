(function(){
  const root = window.DebriPod = window.DebriPod || {};
  let canvas = null;
  let gl = null;
  let program = null;
  let buffer = null;
  let texCurrent = null;
  let texNext = null;
  let currentSrc = "";
  let nextSrc = "";
  let currentImage = null;
  let nextImage = null;
  let currentImageSize = {width:1, height:1};
  let nextImageSize = {width:1, height:1};
  let transitionStart = 0;
  let transitionMs = 0;
  let ready = false;
  let animFrame = 0;
  let glassState = null;
  const vsSource = "attribute vec2 p; varying vec2 uv; void main(){ uv=(p+1.0)*0.5; gl_Position=vec4(p,0.0,1.0); }";
  const fsSource = "precision mediump float; uniform sampler2D currentTex; uniform sampler2D nextTex; uniform float mixNext; uniform vec2 canvasSize; uniform vec2 currentSize; uniform vec2 nextSize; varying vec2 uv; vec2 coverUv(vec2 v, vec2 imageSize){ float ca=canvasSize.x/max(1.0,canvasSize.y); float ia=imageSize.x/max(1.0,imageSize.y); vec2 outUv=v; if(ca>ia){ outUv.y=(v.y-0.5)*ca/ia+0.5; }else{ outUv.x=(v.x-0.5)*ia/ca+0.5; } return vec2(outUv.x, 1.0-outUv.y); } void main(){ vec4 a=texture2D(currentTex,coverUv(uv,currentSize)); vec4 b=texture2D(nextTex,coverUv(uv,nextSize)); gl_FragColor=mix(a,b,mixNext); }";

  function compileShader(type, source){
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if(!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return null;
    return shader;
  }

  function ensure(outputCanvas){
    if(!outputCanvas) return false;
    if(canvas !== outputCanvas){
      canvas = outputCanvas;
      gl = null;
      program = null;
      buffer = null;
      texCurrent = null;
      texNext = null;
      ready = false;
    }
    if(gl) return true;
    const contextOptions = {alpha:true, premultipliedAlpha:true, preserveDrawingBuffer:true};
    gl = canvas.getContext("webgl", contextOptions) || canvas.getContext("experimental-webgl", contextOptions);
    if(!gl) return false;
    const vs = compileShader(gl.VERTEX_SHADER, vsSource);
    const fs = compileShader(gl.FRAGMENT_SHADER, fsSource);
    if(!vs || !fs) return false;
    program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if(!gl.getProgramParameter(program, gl.LINK_STATUS)) return false;
    buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
    texCurrent = createTexture();
    texNext = createTexture();
    return !!(texCurrent && texNext);
  }

  function createTexture(){
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0,0,0,0]));
    return tex;
  }

  function compileShaderFor(ctx, type, source){
    const shader = ctx.createShader(type);
    ctx.shaderSource(shader, source);
    ctx.compileShader(shader);
    if(!ctx.getShaderParameter(shader, ctx.COMPILE_STATUS)) return null;
    return shader;
  }

  function createTextureFor(ctx){
    const tex = ctx.createTexture();
    ctx.bindTexture(ctx.TEXTURE_2D, tex);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_MIN_FILTER, ctx.LINEAR);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_MAG_FILTER, ctx.LINEAR);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_WRAP_S, ctx.CLAMP_TO_EDGE);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_WRAP_T, ctx.CLAMP_TO_EDGE);
    ctx.texImage2D(ctx.TEXTURE_2D, 0, ctx.RGBA, 1, 1, 0, ctx.RGBA, ctx.UNSIGNED_BYTE, new Uint8Array([0,0,0,0]));
    return tex;
  }

  function createRenderState(outputCanvas){
    if(!outputCanvas) return null;
    const contextOptions = {alpha:true, premultipliedAlpha:true, preserveDrawingBuffer:true};
    const ctx = outputCanvas.getContext("webgl", contextOptions) || outputCanvas.getContext("experimental-webgl", contextOptions);
    if(!ctx) return null;
    const vs = compileShaderFor(ctx, ctx.VERTEX_SHADER, vsSource);
    const fs = compileShaderFor(ctx, ctx.FRAGMENT_SHADER, fsSource);
    if(!vs || !fs) return null;
    const prog = ctx.createProgram();
    ctx.attachShader(prog, vs);
    ctx.attachShader(prog, fs);
    ctx.linkProgram(prog);
    if(!ctx.getProgramParameter(prog, ctx.LINK_STATUS)) return null;
    const buf = ctx.createBuffer();
    ctx.bindBuffer(ctx.ARRAY_BUFFER, buf);
    ctx.bufferData(ctx.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), ctx.STATIC_DRAW);
    const cur = createTextureFor(ctx);
    const next = createTextureFor(ctx);
    if(!cur || !next) return null;
    return {
      canvas: outputCanvas,
      gl: ctx,
      program: prog,
      buffer: buf,
      texCurrent: cur,
      texNext: next,
      uploadedCurrentSrc: "",
      uploadedNextSrc: ""
    };
  }

  function upload(tex, image){
    if(!gl || !tex || !image || !image.naturalWidth || !image.naturalHeight) return false;
    try{
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      return true;
    }catch(e){
      return false;
    }
  }

  function uploadFor(ctx, tex, image){
    if(!ctx || !tex || !image || !image.naturalWidth || !image.naturalHeight) return false;
    try{
      ctx.bindTexture(ctx.TEXTURE_2D, tex);
      ctx.pixelStorei(ctx.UNPACK_FLIP_Y_WEBGL, false);
      ctx.texImage2D(ctx.TEXTURE_2D, 0, ctx.RGBA, ctx.RGBA, ctx.UNSIGNED_BYTE, image);
      return true;
    }catch(e){
      return false;
    }
  }

  function loadImage(src, cb){
    const img = new Image();
    img.decoding = "async";
    try{ img.crossOrigin = "anonymous"; }catch(e){}
    img.onload = ()=> cb(null, img);
    img.onerror = ()=> cb(new Error("Album art failed to load"));
    img.src = src;
  }

  function resizeCanvasToDisplay(outputCanvas){
    const rect = outputCanvas.getBoundingClientRect();
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const w = Math.max(1, Math.round((rect.width || outputCanvas.clientWidth || 1) * dpr));
    const h = Math.max(1, Math.round((rect.height || outputCanvas.clientHeight || 1) * dpr));
    if(outputCanvas.width !== w || outputCanvas.height !== h){
      outputCanvas.width = w;
      outputCanvas.height = h;
    }
    return {width:w, height:h};
  }

  function resizeCanvasToElement(outputCanvas, referenceEl){
    const rect = referenceEl ? referenceEl.getBoundingClientRect() : outputCanvas.getBoundingClientRect();
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const w = Math.max(1, Math.round((rect.width || referenceEl && referenceEl.clientWidth || outputCanvas.clientWidth || 1) * dpr));
    const h = Math.max(1, Math.round((rect.height || referenceEl && referenceEl.clientHeight || outputCanvas.clientHeight || 1) * dpr));
    if(outputCanvas.width !== w || outputCanvas.height !== h){
      outputCanvas.width = w;
      outputCanvas.height = h;
    }
    return {width:w, height:h};
  }

  function finishTransition(){
    if(nextSrc){
      const tmpTex = texCurrent;
      texCurrent = texNext;
      texNext = tmpTex;
      currentSrc = nextSrc;
      currentImage = nextImage;
      currentImageSize = nextImageSize;
      nextSrc = "";
      nextImage = null;
      transitionStart = 0;
      transitionMs = 0;
      if(glassState){
        glassState.uploadedCurrentSrc = "";
        glassState.uploadedNextSrc = "";
      }
    }
  }

  function cancelTransitionFrame(){
    try{
      if(animFrame === -1 && root.frameScheduler && root.frameScheduler.cancel){
        root.frameScheduler.cancel("album-art-transition");
      }else if(animFrame){
        cancelAnimationFrame(animFrame);
      }
    }catch(e){}
    animFrame = 0;
  }

  function requestTransitionFrame(fn){
    try{
      if(root.frameScheduler && root.frameScheduler.request){
        animFrame = -1;
        root.frameScheduler.request("album-art-transition", fn);
        root.frameScheduler.mark({render:true, keepAlive:true});
        return;
      }
    }catch(e){}
    animFrame = requestAnimationFrame(fn);
  }

  function animationIntervalMs(){
    try{
      const ui = root.uiSettings || {};
      const settings = ui.settings || {};
      const fps = ui.normalizeAnimationFps ? ui.normalizeAnimationFps(settings.animationFps && settings.animationFps.albumArtTransition) : 60;
      return 1000 / fps;
    }catch(e){
      return 1000 / 60;
    }
  }

  function setSource(src, options){
    const next = String(src || "").trim();
    const opts = options || {};
    if(next === currentSrc || next === nextSrc) return;
    if(!next){
      currentSrc = "";
      nextSrc = "";
      currentImage = null;
      nextImage = null;
      ready = false;
      cancelTransitionFrame();
      renderToCanvas(document.getElementById("npArt"));
      return;
    }
    loadImage(next, (err, img)=>{
      if(err || !img) return;
      const outputCanvas = document.getElementById("npArt");
      if(!ensure(outputCanvas)) return;
      const animate = !!(opts.animate && ready && currentSrc);
      const targetTex = animate ? texNext : texCurrent;
      if(!upload(targetTex, img)) return;
      if(animate){
        nextSrc = next;
        nextImage = img;
        nextImageSize = {width:img.naturalWidth || 1, height:img.naturalHeight || 1};
        transitionStart = performance.now ? performance.now() : Date.now();
        transitionMs = Math.max(1, Number(opts.duration || 220));
      }else{
        currentSrc = next;
        currentImage = img;
        currentImageSize = {width:img.naturalWidth || 1, height:img.naturalHeight || 1};
        nextSrc = "";
        nextImage = null;
        transitionStart = 0;
        transitionMs = 0;
      }
      ready = true;
      renderToCanvas(outputCanvas);
      try{ if(typeof scheduleNpOverlayGlassRender === "function") scheduleNpOverlayGlassRender(); }catch(e){}
      if(animate) animateTransition(outputCanvas);
    });
  }

  function animateTransition(outputCanvas){
    cancelTransitionFrame();
    let lastTick = 0;
    const tick = (frameState)=>{
      animFrame = 0;
      const now = (frameState && frameState.timestamp) || (performance && performance.now ? performance.now() : Date.now());
      if(lastTick && now - lastTick < animationIntervalMs() - 1){
        requestTransitionFrame(tick);
        return;
      }
      lastTick = now;
      renderToCanvas(outputCanvas);
      try{ if(typeof scheduleNpOverlayGlassRender === "function") scheduleNpOverlayGlassRender(); }catch(e){}
      if(nextSrc){
        requestTransitionFrame(tick);
      }
    };
    requestTransitionFrame(tick);
  }

  function renderToCanvas(outputCanvas){
    if(!ensure(outputCanvas)) return null;
    const size = resizeCanvasToDisplay(outputCanvas);
    gl.viewport(0, 0, size.width, size.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if(!ready || !currentSrc) return null;
    let mix = 0;
    if(nextSrc && transitionStart && transitionMs){
      const now = performance.now ? performance.now() : Date.now();
      mix = Math.max(0, Math.min(1, (now - transitionStart) / transitionMs));
      if(mix >= 1){
        finishTransition();
        mix = 0;
        cancelTransitionFrame();
      }
    }
    gl.useProgram(program);
    const loc = gl.getAttribLocation(program, "p");
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texCurrent);
    gl.uniform1i(gl.getUniformLocation(program, "currentTex"), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, nextSrc ? texNext : texCurrent);
    gl.uniform1i(gl.getUniformLocation(program, "nextTex"), 1);
    gl.uniform1f(gl.getUniformLocation(program, "mixNext"), mix);
    gl.uniform2f(gl.getUniformLocation(program, "canvasSize"), size.width, size.height);
    gl.uniform2f(gl.getUniformLocation(program, "currentSize"), currentImageSize.width, currentImageSize.height);
    gl.uniform2f(gl.getUniformLocation(program, "nextSize"), nextImageSize.width, nextImageSize.height);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    try{ gl.flush(); gl.finish(); }catch(e){}
    return outputCanvas;
  }

  function transitionMix(){
    if(nextSrc && transitionStart && transitionMs){
      const now = performance.now ? performance.now() : Date.now();
      const mix = Math.max(0, Math.min(1, (now - transitionStart) / transitionMs));
      if(mix >= 1){
        finishTransition();
        cancelTransitionFrame();
        return 0;
      }
      return mix;
    }
    return 0;
  }

  function renderStateToCanvas(state, outputCanvas, referenceEl){
    if(!state || !outputCanvas || !ready || !currentSrc || !currentImage) return null;
    if(state.canvas !== outputCanvas) return null;
    const mix = transitionMix();
    const ctx = state.gl;
    const size = resizeCanvasToElement(outputCanvas, referenceEl);
    if(!size.width || !size.height) return null;
    if(state.uploadedCurrentSrc !== currentSrc){
      if(!uploadFor(ctx, state.texCurrent, currentImage)) return null;
      state.uploadedCurrentSrc = currentSrc;
    }
    const activeNextSrc = nextSrc && nextImage ? nextSrc : "";
    if(activeNextSrc && state.uploadedNextSrc !== activeNextSrc){
      if(!uploadFor(ctx, state.texNext, nextImage)) return null;
      state.uploadedNextSrc = activeNextSrc;
    }else if(!activeNextSrc){
      state.uploadedNextSrc = "";
    }
    ctx.viewport(0, 0, size.width, size.height);
    ctx.clearColor(0, 0, 0, 0);
    ctx.clear(ctx.COLOR_BUFFER_BIT);
    ctx.useProgram(state.program);
    const loc = ctx.getAttribLocation(state.program, "p");
    ctx.bindBuffer(ctx.ARRAY_BUFFER, state.buffer);
    ctx.enableVertexAttribArray(loc);
    ctx.vertexAttribPointer(loc, 2, ctx.FLOAT, false, 0, 0);
    ctx.activeTexture(ctx.TEXTURE0);
    ctx.bindTexture(ctx.TEXTURE_2D, state.texCurrent);
    ctx.uniform1i(ctx.getUniformLocation(state.program, "currentTex"), 0);
    ctx.activeTexture(ctx.TEXTURE1);
    ctx.bindTexture(ctx.TEXTURE_2D, activeNextSrc ? state.texNext : state.texCurrent);
    ctx.uniform1i(ctx.getUniformLocation(state.program, "nextTex"), 1);
    ctx.uniform1f(ctx.getUniformLocation(state.program, "mixNext"), activeNextSrc ? mix : 0);
    ctx.uniform2f(ctx.getUniformLocation(state.program, "canvasSize"), size.width, size.height);
    ctx.uniform2f(ctx.getUniformLocation(state.program, "currentSize"), currentImageSize.width, currentImageSize.height);
    ctx.uniform2f(ctx.getUniformLocation(state.program, "nextSize"), nextImageSize.width, nextImageSize.height);
    ctx.drawArrays(ctx.TRIANGLES, 0, 6);
    try{ ctx.flush(); ctx.finish(); }catch(e){}
    return outputCanvas;
  }

  function renderGlassSourceCanvas(){
    const visible = document.getElementById("npArt");
    const glass = document.getElementById("npArtGlassSource");
    if(!glass || !visible || !ready || !currentSrc || !currentImage) return null;
    if(!glassState || glassState.canvas !== glass){
      glassState = createRenderState(glass);
    }
    return renderStateToCanvas(glassState, glass, visible);
  }

  root.albumArtTexture = {
    setSource,
    currentSource: function(){ return nextSrc || currentSrc || ""; },
    renderToCanvas,
    renderGlassSourceCanvas,
    renderFromElements: function(){ return renderToCanvas(document.getElementById("npArt")); },
    sourceCanvas: function(){ return ready ? canvas : null; },
    sourceTexture: function(){ return texCurrent; },
    gl: function(){ return gl; },
    available: function(){ return !!ready; },
    hasTransition: function(){ return !!nextSrc; }
  };
})();
