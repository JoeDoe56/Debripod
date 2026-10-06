// Testing-glass branch: a device-local, static backdrop for visual comparison.
(function(){
  "use strict";
  const root = window.DebriPod = window.DebriPod || {};
  const storageKey = String(window.DEBRIPOD_DEVICE_SETTINGS_USER_ID || "anonymous");
  const clearedKey = "debripod-test-wallpaper-cleared:" + storageKey;
  let current = null;
  let revision = 0;
  let operation = 0;
  let picker = null;
  let storageQueue = Promise.resolve();

  function status(message, tone){
    if(typeof reportUiStatus === "function") reportUiStatus(message, tone || "info");
  }
  function stored(action, value){
    const task = storageQueue.catch(()=>{}).then(()=>new Promise((resolve, reject)=>{
      const request = indexedDB.open("debripod-test-wallpaper", 1);
      request.onupgradeneeded = ()=>request.result.createObjectStore("images");
      request.onerror = ()=>reject(request.error);
      request.onsuccess = ()=>{
        const db = request.result;
        const tx = db.transaction("images", action === "get" ? "readonly" : "readwrite");
        const store = tx.objectStore("images");
        const req = action === "get" ? store.get(storageKey) : action === "put" ? store.put(value, storageKey) : store.delete(storageKey);
        tx.oncomplete = ()=>{ db.close(); resolve(req.result); };
        tx.onabort = tx.onerror = ()=>{ db.close(); reject(tx.error || new Error("Wallpaper storage unavailable")); };
      };
    }));
    storageQueue = task;
    return task;
  }
  function refresh(){
    if(typeof refreshLiquidGlassVisualizerSources === "function") refreshLiquidGlassVisualizerSources("wallpaper", {force:true});
    if(typeof scheduleLiquidGlassRender === "function") scheduleLiquidGlassRender();
  }
  function mount(image, url, name){
    const previous = current;
    const node = document.getElementById("debripodWallpaper") || document.createElement("img");
    node.id = "debripodWallpaper";
    node.alt = "";
    node.setAttribute("aria-hidden", "true");
    node.setAttribute("data-liquid-ignore", "");
    node.draggable = false;
    node.src = url;
    if(!node.isConnected){
      const visualizer = document.getElementById("visualizerBg");
      (visualizer && visualizer.parentElement || document.body).prepend(node);
    }
    current = {image, url, name, key:"wallpaper:" + (++revision)};
    document.documentElement.classList.add("dpTestingWallpaper");
    if(previous) URL.revokeObjectURL(previous.url);
    refresh();
  }
  async function decoded(blob){
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
      if(!image.naturalWidth || !image.naturalHeight) throw new Error("Empty image");
      return {image, url};
    } catch(error){ URL.revokeObjectURL(url); throw error; }
  }
  async function upload(file){
    if(!file) return false; // Native picker cancellation does nothing.
    const token = ++operation;
    let decodedImage;
    try {
      if(file.size > 40 * 1024 * 1024) throw new Error("Choose an image smaller than 40 MB.");
      if(file.type && !file.type.startsWith("image/")) throw new Error("Choose an image file.");
      decodedImage = await decoded(file);
      // Freeze animated formats and normalize orientation once, not per frame.
      const image = decodedImage.image;
      const scale = Math.min(1, 4096 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve=>canvas.toBlob(resolve, "image/png"));
      if(!blob) throw new Error("This image could not be prepared.");
      URL.revokeObjectURL(decodedImage.url);
      decodedImage = await decoded(blob);
      if(token !== operation){ URL.revokeObjectURL(decodedImage.url); return false; }
      let saved = true;
      try { await stored("put", {blob, name:file.name || "Wallpaper"}); }
      catch(error){ saved = false; }
      if(token !== operation){ URL.revokeObjectURL(decodedImage.url); return false; }
      try { localStorage.removeItem(clearedKey); } catch(error) {}
      if(typeof setVisualizerEnabled === "function") setVisualizerEnabled(false);
      mount(decodedImage.image, decodedImage.url, file.name || "Wallpaper");
      decodedImage = null;
      status(saved ? "Wallpaper applied. Turn Visualizer on to clear it." : "Wallpaper applied for this session; device storage is unavailable.", saved ? "info" : "warn");
      if(typeof viewLibUiSettings === "function" && typeof state !== "undefined" && state.current && state.current.kind === "libuisettings") await viewLibUiSettings(false);
      return true;
    } catch(error){
      if(decodedImage) URL.revokeObjectURL(decodedImage.url);
      if(token === operation) status(error.message && /Choose|prepared/.test(error.message) ? error.message : "This image could not be opened. Try a JPEG or PNG.", "warn");
      return false;
    }
  }
  function choose(){
    if(!picker){
      picker = document.createElement("input");
      picker.type = "file";
      picker.accept = "image/*";
      // Deliberately omit capture: iOS offers its normal Photos/Files/Camera menu.
      picker.hidden = true;
      picker.setAttribute("aria-label", "Upload Wallpaper");
      picker.addEventListener("change", ()=>{ const file = picker.files && picker.files[0]; if(file) upload(file); });
      document.body.appendChild(picker);
    }
    picker.value = "";
    picker.click(); // Must remain synchronous with the settings action gesture.
  }
  function clear(){
    operation++;
    // Persist removal synchronously too: an immediate reload must not revive
    // the blob while its IndexedDB delete transaction is still queued.
    try { localStorage.setItem(clearedKey, "1"); } catch(error) {}
    const previous = current;
    current = null;
    document.getElementById("debripodWallpaper")?.remove();
    document.documentElement.classList.remove("dpTestingWallpaper");
    if(previous) URL.revokeObjectURL(previous.url);
    refresh();
    return stored("delete").catch(()=>{ status("Wallpaper cleared. Device storage could not be updated.", "warn"); });
  }
  async function restore(){
    const token = operation;
    try {
      if(localStorage.getItem(clearedKey) === "1"){ await stored("delete"); return; }
      const saved = await stored("get");
      if(!saved || token !== operation) return;
      if(typeof visualizerEnabled !== "undefined" && visualizerEnabled){ await stored("delete"); return; }
      const result = await decoded(saved.blob);
      if(token !== operation){ URL.revokeObjectURL(result.url); return; }
      mount(result.image, result.url, saved.name);
    } catch(error){ /* The normal backdrop remains usable without storage. */ }
  }
  root.wallpaper = {
    choose, upload, clear,
    active:()=>!!current,
    source:()=>current ? {image:current.image, artKey:current.key, wallpaper:true, ready:true,
      sourceRect:{left:0, top:0, width:window.innerWidth || 1, height:window.innerHeight || 1}} : null
  };
  root.wallpaper.ready = restore();
})();
