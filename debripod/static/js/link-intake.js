/* Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818 */
(function(root, factory){
  const api = factory();
  if(typeof module === "object" && module.exports) module.exports = api;
  if(root){
    root.DebriPod = root.DebriPod || {};
    root.DebriPod.linkIntakePure = api;
    root.DebriPod.linkIntake = api.createBrowserController(root);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function(){
  "use strict";

  function classify(value){
    const text = String(value == null ? "" : value).trim();
    if(/^magnet:\?/i.test(text)){
      try{
        const url = new URL(text);
        const valid = url.searchParams.getAll("xt").some(function(xt){
          const hash = String(xt).replace(/^urn:btih:/i, "");
          return /^[a-f0-9]{40}$/i.test(hash) || /^[a-z2-7]{32}$/i.test(hash);
        });
        if(valid) return "magnet";
      }catch(_error){}
    }
    try{
      const url = new URL(text);
      if((url.protocol === "http:" || url.protocol === "https:") && url.hostname) return "ytdlp_url";
    }catch(_error){}
    return "query";
  }

  function parseDeepLinks(href){
    const url = new URL(String(href || ""), "http://debripod.invalid/");
    return {
      intake: url.searchParams.get("intake") || "",
      task: url.searchParams.get("task") || ""
    };
  }

  function createBrowserController(win){
    if(!win || !win.document) return null;
    let intakeBusy = false;
    let deepLinksConsumed = false;

    async function showIntakeLoading(){
      if(typeof win.setView !== "function") return;
      await win.setView({
        kind:"link_intake_loading",
        label:"Files",
        load:async function(){
          if(typeof win.resetList === "function") win.resetList([{kind:"loading", label:"Inspecting link", loading:true}]);
          if(typeof win.libSetFileStatus === "function") win.libSetFileStatus("", "");
        }
      }, true);
    }

    async function inspect(value){
      if(intakeBusy) return false;
      const kind = classify(value);
      if(kind === "query") return false;
      intakeBusy = true;
      try{
        const inspection = win.apiPost("/api/link/inspect", {value:String(value || "").trim()});
        await showIntakeLoading();
        const response = await inspection;
        const payload = response && response.json ? response.json : {};
        if(!response || !response.ok || !payload.ok) throw new Error(payload.error || "Failed to inspect link");
        if(typeof win.openSearchResultDetail !== "function") throw new Error("Search is not ready");
        await win.openSearchResultDetail(payload.result, false);
        return true;
      }catch(error){
        if(typeof win.libSetStatus === "function") win.libSetStatus(String(error && error.message || error), "warn");
        if(typeof win.resetList === "function") win.resetList([{kind:"info", label:"Failed to inspect link"}]);
        return false;
      }finally{
        intakeBusy = false;
      }
    }

    function onPaste(event){
      const text = event && event.clipboardData ? event.clipboardData.getData("text") : "";
      if(classify(text) === "query") return;
      win.setTimeout(function(){
        const input = event && event.target;
        inspect(input && typeof input.value === "string" ? input.value : text);
      }, 0);
    }

    async function consumeDeepLinks(){
      if(deepLinksConsumed) return;
      const values = parseDeepLinks(win.location.href);
      if(!values.intake && !values.task) return;
      deepLinksConsumed = true;
      const url = new URL(win.location.href);
      url.searchParams.delete("intake");
      url.searchParams.delete("task");
      win.history.replaceState(win.history.state, "", url.pathname + url.search + url.hash);
      if(values.intake) await inspect(values.intake);
      if(values.task){
        if(typeof win.viewLibTasks === "function") await win.viewLibTasks(true);
        if(typeof win.viewLibTask === "function") await win.viewLibTask(true, values.task);
      }
    }

    return {classify:classify, inspect:inspect, onPaste:onPaste, consumeDeepLinks:consumeDeepLinks};
  }

  return {classify:classify, classifyLinkIntake:classify, parseDeepLinks:parseDeepLinks, createBrowserController:createBrowserController};
});
