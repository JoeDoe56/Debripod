(function(){
  if(window.Hls) return;
  function Hls(){
    this._media = null;
    this._src = "";
  }
  Hls.isSupported = function(){ return false; };
  Hls.Events = {
    MEDIA_ATTACHED: "hlsMediaAttached",
    MANIFEST_PARSED: "hlsManifestParsed",
    ERROR: "hlsError"
  };
  Hls.prototype.loadSource = function(src){ this._src = String(src || ""); };
  Hls.prototype.attachMedia = function(media){ this._media = media || null; };
  Hls.prototype.on = function(){};
  Hls.prototype.startLoad = function(){};
  Hls.prototype.destroy = function(){ this._media = null; this._src = ""; };
  window.Hls = Hls;
})();
