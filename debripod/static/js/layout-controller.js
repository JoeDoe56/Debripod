/* Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818 */
(function(root, factory){
  const api = factory();
  if(typeof module === "object" && module.exports) module.exports = api;
  if(root){
    root.DebriPod = root.DebriPod || {};
    root.DebriPod.layoutControllerPure = api;
    root.DebriPod.layoutController = api.createBrowserController(root);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function(){
  "use strict";
  function intersects(a, b, tolerance){
    if(!a || !b) return false;
    const t = Number(tolerance == null ? 1 : tolerance);
    return Math.min(a.right, b.right) - Math.max(a.left, b.left) > t &&
      Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > t;
  }
  function outside(rect, viewport, padding, tolerance){
    if(!rect || !viewport) return false;
    const p = Number(padding || 0);
    const t = Number(tolerance == null ? 1 : tolerance);
    return rect.left - p < viewport.left - t || rect.top - p < viewport.top - t ||
      rect.right + p > viewport.right + t || rect.bottom + p > viewport.bottom + t;
  }
  function normalWheelWellLayout(viewport, pathPill, infoPillHeight, gap){
    const viewportWidth = Math.max(0, Number(viewport && viewport.width || 0));
    const pathBottom = pathPill ? Number(pathPill.bottom) : Number(viewport && viewport.top || 0);
    const screenTop = pathBottom + gap;
    const screenSize = Math.max(0, viewportWidth - (gap * 2));
    const infoBottom = screenTop + screenSize + gap + Number(infoPillHeight || 0);
    const wheelWellSize = Number(viewport && viewport.bottom || 0) - infoBottom;
    return {
      wheelWellSize:wheelWellSize,
      screenTop:screenTop,
      infoBottom:infoBottom,
      screenHeight:screenSize,
      fits:screenSize > 0 && wheelWellSize >= 0,
    };
  }
  function chooseLayout(geometry, tolerance){
    const g = geometry || {};
    const padding = Number(g.padding || 0);
    if(intersects(g.wheel, g.screen, tolerance)) return "layoutExpanded";
    if(intersects(g.wheel, g.pathPill, tolerance) || intersects(g.wheel, g.infoPill, tolerance)) return "layoutExpanded";
    // The screen and centered wheel may meet the side edges on narrow
    // viewports. Any actual overlap or viewport overflow still expands.
    if([g.screen, g.wheel].some(rect=>outside(rect, g.viewport, 0, tolerance)) ||
      [g.pathPill, g.infoPill].some(rect=>outside(rect, g.viewport, padding, tolerance))) return "layoutExpanded";
    return "layoutWheel";
  }
  function mediaBox(kind, available){
    const width = Math.max(0, Number(available && available.width || 0));
    const height = Math.max(0, Number(available && available.height || 0));
    if(String(kind || "").toLowerCase() === "video") return {width:width, height:height};
    const side = Math.min(width, height);
    return {width:side, height:side};
  }
  function stableViewportChange(previous, candidate, signals){
    const next = candidate || previous || {width:0, height:0};
    if(!previous || (signals && signals.force)) return next;
    if(signals && (signals.zoomed || signals.keyboardOpen)) return previous;
    if(signals && signals.touchViewport && Number(previous.width) === Number(next.width)) return previous;
    return next;
  }
  function createBrowserController(win){
    if(!win || !win.document) return null;
    const doc = win.document;
    let frame = 0;
    let generation = 0;
    let stableViewport = null;
    function viewportSize(){
      const root = doc.documentElement;
      return {
        width:Math.max(1, Number(root && root.clientWidth || win.innerWidth || 1)),
        height:Math.max(1, Number(root && root.clientHeight || win.innerHeight || 1))
      };
    }
    function editableFocused(){
      const active = doc.activeElement;
      if(!active || !active.matches) return false;
      return active.matches("input, textarea, select, [contenteditable='true']");
    }
    function captureStableViewport(force){
      const candidate = viewportSize();
      const visual = win.visualViewport;
      const zoomed = !!(visual && Math.abs(Number(visual.scale || 1) - 1) > 0.01);
      const keyboardOpen = !!(
        editableFocused() && stableViewport &&
        candidate.height < Number(stableViewport.height || candidate.height) * 0.9
      );
      stableViewport = stableViewportChange(stableViewport, candidate, {
        force:!!force,
        zoomed:zoomed,
        keyboardOpen:keyboardOpen,
        touchViewport:!!(win.navigator && Number(win.navigator.maxTouchPoints || 0) > 0)
      });
      doc.documentElement.style.setProperty("--stable-viewport-width", stableViewport.width + "px");
      doc.documentElement.style.setProperty("--stable-viewport-height", stableViewport.height + "px");
      doc.documentElement.classList.toggle("dpStableShortViewport", stableViewport.height <= 760);
      return !(zoomed || keyboardOpen);
    }
    function rectFor(element){
      if(!element) return null;
      return element.getBoundingClientRect();
    }
    function viewportRect(){
      // Pinch zoom and the software keyboard change the visual viewport. The
      // controls intentionally remain laid out against this stable viewport.
      const current = stableViewport || viewportSize();
      const width = current.width;
      const height = current.height;
      return {left:0, top:0, right:width, bottom:height, width:width, height:height};
    }
    function measure(){
      const stage = doc.querySelector(".ipodStage");
      const screen = doc.getElementById("ipodScreen");
      const wheelZone = doc.getElementById("wheelZone");
      const wheel = doc.getElementById("wheel");
      const path = doc.getElementById("libHeader");
      const info = doc.getElementById("infoPill");
      if(!stage || !screen || !wheelZone || !wheel) return null;
      stage.classList.add("layoutMeasuring");
      stage.classList.remove("layoutWheel", "layoutExpanded");
      wheelZone.style.removeProperty("height");
      wheelZone.style.removeProperty("min-height");
      wheelZone.style.removeProperty("flex");
      [screen, wheelZone, wheel, path, info].forEach(element=>{ if(element) element.style.removeProperty("transform"); });
      const gap = parseFloat(win.getComputedStyle(stage).getPropertyValue("--stageGap")) || 8;
      const pathRect = rectFor(path);
      const infoRect = rectFor(info);
      const normalLayout = normalWheelWellLayout(viewportRect(), pathRect, infoRect && infoRect.height, gap);
      stage.style.setProperty("--normal-wheel-well-size", Math.max(0, normalLayout.wheelWellSize) + "px");
      stage.style.setProperty("--normal-screen-height", Math.max(0, normalLayout.screenHeight) + "px");
      doc.documentElement.style.setProperty("--layout-screen-top", normalLayout.screenTop + "px");
      const result = {stage:stage, mode:normalLayout.fits && chooseLayout({
        // Pill visibility is animation state, not layout state. Always reserve
        // and collide against their geometry, including while they are hidden.
        wheel:rectFor(wheel), screen:rectFor(screen), pathPill:pathRect, infoPill:infoRect,
        viewport:viewportRect(), padding:gap
      }, 1) ? "layoutWheel" : "layoutExpanded"};
      stage.classList.remove("layoutMeasuring");
      return result;
    }
    function setMode(result){
      if(!result) return;
      result.stage.classList.toggle("layoutWheel", result.mode === "layoutWheel");
      result.stage.classList.toggle("layoutExpanded", result.mode === "layoutExpanded");
    }
    function apply(){
      frame = 0;
      const token = ++generation;
      setMode(measure());
      win.requestAnimationFrame(()=>{
        if(token !== generation) return;
        setMode(measure());
        win.requestAnimationFrame(()=>{
          if(token !== generation) return;
          try{ if(typeof win.scheduleLiquidGlassSnapshot === "function") win.scheduleLiquidGlassSnapshot("layout stable", true); }catch(_error){}
        });
      });
    }
    function schedule(){
      generation += 1;
      if(frame) win.cancelAnimationFrame(frame);
      frame = win.requestAnimationFrame(apply);
    }
    function start(){
      captureStableViewport(true);
      const targets = [doc.querySelector(".ipodStage"), doc.getElementById("ipodScreen"), doc.getElementById("wheelZone"), doc.getElementById("wheel"), doc.getElementById("libHeader"), doc.getElementById("infoPill")].filter(Boolean);
      if("ResizeObserver" in win){
        const observer = new ResizeObserver(schedule);
        targets.forEach(target=>observer.observe(target));
      }
      win.addEventListener("resize", ()=>{
        if(captureStableViewport(false)) schedule();
      });
      win.addEventListener("orientationchange", ()=>{
        win.setTimeout(()=>{
          captureStableViewport(true);
          schedule();
        }, 120);
      });
      doc.addEventListener("fullscreenchange", ()=>{
        captureStableViewport(true);
        schedule();
        // Mobile browsers can finish resizing after fullscreenchange. Read
        // the settled layout viewport again on the following frame.
        win.requestAnimationFrame(()=>{
          captureStableViewport(true);
          schedule();
        });
      });
      schedule();
    }
    if(doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start, {once:true});
    else start();
    return {schedule:schedule, chooseLayout:chooseLayout, mediaBox:mediaBox, stableViewportChange:stableViewportChange};
  }
  return {chooseLayout:chooseLayout, normalWheelWellLayout:normalWheelWellLayout, mediaBox:mediaBox, stableViewportChange:stableViewportChange, createBrowserController:createBrowserController};
});
