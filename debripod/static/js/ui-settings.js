(function(){
  const root = window.DebriPod = window.DebriPod || {};

  // GLASS_DEFAULTS_BEGIN
  const DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS = {
    "libraryList": {
      "label": "Library list",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 1.0,
      "refraction": 0.047,
      "bevelDepth": 0.136,
      "bevelWidth": 0.076,
      "frost": 2.0,
      "refractionFill": 1.0,
      "magnify": 1.0,
      "specular": false,
      "shadow": false
    },
    "wheel": {
      "label": "Wheel",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 1.0,
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
      "resolution": 1.0,
      "refraction": 0.047,
      "bevelDepth": 0.136,
      "bevelWidth": 0.076,
      "frost": 2.0,
      "refractionFill": 0.0,
      "magnify": 1.0,
      "specular": false,
      "shadow": false
    },
    "nowPlayingPill": {
      "label": "Now playing pill",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 1.0,
      "refraction": 0.047,
      "bevelDepth": 0.136,
      "bevelWidth": 0.076,
      "frost": 2.0,
      "refractionFill": 0.0,
      "magnify": 1.0,
      "specular": false,
      "shadow": false
    },
    "listPills": {
      "label": "List pills",
      "mode": "clear",
      "glassTint": 1.0,
      "resolution": 1.0,
      "refraction": 0.047,
      "bevelDepth": 0.136,
      "bevelWidth": 0.076,
      "frost": 2.0,
      "refractionFill": 0.0,
      "magnify": 1.0,
      "specular": false,
      "shadow": false
    }
  };
  // GLASS_DEFAULTS_END
  const GLASS_ELEMENT_KEYS = ["libraryList", "wheel", "pathPill", "nowPlayingPill", "listPills"];
  const UI_SETTINGS_KEY = "debripod_ui_settings";
  const VISUALIZER_PRESETS = {
    album: {label: "Orbit", style: "orbit", motion: 1},
    aurora: {label: "Aurora", style: "ribbon", motion: 0.82},
    ember: {label: "Ember", style: "bloom", motion: 0.72},
    prism: {label: "Prism", style: "prism", motion: 1.18},
    sonar: {label: "Sonar", style: "rings", motion: 0.94},
    cascade: {label: "Cascade", style: "cascade", motion: 0.76},
    nova: {label: "Nova", style: "nova", motion: 1.08},
    lattice: {label: "Lattice", style: "lattice", motion: 0.88}
  };
  const VISUALIZER_BAND_LABELS = ["low low", "low high", "low mids", "mids", "upper mids", "high low", "high high"];
  const DEFAULT_UI_SETTINGS = {
    visualizer: false,
    visualizerStrength: "medium",
    visualizerPreset: "album",
    liquidGlassElements: cloneGlassElementSettings(DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS),
    centerBounceAmount: 0.075,
    centerBounceDuration: 240,
    centerBounceOvershoot: 0.9,
    wheelClickTiltAmount: 0.5,
    wheelTiltRampDuration: 90,
    wheelTiltReleaseDuration: 360,
    infoPillDarkMultiplier: 1,
    infoPillLightMultiplier: 1
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

  function normalizeVisualizerPreset(value){
    const k = String(value || "album").trim().toLowerCase();
    return VISUALIZER_PRESETS[k] ? k : "album";
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
    const input = value && typeof value === "object" ? value : {};
    GLASS_ELEMENT_KEYS.forEach((key)=>{
      const def = DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS[key];
      const src = input[key] && typeof input[key] === "object" ? input[key] : {};
      const tintFallback = def.glassTint == null ? liquidGlassModeToTint(def.mode) : def.glassTint;
      const srcTint = src.glassTint == null ? liquidGlassModeToTint(src.mode || def.mode) : src.glassTint;
      out[key] = {
        label: def.label,
        mode: normalizeLiquidGlassMode(src.mode || def.mode),
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
      out[key].mode = liquidGlassTintMode(out[key].glassTint);
    });
    return out;
  }

  function loadUiSettings(){
    const out = Object.assign({}, DEFAULT_UI_SETTINGS);
    try{
      const raw = localStorage.getItem(UI_SETTINGS_KEY) || "";
      if(raw){
        const saved = JSON.parse(raw);
        if(saved && typeof saved === "object"){
          out.visualizer = !!saved.visualizer;
          out.visualizerStrength = normalizeVisualizerStrength(saved.visualizerStrength);
          out.visualizerPreset = normalizeVisualizerPreset(saved.visualizerPreset);
          out.liquidGlassElements = cloneGlassElementSettings(saved.liquidGlassElements);
          out.centerBounceAmount = clampNumber(saved.centerBounceAmount, out.centerBounceAmount, 0, 0.3);
          out.centerBounceDuration = clampNumber(saved.centerBounceDuration, out.centerBounceDuration, 0, 1000);
          out.centerBounceOvershoot = clampNumber(saved.centerBounceOvershoot, out.centerBounceOvershoot, 0, 1.4);
          out.wheelClickTiltAmount = clampNumber(saved.wheelClickTiltAmount, out.wheelClickTiltAmount, 0, 1);
          out.wheelTiltRampDuration = clampNumber(saved.wheelTiltRampDuration, out.wheelTiltRampDuration, 0, 1000);
          out.wheelTiltReleaseDuration = clampNumber(saved.wheelTiltReleaseDuration, out.wheelTiltReleaseDuration, 0, 1200);
          out.infoPillDarkMultiplier = clampNumber(saved.infoPillDarkMultiplier, out.infoPillDarkMultiplier, 0, 4);
          out.infoPillLightMultiplier = clampNumber(saved.infoPillLightMultiplier, out.infoPillLightMultiplier, 0, 4);
          return out;
        }
      }
    }catch(e){}
    try{ out.visualizer = (localStorage.getItem("debripod_visualizer") || "") === "1"; }catch(e){}
    try{ out.visualizerStrength = normalizeVisualizerStrength(localStorage.getItem("debripod_visualizer_strength") || out.visualizerStrength); }catch(e){}
    try{ out.visualizerPreset = normalizeVisualizerPreset(localStorage.getItem("debripod_visualizer_preset") || out.visualizerPreset); }catch(e){}
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
    try{ localStorage.setItem("debripod_visualizer_strength", uiSettings.visualizerStrength); }catch(e){}
    try{ localStorage.setItem("debripod_visualizer_preset", uiSettings.visualizerPreset); }catch(e){}
    try{ uiSettings.liquidGlassElements = cloneGlassElementSettings(uiSettings.liquidGlassElements); }catch(e){}
  }

  root.uiSettings = {
    DEFAULT_UI_SETTINGS,
    DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS,
    GLASS_ELEMENT_KEYS,
    UI_SETTINGS_KEY,
    VISUALIZER_PRESETS,
    VISUALIZER_BAND_LABELS,
    clampNumber,
    normalizeVisualizerStrength,
    normalizeVisualizerPreset,
    normalizeLiquidGlassMode,
    normalizeLiquidGlassTint,
    liquidGlassTintMode,
    liquidGlassModeToTint,
    cloneGlassElementSettings,
    loadUiSettings,
    saveUiSettings,
    settings: loadUiSettings()
  };
})();
