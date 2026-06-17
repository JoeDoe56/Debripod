(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const jobs = new Map();
  let frame = 0;

  function request(key, fn){
    if(typeof fn !== "function") return;
    jobs.set(String(key || "default"), fn);
    if(frame) return;
    frame = requestAnimationFrame((ts)=>{
      frame = 0;
      const run = Array.from(jobs.entries());
      jobs.clear();
      for(const entry of run){
        try{ entry[1]({time: ts, key: entry[0]}); }catch(e){}
      }
    });
  }

  function cancel(key){
    jobs.delete(String(key || "default"));
    if(!jobs.size && frame){
      cancelAnimationFrame(frame);
      frame = 0;
    }
  }

  root.frameScheduler = {
    request,
    cancel,
    hasPending: function(){ return !!frame; }
  };
})();
