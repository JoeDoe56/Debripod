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
    try{
      if(window.DebriPod && DebriPod.passkeys && typeof DebriPod.passkeys.maybeOfferAfterLogin === "function"){
        await DebriPod.passkeys.maybeOfferAfterLogin();
      }
    }catch(e){}
    try{
      if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.awaitReady){
        restoredFromLocal = !!(await Promise.race([
          DebriPod.clientSync.awaitReady(),
          new Promise(resolve=> setTimeout(()=> resolve(false), 160))
        ]));
      }
    }catch(e){}
    if(!restoredFromLocal){
      await showRoots();
    }
    await maybeOpenFromUrl();
    try{ await maybeStartSetupWizard(); }catch(e){}
    syncWheelZoneHeight();
  })().catch(()=>{});
