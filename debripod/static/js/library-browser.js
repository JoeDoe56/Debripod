  function folderViewObj(root, rel, label){
    return {
      kind: "folder",
      label: label || (rel ? rel.split("/").slice(-1)[0] : ""),
      root: root,
      rel: rel || "",
      load: async function(){
        const url = "/api/library/browse?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.rel);
        let js = null;
        try{
          js = await apiGet(url);
        }catch(e){
          if(await restoreCachedLibraryView({kind:"folder", root:root, rel:this.rel, label:this.label})) return;
          throw e;
        }
        const items = [];
        for(const e of (js.entries || [])){
          if(e.type === "dir"){
            items.push({kind:"dir", label:e.name, rel:e.rel, root: root});
          }else if(e.type === "file"){
            const mediaPill = e.media === "video" ? "video" : (e.media === "audio" ? "audio" : "");
            const pills = mediaPill ? [mediaPill] : [];
            items.push({kind:"file", label:e.name, pills: pills, rel:e.rel, root: root, media: e.media});
          }
        }
        resetList(items);
      }
    };
  }

  async function restoreCachedLibraryView(desc){
    try{
      if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.restoreCachedView){
        return await DebriPod.clientSync.restoreCachedView(desc || {});
      }
    }catch(e){}
    return false;
  }

  async function openNowFolder(options){
    const opts = options || {};
    if(opts.ordinaryOrigin && window.DebriPod && DebriPod.navigationController){
      try{
        await DebriPod.navigationController.restoreOrdinaryOrigin(opts.ordinaryOrigin);
        const rootId = state.now && state.now.rootId ? String(state.now.rootId) : "";
        const rel = state.now && state.now.rel ? String(state.now.rel) : "";
        const index = (state.items || []).findIndex((item)=>item && item.rel === rel && item.root && String(item.root.id) === rootId);
        if(index >= 0){
          state.sel = index;
          renderList();
          return;
        }
      }catch(e){}
    }
    if(!state.now){
      showNowPlaying(false);
      await showRoots();
      return;
    }
    try{
      const nav = (state.now && state.now.nav) || state.nowNavContext || (state.playbackSession && state.playbackSession.nav) || null;
      if(nav && nav.root_id && nav.kind){
        await openNavContext(nav);
        const nowRel = state.now && state.now.rel ? state.now.rel : "";
        const nowRoot = state.now && state.now.rootId ? state.now.rootId : "";
        try{
          const idx = (state.items || []).findIndex(x => x && x.rel === nowRel && x.root && x.root.id === nowRoot);
          if(idx >= 0){
            state.sel = idx;
            renderList();
          }
        }catch(e){}
        return;
      }
    }catch(e){}
    const cfg = await loadConfig();
    const root = (cfg.roots || []).find(r => r.id === state.now.rootId);
    if(!root){
      showNowPlaying(false);
      await showRoots();
      return;
    }

    let folderRel = "";
    try{
      const parts = (state.now.rel || "").split("/");
      parts.pop();
      folderRel = parts.join("/");
    }catch(e){ folderRel = ""; }

    state.root = root;

    showNowPlaying(false);
    await setView(folderViewObj(root, folderRel, folderRel ? folderRel.split("/").slice(-1)[0] : ""), false);
    try{
      const idx = (state.items || []).findIndex(x => x && x.rel === state.now.rel && x.root && x.root.id === root.id);
      if(idx >= 0){
        state.sel = idx;
        renderList();
      }
    }catch(e){}
  }

  
  function persistedNowRootId(entry){
    return String((entry && (entry.root_id || entry.rootId || (entry.root && entry.root.id))) || "");
  }

  function persistedNowRel(entry){
    return String((entry && entry.rel) || "");
  }

  function persistedNowMedia(entry){
    const media = String((entry && entry.media) || "").toLowerCase();
    return media === "video" ? "video" : "audio";
  }

  function persistedNowMeta(entry){
    const meta = (entry && entry.meta && typeof entry.meta === "object") ? entry.meta : {};
    return Object.assign({}, meta, {
      label: entry && entry.label ? String(entry.label || "") : (meta.label || ""),
      title: entry && entry.title ? String(entry.title || "") : (meta.title || ""),
      artist: entry && entry.artist ? String(entry.artist || "") : (meta.artist || ""),
      album: entry && entry.album ? String(entry.album || "") : (meta.album || ""),
      art: entry && entry.art ? String(entry.art || "") : (meta.art || ""),
      streamed: !!(entry && entry.streamed),
      source: String((entry && entry.source) || meta.source || ""),
      ext: String((entry && entry.ext) || meta.ext || ""),
      quality: String((entry && entry.quality) || meta.quality || "")
    });
  }

  function serverNowMatches(rootId, rel, media){
    const sn = state.serverNow || null;
    return !!(sn && String(sn.root_id || "") === String(rootId || "") && String(sn.rel || "") === String(rel || "") && (!media || String(sn.media || media).toLowerCase() === String(media || "").toLowerCase()));
  }

  function persistedNowPosition(entry, media){
    try{
      const rootId = persistedNowRootId(entry);
      const rel = persistedNowRel(entry);
      if(serverNowMatches(rootId, rel, media) && state.serverNow && isFinite(state.serverNow.position)){
        return Math.max(0, Number(state.serverNow.position || 0));
      }
      if(entry && isFinite(entry.position)) return Math.max(0, Number(entry.position || 0));
    }catch(e){}
    return 0;
  }

  function persistedNowItem(entry, media){
    const meta = persistedNowMeta(entry);
    const rootId = persistedNowRootId(entry);
    const rel = persistedNowRel(entry);
    if(!rootId || !rel) return null;
    return {
      kind:"file",
      media:media || persistedNowMedia(entry),
      root:{id:rootId},
      rel:rel,
      label: meta.label || meta.title || rel.split("/").slice(-1)[0] || "",
      streamed: !!meta.streamed,
      source: meta.source || "",
      ext: meta.ext || "",
      quality: meta.quality || ""
    };
  }

  function persistedQueueItems(media, entry){
    const fallbackItem = persistedNowItem(entry, media);
    let queue = null;
    let index = -1;
    try{
      const sess = ensurePlaybackSession();
      if(sess && Array.isArray(sess.queue) && sess.queue.length){
        queue = sess.queue;
        index = isFinite(sess.queueIndex) ? Number(sess.queueIndex) : -1;
      }
    }catch(e){}
    try{
      const sn = state.serverNow || null;
      if((!queue || !queue.length) && sn && sn.playlist && Array.isArray(sn.playlist.items) && sn.playlist.items.length){
        queue = sn.playlist.items;
        index = isFinite(sn.playlist.index) ? Number(sn.playlist.index) : -1;
      }
    }catch(e){}
    let items = normalizePlaybackQueue(queue || [], media).map((it)=>({
      kind:"file",
      media:String(it.media || media || "audio"),
      root:{id:(it.root && it.root.id) || it.root_id || it.rootId || ""},
      rel:it.rel || "",
      label:it.label || "",
      streamed:!!it.streamed,
      source:it.source || "",
      ext:it.ext || "",
      quality:it.quality || ""
    })).filter(x=>x.root.id && x.rel);
    if(!items.length && fallbackItem) items = [fallbackItem];
    if(items.length){
      const rootId = persistedNowRootId(entry);
      const rel = persistedNowRel(entry);
      const found = items.findIndex(x=>x && x.root && x.root.id === rootId && x.rel === rel);
      if(found >= 0) index = found;
      index = Math.max(0, Math.min(items.length - 1, index >= 0 ? index : 0));
    }else{
      index = -1;
    }
    return {items:items, index:index};
  }

  function persistedNowEntry(){
    try{
      const sess = ensurePlaybackSession();
      if(sess && sess.now && persistedNowRootId(sess.now) && persistedNowRel(sess.now)) return sess.now;
    }catch(e){}
    const sn = state.serverNow || null;
    if(sn && sn.root_id && sn.rel) return sn;
    return null;
  }

  async function resumePersistedPlayback(forceShow, options){
    const opts = options || {};
    if(opts.sync !== false) await syncPlaybackFromServer();
    const entry = persistedNowEntry();
    if(!entry || !persistedNowRootId(entry) || !persistedNowRel(entry)) return false;
    const media = persistedNowMedia(entry);
    const item = persistedNowItem(entry, media);
    if(!item) return false;
    const resumeAt = persistedNowPosition(entry, media);
    try{
      const meta = persistedNowMeta(entry);
      state.nowMeta = Object.assign({}, state.nowMeta || {}, meta);
      state.nowNavContext = (entry && entry.nav) || (state.playbackSession && state.playbackSession.nav) || state.nowNavContext || null;
    }catch(e){}
    if(media === "video"){
      const q = persistedQueueItems("video", entry);
      const canonical = window.DebriPod && DebriPod.playbackQueue;
      if(canonical) canonical.replaceFromPlayableList(q.items.length ? q.items : [item], item);
      await startVideoFromItem(item, !!forceShow, resumeAt);
      return true;
    }
    const q = persistedQueueItems("audio", entry);
    const canonical = window.DebriPod && DebriPod.playbackQueue;
    if(canonical) canonical.replaceFromPlayableList(q.items.length ? q.items : [item], item);
    await startAudioFromItem(item, q.items.length ? q.items : [item], q.index >= 0 ? q.index : 0, !!forceShow, resumeAt);
    return true;
  }

  async function resumeFromServerNow(forceShow){
    const resumed = await resumePersistedPlayback(forceShow, {sync:true});
    if(!resumed){
      if(forceShow){
        showNowPlaying(false);
        await showRoots();
      }
      return;
    }
  }


async function goBack(){
    if(typeof rangeEditorCancelActive === "function" && rangeEditorCancelActive()){
      return;
    }
    const navigationController = window.DebriPod && DebriPod.navigationController;
    if(navigationController && navigationController.isActive && navigationController.isActive()){
      await navigationController.back();
      return;
    }
    if(state.history.length){
      await runLibraryPageTransition(async ()=>{
        state.current = state.history.pop();
        setHeader();
        try{
          await state.current.load();
        }catch(loadErr){
          let restored = false;
          try{ restored = await restoreCachedLibraryView(state.current); }catch(e){ restored = false; }
          if(!restored) throw loadErr;
        }
        if(state.pendingLibSearch && state.current && state.current.kind === "libsearch"){
          const p = state.pendingLibSearch;
          state.pendingLibSearch = null;
          try{
            if(p && p.q) state.libSearch.q = p.q;
            const inQ = document.getElementById("libSearchInput");
            if(inQ && p && p.q) inQ.value = p.q;
            if(p && p.engine && p.q){
              await libDoSearch(p.engine, p.q);
            }
          }catch(e){}
        }
      });
      return;
    }
    await runLibraryPageTransition(async ()=>{
      try{
        await showRoots();
      }catch(loadErr){
        const restored = await restoreCachedLibraryView({kind:"roots"});
        if(!restored) throw loadErr;
      }
    });
  }

  function buildPlaylistFromItems(items){
    const pl = [];
    for(const it of items){
      if(it.kind === "track" || (it.kind === "file" && it.media === "audio")){
        pl.push(it);
      }
    }
    return pl;
  }

  function buildVideoPlaylistFromItems(items){
    const pl = [];
    for(const it of items){
      if(it && it.kind === "file" && it.media === "video"){
        pl.push(it);
      }
    }
    return pl;
  }

  async function refreshNowPlayingMeta(item){
    if(!item) return;
    const rootId = item.root.id;
    const rel = item.rel;

    try{
      const meta = Object.assign({}, await apiGet("/api/library/filemeta?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel)), {streamed: !!item.streamed, source: item.source || "", ext: item.ext || "", quality: item.quality || ""});
      state.now = {rootId: rootId, rel: rel, media: "audio", streamed: !!item.streamed};
      state.nowMeta = meta;
      try{ loadVisualizerAnalysisForTrack(rootId, rel, "audio", {streamed: !!item.streamed}); }catch(err){}
      saveResumeNowPlaying();
      await updateNowPlayingDisplay(meta, item.label || "Track", {animateArt: true, animatePill: true});
      playbackPillActivity(false, "audio metadata");
      updateMediaSession({title: meta.title, artist: meta.artist, album: meta.album, art: meta.art});
      try{ syncMediaSessionControls(); }catch(e){}
      lastfmOnTrack(meta);
    }catch(e){}
  }
  var videoOverlayActive = false;


  function isVideoActive(){
    try{
      return !!(videoOverlayActive && npVideoOverlay && npVideo && npVideoOverlay.style.display !== "none" && npVideo.src);
    }catch(e){ return false; }
  }

  function wheelMedia(){
    return isVideoActive() ? npVideo : activeAudio;
  }

  function stopVideoOverlay(){
    if(!npVideoOverlay || !npVideo) return;

    // Only write playback state when a real video overlay is active.
    const wasActive = isVideoActive();

    if(wasActive){
      let d = 0;
      let t = 0;
      try{ d = (npVideo && npVideo.duration && isFinite(npVideo.duration)) ? Number(npVideo.duration) : 0; }catch(e){ d = 0; }
      try{ t = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0; }catch(e){ t = 0; }
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "stop");
        }
      }catch(e){}
    }

    videoOverlayActive = false;
    try{ npVideo.pause(); }catch(e){}
    try{
      npVideo.removeAttribute("src");
      npVideo.load();
    }catch(e){}
    try{ npVideoOverlay.style.display = "none"; }catch(e){}
  }



  async function startVideoFromItem(item, forceShow, resumeTime){
    if(typeof forceShow !== "boolean") forceShow = true;
    syncCanonicalPlaybackStart(item, state.videoPlaylist && state.videoPlaylist.length ? state.videoPlaylist : (state.items || []), forceShow);
    const playbackNav = captureNavContext();
    const sourceView = captureSourceViewContext(item, state.videoPlaylist && state.videoPlaylist.length ? state.videoPlaylist : (state.items || []), state.videoIndex >= 0 ? state.videoIndex : 0);
    if(forceShow) openNowPlayingExplicit();

    try{ if(activeAudio) activeAudio.pause(); }catch(e){}
    resetGaplessPrime();
    destroyHlsController("audio");

    if(npVideoOverlay) npVideoOverlay.style.display = "flex";
    videoOverlayActive = true;

    const rootId = item.root.id;
    const rel = item.rel;
    if(!(resumeTime > 0)){
      const key = String(rootId || "") + "::" + String(rel || "").replace(/\\/g, "/").replace(/^\/+/, "");
      const saved = state.serverMediaProgress && state.serverMediaProgress[key];
      resumeTime = Number((saved && saved.position) || item.position || 0);
    }

    try{
      if(isVideoActive() && state.now && state.now.media === "video" && state.now.rootId === rootId && state.now.rel === rel){
        const rt0 = (resumeTime && isFinite(resumeTime)) ? Number(resumeTime) : 0;
        if(rt0 > 0){
          try{ setTimeout(()=>{ resumeVideoViaSeekInputs(rt0); }, 200); }catch(e){}
        }
        if(forceShow) openNowPlayingExplicit();
        return;
      }
    }catch(e){}

    let meta = {};
    try{
      meta = Object.assign({}, await apiGet("/api/library/filemeta?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel)), {streamed: !!item.streamed, source: item.source || "", ext: item.ext || "", quality: item.quality || ""});
    }catch(e){ meta = {}; }
    try{
      if(!meta.art){
        meta.art = String(item.art || item.thumbnail || item.poster || "");
      }
    }catch(e){}

    state.now = {rootId: rootId, rel: rel, media: "video", streamed: !!item.streamed, nav: playbackNav};
    state.nowNavContext = playbackNav;
    state.nowMeta = meta;
    try{
      let vq = Array.isArray(state.videoPlaylist) && state.videoPlaylist.length ? state.videoPlaylist : buildVideoPlaylistFromItems(state.items || []);
      if(!vq.length) vq = [item];
      let vi = vq.findIndex(x => x && x.rel === rel && x.root && x.root.id === rootId);
      if(vi < 0) vi = state.videoIndex >= 0 ? state.videoIndex : 0;
      buildPlaybackSessionUpdate({now:Object.assign({}, state.now, {meta:meta}), queue:vq, queueIndex:vi, nav:playbackNav, sourceView:sourceView, media:"video"}, "playback-start");
    }catch(e){}
    try{ loadVisualizerAnalysisForTrack(rootId, rel, "video", {streamed: !!item.streamed}); }catch(err){}
    visualizerVideoSampleLastTs = 0;
    saveResumeNowPlaying();

    await updateNowPlayingDisplay(meta, item.label || "Video", {animateArt: true, animatePill: true});
    if(forceShow) openNowPlayingExplicit();
    updateMediaSession({title: meta.title || item.label || "Video", artist: meta.artist || "", album: meta.album || "", art: meta.art || ""});
    try{ syncMediaSessionControls(); }catch(e){}

    try{
      try{ npVideo.pause(); }catch(e){}
      destroyHlsController("video");
      npVideo.removeAttribute("src");
      try{ npVideo.load(); }catch(e){}
      try{
        if(meta && meta.art) npVideo.poster = meta.art;
        else npVideo.removeAttribute("poster");
      }catch(e){}
      applyVolume();
      await loadPlaybackIntoElement(npVideo, rootId, rel, "video");

      const rt = (resumeTime && isFinite(resumeTime)) ? Number(resumeTime) : 0;
      try{
        const pos0 = (rt > 0) ? rt : ((npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0);
        playbackMaybePost("video", rootId, rel, meta || {}, (pos0 || 0), null, true, "start");
      }catch(e){}

      const p = npVideo.play();
      try{ if(rt > 0) scheduleVideoResume(rt); }catch(e){}
      if(p && p.catch) p.catch((err)=>{ warnMedia("video", "play rejected" + (err && err.name ? " (" + err.name + ")" : ""), npVideo); });
    }catch(e){
      warnMedia("video", "start failed" + (e && e.name ? " (" + e.name + ")" : ""), npVideo);
    }
  }



  async function startAudioFromItem(item, playlist, index, forceShow, resumeTime){
    if(typeof forceShow !== "boolean") forceShow = true;
    syncCanonicalPlaybackStart(item, playlist || state.playlist || state.items || [], forceShow);
    const playbackNav = captureNavContext();
    const sourceView = captureSourceViewContext(item, playlist || state.playlist || state.items || [], (typeof index === "number" ? index : state.playIndex));
    stopVideoOverlay();
    const rootId = item.root.id;
    const rel = item.rel;

    const same = state.now && state.now.rootId === rootId && state.now.rel === rel;
    if(same){
      try{
        buildPlaybackSessionUpdate({now:Object.assign({}, state.now, {nav:playbackNav, meta:state.nowMeta || {}}), queue:state.playlist, queueIndex:state.playIndex, nav:playbackNav, sourceView:sourceView, media:"audio"}, "playback-start");
      }catch(e){}
      ensurePlayOrder(false);
      const hasPlayableSource = !!(activeAudio && (activeAudio.currentSrc || activeAudio.src));
      if(!hasPlayableSource){
        try{ replaceNowPlaying(null, "explicit-clear"); }catch(e){}
        state.now = null;
        state.nowMeta = null;
      }else{
      if(forceShow) openNowPlayingExplicit();

      const meta = Object.assign({}, state.nowMeta || {}, {streamed: !!item.streamed, source: item.source || "", ext: item.ext || "", quality: item.quality || ""});
      try{ loadVisualizerAnalysisForTrack(rootId, rel, "audio", {streamed: !!item.streamed}); }catch(err){}
      await updateNowPlayingDisplay(meta, item.label || "Track", {animateArt: false, animatePill: false});
      if(forceShow) openNowPlayingExplicit();
      updateMediaSession({title: meta.title, artist: meta.artist, album: meta.album, art: meta.art});
      try{ syncMediaSessionControls(); }catch(e){}
      lastfmOnTrack(meta);

      try{ applyVolume(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}

      let playlistCtx = null;
      try{
        if(Array.isArray(state.playlist) && state.playlist.length){
          const items = state.playlist.slice(0, 500).map(it=>({
            root_id: (it.root && it.root.id) ? it.root.id : "",
            rel: it.rel || "",
            media: "audio",
            label: it.label || ""
          })).filter(x=>x.root_id && x.rel);
          playlistCtx = {items: items, index: (state.playIndex >= 0 ? state.playIndex : 0)};
        }
      }catch(e){ playlistCtx = null; }

      playbackPost({
        media: "audio",
        root_id: rootId,
        rel: rel,
        playlist: playlistCtx,
        label: item.label || "",
        title: meta.title || "",
        artist: meta.artist || "",
        album: meta.album || "",
        art: meta.art || "",
        position: (activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0,
        duration: (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : null,
        playing: (activeAudio && !activeAudio.paused),
        nav: playbackNav,
        source_view: sourceView,
        event: "time"
      });

      preloadNextAudio();
      return;
      }
    }

    if(forceShow) openNowPlayingExplicit();

    const meta = await apiGet("/api/library/filemeta?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel));

    try{ if(activeAudio) activeAudio.pause(); }catch(e){}
    destroyHlsController("audio");
    resetGaplessPrime();
    try{ activeAudio.removeAttribute("src"); activeAudio.load(); }catch(e){}

    try{ applyVolume(); }catch(e){}
    try{ enforceSingleAudio(); }catch(e){}

    await loadPlaybackIntoElement(activeAudio, rootId, rel, "audio");

    const rt = (resumeTime && isFinite(resumeTime)) ? Number(resumeTime) : 0;
    if(rt > 0){
      try{
        await new Promise((resolve)=>{
          let done = false;
          const finish = ()=>{
            if(done) return;
            done = true;
            try{ activeAudio.removeEventListener("loadedmetadata", onMeta); }catch(e){}
            resolve();
          };
          const onMeta = ()=>finish();
          activeAudio.addEventListener("loadedmetadata", onMeta, {once:true});
          setTimeout(finish, 1200);
        });
        const maxT = (activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : rt;
        activeAudio.currentTime = Math.max(0, Math.min(rt, maxT));
      }catch(e){}
    }

    ensurePlayOrder(false);

    state.now = {rootId: rootId, rel: rel, media: "audio", streamed: !!item.streamed, nav: playbackNav};
    state.nowNavContext = playbackNav;
    state.nowMeta = meta;
    try{
      buildPlaybackSessionUpdate({now:Object.assign({}, state.now, {meta:meta}), queue:state.playlist, queueIndex:state.playIndex, nav:playbackNav, sourceView:sourceView, media:"audio"}, "playback-start");
    }catch(e){}
    try{ loadVisualizerAnalysisForTrack(rootId, rel, "audio", {streamed: !!item.streamed}); }catch(err){}
    saveResumeNowPlaying();

    let playlistCtx = null;
    try{
      if(Array.isArray(state.playlist) && state.playlist.length){
        const items = state.playlist.slice(0, 500).map(it=>({
          root_id: (it.root && it.root.id) ? it.root.id : "",
          rel: it.rel || "",
          media: "audio",
          label: it.label || ""
        })).filter(x=>x.root_id && x.rel);
        playlistCtx = {items: items, index: (state.playIndex >= 0 ? state.playIndex : 0)};
      }
    }catch(e){ playlistCtx = null; }

    playbackPost({
      media: "audio",
      root_id: rootId,
      rel: rel,
      playlist: playlistCtx,
      label: item.label || "",
      title: meta.title || "",
      artist: meta.artist || "",
      album: meta.album || "",
      art: meta.art || "",
      position: (rt && isFinite(rt)) ? rt : 0,
      duration: (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : (meta && meta.duration ? meta.duration : null),
      playing: true,
      nav: playbackNav,
      source_view: sourceView,
      event: "start"
    });

    await updateNowPlayingDisplay(meta, item.label || "Track", {animateArt: true, animatePill: true});
    if(forceShow) openNowPlayingExplicit();
    updateMediaSession({title: meta.title, artist: meta.artist, album: meta.album, art: meta.art});
    try{ syncMediaSessionControls(); }catch(e){}
    lastfmOnTrack(meta);

    try{ ensurePlaybackAudioSession(); }catch(e){}
    try{
      await activeAudio.play();
      if(canMediaSession()) navigator.mediaSession.playbackState = "playing";
    }catch(e){
      warnMedia("audio", "play rejected" + (e && e.name ? " (" + e.name + ")" : ""), activeAudio);
      if(canMediaSession()) navigator.mediaSession.playbackState = "paused";
    }

    setTimeout(()=>{ try{ preloadNextAudio(); }catch(e){} }, 250);
  }

  async function togglePlay(){
    try{
      const hasAudioSource = !!(activeAudio && (activeAudio.currentSrc || activeAudio.src));
      if(!isVideoActive() && (!state.now || !hasAudioSource)){
        const resumed = await resumePersistedPlayback(false, {sync:true});
        if(resumed) return;
      }
    }catch(e){}
    if(!isVideoActive() && !state.now) return;
    const m = wheelMedia();
    if(!m) return;
    if(m.paused){

      try{
        const p = m.play();
        if(p && p.catch) p.catch((err)=>{ warnMedia(isVideoActive() ? "video" : "audio", "play rejected" + (err && err.name ? " (" + err.name + ")" : ""), m); });
      }catch(e){
        warnMedia(isVideoActive() ? "video" : "audio", "play failed" + (e && e.name ? " (" + e.name + ")" : ""), m);
      }
      if(!isVideoActive() && canMediaSession()) navigator.mediaSession.playbackState = "playing";
      try{ syncMediaSessionControls(); }catch(e){}
    }else{
      try{ m.pause(); }catch(e){}
      if(!isVideoActive() && canMediaSession()) navigator.mediaSession.playbackState = "paused";
      try{ syncMediaSessionControls(); }catch(e){}
    }
  }

  function seek(delta){
    if(nowPlaying.style.display !== "block") return;
    const m = wheelMedia();
    if(!m) return;
    const d = m.duration || 0;
    const t = m.currentTime || 0;
    const nt = Math.max(0, Math.min(d || (t + delta), t + delta));
    try{ m.currentTime = nt; }catch(e){}
    if(seekMode){
      seekPreview = nt;
      seekChanged = true;
      updateSeekIndicator();
      resetSeekIdle();
    }
  }

  function ensurePlayOrder(forceRebuild){
    if(!state.shuffleEnabled){
      state.playOrder = null;
      state.orderPos = 0;
      state.playOrderPlaylist = null;
      return;
    }
    const pl = state.playlist || [];
    const n = pl.length || 0;
    if(n <= 0){
      state.playOrder = [];
      state.orderPos = 0;
      state.playOrderPlaylist = pl;
      return;
    }
    const idx = (typeof state.playIndex === "number" && state.playIndex >= 0 && state.playIndex < n) ? state.playIndex : 0;

    const same = (!forceRebuild &&
      state.playOrderPlaylist === pl &&
      Array.isArray(state.playOrder) &&
      state.playOrder.length === n);

    if(same){
      const p = state.playOrder.indexOf(idx);
      if(p >= 0){
        state.orderPos = p;
        return;
      }
    }

    const rest = [];
    for(let i=0;i<n;i++){
      if(i !== idx) rest.push(i);
    }
    for(let i=rest.length-1;i>0;i--){
      const j = Math.floor(Math.random() * (i + 1));
      const tmp = rest[i];
      rest[i] = rest[j];
      rest[j] = tmp;
    }
    state.playOrder = [idx].concat(rest);
    state.orderPos = 0;
    state.playOrderPlaylist = pl;
  }

  function nextIndexPeek(){
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const p = (state.orderPos || 0) + 1;
      if(p < state.playOrder.length) return state.playOrder[p];
      return null;
    }
    const ni = (state.playIndex || 0) + 1;
    if(ni >= 0 && ni < state.playlist.length) return ni;
    return null;
  }

  function prevIndexPeek(){
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const p = (state.orderPos || 0) - 1;
      if(p >= 0 && p < state.playOrder.length) return state.playOrder[p];
      return null;
    }
    const pi = (state.playIndex || 0) - 1;
    if(pi >= 0 && pi < state.playlist.length) return pi;
    return null;
  }

  function setShuffleEnabled(on){
    const nextOn = !!on;
    try{
      const canonical = window.DebriPod && DebriPod.playbackQueue;
      if(canonical && canonical.state.shuffle !== nextOn) canonical.setShuffle(nextOn);
    }catch(e){}
    if(nextOn){
      try{
        if((!Array.isArray(state.playlist) || state.playlist.length <= 1) && state.playbackSession && Array.isArray(state.playbackSession.queue) && state.playbackSession.queue.length > 1){
          const canonicalQueue = window.DebriPod && DebriPod.playbackQueue;
          if(canonicalQueue) canonicalQueue.restoreFromPlaybackSession(state.playbackSession);
        }
        const needsQueue = !Array.isArray(state.playlist) || state.playlist.length <= 1;
        const canUseCurrentList = !(state.current && (state.current.kind === "history" || state.current.kind === "playback_queue"));
        if(needsQueue && canUseCurrentList && state.now && state.now.media !== "video"){
          const pl = buildPlaylistFromItems(state.items || []);
          const idx = pl.findIndex(x => x && x.rel === state.now.rel && x.root && x.root.id === state.now.rootId);
          if(pl.length > 1 && idx >= 0){
            const canonicalQueue = window.DebriPod && DebriPod.playbackQueue;
            if(canonicalQueue) canonicalQueue.replaceFromPlayableList(pl, pl[idx]);
          }
        }
      }catch(e){}
    }
    state.shuffleEnabled = nextOn;
    try{ localStorage.setItem("debripod_shuffle", state.shuffleEnabled ? "1" : "0"); }catch(e){}
    if(state.shuffleEnabled) ensurePlayOrder(true);
    else{
      state.playOrder = null;
      state.orderPos = 0;
      state.playOrderPlaylist = null;
    }
    preloadNextAudio();
    try{
      if(state.playbackSession && Array.isArray(state.playlist) && state.playlist.length){
        buildPlaybackSessionUpdate({now:state.playbackSession.now || state.now, queue:state.playlist, queueIndex:state.playIndex, nav:state.nowNavContext || state.playbackSession.nav || null, sourceView:state.playbackSession.sourceView || null, media:"audio"}, "shuffle-toggle");
      }
    }catch(e){}
    updateWheelLabels();
  }

  function toggleShuffle(){
    setShuffleEnabled(!state.shuffleEnabled);
  }

  async function playIndex(i, forceShow){
    if(i < 0 || i >= state.playlist.length) return;
    if(typeof forceShow !== "boolean") forceShow = (nowPlaying.style.display === "block");
    const item = state.playlist[i];
    await startAudioFromItem(item, state.playlist, i, forceShow);
  }

  function playNext(){
    const canonical = window.DebriPod && DebriPod.playbackQueue;
    if(canonical && canonical.hasItems()){
      canonical.next();
      return;
    }
    if(isSearchStreamActive()){
      const ni = (state.streamQueueIndex || 0) + 1;
      if(ni >= 0 && ni < state.streamQueue.length){
        playStreamQueueIndex(ni, true);
      }
      return;
    }
    if(!state.playlist.length) return;
    const ni = nextIndexPeek();
    if(ni === null) return;
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const np = (state.orderPos || 0) + 1;
      if(np >= 0 && np < state.playOrder.length) state.orderPos = np;
    }
    playIndex(ni);
  }

  function playPrev(){
    const canonical = window.DebriPod && DebriPod.playbackQueue;
    if(canonical && canonical.hasItems()){
      canonical.previous();
      return;
    }
    if(isSearchStreamActive()){
      const pi = (state.streamQueueIndex || 0) - 1;
      if(pi >= 0 && pi < state.streamQueue.length){
        playStreamQueueIndex(pi, true);
      }
      return;
    }
    if(!state.playlist.length) return;
    const pi = prevIndexPeek();
    if(pi === null) return;
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const pp = (state.orderPos || 0) - 1;
      if(pp >= 0 && pp < state.playOrder.length) state.orderPos = pp;
    }
    playIndex(pi);
  }


  function playVideoIndex(i, forceShow, resumeTime){
    try{
      if(!Array.isArray(state.videoPlaylist) || !state.videoPlaylist.length) return;
      if(i < 0 || i >= state.videoPlaylist.length) return;
      const it = state.videoPlaylist[i];
      startVideoFromItem(it, (typeof forceShow === "boolean" ? forceShow : true), (resumeTime || 0));
    }catch(e){}
  }

  function playVideoNext(){
    const canonical = window.DebriPod && DebriPod.playbackQueue;
    if(canonical && canonical.hasItems()){
      canonical.next();
      return;
    }
    try{
      if(!Array.isArray(state.videoPlaylist) || !state.videoPlaylist.length){
        const candidates = buildVideoPlaylistFromItems(state.items || []);
        if(canonical) canonical.replaceFromPlayableList(candidates, candidates[0] || null);
      }
      const ni = (state.videoIndex || 0) + 1;
      if(ni >= 0 && ni < state.videoPlaylist.length){
        playVideoIndex(ni, true, 0);
      }
    }catch(e){}
  }

  function playVideoPrev(){
    const canonical = window.DebriPod && DebriPod.playbackQueue;
    if(canonical && canonical.hasItems()){
      canonical.previous();
      return;
    }
    try{
      if(!Array.isArray(state.videoPlaylist) || !state.videoPlaylist.length){
        const candidates = buildVideoPlaylistFromItems(state.items || []);
        if(canonical) canonical.replaceFromPlayableList(candidates, candidates[0] || null);
      }
      const pi = (state.videoIndex || 0) - 1;
      if(pi >= 0 && pi < state.videoPlaylist.length){
        playVideoIndex(pi, true, 0);
      }
    }catch(e){}
  }


  function wireAudio(el){
    el.addEventListener("timeupdate", ()=>{
      if(el !== activeAudio) return;
      const d = el.duration || 0;
      const t = el.currentTime || 0;
      if(d > 0){
        npSeek.value = Math.floor((t / d) * 1000);
      }
      try{ syncMediaSessionPosition(); }catch(e){}
      try{ syncMediaSessionControls(); }catch(e){}
      npCur.textContent = fmtTime(t);
      npDur.textContent = fmtTime(d);
      lastfmMaybeScrobble(false);
      try{ updateBufferedBarFor(el); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      try{ syncMediaSessionControls(); }catch(e){}
      try{
        if(state.now && state.now.rootId && state.now.rel){
          playbackMaybePost("audio", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, (!activeAudio.paused), "time");
        }
      }catch(e){}
    });
    el.addEventListener("ended", ()=>{
      if(el !== activeAudio) return;
      lastfmMaybeScrobble(true);
      try{
        if(state.now && state.now.rootId && state.now.rel){
          const d = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
          const t = d || ((activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0);
          playbackMaybePost("audio", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "ended");
        }
      }catch(e){}
      clearBufferedBar();
      playNext();
    });
    el.addEventListener("play", ()=>{
      if(el !== activeAudio) return;
      try{ ensureVisualizerAudioGraphFor(el); }catch(e){}
      updateVisualizerState();
      if(canMediaSession()) navigator.mediaSession.playbackState = "playing";
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      playbackPillActivity(false, "audio play");
    });
    el.addEventListener("pause", ()=>{
      if(el !== activeAudio) return;
      updateVisualizerState();
      if(canMediaSession()) navigator.mediaSession.playbackState = "paused";
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      showPlaybackPills(true, "audio pause");
      try{
        if(state.now && state.now.rootId && state.now.rel){
          const d = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
          const t = (activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0;
          playbackMaybePost("audio", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "pause");
        }
      }catch(e){}
    });
    ["error","stalled","waiting","suspend","abort"].forEach((name)=>{
      try{
        el.addEventListener(name, ()=>{
          if(el !== activeAudio) return;
          warnMedia("audio", name, el);
        });
      }catch(e){}
    });
  }
  try{ ensurePlaybackAudioSession(); }catch(e){}
  wireAudio(audioMain);
  try{ ensureVisualizerFrameLoop(); }catch(e){}
  if(npVideo){
    npVideo.addEventListener("timeupdate", ()=>{
      if(!isVideoActive()) return;
      const d = npVideo.duration || 0;
      const t = npVideo.currentTime || 0;
      if(d > 0){
        npSeek.value = Math.floor((t / d) * 1000);
      }
      try{ updateBufferedBarFor(npVideo); }catch(e){}
      npCur.textContent = fmtTime(t);
      npDur.textContent = fmtTime(d);
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, (!npVideo.paused), "time");
        }
      }catch(e){}
    });

    npVideo.addEventListener("play", ()=>{
      if(!isVideoActive()) return;
      try{ ensureVisualizerAudioGraphFor(npVideo); }catch(e){}
      updateVisualizerState();
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      playbackPillActivity(false, "video play");
    });

    npVideo.addEventListener("pause", ()=>{
      if(!isVideoActive()) return;
      updateVisualizerState();
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      showPlaybackPills(true, "video pause");
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          const d = (npVideo && npVideo.duration && isFinite(npVideo.duration)) ? npVideo.duration : 0;
          const t = (npVideo && isFinite(npVideo.currentTime)) ? npVideo.currentTime : 0;
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "pause");
        }
      }catch(e){}
    });

    npVideo.addEventListener("ended", ()=>{
      if(!isVideoActive()) return;
      updateVisualizerState();
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          const d = (npVideo && npVideo.duration && isFinite(npVideo.duration)) ? npVideo.duration : 0;
          const t = d || ((npVideo && isFinite(npVideo.currentTime)) ? npVideo.currentTime : 0);
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "ended");
        }
      }catch(e){}
      if(isSearchStreamActive()) playNext();
    });
    ["error","stalled","waiting","suspend","abort"].forEach((name)=>{
      try{
        npVideo.addEventListener(name, ()=>{
          if(!isVideoActive()) return;
          warnMedia("video", name, npVideo);
        });
      }catch(e){}
    });
  }

  npSeek.addEventListener("input", ()=>{
    const m = wheelMedia();
    const d = (m && m.duration) ? m.duration : 0;
    if(d > 0){
      try{ m.currentTime = (parseInt(npSeek.value, 10) / 1000) * d; }catch(e){}
    }
  });

  // ===== views =====
  async function viewFolder(root, rel, label, push){
    showNowPlaying(false);
    await setView({
      kind: "folder",
      label: label || (rel ? rel.split("/").slice(-1)[0] : ""),
      root: root,
      rel: rel || "",
      load: async function(){
        const url = "/api/library/browse?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.rel);
        let js = null;
        try{
          js = await apiGet(url);
        }catch(e){
          if(await restoreCachedLibraryView({kind:"folder", root:root, rel:this.rel, label:this.label})) return;
          throw e;
        }
        const items = [];
        if(state.history.length || this.rel){
          items.push({kind:"up", label:".."});
        }
        for(const e of (js.entries || [])){
          if(e.type === "dir"){
            items.push({kind:"dir", label:e.name, rel:e.rel, root: root});
          }else if(e.type === "file"){
            const mediaPill = e.media === "video" ? "video" : (e.media === "audio" ? "audio" : "");
            const pills = mediaPill ? [mediaPill] : [];
            items.push({kind:"file", label:e.name, pills: pills, rel:e.rel, root: root, media: e.media});
          }
        }
        resetList(items);
      }
    }, !!push);
  }

  async function viewMetaTop(root, push){
    showNowPlaying(false);
    await setView({
      kind: "metatop",
      label: "Browse",
      root: root,
      load: async function(){
        let js = null;
        try{
          js = await apiGet("/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=top");
        }catch(e){
          if(await restoreCachedLibraryView({kind:"metatop", root:root, label:"Browse"})) return;
          throw e;
        }
        const items = [];
        for(const c of (js.categories || [])){
          items.push({kind:"metacat", label:c.label, cat:c.key, root: root, badge: js.building ? "indexing" : ""});
        }
        if(js.building){
          items.push({kind:"info", label:"Indexing media files in background..."});
        }
        resetList(items);
      }
    }, !!push);
  }

  async function viewFolderSources(push){
    showNowPlaying(false);
    await setView({
      kind:"folder_sources",
      label:"Folders",
      load:async function(){
        const cfg = await loadConfig();
        const items = (cfg.roots || []).map(root=>({kind:"folder_source", label:root.name || "Folder", root:root, pills:[root.source ? String(root.source) : "library"]}));
        if(!items.length) items.push({kind:"info", label:"No library folders configured"});
        resetList(items);
      }
    }, !!push);
  }

  async function viewMetaList(root, level, value, label, push){
    showNowPlaying(false);
    await setView({
      kind: "metalist",
      label: label || level,
      root: root,
      level: level,
      value: value || "",
      load: async function(){
        const url = "/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=" + encodeURIComponent(this.level) + (this.value ? "&value=" + encodeURIComponent(this.value) : "");
        let js = null;
        try{
          js = await apiGet(url);
        }catch(e){
          if(await restoreCachedLibraryView({kind:"metalist", root:root, level:this.level, value:this.value, label:this.label})) return;
          throw e;
        }
        const items = [];
        const cfg = await loadConfig();
        items.push.apply(items, categoryPreludeItems(this.level, root));
        if(this.level === "playlists"){
          items.push({kind:"playlist_create", label:"Create playlist"});
          items.push({kind:"smart_playlist_create", label:"Create smart playlist"});
        }
        if(this.level === "playlist_tracks"){
          items.push({kind:"playlist_edit_entry", label:(isSmartPlaylistRel(this.value || "") ? "Edit rules" : "Edit"), rel:(this.value || ""), playlistLabel:(this.label || ""), root: root});
        }
        for(const it of (js.items || [])){
          if(it.kind === "info"){
            items.push({kind:"info", label: it.label || ""});
            continue;
          }
          const out = Object.assign({}, it);
          out.root = out.root_id ? ((cfg.roots || []).find(candidate=>candidate.id === out.root_id) || {id:out.root_id, name:"Library", mode:"metadata"}) : root;
          if(out.kind === "track" && !out.media) out.media = "audio";
          items.push(out);
        }
        if(js.building){
          items.push({kind:"info", label:"Indexing media files in background..."});
        }
        resetList(items);
      }
    }, !!push);
  }

  function currentItem(){
    if(state.items.length === 0) return null;
    return state.items[state.sel] || null;
  }

  async function selectItem(forcedItem){
    if(!forcedItem && typeof rangeEditorCenterPress === "function" && rangeEditorCenterPress()){
      return;
    }
    const it = forcedItem || currentItem();
if(!it) return;
    if(it.disabled) return;
    if(!it.root && it.root_id){
      try{
        const cfg = await loadConfig();
        it.root = (cfg.roots || []).find(candidate=>candidate.id === it.root_id) || {id:it.root_id, name:"Library", mode:"metadata"};
      }catch(e){ it.root = {id:it.root_id, name:"Library", mode:"metadata"}; }
    }
    if(!it.root && state.current && state.current.root) it.root = state.current.root;
    if(it.kind === "info" || it.kind === "loading") return;

    if(it.kind === "media_action"){
      const actions = window.DebriPod && DebriPod.mediaActions;
      if(actions && typeof actions.executeAction === "function") await actions.executeAction(it);
      return;
    }

    if(it.kind === "libsearch_query" || it.kind === "libsearch_filter"){
      const field = (it.kind === "libsearch_filter") ? "filter" : "q";
      try{
        if(!state.libSearch) state.libSearch = {q:"", filter:"", engine:"combined", cache_key:"", result_source:"combined", last_count:0, results:[], knaben_results:[], slsk_users:[], sourceStatus:{}, searching:false, cached:false, showSourceStatus:false, editField:"", editValue:""};
        if(field === "q") state.libSearch.showSourceStatus = false;
        state.libSearch.editField = field;
        state.libSearch.editValue = (typeof state.libSearch[field] === "string") ? state.libSearch[field] : "";
        renderList();
        try{
          const activeEdit = libList ? libList.querySelector(".ipodItem.sel .libInlineInput") : null;
          if(activeEdit){
            activeEdit.focus();
            activeEdit.click();
            const n = activeEdit.value.length;
            activeEdit.setSelectionRange(n, n);
          }
        }catch(e){}
      }catch(e){}
      return;
    }

    if(it.kind === "playlist_create"){
      beginPlaylistCreateEdit();
      return;
    }

    if(it.kind === "smart_playlist_create"){
      beginSmartPlaylistCreateEdit();
      return;
    }

    if(it.kind === "playlist_edit_name"){
      beginPlaylistRenameEdit();
      return;
    }

    if(it.kind === "playlist_edit_entry"){
      if(isSmartPlaylistRel(it.rel || "")){
        await viewSmartPlaylistRules(it.root, it.rel || "", it.playlistLabel || it.label || "Playlist", true);
      }else{
        await viewPlaylistEditMenu(it.root, it.rel || "", it.playlistLabel || it.label || "Playlist", true);
      }
      return;
    }

    if(it.kind === "smart_playlist_rules_entry"){
      const cur = state.current || {};
      await viewSmartPlaylistRules(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", true);
      return;
    }

    if(it.kind === "smart_playlist_rules_save"){
      await saveSmartPlaylistRules();
      return;
    }

    if(it.kind === "smart_playlist_rules_cancel"){
      await goBack();
      return;
    }

    if(it.kind === "playlist_edit_add"){
      const cur = state.current || {};
      const startRel = playlistBrowseStartRel(cur.playlistRel || "");
      await viewPlaylistAddSongs(cur.root, cur.playlistRel || "", startRel, true);
      return;
    }

    if(it.kind === "playlist_edit_remove"){
      const cur = state.current || {};
      await viewPlaylistRemoveSongs(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", true);
      return;
    }


    if(it.kind === "playlist_edit_delete"){
      const cur = state.current || {};
      await viewPlaylistDeleteConfirm(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", "playlist_edit_menu", true);
      return;
    }

    if(it.kind === "smart_playlist_rules_delete"){
      const cur = state.current || {};
      await viewPlaylistDeleteConfirm(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", "smart_playlist_rules", true);
      return;
    }

    if(it.kind === "playlist_delete_no"){
      await goBack();
      return;
    }

    if(it.kind === "playlist_delete_yes"){
      await confirmDeletePlaylist();
      return;
    }

    if(it.kind === "playlist_add_dir"){
      const cur = state.current || {};
      await viewPlaylistAddSongs(cur.root, cur.playlistRel || "", it.rel || "", true);
      return;
    }

    if(it.kind === "playlist_add_selectall"){
      const cur = state.current || {};
      const rels = (state.items || []).filter(x => x && x.kind === "playlist_add_file" && !x.selected).map(x => x.rel).filter(Boolean);
      if(!rels.length) return;
      try{
        await playlistAddSongsToCurrentView(rels);
        if(cur._added){
          for(const rp of rels) cur._added.add(String(rp));
        }
        await viewPlaylistAddSongs(cur.root, cur.playlistRel || "", cur.rel || "", false);
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "playlist_add_file"){
      if(it.selected) return;
      const cur = state.current || {};
      try{
        await playlistAddSongsToCurrentView([it.rel || ""]);
        if(cur._added && it.rel) cur._added.add(String(it.rel));
        it.selected = true;
        renderList();
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "playlist_remove_selectall"){
      const cur = state.current || {};
      if(!cur.selected) cur.selected = new Set();
      const tracks = (state.items || []).filter(x => x && x.kind === "playlist_remove_track");
      let anyUnsel = false;
      for(const tr of tracks){
        if(tr && tr.rel && !cur.selected.has(String(tr.rel))){
          anyUnsel = true;
          break;
        }
      }
      if(anyUnsel){
        for(const tr of tracks){
          if(tr && tr.rel) cur.selected.add(String(tr.rel));
        }
      }else{
        for(const tr of tracks){
          if(tr && tr.rel) cur.selected.delete(String(tr.rel));
        }
      }
      refreshPlaylistRemoveSelectionUI();
      return;
    }

    if(it.kind === "playlist_remove_commit"){
      const cur = state.current || {};
      const rels = cur.selected ? Array.from(cur.selected.values()) : [];
      if(!rels.length) return;
      try{
        const res = await apiPost("/api/library/playlist_remove", {root_id: cur.root.id, rel: cur.playlistRel || "", tracks: rels});
        const js = (res && res.json) ? res.json : {};
        if(!res || !res.ok || !js.ok){
          throw new Error((js && js.error) ? js.error : "Failed to remove songs");
        }
        cur.selected = new Set();
        await viewMetaList(cur.root, "playlist_tracks", cur.playlistRel || "", cur.playlistLabel || "Playlist", false);
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "playlist_remove_track"){
      const cur = state.current || {};
      if(!cur.selected) cur.selected = new Set();
      const rp = String(it.rel || "");
      if(rp){
        if(cur.selected.has(rp)) cur.selected.delete(rp);
        else cur.selected.add(rp);
      }
      refreshPlaylistRemoveSelectionUI();
      return;
    }

    if(it.kind === "np_playlist_close"){
      await closeNowPlayingPlaylistMode();
      return;
    }

    if(it.kind === "np_playlist_entry"){
      if(it.selected) return;
      const cur = state.current || {};
      try{
        await addCurrentNowPlayingTrackToPlaylist(it.rel || "");
        if(cur._added && it.rel) cur._added.add(String(it.rel));
        it.selected = true;
        try{
          if(Array.isArray(it.pills) && it.pills.length){
            it.pills[0].text = "Ã¢Å“â€œ";
          }
        }catch(e){}
        renderList();
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "random"){
      const idxs = [];
      for(let i=0;i<state.items.length;i++){
        const cand = state.items[i];
        if(_randomEligibleItem(cand)) idxs.push(i);
      }
      if(!idxs.length) return;
      const ri = idxs[Math.floor(Math.random() * idxs.length)];
      state.sel = ri;
      renderList();
      try{ await new Promise(r=>setTimeout(r, 20)); }catch(e){}
      await selectItem();
      return;
    }


    if(it.kind === "up"){
      await goBack();
      return;
    }
    
    if(it.kind === "libsearch_entry"){
      await viewLibSearch(true);
      return;
    }



if(it.kind === "libtasks_entry"){
  await viewLibTasks(true);
  return;
}

    if(it.kind === "libinfo_entry"){
      await viewLibInfo(true);
      return;
    }

    if(it.kind === "libsearch_action"){
      if(it.label === "Clear"){
        state.libSearch.q = "";
        state.libSearch.filter = "";
        state.libSearch.engine = "combined";
        state.libSearch.cache_key = "";
        state.libSearch.result_source = "combined";
        state.libSearch.results = [];
        state.libSearch.knaben_results = [];
        state.libSearch.slsk_users = [];
        state.libSearch.last_count = 0;
        state.libSearch.searching = false;
        state.libSearch.showSourceStatus = false;
        state.libSearch.sourceStatus = {};
        libSetStatus("", "");
        await viewLibSearch(false);
        return;
      }
      if(it.label === "Search history"){
        await viewLibSearchHistory(true);
        return;
      }
      if(it.engine){
        await libDoSearch(it.engine, state.libSearch.q || "");
        return;
      }
    }

    
    if(it.kind === "libinfo_action"){
      if(await handleLibInfoAction(it.action)) return;
    }

    if(it.kind === "account_action"){
      if(it.action === "create_user"){
        await createUserFromInfo();
        return;
      }
      if(it.action === "delete_current_user"){
        await deleteCurrentUserFromInfo();
        return;
      }
      if(it.action === "settings_export"){
        await exportUserSettings();
        return;
      }
      if(it.action === "settings_import"){
        await importUserSettings();
        await viewAccountSettings(false);
        return;
      }
      if(it.action === "logout"){
        window.location.href = "/logout";
        return;
      }
    }

    if(it.kind === "setting_value"){
      try{
        await editSettingRow(it);
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "settings_add_library_folder"){
      const setupReturnPage = String(it.setupReturnPage || "");
      const picked = setupReturnPage && typeof setupPickPath === "function" ? await setupPickPath("directory") : await settingsPickPath("directory");
      if(!picked){
        if(setupReturnPage && typeof viewSetupEditor === "function"){
          await viewSetupEditor({label:"Add folder", value:"", directory:true, libraryPath:true, returnPage:setupReturnPage}, true);
        }
        return;
      }
      const folders = libraryFolders();
      if(!folders.some(item=>String((item && item.path) || "").toLowerCase() === String(picked).toLowerCase())) folders.push({path:String(picked), mode:"meta"});
      await settingsSave({LIBRARY_FOLDERS:folders}, {});
      if(setupReturnPage && typeof viewSetupWizardPage === "function") await viewSetupWizardPage(setupReturnPage, false);
      else await viewSettingsLibrary(false);
      return;
    }

    if(it.kind === "settings_library_folder"){
      const folders = libraryFolders();
      const f = folders[Number(it.folderIndex || 0)] || {};
      await viewSettingsLibraryDetail(String(f.path || ""), Number(it.folderIndex || 0), true, String(it.setupReturnPage || ""));
      return;
    }

    if(it.kind === "settings_library_remove"){
      const cur = state.current || {};
      const setupReturnPage = String(cur.setupReturnPage || "");
      if(setupReturnPage && typeof viewSetupRemoveFolderConfirm === "function"){
        await viewSetupRemoveFolderConfirm(Number(cur.folderIndex), String(cur.folderPath || ""), setupReturnPage, true);
        return;
      }
      const idx = Number(cur.folderIndex);
      const folders = libraryFolders();
      if(Number.isFinite(idx) && idx >= 0 && idx < folders.length){
        folders.splice(idx, 1);
        try{
          await settingsSave({LIBRARY_FOLDERS: folders}, {});
          await goBack();
          await viewSettingsLibrary(false);
        }catch(e){
          alert(String(e && e.message ? e.message : e));
        }
      }
      return;
    }

    if(it.kind === "libui_action"){
      if(await handleLibUiAction(it.action)) return;
    }
    if(it.kind === "range_editor_input"){
      try{
        const editor = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
        if(editor && editor.rangeWheelArmed) openRangeEditorKeyboard();
        else armRangeEditorWheel();
      }catch(e){}
      return;
    }
    if(it.kind === "range_editor_slider"){
      return;
    }

if(it.kind === "libsearch_history_action"){
      if(it.action === "clear_history"){
        try{
          const res = await apiPost("/api/search_history/clear", {});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to clear history");
          }
        }catch(e){
          alert(String(e && e.message ? e.message : e));
        }
        await viewLibSearchHistory(false);
        return;
      }
    }

    if(it.kind === "libsearch_history_entry"){
      state.pendingLibSearch = {engine: "combined", q: it.q || "", cache_key:it.cache_key || ""};
      await goBack();
      return;
    }

    if(it.kind === "libsearch_result"){
      await openSearchResultDetail(it);
      return;
    }

    if(it.kind === "libsearch_file_action"){
      const view = state.current || {};
      if((it.action === "result_selectall" || it.action === "result_clear" || it.action === "result_download" || it.action === "result_browse" || it.action === "result_stream") && view._searchResult){
        const target = view._searchResult;
        const src = String(target.source || "");
        if(it.action === "result_browse"){
          if(src === "soulseek"){
            target.loadingBrowse = true;
            libSearchRebuildFilesList(target.buildItems());
            try{
              await viewLibSearchSlskBrowse(true, String((target.result && target.result.user) || ""), String((target.result && target.result.directory) || ""));
            }catch(e){
              target.loadingBrowse = false;
              libSearchRebuildFilesList(target.buildItems());
              throw e;
            }
          }else if(src === "youtube"){
            await viewLibSearchYouTubeChannel(true, target.result || {});
          }
          return;
        }
        if(it.action === "result_selectall"){
          const visible = (state.items || []).filter(x=>x && x.kind === "libsearch_file" && x.selectable);
          let anyUnsel = false;
          for(const v of visible){
            const key = src === "knaben" ? ("file:" + firstIdentifierText(v.file_id, v.label)) : (src === "youtube" ? ("itag:" + firstIdentifierText(v.itag, v.file_id, v.label)) : (src === "library" ? ("library:" + String(v.root_id || (target.result && target.result.root_id) || "") + ":" + String(v.rel || "")) : String(v.remote_path || v.label || "")));
            if(key && !target.selected.has(key)){ anyUnsel = true; break; }
          }
          target.downloadQueued = false;
          if(anyUnsel){
            for(const v of visible){
              const key = src === "knaben" ? ("file:" + firstIdentifierText(v.file_id, v.label)) : (src === "youtube" ? ("itag:" + firstIdentifierText(v.itag, v.file_id, v.label)) : (src === "library" ? ("library:" + String(v.root_id || (target.result && target.result.root_id) || "") + ":" + String(v.rel || "")) : String(v.remote_path || v.label || "")));
              if(!key) continue;
              target.selected.set(key, {key:key, remote_path:String(v.remote_path || ""), file_id:identifierText(v.file_id), itag:firstIdentifierText(v.itag, v.format_id, v.file_id), format_id:firstIdentifierText(v.format_id, v.itag, v.file_id), size:Number(v.size || 0), name:String(v.label || ""), label:String(v.label || ""), source:String(v.source || src || ""), ext:String(v.ext || ((((v.pills || [])[1] && typeof (v.pills || [])[1] === "string") ? (v.pills || [])[1] : "") || "")), quality:String(v.quality || ""), bitrate:String(v.bitrate || ""), media:String(v.media || (target.result && target.result.media) || ""), root_id:String(v.root_id || (target.result && target.result.root_id) || ""), rel:String(v.rel || ""), direct_url:String(v.direct_url || ""), url:String((target.result && target.result.url) || "")});
            }
          }else{
            for(const v of visible){
              const key = src === "knaben" ? ("file:" + firstIdentifierText(v.file_id, v.label)) : (src === "youtube" ? ("itag:" + firstIdentifierText(v.itag, v.file_id, v.label)) : (src === "library" ? ("library:" + String(v.root_id || (target.result && target.result.root_id) || "") + ":" + String(v.rel || "")) : String(v.remote_path || v.label || "")));
              if(key) target.selected.delete(key);
            }
          }
          libSearchRebuildFilesList(target.buildItems());
          return;
        }
        if(it.action === "result_clear"){
          target.selected = new Map();
          target.downloadQueued = false;
          libSearchRebuildFilesList(target.buildItems());
          return;
        }
        if(it.action === "result_stream"){
          if(!target.selected || target.selected.size === 0){
            libSetFileStatus("Select files", "warn");
            return;
          }
          libSetFileStatus("Preparing stream", "");
          try{
            const rr = target.result || {};
            if(src === "library"){
              await startSearchStreamQueue(Array.from(target.selected.values()), 0);
              libSetFileStatus("", "");
              return;
            }
            const sel = Array.from(target.selected.values()).map(x=>({remote_path:x.remote_path || "", file_id:identifierText(x.file_id), itag:firstIdentifierText(x.itag, x.format_id, x.file_id), format_id:firstIdentifierText(x.format_id, x.itag, x.file_id), size:x.size || 0, name:x.name || "", source:x.source || src || "", ext:x.ext || "", quality:x.quality || "", bitrate:x.bitrate || "", media:x.media || "", direct_url:x.direct_url || "", url:x.url || rr.url || ""}));
            const res = await apiPost("/api/libsearch/stream_selected", {
              source: src,
              provider: rr.provider || "",
              debrid_task_id: rr.debrid_task_id || "",
              magnet: rr.magnet || "",
              url: rr.url || "",
              channel: rr.channel || rr.user || "",
              thumbnail: rr.thumbnail || rr.art || "",
              title: rr.title || rr.directory_title || rr.directory || "Search stream",
              selected: sel
            });
            const js = (res && res.json) ? res.json : {};
            if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to prepare stream");
            libSetFileStatus("", "");
            await startSearchStreamQueue(js.items || [], 0);
          }catch(e){
            libSetFileStatus("Error", "warn");
            alert(String(e && e.message ? e.message : e));
          }
          return;
        }
        if(it.action === "result_download"){
          if(!target.selected || target.selected.size === 0){
            libSetFileStatus("Select files", "warn");
            return;
          }
          libSetFileStatus("Queuing", "");
          try{
            if(src === "knaben"){
              const ids = Array.from(target.selected.values()).map(x=>identifierText(x.file_id)).filter(Boolean);
              const rr = target.result || {};
              const res = await apiPost("/api/debrid/enqueue_selected", {provider: rr.provider || "", debrid_task_id: rr.debrid_task_id || "", file_ids: ids, title: rr.title || "Knaben item", magnet: rr.magnet || ""});
              const js = (res && res.json) ? res.json : {};
              if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to queue download");
            }else if(src === "youtube"){
              const rr = target.result || {};
              const sel = Array.from(target.selected.values()).map(x=>({
                file_id:firstIdentifierText(x.file_id, x.itag, x.format_id),
                itag:firstIdentifierText(x.itag, x.format_id, x.file_id),
                format_id:firstIdentifierText(x.format_id, x.itag, x.file_id),
                name:String(x.name || x.title || x.label || ""),
                title:String(x.title || x.name || x.label || ""),
                ext:String(x.ext || ""),
                media:String(x.media || ""),
                direct_url:String(x.direct_url || ""),
                url:String(x.url || rr.url || ""),
                size:Number(x.size || 0)
              })).filter(x=>x.itag || x.format_id || x.file_id || x.url);
              const res = await apiPost("/api/youtube/enqueue", {
                title: rr.title || rr.directory_title || rr.name || "YouTube",
                url: rr.url || "",
                selected: sel
              });
              const js = (res && res.json) ? res.json : {};
              if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to queue download");
              target.downloadQueued = true;
            }else if(src === "soulseek"){
              const rr = target.result || {};
              const sel = Array.from(target.selected.values()).map(x=>({remote_path:x.remote_path, size:x.size || 0})).filter(x=>x.remote_path);
              const dirPath = String(rr.directory || "");
              const dirBase = dirPath.split("\\").filter(Boolean).slice(-1)[0] || "";
              const title = "Soulseek: " + String(rr.user || "") + " " + dirBase;
              const res = await apiPost("/api/soulseek/enqueue", {user: rr.user || "", directory: dirPath, title: title, files: sel});
              const js = (res && res.json) ? res.json : {};
              if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to queue download");
              for(const x of sel){
                const key = String(x.remote_path || "");
                if(!key) continue;
                target.selected.set(key, {key:key, remote_path:key, size:Number(x.size || 0), download_state:"queued"});
                try{
                  const srcFiles = Array.isArray(rr.files) ? rr.files : [];
                  const hit = srcFiles.find(fx => String((fx && fx.remote_path) || "") === key);
                  if(hit) hit.download_state = "queued";
                }catch(e){}
              }
            }
            libSetFileStatus("", "");
            libSearchRebuildFilesList(target.buildItems());
          }catch(e){
            libSetFileStatus("Error", "warn");
            alert(String(e && e.message ? e.message : e));
          }
          return;
        }
      }
      if(it.action === "slsk_browse_user" && view._slsk){
        view._slsk.loadingBrowse = true;
        libSearchRebuildFilesList(view._slsk.buildItems());
        try{
          await viewLibSearchSlskBrowse(true, view._slsk.user || "", view._slsk.directory || "");
        }catch(e){
          view._slsk.loadingBrowse = false;
          libSearchRebuildFilesList(view._slsk.buildItems());
          throw e;
        }
        return;
      }
      if(it.action === "slsk_browse_up" && view._slskbrowse){
        view._slskbrowse.current_dir = slskBrowseParentPath(view._slskbrowse.current_dir || "");
        view._slskbrowse.selected_path = "";
        libSearchRebuildFilesList(view._slskbrowse.buildItems());
        return;
      }
      if(it.action === "slsk_selectall" && (view._slsk || view._slskbrowse)){
        const target = view._slsk || view._slskbrowse;
        target.downloadQueued = false;
        const visible = (state.items || []).filter(x=>x && x.kind === "libsearch_file");
        let anyUnsel = false;
        for(const v of visible){
          if(v && v.remote_path && !target.selected.has(String(v.remote_path))){
            anyUnsel = true;
            break;
          }
        }
        if(anyUnsel){
          for(const v of visible){
            if(v && v.remote_path){
              const rp = String(v.remote_path);
              target.selected.set(rp, {remote_path: rp, size: Number(v.size || 0)});
            }
          }
        }else{
          for(const v of visible){
            if(v && v.remote_path) target.selected.delete(String(v.remote_path));
          }
        }
        libSearchRebuildFilesList(target.buildItems());
        return;
      }
      if(it.action === "slsk_clear" && (view._slsk || view._slskbrowse)){
        const target = view._slsk || view._slskbrowse;
        target.selected = new Map();
        target.downloadQueued = false;
        libSearchRebuildFilesList(target.buildItems());
        return;
      }
      if(it.action === "slsk_download" && (view._slsk || view._slskbrowse)){
        const target = view._slsk || view._slskbrowse;
        if(!target.selected || target.selected.size === 0){
          libSetFileStatus("Select files", "warn");
          return;
        }
        libSetFileStatus("Queuing", "");
        try{
          const sel = Array.from(target.selected.values()).map(x=>({remote_path: x.remote_path, size: x.size || 0}));
          const dirPath = String((target.directory || target.current_dir) || "");
          const dirBase = dirPath.split("\\").filter(Boolean).slice(-1)[0] || "";
          const title = "Soulseek: " + (target.user || "") + " " + dirBase;
          const res = await apiPost("/api/soulseek/enqueue", {user: target.user || "", directory: dirPath, title: title, files: sel});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to queue download");
          }
          target.downloadQueued = true;
          if(typeof target.buildItems === "function") libSearchRebuildFilesList(target.buildItems());
          libSetFileStatus("", "");
        }catch(e){
          libSetFileStatus("Error", "warn");
          alert(String(e && e.message ? e.message : e));
        }
        return;
      }
    }

    if(it.kind === "libsearch_file"){
      if(it.selectable){
        try{
          if(typeof it.onToggle === "function") it.onToggle();
          else it.selected = !it.selected;
        }catch(e){}
        const view = state.current || {};
        if(view._searchResult && typeof view._searchResult.buildItems === "function"){
          libSearchRebuildFilesList(view._searchResult.buildItems());
        }else if(view._slsk && typeof view._slsk.buildItems === "function"){
          libSearchRebuildFilesList(view._slsk.buildItems());
        }else if(view._slskbrowse && typeof view._slskbrowse.buildItems === "function"){
          libSearchRebuildFilesList(view._slskbrowse.buildItems());
        }else{
          renderList();
        }
        return;
      }
    }

    if(it.kind === "slsk_browse_dir") {
      const view = state.current || {};
      if(view._slskbrowse && typeof view._slskbrowse.buildItems === "function"){
        view._slskbrowse.current_dir = String(it.browse_path || "");
        view._slskbrowse.selected_path = "";
        libSearchRebuildFilesList(view._slskbrowse.buildItems());
      }
      return;
    }



if(it.kind === "libtasks_action"){
  if(it.action === "clear_all"){
    await apiPost("/api/tasks/clear_all", {});
    try{
      const js = await apiGet("/api/tasks");
      state.libTasks.tasks = (js && js.tasks) ? js.tasks : [];
    }catch(e){
      state.libTasks.tasks = [];
    }
    libTasksRefreshList(false);
    return;
  }
}

if(it.kind === "libtask_entry"){
  await viewLibTask(true, it.task_id || "");
  return;
}

if(it.kind === "libtask_action"){
  var view = state.current || {};
  var tid = String(view.task_id || "");
  if(!tid) return;

  if(it.action === "selectall"){
    const visible = (state.items || []).filter(x=>x && x.kind === "libtask_file");
    let anyUnsel = false;
    for(const v of visible){
      if(v && v.file_id && view.selected && !view.selected.has(String(v.file_id))){
        anyUnsel = true; break;
      }
    }
    if(!view.selected) view.selected = new Set();
    if(anyUnsel){
      for(const v of visible){
        if(v && v.file_id) view.selected.add(String(v.file_id));
      }
    }else{
      for(const v of visible){
        if(v && v.file_id) view.selected.delete(String(v.file_id));
      }
    }
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    const nextItems = libTaskBuildItemsForView(view);
    const max = Math.max(0, nextItems.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    replaceListItems(nextItems, {animate:true, preserveSelection:true, preserveScroll:true, selectionIndex:state.sel, reason:"task selection"});
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    return;
  }

  if(it.action === "clear"){
    view.selected = new Set();
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    const nextItems = libTaskBuildItemsForView(view);
    const max = Math.max(0, nextItems.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    replaceListItems(nextItems, {animate:true, preserveSelection:true, preserveScroll:true, selectionIndex:state.sel, reason:"task selection"});
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    return;
  }

  if(it.action === "pause_selected" || it.action === "cancel_selected"){
    if(!view.selected || view.selected.size === 0){
      return;
    }
    const action = (it.action === "pause_selected") ? "pause" : "cancel";
    for(const fid of Array.from(view.selected)){
      try{
        await apiPost("/api/tasks/file_action", {task_id: tid, file_id: String(fid), action: action});
      }catch(e){}
    }
    await libTasksPollTick();
    return;
  }

  if(it.action === "pause_task"){
    await apiPost("/api/tasks/pause", {task_id: tid});
    await libTasksPollTick();
    return;
  }
  if(it.action === "resume_task"){
    await apiPost("/api/tasks/resume", {task_id: tid});
    await libTasksPollTick();
    return;
  }
  if(it.action === "cancel_task"){
    await apiPost("/api/tasks/cancel", {task_id: tid});
    await libTasksPollTick();
    return;
  }
  if(it.action === "open_library_location"){
    const nav = it.library_nav || {};
    if(!nav.available) return;
    const cfg = await loadConfig();
    const root = (cfg.roots || []).find(candidate=>candidate.id === nav.root_id);
    if(!root) return;
    state.root = root;
    await viewFolder(root, String(nav.rel || ""), "Open library location", true);
    return;
  }
  if(it.action === "clear_task"){
    await apiPost("/api/tasks/clear", {task_id: tid});
    await libTasksPollTick();
    return;
  }
}

if(it.kind === "libtask_file"){
  if(it.selectable){
    try{
      if(typeof it.onToggle === "function") it.onToggle();
      else it.selected = !it.selected;
    }catch(e){}
    const view = state.current || {};
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    const nextItems = libTaskBuildItemsForView(view);
    const max = Math.max(0, nextItems.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    replaceListItems(nextItems, {animate:true, preserveSelection:true, preserveScroll:true, selectionIndex:state.sel, reason:"task file selection"});
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    return;
  }
}

if(it.kind === "queue_item"){
      const item = it.queueItem || null;
      const index = Math.max(0, Number(it.queueIndex || 0));
      const canonical = window.DebriPod && DebriPod.playbackQueue;
      if(canonical && canonical.hasItems()){
        await canonical.playIndex(index, {forceShow:true});
        return;
      }
      if(it.queueKind === "stream" && typeof playStreamQueueIndex === "function"){
        await playStreamQueueIndex(index, true);
        return;
      }
      if(it.queueKind === "video"){
        playVideoIndex(index, true, 0);
        return;
      }
      if(it.queueKind === "shuffle"){
        const orderPos = Math.max(0, Number(it.queueOrderPos || 0));
        if(Array.isArray(state.playOrder) && orderPos >= 0 && orderPos < state.playOrder.length){
          state.orderPos = orderPos;
        }
        if(Array.isArray(state.playlist) && item){
          await startAudioFromItem(item, state.playlist, index, true, 0);
        }
        return;
      }
      if(it.queueKind === "audio" && Array.isArray(state.playlist) && item){
        await startAudioFromItem(item, state.playlist, index, true, 0);
        return;
      }
      return;
    }

if(it.kind === "root"){
      state.root = it.root;
      setHeader();
      if((it.root.mode || "folders") === "metadata"){
        await viewMetaTop(it.root, true);
      }else{
        await viewFolder(it.root, "", "", true);
      }
      return;
    }
    if(it.kind === "nowplaying"){
      await resumeFromServerNow(false);
      await openNowPlayingExplicit({explicit:true});
      return;
    }
    if(it.kind === "history_item"){
      // Restore the last browsing context first, then play
      const nav = (it.nav && typeof it.nav === "object") ? it.nav : {};
      if(nav && nav.root_id){
        await openNavContext(nav);
      }else{
        // fallback to folder containing the file
        try{
          const cfg = await loadConfig();
          const root = (cfg.roots || []).find(r => r.id === it.rootId);
          if(root){
            let folderRel = "";
            try{
              const parts = (it.rel || "").split("/");
              parts.pop();
              folderRel = parts.join("/");
            }catch(e){ folderRel = ""; }
            state.root = root;
            showNowPlaying(false);
            await setView(folderViewObj(root, folderRel, folderRel ? folderRel.split("/").slice(-1)[0] : ""), false);
          }
        }catch(e){}
      }

      // If selecting current now playing while it is still playing, just open it
      const sn = state.serverNow;
      const sameAsServer = (sn && sn.root_id === it.rootId && sn.rel === it.rel && (sn.media || "") === it.media);
      if(it.media === "audio"){
        const itemObj = {kind:"file", media:"audio", root:{id: it.rootId}, rel: it.rel, label: it.label};
        let pl = null;
        let idx = -1;
        try{
          if(it.playlist && Array.isArray(it.playlist.items) && it.playlist.items.length){
            pl = it.playlist.items.map(x=>({kind:"file", media:String(x.media || "audio"), root:{id:x.root_id}, rel:x.rel, label:x.label || "", streamed:!!x.streamed, source:x.source || "", ext:x.ext || "", quality:x.quality || ""})).filter(x=>x.root.id && x.rel);
            idx = isFinite(it.playlist.index) ? Number(it.playlist.index) : 0;
          }
        }catch(e){ pl = null; idx = -1; }
        if(!pl || !pl.length){
          pl = buildPlaylistFromItems(state.items);
          try{
            idx = pl.findIndex(x => x.rel === itemObj.rel && x.root && x.root.id === itemObj.root.id);
          }catch(e){ idx = -1; }
        }
        if(!pl || !pl.length){
          pl = [itemObj];
          idx = 0;
        }else{
          idx = Math.max(0, Math.min(pl.length - 1, (idx >= 0 ? idx : 0)));
        }
        const resume = (sameAsServer && state.serverNow && state.serverNow.playing && isFinite(state.serverNow.position)) ? Number(state.serverNow.position) : 0;
        const canonicalQueue = window.DebriPod && DebriPod.playbackQueue;
        if(canonicalQueue) canonicalQueue.replaceFromPlayableList(pl, itemObj);
        await startAudioFromItem(itemObj, pl, idx, true, resume);
        return;
      }
      if(it.media === "video"){
        let videoCandidates = [];
        try{
          if(it.playlist && Array.isArray(it.playlist.items) && it.playlist.items.length){
            videoCandidates = it.playlist.items.map(x=>({kind:"file", media:String(x.media || "video"), root:{id:x.root_id}, rel:x.rel, label:x.label || "", streamed:!!x.streamed, source:x.source || "", ext:x.ext || "", quality:x.quality || ""})).filter(x=>x.root.id && x.rel);
          }
        }catch(e){}
        const resume = (sameAsServer && state.serverNow && isFinite(state.serverNow.position)) ? Number(state.serverNow.position) : ((it.position && isFinite(it.position)) ? Number(it.position) : 0);
        const videoItem = {kind:"file", media:"video", root:{id: it.rootId}, rel: it.rel, label: it.label, streamed: !!it.streamed, source: it.source || "", ext: it.ext || "", quality: it.quality || ""};
        const canonicalQueue = window.DebriPod && DebriPod.playbackQueue;
        if(canonicalQueue) canonicalQueue.replaceFromPlayableList(videoCandidates.length ? videoCandidates : [videoItem], videoItem);
        await startVideoFromItem(videoItem, true, resume);
        return;
      }
      return;
    }
    if(it.kind === "dir"){
      await viewFolder(it.root, it.rel, it.label, true);
      return;
    }
    if(it.kind === "folder_sources"){
      await viewFolderSources(true);
      return;
    }

    if(it.kind === "debrid_token"){
      try{ if(typeof beginDebridTokenEdit === "function") beginDebridTokenEdit(); }catch(e){}
      return;
    }
    if(it.kind === "folder_source"){
      state.root = it.root;
      await viewFolder(it.root, "", it.label || "Folders", true);
      return;
    }
    if(it.kind === "metacat"){
      if(it.cat === "folders"){
        await viewFolderSources(true);
        return;
      }
      if(it.cat === "artists"){
        await viewMetaList(it.root, "artists", "", it.label, true);
        return;
      }
      if(it.cat === "albums"){
        await viewMetaList(it.root, "albums", "", it.label, true);
        return;
      }
      if(it.cat === "songs"){
        await viewMetaList(it.root, "songs", "", it.label, true);
        return;
      }
      if(it.cat === "playlists"){
        await viewMetaList(it.root, "playlists", "", it.label, true);
        return;
      }
      if(it.cat === "genres"){
        await viewMetaList(it.root, "genres", "", it.label, true);
        return;
      }
      if(it.cat === "movies"){
        await viewMetaList(it.root, "movies", "", it.label, true);
        return;
      }
      if(it.cat === "shows"){
        await viewMetaList(it.root, "shows", "", it.label, true);
        return;
      }
      if(it.cat === "videos"){
        await viewMetaList(it.root, "videos", "", it.label, true);
        return;
      }
      return;
    }
    if(it.kind === "artist"){
      await viewMetaList(it.root, "albums", it.value, it.label, true);
      return;
    }
    if(it.kind === "album"){
      await viewMetaList(it.root, "tracks", it.value, it.label, true);
      return;
    }
    if(it.kind === "genre"){
      await viewMetaList(it.root, "genre_albums", it.value, it.label, true);
      return;
    }
    if(it.kind === "show"){
      await viewMetaList(it.root, "show_seasons", it.show_key || "", it.label, true);
      return;
    }
    if(it.kind === "liked_category"){
      await viewMetaList(it.root, it.level, "", it.label, true);
      return;
    }
    if(it.kind === "show_season"){
      await viewMetaList(it.root, "show_episodes", JSON.stringify({show_key:it.show_key || "", season:Number(it.season || 0)}), it.label, true);
      return;
    }
    if(it.kind === "movie" || it.kind === "show_episode"){
      await startVideoFromItem(it, true, Number(it.position || 0));
      return;
    }
    if(it.kind === "playlist"){
      await viewMetaList(it.root, "playlist_tracks", it.rel || "", it.label, true);
      return;
    }
    if(it.kind === "track"){
      const pl = buildPlaylistFromItems(state.items);
      const idx = pl.findIndex(x => x.rel === it.rel && x.root.id === it.root.id);
      await startAudioFromItem(it, pl, idx >= 0 ? idx : 0, true);
      return;
    }
    if(it.kind === "file"){
      if(it.media === "video"){
        await startVideoFromItem(it, true);
        return;
      }
      if(it.media === "audio"){
        const pl = buildPlaylistFromItems(state.items);
        const idx = pl.findIndex(x => x.rel === it.rel && x.root.id === it.root.id);
        await startAudioFromItem(it, pl, idx >= 0 ? idx : 0, true);
        return;
      }
    }
  }

  // ===== wheel controls =====
  var wheel = document.getElementById("wheel");
  var btnMenu = document.getElementById("btnMenu");
  function openNowPlayingExplicit(options){
    const controller = window.DebriPod && DebriPod.navigationController;
    if(controller && typeof controller.openNowPlaying === "function"){
      return controller.openNowPlaying(options || {});
    }
    showNowPlaying(true, {navigationControlled:true});
    return Promise.resolve();
  }

  function syncCanonicalPlaybackStart(item, candidates, forceShow){
    try{
      const root = window.DebriPod || {};
      const controller = root.playbackQueue;
      const api = root.playbackQueueApi;
      if(!controller || !api) return;
      const normalized = api.normalizeQueueItem(item);
      if(controller.isDispatching()){
        if(normalized) controller.setCurrent(normalized.queue_id);
        return;
      }
      if(forceShow === false && controller.hasItems()){
        if(normalized && controller.setCurrent(normalized.queue_id)) return;
      }
      controller.replaceFromPlayableList(candidates, item);
    }catch(e){}
  }

  function categoryPreludeItems(level, root){
    const entry = {
      songs:{label:"Liked Songs", level:"liked_music"},
      movies:{label:"Liked Movies", level:"liked_movies"},
      shows:{label:"Liked Episodes", level:"liked_episodes"},
      videos:{label:"Liked Videos", level:"liked_videos"}
    }[String(level || "").toLowerCase()];
    return entry ? [{kind:"liked_category", label:entry.label, level:entry.level, root:root}] : [];
  }
