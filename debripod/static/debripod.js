  function updateTopbarVar(){
    try{
      const tb = document.querySelector(".topbar");
      const h = tb ? tb.getBoundingClientRect().height : 0;
      document.documentElement.style.setProperty("--topbarH", (h ? (h + "px") : "0px"));
    }catch(e){}
  }
  window.addEventListener("resize", updateTopbarVar);
  window.addEventListener("load", syncWheelZoneHeight);
  updateTopbarVar();
  syncWheelZoneHeight();


  // start
  (async ()=>{
    let restoredFromLocal = false;
    // Configuration also initializes LiquidGL and playback capabilities. It
    // must run even when client sync restores a cached library view and the
    // normal showRoots() path is skipped.
    try{
      await loadConfig();
      document.documentElement.setAttribute("data-debripod-config", "ready");
    }catch(e){
      document.documentElement.setAttribute("data-debripod-config", "error");
      try{ console.error("[DebriPod startup] configuration initialization failed", e); }catch(err){}
    }
    try{
      if(window.DebriPod && DebriPod.passkeys && typeof DebriPod.passkeys.maybeOfferAfterLogin === "function"){
        await DebriPod.passkeys.maybeOfferAfterLogin();
      }
    }catch(e){}
    try{
      if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.awaitReady){
        restoredFromLocal = !!(await DebriPod.clientSync.awaitReady());
      }
    }catch(e){}
    if(!restoredFromLocal){
      try{
        if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.restoreCachedView){
          restoredFromLocal = !!(await DebriPod.clientSync.restoreCachedView({kind:"roots"}));
        }
      }catch(e){}
    }
    if(!restoredFromLocal){
      try{
        await showRoots();
      }catch(e){
        const msg = (window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.serverRequiredMessage)
          ? DebriPod.clientSync.serverRequiredMessage("Library browsing")
          : "Library browsing requires the local DebriPod server.";
        state.current = state.rootView || rootViewObj();
        resetList([{kind:"info", label:msg}]);
      }
    }
    await maybeOpenFromUrl();
    try{ await maybeStartSetupWizard(); }catch(e){}
    syncWheelZoneHeight();
  })().catch(()=>{});
