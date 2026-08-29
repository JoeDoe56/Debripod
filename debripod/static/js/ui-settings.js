(function(){
  const root = window.DebriPod = window.DebriPod || {};

  // GLASS_DEFAULTS_BEGIN
  const DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS = {
    "libraryList": {"label": "Library list", "material": 0.0},
    "wheel": {"label": "Wheel", "material": 0.0},
    "pathPill": {"label": "Path pill", "material": 0.0},
    "infoPill": {"label": "Info pill", "material": 0.0},
    "listPills": {"label": "List pills", "material": 0.0},
    "selectedRow": {"label": "Selected row", "material": 0.0}
  };
  // GLASS_DEFAULTS_END
  const GLASS_ELEMENT_KEYS = ["libraryList", "wheel", "pathPill", "infoPill", "listPills", "selectedRow"];
  const UI_SETTINGS_KEY = "debripod_ui_settings";
  const DEFAULT_TEXT_MODES = {
    wheelLabels: "transparent",
    pathPill: "transparent",
    infoPill: "transparent",
    rows: "transparent",
    rowPills: "transparent",
    selectedRow: "contrast",
    selectedRowPills: "contrast"
  };
  const DEFAULT_ANIMATION_FPS = {
    selectedRow: 60,
    wheelTilt: 60,
    libraryList: 60,
    infoPill: 60,
    albumArtTransition: 60,
    pathPill: 60,
    rowInsertion: 60
  };
  const BOOTSTRAP_UI_DEFAULTS = (window.DEBRIPOD_UI_DEFAULTS && typeof window.DEBRIPOD_UI_DEFAULTS === "object") ? window.DEBRIPOD_UI_DEFAULTS : {};
  if(BOOTSTRAP_UI_DEFAULTS.liquidGlassElements && typeof BOOTSTRAP_UI_DEFAULTS.liquidGlassElements === "object") Object.assign(DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS, BOOTSTRAP_UI_DEFAULTS.liquidGlassElements);
  if(BOOTSTRAP_UI_DEFAULTS.textModes && typeof BOOTSTRAP_UI_DEFAULTS.textModes === "object") Object.assign(DEFAULT_TEXT_MODES, BOOTSTRAP_UI_DEFAULTS.textModes);
  if(BOOTSTRAP_UI_DEFAULTS.animationFps && typeof BOOTSTRAP_UI_DEFAULTS.animationFps === "object") Object.assign(DEFAULT_ANIMATION_FPS, BOOTSTRAP_UI_DEFAULTS.animationFps);
  const VISUALIZER_PRESETS = {
    album: {label: "Orbit", style: "orbit", motion: 1.0, layers: 5, flow: 0.88, bassResponse: 1.18, midResponse: 0.72, trebleResponse: 0.92, beatResponse: 1.12},
    aurora: {label: "Aurora", style: "aurora", motion: 0.82, layers: 7, flow: 1.12, bassResponse: 0.52, midResponse: 1.14, trebleResponse: 0.84, beatResponse: 0.62},
    ember: {label: "Ember", style: "ember", motion: 0.72, layers: 6, flow: 0.68, bassResponse: 1.26, midResponse: 0.68, trebleResponse: 1.08, beatResponse: 1.34},
    prism: {label: "Prism", style: "prism", motion: 1.18, layers: 8, flow: 0.94, bassResponse: 0.64, midResponse: 0.92, trebleResponse: 1.42, beatResponse: 0.84},
    sonar: {label: "Sonar", style: "sonar", motion: 0.94, layers: 6, flow: 0.76, bassResponse: 1.42, midResponse: 0.62, trebleResponse: 0.96, beatResponse: 1.48},
    cascade: {label: "Cascade", style: "cascade", motion: 0.76, layers: 9, flow: 1.22, bassResponse: 0.88, midResponse: 1.2, trebleResponse: 1.04, beatResponse: 0.72},
    nova: {label: "Nova", style: "nova", motion: 1.08, layers: 6, flow: 0.86, bassResponse: 1.34, midResponse: 0.74, trebleResponse: 0.9, beatResponse: 1.58},
    lattice: {label: "Lattice", style: "lattice", motion: 0.88, layers: 10, flow: 0.72, bassResponse: 0.82, midResponse: 1.02, trebleResponse: 1.18, beatResponse: 0.74}
  };
  const VISUALIZER_BAND_LABELS = ["low low", "low high", "low mids", "mids", "upper mids", "high low", "high high"];
  let serverUiSettings = null;
  const DEFAULT_UI_SETTINGS = {
      "visualizer": true,
      "visualizerMaxBrightnessPct": 60,
      "visualizerPreset": "album",
      "visualizerFpsLock": 30,
      "textModes": {
          "wheelLabels": "transparent",
          "pathPill": "transparent",
          "infoPill": "transparent",
          "rows": "transparent",
          "rowPills": "transparent",
          "selectedRow": "contrast",
          "selectedRowPills": "contrast"
      },
      "textTransparency": 0.68,
      "animationFps": {
          "selectedRow": 60,
          "wheelTilt": 60,
          "libraryList": 60,
          "infoPill": 60,
          "albumArtTransition": 60,
          "pathPill": 60
      },
      "performanceOverlayButton": true,
      "performanceOverlayText": false,
      "liquidGlassElements": cloneGlassElementSettings(DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS),
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

  function normalizeVisualizerPreset(value){
    const k = String(value || "album").trim().toLowerCase();
    return VISUALIZER_PRESETS[k] ? k : "album";
  }

  function normalizeVisualizerFpsLock(value){
    const n = Number(value);
    if(n === 30 || n === 60 || n === 120) return n;
    return 60;
  }

  function normalizeTextMode(value, fallback){
    const k = String(value || "transparent").trim().toLowerCase();
    if(k === "black" || k === "white" || k === "engraved") return "contrast";
    if(k === "contrast" || k === "transparent") return k;
    return fallback === "contrast" ? "contrast" : "transparent";
  }

  function normalizeTextTransparency(value){
    return clampNumber(value, DEFAULT_UI_SETTINGS && DEFAULT_UI_SETTINGS.textTransparency != null ? DEFAULT_UI_SETTINGS.textTransparency : 0.68, 0, 1);
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
    if(saved.visualizerPreset != null) out.visualizerPreset = normalizeVisualizerPreset(saved.visualizerPreset);
    if(saved.visualizerFpsLock != null) out.visualizerFpsLock = normalizeVisualizerFpsLock(saved.visualizerFpsLock);
    if(saved.textModes != null) out.textModes = cloneTextModes(saved.textModes);
    if(saved.textTransparency != null) out.textTransparency = normalizeTextTransparency(saved.textTransparency);
    if(saved.animationFps != null) out.animationFps = cloneAnimationFps(saved.animationFps);
    if(saved.performanceOverlayButton != null) out.performanceOverlayButton = !!saved.performanceOverlayButton;
    if(saved.performanceOverlayText != null) out.performanceOverlayText = !!saved.performanceOverlayText;
    if(saved.liquidGlassElements != null) out.liquidGlassElements = cloneGlassElementSettings(saved.liquidGlassElements);
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

  function loadUiSettings(){
    const out = Object.assign({}, DEFAULT_UI_SETTINGS);
    if(serverUiSettings) applyUiSettingsObject(out, serverUiSettings);
    if(!serverUiSettings) try{
      const raw = localStorage.getItem(UI_SETTINGS_KEY) || "";
      if(raw){
        const saved = JSON.parse(raw);
        if(saved && typeof saved === "object") applyUiSettingsObject(out, saved);
      }
    }catch(e){}
    try{
      const legacyVisualizer = localStorage.getItem("debripod_visualizer");
      if(legacyVisualizer !== null) out.visualizer = legacyVisualizer === "1";
    }catch(e){}
    try{
      const legacyStrength = localStorage.getItem("debripod_visualizer_strength");
      if(legacyStrength !== null) out.visualizerMaxBrightnessPct = legacyVisualizerBrightnessPct(legacyStrength);
      out.visualizerMaxBrightnessPct = normalizeVisualizerMaxBrightnessPct(out.visualizerMaxBrightnessPct);
    }catch(e){}
    try{ out.visualizerPreset = normalizeVisualizerPreset(localStorage.getItem("debripod_visualizer_preset") || out.visualizerPreset); }catch(e){}
    try{ out.visualizerFpsLock = normalizeVisualizerFpsLock(localStorage.getItem("debripod_visualizer_fps_lock") || out.visualizerFpsLock); }catch(e){}
    out.textModes = cloneTextModes(out.textModes);
    out.textTransparency = normalizeTextTransparency(out.textTransparency);
    out.animationFps = cloneAnimationFps(out.animationFps);
    try{
      const legacyMode = String(localStorage.getItem("debripod_liquid_gl_mode") || "").trim().toLowerCase();
      if(legacyMode === "dark" || legacyMode === "light") {
        out.liquidGlassElements = cloneGlassElementSettings(out.liquidGlassElements);
        GLASS_ELEMENT_KEYS.forEach((key)=>{
          out.liquidGlassElements[key].material = legacyMode === "dark" ? -0.52 : 0.52;
        });
      }
    }catch(e){}
    return out;
  }

  function saveUiSettings(settings){
    const uiSettings = settings || root.uiSettings.settings || DEFAULT_UI_SETTINGS;
    try{ localStorage.setItem(UI_SETTINGS_KEY, JSON.stringify(uiSettings)); }catch(e){}
    try{ localStorage.setItem("debripod_visualizer", uiSettings.visualizer ? "1" : "0"); }catch(e){}
    try{ localStorage.setItem("debripod_visualizer_preset", uiSettings.visualizerPreset); }catch(e){}
    try{ localStorage.setItem("debripod_visualizer_fps_lock", String(normalizeVisualizerFpsLock(uiSettings.visualizerFpsLock))); }catch(e){}
    try{ uiSettings.textModes = cloneTextModes(uiSettings.textModes); }catch(e){}
    try{ uiSettings.textTransparency = normalizeTextTransparency(uiSettings.textTransparency); }catch(e){}
    try{ uiSettings.animationFps = cloneAnimationFps(uiSettings.animationFps); }catch(e){}
    try{ uiSettings.visualizerMaxBrightnessPct = normalizeVisualizerMaxBrightnessPct(uiSettings.visualizerMaxBrightnessPct); }catch(e){}
    uiSettings.performanceOverlayButton = !!uiSettings.performanceOverlayButton;
    uiSettings.performanceOverlayText = !!uiSettings.performanceOverlayText;
    try{ uiSettings.liquidGlassElements = cloneGlassElementSettings(uiSettings.liquidGlassElements); }catch(e){}
    try{
      clearTimeout(root.uiSettings._saveTimer || 0);
      root.uiSettings._saveTimer = setTimeout(function(){
        if(typeof apiPost === "function") apiPost("/api/settings/save", {settings:uiSettingsToAppSettings(uiSettings)}).catch(function(){});
      }, 350);
    }catch(e){}
  }

  async function flushUiSettings(){
    try{
      clearTimeout(root.uiSettings._saveTimer || 0);
      if(typeof apiPost === "function") await apiPost("/api/settings/save", {settings:uiSettingsToAppSettings(uiSettings)});
    }catch(e){}
  }

  function appSettingsToUiSettings(settings){
    const s = settings && typeof settings === "object" ? settings : {};
    const out = {visualizer:s.UI_VISUALIZER, visualizerMaxBrightnessPct:s.UI_VISUALIZER_MAX_BRIGHTNESS_PCT, visualizerPreset:s.UI_VISUALIZER_PRESET, visualizerFpsLock:s.UI_VISUALIZER_FPS_LOCK, textTransparency:s.UI_TEXT_TRANSPARENCY, performanceOverlayButton:s.UI_PERFORMANCE_OVERLAY_BUTTON, performanceOverlayText:s.UI_PERFORMANCE_OVERLAY_TEXT, centerBounceAmount:s.UI_CENTER_BOUNCE_AMOUNT, centerBounceDuration:s.UI_CENTER_BOUNCE_DURATION, centerBounceOvershoot:s.UI_CENTER_BOUNCE_OVERSHOOT, wheelClickTiltAmount:s.UI_WHEEL_CLICK_TILT_AMOUNT, wheelTiltRampDuration:s.UI_WHEEL_TILT_RAMP_DURATION, wheelTiltReleaseDuration:s.UI_WHEEL_TILT_RELEASE_DURATION, infoPillDarkMultiplier:s.UI_INFO_PILL_DARK_MULTIPLIER, infoPillLightMultiplier:s.UI_INFO_PILL_LIGHT_MULTIPLIER,
      textModes:{wheelLabels:s.UI_TEXT_WHEEL_LABELS,pathPill:s.UI_TEXT_PATH_PILL,infoPill:s.UI_TEXT_INFO_PILL,rows:s.UI_TEXT_ROWS,rowPills:s.UI_TEXT_ROW_PILLS,selectedRow:s.UI_TEXT_SELECTED_ROW,selectedRowPills:s.UI_TEXT_SELECTED_ROW_PILLS}, animationFps:{selectedRow:s.UI_ANIMATION_SELECTED_ROW_FPS,wheelTilt:s.UI_ANIMATION_WHEEL_TILT_FPS,libraryList:s.UI_ANIMATION_LIBRARY_LIST_FPS,infoPill:s.UI_ANIMATION_INFO_PILL_FPS,albumArtTransition:s.UI_ANIMATION_ALBUM_ART_TRANSITION_FPS,pathPill:s.UI_ANIMATION_PATH_PILL_FPS,rowInsertion:s.UI_ANIMATION_ROW_INSERTION_FPS}, liquidGlassElements:{libraryList:s.UI_GLASS_LIBRARY_LIST,wheel:s.UI_GLASS_WHEEL,pathPill:s.UI_GLASS_PATH_PILL,infoPill:s.UI_GLASS_INFO_PILL,listPills:s.UI_GLASS_LIST_PILLS,selectedRow:s.UI_GLASS_SELECTED_ROW}};
    return out;
  }

  function uiSettingsToAppSettings(s){
    const u=s||{}; const text=u.textModes||{}, fps=u.animationFps||{}, glass=u.liquidGlassElements||{};
    return {UI_VISUALIZER:u.visualizer,UI_VISUALIZER_MAX_BRIGHTNESS_PCT:u.visualizerMaxBrightnessPct,UI_VISUALIZER_PRESET:u.visualizerPreset,UI_VISUALIZER_FPS_LOCK:u.visualizerFpsLock,UI_TEXT_TRANSPARENCY:u.textTransparency,UI_PERFORMANCE_OVERLAY_BUTTON:u.performanceOverlayButton,UI_PERFORMANCE_OVERLAY_TEXT:u.performanceOverlayText,UI_CENTER_BOUNCE_AMOUNT:u.centerBounceAmount,UI_CENTER_BOUNCE_DURATION:u.centerBounceDuration,UI_CENTER_BOUNCE_OVERSHOOT:u.centerBounceOvershoot,UI_WHEEL_CLICK_TILT_AMOUNT:u.wheelClickTiltAmount,UI_WHEEL_TILT_RAMP_DURATION:u.wheelTiltRampDuration,UI_WHEEL_TILT_RELEASE_DURATION:u.wheelTiltReleaseDuration,UI_INFO_PILL_DARK_MULTIPLIER:u.infoPillDarkMultiplier,UI_INFO_PILL_LIGHT_MULTIPLIER:u.infoPillLightMultiplier,UI_TEXT_WHEEL_LABELS:text.wheelLabels,UI_TEXT_PATH_PILL:text.pathPill,UI_TEXT_INFO_PILL:text.infoPill,UI_TEXT_ROWS:text.rows,UI_TEXT_ROW_PILLS:text.rowPills,UI_TEXT_SELECTED_ROW:text.selectedRow,UI_TEXT_SELECTED_ROW_PILLS:text.selectedRowPills,UI_ANIMATION_SELECTED_ROW_FPS:fps.selectedRow,UI_ANIMATION_WHEEL_TILT_FPS:fps.wheelTilt,UI_ANIMATION_LIBRARY_LIST_FPS:fps.libraryList,UI_ANIMATION_INFO_PILL_FPS:fps.infoPill,UI_ANIMATION_ALBUM_ART_TRANSITION_FPS:fps.albumArtTransition,UI_ANIMATION_PATH_PILL_FPS:fps.pathPill,UI_ANIMATION_ROW_INSERTION_FPS:fps.rowInsertion,UI_GLASS_LIBRARY_LIST:glass.libraryList,UI_GLASS_WHEEL:glass.wheel,UI_GLASS_PATH_PILL:glass.pathPill,UI_GLASS_INFO_PILL:glass.infoPill,UI_GLASS_LIST_PILLS:glass.listPills,UI_GLASS_SELECTED_ROW:glass.selectedRow};
  }

  function applyServerAppSettings(settings){
    serverUiSettings = appSettingsToUiSettings(settings);
    if(root.uiSettings){
      root.uiSettings.serverUiSettings = serverUiSettings;
      root.uiSettings.settings = loadUiSettings();
    }
    return root.uiSettings ? root.uiSettings.settings : loadUiSettings();
  }

  function takeLocalUiMigration(){
    try{
      if(localStorage.getItem("debripod_ui_settings_sqlite_v1") === "1") return null;
      const raw = localStorage.getItem(UI_SETTINGS_KEY) || "";
      if(!raw) return null;
      const value = JSON.parse(raw);
      if(!value || typeof value !== "object") return null;
      localStorage.setItem("debripod_ui_settings_sqlite_v1", "1");
      return value;
    }catch(e){ return null; }
  }

  root.uiSettings = {
    DEFAULT_UI_SETTINGS,
    DEFAULT_TEXT_MODES,
    DEFAULT_ANIMATION_FPS,
    DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS,
    GLASS_ELEMENT_KEYS,
    UI_SETTINGS_KEY,
    VISUALIZER_PRESETS,
    VISUALIZER_BAND_LABELS,
    clampNumber,
    normalizeVisualizerStrength,
    normalizeVisualizerMaxBrightnessPct,
    normalizeVisualizerPreset,
    normalizeVisualizerFpsLock,
    normalizeTextMode,
    normalizeTextTransparency,
    cloneTextModes,
    normalizeAnimationFps,
    cloneAnimationFps,
    normalizeLiquidGlassMaterial,
    migrateLegacyGlassMaterial,
    cloneGlassElementSettings,
    applyUiSettingsObject,
    applyServerAppSettings,
    uiSettingsToAppSettings,
    takeLocalUiMigration,
    serverUiSettings,
    loadUiSettings,
    saveUiSettings,
    flushUiSettings,
    settings: loadUiSettings()
  };
})();
