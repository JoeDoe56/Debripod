(function(){
  const root = window.DebriPod = window.DebriPod || {};

  // GLASS_DEFAULTS_BEGIN
  const DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS = {
    "libraryList": {
      "label": "Library list",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 0.25,
      "refraction": 0.045,
      "bevelDepth": 0.02,
      "bevelWidth": 0.1,
      "frost": 3.0,
      "refractionFill": 0.0,
      "magnify": 1.0,
      "specular": false,
      "shadow": true
    },
    "wheel": {
      "label": "Wheel",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 0.25,
      "refraction": 0.047,
      "bevelDepth": 0.136,
      "bevelWidth": 0.076,
      "frost": 2.0,
      "refractionFill": 0.0,
      "magnify": 1.0,
      "specular": false,
      "shadow": false
    },
    "pathPill": {
      "label": "Path pill",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 0.25,
      "refraction": 0.047,
      "bevelDepth": 0.136,
      "bevelWidth": 0.076,
      "frost": 2.0,
      "refractionFill": 0.0,
      "magnify": 1.0,
      "specular": false,
      "shadow": true
    },
    "infoPill": {
      "label": "Info pill",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 0.25,
      "refraction": 0.047,
      "bevelDepth": 0.136,
      "bevelWidth": 0.076,
      "frost": 2.0,
      "refractionFill": 0.0,
      "magnify": 1.0,
      "specular": false,
      "shadow": true
    },
    "listPills": {
      "label": "List pills",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 0.25,
      "refraction": 0.047,
      "bevelDepth": 0.136,
      "bevelWidth": 0.076,
      "frost": 2.0,
      "refractionFill": 0.0,
      "magnify": 1.0,
      "specular": false,
      "shadow": true
    },
    "selectedRow": {
      "label": "Selected row",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 0.25,
      "refraction": 0.25,
      "bevelDepth": 0.01,
      "bevelWidth": 0.07,
      "frost": 4.0,
      "refractionFill": 0.3,
      "magnify": 1.0,
      "specular": false,
      "shadow": true
    }
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
    pageTransition: 60,
    pathPill: 60
  };
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
  let serverAdvancedUiDefaults = {};
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
          "pageTransition": 60,
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

  function normalizeTextMode(value){
    const k = String(value || "transparent").trim().toLowerCase();
    return (k === "black" || k === "white" || k === "engraved" || k === "contrast" || k === "transparent") ? k : "transparent";
  }

  function normalizeTextTransparency(value){
    return clampNumber(value, DEFAULT_UI_SETTINGS && DEFAULT_UI_SETTINGS.textTransparency != null ? DEFAULT_UI_SETTINGS.textTransparency : 0.68, 0, 1);
  }

  function cloneTextModes(value){
    const src = value && typeof value === "object" ? value : {};
    const out = {};
    Object.keys(DEFAULT_TEXT_MODES).forEach((key)=>{
      const inherit = key === "infoPill" && src.infoPill == null && src.pathPill != null ? src.pathPill : null;
      out[key] = normalizeTextMode(inherit || src[key] || DEFAULT_TEXT_MODES[key]);
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

  function normalizeLiquidGlassMode(name){
    const key = String(name || "clear").trim().toLowerCase();
    return (key === "dark" || key === "light" || key === "clear") ? key : "clear";
  }

  function liquidGlassModeToTint(modeName){
    const mode = normalizeLiquidGlassMode(modeName);
    if(mode === "dark") return 0;
    if(mode === "light") return 2;
    return 1;
  }

  function normalizeLiquidGlassTint(value, fallback){
    return clampNumber(value, fallback == null ? 1 : fallback, 0, 2);
  }

  function liquidGlassTintMode(value){
    const tint = normalizeLiquidGlassTint(value, 1);
    if(tint < 0.995) return "dark";
    if(tint > 1.005) return "light";
    return "clear";
  }

  function cloneGlassElementSettings(value){
    const out = {};
    const input = value && typeof value === "object" ? Object.assign({}, value) : {};
    if(!input.infoPill && input.pathPill) input.infoPill = input.pathPill;
    else if(!input.infoPill && input.nowPlayingPill) input.infoPill = input.nowPlayingPill;
    GLASS_ELEMENT_KEYS.forEach((key)=>{
      const def = DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS[key];
      const src = input[key] && typeof input[key] === "object" ? input[key] : {};
      const tintFallback = def.glassTint == null ? liquidGlassModeToTint(def.mode) : def.glassTint;
      const srcTint = src.glassTint == null ? liquidGlassModeToTint(src.mode || def.mode) : src.glassTint;
      out[key] = {
        label: def.label,
        mode: normalizeLiquidGlassMode(src.mode || liquidGlassTintMode(srcTint)),
        glassTint: normalizeLiquidGlassTint(srcTint, tintFallback),
        resolution: clampNumber(src.resolution, def.resolution, 0.25, 3),
        refraction: clampNumber(src.refraction, def.refraction, 0, 0.25),
        bevelDepth: clampNumber(src.bevelDepth, def.bevelDepth, 0, 0.35),
        bevelWidth: clampNumber(src.bevelWidth, def.bevelWidth, 0, 0.5),
        frost: clampNumber(src.frost, def.frost, 0, 5),
        magnify: clampNumber(src.magnify, def.magnify == null ? 1 : def.magnify, 0.001, 3),
        specular: src.specular === undefined ? !!def.specular : !!src.specular,
        shadow: src.shadow === undefined ? !!def.shadow : !!src.shadow,
        refractionFill: clampNumber(src.refractionFill, def.refractionFill, 0, 1)
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
    applyUiSettingsObject(out, serverAdvancedUiDefaults);
    try{
      const raw = localStorage.getItem(UI_SETTINGS_KEY) || "";
      if(raw){
        const saved = JSON.parse(raw);
        if(saved && typeof saved === "object"){
          applyUiSettingsObject(out, saved);
          return out;
        }
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
      const mode = normalizeLiquidGlassMode(localStorage.getItem("debripod_liquid_gl_mode") || "");
      if(mode) {
        out.liquidGlassElements = cloneGlassElementSettings(out.liquidGlassElements);
        GLASS_ELEMENT_KEYS.forEach((key)=>{
          out.liquidGlassElements[key].mode = mode;
          out.liquidGlassElements[key].glassTint = liquidGlassModeToTint(mode);
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
  }

  function applyServerAdvancedDefaults(defaults){
    serverAdvancedUiDefaults = defaults && typeof defaults === "object" ? defaults : {};
    if(root.uiSettings){
      root.uiSettings.serverAdvancedUiDefaults = serverAdvancedUiDefaults;
      root.uiSettings.settings = loadUiSettings();
    }
    return root.uiSettings ? root.uiSettings.settings : loadUiSettings();
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
    normalizeLiquidGlassMode,
    normalizeLiquidGlassTint,
    liquidGlassTintMode,
    liquidGlassModeToTint,
    cloneGlassElementSettings,
    applyUiSettingsObject,
    applyServerAdvancedDefaults,
    serverAdvancedUiDefaults,
    loadUiSettings,
    saveUiSettings,
    settings: loadUiSettings()
  };
})();
