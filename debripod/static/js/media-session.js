  function swapAudios(){
    activeAudio = audioMain;
    standbyAudio = null;
  }

  function canMediaSession(){
    return !!(navigator.mediaSession && typeof MediaMetadata === "function");
  }

  function ensurePlaybackAudioSession(){
    try{
      if("audioSession" in navigator && navigator.audioSession){
        if(navigator.audioSession.type !== "playback") navigator.audioSession.type = "playback";
      }
    }catch(e){}
  }

  function mediaSessionHasPrev(){
    try{
      const queue = window.DebriPod && DebriPod.playbackQueue;
      return !!(queue && queue.state.index > 0);
    }catch(e){ return false; }
  }

  function mediaSessionHasNext(){
    try{
      const queue = window.DebriPod && DebriPod.playbackQueue;
      return !!(queue && queue.state.index >= 0 && queue.state.index < queue.state.items.length - 1);
    }catch(e){ return false; }
  }

  function syncMediaSessionPosition(){
    if(!canMediaSession()) return;
    const ms = navigator.mediaSession;
    if(!ms || typeof ms.setPositionState !== "function") return;
    try{
      const m = isVideoActive() ? npVideo : activeAudio;
      if(!m) return;
      const d = Number(m.duration || 0);
      const t = Number(m.currentTime || 0);
      const rate = Number(m.playbackRate || 1) || 1;
      if(!(d > 0) || !isFinite(d) || !isFinite(t) || !isFinite(rate)) return;
      ms.setPositionState({
        duration: d,
        playbackRate: rate,
        position: Math.max(0, Math.min(t, d))
      });
    }catch(e){}
  }

  function updateMediaSession(meta){
    if(!canMediaSession()) return;
    const normalized = typeof normalizePlaybackMetadata === "function"
      ? normalizePlaybackMetadata(meta || {}, meta || {}, meta && meta.label)
      : (meta || {});
    try{
      const artwork = normalized.art ? [{
        src: typeof playbackArtworkUrl === "function" ? playbackArtworkUrl(normalized.art) : normalized.art,
        sizes: "512x512"
      }] : [];
      navigator.mediaSession.metadata = new MediaMetadata({
        title: normalized.title || normalized.label || "Track",
        artist: normalized.artist || "",
        album: normalized.album || "",
        artwork: artwork
      });
    }catch(e){}
    try{ syncMediaSessionControls(); }catch(e){}
    try{ syncMediaSessionPosition(); }catch(e){}
  }

  function setMediaActionHandler(name, handler){
    if(!canMediaSession()) return;
    try{ navigator.mediaSession.setActionHandler(name, handler); }catch(e){}
  }

  function syncMediaSessionControls(){
    if(!canMediaSession()) return;
    const ms = navigator.mediaSession;
    try{
      ms.playbackState = ((isVideoActive() ? npVideo : activeAudio) && !(isVideoActive() ? npVideo : activeAudio).paused) ? "playing" : "paused";
    }catch(e){}
    setMediaActionHandler("play", ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      try{
        const hasAudioSource = !!(activeAudio && (activeAudio.currentSrc || activeAudio.src));
        if(!isVideoActive() && !hasAudioSource && typeof resumePersistedPlayback === "function"){
          const p = resumePersistedPlayback(false, {sync:true});
          if(p && p.catch) p.catch(()=>{});
          return;
        }
      }catch(e){}
      if(isVideoActive()){
        try{ preparePlaybackMediaAudio(npVideo); }catch(e){}
        try{ unlockPlaybackMediaAudio(); }catch(e){}
        try{ npVideo.play().catch(()=>{}); }catch(e){}
        return;
      }
      try{ if(standbyAudio && !standbyAudio.paused) standbyAudio.pause(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
      try{ preparePlaybackMediaAudio(activeAudio); }catch(e){}
      try{ unlockPlaybackMediaAudio(); }catch(e){}
      try{ activeAudio.play().catch(()=>{}); }catch(e){}
    });
    setMediaActionHandler("pause", ()=>{
      try{
        const m = isVideoActive() ? npVideo : activeAudio;
        if(m) m.pause();
      }catch(e){}
    });
    setMediaActionHandler("stop", ()=>{
      try{
        const m = isVideoActive() ? npVideo : activeAudio;
        if(m) m.pause();
      }catch(e){}
    });
    setMediaActionHandler("seekbackward", null);
    setMediaActionHandler("seekforward", null);
    setMediaActionHandler("seekto", null);
    setMediaActionHandler("previoustrack", mediaSessionHasPrev() ? ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      try{
        const queue = window.DebriPod && DebriPod.playbackQueue;
        if(queue) queue.previous();
      }catch(e){}
      setTimeout(()=>{ try{ syncMediaSessionControls(); }catch(e){} }, 50);
    } : null);
    setMediaActionHandler("nexttrack", mediaSessionHasNext() ? ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      try{
        const queue = window.DebriPod && DebriPod.playbackQueue;
        if(queue) queue.next();
      }catch(e){}
      setTimeout(()=>{ try{ syncMediaSessionControls(); }catch(e){} }, 50);
    } : null);
  }
  syncMediaSessionControls();

  // Last.fm scrobbling
  var lastfmState = {
    key: "",
    startTs: 0,
    duration: 0,
    meta: null,
    sentNow: false,
    sentScrobble: false,
    lovedKnown: false,
    loved: false
  };

  function lastfmIsEnabled(){
    return !!state.lastfmEnabled;
  }

  function lastfmTrackKey(meta){
    const a = (meta && meta.artist ? meta.artist : "").trim().toLowerCase();
    const t = (meta && meta.title ? meta.title : "").trim().toLowerCase();
    const b = (meta && meta.album ? meta.album : "").trim().toLowerCase();
    return a + "\n" + t + "\n" + b;
  }

  async function lastfmPost(path, payload){
    if(!lastfmIsEnabled()) return;
    try{
      await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload || {}),
        keepalive: true
      });
    }catch(e){}
  }

  async function lastfmGetLoved(meta){
    try{
      const a = encodeURIComponent((meta && meta.artist) ? meta.artist : "");
      const t = encodeURIComponent((meta && meta.title) ? meta.title : "");
      const b = encodeURIComponent((meta && meta.album) ? meta.album : "");
      const rootId = String((state.now && state.now.rootId) || "");
      const rel = String((state.now && state.now.rel) || "");
      const mediaKey = rootId && rel ? ("local:" + rootId + ":" + rel.replace(/\\/g, "/")) : "";
      if(!mediaKey && (!a || !t)) return;
      const js = await apiGet("/api/library/like?media_key=" + encodeURIComponent(mediaKey || ("music:" + [String((meta && meta.artist) || "").trim().toLowerCase(), String((meta && meta.title) || "").trim().toLowerCase(), String((meta && meta.album) || "").trim().toLowerCase()].join("\u001f"))) + "&artist=" + a + "&title=" + t + "&album=" + b);
      if(js && js.ok){
        lastfmState.loved = !!(js.like && js.like.liked);
        lastfmState.lovedKnown = true;
        updateWheelLabels();
      }
    }catch(e){}
  }

  async function lastfmToggleLoved(meta){
    let prevKnown = false;
    let prevLoved = false;
    let havePrev = false;
    try{
      const artist = (meta && meta.artist) ? meta.artist : "";
      const title = (meta && meta.title) ? meta.title : "";
      const album = (meta && meta.album) ? meta.album : "";
      const rootId = String((state.now && state.now.rootId) || "");
      const rel = String((state.now && state.now.rel) || "");
      if((!rootId || !rel) && (!artist.trim() || !title.trim())) return;

      prevKnown = !!lastfmState.lovedKnown;
      prevLoved = !!lastfmState.loved;
      havePrev = true;

      // Optimistic flip so the UI responds immediately.
      const optimistic = prevKnown ? (!prevLoved) : true;
      lastfmState.loved = optimistic;
      lastfmState.lovedKnown = true;
      updateWheelLabels();

      const res = await apiPost("/api/library/like", {
        media_type:"music", source:"library", root_id:rootId, rel:rel,
        title:title, artist:artist, album:album, liked:optimistic
      });
      const js = (res && res.json) ? res.json : null;

      if(res && res.ok && js && js.ok){
        lastfmState.loved = !!(js.like && js.like.liked);
        lastfmState.lovedKnown = true;
        updateWheelLabels();

        // Reconcile after propagation and any metadata normalization differences.
        setTimeout(()=>{ lastfmGetLoved(meta); }, 1500);
      }else{
        // Revert if server rejected.
        lastfmState.loved = prevLoved;
        lastfmState.lovedKnown = prevKnown;
        updateWheelLabels();
      }
    }catch(e){
      if(havePrev){
        lastfmState.loved = prevLoved;
        lastfmState.lovedKnown = prevKnown;
        updateWheelLabels();
      }
    }
  }

  // Server-side playback sync (Now Playing + History)
  async function playbackPost(payload){
    try{
      if(payload && typeof payload === "object"){
        try{
          payload.session = state.playbackSession || payload.session || null;
          if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.savePlaybackSession){
            DebriPod.clientSync.savePlaybackSession(state.playbackSession);
          }
        }catch(e){}
      }
      await fetch("/api/playback/update", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload || {}),
        cache: "no-store",
        keepalive: true
      });
    }catch(e){}
  }

  async function syncPlaybackFromServer(){
    try{
      const js = await apiGet("/api/playback/snapshot");
      state.serverNow = (js && js.now) ? js.now : null;
      state.serverRecent = (js && Array.isArray(js.recent)) ? js.recent : [];
      state.serverMediaProgress = (js && js.media_progress && typeof js.media_progress === "object") ? js.media_progress : {};
      state.serverLoaded = true;
      try{
        if(typeof applyServerPlaybackSession === "function"){
          applyServerPlaybackSession(js || {});
        }else if(state.serverNow && state.serverNow.root_id && state.serverNow.rel){
          state.now = {rootId: state.serverNow.root_id, rel: state.serverNow.rel, media: state.serverNow.media || "", streamed: !!state.serverNow.streamed};
        }else if(!state.now){
          state.now = null;
        }
      }catch(e){
        if(state.serverNow && state.serverNow.root_id && state.serverNow.rel){
          state.now = {rootId: state.serverNow.root_id, rel: state.serverNow.rel, media: state.serverNow.media || "", streamed: !!state.serverNow.streamed};
        }else if(!state.now){
          state.now = null;
        }
      }
    }catch(e){
      state.serverLoaded = false;
    }
  }

  function nowBadgeText(){
    try{
      if(isVideoActive()){
        return (npVideo && !npVideo.paused) ? "playing" : "";
      }
      if(activeAudio && !activeAudio.paused){
        return "playing";
      }
      if(state.serverNow && state.serverNow.playing){
        return "playing";
      }
      return "";
    }catch(e){
      return "";
    }
  }

  function captureNavContext(){
    const nav = {};
    try{
      if(state.root && state.root.id){
        nav.root_id = state.root.id;
        nav.root_name = state.root.name || "";
      }
      if(state.current && state.current.kind){
        nav.kind = state.current.kind;
        nav.label = state.current.label || "";
        if(state.current.kind === "folder"){
          nav.rel = state.current.rel || "";
        }else if(state.current.kind === "metatop"){
          // nothing extra
        }else if(state.current.kind === "metalist"){
          nav.level = state.current.level || "";
          nav.value = state.current.value || "";
        }
      }
      // if we're on now playing screen, try to use the last non-now view for better restore
      if(nowPlaying && nowPlaying.style.display === "block" && state.history && state.history.length){
        const v = state.history[state.history.length - 1];
        if(v && v.kind){
          nav.kind = v.kind;
          nav.label = v.label || nav.label || "";
          if(v.kind === "folder") nav.rel = v.rel || "";
          if(v.kind === "metalist"){ nav.level = v.level || ""; nav.value = v.value || ""; }
        }
      }
    }catch(e){}
    return nav;
  }

  async function openNavContext(nav, options){
    try{
      if(!nav || !nav.root_id){
        return;
      }
      const cfg = await loadConfig();
      const root = (cfg.roots || []).find(r => r.id === nav.root_id);
      if(!root) return;

      state.root = root;
      const opts = options || {};
      if(opts.history && Array.isArray(opts.history)) state.history = opts.history.slice();

      if(nav.kind === "folder"){
        const rel = (nav.rel || "").trim();
        if(rel){
          const segs = rel.split("/");
          state.history.push(folderViewObj(root, "", ""));
          for(let i = 0; i < segs.length - 1; i++){
            const r = segs.slice(0, i + 1).join("/");
            state.history.push(folderViewObj(root, r, segs[i]));
          }
        }
        showNowPlaying(false);
        await setView(folderViewObj(root, rel, rel ? rel.split("/").slice(-1)[0] : ""), false);
        return;
      }

      if((root.mode || "folders") === "metadata"){
        if(nav.kind === "metalist" && nav.level){
          await viewMetaList(root, nav.level, nav.value || "", nav.label || nav.level, false);
          return;
        }
        await viewMetaTop(root, false);
        return;
      }

      // fallback
      await viewFolder(root, "", "", false);
    }catch(e){}
  }

  function lastfmSendNowPlaying(){
    if(!lastfmIsEnabled()) return;
    if(lastfmState.sentNow) return;
    const m = lastfmState.meta;
    if(!m) return;
    if(!m.title || !m.artist) return;
    lastfmState.sentNow = true;
    lastfmPost("/api/lastfm/nowplaying", {
      title: m.title || "",
      artist: m.artist || "",
      album: m.album || "",
      duration: (lastfmState.duration && isFinite(lastfmState.duration)) ? Math.round(lastfmState.duration) : null
    });
  }

  function lastfmOnTrack(meta){
    if(!meta) return;
    const k = lastfmTrackKey(meta);
    if(!k.trim()) return;
    if(k !== lastfmState.key){
      lastfmState.key = k;
      lastfmState.startTs = Math.floor(Date.now()/1000);
      lastfmState.sentNow = false;
      lastfmState.sentScrobble = false;
      lastfmState.lovedKnown = false;
      lastfmState.loved = false;
      lastfmGetLoved(meta);
    }
    lastfmState.meta = meta;
    const d0 = (meta.duration && isFinite(meta.duration)) ? meta.duration : 0;
    const d1 = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
    const d = d0 || d1 || 0;
    lastfmState.duration = d;
    lastfmSendNowPlaying();
  }

  function lastfmMaybeScrobble(force){
    if(!lastfmIsEnabled()) return;
    if(lastfmState.sentScrobble) return;
    const m = lastfmState.meta;
    if(!m) return;
    if(!m.title || !m.artist) return;
    const d0 = (lastfmState.duration && isFinite(lastfmState.duration)) ? lastfmState.duration : 0;
    const d1 = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
    const d = d0 || d1 || 0;
    if(!(d > 0)) return;
    if(d < 30) return;
    const t = (activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0;
    const need = Math.min(240, d * 0.5);
    if(force || t >= need){
      lastfmState.sentScrobble = true;
      lastfmPost("/api/lastfm/scrobble", {
        title: m.title || "",
        artist: m.artist || "",
        album: m.album || "",
        duration: Math.round(d),
        start_ts: lastfmState.startTs || Math.floor(Date.now()/1000)
      });
    }
  }
