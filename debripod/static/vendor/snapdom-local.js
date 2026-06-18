(function(){
  window.snapdom = window.snapdom || {
    toCanvas: function(target, options){
      if(typeof window.html2canvas === "function"){
        return window.html2canvas(target, options || {});
      }
      return Promise.reject(new Error("snapdom local shim requires html2canvas"));
    }
  };
})();
