/*
 * Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818
 * Maps every wheel and keyboard gesture through the final control contract.
 */
(function(globalScope, factory){
  const api = factory();
  if(typeof module === "object" && module.exports) module.exports = api;
  if(globalScope && globalScope.document){
    const root = globalScope.DebriPod = globalScope.DebriPod || {};
    root.controlDispatcher = api.createBrowserControlDispatcher(globalScope);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function(){
  "use strict";

  const TAP_TABLE = Object.freeze({
    list: Object.freeze({
      center: "select",
      top: "back",
      right: "next",
      bottom: "toggle_play",
      left: "previous",
      scroll_back: "scroll_back",
      scroll_forward: "scroll_forward",
    }),
    now_playing: Object.freeze({
      center: "enter_seek",
      top: "back",
      right: "next",
      bottom: "toggle_play",
      left: "previous",
      scroll_back: "volume_down",
      scroll_forward: "volume_up",
    }),
    seek_mode: Object.freeze({
      center: "commit_seek",
      top: "toggle_like",
      right: "skip_forward",
      bottom: "toggle_shuffle",
      left: "skip_back",
      scroll_back: "seek_back",
      scroll_forward: "seek_forward",
    }),
  });

  const HOLD_TABLE = Object.freeze({
    center: "open_context",
    top: "jump_to_item",
    right: "open_queue",
    bottom: "open_now_playing",
    left: "open_history",
  });

  function resolveControlCommand(gesture, control, context, details){
    const cleanGesture = String(gesture || "");
    const cleanControl = String(control || "");
    const cleanContext = TAP_TABLE[context] ? context : "list";
    if(cleanGesture === "hold") return HOLD_TABLE[cleanControl] || null;
    const command = TAP_TABLE[cleanContext][cleanControl] || null;
    if(command === "commit_seek" && details && details.seekChanged === false) return "cancel_seek";
    return command;
  }

  function createBrowserControlDispatcher(win){
    const root = win.DebriPod = win.DebriPod || {};

    function context(){
      try{
        if(win.nowPlaying && win.nowPlaying.style.display === "block"){
          return win.seekMode ? "seek_mode" : "now_playing";
        }
      }catch(_error){}
      return "list";
    }

    function callMaybe(name, ...args){
      const fn = win[name];
      if(typeof fn !== "function") return undefined;
      return fn.apply(win, args);
    }

    async function execute(command, details){
      const nav = root.navigationController;
      const queue = root.playbackQueue;
      const mediaActions = root.mediaActions;
      switch(command){
        case "select":
          if(callMaybe("rangeEditorCenterPress")) return true;
          return callMaybe("selectItem", details && details.item);
        case "back":
          if(callMaybe("rangeEditorCancelActive")) return true;
          if(nav && nav.isActive && nav.isActive()) return nav.back();
          return callMaybe("goBack");
        case "next":
          if(queue && queue.hasItems && queue.hasItems()) return queue.next();
          return callMaybe("isVideoActive") ? callMaybe("playVideoNext") : callMaybe("playNext");
        case "previous":
          if(queue && queue.hasItems && queue.hasItems()) return queue.previous();
          return callMaybe("isVideoActive") ? callMaybe("playVideoPrev") : callMaybe("playPrev");
        case "toggle_play":
          return callMaybe("togglePlay");
        case "enter_seek":
          return callMaybe("enterSeekMode");
        case "commit_seek":
          return callMaybe("commitSeekMode");
        case "cancel_seek":
          return callMaybe("cancelSeekMode");
        case "toggle_like":
          if(mediaActions && mediaActions.toggleLikeForCurrentTarget) return mediaActions.toggleLikeForCurrentTarget();
          return undefined;
        case "skip_forward":
          callMaybe("seek", 15);
          return callMaybe("resetSeekIdle");
        case "skip_back":
          callMaybe("seek", -15);
          return callMaybe("resetSeekIdle");
        case "toggle_shuffle":
          callMaybe("toggleShuffle");
          return callMaybe("resetSeekIdle");
        case "volume_up":
          return callMaybe("adjustVolumeStep", 1);
        case "volume_down":
          return callMaybe("adjustVolumeStep", -1);
        case "seek_forward":
          return callMaybe("adjustSeekPreview", 1);
        case "seek_back":
          return callMaybe("adjustSeekPreview", -1);
        case "scroll_forward":
          if(callMaybe("rangeEditorWheelActive")) return callMaybe("adjustRangeEditor", 1);
          return callMaybe("scrollSel", 1);
        case "scroll_back":
          if(callMaybe("rangeEditorWheelActive")) return callMaybe("adjustRangeEditor", -1);
          return callMaybe("scrollSel", -1);
        case "open_context":
          if(callMaybe("rangeEditorCenterHold")) return true;
          if(!mediaActions || !mediaActions.openContextMenuForCurrentTarget) return undefined;
          return mediaActions.openContextMenuForCurrentTarget(details && details.item);
        case "jump_to_item":
          return nav && nav.jumpToCurrentItem ? nav.jumpToCurrentItem() : undefined;
        case "open_queue":
          return nav && nav.openQueue ? nav.openQueue() : undefined;
        case "open_history":
          return nav && nav.openHistory ? nav.openHistory() : undefined;
        case "open_now_playing":
          if(!win.state || !win.state.now) return undefined;
          return nav && nav.openNowPlaying ? nav.openNowPlaying() : undefined;
        default:
          return undefined;
      }
    }

    function dispatch(gesture, control, details){
      const currentContext = context();
      const extra = Object.assign({}, details || {});
      if(currentContext === "seek_mode" && !Object.prototype.hasOwnProperty.call(extra, "seekChanged")){
        extra.seekChanged = !!win.seekChanged;
      }
      const command = resolveControlCommand(gesture, control, currentContext, extra);
      if(!command) return Promise.resolve(undefined);
      try{
        return Promise.resolve(execute(command, extra));
      }catch(error){
        return Promise.reject(error);
      }
    }

    return {context, dispatch, execute, resolveControlCommand};
  }

  return {TAP_TABLE, HOLD_TABLE, resolveControlCommand, createBrowserControlDispatcher};
});
