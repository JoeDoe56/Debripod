/* DebriPod's instances of sfgl's reusable pieces: the frame scheduler, the
 * light (device tilt with the pointer as the alternative), the motion clock,
 * content transitions and the row-text underlay. Loaded after ui-settings.js
 * and before anything that uses them; the glass itself starts in
 * liquid-glue.js. */
(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const SF = window.SFGL;
  if(!SF){
    try{ document.documentElement.classList.add("liquidGlassFallback"); }catch(e){}
    return;
  }
  const appSettings = ()=> (root.uiSettings && root.uiSettings.settings) || {};
  const deviceUserId = ()=> String(window.DEBRIPOD_DEVICE_SETTINGS_USER_ID || "anonymous").trim() || "anonymous";

  root.frameScheduler = SF.createScheduler();

  root.glassLighting = SF.createLighting({
    fps: ()=> appSettings().glassInteractionFps,
    multiplier: ()=> appSettings().glassMotionEffectMultiplier,
    storage: {
      getItem: (key)=>{ try{ return window.localStorage ? window.localStorage.getItem(key) : null; }catch(e){ return null; } },
      setItem: (key, value)=>{ try{ if(window.localStorage) window.localStorage.setItem(key, value); }catch(e){} }
    },
    storageKey: ()=> "debripod_glass_orientation_permission:v1:" + deviceUserId(),
    // A light change only needs a draw; geometry is unchanged.
    onChange: ()=>{ root.frameScheduler.mark({render:true, keepAlive:true}); }
  });

  window.LiquidGlassMotion = SF.motion;

  // Below the full WebGL tiers, text changes fade without the blur and scale.
  const transitionEffects = ()=>{
    try{
      const tier = root.glass && root.glass.instance ? root.glass.instance.tier() : null;
      return tier && (!tier.webgl || tier.name === "lite") ? "opacity" : "full";
    }catch(e){ return "full"; }
  };
  const transitions = SF.createContentTransitions({root: document.body, effects: transitionEffects});
  window.LiquidGlassOverlays = transitions;
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", ()=> transitions.start(), {once:true});
  else transitions.start();

  root.rowRefraction = SF.createTextUnderlay({
    container: ()=> document.getElementById("libList"),
    textSelector: ".ipodItem:not(.sel) .glassText, .ipodItem:not(.sel) .dpRowPrimary, .ipodItem:not(.sel) .dpRowSecondary",
    sampleRowSelector: ".dpStandardRow, .ipodItem",
    fadeHostSelector: ".dpRowText, .hScrollTextScrollable",
    fadeVariable: "--path-text-fade",
    fadeDefaultPx: 18,
    leftFade: (host)=> !!(host.dataset && host.dataset.scrollAway === "true")
  });
})();
