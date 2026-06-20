(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const oneShotJobs = new Map();
  const tasks = new Map();
  const work = {
    refreshSources: false,
    metrics: false,
    render: false,
    textContrast: false,
    keepAlive: false
  };
  let frame = 0;
  let running = false;
  let lastTime = 0;
  let longFrames = 0;
  let frameCount = 0;
  let qualityBias = 1;
  const frameSamples = [];

  function request(key, fn){
    if(typeof fn !== "function") return;
    oneShotJobs.set(String(key || "default"), fn);
    schedule();
  }

  function cancel(key){
    oneShotJobs.delete(String(key || "default"));
    tasks.delete(String(key || "default"));
    if(!oneShotJobs.size && !tasks.size && !hasWork() && frame){
      cancelAnimationFrame(frame);
      frame = 0;
    }
  }

  function hasWork(){
    return work.refreshSources || work.metrics || work.render || work.textContrast || work.keepAlive || oneShotJobs.size || tasks.size;
  }

  function schedule(){
    if(frame || running) return;
    frame = requestAnimationFrame(runFrame);
  }

  function mark(flags){
    if(typeof flags === "string") work[flags] = true;
    else if(flags && typeof flags === "object"){
      Object.keys(flags).forEach((key)=>{ if(flags[key]) work[key] = true; });
    }else{
      work.render = true;
    }
    schedule();
  }

  function register(key, fn, options){
    if(typeof fn !== "function") return;
    tasks.set(String(key || "default"), {fn: fn, options: Object.assign({persistent:true}, options || {})});
    schedule();
  }

  function unregister(key){
    tasks.delete(String(key || "default"));
  }

  function consumeWork(){
    const snapshot = Object.assign({}, work);
    work.refreshSources = false;
    work.metrics = false;
    work.render = false;
    work.textContrast = false;
    work.keepAlive = false;
    return snapshot;
  }

  function runFrame(ts){
    frame = 0;
    running = true;
    const delta = lastTime ? Math.max(0, ts - lastTime) : 16.7;
    lastTime = ts;
    frameCount += 1;
    frameSamples.push(ts);
    while(frameSamples.length && ts - frameSamples[0] > 1000) frameSamples.shift();
    if(delta > 34) longFrames += 1;
    if(delta > 24) qualityBias = Math.max(0.55, qualityBias * 0.92);
    else if(delta < 18) qualityBias = Math.min(1, qualityBias + 0.015);
    const flags = consumeWork();
    const frameState = {
      time: ts,
      timestamp: ts,
      delta,
      flags,
      qualityBias,
      hidden: !!document.hidden,
      frameCount,
      longFrames
    };
    const run = Array.from(oneShotJobs.entries());
    oneShotJobs.clear();
    for(const entry of run){
      try{ entry[1](Object.assign({key: entry[0]}, frameState)); }catch(e){}
    }
    const taskRun = Array.from(tasks.entries());
    for(const entry of taskRun){
      const task = entry[1];
      try{
        const keep = task.fn(Object.assign({key: entry[0]}, frameState));
        if(task.options && task.options.persistent === false && keep !== true) tasks.delete(entry[0]);
      }catch(e){
        if(task.options && task.options.persistent === false) tasks.delete(entry[0]);
      }
    }
    running = false;
    if(!document.hidden && (work.keepAlive || work.render || work.metrics || work.refreshSources || work.textContrast || oneShotJobs.size)){
      schedule();
    }
  }

  root.frameScheduler = {
    request,
    cancel,
    mark,
    requestWork: mark,
    register,
    unregister,
    hasPending: function(){ return !!frame; },
    isRunning: function(){ return running; },
    stats: function(){
      const fps = frameSamples.length > 1 ? (frameSamples.length - 1) * 1000 / Math.max(1, frameSamples[frameSamples.length - 1] - frameSamples[0]) : 0;
      return {frameCount, longFrames, fps, qualityBias, pending: !!frame, tasks: tasks.size};
    }
  };
})();
