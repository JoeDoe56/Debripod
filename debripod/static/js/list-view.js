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
    prefixSignature: "",
    prefixItemsVersion: -1,
    prefixRowHeightRevision: -1,
    prefixCount: -1
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
        item.row_layout_key || (item.sub_row ? "sub-row" : ""),
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

  function virtualPrefixHeights(){
    const count = state && Array.isArray(state.items) ? state.items.length : 0;
    const metrics = rowViewMetrics();
    const itemsVersion = Number(state.itemsVersion || 0);
    const heightRevision = Number(state.rowHeightRevision || 0);
    if(metrics.prefix && metrics.prefixItemsVersion === itemsVersion && metrics.prefixRowHeightRevision === heightRevision && metrics.prefixCount === count && metrics.prefix.length === count + 1){
      return metrics.prefix;
    }
    const prefix = new Array(count + 1);
    prefix[0] = 0;
    for(let i = 0; i < count; i++){
      prefix[i + 1] = prefix[i] + Math.max(1, virtualHeightForIndex(i));
    }
    metrics.prefix = prefix;
    metrics.prefixItemsVersion = itemsVersion;
    metrics.prefixRowHeightRevision = heightRevision;
    metrics.prefixCount = count;
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
      let heightsChanged = false;
      libList.querySelectorAll(".ipodItem[data-index]").forEach((row)=>{
        const idx = Number(row.dataset.index);
        if(!Number.isFinite(idx) || !state.items[idx]) return;
        const fixedKind = String(state.items[idx].kind || "");
        if(fixedKind === "libsearch_result" || fixedKind === "libsearch_file" || fixedKind === "libsearch_status" || fixedKind === "libsearch_filter") return;
        const h = row.getBoundingClientRect ? row.getBoundingClientRect().height : row.offsetHeight;
        if(h > 0){
          const safeH = Math.max(24, h);
          const item = state.items[idx];
          const key = virtualMetricKey(idx, item);
          dpRowHeightCache.set(rowHeightCacheKey(idx, item), safeH);
          if(Math.abs((metrics.byKey.get(key) || 0)-safeH)>.1)heightsChanged=true;
          metrics.byKey.set(key, safeH);
          metrics.byIndexType.set(String(idx) + "|" + virtualRowType(item), safeH);
          total += safeH;
          count += 1;
        }
      });
      if(count){
        metrics.fallback = Math.max(metrics.fallback || 0, Math.ceil(total / count));
        if(heightsChanged){state.rowHeightRevision = Number(state.rowHeightRevision || 0) + 1;
        invalidateVirtualPrefix();}
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
      libList._dpScrollAnimTarget = target;
      if(Math.abs((libList.scrollTop || 0) - target) < 0.5){
        if(libList._dpScrollAnimFrame){
          cancelAnimationFrame(libList._dpScrollAnimFrame);
          libList._dpScrollAnimFrame = 0;
        }
        libList.scrollTop = target;
        libList._dpScrollAnimTarget = null;
        if(typeof invalidateLibPillGlass === "function") invalidateLibPillGlass("scroll correction");
        return;
      }
      let lastTick = 0;
      const tick = (now)=>{
        try{
          const frameNow = Number(now || performance.now());
          const interval = (typeof animationFrameIntervalMs === "function") ? animationFrameIntervalMs("libraryList") : (1000 / 60);
          if(lastTick && frameNow - lastTick < interval - 1){
            libList._dpScrollAnimFrame = requestAnimationFrame(tick);
            return;
          }
          const elapsed = lastTick ? Math.max(1, frameNow - lastTick) : interval;
          lastTick = frameNow;
          const current = Number(libList.scrollTop || 0);
          if(libList._dpScrollAnimTarget == null){
            libList._dpScrollAnimFrame = 0;
            return;
          }
          const desired = Number(libList._dpScrollAnimTarget);
          if(!Number.isFinite(desired)){
            libList._dpScrollAnimTarget = null;
            libList._dpScrollAnimFrame = 0;
            return;
          }
          const mix = 1 - Math.exp(-elapsed / 78);
          const next = current + ((desired - current) * mix);
          libList.scrollTop = Math.abs(desired - next) < 0.35 ? desired : next;
          if(typeof invalidateLibPillGlass === "function") invalidateLibPillGlass("smooth scroll");
          if(Math.abs(desired - libList.scrollTop) > 0.35) libList._dpScrollAnimFrame = requestAnimationFrame(tick);
          else{
            libList._dpScrollAnimTarget = null;
            libList._dpScrollAnimFrame = 0;
          }
        }catch(e){
          libList._dpScrollAnimFrame = 0;
        }
      };
      if(libList._dpScrollAnimFrame) return;
      libList._dpScrollAnimFrame = requestAnimationFrame(tick);
    }catch(e){}
  }

  function estimatedItemHeight(item){
    // One standard row estimate; the multiline rule editor is a dedicated
    // input surface rather than a navigation row.
    return item && item.kind === "smart_playlist_rules_text" ? 236 : 55;
  }

  function replaceListItems(nextItems, options){
    const opts = Object.assign({preserveSelection:true, preserveScroll:true, reason:"list update"}, options || {});
    const previous = Array.isArray(state.items) ? state.items : [];
    const next = Array.isArray(nextItems) ? nextItems.slice() : [];
    let changedRows = Math.abs(previous.length - next.length);
    for(let ci=0;ci<Math.min(previous.length,next.length) && changedRows<=100;ci++) if(virtualItemIdentity(previous[ci],ci)!==virtualItemIdentity(next[ci],ci)) changedRows++;
    const oldScroll = libList ? libList.scrollTop : 0;
    const selectedIdentity = Object.prototype.hasOwnProperty.call(opts, "transitionSelectionIdentity")
      ? String(opts.transitionSelectionIdentity || "")
      : (previous[state.sel] ? virtualItemIdentity(previous[state.sel], state.sel) : "");
    const transitionApi = window.DebriPod && DebriPod.rowTransitions;
    const reducedMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    const plan = transitionApi ? transitionApi.planRowMutation(previous, next, virtualItemIdentity, selectedIdentity, {reducedMotion:reducedMotion}) : null;
    state.items = next;
    state.itemsVersion = Number(state.itemsVersion || 0) + 1;
    if(opts.preserveSelection && plan && plan.selectionIndex >= 0) state.sel = plan.selectionIndex;
    else if(typeof opts.selectionIndex === "number") state.sel = Math.max(0, Math.min(Math.max(0, next.length - 1), opts.selectionIndex));
    else state.sel = Math.max(0, Math.min(Math.max(0, next.length - 1), state.sel || 0));
    invalidateVirtualPrefix();
    renderList({rowMutation:true, preserveEntryAnchor:!!opts.preserveEntryAnchor});
    if(opts.preserveScroll && libList) libList.scrollTop = oldScroll;
    invalidateVirtualPrefix();
    return plan;
  }

  let nowPlayingListSnapshot = null;

  function suspendListRenderingForNowPlaying(){
    if(!libList || nowPlayingListSnapshot) return;
    const selected = state.items[state.sel];
    nowPlayingListSnapshot = {
      selectedIdentity:selected ? virtualItemIdentity(selected, state.sel) : "",
      selectionIndex:state.sel,
      scrollTop:libList.scrollTop,
      descriptor:virtualViewDescriptor(),
      virtualWindow:libList._dpLastVirtualWindow || null
    };
    if(libList.replaceChildren) libList.replaceChildren();
    else libList.innerHTML = "";
    libList.inert = true;
    libList.setAttribute("aria-hidden", "true");
    try{ if(typeof hideTransientListGlass === "function") hideTransientListGlass("list suspended"); }catch(e){}
    try{ if(typeof destroyLibSelectionGlass === "function") destroyLibSelectionGlass("list suspended"); }catch(e){}
    try{ if(typeof invalidateLibPillGlass === "function") invalidateLibPillGlass("list suspended"); }catch(e){}
  }

  function restoreListRenderingAfterNowPlaying(){
    if(!libList || !nowPlayingListSnapshot) return;
    const snapshot = nowPlayingListSnapshot;
    nowPlayingListSnapshot = null;
    libList.inert = false;
    libList.removeAttribute("aria-hidden");
    const found = state.items.findIndex((item, index)=>virtualItemIdentity(item, index) === snapshot.selectedIdentity);
    state.sel = found >= 0 ? found : Math.max(0, Math.min(Math.max(0, state.items.length - 1), snapshot.selectionIndex));
    libList.scrollTop = snapshot.scrollTop;
    renderList({virtualScroll:true, restoringNowPlaying:true});
    libList.scrollTop = snapshot.scrollTop;
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

    function nonVirtualInfoView(kind){
      const transitionApi = window.DebriPod && DebriPod.rowTransitions;
      if(transitionApi && typeof transitionApi.isNonVirtualInfoView === "function"){
        return transitionApi.isNonVirtualInfoView(kind);
      }
      const value = String(kind || "");
    return value === "roots" || value === "libinfo" || value === "media_information" || value === "youtube_comments" ||
      value === "settings" || value === "performance" || value.indexOf("settings") === 0 || value.indexOf("setup") === 0 ||
      value.indexOf("account") === 0 || value.indexOf("libinfo") === 0 || value.indexOf("libui") === 0 ||
      value.indexOf("libadvanced") === 0 || value.indexOf("libbinds") === 0 || value.indexOf("libdatabase") === 0 ||
      value.indexOf("ui_settings") === 0 || value.indexOf("range_editor") === 0;
  }

  function canVirtualizeList(){
    try{
      if(!libList || !state || !Array.isArray(state.items)) return false;
      const cur = state.current || {};
      const kind = String(cur.kind || "");
      if(!state.items.length || !kind || nonVirtualInfoView(kind)) return false;
      // Library subpages are virtual by default. Form/info pages above opt
      // out, while the row-content guard below keeps live controls safe.
      const active = document.activeElement;
      if(active && libList.contains(active) && /^(INPUT|TEXTAREA|SELECT|BUTTON)$/i.test(active.tagName || "")) return false;
      return !state.items.some((item)=> item && (
        item.settingRow ||
        item.kind === "range_editor_input" ||
        item.kind === "range_editor_slider" ||
        item.kind === "smart_playlist_rules_text" ||
        item.kind === "playlist_edit_name" ||
        item.kind === "setting_value" ||
        item.kind === "settings_library_folder" ||
        item.kind === "settings_library_remove"
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
    const anchorOffset = Math.max(0, Number(state.pageAnchorOffset || 0));
    const viewportTop = Math.max(0, (libList.scrollTop || 0) - anchorOffset);
    const viewportBottom = Math.max(viewportTop + 1, (libList.scrollTop || 0) + Math.max(1, libList.clientHeight || 1) - anchorOffset);
    const firstVisible = Math.max(0, virtualLowerBound(prefix, viewportTop) - 1);
    const lastVisible = Math.min(count, virtualLowerBound(prefix, viewportBottom) + 1);
      const metrics = rowViewMetrics();
      const rowHeight = Math.max(1, Number(metrics.fallback || 56));
      const viewportRows = Math.max(1, Math.ceil(Math.max(1, libList.clientHeight || 1) / rowHeight));
      const velocity = Math.abs(Number(libList._dpScrollVelocity || 0));
      const transitionApi = window.DebriPod && DebriPod.rowTransitions;
      const overscan = transitionApi && typeof transitionApi.adaptiveOverscanRows === "function"
        ? transitionApi.adaptiveOverscanRows(libList.clientHeight || 1, rowHeight, velocity)
        : Math.min(16, Math.min(4, Math.max(2, Math.ceil(viewportRows * 0.25))) + Math.min(12, Math.ceil((velocity * 100) / rowHeight)));
    const start = Math.max(0, firstVisible - overscan);
    const end = Math.max(start, Math.min(count, lastVisible + overscan));
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

  function appendPageAnchorSpacer(layer){
    const height = Math.max(0, Number(state.pageAnchorOffset || 0));
    if(!(height > 0)) return;
    const spacer = document.createElement("li");
    spacer.className = "ipodPageAnchorSpacer";
    spacer.setAttribute("aria-hidden", "true");
    spacer.style.height = height.toFixed(1) + "px";
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
      const extra = Math.max(0, Number(state.pageAnchorBottomSlack || 0));
      if(extra > 0){
        const rootStyle = window.getComputedStyle ? window.getComputedStyle(document.documentElement) : null;
        const edgeRoom = rootStyle ? (parseFloat(rootStyle.getPropertyValue("--dp-selected-pill-edge-room")) || 44) : 44;
        spacer.style.height = (edgeRoom + 56 + extra).toFixed(1) + "px";
      }
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
      return Math.max(0, Number(state.pageAnchorOffset || 0)) + (prefix[n] || 0);
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
    if(libList) libList.classList.toggle("dpLibraryRoot", !!(state.current && state.current.kind === "roots"));
    const itemsLayer = document.createDocumentFragment();
    const virtual = listVirtualWindow();
    if(libList) libList._dpVirtualized = !!virtual.enabled;
    appendPageAnchorSpacer(itemsLayer);
    appendVirtualSpacer(itemsLayer, virtual.top, "top");
    for(let i=virtual.start;i<virtual.end;i++){
      const it = state.items[i];
      const li = document.createElement("li");
      li.dataset.index = String(i);
      li.dataset.liquidKey = virtualItemIdentity(it, i);
      li.dataset.kind = String((it && it.kind) || "");
      if(it && it.row_layout_key) li.dataset.rowLayoutKey = String(it.row_layout_key);

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
                const parsed = Number(inp.value);
                if(Number.isFinite(parsed)){
                  const meta = editor.rangeMeta || settingRangeMeta("", 0, 1);
                  const next = rangeEditorClamp(parsed, meta, Number(editor.rangeValue || 0));
                  editor.rangeValue = next;
                  const config = editor.rangeConfig || {};
                  if(typeof config.onPreview === "function") Promise.resolve(config.onPreview(next)).catch(()=>{});
                  if(typeof syncRangeFeedback === "function") syncRangeFeedback(editor);
                  const ring = li.querySelector(".uiRing");
                  if(ring && DebriPod.uiPrimitives) DebriPod.uiPrimitives.setRing(ring, next, meta.min, meta.max);
                  if(DebriPod.rowSystem) DebriPod.rowSystem.updatePanel();
                }
              }
            }catch(e){}
          });
          inp.addEventListener("keydown", (ev)=>{
            if(ev.key === "Enter"){
              ev.preventDefault();
              let valid = false;
              try{
                const editor = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
                const parsed = Number(inp.value);
                if(editor && Number.isFinite(parsed)){
                  const meta = editor.rangeMeta || settingRangeMeta("", 0, 1);
                  editor.rangeValue = rangeEditorClamp(parsed, meta, Number(editor.rangeValue || 0));
                  valid = true;
                }
              }catch(e){}
              if(!valid) return;
              try{
                const result = applyRangeEditor();
                if(result && typeof result.catch === "function") result.catch(()=>{});
              }catch(e){}
            }
          });
          inp.addEventListener("blur", ()=>{
            const editor = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
            if(!editor || editor.committing || editor.cancelling || !editor.rangeKeyboardOpen) return;
            setTimeout(()=>{
              const active = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
              if(active === editor && !editor.committing && !editor.cancelling) cancelRangeEditor();
            }, 0);
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
            try{ rangeEditorCenterPress(); }catch(e){}
          });
        }
        itemsLayer.appendChild(li);
        continue;
      }

      if(it.kind === "setup_text_input" || it.kind === "settings_text_input"){
        li.className += " editing twoLine settingRow";
        const isSettingsEditor = it.kind === "settings_text_input";
        const inp = document.createElement(it.multiline ? "textarea" : "input");
        if(!it.multiline) inp.type = it.secret ? "password" : "text";
        inp.className = "libInlineInput";
        inp.placeholder = it.placeholder || "";
        inp.value = String(it.value == null ? "" : it.value);
        inp.readOnly = !!it.readOnly;
        inp.addEventListener("input", ()=>{
          try{
            if(state.current && (state.current.kind === "setup_editor" || (isSettingsEditor && state.current.kind === "settings_editor"))) state.current.editorValue = inp.value;
          }catch(e){}
        });
        inp.addEventListener("keydown", (ev)=>{
          if(ev.key === "Enter" && !it.multiline){
            ev.preventDefault();
            try{
              if(state.current && (state.current.kind === "setup_editor" || (isSettingsEditor && state.current.kind === "settings_editor"))) state.current.editorValue = inp.value;
              if(isSettingsEditor && typeof commitSettingsEditor === "function") commitSettingsEditor();
              else if(typeof commitSetupEditor === "function") commitSetupEditor();
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
        const placeholder = isPlaylistCreate ? "Create playlist" : (isSmartPlaylistCreate ? "Create smart playlist" : (isPlaylistRename ? "Edit name" : ((it.kind === "libsearch_filter") ? "Enter filters" : "Enter query or link")));
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
          inp.addEventListener("click", ev=>ev.stopPropagation());
          inp.addEventListener("pointerdown", ev=>ev.stopPropagation());
          if(field === "q" && window.DebriPod && DebriPod.linkIntake){
            inp.addEventListener("paste", DebriPod.linkIntake.onPaste);
          }
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
                if(field === "filter" && typeof libUnifiedSearchModel === "function") libUnifiedSearchModel().applyFilters(inp.value || "");
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
                  try{
                    const intake = window.DebriPod && DebriPod.linkIntake;
                    if(intake && intake.classify(inp.value || "") !== "query") intake.inspect(inp.value || "");
                    else libDoSearch((state.libSearch && state.libSearch.engine) ? state.libSearch.engine : "combined", inp.value || "");
                  }catch(e){}
                }else if(typeof libUnifiedSearchModel === "function") libUnifiedSearchModel().applyFilters(inp.value || "");
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
          if(isPlaylistCreate || isSmartPlaylistCreate || isPlaylistRename){
            const sp = document.createElement("span");
            sp.className = "ipodPill";
            prepareGlassPill(sp, isPlaylistCreate ? "New" : (isSmartPlaylistCreate ? "Smart" : "Name"));
            wrap.appendChild(sp);
          }
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
          if(wrap.childNodes.length) li.appendChild(wrap);
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
            setGlassText(labelSpan, album);
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
                const parsed = Number(inp.value);
                if(editor && Number.isFinite(parsed)){
                  const meta = editor.rangeMeta || settingRangeMeta("", 0, 1);
                  const next = rangeEditorClamp(parsed, meta, Number(editor.rangeValue || 0));
                  editor.rangeValue = next;
                  const config = editor.rangeConfig || {};
                  if(typeof config.onPreview === "function") Promise.resolve(config.onPreview(next)).catch(()=>{});
                  if(typeof syncRangeFeedback === "function") syncRangeFeedback(editor);
                  const ring = li.querySelector(".uiRing");
                  if(ring && DebriPod.uiPrimitives) DebriPod.uiPrimitives.setRing(ring, next, meta.min, meta.max);
                  if(DebriPod.rowSystem) DebriPod.rowSystem.updatePanel();
                }
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
            inp.addEventListener("blur", ()=>{
              if(committed) return;
              const editor = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
              if(!editor || editor.committing || editor.cancelling) return;
              setTimeout(()=>{
                const active = state.inlineRangeEditor || ((state.current && state.current.kind === "range_editor") ? state.current : null);
                if(active === editor && !editor.committing && !editor.cancelling){
                  try{ cancelRangeEditor(); }catch(e){}
                }
              }, 0);
            });
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
          if(p.filter_kind){ sp.dataset.filterKind=String(p.filter_kind); sp.dataset.filterValue=String(p.filter_value || p.text || ""); }
          wrap.appendChild(sp);
        }
        li.appendChild(wrap);
      }

      if(it.loading && !it.expanded){
        labelWrap.appendChild(makeInlineLoader(it.label || "Loading"));
      }
      appendExpandedSubRow(li, it);

      if(it.kind === "libsearch_result") li.dataset.searchResultDelegated = "1";
      else li.addEventListener("click", ()=>{
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
    // Normalize every rendered item through the shared row system. The
    // renderer above still owns editing and activation behavior; this pass
    // owns the universal icon/text geometry and contextual panel metadata.
    try{
      if(window.DebriPod && DebriPod.rowSystem && typeof DebriPod.rowSystem.decorateList === "function"){
        DebriPod.rowSystem.decorateList(libList, state);
      }
    }catch(e){}
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
    // The replacement row receives its lens offset before the browser paints.
    if(typeof applyLibSelectionMotion === "function")applyLibSelectionMotion();
    const selEl = libList.querySelector(".ipodItem.sel");
    if(selEl && !renderOptions.virtualScroll && !renderOptions.preserveEntryAnchor){
      ensureLibItemVisible(selEl);
    }
    if(editInputToFocus){
      try{
        editInputToFocus.focus();

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
          const renderer = (typeof liquidGlassRendererByKey === "function") ? liquidGlassRendererByKey("main") : null;
          if(renderer) renderer._metricsDirty = true;
          if(libList._dpVirtualized){
            const now = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
            const top = Number(libList.scrollTop || 0);
            const previousTop = Number(libList._dpLastScrollTop == null ? top : libList._dpLastScrollTop);
            const previousTs = Number(libList._dpLastScrollTs == null ? now : libList._dpLastScrollTs);
            libList._dpScrollVelocity = Math.abs(top - previousTop) / Math.max(1, now - previousTs);
            libList._dpLastScrollTop = top;
            libList._dpLastScrollTs = now;
            if(libList._dpVirtualVelocityTimer) clearTimeout(libList._dpVirtualVelocityTimer);
            libList._dpVirtualVelocityTimer = setTimeout(()=>{
              libList._dpScrollVelocity = 0;
              scheduleVirtualListRender("virtual scroll settled");
            }, 120);
            scheduleVirtualListRender("virtual scroll render");
            if(libList._dpLiquidPillScrollFrame) cancelAnimationFrame(libList._dpLiquidPillScrollFrame);
            libList._dpLiquidPillScrollFrame = requestAnimationFrame(()=>{
              libList._dpLiquidPillScrollFrame = 0;
              try{ if(typeof reconcileLibPillGlassTargets === "function") reconcileLibPillGlassTargets("list scroll frame"); }catch(e){}
            });
            return;
          }
          if(typeof invalidateLibPillGlass === "function") invalidateLibPillGlass("list scroll");
          if(libList._dpLiquidPillScrollFrame) cancelAnimationFrame(libList._dpLiquidPillScrollFrame);
          libList._dpLiquidPillScrollFrame = requestAnimationFrame(()=>{
            libList._dpLiquidPillScrollFrame = 0;
            try{ if(typeof reconcileLibPillGlassTargets === "function") reconcileLibPillGlassTargets("list scroll frame"); }catch(e){}
          });
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
    const pending = state.lastfmLoginAuth || null;
    if(pending && pending.token){
      try{
        const r2 = await fetch("/api/lastfm/auth/finish", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({token: pending.token})
        });
        const j2 = await r2.json();
        if(!j2 || !j2.ok) throw new Error((j2 && j2.error) ? j2.error : "Last.fm auth finish failed");
        state.lastfmLoginAuth = null;
        reportUiStatus("Last.fm login complete.", "ok");
        return true;
      }catch(e){
        reportUiStatus("Last.fm login failed: " + (e && e.message ? e.message : String(e)), "warn");
        return false;
      }
    }

    try{
      const r = await fetch("/api/lastfm/auth/start", {method: "GET"});
      const j = await r.json();
      if(!j || !j.ok){
        throw new Error((j && j.error) ? j.error : "Last.fm auth start failed");
      }
      state.lastfmLoginAuth = {token:j.token, authUrl:j.auth_url};
    }catch(e){
      reportUiStatus("Last.fm login failed: " + (e && e.message ? e.message : String(e)), "warn");
      return false;
    }

    try{
      if(state.lastfmLoginAuth.authUrl){
        window.open(state.lastfmLoginAuth.authUrl, "_blank", "noopener");
      }
    }catch(e){}
    reportUiStatus("Approve DebriPod in the Last.fm tab, then select Finish Last.fm authorization here.", "ok");
    return false;
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


  var selectionRefreshFrame = 0;

  function setSelectionFast(nextIndex){
    if(!state.items.length) return;
    const n = state.items.length;
    const prev = state.sel;
    const selectionApi = window.DebriPod && DebriPod.controlDispatcherApi;
    const delta = Number(nextIndex || 0) - state.sel;
    const next = selectionApi && typeof selectionApi.clampSelectionIndex === "function"
      ? selectionApi.clampSelectionIndex(state.sel, delta, n)
      : Math.max(0, Math.min(n - 1, Number(nextIndex || 0)));
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
        ensureLibItemVisible(newEl);
      }else if(libList._dpVirtualized){
        libList.scrollTop = Math.max(0, virtualOffsetForIndex(state.sel) - Math.max(32, (libList.clientHeight || 320) * 0.35));
        renderList();
        return;
      }
      if(!selectionRefreshFrame) selectionRefreshFrame = requestAnimationFrame(()=>{
        selectionRefreshFrame = 0;
        refreshSelectedHScrollText();
        if(typeof updateLibSelectionGlass === "function") updateLibSelectionGlass("selection target settled");
        if(typeof reconcileLibPillGlassTargets === "function") reconcileLibPillGlassTargets("selection");
        if(typeof updateGlassTextUnderColors === "function") updateGlassTextUnderColors();
      });
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
    if(k === "info" || k === "up" || k === "random" || k === "liked_category" || k === "playlist_create" || k === "smart_playlist_create" || k === "playlist_edit_entry") return false;
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
    // A previous page's scroll target must never move the newly anchored list.
    if(libList){
      if(libList._dpScrollAnimFrame) cancelAnimationFrame(libList._dpScrollAnimFrame);
      libList._dpScrollAnimFrame = 0;
      libList._dpScrollAnimTarget = null;
    }
    try{ if(typeof window.cancelSelectionStepQueue === "function") window.cancelSelectionStepQueue(); }catch(e){}
    // Capture the pill that is actually visible before changing selection or
    // replacing the list. A destination view can carry an older saved anchor
    // from when it was entered, while the live glass may have settled lower.
    const liveAnchorY = selectedRowViewportY();
    // Random is synthetic; never let a refresh feed an old control row back
    // into the logical dataset and inject another one.
    const arr = (Array.isArray(items) ? items : []).filter((item)=>!(item && item.kind === "random"));
    const oldSelectedItem = state.items && state.items[state.sel];
    const transitionSelectionIdentity = oldSelectedItem ? virtualItemIdentity(oldSelectedItem, state.sel) : "";
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
    // Restore selection and scroll when returning to a list via Menu/back
    let restoreSel = null;
    let restoreScroll = null;
    let restoreAnchorY = null;
    try{
      if(state.current && typeof state.current.savedSel === "number" && isFinite(state.current.savedSel)){
        restoreSel = Number(state.current.savedSel);
      }
      if(state.current && typeof state.current.savedScroll === "number" && isFinite(state.current.savedScroll)){
        restoreScroll = Number(state.current.savedScroll);
      }
      if(state.current && typeof state.current.savedAnchorY === "number" && isFinite(state.current.savedAnchorY)){
        restoreAnchorY = Number(state.current.savedAnchorY);
      }
    }catch(e){ restoreSel = null; restoreScroll = null; restoreAnchorY = null; }

    if(restoreSel != null){
      const max = Math.max(0, arr.length - 1);
      state.sel = Math.max(0, Math.min(max, restoreSel));
    }else{
      state.sel = 0;
    }

    let preserveEntryAnchor = false;
    let requestedAnchorY = null;
    state.pageAnchorOffset = 0;
    state.pageAnchorBottomSlack = 0;
    if(libList){
      libList.classList.toggle("dpLibraryRoot", !!(state.current && state.current.kind === "roots"));
      requestedAnchorY = resolveListAnchorY(
        liveAnchorY,
        restoreAnchorY,
        state.current && state.current.entryAnchorY,
      );
      if(Number.isFinite(requestedAnchorY)){
        const style = window.getComputedStyle ? window.getComputedStyle(libList) : null;
        const paddingTop = style ? (parseFloat(style.paddingTop || "0") || 0) : 0;
        // Include the restored selection's natural prefix in the spacer so
        // back navigation can keep a selected row at the live glass position,
        // even when that row is not the first item in a short destination.
        let selectedPrefix = 0;
        for(let i = 0; i < Math.max(0, state.sel); i++) selectedPrefix += estimatedItemHeight(arr[i]);
        state.pageAnchorOffset = Math.max(0, requestedAnchorY - paddingTop - selectedPrefix);
        state.pageAnchorBottomSlack = Math.max(0, paddingTop + selectedPrefix - requestedAnchorY) + 48;
        // Keep the selected row at the same viewport coordinate for every
        // destination size. The spacer is laid out before the new rows, so
        // the replacement does not need a visual row transition.
        preserveEntryAnchor = true;
      }
      libList.scrollTop = 0;
    }
    replaceListItems(arr, {preserveSelection:false, preserveScroll:false, preserveEntryAnchor:preserveEntryAnchor, selectionIndex:state.sel, transitionSelectionIdentity:transitionSelectionIdentity, reason:"page load"});
    setHeader();
    if(Number.isFinite(requestedAnchorY) && libList){
      // Correct the estimated prefix against the actual rendered row before
      // the browser gets a chance to paint. This keeps the selected pill
      // stationary without a deferred scroll jump.
      try{
        const row = libList.querySelector(".ipodItem.sel");
        const listRect = libList.getBoundingClientRect();
        if(row && listRect){
          const actualY = row.getBoundingClientRect().top - listRect.top;
          if(Number.isFinite(actualY)) libList.scrollTop = Math.max(0, (libList.scrollTop || 0) + actualY - requestedAnchorY);
        }
      }catch(e){}
    }else if(restoreScroll != null && libList){
      const top = Math.max(0, restoreScroll);
      try{ libList.scrollTop = top; }catch(e){}
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
        if(libList){
          state.current.savedScroll = libList.scrollTop;
          state.current.savedAnchorY = selectedRowViewportY();
        }
      }
    }catch(e){}
  }

  function resolveListAnchorY(liveAnchorY, savedAnchorY, entryAnchorY){
    for(const value of [liveAnchorY, savedAnchorY, entryAnchorY]){
      if(value == null || value === "") continue;
      const number = Number(value);
      if(Number.isFinite(number)) return number;
    }
    return null;
  }

  // The glass lens has its own spring while it catches up with the selected
  // row.  The caller (liquid-glue) can pass the lens's current and target Y
  // values so the selected row's foreground follows that same spring without
  // moving the row's layout or its neighbouring rows.
  function setSelectedRowContentOffset(currentY, targetY){
    try{
      const selected = libList && libList.querySelector ? libList.querySelector(".ipodItem.sel") : null;
      const previous = libList && libList._dpSelectedContentRow;
      if(previous && previous !== selected) previous.style.removeProperty("--dp-selected-content-offset-y");
      if(!selected){
        if(libList) libList._dpSelectedContentRow = null;
        return 0;
      }
      const current = Number(currentY);
      let target = Number(targetY);
      const host = typeof document !== "undefined" ? document.getElementById("ipodScreen") : null;
      if(host && selected.getBoundingClientRect)target=selected.getBoundingClientRect().top-host.getBoundingClientRect().top;
      const offset = Number.isFinite(current) && Number.isFinite(target) ? current - target : 0;
      const value = offset.toFixed(3) + "px";
      if(selected.style.getPropertyValue("--dp-selected-content-offset-y") !== value){
        selected.style.setProperty("--dp-selected-content-offset-y", value);
      }
      libList._dpSelectedContentRow = selected;
      return offset;
    }catch(e){
      return 0;
    }
  }
  try{ window.setSelectedRowContentOffset = setSelectedRowContentOffset; }catch(e){}

  function selectedRowViewportY(){
    try{
      if(!libList) return null;
      const listRect = libList.getBoundingClientRect();
      const glass = document.getElementById("libListSelectedGlass");
      if(glass && glass.classList && glass.classList.contains("isVisible")){
        const glassRect = glass.getBoundingClientRect();
        if(glassRect && glassRect.height > 0){
          const glassY = glassRect.top - listRect.top;
          if(Number.isFinite(glassY)) return Math.max(0, glassY);
        }
      }
      const row = libList.querySelector(".ipodItem.sel");
      if(!row) return null;
      const rowRect = row.getBoundingClientRect();
      const y = rowRect.top - listRect.top;
      return Number.isFinite(y) ? Math.max(0, y) : null;
    }catch(e){
      return null;
    }
  }

  async function setView(view, push){
    if(push && state.current){
      const entryAnchorY = selectedRowViewportY();
      if(entryAnchorY != null) view.entryAnchorY = entryAnchorY;
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
    if(libList && !libList._dpUnifiedSearchDelegated){
      libList._dpUnifiedSearchDelegated = true;
      libList.addEventListener("click", function(event){
        const pill = event.target && event.target.closest ? event.target.closest(".ipodPill[data-filter-kind]") : null;
        if(pill && libList.contains(pill)){
          event.preventDefault();
          event.stopPropagation();
          if(typeof libUnifiedSearchModel === "function"){
            libUnifiedSearchModel().toggleFilter(String(pill.dataset.filterKind || ""), String(pill.dataset.filterValue || ""));
          }
          return;
        }
        const row = event.target && event.target.closest ? event.target.closest(".ipodItem[data-search-result-delegated]") : null;
        if(!row || !libList.contains(row)) return;
        const index = Number(row.dataset.index);
        if(!Number.isFinite(index) || !state.items[index]) return;
        state.sel = index;
        renderList({pointerSelection:true});
            if(typeof selectItem === "function") Promise.resolve(selectItem(state.items[index])).catch(function(error){ reportUiStatus(String(error && error.message ? error.message : error), "warn"); });
      });
    }
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
