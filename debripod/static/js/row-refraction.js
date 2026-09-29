(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const clipped = new Map();
  let canvas = null;
  let context = null;
  let touched = false;
  let cached = null;
  let revision = 0;

  function restore(el, previous){
    el.style.clipPath = previous.clip;
    el.style.webkitClipPath = previous.webkit;
    if(previous.rule !== undefined) el.style.clipRule = previous.rule;
    if(previous.webkitRule !== undefined) el.style.webkitClipRule = previous.webkitRule;
  }
  function clear(){
    clipped.forEach((previous, el)=>restore(el, previous));
    clipped.clear();
    cached = null;
  }
  function roundedPath(x, y, width, height, radius){
    const r = Math.max(0, Math.min(Number(radius) || 0, width / 2, height / 2));
    return "M"+(x+r)+" "+y+" H"+(x+width-r)+" Q"+(x+width)+" "+y+" "+(x+width)+" "+(y+r)+" V"+(y+height-r)+" Q"+(x+width)+" "+(y+height)+" "+(x+width-r)+" "+(y+height)+" H"+(x+r)+" Q"+x+" "+(y+height)+" "+x+" "+(y+height-r)+" V"+(y+r)+" Q"+x+" "+y+" "+(x+r)+" "+y+" Z";
  }
  // Native CSS paths avoid Safari's data-SVG image decoding flicker and keep
  // each row's existing horizontal fade mask untouched.
  function cutout(rect, lens, radius){
    if(!lens.width || !lens.height) return "none";
    const x = lens.left - rect.left;
    const y = lens.top - rect.top;
    const outerPadding = 8;
    const outer = roundedPath(0, -outerPadding, rect.width, rect.height + outerPadding * 2, 0);
    const inner = roundedPath(x, y, lens.width, lens.height, radius);
    return 'path(evenodd, "' + outer + " " + inner + '")';
  }
  function ancestorOpacity(el){
    let opacity = 1;
    let node = el;
    while(node){
      try{
        const value = Number.parseFloat(getComputedStyle(node).opacity);
        if(Number.isFinite(value)) opacity *= Math.max(0, Math.min(1, value));
      }catch(_error){}
      node = node.parentElement;
    }
    return opacity;
  }
  function collectTextRuns(elements){
    const runs=[];
    elements.forEach(el=>{
      const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
      let node;
      while((node=walker.nextNode())){
        if(!node.nodeValue.trim()) continue;
        const style=getComputedStyle(node.parentElement||el);
        if(style.visibility==="hidden"||style.display==="none") continue;
        const range=document.createRange();range.selectNodeContents(node);
        const rect=range.getBoundingClientRect();
        const fadeHost=el.closest ? (el.closest(".dpRowText, .hScrollTextScrollable")||el) : el;
        const fadeStyle=getComputedStyle(fadeHost);
        const fadeRect=fadeHost.getBoundingClientRect();
        const fadeValue=fadeStyle.getPropertyValue ? fadeStyle.getPropertyValue("--path-text-fade") : "";
        const hasFade=!!(fadeHost.classList&&fadeHost.classList.contains&&(fadeHost.classList.contains("dpRowText")||fadeHost.classList.contains("hScrollTextScrollable")));
        const fadePx=hasFade?Math.max(0,Number.parseFloat(fadeValue)||18):0;
        runs.push({node,value:node.nodeValue,rect,style,alpha:ancestorOpacity(node.parentElement||el),fadeRect,fadePx,leftFade:hasFade&&fadeHost.dataset&&fadeHost.dataset.scrollAway==="true"});
      }
    });
    return runs;
  }
  function textSignature(runs){
    return JSON.stringify(runs.map(run=>{
      const r=run.rect,f=run.fadeRect,s=run.style;
      return [run.value,r.left,r.top,r.width,r.height,f.left,f.top,f.width,f.height,run.fadePx,run.leftFade,run.alpha,s.font,s.color,s.opacity,s.letterSpacing];
    }));
  }
  function drawText(runs, bounds){
    if(!canvas){
      canvas = document.createElement("canvas");
      context = canvas.getContext("2d");
    }
    if(!context) return false;
    const scale = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.max(1, Math.ceil(bounds.width * scale));
    canvas.height = Math.max(1, Math.ceil(bounds.height * scale));
    context.setTransform(scale, 0, 0, scale, -bounds.left * scale, -bounds.top * scale);
    runs.forEach(run=>{
        const style=run.style,textRect=run.rect,fadeRect=run.fadeRect;
        const size = Number.parseFloat(style.fontSize) || 16;
        context.save();
        const padding = Math.max(2, size * .2);
        context.beginPath();
        // Keep horizontal clipping aligned with the native row fade while
        // expanding only vertically for Host Grotesk's glyph metrics.
        context.rect(fadeRect.left, textRect.top - padding, fadeRect.width, textRect.height + padding * 2);
        context.clip();
        context.font = style.font || (style.fontWeight + " " + style.fontSize + " " + style.fontFamily);
        context.fillStyle = style.color;
        context.globalAlpha = run.alpha;
        context.textBaseline = "alphabetic";
        if("letterSpacing" in context) context.letterSpacing = style.letterSpacing || "0px";
        const gradient = typeof context.createLinearGradient === "function" ? context.createLinearGradient(fadeRect.left,0,fadeRect.right,0) : null;
        if(gradient){
          const width=Math.max(1,fadeRect.width), left=run.leftFade ? Math.min(1,run.fadePx/width) : 0, right=Math.max(left,1-Math.min(1,run.fadePx/width));
          if(run.leftFade){gradient.addColorStop(0,"transparent");gradient.addColorStop(left,style.color);}
          else gradient.addColorStop(0,style.color);
          gradient.addColorStop(right,style.color);gradient.addColorStop(1,"transparent");
          context.fillStyle=gradient;
        }
        const metrics = context.measureText(run.value);
        const ascent = metrics.fontBoundingBoxAscent || metrics.actualBoundingBoxAscent || size * .8;
        const descent = metrics.fontBoundingBoxDescent || metrics.actualBoundingBoxDescent || size * .2;
        const baseline = textRect.top + (textRect.height - ascent - descent) / 2 + ascent;
        context.fillText(run.value, textRect.left, baseline);
        context.restore();
    });
    return true;
  }
  function prepare(lens, radius){
    touched = true;
    const list = document.getElementById("libList");
    if(!list){clear();return null;}
    const listRect = list.getBoundingClientRect();
    const margin = 32;
    const bounds = {left:Math.max(listRect.left,lens.left-margin),top:Math.max(listRect.top,lens.top-margin),right:Math.min(listRect.right,lens.left+lens.width+margin),bottom:Math.min(listRect.bottom,lens.top+lens.height+margin)};
    bounds.width = Math.max(0,bounds.right-bounds.left); bounds.height = Math.max(0,bounds.bottom-bounds.top);
    if(!bounds.width || !bounds.height){clear();return null;}
    const sampleRow = list.querySelector && list.querySelector(".dpStandardRow, .ipodItem");
    const sampleHeight = sampleRow ? Number(sampleRow.getBoundingClientRect().height) : 55;
    const band = Math.max(44, Number.isFinite(sampleHeight) && sampleHeight > 0 ? sampleHeight : 55) * 2;
    const bandIndex = Math.floor(Math.max(0, lens.top - listRect.top) / band);
    const stableTop = Math.max(listRect.top, listRect.top + bandIndex * band - band);
    const stableBottom = Math.min(listRect.bottom, stableTop + band * 3);
    const stableBounds={left:listRect.left,top:stableTop,width:listRect.width,height:Math.max(0,stableBottom-stableTop)};
    const elements = Array.from(list.querySelectorAll(".ipodItem:not(.sel) .glassText, .ipodItem:not(.sel) .dpRowPrimary, .ipodItem:not(.sel) .dpRowSecondary")).filter(el=>{
      const rect=el.getBoundingClientRect();
      return rect.width>0&&rect.height>0&&rect.right>stableBounds.left&&rect.left<stableBounds.left+stableBounds.width&&rect.bottom>stableBounds.top&&rect.top<stableBounds.top+stableBounds.height;
    });
    if(!elements.length){clear();return null;}
    const runs=collectTextRuns(elements);
    if(!runs.length){clear();return null;}
    const signature=JSON.stringify([stableBounds.left,stableBounds.top,stableBounds.width,stableBounds.height,textSignature(runs)]);
    if(!cached||cached.signature!==signature||!elements.every(el=>cached.elements.includes(el))){
      if(!drawText(runs,stableBounds)){clear();return null;}
      cached={signature,elements:elements.slice(),result:{canvas,bounds:stableBounds,revision:++revision}};
    }
    const retained=new Set();
    elements.forEach(el=>{
      const rect=el.getBoundingClientRect();
      if(rect.right<=lens.left||rect.left>=lens.left+lens.width||rect.bottom<=lens.top||rect.top>=lens.top+lens.height)return;
      retained.add(el);
      if(!clipped.has(el))clipped.set(el,{clip:el.style.clipPath,webkit:el.style.webkitClipPath,rule:el.style.clipRule,webkitRule:el.style.webkitClipRule});
      const value=cutout(rect,lens,radius);
      if(el.style.clipPath!==value)el.style.clipPath=value;
      if(el.style.webkitClipPath!==value)el.style.webkitClipPath=value;
      el.style.clipRule="evenodd";el.style.webkitClipRule="evenodd";
    });
    clipped.forEach((previous,el)=>{if(!retained.has(el)){restore(el,previous);clipped.delete(el);}});
    return cached.result;
  }
  root.rowRefraction={prepare,clear,beginFrame:()=>{touched=false;},endFrame:()=>{if(!touched)clear();},testing:{cutout,textSignature}};
})();
