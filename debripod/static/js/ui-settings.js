(function(){
  const root = window.DebriPod = window.DebriPod || {};

  // GLASS_DEFAULTS_BEGIN
  const DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS = {
    "libraryList": {"label": "Library list", "material": -0.20},
    "wheel": {"label": "Wheel", "material": -0.20},
    "pathPill": {"label": "Path pill", "material": -0.20},
    "infoPill": {"label": "Info pill", "material": -0.20},
    "listPills": {"label": "List pills", "material": 0.0},
    "selectedRow": {"label": "Selected row", "material": -0.50}
  };
  // GLASS_DEFAULTS_END
  const GLASS_ELEMENT_KEYS = ["libraryList", "wheel", "pathPill", "infoPill", "listPills", "selectedRow"];
  const UI_SETTINGS_KEY = "debripod_device_ui_settings:v3";
  const LEGACY_UI_SETTINGS_KEY = "debripod_ui_settings";
  const LEGACY_UI_MIGRATION_KEY = "debripod_device_ui_settings:v3:migrated";
  const DEFAULT_TEXT_MODES = {
    wheelLabels: "transparent",
    pathPill: "transparent",
    infoPill: "transparent",
    rows: "transparent",
    rowPills: "transparent",
    selectedRow: "white",
    selectedRowPills: "white"
  };
  const DEFAULT_ANIMATION_FPS = {
    selectedRow: 60,
    wheelTilt: 60,
    libraryList: 60,
    infoPill: 60,
    pathPill: 60,
    rowInsertion: 60
  };
  const BOOTSTRAP_UI_DEFAULTS = (window.DEBRIPOD_UI_DEFAULTS && typeof window.DEBRIPOD_UI_DEFAULTS === "object") ? window.DEBRIPOD_UI_DEFAULTS : {};
  if(BOOTSTRAP_UI_DEFAULTS.liquidGlassElements && typeof BOOTSTRAP_UI_DEFAULTS.liquidGlassElements === "object") Object.assign(DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS, BOOTSTRAP_UI_DEFAULTS.liquidGlassElements);
  if(BOOTSTRAP_UI_DEFAULTS.textModes && typeof BOOTSTRAP_UI_DEFAULTS.textModes === "object") Object.assign(DEFAULT_TEXT_MODES, BOOTSTRAP_UI_DEFAULTS.textModes);
  if(BOOTSTRAP_UI_DEFAULTS.animationFps && typeof BOOTSTRAP_UI_DEFAULTS.animationFps === "object") Object.assign(DEFAULT_ANIMATION_FPS, BOOTSTRAP_UI_DEFAULTS.animationFps);
  const VISUALIZER_BAND_LABELS = ["low-low", "mid-low", "high-low", "low-mid", "mid-mid", "high-mid", "low-high", "mid-high", "high-high"];
  let deviceSettingsUserId = String(window.DEBRIPOD_DEVICE_SETTINGS_USER_ID || "").trim();
  const DEFAULT_UI_SETTINGS = {
      "visualizer": true,
      "visualizerMaxBrightnessPct": 60,
      "visualizerFpsLock": 30,
      "visualizerRotationsPerTrack": 3,
      "visualizerFrequencyResponse": {"brightness": 1.0, "opacity": 0.0, "saturation": 0.15, "contrast": 0.10},
      "visualizerEnergyResponse": {"brightness": 0.12, "opacity": 0.0, "saturation": 0.05, "contrast": 0.05},
      "visualizerBeatResponse": {"brightness": 0.10, "opacity": 0.0, "saturation": 0.0, "contrast": 0.05},
      "videoAmbient": {"enabled": true, "sampleFps": 8, "brightness": 1.0, "saturation": 1.0, "audioEnergyBrightness": 0.12, "smoothing": 0.82},
      "textModes": {
          "wheelLabels": "transparent",
          "pathPill": "transparent",
          "infoPill": "transparent",
          "rows": "transparent",
          "rowPills": "transparent",
          "selectedRow": "white",
          "selectedRowPills": "white"
      },
      // Text opacity is the single base foreground value. textTransparency is
      // retained as a read/write migration alias for older saved devices.
      "textOpacity": 0.45,
      "textTransparency": 0.45,
      "animationFps": {
          "selectedRow": 60,
          "wheelTilt": 60,
          "libraryList": 60,
          "infoPill": 60,
          "pathPill": 60
      },
      "performanceOverlayText": false,
      "liquidGlassElements": cloneGlassElementSettings(DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS),
      "glassRenderScale": 1.5,
      "glassRenderScaleVersion": 1,
      "glassFrostSamples": 8,
      "glassIdleFps": 30,
      "glassInteractionFps": 60,
      "glassMotionEffectMultiplier": 1.0,
      "centerBounceAmount": 0.075,
      "centerBounceDuration": 240.0,
      "centerBounceOvershoot": 0.9,
      "wheelClickTiltAmount": 0.5,
      "wheelTiltRampDuration": 90.0,
      "wheelTiltReleaseDuration": 360.0,
      "infoPillDarkMultiplier": 1.0,
      "infoPillLightMultiplier": 1.0
  };
  Object.assign(DEFAULT_UI_SETTINGS, BOOTSTRAP_UI_DEFAULTS);
  if(BOOTSTRAP_UI_DEFAULTS.textOpacity == null && BOOTSTRAP_UI_DEFAULTS.textTransparency != null) DEFAULT_UI_SETTINGS.textOpacity = Number(BOOTSTRAP_UI_DEFAULTS.textTransparency);
  DEFAULT_UI_SETTINGS.textModes = cloneTextModes(DEFAULT_UI_SETTINGS.textModes);
  DEFAULT_UI_SETTINGS.animationFps = cloneAnimationFps(DEFAULT_UI_SETTINGS.animationFps);
  DEFAULT_UI_SETTINGS.liquidGlassElements = cloneGlassElementSettings(DEFAULT_UI_SETTINGS.liquidGlassElements);

  function clampNumber(value, fallback, min, max){
    const n = Number(value);
    if(!Number.isFinite(n)) return fallback;
    return Math.max(min, Math.min(max, n));
  }

  function normalizeVisualizerStrength(value){
    const k = String(value || "medium").trim().toLowerCase();
    return (k === "low" || k === "medium" || k === "high") ? k : "medium";
  }

  function normalizeVisualizerMaxBrightnessPct(value){
    return clampNumber(value, 60, 0, 200);
  }

  function legacyVisualizerBrightnessPct(value){
    const k = normalizeVisualizerStrength(value);
    if(k === "low") return 35;
    if(k === "medium") return 50;
    return 60;
  }

  function normalizeVisualizerFpsLock(value){
    const n = Number(value);
    if(n === 30 || n === 60 || n === 120) return n;
    return 60;
  }

  function normalizeVisualizerRotationsPerTrack(value){
    const n = Number(value);
    return Number.isFinite(n) ? Math.max(1, Math.min(12, Math.round(n))) : 3;
  }

  function normalizeTextMode(value, fallback){
    const k = String(value || "transparent").trim().toLowerCase();
    if(k === "black" || k === "contrast" || k === "engraved") return "white";
    if(k === "white" || k === "transparent") return k;
    return fallback === "white" ? "white" : "transparent";
  }

  function normalizeTextTransparency(value){
    return clampNumber(value, DEFAULT_UI_SETTINGS && DEFAULT_UI_SETTINGS.textOpacity != null ? DEFAULT_UI_SETTINGS.textOpacity : 0.45, 0, 1);
  }

  function normalizeTextOpacity(value){
    return clampNumber(value, DEFAULT_UI_SETTINGS && DEFAULT_UI_SETTINGS.textOpacity != null ? DEFAULT_UI_SETTINGS.textOpacity : 0.45, 0, 1);
  }

  function strongerForegroundOpacity(value){
    return Math.min(1, normalizeTextOpacity(value) * 2);
  }

  function cloneTextModes(value){
    const src = value && typeof value === "object" ? value : {};
    const out = {};
    Object.keys(DEFAULT_TEXT_MODES).forEach((key)=>{
      const inherit = key === "infoPill" && src.infoPill == null && src.pathPill != null ? src.pathPill : null;
      out[key] = normalizeTextMode(inherit || src[key] || DEFAULT_TEXT_MODES[key], DEFAULT_TEXT_MODES[key]);
    });
    return out;
  }

  function normalizeAnimationFps(value){
    const n = Number(value);
    if(n === 30 || n === 60 || n === 120) return n;
    return 60;
  }

  function cloneAnimationFps(value){
    const src = value && typeof value === "object" ? value : {};
    const out = {};
    Object.keys(DEFAULT_ANIMATION_FPS).forEach((key)=>{
      const inherit = key === "infoPill" && src.infoPill == null && src.pathPill != null ? src.pathPill : null;
      out[key] = normalizeAnimationFps(src[key] == null ? (inherit == null ? DEFAULT_ANIMATION_FPS[key] : inherit) : src[key]);
    });
    return out;
  }

  function normalizeLiquidGlassMaterial(value, fallback){
    return clampNumber(value, fallback == null ? 0 : fallback, -1, 1);
  }

  function normalizeGlassMotionEffectMultiplier(value){
    return clampNumber(value, 1, 0, 2);
  }

  function migrateLegacyGlassMaterial(src, fallback){
    if(src && Number.isFinite(Number(src.material))){
      return normalizeLiquidGlassMaterial(src.material, fallback);
    }
    const tint = src && Number.isFinite(Number(src.glassTint)) ? Math.max(0, Math.min(2, Number(src.glassTint))) : 1;
    let material = tint < 1 ? -(1 - tint) * 0.52 : (tint > 1 ? (tint - 1) * 0.52 : fallback);
    const legacyMode = String((src && src.mode) || "").trim().toLowerCase();
    if(material === 0 && legacyMode === "dark") material = -0.52;
    if(material === 0 && legacyMode === "light") material = 0.52;
    if(src && Number.isFinite(Number(src.transparency))){
      const opacityScale = 1 - Math.max(0, Math.min(1, Number(src.transparency)));
      material *= opacityScale;
    }
    return normalizeLiquidGlassMaterial(material, fallback);
  }

  function cloneGlassElementSettings(value){
    const out = {};
    const input = value && typeof value === "object" ? Object.assign({}, value) : {};
    if(!input.infoPill && input.pathPill) input.infoPill = input.pathPill;
    else if(!input.infoPill && input.nowPlayingPill) input.infoPill = input.nowPlayingPill;
    GLASS_ELEMENT_KEYS.forEach((key)=>{
      const def = DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS[key];
      const src = input[key] && typeof input[key] === "object" ? input[key] : {};
      out[key] = {
        label: def.label,
        material: migrateLegacyGlassMaterial(src, normalizeLiquidGlassMaterial(def.material, 0))
      };
    });
    return out;
  }

  function applyUiSettingsObject(out, saved){
    if(!out || !saved || typeof saved !== "object") return out;
    if(Object.prototype.hasOwnProperty.call(saved, "visualizer")) out.visualizer = !!saved.visualizer;
    if(saved.visualizerMaxBrightnessPct != null) out.visualizerMaxBrightnessPct = normalizeVisualizerMaxBrightnessPct(saved.visualizerMaxBrightnessPct);
    else if(saved.visualizerStrength != null) out.visualizerMaxBrightnessPct = legacyVisualizerBrightnessPct(saved.visualizerStrength);
    if(saved.visualizerFpsLock != null) out.visualizerFpsLock = normalizeVisualizerFpsLock(saved.visualizerFpsLock);
    if(saved.visualizerRotationsPerTrack != null) out.visualizerRotationsPerTrack = normalizeVisualizerRotationsPerTrack(saved.visualizerRotationsPerTrack);
    if(saved.visualizerFrequencyResponse != null) out.visualizerFrequencyResponse = cloneVisualizerResponse(saved.visualizerFrequencyResponse, out.visualizerFrequencyResponse);
    if(saved.visualizerEnergyResponse != null) out.visualizerEnergyResponse = cloneVisualizerResponse(saved.visualizerEnergyResponse, out.visualizerEnergyResponse);
    if(saved.visualizerBeatResponse != null) out.visualizerBeatResponse = cloneVisualizerResponse(saved.visualizerBeatResponse, out.visualizerBeatResponse);
    if(saved.videoAmbient != null) out.videoAmbient = cloneVideoAmbientSettings(saved.videoAmbient);
    if(saved.textModes != null) out.textModes = cloneTextModes(saved.textModes);
    if(saved.textOpacity != null) out.textOpacity = normalizeTextOpacity(saved.textOpacity);
    else if(saved.textTransparency != null) out.textOpacity = normalizeTextOpacity(saved.textTransparency);
    if(saved.textTransparency != null || saved.textOpacity != null) out.textTransparency = normalizeTextOpacity(saved.textOpacity == null ? saved.textTransparency : saved.textOpacity);
    if(saved.animationFps != null) out.animationFps = cloneAnimationFps(saved.animationFps);
    if(saved.performanceOverlayText != null) out.performanceOverlayText = !!saved.performanceOverlayText;
    if(saved.liquidGlassElements != null) out.liquidGlassElements = cloneGlassElementSettings(saved.liquidGlassElements);
    if(saved.glassRenderScale != null) out.glassRenderScale = Number(saved.glassRenderScaleVersion || 0) < 1 ? 1.5 : clampNumber(saved.glassRenderScale, out.glassRenderScale, 0.5, 2);
    out.glassRenderScaleVersion = 1;
    if(saved.glassFrostSamples != null) out.glassFrostSamples = Math.round(clampNumber(saved.glassFrostSamples, out.glassFrostSamples, 0, 16));
    if(saved.glassIdleFps != null) out.glassIdleFps = normalizeAnimationFps(saved.glassIdleFps);
    if(saved.glassInteractionFps != null) out.glassInteractionFps = normalizeAnimationFps(saved.glassInteractionFps);
    if(saved.glassMotionEffectMultiplier != null) out.glassMotionEffectMultiplier = normalizeGlassMotionEffectMultiplier(saved.glassMotionEffectMultiplier);
    if(saved.centerBounceAmount != null) out.centerBounceAmount = clampNumber(saved.centerBounceAmount, out.centerBounceAmount, 0, 0.3);
    if(saved.centerBounceDuration != null) out.centerBounceDuration = clampNumber(saved.centerBounceDuration, out.centerBounceDuration, 0, 1000);
    if(saved.centerBounceOvershoot != null) out.centerBounceOvershoot = clampNumber(saved.centerBounceOvershoot, out.centerBounceOvershoot, 0, 1.4);
    if(saved.wheelClickTiltAmount != null) out.wheelClickTiltAmount = clampNumber(saved.wheelClickTiltAmount, out.wheelClickTiltAmount, 0, 1);
    if(saved.wheelTiltRampDuration != null) out.wheelTiltRampDuration = clampNumber(saved.wheelTiltRampDuration, out.wheelTiltRampDuration, 0, 1000);
    if(saved.wheelTiltReleaseDuration != null) out.wheelTiltReleaseDuration = clampNumber(saved.wheelTiltReleaseDuration, out.wheelTiltReleaseDuration, 0, 1200);
    if(saved.infoPillDarkMultiplier != null) out.infoPillDarkMultiplier = clampNumber(saved.infoPillDarkMultiplier, out.infoPillDarkMultiplier, 0, 4);
    if(saved.infoPillLightMultiplier != null) out.infoPillLightMultiplier = clampNumber(saved.infoPillLightMultiplier, out.infoPillLightMultiplier, 0, 4);
    return out;
  }

  function deviceSettingsKey(userId){
    const id = String(userId == null ? deviceSettingsUserId : userId).trim();
    return id ? (UI_SETTINGS_KEY + ":" + id) : "";
  }

  function normalizeUiSettings(out){
    out.textModes = cloneTextModes(out.textModes);
    out.textOpacity = normalizeTextOpacity(out.textOpacity == null ? out.textTransparency : out.textOpacity);
    out.textTransparency = out.textOpacity;
    out.animationFps = cloneAnimationFps(out.animationFps);
    out.visualizerMaxBrightnessPct = normalizeVisualizerMaxBrightnessPct(out.visualizerMaxBrightnessPct);
    out.visualizerRotationsPerTrack = normalizeVisualizerRotationsPerTrack(out.visualizerRotationsPerTrack);
    out.visualizerFrequencyResponse = cloneVisualizerResponse(out.visualizerFrequencyResponse, DEFAULT_UI_SETTINGS.visualizerFrequencyResponse);
    out.visualizerEnergyResponse = cloneVisualizerResponse(out.visualizerEnergyResponse, DEFAULT_UI_SETTINGS.visualizerEnergyResponse);
    out.visualizerBeatResponse = cloneVisualizerResponse(out.visualizerBeatResponse, DEFAULT_UI_SETTINGS.visualizerBeatResponse);
    out.videoAmbient = cloneVideoAmbientSettings(out.videoAmbient);
    out.performanceOverlayText = !!out.performanceOverlayText;
    out.liquidGlassElements = cloneGlassElementSettings(out.liquidGlassElements);
    out.glassRenderScale = clampNumber(out.glassRenderScale, 1.5, 0.5, 2);
    out.glassFrostSamples = Math.round(clampNumber(out.glassFrostSamples, 8, 0, 16));
    out.glassIdleFps = normalizeAnimationFps(out.glassIdleFps);
    out.glassInteractionFps = normalizeAnimationFps(out.glassInteractionFps);
    out.glassMotionEffectMultiplier = normalizeGlassMotionEffectMultiplier(out.glassMotionEffectMultiplier);
    return out;
  }

  function legacyDeviceSettings(){
    const legacy = {};
    try{
      const raw = localStorage.getItem(LEGACY_UI_SETTINGS_KEY) || "";
      if(raw){
        const parsed = JSON.parse(raw);
        if(parsed && typeof parsed === "object") Object.assign(legacy, parsed);
      }
      const visualizer = localStorage.getItem("debripod_visualizer");
      if(visualizer !== null) legacy.visualizer = visualizer === "1";
      const strength = localStorage.getItem("debripod_visualizer_strength");
      if(strength !== null) legacy.visualizerMaxBrightnessPct = legacyVisualizerBrightnessPct(strength);
      const fps = localStorage.getItem("debripod_visualizer_fps_lock");
      if(fps !== null) legacy.visualizerFpsLock = fps;
      const mode = String(localStorage.getItem("debripod_liquid_gl_mode") || "").trim().toLowerCase();
      if(mode === "dark" || mode === "light"){
        legacy.liquidGlassElements = legacy.liquidGlassElements || {};
        GLASS_ELEMENT_KEYS.forEach((key)=>{ legacy.liquidGlassElements[key] = {material:mode === "dark" ? -0.52 : 0.52}; });
      }
    }catch(e){}
    return legacy;
  }

  function setDeviceSettingsUserId(userId){
    const next = String(userId || "").trim();
    if(!next) return root.uiSettings ? root.uiSettings.settings : loadUiSettings();
    if(next === deviceSettingsUserId && root.uiSettings){
      // Keep the legacy alias live for older modules that still mutate it
      // directly; the settings screen writes both fields together.
      const current = root.uiSettings.settings;
      if(current && current.textTransparency !== current.textOpacity) current.textOpacity = normalizeTextOpacity(current.textTransparency);
      return current;
    }
    deviceSettingsUserId = next;
    const targetKey = deviceSettingsKey(next);
    try{
      if(!localStorage.getItem(targetKey) && localStorage.getItem(LEGACY_UI_MIGRATION_KEY) !== "1"){
        const migrated = normalizeUiSettings(applyUiSettingsObject(Object.assign({}, DEFAULT_UI_SETTINGS), legacyDeviceSettings()));
        localStorage.setItem(targetKey, JSON.stringify(migrated));
        localStorage.setItem(LEGACY_UI_MIGRATION_KEY, "1");
      }
    }catch(e){}
    const loaded = loadUiSettings();
    if(root.uiSettings) root.uiSettings.settings = loaded;
    return loaded;
  }

  function loadUiSettings(){
    const out = Object.assign({}, DEFAULT_UI_SETTINGS);
    const key = deviceSettingsKey();
    if(key) try{
      const raw = localStorage.getItem(key) || "";
      if(raw){
        const saved = JSON.parse(raw);
        if(saved && typeof saved === "object") applyUiSettingsObject(out, saved);
      }
    }catch(e){}
    return normalizeUiSettings(out);
  }

  function saveUiSettings(settings){
    const saved = normalizeUiSettings(settings || root.uiSettings.settings || Object.assign({}, DEFAULT_UI_SETTINGS));
    const key = deviceSettingsKey();
    if(key) try{ localStorage.setItem(key, JSON.stringify(saved)); }catch(e){}
    if(root.uiSettings) root.uiSettings.settings = saved;
    return saved;
  }

  async function flushUiSettings(){
    return saveUiSettings(root.uiSettings && root.uiSettings.settings);
  }

  function cloneVisualizerResponse(value, fallback){
    const src = value && typeof value === "object" ? value : {};
    const def = fallback && typeof fallback === "object" ? fallback : {};
    return {
      brightness: clampNumber(src.brightness, Number(def.brightness || 0), 0, 2),
      opacity: clampNumber(src.opacity, Number(def.opacity || 0), 0, 1),
      saturation: clampNumber(src.saturation, Number(def.saturation || 0), -1, 1),
      contrast: clampNumber(src.contrast, Number(def.contrast || 0), -1, 1)
    };
  }

  function cloneVideoAmbientSettings(value){
    const src = value && typeof value === "object" ? value : {};
    const def = (DEFAULT_UI_SETTINGS && DEFAULT_UI_SETTINGS.videoAmbient) || {};
    return {
      enabled: src.enabled == null ? !!def.enabled : !!src.enabled,
      sampleFps: clampNumber(src.sampleFps, Number(def.sampleFps || 8), 1, 30),
      brightness: clampNumber(src.brightness, Number(def.brightness || 1), 0, 2),
      saturation: clampNumber(src.saturation, Number(def.saturation || 1), 0, 2),
      audioEnergyBrightness: clampNumber(src.audioEnergyBrightness, Number(def.audioEnergyBrightness || 0), 0, 2),
      smoothing: clampNumber(src.smoothing, Number(def.smoothing || 0.82), 0, 0.99)
    };
  }

  // Bootstrap already knows the authenticated immutable user ID, so migrate
  // an old browser-local payload before the first visual frame is rendered.
  if(deviceSettingsUserId) setDeviceSettingsUserId(deviceSettingsUserId);

  root.uiSettings = {
    DEFAULT_UI_SETTINGS,
    DEFAULT_TEXT_MODES,
    DEFAULT_ANIMATION_FPS,
    DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS,
    GLASS_ELEMENT_KEYS,
    UI_SETTINGS_KEY,
    VISUALIZER_BAND_LABELS,
    clampNumber,
    normalizeVisualizerStrength,
    normalizeVisualizerMaxBrightnessPct,
    normalizeVisualizerFpsLock,
    normalizeVisualizerRotationsPerTrack,
    normalizeTextMode,
    normalizeTextTransparency,
    normalizeTextOpacity,
    strongerForegroundOpacity,
    cloneTextModes,
    normalizeAnimationFps,
    cloneAnimationFps,
    normalizeLiquidGlassMaterial,
    normalizeGlassMotionEffectMultiplier,
    migrateLegacyGlassMaterial,
    cloneGlassElementSettings,
    cloneVisualizerResponse,
    cloneVideoAmbientSettings,
    applyUiSettingsObject,
    deviceSettingsKey,
    setDeviceSettingsUserId,
    loadUiSettings,
    saveUiSettings,
    flushUiSettings,
    settings: loadUiSettings()
  };
})();
