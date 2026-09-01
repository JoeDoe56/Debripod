(function(){
  const root = window.DebriPod = window.DebriPod || {};
  try{
    const matches = (query)=> !!(window.matchMedia && window.matchMedia(query).matches);
    const touchPoints = Number(navigator.maxTouchPoints || 0);
    const coarsePointer = matches("(pointer: coarse)");
    const narrowViewport = matches("(max-width: 760px)");
    const mobile = !!(touchPoints > 0 && coarsePointer && narrowViewport);
    const ua = String(navigator.userAgent || "");
    const platform = String(navigator.platform || "");
    const isiPhone = /iPhone|iPod/i.test(ua) || (platform === "MacIntel" && touchPoints > 1 && Math.min(screen.width || 0, screen.height || 0) < 820);
    const capabilities = Object.freeze({mobile:mobile, canEditLibraryFolders:!mobile, canUseSystemFilePicker:!mobile});
    root.platform = capabilities;
    window.DebriPodPlatform = capabilities;
    document.documentElement.classList.toggle("isIphone", !!isiPhone);
    document.documentElement.classList.toggle("isMobile", mobile);
  }catch(e){
    const capabilities = Object.freeze({mobile:false, canEditLibraryFolders:true, canUseSystemFilePicker:true});
    root.platform = capabilities;
    window.DebriPodPlatform = capabilities;
  }
})();
