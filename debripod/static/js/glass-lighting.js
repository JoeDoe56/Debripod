(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const neutral = {x:-0.16, y:-0.22, intensity:0.22, source:"default"};
  const light = Object.assign({}, neutral);
  let target = Object.assign({}, neutral);
  let frame = 0;
  let lastFrameAt = 0;
  let pointerIdleTimer = 0;
  let orientationAttached = false;
  let orientationActive = false;
  let permissionRequested = false;
  let orientationOrigin = null;

  function clamp(value, low, high){ return Math.max(low, Math.min(high, Number(value) || 0)); }
  function deviceUserId(){ return String(window.DEBRIPOD_DEVICE_SETTINGS_USER_ID || "anonymous").trim() || "anonymous"; }
  function permissionKey(){ return "debripod_glass_orientation_permission:v1:" + deviceUserId(); }
  function storedPermission(){
    try{
      const value = String(window.localStorage && localStorage.getItem(permissionKey()) || "");
      return value === "granted" || value === "denied" ? value : "unknown";
    }catch(e){ return "unknown"; }
  }
  function savePermission(value){
    try{ if(window.localStorage) localStorage.setItem(permissionKey(), value); }catch(e){}
  }
  function currentFps(){
    try{
      const settings = root.uiSettings && root.uiSettings.settings || {};
      const raw = Number(settings.glassInteractionFps || 60);
      return Math.max(30, Math.min(120, Number.isFinite(raw) ? raw : 60));
    }catch(e){ return 60; }
  }
  function motionEffectMultiplier(){
    try{
      const settings = root.uiSettings && root.uiSettings.settings || {};
      const raw = Number(settings.glassMotionEffectMultiplier);
      return Number.isFinite(raw) ? clamp(raw, 0, 2) : 1;
    }catch(e){ return 1; }
  }
  function markGlassFrame(){
    try{
      const scheduler = root.frameScheduler;
      if(scheduler && scheduler.mark) scheduler.mark({render:true, metrics:true, keepAlive:true});
    }catch(e){}
  }
  function schedule(){
    if(frame || document.hidden) return;
    frame = requestAnimationFrame(step);
  }
  function setTarget(x, y, intensity, source){
    target = {
      x: clamp(x, -1, 1),
      y: clamp(y, -1, 1),
      intensity: clamp(intensity, 0, 1),
      source: source === "orientation" || source === "pointer" ? source : "default"
    };
    schedule();
  }
  function step(timestamp){
    frame = 0;
    const now = Number(timestamp || performance.now() || Date.now());
    const interval = 1000 / currentFps();
    if(lastFrameAt && now - lastFrameAt < interval - 1){ schedule(); return false; }
    const elapsed = lastFrameAt ? Math.max(1, now - lastFrameAt) : interval;
    lastFrameAt = now;
    const smoothing = 1 - Math.exp(-elapsed / 45);
    light.x += (target.x - light.x) * smoothing;
    light.y += (target.y - light.y) * smoothing;
    light.intensity += (target.intensity - light.intensity) * smoothing;
    light.source = target.source;
    const moving = Math.abs(target.x - light.x) > 0.002 || Math.abs(target.y - light.y) > 0.002 || Math.abs(target.intensity - light.intensity) > 0.002;
    markGlassFrame();
    if(moving) schedule();
    return moving;
  }
  function resetPointerLight(){
    if(!orientationActive)setTarget(neutral.x,neutral.y,neutral.intensity,"default");
  }
  function pointerMove(event){
    if(orientationActive) return;
    const width = Math.max(1, window.innerWidth || 1);
    const height = Math.max(1, window.innerHeight || 1);
    const x = clamp(((Number(event.clientX) || width / 2) / width - .5) * 0.90, -0.45, 0.45);
    const y = clamp(((Number(event.clientY) || height / 2) / height - .5) * 0.75, -0.38, 0.38);
    setTarget(x, y, 0.42, "pointer");
    if(pointerIdleTimer) clearTimeout(pointerIdleTimer);
    pointerIdleTimer = setTimeout(resetPointerLight, 900);
  }
  function orientationChange(event){
    if(!event || event.beta == null || event.gamma == null) return;
    const beta = Number(event && event.beta);
    const gamma = Number(event && event.gamma);
    if(!Number.isFinite(beta) || !Number.isFinite(gamma)) return;
    if(!orientationOrigin) orientationOrigin = {beta, gamma};
    const angle = Number(window.screen && window.screen.orientation && window.screen.orientation.angle || window.orientation || 0) * Math.PI / 180;
    const multiplier = motionEffectMultiplier();
    const dx = Math.sin((gamma - orientationOrigin.gamma) * Math.PI / 180) * 2 * multiplier;
    const dy = Math.sin((beta - orientationOrigin.beta) * Math.PI / 180) * 2 * multiplier;
    orientationActive = true;
    setTarget(neutral.x + dx * Math.cos(angle) + dy * Math.sin(angle), neutral.y + dy * Math.cos(angle) - dx * Math.sin(angle), 0.95, "orientation");
  }
  function attachOrientation(){
    if(orientationAttached || !window.addEventListener) return;
    orientationAttached = true;
    window.addEventListener("deviceorientation", orientationChange, {passive:true});
  }
  function requestOrientationPermission(retry){
    const eventType = window.DeviceOrientationEvent;
    if(!eventType || typeof eventType.requestPermission !== "function"){
      attachOrientation();
      return Promise.resolve("granted");
    }
    const stored = storedPermission();
    if(stored === "granted"){
      attachOrientation();
      if(orientationActive) return Promise.resolve("granted");
    }
    if(retry === true && stored === "denied"){
      permissionRequested = false;
      savePermission("unknown");
    }
    if(stored === "denied" && retry !== true) return Promise.resolve("denied");
    if(permissionRequested) return Promise.resolve(stored);
    permissionRequested = true;
    let request;
    try{ request = eventType.requestPermission(); }
    catch(e){ permissionRequested = false; return Promise.resolve("unknown"); }
    return Promise.resolve(request).then((result)=>{
      const value = result === "granted" ? "granted" : result === "denied" ? "denied" : "unknown";
      if(value !== "unknown") savePermission(value);
      if(value === "granted") attachOrientation();
      if(value === "unknown") permissionRequested = false;
      return value;
    }).catch(()=>{
      // A missing user activation is not a user denial. Retry on a valid gesture.
      permissionRequested = false;
      return "unknown";
    });
  }
  function armOrientationPermission(){
    const eventType = window.DeviceOrientationEvent;
    if(!eventType) return;
    if(typeof eventType.requestPermission !== "function"){
      attachOrientation();
      return;
    }
    const stored = storedPermission();
    if(stored === "denied") return;
    if(stored === "granted"){
      attachOrientation();
    }
    const requestOnce = ()=>{
      requestOrientationPermission().then(result=>{
        if(result === "unknown") return;
        ["click", "touchend", "keydown"].forEach(name=>document.removeEventListener(name, requestOnce, true));
      });
    };
    ["click", "touchend", "keydown"].forEach(name=>document.addEventListener(name, requestOnce, {capture:true, passive:true}));
  }
  function init(){
    armOrientationPermission();
    if(window.addEventListener){
      window.addEventListener("pointermove", pointerMove, {passive:true});
      window.addEventListener("pointerleave", resetPointerLight, {passive:true});
      window.addEventListener("blur", resetPointerLight, {passive:true});
    }
  }

  root.glassLighting = {
    state: ()=>({x:light.x, y:light.y, intensity:light.intensity, source:light.source}),
    status: ()=> orientationActive ? "Active" : storedPermission() === "denied" ? "Denied" : "Waiting for motion",
    requestOrientationPermission,
    testing:{permissionKey,storedPermission,setTarget,pointerMove,orientationChange,step,isAnimating:()=>!!frame}
  };
  init();
})();
