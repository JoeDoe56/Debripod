  function setGlassText(el, text){
    if(!el) return el;
    const value = String(text == null ? "" : text);
    el.classList.add("glassText");
    el.setAttribute("data-text", value);
    el.setAttribute("data-liquid-ignore", "");
    el.textContent = value;
    return el;
  }

  function syncGlassText(el){
    if(!el) return el;
    el.classList.add("glassText");
    el.setAttribute("data-text", String(el.textContent || ""));
    el.setAttribute("data-liquid-ignore", "");
    return el;
  }

  function makeGlassPillText(text, extraClass){
    const span = document.createElement("span");
    span.className = "ipodPillText glassText" + (extraClass ? (" " + extraClass) : "");
    return setGlassText(span, text);
  }

  function prepareGlassPill(el, text){
    if(!el) return el;
    el.classList.add("liquidGlass");
    el.setAttribute("data-liquid-row-pill", "");
    el.appendChild(makeGlassPillText(text));
    return el;
  }

  const dpRowHeightCache = new Map();
  const dpVirtualMetrics = {
    descriptor: "",
    byKey: new Map(),
    byIndexType: new Map(),
    fallback: 56,
    prefix: null,
    prefixSignature: ""
  };

  function virtualViewDescriptor(){
    try{
      const cur = state && state.current ? state.current : {};
      return [
        cur.kind || "",
        cur.root && cur.root.id || cur.root_id || "",
        cur.level || "",
        cur.value || "",
        cur.rel || "",
        cur.label || ""
      ].join("|");
    }catch(e){
      return "default";
    }
  }

  function rowViewMetrics(){
    const descriptor = virtualViewDescriptor();
    if(dpVirtualMetrics.descriptor !== descriptor){
      dpVirtualMetrics.descriptor = descriptor;
      dpVirtualMetrics.byKey.clear();
      dpVirtualMetrics.byIndexType.clear();
      dpVirtualMetrics.fallback = 56;
      dpVirtualMetrics.prefix = null;
      dpVirtualMetrics.prefixSignature = "";
    }
    return dpVirtualMetrics;
  }

  function virtualRowType(item){
    try{
      if(!item) return "empty";
      const flags = [
        item.kind || "",
        item.media || "",
        item.forceTwoLine ? "two" : "",
        item.settingRow ? "setting" : "",
        item.sub_label ? "sub" : "",
        item.expanded ? "expanded" : "",
        item.sub_row ? JSON.stringify(item.sub_row) : "",
        Array.isArray(item.pills) ? "p" + item.pills.length : "p0"
      ];
      return flags.join(":");
    }catch(e){
      return "unknown";
    }
  }

  function virtualItemIdentity(item, index){
    try{
      if(!item) return "idx:" + String(index || 0);
      const rootId = item.root && item.root.id || item.rootId || item.root_id || "";
      const stable = item.rel || item.value || item.cat || item.action || item.task_id || item.result_id || "";
      if(stable) return [rootId, stable].join("/");
      if(item.queueKind || item.queueIndex != null) return ["queue", item.queueKind || "", item.queueIndex == null ? index : item.queueIndex].join("/");
      return "idx:" + String(index || 0);
    }catch(e){
      return "idx:" + String(index || 0);
    }
  }

  function virtualMetricKey(index, item){
    return virtualRowType(item) + "|" + virtualItemIdentity(item, index);
  }

  function rowHeightCacheKey(index, item){
    return virtualViewDescriptor() + "::" + virtualMetricKey(index, item);
  }

  function invalidateVirtualPrefix(){
    try{
      dpVirtualMetrics.prefix = null;
      dpVirtualMetrics.prefixSignature = "";
    }catch(e){}
  }

  function cachedItemHeight(index, item){
    try{
      const metrics = rowViewMetrics();
      const key = virtualMetricKey(index, item);
      const byKey = metrics.byKey.get(key);
      if(byKey && byKey > 0) return byKey;
      const byIndex = metrics.byIndexType.get(String(index) + "|" + virtualRowType(item));
      if(byIndex && byIndex > 0) return byIndex;
      const cached = dpRowHeightCache.get(rowHeightCacheKey(index, item));
      if(cached && cached > 0) return cached;
      if(metrics && metrics.fallback) return Math.max(estimatedItemHeight(item), metrics.fallback);
    }catch(e){}
    return estimatedItemHeight(item);
  }

  function virtualHeightForIndex(index){
    try{
      return cachedItemHeight(index, state.items[index]);
    }catch(e){
      return estimatedItemHeight(state.items[index]);
    }
  }

  function virtualPrefixSignature(){
    try{
      const items = state && Array.isArray(state.items) ? state.items : [];
      const parts = [String(items.length)];
      for(let i = 0; i < items.length; i++){
        parts.push(virtualMetricKey(i, items[i]));
      }
      return parts.join("\n");
    }catch(e){
      return "";
    }
  }

  function virtualPrefixHeights(){
    const count = state && Array.isArray(state.items) ? state.items.length : 0;
    const metrics = rowViewMetrics();
    const signature = virtualPrefixSignature();
    if(metrics.prefix && metrics.prefixSignature === signature && metrics.prefix.length === count + 1){
      return metrics.prefix;
    }
    const prefix = new Array(count + 1);
    prefix[0] = 0;
    for(let i = 0; i < count; i++){
      prefix[i + 1] = prefix[i] + Math.max(1, virtualHeightForIndex(i));
    }
    metrics.prefix = prefix;
    metrics.prefixSignature = signature;
    return prefix;
  }

  function virtualLowerBound(prefix, target){
    let lo = 0;
    let hi = prefix.length;
    const needle = Math.max(0, Number(target || 0));
    while(lo < hi){
      const mid = (lo + hi) >> 1;
      if(prefix[mid] < needle) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  function measureRenderedRowHeights(){
    try{
      if(!libList || !state || !Array.isArray(state.items)) return;
      const metrics = rowViewMetrics();
      let total = 0;
      let count = 0;
      libList.querySelectorAll(".ipodItem[data-index]").forEach((row)=>{
        const idx = Number(row.dataset.index);
        if(!Number.isFinite(idx) || !state.items[idx]) return;
        const h = row.getBoundingClientRect ? row.getBoundingClientRect().height : row.offsetHeight;
        if(h > 0){
          const safeH = Math.max(24, h);
          const item = state.items[idx];
          const key = virtualMetricKey(idx, item);
          dpRowHeightCache.set(rowHeightCacheKey(idx, item), safeH);
          metrics.byKey.set(key, safeH);
          metrics.byIndexType.set(String(idx) + "|" + virtualRowType(item), safeH);
          total += safeH;
          count += 1;
        }
      });
      if(count){
        metrics.fallback = Math.max(metrics.fallback || 0, Math.ceil(total / count));
        invalidateVirtualPrefix();
      }
      while(dpRowHeightCache.size > 600){
        const first = dpRowHeightCache.keys().next();
        if(first.done) break;
        dpRowHeightCache.delete(first.value);
      }
    }catch(e){}
  }

  function ensureLibItemVisible(el){
    try{
      if(!libList || !el) return;
      const cs = window.getComputedStyle ? window.getComputedStyle(libList) : null;
      const padTop = cs ? (parseFloat(cs.paddingTop || "0") || 0) : 0;
      const padBottom = cs ? (parseFloat(cs.paddingBottom || "0") || 0) : padTop;
      const safeTop = padTop;
      const safeBottom = padBottom;
      const top = el.offsetTop;
      const bottom = top + el.offsetHeight;
      const viewTop = libList.scrollTop + safeTop;
      const viewBottom = libList.scrollTop + libList.clientHeight - safeBottom;
      if(top < viewTop) animateLibListScrollTo(Math.max(0, top - safeTop));
      else if(bottom > viewBottom) animateLibListScrollTo(Math.max(0, bottom + safeBottom - libList.clientHeight));
    }catch(e){}
  }

  function animateLibListScrollTo(targetTop){
    try{
      if(!libList) return;
      const maxTop = Math.max(0, libList.scrollHeight - libList.clientHeight);
      const target = Math.max(0, Math.min(maxTop, Number(targetTop || 0)));
      if(Math.abs((libList.scrollTop || 0) - target) < 0.5){
        libList.scrollTop = target;
        if(typeof invalidateLibPillGlass === "function") invalidateLibPillGlass("scroll correction");
        return;
      }
      if(libList._dpScrollAnimFrame) cancelAnimationFrame(libList._dpScrollAnimFrame);
      const start = libList.scrollTop || 0;
      const delta = target - start;
      const started = performance.now();
      const duration = Math.min(180, Math.max(80, Math.abs(delta) * 1.15));
      let lastTick = 0;
      const tick = (now)=>{
        try{
          const frameNow = Number(now || performance.now());
          const interval = (typeof animationFrameIntervalMs === "function") ? animationFrameIntervalMs("libraryList") : (1000 / 60);
          if(lastTick && frameNow - lastTick < interval - 1){
            libList._dpScrollAnimFrame = requestAnimationFrame(tick);
            return;
          }
          lastTick = frameNow;
          const t = Math.max(0, Math.min(1, (frameNow - started) / duration));
          const eased = 1 - Math.pow(1 - t, 3);
          libList.scrollTop = start + delta * eased;
          if(typeof invalidateLibPillGlass === "function") invalidateLibPillGlass("smooth scroll");
          if(t < 1) libList._dpScrollAnimFrame = requestAnimationFrame(tick);
          else libList._dpScrollAnimFrame = 0;
        }catch(e){
          libList._dpScrollAnimFrame = 0;
        }
      };
      libList._dpScrollAnimFrame = requestAnimationFrame(tick);
    }catch(e){}
  }

  function estimatedItemHeight(item){
    try{
      if(!item) return 44;
      if(item.expanded && item.sub_row) return 88;
      if(item.kind === "smart_playlist_rules_text") return 236;
      if(item.kind === "range_editor_input" || item.kind === "range_editor_slider") return 76;
      if(item.sub_label) return 68;
      if(item.forceTwoLine || item.settingRow || item.kind === "setting_value" || item.kind === "settings_library_folder" || item.kind === "settings_library_remove") return 76;
      if(item.kind === "libsearch_result" || item.kind === "libsearch_file" || item.kind === "libtask_file") return 76;
      if(item.kind === "song" || item.kind === "track" || item.kind === "file" || item.kind === "liked_song" || item.media === "audio") return item.pills && item.pills.length > 2 ? 64 : 56;
    }catch(e){}
    return 44;
  }

  function makeInlineLoader(label){
    const loader = document.createElement("span");
    loader.className = "dpInlineLoader";
    loader.setAttribute("role", "status");
    loader.setAttribute("aria-label", String(label || "Loading"));
    loader.setAttribute("title", String(label || "Loading"));
    return loader;
  }

  function appendExpandedSubRow(li, item){
    const sub = item && item.expanded && item.sub_row;
    if(!li || !sub) return;
    li.classList.add("isExpandedRow");
    const main = document.createElement("span");
    main.className = "ipodExpandedMain";
    while(li.firstChild) main.appendChild(li.firstChild);
    li.appendChild(main);
    const row = document.createElement("span");
    row.className = "ipodExpandedSub";
    const subText = String(sub.text || sub.label || "");
    if(sub.loading) row.appendChild(makeInlineLoader(subText || "Loading"));
    const label = document.createElement("span");
    label.className = "ipodExpandedSubLabel";
    setGlassText(label, subText);
    row.appendChild(label);
    if(Array.isArray(sub.pills)){
      const pills = document.createElement("span");
      pills.className = "ipodPills";
      for(const value of sub.pills){
        const pill = document.createElement("span");
        pill.className = "ipodPill" + (typeof value === "object" && value.tone ? " " + String(value.tone) : "");
        prepareGlassPill(pill, typeof value === "object" ? String(value.text || "") : String(value || ""));
        pills.appendChild(pill);
      }
      row.appendChild(pills);
    }
    li.appendChild(row);
  }

  function virtualizableViewKind(kind){
    const stableViews = new Set([
      "folder",
      "metatop",
      "metalist",
      "history",
      "playback_queue",
      "libsearch_history",
      "libsearch",
      "libsearch_files",
      "libsearch_result_list",
      "libtasks"
    ]);
    return stableViews.has(String(kind || ""));
  }

  function canVirtualizeList(){
    try{
      if(!libList || !state || !Array.isArray(state.items)) return false;
      if(state.items.length < 220) return false;
      const cur = state.current || {};
      const kind = String(cur.kind || "");
      if(!virtualizableViewKind(kind) && cur.readOnly !== true) return false;
      const active = document.activeElement;
      if(active && libList.contains(active) && /^(INPUT|TEXTAREA|SELECT|BUTTON)$/i.test(active.tagName || "")) return false;
      return !state.items.some((item)=> item && (
        item.settingRow ||
        item.kind === "range_editor_input" ||
        item.kind === "range_editor_slider" ||
        item.kind === "smart_playlist_rules_text" ||
        item.kind === "playlist_create" ||
        item.kind === "smart_playlist_create" ||
        item.kind === "playlist_edit_name" ||
        item.kind === "setting_value" ||
        item.kind === "settings_library_folder" ||
        item.kind === "settings_library_remove" ||
        item.kind === "libui_action"
      ));
    }catch(e){
      return false;
    }
  }

  function listVirtualWindow(){
    const count = state && Array.isArray(state.items) ? state.items.length : 0;
    const enabled = canVirtualizeList();
    if(!enabled) return {enabled:false, start:0, end:count, top:0, bottom:0, visible:count, total:count};
    const prefix = virtualPrefixHeights();
    const totalHeight = prefix[count] || 0;
    const viewportTop = Math.max(0, libList.scrollTop || 0);
    const viewportBottom = viewportTop + Math.max(1, libList.clientHeight || 1);
    const overscan = Math.max(280, (libList.clientHeight || 360) * 0.8);
    const startTarget = Math.max(0, viewportTop - overscan);
    const endTarget = Math.min(totalHeight, viewportBottom + overscan);
    const start = Math.max(0, Math.min(count, virtualLowerBound(prefix, startTarget) - 1));
    const end = Math.max(start + 1, Math.min(count, virtualLowerBound(prefix, endTarget) + 1));
    const top = prefix[start] || 0;
    const bottom = Math.max(0, totalHeight - (prefix[end] || top));
    return {enabled:true, start, end, top, bottom, visible:end - start, total:count, height:totalHeight};
  }

  function appendVirtualSpacer(layer, height, pos){
    if(!(height > 0)) return;
    const spacer = document.createElement("li");
    spacer.className = "ipodVirtualSpacer";
    spacer.setAttribute("aria-hidden", "true");
    spacer.dataset.virtualSpacer = pos || "";
    spacer.style.height = Math.max(0, height).toFixed(1) + "px";
    layer.appendChild(spacer);
  }

  function syncVirtualSpacerHeights(virtual){
    try{
      if(!libList || !virtual || !virtual.enabled) return virtual;
      const prefix = virtualPrefixHeights();
      const count = state && Array.isArray(state.items) ? state.items.length : 0;
      const top = prefix[virtual.start] || 0;
      const bottom = Math.max(0, (prefix[count] || 0) - (prefix[virtual.end] || top));
      const topSpacer = libList.querySelector('.ipodVirtualSpacer[data-virtual-spacer="top"]');
      const bottomSpacer = libList.querySelector('.ipodVirtualSpacer[data-virtual-spacer="bottom"]');
      if(topSpacer) topSpacer.style.height = Math.max(0, top).toFixed(1) + "px";
      if(bottomSpacer) bottomSpacer.style.height = Math.max(0, bottom).toFixed(1) + "px";
      virtual.top = top;
      virtual.bottom = bottom;
      virtual.height = prefix[count] || 0;
      return virtual;
    }catch(e){
      return virtual;
    }
  }

  function appendListEndSpacer(layer){
    try{
      const spacer = document.createElement("li");
      spacer.className = "ipodListEndSpacer";
      spacer.setAttribute("aria-hidden", "true");
      layer.appendChild(spacer);
    }catch(e){}
  }

  function syncSelectedRowMarkers(row, selected){
    try{
      if(!row) return;
      row.classList.toggle("sel", !!selected);
      if(selected) row.setAttribute("data-selected-row", "");
      else row.removeAttribute("data-selected-row");
      row.querySelectorAll("[data-selected-row-text],[data-selected-row-pill-text]").forEach((el)=>{
        el.removeAttribute("data-selected-row-text");
        el.removeAttribute("data-selected-row-pill-text");
      });
      if(!selected) return;
      row.querySelectorAll(".ipodLabel, .ipodSubLabel").forEach((el)=> el.setAttribute("data-selected-row-text", ""));
      row.querySelectorAll(".ipodPillText").forEach((el)=> el.setAttribute("data-selected-row-pill-text", ""));
    }catch(e){}
  }

  function virtualOffsetForIndex(index){
    try{
      const n = Math.max(0, Math.min((state.items.length || 1) - 1, Number(index || 0)));
      const prefix = virtualPrefixHeights();
      return prefix[n] || 0;
    }catch(e){
      return 0;
    }
  }

  function renderList(options){
    const renderOptions = options || {};
    const prevScroll = (libList ? libList.scrollTop : 0);
    let editInputToFocus = null;
    const finishRenderingList = ()=>{
      try{
        if(!libList) return;
        libList._dpRenderingList = false;
        libList._dpRenderGuardFrame = 0;
        if(libList._dpVirtualScrollPending && libList._dpVirtualized){
          libList._dpVirtualScrollPending = false;
          scheduleVirtualListRender("pending scroll");
        }
      }catch(e){}
    };
    if(libList){
      libList._dpRenderingList = true;
      libList.style.overflowAnchor = "none";
      if(libList._dpRenderGuardFrame){
        try{ cancelAnimationFrame(libList._dpRenderGuardFrame); }catch(e){}
        libList._dpRenderGuardFrame = 0;
      }
    }
    try{
    try{ if(!renderOptions.virtualScroll && typeof hideTransientListGlass === "function") hideTransientListGlass("before list render"); }catch(e){}
    const itemsLayer = document.createDocumentFragment();
    const virtual = listVirtualWindow();
    if(libList) libList._dpVirtualized = !!virtual.enabled;
    appendVirtualSpacer(itemsLayer, virtual.top, "top");
    for(let i=virtual.start;i<virtual.end;i++){
      const it = state.items[i];
      const li = document.createElement("li");
      li.dataset.index = String(i);

      const isSel = (i === state.sel);
      const settingsTall = (
        it.forceTwoLine ||
        it.settingRow ||
        it.kind === "setting_value" ||
        it.kind === "settings_library_folder" ||
        it.kind === "settings_library_remove"
      );
      const twoLine = (settingsTall || it.kind === "libsearch_result" || it.kind === "libsearch_file" || it.kind === "libtask_file");
      li.className = "ipodItem" + (isSel ? " sel" : "") + ((it.kind === "info" || it.kind === "loading") ? " info" : "") + (it.kind === "random" ? " random" : "") + (twoLine ? " twoLine" : "") + (settingsTall ? " settingRow" : "");
      if(it.kind === "loading") it.disabled = true;
      if(it.disabled){
        li.classList.add("disabled");
        li.setAttribute("aria-disabled", "true");
      }
      if(isSel) li.setAttribute("data-selected-row", "");

      if(it.kind === "range_editor_input"){
        const editing = !!((state.inlineRangeEditor && state.inlineRangeEditor.rangeKeyboardOpen) || (state.current && state.current.kind === "range_editor" && state.current.rangeKeyboardOpen));
        if(editing){
          li.className += " editing";
          const inp = document.createElement("input");
          inp.type = "text";
          inp.inputMode = "decimal";
          inp.className = "libInlineInput";
          inp.value = String(it.value == null ? "" : it.value);
          inp.addEventListener("input", ()=>{
            try{
              const editor = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
              if(editor){
                editor.rangeValue = Number(inp.value);
              }
            }catch(e){}
          });
          inp.addEventListener("keydown", (ev)=>{
            if(ev.key === "Enter"){
              ev.preventDefault();
              try{
                const editor = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
                if(editor) editor.rangeValue = Number(inp.value);
              }catch(e){}
              try{ applyRangeEditor(); }catch(e){}
            }
          });
          li.appendChild(inp);
          editInputToFocus = inp;
        }else{
          const labelWrap = document.createElement("span");
          labelWrap.className = "ipodLabelWrap";
          const labelSpan = document.createElement("span");
          labelSpan.className = "ipodLabel hScrollText";
          setGlassText(labelSpan, it.label || "Value");
          labelWrap.appendChild(labelSpan);
          li.appendChild(labelWrap);
          const wrap = document.createElement("span");
          wrap.className = "ipodPills";
          const bar = document.createElement("span");
          bar.className = "ipodPill bar";
          bar.classList.add("liquidGlass");
          bar.setAttribute("data-liquid-row-pill", "");
          const fill = document.createElement("span");
          fill.className = "pillBarFill";
          fill.style.width = (Math.max(0, Math.min(1, Number(it.bar || 0))) * 100).toFixed(1) + "%";
          const txt = makeGlassPillText(String(it.value == null ? "" : it.value), "pillBarText");
          if(isSel) txt.setAttribute("data-selected-row-pill-text", "");
          bar.appendChild(fill);
          bar.appendChild(txt);
          wrap.appendChild(bar);
          if(Array.isArray(it.pills)){
            for(const p of it.pills){
              if(!p) continue;
              const sp = document.createElement("span");
              sp.className = "ipodPill";
              prepareGlassPill(sp, String(p));
              wrap.appendChild(sp);
            }
          }
          li.appendChild(wrap);
          li.addEventListener("click", ()=>{
            state.sel = i;
            try{
              const editor = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
              if(editor && editor.rangeWheelArmed) openRangeEditorKeyboard();
              else armRangeEditorWheel();
            }catch(e){}
          });
        }
        itemsLayer.appendChild(li);
        continue;
      }

      if(it.kind === "setup_text_input"){
        li.className += " editing twoLine settingRow";
        const inp = document.createElement("input");
        inp.type = it.secret ? "password" : "text";
        inp.className = "libInlineInput";
        inp.placeholder = it.placeholder || "";
        inp.value = String(it.value == null ? "" : it.value);
        inp.addEventListener("input", ()=>{
          try{
            if(state.current && state.current.kind === "setup_editor") state.current.editorValue = inp.value;
          }catch(e){}
        });
        inp.addEventListener("keydown", (ev)=>{
          if(ev.key === "Enter"){
            ev.preventDefault();
            try{
              if(state.current && state.current.kind === "setup_editor") state.current.editorValue = inp.value;
              if(typeof commitSetupEditor === "function") commitSetupEditor();
            }catch(e){}
          }
        });
        li.appendChild(inp);
        editInputToFocus = inp;
        itemsLayer.appendChild(li);
        continue;
      }

      if(it.kind === "range_editor_slider"){
        const labelWrap = document.createElement("span");
        labelWrap.className = "ipodLabelWrap";
        const labelSpan = document.createElement("span");
        labelSpan.className = "ipodLabel hScrollText";
        setGlassText(labelSpan, it.label || "Slider");
        labelWrap.appendChild(labelSpan);
        li.appendChild(labelWrap);
        const wrap = document.createElement("span");
        wrap.className = "ipodPills";
        const sp = document.createElement("span");
        sp.className = "ipodPill bar";
        sp.classList.add("liquidGlass");
        sp.setAttribute("data-liquid-row-pill", "");
        const fill = document.createElement("span");
        fill.className = "pillBarFill";
        fill.style.width = (Math.max(0, Math.min(1, Number(it.bar || 0))) * 100).toFixed(1) + "%";
        const txt = makeGlassPillText(String(Math.round(Math.max(0, Math.min(1, Number(it.bar || 0))) * 100)) + "%", "pillBarText");
        if(isSel) txt.setAttribute("data-selected-row-pill-text", "");
        sp.appendChild(fill);
        sp.appendChild(txt);
        wrap.appendChild(sp);
        li.appendChild(wrap);
        itemsLayer.appendChild(li);
        continue;
      }

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
        itemsLayer.appendChild(li);
        continue;
      }

      if(it.kind === "debrid_token"){
        const view = state.current || {};
        const editing = !!(isSel && view.debridTokenEditing);
        if(editing){
          li.className += " editing";
          const inp = document.createElement("input");
          inp.type = "text";
          inp.autocomplete = "off";
          inp.autocapitalize = "none";
          inp.spellcheck = false;
          inp.className = "libInlineInput";
          inp.value = String(view.debridTokenValue || "");
          inp.placeholder = String(it.placeholder || "Paste debrid token");
          inp.addEventListener("input", ()=>{ view.debridTokenValue = inp.value || ""; });
          inp.addEventListener("keydown", (ev)=>{
            if(ev.key === "Enter"){
              ev.preventDefault();
              view.debridTokenValue = inp.value || "";
              try{ if(typeof connectDebridToken === "function") connectDebridToken(inp.value || ""); }catch(e){}
            }else if(ev.key === "Escape"){
              ev.preventDefault();
              view.debridTokenEditing = false;
              view.debridTokenValue = "";
              renderList();
            }
          });
          inp.addEventListener("blur", ()=>{
            if(view.debridTokenSubmitting) return;
            view.debridTokenEditing = false;
            view.debridTokenValue = "";
            renderList();
          });
          li.appendChild(inp);
          if(view.debridTokenSubmitting || view.debridTokenError){
            const status = document.createElement("span");
            status.className = "ipodPills";
            const pill = document.createElement("span");
            pill.className = "ipodPill " + (view.debridTokenError ? "warn" : "");
            prepareGlassPill(pill, view.debridTokenError ? String(view.debridTokenError) : "Connecting");
            status.appendChild(pill);
            li.appendChild(status);
          }
          editInputToFocus = inp;
        }else{
          li.className += " twoLine";
          const labelWrap = document.createElement("span");
          labelWrap.className = "ipodLabelWrap";
          const label = document.createElement("span");
          label.className = "ipodLabel hScrollText";
          setGlassText(label, String(it.label || "Debrid token"));
          labelWrap.appendChild(label);
          const prompt = document.createElement("span");
          prompt.className = "ipodSubLabel hScrollText";
          setGlassText(prompt, String(it.placeholder || "Paste debrid token"));
          labelWrap.appendChild(prompt);
          li.appendChild(labelWrap);
          const pills = document.createElement("span");
          pills.className = "ipodPills";
          for(const p of (it.pills || [])){
            const pill = document.createElement("span");
            const tone = typeof p === "object" ? String(p.tone || "") : "";
            pill.className = "ipodPill" + (tone ? " " + tone : "");
            prepareGlassPill(pill, typeof p === "object" ? String(p.text || "") : String(p || ""));
            pills.appendChild(pill);
          }
          li.appendChild(pills);
        }
        li.addEventListener("click", ()=>{
          state.sel = i;
          if(!view.debridTokenEditing && typeof beginDebridTokenEdit === "function") beginDebridTokenEdit();
        });
        itemsLayer.appendChild(li);
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
          setGlassText(labelSpan, (v && v.trim()) ? v : placeholder);
          li.appendChild(labelSpan);

          const wrap = document.createElement("span");
          wrap.className = "ipodPills";
          const sp = document.createElement("span");
          sp.className = "ipodPill" + ((!isPlaylistCreate && !isPlaylistRename && field === "q") ? " v" : "");
          prepareGlassPill(sp, isPlaylistCreate ? "New" : (isSmartPlaylistCreate ? "Smart" : (isPlaylistRename ? "Name" : ((field === "q") ? "Query" : "Filters"))));
          wrap.appendChild(sp);
          // extra pills (status etc.)
          if(Array.isArray(it.pills)){
            for(const p of it.pills){
              if(!p) continue;
              const sp2 = document.createElement("span");
              if(typeof p === "string"){
                sp2.className = "ipodPill";
                prepareGlassPill(sp2, p);
              }else{
                const tone = String(p.tone || "");
                sp2.className = "ipodPill" + (tone ? (" " + tone) : "");
                prepareGlassPill(sp2, String(p.text || ""));
              }
              wrap.appendChild(sp2);
            }
          }
          li.appendChild(wrap);
        }

        appendExpandedSubRow(li, it);

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

        itemsLayer.appendChild(li);
        continue;
      }

      const labelWrap = document.createElement("span");
      labelWrap.className = "ipodLabelWrap";
      const labelSpan = document.createElement("span");
      labelSpan.className = "ipodLabel hScrollText";
      if(it && it.label_html){
        labelSpan.innerHTML = String(it.label_html || "");
        syncGlassText(labelSpan);
      }else if(it && it.kind === "album") {
        let rendered = false;
        try{
          const raw = (typeof it.value === "string") ? JSON.parse(it.value) : (it.value || {});
          const artist = String((raw && raw.artist) || "").trim();
          const album = String((raw && raw.album) || "").trim();
          if(artist && album){
            labelSpan.innerHTML = escapeHtml(album) + '   ' + '<span class="artistStrong">' + escapeHtml(artist) + '</span>';
            syncGlassText(labelSpan);
            rendered = true;
          }
        }catch(e){}
        if(!rendered) setGlassText(labelSpan, it.label || "");
      }else{
        setGlassText(labelSpan, it.label || "");
      }
      labelWrap.appendChild(labelSpan);
      if(isSel) labelSpan.setAttribute("data-selected-row-text", "");
      if(it && it.sub_label){
        const sub = document.createElement("span");
        sub.className = "ipodSubLabel hScrollText";
        setGlassText(sub, String(it.sub_label || ""));
        if(isSel) sub.setAttribute("data-selected-row-text", "");
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

      try{
        if(typeof rangeEditorDisplayForIndex === "function"){
          const editorPill = rangeEditorDisplayForIndex(i);
          if(editorPill){
            const replacement = {
              text: editorPill.text,
              tone: editorPill.armed ? "ok" : "",
              bar: null,
              _rangeEditor: true,
              _keyboardOpen: editorPill.keyboardOpen
            };
            if(pills.length) pills[0] = replacement;
            else pills.push(replacement);
          }
        }
      }catch(e){}

      if(pills.length){
        const wrap = document.createElement("span");
        wrap.className = "ipodPills";
        for(const p of pills){
          const sp = document.createElement("span");
          const toneCls = p.tone ? (" " + p.tone) : "";
          if(p._rangeEditor && p._keyboardOpen){
            sp.className = "ipodPill rangeValueEditing" + toneCls;
            sp.setAttribute("data-liquid-row-pill", "");
            const inp = document.createElement("input");
            inp.type = "text";
            inp.inputMode = "decimal";
            inp.className = "libInlineInput";
            inp.value = String(p.text || "");
            let committed = false;
            const syncValue = ()=>{
              try{
                const editor = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
                if(editor) editor.rangeValue = Number(inp.value);
              }catch(e){}
            };
            const commit = ()=>{
              if(committed) return;
              committed = true;
              syncValue();
              try{
                const result = applyRangeEditor();
                if(result && typeof result.catch === "function") result.catch(()=>{});
              }catch(e){}
            };
            inp.addEventListener("input", syncValue);
            inp.addEventListener("click", (ev)=>{ ev.stopPropagation(); });
            inp.addEventListener("pointerdown", (ev)=>{ ev.stopPropagation(); });
            inp.addEventListener("keydown", (ev)=>{
              if(ev.key === "Enter"){
                ev.preventDefault();
                commit();
              }else if(ev.key === "Escape"){
                ev.preventDefault();
                try{ cancelRangeEditor(); }catch(e){}
              }
            });
            inp.addEventListener("blur", commit);
            sp.appendChild(inp);
            editInputToFocus = inp;
          }else if(p.bar != null && isFinite(Number(p.bar))){
            sp.className = "ipodPill bar" + toneCls;
            sp.classList.add("liquidGlass");
            sp.setAttribute("data-liquid-row-pill", "");
            const fill = document.createElement("span");
            fill.className = "pillBarFill";
            fill.style.width = (Math.max(0, Math.min(1, Number(p.bar))) * 100).toFixed(1) + "%";
            const txt = makeGlassPillText(p.text || "", "pillBarText");
            if(isSel) txt.setAttribute("data-selected-row-pill-text", "");
            sp.appendChild(fill);
            sp.appendChild(txt);
          }else{
            sp.className = "ipodPill" + toneCls;
            prepareGlassPill(sp, p.text || "");
            if(isSel){
              const txt = sp.querySelector(".ipodPillText");
              if(txt) txt.setAttribute("data-selected-row-pill-text", "");
            }
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

      if(it.loading && !it.expanded){
        labelWrap.appendChild(makeInlineLoader(it.label || "Loading"));
      }
      appendExpandedSubRow(li, it);

      li.addEventListener("click", ()=>{
        setSelectionFast(i);
        try{
          if(typeof rangeEditorOwnsIndex === "function" && rangeEditorOwnsIndex(i)){
            const editor = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
            if(editor && editor.rangeWheelArmed) openRangeEditorKeyboard();
            else armRangeEditorWheel();
            return;
          }
        }catch(e){}
        try{
          const p = selectItem(it);
          if(p && typeof p.catch === "function"){ p.catch(()=>{}); }
        }catch(e){}
      });
      itemsLayer.appendChild(li);
    }
    appendVirtualSpacer(itemsLayer, virtual.bottom, "bottom");
    if(state.items.length === 0){
      const li = document.createElement("li");
      li.className = "ipodItem info";
      const emptyText = document.createElement("span");
      emptyText.className = "ipodLabel hScrollText";
      setGlassText(emptyText, "Empty");
      li.appendChild(emptyText);
      itemsLayer.appendChild(li);
    }
    appendListEndSpacer(itemsLayer);
    if(libList.replaceChildren) libList.replaceChildren(itemsLayer);
    else {
      libList.innerHTML = "";
      libList.appendChild(itemsLayer);
    }
    measureRenderedRowHeights();
    syncVirtualSpacerHeights(virtual);
    if(libList){
      libList._dpLastVirtualWindow = {
        start: Number(virtual.start || 0),
        end: Number(virtual.end || 0),
        top: Number(virtual.top || 0),
        bottom: Number(virtual.bottom || 0),
        height: Number(virtual.height || 0),
        visible: Number(virtual.visible || 0)
      };
    }

    // restore scroll position first, then ensure selection is visible without jumping to top
    try{
      if(libList) libList.scrollTop = prevScroll;
    }catch(e){}
    if(renderOptions.virtualScroll && libList){
      const wantedScroll = prevScroll;
      requestAnimationFrame(()=>{
        try{
          if(!libList || !libList._dpVirtualized) return;
          if(Math.abs((libList.scrollTop || 0) - wantedScroll) > 1){
            libList.scrollTop = wantedScroll;
            scheduleVirtualListRender("scroll restore");
          }
        }catch(e){}
      });
    }
    const selEl = libList.querySelector(".ipodItem.sel");
    if(selEl && !renderOptions.virtualScroll){
      ensureLibItemVisible(selEl);
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
    try{
      if(typeof refreshLibPillGlassLenses === "function") refreshLibPillGlassLenses("list render");
    }catch(e){}
    try{
      if(typeof invalidateLibPillGlass === "function") invalidateLibPillGlass("list render settled");
    }catch(e){}
    try{
      if(typeof updateGlassTextUnderColors === "function") updateGlassTextUnderColors();
    }catch(e){}
    try{
      document.documentElement.style.setProperty("--dp-visible-row-count", String(virtual.visible || 0));
      document.documentElement.style.setProperty("--dp-total-row-count", String(virtual.total || 0));
    }catch(e){}
    }finally{
      if(libList){
        libList._dpRenderGuardFrame = requestAnimationFrame(finishRenderingList);
      }
    }
  }

  function scheduleVirtualListRender(reason){
    try{
      if(!libList || !libList._dpVirtualized) return;
      if(libList._dpRenderingList){
        libList._dpVirtualScrollPending = true;
        return;
      }
      if(libList._dpVirtualFrame) cancelAnimationFrame(libList._dpVirtualFrame);
      libList._dpVirtualFrame = requestAnimationFrame(()=>{
        libList._dpVirtualFrame = 0;
        if(!libList || !libList._dpVirtualized) return;
        if(libList._dpRenderingList){
          libList._dpVirtualScrollPending = true;
          return;
        }
        try{ renderList({virtualScroll:true, reason:reason || "virtual scroll"}); }catch(e){}
        try{ if(typeof reconcileLibPillGlassTargets === "function") reconcileLibPillGlassTargets(reason || "virtual scroll render"); }catch(e){}
        try{ if(typeof scheduleLiquidGlassRender === "function") scheduleLiquidGlassRender(); }catch(e){}
      });
    }catch(e){}
  }

  try{
    if(libList && !libList._dpLiquidPillScrollBound){
      libList._dpLiquidPillScrollBound = true;
      libList.addEventListener("scroll", ()=>{
        try{
          const renderer = (typeof liquidGlassRendererByKey === "function") ? liquidGlassRendererByKey("libPills") : null;
          if(renderer) renderer._metricsDirty = true;
          if(libList._dpVirtualized){
            scheduleVirtualListRender("virtual scroll render");
            if(libList._dpLiquidPillScrollTimer) clearTimeout(libList._dpLiquidPillScrollTimer);
            libList._dpLiquidPillScrollTimer = setTimeout(()=>{
              libList._dpLiquidPillScrollTimer = 0;
              try{ if(typeof reconcileLibPillGlassTargets === "function") reconcileLibPillGlassTargets("list scroll settled"); }catch(e){}
            }, 90);
            return;
          }
          if(typeof invalidateLibPillGlass === "function") invalidateLibPillGlass("list scroll");
          if(libList._dpLiquidPillScrollTimer) clearTimeout(libList._dpLiquidPillScrollTimer);
          libList._dpLiquidPillScrollTimer = setTimeout(()=>{
            libList._dpLiquidPillScrollTimer = 0;
            try{ if(typeof reconcileLibPillGlassTargets === "function") reconcileLibPillGlassTargets("list scroll settled"); }catch(e){}
          }, 90);
          if(typeof scheduleLiquidGlassRender === "function") scheduleLiquidGlassRender();
        }catch(e){}
      }, {passive:true});
    }
  }catch(e){}

function vibeTick(){
  try{
    if(navigator && typeof navigator.vibrate === "function"){
      navigator.vibrate(8);
    }
  }catch(e){}
}

// ===== library actions (reindex, last.fm auth, forced fullscreen) =====
  var forceFullscreen = false;

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
      const oldEl = libList.querySelector('.ipodItem[data-index="' + prev + '"]');
      const newEl = libList.querySelector('.ipodItem[data-index="' + state.sel + '"]');
      if(oldEl) syncSelectedRowMarkers(oldEl, false);
      if(newEl){
        syncSelectedRowMarkers(newEl, true);
        if(typeof updateLibSelectionGlass === "function") updateLibSelectionGlass("selection target");
        requestAnimationFrame(()=>{ try{ updateLibSelectionGlass("selection target settled"); }catch(e){} });
        ensureLibItemVisible(newEl);
      }else if(libList._dpVirtualized){
        libList.scrollTop = Math.max(0, virtualOffsetForIndex(state.sel) - Math.max(32, (libList.clientHeight || 320) * 0.35));
        renderList();
        return;
      }
      refreshSelectedHScrollText();
      if(typeof reconcileLibPillGlassTargets === "function") reconcileLibPillGlassTargets("selection");
      if(typeof applySelectedTextContrast === "function") applySelectedTextContrast();
      if(typeof updateGlassTextUnderColors === "function") updateGlassTextUnderColors();
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
    try{ if(typeof applySelectedTextContrast === "function") applySelectedTextContrast(); }catch(e){}

    if(restoreScroll != null && libList){
      const top = Math.max(0, restoreScroll);
      requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
    }
    try{
      if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.saveRenderedViewSnapshot){
        DebriPod.clientSync.saveRenderedViewSnapshot(arr);
      }
    }catch(e){}
  }

  function snapshotListState(){
    try{
      if(state.current){
        state.current.savedSel = state.sel;
        if(libList) state.current.savedScroll = libList.scrollTop;
      }
    }catch(e){}
  }

  async function runLibraryPageTransition(loadFn){
    let fadeTimer = 0;
    let faded = false;
    try{
      try{ if(typeof hideTransientListGlass === "function") hideTransientListGlass("page transition"); }catch(e){}
      if(libList){
        fadeTimer = setTimeout(()=>{
          faded = true;
          try{ libList.classList.add("pageFadeHidden"); }catch(e){}
        }, 80);
      }
      await loadFn();
      if(fadeTimer) clearTimeout(fadeTimer);
      if(libList){
        if(faded){
          requestAnimationFrame(()=>{
            requestAnimationFrame(()=>{
              try{ libList.classList.remove("pageFadeHidden"); }catch(e){}
            });
          });
        }else{
          try{ libList.classList.remove("pageFadeHidden"); }catch(e){}
        }
      }
    }catch(e){
      if(fadeTimer) clearTimeout(fadeTimer);
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
      try{
        await view.load();
      }catch(loadErr){
        let restored = false;
        try{
          if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.restoreCachedView){
            restored = await DebriPod.clientSync.restoreCachedView(view);
          }
        }catch(e){ restored = false; }
        if(!restored) throw loadErr;
      }
      setHeader();
      try{
        if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.saveCurrentViewState){
          DebriPod.clientSync.saveCurrentViewState();
        }
      }catch(e){}
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

  try{
    DebriPod.listDiagnostics = {
      rows: function(){
        const virtual = listVirtualWindow();
        return {
          visible:Number(virtual.visible || 0),
          total:Number(virtual.total || (state && state.items ? state.items.length : 0) || 0),
          start:Number(virtual.start || 0),
          end:Number(virtual.end || 0),
          top:Number(virtual.top || 0),
          bottom:Number(virtual.bottom || 0),
          virtualized:!!virtual.enabled,
          virtualHeight:Number(virtual.height || (libList ? libList.scrollHeight : 0) || 0),
          scrollTop:Number((libList && libList.scrollTop) || 0),
          scrollHeight:Number((libList && libList.scrollHeight) || 0),
          rendering:!!(libList && libList._dpRenderingList)
        };
      }
    };
  }catch(e){}
