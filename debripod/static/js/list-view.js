  function renderList(){
    const prevScroll = (libList ? libList.scrollTop : 0);
    let editInputToFocus = null;
    libList.innerHTML = "";
    for(let i=0;i<state.items.length;i++){
      const it = state.items[i];
      const li = document.createElement("li");
      li.dataset.index = String(i);

      const isSel = (i === state.sel);
      const settingsTall = (
        it.kind === "setting_value" ||
        it.kind === "settings_library_folder" ||
        it.kind === "settings_library_mode_choice" ||
        it.kind === "settings_library_remove"
      );
      const twoLine = (settingsTall || it.kind === "libsearch_result" || it.kind === "libsearch_file" || it.kind === "libtask_file");
      li.className = "ipodItem" + (isSel ? " sel" : "") + (it.kind === "info" ? " info" : "") + (it.kind === "random" ? " random" : "") + (twoLine ? " twoLine" : "") + (settingsTall ? " settingRow" : "");

      if(it.kind === "smart_playlist_rules_text"){
        li.className += " editing";
        const ta = document.createElement("textarea");
        ta.className = "libInlineInput";
        ta.style.minHeight = "220px";
        ta.style.height = "220px";
        ta.style.whiteSpace = "pre";
        ta.value = (state.smartPlaylistRules && typeof state.smartPlaylistRules.text === "string") ? state.smartPlaylistRules.text : "";
        ta.placeholder = "Enter smart playlist rules";
        ta.addEventListener("input", ()=>{
          try{
            if(!state.smartPlaylistRules) state.smartPlaylistRules = {text:"", saving:false};
            state.smartPlaylistRules.text = ta.value || "";
          }catch(e){}
        });
        li.appendChild(ta);
        editInputToFocus = ta;
        libList.appendChild(li);
        continue;
      }

      // Special inline input rows for Library search query/filter and playlist creation
      if(it.kind === "libsearch_query" || it.kind === "libsearch_filter" || it.kind === "playlist_create" || it.kind === "smart_playlist_create" || it.kind === "playlist_edit_name"){
        const isPlaylistCreate = (it.kind === "playlist_create");
        const isSmartPlaylistCreate = (it.kind === "smart_playlist_create");
        const isPlaylistRename = (it.kind === "playlist_edit_name");
        const field = (isPlaylistCreate || isSmartPlaylistCreate || isPlaylistRename) ? "name" : ((it.kind === "libsearch_filter") ? "filter" : "q");
        const placeholder = isPlaylistCreate ? "Create playlist" : (isSmartPlaylistCreate ? "Create smart playlist" : (isPlaylistRename ? "Edit name" : ((it.kind === "libsearch_filter") ? "Enter filters" : "Enter query")));
        const isEditing = (isPlaylistCreate || isSmartPlaylistCreate)
          ? !!(isSel && (isSmartPlaylistCreate ? state.smartPlaylistCreate : state.playlistCreate) && (isSmartPlaylistCreate ? state.smartPlaylistCreate.editing : state.playlistCreate.editing))
          : (isPlaylistRename ? !!(isSel && state.playlistEdit && state.playlistEdit.editingName) : !!(isSel && state.libSearch && state.libSearch.editField === field));
        if(isEditing){
          li.className += " editing";
          const inp = document.createElement("input");
          inp.type = "text";
          inp.className = "libInlineInput";
          inp.value = isPlaylistCreate
            ? ((state.playlistCreate && typeof state.playlistCreate.editValue === "string") ? state.playlistCreate.editValue : "")
            : (isSmartPlaylistCreate
                ? ((state.smartPlaylistCreate && typeof state.smartPlaylistCreate.editValue === "string") ? state.smartPlaylistCreate.editValue : "")
            : (isPlaylistRename
                ? ((state.playlistEdit && typeof state.playlistEdit.editNameValue === "string") ? state.playlistEdit.editNameValue : "")
                : ((state.libSearch && typeof state.libSearch.editValue === "string") ? state.libSearch.editValue : ((state.libSearch && typeof state.libSearch[field] === "string") ? state.libSearch[field] : ""))));
          inp.placeholder = placeholder;
          inp.addEventListener("input", ()=>{
            try{
              if(isPlaylistCreate){
                if(!state.playlistCreate) return;
                state.playlistCreate.editValue = inp.value || "";
              }else if(isSmartPlaylistCreate){
                if(!state.smartPlaylistCreate) return;
                state.smartPlaylistCreate.editValue = inp.value || "";
              }else if(isPlaylistRename){
                if(!state.playlistEdit) return;
                state.playlistEdit.editNameValue = inp.value || "";
              }else{
                if(!state.libSearch) return;
                state.libSearch.editValue = inp.value || "";
                state.libSearch[field] = inp.value || "";
              }
            }catch(e){}
          });
          inp.addEventListener("keydown", (ev)=>{
            if(ev.key === "Enter"){
              ev.preventDefault();
              if(isPlaylistCreate){
                try{
                  if(state.playlistCreate){
                    state.playlistCreate.editValue = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                try{ submitPlaylistCreate(inp.value || ""); }catch(e){}
              }else if(isSmartPlaylistCreate){
                try{
                  if(state.smartPlaylistCreate){
                    state.smartPlaylistCreate.editValue = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                try{ submitSmartPlaylistCreate(inp.value || ""); }catch(e){}
              }else if(isPlaylistRename){
                try{
                  if(state.playlistEdit){
                    state.playlistEdit.editNameValue = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                try{ submitPlaylistRename(inp.value || ""); }catch(e){}
              }else{
                try{
                  if(state.libSearch){
                    state.libSearch.editValue = inp.value || "";
                    state.libSearch[field] = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                if(field === "q") {
                  try{ libDoSearch((state.libSearch && state.libSearch.engine) ? state.libSearch.engine : "combined", inp.value || ""); }catch(e){}
                }
              }
              return;
            }
            if(ev.key === "Escape"){
              ev.preventDefault();
              if(isPlaylistCreate){
                try{
                  if(state.playlistCreate){
                    state.playlistCreate.editing = false;
                    state.playlistCreate.editValue = "";
                  }
                }catch(e){}
                try{ renderList(); }catch(e){}
              }else if(isSmartPlaylistCreate){
                try{
                  if(state.smartPlaylistCreate){
                    state.smartPlaylistCreate.editing = false;
                    state.smartPlaylistCreate.editValue = "";
                  }
                }catch(e){}
                try{ renderList(); }catch(e){}
              }else if(isPlaylistRename){
                try{
                  if(state.playlistEdit){
                    state.playlistEdit.editingName = false;
                    state.playlistEdit.editNameValue = state.playlistEdit.label || "";
                  }
                }catch(e){}
                try{ renderList(); }catch(e){}
              }else{
                try{ inp.blur(); }catch(e){}
              }
              return;
            }
          });
          inp.addEventListener("blur", ()=>{
            try{
              if(isPlaylistCreate){
                if(!state.playlistCreate) return;
                if(state.playlistCreate.editing){
                  state.playlistCreate.editing = false;
                  state.playlistCreate.editValue = "";
                }
              }else if(isSmartPlaylistCreate){
                if(!state.smartPlaylistCreate) return;
                if(state.smartPlaylistCreate.editing){
                  state.smartPlaylistCreate.editing = false;
                  state.smartPlaylistCreate.editValue = "";
                }
              }else if(isPlaylistRename){
                if(!state.playlistEdit) return;
                if(state.playlistEdit.editingName){
                  state.playlistEdit.editingName = false;
                  if(!state.playlistEdit.submitting){
                    state.playlistEdit.editNameValue = state.playlistEdit.label || "";
                  }
                }
              }else{
                if(!state.libSearch) return;
                state.libSearch[field] = inp.value || "";
                if(state.libSearch.editField === field){
                  state.libSearch.editField = "";
                  state.libSearch.editValue = "";
                }
              }
            }catch(e){}
            try{
              if(isPlaylistCreate || isSmartPlaylistCreate || isPlaylistRename){
                renderList();
              }else if(field === "filter"){
                libRefreshList(true);
              }else{
                renderList();
              }
            }catch(e){}
          });
          li.appendChild(inp);
          editInputToFocus = inp;
        }else{
          const labelSpan = document.createElement("span");
          labelSpan.className = "ipodLabel hScrollText";
          const v = isPlaylistCreate
            ? ((state.playlistCreate && typeof state.playlistCreate.editValue === "string") ? state.playlistCreate.editValue : "")
            : (isSmartPlaylistCreate
                ? ((state.smartPlaylistCreate && typeof state.smartPlaylistCreate.editValue === "string") ? state.smartPlaylistCreate.editValue : "")
            : (isPlaylistRename
                ? ((state.playlistEdit && typeof state.playlistEdit.editNameValue === "string") ? state.playlistEdit.editNameValue : ((state.playlistEdit && state.playlistEdit.label) ? state.playlistEdit.label : ""))
                : ((state.libSearch && typeof state.libSearch[field] === "string") ? state.libSearch[field] : "")));
          labelSpan.textContent = (v && v.trim()) ? v : placeholder;
          if(!isPlaylistCreate && !isSmartPlaylistCreate && !isPlaylistRename && field === "q" && v && String(v).trim() && state.libSearch && state.libSearch.searching){
            const searchTextWrap = document.createElement("span");
            searchTextWrap.className = "libSearchQueryText";
            searchTextWrap.appendChild(labelSpan);
            const loader = document.createElement("span");
            loader.className = "libSearchInlineLoader";
            loader.setAttribute("aria-label", "Searching");
            loader.setAttribute("title", "Searching");
            searchTextWrap.appendChild(loader);
            li.appendChild(searchTextWrap);
          }else{
            li.appendChild(labelSpan);
          }

          const wrap = document.createElement("span");
          wrap.className = "ipodPills";
          const sp = document.createElement("span");
          sp.className = "ipodPill" + ((!isPlaylistCreate && !isPlaylistRename && field === "q") ? " v" : "");
          sp.textContent = isPlaylistCreate ? "New" : (isSmartPlaylistCreate ? "Smart" : (isPlaylistRename ? "Name" : ((field === "q") ? "Query" : "Filters")));
          wrap.appendChild(sp);
          // extra pills (status etc.)
          if(Array.isArray(it.pills)){
            for(const p of it.pills){
              if(!p) continue;
              const sp2 = document.createElement("span");
              if(typeof p === "string"){
                sp2.className = "ipodPill";
                sp2.textContent = p;
              }else{
                const tone = String(p.tone || "");
                sp2.className = "ipodPill" + (tone ? (" " + tone) : "");
                sp2.textContent = String(p.text || "");
              }
              wrap.appendChild(sp2);
            }
          }
          li.appendChild(wrap);
        }

        li.addEventListener("click", ()=>{
          const wasSel = (state.sel === i);
          state.sel = i;
          if(isPlaylistCreate){
            if(wasSel) beginPlaylistCreateEdit();
            else renderList();
          }else if(isSmartPlaylistCreate){
            if(wasSel) beginSmartPlaylistCreateEdit();
            else renderList();
          }else if(isPlaylistRename){
            if(wasSel) beginPlaylistRenameEdit();
            else renderList();
          }else if(!(state.libSearch && state.libSearch.editField === field)){
            renderList();
          }
        });

        libList.appendChild(li);
        continue;
      }

      const labelWrap = document.createElement("span");
      labelWrap.className = "ipodLabelWrap";
      const labelSpan = document.createElement("span");
      labelSpan.className = "ipodLabel hScrollText";
      if(it && it.label_html){
        labelSpan.innerHTML = String(it.label_html || "");
      }else if(it && it.kind === "album") {
        let rendered = false;
        try{
          const raw = (typeof it.value === "string") ? JSON.parse(it.value) : (it.value || {});
          const artist = String((raw && raw.artist) || "").trim();
          const album = String((raw && raw.album) || "").trim();
          if(artist && album){
            labelSpan.innerHTML = escapeHtml(album) + '   ' + '<span class="artistStrong">' + escapeHtml(artist) + '</span>';
            rendered = true;
          }
        }catch(e){}
        if(!rendered) labelSpan.textContent = it.label || "";
      }else{
        labelSpan.textContent = it.label || "";
      }
      labelWrap.appendChild(labelSpan);
      if(it && it.sub_label){
        const sub = document.createElement("span");
        sub.className = "ipodSubLabel hScrollText";
        sub.textContent = String(it.sub_label || "");
        labelWrap.appendChild(sub);
      }
      li.appendChild(labelWrap);

      const pills = [];
      if(Array.isArray(it.pills)){
        for(const p of it.pills){
          if(!p) continue;
          if(typeof p === "string"){
            pills.push({text: p, tone: "", bar: null});
          }else if(typeof p === "object"){
            const bar = (p.bar != null && isFinite(Number(p.bar))) ? Math.max(0, Math.min(1, Number(p.bar))) : null;
            pills.push({text: String(p.text || ""), tone: String(p.tone || ""), bar: bar});
          }
        }
      }
      if(it.badge){
        pills.push({text: String(it.badge), tone: "warn"});
      }

      if(it.selectable){
        pills.push({text: it.selected ? "Selected" : "Select", tone: it.selected ? "ok" : "" , _selectPill: true});
      }

      if(pills.length){
        const wrap = document.createElement("span");
        wrap.className = "ipodPills";
        for(const p of pills){
          const sp = document.createElement("span");
          const toneCls = p.tone ? (" " + p.tone) : "";
          if(p.bar != null && isFinite(Number(p.bar))){
            sp.className = "ipodPill bar" + toneCls;
            const fill = document.createElement("span");
            fill.className = "pillBarFill";
            fill.style.width = (Math.max(0, Math.min(1, Number(p.bar))) * 100).toFixed(1) + "%";
            const txt = document.createElement("span");
            txt.className = "pillBarText";
            txt.textContent = p.text || "";
            sp.appendChild(fill);
            sp.appendChild(txt);
          }else{
            sp.className = "ipodPill" + toneCls;
            sp.textContent = p.text || "";
          }
          if(p._selectPill){
            sp.addEventListener("click", (ev)=>{
              ev.preventDefault();
              ev.stopPropagation();
              state.sel = i;
              try{
                if(it.kind === "playlist_add_file"){
                  const act = selectItem(it);
                  if(act && typeof act.catch === "function") act.catch(()=>{});
                  return;
                }
                if(it.kind === "np_playlist_entry"){
                  const act = selectItem(it);
                  if(act && typeof act.catch === "function") act.catch(()=>{});
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
                  const act = viewPlaylistRemoveSongs(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", false);
                  if(act && typeof act.catch === "function") act.catch(()=>{});
                  return;
                }
                if(typeof it.onToggle === "function"){
                  it.onToggle();
                }else{
                  it.selected = !it.selected;
                }
              }catch(e){}
              renderList();
            });
          }
          wrap.appendChild(sp);
        }
        li.appendChild(wrap);
      }

      li.addEventListener("click", ()=>{
        setSelectionFast(i);
        try{
          const p = selectItem(it);
          if(p && typeof p.catch === "function"){ p.catch(()=>{}); }
        }catch(e){}
      });
      libList.appendChild(li);
    }
    if(state.items.length === 0){
      const li = document.createElement("li");
      li.className = "ipodItem info";
      li.textContent = "Empty";
      libList.appendChild(li);
    }

    // restore scroll position first, then ensure selection is visible without jumping to top
    try{
      if(libList) libList.scrollTop = prevScroll;
    }catch(e){}
    const selEl = libList.querySelector(".ipodItem.sel");
    if(selEl){
      selEl.scrollIntoView({block: "nearest"});
    }
    if(editInputToFocus){
      try{
        editInputToFocus.focus();
        editInputToFocus.click();
        const n = editInputToFocus.value.length;
        editInputToFocus.setSelectionRange(n, n);
      }catch(e){}
    }
    try{
      refreshSelectedHScrollText();
    }catch(e){}
  }

function vibeTick(){
  try{
    if(navigator && typeof navigator.vibrate === "function"){
      navigator.vibrate(8);
    }
  }catch(e){}
}

// ===== library actions (reindex, last.fm auth, forced fullscreen) =====
  var forceFullscreen = false;

  async function doLibraryReindex(){
    try{
      await fetch("/api/library/reindex", {method: "POST"});
      return true;
    }catch(e){
      alert("Reindex failed: " + (e && e.message ? e.message : String(e)));
      return false;
    }
  }

  async function getAnyIndexBuilding(){
    try{
      const js = await apiGet("/api/library/building");
      return !!(js && js.ok && js.any_building);
    }catch(e){
      return false;
    }
  }

  async function startLastfmLoginFlow(){
    let token = null;
    let authUrl = null;

    try{
      const r = await fetch("/api/lastfm/auth/start", {method: "GET"});
      const j = await r.json();
      if(!j || !j.ok){
        throw new Error((j && j.error) ? j.error : "Last.fm auth start failed");
      }
      token = j.token;
      authUrl = j.auth_url;
    }catch(e){
      alert("Last.fm login failed: " + (e && e.message ? e.message : String(e)));
      return false;
    }

    try{
      if(authUrl){
        window.open(authUrl, "_blank", "noopener");
      }
    }catch(e){}

    let proceed = true;
    try{
      proceed = confirm("A Last.fm approval page was opened. After you approve DebriPod, click OK to finish login.");
    }catch(e){}

    if(!proceed){
      return false;
    }

    try{
      const r2 = await fetch("/api/lastfm/auth/finish", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token: token})
      });
      const j2 = await r2.json();
      if(!j2 || !j2.ok){
        throw new Error((j2 && j2.error) ? j2.error : "Last.fm auth finish failed");
      }
      alert("Last.fm login complete.");
      return true;
    }catch(e){
      alert("Last.fm login failed: " + (e && e.message ? e.message : String(e)));
      return false;
    }
  }

  async function forceFullscreenOn(){
    forceFullscreen = true;
    try{
      if(!document.fullscreenElement && document.documentElement && document.documentElement.requestFullscreen){
        await document.documentElement.requestFullscreen();
      }
    }catch(e){}
  }

  document.addEventListener("fullscreenchange", ()=>{
    if(forceFullscreen && !document.fullscreenElement){
      setTimeout(async ()=>{
        if(forceFullscreen && !document.fullscreenElement){
          try{
            if(document.documentElement && document.documentElement.requestFullscreen){
              await document.documentElement.requestFullscreen();
            }
          }catch(e){}
        }
      }, 150);
    }
  });
;


  function setSelectionFast(nextIndex){
    if(!state.items.length) return;
    const n = state.items.length;
    const prev = state.sel;
    const next = Math.max(0, Math.min(n - 1, Number(nextIndex || 0)));
    if(next === prev) return;
    state.sel = next;
    if(state.sel !== prev){
      try{
        if(state.playlistCreate) state.playlistCreate.editing = false;
        if(state.smartPlaylistCreate) state.smartPlaylistCreate.editing = false;
        if(state.playlistEdit) state.playlistEdit.editingName = false;
        if(state.libSearch && state.libSearch.editField) state.libSearch.editField = "";
      }catch(e){}
      vibeTick();
    }
    try{
      if(!libList) return;
      const oldEl = libList.querySelector('.ipodItem[data-index="' + prev + '"]') || libList.children[prev];
      const newEl = libList.querySelector('.ipodItem[data-index="' + state.sel + '"]') || libList.children[state.sel];
      if(oldEl) oldEl.classList.remove("sel");
      if(newEl){
        newEl.classList.add("sel");
        const top = newEl.offsetTop;
        const bottom = top + newEl.offsetHeight;
        const viewTop = libList.scrollTop;
        const viewBottom = viewTop + libList.clientHeight;
        if(top < viewTop) libList.scrollTop = top;
        else if(bottom > viewBottom) libList.scrollTop = Math.max(0, bottom - libList.clientHeight);
      }
      refreshSelectedHScrollText();
    }catch(e){
      renderList();
    }
  }

  function scrollSel(delta){
    setSelectionFast(state.sel + delta);
  }

  function _randomEligibleItem(it){
    if(!it) return false;
    const k = (it.kind || "");
    if(!k) return false;
    if(k === "info" || k === "up" || k === "random" || k === "playlist_create" || k === "smart_playlist_create" || k === "playlist_edit_entry") return false;
    return true;
  }

  function _shouldAddRandom(items){
    try{
      if(!state.current) return false;
      const vk = state.current.kind || "";
      // Remove Random from the top-level Browse screen
      if(vk !== "folder" && vk !== "metalist") return false;

      // Remove Random from individual album tracklists
      if(vk === "metalist" && (state.current.level || "") === "tracks") return false;

      for(const it of (items || [])){
        if(_randomEligibleItem(it)) return true;
      }
      return false;
    }catch(e){
      return false;
    }
  }

  function resetList(items){
    const arr = Array.isArray(items) ? items.slice() : [];
    if(_shouldAddRandom(arr)){
      const btn = {kind:"random", label:"Random"};
      let insertAt = 0;
      while(insertAt < arr.length){
        const k = (arr[insertAt] && arr[insertAt].kind) ? arr[insertAt].kind : "";
        if(k === "up" || k === "playlist_create" || k === "smart_playlist_create" || k === "playlist_edit_entry"){
          insertAt += 1;
          continue;
        }
        break;
      }
      arr.splice(insertAt, 0, btn);
    }
    state.items = arr;

    // Restore selection and scroll when returning to a list via Menu/back
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

    if(restoreSel != null){
      const max = Math.max(0, arr.length - 1);
      state.sel = Math.max(0, Math.min(max, restoreSel));
    }else{
      state.sel = 0;
    }

    setHeader();
    renderList();

    if(restoreScroll != null && libList){
      const top = Math.max(0, restoreScroll);
      requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
    }
  }

  function snapshotListState(){
    try{
      if(state.current){
        state.current.savedSel = state.sel;
        if(libList) state.current.savedScroll = libList.scrollTop;
      }
    }catch(e){}
  }

  function waitLibPageFade(ms){
    return new Promise(resolve=> setTimeout(resolve, ms || 220));
  }

  async function runLibraryPageTransition(loadFn){
    try{
      if(libList){
        libList.classList.add("pageFadeHidden");
        await waitLibPageFade(220);
      }
      await loadFn();
      if(libList){
        requestAnimationFrame(()=>{
          requestAnimationFrame(()=>{
            try{ libList.classList.remove("pageFadeHidden"); }catch(e){}
          });
        });
      }
    }catch(e){
      try{ if(libList) libList.classList.remove("pageFadeHidden"); }catch(_e){}
      throw e;
    }
  }

  async function setView(view, push){
    await runLibraryPageTransition(async ()=>{
      if(push && state.current){
        snapshotListState();
        state.history.push(state.current);
      }
      state.current = view;
      setHeader();
      await view.load();
      setHeader();
    });
  }

  function rootViewObj(){
    return {
      kind: "roots",
      label: "",
      savedSel: 0,
      savedScroll: 0,
      load: async function(){
        await showRoots(false);
      }
    };
  }
