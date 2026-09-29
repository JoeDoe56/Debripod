(function(root){
  "use strict";

  /*
   * Shared visual primitives for the row, settings, and wheel surfaces.
   * The primitives deliberately expose state instead of owning a particular
   * list implementation, so virtualized rows can reuse them safely.
   */
  const ns = root.DebriPod = root.DebriPod || {};
  const symbols = Object.freeze({
    next: {name:"forward.end.alt.fill", file:"forward.end.alt.fill", ext:"png"},
    previous: {name:"backward.end.alt.fill", file:"backward.end.alt.fill", ext:"png"},
    prev: {name:"backward.end.alt.fill", file:"backward.end.alt.fill", ext:"png"},
    like: {name:"heart", file:"heart", ext:"png"},
    likeActive: {name:"heart.fill", file:"heart.fill", ext:"png"},
    playPause: {name:"playpause.fill", file:"playpause.fill", ext:"png"},
    playPauseOutline: {name:"playpause", file:"playpause", ext:"png"},
    "play.fill": {name:"play.fill", file:"play.fill", ext:"png"},
    "slider.horizontal.3": {name:"slider.horizontal.3", file:"slider.horizontal.3", ext:"png"},
    circle: {name:"circle", file:"circle", ext:"png"},
    menu: {name:"list.bullet", file:"list.bullet", ext:"png"},
    info: {name:"info.circle", file:"info.circle", ext:"png"},
    network: {name:"antenna.radiowaves.left.and.right", file:"antenna.radiowaves.left.and.right", ext:"png", note:"network is unavailable upstream"},
    waveform: {name:"waveform", file:"waveform", ext:"png"},
    keyboard: {name:"keyboard", file:"keyboard", ext:"png"},
    bell: {name:"bell", file:"bell", ext:"png"},
    fullscreen: {name:"rectangle.expand.vertical", file:"rectangle.expand.vertical", ext:"png"},
    "arrow.up.left.and.arrow.down.right": {name:"arrow.up.left.and.arrow.down.right", file:"arrow.up.left.and.arrow.down.right", ext:"png"},
    settings: {name:"gear", file:"gear", ext:"png", note:"gearshape is unavailable upstream"},
    gearshape: {name:"gear", file:"gear", ext:"png", note:"gearshape is unavailable upstream"},
    library: {name:"rectangle.stack", file:"rectangle.stack", ext:"png", note:"books.vertical is unavailable upstream"},
    "books.vertical": {name:"rectangle.stack", file:"rectangle.stack", ext:"png", note:"books.vertical is unavailable upstream"},
    artists: {name:"person.2", file:"person.2", ext:"png"},
    albums: {name:"square.stack", file:"square.stack", ext:"png"},
    songs: {name:"music.note.list", file:"music.note.list", ext:"png"},
    genres: {name:"guitars", file:"guitars", ext:"png"},
    movies: {name:"film", file:"film", ext:"png"},
    shows: {name:"tv", file:"tv", ext:"png"},
    search: {name:"magnifyingglass", file:"magnifyingglass", ext:"png"},
    downloads: {name:"arrow.down.circle", file:"arrow.down.circle", ext:"png"},
    playlist: {name:"music.note.list", file:"music.note.list", ext:"png"},
    playNext: {name:"forward.end.fill", file:"forward.end.fill", ext:"png", note:"text.line.first.and.arrowtriangle.forward is unavailable upstream"},
    playAfter: {name:"arrowshape.turn.up.right.fill", file:"arrowshape.turn.up.right.fill", ext:"png", note:"text.line.last.and.arrowtriangle.forward is unavailable upstream"},
    addToPlaylist: {name:"text.badge.plus", file:"text.badge.plus", ext:"png"},
    music: {name:"music.note", file:"music.note", ext:"png"},
    video: {name:"play.rectangle", file:"play.rectangle", ext:"png"},
    podcast: {name:"mic", file:"mic", ext:"png"},
    folder: {name:"folder", file:"folder", ext:"png"},
    check: {name:"checkmark", file:"checkmark", ext:"png"},
    close: {name:"xmark", file:"xmark", ext:"png"},
    add: {name:"plus", file:"plus", ext:"png"},
    heart: {name:"heart", file:"heart", ext:"png"},
    "heart.fill": {name:"heart.fill", file:"heart.fill", ext:"png"}
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
    // Keep dotted SF names intact. The upstream glyph repository uses the
    // symbol name as its filename, so hyphenating here creates false assets.
    return symbols[name] || {name:String(name || ""), file:String(name || ""), ext:"png", note:"asset must be supplied by the upstream glyph set"};
  }

  function symbolUrl(descriptor, version){
    const file = descriptor && descriptor.file ? descriptor.file : "";
    if(!file) return "";
    const query = version == null ? String(root.DEBRIPOD_ASSET_VERSION || root.DEBRIPOD_ICON_VERSION || "") : String(version || "");
    return "/static/icons/sf/" + file + "." + (descriptor.ext || "png") + (query ? "?v=" + encodeURIComponent(query) : "");
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
