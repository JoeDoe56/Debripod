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
    const roots = cfg.roots || [];
    const items = [{kind:"libsearch_entry", label:"Search"},{kind:"libtasks_entry", label:"Tasks"}].concat(roots.map(r=>({kind:"root", label:r.name, root:r})));
    if(!roots.length){
      items.push({kind:"info", label:"No library folders yet. Add one in Library settings or run setup."});
    }
    if(state.now || state.serverNow){
      items.push({kind:"nowplaying", label:"Now Playing"});
    }
    items.push({kind:"libinfo_entry", label:"Info"});
    resetList(items);
    try{ await maybeStartSetupWizard(); }catch(e){}
  }

  async function settingsLoad(){
    const js = await apiGet("/api/settings");
    state.settingsData = js || {};
    state.appSettings = Object.assign({}, (js && js.settings) || {});
    state.advancedUiDefaults = Object.assign({}, (js && js.advanced_ui_defaults) || {});
    if(window.DebriPod && DebriPod.uiSettings && DebriPod.uiSettings.applyServerAdvancedDefaults){
      DebriPod.uiSettings.applyServerAdvancedDefaults(state.advancedUiDefaults);
      uiSettings = DebriPod.uiSettings.settings;
    }
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
    if(value && typeof value === "object") return JSON.stringify(value);
    if(value === true) return "On";
    if(value === false) return "Off";
    if(value == null || value === "") return "Unset";
    if(value === "***") return "Saved";
    return String(value);
  }

  async function setupStatusLoad(){
    try{
      const js = await apiGet("/api/setup/status");
      state.setupStatus = js || {};
      return js || {};
    }catch(e){
      state.setupStatus = {};
      return {};
    }
  }

  async function maybeStartSetupWizard(){
    const js = await setupStatusLoad();
    if(js && js.ok && js.should_show && !(state.current && String(state.current.kind || "").indexOf("setupwizard") === 0)){
      await viewSetupWizardPage("library", false);
    }
  }

  function numberSettingRangeMeta(key, type){
    const k = String(key || "");
    if(k === "PORT" || k === "SOULSEEK_LISTENING_PORT" || k === "SOULSEEK_OBFUSCATED_PORT") return {min:0, max:65535, step:1, integer:true};
    if(k === "SOULSEEK_SEARCH_TIMEOUT_SEC" || k === "SOULSEEK_SEARCH_HARD_MAX_SEC") return {min:1, max:600, step:1, integer:false};
    if(k === "SOULSEEK_SEARCH_MAX_RESULTS") return {min:1, max:10000, step:1, integer:true};
    if(k === "SOULSEEK_SEARCH_IDLE_STOP_SEC") return {min:0.1, max:600, step:0.1, integer:false};
    if(k === "TASKS_POLL_MS") return {min:250, max:60000, step:250, integer:true};
    if(k === "REQUEST_TIMEOUT_SECONDS") return {min:1, max:600, step:1, integer:false};
    if(k === "WHEEL_ROTATION_MAX_DEGREES") return {min:0, max:12, step:0.1, integer:false};
    return {min:0, max:10000, step:(type === "startup_number" ? 1 : 0.1), integer:false};
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
        {key:"SOULSEEK_PASSWORD", label:"Soulseek password", type:"secret", value:s.SOULSEEK_PASSWORD, sub_label: slsk.set ? (slsk.connected ? "Soulseek is connected for this account." : "Soulseek is configured but not connected. Check username, password, and listening port in Services.") : "Set username and password to connect Soulseek for this account."},
        {key:"LASTFM_API_KEY", label:"Last.fm API key", type:"secret", value:s.LASTFM_API_KEY},
        {key:"LASTFM_API_SECRET", label:"Last.fm secret", type:"secret", value:s.LASTFM_API_SECRET},
        {key:"LASTFM_SESSION_KEY", label:"Last.fm session key", type:"secret", value:s.LASTFM_SESSION_KEY, sub_label: lf.set ? ("Last.fm session is set for this account" + (lf.username ? (": " + lf.username) : ".")) : "Last.fm is not configured. Add API credentials or skip Last.fm features.", advanced:true},
        {key:"YTDLP_CMD", label:"yt-dlp command", type:"text", value:s.YTDLP_CMD, advanced:true}
      ],
      playback: [
        {key:"PLAYBACK_STREAMING_MODE", label:"Streaming mode", type:"choice", choices:["http","hls"], value:s.PLAYBACK_STREAMING_MODE},
        {key:"PRELOAD_NEXT_FOR_GAPLESS", label:"Preload next", type:"bool", value:s.PRELOAD_NEXT_FOR_GAPLESS},
        {key:"FFMPEG_PATH", label:"ffmpeg", type:"tool_path", value:s.FFMPEG_PATH, tool:"ffmpeg", toolStatus:ffmpeg, sub_label: ffmpeg.ok ? ("Detected: " + (ffmpeg.found || "ffmpeg")) : "ffmpeg was not found. Set the ffmpeg path in Playback settings.", advanced:true},
        {key:"FFPROBE_PATH", label:"ffprobe", type:"tool_path", value:s.FFPROBE_PATH, tool:"ffprobe", toolStatus:ffprobe, sub_label: ffprobe.ok ? ("Detected: " + (ffprobe.found || "ffprobe")) : (ffprobe.install_hint || "Install ffprobe or set a path."), advanced:true}
      ],
      advanced: [
      {key:"PORT", label:"Port", type:"startup_number", value:startup.PORT},
      {key:"WHEEL_ROTATION_MAX_DEGREES", label:"Max wheel tilt", type:"number", value:(s.WHEEL_ROTATION_MAX_DEGREES == null ? 10 : s.WHEEL_ROTATION_MAX_DEGREES)},
      {key:"RESULTS_PER_PAGE", label:"Results per page", type:"number", value:s.RESULTS_PER_PAGE},
      {key:"MAX_FILES_PER_TORRENT", label:"Max files per torrent", type:"number", value:s.MAX_FILES_PER_TORRENT},
      {key:"MAX_TORRENT_WAIT_SECONDS", label:"Max torrent wait", type:"number", value:s.MAX_TORRENT_WAIT_SECONDS},
      {key:"SEARCH_HISTORY_MAX_ITEMS", label:"Search history max", type:"number", value:s.SEARCH_HISTORY_MAX_ITEMS},
      {key:"SEARCH_DISK_CACHE_TTL_SECONDS", label:"Search cache TTL", type:"number", value:s.SEARCH_DISK_CACHE_TTL_SECONDS},
      {key:"SEARCH_STREAM_SESSION_TTL_SECONDS", label:"Search stream TTL", type:"number", value:s.SEARCH_STREAM_SESSION_TTL_SECONDS},
      {key:"POLL_INTERVAL_SECONDS", label:"Poll interval", type:"number", value:s.POLL_INTERVAL_SECONDS},
      {key:"SOULSEEK_LISTENING_PORT", label:"Soulseek listen port", type:"number", value:s.SOULSEEK_LISTENING_PORT, sub_label:"Effective: " + String(slskStatus.listening_port == null ? s.SOULSEEK_LISTENING_PORT : slskStatus.listening_port)},
      {key:"SOULSEEK_OBFUSCATED_PORT", label:"Soulseek obfuscated port", type:"number", value:s.SOULSEEK_OBFUSCATED_PORT, sub_label:"Effective: " + String(slskStatus.obfuscated_port == null ? s.SOULSEEK_OBFUSCATED_PORT : slskStatus.obfuscated_port)},
      {key:"SOULSEEK_SEARCH_TIMEOUT_SEC", label:"Soulseek search timeout", type:"number", value:s.SOULSEEK_SEARCH_TIMEOUT_SEC},
      {key:"SOULSEEK_SEARCH_MAX_RESULTS", label:"Soulseek search max results", type:"number", value:s.SOULSEEK_SEARCH_MAX_RESULTS},
      {key:"SOULSEEK_SEARCH_IDLE_STOP_SEC", label:"Soulseek idle stop", type:"number", value:s.SOULSEEK_SEARCH_IDLE_STOP_SEC},
      {key:"SOULSEEK_SEARCH_HARD_MAX_SEC", label:"Soulseek hard max", type:"number", value:s.SOULSEEK_SEARCH_HARD_MAX_SEC},
      {key:"KNABEN_MIN_SECONDS_BETWEEN_REQUESTS", label:"Knaben min interval", type:"number", value:s.KNABEN_MIN_SECONDS_BETWEEN_REQUESTS},
      {key:"KNABEN_CACHE_TTL_SECONDS", label:"Knaben cache TTL", type:"number", value:s.KNABEN_CACHE_TTL_SECONDS},
      {key:"KNABEN_MAX_RETRIES", label:"Knaben retries", type:"number", value:s.KNABEN_MAX_RETRIES},
      {key:"KNABEN_API_BASE", label:"Knaben API base", type:"text", value:s.KNABEN_API_BASE},
      {key:"KNABEN_WEB_BASE", label:"Knaben web base", type:"text", value:s.KNABEN_WEB_BASE},
      {key:"YOUTUBE_STREAM_CACHE_SUBDIR", label:"YouTube stream cache", type:"text", value:s.YOUTUBE_STREAM_CACHE_SUBDIR},
      {key:"YOUTUBE_WEB_BASE", label:"YouTube web base", type:"text", value:s.YOUTUBE_WEB_BASE},
      {key:"YOUTUBE_SEARCH_LIMIT", label:"YouTube search limit", type:"number", value:s.YOUTUBE_SEARCH_LIMIT},
      {key:"YOUTUBE_CHANNEL_BROWSE_LIMIT", label:"YouTube channel limit", type:"number", value:s.YOUTUBE_CHANNEL_BROWSE_LIMIT},
      {key:"YOUTUBE_REQUEST_HEADERS", label:"YouTube request headers", type:"json", value:s.YOUTUBE_REQUEST_HEADERS},
      {key:"AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY", label:"Auto browser transcode", type:"bool", value:s.AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY},
      {key:"PRELOAD_NEXT_CHUNK_BYTES", label:"Preload chunk bytes", type:"number", value:s.PRELOAD_NEXT_CHUNK_BYTES},
      {key:"RD_BASE", label:"Real Debrid API base", type:"text", value:s.RD_BASE},
      {key:"LASTFM_CALLBACK_URL", label:"Last.fm callback URL", type:"text", value:s.LASTFM_CALLBACK_URL},
      {key:"LASTFM_API_ROOT", label:"Last.fm API root", type:"text", value:s.LASTFM_API_ROOT},
      {key:"LASTFM_REQUEST_TIMEOUT_SECONDS", label:"Last.fm timeout", type:"number", value:s.LASTFM_REQUEST_TIMEOUT_SECONDS},
      {key:"ENABLE_MCP", label:"MCP enabled", type:"startup_bool", value:startup.ENABLE_MCP},
      {key:"MCP_TOKEN", label:"Reset MCP token", type:"mcp_token", value:startup.MCP_TOKEN_SET ? "Saved" : "Unset"},
      {key:"MCP_PROTOCOL_VERSION", label:"MCP protocol", type:"text", value:s.MCP_PROTOCOL_VERSION},
      {key:"MCP_SEARCH_RESULT_LIMIT", label:"MCP result limit", type:"number", value:s.MCP_SEARCH_RESULT_LIMIT},
      {key:"MCP_SSE_KEEPALIVE_SECONDS", label:"MCP keepalive", type:"number", value:s.MCP_SSE_KEEPALIVE_SECONDS},
      {key:"MCP_SESSION_TTL_SECONDS", label:"MCP session TTL", type:"number", value:s.MCP_SESSION_TTL_SECONDS},
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
          {kind:"settings_category", category:"ui", label:"Visualizer"},
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
        items.push({kind:"account_action", label:"Export settings", action:"settings_export", pills:["No secrets"]});
        items.push({kind:"account_action", label:"Export settings with secrets", sub_label:"Includes saved service credentials. Keep the file private.", action:"settings_export_secrets", pills:[{text:"Sensitive", tone:"warn"}]});
        items.push({kind:"account_action", label:"Import settings", action:"settings_import"});
        items.push({kind:"account_action", label:"Log out", action:"logout"});
        const users = Array.isArray(js.users) ? js.users : [];
        if(users.length){
          items.push({kind:"info", label:"Users"});
          users.forEach((u)=>{
            const name = String((u && u.username) || "");
            if(name) items.push({kind:"info", label:name, pills:[name === username ? "current" : "user"]});
          });
        }
        items.push({kind:"account_action", label:"Delete current user", sub_label:"Requires your password. This removes the current local login and signs you out.", action:"delete_current_user", pills:[{text:"Danger", tone:"warn"}]});
        resetList(items);
      }
    }, !!push);
  }

  async function createUserFromInfo(){
    window.location.href = "/account/create";
  }

  async function deleteCurrentUserFromInfo(){
    const password = prompt("Enter your password to delete the current user.");
    if(password == null) return;
    if(!password){
      alert("Password is required.");
      return;
    }
    if(!confirm("Delete the current DebriPod user? This signs you out immediately.")) return;
    const res = await apiPost("/api/auth/users/delete_current", {password: password});
    const js = (res && res.json) ? res.json : {};
    if(!res || !res.ok || !js.ok){
      alert(String((js && js.error) ? js.error : "Could not delete user"));
      return;
    }
    window.location.href = js.setup_required ? "/setup" : "/login";
  }

  function serviceStatusPill(ok, goodText, badText){
    return {text: ok ? goodText : badText, tone: ok ? "ok" : "warn"};
  }

  async function viewServiceStatusPanel(push){
    showNowPlaying(false);
    await setView({
      kind:"servicestatus",
      label:"Service Status",
      load: async function(){
        libControlsHide();
        let services = {};
        try{
          const js = await apiGet("/api/services/status");
          services = (js && js.services) || {};
        }catch(e){}
        const items = [];
        const rd = services.real_debrid || {};
        items.push({kind:"info", label:"Real Debrid", sub_label: rd.status === "skipped" ? "Skipped during setup. Add a token in Services to enable debrid streaming and downloads." : "", pills:[serviceStatusPill(!!rd.configured, "Configured", rd.status === "skipped" ? "Skipped" : "Missing token")]});
        const slsk = services.soulseek || {};
        const slskPills = [serviceStatusPill(!!slsk.configured, slsk.connected ? "Connected" : "Configured", slsk.status === "skipped" ? "Skipped" : "Missing credentials")];
        if(slsk.listening_port != null) slskPills.push("Port " + String(slsk.listening_port));
        if(slsk.obfuscated_port != null) slskPills.push("Obf " + String(slsk.obfuscated_port));
        items.push({kind:"info", label:"Soulseek", sub_label:slsk.configured && !slsk.connected ? "Soulseek is configured but not connected. Check username, password, and listening port in Services." : String(slsk.error || slsk.warning || ""), pills:slskPills});
        const lf = services.lastfm || {};
        items.push({kind:"info", label:"Last.fm", sub_label:lf.api_configured ? "" : "Last.fm is not configured. Add API credentials or skip Last.fm features.", pills:[serviceStatusPill(!!lf.api_configured, lf.session_user ? ("Logged in " + String(lf.session_user)) : "API set", lf.status === "skipped" ? "Skipped" : "Missing API")]});
        const kb = services.knaben || {};
        items.push({kind:"info", label:"Knaben", pills:[{text:kb.api_key_configured ? "API key set" : "Optional"}]});
        const yt = services.youtube || {};
        const ytTool = yt.tool || {};
        items.push({kind:"info", label:"YouTube", sub_label:String(yt.download_dir || ""), pills:[serviceStatusPill(!!ytTool.ok, "yt-dlp found", yt.status === "skipped" ? "Skipped" : "yt-dlp missing")]});
        const ffmpeg = services.ffmpeg || {};
        items.push({kind:"info", label:"ffmpeg", sub_label:ffmpeg.ok ? String(ffmpeg.found || "") : "ffmpeg was not found. Set the ffmpeg path in Playback settings.", pills:[serviceStatusPill(!!ffmpeg.ok, "Detected", "Missing")]});
        const ffprobe = services.ffprobe || {};
        items.push({kind:"info", label:"ffprobe", sub_label:String(ffprobe.install_hint || ""), pills:[serviceStatusPill(!!ffprobe.ok, "Detected", "Missing")]});
        resetList(items);
      }
    }, !!push);
  }

  async function exportUserSettings(includeSecrets){
    const js = await apiGet("/api/settings/export?include_secrets=" + (includeSecrets ? "1" : "0"));
    const text = JSON.stringify(js, null, 2);
    try{
      if(navigator.clipboard && navigator.clipboard.writeText){
        await navigator.clipboard.writeText(text);
        alert("Settings export copied to clipboard.");
        return true;
      }
    }catch(e){}
    prompt("Settings export", text);
    return true;
  }

  async function importUserSettings(){
    const raw = prompt("Paste settings export JSON", "");
    if(raw == null) return false;
    let parsed = null;
    try{ parsed = JSON.parse(raw); }catch(e){ alert("Invalid JSON"); return false; }
    const includeSecrets = !!confirm("Import service secrets if this export contains them?");
    const res = await apiPost("/api/settings/import", {settings:(parsed && parsed.settings) || parsed, include_secrets:includeSecrets});
    const js = res && res.json ? res.json : {};
    if(!res || !res.ok || !js.ok){
      alert((js && js.error) ? js.error : "Settings import failed.");
      return false;
    }
    await settingsLoad();
    alert("Settings imported.");
    return true;
  }

  async function setupFinish(){
    const res = await apiPost("/api/setup/finish", {});
    const js = res && res.json ? res.json : {};
    if(!res || !res.ok || !js.ok){
      libSetStatus((js && js.error) ? js.error : "Setup is not complete yet.", "warn");
      await viewSetupWizardPage("library", false);
      return false;
    }
    await showRoots(true);
    return true;
  }

  async function setupSkipMany(services, nextPage){
    const list = Array.isArray(services) ? services : [services];
    for(const service of list){
      const key = String(service || "").trim();
      if(!key) continue;
      const res = await apiPost("/api/setup/skip", {service:key});
      const js = res && res.json ? res.json : {};
      if(!res || !res.ok || !js.ok){
        libSetStatus((js && js.error) ? js.error : "Could not skip setup step.", "warn");
        return false;
      }
    }
    if(nextPage === "finish") return await setupFinish();
    await viewSetupWizardPage(nextPage || "library", true);
    return true;
  }

  async function viewSettingsCategory(category, push){
    const labels = {ui:"Visualizer", downloads:"Downloads", services:"Services", playback:"Playback", advanced:"Advanced"};
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
        if(category === "services"){
          rows.unshift({kind:"libinfo_action", label:"Service Status", action:"service_status"});
        }
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
        if(!folders.length) items.push({kind:"info", label:"No library folders yet. Add one in Library settings or run setup."});
        resetList(items);
      }
    };
    await setView(view, !!push);
  }

  async function viewSettingsLibraryMode(folderPath, folderIndex, push, setupReturnOverride){
    const isExisting = typeof folderIndex === "number" && folderIndex >= 0;
    const setupReturnPage = setupReturnOverride ? String(setupReturnOverride) : ((state.current && state.current.setupReturnPage) ? String(state.current.setupReturnPage) : ((state.current && state.current.kind === "setup_editor") ? String(state.current.setupEditorReturnPage || "") : ""));
    const view = {
      kind:"settings_library_mode",
      label:"Folder Type",
      folderPath:String(folderPath || ""),
      folderIndex:isExisting ? folderIndex : -1,
      setupReturnPage:setupReturnPage,
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

  async function viewSetupRemoveFolderConfirm(folderIndex, folderPath, returnPage, push){
    await setView({
      kind:"setupwizard_confirm",
      setupPage:"remove_library_folder_confirm",
      setupReturnPage:String(returnPage || "library"),
      setupFolderIndex:Number(folderIndex),
      label:"Remove folder?",
      load: async function(){
        resetList([
          {kind:"info", label:"Remove folder?", sub_label:"This removes the folder from DebriPod setup. It does not delete files from disk.", pills:[{text:"Delete", tone:"warn"}], forceTwoLine:true},
          {kind:"libinfo_action", label:"Remove folder", action:"setup_remove_library_folder_confirmed", sub_label:String(folderPath || ""), pills:[{text:"Delete", tone:"warn"}], forceTwoLine:true},
          {kind:"libinfo_action", label:"Go back", action:"setup_remove_library_folder_cancel"}
        ]);
      }
    }, !!push);
  }

  async function viewSetupLastfmAuthPage(push){
    await setView({
      kind:"setupwizard_lastfm_auth",
      setupPage:"lastfm_auth",
      label:"Last.fm authorize",
      load: async function(){
        const auth = state.setupLastfmAuth || {};
        const rows = [
          {kind:"info", label:"Last.fm authorize", sub_label:"DebriPod will open Last.fm for approval. After approving DebriPod in the browser window, return here and select Finish authorization.", pills:[auth.token ? "Opened" : "Authorize"], forceTwoLine:true},
          {kind:"libinfo_action", label:"Open approval page", action:"setup_lastfm_auth_open", pills:[auth.token ? "Reopen" : "Authorize"]},
          {kind:"libinfo_action", label:"Finish authorization", action:"setup_lastfm_auth_finish", pills:[auth.token ? "Ready" : {text:"Open first", tone:"warn"}]},
          {kind:"libinfo_action", label:"Go back", action:"setup_page:soulseek_lastfm"}
        ];
        if(auth.message) rows.unshift({kind:"info", label:"Last.fm status", sub_label:String(auth.message || ""), pills:[auth.error ? {text:"Error", tone:"warn"} : "Status"], forceTwoLine:true});
        resetList(rows);
      }
    }, !!push);
  }

  async function setupLastfmAuthOpen(){
    state.setupLastfmAuth = {message:"Starting Last.fm authorization...", error:false};
    try{
      const r = await fetch("/api/lastfm/auth/start", {method:"GET"});
      const j = await r.json();
      if(!j || !j.ok) throw new Error((j && j.error) ? j.error : "Last.fm auth start failed");
      state.setupLastfmAuth = {token:String(j.token || ""), authUrl:String(j.auth_url || ""), message:"Approval page opened. Approve DebriPod, then finish authorization here.", error:false};
      try{ if(j.auth_url) window.open(j.auth_url, "_blank", "noopener"); }catch(e){}
    }catch(e){
      state.setupLastfmAuth = {message:"Last.fm login failed: " + String(e && e.message ? e.message : e), error:true};
    }
    await viewSetupLastfmAuthPage(false);
    return true;
  }

  async function setupLastfmAuthFinish(){
    const auth = state.setupLastfmAuth || {};
    if(!auth.token){
      state.setupLastfmAuth = {message:"Open the approval page before finishing authorization.", error:true};
      await viewSetupLastfmAuthPage(false);
      return true;
    }
    try{
      const r = await fetch("/api/lastfm/auth/finish", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({token:auth.token})
      });
      const j = await r.json();
      if(!j || !j.ok) throw new Error((j && j.error) ? j.error : "Last.fm auth finish failed");
      state.setupLastfmAuth = {message:"Last.fm login complete.", error:false};
      await viewSetupWizardPage("soulseek_lastfm", false);
    }catch(e){
      state.setupLastfmAuth = {token:auth.token, authUrl:auth.authUrl, message:"Last.fm login failed: " + String(e && e.message ? e.message : e), error:true};
      await viewSetupLastfmAuthPage(false);
    }
    return true;
  }

  async function settingsPickPath(kind){
    const res = await apiPost("/api/settings/pick_path", {kind:kind || "directory"});
    const js = (res && res.json) ? res.json : {};
    if(res && res.ok && js && js.ok && js.path) return String(js.path || "");
    const fallback = prompt("Enter path", "");
    return fallback ? String(fallback).trim() : "";
  }

  async function setupPickPath(kind){
    const res = await apiPost("/api/settings/pick_path", {kind:kind || "directory"});
    const js = (res && res.json) ? res.json : {};
    if(res && res.ok && js && js.ok && js.path) return String(js.path || "");
    return "";
  }

  async function viewSetupEditor(opts, push){
    const options = opts || {};
    const key = String(options.key || "");
    const label = String(options.label || key || "Value");
    const returnPage = String(options.returnPage || "library");
    const current = options.value == null ? "" : String(options.value);
    await setView({
      kind:"setup_editor",
      label:label,
      setupEditorKey:key,
      setupEditorSecret:!!options.secret,
      setupEditorReturnPage:returnPage,
      setupEditorIsDirectory:!!options.directory,
      setupEditorLibraryPath:!!options.libraryPath,
      editorValue:current,
      load: async function(){
        libControlsHide();
        const rows = [
          {kind:"info", label:label, sub_label:options.directory ? "Enter a local folder path. This stays inside DebriPod when the system picker is unavailable or canceled." : "Enter the value, then select Save.", pills:[options.secret ? "Secret" : "Edit"], forceTwoLine:true},
          {kind:"setup_text_input", label:label, value:current, secret:!!options.secret, placeholder:label, forceTwoLine:true},
          {kind:"libinfo_action", label:"Save", action:"setup_editor_save", pills:["Save"]},
          {kind:"libinfo_action", label:"Cancel", action:"setup_editor_cancel"}
        ];
        resetList(rows);
      }
    }, !!push);
  }

  async function commitSetupEditor(){
    const cur = state.current || {};
    if(cur.kind !== "setup_editor") return false;
    const value = String(cur.editorValue == null ? "" : cur.editorValue).trim();
    const returnPage = String(cur.setupEditorReturnPage || "library");
    if(cur.setupEditorLibraryPath){
      if(!value){
        libSetStatus("Enter a folder path first.", "warn");
        return false;
      }
      await viewSettingsLibraryMode(value, -1, true);
      return true;
    }
    const key = String(cur.setupEditorKey || "");
    if(!key) return false;
    await settingsSave({[key]: value}, {});
    await viewSetupWizardPage(returnPage, false);
    return true;
  }
  try{ window.commitSetupEditor = commitSetupEditor; }catch(e){}

  async function editSettingRow(row){
    const key = String(row.key || "");
    const type = String(row.settingType || "text");
    if(!key) return;
    const returnKind = state.current && state.current.kind;
    const returnAdvancedCategory = state.current && state.current.advancedCategory;
    const returnSettingsCategory = state.current && state.current.category;
    const refreshAfterSettingEdit = async ()=>{
      if(returnKind === "libadvancedsettings") await viewLibAdvancedSettings(false);
      else if(returnKind === "libadvancedcategory") await viewLibAdvancedCategory(returnAdvancedCategory || "system", false);
      else await viewSettingsCategory(returnSettingsCategory || "advanced", false);
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
    if(type === "json"){
      const raw = prompt(row.label || key, JSON.stringify(row.value == null ? {} : row.value, null, 2));
      if(raw == null) return;
      let value = {};
      try{
        value = JSON.parse(raw);
      }catch(e){
        alert("Invalid JSON");
        return;
      }
      await settingsSave({[key]: value}, {});
      await refreshAfterSettingEdit();
      return;
    }
    if(type === "number" || type === "startup_number"){
      await viewRangeEditor({
        label: row.label || key,
        current: Number(row.value == null ? 0 : row.value),
        meta: numberSettingRangeMeta(key, type),
        onCommit: async function(value){
          const next = numberSettingRangeMeta(key, type).integer ? Math.trunc(value) : value;
          if(type === "startup_number") await settingsSave({}, {[key]: next});
          else await settingsSave({[key]: next}, {});
        },
        onReturn: refreshAfterSettingEdit
      }, true);
      return;
    }
    const raw = prompt(row.label || key, (row.value === "***") ? "" : String(row.value == null ? "" : row.value));
    if(raw == null) return;
    let value = raw;
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
    if(state.libSearch && Array.isArray(state.libSearch.source_status)){
      for(const src of state.libSearch.source_status){
        if(!src) continue;
        const label = String(src.label || src.source || "");
        const count = Number(src.result_count || 0);
        const err = String(src.error || "");
        if(err) qPills.push({text: label + " error", tone:"warn"});
        else if(label) qPills.push({text: label + " " + String(count), tone: src.done === false ? "" : "ok"});
      }
    }
    items.push({kind:"libsearch_query", label:"Enter query", pills: qPills});
    items.push({kind:"libsearch_filter", label:"Enter filters"});

    items.push({kind:"libsearch_action", label:"Clear"});
    items.push({kind:"libsearch_action", label:"Search history"});
    if(state.libSearch && Array.isArray(state.libSearch.source_status)){
      for(const src of state.libSearch.source_status){
        const err = String((src && src.error) || "").trim();
        if(err){
          items.push({kind:"info", label:String(src.label || src.source || "Source") + ": " + err});
        }
      }
    }

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
    if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.isServerUnavailable && DebriPod.clientSync.isServerUnavailable()){
      return;
    }
  }catch(e){}
  try{
    const js = await apiGet("/api/tasks");
    const tasks = (js && js.tasks) ? js.tasks : [];
    const signature = JSON.stringify(tasks.map(t=>({
      id:t.id || "",
      state:t.state || "",
      paused:!!t.paused,
      message:t.message || "",
      overall_done:t.overall_done || 0,
      overall_total:t.overall_total || 0,
      rd_files:(t.rd_files || []).map(f=>[f.file_id, f.state, f.done, f.total]),
      slsk_files:(t.slsk_files || []).map(f=>[f.file_id, f.state, f.done, f.total])
    })));
    if(state.libTasks && state.libTasks.lastSignature === signature) return;
    if(!state.libTasks) state.libTasks = {tasks:[]};
    state.libTasks.lastSignature = signature;
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
if(window.dpLibTasksTimer) clearTimeout(window.dpLibTasksTimer);
function scheduleLibTasksPoll(delay){
  try{
    if(window.dpLibTasksTimer) clearTimeout(window.dpLibTasksTimer);
    window.dpLibTasksTimer = setTimeout(async ()=>{
      try{ await libTasksPollTick(); }catch(e){}
      const visible = !!(state.current && (state.current.kind === "libtasks" || state.current.kind === "libtask"));
      const base = Number(window.DEBRIPOD_TASKS_POLL_MS || 1200);
      const next = visible ? base : Math.max(15000, base * 6);
      scheduleLibTasksPoll(document.hidden ? Math.max(30000, next) : next);
    }, Math.max(500, Number(delay || window.DEBRIPOD_TASKS_POLL_MS || 1200)));
  }catch(e){}
}
scheduleLibTasksPoll(window.DEBRIPOD_TASKS_POLL_MS || 1200);
try{
  document.addEventListener("visibilitychange", ()=>{
    scheduleLibTasksPoll(document.hidden ? 30000 : 500);
  });
}catch(e){}

async function libDoSearch(engine, q){
    const qq = String(q || "").trim();
    if(!qq){
      libSetStatus("Enter a query", "warn");
      return;
    }
    try{
      if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.isServerUnavailable && DebriPod.clientSync.isServerUnavailable()){
        libSetStatus(DebriPod.clientSync.serverRequiredMessage ? DebriPod.clientSync.serverRequiredMessage("Search") : "Search requires the local DebriPod server.", "warn");
        if(state.libSearch) state.libSearch.searching = false;
        libRefreshList(true);
        return;
      }
    }catch(e){}
    const useEngine = String(engine || "combined").toLowerCase() || "combined";
    state.libSearch.q = qq;
    state.libSearch.engine = useEngine;
    const searchToken = Date.now() + ":" + Math.random().toString(16).slice(2);
    state.libSearch.search_token = searchToken;
    state.libSearch.searching = true;
    state.libSearch.source_status = [];
    libSetStatus("Searching", "");
    libRefreshList(true);
    try{
      const js = useEngine === "combined" ? await libSearchCombinedProgressive(qq, searchToken) : await apiGet("/api/libsearch/youtube?q=" + encodeURIComponent(qq));
      if(state.libSearch.search_token !== searchToken) return;
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
      state.libSearch.source_status = Array.isArray(js.source_status) ? js.source_status : state.libSearch.source_status;
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

        const v = (APP_INFO && APP_INFO.display_version) ? String(APP_INFO.display_version) : ((APP_INFO && APP_INFO.version) ? ("v" + String(APP_INFO.version)) : "vdev");
        const vPills = [];
        if(v) vPills.push(v);
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

        items.push({kind:"libinfo_action", label:"Full Screen", action:"force_fullscreen"});
        items.push({kind:"libinfo_action", label:"Binds", action:"binds_menu"});

        try{
          await settingsLoad();
        }catch(e){}

        items.push({kind:"libinfo_action", label:"Account", action:"account_settings"});
        items.push({kind:"libinfo_action", label:"Visualizer", action:"ui_settings_menu"});
        items.push({kind:"libinfo_action", label:"Library", action:"settings_library"});
        items.push({kind:"libinfo_action", label:"Downloads", action:"settings_downloads"});
        const svcPills = [];
        try{
          const settings = state.appSettings || {};
          const connections = state.connectionStatus || {};
          const tools = state.toolStatus || {};
          const slsk = connections.SOULSEEK || {};
          const lf = connections.LASTFM_SESSION || {};
          const rd = connections.REAL_DEBRID_API_KEY || {};
          const knaben = connections.KNABEN_API_KEY || {};
          svcPills.push({text: rd.set ? "Debrid set" : "Debrid unset", tone: rd.set ? "ok" : "warn"});
          svcPills.push({text: slsk.set ? (slsk.connected ? "Soulseek connected" : "Soulseek not connected") : "Soulseek unset", tone: slsk.set && slsk.connected ? "ok" : "warn"});
          svcPills.push({text: lf.set ? (lf.username ? ("Last.fm " + String(lf.username)) : "Last.fm set") : "Last.fm unset", tone: lf.set ? "ok" : "warn"});
          svcPills.push({text: knaben.set ? "Knaben set" : "Knaben optional", tone: knaben.set ? "ok" : ""});
          svcPills.push({text: settings.YTDLP_CMD ? "YouTube tool" : "YouTube default"});
          if(tools.ffmpeg && tools.ffmpeg.ok === false) svcPills.push({text:"ffmpeg missing", tone:"warn"});
        }catch(e){}
        items.push({kind:"libinfo_action", label:"Services", action:"settings_services", pills:svcPills});
        items.push({kind:"libinfo_action", label:"Service Status", action:"service_status"});
        items.push({kind:"libinfo_action", label:"Playback", action:"settings_playback"});
        items.push({kind:"libinfo_action", label:"Advanced", action:"settings_advanced"});

        resetList(items);
      }
    }, push);
  }

  function titleCaseSetting(value){
    const text = String(value || "").trim();
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
  }

  function glassElementLabel(key){
    const settings = cloneGlassElementSettings(uiSettings.liquidGlassElements);
    return (settings[key] && settings[key].label) || key;
  }

  async function viewSetupWizard(push){
    return viewSetupWizardPage("library", push);
  }

  function setupRequiredPill(status, skipped){
    return status.library_folder_count ? "Configured" : "Required";
  }

  function setupToolStatus(status, key){
    const tools = (status && status.tools) || {};
    const services = (status && status.services) || {};
    if(key === "ytdlp") return tools.ytdlp || tools.yt_dlp || (services.youtube && services.youtube.tool) || {};
    return tools[key] || services[key] || {};
  }

  function setupConfigured(status, path, fallback){
    let cur = status || {};
    String(path || "").split(".").forEach((part)=>{ cur = cur && cur[part]; });
    if(cur === undefined || cur === null) cur = fallback;
    return !!cur;
  }

  function setupDisplayPath(value){
    return value ? String(value) : "Not set";
  }

  function setupFolderRows(folders){
    return (Array.isArray(folders) ? folders : []).map((f, idx)=>{
      const path = String((f && f.path) || f || "");
      const mode = String((f && f.mode) || "list").toLowerCase();
      return {
        kind:"settings_library_folder",
        setupReturnPage:"library",
        label:settingPathBase(path),
        sub_label:path,
        folderIndex:idx,
        pills:[{text: mode === "meta" || mode === "metadata" ? "Metadata" : "List"}],
        forceTwoLine:true
      };
    });
  }

  function setupPageLabel(page){
    const p = String(page || "library");
    if(p === "library") return "Add a library folder (required)";
    if(p === "tools") return "Optional tools";
    if(p === "soulseek_lastfm") return "Soulseek and Last.fm";
    if(p === "realdebrid") return "Real Debrid";
    if(p === "skip_tools_confirm") return "Skip optional tools?";
    if(p === "skip_soulseek_lastfm_confirm") return "Skip Soulseek and Last.fm?";
    if(p === "skip_realdebrid_confirm") return "Skip Real Debrid?";
    return "Setup";
  }

  async function viewSetupWizardPage(page, push){
    const setupPage = String(page || "library");
    showNowPlaying(false);
    await setView({
      kind:"setupwizard",
      setupPage:setupPage,
      label:setupPageLabel(setupPage),
      load: async function(){
        libControlsHide();
        const status = await setupStatusLoad();
        const skipped = (status && status.skipped) || {};
        const setup = (status && status.setup) || {};
        const settings = (status && status.settings) || {};
        const folders = (status && (status.library_folders || status.folders)) || [];
        const items = [];
        const ffmpeg = setupToolStatus(status, "ffmpeg");
        const ffprobe = setupToolStatus(status, "ffprobe");
        const ytdlp = setupToolStatus(status, "ytdlp");
        const youtubeFolderSet = setupConfigured(status, "setup.youtube_download_folder_configured", !!settings.YOUTUBE_DOWNLOAD_DIR);
        const slUser = setupConfigured(status, "setup.soulseek_username_configured", false);
        const slPass = setupConfigured(status, "setup.soulseek_password_configured", false);
        const slDir = setupConfigured(status, "setup.soulseek_download_folder_configured", !!settings.SOULSEEK_DOWNLOAD_DIR);
        const lfKey = setupConfigured(status, "setup.lastfm_api_key_configured", false);
        const lfSecret = setupConfigured(status, "setup.lastfm_secret_configured", false);
        const lfSession = setupConfigured(status, "setup.lastfm_session_configured", false);
        const rdToken = setupConfigured(status, "setup.real_debrid_token_configured", false);
        const rdDir = setupConfigured(status, "setup.real_debrid_download_folder_configured", !!settings.DOWNLOAD_DIR);
        const toolsDone = !!ffmpeg.ok && !!ffprobe.ok && !!ytdlp.ok && youtubeFolderSet;
        const soulLastDone = slUser && slPass && slDir && lfKey && lfSecret && lfSession;
        const rdDone = rdToken && rdDir;
        if(setupPage === "library"){
          items.push({kind:"info", label:"Why this is required", sub_label:"DebriPod needs at least one local folder for initial library indexing. This enables local browsing, artwork palettes, playback history, and precomputed local audio analysis. You can add more folders later from Library settings.", pills:[setupRequiredPill(status, skipped)], forceTwoLine:true});
          items.push({kind:"settings_add_library_folder", setupReturnPage:"library", label:"Add folder", sub_label:"Choose a folder, then pick Metadata folder or List folder.", pills:["Required"], forceTwoLine:true});
          setupFolderRows(folders).forEach((row)=>items.push(row));
          if(status.library_folder_count){
            items.push({kind:"libinfo_action", label:"Continue", sub_label:"Move to optional tool setup.", action:"setup_page:tools", pills:["Ready"]});
          }else{
            items.push({kind:"info", label:"Required", sub_label:"Add at least one local library folder before setup can continue.", pills:[{text:"Required", tone:"warn"}], forceTwoLine:true});
          }
        }else if(setupPage === "tools"){
          items.push({kind:"info", label:"Optional tools", sub_label:"ffmpeg, ffprobe, and yt-dlp improve metadata, thumbnails, transcoding, compatibility conversion, external downloads, and precompute features. The app can still run if they are skipped, but some features will be limited.", pills:["Optional"], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"ffmpeg", sub_label:ffmpeg.ok ? ("Detected: " + String(ffmpeg.path || ffmpeg.found || "ffmpeg")) : "Missing. Select to set a command or path.", action:"setup_edit:FFMPEG_PATH:ffmpeg:tools", pills:[ffmpeg.ok ? "Detected" : {text:"Missing", tone:"warn"}], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"ffprobe", sub_label:ffprobe.ok ? ("Detected: " + String(ffprobe.path || ffprobe.found || "ffprobe")) : "Missing. Select to set a command or path.", action:"setup_edit:FFPROBE_PATH:ffprobe:tools", pills:[ffprobe.ok ? "Detected" : {text:"Missing", tone:"warn"}], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"yt-dlp", sub_label:ytdlp.ok ? ("Detected: " + String(ytdlp.path || ytdlp.found || "yt-dlp")) : "Missing. Select to set a command or path.", action:"setup_edit:YTDLP_CMD:yt-dlp:tools", pills:[ytdlp.ok ? "Detected" : {text:"Missing", tone:"warn"}], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"yt-dlp download folder", sub_label:setupDisplayPath(settings.YOUTUBE_DOWNLOAD_DIR), action:"setup_dir:YOUTUBE_DOWNLOAD_DIR:yt-dlp download folder:tools", pills:[youtubeFolderSet ? "Configured" : {text:"Missing", tone:"warn"}], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:toolsDone ? "Finish tools" : "Skip tools", sub_label:toolsDone ? "Continue to Soulseek and Last.fm." : "Missing tools may limit thumbnails, metadata extraction, transcoding, compatibility conversion, downloads, and precompute.", action:toolsDone ? "setup_page:soulseek_lastfm" : "setup_page:skip_tools_confirm", pills:[toolsDone ? "Finish" : "Optional"], forceTwoLine:true});
        }else if(setupPage === "soulseek_lastfm"){
          items.push({kind:"info", label:"Soulseek and Last.fm", sub_label:"Soulseek enables Soulseek search and downloads when credentials are configured. Last.fm enables scrobbling, loved track sync, and metadata actions after API credentials and authorization. Both are optional and can be configured later from Services settings.", pills:["Optional"], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"Soulseek username", sub_label:slUser ? "Configured" : "Missing", action:"setup_edit:SOULSEEK_USERNAME:Soulseek username:soulseek_lastfm", pills:[slUser ? "Configured" : {text:"Missing", tone:"warn"}]});
          items.push({kind:"libinfo_action", label:"Soulseek password", sub_label:slPass ? "Configured" : "Missing", action:"setup_secret:SOULSEEK_PASSWORD:Soulseek password:soulseek_lastfm", pills:[slPass ? "Configured" : {text:"Missing", tone:"warn"}]});
          items.push({kind:"libinfo_action", label:"Soulseek download folder", sub_label:setupDisplayPath(settings.SOULSEEK_DOWNLOAD_DIR), action:"setup_dir:SOULSEEK_DOWNLOAD_DIR:Soulseek download folder:soulseek_lastfm", pills:[slDir ? "Configured" : {text:"Missing", tone:"warn"}], forceTwoLine:true});
          items.push({kind:"info", label:"Last.fm setup help", sub_label:"To use Last.fm, create or sign in to a Last.fm account, create an API application, then copy the API key and shared secret into DebriPod. After saving them, use the authorize row to create a session for scrobbling and loved track sync.", pills:["Help"], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"Last.fm API key", sub_label:lfKey ? "Configured" : "Missing", action:"setup_secret:LASTFM_API_KEY:Last.fm API key:soulseek_lastfm", pills:[lfKey ? "Configured" : {text:"Missing", tone:"warn"}]});
          items.push({kind:"libinfo_action", label:"Last.fm secret", sub_label:lfSecret ? "Configured" : "Missing", action:"setup_secret:LASTFM_API_SECRET:Last.fm secret:soulseek_lastfm", pills:[lfSecret ? "Configured" : {text:"Missing", tone:"warn"}]});
          items.push({kind:"libinfo_action", label:"Last.fm session / authorize", sub_label:lfSession ? "Last.fm session is configured." : "Authorize after saving API key and secret.", action:"setup_lastfm_authorize", pills:[lfSession ? "Authorized" : "Authorize"], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:soulLastDone ? "Finish Soulseek and Last.fm" : "Skip Soulseek and Last.fm", sub_label:soulLastDone ? "Continue to Real Debrid." : "Skipping keeps these features unavailable until credentials, folders, and authorization are configured.", action:soulLastDone ? "setup_page:realdebrid" : "setup_page:skip_soulseek_lastfm_confirm", pills:[soulLastDone ? "Finish" : "Optional"], forceTwoLine:true});
        }else if(setupPage === "realdebrid"){
          items.push({kind:"info", label:"Real Debrid", sub_label:"Real Debrid enables debrid-backed streaming and downloads plus torrent/debrid lookup actions. It is optional and can be configured later, but a token is required for Real Debrid features.", pills:["Optional"], forceTwoLine:true});
          items.push({kind:"info", label:"How to get a token", sub_label:"Sign in to Real Debrid, open the API token page in your account settings, copy the private API token, and paste it here. Keep it private because it gives access to your Real Debrid account features.", pills:["Help"], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"Real Debrid token", sub_label:rdToken ? "Configured" : "Missing", action:"setup_secret:REAL_DEBRID_API_KEY:Real Debrid token:realdebrid", pills:[rdToken ? "Configured" : {text:"Missing", tone:"warn"}]});
          items.push({kind:"libinfo_action", label:"Real Debrid download folder", sub_label:setupDisplayPath(settings.DOWNLOAD_DIR), action:"setup_dir:DOWNLOAD_DIR:Real Debrid download folder:realdebrid", pills:[rdDir ? "Configured" : {text:"Missing", tone:"warn"}], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:rdDone ? "Finish setup" : "Skip Real Debrid", sub_label:rdDone ? "Complete setup and start indexing." : "Skipping leaves debrid streaming/downloads and torrent lookup unavailable until configured.", action:rdDone ? "setup_finish" : "setup_page:skip_realdebrid_confirm", pills:[rdDone ? "Finish" : "Optional"], forceTwoLine:true});
        }else if(setupPage === "skip_tools_confirm"){
          items.push({kind:"info", label:"Skip optional tools?", sub_label:"Missing tools may limit thumbnails, metadata extraction, transcoding, compatibility conversion, YouTube/local video downloads, and precompute features.", pills:["Optional"], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"Skip and continue", action:"setup_skip_tools_confirmed", pills:["Skipped"]});
          items.push({kind:"libinfo_action", label:"Go back", action:"setup_page:tools"});
        }else if(setupPage === "skip_soulseek_lastfm_confirm"){
          items.push({kind:"info", label:"Skip Soulseek and Last.fm?", sub_label:"Soulseek search/downloads remain unavailable until credentials and folders are configured. Scrobbling, loved track sync, and Last.fm metadata actions remain unavailable until credentials and authorization are configured.", pills:["Optional"], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"Skip and continue", action:"setup_skip_soulseek_lastfm_confirmed", pills:["Skipped"]});
          items.push({kind:"libinfo_action", label:"Go back", action:"setup_page:soulseek_lastfm"});
        }else if(setupPage === "skip_realdebrid_confirm"){
          items.push({kind:"info", label:"Skip Real Debrid?", sub_label:"Real Debrid streaming/downloads, torrent lookup/download actions, and debrid-backed playback will be unavailable until a token is added. You can configure Real Debrid later from Services settings.", pills:["Optional"], forceTwoLine:true});
          items.push({kind:"libinfo_action", label:"Skip and finish setup", action:"setup_skip_realdebrid_confirmed", pills:["Finish"]});
          items.push({kind:"libinfo_action", label:"Go back", action:"setup_page:realdebrid"});
        }else{
          items.push({kind:"libinfo_action", label:"Add a library folder (required)", action:"setup_page:library", pills:[setupRequiredPill(status, skipped)]});
        }
        resetList(items);
      }
    }, !!push);
  }

  function glassTintLabel(value){
    const tint = normalizeLiquidGlassTint(value, 1);
    if(tint < 0.995) return tint.toFixed(2) + " Dark";
    if(tint > 1.005) return tint.toFixed(2) + " Light";
    return "1.00 Clear";
  }

  function glassElementSummary(key){
    const settings = cloneGlassElementSettings(uiSettings.liquidGlassElements);
    const item = settings[key] || {};
    return [
      glassTintLabel(item.glassTint),
      "R " + String(item.refraction),
      "B " + String(item.bevelDepth)
    ];
  }

  async function viewLibUiSettings(push){
    showNowPlaying(false, {immediate:true});
    try{ if(libList){ libList.style.display = "block"; libList.classList.remove("npUnderlay", "pageFadeHidden"); } }catch(e){}
    const restoreSel = (!push && state.current && state.current.kind === "libuisettings") ? state.sel : null;
    const restoreScroll = (!push && state.current && state.current.kind === "libuisettings" && libList) ? libList.scrollTop : null;
    await setView({
      kind:"libuisettings",
      label:"Visualizer",
      savedSel: restoreSel,
      savedScroll: restoreScroll,
      load: async function(){
        libControlsHide();
        const items = [];
        const vizOn = (typeof visualizerEnabled === "boolean") ? visualizerEnabled : !!uiSettings.visualizer;
        const presetName = (typeof visualizerPresetName !== "undefined") ? visualizerPresetName : normalizeVisualizerPreset(uiSettings.visualizerPreset);
        const presetLabel = (typeof visualizerPresetLabel === "function") ? visualizerPresetLabel(presetName) : String(presetName || "album");
        const fps = (typeof visualizerFpsLock !== "undefined") ? visualizerFpsLock : uiSettings.visualizerFpsLock;
        const bpm = (typeof visualizerBpm !== "undefined") ? visualizerBpm : (state.visualizerBpm || 120);
        items.push({kind:"libui_action", label:"Visualizer", action:"toggle_visualizer", pills:[vizOn ? "On" : "Off"]});
        items.push({
          kind:"libui_action",
          label:"Max visualizer brightness",
          sub_label:"At 100%, the brightest visualizer output is capped to the measured album cover brightness.",
          action:"set_visualizer_max_brightness",
          pills:[String(normalizeVisualizerMaxBrightnessPct(uiSettings.visualizerMaxBrightnessPct)) + "% of album cover"],
          forceTwoLine:true,
          settingRow:true
        });
        items.push({kind:"libui_action", label:"Visualizer Preset", action:"cycle_visualizer_preset", pills:[presetLabel]});
        items.push({kind:"libui_action", label:"FPS Lock", action:"cycle_visualizer_fps_lock", pills:[String(normalizeVisualizerFpsLock(fps)) + " FPS"]});
        items.push({kind:"info", label:"Estimated Tempo", pills:[String(Math.round(bpm || 120)) + " BPM"]});
        resetList(items);
      }
    }, push);
  }

  async function viewPerformancePanel(push){
    showNowPlaying(false);
    await setView({
      kind:"performance",
      label:"Performance",
      load: async function(){
        libControlsHide();
        const items = [];
        let backend = null;
        try{ backend = await apiGet("/api/performance", {networkOnly:true, skipMirror:true}); }catch(e){ backend = null; }
        const schedulerStats = (window.DebriPod && DebriPod.frameScheduler && DebriPod.frameScheduler.stats) ? DebriPod.frameScheduler.stats() : {};
        items.push({kind:"info", label:"FPS", pills:[String(Math.round(Number(schedulerStats.fps || 0))), "long " + String(Number(schedulerStats.longFrames || 0))]});
        const renderers = (window.DebriPod && DebriPod.liquidDiagnostics && DebriPod.liquidDiagnostics.renderers) ? DebriPod.liquidDiagnostics.renderers() : [];
        for(const r of renderers){
          items.push({kind:"info", label:"LiquidGL " + String(r.key || "renderer"), pills:[r.visible ? "visible" : "hidden", "res " + String(r.resolution || ""), String(r.texture || "")]});
        }
        const rows = (window.DebriPod && DebriPod.listDiagnostics && DebriPod.listDiagnostics.rows) ? DebriPod.listDiagnostics.rows() : {visible:0,total:(state.items || []).length};
        items.push({kind:"info", label:"Rows", pills:[String(rows.visible || 0) + " visible", String(rows.total || 0) + " total"]});
        const sync = (window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.getStateSummary) ? DebriPod.clientSync.getStateSummary() : null;
        const versions = (backend && backend.library_versions) || (sync && sync.library_versions) || {};
        Object.keys(versions).forEach((rootId)=>{
          items.push({kind:"info", label:"Library root " + rootId, pills:["v" + String(versions[rootId] || 0)]});
        });
        if(sync) items.push({kind:"info", label:"Last sync", pills:[sync.server_version ? String(new Date(Number(sync.server_version) * 1000).toLocaleTimeString()) : "Unknown"]});
        const indexing = (backend && backend.indexing) || {};
        items.push({kind:"info", label:"Indexing", pills:[indexing.any_building ? "building" : "idle"]});
        const services = (backend && backend.services) || {};
        Object.keys(services).forEach((name)=>{
          const svc = services[name] || {};
          const pills = [svc.connected ? "connected" : (svc.configured ? "configured" : (svc.status || "not configured"))];
          if(svc.error) pills.push({text:String(svc.error), tone:"warn"});
          items.push({kind:"info", label:"Service " + name, pills:pills});
        });
        const clientTimings = (window.DebriPod && DebriPod.apiClient && DebriPod.apiClient.recentTimings) ? DebriPod.apiClient.recentTimings().slice(-8).reverse() : [];
        clientTimings.forEach((t)=>{
          items.push({kind:"info", label:String(t.method || "GET") + " " + String(t.url || ""), pills:[String(Math.round(Number(t.ms || 0))) + " ms", String(t.status || "")]});
        });
        const serverTimings = (backend && Array.isArray(backend.api_timings)) ? backend.api_timings.slice(-8).reverse() : [];
        serverTimings.forEach((t)=>{
          items.push({kind:"info", label:"Server " + String(t.path || ""), pills:[String(t.ms || 0) + " ms", String(t.status || "")]});
        });
        const version = (backend && backend.version) || APP_INFO || {};
        items.push({kind:"info", label:"Version", pills:[String(version.display || version.display_version || "vdev"), String(version.source || ""), String(version.short_commit || ""), version.dirty ? {text:"dirty", tone:"warn"} : "clean"]});
        resetList(items);
      }
    }, push);
  }

  async function viewGlassElementSettings(elementKey, push){
    showNowPlaying(false);
    const settings = cloneGlassElementSettings(uiSettings.liquidGlassElements);
    const item = settings[elementKey];
    if(!item) return viewLibAdvancedCategory("glass", false);
    await setView({
      kind:"libglasselement",
      label:item.label,
      glassElementKey:elementKey,
      load: async function(){
        libControlsHide();
        const rows = [
          {label:"Glass tint", field:"glassTint", value:glassTintLabel(item.glassTint), action:"set_glass_value:" + elementKey + ":glassTint"},
          {label:"Resolution", field:"resolution", value:item.resolution, action:"set_glass_value:" + elementKey + ":resolution"},
          {label:"Refraction", field:"refraction", value:item.refraction, action:"set_glass_value:" + elementKey + ":refraction"},
          {label:"Refraction fill", field:"refractionFill", value:item.refractionFill, action:"set_glass_value:" + elementKey + ":refractionFill"},
          {label:"Bevel depth", field:"bevelDepth", value:item.bevelDepth, action:"set_glass_value:" + elementKey + ":bevelDepth"},
          {label:"Bevel width", field:"bevelWidth", value:item.bevelWidth, action:"set_glass_value:" + elementKey + ":bevelWidth"},
          {label:"Frost", field:"frost", value:item.frost, action:"set_glass_value:" + elementKey + ":frost"},
          {label:"Magnification", field:"magnify", value:item.magnify, action:"set_glass_value:" + elementKey + ":magnify"},
          {label:"Specular", field:"specular", value:item.specular ? "On" : "Off", action:"toggle_glass_specular:" + elementKey},
          {label:"Shadow", field:"shadow", value:item.shadow ? "On" : "Off", action:"toggle_glass_shadow:" + elementKey}
        ];
        resetList(rows.map((row)=>({kind:"libui_action", label:row.label, action:row.action, pills:[String(row.value)]})));
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

  const TEXT_MODE_ORDER = ["black", "white", "engraved", "contrast", "transparent"];
  const ANIMATION_FPS_ORDER = [30, 60, 120];
  const TEXT_MODE_LABELS = {
    black:"Black",
    white:"White",
    engraved:"Engraved",
    contrast:"Contrast",
    transparent:"Transparent"
  };

  function textModeLabel(value){
    return TEXT_MODE_LABELS[normalizeTextMode(value)] || "Transparent";
  }

  function textModeRows(){
    const modes = cloneTextModes(uiSettings.textModes);
    return [
      {key:"wheelLabels", label:"Wheel labels"},
      {key:"pathPill", label:"Path pill"},
      {key:"infoPill", label:"Info pill"},
      {key:"rows", label:"Rows"},
      {key:"rowPills", label:"Row pills"},
      {key:"selectedRow", label:"Selected row"},
      {key:"selectedRowPills", label:"Selected row pills"}
    ].map((row)=>({
      kind:"libui_action",
      label:row.label,
      sub_label:"Text color mode",
      action:"cycle_text_mode:" + row.key,
      pills:[textModeLabel(modes[row.key])],
      forceTwoLine:true,
      settingRow:true
    })).concat([{
      kind:"libui_action",
      label:"Text transparency",
      sub_label:"Opacity used by transparent text mode",
      action:"set_text_transparency",
      pills:[String(Math.round(normalizeTextTransparency(uiSettings.textTransparency) * 100)) + "%"],
      forceTwoLine:true,
      settingRow:true
    }]);
  }

  function animationRows(){
    const fps = cloneAnimationFps(uiSettings.animationFps);
    return [
      {key:"selectedRow", label:"Selected row animations"},
      {key:"wheelTilt", label:"Wheel tilt animations"},
      {key:"libraryList", label:"Library list moving animation"},
      {key:"infoPill", label:"Info pill animations"},
      {key:"albumArtTransition", label:"Album art transition animation"},
      {key:"pageTransition", label:"Page transition animation"},
      {key:"pathPill", label:"Path pill animations"}
    ].map((row)=>({
      kind:"libui_action",
      label:row.label,
      sub_label:"Animation frame cap",
      action:"cycle_animation_fps:" + row.key,
      pills:[String(normalizeAnimationFps(fps[row.key])) + " FPS"],
      forceTwoLine:true,
      settingRow:true
    }));
  }

  function advancedCategoryLabels(){
    return {
      glass:"Glass",
      text:"Text",
      ui:"Visualizer",
      animations:"Animations",
      search:"Search",
      downloads:"Downloads",
      services:"Services",
      playback:"Playback",
      system:"System"
    };
  }

  function advancedRowsForCategory(category){
    const cat = String(category || "system");
    if(cat === "glass"){
      const items = [];
      GLASS_ELEMENT_KEYS.forEach((key)=>{
        items.push({kind:"libui_action", label:glassElementLabel(key), sub_label:"Liquid Glass element controls", action:"glass_section:" + key, pills:glassElementSummary(key), forceTwoLine:true, settingRow:true});
      });
      return items;
    }
    if(cat === "ui"){
      return uiTuningRows().map((row)=>({kind:"libui_action", label:row.label, sub_label:"Visualizer tuning", action:row.action, pills:[String(row.value)], forceTwoLine:true, settingRow:true}))
        .concat(settingRowsForCategory("advanced").filter((row)=> row && String(row.key || "").indexOf("TASKS_") === 0).map(settingRowToListItem));
    }
    if(cat === "text") return textModeRows();
    if(cat === "animations") return animationRows();
    if(cat === "system"){
      const systemKeys = new Set(["PORT", "ENABLE_MCP", "MCP_TOKEN", "MCP_PROTOCOL_VERSION", "MCP_SEARCH_RESULT_LIMIT", "MCP_SSE_KEEPALIVE_SECONDS", "MCP_SESSION_TTL_SECONDS", "CACHE_DIR_NAME", "STREAM_PROXY_ALLOWED_HOST_SUFFIXES", "REQUEST_TIMEOUT_SECONDS", "POLL_INTERVAL_SECONDS"]);
      const reindex = state.fullReindexStatus || {};
      const pct = Math.max(0, Math.min(100, Number(reindex.percent || 0)));
      const reindexPill = reindex.running ? (String(Math.round(pct)) + "%") : (reindex.error ? {text:"Error", tone:"warn"} : (pct >= 100 ? "Complete" : "Idle"));
      const reindexRow = {
        kind:"libui_action",
        label:"Full reindex",
        sub_label:reindex.running ? ("Running " + String(reindex.phase || "index") + (reindex.root ? (" for " + reindex.root) : "")) : "Rebuilds all library folders, artwork palettes, audio analysis, video analysis, and client sync data",
        action:"full_reindex",
        pills:[reindexPill],
        forceTwoLine:true,
        settingRow:true
      };
      return [reindexRow].concat(settingRowsForCategory("advanced").filter((row)=> row && systemKeys.has(String(row.key || ""))).map(settingRowToListItem));
    }
    return settingRowsForCategory("advanced").filter((row)=>{
      const key = String((row && row.key) || "");
      if(cat === "search") return key === "RESULTS_PER_PAGE" || key === "MAX_FILES_PER_TORRENT" || key === "MAX_TORRENT_WAIT_SECONDS" || key === "SEARCH_HISTORY_MAX_ITEMS" || key === "SEARCH_DISK_CACHE_TTL_SECONDS" || key === "SEARCH_STREAM_SESSION_TTL_SECONDS";
      if(cat === "downloads") return key === "REPLACE_ORIGINAL";
      if(cat === "services") return key.indexOf("SOULSEEK_") === 0 || key.indexOf("KNABEN_") === 0 || key.indexOf("LASTFM_") === 0 || key === "YTDLP_CMD" || key.indexOf("YOUTUBE_") === 0 || key === "RD_BASE";
      if(cat === "playback") return key === "WHEEL_ROTATION_MAX_DEGREES" || key === "FFMPEG_PATH" || key === "FFPROBE_PATH" || key === "AUDIO_TRANSCODE" || key === "VIDEO_BROWSER_TARGET_EXT" || key === "AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY" || key === "PRELOAD_NEXT_CHUNK_BYTES";
      return false;
    }).map(settingRowToListItem);
  }

  function settingRowToListItem(r){
    return {
      kind:"setting_value",
      label:r.label,
      sub_label:r.sub_label || "",
      key:r.key,
      settingType:r.type,
      choices:r.choices || [],
      value:r.value,
      tool:r.tool || "",
      toolStatus:r.toolStatus || null,
      pills:(settingConnectionPills(r) || [{text:settingValueLabel(r.value)}]).concat([settingSavePill(r)]),
      forceTwoLine:true,
      settingRow:true
    };
  }

  async function viewLibAdvancedSettings(push){
    showNowPlaying(false);
    await setView({
      kind:"libadvancedsettings",
      label:"Advanced",
      load: async function(){
        libControlsHide();
        await settingsLoad();
        const labels = advancedCategoryLabels();
        const items = [
          {kind:"libui_action", label:"Save advanced defaults", sub_label:"Writes commit ready app defaults to config", action:"save_advanced_defaults", pills:["Config"], forceTwoLine:true, settingRow:true},
          {kind:"libui_action", label:"Reset advanced defaults", sub_label:"Removes saved advanced UI defaults from config", action:"reset_advanced_defaults", pills:["Config"], forceTwoLine:true, settingRow:true},
          {kind:"libui_action", label:"Performance overlay button", sub_label:"Show the compact performance toggle button", action:"toggle_performance_overlay_button", pills:[uiSettings.performanceOverlayButton ? "On" : "Off"], forceTwoLine:true, settingRow:true}
        ].concat(["glass", "text", "ui", "animations", "search", "downloads", "services", "playback", "system"].map((key)=>({
          kind:"libui_action",
          label:labels[key],
          sub_label:"Advanced " + String(labels[key] || key).toLowerCase() + " settings",
          action:"advanced_category:" + key,
          pills:[String(advancedRowsForCategory(key).length)]
        })));
        resetList(items);
      }
    }, push);
  }

  async function viewLibAdvancedCategory(category, push){
    const labels = advancedCategoryLabels();
    const cat = String(category || "system");
    showNowPlaying(false);
    await setView({
      kind:"libadvancedcategory",
      label:labels[cat] || "Advanced",
      advancedCategory:cat,
      load: async function(){
        libControlsHide();
        await settingsLoad();
        if(cat === "system"){
          try{
            const js = await apiGet("/api/library/reindex/status", {networkOnly:true, cache:"no-store"});
            state.fullReindexStatus = (js && js.status) ? js.status : {};
          }catch(e){}
          scheduleFullReindexPoll();
        }
        const items = advancedRowsForCategory(cat);
        if(!items.length) items.push({kind:"info", label:"No advanced settings"});
        resetList(items);
      }
    }, push);
  }

  var fullReindexPollTimer = 0;
  async function refreshFullReindexStatus(){
    try{
      const js = await apiGet("/api/library/reindex/status", {networkOnly:true, cache:"no-store"});
      state.fullReindexStatus = (js && js.status) ? js.status : {};
      if(state.current && state.current.kind === "libadvancedcategory" && state.current.advancedCategory === "system"){
        const prevSel = state.sel;
        const prevScroll = libList ? libList.scrollTop : 0;
        resetList(advancedRowsForCategory("system"));
        state.sel = Math.max(0, Math.min((state.items || []).length - 1, prevSel));
        renderList();
        try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
      }
      scheduleFullReindexPoll();
    }catch(e){
      scheduleFullReindexPoll();
    }
  }

  function scheduleFullReindexPoll(){
    try{
      if(fullReindexPollTimer) clearTimeout(fullReindexPollTimer);
      const s = state.fullReindexStatus || {};
      if(s.running || (state.current && state.current.kind === "libadvancedcategory" && state.current.advancedCategory === "system")){
        fullReindexPollTimer = setTimeout(()=>{ refreshFullReindexStatus(); }, s.running ? 1500 : 8000);
      }
    }catch(e){}
  }

  async function startFullReindex(){
    try{
      const res = await apiPost("/api/library/reindex", {});
      const js = res && res.json ? res.json : {};
      if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to start full reindex");
      state.fullReindexStatus = js.status || {running:true, percent:0, phase:"starting"};
      await viewLibAdvancedCategory("system", false);
      scheduleFullReindexPoll();
      return true;
    }catch(e){
      alert(String(e && e.message ? e.message : e));
      return true;
    }
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
    if(String(action || "").indexOf("setup_page:") === 0){
      await viewSetupWizardPage(String(action).split(":")[1] || "library", true);
      return true;
    }
    if(String(action || "").indexOf("setup_edit:") === 0 || String(action || "").indexOf("setup_secret:") === 0){
      const parts = String(action || "").split(":");
      const secret = parts[0] === "setup_secret";
      const key = parts[1] || "";
      const label = parts[2] || key;
      const returnPage = parts[3] || "library";
      await settingsLoad();
      const value = secret ? "" : String((state.appSettings || {})[key] || "");
      await viewSetupEditor({key:key, label:label, value:value, secret:secret, returnPage:returnPage}, true);
      return true;
    }
    if(String(action || "").indexOf("setup_dir:") === 0){
      const parts = String(action || "").split(":");
      const key = parts[1] || "";
      const label = parts[2] || key;
      const returnPage = parts[3] || "library";
      await settingsLoad();
      const picked = await setupPickPath("directory");
      if(picked){
        await settingsSave({[key]: picked}, {});
        await viewSetupWizardPage(returnPage, false);
      }else{
        await viewSetupEditor({key:key, label:label, value:String((state.appSettings || {})[key] || ""), directory:true, returnPage:returnPage}, true);
      }
      return true;
    }
    switch(action){
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
      case "service_status":
        await viewServiceStatusPanel(true);
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
      case "setup_wizard":
        await viewSetupWizard(true);
        return true;
      case "setup_library":
        await viewSettingsLibrary(true);
        return true;
      case "setup_editor_save":
        return await commitSetupEditor();
      case "setup_editor_cancel":
        await viewSetupWizardPage((state.current && state.current.setupEditorReturnPage) || "library", false);
        return true;
      case "setup_remove_library_folder_confirmed": {
        const cur = state.current || {};
        const folders = libraryFolders();
        const idx = Number(cur.setupFolderIndex);
        if(Number.isFinite(idx) && idx >= 0 && idx < folders.length){
          folders.splice(idx, 1);
          await settingsSave({LIBRARY_FOLDERS: folders}, {});
        }
        await viewSetupWizardPage(String(cur.setupReturnPage || "library"), false);
        return true;
      }
      case "setup_remove_library_folder_cancel":
        await viewSetupWizardPage((state.current && state.current.setupReturnPage) || "library", false);
        return true;
      case "setup_lastfm_authorize":
        await viewSetupLastfmAuthPage(true);
        return true;
      case "setup_lastfm_auth_open":
        return await setupLastfmAuthOpen();
      case "setup_lastfm_auth_finish":
        return await setupLastfmAuthFinish();
        return true;
      case "setup_skip_tools_confirmed":
        return await setupSkipMany(["ffmpeg", "ffprobe", "ytdlp", "youtube"], "soulseek_lastfm");
      case "setup_skip_soulseek_lastfm_confirmed":
        return await setupSkipMany(["soulseek", "lastfm"], "realdebrid");
      case "setup_skip_realdebrid_confirmed":
        return await setupSkipMany(["real_debrid"], "finish");
      case "setup_finish":
        return await setupFinish();
      default:
        return false;
    }
  }

  function libSearchSortResults(results){
    const arr = (Array.isArray(results) ? results : []).map(x=> Object.assign({}, x || {}));
    arr.sort((a,b)=>{
      const as = Number(a._score || 0);
      const bs = Number(b._score || 0);
      if(bs !== as) return bs - as;
      const az = Number(a.size || 0);
      const bz = Number(b.size || 0);
      if(bz !== az) return bz - az;
      return String(a.title || "").localeCompare(String(b.title || ""));
    });
    arr.forEach(x=>{ try{ delete x._score; }catch(e){} });
    return arr;
  }

  function libSearchCombinedStatusText(status){
    const list = Array.isArray(status) ? status : [];
    if(!list.length) return "Searching";
    const done = list.filter(x=>x && x.done !== false).length;
    const total = Math.max(3, list.length);
    const count = list.reduce((n, x)=> n + Number((x && x.result_count) || 0), 0);
    return String(done) + "/" + String(total) + " sources, " + String(count) + " results";
  }

  async function libSearchCombinedProgressive(qq, searchToken){
    const url = "/api/libsearch/combined?q=" + encodeURIComponent(qq) + "&stream=1";
    try{
      if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.isServerUnavailable && DebriPod.clientSync.isServerUnavailable()){
        throw new Error(DebriPod.clientSync.serverRequiredMessage ? DebriPod.clientSync.serverRequiredMessage("Search") : "Search requires the local DebriPod server.");
      }
    }catch(e){
      if(e && e.message) throw e;
    }
    const started = (performance && performance.now) ? performance.now() : Date.now();
    const res = await fetch(url, {cache:"no-store"});
    try{
      if(window.DebriPod && DebriPod.apiClient && DebriPod.apiClient.rememberTiming){
        DebriPod.apiClient.rememberTiming("GET", url, res.status, started);
      }
    }catch(e){}
    if(!res.ok || !res.body || !window.TextDecoder){
      return await apiGet("/api/libsearch/combined?q=" + encodeURIComponent(qq));
    }
    const decoder = new TextDecoder();
    const reader = res.body.getReader();
    let buffer = "";
    const sourceResults = {};
    const sourceStatus = [];
    let finalPayload = null;
    function upsertStatus(payload, done){
      const source = String(payload.source || "");
      if(!source) return;
      const row = {
        source:source,
        label:String(payload.source_label || payload.label || source),
        ok:payload.ok !== false,
        error:String(payload.error || ""),
        result_count:Number(payload.result_count || (Array.isArray(payload.results) ? payload.results.length : 0) || 0),
        duration_ms:Number(payload.duration_ms || 0),
        done:done !== false
      };
      const idx = sourceStatus.findIndex(x=>x && x.source === source);
      if(idx >= 0) sourceStatus[idx] = row;
      else sourceStatus.push(row);
    }
    function applyProgress(){
      if(state.libSearch.search_token !== searchToken) return;
      const merged = [];
      Object.keys(sourceResults).forEach((key)=>{
        merged.push.apply(merged, sourceResults[key] || []);
      });
      state.libSearch.results = libSearchSortResults(merged);
      state.libSearch.last_count = state.libSearch.results.length;
      state.libSearch.source_status = sourceStatus.slice();
      libSetStatus(libSearchCombinedStatusText(sourceStatus), sourceStatus.some(x=>x && x.error) ? "warn" : "");
      libRefreshList(true);
    }
    function handleLine(line){
      if(!line) return;
      let ev = null;
      try{ ev = JSON.parse(line); }catch(e){ return; }
      if(!ev || state.libSearch.search_token !== searchToken) return;
      if(ev.event === "source"){
        sourceResults[String(ev.source || "")] = Array.isArray(ev.results) ? ev.results : [];
        upsertStatus(ev, true);
        applyProgress();
      }else if(ev.event === "done"){
        finalPayload = ev;
      }else if(ev.event === "start"){
        const sources = Array.isArray(ev.sources) ? ev.sources : ["youtube", "soulseek", "knaben"];
        state.libSearch.source_status = sources.map(src=>({source:String(src), label:String(src), result_count:0, done:false, error:""}));
        libSetStatus("Searching", "");
        libRefreshList(true);
      }
    }
    while(true){
      const chunk = await reader.read();
      if(chunk.done) break;
      buffer += decoder.decode(chunk.value, {stream:true});
      const lines = buffer.split(/\n/);
      buffer = lines.pop() || "";
      lines.forEach(handleLine);
    }
    if(buffer) handleLine(buffer);
    if(finalPayload) return finalPayload;
    return {
      ok:true,
      q:qq,
      cache_key:"",
      results:state.libSearch.results || [],
      result_count:(state.libSearch.results || []).length,
      source_status:sourceStatus
    };
  }

  function settingRangeMeta(field, fallbackMin, fallbackMax){
    const ranges = {
      glassTint: {min:0, max:2, step:0.01},
      resolution: {min:0.25, max:3, step:0.05},
      refraction: {min:0, max:0.25, step:0.001},
      refractionFill: {min:0, max:1, step:0.01},
      bevelDepth: {min:0, max:0.35, step:0.001},
      bevelWidth: {min:0, max:0.5, step:0.001},
      frost: {min:0, max:5, step:0.01},
      magnify: {min:0.001, max:3, step:0.001}
    };
    if(ranges[field]) return ranges[field];
    const min = Number.isFinite(Number(fallbackMin)) ? Number(fallbackMin) : 0;
    const max = Number.isFinite(Number(fallbackMax)) ? Number(fallbackMax) : 1;
    const span = Math.abs(max - min);
    return {min:min, max:max, step: span >= 100 ? 1 : (span >= 10 ? 0.1 : 0.01)};
  }

  function rangeEditorValueLabel(value, meta){
    const n = Number(value);
    const step = Number((meta && meta.step) || 0.01);
    if(!Number.isFinite(n)) return "0";
    if(step >= 1) return String(Math.round(n));
    const decimals = step < 0.01 ? 3 : (step < 0.1 ? 2 : 1);
    return String(Number(n.toFixed(decimals)));
  }

  function rangeEditorClamp(value, meta, fallback){
    const range = meta || settingRangeMeta("", 0, 1);
    const next = clampNumber(Number(value), fallback == null ? 0 : fallback, Number(range.min), Number(range.max));
    return range.integer ? Math.trunc(next) : next;
  }

  async function viewRangeEditor(config, push){
    const meta = config.meta || settingRangeMeta("", 0, 1);
    const current = rangeEditorClamp(config.current, meta, Number(meta.min || 0));
    state.inlineRangeEditor = {
      kind:"range_editor",
      label:String(config.label || "Value"),
      rangeConfig:config,
      rangeMeta:meta,
      rangeValue:current,
      rangeWheelArmed:true,
      rangeKeyboardOpen:false,
      itemIndex: state.sel,
      committing:false
    };
    renderRangeEditor();
  }

  function activeRangeEditor(){
    return state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
  }

  function rangeEditorRows(){
    const view = activeRangeEditor() || {};
    const meta = view.rangeMeta || settingRangeMeta("", 0, 1);
    const value = rangeEditorClamp(view.rangeValue, meta, Number(meta.min || 0));
    const min = Number(meta.min);
    const max = Number(meta.max);
    const pct = max > min ? ((value - min) / (max - min)) : 0;
    const armed = !!view.rangeWheelArmed;
    return [{kind:"range_editor_input", label:view.label || "Value", value:rangeEditorValueLabel(value, meta), bar:Math.max(0, Math.min(1, pct)), pills:[armed ? "Wheel active" : "Click to adjust", rangeEditorValueLabel(value, meta), rangeEditorValueLabel(min, meta) + "-" + rangeEditorValueLabel(max, meta)]}];
  }

  function renderRangeEditor(){
    if(state.inlineRangeEditor && Array.isArray(state.items)){
      const idx = Math.max(0, Math.min(state.items.length - 1, Number(state.inlineRangeEditor.itemIndex || state.sel || 0)));
      state.inlineRangeEditor.itemIndex = idx;
      state.sel = idx;
      renderList();
      return;
    }
    resetList(rangeEditorRows());
  }

  function adjustRangeEditor(delta){
    try{
      const view = activeRangeEditor() || {};
      if(view.kind !== "range_editor") return false;
      if(!view.rangeWheelArmed) return false;
      const meta = view.rangeMeta || settingRangeMeta("", 0, 1);
      const step = rangeEditorWheelStep(meta);
      const next = rangeEditorClamp(Number(view.rangeValue || 0) + Number(delta || 0) * step, meta, Number(view.rangeValue || 0));
      view.rangeValue = next;
      renderRangeEditor();
      return true;
    }catch(e){
      return false;
    }
  }

  function rangeEditorWheelStep(meta){
    if(meta && meta.integer) return Math.max(1, Math.abs(Number(meta.step || 1)) || 1);
    const rawText = String((meta && meta.step != null) ? meta.step : 0.1);
    const decimal = rawText.indexOf(".") >= 0 ? rawText.split(".")[1].replace(/0+$/, "").length : 0;
    if(decimal >= 3) return 0.001;
    if(decimal >= 2) return 0.01;
    return 0.1;
  }

  function armRangeEditorWheel(){
    const view = activeRangeEditor() || {};
    if(view.kind !== "range_editor") return false;
    view.rangeWheelArmed = true;
    view.rangeKeyboardOpen = false;
    renderRangeEditor();
    return true;
  }

  function rangeEditorWheelActive(){
    const view = activeRangeEditor() || {};
    return !!(view && view.kind === "range_editor" && view.rangeWheelArmed);
  }

  function openRangeEditorKeyboard(){
    const view = activeRangeEditor() || {};
    if(view.kind !== "range_editor") return false;
    view.rangeWheelArmed = false;
    view.rangeKeyboardOpen = true;
    renderRangeEditor();
    setTimeout(()=>{
      try{
        const input = libList ? libList.querySelector(".ipodItem.sel .libInlineInput") : null;
        if(input){
          input.focus();
          input.click();
          const n = String(input.value || "").length;
          input.setSelectionRange(n, n);
        }
      }catch(e){}
    }, 0);
    return true;
  }

  function rangeEditorDisplayForIndex(index){
    const view = activeRangeEditor() || {};
    if(view.kind !== "range_editor") return null;
    if(Number(view.itemIndex) !== Number(index)) return null;
    const meta = view.rangeMeta || settingRangeMeta("", 0, 1);
    const value = rangeEditorClamp(view.rangeValue, meta, Number(meta.min || 0));
    const min = Number(meta.min);
    const max = Number(meta.max);
    return {
      text: rangeEditorValueLabel(value, meta),
      value:value,
      bar: max > min ? Math.max(0, Math.min(1, (value - min) / (max - min))) : null,
      armed: !!view.rangeWheelArmed,
      keyboardOpen: !!view.rangeKeyboardOpen
    };
  }

  function rangeEditorOwnsIndex(index){
    const view = activeRangeEditor() || {};
    return !!(view.kind === "range_editor" && Number(view.itemIndex) === Number(index));
  }

  function rangeEditorCenterPress(){
    const view = activeRangeEditor() || {};
    if(view.kind !== "range_editor") return false;
    if(view.rangeKeyboardOpen) return false;
    if(view.rangeWheelArmed) return openRangeEditorKeyboard();
    return armRangeEditorWheel();
  }

  function rangeEditorCancelActive(){
    const view = activeRangeEditor() || {};
    if(view.kind !== "range_editor") return false;
    cancelRangeEditor();
    return true;
  }

  async function applyRangeEditor(){
    const view = activeRangeEditor() || {};
    if(view.kind !== "range_editor") return false;
    if(view.committing) return false;
    view.committing = true;
    const config = view.rangeConfig || {};
    const meta = view.rangeMeta || settingRangeMeta("", 0, 1);
    const value = rangeEditorClamp(view.rangeValue, meta, Number(meta.min || 0));
    try{
      if(typeof config.onCommit === "function") await config.onCommit(value);
      state.inlineRangeEditor = null;
      if(typeof config.onReturn === "function") await config.onReturn();
      else if(state.current && state.current.kind === "range_editor") goBack();
      else if(typeof renderList === "function") renderList();
    }finally{
      if(view && view.kind === "range_editor") view.committing = false;
    }
    return true;
  }

  async function cancelRangeEditor(){
    const view = activeRangeEditor() || {};
    const config = view.rangeConfig || {};
    state.inlineRangeEditor = null;
    if(typeof config.onReturn === "function") await config.onReturn();
    else if(state.current && state.current.kind === "range_editor") goBack();
    else if(typeof renderList === "function") renderList();
    return true;
  }

  async function handleLibUiAction(action){
    const setNumber = async (key, label, min, max)=>{
      const current = uiSettings[key];
      const returnCategory = (state.current && state.current.kind === "libadvancedcategory") ? (state.current.advancedCategory || "ui") : "ui";
      await viewRangeEditor({
        label:label,
        current:current,
        meta:settingRangeMeta(key, min, max),
        onCommit: async function(value){
          uiSettings[key] = clampNumber(Number(value), current, min, max);
          saveUiSettings();
          applyUiTuningCss();
          try{ if(typeof forcePathPillGlassRender === "function") forcePathPillGlassRender("ui tuning", true); }catch(e){}
          try{ if(typeof forceInfoPillGlassRender === "function") forceInfoPillGlassRender("ui tuning", true); }catch(e){}
        },
        onReturn: async function(){
          await viewLibAdvancedCategory(returnCategory, false);
        }
      }, true);
      return true;
    };
    const setGlassNumber = async (elementKey, field)=>{
      const settings = cloneGlassElementSettings(uiSettings.liquidGlassElements);
      const current = settings[elementKey] ? settings[elementKey][field] : 0;
      await viewRangeEditor({
        label:glassElementLabel(elementKey) + " " + field,
        current:current,
        meta:settingRangeMeta(field, 0, 1),
        onCommit: async function(value){ setLiquidGlassElementSetting(elementKey, field, Number(value)); },
        onReturn: async function(){ await viewGlassElementSettings(elementKey, false); }
      }, true);
      return true;
    };
    const saveAdvancedDefaults = async ()=>{
      try{
        uiSettings.textModes = cloneTextModes(uiSettings.textModes);
        uiSettings.animationFps = cloneAnimationFps(uiSettings.animationFps);
        uiSettings.textTransparency = normalizeTextTransparency(uiSettings.textTransparency);
        saveUiSettings();
        const res = await apiPost("/api/ui/advanced_defaults/save", {
          uiSettings: uiSettings,
          liquidGlassElements: cloneGlassElementSettings(uiSettings.liquidGlassElements),
          appSettings: state.appSettings || {},
          startupSettings: state.startupSettings || {}
        });
        const js = res && res.json ? res.json : {};
        if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to write defaults");
        if(js.advanced_ui_defaults && window.DebriPod && DebriPod.uiSettings && DebriPod.uiSettings.applyServerAdvancedDefaults){
          DebriPod.uiSettings.applyServerAdvancedDefaults(js.advanced_ui_defaults);
          uiSettings = DebriPod.uiSettings.settings;
        }
        try{ libSetStatus("Advanced defaults saved to config.", "ok"); }catch(statusErr){}
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      await viewLibAdvancedSettings(false);
      return true;
    };
    const resetAdvancedDefaults = async ()=>{
      try{
        const res = await apiPost("/api/ui/advanced_defaults/reset", {});
        const js = res && res.json ? res.json : {};
        if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to reset defaults");
        if(window.DebriPod && DebriPod.uiSettings && DebriPod.uiSettings.applyServerAdvancedDefaults){
          DebriPod.uiSettings.applyServerAdvancedDefaults({});
          uiSettings = DebriPod.uiSettings.settings;
        }
        try{ libSetStatus("Advanced defaults removed from config.", "ok"); }catch(statusErr){}
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      await viewLibAdvancedSettings(false);
      return true;
    };
    const returnAdvancedCategory = async (category)=>{
      try{
        saveUiSettings();
        if(typeof applyUiTuningCss === "function") applyUiTuningCss();
        if(typeof scheduleLiquidGlassRender === "function") scheduleLiquidGlassRender();
        if(typeof updateGlassTextUnderColors === "function") updateGlassTextUnderColors();
        if(typeof updateVisualizerState === "function") updateVisualizerState();
        if(typeof scheduleVisualizerFrame === "function") scheduleVisualizerFrame(0);
      }catch(e){}
      await viewLibAdvancedCategory(category, false);
      return true;
    };
    switch(action){
      default:
        if(String(action || "").indexOf("cycle_text_mode:") === 0){
          const key = String(action).split(":")[1] || "";
          const modes = cloneTextModes(uiSettings.textModes);
          if(!Object.prototype.hasOwnProperty.call(modes, key)) return false;
          const current = normalizeTextMode(modes[key]);
          const idx = Math.max(0, TEXT_MODE_ORDER.indexOf(current));
          modes[key] = TEXT_MODE_ORDER[(idx + 1) % TEXT_MODE_ORDER.length];
          uiSettings.textModes = cloneTextModes(modes);
          return await returnAdvancedCategory("text");
        }
        if(String(action || "").indexOf("cycle_animation_fps:") === 0){
          const key = String(action).split(":")[1] || "";
          const fps = cloneAnimationFps(uiSettings.animationFps);
          if(!Object.prototype.hasOwnProperty.call(fps, key)) return false;
          const current = normalizeAnimationFps(fps[key]);
          const idx = Math.max(0, ANIMATION_FPS_ORDER.indexOf(current));
          fps[key] = ANIMATION_FPS_ORDER[(idx + 1) % ANIMATION_FPS_ORDER.length];
          uiSettings.animationFps = cloneAnimationFps(fps);
          return await returnAdvancedCategory("animations");
        }
        if(String(action || "").indexOf("glass_section:") === 0){
          await viewGlassElementSettings(String(action).split(":")[1] || "", true);
          return true;
        }
        if(String(action || "").indexOf("advanced_category:") === 0){
          await viewLibAdvancedCategory(String(action).split(":")[1] || "system", true);
          if(String(action).split(":")[1] === "system") refreshFullReindexStatus();
          return true;
        }
        if(String(action || "").indexOf("toggle_glass_specular:") === 0){
          const key = String(action).split(":")[1] || "";
          const settings = cloneGlassElementSettings(uiSettings.liquidGlassElements);
          if(settings[key]) setLiquidGlassElementSetting(key, "specular", !settings[key].specular);
          await viewGlassElementSettings(key, false);
          return true;
        }
        if(String(action || "").indexOf("toggle_glass_shadow:") === 0){
          const key = String(action).split(":")[1] || "";
          const settings = cloneGlassElementSettings(uiSettings.liquidGlassElements);
          if(settings[key]) setLiquidGlassElementSetting(key, "shadow", !settings[key].shadow);
          await viewGlassElementSettings(key, false);
          return true;
        }
        if(String(action || "").indexOf("set_glass_value:") === 0){
          const parts = String(action).split(":");
          return await setGlassNumber(parts[1] || "", parts[2] || "");
        }
        return false;
      case "range_editor_apply":
        return await applyRangeEditor();
      case "range_editor_cancel":
        return await cancelRangeEditor();
      case "toggle_visualizer":
        setVisualizerEnabled(!visualizerEnabled);
        await viewLibUiSettings(false);
        return true;
      case "set_visualizer_max_brightness":
        await viewRangeEditor({
          label:"Max visualizer brightness",
          current:normalizeVisualizerMaxBrightnessPct(uiSettings.visualizerMaxBrightnessPct),
          meta:{min:0, max:200, step:1, integer:true},
          onCommit: async function(value){
            setVisualizerMaxBrightnessPct(value);
          },
          onReturn: async function(){
            await viewLibUiSettings(false);
          }
        }, true);
        return true;
      case "cycle_visualizer_preset":
        cycleVisualizerPreset();
        await viewLibUiSettings(false);
        return true;
      case "cycle_visualizer_fps_lock":
        cycleVisualizerFpsLock();
        await viewLibUiSettings(false);
        return true;
      case "save_advanced_defaults":
        return await saveAdvancedDefaults();
      case "reset_advanced_defaults":
        return await resetAdvancedDefaults();
      case "toggle_performance_overlay_button":
        uiSettings.performanceOverlayButton = !uiSettings.performanceOverlayButton;
        saveUiSettings();
        if(window.DebriPod && DebriPod.performanceOverlay && DebriPod.performanceOverlay.refresh){
          DebriPod.performanceOverlay.refresh();
          setTimeout(()=>{ try{ DebriPod.performanceOverlay.refresh(); }catch(e){} }, 0);
        }
        await viewLibAdvancedSettings(false);
        return true;
      case "full_reindex":
        return await startFullReindex();
      case "set_text_transparency":
        await viewRangeEditor({
          label:"Text transparency",
          current:normalizeTextTransparency(uiSettings.textTransparency),
          meta:{min:0, max:1, step:0.01},
          onCommit: async function(value){
            uiSettings.textTransparency = normalizeTextTransparency(value);
            saveUiSettings();
            if(typeof applyUiTuningCss === "function") applyUiTuningCss();
            if(typeof scheduleLiquidGlassRender === "function") scheduleLiquidGlassRender();
            if(typeof updateGlassTextUnderColors === "function") updateGlassTextUnderColors();
          },
          onReturn: async function(){
            await viewLibAdvancedCategory("text", false);
          }
        }, true);
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
    }
  }
