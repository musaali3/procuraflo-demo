import {useEffect,useRef,useState} from 'react';
export default function HorizontalScroll({children,className='',...props}){
 const ref=useRef(null);const [edges,setEdges]=useState({overflow:false,left:false,right:false});
 useEffect(()=>{
  const node=ref.current;
  const update=()=>{const max=node.scrollWidth-node.clientWidth;setEdges(old=>{const next={overflow:max>2,left:node.scrollLeft>1,right:node.scrollLeft<max-1};return Object.keys(next).every(key=>next[key]===old[key])?old:next;});};
  const resize=new ResizeObserver(update);resize.observe(node);for(const child of node.children)resize.observe(child);
  const mutations=new MutationObserver(()=>{for(const child of node.children)resize.observe(child);update();});mutations.observe(node,{childList:true,subtree:true,characterData:true});
  node.addEventListener('scroll',update,{passive:true});update();return()=>{resize.disconnect();mutations.disconnect();node.removeEventListener('scroll',update);};
 },[]);
 const move=direction=>ref.current.scrollBy({left:direction*Math.max(160,ref.current.clientWidth*.75),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
 return <div className="horizontal-scroll-region min-w-0 max-w-full">{edges.overflow&&<div className="horizontal-scroll-controls flex justify-end gap-2 py-2 print:hidden" data-output-exclude="true"><button type="button" className="btn-secondary" disabled={!edges.left} onClick={()=>move(-1)} aria-label="Scroll content left">← Move Left</button><button type="button" className="btn-secondary" disabled={!edges.right} onClick={()=>move(1)} aria-label="Scroll content right">Move Right →</button></div>}<div {...props} ref={ref} className={`horizontal-scroll-content ${className}`} tabIndex={props.tabIndex??0} onKeyDown={event=>{if(event.target!==event.currentTarget)return;if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();move(event.key==='ArrowLeft'?-1:1);}}}>{children}</div></div>;
}
