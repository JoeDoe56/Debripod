(function(global){
  "use strict";
  const memo = new Map();
  const clamp = value => Math.max(0, Math.min(255, Math.round(Number(value) || 0)));
  const rgb = value => {
    if(Array.isArray(value)) return {r:clamp(value[0]), g:clamp(value[1]), b:clamp(value[2])};
    if(value && typeof value === "object") return {r:clamp(value.r), g:clamp(value.g), b:clamp(value.b)};
    let text = String(value || "").replace(/^#/, "");
    if(text.length === 3) text = text.split("").map(ch => ch + ch).join("");
    const functional = String(value || "").match(/^rgba?\(\s*([\d.]+)\s*[, ]\s*([\d.]+)\s*[, ]\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/i);
    if(functional){
      const alpha = functional[4] == null ? 1 : Math.max(0, Math.min(1, Number(functional[4])));
      return {r:clamp(Number(functional[1]) * alpha), g:clamp(Number(functional[2]) * alpha), b:clamp(Number(functional[3]) * alpha)};
    }
    const number = /^[0-9a-f]{6}$/i.test(text) ? parseInt(text, 16) : 0xffffff;
    return {r:(number >> 16) & 255, g:(number >> 8) & 255, b:number & 255};
  };
  const hex = color => "#" + [color.r, color.g, color.b].map(v => clamp(v).toString(16).padStart(2, "0")).join("");
  const channel = value => { const x = clamp(value) / 255; return x <= .04045 ? x / 12.92 : Math.pow((x + .055) / 1.055, 2.4); };
  const luminance = color => .2126 * channel(color.r) + .7152 * channel(color.g) + .0722 * channel(color.b);
  const contrast = (a, b) => { const x=luminance(a), y=luminance(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); };
  const distance = (a,b) => Math.hypot(a.r-b.r, a.g-b.g, a.b-b.b);
  const best = (background, colors) => {
    let chosen = null, ratio = -1;
    colors.forEach(color => { if(distance(background,color) < 1.5) return; const score=contrast(background,color); if(score>ratio){ chosen=color; ratio=score; } });
    let fallback = false;
    if(!chosen || ratio < 3){
      const black={r:0,g:0,b:0}, white={r:255,g:255,b:255};
      const solid = contrast(background, black) >= contrast(background, white) ? black : white;
      if(contrast(background,solid)>ratio){ chosen=solid; ratio=contrast(background,solid); fallback=true; }
    }
    return {rgb:chosen || {r:255,g:255,b:255}, contrast:ratio, fallback:fallback};
  };
  const sampleContrastText = (values, preferred) => {
    const samples = (Array.isArray(values) ? values : [values]).map(rgb).filter(Boolean);
    const candidates = [{r:0,g:0,b:0}, {r:255,g:255,b:255}];
    const preferredColor = preferred == null ? null : rgb(preferred);
    const preferredIndex = preferredColor && distance(preferredColor, candidates[0]) <= distance(preferredColor, candidates[1]) ? 0 : (preferredColor ? 1 : -1);
    if(!samples.length) return preferredIndex >= 0 ? hex(candidates[preferredIndex]) : "#ffffff";
    const score = candidate => Math.min(...samples.map(sample => contrast(sample, candidate)));
    const scores = candidates.map(score);
    const winner = scores[0] === scores[1] && preferredIndex >= 0
      ? preferredIndex
      : (scores[0] >= scores[1] ? 0 : 1);
    return hex(candidates[winner]);
  };
  function derive(values){
    const colors = (Array.isArray(values) ? values : []).map(rgb).slice(0,16);
    const palette = colors.length ? colors : [{r:255,g:76,b:76},{r:255,g:166,b:77},{r:255,g:225,b:87},{r:76,g:217,b:100},{r:90,g:200,b:250},{r:10,g:132,b:255},{r:94,g:92,b:230}];
    const identity = palette.map(hex).join("");
    if(memo.has(identity)) return memo.get(identity);
    const pairs = palette.map(color => { const item=best(color,palette); return {color:hex(color),contrast:hex(item.rgb),contrastRatio:item.contrast,fallback:item.fallback}; });
    const map={}; pairs.forEach(item => { map[item.color]=item; });
    const names=["low","lowHigh","lowMid","mid","upperMid","highLow","high"], roles={};
    names.forEach((name,index) => { const color=palette[index%palette.length], item=pairs[index%pairs.length]; roles[name]={color:hex(color),contrast:item.contrast,contrastRatio:item.contrastRatio}; });
    const selected=best(palette[0],palette).rgb;
    const result={version:1,identity:identity,colors:palette.map(hex),contrastPairs:pairs,contrastMap:map,
      metadata:{paletteColorCount:palette.length,contrastSource:"client"},roles:roles,
      ui:{darkText:hex(best({r:18,g:18,b:22},palette).rgb),lightText:hex(best({r:236,g:238,b:242},palette).rgb),
        clearEngraveA:roles.low.contrast,clearEngraveB:roles.high.contrast,selectedFallbackText:hex(selected),
        selectedFallbackPillText:hex(selected),selectedPillEdge:roles.mid.contrast,wheelText:hex(selected)}};
    memo.set(identity,result);
    return result;
  }
  function interpolate(timeline, seconds){
    const samples=timeline && Array.isArray(timeline.samples) ? timeline.samples : [];
    if(!samples.length) return [];
    const rate=Math.max(1,Number(timeline.sampleRateHz||2)), position=Math.max(0,Number(seconds||0)*rate);
    let left=samples[0], right=samples[samples.length-1];
    for(let i=0;i<samples.length;i++){ if(Number(samples[i].position)<=position) left=samples[i]; if(Number(samples[i].position)>=position){ right=samples[i]; break; } }
    const span=Math.max(1,Number(right.position)-Number(left.position)), mix=Math.max(0,Math.min(1,(position-Number(left.position))/span));
    const a=left.colors||[], b=right.colors||a, count=Math.max(a.length,b.length), out=[];
    for(let i=0;i<count;i++){ const x=rgb(a[i%a.length]||b[i%b.length]), y=rgb(b[i%b.length]||a[i%a.length]); out.push({r:clamp(x.r+(y.r-x.r)*mix),g:clamp(x.g+(y.g-x.g)*mix),b:clamp(x.b+(y.b-x.b)*mix)}); }
    return out;
  }
  global.DebriPodPalette={derive:derive,interpolate:interpolate,rgb:rgb,hex:hex,luminance:luminance,contrast:contrast,sampleContrastText:sampleContrastText};
})(window);
