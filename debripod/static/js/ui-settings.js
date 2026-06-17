(function(){
  const root = window.DebriPod = window.DebriPod || {};

  const LIQUID_GL_PRESETS = {
    "default": {refraction: 0, bevelDepth: 0.052, bevelWidth: 0.211, frost: 2, shadow: true, specular: true},
    "alien": {refraction: 0.073, bevelDepth: 0.2, bevelWidth: 0.156, frost: 2, shadow: true, specular: false},
    "pulse": {refraction: 0.03, bevelDepth: 0, bevelWidth: 0.273, frost: 0, shadow: false, specular: false},
    "frost": {refraction: 0, bevelDepth: 0.035, bevelWidth: 0.119, frost: 0.9, shadow: true, specular: true},
    "edge": {refraction: 0.047, bevelDepth: 0.136, bevelWidth: 0.076, frost: 2, shadow: true, specular: false}
  };
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
    liquidGlassPreset: "default",
    liquidGlassMode: "clear",
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

  function normalizeLiquidGlassPreset(name){
    const key = String(name || "default").trim().toLowerCase();
    return LIQUID_GL_PRESETS[key] ? key : "default";
  }

  function normalizeLiquidGlassMode(name){
    const key = String(name || "clear").trim().toLowerCase();
    return (key === "dark" || key === "light" || key === "clear") ? key : "clear";
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
          out.liquidGlassPreset = normalizeLiquidGlassPreset(saved.liquidGlassPreset);
          out.liquidGlassMode = normalizeLiquidGlassMode(saved.liquidGlassMode);
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
    try{ out.liquidGlassPreset = normalizeLiquidGlassPreset(localStorage.getItem("debripod_liquid_gl_preset") || out.liquidGlassPreset); }catch(e){}
    try{ out.liquidGlassMode = normalizeLiquidGlassMode(localStorage.getItem("debripod_liquid_gl_mode") || out.liquidGlassMode); }catch(e){}
    return out;
  }

  function saveUiSettings(settings){
    const uiSettings = settings || root.uiSettings.settings || DEFAULT_UI_SETTINGS;
    try{ localStorage.setItem(UI_SETTINGS_KEY, JSON.stringify(uiSettings)); }catch(e){}
    try{ localStorage.setItem("debripod_visualizer", uiSettings.visualizer ? "1" : "0"); }catch(e){}
    try{ localStorage.setItem("debripod_visualizer_strength", uiSettings.visualizerStrength); }catch(e){}
    try{ localStorage.setItem("debripod_visualizer_preset", uiSettings.visualizerPreset); }catch(e){}
    try{ localStorage.setItem("debripod_liquid_gl_preset", uiSettings.liquidGlassPreset); }catch(e){}
    try{ localStorage.setItem("debripod_liquid_gl_mode", uiSettings.liquidGlassMode); }catch(e){}
  }

  root.uiSettings = {
    DEFAULT_UI_SETTINGS,
    LIQUID_GL_PRESETS,
    UI_SETTINGS_KEY,
    VISUALIZER_PRESETS,
    VISUALIZER_BAND_LABELS,
    clampNumber,
    normalizeVisualizerStrength,
    normalizeVisualizerPreset,
    normalizeLiquidGlassPreset,
    normalizeLiquidGlassMode,
    loadUiSettings,
    saveUiSettings,
    settings: loadUiSettings()
  };
})();
