  function swapAudios(){
    activeAudio = audioMain;
    standbyAudio = null;
  }

  function canMediaSession(){
    return !!(navigator.mediaSession && window.MediaMetadata);
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
      if(isVideoActive()) return !!(Array.isArray(state.videoPlaylist) && state.videoPlaylist.length > 1 && prevVideoIndexPeek() !== null);
      return !!(Array.isArray(state.playlist) && state.playlist.length > 1 && prevIndexPeek() !== null);
    }catch(e){ return false; }
  }

  function mediaSessionHasNext(){
    try{
      if(isVideoActive()) return !!(Array.isArray(state.videoPlaylist) && state.videoPlaylist.length > 1 && nextVideoIndexPeek() !== null);
      return !!(Array.isArray(state.playlist) && state.playlist.length > 1 && nextIndexPeek() !== null);
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
    try{
      navigator.mediaSession.metadata = new MediaMetadata({
        title: meta.title || "",
        artist: meta.artist || "",
        album: meta.album || "",
        artwork: meta.art ? [{src: meta.art, sizes: "400x400", type: "image/jpeg"}] : []
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
      if(isVideoActive()){
        try{ npVideo.play().catch(()=>{}); }catch(e){}
        return;
      }
      try{ if(standbyAudio && !standbyAudio.paused) standbyAudio.pause(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
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
      if(isVideoActive()){
        try{ playVideoPrev(); }catch(e){}
      }else{
        try{ playPrev(); }catch(e){}
      }
      setTimeout(()=>{ try{ syncMediaSessionControls(); }catch(e){} }, 50);
    } : null);
    setMediaActionHandler("nexttrack", mediaSessionHasNext() ? ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      if(isVideoActive()){
        try{ playVideoNext(); }catch(e){}
      }else{
        try{ playNext(); }catch(e){}
      }
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
    if(!lastfmIsEnabled()) return;
    try{
      const a = encodeURIComponent((meta && meta.artist) ? meta.artist : "");
      const t = encodeURIComponent((meta && meta.title) ? meta.title : "");
      const b = encodeURIComponent((meta && meta.album) ? meta.album : "");
      if(!a || !t) return;
      const js = await apiGet("/api/lastfm/loved?artist=" + a + "&title=" + t + "&album=" + b);
      if(js && js.ok){
        lastfmState.loved = !!js.loved;
        lastfmState.lovedKnown = true;
        updateWheelLabels();
      }
    }catch(e){}
  }

  async function lastfmToggleLoved(meta){
    if(!lastfmIsEnabled()) return;
    let prevKnown = false;
    let prevLoved = false;
    let havePrev = false;
    try{
      const artist = (meta && meta.artist) ? meta.artist : "";
      const title = (meta && meta.title) ? meta.title : "";
      const album = (meta && meta.album) ? meta.album : "";
      if(!artist.trim() || !title.trim()) return;

      prevKnown = !!lastfmState.lovedKnown;
      prevLoved = !!lastfmState.loved;
      havePrev = true;

      // Optimistic flip so the UI responds immediately.
      const optimistic = prevKnown ? (!prevLoved) : true;
      lastfmState.loved = optimistic;
      lastfmState.lovedKnown = true;
      updateWheelLabels();

      const res = await apiPost("/api/lastfm/toggle_loved", {artist: artist, title: title, album: album});
      const js = (res && res.json) ? res.json : null;

      if(res && res.ok && js && js.ok){
        lastfmState.loved = !!js.loved;
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
      state.serverLoaded = true;
      if(state.serverNow && state.serverNow.root_id && state.serverNow.rel){
        state.now = {rootId: state.serverNow.root_id, rel: state.serverNow.rel, media: state.serverNow.media || "", streamed: !!state.serverNow.streamed};
      }else{
        // keep local state.now if it exists; otherwise clear
        if(!state.now) state.now = null;
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

  async function openNavContext(nav){
    try{
      if(!nav || !nav.root_id){
        return;
      }
      const cfg = await loadConfig();
      const root = (cfg.roots || []).find(r => r.id === nav.root_id);
      if(!root) return;

      state.root = root;
      state.history = [];
      state.current = null;

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
    if(!lastfmIsEnabled()) return;
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
