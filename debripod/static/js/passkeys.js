(function(){
  const root = window.DebriPod = window.DebriPod || {};

  function isSupported(){
    return !!(window.PublicKeyCredential && navigator.credentials);
  }

  function b64urlToBuffer(value){
    var s = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
    while(s.length % 4) s += "=";
    var raw = atob(s);
    var out = new Uint8Array(raw.length);
    for(var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out.buffer;
  }

  function bufferToB64url(buffer){
    var bytes = new Uint8Array(buffer || new ArrayBuffer(0));
    var s = "";
    for(var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function creationOptionsFromServer(options){
    var out = Object.assign({}, options || {});
    out.challenge = b64urlToBuffer(out.challenge);
    if(out.user && out.user.id) out.user = Object.assign({}, out.user, {id:b64urlToBuffer(out.user.id)});
    if(Array.isArray(out.excludeCredentials)){
      out.excludeCredentials = out.excludeCredentials.map(function(c){
        return Object.assign({}, c, {id:b64urlToBuffer(c.id)});
      });
    }
    return out;
  }

  function requestOptionsFromServer(options){
    var out = Object.assign({}, options || {});
    out.challenge = b64urlToBuffer(out.challenge);
    if(Array.isArray(out.allowCredentials)){
      out.allowCredentials = out.allowCredentials.map(function(c){
        return Object.assign({}, c, {id:b64urlToBuffer(c.id)});
      });
    }
    return out;
  }

  function registrationCredentialToJSON(cred){
    var transports = [];
    try{
      if(cred.response && typeof cred.response.getTransports === "function") transports = cred.response.getTransports() || [];
    }catch(e){}
    return {
      id: cred.id,
      rawId: bufferToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufferToB64url(cred.response.clientDataJSON),
        attestationObject: bufferToB64url(cred.response.attestationObject),
        transports: transports
      },
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {}
    };
  }

  function authenticationCredentialToJSON(cred){
    return {
      id: cred.id,
      rawId: bufferToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufferToB64url(cred.response.clientDataJSON),
        authenticatorData: bufferToB64url(cred.response.authenticatorData),
        signature: bufferToB64url(cred.response.signature),
        userHandle: cred.response.userHandle ? bufferToB64url(cred.response.userHandle) : null
      },
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {}
    };
  }

  async function registeredPasskeys(){
    const js = await root.apiClient.apiGet("/api/auth/passkeys");
    return Array.isArray(js && js.passkeys) ? js.passkeys : [];
  }

  async function register(options){
    if(!isSupported()){
      return {ok:false, error:"Passkey sign in is not available in this browser. Use your password."};
    }
    options = options || {};
    let password = "";
    if(options.requirePassword){
      password = prompt("Enter your DebriPod password to add a passkey", "");
      if(password == null) return {ok:false, error:"Passkey setup cancelled."};
    }
    const res = await root.apiClient.apiPost("/api/auth/passkey/register/options", {password:password});
    const js = res && res.json ? res.json : {};
    if(!res || !res.ok || !js.ok){
      return {ok:false, error:(js && js.error) || "Passkey setup is not available."};
    }
    const cred = await navigator.credentials.create({publicKey: creationOptionsFromServer(js.publicKey)});
    const verify = await root.apiClient.apiPost("/api/auth/passkey/register/verify", {
      challenge_id: js.challenge_id,
      credential: registrationCredentialToJSON(cred)
    });
    const out = verify && verify.json ? verify.json : {};
    if(!verify || !verify.ok || !out.ok){
      return {ok:false, error:(out && out.error) || "Passkey setup failed."};
    }
    return out;
  }

  function gateElements(){
    return {
      gate: document.getElementById("passkeyGate"),
      add: document.getElementById("passkeyGateAdd"),
      skip: document.getElementById("passkeyGateSkip"),
      error: document.getElementById("passkeyGateError")
    };
  }

  function setGateError(text){
    const els = gateElements();
    if(els.error) els.error.textContent = String(text || "");
  }

  function setGateBusy(busy){
    const els = gateElements();
    if(els.add) els.add.disabled = !!busy;
    if(els.skip) els.skip.disabled = !!busy;
    if(els.add) els.add.textContent = busy ? "Creating..." : "Create Passkey";
  }

  async function maybeOfferAfterLogin(){
    if(!isSupported()) return false;
    let status = null;
    try{ status = await root.apiClient.apiGet("/api/auth/status"); }catch(e){ return false; }
    if(!status || !status.logged_in) return false;
    const username = String(status.username || "");
    const skipKey = "debripod.passkeyOfferSkipped." + username;
    try{
      if(sessionStorage.getItem(skipKey) === "1") return false;
    }catch(e){}
    let existing = [];
    try{ existing = await registeredPasskeys(); }catch(e){ existing = []; }
    if(existing.length) return false;
    const els = gateElements();
    if(!els.gate || !els.add || !els.skip) return false;
    els.gate.hidden = false;
    setGateError("");
    setGateBusy(false);
    return await new Promise((resolve)=>{
      const finish = (value)=>{
        els.gate.hidden = true;
        resolve(value);
      };
      els.skip.onclick = function(){
        try{ sessionStorage.setItem(skipKey, "1"); }catch(e){}
        finish(false);
      };
      els.add.onclick = async function(){
        setGateError("");
        setGateBusy(true);
        try{
          const result = await register({requirePassword:false});
          if(result && result.ok){
            finish(true);
            return;
          }
          setGateError((result && result.error) || "Passkey setup failed. You can keep using your password.");
        }catch(e){
          setGateError(String(e && e.message ? e.message : e));
        }finally{
          setGateBusy(false);
        }
      };
    });
  }

  async function login(){
    if(!isSupported()){
      return {ok:false, error:"Passkey sign in is not available in this browser. Use your password."};
    }
    const res = await root.apiClient.apiPost("/api/auth/passkey/login/options", {});
    const js = res && res.json ? res.json : {};
    if(!res || !res.ok || !js.ok){
      return {ok:false, error:(js && js.error) || "Passkey sign in is not available."};
    }
    const cred = await navigator.credentials.get({publicKey: requestOptionsFromServer(js.publicKey)});
    const verify = await root.apiClient.apiPost("/api/auth/passkey/login/verify", {
      challenge_id: js.challenge_id,
      credential: authenticationCredentialToJSON(cred)
    });
    const out = verify && verify.json ? verify.json : {};
    if(!verify || !verify.ok || !out.ok){
      return {ok:false, error:(out && out.error) || "Passkey sign in failed."};
    }
    return out;
  }

  root.passkeys = {isSupported, register, login, registeredPasskeys, maybeOfferAfterLogin};
})();
