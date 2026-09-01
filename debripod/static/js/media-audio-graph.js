(function(root){
  "use strict";

  const records = new WeakMap();
  const knownRecords = new Set();
  let audioContext = null;
  let activeElement = null;
  let volume = 1;

  function clampVolume(value){
    const n = Number(value);
    return Math.max(0, Math.min(1, Number.isFinite(n) ? n : 0));
  }

  function getContext(){
    if(audioContext) return audioContext;
    const AudioContextClass = root.AudioContext || root.webkitAudioContext;
    if(!AudioContextClass) return null;
    try{
      audioContext = new AudioContextClass();
      return audioContext;
    }catch(error){
      return null;
    }
  }

  function setNativeVolume(element, value){
    if(!element) return;
    try{
      element.muted = false;
      element.volume = clampVolume(value);
    }catch(error){}
  }

  function ensureRecord(element){
    if(!element) return null;
    const existing = records.get(element);
    if(existing) return existing;
    const context = getContext();
    if(!context) return null;
    try{
      const source = context.createMediaElementSource(element);
      const analyser = context.createAnalyser();
      const gain = context.createGain();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.62;
      source.connect(analyser);
      analyser.connect(gain);
      gain.connect(context.destination);
      const record = {
        element: element,
        source: source,
        analyser: analyser,
        gain: gain,
        frequencyData: new Uint8Array(analyser.frequencyBinCount),
        timeData: new Uint8Array(analyser.fftSize)
      };
      records.set(element, record);
      knownRecords.add(record);
      return record;
    }catch(error){
      return null;
    }
  }

  function applyActiveVolume(){
    knownRecords.forEach((record)=>{
      try{ record.gain.gain.value = record.element === activeElement ? volume : 0; }catch(error){}
    });
    const activeRecord = activeElement ? records.get(activeElement) : null;
    if(activeElement){
      if(activeRecord){
        try{
          activeElement.muted = false;
          activeElement.volume = 1;
        }catch(error){}
      }else{
        setNativeVolume(activeElement, volume);
      }
    }
  }

  function setActiveElement(element){
    activeElement = element || null;
    if(activeElement && audioContext) ensureRecord(activeElement);
    applyActiveVolume();
    return !!(activeElement && records.get(activeElement));
  }

  function setVolume(value){
    volume = clampVolume(value);
    applyActiveVolume();
    return volume;
  }

  function unlock(){
    const context = getContext();
    if(!context) return Promise.resolve(false);
    if(activeElement) ensureRecord(activeElement);
    applyActiveVolume();
    try{
      if(context.state === "suspended" && typeof context.resume === "function"){
        return Promise.resolve(context.resume()).then(()=>true).catch(()=>false);
      }
    }catch(error){}
    return Promise.resolve(true);
  }

  function getFrequencyData(element){
    const record = records.get(element || activeElement);
    if(!record) return null;
    try{
      record.analyser.getByteFrequencyData(record.frequencyData);
      return record.frequencyData;
    }catch(error){
      return null;
    }
  }

  function getRms(element){
    const record = records.get(element || activeElement);
    if(!record) return 0;
    try{
      record.analyser.getByteTimeDomainData(record.timeData);
      let total = 0;
      for(let index = 0; index < record.timeData.length; index++){
        const sample = (Number(record.timeData[index]) - 128) / 128;
        total += sample * sample;
      }
      return Math.min(1, Math.sqrt(total / Math.max(1, record.timeData.length)));
    }catch(error){
      return 0;
    }
  }

  root.DebriPod = root.DebriPod || {};
  root.DebriPod.mediaAudioGraph = {
    unlock: unlock,
    setActiveElement: setActiveElement,
    setVolume: setVolume,
    getFrequencyData: getFrequencyData,
    getRms: getRms,
    isRouted: (element)=>!!records.get(element),
    testing: {
      getRecord: (element)=>records.get(element) || null,
      getActiveElement: ()=>activeElement,
      getContext: ()=>audioContext
    }
  };
})(window);
