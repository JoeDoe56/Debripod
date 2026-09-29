(function(root){
  "use strict";
  const SF = Object.freeze({
    prev:{name:"backward.end.alt.fill",file:"backward.end.alt.fill",ext:"png"},
    next:{name:"forward.end.alt.fill",file:"forward.end.alt.fill",ext:"png"},
    back15:{name:"gobackward.15",file:"gobackward.15",ext:"png"},
    forward15:{name:"goforward.15",file:"goforward.15",ext:"png"},
    play:{name:"playpause",file:"playpause",ext:"png"},
    pause:{name:"playpause.fill",file:"playpause.fill",ext:"png"},
    menu:{name:"list.bullet",file:"list.bullet",ext:"png"},
    playlist:{name:"text.badge.plus",file:"text.badge.plus",ext:"png"},
    addToPlaylist:{name:"text.badge.plus",file:"text.badge.plus",ext:"png"},
    playNext:{name:"forward.end.fill",file:"forward.end.fill",ext:"png",note:"text.line.first.and.arrowtriangle.forward is unavailable upstream"},
    playAfter:{name:"arrowshape.turn.up.right.fill",file:"arrowshape.turn.up.right.fill",ext:"png",note:"text.line.last.and.arrowtriangle.forward is unavailable upstream"},
    like:{name:"heart",file:"heart",ext:"png"},
    likeActive:{name:"heart.fill",file:"heart.fill",ext:"png"},
    shuffle:{name:"shuffle",file:"shuffleinactivefull-fixed",legacy:true},
    shuffleActive:{name:"shuffle.fill",file:"shuffleactivefull-fixed",legacy:true}
  });
  function descriptorFor(name, active){
    if(name === "heart") return active ? SF.likeActive : SF.like;
    if(name === "shuffle") return active ? SF.shuffleActive : SF.shuffle;
    if(name === "play" || name === "pause") return active == null ? SF[name] : active ? SF.pause : SF.play;
    return SF[name] || null;
  }
  function symbolFor(name, active){ const descriptor=descriptorFor(name,active); return descriptor ? descriptor.name : ""; }
  function assetFor(name, active){
    const descriptor=descriptorFor(name,active); if(!descriptor) return "";
    const version=String(descriptor.legacy ? root.DEBRIPOD_ICON_VERSION||root.DEBRIPOD_ASSET_VERSION||"" : root.DEBRIPOD_ASSET_VERSION||root.DEBRIPOD_ICON_VERSION||"");
    const base = descriptor.legacy ? "/icons/" : "/static/icons/sf/";
    return descriptor.legacy ? base+descriptor.file+".svg"+(version?"?v="+encodeURIComponent(version):"") : base+descriptor.file+"."+(descriptor.ext||"png")+(version?"?v="+encodeURIComponent(version):"");
  }
  function update(label,name,active,options){
    if(!label) return false;
    const menu=label.querySelector(".menuWord"), icon=label.querySelector(".wheelIcon");
    const visible=!!name, isMenu=name === "menu", src=isMenu ? "" : assetFor(name,active);
    if(menu) menu.hidden=isMenu ? false : true;
    if(label.hidden !== !visible) label.hidden=!visible;
    if(icon){
      icon.setAttribute("data-liquid-symbol","");
      const hide=!visible||isMenu||!src; if(icon.hidden!==hide) icon.hidden=hide;
      icon.classList.toggle("seekModeIcon",!!(options&&options.seekMode));
      icon.classList.toggle("isInactive",(name === "play"||name === "shuffle")&&!active);
      if(icon.dataset) icon.dataset.sfSymbol=symbolFor(name,active);
      if(src){
        if(icon.getAttribute("src")!==src) icon.setAttribute("src",src);
        if(icon.style&&typeof icon.style.setProperty === "function"){
          icon.style.setProperty("--sf-symbol-mask",'url("'+src+'")');
          icon.style.setProperty("--wheel-icon-mask",'url("'+src+'")');
        }
      }
    }
    label.dataset.wheelIcon=symbolFor(name,active)||(isMenu?"line.3.horizontal":"");
    return visible&&(isMenu||!!src);
  }
  if(root.Image){
    const seen=new Set(Object.keys(SF).map((name)=>assetFor(name,false)).concat([assetFor("heart",true),assetFor("play",true)]));
    for(const src of seen){ if(!src) continue; const image=new root.Image(); image.src=src; }
  }
  const namespace=root.DebriPod=root.DebriPod||{};
  // ui-primitives exposes an immutable semantic registry; keep wheel aliases
  // in a shallow copy so loading this module never mutates the frozen object.
  namespace.symbols=Object.assign({}, namespace.symbols || {}); Object.keys(SF).forEach((key)=>{namespace.symbols[key]=SF[key];});
  namespace.wheelIcons={SF,symbolFor,assetFor,update};
  if(typeof module!=="undefined"&&module.exports) module.exports=namespace.wheelIcons;
})(typeof window!=="undefined"?window:globalThis);
