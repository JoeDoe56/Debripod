(function(){
  function b64urlToBuffer(value){
    let text = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
    while(text.length % 4) text += "=";
    const raw = atob(text);
    const out = new Uint8Array(raw.length);
    for(let index = 0; index < raw.length; index += 1) out[index] = raw.charCodeAt(index);
    return out.buffer;
  }

  function bufferToB64url(buffer){
    const bytes = new Uint8Array(buffer || new ArrayBuffer(0));
    let text = "";
    for(const byte of bytes) text += String.fromCharCode(byte);
    return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function publicKeyFromServer(options){
    const out = Object.assign({}, options || {});
    out.challenge = b64urlToBuffer(out.challenge);
    if(Array.isArray(out.allowCredentials)){
      out.allowCredentials = out.allowCredentials.map((item)=>Object.assign({}, item, {id:b64urlToBuffer(item.id)}));
    }
    return out;
  }

  function credentialToJSON(credential){
    return {
      id: credential.id,
      rawId: bufferToB64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: bufferToB64url(credential.response.clientDataJSON),
        authenticatorData: bufferToB64url(credential.response.authenticatorData),
        signature: bufferToB64url(credential.response.signature),
        userHandle: credential.response.userHandle ? bufferToB64url(credential.response.userHandle) : null
      }
    };
  }

  const form = document.getElementById("loginForm");
  const passkeyButton = document.getElementById("passkeyBtn");
  const passkeyState = document.getElementById("passkeyState");
  const errorNode = document.getElementById("authError");
  let bootstrap = null;

  function pending(active){
    form.classList.toggle("passkey-pending", !!active);
    passkeyState.classList.toggle("active", !!active);
    passkeyButton.disabled = !!active;
  }

  async function signInWithPasskey(automatic){
    pending(true);
    try{
      const optionResponse = await fetch("/api/auth/passkey/login/options", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
      const options = await optionResponse.json();
      if(!options.available) return false;
      if(!optionResponse.ok || !options.ok) throw new Error(options.error || "Passkey sign in is not available.");
      const credential = await navigator.credentials.get({publicKey:publicKeyFromServer(options.publicKey)});
      const verifyResponse = await fetch("/api/auth/passkey/login/verify", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({challenge_id:options.challenge_id, credential:credentialToJSON(credential)})
      });
      const verified = await verifyResponse.json();
      if(!verifyResponse.ok || !verified.ok) throw new Error(verified.error || "Passkey sign in failed.");
      window.location.replace(bootstrap.next_url || "/");
      return true;
    }catch(error){
      if(!automatic || (error && error.name !== "NotAllowedError")) errorNode.textContent = error && error.message ? error.message : String(error);
      return false;
    }finally{
      pending(false);
    }
  }

  (async ()=>{
    const mode = location.pathname === "/setup" ? "setup" : (location.pathname === "/account/create" ? "create" : "login");
    const response = await fetch("/api/auth/bootstrap?mode=" + encodeURIComponent(mode) + "&next=" + encodeURIComponent(new URLSearchParams(location.search).get("next") || "/"));
    bootstrap = await response.json();
    if(!response.ok || !bootstrap.ok) throw new Error(bootstrap.error || "Could not load authentication settings.");
    document.title = bootstrap.title + " - DebriPod";
    document.getElementById("authTitle").textContent = bootstrap.title;
    document.getElementById("authSubtitle").textContent = bootstrap.subtitle;
    document.getElementById("csrfToken").value = bootstrap.csrf_token;
    document.getElementById("submitButton").textContent = bootstrap.button;
    form.action = bootstrap.action;
    const setup = !!bootstrap.setup;
    document.getElementById("confirmLabel").hidden = !setup;
    document.querySelector("input[name=confirm_password]").required = setup;
    document.getElementById("passwordInput").autocomplete = setup ? "new-password" : "current-password";
    errorNode.textContent = bootstrap.error || "";
    const supported = !!(window.PublicKeyCredential && navigator.credentials && bootstrap.passkey);
    passkeyButton.hidden = !supported;
    passkeyButton.addEventListener("click", ()=>signInWithPasskey(false));
    if(supported) signInWithPasskey(true);
  })().catch((error)=>{ errorNode.textContent = error && error.message ? error.message : "Could not load authentication settings."; });
})();
