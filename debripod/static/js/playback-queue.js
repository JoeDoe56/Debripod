/*
 * Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818
 * Owns the canonical mixed-media playback queue and legacy projections.
 */
(function(globalScope, factory){
  const api = factory();
  if(typeof module === "object" && module.exports) module.exports = api;
  if(globalScope && globalScope.document){
    const root = globalScope.DebriPod = globalScope.DebriPod || {};
    root.playbackQueueApi = api;
    root.playbackQueue = api.createBrowserPlaybackQueueController(globalScope);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function(){
  "use strict";

  function text(value){
    return value == null ? "" : String(value);
  }

  function normalizePath(value){
    return text(value).replace(/\\/g, "/").replace(/^\/+/, "");
  }

  function queueIdentity(item){
    const source = text(item && item.source) || "library";
    const rootId = text(item && (item.root_id != null ? item.root_id : (item.root && item.root.id)));
    const rel = normalizePath(item && item.rel);
    const sourceId = text(item && (item.source_id != null ? item.source_id : (item.video_id != null ? item.video_id : item.result_id)));
    return [source, rootId, rel || sourceId].map(encodeURIComponent).join(":");
  }

  function normalizeQueueItem(item){
    if(!item || typeof item !== "object") return null;
    const media = text(item.media).toLowerCase();
    if(media !== "audio" && media !== "video") return null;
    const rootId = text(item.root_id != null ? item.root_id : (item.root && item.root.id));
    const rel = normalizePath(item.rel);
    const source = text(item.source) || (rootId === "__search_stream__" ? "stream" : "library");
    if(!rel && !item.source_id && !item.video_id && !item.result_id) return null;
    const normalized = {
      queue_id: text(item.queue_id) || "",
      media,
      root_id: rootId,
      rel,
      label: text(item.label || item.title || rel.split("/").pop()),
      source,
      streamed: !!item.streamed,
      title: text(item.title),
      artist: text(item.artist),
      album: text(item.album),
      genre: text(item.genre),
      duration: Number.isFinite(Number(item.duration)) ? Number(item.duration) : null,
      tech: text(item.tech),
      art: text(item.art || item.thumbnail || item.poster),
      ext: text(item.ext),
      quality: text(item.quality),
      origin: item.origin && typeof item.origin === "object" ? item.origin : null,
      source_url: text(item.source_url || item.url),
      source_id: text(item.source_id || item.video_id || item.result_id),
      year: item.year == null ? null : item.year,
      show_key: text(item.show_key),
      season: item.season == null ? null : item.season,
      episode: item.episode == null ? null : item.episode,
    };
    normalized.queue_id = normalized.queue_id || queueIdentity(normalized);
    return normalized;
  }

  function randomEligibleIndexes(items){
    const excluded = new Set(["info", "up", "random", "liked_category", "playlist_create", "smart_playlist_create", "playlist_edit_entry"]);
    const indexes = [];
    (Array.isArray(items) ? items : []).forEach((item, index)=>{
      const kind = text(item && item.kind);
      if(kind && !excluded.has(kind)) indexes.push(index);
    });
    return indexes;
  }

  function defaultState(source){
    const state = source && typeof source === "object" ? source : {};
    if(!Array.isArray(state.items)) state.items = [];
    if(!Number.isInteger(state.index)) state.index = -1;
    state.shuffle = !!state.shuffle;
    if(!Array.isArray(state.shuffleOrder)) state.shuffleOrder = [];
    if(!Number.isInteger(state.version)) state.version = 0;
    return state;
  }

  function createPlaybackQueueController(initialState, playCallback, mutationCallback){
    const state = defaultState(initialState);
    let dispatching = false;

    function notify(reason){
      state.version += 1;
      if(typeof mutationCallback === "function") mutationCallback(state, reason || "mutation");
      return state;
    }

    function current(){
      return state.index >= 0 && state.index < state.items.length ? state.items[state.index] : null;
    }

    function setCurrent(queueId){
      const clean = text(queueId);
      const index = state.items.findIndex((item) => item.queue_id === clean);
      if(index < 0) return false;
      state.index = index;
      notify("set-current");
      return true;
    }

    function replaceFromPlayableList(items, currentItem){
      const next = [];
      const seen = new Set();
      for(const raw of Array.isArray(items) ? items : []){
        const item = normalizeQueueItem(raw);
        if(!item || seen.has(item.queue_id)) continue;
        seen.add(item.queue_id);
        next.push(item);
      }
      const normalizedCurrent = normalizeQueueItem(currentItem);
      if(normalizedCurrent && !seen.has(normalizedCurrent.queue_id)){
        next.push(normalizedCurrent);
      }
      state.items = next;
      state.index = normalizedCurrent ? next.findIndex((item) => item.queue_id === normalizedCurrent.queue_id) : -1;
      if(state.index < 0 && next.length) state.index = 0;
      state.shuffleOrder = state.shuffle ? makeShuffleOrder(next.length, state.index) : [];
      notify("replace");
      return state;
    }

    function insertNext(raw){
      if(!current()) return false;
      const item = normalizeQueueItem(raw);
      if(!item) return false;
      const existing = state.items.findIndex((entry) => entry.queue_id === item.queue_id);
      if(existing >= 0){
        state.items.splice(existing, 1);
        if(existing < state.index) state.index -= 1;
      }
      state.items.splice(state.index + 1, 0, item);
      if(state.shuffle) state.shuffleOrder = makeShuffleOrder(state.items.length, state.index);
      notify("insert-next");
      return true;
    }

    function append(raw){
      if(!current()) return false;
      const item = normalizeQueueItem(raw);
      if(!item) return false;
      const existing = state.items.findIndex((entry) => entry.queue_id === item.queue_id);
      if(existing >= 0){
        state.items.splice(existing, 1);
        if(existing < state.index) state.index -= 1;
      }
      state.items.push(item);
      if(state.shuffle) state.shuffleOrder = makeShuffleOrder(state.items.length, state.index);
      notify("append");
      return true;
    }

    function makeShuffleOrder(length, currentIndex){
      const order = [];
      for(let index = 0; index < length; index += 1){
        if(index !== currentIndex) order.push(index);
      }
      for(let index = order.length - 1; index > 0; index -= 1){
        const swap = Math.floor(Math.random() * (index + 1));
        const value = order[index];
        order[index] = order[swap];
        order[swap] = value;
      }
      if(currentIndex >= 0) order.unshift(currentIndex);
      return order;
    }

    function setShuffle(enabled){
      state.shuffle = !!enabled;
      state.shuffleOrder = state.shuffle ? makeShuffleOrder(state.items.length, state.index) : [];
      notify("shuffle");
    }

    function orderedIndexes(){
      return state.shuffle && state.shuffleOrder.length ? state.shuffleOrder.slice() : state.items.map((_item, index) => index);
    }

    function orderedItems(){
      return orderedIndexes().map((index)=>state.items[index]).filter(Boolean);
    }

    function orderedEntries(){
      return orderedIndexes().map((canonicalIndex, orderIndex)=>({
        item: state.items[canonicalIndex],
        canonicalIndex,
        orderIndex,
      })).filter((entry)=>entry.item);
    }

    function isPermutation(order, length){
      if(!Array.isArray(order) || order.length !== length) return false;
      const seen = new Set(order);
      if(seen.size !== length) return false;
      for(let index = 0; index < length; index += 1) if(!seen.has(index)) return false;
      return true;
    }

    async function playIndex(index, options){
      const target = Number(index);
      if(!Number.isInteger(target) || target < 0 || target >= state.items.length) return false;
      state.index = target;
      notify("play-index");
      if(typeof playCallback === "function"){
        dispatching = true;
        try{
          await playCallback(state.items[target], target, options || {});
        }finally{
          dispatching = false;
        }
      }
      return true;
    }

    async function step(direction, options){
      if(!current()) return false;
      const order = orderedIndexes();
      const position = order.indexOf(state.index);
      const nextPosition = position + direction;
      if(position < 0 || nextPosition < 0 || nextPosition >= order.length) return false;
      return playIndex(order[nextPosition], options);
    }

    function remove(queueId){
      const clean = text(queueId);
      const index = state.items.findIndex((item) => item.queue_id === clean);
      if(index < 0) return false;
      state.items.splice(index, 1);
      if(!state.items.length) state.index = -1;
      else if(index < state.index) state.index -= 1;
      else if(state.index >= state.items.length) state.index = state.items.length - 1;
      if(state.shuffle) state.shuffleOrder = makeShuffleOrder(state.items.length, state.index);
      notify("remove");
      return true;
    }

    function serializeForPlaybackSession(){
      return {
        queue: state.items.map((item) => Object.assign({}, item)),
        queueIndex: state.index,
        shuffle: state.shuffle,
        shuffleOrder: state.shuffleOrder.slice(),
        queueVersion: state.version,
      };
    }

    function restoreFromPlaybackSession(session){
      const source = session && typeof session === "object" ? session : {};
      state.items = (Array.isArray(source.queue) ? source.queue : []).map(normalizeQueueItem).filter(Boolean);
      state.index = Number.isInteger(source.queueIndex) ? source.queueIndex : Number(source.queueIndex);
      if(!Number.isInteger(state.index) || state.index < 0 || state.index >= state.items.length){
        state.index = state.items.length ? 0 : -1;
      }
      state.shuffle = !!source.shuffle;
      state.shuffleOrder = Array.isArray(source.shuffleOrder)
        ? source.shuffleOrder.filter((index) => Number.isInteger(index) && index >= 0 && index < state.items.length)
        : [];
      if(state.shuffle && !isPermutation(state.shuffleOrder, state.items.length)){
        state.shuffleOrder = makeShuffleOrder(state.items.length, state.index);
      }
      notify("restore");
      return state;
    }

    return {
      state,
      current,
      hasItems: () => state.items.length > 0,
      hasCurrent: () => !!current(),
      isDispatching: () => dispatching,
      replaceFromPlayableList,
      setCurrent,
      insertNext,
      append,
      next: (options) => step(1, options),
      previous: (options) => step(-1, options),
      playIndex,
      remove,
      setShuffle,
      orderedIndexes,
      orderedItems,
      orderedEntries,
      serializeForPlaybackSession,
      restoreFromPlaybackSession,
    };
  }

  function legacyItem(item){
    return {
      kind: "file",
      media: item.media,
      root: {id: item.root_id},
      rel: item.rel,
      label: item.label,
      streamed: item.streamed,
      source: item.source,
      source_url: item.source_url,
      source_id: item.source_id,
      title: item.title,
      artist: item.artist,
      album: item.album,
      genre: item.genre,
      duration: item.duration,
      tech: item.tech,
      art: item.art,
      ext: item.ext,
      quality: item.quality,
    };
  }

  function createBrowserPlaybackQueueController(win){
    const appState = win.state;
    if(!appState) return null;
    appState.playbackQueue = defaultState(appState.playbackQueue);
    let controller;

    function projectCompatibility(){
      const currentItem = controller.current();
      const audio = controller.state.items.filter((item) => item.media === "audio");
      const video = controller.state.items.filter((item) => item.media === "video");
      const streamed = controller.state.items.filter((item) => item.streamed);
      appState.playlist = audio.map(legacyItem);
      appState.videoPlaylist = video.map(legacyItem);
      appState.streamQueue = streamed.map(legacyItem);
      appState.playIndex = currentItem && currentItem.media === "audio"
        ? audio.findIndex((item) => item.queue_id === currentItem.queue_id) : -1;
      appState.videoIndex = currentItem && currentItem.media === "video"
        ? video.findIndex((item) => item.queue_id === currentItem.queue_id) : -1;
      appState.streamQueueIndex = currentItem && currentItem.streamed
        ? streamed.findIndex((item) => item.queue_id === currentItem.queue_id) : -1;
      appState.shuffleEnabled = !!controller.state.shuffle;
    }

    function persist(_state, reason){
      projectCompatibility();
      const serialized = controller.serializeForPlaybackSession();
      if(appState.playbackSession){
        appState.playbackSession.queue = serialized.queue;
        appState.playbackSession.queueIndex = serialized.queueIndex;
        appState.playbackSession.shuffle = serialized.shuffle;
        appState.playbackSession.shuffleOrder = serialized.shuffleOrder;
      }
      try{
        if(typeof win.buildPlaybackSessionUpdate === "function"){
          win.buildPlaybackSessionUpdate(serialized, "canonical-queue-" + reason);
        }
      }catch(_error){}
      try{
        if(win.DebriPod && win.DebriPod.clientSync && win.DebriPod.clientSync.savePlaybackSession){
          win.DebriPod.clientSync.savePlaybackSession();
        }
      }catch(_error){}
      // Queue edits must update the current history entry as well as the
      // resumable session. Otherwise an album/playlist opened from History
      // keeps the queue snapshot from before Play After was used.
      if(["append", "insert-next", "remove", "shuffle"].includes(String(reason || ""))){
        const now = appState.now;
        const current = controller.current();
        const queue = serialized.queue.map((item)=>Object.assign({}, item));
        const queueIndex = serialized.queueIndex;
        try{
          const history = appState.playbackSession && appState.playbackSession.history;
          if(Array.isArray(history) && history.length && now && current){
            const match = history.find((entry)=>entry && String(entry.root_id || entry.rootId || "") === String(current.root_id || "") && String(entry.rel || "") === String(current.rel || "")) || history[0];
            if(match) match.playlist = {items: queue, index: queueIndex};
            try{
              if(win.DebriPod && win.DebriPod.clientSync && win.DebriPod.clientSync.savePlaybackSession){
                win.DebriPod.clientSync.savePlaybackSession();
              }
            }catch(_error){}
          }
        }catch(_error){}
        try{
          if(typeof win.playbackPost === "function" && now && current){
            const media = String(current.media || now.media || "audio");
            const element = media === "video" ? win.npVideo : win.activeAudio;
            win.playbackPost({
              media,
              root_id: current.root_id,
              rel: current.rel,
              playlist: {items: queue, index: queueIndex},
              label: current.label || current.title || "",
              title: current.title || "",
              artist: current.artist || "",
              album: current.album || "",
              art: current.art || "",
              position: element && Number.isFinite(Number(element.currentTime)) ? Number(element.currentTime) : 0,
              duration: element && Number.isFinite(Number(element.duration)) ? Number(element.duration) : current.duration,
              playing: !!(element && !element.paused),
              nav: now.nav || appState.nowNavContext || null,
              session: appState.playbackSession || null,
              event: "time",
              streamed: !!current.streamed,
              source: current.source || "",
              ext: current.ext || "",
              quality: current.quality || ""
            });
          }
        }catch(_error){}
      }
    }

    async function play(item, _index, options){
      const legacy = legacyItem(item);
      // Queue dispatches are also used by the media ended handler.  Opening
      // Now Playing is an explicit user action, so an omitted option must not
      // turn an automatic next-track handoff into a navigation event.
      const forceShow = !!(options && options.forceShow);
      if(item.media === "video"){
        return win.startVideoFromItem(legacy, forceShow, Number((options && options.resumeTime) || 0));
      }
      return win.startAudioFromItem(legacy, appState.playlist, appState.playIndex, forceShow, Number((options && options.resumeTime) || 0));
    }

    controller = createPlaybackQueueController(appState.playbackQueue, play, persist);
    if(!controller.state.items.length) controller.state.shuffle = !!appState.shuffleEnabled;
    if(appState.playbackSession && Array.isArray(appState.playbackSession.queue) && appState.playbackSession.queue.length){
      controller.restoreFromPlaybackSession(appState.playbackSession);
    }else{
      projectCompatibility();
    }
    return controller;
  }

  return {
    queueIdentity,
    normalizeQueueItem,
    randomEligibleIndexes,
    createPlaybackQueueController,
    createBrowserPlaybackQueueController,
  };
});
