(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const masked = new Map();
  let canvas = null;
  let context = null;
  let touched = false;
  let cached = null;
  let revision = 0;
  function restore(el, previous){
    el.style.maskImage = previous.mask;
    el.style.webkitMaskImage = previous.webkit;
  }
  function clear(){
    masked.forEach((previous,el)=>restore(el,previous));
    masked.clear();
    cached = null;
  }
  function cutout(rect, lens, radius){
    const x = lens.left - rect.left, y = lens.top - rect.top;
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="'+rect.width+'" height="'+rect.height+'"><defs><mask id="c" maskUnits="userSpaceOnUse" x="0" y="0" width="'+rect.width+'" height="'+rect.height+'"><rect width="100%" height="100%" fill="white"/><rect x="'+x+'" y="'+y+'" width="'+lens.width+'" height="'+lens.height+'" rx="'+radius+'" fill="black"/></mask></defs><rect width="100%" height="100%" fill="white" mask="url(#c)"/></svg>';
    return 'url("data:image/svg+xml,'+encodeURIComponent(svg)+'")';
  }
  function prepare(lens, radius){
    touched = true;
    const list = document.getElementById("libList");
    if(!list){clear(); return null;}
    const clip = list.getBoundingClientRect();
    const margin = 32;
    const bounds = {left:Math.max(clip.left,lens.left-margin),top:Math.max(clip.top,lens.top-margin)};
    bounds.width = Math.max(0, Math.min(clip.right,lens.left+lens.width+margin)-bounds.left);
    bounds.height = Math.max(0, Math.min(clip.bottom,lens.top+lens.height+margin)-bounds.top);
    if(!bounds.width || !bounds.height){clear();return null;}
    const elements = Array.from(list.querySelectorAll(".ipodItem:not(.sel) .glassText")).filter(el=>{
      const r=el.getBoundingClientRect();
      return r.width>0 && r.height>0 && r.right>bounds.left && r.left<bounds.left+bounds.width && r.bottom>bounds.top && r.top<bounds.top+bounds.height;
    });
    if(!elements.length){clear();return null;}
    const signature = JSON.stringify([lens,radius,clip.left,clip.top,clip.right,clip.bottom,elements.map(el=>{
      const r=el.getBoundingClientRect(),style=getComputedStyle(el);
      return [el.textContent,r.left,r.top,r.width,r.height,style.font,style.color];
    })]);
    if(cached && cached.signature === signature && elements.every(el=>cached.elements.includes(el))) return cached.result;
    if(!canvas){canvas=document.createElement("canvas");context=canvas.getContext("2d");}
    if(!context){clear();return null;}
    const scale=Math.min(2,window.devicePixelRatio || 1);
    canvas.width=Math.max(1,Math.ceil(bounds.width*scale));
    canvas.height=Math.max(1,Math.ceil(bounds.height*scale));
    context.setTransform(scale,0,0,scale,-bounds.left*scale,-bounds.top*scale);
    const retained=new Set();
    elements.forEach(el=>{
      const rect=el.getBoundingClientRect();
      context.save();
      context.beginPath();context.rect(rect.left,rect.top,rect.width,rect.height);context.clip();
      // Draw individual text runs so inline artist weights remain intact.
      const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
      let node;
      while((node=walker.nextNode())){
        if(!node.nodeValue.trim()) continue;
        const style=getComputedStyle(node.parentElement);
        if(style.visibility==='hidden' || style.display==='none') continue;
        const range=document.createRange();range.selectNodeContents(node);
        const r=range.getBoundingClientRect();
        context.font=style.font || (style.fontWeight+' '+style.fontSize+' '+style.fontFamily);
        context.fillStyle=style.color;
        context.textBaseline='alphabetic';
        if('letterSpacing' in context) context.letterSpacing=style.letterSpacing;
        const metrics=context.measureText(node.nodeValue);
        const ascent=metrics.actualBoundingBoxAscent || parseFloat(style.fontSize)*.8;
        const descent=metrics.actualBoundingBoxDescent || parseFloat(style.fontSize)*.2;
        context.fillText(node.nodeValue,r.left,r.top+(r.height-ascent-descent)/2+ascent);
      }
      context.restore();
      if(rect.right>lens.left && rect.left<lens.left+lens.width && rect.bottom>lens.top && rect.top<lens.top+lens.height){
        retained.add(el);
        if(!masked.has(el)) masked.set(el,{mask:el.style.maskImage,webkit:el.style.webkitMaskImage});
        const mask=cutout(rect,lens,radius);
        el.style.maskImage=mask;el.style.webkitMaskImage=mask;
      }
    });
    masked.forEach((previous,el)=>{if(!retained.has(el)){restore(el,previous);masked.delete(el);}});
    const result={canvas,bounds,revision:++revision};
    cached={signature,elements,result};
    return result;
  }
  root.rowRefraction={prepare,clear,beginFrame:()=>{touched=false;},endFrame:()=>{if(!touched)clear();},testing:{cutout}};
})();
