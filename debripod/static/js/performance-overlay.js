(function(){
  const root = window.DebriPod = window.DebriPod || {};
  let button = null;
  let overlay = null;
  let timer = 0;

  function settings(){
    try{ return root.uiSettings && root.uiSettings.settings ? root.uiSettings.settings : window.uiSettings; }catch(e){ return null; }
  }

  function save(){
    try{ if(root.uiSettings && root.uiSettings.saveUiSettings) root.uiSettings.saveUiSettings(settings()); }catch(e){}
  }

  function ensure(){
    if(!button){
      button = document.createElement("button");
      button.type = "button";
      button.className = "dpPerfButton";
      button.textContent = "P";
      button.setAttribute("aria-label", "Performance overlay");
      button.addEventListener("click", ()=>{
        const s = settings();
        if(!s) return;
        s.performanceOverlayText = !s.performanceOverlayText;
        save();
        refresh();
      });
      document.body.appendChild(button);
    }
    if(!overlay){
      overlay = document.createElement("div");
      overlay.className = "dpPerfOverlay";
      overlay.setAttribute("aria-hidden", "true");
      document.body.appendChild(overlay);
    }
  }

  function placeButton(){
    try{
      if(!button) return;
      const wheel = document.getElementById("wheel");
      const rect = wheel ? wheel.getBoundingClientRect() : null;
      const vw = window.innerWidth || 1;
      const vh = window.innerHeight || 1;
      if(!rect || !rect.width || !rect.height){
        button.style.left = Math.max(8, vw - 54) + "px";
        button.style.top = Math.max(8, vh - 54) + "px";
        return;
      }
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const radius = Math.max(rect.width, rect.height) / 2;
      const dx = vw - cx;
      const dy = vh - cy;
      const len = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const edgeX = cx + (dx / len) * radius;
      const edgeY = cy + (dy / len) * radius;
      const size = 34;
      const x = Math.max(8, Math.min(vw - size - 8, (edgeX + vw) / 2 - size / 2));
      const y = Math.max(8, Math.min(vh - size - 8, (edgeY + vh) / 2 - size / 2));
      button.style.left = x.toFixed(1) + "px";
      button.style.top = y.toFixed(1) + "px";
    }catch(e){}
  }

  function compactJson(value){
    try{ return JSON.stringify(value).slice(0, 160); }catch(e){ return ""; }
  }

  async function updateText(){
    try{
      if(!overlay || overlay.hidden) return;
      const stats = root.frameScheduler && root.frameScheduler.stats ? root.frameScheduler.stats() : {};
      const rows = root.listDiagnostics && root.listDiagnostics.rows ? root.listDiagnostics.rows() : {};
      const sync = root.clientSync && root.clientSync.getStateSummary ? root.clientSync.getStateSummary() : null;
      const timings = root.apiClient && root.apiClient.recentTimings ? root.apiClient.recentTimings().slice(-3).reverse() : [];
      let backend = null;
      try{
        const apiGet = root.apiClient && root.apiClient.apiGet;
        if(apiGet) backend = await apiGet("/api/performance", {networkOnly:true, skipMirror:true});
      }catch(e){ backend = null; }
      const renderers = root.liquidDiagnostics && root.liquidDiagnostics.renderers ? root.liquidDiagnostics.renderers() : [];
      const version = (backend && backend.version) || window.DEBRIPOD_APP_INFO || {};
      overlay.textContent = [
        "fps " + Math.round(Number(stats.fps || 0)) + " long " + Number(stats.longFrames || 0),
        "rows " + Number(rows.visible || 0) + "/" + Number(rows.total || 0) + (rows.virtualized ? " virtual" : ""),
        "liquid " + renderers.map(r=>String(r.key || "?") + ":" + (r.visible ? "on" : "off") + " " + Number(r.visibleLensCount || 0) + " lens " + Math.round(Number(r.averageRenderSubmissionMs || 0) * 10) / 10 + "ms " + Number(r.sourceRefreshCount || 0) + " src " + Number(r.frostSamples || 0) + " frost " + Number(r.renderScale || 1) + "x").join(" | "),
        sync ? ("sync " + compactJson(sync)) : "",
        timings.map(t=>String(t.method || "GET") + " " + String(t.status || "") + " " + Math.round(Number(t.ms || 0)) + "ms").join(" | "),
        "version " + String(version.display || version.display_version || "vdev") + " " + String(version.short_commit || "")
      ].filter(Boolean).join("\n");
      placeOverlay();
    }catch(e){}
  }

  function placeOverlay(){
    try{
      if(!overlay || overlay.hidden) return;
      const wheel = document.getElementById("wheel");
      const wr = wheel ? wheel.getBoundingClientRect() : null;
      const br = button ? button.getBoundingClientRect() : null;
      const vw = window.innerWidth || 1;
      const vh = window.innerHeight || 1;
      const width = Math.min(360, Math.max(220, vw - 24));
      overlay.style.width = width + "px";
      let x = 12;
      let y = 12;
      if(wr){
        const rightSpace = vw - wr.right - 16;
        const leftSpace = wr.left - 16;
        if(rightSpace >= width) x = wr.right + 8;
        else if(leftSpace >= width) x = wr.left - width - 8;
        else x = Math.max(12, Math.min(vw - width - 12, (vw - width) / 2));
        y = Math.max(12, Math.min(vh - 170, wr.top));
      }
      if(br && Math.abs(x - br.left) < 48 && Math.abs(y - br.top) < 48) y = Math.max(12, br.top - 170);
      overlay.style.left = x.toFixed(1) + "px";
      overlay.style.top = y.toFixed(1) + "px";
    }catch(e){}
  }

  function refresh(){
    ensure();
    const s = settings() || {};
    const buttonOn = !!s.performanceOverlayButton;
    const textOn = !!(s.performanceOverlayButton && s.performanceOverlayText);
    button.hidden = !buttonOn;
    overlay.hidden = !textOn;
    button.style.display = buttonOn ? "block" : "none";
    overlay.style.display = textOn ? "block" : "none";
    overlay.setAttribute("aria-hidden", overlay.hidden ? "true" : "false");
    placeButton();
    if(timer) clearInterval(timer);
    timer = 0;
    if(!overlay.hidden){
      updateText();
      timer = setInterval(updateText, 1000);
    }
  }

  window.addEventListener("resize", refresh, {passive:true});
  window.addEventListener("orientationchange", refresh, {passive:true});
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", refresh, {once:true});
  else refresh();
  root.performanceOverlay = {refresh};
})();
