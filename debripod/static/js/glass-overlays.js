/* Reusable content replacement, independent of layout and geometry motion. */
(function(root){
  "use strict";
  const duration=135, active=new WeakMap(), running=new Set();let observer=null;
  const segment=text=>root.Intl?.Segmenter?Array.from(new Intl.Segmenter(undefined,{granularity:'grapheme'}).segment(text),x=>x.segment):Array.from(text);
  // LCS retains each unchanged character, including stable runs in the middle.
  function changes(before,after){
    const a=segment(before),b=segment(after),same=new Set();
    if(a.length*b.length>65536){let i=0,j=0;while(i<a.length&&a[i]===b[i])same.add(i++);while(j<a.length-i&&j<b.length-i&&a[a.length-1-j]===b[b.length-1-j])same.add(b.length-1-j++);}
    else{
      const table=Array.from({length:a.length+1},()=>new Uint16Array(b.length+1));
      for(let i=a.length-1;i>=0;i--)for(let j=b.length-1;j>=0;j--)table[i][j]=a[i]===b[j]?1+table[i+1][j+1]:Math.max(table[i+1][j],table[i][j+1]);
      let i=0,j=0;while(i<a.length&&j<b.length){if(a[i]===b[j]){same.add(j);i++;j++;}else if(table[i+1][j]>=table[i][j+1])i++;else j++;}
    }
    const runs=[];b.forEach((char,index)=>{const changed=!same.has(index),last=runs.at(-1);if(last&&last.changed===changed)last.text+=char;else runs.push({text:char,changed});});
    return runs;
  }
  function visible(el){
    if(!el?.isConnected || root.document.hidden || root.matchMedia?.('(prefers-reduced-motion: reduce)').matches)return false;
    if(el.closest('script,style,textarea,input,select,[aria-hidden="true"],[data-liquid-overlay],.liquidOverlayGhost'))return false;
    for(let p=el;p&&p!==root.document.documentElement;p=p.parentElement){const s=root.getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}
    const r=el.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.right>0&&r.top<root.innerHeight&&r.left<root.innerWidth;
  }
  function watch(){if(observer)observer.observe(root.document.body,{subtree:true,childList:true,characterData:true,characterDataOldValue:true,attributes:true,attributeFilter:['src','hidden'],attributeOldValue:true});}
  function write(fn){observer?.disconnect();try{return fn();}finally{watch();}}
  // Overlay attachments follow their host without changing its layout or scroll position.
  function attach(host,content,options={}){
    const portal=root.document.createElement('span'),style=root.getComputedStyle(host);
    portal.dataset.liquidOverlay='';portal.setAttribute('aria-hidden','true');
    portal.style.cssText='position:fixed;pointer-events:none;overflow:hidden;z-index:2147483000;box-sizing:border-box;';
    for(const key of ['font','letterSpacing','lineHeight','textAlign','whiteSpace','color','padding'])portal.style[key]=style[key];
    portal.append(content);write(()=>root.document.body.append(portal));
    let frame=0,disposed=false;
    const sync=()=>{if(disposed)return;if(!visible(host)){dispose();options.hidden?.();return;}const r=host.getBoundingClientRect();Object.assign(portal.style,{left:r.left+'px',top:r.top+'px',width:r.width+'px',height:r.height+'px'});frame=root.requestAnimationFrame(sync);};
    const dispose=()=>{if(disposed)return;disposed=true;root.cancelAnimationFrame(frame);write(()=>portal.remove());};
    sync();return {element:portal,dispose};
  }
  function animateText(node,previous){
    const el=node.parentElement,next=node.data;
    if(previous===next || !previous || !next || !visible(el) || !el.animate)return;
    active.get(el)?.();if(!node.isConnected)return;
    const pieces=changes(previous,next),outgoing=changes(next,previous);
    const oldContent=root.document.createElement('span'),oldSpans=[];
    for(const part of outgoing){const span=root.document.createElement('span');span.textContent=part.text;if(!part.changed)span.style.visibility='hidden';else{span.style.cssText='display:inline-block;white-space:pre;transform-origin:center';oldSpans.push(span);}oldContent.append(span);}
    let cleanup;
    const ghost=attach(el,oldContent,{hidden:()=>cleanup?.()});
    const exits=oldSpans.map(span=>span.animate([{filter:'blur(0)',transform:'scale(1)',opacity:1},{filter:'blur(3px)',transform:'scale(1.08)',opacity:0}],{duration,easing:'ease-out'}));
    const exit={finished:Promise.all(exits.map(a=>a.finished.catch(()=>{}))),cancel:()=>exits.forEach(a=>a.cancel())};
    const spans=[],fragment=root.document.createDocumentFragment();
    for(const part of pieces){if(!part.changed){fragment.append(root.document.createTextNode(part.text));continue;}
      const span=root.document.createElement('span');span.dataset.liquidOverlay='';span.textContent=part.text;
      span.style.cssText='display:inline-block;white-space:pre;transform-origin:center;';spans.push(span);fragment.append(span);
    }
    write(()=>node.replaceWith(fragment));
    let finished=false;
    cleanup=()=>{if(finished)return;finished=true;ghost.dispose();exit.cancel();write(()=>{for(const span of spans){for(const anim of span.getAnimations?.()||[])anim.cancel();if(span.isConnected)span.replaceWith(root.document.createTextNode(span.textContent));}el.normalize();});active.delete(el);running.delete(cleanup);};
    active.set(el,cleanup);running.add(cleanup);
    Promise.all([exit.finished.catch(()=>{}),...spans.map(span=>span.animate([{filter:'blur(3px)',transform:'scale(1.12)',opacity:.15},{filter:'blur(0)',transform:'scale(1)',opacity:1}],{duration,easing:'cubic-bezier(.2,.8,.2,1)'}).finished.catch(()=>{}))]).then(cleanup);
  }
  function animateSymbol(el,oldSource){
    if(!oldSource||!visible(el)||!el.animate)return;
    active.get(el)?.();const animations=[];
    const rect=el.getBoundingClientRect(),ghost=el.cloneNode(true);
    ghost.removeAttribute('id');ghost.classList.add('liquidOverlayGhost');ghost.setAttribute('aria-hidden','true');ghost.src=oldSource;
    ghost.style.cssText+=';position:fixed;pointer-events:none;z-index:2147483000;margin:0;left:'+rect.left+'px;top:'+rect.top+'px;width:'+rect.width+'px;height:'+rect.height+'px;';
    ghost.style.maskImage='url("'+oldSource.replace(/"/g,'%22')+'")';ghost.style.webkitMaskImage=ghost.style.maskImage;
    write(()=>root.document.body.append(ghost));
    animations.push(ghost.animate([{filter:'blur(0)',scale:'1',opacity:1},{filter:'blur(3px)',scale:'1.12',opacity:0}],{duration,easing:'ease-out'}));
    animations.push(el.animate([{filter:'blur(3px)',scale:'.9',opacity:.1},{filter:'blur(0)',scale:'1',opacity:1}],{duration,easing:'ease-out'}));
    let finished=false;const cleanup=()=>{if(finished)return;finished=true;for(const a of animations)a.cancel();write(()=>ghost.remove());active.delete(el);running.delete(cleanup);};active.set(el,cleanup);running.add(cleanup);
    Promise.all(animations.map(a=>a.finished.catch(()=>{}))).then(cleanup);
  }
  function textLeaves(nodes){
    const found=new Map();
    const visit=(node,path)=>{
      if(node.nodeType===3){found.set(path,node);return;}
      if(node.nodeType!==1||node.matches('script,style,[data-liquid-overlay],.liquidOverlayGhost'))return;
      const key=node.getAttribute('data-liquid-key')||node.id;
      if(key)path='key:'+key;
      Array.from(node.childNodes).forEach((child,i)=>visit(child,path+'/'+i));
    };
    Array.from(nodes).forEach((node,i)=>visit(node,String(i)));return found;
  }
  function stop(){observer?.disconnect();observer=null;for(const cancel of running)cancel();}
  function start(){
    if(observer)return;
    if(!root.MutationObserver||!root.document.body)return;
    observer=new root.MutationObserver(records=>{
      const pending=new Map();
      for(const r of records){
        if(r.target.nodeType===1&&r.target.closest('[data-liquid-overlay],.liquidOverlayGhost'))continue;
        if(r.type==='attributes'){
          if(r.attributeName==='src'&&r.target.hasAttribute('data-liquid-symbol'))animateSymbol(r.target,r.oldValue);
          else if(r.attributeName==='hidden'&&r.oldValue!==null&&!r.target.hidden&&visible(r.target))r.target.animate?.([{filter:'blur(3px)',scale:'.9',opacity:.1},{filter:'blur(0)',scale:'1',opacity:1}],{duration,easing:'ease-out'});
          continue;
        }
        if(r.type==='characterData'){if(!pending.has(r.target))pending.set(r.target,r.oldValue||'');continue;}
        if(r.type==='childList'&&r.removedNodes.length&&r.addedNodes.length){
          const old=textLeaves(r.removedNodes),next=textLeaves(r.addedNodes);
          for(const [key,node] of next){const previous=old.get(key);if(previous&&previous.data!==node.data&&!pending.has(node))pending.set(node,previous.data);}
        }
        if(r.type==='childList'&&r.target.childNodes.length===1&&r.target.firstChild.nodeType===3){
          const previous=Array.from(r.removedNodes).map(n=>n.textContent||'').join('');if(previous&&!pending.has(r.target.firstChild))pending.set(r.target.firstChild,previous);
        }
      }
      for(const [node,previous] of pending)if(node.isConnected)animateText(node,previous);
    });watch();
  }
  root.LiquidGlassOverlays={changes,visible,attach,animateText,animateSymbol,start,stop};
  if(root.document){root.document.addEventListener('visibilitychange',()=>{if(root.document.hidden)for(const cancel of running)cancel();});if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',start,{once:true});else start();}
  if(typeof module!=='undefined')module.exports=root.LiquidGlassOverlays;
})(typeof window!=='undefined'?window:globalThis);
