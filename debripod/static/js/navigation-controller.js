/*
 * Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818
 * Owns the finite special-page stack and canonical ordinary-view snapshots.
 */
(function(globalScope, factory){
  const api = factory(globalScope && globalScope.document ? globalScope : null);
  if(typeof module === "object" && module.exports) module.exports = api;
  if(globalScope && globalScope.document){
    const root = globalScope.DebriPod = globalScope.DebriPod || {};
    root.navigationController = api.createBrowserNavigationController(globalScope);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function(browserWindow){
  "use strict";

  const SPECIAL_KINDS = new Set([
    "now_playing",
    "queue",
    "history",
    "context_menu",
    "media_information",
    "youtube_comments",
    "playlist_picker",
  ]);

  function cloneValue(value){
    if(value == null) return value;
    try{
      if(typeof structuredClone === "function") return structuredClone(value);
    }catch(_error){}
    try{
      return JSON.parse(JSON.stringify(value));
    }catch(_error){
      return value;
    }
  }

  function immutableClone(value){
    const result = cloneValue(value);
    try{
      if(result && typeof result === "object") Object.freeze(result);
    }catch(_error){}
    return result;
  }

  // Ordinary view objects contain live load functions. Preserve those
  // references while cloning the serializable navigation snapshot.
  function immutableOriginClone(origin){
    const source = origin && typeof origin === "object" ? origin : {};
    const result = cloneValue(source) || {};
    try{
      if(source.currentRef) result.currentRef = source.currentRef;
      if(source.rootRef) result.rootRef = source.rootRef;
      if(Array.isArray(source.historyRefs)) result.historyRefs = source.historyRefs.slice();
      if(source.current) result.current = cloneValue(source.current);
      if(source.root) result.root = cloneValue(source.root);
      if(Array.isArray(source.history)) result.history = source.history.map(cloneValue);
      Object.freeze(result);
    }catch(_error){}
    return result;
  }

  function createSpecialNavigationModel(initial){
    const source = initial && typeof initial === "object" ? initial : {};
    const model = {
      origin: source.origin || null,
      stack: Array.isArray(source.stack) ? source.stack.slice() : [],
      restoring: false,
      startedFromDeepLink: !!source.startedFromDeepLink,
    };

    function snapshot(){
      return {
        origin: model.origin,
        stack: model.stack.slice(),
        restoring: model.restoring,
        startedFromDeepLink: model.startedFromDeepLink,
      };
    }

    function open(kind, ordinaryOrigin, options){
      const cleanKind = String(kind || "");
      if(!SPECIAL_KINDS.has(cleanKind)) throw new Error("Unknown special page: " + cleanKind);
      const opts = options || {};
      if(!model.stack.length){
        if(!ordinaryOrigin && !model.origin) throw new Error("A special page requires an ordinary origin");
        if(ordinaryOrigin) model.origin = immutableOriginClone(ordinaryOrigin);
        model.startedFromDeepLink = !!opts.startedFromDeepLink;
      }
      const active = model.stack.length ? model.stack[model.stack.length - 1] : null;
      if(!active || active.kind !== cleanKind){
        model.stack.push(Object.freeze({kind: cleanKind, render: typeof opts.render === "function" ? opts.render : null}));
      }
      return snapshot();
    }

    function back(){
      if(!model.stack.length) return {kind: "ordinary"};
      model.stack.pop();
      if(model.stack.length){
        return {kind: "special", entry: model.stack[model.stack.length - 1]};
      }
      const origin = model.origin;
      model.origin = null;
      model.startedFromDeepLink = false;
      return {kind: "origin", origin};
    }

    function clear(){
      model.stack.length = 0;
      model.origin = null;
      model.restoring = false;
      model.startedFromDeepLink = false;
      return snapshot();
    }

    return {state: model, snapshot, open, back, clear};
  }

  function viewDescriptor(view){
    if(!view || typeof view !== "object") return null;
    const root = view.root || null;
    return {
      kind: String(view.kind || ""),
      label: String(view.label || ""),
      root_id: String((root && root.id) || view.root_id || ""),
      root_name: String((root && root.name) || view.root_name || ""),
      root_mode: String((root && root.mode) || view.root_mode || ""),
      rel: String(view.rel || ""),
      level: String(view.level || ""),
      value: String(view.value || ""),
      playlistRel: String(view.playlistRel || ""),
      taskId: String(view.taskId || view.task_id || ""),
      source: String(view.source || ""),
    };
  }

  function createBrowserNavigationController(win){
    const document = win.document;
    const appState = win.state;
    if(!appState) return null;
    if(!appState.specialNav){
      appState.specialNav = {origin: null, stack: [], restoring: false, startedFromDeepLink: false};
    }
    const model = createSpecialNavigationModel(appState.specialNav);
    appState.specialNav = model.state;

    function captureOrdinaryOrigin(){
      const list = document.getElementById("libList");
      const historyRefs = Array.isArray(appState.history) ? appState.history.slice() : [];
      const search = appState.libSearch || {};
      return {
        current: viewDescriptor(appState.current),
        currentRef: appState.current || null,
        root: cloneValue(appState.root),
        rootRef: appState.root || null,
        selectionIndex: Number(appState.sel || 0),
        scrollTop: Number((list && list.scrollTop) || 0),
        history: historyRefs.map(viewDescriptor),
        historyRefs,
        search: cloneValue({
          q: search.q || "",
          filter: search.filter || "",
          engine: search.engine || "combined",
          cache_key: search.cache_key || "",
          result_source: search.result_source || "",
          last_count: Number(search.last_count || 0),
          results: Array.isArray(search.results) ? search.results : [],
          sourceStatus: search.sourceStatus || {},
          cached: !!search.cached,
          showSourceStatus: !!search.showSourceStatus,
        }),
      };
    }

    async function restoreOrdinaryOrigin(origin){
      if(!origin) return false;
      model.state.restoring = true;
      try{
        if(typeof win.showNowPlaying === "function") win.showNowPlaying(false, {navigationControlled: true});
        appState.root = origin.rootRef || origin.root || null;
        appState.history = Array.isArray(origin.historyRefs) ? origin.historyRefs.slice() : [];
        if(origin.search && appState.libSearch) Object.assign(appState.libSearch, cloneValue(origin.search));
        appState.current = origin.currentRef || appState.current;
        if(appState.current && typeof appState.current.load === "function"){
          await appState.current.load();
        }else if(typeof win.showRoots === "function"){
          await win.showRoots();
        }
        appState.sel = Math.max(0, Number(origin.selectionIndex || 0));
        if(typeof win.renderList === "function") win.renderList({preserveScroll: true});
        const list = document.getElementById("libList");
        if(list) list.scrollTop = Math.max(0, Number(origin.scrollTop || 0));
        return true;
      }finally{
        model.state.restoring = false;
      }
    }

    async function renderSpecial(entryOrKind){
      const entry = typeof entryOrKind === "string" ? {kind:entryOrKind} : (entryOrKind || {});
      const kind = entry.kind;
      model.state.restoring = true;
      try{
        if(typeof entry.render === "function"){
          await entry.render();
        }else if(kind === "now_playing"){
          if(typeof win.showNowPlaying === "function") win.showNowPlaying(true, {navigationControlled: true});
        }else if(kind === "queue"){
          if(typeof win.viewPlaybackQueue === "function") await win.viewPlaybackQueue(false, {navigationControlled: true});
        }else if(kind === "history"){
          if(typeof win.viewHistory === "function") await win.viewHistory(false, {navigationControlled: true});
        }
      }finally{
        model.state.restoring = false;
      }
    }

    async function openSpecial(kind, options){
      const opts = options || {};
      const origin = model.state.stack.length ? null : (opts.origin || captureOrdinaryOrigin());
      model.open(kind, origin, opts);
      await renderSpecial(model.state.stack[model.state.stack.length - 1]);
      return model.snapshot();
    }

    async function back(){
      const result = model.back();
      if(result.kind === "special"){
        await renderSpecial(result.entry);
        return true;
      }
      if(result.kind === "origin"){
        await restoreOrdinaryOrigin(result.origin);
        return true;
      }
      return false;
    }

    async function jumpToCurrentItem(){
      const origin = model.state.origin;
      model.clear();
      try{
        if(typeof win.openNowFolder === "function") await win.openNowFolder({ordinaryOrigin: origin});
      }finally{
        model.clear();
      }
    }

    function clear(){
      return model.clear();
    }

    function isActive(){
      return model.state.stack.length > 0;
    }

    async function openTransient(kind, render, options){
      if(typeof render !== "function") throw new Error("A transient special page requires a renderer");
      return openSpecial(kind, Object.assign({}, options || {}, {render}));
    }

    return {
      state: model.state,
      captureOrdinaryOrigin,
      restoreOrdinaryOrigin,
      openSpecial,
      openNowPlaying: (options) => openSpecial("now_playing", options),
      openQueue: (options) => openSpecial("queue", options),
      openHistory: (options) => openSpecial("history", options),
      openTransient,
      back,
      jumpToCurrentItem,
      clear,
      isActive,
    };
  }

  return {
    SPECIAL_KINDS,
    createSpecialNavigationModel,
    createBrowserNavigationController,
    viewDescriptor,
  };
});
