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
  let currentImageSize = {width:1, height:1};
  let nextImageSize = {width:1, height:1};
  let transitionStart = 0;
  let transitionMs = 0;
  let ready = false;
  let animFrame = 0;

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
    const vs = compileShader(gl.VERTEX_SHADER, "attribute vec2 p; varying vec2 uv; void main(){ uv=(p+1.0)*0.5; gl_Position=vec4(p,0.0,1.0); }");
    const fs = compileShader(gl.FRAGMENT_SHADER, "precision mediump float; uniform sampler2D currentTex; uniform sampler2D nextTex; uniform float mixNext; uniform vec2 canvasSize; uniform vec2 currentSize; uniform vec2 nextSize; varying vec2 uv; vec2 coverUv(vec2 v, vec2 imageSize){ float ca=canvasSize.x/max(1.0,canvasSize.y); float ia=imageSize.x/max(1.0,imageSize.y); vec2 outUv=v; if(ca>ia){ outUv.y=(v.y-0.5)*ca/ia+0.5; }else{ outUv.x=(v.x-0.5)*ia/ca+0.5; } return vec2(outUv.x, 1.0-outUv.y); } void main(){ vec4 a=texture2D(currentTex,coverUv(uv,currentSize)); vec4 b=texture2D(nextTex,coverUv(uv,nextSize)); gl_FragColor=mix(a,b,mixNext); }");
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

  function finishTransition(){
    if(nextSrc){
      const tmpTex = texCurrent;
      texCurrent = texNext;
      texNext = tmpTex;
      currentSrc = nextSrc;
      currentImageSize = nextImageSize;
      nextSrc = "";
      transitionStart = 0;
      transitionMs = 0;
    }
  }

  function setSource(src, options){
    const next = String(src || "").trim();
    const opts = options || {};
    if(next === currentSrc || next === nextSrc) return;
    if(!next){
      currentSrc = "";
      nextSrc = "";
      ready = false;
      try{ if(animFrame) cancelAnimationFrame(animFrame); }catch(e){}
      animFrame = 0;
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
        nextImageSize = {width:img.naturalWidth || 1, height:img.naturalHeight || 1};
        transitionStart = performance.now ? performance.now() : Date.now();
        transitionMs = Math.max(1, Number(opts.duration || 220));
      }else{
        currentSrc = next;
        currentImageSize = {width:img.naturalWidth || 1, height:img.naturalHeight || 1};
        nextSrc = "";
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
    try{ if(animFrame) cancelAnimationFrame(animFrame); }catch(e){}
    const tick = ()=>{
      animFrame = 0;
      renderToCanvas(outputCanvas);
      try{ if(typeof scheduleNpOverlayGlassRender === "function") scheduleNpOverlayGlassRender(); }catch(e){}
      if(nextSrc){
        animFrame = requestAnimationFrame(tick);
      }
    };
    animFrame = requestAnimationFrame(tick);
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
        try{ if(animFrame) cancelAnimationFrame(animFrame); }catch(e){}
        animFrame = 0;
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

  root.albumArtTexture = {
    setSource,
    currentSource: function(){ return nextSrc || currentSrc || ""; },
    renderToCanvas,
    renderFromElements: function(){ return renderToCanvas(document.getElementById("npArt")); },
    sourceCanvas: function(){ return ready ? canvas : null; },
    sourceTexture: function(){ return texCurrent; },
    gl: function(){ return gl; },
    available: function(){ return !!ready; },
    hasTransition: function(){ return !!nextSrc; }
  };
})();
