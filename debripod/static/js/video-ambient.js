(function(){
  var ambient = {canvas:null, context:null, timer:0, running:false, colors:null, lastSample:0, samples:0};

  function clampByte(value){ return Math.max(0, Math.min(255, Math.round(Number(value || 0)) || 0)); }
  function luma(r, g, b){ return (Number(r || 0) * .2126) + (Number(g || 0) * .7152) + (Number(b || 0) * .0722); }
  function nearBlack(data, offset){ return luma(data[offset], data[offset + 1], data[offset + 2]) < 18; }

  function edgeBlackRun(data, width, height, direction){
    var limit = direction === "top" || direction === "bottom" ? Math.floor(height / 3) : Math.floor(width / 3);
    var span = direction === "top" || direction === "bottom" ? width : height;
    var run = 0;
    for(var outer = 0; outer < limit; outer++){
      var row = direction === "bottom" ? height - 1 - outer : outer;
      var column = direction === "right" ? width - 1 - outer : outer;
      var dark = 0;
      for(var inner = 0; inner < span; inner++){
        var x = direction === "top" || direction === "bottom" ? inner : column;
        var y = direction === "top" || direction === "bottom" ? row : inner;
        if(nearBlack(data, (y * width + x) * 4)) dark += 1;
      }
      if(dark / Math.max(1, span) < .88) break;
      run += 1;
    }
    return run;
  }

  function meanColor(data, width, left, top, right, bottom){
    var total = [0, 0, 0];
    var count = 0;
    for(var y = top; y < bottom; y++) for(var x = left; x < right; x++){
      var offset = (y * width + x) * 4;
      if(nearBlack(data, offset)) continue;
      total[0] += data[offset]; total[1] += data[offset + 1]; total[2] += data[offset + 2]; count += 1;
    }
    if(!count) return [0, 0, 0];
    return total.map(value=>clampByte(value / count));
  }

  function sampleVideoAmbientPixels(imageData){
    var data = imageData && imageData.data ? imageData.data : new Uint8ClampedArray();
    var width = Math.max(1, Number(imageData && imageData.width || 1));
    var height = Math.max(1, Number(imageData && imageData.height || 1));
    var topBar = edgeBlackRun(data, width, height, "top");
    var bottomBar = edgeBlackRun(data, width, height, "bottom");
    var leftBar = edgeBlackRun(data, width, height, "left");
    var rightBar = edgeBlackRun(data, width, height, "right");
    var left = Math.min(width - 1, leftBar);
    var right = Math.max(left + 1, width - rightBar);
    var top = Math.min(height - 1, topBar);
    var bottom = Math.max(top + 1, height - bottomBar);
    var contentWidth = Math.max(1, right - left);
    var contentHeight = Math.max(1, bottom - top);
    return {
      left:meanColor(data, width, left, top, Math.max(left + 1, left + Math.ceil(contentWidth * .28)), bottom),
      right:meanColor(data, width, Math.min(right - 1, right - Math.ceil(contentWidth * .28)), top, right, bottom),
      top:meanColor(data, width, left, top, right, Math.max(top + 1, top + Math.ceil(contentHeight * .28))),
      bottom:meanColor(data, width, left, Math.min(bottom - 1, bottom - Math.ceil(contentHeight * .28)), right, bottom),
      bars:{top:topBar, bottom:bottomBar, left:leftBar, right:rightBar}
    };
  }

  function settings(){
    var ui = window.DebriPod && window.DebriPod.uiSettings && window.DebriPod.uiSettings.settings;
    return ui && ui.videoAmbient ? ui.videoAmbient : {enabled:true, sampleFps:8, brightness:1, saturation:1, audioEnergyBrightness:.12, smoothing:.82};
  }

  function activeVideo(){
    var video = document.getElementById("npVideo");
    var overlay = document.getElementById("npVideoOverlay");
    return canSampleVideoAmbient(video, !!(overlay && overlay.style.display !== "none")) ? video : null;
  }

  function canSampleVideoAmbient(video, overlayVisible){
    return !!(video && overlayVisible && !video.paused && !video.ended && video.readyState >= 2 && !!video.src);
  }

  function ensureSurface(){
    var host = document.getElementById("divwrap") || document.body;
    var surface = document.getElementById("videoAmbientBg");
    if(!surface){
      surface = document.createElement("div");
      surface.id = "videoAmbientBg";
      surface.setAttribute("aria-hidden", "true");
      host.insertBefore(surface, host.firstChild || null);
    }
    if(!ambient.canvas){
      ambient.canvas = document.createElement("canvas");
      ambient.canvas.width = 32;
      ambient.canvas.height = 18;
      ambient.context = ambient.canvas.getContext("2d", {willReadFrequently:true});
    }
    return surface;
  }

  function cssColor(color, brightness, saturation){
    var base = color || [0, 0, 0];
    var grey = luma(base[0], base[1], base[2]);
    return "rgb(" + [0, 1, 2].map(index=>clampByte((grey + (base[index] - grey) * saturation) * brightness)).join(",") + ")";
  }

  function sharedAudioEnergy(video){
    try{
      var graph = window.DebriPod && window.DebriPod.mediaAudioGraph;
      var bins = graph && graph.getFrequencyData ? graph.getFrequencyData(video) : null;
      if(!bins || !bins.length) return 0;
      var total = 0;
      for(var index = 0; index < bins.length; index++) total += Number(bins[index] || 0) / 255;
      return Math.max(0, Math.min(1, total / bins.length));
    }catch(e){ return 0; }
  }

  function applyColors(colors, video){
    var cfg = settings();
    var surface = ensureSurface();
    var smoothing = Math.max(0, Math.min(.99, Number(cfg.smoothing == null ? .82 : cfg.smoothing)));
    if(!ambient.colors) ambient.colors = colors;
    else ["left", "right", "top", "bottom"].forEach((key)=>{
      ambient.colors[key] = ambient.colors[key].map((value, index)=>value * smoothing + colors[key][index] * (1 - smoothing));
    });
    var energy = sharedAudioEnergy(video);
    var brightness = Math.max(0, Number(cfg.brightness == null ? 1 : cfg.brightness)) * (1 + energy * Math.max(0, Number(cfg.audioEnergyBrightness || 0)));
    var saturation = Math.max(0, Number(cfg.saturation == null ? 1 : cfg.saturation));
    var left = cssColor(ambient.colors.left, brightness, saturation);
    var right = cssColor(ambient.colors.right, brightness, saturation);
    var top = cssColor(ambient.colors.top, brightness, saturation);
    var bottom = cssColor(ambient.colors.bottom, brightness, saturation);
    surface.style.background = "radial-gradient(ellipse at left center," + left + " 0%,transparent 58%),radial-gradient(ellipse at right center," + right + " 0%,transparent 58%),radial-gradient(ellipse at center top," + top + " 0%,transparent 60%),radial-gradient(ellipse at center bottom," + bottom + " 0%,#000 74%)";
    surface.classList.add("active");
  }

  function sample(){
    ambient.timer = 0;
    var cfg = settings();
    var video = activeVideo();
    if(!cfg.enabled || !video || !ambient.context){
      stop();
      return;
    }
    try{
      ambient.context.drawImage(video, 0, 0, ambient.canvas.width, ambient.canvas.height);
      applyColors(sampleVideoAmbientPixels(ambient.context.getImageData(0, 0, ambient.canvas.width, ambient.canvas.height)), video);
      ambient.samples += 1;
    }catch(e){}
    var fps = Math.max(1, Math.min(30, Number(cfg.sampleFps || 8)));
    ambient.timer = setTimeout(sample, 1000 / fps);
  }

  function start(){
    if(ambient.timer) return;
    ensureSurface();
    sample();
  }

  function stop(){
    if(ambient.timer) clearTimeout(ambient.timer);
    ambient.timer = 0;
    ambient.colors = null;
    var surface = document.getElementById("videoAmbientBg");
    if(surface){
      surface.classList.remove("active");
      surface.style.background = "#000";
    }
  }

  function sync(){ activeVideo() && settings().enabled ? start() : stop(); }

  ["play", "playing", "loadeddata", "canplay", "timeupdate"].forEach((name)=>document.addEventListener(name, (event)=>{
    if(event.target && event.target.id === "npVideo") sync();
  }, true));
  ["pause", "ended", "emptied"].forEach((name)=>document.addEventListener(name, (event)=>{
    if(event.target && event.target.id === "npVideo") setTimeout(sync, 0);
  }, true));
  window.addEventListener("pagehide", stop);

  window.DebriPod = window.DebriPod || {};
  window.DebriPod.videoAmbient = {start, stop, sync, samplePixels:sampleVideoAmbientPixels, diagnostics:()=>({samples:ambient.samples, active:!!ambient.timer})};
})();
