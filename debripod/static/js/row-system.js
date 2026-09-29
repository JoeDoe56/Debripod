(function(global){
  "use strict";

  const root = global.DebriPod = global.DebriPod || {};
  const SAFE_ZONE = "var(--dp-row-safe-zone, var(--dp-selected-pill-edge-room, 44px))";
  const stateFor = ()=>{
    try { return global.state || null; } catch(e) { return null; }
  };

  function clamp(value, min, max){
    const n = Number(value);
    if(!Number.isFinite(n)) return min;
    return Math.max(min, Math.min(max, n));
  }

  function normalizedValue(value, min, max){
    return root.uiPrimitives.normalize(value, min, max);
  }

  function setText(element, value){
    const text = String(value == null ? "" : value);
    element.classList.add("glassText");
    element.setAttribute("data-text", text);
    element.setAttribute("data-liquid-ignore", "");
    element.textContent = text;
    return element;
  }

  function createRing(value, options){
    const opts = options || {};
    const shared = root.uiPrimitives && typeof root.uiPrimitives.createRing === "function"
      ? root.uiPrimitives.createRing(clamp(value, 0, 1), 0, 1, {role:opts.label ? "img" : "presentation", label:opts.label})
      : null;
    if(!shared) return null;
    shared.classList.add("dpValueRing");
    if(opts.className) shared.classList.add(opts.className);
    return shared;
  }

  function createSelectedState(symbol, label){
    const selected = document.createElement("span");
    selected.className = "dpSelectedIconState uiSelectedState uiSelectedStateActive";
    selected.setAttribute("role", "img");
    if(label) selected.setAttribute("aria-label", String(label));
    selected.dataset.symbol = String(symbol || "checkmark");
    try{
      const shared = root.uiPrimitives;
      const icon = shared && typeof shared.createSymbol === "function" ? shared.createSymbol(symbol || "checkmark", {label:label}) : null;
      if(icon) selected.appendChild(icon);
      if(shared && typeof shared.setSelectedState === "function") shared.setSelectedState(selected, true, {symbolActive:true, label:label});
    }catch(e){}
    return selected;
  }

  function makeSymbol(symbol, label){
    let icon = null;
    try{
      if(root.uiPrimitives && typeof root.uiPrimitives.createSymbol === "function"){
        icon = root.uiPrimitives.createSymbol(symbol, {label:label});
      }
      const api = root.iconSystem || root.sfSymbols || root.symbols;
      if(!icon && api && typeof api.create === "function") icon = api.create(symbol, {label:label, className:"dpRowSymbol"});
    }catch(e){}
    if(!icon){
      icon = document.createElement("span");
      icon.className = "dpRowSymbol";
      icon.dataset.symbol = String(symbol || "circle");
      icon.setAttribute("aria-hidden", "true");
    }
    icon.classList.add("dpRowSymbol");
    if(label && !icon.getAttribute("aria-label")) icon.setAttribute("aria-label", label);
    return icon;
  }

  function itemNumber(item){
    if(!item) return "";
    const values = [item.track_number, item.trackNumber, item.track_no, item.track, item.episode_number, item.episodeNumber, item.episode, item.number];
    for(const value of values){
      if(value !== undefined && value !== null && String(value).trim() !== "") return String(value).split("/")[0];
    }
    return "";
  }

  function itemProgress(item){
    if(!item) return null;
    if(item.ended) return 1;
    if(item.completion_percent != null) return clamp(Number(item.completion_percent) / 100, 0, 1);
    if(Number(item.duration) > 0 && item.position != null) return normalizedValue(item.position, 0, item.duration);
    const candidates = [item.progress, item.watch_progress, item.watchProgress, item.playback_progress, item.playbackProgress, item.resume_progress];
    for(const value of candidates){
      if(value === undefined || value === null || value === "") continue;
      const number = Number(value);
      if(Number.isFinite(number)) return number > 1 ? clamp(number / 100, 0, 1) : clamp(number, 0, 1);
    }
    return null;
  }

  function itemQuality(item){
    if(!item) return null;
    const text = [item.codec, item.ext, item.quality, item.quality_label].filter(Boolean).join(" ").toLowerCase();
    // Lossy 32–320 kb/s maps to .1–.7; CD lossless .82; higher
    // bit depth and sample rate rise to 1. Unknown is not scored.
    if(/flac|alac|wav|aiff|pcm|lossless|hi.?res/.test(text)){
      return .82 + .09 * normalizedValue(Number(item.bit_depth) || 16, 16, 24)
        + .09 * normalizedValue(Number(item.sample_rate) || 44100, 44100, 192000);
    }
    let bitrate = Number(item.bitrate || item.bit_rate || item.bps);
    if(!(bitrate > 0)) bitrate = Number((text.match(/(\d+)\s*k(?:b|bps)/) || [])[1]) * 1000;
    if(bitrate > 0){
      if(bitrate <= 1536) bitrate *= 1000;
      return .1 + .6 * normalizedValue(bitrate, 32000, 320000);
    }
    const value = item.quality_score ?? item.qualityScore;
    if(value != null && Number.isFinite(Number(value))) return normalizedValue(value, 0, Number(value) > 1 ? 100 : 1);
    return null;
  }

  const CATEGORIES = {
    artists:["person.2", "Browse recordings by artist"], albums:["square.stack", "Browse complete albums"],
    songs:["music.note.list", "All indexed audio recordings"], genres:["guitars", "Browse music by genre"],
    playlists:["music.note.list", "Saved and smart playlists"], movies:["film", "Indexed feature films"],
    shows:["tv", "Shows, seasons, and episodes"], videos:["play.rectangle", "Other indexed videos"]
  };
  const ACTION_CONTEXT = {
    force_fullscreen:["arrow.up.left.and.arrow.down.right","Expand DebriPod to fill the display"],
    binds_menu:["keyboard","Keyboard and click-wheel control assignments"],
    account_settings:["person.2","Profile, sign-in, and passkeys"],
    settings_library:["books.vertical","Library folders and indexing"],
    settings_downloads:["arrow.down.circle","Download locations, formats, and task behavior"],
    settings_services:["network","Connected sources and service credentials"],
    settings_playback:["playpause","Playback, preloading, and compatibility"],
    settings_advanced:["gearshape","Display, motion, text, and advanced behavior"],
    ui_settings_menu:["waveform","Artwork visualization and ambient lighting"],
    lastfm_login:["network","Connect Last.fm to synchronize listening activity"],
    enable_task_notifications:["bell","Notify you when downloads finish"],
    disable_task_notifications:["bell","Manage download notifications"]
  };
  function itemDescription(item){
    if(item.description || item.sub_label) return String(item.description || item.sub_label);
    if(CATEGORIES[item.cat]) return CATEGORIES[item.cat][1];
    if(ACTION_CONTEXT[item.action]) return ACTION_CONTEXT[item.action][1];
    if(String(item.action || "").startsWith("advanced_category:")){
      const category=String(item.action).split(":")[1];
      return {glass:"Glass surfaces, rendering quality, and motion",text:"Foreground opacity and text emphasis",animations:"Animation timing and frame limits",ui:"Visualizer appearance",system:"Server settings and database maintenance",search:"Search limits, caching, and sources",downloads:"Download processing and task limits",services:"Service connections and network settings",playback:"Playback compatibility and buffering"}[category] || "";
    }
    const descriptions = {libsearch_entry:"Search your library and connected sources",libtasks_entry:"Download progress and completed tasks",folder_sources:"Browse configured library folders",libinfo_entry:"Settings, account, and application information",nowplaying:"Return to the current recording",root:"Configured library folder"};
    return descriptions[item.kind] || "";
  }
  function itemSymbol(item){
    if(item.symbol || item.source_icon) return item.symbol || item.source_icon;
    if(CATEGORIES[item.cat]) return CATEGORIES[item.cat][0];
    const byKind = {info:"info.circle",np_playlist_entry:"music.note.list",np_playlist_close:"xmark",playlist_create:"plus",smart_playlist_create:"plus",libsearch_entry:"magnifyingglass",libtasks_entry:"arrow.down.circle",folder_sources:"folder",folder_source:"folder",dir:"folder",root:"books.vertical",album:"square.stack",artist:"person.2",playlist:"music.note.list",libinfo_entry:"info.circle",nowplaying:"play.fill",up:"backward.end.alt.fill"};
    if(byKind[item.kind]) return byKind[item.kind];
    const action = String(item.action || "");
    if(ACTION_CONTEXT[action]) return ACTION_CONTEXT[action][0];
    if(item.settingRow || /setting|libui|advanced/.test(item.kind || "")) return "gearshape";
    if(/^libinfo|^account|^libbinds|^libdatabase/.test(item.kind || "")) return "info.circle";
    return "";
  }

  function collectPillText(row){
    return Array.from(row.querySelectorAll(".ipodPillText, .pillBarText"))
      .map(el=>String(el.textContent || "").trim())
      .filter(Boolean);
  }

  function itemSecondary(item, row){
    const direct = item && (item.secondary || item.subtitle || [item.artist, item.album].filter(Boolean).join(" · ") || itemDescription(item));
    if(direct) return String(direct);
    const values = collectPillText(row);
    if(item && item.badge && values.indexOf(String(item.badge)) < 0) values.unshift(String(item.badge));
    return values.slice(0, 3).join("  ·  ");
  }

  function rowIcon(row, item){
    const slot = document.createElement("span");
    slot.className = "dpRowIconArea";
    const number = itemNumber(item);
    const quality = itemQuality(item);
    const progress = itemProgress(item);
    const video = item.media === "video" || ["movie","show","show_season","show_episode","episode"].includes(item.kind);
    const ringValue = video ? (progress == null ? 0 : progress) : quality;
    const numeric = typeof global.numericSettingState === "function" ? global.numericSettingState(item, Number(row.dataset.index)) : null;
    if(numeric){
      const ring = createRing(numeric.progress, {label:String(item.label || "Setting value")});
      if(ring){
        slot.appendChild(ring);
        ring.appendChild(makeSymbol(item.symbol || "slider.horizontal.3", item.label || "Setting"));
      }
    }else if(item.selected || item.active || (['bool','startup_bool'].includes(item.settingType) && item.value) || item.enabled === true){
      slot.appendChild(createSelectedState(itemSymbol(item) || "checkmark", "Selected"));
    }else if(ringValue != null){
      const ring = createRing(ringValue, {label:video ? "Watch progress" : "Audio quality"});
      if(ring){
        if(number){
          ring.appendChild(document.createElement("span"));
          ring.lastChild.className = "dpRowNumber";
          ring.lastChild.textContent = number;
        }else if(item.playing || item.is_playing) ring.appendChild(makeSymbol("play.fill", "Playing"));
        slot.appendChild(ring);
      }
    }else if(number){
      const count = document.createElement("span");
      count.className = "dpRowNumber";
      count.textContent = number;
      slot.appendChild(count);
    }else if(item && (item.playing || item.is_playing)){
      slot.appendChild(makeSymbol("play.fill", "Playing"));
    }else if(itemSymbol(item)){
      slot.appendChild(makeSymbol(itemSymbol(item), ""));
    }
    return slot;
  }

  let screenContent = null;
  let contextPanel = null;
  let panelProgressValue = 0;
  let panelFrame = 0;
  let geometryFrame = 0;
  let geometryUntil = 0;
  function followPanelGeometry(){
    geometryFrame = 0;
    if(typeof global.updateLibSelectionGlass === "function") global.updateLibSelectionGlass("panel reflow");
    if(global.performance.now() < geometryUntil) geometryFrame = global.requestAnimationFrame(followPanelGeometry);
  }

  function buildPanel(){
    const content = screenContent || document.querySelector(".ipodScreenContent");
    if(!content) return null;
    screenContent = content;
    let panel = contextPanel || content.querySelector(".dpContextPanel");
    if(panel) return panel;
    panel = document.createElement("aside");
    panel.className = "dpContextPanel";
    panel.setAttribute("aria-hidden", "true");
    panel.setAttribute("aria-label", "Selected item information");
    const inner = document.createElement("div");
    inner.className = "dpContextPanelInner";
    panel.appendChild(inner);
    content.appendChild(panel);
    contextPanel = panel;
    return panel;
  }

  function panelEntries(item, current){
    item = Object.assign({}, item && item.raw || {}, item && item.queueItem || {}, item || {});
    const pairs = [];
    const add = (label, value)=>{
      if(value === undefined || value === null || String(value).trim() === "") return;
      const text = typeof value === "object" ? "" : String(value);
      if(text) pairs.push([label, text]);
    };
    add("Artist", item && (item.artist || item.artist_name));
    add("Album", item && (item.album || item.album_name));
    add("Year", item && (item.year || item.release_year));
    const duration = value => {const seconds=Number(value);return Number.isFinite(seconds) ? Math.floor(seconds/60)+":"+String(Math.floor(seconds%60)).padStart(2,"0") : value;};
    add("Duration", item.duration_text || (item.duration != null ? duration(item.duration) : null));
    add("Track", item.track_number ?? item.track_no ?? item.track);
    add("Episode", item && (item.episode_number || item.episode));
    add("Quality", item && (item.quality_label || item.quality));
    add("Codec", item && (item.video_codec || item.codec || item.codec_name));
    if(item.video_codec) add("Audio codec", item.audio_codec);
    const sampleRate = item.sample_rate ?? item.sampleRate;
    add("Sample rate", sampleRate != null ? (Number(sampleRate)/1000).toLocaleString()+" kHz" : null);
    const bitrate = item.bitrate ?? item.bit_rate;
    add("Bitrate", bitrate != null ? Math.round(Number(bitrate)>1536?Number(bitrate)/1000:Number(bitrate))+" kb/s" : null);
    add("Bit depth", (item.bit_depth ?? item.bitDepth) != null ? (item.bit_depth ?? item.bitDepth)+" bit" : null);
    add("Resolution", item && (item.resolution || item.video_resolution));
    add("Container", item && (item.container || item.container_format || item.format));
    add("Source", item && item.source);
    add("Library", item.root && item.root.name);
    add("Provider", item && (item.provider || item.service));
    add("Indexer", item && item.indexer);
    add("Files", item.file_count ?? item.files_count);
    add("Items", item.item_count ?? item.track_count ?? item.episode_count ?? item.count ?? item.child_count);
    const size = item.file_size ?? item.filesize ?? item.size;
    add("File size", size != null ? (typeof global.fmtBytes === "function" ? global.fmtBytes(size) : Number(size).toLocaleString()+" bytes") : null);
    add("Category", item && item.category);
    add("Availability", item.availability ?? (item.available != null ? (item.available ? "Available" : "Unavailable") : null));
    if(item.browser_friendly != null) add("Playback", item.browser_friendly ? "Browser compatible" : "Conversion may be required");
    const progress = itemProgress(item);
    add("Progress", item.progress_text || item.watch_progress_text || (progress != null ? Math.round(progress*100)+"%" : null));
    add("Task", item && (item.task_state || item.task_status));
    add("Download", item && (item.download_state || item.download_status));
    const numeric = typeof global.numericSettingState === "function" ? global.numericSettingState(item, stateFor()?.sel) : null;
    add("Value", numeric ? numeric.value : item.setting_state ?? item.settingValue);
    if(numeric) add("Range", numeric.min+" – "+numeric.max);
    add("Description", itemDescription(item));
    const details = (item.pills || []).map(value=>typeof value === "object" ? value.text : value).filter(value=>value != null && String(value).trim());
    add("Details", details.join(" · "));
    if(item.disabled) add("State", "Unavailable");
    if(item.kind === "folder_sources") add("Folders", (stateFor()?.roots || []).length);
    if(current){
      if(!pairs.length) add("Description", current.description || current.label);
    }
    return pairs;
  }

  function updatePanel(){
    const panel = buildPanel();
    if(!panel) return;
    const state = stateFor();
    const item = state && Array.isArray(state.items) ? state.items[state.sel] : null;
    const title = item && (item.label || item.title) || (state && state.current && state.current.label) || "Information";
    const entries = panelEntries(item,state && state.current);
    const signature = JSON.stringify([state && state.sel,title,entries]);
    if(panel.dataset.contentSignature === signature) return;
    panel.dataset.contentSignature = signature;
    const inner = panel.querySelector(".dpContextPanelInner");
    inner.replaceChildren();
    const heading = document.createElement("div");
    heading.className = "dpContextPanelHeading";
    setText(heading, title);
    inner.appendChild(heading);
    for(const [label, value] of entries){
      const entry = document.createElement("div");
      entry.className = "dpContextEntry";
      const labelEl = document.createElement("span");
      labelEl.className = "dpContextLabel";
      setText(labelEl, label);
      const valueEl = document.createElement("span");
      valueEl.className = "dpContextValue dpTabularNums";
      setText(valueEl, value);
      entry.append(labelEl, valueEl);
      inner.appendChild(entry);
    }
  }

  function decorateRow(row, item){
    if(!row || row.classList.contains("dpStandardRow")) return;
    if(row.classList.contains("ipodVirtualSpacer") || row.classList.contains("ipodPageAnchorSpacer") || row.classList.contains("ipodListEndSpacer")) return;
    row.classList.add("dpStandardRow");
    row.style.setProperty("--dp-row-index", row.dataset.index || "0");
    item = Object.assign({}, item.raw || {}, item.queueItem || {}, item);
    const icon = rowIcon(row, item || {});
    row.insertBefore(icon, row.firstChild);
    let labelWrap = row.querySelector(":scope > .ipodLabelWrap");
    if(!labelWrap){
      const label = row.querySelector(":scope > .ipodLabel, :scope > .libInlineInput, :scope > .ipodExpandedMain > .ipodLabel");
      if(label){
        labelWrap = document.createElement("span");
        labelWrap.className = "ipodLabelWrap dpRowText";
        // Expanded rows may keep their label in a nested main wrapper. Move
        // the text into the shared column without calling insertBefore on a
        // parent that does not own the node.
        if(label.parentNode === row) row.insertBefore(labelWrap, label);
        else row.insertBefore(labelWrap, row.firstChild || null);
        labelWrap.appendChild(label);
      }
    }
    if(labelWrap){
      labelWrap.classList.add("dpRowText");
      const primary = labelWrap.querySelector(":scope > .ipodLabel, :scope > .libInlineInput");
      if(primary) primary.classList.add("dpRowPrimary");
      let secondary = labelWrap.querySelector(":scope > .ipodSubLabel");
      if(!secondary){
        secondary = document.createElement("span");
        secondary.className = "ipodSubLabel dpRowSecondary hScrollText";
        setText(secondary, itemSecondary(item || {}, row));
        labelWrap.appendChild(secondary);
      }else{
        secondary.classList.add("dpRowSecondary");
      }
      const numericInput = row.querySelector(".rangeValueEditing .libInlineInput");
      if(numericInput){
        numericInput.classList.add("dpRowSecondary");
        secondary.replaceWith(numericInput);
        labelWrap.classList.add("dpRowEditing");
      }
    }
    row.querySelectorAll(".ipodPills").forEach(pills=>pills.remove());
    // Move the complete foreground with the selection spring. Keeping layout
    // on the row and motion on this wrapper avoids individual line clipping.
    const content = document.createElement("span");
    content.className = "dpRowContent";
    while(row.firstChild) content.appendChild(row.firstChild);
    row.appendChild(content);
    row.setAttribute("data-row-system", "standard");
  }

  let observer = null;
  const controlKinds = new Set(["smart_playlist_rules_text", "setup_text_input", "settings_text_input"]);
  function decorateList(list, state){
    if(!list) return;
    list.dataset.rowSystem = "standard";
    const items = state && Array.isArray(state.items) ? state.items : [];
    list.querySelectorAll(":scope > .ipodItem").forEach(row=>{
      const item = items[Number(row.dataset.index)] || {};
      // Text editors are dedicated controls rather than standard navigation
      // rows; retaining their natural height avoids clipping input surfaces.
      if(!controlKinds.has(String(item.kind || ""))) decorateRow(row, item);
    });
    buildPanel();
    updatePanel();
    if(!observer){
      observer = new MutationObserver((records)=>{
        let selectionChanged = false;
        for(const record of records){
          if(record.type === "attributes" && record.attributeName === "class") selectionChanged = true;
        }
        if(selectionChanged) updatePanel();
      });
      observer.observe(list, {subtree:true, attributes:true, attributeFilter:["class"]});
    }
  }

  function applyPanelProgress(){
    panelFrame = 0;
    const progress = panelProgressValue;
    const content = screenContent || document.querySelector(".ipodScreenContent");
    if(content){
      screenContent = content;
      content.style.setProperty("--dp-panel-progress", progress.toFixed(4));
    }
    const panel = contextPanel || buildPanel();
    if(panel){
      panel.setAttribute("aria-hidden", progress < 0.01 ? "true" : "false");
      panel.classList.toggle("isOpen", progress > 0.01);
    }
  }

  function setPanelProgress(value, options){
    panelProgressValue = clamp(value, 0, 1);
    const opts = options || {};
    const content = screenContent || document.querySelector(".ipodScreenContent");
    if(content){
      screenContent = content;
      content.classList.toggle("dpPanelInteractive", !!opts.immediate);
    }
    if(!panelFrame){
      panelFrame = (global.requestAnimationFrame || ((fn)=>global.setTimeout(fn, 16)))(applyPanelProgress);
    }
    geometryUntil = global.performance.now() + (opts.immediate ? 20 : 320);
    if(!geometryFrame) geometryFrame = global.requestAnimationFrame(followPanelGeometry);
    return panelProgressValue;
  }

  function setPanelOpen(open, options){
    const content = screenContent || document.querySelector(".ipodScreenContent");
    if(content) content.classList.remove("dpPanelInteractive");
    return setPanelProgress(open ? 1 : 0, Object.assign({}, options || {}, {immediate:false}));
  }

  function isPanelOpen(){
    return panelProgressValue > 0.5;
  }

  root.rowSystem = {
    SAFE_ZONE,
    createRing,
    createSelectedState,
    decorateList,
    updatePanel,
    setPanelProgress,
    setPanelOpen,
    isPanelOpen,
    getPanelSafeZone: ()=>SAFE_ZONE
  };
  root.rowSystem.model = {itemNumber,itemProgress,itemQuality,itemDescription,itemSymbol,panelEntries};
  if(typeof module !== "undefined" && module.exports) module.exports = root.rowSystem;
  if(global.addEventListener) global.addEventListener("resize", ()=>{ if(isPanelOpen()) updatePanel(); }, {passive:true});
})(typeof window !== "undefined" ? window : globalThis);
