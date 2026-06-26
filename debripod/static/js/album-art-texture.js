var npArtTextureState = {
  canvas: null,
  gl: null,
  program: null,
  buffer: null,
  textures: [null, null],
  images: [null, null],
  currentSrc: "",
  currentSlot: 0,
  nextSlot: 1,
  fadeStart: 0,
  fadeDuration: 0,
  fadeActive: false,
  frame: 0,
  missingTexture: null
};

function currentNowPlayingArtTextureSrc(){
  try{
    const canvas = document.getElementById("npArt");
    return nowPlayingArtSrcValue((canvas && canvas.dataset && canvas.dataset.artSrc) || npArtTextureState.currentSrc || "");
  }catch(e){
    return "";
  }
}

function npArtCompileShader(gl, type, source){
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if(!gl.getShaderParameter(shader, gl.COMPILE_STATUS)){
    try{ console.warn("[DebriPod album art] shader failed", gl.getShaderInfoLog(shader) || ""); }catch(e){}
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function npArtCreateProgram(gl){
  const vs = npArtCompileShader(gl, gl.VERTEX_SHADER, [
    "attribute vec2 pos;",
    "varying vec2 uv;",
    "void main(){",
    "  uv = pos * 0.5 + 0.5;",
    "  gl_Position = vec4(pos, 0.0, 1.0);",
    "}"
  ].join("\n"));
  const fs = npArtCompileShader(gl, gl.FRAGMENT_SHADER, [
    "precision mediump float;",
    "varying vec2 uv;",
    "uniform sampler2D texA;",
    "uniform sampler2D texB;",
    "uniform vec2 canvasSize;",
    "uniform vec2 sizeA;",
    "uniform vec2 sizeB;",
    "uniform float mixAmount;",
    "vec2 coverUv(vec2 baseUv, vec2 imgSize){",
    "  vec2 safeSize = max(imgSize, vec2(1.0));",
    "  float canvasAspect = canvasSize.x / max(1.0, canvasSize.y);",
    "  float imgAspect = safeSize.x / max(1.0, safeSize.y);",
    "  vec2 outUv = baseUv;",
    "  if(imgAspect > canvasAspect){",
    "    float scale = canvasAspect / imgAspect;",
    "    outUv.x = (baseUv.x - 0.5) * scale + 0.5;",
    "  }else{",
    "    float scale = imgAspect / canvasAspect;",
    "    outUv.y = (baseUv.y - 0.5) * scale + 0.5;",
    "  }",
    "  outUv.y = 1.0 - outUv.y;",
    "  return outUv;",
    "}",
    "void main(){",
    "  vec4 a = texture2D(texA, coverUv(uv, sizeA));",
    "  vec4 b = texture2D(texB, coverUv(uv, sizeB));",
    "  gl_FragColor = mix(a, b, smoothstep(0.0, 1.0, mixAmount));",
    "}"
  ].join("\n"));
  if(!vs || !fs) return null;
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if(!gl.getProgramParameter(program, gl.LINK_STATUS)){
    try{ console.warn("[DebriPod album art] program failed", gl.getProgramInfoLog(program) || ""); }catch(e){}
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

function ensureNowPlayingArtTexture(){
  try{
    const stateObj = npArtTextureState;
    const canvas = document.getElementById("npArt");
    if(!canvas || !canvas.getContext) return false;
    stateObj.canvas = canvas;
    if(stateObj.gl && stateObj.program && stateObj.buffer) return true;
    const gl = canvas.getContext("webgl", {alpha:true, premultipliedAlpha:true, antialias:false, depth:false, stencil:false})
      || canvas.getContext("experimental-webgl", {alpha:true, premultipliedAlpha:true, antialias:false, depth:false, stencil:false});
    if(!gl) return false;
    const program = npArtCreateProgram(gl);
    if(!program) return false;
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
    stateObj.textures = [gl.createTexture(), gl.createTexture()];
    stateObj.textures.forEach(tex=>{
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
    });
    stateObj.gl = gl;
    stateObj.program = program;
    stateObj.buffer = buffer;
    return true;
  }catch(e){
    return false;
  }
}

function resizeNowPlayingArtTexture(){
  const st = npArtTextureState;
  const canvas = st.canvas;
  if(!canvas) return false;
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  const w = Math.max(1, Math.round((rect.width || window.innerWidth || 1) * dpr));
  const h = Math.max(1, Math.round((rect.height || window.innerHeight || 1) * dpr));
  if(canvas.width !== w || canvas.height !== h){
    canvas.width = w;
    canvas.height = h;
    return true;
  }
  return false;
}

function uploadNowPlayingArtTexture(slot, img){
  const st = npArtTextureState;
  const gl = st.gl;
  if(!gl || !st.textures[slot] || !img) return;
  gl.bindTexture(gl.TEXTURE_2D, st.textures[slot]);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
  st.images[slot] = img;
}

function renderNowPlayingArtTexture(ts){
  const st = npArtTextureState;
  if(!ensureNowPlayingArtTexture()) return false;
  const gl = st.gl;
  resizeNowPlayingArtTexture();
  let mixAmount = st.fadeActive ? Math.max(0, Math.min(1, ((Number(ts || performance.now()) - st.fadeStart) / Math.max(1, st.fadeDuration)))) : 1;
  if(st.fadeActive && mixAmount >= 1){
    st.fadeActive = false;
    st.currentSlot = st.nextSlot;
    st.nextSlot = st.currentSlot ? 0 : 1;
    mixAmount = 1;
  }
  const aSlot = st.fadeActive ? st.currentSlot : st.currentSlot;
  const bSlot = st.fadeActive ? st.nextSlot : st.currentSlot;
  const imgA = st.images[aSlot] || {};
  const imgB = st.images[bSlot] || imgA || {};
  gl.viewport(0, 0, st.canvas.width, st.canvas.height);
  gl.clearColor(0, 0, 0, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.useProgram(st.program);
  gl.bindBuffer(gl.ARRAY_BUFFER, st.buffer);
  const pos = gl.getAttribLocation(st.program, "pos");
  gl.enableVertexAttribArray(pos);
  gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, st.textures[aSlot]);
  gl.uniform1i(gl.getUniformLocation(st.program, "texA"), 0);
  gl.activeTexture(gl.TEXTURE1);
  gl.bindTexture(gl.TEXTURE_2D, st.textures[bSlot]);
  gl.uniform1i(gl.getUniformLocation(st.program, "texB"), 1);
  gl.uniform2f(gl.getUniformLocation(st.program, "canvasSize"), st.canvas.width || 1, st.canvas.height || 1);
  gl.uniform2f(gl.getUniformLocation(st.program, "sizeA"), imgA.naturalWidth || imgA.width || 1, imgA.naturalHeight || imgA.height || 1);
  gl.uniform2f(gl.getUniformLocation(st.program, "sizeB"), imgB.naturalWidth || imgB.width || 1, imgB.naturalHeight || imgB.height || 1);
  gl.uniform1f(gl.getUniformLocation(st.program, "mixAmount"), mixAmount);
  gl.drawArrays(gl.TRIANGLES, 0, 6);
  if(st.fadeActive){
    st.frame = requestAnimationFrame(renderNowPlayingArtTexture);
  }else{
    st.frame = 0;
  }
  return true;
}

function setNowPlayingArtTexture(src, opts){
  const art = nowPlayingArtSrcValue(src);
  const options = opts || {};
  const st = npArtTextureState;
  const canvas = document.getElementById("npArt");
  if(canvas && canvas.dataset) canvas.dataset.artSrc = art;
  if(!ensureNowPlayingArtTexture()){
    st.currentSrc = art;
    return;
  }
  const nextKey = nowPlayingArtCompareKey(art);
  const curKey = nowPlayingArtCompareKey(st.currentSrc);
  if(nextKey === curKey){
    renderNowPlayingArtTexture(performance.now());
    return;
  }
  if(!art){
    st.currentSrc = "";
    st.images[st.currentSlot] = null;
    renderNowPlayingArtTexture(performance.now());
    return;
  }
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = function(){
    try{
      const targetSlot = options.animate && st.currentSrc ? st.nextSlot : st.currentSlot;
      uploadNowPlayingArtTexture(targetSlot, img);
      if(options.animate && st.currentSrc){
        st.nextSlot = targetSlot;
        st.fadeStart = performance.now();
        st.fadeDuration = Math.max(80, Number(options.duration || 240));
        st.fadeActive = true;
      }else{
        st.currentSlot = targetSlot;
        st.nextSlot = st.currentSlot ? 0 : 1;
        st.fadeActive = false;
      }
      st.currentSrc = art;
      if(st.frame) cancelAnimationFrame(st.frame);
      renderNowPlayingArtTexture(performance.now());
    }catch(e){}
  };
  img.onerror = function(){
    st.currentSrc = "";
    renderNowPlayingArtTexture(performance.now());
  };
  img.src = art;
}

window.addEventListener("resize", ()=>{ try{ renderNowPlayingArtTexture(performance.now()); }catch(e){} }, {passive:true});
