  async function showRoots(resetHistory){
    const shouldResetHistory = (resetHistory !== false);
    showNowPlaying(false);
    const cfg = await loadConfig();
    await syncPlaybackFromServer();
    state.root = null;
    if(shouldResetHistory){
      state.history = [];
    }
    if(!state.rootView){
      state.rootView = rootViewObj();
    }
    state.current = state.rootView;
    const items = [{kind:"libsearch_entry", label:"Search"},{kind:"libtasks_entry", label:"Tasks"}].concat((cfg.roots||[]).map(r=>({kind:"root", label:r.name, root:r})));
    if(state.now || state.serverNow){
      items.push({kind:"nowplaying", label:"Now Playing"});
      if(state.serverRecent && state.serverRecent.length){
        items.push({kind:"recently", label:"Recently Played"});
      }
    }else{
      // show Recently Played only if there is history (even without now playing)
      if(state.serverRecent && state.serverRecent.length){
        items.push({kind:"recently", label:"Recently Played"});
      }
    }
    items.push({kind:"libinfo_entry", label:"Info"});
    resetList(items);
  }

  async function settingsLoad(){
    const js = await apiGet("/api/settings");
    state.settingsData = js || {};
    state.appSettings = Object.assign({}, (js && js.settings) || {});
    state.startupSettings = Object.assign({}, (js && js.startup) || {});
    state.toolStatus = Object.assign({}, (js && js.tools) || {});
    state.connectionStatus = Object.assign({}, (js && js.connections) || {});
    return js;
  }

  async function authStatusLoad(){
    try{
      return await apiGet("/api/auth/status");
    }catch(e){
      return {ok:false, logged_in:false, username:"", users:[]};
    }
  }

  function settingsRestartPill(){
    return {text:"Restart after save", tone:"warn"};
  }

  function settingSavePill(row){
    const key = String((row && row.key) || "");
    if(key.indexOf("SOULSEEK_") === 0) return {text:"Applied after save"};
    if((row && row.type) === "startup_number" || (row && row.type) === "startup_bool") return settingsRestartPill();
    return {text:"Saved after edit"};
  }

  async function settingsSave(updates, startupUpdates){
    const res = await apiPost("/api/settings/save", {settings: updates || {}, startup: startupUpdates || {}});
    const js = (res && res.json) ? res.json : {};
    if(!res || !res.ok || !js.ok){
      throw new Error((js && js.error) ? js.error : "Failed to save settings");
    }
    await settingsLoad();
    return js;
  }

  function settingValueLabel(value){
    if(Array.isArray(value)) return value.length ? (String(value.length) + " hosts") : "Unset";
    if(value === true) return "On";
    if(value === false) return "Off";
    if(value == null || value === "") return "Unset";
    if(value === "***") return "Saved";
    return String(value);
  }

  function settingPathBase(value){
    const s = String(value || "");
    if(!s) return "Unset";
    const parts = s.replace(/\\/g, "/").split("/").filter(Boolean);
    return parts.length ? parts[parts.length - 1] : s;
  }

  function settingConnectionPills(row){
    const key = String((row && row.key) || "");
    const type = String((row && row.type) || "");
    const connections = state.connectionStatus || {};
    if(type === "secret"){
      const status = connections[key] || {};
      const isSet = !!status.set || row.value === "***" || (row.value != null && row.value !== "");
      const pills = [{text: isSet ? "Set for current user" : "Not set for current user", tone: isSet ? "ok" : "warn"}];
      if(key === "SOULSEEK_USERNAME" || key === "SOULSEEK_PASSWORD"){
        const slsk = connections.SOULSEEK || {};
        if(slsk.set) pills.push({text: slsk.connected ? "Connected" : "Not connected", tone: slsk.connected ? "ok" : "warn"});
      }
      if(key === "LASTFM_API_KEY" || key === "LASTFM_API_SECRET" || key === "LASTFM_SESSION_KEY"){
        const lf = connections.LASTFM_SESSION || {};
        if(lf.set) pills.push({text: lf.username ? ("Session: " + String(lf.username)) : "Session set", tone:"ok"});
      }
      return pills;
    }
    if(type === "mcp_token"){
      const isSet = row.value === "Saved" || row.value === "***";
      return [{text: isSet ? "Set locally" : "Not set", tone: isSet ? "ok" : "warn"}];
    }
    return null;
  }

  function libraryFolders(){
    const s = state.appSettings || {};
    return Array.isArray(s.LIBRARY_FOLDERS) ? s.LIBRARY_FOLDERS.slice() : [];
  }

  function settingRowsForCategory(cat){
    const s = state.appSettings || {};
    const startup = state.startupSettings || {};
    const connections = state.connectionStatus || {};
    const slsk = connections.SOULSEEK || {};
    const slskStatus = slsk.startup_status || {};
    const lf = connections.LASTFM_SESSION || {};
    const tools = state.toolStatus || {};
    const ffmpeg = tools.ffmpeg || {};
    const ffprobe = tools.ffprobe || {};
    const groups = {
      ui: [
        {key:"TASKS_POLL_MS", label:"Task refresh", type:"number", value:s.TASKS_POLL_MS, advanced:true}
      ],
      downloads: [
        {key:"DOWNLOAD_DIR", label:"Real Debrid folder", type:"directory", value:s.DOWNLOAD_DIR},
        {key:"SOULSEEK_DOWNLOAD_DIR", label:"Soulseek folder", type:"directory", value:s.SOULSEEK_DOWNLOAD_DIR},
        {key:"YOUTUBE_DOWNLOAD_DIR", label:"YouTube folder", type:"directory", value:s.YOUTUBE_DOWNLOAD_DIR},
        {key:"REPLACE_ORIGINAL", label:"Replace original", type:"bool", value:s.REPLACE_ORIGINAL, advanced:true}
      ],
      services: [
        {key:"REAL_DEBRID_API_KEY", label:"Real Debrid token", type:"secret", value:s.REAL_DEBRID_API_KEY},
        {key:"KNABEN_API_KEY", label:"Knaben API key", type:"secret", value:s.KNABEN_API_KEY, advanced:true},
        {key:"SOULSEEK_USERNAME", label:"Soulseek username", type:"secret", value:s.SOULSEEK_USERNAME},
        {key:"SOULSEEK_PASSWORD", label:"Soulseek password", type:"secret", value:s.SOULSEEK_PASSWORD, sub_label: slsk.set ? (slsk.connected ? "Soulseek is connected for this account." : (slsk.error ? ("Soulseek is not connected: " + slsk.error) : "Soulseek is not connected for this account.")) : "Set username and password to connect Soulseek for this account."},
        {key:"LASTFM_API_KEY", label:"Last.fm API key", type:"secret", value:s.LASTFM_API_KEY},
        {key:"LASTFM_API_SECRET", label:"Last.fm secret", type:"secret", value:s.LASTFM_API_SECRET},
        {key:"LASTFM_SESSION_KEY", label:"Last.fm session key", type:"secret", value:s.LASTFM_SESSION_KEY, sub_label: lf.set ? ("Last.fm session is set for this account" + (lf.username ? (": " + lf.username) : ".")) : "Use Last.fm login or paste a session key for this account.", advanced:true},
        {key:"YTDLP_CMD", label:"yt-dlp command", type:"text", value:s.YTDLP_CMD, advanced:true}
      ],
      playback: [
        {key:"PLAYBACK_STREAMING_MODE", label:"Streaming mode", type:"choice", choices:["http","hls"], value:s.PLAYBACK_STREAMING_MODE},
        {key:"PRELOAD_NEXT_FOR_GAPLESS", label:"Preload next", type:"bool", value:s.PRELOAD_NEXT_FOR_GAPLESS},
        {key:"FFMPEG_PATH", label:"ffmpeg", type:"tool_path", value:s.FFMPEG_PATH, tool:"ffmpeg", toolStatus:ffmpeg, sub_label: ffmpeg.ok ? ("Detected: " + (ffmpeg.found || "ffmpeg")) : (ffmpeg.install_hint || "Install ffmpeg or set a path."), advanced:true},
        {key:"FFPROBE_PATH", label:"ffprobe", type:"tool_path", value:s.FFPROBE_PATH, tool:"ffprobe", toolStatus:ffprobe, sub_label: ffprobe.ok ? ("Detected: " + (ffprobe.found || "ffprobe")) : (ffprobe.install_hint || "Install ffprobe or set a path."), advanced:true}
      ],
      advanced: [
      {key:"PORT", label:"Port", type:"startup_number", value:startup.PORT},
      {key:"WHEEL_ROTATION_MAX_DEGREES", label:"Max wheel tilt", type:"number", value:(s.WHEEL_ROTATION_MAX_DEGREES == null ? 10 : s.WHEEL_ROTATION_MAX_DEGREES)},
      {key:"SOULSEEK_LISTENING_PORT", label:"Soulseek listen port", type:"number", value:s.SOULSEEK_LISTENING_PORT, sub_label:"Effective: " + String(slskStatus.listening_port == null ? s.SOULSEEK_LISTENING_PORT : slskStatus.listening_port)},
      {key:"SOULSEEK_OBFUSCATED_PORT", label:"Soulseek obfuscated port", type:"number", value:s.SOULSEEK_OBFUSCATED_PORT, sub_label:"Effective: " + String(slskStatus.obfuscated_port == null ? s.SOULSEEK_OBFUSCATED_PORT : slskStatus.obfuscated_port)},
      {key:"SOULSEEK_SEARCH_TIMEOUT_SEC", label:"Soulseek search timeout", type:"number", value:s.SOULSEEK_SEARCH_TIMEOUT_SEC},
      {key:"SOULSEEK_SEARCH_MAX_RESULTS", label:"Soulseek search max results", type:"number", value:s.SOULSEEK_SEARCH_MAX_RESULTS},
      {key:"SOULSEEK_SEARCH_IDLE_STOP_SEC", label:"Soulseek idle stop", type:"number", value:s.SOULSEEK_SEARCH_IDLE_STOP_SEC},
      {key:"SOULSEEK_SEARCH_HARD_MAX_SEC", label:"Soulseek hard max", type:"number", value:s.SOULSEEK_SEARCH_HARD_MAX_SEC},
      {key:"ENABLE_MCP", label:"MCP enabled", type:"startup_bool", value:startup.ENABLE_MCP},
      {key:"MCP_TOKEN", label:"Reset MCP token", type:"mcp_token", value:startup.MCP_TOKEN_SET ? "Saved" : "Unset"},
      {key:"CACHE_DIR_NAME", label:"Cache folder name", type:"text", value:s.CACHE_DIR_NAME},
      {key:"STREAM_PROXY_ALLOWED_HOST_SUFFIXES", label:"Stream proxy hosts", type:"csv_list", value:s.STREAM_PROXY_ALLOWED_HOST_SUFFIXES},
      {key:"AUDIO_TRANSCODE", label:"Audio transcode rules", type:"text", value:s.AUDIO_TRANSCODE},
      {key:"VIDEO_BROWSER_TARGET_EXT", label:"Video target", type:"text", value:s.VIDEO_BROWSER_TARGET_EXT},
      {key:"REQUEST_TIMEOUT_SECONDS", label:"Request timeout", type:"number", value:s.REQUEST_TIMEOUT_SECONDS}
      ]
    };
    if(cat === "advanced"){
      return groups.advanced.concat(groups.ui, groups.downloads, groups.services, groups.playback).filter(r => r && (r.advanced || groups.advanced.indexOf(r) >= 0));
    }
    return (groups[cat] || []).filter(r => r && !r.advanced);
  }

  async function viewSettings(push){
    const view = {
      kind:"settings",
      label:"Settings",
      load: async function(){
        await settingsLoad();
        resetList([
          {kind:"settings_category", category:"ui", label:"Interface"},
          {kind:"settings_library", label:"Library"},
          {kind:"settings_category", category:"downloads", label:"Downloads"},
          {kind:"settings_category", category:"services", label:"Services"},
          {kind:"settings_category", category:"playback", label:"Playback"},
          {kind:"settings_category", category:"advanced", label:"Advanced"}
        ]);
      }
    };
    await setView(view, !!push);
  }

  async function viewAccountSettings(push){
    showNowPlaying(false);
    await setView({
      kind:"account_settings",
      label:"Account",
      load: async function(){
        libControlsHide();
        const js = await authStatusLoad();
        const items = [];
        const username = String((js && js.username) || "");
        items.push({kind:"info", label:"Signed in", pills:[username || "Unknown"]});
        items.push({kind:"account_action", label:"Create user", action:"create_user"});
        items.push({kind:"account_action", label:"Log out", action:"logout"});
        const users = Array.isArray(js.users) ? js.users : [];
        if(users.length){
          items.push({kind:"info", label:"Users"});
          users.forEach((u)=>{
            const name = String((u && u.username) || "");
            if(name) items.push({kind:"info", label:name, pills:[name === username ? "current" : "user"]});
          });
        }
        resetList(items);
      }
    }, !!push);
  }

  async function createUserFromInfo(){
    window.location.href = "/account/create";
  }

  async function viewSettingsCategory(category, push){
    const labels = {ui:"Interface", downloads:"Downloads", services:"Services", playback:"Playback", advanced:"Advanced"};
    const view = {
      kind:"settings_category",
      category:category,
      label:labels[category] || "Settings",
      load: async function(){
        await settingsLoad();
        const rows = settingRowsForCategory(category).map(r=>({
          kind:"setting_value",
          label:r.label,
          sub_label: r.sub_label || (r.advanced ? "Advanced" : ""),
          key:r.key,
          settingType:r.type,
          choices:r.choices || [],
          value:r.value,
          tool:r.tool || "",
          toolStatus:r.toolStatus || null,
          pills:(settingConnectionPills(r) || [{text:settingValueLabel(r.value)}]).concat([settingSavePill(r)])
        }));
        resetList(rows);
      }
    };
    await setView(view, !!push);
  }

  async function viewSettingsLibrary(push){
    const view = {
      kind:"settings_library",
      label:"Library",
      load: async function(){
        await settingsLoad();
        const folders = libraryFolders();
        const items = [{kind:"settings_add_library_folder", label:"Add folder"}];
        folders.forEach((f, idx)=>{
          const mode = String((f && f.mode) || "list").toLowerCase();
          items.push({
            kind:"settings_library_folder",
            label:settingPathBase(f && f.path),
            sub_label:String((f && f.path) || ""),
            folderIndex:idx,
            pills:[{text: mode === "meta" ? "Metadata" : "List"}]
          });
        });
        if(!folders.length) items.push({kind:"info", label:"No library folders"});
        resetList(items);
      }
    };
    await setView(view, !!push);
  }

  async function viewSettingsLibraryMode(folderPath, folderIndex, push){
    const isExisting = typeof folderIndex === "number" && folderIndex >= 0;
    const view = {
      kind:"settings_library_mode",
      label:"Folder Type",
      folderPath:String(folderPath || ""),
      folderIndex:isExisting ? folderIndex : -1,
      load: async function(){
        resetList([
          {
            kind:"settings_library_mode_choice",
            mode:"meta",
            label:"Metadata folder",
            sub_label:"Indexes tags for Artists, Albums, Songs, Genres, liked songs, and richer browsing."
          },
          {
            kind:"settings_library_mode_choice",
            mode:"list",
            label:"List folder",
            sub_label:"Uses simple folder-by-folder browsing without tag indexing."
          },
          ...(isExisting ? [{kind:"settings_library_remove", label:"Remove folder", sub_label:String(folderPath || ""), pills:[{text:"Delete", tone:"warn"}]}] : [])
        ]);
      }
    };
    await setView(view, !!push);
  }

  async function settingsPickPath(kind){
    const res = await apiPost("/api/settings/pick_path", {kind:kind || "directory"});
    const js = (res && res.json) ? res.json : {};
    if(res && res.ok && js && js.ok && js.path) return String(js.path || "");
    const fallback = prompt("Enter path", "");
    return fallback ? String(fallback).trim() : "";
  }

  async function editSettingRow(row){
    const key = String(row.key || "");
    const type = String(row.settingType || "text");
    if(!key) return;
    const refreshAfterSettingEdit = async ()=>{
      if(state.current && state.current.kind === "libadvancedsettings") await viewLibAdvancedSettings(false);
      else await viewSettingsCategory((state.current && state.current.category) || "advanced", false);
    };
    if(type === "mcp_token"){
      const ok = confirm("Reset the MCP token? The new token will be shown once.");
      if(!ok) return;
      const res = await apiPost("/api/settings/mcp_reset_token", {});
      const js = (res && res.json) ? res.json : {};
      if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to reset token");
      alert("New MCP token:\n\n" + String(js.token || ""));
      await refreshAfterSettingEdit();
      return;
    }
    if(type === "bool" || type === "startup_bool"){
      const next = !(row.value === true || String(row.value).toLowerCase() === "true");
      if(type === "startup_bool") await settingsSave({}, {[key]: next});
      else await settingsSave({[key]: next}, {});
      await refreshAfterSettingEdit();
      return;
    }
    if(type === "choice"){
      const choices = Array.isArray(row.choices) ? row.choices : [];
      const current = String(row.value || "");
      const idx = choices.indexOf(current);
      const next = choices[(idx + 1 + choices.length) % choices.length] || current;
      await settingsSave({[key]: next}, {});
      await refreshAfterSettingEdit();
      return;
    }
    if(type === "tool_path"){
      const status = row.toolStatus || {};
      const platform = String(status.platform || "");
      let picked = "";
      if(platform.indexOf("win") === 0){
        picked = await settingsPickPath("file");
      }else{
        const hint = status.install_hint || "Install this tool with your package manager and keep the command on PATH.";
        const current = (row.value === "***") ? "" : String(row.value == null ? "" : row.value);
        picked = prompt(hint + "\n\nCommand or path:", current || String(row.tool || row.key || ""));
      }
      if(!picked) return;
      await settingsSave({[key]: String(picked).trim()}, {});
      await refreshAfterSettingEdit();
      return;
    }
    if(type === "directory" || type === "file"){
      const picked = await settingsPickPath(type === "file" ? "file" : "directory");
      if(!picked) return;
      await settingsSave({[key]: picked}, {});
      await refreshAfterSettingEdit();
      return;
    }
    if(type === "csv_list"){
      const current = Array.isArray(row.value) ? row.value.join(", ") : String(row.value == null ? "" : row.value);
      const raw = prompt(row.label || key, current);
      if(raw == null) return;
      const values = String(raw || "").split(",").map(x=>x.trim()).filter(Boolean);
      await settingsSave({[key]: values}, {});
      await refreshAfterSettingEdit();
      return;
    }
    const raw = prompt(row.label || key, (row.value === "***") ? "" : String(row.value == null ? "" : row.value));
    if(raw == null) return;
    let value = raw;
    if(type === "number" || type === "startup_number"){
      value = Number(raw);
      if(!Number.isFinite(value)) return;
      if(key === "SOULSEEK_LISTENING_PORT" || key === "SOULSEEK_OBFUSCATED_PORT"){
        value = Math.max(0, Math.min(65535, Math.trunc(value)));
      }else if(key === "SOULSEEK_SEARCH_TIMEOUT_SEC" || key === "SOULSEEK_SEARCH_MAX_RESULTS" || key === "SOULSEEK_SEARCH_HARD_MAX_SEC"){
        value = Math.max(1, Math.trunc(value));
      }else if(key === "SOULSEEK_SEARCH_IDLE_STOP_SEC"){
        value = Math.max(0.1, value);
      }
    }
    if(type === "startup_number") await settingsSave({}, {[key]: value});
    else await settingsSave({[key]: value}, {});
    await refreshAfterSettingEdit();
  }


  
  

  function libControlsHide(){}

  function libControlsShow(html){}

  function libSetStatus(msg, tone){
    try{
      if(!state.libSearch) state.libSearch = {q:"", filter:"", engine:"combined", cache_key:"", result_source:"combined", last_count:0, results:[], knaben_results:[], slsk_users:[]};
      state.libSearch.status_msg = msg ? String(msg) : "";
      state.libSearch.status_tone = tone ? String(tone) : "";
    }catch(e){}
    // legacy element (if present)
    const el = document.getElementById("libSearchStatus");
    if(!el) return;
    if(!msg){
      el.style.display = "none";
      el.textContent = "";
      el.className = "ipodPill";
      return;
    }
    el.style.display = "inline-flex";
    el.textContent = String(msg);
    el.className = "ipodPill" + (tone ? (" " + tone) : "");
  }

  function libSetFileStatus(msg, tone){
    const view = state.current || null;
    if(view){
      view._fileStatus = msg ? String(msg) : "";
      view._fileStatusTone = tone ? String(tone) : "";
      const target = (view._searchResult || view._rd || view._slsk || view._slskbrowse || null);
      if(target && typeof target.buildItems === "function"){
        try{ libSearchRebuildFilesList(target.buildItems()); }catch(e){}
      }
    }
  }

  function libParseFilter(q){
    const s = String(q || "").trim().toLowerCase();
    const tokens = s.split(/\s+/).filter(Boolean);

    const out = {exts: new Set(), bitDepth: 0, sampleRate: 0, source: "", rest: []};

    for(const t of tokens){
      if(t === "source:knaben" || t === "src:knaben"){ out.source = "knaben"; continue; }
      else if(t === "source:soulseek" || t === "src:soulseek" || t === "source:slsk" || t === "src:slsk"){ out.source = "soulseek"; continue; }
      else if(t === "source:youtube" || t === "src:youtube" || t === "source:yt" || t === "src:yt"){ out.source = "youtube"; continue; }
      else if(t === "source:combined" || t === "src:combined"){ out.source = "combined"; continue; }
      if(t === "flac" || t === ".flac") out.exts.add("flac");
      else if(t === "mp3" || t === ".mp3") out.exts.add("mp3");
      else if(t === "m4a" || t === ".m4a") out.exts.add("m4a");
      else if(t === "aac" || t === ".aac") out.exts.add("aac");
      else if(t === "ogg" || t === ".ogg") out.exts.add("ogg");
      else if(t === "wav" || t === ".wav") out.exts.add("wav");
      else if(t === "alac" || t === ".alac") out.exts.add("alac");
      else if(t === "opus" || t === ".opus") out.exts.add("opus");
      else if(t === "16" || t === "16bit" || t === "16-bit") out.bitDepth = 16;
      else if(t === "24" || t === "24bit" || t === "24-bit") out.bitDepth = 24;
      else if(t === "32" || t === "32bit" || t === "32-bit") out.bitDepth = 32;
      else if(t === "44" || t === "44.1" || t === "44100" || t === "44khz" || t === "44.1khz") out.sampleRate = 44100;
      else if(t === "48" || t === "48000" || t === "48khz") out.sampleRate = 48000;
      else if(t === "88" || t === "88.2" || t === "88200" || t === "88khz" || t === "88.2khz") out.sampleRate = 88200;
      else if(t === "96" || t === "96000" || t === "96khz") out.sampleRate = 96000;
      else if(t === "176" || t === "176.4" || t === "176khz" || t === "176.4khz") out.sampleRate = 176400;
      else if(t === "192" || t === "192000" || t === "192khz") out.sampleRate = 192000;
      else out.rest.push(t);
    }
    return out;
  }

  function libTextHasAllTokens(text, tokens){
    const t = String(text || "").toLowerCase();
    for(const x of (tokens || [])){
      if(!x) continue;
      if(!t.includes(x)) return false;
    }
    return true;
  }

  function libGuessFromName(name){
    const s = String(name || "").toLowerCase();
    const mExt = s.match(/\.([a-z0-9]{2,5})$/);
    const ext = mExt ? mExt[1] : "";
    let bd = 0;
    let sr = 0;
    if(/\b24\s*bit\b/.test(s) || /\b24bit\b/.test(s)) bd = 24;
    else if(/\b16\s*bit\b/.test(s) || /\b16bit\b/.test(s)) bd = 16;
    else if(/\b32\s*bit\b/.test(s) || /\b32bit\b/.test(s)) bd = 32;

    const mK = s.match(/\b(44\.1|48|88\.2|96|176\.4|192)\s*k(?:hz)?\b/);
    if(mK){
      const v = mK[1];
      if(v === "44.1") sr = 44100;
      else if(v === "48") sr = 48000;
      else if(v === "88.2") sr = 88200;
      else if(v === "96") sr = 96000;
      else if(v === "176.4") sr = 176400;
      else if(v === "192") sr = 192000;
    }
    return {ext: ext, bitDepth: bd, sampleRate: sr};
  }

  function libHumanSpeed(v){
    const n = Number(v || 0);
    if(!n) return "";
    if(n >= 1000000) return (n/1000000).toFixed(1) + " MBps";
    if(n >= 1000) return (n/1000).toFixed(0) + " KBps";
    return String(Math.round(n)) + " Bps";
  }

  function libResultsToItems(){
    const q = state.libSearch.q || "";
    const filt = libParseFilter(state.libSearch.filter || "");
    const items = [];

    const stMsg = (state.libSearch && state.libSearch.status_msg) ? String(state.libSearch.status_msg) : "";
    const stTone = (state.libSearch && state.libSearch.status_tone) ? String(state.libSearch.status_tone) : "";
    const qPills = [];
    if(stMsg){
      qPills.push({text: stMsg, tone: stTone || ""});
    }
    items.push({kind:"libsearch_query", label:"Enter query", pills: qPills});
    items.push({kind:"libsearch_filter", label:"Enter filters"});

    items.push({kind:"libsearch_action", label:"Clear"});
    items.push({kind:"libsearch_action", label:"Search history"});

    for(const r of (state.libSearch.results || [])){
      const source = String(r.source || "").toLowerCase();
      if(filt.source && source !== filt.source) continue;

      const title = String(r.title || r.label || "Result");
      const user = String(r.user || "").trim();
      const searchable = [
        source,
        user,
        title,
        String(r.directory || ""),
        String(r.infohash || ""),
        String(r.category || ""),
        ...(Array.isArray(r.files) ? r.files.map(f => [f.name || "", f.ext || "", f.quality || ""].join(" ")) : [])
      ].join(" ").toLowerCase();
      if(filt.rest.length && !libTextHasAllTokens(searchable, filt.rest)) continue;

      const files = Array.isArray(r.files) ? r.files : [];
      if(filt.exts.size || filt.bitDepth || filt.sampleRate){
        let ok = false;
        for(const f of files){
          const ext = String(f.ext || "").toLowerCase();
          const bd = Number(f.bit_depth || 0);
          const sr = Number(f.sample_rate || 0);
          if(filt.exts.size && (!ext || !filt.exts.has(ext))) continue;
          if(filt.bitDepth && (!bd || bd !== filt.bitDepth)) continue;
          if(filt.sampleRate && (!sr || sr !== filt.sampleRate)) continue;
          ok = true;
          break;
        }
        if(!ok) continue;
      }

      const pills = [];
      pills.push({text: String(r.source_label || source || "source")});
      if(Number(r.file_count || 0) > 0) pills.push({text: String(r.file_count) + " files"});
      if(Number(r.size || 0) > 0) pills.push({text: humanBytes(Number(r.size || 0))});
      if(source === "soulseek" && Number(r.speed || 0) > 0){
        pills.push({text: libHumanSpeed(Number(r.speed || 0))});
      }else if(source === "knaben"){
        const s = Number(r.seeders || 0);
        const l = Number(r.leechers || 0);
        pills.push({text: "S " + String(s) + " L " + String(l)});
      }else if(source === "youtube"){
        if(r.length) pills.push({text: String(r.length)});
        if(r.published) pills.push({text: String(r.published)});
      }

      const primary = user ? ('<span class="artistStrong">' + escapeHtml(user) + '</span>') : ('<span class="artistStrong">' + escapeHtml(title) + '</span>');
      const sub = user ? title : String(r.directory_title || r.directory || r.category || "");

      items.push({
        kind:"libsearch_result",
        label: user || title,
        label_html: primary,
        sub_label: sub || "",
        source: source,
        result_id: r.result_id || "",
        raw: r,
        pills: pills
      });
    }

    return items;
  }

  function libRefreshList(preserveSel){
    const items = libResultsToItems();
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);

    let restoreSel = null;
    let restoreScroll = null;
    try{
      if(state.current && typeof state.current.savedSel === "number" && isFinite(state.current.savedSel)){
        restoreSel = Number(state.current.savedSel);
      }
      if(state.current && typeof state.current.savedScroll === "number" && isFinite(state.current.savedScroll)){
        restoreScroll = Number(state.current.savedScroll);
      }
    }catch(e){ restoreSel = null; restoreScroll = null; }

    state.items = Array.isArray(items) ? items : [];
    if(preserveSel){
      const max = Math.max(0, state.items.length - 1);
      state.sel = Math.max(0, Math.min(max, prevSel));
    }else if(restoreSel != null){
      const max = Math.max(0, state.items.length - 1);
      state.sel = Math.max(0, Math.min(max, restoreSel));
    }else{
      state.sel = 0;
    }

    setHeader();
    renderList();

    if(!preserveSel && restoreScroll != null && libList){
      const top = Math.max(0, restoreScroll);
      requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
    }else{
      try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    }
  }

  function libSearchRebuildFilesList(items){
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    const arr = Array.isArray(items) ? items : [];
    state.items = arr;
    const max = Math.max(0, arr.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    renderList();
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
  }



  async function viewLibSearch(push){
    showNowPlaying(false);
    await setView({
      kind:"libsearch",
      label:"Search",
      load: async function(){
        libControlsHide();
        // keep existing query/filter text; list rows handle editing/focus
        state.libSearch.engine = state.libSearch.engine || "";
        libRefreshList(false);
      }
    }, push);
  }

// Library-root Tasks view (parity with Tasks tab, but in the iPod list UI)
async function viewLibTasks(push){
  showNowPlaying(false);
  await setView({
    kind:"libtasks",
    label:"Tasks",
    load: async function(){
      libControlsHide();
      try{
        const js = await apiGet("/api/tasks");
        state.libTasks.tasks = (js && js.tasks) ? js.tasks : [];
      }catch(e){
        state.libTasks.tasks = [];
      }
      libTasksRefreshList(false);
    }
  }, push);
}

function libTasksBuildItems(){
  var tasks = Array.isArray(state.libTasks.tasks) ? state.libTasks.tasks : [];
  var items = [];
  items.push({kind:"libtasks_action", label:"Clear all tasks", action:"clear_all"});
  for(const t of tasks){
    const id = String(t.id || "");
    const title = String(t.title || "Task");
    const src = String(t.source || "rd").toLowerCase();
    const stLower = String(t.state || "").toLowerCase();
    const pills = [];
    pills.push(src === "soulseek" ? "Soulseek" : (src === "youtube" ? "YouTube" : "Debrid"));
    if(t.paused) pills.push({text:"paused", tone:"warn"});
    if(stLower){
      let tone = "";
      if(stLower === "done") tone = "ok";
      else if(stLower === "error" || stLower === "canceled") tone = "warn";
      pills.push({text: stLower, tone: tone});
    }
    // light overall percent indicator when available
    try{
      const ot = Number(t.overall_total || 0);
      const od = Number(t.overall_done || 0);
      if(ot > 0){
        const pct = Math.max(0, Math.min(100, Math.floor((od / ot) * 100)));
        pills.push(String(pct) + "%");
      }
    }catch(e){}
    items.push({kind:"libtask_entry", label:title, task_id:id, pills:pills});
  }
  if(tasks.length === 0){
    items.push({kind:"info", label:"No tasks"});
  }
  return items;
}

function libTasksRefreshList(preserveSel){
  var items = libTasksBuildItems();
  var prevSel = state.sel;
  var prevScroll = (libList ? libList.scrollTop : 0);

  var restoreSel = null;
  var restoreScroll = null;
  try{
    if(state.current && typeof state.current.savedSel === "number" && isFinite(state.current.savedSel)){
      restoreSel = Number(state.current.savedSel);
    }
    if(state.current && typeof state.current.savedScroll === "number" && isFinite(state.current.savedScroll)){
      restoreScroll = Number(state.current.savedScroll);
    }
  }catch(e){ restoreSel = null; restoreScroll = null; }

  state.items = Array.isArray(items) ? items : [];
  if(preserveSel){
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
  }else if(restoreSel != null){
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, restoreSel));
  }else{
    state.sel = 0;
  }

  setHeader();
  renderList();

  if(!preserveSel && restoreScroll != null && libList){
    const top = Math.max(0, restoreScroll);
    requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
  }else{
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
  }
}

function libTaskFilesForTask(t){
  var src = String((t && t.source) || "rd").toLowerCase();
  if(src === "soulseek"){
    return Array.isArray(t.slsk_files) ? t.slsk_files : [];
  }
  return Array.isArray(t.rd_files) ? t.rd_files : [];
}

function libTaskBuildItemsForView(view){
  var t = (view && view.task) ? view.task : {};
  var files = libTaskFilesForTask(t);
  var items = [];
  var selCount = (view && view.selected && view.selected.size) ? view.selected.size : 0;

  items.push({kind:"libtask_action", label:"Pause selected", action:"pause_selected", badge: selCount ? String(selCount) : ""});
  items.push({kind:"libtask_action", label:"Cancel selected", action:"cancel_selected", badge: selCount ? String(selCount) : ""});
  items.push({kind:"libtask_action", label:"Select all", action:"selectall"});
  items.push({kind:"libtask_action", label:"Clear task", action:"clear_task"});

  var msg = String((t && t.message) || "");
  if(msg){
    items.push({kind:"info", label: msg});
  }

  for(const f of files){
    const fid = String((f && f.file_id) || "");
    const rp = String((f && (f.name || f.remote_path || f.out_path)) || "");
    const name = (rp.split("\\").pop() || rp || fid || "File");
    const stLower = String((f && f.state) || "queued").toLowerCase();
    const done = Number((f && f.done) || 0);
    const total = Number((f && f.total) || 0);

    let pct = 0;
    let bar = 0;
    let pctText = "?";
    if(total > 0){
      pct = Math.max(0, Math.min(100, Math.floor((done / total) * 100)));
      bar = pct / 100;
      pctText = String(pct) + "%";
    }else if(stLower === "complete" || stLower === "done"){
      pct = 100;
      bar = 1;
      pctText = "100%";
    }else{
      pct = 0;
      bar = 0;
      pctText = "0%";
    }

    let stTone = "";
    if(stLower === "complete" || stLower === "done") stTone = "ok";
    else if(stLower === "failed" || stLower === "error" || stLower === "canceled" || stLower === "aborted" || stLower === "incomplete" || stLower === "paused") stTone = "warn";

    const stLabel = slskDownloadLabel(stLower) || String(stLower || "").toUpperCase();
    const pills = [
      {text: stLabel, tone: stTone},
      {text: pctText, tone: ""},
      {text: "", tone: "", bar: bar}
    ];

    const item = {
      kind:"libtask_file",
      label:name,
      task_id:String(view.task_id || ""),
      file_id:fid,
      selectable:true,
      selected:(view && view.selected && fid) ? view.selected.has(fid) : false,
      pills:pills
    };
    item.onToggle = ()=>{
      if(!view.selected) view.selected = new Set();
      if(view.selected.has(fid)) view.selected.delete(fid);
      else view.selected.add(fid);
      item.selected = view.selected.has(fid);
    };
    items.push(item);
  }

  if(!files.length){
    items.push({kind:"info", label:"No files"});
  }
  return items;
}

async function viewLibTask(push, taskId){
  showNowPlaying(false);
  await setView({
    kind:"libtask",
    label:"Task",
    task_id: String(taskId || ""),
    task: null,
    selected: new Set(),
    load: async function(){
      libControlsHide();
      try{
        const js = await apiGet("/api/tasks");
        const tasks = (js && js.tasks) ? js.tasks : [];
        const t = tasks.find(x => String(x.id || "") === String(this.task_id || ""));
        this.task = t || this.task || null;
        if(t && t.title){
          this.label = String(t.title);
        }
      }catch(e){}
      setHeader();
      resetList(libTaskBuildItemsForView(this));
    }
  }, push);
}

async function libTasksPollTick(){
  var vk = (state.current && state.current.kind) ? state.current.kind : "";
  if(vk !== "libtasks" && vk !== "libtask") return;
  try{
    const js = await apiGet("/api/tasks");
    const tasks = (js && js.tasks) ? js.tasks : [];
    if(vk === "libtasks"){
      state.libTasks.tasks = tasks;
      libTasksRefreshList(true);
    }else if(vk === "libtask"){
      const view = state.current;
      const t = tasks.find(x => String(x.id || "") === String(view.task_id || ""));
      if(t){
        view.task = t;
        if(t.title) view.label = String(t.title);
      }
      const prevSel = state.sel;
      const prevScroll = (libList ? libList.scrollTop : 0);
      state.items = libTaskBuildItemsForView(view);
      const max = Math.max(0, state.items.length - 1);
      state.sel = Math.max(0, Math.min(max, prevSel));
      setHeader();
      renderList();
      try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    }
  }catch(e){}
}

// start/refresh library tasks poller
if(window.dpLibTasksTimer) clearInterval(window.dpLibTasksTimer);
window.dpLibTasksTimer = setInterval(()=>{ libTasksPollTick(); }, window.DEBRIPOD_TASKS_POLL_MS || 1200);

async function libDoSearch(engine, q){
    const qq = String(q || "").trim();
    if(!qq){
      libSetStatus("Enter a query", "warn");
      return;
    }
    const useEngine = String(engine || "combined").toLowerCase() || "combined";
    state.libSearch.q = qq;
    state.libSearch.engine = useEngine;
    state.libSearch.searching = true;
    libSetStatus("Searching", "");
    libRefreshList(true);
    try{
      const endpoint = (useEngine === "youtube") ? "/api/libsearch/youtube?q=" : "/api/libsearch/combined?q=";
      const js = await apiGet(endpoint + encodeURIComponent(qq));
      if(!js || !js.ok){
        throw new Error((js && js.error) ? js.error : "Search failed");
      }
      state.libSearch.result_source = useEngine;
      state.libSearch.cache_key = js.cache_key || "";
      state.libSearch.results = Array.isArray(js.results) ? js.results : [];
      state.libSearch.knaben_results = js.knaben_results || [];
      state.libSearch.slsk_users = js.slsk_users || [];
      state.libSearch.last_count = Number(js.result_count || state.libSearch.results.length || 0);
      state.libSearch.searching = false;
      libSetStatus(String(state.libSearch.last_count) + " results", "ok");
      libRefreshList(true);
    }catch(e){
      state.libSearch.searching = false;
      libSetStatus("Error", "warn");
      libRefreshList(true);
      alert(String(e && e.message ? e.message : e));
    }
  }

  async function viewLibSearchHistory(push){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_history",
      label:"Search history",
      load: async function(){
        libControlsHide();
        let items = [];
        items.push({kind:"libsearch_history_action", label:"Clear", action:"clear_history"});
        try{
          const js = await apiGet("/api/search_history");
          const hist = (js && js.ok && Array.isArray(js.items)) ? js.items : [];
          for(const h of hist){
            const q = h.q || "";
            const engine = h.engine || "";
            const when = h.when || "";
            const lbl = q ? q : "(empty)";
            const pills = [];
            if(engine) pills.push(engine);
            if(when) pills.push(String(when));
            items.push({kind:"libsearch_history_entry", label: lbl, engine: engine, q: q, pills: pills});
          }
          if(!items.length){
            items.push({kind:"info", label:"No search history"});
          }
        }catch(e){
          items = [{kind:"info", label:"Failed to load history"}];
        }
        resetList(items);
      }
    }, push);
  }
  
  async function viewLibInfo(push){
    showNowPlaying(false);
    await setView({
      kind:"libinfo",
      label:"Info",
      load: async function(){
        libControlsHide();
        const items = [];

        const v = (APP_INFO && APP_INFO.version) ? String(APP_INFO.version) : "dev";
        const vPills = [];
        if(v) vPills.push("v" + v);
        if(APP_INFO && APP_INFO.source) vPills.push("source: " + String(APP_INFO.source));
        if(APP_INFO && APP_INFO.short_commit) vPills.push(String(APP_INFO.short_commit));
        if(APP_INFO && APP_INFO.dirty) vPills.push({text:"dirty", tone:"warn"});
        items.push({kind:"info", label:"DebriPod", pills: vPills});

        const host = (APP_INFO && APP_INFO.host) ? String(APP_INFO.host) : (location.hostname || "");
        const port = (APP_INFO && (APP_INFO.port !== undefined && APP_INFO.port !== null)) ? String(APP_INFO.port) : (location.port || "");
        const hp = [];
        if(host) hp.push(host);
        if(port) hp.push(port);
        items.push({kind:"info", label:"Host and port", pills: hp});

        const ddir = (APP_INFO && APP_INFO.ddir) ? String(APP_INFO.ddir) : "";
        const dP = [];
        if(ddir) dP.push(ddir);
        items.push({kind:"info", label:"Debrid download dir", pills: dP});

        const sdir = (APP_INFO && APP_INFO.sdir) ? String(APP_INFO.sdir) : "";
        const sP = [];
        if(sdir) sP.push(sdir);
        items.push({kind:"info", label:"Soulseek download dir", pills: sP});

        try{
          await settingsLoad();
          const slsk = (state.connectionStatus && state.connectionStatus.SOULSEEK) ? state.connectionStatus.SOULSEEK : {};
          const slskStatus = slsk.startup_status || {};
          const statusPills = [];
          if(slsk.set) statusPills.push({text: slsk.connected ? "Connected" : "Not connected", tone: slsk.connected ? "ok" : "warn"});
          else statusPills.push({text:"Not configured", tone:"warn"});
          if(slskStatus.listening_port != null) statusPills.push("Port " + String(slskStatus.listening_port));
          if(slskStatus.obfuscated_port != null) statusPills.push("Obf " + String(slskStatus.obfuscated_port));
          items.push({kind:"info", label:"Soulseek", pills:statusPills});
          const slskMessage = String(slsk.error || slsk.warning || "");
          if(slskMessage){
            items.push({kind:"info", label: slsk.error ? "Soulseek error" : "Soulseek warning", sub_label:slskMessage, pills:[{text: slsk.error ? "Error" : "Warning", tone:"warn"}]});
          }
        }catch(e){}

        let anyBuilding = false;
        try{
          anyBuilding = await getAnyIndexBuilding();
        }catch(e){}
        const rp = anyBuilding ? ["indexing"] : [];
        items.push({kind:"libinfo_action", label:"Reindex", action:"reindex", pills: rp});

        let lfUser = "";
        try{
          const js = await apiGet("/api/lastfm/status");
          if(js && js.ok && js.username) lfUser = String(js.username || "");
        }catch(e){}
        const lp = [];
        if(lfUser) lp.push("logged in as " + lfUser);
        items.push({kind:"libinfo_action", label:"Login to Last.fm", action:"lastfm_login", pills: lp});

        items.push({kind:"libinfo_action", label:"Account", action:"account_settings"});
        items.push({kind:"libinfo_action", label:"Interface", action:"ui_settings_menu"});
        items.push({kind:"libinfo_action", label:"Library", action:"settings_library"});
        items.push({kind:"libinfo_action", label:"Downloads", action:"settings_downloads"});
        items.push({kind:"libinfo_action", label:"Services", action:"settings_services"});
        items.push({kind:"libinfo_action", label:"Playback", action:"settings_playback"});
        items.push({kind:"libinfo_action", label:"Advanced", action:"settings_advanced"});
        items.push({kind:"libinfo_action", label:"Full Screen", action:"force_fullscreen"});
        items.push({kind:"libinfo_action", label:"Binds", action:"binds_menu"});

        resetList(items);
      }
    }, push);
  }

  function titleCaseSetting(value){
    const text = String(value || "").trim();
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
  }

  function nextLiquidGlassPreset(){
    const order = Object.keys(LIQUID_GL_PRESETS);
    const idx = order.indexOf(normalizeLiquidGlassPreset(liquidGlassPresetName));
    return order[(idx + 1) % order.length] || "default";
  }

  function nextLiquidGlassMode(){
    const order = ["clear", "light", "dark"];
    const idx = order.indexOf(normalizeLiquidGlassMode(liquidGlassModeName));
    return order[(idx + 1) % order.length] || "clear";
  }

  async function viewLibUiSettings(push){
    showNowPlaying(false);
    const restoreSel = (!push && state.current && state.current.kind === "libuisettings") ? state.sel : null;
    const restoreScroll = (!push && state.current && state.current.kind === "libuisettings" && libList) ? libList.scrollTop : null;
    await setView({
      kind:"libuisettings",
      label:"Interface",
      savedSel: restoreSel,
      savedScroll: restoreScroll,
      load: async function(){
        libControlsHide();
        const items = [];
        items.push({kind:"libui_action", label:"Visualizer", action:"toggle_visualizer", pills:[visualizerEnabled ? "On" : "Off"]});
        items.push({kind:"libui_action", label:"Visualizer Strength", action:"cycle_visualizer_strength", pills:[titleCaseSetting(visualizerStrength)]});
        items.push({kind:"libui_action", label:"Visualizer Preset", action:"cycle_visualizer_preset", pills:[visualizerPresetLabel(visualizerPresetName)]});
        items.push({kind:"info", label:"Estimated Tempo", pills:[String(Math.round(visualizerBpm || 120)) + " BPM"]});
        items.push({kind:"libui_action", label:"Liquid Glass Preset", action:"cycle_liquid_preset", pills:[titleCaseSetting(liquidGlassPresetName)]});
        items.push({kind:"libui_action", label:"Liquid Glass Mode", action:"cycle_liquid_mode", pills:[titleCaseSetting(liquidGlassModeName)]});
        resetList(items);
      }
    }, push);
  }

  function uiTuningRows(){
    return [
      {action:"set_center_bounce_amount", label:"Center bounce amount", value:uiSettings.centerBounceAmount},
      {action:"set_center_bounce_duration", label:"Center bounce duration", value:uiSettings.centerBounceDuration},
      {action:"set_center_bounce_overshoot", label:"Center bounce overshoot", value:uiSettings.centerBounceOvershoot},
      {action:"set_wheel_click_tilt_amount", label:"Wheel click tilt amount", value:uiSettings.wheelClickTiltAmount},
      {action:"set_wheel_tilt_ramp_duration", label:"Wheel tilt ramp duration", value:uiSettings.wheelTiltRampDuration},
      {action:"set_wheel_tilt_release_duration", label:"Wheel tilt release duration", value:uiSettings.wheelTiltReleaseDuration},
      {action:"set_info_pill_dark_multiplier", label:"Info pill dark multiplier", value:uiSettings.infoPillDarkMultiplier},
      {action:"set_info_pill_light_multiplier", label:"Info pill light multiplier", value:uiSettings.infoPillLightMultiplier}
    ];
  }

  async function viewLibAdvancedSettings(push){
    showNowPlaying(false);
    await setView({
      kind:"libadvancedsettings",
      label:"Advanced",
      load: async function(){
        libControlsHide();
        await settingsLoad();
        const items = [];
        uiTuningRows().forEach((row)=>{
          items.push({kind:"libui_action", label:row.label, action:row.action, pills:[String(row.value)]});
        });
        settingRowsForCategory("advanced").forEach((r)=>{
          items.push({
            kind:"setting_value",
            label:r.label,
            sub_label:r.sub_label || "",
            key:r.key,
            settingType:r.type,
            choices:r.choices || [],
            value:r.value,
            tool:r.tool || "",
            toolStatus:r.toolStatus || null,
            pills:(settingConnectionPills(r) || [{text:settingValueLabel(r.value)}]).concat([settingSavePill(r)])
          });
        });
        resetList(items);
      }
    }, push);
  }


  async function viewLibBinds(push){
    showNowPlaying(false);
    await setView({
      kind:"libbinds",
      label:"Binds",
      load: async function(){
        libControlsHide();
        const items = [];

        items.push({kind:"info", label:"Navigation"});
        items.push({kind:"info", label:"W", pills:["Back or menu"]});
        items.push({kind:"info", label:"A", pills:["Previous or left"]});
        items.push({kind:"info", label:"S", pills:["Select or center"]});
        items.push({kind:"info", label:"D", pills:["Next or right"]});
        items.push({kind:"info", label:"Space", pills:["Play or pause"]});
        items.push({kind:"info", label:"Q", pills:["Scroll up"]});
        items.push({kind:"info", label:"E", pills:["Scroll down"]});
        items.push({kind:"info", label:"Mouse wheel", pills:["Scroll lists"]});
        items.push({kind:"info", label:"Arrow Up", pills:["Scroll up","Now Playing volume up","Seek left in seek mode"]});
        items.push({kind:"info", label:"Arrow Down", pills:["Scroll down","Now Playing volume down","Seek right in seek mode"]});

        resetList(items);
      }
    }, push);
  }

  async function handleLibInfoAction(action){
    switch(action){
      case "reindex":
        await doLibraryReindex();
        await viewLibInfo(false);
        return true;
      case "lastfm_login":
        await startLastfmLoginFlow();
        await viewLibInfo(false);
        return true;
      case "force_fullscreen":
        await forceFullscreenOn();
        await viewLibInfo(false);
        return true;
      case "ui_settings_menu":
        await viewLibUiSettings(true);
        return true;
      case "account_settings":
        await viewAccountSettings(true);
        return true;
      case "settings_library":
        await viewSettingsLibrary(true);
        return true;
      case "settings_downloads":
        await viewSettingsCategory("downloads", true);
        return true;
      case "settings_services":
        await viewSettingsCategory("services", true);
        return true;
      case "settings_playback":
        await viewSettingsCategory("playback", true);
        return true;
      case "settings_advanced":
        await viewLibAdvancedSettings(true);
        return true;
      case "binds_menu":
        await viewLibBinds(true);
        return true;
      default:
        return false;
    }
  }

  async function handleLibUiAction(action){
    const setNumber = async (key, label, min, max)=>{
      const current = uiSettings[key];
      const raw = prompt(label, String(current));
      if(raw == null) return true;
      uiSettings[key] = clampNumber(Number(raw), current, min, max);
      saveUiSettings();
      applyUiTuningCss();
      forceNpOverlayGlassRender("ui tuning", true);
      if(state.current && state.current.kind === "libadvancedsettings") await viewLibAdvancedSettings(false);
      else await viewLibUiSettings(false);
      return true;
    };
    switch(action){
      case "toggle_visualizer":
        setVisualizerEnabled(!visualizerEnabled);
        await viewLibUiSettings(false);
        return true;
      case "cycle_visualizer_strength":
        cycleVisualizerStrength();
        await viewLibUiSettings(false);
        return true;
      case "cycle_visualizer_preset":
        cycleVisualizerPreset();
        await viewLibUiSettings(false);
        return true;
      case "cycle_liquid_preset":
        setLiquidGlassSettings(nextLiquidGlassPreset(), liquidGlassModeName, true);
        await viewLibUiSettings(false);
        return true;
      case "cycle_liquid_mode":
        setLiquidGlassSettings(liquidGlassPresetName, nextLiquidGlassMode(), true);
        await viewLibUiSettings(false);
        return true;
      case "set_center_bounce_amount":
        return await setNumber("centerBounceAmount", "Center bounce amount", 0, 0.3);
      case "set_center_bounce_duration":
        return await setNumber("centerBounceDuration", "Center bounce duration (ms)", 0, 1000);
      case "set_center_bounce_overshoot":
        return await setNumber("centerBounceOvershoot", "Center bounce overshoot", 0, 1.4);
      case "set_wheel_click_tilt_amount":
        return await setNumber("wheelClickTiltAmount", "Wheel click tilt amount", 0, 1);
      case "set_wheel_tilt_ramp_duration":
        return await setNumber("wheelTiltRampDuration", "Wheel tilt ramp duration (ms)", 0, 1000);
      case "set_wheel_tilt_release_duration":
        return await setNumber("wheelTiltReleaseDuration", "Wheel tilt release duration (ms)", 0, 1200);
      case "set_info_pill_dark_multiplier":
        return await setNumber("infoPillDarkMultiplier", "Info pill dark multiplier", 0, 4);
      case "set_info_pill_light_multiplier":
        return await setNumber("infoPillLightMultiplier", "Info pill light multiplier", 0, 4);
      default:
        return false;
    }
  }
