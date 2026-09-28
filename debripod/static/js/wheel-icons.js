(function(root){
  "use strict";

  const SYMBOLS = Object.freeze({
    prev: "button5_previous-track.svg",
    next: "button3_next-track.svg",
    back15: "button5_seek-mode_skip-back.svg",
    forward15: "button3_seek-mode_skip-forward.svg",
    play: "button4_media-paused.svg",
    pause: "button4_media-playing.svg"
  });

  function symbolFor(name, active){
    if(name === "heart") return active ? "button2_seek-mode_liked-active.svg" : "button2_seek-mode_liked-inactive.svg";
    if(name === "shuffle") return active ? "shuffleactivefull-fixed.svg" : "shuffleinactivefull-fixed.svg";
    return SYMBOLS[name] || "";
  }

  function update(label, name, active, options){
    if(!label) return false;
    const menu = label.querySelector(".menuWord");
    const icon = label.querySelector(".wheelIcon");
    const visible = !!name;
    const isMenu = name === "menu";
    const symbol = isMenu ? "" : symbolFor(name, active);

    const overlays=root.LiquidGlassOverlays;
    const disappearing=menu&&!menu.hidden&&!isMenu?overlays?.capture(menu):null;
    if(disappearing)overlays.exit(disappearing);
    if(icon&&!icon.hidden&&(!visible||isMenu||!symbol))overlays?.exit(overlays.capture(icon));
    if(label.hidden !== !visible) label.hidden = !visible;
    if(menu && menu.hidden !== !isMenu) menu.hidden = !isMenu;
    if(icon){
      icon.setAttribute("data-liquid-symbol", "");
      const hide = !visible || isMenu || !symbol;
      if(icon.hidden !== hide) icon.hidden = hide;
      icon.classList.toggle("seekModeIcon", !!(options && options.seekMode));
      icon.classList.toggle("isInactive", (name === "play" || name === "shuffle") && !active);
    }
    if(icon && symbol){
      const version = String(root.DEBRIPOD_ICON_VERSION || root.DEBRIPOD_ASSET_VERSION || "");
      const src = "/icons/" + symbol + (version ? ("?v=" + encodeURIComponent(version)) : "");
      if(icon.getAttribute("src") !== src) icon.setAttribute("src", src);
      const mask = 'url("' + src + '")';
      if(icon.style && icon.style.getPropertyValue("--wheel-icon-mask") !== mask) icon.style.setProperty("--wheel-icon-mask", mask);
    }
    label.dataset.wheelIcon = symbol || (isMenu ? "menu" : "");
    return visible && (isMenu || !!symbol);
  }

  // Warm both states before the first interaction; CSS masks otherwise fetch only
  // when revealed, leaving an empty symbol on slower connections.
  if(root.Image){
    const version=String(root.DEBRIPOD_ICON_VERSION||root.DEBRIPOD_ASSET_VERSION||"");
    const symbols=new Set([...Object.values(SYMBOLS),symbolFor("heart",true),symbolFor("heart",false),symbolFor("shuffle",true),symbolFor("shuffle",false)]);
    for(const symbol of symbols){const image=new root.Image();image.src="/icons/"+symbol+(version?"?v="+encodeURIComponent(version):"");}
  }
  const namespace = root.DebriPod = root.DebriPod || {};
  namespace.wheelIcons = {symbolFor, update};
  if(typeof module !== "undefined" && module.exports) module.exports = namespace.wheelIcons;
})(typeof window !== "undefined" ? window : globalThis);
