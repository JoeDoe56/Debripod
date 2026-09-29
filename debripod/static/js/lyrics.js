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
      panel.append(status, content);
      host.appendChild(panel);
      return panel;
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
      content.replaceChildren();
      mode = data && data.instrumental ? "instrumental" : lines.length ? "synced" : data && data.plainLyrics ? "plain" : "missing";
      panel.dataset.mode = mode;
      showMessage(mode === "instrumental" ? "Instrumental" : mode === "missing" ? "No lyrics found for this recording" : "");
      const values = mode === "synced" ? lines : mode === "plain" ? String(data.plainLyrics).split(/\r?\n/).map(text => ({text})) : [];
      values.forEach(line => {
        const node = env.document.createElement("p");
        node.className = "npLyricLine";
        node.textContent = line.text || "\u00a0";
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
    function updatePosition(){
      if(!progress || mode !== "synced" || !content) return;
      const media = typeof env.wheelMedia === "function" ? env.wheelMedia() : null;
      const gapless = typeof env.gaplessPlaybackSnapshot === "function" ? env.gaplessPlaybackSnapshot() : null;
      const position = gapless ? Number(gapless.position) : Number(media && media.currentTime);
      const next = activeLine(lines, Number.isFinite(position) ? position : 0);
      if(next === active) return;
      active = next;
      Array.from(content.children).forEach((node, index) => {
        node.classList.toggle("isActive", index === next);
        node.classList.toggle("isPast", index < next);
        if(index === next) node.setAttribute("aria-current", "true");
        else node.removeAttribute("aria-current");
      });
      const node = content.children[Math.max(0, next)];
      if(node){
        const top = Math.max(0, node.offsetTop - content.offsetTop - content.clientHeight * .42 + node.clientHeight / 2);
        const reduced = env.matchMedia && env.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if(content.scrollTo) content.scrollTo({top, behavior: reduced ? "instant" : "smooth"});
        else content.scrollTop = top;
      }
    }
    function tick(){
      if(!progress) return;
      const host = env.document.getElementById("nowPlaying");
      if(!host || host.style.display !== "block"){ setOpen(false); return; }
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
      if(progress) load(currentMetadata(), false);
    }
    return {setProgress, setOpen, isOpen: () => progress > .5, trackChanged, updatePosition};
  }
  return {parseLrc, activeLine, trackIdentity, createController};
});
