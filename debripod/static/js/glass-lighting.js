/* Glass light direction from device orientation, with the pointer as the
 * alternative on devices that do not tilt. Reusable: createGlassLighting()
 * takes the host's settings, storage and frame request as options. */
(function(){
  function createGlassLighting(config){
    const options = config || {};
    const neutral = {x:-0.16, y:-0.22, intensity:0.22, source:"default"};
    // Pointer and device tilt drive the same light at the same strength, so a
    // computer's mouse reaches every rim the way tilting a phone does.
    const activeIntensity = 0.95;
    const pointerGain = 0.9;
    const light = Object.assign({}, neutral);
    let target = Object.assign({}, neutral);
    let frame = 0;
    let lastFrameAt = 0;
    let orientationAttached = false;
    let orientationActive = false;
    let permissionRequested = false;
    let orientationOrigin = null;

    function clamp(value, low, high){ return Math.max(low, Math.min(high, Number(value) || 0)); }
    function setting(name, fallback){
      try{
        const value = typeof options[name] === "function" ? options[name]() : options[name];
        return value === undefined || value === null ? fallback : value;
      }catch(e){ return fallback; }
    }
    function permissionKey(){ return String(setting("storageKey", "liquid-glass:orientation-permission")); }
    function storedPermission(){
      try{
        const storage = options.storage;
        const value = String(storage && storage.getItem(permissionKey()) || "");
        return value === "granted" || value === "denied" ? value : "unknown";
      }catch(e){ return "unknown"; }
    }
    function savePermission(value){
      try{ if(options.storage) options.storage.setItem(permissionKey(), value); }catch(e){}
    }
    function currentFps(){
      const raw = Number(setting("fps", 60));
      return Math.max(30, Math.min(120, Number.isFinite(raw) ? raw : 60));
    }
    function motionEffectMultiplier(){
      const raw = Number(setting("multiplier", 1));
      return Number.isFinite(raw) ? clamp(raw, 0, 2) : 1;
    }
    function markGlassFrame(){
      try{ if(typeof options.onChange === "function") options.onChange(); }catch(e){}
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
    function compressLightVector(x, y){
      const radius = Math.hypot(x, y);
      const limit = 0.8;
      if(!Number.isFinite(radius) || radius <= limit) return {x, y};
      // Preserve the diagonal direction while easing the vector into the
      // allowed circle. Independent x/y clamping turns diagonal motion into a
      // cardinal snap when the phone is rotated far enough.
      const headroom = 1 - limit;
      const compressed = limit + headroom * (1 - Math.exp(-(radius - limit) / headroom));
      const factor = compressed / radius;
      return {x:x * factor, y:y * factor};
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
      else lastFrameAt = 0; // A new movement must not include time spent idle.
      return moving;
    }
    function resetPointerLight(){
      if(!orientationActive) setTarget(neutral.x, neutral.y, neutral.intensity, "default");
    }
    // The pointer stands in for device tilt: the centre of the window is the
    // resting direction and the edges sweep the light around the full circle.
    // The light holds where the pointer stops and eases back to neutral only
    // when the pointer leaves the window.
    function pointerMove(event){
      if(orientationActive || !event) return;
      const width = Math.max(1, window.innerWidth || 1);
      const height = Math.max(1, window.innerHeight || 1);
      const clientX = Number.isFinite(Number(event.clientX)) ? Number(event.clientX) : width / 2;
      const clientY = Number.isFinite(Number(event.clientY)) ? Number(event.clientY) : height / 2;
      const dx = clamp((clientX / width - 0.5) * 2, -1, 1) * pointerGain;
      const dy = clamp((clientY / height - 0.5) * 2, -1, 1) * pointerGain;
      const projected = compressLightVector(neutral.x + dx, neutral.y + dy);
      setTarget(projected.x, projected.y, activeIntensity, "pointer");
    }
    function pointerLeftWindow(event){
      if(event && event.relatedTarget) return;
      resetPointerLight();
    }
    // W3C device orientation uses Rz(alpha) * Rx(beta) * Ry(gamma).
    // Reconstruct the physical basis before comparing poses: individual Euler
    // angles can exchange values at vertical without any real phone movement.
    function orientationMatrix(alpha, beta, gamma){
      const a = alpha * Math.PI / 180, b = beta * Math.PI / 180, g = gamma * Math.PI / 180;
      const ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b), cg = Math.cos(g), sg = Math.sin(g);
      return [ca*cg-sa*sb*sg, -cb*sa, cg*sa*sb+ca*sg,
        cg*sa+ca*sb*sg, ca*cb, sa*sg-ca*cg*sb,
        -cb*sg, sb, cb*cg];
    }
    function orientationChange(event){
      if(!event || event.beta == null || event.gamma == null) return;
      const beta = Number(event && event.beta);
      const gamma = Number(event && event.gamma);
      if(!Number.isFinite(beta) || !Number.isFinite(gamma)) return;
      const alpha = Number(event.alpha);
      const matrix = orientationMatrix(Number.isFinite(alpha) ? alpha : 0, beta, gamma);
      if(!orientationOrigin) orientationOrigin = {x:matrix[2], y:matrix[5], z:matrix[8]};
      const angle = Number(window.screen && window.screen.orientation && window.screen.orientation.angle || window.orientation || 0) * Math.PI / 180;
      const multiplier = motionEffectMultiplier();
      // Project the initial screen normal into the current phone frame. This
      // gives continuous local tilt whether the initial phone pose is flat or
      // upright, including alpha/gamma exchanges and angle wraparound.
      const sensorScale = 1.15;
      const dx = -(matrix[0]*orientationOrigin.x + matrix[3]*orientationOrigin.y + matrix[6]*orientationOrigin.z) * sensorScale * multiplier;
      const dy = (matrix[1]*orientationOrigin.x + matrix[4]*orientationOrigin.y + matrix[7]*orientationOrigin.z) * sensorScale * multiplier;
      orientationActive = true;
      const projected = compressLightVector(
        neutral.x + dx * Math.cos(angle) + dy * Math.sin(angle),
        neutral.y + dy * Math.cos(angle) - dx * Math.sin(angle)
      );
      setTarget(projected.x, projected.y, activeIntensity, "orientation");
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
        // Capture phase: controls such as the wheel stop pointermove from
        // bubbling while they own a drag, and the light must keep following.
        window.addEventListener("pointermove", pointerMove, {passive:true, capture:true});
        window.addEventListener("blur", resetPointerLight, {passive:true});
      }
      if(document.addEventListener) document.addEventListener("mouseout", pointerLeftWindow, {passive:true});
    }

    init();
    return {
      state: ()=>({x:light.x, y:light.y, intensity:light.intensity, source:light.source}),
      status: ()=> orientationActive ? "Active" : storedPermission() === "denied" ? "Denied" : "Waiting for motion",
      requestOrientationPermission,
      testing:{permissionKey,storedPermission,setTarget,pointerMove,pointerLeftWindow,orientationChange,step,isAnimating:()=>!!frame}
    };
  }

  window.LiquidGlassLighting = {create: createGlassLighting};

  const root = window.DebriPod = window.DebriPod || {};
  const deviceUserId = ()=> String(window.DEBRIPOD_DEVICE_SETTINGS_USER_ID || "anonymous").trim() || "anonymous";
  const appSettings = ()=> (root.uiSettings && root.uiSettings.settings) || {};
  root.glassLighting = createGlassLighting({
    fps: ()=> appSettings().glassInteractionFps,
    multiplier: ()=> appSettings().glassMotionEffectMultiplier,
    storage: {
      getItem: (key)=>{ try{ return window.localStorage ? window.localStorage.getItem(key) : null; }catch(e){ return null; } },
      setItem: (key, value)=>{ try{ if(window.localStorage) window.localStorage.setItem(key, value); }catch(e){} }
    },
    storageKey: ()=> "debripod_glass_orientation_permission:v1:" + deviceUserId(),
    onChange: ()=>{
      const scheduler = root.frameScheduler;
      if(scheduler && scheduler.mark) scheduler.mark({render:true, metrics:true, keepAlive:true});
    }
  });
})();
