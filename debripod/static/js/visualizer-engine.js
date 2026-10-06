var volBarTimer = null;
var seekMode = false;
var seekChanged = false;
var seekPreview = 0;
var seekIdleTimer = null;

var visualizerEnabled = !!uiSettings.visualizer;
var visualizerActive = false;
var visualizerTrackKey = "";
var visualizerFpsLock = normalizeVisualizerFpsLock(uiSettings.visualizerFpsLock);
var visualizerFrameHandle = 0;
var visualizerFrameTimer = 0;
var visualizerLastFrameTs = 0;
var visualizerEnergy = 0;
var visualizerBeatPulse = 0;
var visualizerBass = 0;
var visualizerMid = 0;
var visualizerTreble = 0;
var visualizerBands = new Float32Array(9);
var visualizerActiveBands = [true, true, true, true, true, true, true, true, true];
var visualizerBandCenters = new Float32Array(9);
var visualizerBandWidths = new Float32Array(9);
var visualizerCanvasW = 0;
var visualizerCanvasH = 0;
var visualizerCanvasCssW = 0;
var visualizerCanvasCssH = 0;
var visualizerCanvasDpr = 1;
var visualizerGl = null;
var visualizerProgram = null;
var visualizerBuffer = null;
var visualizerArtTexture = null;
var visualizerPreviousArtTexture = null;
var visualizerUploadedPreviousArtKey = "";
var visualizerUniforms = null;
var visualizerWebglUnavailable = false;
var visualizerUploadedArtKey = "";
var visualizerArtUploadCount = 0;
var visualizerFade = 0;
var visualizerFadeTarget = 0;
var visualizerTransportWasActive = false;
var visualizerNeedsBlackFrame = true;
var visualizerContrastState = "";
var visualizerAnalysisNonce = 0;
var visualizerAnalysisRetryTimer = 0;
var visualizerArtFieldNonce = 0;
var visualizerArtRetryTimer = 0;
var visualizerArtField = {
  key: "", loading: false, loaded: false, image: null, url: "", artIdentity: "", algorithmVersion: 0,
  usefulLumaLow: 0, usefulLumaHigh: 1, source: "idle"
};
var visualizerRotationOffset = 0;
var visualizerRotationStartProgress = 0;
var visualizerFrozenAngle = Math.PI;
var visualizerTrackTransition = {active:false, pendingFinish:false, pendingSince:0, waitingForArt:false, startedAt:0, progress:1, fromCover:"", toCover:"", sameCover:false};
var visualizerArtTransition = {active:false, progress:1, fromImage:null, fromKey:"", toKey:"", fromAngle:Math.PI, toAngle:Math.PI, startedAt:0};
var VISUALIZER_BAND_LUMA_MIN = 0.06;
var VISUALIZER_BAND_LUMA_MAX = 0.94;
var visualizerAnalysisState = {
  key: "", loaded: false, loading: false, stale: false, rate: 30, stride: 11, bandCount: 9,
  frameCount: 0, bytes: null, rootId: "", rel: "", source: "idle", mediaKind: "", activeBands: visualizerActiveBands
};

function clamp01(n){
  var value = Number(n || 0);
  return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
}

function clampByte(n){
  return Math.max(0, Math.min(255, Math.round(Number(n || 0)) || 0));
}

function visualizerBandLumaEligibility(luma){
  var value = clamp01(luma);
  var rise = value <= 0.04 ? 0 : (value >= 0.10 ? 1 : ((value - 0.04) / 0.06) * ((value - 0.04) / 0.06) * (3 - 2 * ((value - 0.04) / 0.06)));
  var fall = value <= 0.90 ? 1 : (value >= 0.96 ? 0 : 1 - (((value - 0.90) / 0.06) * ((value - 0.90) / 0.06) * (3 - 2 * ((value - 0.90) / 0.06))));
  return Math.max(0, Math.min(1, rise * fall));
}

function visualizerReactiveSourcePixel(rgb, opacity, fade){
  var source = Array.isArray(rgb) ? rgb : [0, 0, 0];
  var alpha = clamp01(opacity) * clamp01(fade);
  // LiquidGL samples the visualizer after its opaque-black canvas clear. Keep
  // that composited source opaque so a fade changes the sampled color, not the
  // glass layer's coverage.
  return {
    r: clamp01(Number(source[0] || 0)) * alpha,
    g: clamp01(Number(source[1] || 0)) * alpha,
    b: clamp01(Number(source[2] || 0)) * alpha,
    a: 1
  };
}

function currentVisualizerMediaElement(){
  try{ if(isVideoActive && isVideoActive() && npVideo) return npVideo; }catch(e){}
  try{ if(activeAudio && activeAudio.src) return activeAudio; }catch(e){}
  return null;
}

function currentVisualizerMediaKind(){
  try{ return state && state.now && state.now.media ? String(state.now.media).toLowerCase() : ""; }catch(e){ return ""; }
}

function normalizeVisualizerArtLuma(value, usefulLow, usefulHigh){
  var low = clamp01(usefulLow);
  var high = Math.max(low + 0.08, clamp01(usefulHigh));
  return clamp01((clamp01(value) - low) / (high - low));
}

function visualizerArtRotationOverscan(viewportWidth, viewportHeight){
  var width = Math.max(1, Number(viewportWidth || 1));
  var height = Math.max(1, Number(viewportHeight || 1));
  return Math.hypot(width, height) / Math.max(width, height);
}

function visualizerBackingSize(viewportWidth, viewportHeight, devicePixelRatio){
  var cssWidth = Math.max(1, Math.round(Number(viewportWidth || 1)));
  var cssHeight = Math.max(1, Math.round(Number(viewportHeight || 1)));
  var dpr = Math.max(1, Math.min(2, Number(devicePixelRatio || 1)));
  return {cssWidth:cssWidth, cssHeight:cssHeight, width:Math.max(1, Math.round(cssWidth * dpr)), height:Math.max(1, Math.round(cssHeight * dpr)), dpr:dpr};
}

function visualizerTextureUsesMipmaps(width, height){
  return Number.isInteger(width) && Number.isInteger(height) && width > 0 && height > 0 &&
    (width & (width - 1)) === 0 && (height & (height - 1)) === 0;
}

function visualizerArtUrlWithCacheBust(url, field){
  var source = String(url || "");
  if(!source) return "";
  var meta = field || {};
  var version = [meta.cache_key, meta.art_identity, meta.algorithm_version, meta.width, meta.height]
    .map(value=>String(value == null ? "" : value).trim())
    .filter(Boolean)
    .join(":");
  if(!version) return source;
  var hashIndex = source.indexOf("#");
  var base = hashIndex >= 0 ? source.slice(0, hashIndex) : source;
  var hash = hashIndex >= 0 ? source.slice(hashIndex) : "";
  return base + (base.indexOf("?") >= 0 ? "&" : "?") + "dp_art=" + encodeURIComponent(version) + hash;
}

function rotatedVisualizerArtUv(u, v, angle, viewportWidth, viewportHeight){
  var width = Math.max(1, Number(viewportWidth || 1));
  var height = Math.max(1, Number(viewportHeight || 1));
  var side = Math.hypot(width, height);
  var x = (clamp01(u) - 0.5) * width;
  var y = (clamp01(v) - 0.5) * height;
  var cosine = Math.cos(Number(angle || 0));
  var sine = Math.sin(Number(angle || 0));
  return {u:clamp01(((cosine * x) + (sine * y)) / side + 0.5), v:clamp01(((-sine * x) + (cosine * y)) / side + 0.5)};
}

function visualizerRotationForProgress(progress01){
  var rotations = arguments.length > 1 ? normalizeVisualizerRotationsPerTrack(arguments[1]) : 3;
  return Math.PI + (2 * Math.PI * rotations * clamp01(progress01));
}

function normalizeVisualizerRotationsPerTrack(value){
  var n = Number(value);
  return Number.isFinite(n) ? Math.max(1, Math.min(12, Math.round(n))) : 3;
}

function currentVisualizerRotationCount(){
  try{ return normalizeVisualizerRotationsPerTrack(uiSettings && uiSettings.visualizerRotationsPerTrack); }catch(e){ return 3; }
}

function visualizerCoverKey(value){
  var text = String(value || "").trim();
  if(!text) return "";
  // Preserve query parameters that identify artwork (root_id/rel).
  return text.replace(/#.*$/, "").replace(/([?&])dp_art=[^&]*&?/, "$1").replace(/[?&]$/, "").replace(/\\/g, "/");
}

function visualizerProgress01(media){
  try{
    var duration = Number(media && media.duration || 0);
    if(!Number.isFinite(duration) || duration <= 0) return null;
    var transport = typeof window !== "undefined" && window.DebriPod && window.DebriPod.playbackTransport;
    var time = transport && typeof transport.visualizerTime === "function" ? transport.visualizerTime(media) : Number(media.currentTime || 0);
    return clamp01(time / duration);
  }catch(e){ return null; }
}

function currentVisualizerAngle(){
  if(visualizerTrackTransition.active) return visualizerFrozenAngle;
  var progress = visualizerProgress01(currentVisualizerMediaElement());
  return progress === null ? visualizerFrozenAngle : visualizerRotationForProgress(clamp01((progress - visualizerRotationStartProgress) / Math.max(0.000001, 1 - visualizerRotationStartProgress)), currentVisualizerRotationCount()) + visualizerRotationOffset;
}

function beginVisualizerTrackTransition(previousCover){
  if(!visualizerTrackTransition.active){
    visualizerFrozenAngle = currentVisualizerAngle();
    visualizerTrackTransition = {
      active:true,
      pendingFinish:false,
      pendingSince:0,
      waitingForArt:false,
      artReady:false,
      resolvedSameCover:null,
      startedAt:(typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now(),
      progress:0,
      fromCover:visualizerCoverKey(previousCover || (state && state.nowMeta && state.nowMeta.art)),
      toCover:"",
      sameCover:false
    };
  }
  scheduleVisualizerFrame(0);
}

function finishVisualizerTrackTransition(nextCover){
  if(!visualizerTrackTransition.active) return;
  var nextKey = visualizerCoverKey(nextCover);
  var sameCover = visualizerTrackTransition.resolvedSameCover != null ? visualizerTrackTransition.resolvedSameCover : !!(visualizerTrackTransition.fromCover && nextKey && visualizerTrackTransition.fromCover === nextKey);
  visualizerTrackTransition.toCover = nextKey;
  visualizerTrackTransition.sameCover = sameCover;
  visualizerTrackTransition.waitingForArt = !sameCover && !visualizerTrackTransition.artReady;
  visualizerTrackTransition.pendingFinish = true;
  visualizerTrackTransition.pendingSince = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
  scheduleVisualizerFrame(0);
}

function cancelVisualizerTrackTransition(){
  if(!visualizerTrackTransition.active) return;
  visualizerRotationStartProgress = visualizerProgress01(currentVisualizerMediaElement()) || 0;
  visualizerRotationOffset = visualizerFrozenAngle - Math.PI;
  visualizerTrackTransition.active = false;
  visualizerTrackTransition.pendingFinish = false;
  visualizerTrackTransition.progress = 1;
  scheduleVisualizerFrame(0);
}

function updateVisualizerTrackTransition(now){
  if(!visualizerTrackTransition.active) return;
  var started = Number(visualizerTrackTransition.startedAt || now || 0);
  visualizerTrackTransition.progress = clamp01((Number(now || 0) - started) / 260);
  if(!visualizerTrackTransition.pendingFinish) return;
  var media = currentVisualizerMediaElement();
  var playing = !!(media && !media.paused && !media.ended);
  var artReady = !visualizerTrackTransition.waitingForArt && (!visualizerArtTransition.active || visualizerArtTransition.progress >= 1);
  if(playing && (visualizerTrackTransition.sameCover || artReady)){
    visualizerRotationStartProgress = visualizerProgress01(media) || 0;
    if(visualizerTrackTransition.sameCover) visualizerRotationOffset = visualizerFrozenAngle - Math.PI;
    else visualizerRotationOffset = 0;
    visualizerTrackTransition.active = false;
    visualizerTrackTransition.pendingFinish = false;
    visualizerTrackTransition.progress = 1;
  }
}

function normalizeActiveBands(value, bandCount){
  var count = Math.max(1, Math.min(9, Number(bandCount || 9)));
  var raw = Array.isArray(value) ? value : [];
  var active = Array.from({length:9}, (_unused, index)=> index < count && (raw.length ? raw[index] !== false : true));
  if(!active.some(Boolean)) active = Array.from({length:9}, (_unused, index)=> index < count);
  return active;
}

function buildVisualizerBandLumaMap(activeBands){
  var active = normalizeActiveBands(activeBands, 9);
  var ordered = active.map((on, index)=> on ? index : -1).filter(index=>index >= 0);
  var centers = Array.from({length:9}, ()=>-2);
  var widths = Array.from({length:9}, ()=>0.0001);
  if(ordered.length === 1){
    centers[ordered[0]] = 0.5;
    widths[ordered[0]] = 1.0;
  }else{
    var width = 1 / Math.max(1, ordered.length - 1);
    ordered.forEach((band, orderedIndex)=>{
      centers[band] = orderedIndex / (ordered.length - 1);
      widths[band] = width;
    });
  }
  return {activeBands:active, centers:centers, widths:widths};
}

function applyVisualizerBandLumaMap(activeBands){
  var mapping = buildVisualizerBandLumaMap(activeBands);
  visualizerActiveBands = mapping.activeBands;
  visualizerBandCenters = new Float32Array(mapping.centers);
  visualizerBandWidths = new Float32Array(mapping.widths);
  return mapping;
}

function visualizerBandWeightsAtLuma(luma, mapping){
  var field = mapping || buildVisualizerBandLumaMap(visualizerActiveBands);
  var position = clamp01(luma);
  var weights = Array.from({length:9}, (_unused, index)=>{
    if(!field.activeBands[index]) return 0;
    return Math.max(0, 1 - Math.abs(position - field.centers[index]) / Math.max(0.0001, field.widths[index]));
  });
  var total = weights.reduce((sum, weight)=>sum + weight, 0);
  if(total <= 0){
    var nearest = field.activeBands.map((on, index)=>on ? Math.abs(position - field.centers[index]) : Infinity);
    var index = nearest.indexOf(Math.min.apply(Math, nearest));
    if(index >= 0) weights[index] = 1;
    total = 1;
  }
  return weights.map(weight=>weight / total);
}

function visualizerResponseForLuma(luma, bands, mapping){
  var weights = visualizerBandWeightsAtLuma(luma, mapping);
  var source = bands || visualizerBands;
  return clamp01(weights.reduce((sum, weight, index)=>sum + weight * clamp01(source[index]), 0));
}

function visualizerResponseChannels(frequency, energy, beat, settings){
  var cfg = settings || {};
  var response = (kind, channel)=> Number((cfg[kind] || {})[channel] || 0);
  var signal = {frequency:clamp01(frequency), energy:clamp01(energy), beat:clamp01(beat)};
  var valueFor = (channel, base, minimum, maximum)=>{
    var value = base + signal.frequency * response("frequency", channel) + signal.energy * response("energy", channel) + signal.beat * response("beat", channel);
    return Math.max(minimum, Math.min(maximum, value));
  };
  return {brightness:valueFor("brightness", 1, 0, 4), opacity:valueFor("opacity", 0.78, 0, 1), saturation:valueFor("saturation", 1, 0, 3), contrast:valueFor("contrast", 1, 0, 3)};
}

function currentVisualizerResponseSettings(){
  return {frequency:uiSettings.visualizerFrequencyResponse || {}, energy:uiSettings.visualizerEnergyResponse || {}, beat:uiSettings.visualizerBeatResponse || {}};
}

function currentVisualizerBrightnessCap(){
  return clamp01(normalizeVisualizerMaxBrightnessPct(uiSettings.visualizerMaxBrightnessPct) / 100);
}

function visualizerShouldSchedule(fade, target, needsBlackFrame){
  return Number(fade || 0) > 0.002 || Number(target || 0) > 0 || !!needsBlackFrame;
}

function resetVisualizerArtField(reason){
  // Missing metadata during a handoff is not an instruction to blank glass.
  if(visualizerTrackTransition.active && visualizerArtField.loaded && visualizerArtField.image) return;
  visualizerArtFieldNonce += 1;
  try{ if(visualizerArtRetryTimer) clearTimeout(visualizerArtRetryTimer); }catch(e){}
  visualizerArtRetryTimer = 0;
  visualizerArtField = {key:"", loading:false, loaded:false, image:null, url:"", artIdentity:"", algorithmVersion:0, usefulLumaLow:0, usefulLumaHigh:1, source:String(reason || "idle")};
  visualizerUploadedArtKey = "";
  visualizerNeedsBlackFrame = true;
}

function scheduleVisualizerArtRetry(rootId, rel, attempt){
  try{
    if(visualizerArtRetryTimer) return;
    var nextAttempt = Math.max(1, Number(attempt || 0) + 1);
    if(nextAttempt > 10) return;
    visualizerArtRetryTimer = setTimeout(()=>{
      visualizerArtRetryTimer = 0;
      loadVisualizerArtFieldForTrack(rootId, rel, {retryAttempt:nextAttempt});
    }, Math.min(15000, 1200 + nextAttempt * 900));
  }catch(e){}
}

function loadVisualizerArtFieldForTrack(rootId, rel, options){
  try{
    var opts = options || {};
    var rid = String(rootId || "");
    var rp = String(rel || "");
    if(!rid || !rp || typeof apiGet !== "function"){
      resetVisualizerArtField("uncached idle");
      return;
    }
    var key = rid + "\n" + rp;
    if(visualizerArtField.key && visualizerArtField.key !== key && visualizerArtRetryTimer){
      try{ clearTimeout(visualizerArtRetryTimer); }catch(e){}
      visualizerArtRetryTimer = 0;
    }
    if(visualizerArtField.key === key && (visualizerArtField.loaded || visualizerArtField.loading || visualizerArtRetryTimer) && !opts.retryAttempt) return;
    var nonce = ++visualizerArtFieldNonce;
    // Keep the outgoing artwork alive while the next field warms and loads.
    // Clearing this object during an ended-event handoff made the WebGL
    // surface fade to its black clear color for a frame or two.
    var previousField = visualizerArtField && visualizerArtField.loaded && visualizerArtField.image ? visualizerArtField : null;
    if(previousField){
      visualizerArtField = Object.assign({}, previousField, {key:key, loading:true, source:"transition-loading"});
    }else{
      visualizerArtField = {key:key, loading:true, loaded:false, image:null, url:"", artIdentity:"", algorithmVersion:0, usefulLumaLow:0, usefulLumaHigh:1, source:"loading"};
    }
    apiGet("/api/library/visualizer-art?root_id=" + encodeURIComponent(rid) + "&rel=" + encodeURIComponent(rp), {networkOnly:true, cache:"no-store", abortKey:"visualizer-art"})
      .then((res)=>{
        if(nonce !== visualizerArtFieldNonce) return;
        var field = res && res.visualizer_art;
        if(!field || !field.url){
          visualizerArtField.loading = false;
          visualizerArtField.source = "warming";
          scheduleVisualizerArtRetry(rid, rp, opts.retryAttempt || 0);
          return;
        }
        var image = new Image();
        image.onload = ()=>{
          if(nonce !== visualizerArtFieldNonce) return;
          var fromKey = visualizerArtField && visualizerArtField.loaded ? String(visualizerArtField.artIdentity || "") + ":" + String(visualizerArtField.algorithmVersion || 0) : "";
          var toKey = String(field.art_identity || field.cache_key || "") + ":" + String(field.algorithm_version || 0);
          if(fromKey && fromKey !== toKey){
            var frozenAngle = currentVisualizerAngle();
            visualizerArtTransition = {active:true, progress:0, fromImage:visualizerArtField.image, fromKey:fromKey, toKey:toKey, fromAngle:frozenAngle, toAngle:Math.PI, startedAt:(typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now()};
          }
          if(visualizerTrackTransition.active){
            visualizerTrackTransition.waitingForArt = false;
            visualizerTrackTransition.artReady = true;
            visualizerTrackTransition.resolvedSameCover = !!fromKey && fromKey === toKey;
            visualizerTrackTransition.sameCover = visualizerTrackTransition.resolvedSameCover;
          }
          visualizerArtField = {
            key:key, loading:false, loaded:true, image:image, url:visualizerArtUrlWithCacheBust(field.url, field), artIdentity:String(field.art_identity || field.cache_key || ""),
            algorithmVersion:Number(field.algorithm_version || 0), usefulLumaLow:clamp01(field.useful_luma_low),
            usefulLumaHigh:Math.max(clamp01(field.useful_luma_low) + 0.08, clamp01(field.useful_luma_high)), source:"art-cache"
          };
          visualizerUploadedArtKey = "";
          // The new texture is uploaded on the next frame; leave the old
          // source available to LiquidGL throughout the handoff.
          visualizerNeedsBlackFrame = false;
          scheduleVisualizerFrame(0);
        };
        image.onerror = ()=>{
          if(nonce !== visualizerArtFieldNonce) return;
          visualizerArtField.loading = false;
          visualizerArtField.source = "unavailable";
          scheduleVisualizerArtRetry(rid, rp, opts.retryAttempt || 0);
        };
        image.src = visualizerArtUrlWithCacheBust(field.url, field);
      })
      .catch(()=>{
        if(nonce !== visualizerArtFieldNonce) return;
        visualizerArtField.loading = false;
        visualizerArtField.source = "unavailable";
        scheduleVisualizerArtRetry(rid, rp, opts.retryAttempt || 0);
      });
  }catch(e){ resetVisualizerArtField("art error"); }
}

function resetVisualizerAnalysis(reason){
  visualizerAnalysisNonce += 1;
  try{ if(visualizerAnalysisRetryTimer) clearTimeout(visualizerAnalysisRetryTimer); }catch(e){}
  visualizerAnalysisRetryTimer = 0;
  visualizerAnalysisState = {key:"", loaded:false, loading:false, stale:false, rate:30, stride:11, bandCount:9, frameCount:0, bytes:null, rootId:"", rel:"", source:String(reason || "idle"), mediaKind:"", activeBands:visualizerActiveBands};
  if(String(reason || "").indexOf("idle") >= 0 || String(reason || "").indexOf("error") >= 0) resetVisualizerArtField(reason);
}

function bytesFromBase64(value){
  try{
    var text = String(value || "");
    if(!text) return null;
    var raw = atob(text);
    var bytes = new Uint8Array(raw.length);
    for(var index = 0; index < raw.length; index++) bytes[index] = raw.charCodeAt(index) & 255;
    return bytes;
  }catch(e){ return null; }
}

function scheduleVisualizerAnalysisRetry(rootId, rel, mediaKind, attempt){
  try{
    if(visualizerAnalysisRetryTimer) return;
    var nextAttempt = Math.max(1, Number(attempt || 0) + 1);
    if(nextAttempt > 12) return;
    visualizerAnalysisRetryTimer = setTimeout(()=>{
      visualizerAnalysisRetryTimer = 0;
      loadVisualizerAnalysisForTrack(rootId, rel, mediaKind, {retryAttempt:nextAttempt});
    }, Math.min(15000, 1800 + nextAttempt * 900));
  }catch(e){}
}

function applyVisualizerAnalysis(rootId, rel, analysis, nonce){
  try{
    if(nonce !== visualizerAnalysisNonce) return;
    var bytes = analysis && bytesFromBase64(analysis.feature_blob_b64 || "");
    var metadata = analysis && analysis.metadata && typeof analysis.metadata === "object" ? analysis.metadata : {};
    var bandCount = Math.max(1, Math.min(9, Number(analysis && analysis.band_count || 9)));
    var stride = Math.max(bandCount + 2, Number(metadata.frame_stride || (bandCount + 2)));
    var frameCount = Math.max(0, Number(analysis && analysis.frame_count || Math.floor((bytes ? bytes.length : 0) / stride)));
    if(!bytes || !frameCount || bytes.length < stride){
      visualizerAnalysisState.loading = false;
      visualizerAnalysisState.loaded = false;
      visualizerAnalysisState.stale = true;
      return;
    }
    var activeBands = normalizeActiveBands(metadata.active_bands, bandCount);
    applyVisualizerBandLumaMap(activeBands);
    visualizerAnalysisState = {key:String(analysis.analysis_key || (rootId + ":" + rel)), loaded:true, loading:false, stale:false, rate:Math.max(1, Number(analysis.analysis_rate_hz || 30)), stride:stride, bandCount:bandCount, frameCount:Math.min(frameCount, Math.floor(bytes.length / stride)), bytes:bytes, rootId:String(rootId || ""), rel:String(rel || ""), source:"sqlite", mediaKind:String(metadata.media_kind || ""), activeBands:activeBands};
    try{ if(visualizerAnalysisRetryTimer) clearTimeout(visualizerAnalysisRetryTimer); }catch(e){}
    visualizerAnalysisRetryTimer = 0;
    scheduleVisualizerFrame(0);
  }catch(e){
    visualizerAnalysisState.loading = false;
    visualizerAnalysisState.loaded = false;
  }
}

function loadVisualizerAnalysisForTrack(rootId, rel, mediaKind, options){
  try{
    var opts = options || {};
    var media = String(mediaKind || "audio").toLowerCase();
    var rid = String(rootId || "");
    var rp = String(rel || "");
    if(opts.streamed || !rid || !rp || typeof apiGet !== "function"){
      resetVisualizerAnalysis(opts.streamed ? "streamed idle" : "uncached idle");
      visualizerAnalysisState.mediaKind = media;
      return;
    }
    loadVisualizerArtFieldForTrack(rid, rp, opts);
    var key = rid + "\n" + rp;
    if(visualizerAnalysisState.key === key && (visualizerAnalysisState.loaded || visualizerAnalysisState.loading) && !opts.retryAttempt) return;
    var nonce = ++visualizerAnalysisNonce;
    visualizerAnalysisState = Object.assign({}, visualizerAnalysisState, {key:key, rootId:rid, rel:rp, loaded:false, loading:true, stale:false, source:"loading", mediaKind:media});
    apiGet("/api/library/analysis?root_id=" + encodeURIComponent(rid) + "&rel=" + encodeURIComponent(rp), {networkOnly:true, cache:"no-store", abortKey:"visualizer-analysis"})
      .then((res)=>{
        if(nonce !== visualizerAnalysisNonce) return;
        if(!res || !res.analysis){
          visualizerAnalysisState.loading = false;
          visualizerAnalysisState.loaded = false;
          visualizerAnalysisState.stale = true;
          visualizerAnalysisState.source = "live";
          scheduleVisualizerAnalysisRetry(rid, rp, media, opts.retryAttempt || 0);
          return;
        }
        applyVisualizerAnalysis(rid, rp, res.analysis, nonce);
      })
      .catch(()=>{
        if(nonce !== visualizerAnalysisNonce) return;
        visualizerAnalysisState.loading = false;
        visualizerAnalysisState.loaded = false;
        visualizerAnalysisState.stale = true;
        visualizerAnalysisState.source = "live";
        scheduleVisualizerAnalysisRetry(rid, rp, media, opts.retryAttempt || 0);
      });
  }catch(e){ resetVisualizerAnalysis("analysis error"); }
}

function sampleCachedVisualizerAnalysis(media){
  try{
    var analysis = visualizerAnalysisState;
    if(!analysis.loaded || !analysis.bytes || !analysis.frameCount || !media) return null;
    var gapless = typeof gaplessPlaybackSnapshot === "function" ? gaplessPlaybackSnapshot() : null;
    var mediaTime = gapless && gapless.duration > 0 ? Number(gapless.position || 0) : Number(media.currentTime || 0);
    var position = Math.max(0, Math.min(analysis.frameCount - 1, mediaTime * analysis.rate));
    var firstFrame = Math.floor(position);
    var secondFrame = Math.min(analysis.frameCount - 1, firstFrame + 1);
    var fraction = position - firstFrame;
    var firstOffset = firstFrame * analysis.stride;
    var secondOffset = secondFrame * analysis.stride;
    var rawBands = Array.from({length:9}, (_unused, index)=>{
      if(index >= analysis.bandCount) return 0;
      var first = Number(analysis.bytes[firstOffset + index] || 0) / 255;
      var second = Number(analysis.bytes[secondOffset + index] || 0) / 255;
      return first + (second - first) * fraction;
    });
    var energyIndex = analysis.bandCount;
    var beatIndex = analysis.bandCount + 1;
    var firstEnergy = Number(analysis.bytes[firstOffset + energyIndex] || 0) / 255;
    var secondEnergy = Number(analysis.bytes[secondOffset + energyIndex] || 0) / 255;
    var firstBeat = Number(analysis.bytes[firstOffset + beatIndex] || 0) / 255;
    var secondBeat = Number(analysis.bytes[secondOffset + beatIndex] || 0) / 255;
    return {bands:rawBands, energy:clamp01(firstEnergy + (secondEnergy - firstEnergy) * fraction), beat:clamp01(firstBeat + (secondBeat - firstBeat) * fraction), activeBands:analysis.activeBands};
  }catch(e){ return null; }
}

function liveVisualizerFeatures(media){
  try{
    var graph = window.DebriPod && window.DebriPod.mediaAudioGraph;
    var frequency = graph && graph.getFrequencyData ? graph.getFrequencyData(media) : null;
    if(!frequency || !frequency.length) return null;
    var bands = Array.from({length:9}, (_unused, index)=>{
      var start = Math.floor(frequency.length * index / 9);
      var end = Math.max(start + 1, Math.floor(frequency.length * (index + 1) / 9));
      var total = 0;
      for(var cursor = start; cursor < end; cursor++) total += Number(frequency[cursor] || 0) / 255;
      return clamp01(total / Math.max(1, end - start));
    });
    return {bands:bands, energy:clamp01(bands.reduce((sum, value)=>sum + value, 0) / bands.length), beat:0, activeBands:[true,true,true,true,true,true,true,true,true]};
  }catch(e){ return null; }
}

function compileVisualizerShader(gl, type, source){
  var shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if(!gl.getShaderParameter(shader, gl.COMPILE_STATUS)){
    try{ console.warn("[DebriPod visualizer] shader compile failed", gl.getShaderInfoLog(shader) || ""); }catch(e){}
    try{ gl.deleteShader(shader); }catch(e){}
    return null;
  }
  return shader;
}

function linkVisualizerProgram(gl, vertexSource, fragmentSource){
  var vertex = compileVisualizerShader(gl, gl.VERTEX_SHADER, vertexSource);
  var fragment = compileVisualizerShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
  if(!vertex || !fragment) return null;
  var program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if(!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  return program;
}

function ensureVisualizerWebGL(){
  if(visualizerWebglUnavailable) return false;
  try{
    if(!visualizerBg || !visualizerBg.getContext) return false;
    if(visualizerGl && visualizerProgram && visualizerArtTexture && visualizerPreviousArtTexture) return true;
    var attrs = {alpha:true, premultipliedAlpha:true, preserveDrawingBuffer:false, antialias:false, depth:false, stencil:false};
    visualizerGl = visualizerBg.getContext("webgl", attrs) || visualizerBg.getContext("experimental-webgl", attrs);
    if(!visualizerGl){ visualizerWebglUnavailable = true; return false; }
    var vertex = "attribute vec2 p; varying vec2 uv; void main(){uv=(p+1.0)*0.5;gl_Position=vec4(p,0.0,1.0);}";
    var fragment = [
      "#ifdef GL_FRAGMENT_PRECISION_HIGH\nprecision highp float;\n#else\nprecision mediump float;\n#endif", "varying vec2 uv;", "uniform sampler2D artTex;", "uniform sampler2D previousArtTex;", "uniform float artMix;", "uniform vec2 canvasSize;", "uniform float previousAngle;", "uniform float incomingAngle;", "uniform float angle;", "uniform float lumaLow;", "uniform float lumaHigh;", "uniform float fade;", "uniform float brightnessCap;", "uniform float energy;", "uniform float beat;", "uniform float bands[9];", "uniform float bandCenters[9];", "uniform float bandWidths[9];", "uniform vec4 frequencyResponse;", "uniform vec4 energyResponse;", "uniform vec4 beatResponse;",
      "float bandWeight(float l,float center,float width){return max(0.0,1.0-abs(l-center)/max(0.0001,width));}",
      "vec2 projectedUv(vec2 source,float radians){vec2 centered=(source-0.5)*canvasSize;float c=cos(radians);float s=sin(radians);vec2 rotated=vec2(c*centered.x+s*centered.y,-s*centered.x+c*centered.y);float overscan=1.08;return clamp(rotated/max(1.0,length(canvasSize))*overscan+0.5,0.0,1.0);}",
      "void main(){", "vec2 previousUv=projectedUv(uv,previousAngle);", "vec2 incomingUv=projectedUv(uv,incomingAngle);", "vec3 incoming=texture2D(artTex,incomingUv).rgb;", "vec3 outgoing=texture2D(previousArtTex,previousUv).rgb;", "vec3 rgb=mix(outgoing,incoming,clamp(artMix,0.0,1.0));", "float luma=dot(rgb,vec3(0.2126,0.7152,0.0722));", "float useful=clamp((luma-lumaLow)/max(0.08,lumaHigh-lumaLow),0.0,1.0);", "float bandEligible=smoothstep(0.04,0.10,luma)*(1.0-smoothstep(0.90,0.96,luma));",
      "float w0=bandWeight(useful,bandCenters[0],bandWidths[0]);float w1=bandWeight(useful,bandCenters[1],bandWidths[1]);float w2=bandWeight(useful,bandCenters[2],bandWidths[2]);", "float w3=bandWeight(useful,bandCenters[3],bandWidths[3]);float w4=bandWeight(useful,bandCenters[4],bandWidths[4]);float w5=bandWeight(useful,bandCenters[5],bandWidths[5]);", "float w6=bandWeight(useful,bandCenters[6],bandWidths[6]);float w7=bandWeight(useful,bandCenters[7],bandWidths[7]);float w8=bandWeight(useful,bandCenters[8],bandWidths[8]);", "float total=max(0.0001,w0+w1+w2+w3+w4+w5+w6+w7+w8);", "float frequency=bandEligible*(w0*bands[0]+w1*bands[1]+w2*bands[2]+w3*bands[3]+w4*bands[4]+w5*bands[5]+w6*bands[6]+w7*bands[7]+w8*bands[8])/total;",
      "float brightness=clamp(1.0+frequency*frequencyResponse.x+energy*energyResponse.x+beat*beatResponse.x,0.0,4.0);", "float opacity=clamp(1.0+frequency*frequencyResponse.y+energy*energyResponse.y+beat*beatResponse.y,0.0,1.0);", "float saturation=clamp(1.0+frequency*frequencyResponse.z+energy*energyResponse.z+beat*beatResponse.z,0.0,3.0);", "float contrast=clamp(1.0+frequency*frequencyResponse.w+energy*energyResponse.w+beat*beatResponse.w,0.0,3.0);", "rgb=mix(vec3(luma),rgb,saturation);rgb=(rgb-0.5)*contrast+0.5;rgb=min(clamp(rgb*brightness,0.0,1.0),vec3(brightnessCap));", "float alpha=opacity*fade;gl_FragColor=vec4(rgb*alpha,alpha);", "}"
    ].join("\n");
    visualizerProgram = linkVisualizerProgram(visualizerGl, vertex, fragment);
    if(!visualizerProgram){ visualizerWebglUnavailable = true; return false; }
    visualizerBuffer = visualizerGl.createBuffer();
    visualizerGl.bindBuffer(visualizerGl.ARRAY_BUFFER, visualizerBuffer);
    visualizerGl.bufferData(visualizerGl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]), visualizerGl.STATIC_DRAW);
    visualizerArtTexture = visualizerGl.createTexture();
    visualizerGl.bindTexture(visualizerGl.TEXTURE_2D, visualizerArtTexture);
    visualizerGl.texParameteri(visualizerGl.TEXTURE_2D, visualizerGl.TEXTURE_WRAP_S, visualizerGl.CLAMP_TO_EDGE);
    visualizerGl.texParameteri(visualizerGl.TEXTURE_2D, visualizerGl.TEXTURE_WRAP_T, visualizerGl.CLAMP_TO_EDGE);
    visualizerGl.texParameteri(visualizerGl.TEXTURE_2D, visualizerGl.TEXTURE_MIN_FILTER, visualizerGl.LINEAR);
    visualizerGl.texParameteri(visualizerGl.TEXTURE_2D, visualizerGl.TEXTURE_MAG_FILTER, visualizerGl.LINEAR);
    visualizerGl.texImage2D(visualizerGl.TEXTURE_2D, 0, visualizerGl.RGBA, 1, 1, 0, visualizerGl.RGBA, visualizerGl.UNSIGNED_BYTE, new Uint8Array([0,0,0,255]));
    visualizerPreviousArtTexture = visualizerGl.createTexture();
    visualizerGl.bindTexture(visualizerGl.TEXTURE_2D, visualizerPreviousArtTexture);
    visualizerGl.texParameteri(visualizerGl.TEXTURE_2D, visualizerGl.TEXTURE_WRAP_S, visualizerGl.CLAMP_TO_EDGE);
    visualizerGl.texParameteri(visualizerGl.TEXTURE_2D, visualizerGl.TEXTURE_WRAP_T, visualizerGl.CLAMP_TO_EDGE);
    visualizerGl.texParameteri(visualizerGl.TEXTURE_2D, visualizerGl.TEXTURE_MIN_FILTER, visualizerGl.LINEAR);
    visualizerGl.texParameteri(visualizerGl.TEXTURE_2D, visualizerGl.TEXTURE_MAG_FILTER, visualizerGl.LINEAR);
    visualizerGl.texImage2D(visualizerGl.TEXTURE_2D, 0, visualizerGl.RGBA, 1, 1, 0, visualizerGl.RGBA, visualizerGl.UNSIGNED_BYTE, new Uint8Array([0,0,0,255]));
    var uniform = name=>visualizerGl.getUniformLocation(visualizerProgram, name);
    visualizerUniforms = {canvasSize:uniform("canvasSize"), artTex:uniform("artTex"), previousArtTex:uniform("previousArtTex"), artMix:uniform("artMix"), previousAngle:uniform("previousAngle"), incomingAngle:uniform("incomingAngle"), angle:uniform("angle"), lumaLow:uniform("lumaLow"), lumaHigh:uniform("lumaHigh"), fade:uniform("fade"), brightnessCap:uniform("brightnessCap"), energy:uniform("energy"), beat:uniform("beat"), bands:uniform("bands[0]"), bandCenters:uniform("bandCenters[0]"), bandWidths:uniform("bandWidths[0]"), frequencyResponse:uniform("frequencyResponse"), energyResponse:uniform("energyResponse"), beatResponse:uniform("beatResponse")};
    visualizerGl.disable(visualizerGl.DEPTH_TEST);
    visualizerGl.disable(visualizerGl.STENCIL_TEST);
    return true;
  }catch(e){ visualizerWebglUnavailable = true; return false; }
}

function resizeVisualizerSurface(){
  try{
    if(!ensureVisualizerWebGL()) return false;
    var backing = visualizerBackingSize(window.innerWidth || 1, window.innerHeight || 1, window.devicePixelRatio || 1);
    if(backing.width === visualizerCanvasW && backing.height === visualizerCanvasH && backing.cssWidth === visualizerCanvasCssW && backing.cssHeight === visualizerCanvasCssH) return true;
    visualizerCanvasW = backing.width;
    visualizerCanvasH = backing.height;
    visualizerCanvasCssW = backing.cssWidth;
    visualizerCanvasCssH = backing.cssHeight;
    visualizerCanvasDpr = backing.dpr;
    visualizerBg.width = backing.width;
    visualizerBg.height = backing.height;
    visualizerGl.viewport(0, 0, backing.width, backing.height);
    return true;
  }catch(e){ return false; }
}

function uploadVisualizerArtTexture(){
  try{
    if(!visualizerArtField.loaded || !visualizerArtField.image || !visualizerArtField.artIdentity) return false;
    var key = visualizerArtField.artIdentity + ":" + visualizerArtField.algorithmVersion;
    if(key === visualizerUploadedArtKey) return true;
    var gl = visualizerGl;
    gl.bindTexture(gl.TEXTURE_2D, visualizerArtTexture);
    // Image sources use a top-left origin; flip once at upload so the
    // renderer's initial PI angle is a real 180-degree turn from the cover.
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, visualizerArtField.image);
    if(visualizerTextureUsesMipmaps(visualizerArtField.image.naturalWidth, visualizerArtField.image.naturalHeight) && gl.generateMipmap && gl.LINEAR_MIPMAP_LINEAR != null){
      gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    }else{
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    }
    visualizerUploadedArtKey = key;
    visualizerArtUploadCount += 1;
    return true;
  }catch(e){ return false; }
}

function uploadVisualizerPreviousArtTexture(){
  try{
    var transition = visualizerArtTransition;
    if(!transition.active || !transition.fromImage || !transition.fromKey) return false;
    if(transition.fromKey === visualizerUploadedPreviousArtKey) return true;
    var gl = visualizerGl;
    gl.bindTexture(gl.TEXTURE_2D, visualizerPreviousArtTexture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, transition.fromImage);
    if(visualizerTextureUsesMipmaps(transition.fromImage.naturalWidth, transition.fromImage.naturalHeight) && gl.generateMipmap && gl.LINEAR_MIPMAP_LINEAR != null){
      gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    }else gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    visualizerUploadedPreviousArtKey = transition.fromKey;
    return true;
  }catch(e){ return false; }
}

function renderVisualizerWebGL(){
  try{
    if(!resizeVisualizerSurface()) return false;
    var gl = visualizerGl;
    var hasArt = uploadVisualizerArtTexture();
    var hasPreviousArt = uploadVisualizerPreviousArtTexture();
    var u = visualizerUniforms;
    gl.viewport(0, 0, visualizerCanvasW, visualizerCanvasH);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if(!hasArt || visualizerFade <= 0.002) return true;
    gl.useProgram(visualizerProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, visualizerBuffer);
    var position = gl.getAttribLocation(visualizerProgram, "p");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, visualizerArtTexture);
    gl.uniform1i(u.artTex, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, visualizerPreviousArtTexture);
    gl.uniform1i(u.previousArtTex, 1);
    gl.uniform1f(u.artMix, hasPreviousArt && visualizerArtTransition.active ? visualizerArtTransition.progress : 1);
    gl.uniform1f(u.previousAngle, visualizerArtTransition.active ? visualizerArtTransition.fromAngle : currentVisualizerAngle());
    gl.uniform1f(u.incomingAngle, visualizerArtTransition.active ? visualizerArtTransition.toAngle : currentVisualizerAngle());
    gl.uniform2f(u.canvasSize, visualizerCanvasCssW || visualizerCanvasW, visualizerCanvasCssH || visualizerCanvasH);
    gl.uniform1f(u.angle, currentVisualizerAngle());
    gl.uniform1f(u.lumaLow, visualizerArtField.usefulLumaLow);
    gl.uniform1f(u.lumaHigh, visualizerArtField.usefulLumaHigh);
    gl.uniform1f(u.fade, visualizerFade);
    gl.uniform1f(u.brightnessCap, currentVisualizerBrightnessCap());
    gl.uniform1f(u.energy, visualizerEnergy);
    gl.uniform1f(u.beat, visualizerBeatPulse);
    gl.uniform1fv(u.bands, visualizerBands);
    gl.uniform1fv(u.bandCenters, visualizerBandCenters);
    gl.uniform1fv(u.bandWidths, visualizerBandWidths);
    var responses = currentVisualizerResponseSettings();
    var values = kind=>["brightness","opacity","saturation","contrast"].map(channel=>Number((responses[kind] || {})[channel] || 0));
    gl.uniform4fv(u.frequencyResponse, new Float32Array(values("frequency")));
    gl.uniform4fv(u.energyResponse, new Float32Array(values("energy")));
    gl.uniform4fv(u.beatResponse, new Float32Array(values("beat")));
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    return true;
  }catch(e){ return false; }
}

function visualizerSourceForLiquidGL(){
  var wallpaper = window.DebriPod && window.DebriPod.wallpaper;
  if(wallpaper && wallpaper.active()) return wallpaper.source();
  return {image:visualizerArtField.image, artKey:visualizerArtField.artIdentity + ":" + visualizerArtField.algorithmVersion, width:visualizerArtField.image && visualizerArtField.image.naturalWidth || 0, height:visualizerArtField.image && visualizerArtField.image.naturalHeight || 0, sourceRect:{left:0, top:0, width:window.innerWidth || 1, height:window.innerHeight || 1}, ready:!!(visualizerArtField.loaded && visualizerArtField.image && visualizerArtField.artIdentity)};
}

function updateVisualizerArtTransition(now){
  if(!visualizerArtTransition.active) return;
  visualizerArtTransition.progress = clamp01((Number(now || 0) - Number(visualizerArtTransition.startedAt || now || 0)) / 220);
  if(visualizerArtTransition.progress >= 1){
    visualizerArtTransition.active = false;
    visualizerArtTransition.fromImage = null;
  }
}

function currentVisualizerFrameState(ts){
  var progress = visualizerProgress01(currentVisualizerMediaElement());
  var angle = currentVisualizerAngle();
  return {kind:"audio", timestamp:Number(ts || performance.now() || 0), active:!!visualizerActive, fade:visualizerFade, brightnessCap:currentVisualizerBrightnessCap(), energy:visualizerEnergy, beat:visualizerBeatPulse, bass:visualizerBass, mid:visualizerMid, treble:visualizerTreble, bands:visualizerBands, bandCenters:visualizerBandCenters, bandWidths:visualizerBandWidths, activeBands:visualizerActiveBands, parallax:{x:0, y:0}, artImage:visualizerArtField.image, artKey:visualizerArtField.artIdentity + ":" + visualizerArtField.algorithmVersion, lumaLow:visualizerArtField.usefulLumaLow, lumaHigh:visualizerArtField.usefulLumaHigh, progress01:progress, angleRadians:angle, responseSettings:currentVisualizerResponseSettings(), sourceRevision:visualizerArtUploadCount, artworkField:{loaded:!!visualizerArtField.loaded, artIdentity:visualizerArtField.artIdentity, normalizedLumaLow:0, normalizedLumaHigh:1, rotationOverscan:visualizerArtRotationOverscan(window.innerWidth || 1, window.innerHeight || 1)}, trackTransition:Object.assign({}, visualizerTrackTransition), artTransition:Object.assign({}, visualizerArtTransition, {fromAngle:Number(visualizerArtTransition.fromAngle || angle), toAngle:Number(visualizerArtTransition.toAngle || angle)}), analysisSource:visualizerAnalysisState.loaded ? "sqlite" : visualizerAnalysisState.source};
}

function applySelectedTextContrast(){
  try{
    var root = document.documentElement;
    var selected = "#ffffff";
    var edge = "rgba(255,255,255,.65)";
    root.style.setProperty("--lib-selected-contrast", selected);
    root.style.setProperty("--lib-selected-pill-contrast", selected);
    root.style.setProperty("--lib-selected-render-contrast", selected);
    root.style.setProperty("--lib-selected-pill-render-contrast", selected);
    root.style.setProperty("--lib-selected-pill-edge", edge);
    return true;
  }catch(e){ return false; }
}

function visualizerShouldShow(){
  try{
    var media = currentVisualizerMediaElement();
    if(!visualizerEnabled || currentVisualizerMediaKind() === "video") return false;
    if(visualizerTrackTransition.active) return !!(visualizerArtField.loaded && visualizerArtField.image);
    var transport = window.DebriPod && DebriPod.playbackTransport;
    if(transport && media && typeof transport.visualizerLevel === "function" && transport.visualizerLevel(media) != null){
      return !!(visualizerArtField.loaded && visualizerArtField.image);
    }
    var gapless = typeof gaplessPlaybackSnapshot === "function" ? gaplessPlaybackSnapshot() : null;
    return gapless ? !!gapless.playing : !!(media && !media.paused && !media.ended);
  }catch(e){ return false; }
}

function scheduleVisualizerFrame(delayMs){
  try{
    if(visualizerFrameHandle || visualizerFrameTimer) return;
    var delay = Math.max(0, Number(delayMs || 0));
    var queue = ()=>{
      var scheduler = window.DebriPod && DebriPod.frameScheduler;
      if(scheduler && scheduler.request){
        visualizerFrameHandle = -1;
        scheduler.request("visualizer-frame", frame=>visualizerFrame(frame && frame.timestamp ? frame.timestamp : performance.now()));
        scheduler.mark({keepAlive:true});
      }else visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
    };
    if(delay > 34) visualizerFrameTimer = setTimeout(()=>{ visualizerFrameTimer = 0; queue(); }, delay);
    else queue();
  }catch(e){}
}

function updateVisualizerSignal(features){
  var source = features || {bands:Array(9).fill(0), energy:0, beat:0, activeBands:visualizerActiveBands};
  var bands = Array.from({length:9}, (_unused, index)=>clamp01(source.bands && source.bands[index]));
  var up = 0.42;
  var down = 0.18;
  for(var index = 0; index < 9; index++){
    var previous = visualizerBands[index] || 0;
    var next = bands[index];
    visualizerBands[index] = previous + (next - previous) * (next > previous ? up : down);
  }
  var mix = (previous, next)=>previous + (next - previous) * (next > previous ? up : down);
  visualizerEnergy = mix(visualizerEnergy, clamp01(source.energy));
  visualizerBeatPulse = mix(visualizerBeatPulse, clamp01(source.beat));
  visualizerBass = (visualizerBands[0] + visualizerBands[1] + visualizerBands[2]) / 3;
  visualizerMid = (visualizerBands[3] + visualizerBands[4] + visualizerBands[5]) / 3;
  visualizerTreble = (visualizerBands[6] + visualizerBands[7] + visualizerBands[8]) / 3;
  if(source.activeBands) applyVisualizerBandLumaMap(source.activeBands);
}

function visualizerFrame(ts){
  visualizerFrameHandle = 0;
  try{
    var now = Number(ts || performance.now() || 0);
    var interval = 1000 / normalizeVisualizerFpsLock(visualizerFpsLock);
    if(visualizerLastFrameTs && now - visualizerLastFrameTs < interval){
      scheduleVisualizerFrame(interval - (now - visualizerLastFrameTs));
      return;
    }
    var elapsed = visualizerLastFrameTs ? Math.max(1, now - visualizerLastFrameTs) : interval;
    visualizerLastFrameTs = now;
    updateVisualizerArtTransition(now);
    updateVisualizerTrackTransition(now);
    visualizerActive = visualizerShouldShow();
    visualizerFadeTarget = visualizerActive && visualizerArtField.loaded ? 1 : 0;
    var fadeWasVisible = visualizerFade > 0.002;
    var transport = window.DebriPod && window.DebriPod.playbackTransport;
    var transportLevel = transport && transport.visualizerLevel(currentVisualizerMediaElement());
    var fadeStep = Math.min(1, elapsed / 260);
    if(transportLevel != null && visualizerEnabled && visualizerArtField.loaded && currentVisualizerMediaKind() !== "video"){
      visualizerFade = clamp01(transportLevel);
      visualizerFadeTarget = transport.isPaused(currentVisualizerMediaElement()) ? 0 : 1;
    }else if(visualizerTransportWasActive && visualizerFadeTarget === 1){
      visualizerFade = 1;
    }else visualizerFade += (visualizerFadeTarget - visualizerFade) * fadeStep;
    visualizerTransportWasActive = transportLevel != null;
    if(Math.abs(visualizerFadeTarget - visualizerFade) < 0.002) visualizerFade = visualizerFadeTarget;
    if(fadeWasVisible && visualizerFadeTarget === 0 && visualizerFade === 0) visualizerNeedsBlackFrame = true;
    var media = currentVisualizerMediaElement();
    var features = visualizerActive && media && !document.hidden ? (sampleCachedVisualizerAnalysis(media) || liveVisualizerFeatures(media)) : null;
    updateVisualizerSignal(features);
    var contrastState = visualizerFade > 0.002 ? "active" : "paused";
    if(contrastState !== visualizerContrastState){
      visualizerContrastState = contrastState;
      applySelectedTextContrast();
    }
    var needsBlackGlassFrame = visualizerNeedsBlackFrame;
    if(visualizerFade > 0.002 || visualizerNeedsBlackFrame){
      renderVisualizerWebGL();
      visualizerNeedsBlackFrame = false;
    }
    if(visualizerBg){
      var showing = visualizerFade > 0.002;
      visualizerBg.classList.toggle("active", showing);
      visualizerBg.classList.toggle("off", !showing);
      if(showing){
        visualizerBg.style.removeProperty("opacity");
        visualizerBg.style.removeProperty("transition");
      }else{
        visualizerBg.style.setProperty("transition", "none");
        visualizerBg.style.setProperty("opacity", "0");
      }
    }
    try{
      if(typeof refreshLiquidGlassVisualizerSources === "function" && visualizerFade > 0.002) refreshLiquidGlassVisualizerSources("reactive artwork visualizer");
      if(typeof renderLiquidGlassVisualizerSourceNow === "function" && visualizerFade > 0.002) renderLiquidGlassVisualizerSourceNow(currentVisualizerFrameState(now), {activeAnimating:true});
      if(typeof renderLiquidGlassVisualizerSourceNow === "function" && visualizerFade <= 0.002 && (fadeWasVisible || needsBlackGlassFrame)) renderLiquidGlassVisualizerSourceNow(currentVisualizerFrameState(now), {activeAnimating:false});
    }catch(e){}
  }catch(e){}
  if(visualizerShouldSchedule(visualizerFade, visualizerFadeTarget, visualizerNeedsBlackFrame)) scheduleVisualizerFrame(0);
}

function ensureVisualizerFrameLoop(){ scheduleVisualizerFrame(0); }

function setVisualizerActive(on){
  visualizerActive = !!on;
  visualizerFadeTarget = visualizerActive && visualizerArtField.loaded ? 1 : 0;
  if(!visualizerActive) visualizerNeedsBlackFrame = true;
  scheduleVisualizerFrame(0);
}

function updateVisualizerState(){
  setVisualizerActive(visualizerShouldShow());
  ensureVisualizerFrameLoop();
}

function setVisualizerEnabled(on){
  visualizerEnabled = !!on;
  if(visualizerEnabled && window.DebriPod && window.DebriPod.wallpaper) window.DebriPod.wallpaper.clear();
  uiSettings.visualizer = visualizerEnabled;
  saveUiSettings();
  updateVisualizerState();
}

function setVisualizerMaxBrightnessPct(value){
  uiSettings.visualizerMaxBrightnessPct = normalizeVisualizerMaxBrightnessPct(value);
  saveUiSettings();
  scheduleVisualizerFrame(0);
}

function setVisualizerFpsLock(value){
  visualizerFpsLock = normalizeVisualizerFpsLock(value);
  uiSettings.visualizerFpsLock = visualizerFpsLock;
  saveUiSettings();
  visualizerLastFrameTs = 0;
  scheduleVisualizerFrame(0);
}

function setVisualizerRotationsPerTrack(value){
  var normalized = normalizeVisualizerRotationsPerTrack(value);
  uiSettings.visualizerRotationsPerTrack = normalized;
  try{ saveUiSettings(); }catch(e){}
  scheduleVisualizerFrame(0);
}

function cycleVisualizerFpsLock(){
  var values = [30,60,120];
  var current = values.indexOf(normalizeVisualizerFpsLock(visualizerFpsLock));
  setVisualizerFpsLock(values[(current + 1) % values.length]);
}

function sampleThemeFromArt(src){
  var value = String(src || "").trim();
  visualizerTrackKey = value;
  if(!value && !visualizerArtField.loaded) resetVisualizerArtField("no artwork");
  updateVisualizerState();
}

try{
  var rootForVisualizer = window.DebriPod = window.DebriPod || {};
  rootForVisualizer.visualizerRenderer = Object.assign(rootForVisualizer.visualizerRenderer || {}, {sourceForLiquidGL:visualizerSourceForLiquidGL, render:renderVisualizerWebGL, available:()=>!!(visualizerGl && !visualizerWebglUnavailable)});
  rootForVisualizer.visualizerArt = {normalizeLuma:normalizeVisualizerArtLuma, rotationOverscan:visualizerArtRotationOverscan, rotatedUv:rotatedVisualizerArtUv, bandMap:buildVisualizerBandLumaMap, bandLumaEligibility:visualizerBandLumaEligibility, reactiveSourcePixel:visualizerReactiveSourcePixel, field:()=>visualizerArtField, uploadCount:()=>visualizerArtUploadCount, transition:()=>Object.assign({}, visualizerArtTransition), trackTransition:()=>Object.assign({}, visualizerTrackTransition)};
}catch(e){}

applyVisualizerBandLumaMap(visualizerActiveBands);
applySelectedTextContrast();
