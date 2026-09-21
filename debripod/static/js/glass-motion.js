/* Standalone geometry clock; no DebriPod element names or application state. */
(function(root){
  "use strict";
  const finite=(v,d)=>Number.isFinite(Number(v))?Number(v):d;
  function normalize(value){
    const g=Object.assign({x:0,y:0,width:0,height:0,radius:0,scaleX:1,scaleY:1},value);
    for(const k of Object.keys(g))g[k]=finite(g[k],0);
    g.width=Math.max(0,g.width);g.height=Math.max(0,g.height);
    g.radius=Math.max(0,Math.min(g.radius,Math.min(g.width,g.height)/2));
    return g;
  }
  function interpolate(from,to,progress){
    const a=normalize(from),b=normalize(to),p=Math.max(0,Math.min(1,progress)),out={};
    for(const k of Object.keys(b))out[k]=finite(a[k],b[k])+(b[k]-finite(a[k],b[k]))*p;
    return normalize(out);
  }
  function advance(from,to,elapsed,tau){
    const a=normalize(from),b=normalize(to);
    const done=Object.keys(b).every(k=>Math.abs(b[k]-finite(a[k],b[k]))<0.01);
    return interpolate(a,b,done?1:1-Math.exp(-Math.max(0,elapsed)/Math.max(1,tau||70)));
  }
  function apply(element,geometry){
    const g=normalize(geometry),s=element.style;
    s.width=g.width+'px';s.height=g.height+'px';s.borderRadius=g.radius+'px';
    s.transform='translate3d('+g.x+'px,'+g.y+'px,0) scale('+g.scaleX+','+g.scaleY+')';
    element._liquidGeometry=g;
    return g;
  }
  function animate(options){
    const frames=options.frames,now=()=>root.performance.now(),start=now();let id=0,stopped=false;
    const duration=root.matchMedia?.('(prefers-reduced-motion: reduce)').matches?0:Math.max(0,options.duration||0);
    const tick=time=>{
      if(stopped)return;
      const p=duration && (!options.visible || options.visible())?Math.min(1,(time-start)/duration):1;
      let i=1;while(i<frames.length-1 && p>frames[i].offset)i++;
      const a=frames[i-1],b=frames[i],t=Math.max(0,Math.min(1,(p-a.offset)/Math.max(.00001,b.offset-a.offset)));
      options.update(interpolate(a.value,b.value,t*t*(3-2*t)));
      if(p<1)id=root.requestAnimationFrame(tick);else{stopped=true;options.complete?.();}
    };
    id=root.requestAnimationFrame(tick);
    return {cancel(){stopped=true;root.cancelAnimationFrame(id);},get playState(){return stopped?'finished':'running';}};
  }
  root.LiquidGlassMotion={normalize,interpolate,advance,apply,animate};
  if(typeof module!=='undefined')module.exports=root.LiquidGlassMotion;
})(typeof window!=='undefined'?window:globalThis);
