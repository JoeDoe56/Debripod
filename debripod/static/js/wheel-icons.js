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

    label.hidden = !visible;
    if(menu) menu.hidden = !isMenu;
    if(icon){
      icon.setAttribute("data-liquid-symbol", "");
      icon.hidden = !visible || isMenu || !symbol;
      icon.classList.toggle("seekModeIcon", !!(options && options.seekMode));
      icon.classList.toggle("isInactive", (name === "play" || name === "shuffle") && !active);
    }
    if(icon && symbol){
      const version = String(root.DEBRIPOD_ICON_VERSION || root.DEBRIPOD_ASSET_VERSION || "");
      const src = "/icons/" + symbol + (version ? ("?v=" + encodeURIComponent(version)) : "");
      if(icon.getAttribute("src") !== src) icon.setAttribute("src", src);
      if(icon.style) icon.style.setProperty("--wheel-icon-mask", 'url("' + src + '")');
    }
    label.dataset.wheelIcon = symbol || (isMenu ? "menu" : "");
    return visible && (isMenu || !!symbol);
  }

  const namespace = root.DebriPod = root.DebriPod || {};
  namespace.wheelIcons = {symbolFor, update};
  if(typeof module !== "undefined" && module.exports) module.exports = namespace.wheelIcons;
})(typeof window !== "undefined" ? window : globalThis);
