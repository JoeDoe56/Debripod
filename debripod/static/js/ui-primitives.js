(function(root){
  "use strict";

  /*
   * Shared visual primitives for the row, settings, and wheel surfaces.
   * The primitives deliberately expose state instead of owning a particular
   * list implementation, so virtualized rows can reuse them safely.
   */
  const ns = root.DebriPod = root.DebriPod || {};
  const symbols = Object.freeze({
    next: {name:"forward.end.alt.fill", file:"forward-end-alt-fill"},
    previous: {name:"backward.end.alt.fill", file:"backward-end-alt-fill"},
    prev: {name:"backward.end.alt.fill", file:"backward-end-alt-fill"},
    like: {name:"heart", file:"heart"},
    likeActive: {name:"heart.fill", file:"heart-fill"},
    playPause: {name:"playpause.fill", file:"playpause-fill"},
    playPauseOutline: {name:"playpause", file:"playpause"},
    "play.fill": {name:"play.fill", file:"play-fill"},
    "slider.horizontal.3": {name:"slider.horizontal.3", file:"slider-horizontal-3"},
    circle: {name:"circle", file:"circle"},
    menu: {name:"line.3.horizontal", file:"line-3-horizontal"},
    info: {name:"info.circle", file:"info-circle"},
    settings: {name:"gearshape", file:"gearshape"},
    library: {name:"books.vertical", file:"books-vertical"},
    artists: {name:"person.2", file:"person-2"},
    albums: {name:"square.stack", file:"square-stack"},
    songs: {name:"music.note.list", file:"music-note-list"},
    genres: {name:"guitars", file:"guitars"},
    movies: {name:"film", file:"film"},
    shows: {name:"tv", file:"tv"},
    search: {name:"magnifyingglass", file:"magnifyingglass"},
    downloads: {name:"arrow.down.circle", file:"arrow-down-circle"},
    playlist: {name:"music.note.list", file:"music-note-list"},
    playNext: {name:"text.line.first.and.arrowtriangle.forward", file:"text-line-first-and-arrowtriangle-forward"},
    playAfter: {name:"text.line.last.and.arrowtriangle.forward", file:"text-line-last-and-arrowtriangle-forward"},
    addToPlaylist: {name:"text.badge.plus", file:"text-badge-plus"},
    music: {name:"music.note", file:"music-note"},
    video: {name:"play.rectangle", file:"play-rectangle"},
    podcast: {name:"mic", file:"mic"},
    folder: {name:"folder", file:"folder"},
    check: {name:"checkmark", file:"checkmark"},
    close: {name:"xmark", file:"xmark"},
    add: {name:"plus", file:"plus"},
    heart: {name:"heart", file:"heart"},
    "heart.fill": {name:"heart.fill", file:"heart-fill"}
  });
  const RING_SIZE = 36;

  function clamp(value, min, max){
    const n = Number(value);
    if(!Number.isFinite(n)) return Number(min);
    return Math.max(Number(min), Math.min(Number(max), n));
  }

  function normalize(value, min, max){
    const lo = Number.isFinite(Number(min)) ? Number(min) : 0;
    const hi = Number.isFinite(Number(max)) ? Number(max) : 1;
    if(hi <= lo || !Number.isFinite(Number(value))) return 0;
    return Math.max(0, Math.min(1, (Number(value) - lo) / (hi - lo)));
  }

  function normalizeSetting(value, range){
    const meta = range && typeof range === "object" ? range : {};
    const min = Number.isFinite(Number(meta.min)) ? Number(meta.min) : 0;
    const max = Number.isFinite(Number(meta.max)) ? Number(meta.max) : 1;
    const current = clamp(value, min, max);
    return {value: current, min, max, progress: normalize(current, min, max), step: Number(meta.step) || 0};
  }

  function symbolDescriptor(name, active){
    if(name === "like" || name === "heart") return active ? symbols.likeActive : symbols.like;
    if(name === "play" || name === "pause" || name === "playpause") return active ? symbols.playPause : symbols.playPauseOutline;
    return symbols[name] || {name:String(name || ""), file:String(name || "").replace(/[^a-z0-9]+/gi, "-").toLowerCase()};
  }

  function symbolUrl(descriptor, version){
    const file = descriptor && descriptor.file ? descriptor.file : "";
    if(!file) return "";
    const query = version == null ? String(root.DEBRIPOD_ASSET_VERSION || root.DEBRIPOD_ICON_VERSION || "") : String(version || "");
    return "/static/icons/sf/" + file + ".svg" + (query ? "?v=" + encodeURIComponent(query) : "");
  }

  function setSymbol(element, name, options){
    if(!element) return element;
    const opts = options && typeof options === "object" ? options : {};
    const descriptor = symbolDescriptor(name, !!opts.active);
    const url = symbolUrl(descriptor, opts.version);
    element.dataset.sfSymbol = descriptor.name || String(name || "");
    element.dataset.sfSymbolFile = descriptor.file || "";
    element.setAttribute("aria-hidden", opts.label ? "false" : "true");
    if(opts.label) element.setAttribute("aria-label", String(opts.label));
    else element.removeAttribute("aria-label");
    element.style.setProperty("--sf-symbol-mask", url ? 'url("' + url + '")' : "none");
    element.classList.add("uiSymbol");
    return element;
  }

  function createSymbol(name, options){
    if(!root.document) return null;
    return setSymbol(root.document.createElement("span"), name, options);
  }

  function ringMarkup(){
    return '<svg class="uiRingSvg" viewBox="0 0 36 36" focusable="false" aria-hidden="true"><circle class="uiRingTrack" cx="18" cy="18" r="15"></circle><circle class="uiRingValue" cx="18" cy="18" r="15" pathLength="1"></circle></svg>';
  }

  function setRing(element, value, min, max, options){
    if(!element) return element;
    const opts = options && typeof options === "object" ? options : {};
    const state = normalizeSetting(value, {min:min, max:max, step:opts.step});
    element.classList.add("uiRing");
    element.dataset.uiRing = "";
    element.dataset.uiRingValue = String(state.value);
    element.dataset.uiRingMin = String(state.min);
    element.dataset.uiRingMax = String(state.max);
    element.style.setProperty("--ui-ring-progress", String(state.progress));
    element.setAttribute("role", opts.role || "progressbar");
    if(opts.label) element.setAttribute("aria-label", String(opts.label));
    element.setAttribute("aria-valuemin", String(state.min));
    element.setAttribute("aria-valuemax", String(state.max));
    element.setAttribute("aria-valuenow", String(state.value));
    if(!element.querySelector(".uiRingSvg") && root.document) element.insertAdjacentHTML("afterbegin", ringMarkup());
    const valuePath = element.querySelector(".uiRingValue");
    if(valuePath) valuePath.style.strokeDasharray = String(state.progress) + " 1";
    return element;
  }

  function createRing(value, min, max, options){
    if(!root.document) return null;
    const el = root.document.createElement("span");
    setRing(el, value, min, max, options);
    return el;
  }

  function setSelectedState(element, selected, options){
    if(!element) return element;
    const opts = options && typeof options === "object" ? options : {};
    const active = !!selected;
    element.classList.toggle("uiSelectedState", active);
    element.classList.toggle("uiSelectedStateActive", active);
    element.dataset.uiSelected = active ? "true" : "false";
    if(opts.baseOpacity != null) element.style.setProperty("--ui-selected-opacity", String(foregroundOpacity(opts.baseOpacity, active ? 2 : 1)));
    else element.style.removeProperty("--ui-selected-opacity");
    if(opts.symbol) setSymbol(element.querySelector(".uiSymbol") || element, opts.symbol, {active:!!opts.symbolActive, label:opts.label});
    const glyph = element.querySelector(".uiSymbol, .wheelIcon, [data-sf-symbol]") || element;
    const mask = glyph.style.getPropertyValue("--sf-symbol-mask") || glyph.style.getPropertyValue("--wheel-icon-mask");
    element.style.setProperty("--ui-selected-mask", mask || "none");
    return element;
  }

  function foregroundOpacity(base, multiplier){
    const configured = Number.isFinite(Number(base)) ? Number(base) : 0.45;
    return Math.max(0, Math.min(1, configured * (Number(multiplier) || 1)));
  }

  ns.symbols = symbols;
  ns.uiPrimitives = {
    RING_SIZE,
    symbols,
    clamp,
    normalize,
    normalizeSetting,
    foregroundOpacity,
    symbolDescriptor,
    symbolUrl,
    setSymbol,
    createSymbol,
    ringMarkup,
    setRing,
    createRing,
    setSelectedState
  };
  if(typeof module !== "undefined" && module.exports) module.exports = ns.uiPrimitives;
})(typeof window !== "undefined" ? window : globalThis);
