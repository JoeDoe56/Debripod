(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const versions = {};
  let started = false;
  let timer = 0;
  let refreshing = false;

  function activeRootId(){
    try{
      return state && state.current && state.current.root ? String(state.current.root.id || "") : "";
    }catch(e){
      return "";
    }
  }

  async function refreshActiveRootView(rootId){
    if(refreshing || !rootId) return;
    let current = null;
    try{ current = state && state.current; }catch(e){ current = null; }
    if(!current || !current.root || String(current.root.id || "") !== rootId || typeof current.load !== "function") return;
    refreshing = true;
    const scrollTop = libList ? libList.scrollTop : 0;
    try{
      await current.load();
      if(libList) libList.scrollTop = scrollTop;
      if(typeof setHeader === "function") setHeader();
    }catch(e){
    }finally{
      refreshing = false;
    }
  }

  async function tick(){
    timer = 0;
    try{
      const js = await apiGet("/api/client-state");
      const next = (js && js.library_versions && typeof js.library_versions === "object") ? js.library_versions : {};
      const changed = [];
      Object.keys(next).forEach((rootId)=>{
        const value = Number(next[rootId] || 0);
        if(versions[rootId] == null){
          versions[rootId] = value;
          return;
        }
        if(value !== versions[rootId]){
          versions[rootId] = value;
          changed.push(rootId);
        }
      });
      const active = activeRootId();
      if(active && changed.indexOf(active) >= 0){
        await refreshActiveRootView(active);
      }
    }catch(e){}
    schedule();
  }

  function schedule(){
    if(timer || !started) return;
    const hidden = document && document.hidden;
    timer = setTimeout(tick, hidden ? 30000 : 6000);
  }

  function start(){
    if(started) return;
    started = true;
    schedule();
  }

  try{
    document.addEventListener("visibilitychange", ()=>{
      if(!document.hidden && started){
        if(timer) clearTimeout(timer);
        timer = setTimeout(tick, 250);
      }
    });
  }catch(e){}

  root.clientSync = {start};
  start();
})();
