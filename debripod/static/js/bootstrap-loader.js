(function(){
  const scripts = [
    "/static/vendor/hls-local.js",
    "/static/js/glass-motion.js",
    "/static/js/glass-overlays.js",
    "/static/liquidGL.js",
    "/static/js/platform.js",
    "/static/js/layout-controller.js",
    "/static/js/pwa-notifications.js",
    "/static/js/api-client.js",
    "/static/js/passkeys.js",
    "/static/js/ui-settings.js",
    "/static/js/frame-scheduler.js",
    "/static/js/app-state.js",
    "/static/js/media-audio-graph.js",
    "/static/js/gapless-audio.js",
    "/static/js/playback-transport.js",
    "/static/js/glass-lighting.js",
    "/static/js/liquid-glue.js",
    "/static/js/format-utils.js",
    "/static/js/path-pill.js",
    "/static/js/playback-loader.js",
    "/static/js/palette-utils.js",
    "/static/js/visualizer-engine.js",
    "/static/js/video-ambient.js",
    "/static/js/album-art-texture.js",
    "/static/js/wheel-icons.js",
    "/static/js/now-playing-ui.js",
    "/static/js/media-session.js",
    "/static/js/search-results-worker.js",
    "/static/js/search-results-model.js",
    "/static/js/playback-sync.js",
    "/static/js/row-transitions.js",
    "/static/js/list-view.js",
    "/static/js/row-refraction.js",
    "/static/js/settings-ui.js",
    "/static/js/search-tasks-ui.js",
    "/static/js/link-intake.js",
    "/static/js/library-browser.js",
    "/static/js/playback-queue.js",
    "/static/js/media-actions.js",
    "/static/js/navigation-controller.js",
    "/static/js/control-dispatcher.js",
    "/static/js/wheel-controls.js",
    "/static/js/client-sync.js",
    "/static/js/performance-overlay.js",
    "/static/debripod.js"
  ];

  function loadScript(src, version){
    return new Promise((resolve, reject)=>{
      const node = document.createElement("script");
      node.src = src + (version ? ("?v=" + encodeURIComponent(version)) : "");
      node.onload = resolve;
      node.onerror = ()=>reject(new Error("Could not load " + src));
      document.body.appendChild(node);
    });
  }

  (async ()=>{
    const response = await fetch("/api/bootstrap", {headers:{"Accept":"application/json"}});
    const payload = await response.json();
    if(!response.ok || !payload.ok) throw new Error(payload.error || "Could not load DebriPod bootstrap data");
    window.DEBRIPOD_APP_INFO = payload.app_info || {};
    window.DEBRIPOD_UI_DEFAULTS = payload.ui_defaults || {};
    window.DEBRIPOD_DEVICE_SETTINGS_USER_ID = String(payload.device_settings_user_id || "");
    window.DEBRIPOD_ASSET_VERSION = String(payload.asset_version || "");
    window.DEBRIPOD_ICON_VERSION = String(payload.icon_version || "");
    window.DEBRIPOD_TASKS_POLL_MS = Number(payload.tasks_poll_ms || 1200);
    window.DEBRIPOD_CSRF_TOKEN = String(payload.csrf_token || "");
    for(const src of scripts) await loadScript(src, window.DEBRIPOD_ASSET_VERSION);
  })().catch((error)=>{
    const message = document.createElement("div");
    message.className = "bootstrapError";
    message.textContent = error && error.message ? error.message : "DebriPod could not start.";
    document.body.appendChild(message);
  });
})();
