  function identifierText(value){
    return value === null || typeof value === "undefined" ? "" : String(value);
  }

  function firstIdentifierText(){
    for(let i = 0; i < arguments.length; i += 1){
      const value = arguments[i];
      if(value !== null && typeof value !== "undefined" && String(value) !== ""){
        return String(value);
      }
    }
    return "";
  }

  function libStandardizePreviewFilesForKnaben(preview){
    const out = [];
    const files = Array.isArray(preview && preview.files) ? preview.files : [];
    for(const ff of files){
      const name = String(ff.path || ff.name || "");
      const guess = libGuessFromName(name);
      const bitDepth = Number(guess.bitDepth || 0);
      const sampleRate = Number(guess.sampleRate || 0);
      const quality = [];
      if(bitDepth) quality.push(String(bitDepth) + " bit");
      if(sampleRate) quality.push(String(Math.round(Number(sampleRate)/100)/10) + " kHz");
      out.push({
        name: name,
        title: name,
        ext: guess.ext || "",
        quality: quality.join(" "),
        bitrate: "",
        size: Number(ff.bytes || 0),
        file_id: identifierText(ff.id),
        bit_depth: bitDepth,
        sample_rate: sampleRate,
        source: "knaben",
        provider: String((preview && preview.provider) || ""),
        debrid_task_id: String((preview && preview.debrid_task_id) || ""),
        selectable: true
      });
    }
    return out;
  }

  function libBuildGenericResultItems(result){
    const view = state.current;
    const src = String((result && result.source) || "").toLowerCase();
    const prev = view._searchResult || null;
    let selected = new Map();
    if(prev && prev.result_id === String(result.result_id || "") && prev.selected instanceof Map){
      selected = prev.selected;
    }
    view._searchResult = {
      result_id: String(result.result_id || ""),
      result: result || {},
      source: src,
      selected: selected,
      downloadQueued: !!(prev && prev.downloadQueued),
      filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : ""),
      loadingBrowse: (prev && prev.loadingBrowse) ? true : false
    };

    const build = ()=>{
      const target = view._searchResult;
      const rr = target.result || {};
      const f = libParseFilter(target.filter || "");
      const items = [];
      const files = Array.isArray(rr.files) ? rr.files : [];
      const selCount = target.selected.size;
      const statusMsg = String(view._fileStatus || "");
      const statusTone = String(view._fileStatusTone || "");
      const streamPills = [];
      const downloadPills = [];
      if(selCount){
        const countPill = {text: String(selCount), tone: ""};
        streamPills.push(countPill);
        downloadPills.push({text: String(selCount), tone: ""});
      }
      if(target.downloadQueued){
        downloadPills.push({text: "Queued", tone: "warn"});
      }
      const streamMsg = statusMsg.toLowerCase();
      if(streamMsg && rr.stream_available && (streamMsg.includes("stream") || streamMsg.includes("prepare"))){
        streamPills.push({text: statusMsg, tone: statusTone || ""});
      }
      if(rr.browse_available){
        items.push({kind:"libsearch_file_action", label:(src === "youtube" ? "Browse channel" : "Browse share"), action:"result_browse", badge: target.loadingBrowse ? "Loading" : ""});
      }
      if(rr.stream_available){
        items.push({kind:"libsearch_file_action", label:"Stream selected", action:"result_stream", pills: streamPills});
      }
      if(rr.download_available !== false){
        items.push({kind:"libsearch_file_action", label:"Download selected", action:"result_download", pills: downloadPills});
      }
      items.push({kind:"libsearch_file_action", label:"Select all", action:"result_selectall"});
      items.push({kind:"libsearch_file_action", label:"Clear selection", action:"result_clear"});

      let visibleFileCount = 0;
      for(const ff of files){
        const name = String(ff.name || ff.title || ff.label || "");
        const ext = String(ff.ext || "").toLowerCase();
        const bd = Number(ff.bit_depth || 0);
        const sr = Number(ff.sample_rate || 0);
        const fileSource = String(ff.source || src || "").toLowerCase();
        const searchText = [fileSource, name, ext, String(ff.quality || ""), String(ff.bitrate || "")].join(" ").toLowerCase();
        if(f.source && fileSource && fileSource !== f.source) continue;
        if(f.rest.length && !libTextHasAllTokens(searchText, f.rest)) continue;
        if(f.exts.size && (!ext || !f.exts.has(ext))) continue;
        if(f.bitDepth && (!bd || bd !== f.bitDepth)) continue;
        if(f.sampleRate && (!sr || sr !== f.sampleRate)) continue;
        visibleFileCount += 1;
        const key = src === "knaben" ? ("file:" + firstIdentifierText(ff.file_id, name)) : (src === "youtube" ? ("itag:" + firstIdentifierText(ff.itag, ff.file_id, name)) : (src === "library" ? ("library:" + String(ff.root_id || rr.root_id || "") + ":" + String(ff.rel || "")) : (String(ff.remote_path || name))));
        const dlState = normalizeSlskDownloadState(String(ff.download_state || ""));
        const pills = [];
        // yt-dlp keeps "youtube" as its internal source for format handling,
        // while source_label carries the actual site name (for example, TikTok).
        const fileSourceLabel = String(ff.source_label || rr.source_label || fileSource || src || "");
        if(fileSourceLabel) pills.push({text:fileSourceLabel});
        if(ext) pills.push(ext);
        if(ff.quality) pills.push(String(ff.quality));
        if(ff.bitrate) pills.push(String(ff.bitrate));
        if(Number(ff.size || 0) > 0) pills.push(humanBytes(Number(ff.size || 0)));
        if(dlState) pills.push({text: slskDownloadLabel(dlState), tone: slskDownloadTone(dlState)});
        items.push({
          kind:"libsearch_file",
          label:name,
          source:src,
          selectable: !dlState,
          selected: !dlState && target.selected.has(key),
          pills:pills,
          remote_path: String(ff.remote_path || ""),
          file_id: identifierText(ff.file_id),
          size: Number(ff.size || 0),
          root_id: String(ff.root_id || rr.root_id || ""),
          rel: String(ff.rel || ""),
          media: String(ff.media || rr.media || ""),
          ext: ext,
          quality: String(ff.quality || ""),
          bitrate: String(ff.bitrate || ""),
          direct_url: String(ff.direct_url || ""),
          itag: firstIdentifierText(ff.itag, ff.format_id, ff.file_id),
          format_id: firstIdentifierText(ff.format_id, ff.itag, ff.file_id),
          source: fileSource || src,
          onToggle: ()=>{
            if(dlState) return;
            if(target.selected.has(key)) target.selected.delete(key);
            else target.selected.set(key, {key:key, remote_path:String(ff.remote_path || ""), file_id:identifierText(ff.file_id), itag:firstIdentifierText(ff.itag, ff.format_id, ff.file_id), format_id:firstIdentifierText(ff.format_id, ff.itag, ff.file_id), size:Number(ff.size || 0), name:name, label:name, source:String(ff.source || src || ""), ext:String(ff.ext || ""), quality:String(ff.quality || ""), bitrate:String(ff.bitrate || ""), media:String(ff.media || rr.media || ""), root_id:String(ff.root_id || rr.root_id || ""), rel:String(ff.rel || ""), direct_url:String(ff.direct_url || ""), url:String((target.result && target.result.url) || "")});
          }
        });
      }
      if(files.length && !visibleFileCount){
        items.push({kind:"info", label:"No files match the current filter"});
      }else if(!files.length){
        items.push({kind:"info", label:"No files available"});
      }
      return items;
    };
    view._searchResult.buildItems = build;
    return build();
  }

  function libBuildStreamQueue(items){
    return (Array.isArray(items) ? items : []).map(it=>({
      kind:"file",
      media:String(it.media || ""),
      root:{id:String(it.root_id || "")},
      rel:String(it.rel || ""),
      label:String(it.label || it.title || ""),
      streamed:!!it.streamed,
      source:String(it.source || ""),
      ext:String(it.ext || ""),
      quality:String(it.quality || "")
    })).filter(it=>it.root.id && it.rel && (it.media === "audio" || it.media === "video"));
  }

  async function startSearchStreamQueue(queue, index){
    const pl = libBuildStreamQueue(queue);
    if(!pl.length) throw new Error("No streamable items");
    const idx = Math.max(0, Math.min(pl.length - 1, Number(index || 0)));
    const first = pl[idx];
    const canonical = window.DebriPod && DebriPod.playbackQueue;
    if(canonical) canonical.replaceFromPlayableList(pl, first);
    if(first.media === "video"){
      await startVideoFromItem(first, true, 0);
    }else{
      await startAudioFromItem(first, pl, idx, true, 0);
    }
  }

  function isSearchStreamActive(){
    try{
      return !!(state.now && state.now.rootId === "__search_stream__" && Array.isArray(state.streamQueue) && state.streamQueue.length);
    }catch(e){
      return false;
    }
  }

  async function playStreamQueueIndex(i, forceShow){
    const q = Array.isArray(state.streamQueue) ? state.streamQueue : [];
    if(i < 0 || i >= q.length) return;
    const item = q[i];
    const canonical = window.DebriPod && DebriPod.playbackQueue;
    if(canonical) canonical.setCurrent(canonical.state.items[i] && canonical.state.items[i].queue_id);
    if(item.media === "video"){
      await startVideoFromItem(item, (typeof forceShow === "boolean" ? forceShow : true), 0);
    }else{
      await startAudioFromItem(item, q, i, (typeof forceShow === "boolean" ? forceShow : true), 0);
    }
  }

  async function openSearchResultDetail(result, push){
    const item = result && result.raw ? result : {
      source:String((result && result.source) || ""),
      raw:result || {}
    };
    showNowPlaying(false);
    await setView({
      kind:"libsearch_result_detail",
      label:"Files",
      source:String(item.source || ""),
      load: async function(){
        const raw = Object.assign({}, item.raw || {});
        resetList([{kind:"loading", label:"Loading files", loading:true}]);
        libSetFileStatus("", "");
        try{
          if(String(raw.source || item.source || "") === "knaben" && !raw.files_loaded){
            const res = await apiPost("/api/debrid/preview_files", {magnet: raw.magnet || ""});
            const js = (res && res.json) ? res.json : {};
            if(!res || !res.ok || !js.ok){
              throw new Error((js && js.error) ? js.error : "Failed to load files");
            }
            raw.preview = js;
            raw.provider = js.provider || "";
            raw.provider_label = js.provider_label || "";
            raw.debrid_task_id = js.debrid_task_id || "";
            raw.files = libStandardizePreviewFilesForKnaben(js);
            raw.file_count = raw.files.length;
            raw.files_loaded = true;
          }else if(String(raw.source || item.source || "") === "youtube" && !raw.files_loaded){
            const js = await apiGet("/api/youtube/files?url=" + encodeURIComponent(raw.url || ""));
            if(!js || !js.ok){
              throw new Error((js && js.error) ? js.error : "Failed to load YouTube formats");
            }
            raw.files = Array.isArray(js.files) ? js.files : [];
            raw.file_count = Number(js.file_count || raw.files.length || 0);
            raw.size = Number(js.size || 0);
            raw.files_loaded = true;
          }
          resetList(libBuildGenericResultItems(raw));
        }catch(e){
          libSetFileStatus("Error", "warn");
          resetList([{kind:"info", label:"Failed to load files"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push !== false);
  }

  function normalizeSlskDownloadState(v){
    const s = String(v || "").trim().toLowerCase();
    if(!s) return "";
    if(s === "canceled") return "aborted";
    if(s === "requesting" || s === "connecting") return "initializing";
    return s;
  }

  function slskDownloadTone(v){
    const s = normalizeSlskDownloadState(v);
    if(s === "complete") return "ok";
    if(s === "failed" || s === "incomplete" || s === "aborted" || s === "paused") return "warn";
    return "";
  }

  function slskDownloadLabel(v){
    const s = normalizeSlskDownloadState(v);
    return s ? s.toUpperCase() : "";
  }

  function libBuildFileItemsFromSlsk(user, directory, files){
    const view = state.current;
    const prev = view._slsk || null;
    const prevSel = (prev && prev.selected instanceof Map) ? prev.selected : new Map();
    view._slsk = {user: user, directory: directory, files: files || [], selected: prevSel, downloadQueued: !!(prev && prev.downloadQueued), filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : ""), loadingBrowse: (prev && prev.loadingBrowse) ? true : false};

    const build = ()=>{
      const f = libParseFilter(view._slsk.filter || "");
      const items = [];
      const selCount = view._slsk.selected.size;
      const statusMsg = String(view._fileStatus || "");
      const downloadPills = [];
      if(selCount) downloadPills.push({text: String(selCount)});
      if(view._slsk.downloadQueued) downloadPills.push({text:"Queued", tone:"warn"});

      if(statusMsg) items.push({kind:"info", label: statusMsg});
      items.push({kind:"libsearch_file_action", label:"Browse user share", action:"slsk_browse_user", badge: view._slsk.loadingBrowse ? "Loading user shares" : ""});
      items.push({kind:"libsearch_file_action", label:"Download selected", action:"slsk_download", pills: downloadPills});
      items.push({kind:"libsearch_file_action", label:"Select all", action:"slsk_selectall"});
      items.push({kind:"libsearch_file_action", label:"Clear selection", action:"slsk_clear"});

      for(const ff of (view._slsk.files || [])){
        const name = ff.name || ff.remote_path || "";
        const fileSource = String(ff.source || "soulseek").toLowerCase();
        const ft = (fileSource + " " + name + " " + (ff.codec||"") + " " + (ff.kind||"") ).toLowerCase();
        const ext = String(ff.ext || "").toLowerCase();
        const bd = Number(ff.bit_depth || 0);
        const sr = Number(ff.sample_rate || 0);
        if(f.source && fileSource !== f.source) continue;
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        if(f.exts.size && (!ext || !f.exts.has(ext))) continue;
        if(f.bitDepth && (!bd || bd !== f.bitDepth)) continue;
        if(f.sampleRate && (!sr || sr !== f.sampleRate)) continue;

        const remote = ff.remote_path || "";
        const size = Number(ff.size || 0);
        const selInfo = view._slsk.selected.get(remote);
        const dlState = normalizeSlskDownloadState((selInfo && selInfo.download_state) || ff.download_state || "");
        const pills = [];
        if(fileSource) pills.push({text:fileSource});
        if(ext) pills.push(ext);
        if(bd) pills.push(String(bd) + " bit");
        if(sr) pills.push(String(Math.round(sr/100)/10) + " kHz");
        if(ff.bitrate) pills.push(String(ff.bitrate) + " kbps");
        if(size) pills.push(humanBytes(size));
        if(ff.codec) pills.push(String(ff.codec));
        if(dlState) pills.push({text: slskDownloadLabel(dlState), tone: slskDownloadTone(dlState)});
        items.push({
          kind:"libsearch_file",
          label:name,
          source:"soulseek",
          remote_path:remote,
          size:size,
          selectable:!dlState,
          selected:!dlState && view._slsk.selected.has(remote),
          pills:pills,
          onToggle: ()=>{
            if(dlState) return;
            if(view._slsk.selected.has(remote)) view._slsk.selected.delete(remote);
            else view._slsk.selected.set(remote, {remote_path: remote, size: size});
          }
        });
      }
      return items;
    };
    view._slsk.buildItems = build;
    return build();
  }

  function slskBrowseParentPath(path){
    const parts = String(path || "").split("\\").filter(Boolean);
    if(parts.length <= 1) return "";
    return parts.slice(0, -1).join("\\");
  }

  function libBuildBrowseItemsFromSlsk(user, allDirs, currentDir, selectedPath){
    const view = state.current;
    const prev = view._slskbrowse || null;
    const prevSel = (prev && prev.selected instanceof Map) ? prev.selected : new Map();
    view._slskbrowse = {
      user: user || "",
      dirs: Array.isArray(allDirs) ? allDirs : [],
      current_dir: String(currentDir || ""),
      selected_path: String(selectedPath || ""),
      selected: prevSel,
      downloadQueued: !!(prev && prev.downloadQueued),
      filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : "")
    };

    const build = ()=>{
      const f = libParseFilter(view._slskbrowse.filter || "");
      const items = [];
      const cur = String(view._slskbrowse.current_dir || "");
      const dirs = Array.isArray(view._slskbrowse.dirs) ? view._slskbrowse.dirs : [];
      const curPrefix = cur ? (cur + "\\") : "";
      let curEntry = null;
      const childMap = new Map();

      for(const d of dirs){
        const dp = String((d && d.directory) || "");
        if(dp === cur){
          curEntry = d;
        }
        if(cur){
          if(!dp || dp === cur) continue;
          if(!dp.startsWith(curPrefix)) continue;
        }else if(!dp){
          continue;
        }
        const rest = cur ? dp.slice(curPrefix.length) : dp;
        if(!rest) continue;
        const parts = rest.split("\\").filter(Boolean);
        if(!parts.length) continue;
        const childName = parts[0];
        const childPath = cur ? (cur + "\\" + childName) : childName;
        let agg = childMap.get(childPath);
        if(!agg){
          agg = {name: childName, path: childPath, fileCount: 0, totalSize: 0};
          childMap.set(childPath, agg);
        }
        agg.fileCount += Number((d && d.total_files) || ((d && d.files) ? d.files.length : 0) || 0);
        agg.totalSize += Number((d && d.total_size) || 0);
      }

      const files = (curEntry && Array.isArray(curEntry.files)) ? curEntry.files : [];
      const selCount = view._slskbrowse.selected.size;
      const statusMsg = String(view._fileStatus || "");
      const downloadPills = [];
      if(selCount) downloadPills.push({text: String(selCount)});
      if(view._slskbrowse.downloadQueued) downloadPills.push({text:"Queued", tone:"warn"});

      if(statusMsg) items.push({kind:"info", label: statusMsg});
      if(cur){
        items.push({kind:"libsearch_file_action", label:"..", action:"slsk_browse_up"});
      }
      if(files.length){
        items.push({kind:"libsearch_file_action", label:"Download selected", action:"slsk_download", pills: downloadPills});
        items.push({kind:"libsearch_file_action", label:"Select all", action:"slsk_selectall"});
        items.push({kind:"libsearch_file_action", label:"Clear selection", action:"slsk_clear"});
      }

      const childDirs = Array.from(childMap.values()).sort((a,b)=> String(a.name || "").localeCompare(String(b.name || "")));
      for(const d of childDirs){
        const ft = (String(d.name || "") + " " + String(d.path || "")).toLowerCase();
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        const pills = [];
        if(d.fileCount) pills.push(String(d.fileCount) + " files");
        if(d.totalSize) pills.push(humanBytes(d.totalSize));
        items.push({
          kind:"slsk_browse_dir",
          label:String(d.name || "") || "(dir)",
          browse_path:String(d.path || ""),
          pills:pills
        });
      }

      for(const ff of files){
        const name = ff.name || ff.remote_path || "";
        const fileSource = String(ff.source || "soulseek").toLowerCase();
        const ft = (fileSource + " " + name + " " + (ff.codec||"") + " " + (ff.kind||"") ).toLowerCase();
        const ext = String(ff.ext || "").toLowerCase();
        const bd = Number(ff.bit_depth || 0);
        const sr = Number(ff.sample_rate || 0);
        if(f.source && fileSource !== f.source) continue;
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        if(f.exts.size && (!ext || !f.exts.has(ext))) continue;
        if(f.bitDepth && (!bd || bd !== f.bitDepth)) continue;
        if(f.sampleRate && (!sr || sr !== f.sampleRate)) continue;

        const remote = ff.remote_path || "";
        const size = Number(ff.size || 0);
        const selInfo = view._slskbrowse.selected.get(remote);
        const dlState = normalizeSlskDownloadState((selInfo && selInfo.download_state) || ff.download_state || "");
        const pills = [];
        if(ext) pills.push(ext);
        if(bd) pills.push(String(bd) + " bit");
        if(sr) pills.push(String(Math.round(sr/100)/10) + " kHz");
        if(ff.bitrate) pills.push(String(ff.bitrate) + " kbps");
        if(size) pills.push(humanBytes(size));
        if(ff.codec) pills.push(String(ff.codec));
        if(dlState) pills.push({text: slskDownloadLabel(dlState), tone: slskDownloadTone(dlState)});
        items.push({
          kind:"libsearch_file",
          label:name,
          source:"soulseek",
          remote_path:remote,
          size:size,
          selectable:!dlState,
          selected:!dlState && view._slskbrowse.selected.has(remote),
          pills:pills,
          onToggle: ()=>{
            if(dlState) return;
            if(view._slskbrowse.selected.has(remote)) view._slskbrowse.selected.delete(remote);
            else view._slskbrowse.selected.set(remote, {remote_path: remote, size: size});
          }
        });
      }

      return items;
    };

    view._slskbrowse.buildItems = build;
    return build();
  }

  async function viewLibSearchSlskBrowse(push, user, selectedDir){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_files",
      label:"Browse",
      source:"soulseek",
      load: async function(){
        const browseUser = user || "";
        const wantedDir = String(selectedDir || "");
        resetList([{kind:"loading", label:"Loading user shares", loading:true}]);
        libSetFileStatus("Loading shares", "");
        try{
          const js = await apiGet("/api/soulseek/browse_user?user=" + encodeURIComponent(browseUser) + "&selected_dir=" + encodeURIComponent(wantedDir));
          if(!js || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to load user shares");
          }
          const selectedPath = String(js.selected_dir || wantedDir || "");
          const currentDir = selectedPath ? slskBrowseParentPath(selectedPath) : "";
          libSetFileStatus("", "");
          const built = libBuildBrowseItemsFromSlsk(browseUser, js.dirs || [], currentDir, selectedPath);
          resetList(built);
          if(selectedPath){
            const idx = (state.items || []).findIndex(x=>x && x.kind === "slsk_browse_dir" && String(x.browse_path || "") === selectedPath);
            if(idx >= 0){
              state.sel = idx;
              renderList();
            }
          }
        }catch(e){
          libSetFileStatus("Error", "warn");
          resetList([{kind:"info", label:"Failed to load user shares"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  async function viewLibSearchYouTubeChannel(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_result_list",
      label:"Channel",
      source:"youtube",
      load: async function(){
        resetList([{kind:"loading", label:"Loading channel", loading:true}]);
        try{
          const js = await apiGet("/api/youtube/channel?channel_id=" + encodeURIComponent(item.channel_id || ""));
          if(!js || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to load channel videos");
          }
          const vids = Array.isArray(js.results) ? js.results : [];
          const items2 = [];
          for(const r of vids){
            const pills = [{text:"YouTube"}];
            if(Number(r.file_count || 0) > 0) pills.push({text:String(r.file_count) + " files"});
            if(Number(r.size || 0) > 0) pills.push({text:humanBytes(Number(r.size || 0))});
            if(r.published) pills.push({text:String(r.published)});
            items2.push({kind:"libsearch_result", label:r.user || r.title || "Video", label_html:'<span class="artistStrong">' + escapeHtml(String(r.user || r.title || "Video")) + '</span>', sub_label:String(r.title || ""), source:"youtube", result_id:r.result_id || "", raw:r, pills:pills});
          }
          if(!items2.length) items2.push({kind:"info", label:"No channel videos found"});
          resetList(items2);
        }catch(e){
          resetList([{kind:"info", label:"Failed to load channel videos"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  async function viewLibSearchSlskFiles(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_files",
      label:"Files",
      source:"soulseek",
      load: async function(){
        const user = item.user || "";
        const directory = item.directory || "";
        const files = item.files || [];
        libSetFileStatus("", "");
        resetList(libBuildFileItemsFromSlsk(user, directory, files));
      }
    }, push);
  }

async function viewHistory(push, options){
    const opts = options || {};
    const controller = window.DebriPod && DebriPod.navigationController;
    if(!opts.navigationControlled && controller && typeof controller.openHistory === "function"){
      return controller.openHistory();
    }
    showNowPlaying(false);
    await syncPlaybackFromServer();
    await setView({
      kind: "history",
      label: "History",
      root: null,
      load: async function(){
        let rec = [];
        try{
          const js = await apiGet("/api/playback/recent");
          rec = (js && Array.isArray(js.recent)) ? js.recent : [];
        }catch(e){
          rec = (state.playbackSession && Array.isArray(state.playbackSession.history)) ? state.playbackSession.history : [];
        }
        const items = [];
        for(const r of rec){
          if(!r || !r.root_id || !r.rel) continue;
          const media = (r.media || "").toLowerCase();
          let label = "";
          if(media === "audio"){
            const a = (r.artist || "").trim();
            const t = (r.title || "").trim();
            if(a && t) label = a + " - " + t;
            else if(t) label = t;
            else label = (r.label || r.rel || "").split("/").slice(-1)[0];
          }else{
            label = (r.title || r.label || r.rel || "").split("/").slice(-1)[0];
          }
          const pills = [];
          const extText = (()=>{
            const ex = String(r.ext || "").trim().toLowerCase();
            if(ex) return ex;
            const rel = String(r.rel || "");
            const base = rel.split("/").slice(-1)[0] || "";
            const dot = base.lastIndexOf(".");
            return (dot > 0 && dot < (base.length - 1)) ? base.slice(dot + 1).toLowerCase() : "";
          })();
          if(r.streamed) pills.push("Streamed");
          if(extText) pills.push(extText);
          if(r.quality) pills.push(String(r.quality));
          items.push({
            kind: "history_item",
            label: label || "item",
            pills: pills,
            media: media,
            rootId: r.root_id,
            rel: r.rel,
            position: (r.position || 0),
            playing: !!r.playing,
            nav: r.nav || {},
            title: r.title || "",
            artist: r.artist || "",
            album: r.album || "",
            art: r.art || "",
            source: r.source || "",
            ext: r.ext || "",
            quality: r.quality || "",
            streamed: !!r.streamed,
            playlist: (r.playlist || null)
          });
        }
        if(items.length === 0){
          items.push({kind:"info", label:"No history yet"});
        }
        resetList(items);
      }
    }, !!push);
  }

  function queueItemLabel(item, index){
    try{
      const metaTitle = item.title || item.name || item.label || "";
      const base = String(metaTitle || item.rel || "").split("/").slice(-1)[0] || ("Item " + String(index + 1));
      return base;
    }catch(e){
      return "Item " + String(index + 1);
    }
  }

  function buildPlaybackQueueItems(){
    const items = [];
    try{
      const queue = window.DebriPod && DebriPod.playbackQueue;
      if(!queue) return items;
      queue.state.items.forEach((item, index)=>{
        const pills = [item.media];
        if(index === queue.state.index) pills.unshift("Now");
        if(queue.state.shuffle) pills.push("Shuffle");
        if(item.quality) pills.push(String(item.quality));
        items.push({
          kind:"queue_item",
          label:queueItemLabel(item, index),
          pills:pills,
          queueKind:"canonical",
          queueIndex:index,
          media:item.media,
          queueItem:item
        });
      });
    }catch(e){}
    return items;
  }

  async function viewPlaybackQueue(push, options){
    const opts = options || {};
    const controller = window.DebriPod && DebriPod.navigationController;
    if(!opts.navigationControlled && controller && typeof controller.openQueue === "function"){
      return controller.openQueue();
    }
    showNowPlaying(false);
    await setView({
      kind:"playback_queue",
      label:"Queue",
      root:null,
      load: async function(){
        const rows = [];
        rows.push.apply(rows, buildPlaybackQueueItems());
        if(rows.length === 0){
          rows.push({kind:"info", label:"Queue is empty"});
        }
        resetList(rows);
      }
    }, !!push);
  }
