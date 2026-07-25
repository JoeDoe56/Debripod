/* Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818 */
(function(){
  "use strict";
  const root = window.DebriPod = window.DebriPod || {};
  const FALLBACK_KEY = "debripod_installation_client_id";
  let installationId = "";

  function randomId(){
    if(window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    return Array.from(bytes, (value, index)=>([4,6,8,10].includes(index) ? "-" : "") + value.toString(16).padStart(2, "0")).join("");
  }

  function openIdDb(){
    return new Promise(resolve=>{
      if(!("indexedDB" in window)) return resolve(null);
      const request = indexedDB.open("debripod-installation", 1);
      request.onupgradeneeded = ()=>request.result.createObjectStore("identity");
      request.onsuccess = ()=>resolve(request.result);
      request.onerror = ()=>resolve(null);
    });
  }

  async function initialize(){
    let fallback = "";
    try{ fallback = localStorage.getItem(FALLBACK_KEY) || ""; }catch(_error){}
    const db = await openIdDb();
    if(db){
      installationId = await new Promise(resolve=>{
        const tx = db.transaction("identity", "readonly");
        const request = tx.objectStore("identity").get("client_id");
        request.onsuccess = ()=>resolve(String(request.result || ""));
        request.onerror = ()=>resolve("");
      });
    }
    installationId = installationId || fallback || randomId();
    try{ localStorage.setItem(FALLBACK_KEY, installationId); }catch(_error){}
    if(db){
      try{ db.transaction("identity", "readwrite").objectStore("identity").put(installationId, "client_id"); }catch(_error){}
    }
    return installationId;
  }

  const ready = initialize();

  function clientId(){
    if(installationId) return installationId;
    try{ return localStorage.getItem(FALLBACK_KEY) || ""; }catch(_error){ return ""; }
  }

  function decodePublicKey(value){
    const padding = "=".repeat((4 - String(value).length % 4) % 4);
    const raw = atob((String(value) + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, char=>char.charCodeAt(0));
  }

  async function status(){
    if(!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unavailable";
    if(Notification.permission === "denied") return "blocked";
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    return subscription ? "enabled" : "disabled";
  }

  async function enable(){
    await ready;
    if(await Notification.requestPermission() !== "granted") return status();
    const key = await window.apiGet("/api/notifications/public-key");
    if(!key || !key.ok) throw new Error(key && key.error || "Notifications unavailable");
    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if(!subscription){
      subscription = await registration.pushManager.subscribe({userVisibleOnly:true, applicationServerKey:decodePublicKey(key.public_key)});
    }
    const response = await window.apiPost("/api/notifications/subscribe", {
      client_id:clientId(),
      subscription:subscription.toJSON()
    });
    if(!response || !response.ok) throw new Error(response && response.json && response.json.error || "Failed to enable notifications");
    return "enabled";
  }

  async function disable(){
    await ready;
    if(!("serviceWorker" in navigator)) return "unavailable";
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    const endpoint = subscription ? subscription.endpoint : "";
    if(subscription) await subscription.unsubscribe();
    await window.apiPost("/api/notifications/unsubscribe", {client_id:clientId(), endpoint:endpoint});
    return "disabled";
  }

  root.pwaNotifications = {ready:ready, clientId:clientId, status:status, enable:enable, disable:disable};
})();
