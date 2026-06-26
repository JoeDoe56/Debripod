  try{
    const ua = String(navigator.userAgent || "");
    const platform = String(navigator.platform || "");
    const isiPhone = /iPhone|iPod/i.test(ua) || (platform === "MacIntel" && navigator.maxTouchPoints > 1 && Math.min(screen.width || 0, screen.height || 0) < 820);
    document.documentElement.classList.toggle("isIphone", !!isiPhone);
  }catch(e){}
