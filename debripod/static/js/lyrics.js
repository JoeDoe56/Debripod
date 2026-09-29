(function(root, factory){
  const api = factory();
  if(typeof module === "object" && module.exports) module.exports = api;
  if(root.document){
    const ns = root.DebriPod = root.DebriPod || {};
    ns.lyrics = api.createController(root);
  }
})(typeof window !== "undefined" ? window : globalThis, function(){
  "use strict";
  const clamp = value => Math.max(0, Math.min(1, Number(value) || 0));

  function parseLrc(text){
    const source = String(text || "");
    const offset = Number((source.match(/\[offset:([+-]?\d+)\]/i) || [])[1] || 0) / 1000;
    const lines = [];
    source.split(/\r?\n/).forEach(line => {
      const timestamps = [...line.matchAll(/\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]/g)];
      const words = line.replace(/\[[^\]]*\]/g, "").trim();
      for(const stamp of timestamps){
        const fraction = Number("0." + (stamp[3] || "0"));
        lines.push({time: Math.max(0, Number(stamp[1]) * 60 + Number(stamp[2]) + fraction + offset), text: words});
      }
    });
    return lines.sort((a, b) => a.time - b.time);
  }

  function activeLine(lines, seconds){
    let lo = 0, hi = lines.length;
    while(lo < hi){
      const mid = (lo + hi) >>> 1;
      if(lines[mid].time <= seconds) lo = mid + 1;
      else hi = mid;
    }
    return lo - 1;
  }

  function trackIdentity(meta){
    return [meta.title, meta.artist, meta.album, Math.round(Number(meta.duration) || 0)].map(v => String(v || "")).join("\u001f");
  }

  function createController(env){
    let progress = 0, panel, content, status, timer, hideTimer, key = "", generation = 0, abort;
    let lines = [], active = -2, mode = "missing", metadata = {};
    let manualLock = false, userScrollIntent = false, userGestureUntil = 0, scrollSettleTimer = null;
    let autoScrollTarget = null;
    let blurArt = null, blurArtSource = "";
    const cache = new Map();
    function ensure(){
      if(panel) return panel;
      const host = env.document.getElementById("nowPlaying");
      if(!host) return null;
      panel = env.document.createElement("section");
      panel.className = "npLyrics";
      panel.hidden = true;
      panel.setAttribute("aria-label", "Lyrics from LRCLIB");
      panel.setAttribute("data-liquid-ignore", "");
      status = env.document.createElement("div");
      status.className = "npLyricsStatus";
      status.setAttribute("role", "status");
      content = env.document.createElement("div");
      content.className = "npLyricsLines";
      content.tabIndex = 0;
      content.setAttribute("aria-label", "Song lyrics");
      const blurShell = env.document.createElement("div");
      blurShell.className = "npLyricsBlur";
      blurArt = env.document.createElement("img");
      blurArt.className = "npLyricsBlurArt";
      blurArt.setAttribute("alt", "");
      blurArt.setAttribute("aria-hidden", "true");
      blurArt.hidden = true;
      blurShell.appendChild(blurArt);
      // Keep status/content as the first two children for existing control
      // consumers; the visual blur compositor sits behind them.
      panel.append(status, content, blurShell);
      host.appendChild(panel);
      if(typeof content.addEventListener === "function"){
        content.addEventListener("scroll", onLyricsScroll, {passive:true});
        ["wheel", "touchstart", "pointerdown"].forEach(type => content.addEventListener(type, markUserScrollIntent, {passive:true}));
      }
      return panel;
    }
    function syncArtwork(){
      if(!blurArt) return;
      const src = typeof env.currentNowPlayingArtSrc === "function" ? env.currentNowPlayingArtSrc() : "";
      if(src === blurArtSource) return;
      blurArtSource = src;
      blurArt.hidden = !src;
      if(src) blurArt.setAttribute("src", src);
      else blurArt.removeAttribute("src");
    }
    function showMessage(value){
      if(!ensure()) return;
      status.textContent = value;
      status.hidden = !value;
    }
    function render(data){
      if(!ensure()) return;
      lines = parseLrc(data && data.syncedLyrics);
      active = -2;
      if(scrollSettleTimer) env.clearTimeout(scrollSettleTimer);
      scrollSettleTimer = null;
      manualLock = false;
      userScrollIntent = false;
      userGestureUntil = 0;
      autoScrollTarget = null;
      content.replaceChildren();
      mode = data && data.instrumental ? "instrumental" : lines.length ? "synced" : data && data.plainLyrics ? "plain" : "missing";
      panel.dataset.mode = mode;
      showMessage(mode === "instrumental" ? "Instrumental" : mode === "missing" ? "No lyrics found for this recording" : "");
      const values = mode === "synced" ? lines : mode === "plain" ? String(data.plainLyrics).split(/\r?\n/).map(text => ({text})) : [];
      values.forEach(line => {
        const node = env.document.createElement("p");
        node.className = "npLyricLine";
        node.textContent = line.text || "\u00a0";
        if(line.time != null){
          node.dataset.lyricTime = String(line.time);
          node.tabIndex = 0;
          node.setAttribute("role", "button");
          if(typeof node.addEventListener === "function"){
            node.addEventListener("click", (event) => {
              if(event && typeof event.stopPropagation === "function") event.stopPropagation();
              seekLine(line.time);
            });
            node.addEventListener("keydown", (event) => {
              if(!event || (event.key !== "Enter" && event.key !== " ")) return;
              if(typeof event.preventDefault === "function") event.preventDefault();
              if(typeof event.stopPropagation === "function") event.stopPropagation();
              seekLine(line.time);
            });
          }
        }
        content.appendChild(node);
      });
      content.scrollTop = 0;
      updatePosition();
    }
    async function load(meta, force){
      const nextKey = trackIdentity(meta);
      metadata = {...meta};
      if(!force && nextKey === key) return;
      key = nextKey;
      const current = ++generation;
      if(abort) abort.abort();
      abort = null;
      lines = [];
      if(scrollSettleTimer) env.clearTimeout(scrollSettleTimer);
      scrollSettleTimer = null;
      manualLock = false;
      userScrollIntent = false;
      userGestureUntil = 0;
      autoScrollTarget = null;
      if(!ensure()) return;
      content.replaceChildren();
      if(!meta.title || !meta.artist){ render(null); return; }
      if(cache.has(key)){ render(cache.get(key)); return; }
      showMessage("Finding lyrics…");
      mode = "loading";
      abort = new env.AbortController();
      const controller = abort;
      const timeout = env.setTimeout(() => controller.abort(), 15000);
      const params = new URLSearchParams({track_name: meta.title, artist_name: meta.artist, album_name: meta.album || "", duration: String(Number(meta.duration) || 0)});
      try{
        const response = await env.fetch("/api/lyrics?" + params, {signal: controller.signal, headers: {Accept: "application/json"}});
        if(!response.ok) throw new Error("Lyrics unavailable");
        const payload = await response.json();
        if(!payload.ok) throw new Error("Lyrics unavailable");
        if(current !== generation) return;
        if(cache.size >= 48) cache.delete(cache.keys().next().value);
        cache.set(key, payload.lyrics || null);
        render(payload.lyrics);
      }catch(error){
        if(current !== generation) return;
        mode = "error";
        showMessage("Lyrics unavailable · close and reopen to retry");
      }finally{
        env.clearTimeout(timeout);
      }
    }
    function currentMetadata(){
      const state = env.state || {};
      const meta = state.nowMeta || metadata;
      const media = typeof env.wheelMedia === "function" ? env.wheelMedia() : null;
      return {...meta, duration: Number(meta.duration) || (media && Number.isFinite(media.duration) ? media.duration : 0)};
    }
    function playbackPosition(){
      const media = typeof env.wheelMedia === "function" ? env.wheelMedia() : null;
      const gapless = typeof env.gaplessPlaybackSnapshot === "function" ? env.gaplessPlaybackSnapshot() : null;
      const position = gapless ? Number(gapless.position) : Number(media && media.currentTime);
      return Number.isFinite(position) ? position : 0;
    }
    function activeNode(){ return content && active >= 0 ? content.children[active] : null; }
    function lineIsVisible(node){
      if(!node || !content) return false;
      const top = Number(node.offsetTop || 0);
      const height = Math.max(1, Number(node.offsetHeight || 1));
      const scroll = Number(content.scrollTop || 0);
      const viewport = Math.max(1, Number(content.clientHeight || 1));
      return top + height >= scroll + viewport * .08 && top <= scroll + viewport * .92;
    }
    function recenterActive(behavior){
      const node = activeNode();
      if(!node || !content) return;
      userScrollIntent = false;
      userGestureUntil = 0;
      const viewport = Math.max(1, Number(content.clientHeight || 1));
      const top = Math.max(0, Number(node.offsetTop || 0) - viewport * .42 + Math.max(1, Number(node.offsetHeight || 1)) / 2);
      autoScrollTarget = top;
      if(typeof content.scrollTo === "function"){
        const reduced = env.matchMedia && env.matchMedia("(prefers-reduced-motion: reduce)").matches;
        content.scrollTo({top, behavior: reduced ? "instant" : (behavior || "smooth")});
      }else content.scrollTop = top;
    }
    function markUserScrollIntent(){
      userScrollIntent = true;
      userGestureUntil = Date.now() + 500;
      const node = activeNode();
      if(node) manualLock = !lineIsVisible(node);
    }
    function onLyricsScroll(){
      const now = Date.now();
      const userInitiated = userScrollIntent || now <= userGestureUntil;
      if(autoScrollTarget != null && !userInitiated) return;
      if(userInitiated){
        autoScrollTarget = null;
        const node = activeNode();
        if(node) manualLock = !lineIsVisible(node);
      }else if(autoScrollTarget == null){
        // Native momentum can outlive the initial wheel/touch event.
        const node = activeNode();
        if(node) manualLock = !lineIsVisible(node);
      }
      userScrollIntent = false;
      if(scrollSettleTimer) env.clearTimeout(scrollSettleTimer);
      scrollSettleTimer = env.setTimeout(() => {
        scrollSettleTimer = null;
        const node = activeNode();
        if(node && lineIsVisible(node)){
          manualLock = false;
          recenterActive("smooth");
        }else if(node){
          manualLock = true;
        }
      }, 180);
    }
    function seekLine(time){
      const target = Math.max(0, Number(time) || 0);
      let handled = false;
      try{
        const gapless = env.DebriPod && env.DebriPod.gaplessAudio;
        if(gapless && typeof gapless.seek === "function") handled = gapless.seek(target) !== false;
      }catch(e){}
      if(!handled){
        try{
          const media = typeof env.wheelMedia === "function" ? env.wheelMedia() : null;
          if(media){ media.currentTime = target; handled = true; }
        }catch(e){}
      }
      manualLock = false;
      active = activeLine(lines, target);
      if(content) Array.from(content.children).forEach((node, index) => {
        node.classList.toggle("isActive", index === active);
        node.classList.toggle("isPast", index < active);
        if(index === active) node.setAttribute("aria-current", "true");
        else node.removeAttribute("aria-current");
      });
      recenterActive("smooth");
      return handled;
    }
    function updatePosition(){
      if(!progress || mode !== "synced" || !content) return;
      const next = activeLine(lines, playbackPosition());
      const changed = next !== active;
      if(!changed) return;
      active = next;
      Array.from(content.children).forEach((node, index) => {
        node.classList.toggle("isActive", index === next);
        node.classList.toggle("isPast", index < next);
        if(index === next) node.setAttribute("aria-current", "true");
        else node.removeAttribute("aria-current");
      });
      const node = content.children[Math.max(0, next)];
      if(node && changed && !manualLock && !scrollSettleTimer) recenterActive("smooth");
    }
    function tick(){
      if(!progress) return;
      const host = env.document.getElementById("nowPlaying");
      if(!host || host.style.display !== "block"){ setOpen(false); return; }
      syncArtwork();
      load(currentMetadata(), false);
      updatePosition();
    }
    function setProgress(value, options){
      const wasOpen = progress > 0;
      progress = clamp(value);
      if(!ensure()) return;
      env.clearTimeout(hideTimer);
      const animate = !!(options && options.animate);
      panel.dataset.dragging = String(!animate);
      if(progress > 0) panel.hidden = false;
      else if(animate) hideTimer = env.setTimeout(() => { if(!progress) panel.hidden = true; }, 200);
      else panel.hidden = true;
      panel.style.setProperty("--lyrics-progress", progress);
      panel.setAttribute("aria-hidden", String(progress === 0));
      if(progress && !wasOpen){
        syncArtwork();
        load(currentMetadata(), mode === "error");
        timer = env.setInterval(tick, 100);
      }else if(!progress && wasOpen){
        env.clearInterval(timer);
        timer = null;
      }
    }
    function setOpen(value){ setProgress(value ? 1 : 0, {animate:true}); }
    function trackChanged(meta){
      metadata = {...meta};
      if(scrollSettleTimer) env.clearTimeout(scrollSettleTimer);
      scrollSettleTimer = null;
      manualLock = false;
      userScrollIntent = false;
      userGestureUntil = 0;
      autoScrollTarget = null;
      if(progress) load(currentMetadata(), false);
    }
    return {setProgress, setOpen, isOpen: () => progress > .5, trackChanged, updatePosition, seekLine};
  }
  return {parseLrc, activeLine, trackIdentity, createController};
});
