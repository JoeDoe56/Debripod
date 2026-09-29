/*
 * Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818
 * Normalizes playable targets and builds type-specific context actions.
 */
(function(globalScope, factory){
  const api = factory();
  if(typeof module === "object" && module.exports) module.exports = api;
  if(globalScope && globalScope.document){
    const root = globalScope.DebriPod = globalScope.DebriPod || {};
    root.mediaActions = api.createBrowserMediaActions(globalScope);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function(){
  "use strict";

  const TYPES = new Set(["music", "movie", "episode", "video", "youtube"]);
  const COLLECTION_TYPES = new Set(["album", "artist", "genre", "playlist", "show", "show_season"]);
  // These collections have a finite playable boundary.  Artist/genre and
  // navigation categories deliberately do not inherit hold actions.
  const BOUNDED_WHEEL_COLLECTIONS = new Set(["album", "playlist", "show", "show_season"]);

  function present(value){
    return value !== null && value !== undefined && String(value).trim() !== "";
  }

  function normalizeMediaTarget(raw){
    let item = raw && typeof raw === "object" ? raw : null;
    if(item && item.kind === "queue_item" && item.queueItem) item = item.queueItem;
    if(!item) return {type:"none", playable:false};
    const kind = String(item.kind || "").toLowerCase();
    const media = String(item.media || "").toLowerCase();
    const source = String(item.source || (item.streamed ? "stream" : "library")).toLowerCase();
    const rootId = item.root_id != null ? item.root_id : (item.rootId != null ? item.rootId : (item.root && item.root.id));
    const rel = String(item.rel || "");
    const sourceUrl = String(item.source_url || item.url || "");
    const collection = COLLECTION_TYPES.has(kind);
    if(collection){
      const rootValue = present(rootId) ? String(rootId) : "";
      let value = item.value;
      if(value && typeof value === "object"){
        try{ value = JSON.stringify(value); }catch(_error){ value = ""; }
      }
      return {
        type: kind,
        playable: false,
        collection: true,
        root_id: rootValue,
        rel: rel,
        label: String(item.label || kind),
        value: String(value || ""),
        show_key: String(item.show_key || item.showKey || ""),
        season: item.season == null ? null : item.season,
        artist: String(item.artist || ""),
        album: String(item.album || ""),
        genre: String(item.genre || ""),
        collection_root_ids: item.collection_root_ids || [],
      };
    }
    const knownNonPlayable = new Set([
      "heading", "info", "loading", "dir", "root", "metacat", "up", "setting_value",
      "libtask_entry", "libtask_file", "libtask_action", "libsearch_result",
      "libsearch_file_action",
    ]);
    if(knownNonPlayable.has(kind)) return {type:"none", playable:false};
    const playable = (media === "audio" || media === "video") && (present(rel) || present(sourceUrl));
    if(!playable) return {type:"none", playable:false};

    let type = TYPES.has(String(item.type || "").toLowerCase()) ? String(item.type).toLowerCase() : "video";
    if(media === "audio") type = "music";
    else if(source === "youtube" || present(item.video_id) || /(?:youtube\.com|youtu\.be)/i.test(sourceUrl)) type = "youtube";
    else if(kind === "movie" || item.movie === true) type = "movie";
    else if(kind === "show_episode" || kind === "episode" || present(item.episode)) type = "episode";
    if(!TYPES.has(type)) type = "video";

    const normalized = {
      type,
      playable: true,
      root_id: present(rootId) ? String(rootId) : "",
      rel,
      media,
      source: source || "library",
      source_url: sourceUrl,
      source_id: String(item.source_id || item.video_id || item.result_id || ""),
      label: String(item.label || item.title || rel.split("/").pop() || "Media"),
      title: String(item.title || item.label || ""),
      artist: String(item.artist || ""),
      album: String(item.album || ""),
      art: String(item.art || item.thumbnail || item.poster || ""),
      streamed: !!item.streamed,
      ext: String(item.ext || ""),
      quality: String(item.quality || ""),
      liked: !!item.liked,
      year: item.year == null ? null : item.year,
      show_key: String(item.show_key || item.showKey || item.show_title || ""),
      show_title: String(item.show_title || item.showTitle || ""),
      season: item.season == null ? null : item.season,
      episode: item.episode == null ? null : item.episode,
    };
    normalized.canonical_queue_item = {
      media: normalized.media,
      root_id: normalized.root_id,
      rel: normalized.rel,
      label: normalized.label,
      source: normalized.source,
      streamed: normalized.streamed,
      title: normalized.title,
      artist: normalized.artist,
      album: normalized.album,
      art: normalized.art,
      ext: normalized.ext,
      quality: normalized.quality,
      source_url: normalized.source_url,
      source_id: normalized.source_id,
      genre: String(item.genre || ""),
      duration: item.duration == null ? null : item.duration,
      tech: String(item.tech || ""),
      year: normalized.year,
      show_key: normalized.show_key,
      season: normalized.season,
      episode: normalized.episode,
    };
    return normalized;
  }

  function contextMenuRows(target, options){
    const current = target && (target.playable === true || target.collection === true) ? target : normalizeMediaTarget(target);
    if(!current.playable && !current.collection) return [];
    const opts = options || {};
    const liked = !!opts.liked;
    const hasCurrent = !!opts.hasCurrentPlayback;
    const rows = [];
    if(current.collection){
      if(hasCurrent){
        rows.push({action:"play_next_collection", label:"Play Next"});
        rows.push({action:"play_after_collection", label:"Play After"});
      }
      return rows;
    }
    if(current.type === "music"){
      // Lyrics are revealed from the Now Playing left-edge wheel gesture.
      // They are intentionally not a second navigation action here.
    }else if(current.type === "movie" || current.type === "episode"){
      rows.push({action:"view_information", label:"View information"});
    }else if(current.type === "youtube"){
      rows.push({action:"view_comments", label:"View comments"});
    }
    if(current.playable && current.root_id && current.rel) rows.push({action:"add_to_playlist", label:"Add to playlist"});
    rows.push({action:"toggle_like", label:liked ? "Unlike" : "Like", heart:liked});
    if(hasCurrent){
      rows.push({action:"play_next", label:"Play Next"});
      rows.push({action:"play_after", label:"Play After"});
    }
    return rows;
  }

  function wheelActionsForTarget(target, options){
    const current = target && (target.playable === true || target.collection === true) ? target : normalizeMediaTarget(target);
    if(!current.playable && !(current.collection && BOUNDED_WHEEL_COLLECTIONS.has(current.type))) return {};
    // Artist/genre "All Songs" rows share the historic album kind but are
    // navigation shortcuts, not bounded albums.
    if(current.type === "album" && current.value){
      try{const value=JSON.parse(current.value);if(value && typeof value === "object" && !value.album) return {};}catch(e){}
    }
    const opts = options || {};
    const canLike = current.playable || BOUNDED_WHEEL_COLLECTIONS.has(current.type);
    const canPlaylist = current.playable ? !!(current.root_id && current.rel) : (current.collection_root_ids || []).length <= 1;
    const queueAction = current.collection ? "_collection" : "";
    return {
      toggle_like: {action:"toggle_like", enabled: canLike, position:"top", active: !!(opts.liked ?? current.liked)},
      add_to_playlist: {action:"add_to_playlist", enabled: canPlaylist, position:"bottom"},
      play_next: {action:"play_next" + queueAction, enabled: true, position:"right"},
      play_after: {action:"play_after" + queueAction, enabled: true, position:"left"},
    };
  }

  function targetObject(raw){
    return raw && (raw.playable === true || raw.collection === true) ? raw : normalizeMediaTarget(raw);
  }

  function createBrowserMediaActions(win){
    const root = win.DebriPod = win.DebriPod || {};
    let activeTarget = null;

    function targetFromCurrent(explicit){
      const direct = targetObject(explicit);
      if(direct.playable || direct.collection) return direct;
      try{
        if(win.nowPlaying && win.nowPlaying.style.display === "block" && win.state.now){
          return normalizeMediaTarget(Object.assign({}, win.state.nowMeta || {}, {
            kind:"file", root_id:win.state.now.rootId, rel:win.state.now.rel,
            media:win.state.now.media, streamed:!!win.state.now.streamed,
            source:(win.state.nowMeta && win.state.nowMeta.source) || "",
            source_url:(win.state.nowMeta && win.state.nowMeta.source_url) || "",
          }));
        }
      }catch(_error){}
      const selected = win.state && Array.isArray(win.state.items) ? win.state.items[win.state.sel] : null;
      return normalizeMediaTarget(selected);
    }

    function mediaKey(target){
      if(target.root_id && target.rel) return "local:" + target.root_id + ":" + target.rel.replace(/\\/g, "/");
      if(target.source_id) return target.source + ":" + target.source_id;
      if(target.source_url) return target.source + ":" + target.source_url;
      return "";
    }

    async function likeState(target){
      try{
        const key = mediaKey(target);
        if(!key || !root.apiClient) return false;
        const response = await root.apiClient.apiGet(
          "/api/library/like?media_key=" + encodeURIComponent(key) +
          "&artist=" + encodeURIComponent(target.artist || "") +
          "&title=" + encodeURIComponent(target.title || "") +
          "&album=" + encodeURIComponent(target.album || "")
        );
        return !!(response && response.like && response.like.liked);
      }catch(_error){
        return false;
      }
    }

    async function toggleLike(target){
      const current = targetObject(target || activeTarget || targetFromCurrent());
      if(current.collection && BOUNDED_WHEEL_COLLECTIONS.has(current.type)){
        const items = await expandCollection(current);
        if(!items.length) return false;
        const states = [];
        for(const item of items) states.push(await likeState(item));
        const liked = !states.every(Boolean);
        for(let index=0;index<items.length;index++){
          if(states[index] !== liked) await setLike(items[index], liked);
        }
        return true;
      }
      if(!current.playable || !root.apiClient) return false;
      const liked = await likeState(current);
      return setLike(current, !liked);
    }

    async function setLike(current, liked){
      const response = await root.apiClient.apiPost("/api/library/like", Object.assign({}, current, {
        media_type:current.type, media_key:mediaKey(current), liked,
      }));
      if(!response || !response.ok) throw new Error((response && response.json && response.json.error) || "Failed to update like");
      try{ if(typeof win.updateNowPlayingHeartState === "function") win.updateNowPlayingHeartState(liked); }catch(_error){}
      return liked;
    }

    async function showInformation(target){
      const current = normalizeMediaTarget(target);
      const render = async ()=>{
        if(typeof win.showNowPlaying === "function") win.showNowPlaying(false, {navigationControlled:true});
        const rows = [];
        if(current.type === "movie"){
          if(present(current.year)) rows.push({kind:"info", label:"Release year", badge:String(current.year)});
        }else{
          try{
            const query = new URLSearchParams({
              show_title:current.show_title || current.show_key,
              season:String(current.season == null ? "" : current.season),
              episode:String(current.episode == null ? "" : current.episode),
            });
            const response = await root.apiClient.apiGet("/api/library/media_information?" + query.toString());
            const info = response && response.information ? response.information : {};
            const ordered = [
              ["Show", info.show_title], ["Episode", info.episode_title], ["Number", info.number],
              ["Airdate", info.airdate], ["Runtime", info.runtime], ["Status", info.show_status],
              ["Genres", Array.isArray(info.genres) ? info.genres.join(", ") : info.genres],
              ["Network", info.network], ["Premiered", info.premiered], ["Summary", info.summary],
            ];
            for(const pair of ordered) if(present(pair[1])) rows.push({kind:"info", label:pair[0], sub_label:String(pair[1])});
          }catch(_error){}
        }
        if(!rows.length) rows.push({kind:"info", label:"No information available"});
        await win.setView({kind:"media_information", label:"Information", mediaTarget:current, load:async function(){ win.resetList(rows); }}, false);
      };
      const nav = root.navigationController;
      return nav && nav.openTransient ? nav.openTransient("media_information", render) : render();
    }

    async function showComments(target){
      const current = normalizeMediaTarget(target);
      const render = async ()=>{
        if(typeof win.showNowPlaying === "function") win.showNowPlaying(false, {navigationControlled:true});
        const rows = [{kind:"loading", label:"Loading comments", loading:true}];
        await win.setView({kind:"youtube_comments", label:"Comments", mediaTarget:current, load:async function(){ win.resetList(rows); }}, false);
        try{
          const response = await root.apiClient.apiGet("/api/youtube/comments?url=" + encodeURIComponent(current.source_url));
          rows.length = 0;
          for(const comment of (response.comments || [])){
            const pills = [];
            if(comment.like_count != null) pills.push(String(comment.like_count) + " likes");
            if(comment.reply_count != null) pills.push(String(comment.reply_count) + " replies");
            rows.push({kind:"info", label:String(comment.author || "Comment"), sub_label:String(comment.text || ""), badge:String(comment.timestamp || ""), pills});
          }
          if(!rows.length) rows.push({kind:"info", label:"No comments available"});
          win.resetList(rows);
        }catch(error){
          win.resetList([{kind:"info", label:"Comments unavailable", sub_label:String(error && error.message || "")}]);
        }
      };
      const nav = root.navigationController;
      return nav && nav.openTransient ? nav.openTransient("youtube_comments", render) : render();
    }

    function collectionQuery(target){
      const current = target || {};
      const rootId = encodeURIComponent(String(current.root_id || ""));
      if(!rootId) return null;
      if(current.type === "playlist"){
        return "/api/library/metadata?root_id=" + rootId + "&level=playlist_tracks&value=" + encodeURIComponent(String(current.rel || current.value || ""));
      }
      if(current.type === "album" || current.type === "artist" || current.type === "genre"){
        let selector = {};
        try{ selector = current.value ? JSON.parse(current.value) : {}; }catch(_error){}
        if(current.type === "artist" && !selector.artist) selector.artist = current.label || "";
        if(current.type === "genre" && !selector.genre) selector.genre = current.label || "";
        return "/api/library/metadata?root_id=" + rootId + "&level=" + (current.type === "genre" ? "genre_tracks" : "tracks") + "&value=" + encodeURIComponent(JSON.stringify(selector));
      }
      if(current.type === "show" || current.type === "show_season"){
        const selector = {show_key:String(current.show_key || current.value || "")};
        if(current.type === "show_season" && current.season != null) selector.season = Number(current.season || 0);
        return "/api/library/metadata?root_id=" + rootId + "&level=show_episodes&value=" + encodeURIComponent(JSON.stringify(selector));
      }
      return null;
    }

    async function expandCollection(target){
      const query = collectionQuery(target);
      if(!query || !root.apiClient) return [];
      const response = await root.apiClient.apiGet(query, {localFirst:false});
      const rows = response && Array.isArray(response.items) ? response.items : [];
      return rows.map((row)=>{
        if(!row || row.kind === "info") return null;
        const media = String(row.media || (row.kind === "show_episode" || row.kind === "movie" ? "video" : "audio")).toLowerCase();
        if(media !== "audio" && media !== "video") return null;
        const item = Object.assign({}, row, {media});
        if(!item.root_id && target.root_id) item.root_id = target.root_id;
        if(!item.root && item.root_id) item.root = {id:item.root_id};
        return normalizeMediaTarget(item);
      }).filter((item)=>item && item.playable);
    }

    async function enqueueCollection(target, mode){
      const current = target && target.collection === true ? target : normalizeMediaTarget(target);
      if(!current.collection || !root.playbackQueue) return false;
      const items = await expandCollection(current);
      if(!items.length) return false;
      const queueItems = items.map((item)=>item.canonical_queue_item);
      const hasCurrent = root.playbackQueue.hasCurrent && root.playbackQueue.hasCurrent();
      if(!hasCurrent){
        root.playbackQueue.replaceFromPlayableList(queueItems, queueItems[0]);
        return true;
      }
      const method = mode === "next" ? "insertNext" : "append";
      let changed = false;
      const itemsToInsert = mode === "next" ? queueItems.slice().reverse() : queueItems;
      for(const item of itemsToInsert) changed = !!root.playbackQueue[method](item) || changed;
      return changed;
    }

    async function executeAction(row){
      const action = String(row && row.action || "");
      const rawTarget = (row && row.target) || activeTarget;
      const target = rawTarget && (rawTarget.playable === true || rawTarget.collection === true) ? rawTarget : normalizeMediaTarget(rawTarget);
      if(action === "lyrics") return false;
      if(action === "add_to_playlist"){
        if(target.type === "music" && typeof win.viewMediaPlaylistAdd === "function"){
          const nav = root.navigationController;
          const render = () => win.viewMediaPlaylistAdd(target);
          return nav && nav.openTransient ? nav.openTransient("playlist_picker", render) : render();
        }
        return false;
      }
      if(action === "toggle_like"){
        return toggleLike(target);
      }
      if(action === "play_next") return root.playbackQueue && root.playbackQueue.insertNext(target.canonical_queue_item);
      if(action === "play_after") return root.playbackQueue && root.playbackQueue.append(target.canonical_queue_item);
      if(action === "play_next_collection") return enqueueCollection(target, "next");
      if(action === "play_after_collection") return enqueueCollection(target, "after");
      if(action === "view_information") return showInformation(target);
      if(action === "view_comments") return showComments(target);
      return false;
    }

    function wheelActionsForCurrentTarget(explicit, options){
      return wheelActionsForTarget(targetFromCurrent(explicit), options);
    }

    async function executeWheelAction(action, explicitTarget){
      const target = targetFromCurrent(explicitTarget);
      const command = String(action || "");
      if(!Object.values(wheelActionsForTarget(target)).some(item=>item.enabled && item.action === command)) return false;
      if(command === "toggle_like") return toggleLike(target);
      if(command === "add_to_playlist"){
        if(typeof win.viewMediaPlaylistAdd !== "function") return false;
        const items = target.collection ? await expandCollection(target) : [target];
        if(!items.length) return false;
        if(new Set(items.map(item=>item.root_id)).size > 1) throw new Error("Playlists currently contain items from one library folder. Choose an album within that folder.");
        const pickerTarget = target.collection ? Object.assign({}, target, {playlistItems:items}) : target;
        const nav = root.navigationController;
        const render = () => win.viewMediaPlaylistAdd(pickerTarget);
        return nav && nav.openTransient ? nav.openTransient("playlist_picker", render) : render();
      }
      if(command === "play_next" || command === "play_next_collection") return target.collection ? enqueueCollection(target, "next") : (root.playbackQueue && root.playbackQueue.insertNext(target.canonical_queue_item));
      if(command === "play_after" || command === "play_after_collection") return target.collection ? enqueueCollection(target, "after") : (root.playbackQueue && root.playbackQueue.append(target.canonical_queue_item));
      return false;
    }

    return {
      normalizeMediaTarget, contextMenuRows, wheelActionsForTarget, targetFromCurrent,
      wheelActionsForCurrentTarget: wheelActionsForCurrentTarget,
      executeWheelAction,
      toggleLikeForCurrentTarget: () => toggleLike(targetFromCurrent()), executeAction,
    };
  }

  return {normalizeMediaTarget, contextMenuRows, wheelActionsForTarget, createBrowserMediaActions};
});
