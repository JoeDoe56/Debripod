  var state = {
    root: null,
    roots: [],
    history: [],
    current: null,
    rootView: null,
    items: [],
    sel: 0,
    playlist: [],
    playIndex: -1,
    videoPlaylist: [],
    videoIndex: -1,
    now: null,
    libSearch: {q: "", filter: "", engine: "combined", cache_key: "", result_source: "combined", last_count: 0, results: [], knaben_results: [], slsk_users: [], editField: "", editValue: ""},
    playlistCreate: {editing: false, editValue: "", submitting: false},
    playlistEdit: {rel: "", label: "", editingName: false, editNameValue: "", submitting: false},
    libTasks: {tasks: []},
    pendingLibSearch: null,
    nowMeta: null,
    serverNow: null,
    serverRecent: [],
    serverLoaded: false,
    lastfmEnabled: false,
    playbackStreamingMode: "http",
    preloadEnabled: true,
    preloadBytes: 2097152,
    shuffleEnabled: false,
    playOrder: null,
    orderPos: 0,
    playOrderPlaylist: null,
    preloadedIndex: null,
    visualizerEnabled: visualizerEnabled,
    visualizerPreset: visualizerPresetName,
    visualizerBpm: visualizerBpm,
    streamQueue: [],
    streamQueueIndex: -1
  };

  var npPlaylistReturnView = null;

  try{
    state.shuffleEnabled = (localStorage.getItem("debripod_shuffle") === "1");
  }catch(e){ state.shuffleEnabled = false; }
  applyThemeVars(defaultTheme);
  applyVisualizerPresetPalette();
  updateVisualizerState();

  var playbackLastPostTs = 0;
  var playbackLastPos = -1;
  var playbackLastPlaylistHash = "";

  function playbackStringHash(text){
    let h = 2166136261;
    const s = String(text || "");
    for(let i=0;i<s.length;i++){
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0).toString(16);
  }

  function playbackPlaylistContext(media){
    let playlistCtx = null;
    try{
      const srcList = media === "video" ? state.videoPlaylist : state.playlist;
      const srcIndex = media === "video" ? state.videoIndex : state.playIndex;
      if(Array.isArray(srcList) && srcList.length){
        const items = srcList.slice(0, 500).map(it=>({
          root_id: (it.root && it.root.id) ? it.root.id : "",
          rel: it.rel || "",
          media: String(it.media || media || "audio"),
          label: it.label || "",
          streamed: !!it.streamed,
          source: it.source || "",
          ext: it.ext || "",
          quality: it.quality || ""
        })).filter(x=>x.root_id && x.rel);
        playlistCtx = {items: items, index: (srcIndex >= 0 ? srcIndex : 0)};
      }
    }catch(e){ playlistCtx = null; }
    if(!playlistCtx || !playlistCtx.items || !playlistCtx.items.length) return {hash:"", playlist:null, changed:false};
    const hash = playbackStringHash(JSON.stringify(playlistCtx));
    const changed = hash !== playbackLastPlaylistHash;
    if(changed) playbackLastPlaylistHash = hash;
    return {hash:hash, playlist: changed ? playlistCtx : null, changed:changed};
  }

  function playbackMaybePost(media, rootId, rel, metaObj, pos, dur, playing, ev){
    const nowTs = Date.now();
    const p = (pos && isFinite(pos)) ? Number(pos) : 0;
    if(ev === "time"){
      if(nowTs - playbackLastPostTs < 5000 && Math.abs(p - playbackLastPos) < 4.0) return;
      playbackLastPostTs = nowTs;
      playbackLastPos = p;
    }else{
      playbackLastPostTs = nowTs;
      playbackLastPos = p;
    }
    const m = metaObj || {};
    const playlistInfo = playbackPlaylistContext(media);
    playbackPost({
      media: media,
      root_id: rootId,
      rel: rel,
      playlist_hash: playlistInfo.hash,
      playlist: playlistInfo.playlist,
      label: m.label || "",
      title: m.title || "",
      artist: m.artist || "",
      album: m.album || "",
      art: m.art || "",
      position: p,
      duration: (dur && isFinite(dur)) ? Number(dur) : null,
      playing: !!playing,
      nav: captureNavContext(),
      event: ev || "time",
      streamed: !!m.streamed,
      source: m.source || "",
      ext: m.ext || "",
      quality: m.quality || ""
    });
  }


  function layoutNowPlayingToLibList(){
    try{
      if(!nowPlaying) return;
      nowPlaying.style.inset = "var(--screenFrame)";
      nowPlaying.style.left = "";
      nowPlaying.style.top = "";
      nowPlaying.style.width = "";
      nowPlaying.style.height = "";
      nowPlaying.style.right = "";
      nowPlaying.style.bottom = "";
      nowPlaying.style.borderRadius = "var(--screenInnerRadius)";
    }catch(e){}
  }

  function resetNowPlayingLayout(){
    try{
      if(!nowPlaying) return;
      nowPlaying.style.inset = "";
      nowPlaying.style.left = "";
      nowPlaying.style.top = "";
      nowPlaying.style.width = "";
      nowPlaying.style.height = "";
      nowPlaying.style.right = "";
      nowPlaying.style.bottom = "";
      nowPlaying.style.borderRadius = "";
    }catch(e){}
  }

  function waitNowPlayingFade(ms){
    return new Promise(resolve=> setTimeout(resolve, ms || 220));
  }

  function showNowPlaying(on){
    const fadeMs = 220;
    try{ if(libList) libList.style.display = "block"; }catch(e){}
    try{
      if(npPageFadeTimer){
        clearTimeout(npPageFadeTimer);
        npPageFadeTimer = null;
      }
    }catch(e){}
    npPageFadeToken += 1;
    const fadeToken = npPageFadeToken;

    if(on){
      try{ libList.classList.add("npUnderlay"); }catch(e){}
      layoutNowPlayingToLibList();
      nowPlaying.style.display = "block";
      try{ setHeader(); }catch(e){}
      try{ nowPlaying.classList.remove("npPageActive"); }catch(e){}
      updateVisualizerState();
      try{
        if(window.DebriPod && DebriPod.albumArtTexture && DebriPod.albumArtTexture.renderToCanvas){
          DebriPod.albumArtTexture.renderToCanvas(npArt);
        }
      }catch(e){}
      scheduleLiquidGlassSnapshot("now playing entering", true);
      setTimeout(()=>{
        try{
          if(window.DebriPod && DebriPod.albumArtTexture && DebriPod.albumArtTexture.renderToCanvas){
            DebriPod.albumArtTexture.renderToCanvas(npArt);
          }
          recaptureLiquidGlassElement(npArt);
          scheduleNpOverlayGlassRender();
          scheduleLiquidGlassRender();
        }catch(e){}
      }, 80);
      requestAnimationFrame(()=>{
        requestAnimationFrame(()=>{
          try{
            if(fadeToken !== npPageFadeToken) return;
            nowPlaying.classList.add("npPageActive");
            try{
              if(window.DebriPod && DebriPod.albumArtTexture && DebriPod.albumArtTexture.renderToCanvas){
                DebriPod.albumArtTexture.renderToCanvas(npArt);
              }
              scheduleNpOverlayGlassRender();
            }catch(e){}
            scheduleLiquidGlassSnapshot("now playing active", true);
          }catch(e){}
        });
      });
      npPillActivity(false);
    }else{
      hideNpPillImmediate("now playing leaving");
      try{ libList.classList.remove("npUnderlay"); }catch(e){}
      try{ nowPlaying.classList.remove("npPageActive"); }catch(e){}
      scheduleLiquidGlassSnapshot("now playing leaving", true);
      npPageFadeTimer = setTimeout(()=>{
        try{
          if(fadeToken !== npPageFadeToken) return;
          nowPlaying.style.display = "none";
          resetNowPlayingLayout();
          try{ setHeader(); }catch(e){}
          scheduleLiquidGlassSnapshot("now playing hidden", true);
        }catch(e){}
        npPageFadeTimer = null;
      }, fadeMs);
    }
    if(!on){
      stopVideoOverlay();
      try{ if(volBarTimer) clearTimeout(volBarTimer); }catch(e){}
      volBarTimer = null;
    }
    cancelSeekMode();
    showProgressBar();
  }

  function syncWheelZoneHeight(){
    try{
      const wrapEl = document.getElementById("divwrap") || document.querySelector(".wrap");
      const screenEl = document.querySelector("#tab-library .ipodScreen");
      const wheelZoneEl = document.getElementById("wheelZone") || document.querySelector("#tab-library .wheelZone");
      if(!wrapEl || !screenEl || !wheelZoneEl) return;
      const wrapRect = wrapEl.getBoundingClientRect();
      const screenRect = screenEl.getBoundingClientRect();
      const rootStyle = getComputedStyle(document.documentElement);
      const wheelSize = parseFloat(rootStyle.getPropertyValue("--wheelSize")) || 0;
      const wheelGap = parseFloat(rootStyle.getPropertyValue("--wheelGap")) || 0;
      const minNeeded = Math.ceil(wheelSize + (wheelGap * 2));
      const available = Math.max(0, Math.round(wrapRect.bottom - screenRect.bottom));
      const target = Math.max(available, minNeeded);
      wheelZoneEl.style.height = target + "px";
      wheelZoneEl.style.minHeight = target + "px";
      wheelZoneEl.style.flex = "0 0 " + target + "px";
    }catch(e){}
  }


  window.addEventListener("resize", ()=>{
    try{ syncWheelZoneHeight(); }catch(e){}
    try{
      if(nowPlaying && nowPlaying.style.display === "block"){
        layoutNowPlayingToLibList();
      }
    }catch(e){}
  });

  function bringToNowPlayingIfPlaying(){
    if(!state.now) return;
    if(activeAudio && !activeAudio.paused){
      setTab("library");
      showNowPlaying(true);
    }
  }

  window.addEventListener("focus", bringToNowPlayingIfPlaying);
  document.addEventListener("visibilitychange", ()=>{
    if(document.hidden){
      try{ saveResumeNowPlaying(); }catch(e){}
      try{ ensurePlaybackAudioSession(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
    }else{
      bringToNowPlayingIfPlaying();
      try{ ensurePlaybackAudioSession(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
    }
  });

  window.addEventListener("pagehide", ()=>{
    try{ saveResumeNowPlaying(); }catch(e){}
  });

  window.addEventListener("beforeunload", ()=>{
    try{ saveResumeNowPlaying(); }catch(e){}
  });

  function saveResumeNowPlaying(){
    if(!state.now) return;
    try{
      localStorage.setItem("debripod_tab", "library");
      localStorage.setItem("debripod_resume_np", JSON.stringify({rootId: state.now.rootId, rel: state.now.rel, playing: (activeAudio && !activeAudio.paused), ts: Date.now()}));
    }catch(e){}
  }

  function encodeRel(rel){
    return (rel||"").split("\\").join("/").split("/").map(encodeURIComponent).join("/");
  }

  function escapeHtml(s){
    const str = String(s ?? "");
    return str
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  async function loadConfig(){
    const js = await apiGet("/api/library/config");
    state.preloadEnabled = !!js.preload_enabled;
    state.preloadBytes = js.preload_bytes || state.preloadBytes;
    state.roots = js.roots || [];
    state.lastfmEnabled = !!js.lastfm_enabled;
    state.playbackStreamingMode = (String(js.playback_streaming_mode || "http").toLowerCase() === "hls") ? "hls" : "http";
    wheelRotationMaxDegrees = normalizeWheelRotationMaxDegrees(js.wheel_rotation_max_degrees);
    applyLiquidGlassStyleOptions();
    initLiquidGlass();
    return js;
  }

  function headerText(){
    try{
      if(nowPlaying && nowPlaying.style.display === "block"){
        const m = state.nowMeta || {};
        const sn = state.serverNow || {};
        const now = state.now || {};
        const rel = String(now.rel || sn.rel || "").replace(/\\/g, "/");
        const fallback = rel ? (rel.split("/").pop() || "") : "";
        const title = String(m.title || m.label || sn.title || sn.label || (npTitle && npTitle.textContent) || fallback || "").trim();
        const artist = String(m.artist || sn.artist || "").trim();
        const item = (artist && title) ? (artist + " - " + title) : (title || fallback);
        return item ? ("Now Playing > " + item) : "Now Playing";
      }
    }catch(e){}
    const parts = [];
    if(state.root && state.root.name) parts.push(state.root.name);
    for(const v of state.history){
      if(v && v.label) parts.push(v.label);
    }
    if(state.current && state.current.label) parts.push(state.current.label);
    return parts.length ? parts.join(" > ") : "Library";
  }

  function setHeader(){
    const text = headerText();
    const headerTextEl = document.getElementById("libHeaderText");
    if(headerTextEl){
      headerTextEl.textContent = text;
      headerTextEl.setAttribute("data-text", text);
      headerTextEl.setAttribute("data-liquid-ignore", "");
      headerTextEl.classList.add("glassText");
    }
    else libHeader.textContent = text;
    try{ if(headerTextEl) headerTextEl.scrollLeft = 0; }catch(e){}
    try{ pathPillActivity(false); }catch(e){}
    try{
      const k = state.current ? state.current.kind : "";
      if(k !== "libsearch" && k !== "libsearch_files"){
        libControlsHide();
      }
    }catch(e){}
  }

  function beginPlaylistCreateEdit(){
    try{
      if(!state.playlistCreate) state.playlistCreate = {editing:false, editValue:"", submitting:false};
      if(state.playlistCreate.submitting) return;
      state.playlistCreate.editing = true;
      if(typeof state.playlistCreate.editValue !== "string") state.playlistCreate.editValue = "";
      renderList();
    }catch(e){}
  }

  function beginSmartPlaylistCreateEdit(){
    try{
      if(!state.smartPlaylistCreate) state.smartPlaylistCreate = {editing:false, editValue:"", submitting:false};
      if(state.smartPlaylistCreate.submitting) return;
      state.smartPlaylistCreate.editing = true;
      if(typeof state.smartPlaylistCreate.editValue !== "string") state.smartPlaylistCreate.editValue = "";
      renderList();
    }catch(e){}
  }

  async function closeNowPlayingPlaylistMode(){
    try{
      const prev = npPlaylistReturnView;
      npPlaylistReturnView = null;
      if(prev){
        await runLibraryPageTransition(async ()=>{
          state.current = prev;
          setHeader();
          await prev.load();
        });
      }
    }catch(e){}
    showNowPlaying(true);
    updateWheelLabels();
  }

  async function addCurrentNowPlayingTrackToPlaylist(playlistRel){
    const cur = state.current || {};
    const root = cur.root || null;
    const trackRel = String(cur.trackRel || "");
    const rel = String(playlistRel || "");
    if(!root || !root.id || !trackRel || !rel) return false;
    const res = await apiPost("/api/library/playlist_add", {root_id: root.id, rel: rel, tracks: [trackRel]});
    const js = (res && res.json) ? res.json : {};
    if(!res || !res.ok || !js.ok){
      if(js && js.error && String(js.error) === "No songs added"){
        return true;
      }
      throw new Error((js && js.error) ? js.error : "Failed to add song");
    }
    return true;
  }

  async function viewNowPlayingPlaylistMode(){
    const currentNow = state.now || null;
    const currentMedia = String((currentNow && currentNow.media) || (isVideoActive() ? "video" : "audio"));
    if(!currentNow || currentMedia !== "audio" || !currentNow.rootId || !currentNow.rel){
      return;
    }
    let root = null;
    try{
      if(!state.roots || !state.roots.length){
        await loadConfig();
      }
      root = (state.roots || []).find(r => r && r.id === currentNow.rootId) || null;
    }catch(e){ root = null; }
    if(!root) return;
    const alreadyInMode = !!(state.current && state.current.kind === "np_playlist_add");
    const existingAdded = (state.current && state.current.kind === "np_playlist_add" && state.current._added instanceof Set) ? state.current._added : new Set();
    if(!alreadyInMode){
      snapshotListState();
      npPlaylistReturnView = state.current || null;
    }
    const view = {
      kind: "np_playlist_add",
      label: "Add to playlist",
      root: root,
      trackRel: String(currentNow.rel || ""),
      _added: existingAdded,
      load: async function(){
        const js = await apiGet("/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=playlists&value=");
        const items = [
          {kind:"np_playlist_close", label:"Close"},
          {kind:"playlist_create", label:"Create playlist"},
          {kind:"smart_playlist_create", label:"Create smart playlist"}
        ];
        const all = Array.isArray(js.items) ? js.items : [];
        const playlistItems = all.filter(it => it && String(it.kind || "") === "playlist" && !it.smart);
        for(const it of playlistItems){
          const rel = String(it.rel || "");
          const added = !!(this._added && this._added.has(rel));
          items.push({
            kind:"np_playlist_entry",
            label:String(it.label || "Playlist"),
            rel:rel,
            root:root,
            selectable:true,
            selected:added,
            pills:[{text: added ? "Ã¢Å“â€œ" : "+", _selectPill:true}]
          });
        }
        if(!playlistItems.length){
          items.push({kind:"info", label:"No playlists found"});
        }
        resetList(items);
      }
    };
    state.current = view;
    setHeader();
    resetList([
      {kind:"np_playlist_close", label:"Close"},
      {kind:"playlist_create", label:"Create playlist"},
          {kind:"smart_playlist_create", label:"Create smart playlist"},
      {kind:"info", label:"Loading playlists..."}
    ]);
    showNowPlaying(false);
    await runLibraryPageTransition(async ()=>{
      await view.load();
    });
    updateWheelLabels();
  }

  async function submitPlaylistCreate(rawName){
    try{
      if(!state.playlistCreate) state.playlistCreate = {editing:false, editValue:"", submitting:false};
      const name = String(rawName || "").trim();
      const root = state.current && state.current.root ? state.current.root : null;
      if(!root || !root.id){
        state.playlistCreate.submitting = false;
        return;
      }
      state.playlistCreate.submitting = true;
      const res = await apiPost("/api/library/playlist_create", {root_id: root.id, name: name});
      const js = (res && res.json) ? res.json : {};
      state.playlistCreate.submitting = false;
      state.playlistCreate.editing = false;
      state.playlistCreate.editValue = "";
      if(!res || !res.ok || !js.ok){
        if(js && js.error){
          alert(String(js.error));
        }
        renderList();
        return;
      }
      if(state.current && state.current.kind === "np_playlist_add"){
        await viewNowPlayingPlaylistMode();
        try{
          const wantRel = String(js.rel || "");
          if(wantRel){
            const idx = state.items.findIndex(x => x && x.kind === "np_playlist_entry" && x.rel === wantRel);
            if(idx >= 0){
              state.sel = idx;
              renderList();
            }
          }
        }catch(e){}
        return;
      }
      await viewMetaList(root, "playlists", "", "Playlists", false);
      try{
        const wantRel = String(js.rel || "");
        if(wantRel){
          const idx = state.items.findIndex(x => x && x.kind === "playlist" && x.rel === wantRel);
          if(idx >= 0){
            state.sel = idx;
            renderList();
          }
        }
      }catch(e){}
    }catch(e){
      try{ state.playlistCreate.submitting = false; }catch(e2){}
      try{ state.playlistCreate.editing = false; state.playlistCreate.editValue = ""; }catch(e2){}
      try{ alert(String(e && e.message ? e.message : e)); }catch(e2){}
      try{ renderList(); }catch(e2){}
    }
  }

  async function submitSmartPlaylistCreate(rawName){
    try{
      if(!state.smartPlaylistCreate) state.smartPlaylistCreate = {editing:false, editValue:"", submitting:false};
      const name = String(rawName || "").trim();
      const root = state.current && state.current.root ? state.current.root : null;
      if(!root || !root.id){
        state.smartPlaylistCreate.submitting = false;
        return;
      }
      state.smartPlaylistCreate.submitting = true;
      const res = await apiPost("/api/library/smart_playlist_create", {root_id: root.id, name: name});
      const js = (res && res.json) ? res.json : {};
      state.smartPlaylistCreate.submitting = false;
      state.smartPlaylistCreate.editing = false;
      state.smartPlaylistCreate.editValue = "";
      if(!res || !res.ok || !js.ok){
        if(js && js.error) alert(String(js.error));
        renderList();
        return;
      }
      if(state.current && state.current.kind === "np_playlist_add"){
        await viewNowPlayingPlaylistMode();
        return;
      }
      await viewMetaList(root, "playlists", "", "Playlists", false);
      try{
        const wantRel = String(js.rel || "");
        if(wantRel){
          const idx = state.items.findIndex(x => x && x.kind === "playlist" && x.rel === wantRel);
          if(idx >= 0){
            state.sel = idx;
            renderList();
          }
        }
      }catch(e){}
    }catch(e){
      try{ state.smartPlaylistCreate.submitting = false; }catch(e2){}
      try{ state.smartPlaylistCreate.editing = false; state.smartPlaylistCreate.editValue = ""; }catch(e2){}
      try{ alert(String(e && e.message ? e.message : e)); }catch(e2){}
      try{ renderList(); }catch(e2){}
    }
  }

  function isSmartPlaylistRel(rel){
    const v = String(rel || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "").toLowerCase();
    return v === "debripod-smartplaylists" || v.startsWith("debripod-smartplaylists/");
  }

  async function viewSmartPlaylistRules(root, playlistRel, playlistLabel, push){
    showNowPlaying(false);
    await setView({
      kind: "smart_playlist_rules",
      label: "Edit rules",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      load: async function(){
        const js = await apiGet("/api/library/smart_playlist_rules?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.playlistRel || ""));
        if(!state.smartPlaylistRules) state.smartPlaylistRules = {text:"", saving:false};
        state.smartPlaylistRules.text = String(js.text || "");
        state.smartPlaylistRules.saving = false;
        resetList([
          {kind:"smart_playlist_rules_text", label:"Rules"},
          {kind:"smart_playlist_rules_save", label:"Save rules"},
          {kind:"smart_playlist_rules_cancel", label:"Back"},
          {kind:"smart_playlist_rules_delete", label:"Delete playlist"}
        ]);
      }
    }, !!push);
  }

  async function saveSmartPlaylistRules(){
    const cur = state.current || {};
    if(cur.kind !== "smart_playlist_rules" || !cur.root || !cur.root.id) return;
    if(!state.smartPlaylistRules) state.smartPlaylistRules = {text:"", saving:false};
    state.smartPlaylistRules.saving = true;
    try{
      const res = await apiPost("/api/library/smart_playlist_rules", {root_id: cur.root.id, rel: cur.playlistRel || "", text: String(state.smartPlaylistRules.text || "")});
      const js = (res && res.json) ? res.json : {};
      state.smartPlaylistRules.saving = false;
      if(!res || !res.ok || !js.ok){
        alert(String((js && js.error) ? js.error : "Failed to save rules"));
        renderList();
        return;
      }
      await goBack();
    }catch(e){
      state.smartPlaylistRules.saving = false;
      alert(String(e && e.message ? e.message : e));
      try{ renderList(); }catch(e2){}
    }
  }


  function beginPlaylistRenameEdit(){
    try{
      const cur = state.current || {};
      if(cur.kind !== "playlist_edit_menu") return;
      if(!state.playlistEdit) state.playlistEdit = {rel:"", label:"", editingName:false, editNameValue:"", submitting:false};
      if(state.playlistEdit.submitting) return;
      state.playlistEdit.rel = String(cur.playlistRel || state.playlistEdit.rel || "");
      state.playlistEdit.label = String(cur.playlistLabel || state.playlistEdit.label || "");
      state.playlistEdit.editingName = true;
      if(typeof state.playlistEdit.editNameValue !== "string" || !state.playlistEdit.editNameValue){
        state.playlistEdit.editNameValue = state.playlistEdit.label || "";
      }
      renderList();
    }catch(e){}
  }

  async function submitPlaylistRename(rawName){
    try{
      if(!state.playlistEdit) state.playlistEdit = {rel:"", label:"", editingName:false, editNameValue:"", submitting:false};
      const cur = state.current || {};
      const root = cur.root || null;
      const playlistRel = String(cur.playlistRel || state.playlistEdit.rel || "");
      const name = String(rawName || "").trim();
      if(!root || !root.id || !playlistRel){
        state.playlistEdit.submitting = false;
        return;
      }
      state.playlistEdit.submitting = true;
      const res = await apiPost("/api/library/playlist_rename", {root_id: root.id, rel: playlistRel, name: name});
      const js = (res && res.json) ? res.json : {};
      state.playlistEdit.submitting = false;
      if(!res || !res.ok || !js.ok){
        if(js && js.error){
          alert(String(js.error));
        }
        renderList();
        return;
      }
      const newRel = String(js.rel || playlistRel);
      const newLabel = String(js.label || name || state.playlistEdit.label || "Playlist");
      state.playlistEdit.rel = newRel;
      state.playlistEdit.label = newLabel;
      state.playlistEdit.editNameValue = newLabel;
      state.playlistEdit.editingName = false;
      if(state.current && state.current.kind === "playlist_edit_menu"){
        state.current.playlistRel = newRel;
        state.current.playlistLabel = newLabel;
      }
      try{
        for(const h of (state.history || [])){
          if(h && h.kind === "metalist" && h.level === "playlist_tracks" && String(h.value || "") === playlistRel){
            h.value = newRel;
            h.label = newLabel;
          }
        }
      }catch(e){}
      renderList();
    }catch(e){
      try{ state.playlistEdit.submitting = false; }catch(e2){}
      try{ alert(String(e && e.message ? e.message : e)); }catch(e2){}
      try{ renderList(); }catch(e2){}
    }
  }

  async function viewPlaylistEditMenu(root, playlistRel, playlistLabel, push){
    showNowPlaying(false);
    await setView({
      kind: "playlist_edit_menu",
      label: "Edit",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      load: async function(){
        if(!state.playlistEdit) state.playlistEdit = {rel:"", label:"", editingName:false, editNameValue:"", submitting:false};
        state.playlistEdit.rel = String(this.playlistRel || "");
        state.playlistEdit.label = String(this.playlistLabel || "");
        state.playlistEdit.editingName = false;
        state.playlistEdit.submitting = false;
        state.playlistEdit.editNameValue = state.playlistEdit.label || "";
        if(isSmartPlaylistRel(this.playlistRel || "")){
          resetList([
            {kind:"smart_playlist_rules_entry", label:"Edit rules"}
          ]);
        }else{
          resetList([
            {kind:"playlist_edit_name", label:"Edit name"},
            {kind:"playlist_edit_add", label:"Add songs"},
            {kind:"playlist_edit_remove", label:"Remove songs"},
            {kind:"playlist_edit_delete", label:"Delete playlist"}
          ]);
        }
      }
    }, !!push);
  }



  async function viewPlaylistDeleteConfirm(root, playlistRel, playlistLabel, returnKind, push){
    showNowPlaying(false);
    await setView({
      kind: "playlist_delete_confirm",
      label: "Delete",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      returnKind: returnKind || "",
      load: async function(){
        resetList([
          {kind:"info", label:"Are you sure?"},
          {kind:"playlist_delete_no", label:"No"},
          {kind:"playlist_delete_yes", label:"Yes"}
        ]);
      }
    }, !!push);
  }

  async function confirmDeletePlaylist(){
    const cur = state.current || {};
    if(cur.kind !== "playlist_delete_confirm" || !cur.root || !cur.root.id) return;
    try{
      const res = await apiPost("/api/library/playlist_delete", {root_id: cur.root.id, rel: cur.playlistRel || ""});
      const js = (res && res.json) ? res.json : {};
      if(!res || !res.ok || !js.ok){
        alert(String((js && js.error) ? js.error : "Failed to delete playlist"));
        return;
      }
      state.history = [];
      await viewMetaList(cur.root, "playlists", "", "Playlists", false);
    }catch(e){
      alert(String(e && e.message ? e.message : e));
    }
  }

  async function playlistAddSongsToCurrentView(rels){
    const cur = state.current || {};
    const root = cur.root || null;
    const playlistRel = String(cur.playlistRel || "");
    if(!root || !root.id || !playlistRel) return false;
    const clean = Array.isArray(rels) ? rels.map(x=>String(x || "")).filter(Boolean) : [];
    if(!clean.length) return false;
    const res = await apiPost("/api/library/playlist_add", {root_id: root.id, rel: playlistRel, tracks: clean});
    const js = (res && res.json) ? res.json : {};
    if(!res || !res.ok || !js.ok){
      throw new Error((js && js.error) ? js.error : "Failed to add songs");
    }
    return true;
  }


  function playlistBrowseStartRel(playlistRel){
    const rel = String(playlistRel || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    if(!rel) return "";
    const lower = rel.toLowerCase();
    if(lower === "debripod-playlists" || lower.startsWith("debripod-playlists/") || lower === "debripod-smartplaylists" || lower.startsWith("debripod-smartplaylists/")){
      return "";
    }
    const idx = rel.lastIndexOf("/");
    if(idx < 0) return "";
    const out = rel.slice(0, idx).replace(/^\/+|\/+$/g, "");
    if(!out || out.toLowerCase() === "debripod-playlists") return "";
    return out;
  }

  async function viewPlaylistAddSongs(root, playlistRel, rel, push){
    showNowPlaying(false);
    const prevAdded = (state.current && state.current.kind === "playlist_add" && state.current._added instanceof Set) ? state.current._added : null;
    await setView({
      kind: "playlist_add",
      label: "Add songs",
      root: root,
      playlistRel: playlistRel || "",
      rel: rel || "",
      _added: prevAdded || new Set(),
      load: async function(){
        const url = "/api/library/browse?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.rel || "");
        const js = await apiGet(url);
        const items = [];
        if(this.rel){
          items.push({kind:"up", label:".."});
        }
        const dirs = [];
        const songs = [];
        for(const e of (js.entries || [])){
          if(e.type === "dir"){
            dirs.push({kind:"playlist_add_dir", label:e.name, rel:e.rel, root: root});
          }else if(e.type === "file" && e.media === "audio"){
            const relv = String(e.rel || "");
            const added = !!(this._added && this._added.has(relv));
            songs.push({kind:"playlist_add_file", label:e.name, rel:relv, root:root, media:"audio", selectable:true, selected:added});
          }
        }
        if(songs.length){
          const addedCount = songs.filter(x => x && x.selected).length;
          items.push({kind:"playlist_add_selectall", label:"Select all", badge: addedCount ? (String(addedCount) + " added") : String(songs.length)});
        }
        for(const d of dirs) items.push(d);
        for(const s of songs) items.push(s);
        if(!dirs.length && !songs.length){
          items.push({kind:"info", label:"No songs found"});
        }
        resetList(items);
      }
    }, !!push);
  }

  function refreshPlaylistRemoveSelectionUI(){
    const cur = state.current || {};
    if(!cur || cur.kind !== "playlist_remove") return;
    const selected = (cur.selected instanceof Set) ? cur.selected : new Set();
    let trackCount = 0;
    let selectedCount = 0;
    for(const it of (state.items || [])){
      if(!it) continue;
      if(it.kind === "playlist_remove_track"){
        trackCount += 1;
        const relv = String(it.rel || "");
        const on = !!(relv && selected.has(relv));
        it.selected = on;
        if(on) selectedCount += 1;
      }else if(it.kind === "playlist_remove_selectall"){
        it.badge = selectedCount ? String(selectedCount) : (trackCount ? String(trackCount) : "");
      }else if(it.kind === "playlist_remove_commit"){
        it.badge = selectedCount ? String(selectedCount) : "";
      }
    }
    renderList();
  }

  async function viewPlaylistRemoveSongs(root, playlistRel, playlistLabel, push){
    showNowPlaying(false);
    const prevSelected = (state.current && state.current.kind === "playlist_remove" && state.current.selected instanceof Set) ? state.current.selected : null;
    await setView({
      kind: "playlist_remove",
      label: "Remove songs",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      selected: prevSelected || new Set(),
      load: async function(){
        const js = await apiGet("/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=playlist_tracks&value=" + encodeURIComponent(this.playlistRel || ""));
        const items = [];
        const tracks = [];
        for(const it of (js.items || [])){
          if(!it || it.kind !== "track") continue;
          const relv = String(it.rel || "");
          tracks.push({kind:"playlist_remove_track", label:String(it.label || "Track"), rel:relv, root:root, badge:String(it.badge || ""), selectable:true, selected:!!(this.selected && this.selected.has(relv))});
        }
        if(tracks.length){
          items.push({kind:"playlist_remove_selectall", label:"Select all", badge:(this.selected && this.selected.size) ? String(this.selected.size) : ""});
          items.push({kind:"playlist_remove_commit", label:"Remove selected", badge:(this.selected && this.selected.size) ? String(this.selected.size) : ""});
        }
        for(const tr of tracks) items.push(tr);
        if(!tracks.length){
          items.push({kind:"info", label:"No songs found"});
        }
        resetList(items);
      }
    }, !!push);
  }
