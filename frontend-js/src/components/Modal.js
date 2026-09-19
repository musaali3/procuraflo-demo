import HorizontalScroll from './HorizontalScroll';
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useBranding } from '../contexts/BrandingContext';
import { CompanyLogo, ProductBrand } from './Branding';
export default function Modal({ title, onClose, children, wide, }) {
    const { company } = useBranding();
    const panel=useRef(null),drag=useRef(null);
    const [offset,setOffset]=useState({x:0,y:0});
    function move(x,y){
        const rect=panel.current.getBoundingClientRect();const baseX=rect.left-offset.x,baseY=rect.top-offset.y;
        setOffset({x:Math.max(4-baseX,Math.min(innerWidth-rect.width-4-baseX,x)),y:Math.max(4-baseY,Math.min(innerHeight-rect.height-4-baseY,y))});
    }
    function startDrag(event){if(event.button!==0||event.target.closest('button,input,a,select,textarea'))return;drag.current={x:event.clientX,y:event.clientY,offset};event.currentTarget.setPointerCapture(event.pointerId);event.preventDefault();}
    function dragMove(event){if(drag.current)move(drag.current.offset.x+event.clientX-drag.current.x,drag.current.offset.y+event.clientY-drag.current.y);}
    useEffect(()=>{const reset=()=>setOffset({x:0,y:0});window.addEventListener('resize',reset);return()=>window.removeEventListener('resize',reset);},[]);

    useEffect(() => {
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        const closeOnEscape = (event) => { if (event.key === 'Escape')
            onClose(); };
        document.addEventListener('keydown', closeOnEscape);
        return () => {
            document.body.style.overflow = previousOverflow;
            document.removeEventListener('keydown', closeOnEscape);
        };
    }, [onClose]);
    return createPortal(_jsx("div", { className: "fixed inset-0 z-[100] overflow-y-auto overscroll-contain bg-slate-950/55 p-2 backdrop-blur-sm sm:p-6", role: "dialog", "aria-modal": "true", "aria-label": title, children: _jsx("div", { className: "flex min-h-full items-center justify-center", children: _jsxs("div", { ref:panel,style:{transform:`translate(${offset.x}px,${offset.y}px)`},className: `app-modal-panel flex w-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-blue-200 ${wide ? 'max-w-[94rem]' : 'max-w-2xl'} max-h-[calc(100dvh-1rem)] sm:max-h-[calc(100dvh-2rem)]`, children: [_jsxs("div", { onPointerDown:startDrag,onPointerMove:dragMove,onPointerUp:()=>{drag.current=null;},onPointerCancel:()=>{drag.current=null;},className: "app-modal-header relative z-20 flex shrink-0 items-center justify-between border-b border-blue-100 bg-gradient-to-r from-blue-50 via-sky-50 to-teal-50 px-4 py-3 sm:px-5 sm:py-4", children: [_jsxs("div", { className: "flex min-w-0 items-center gap-3", children: [_jsx(ProductBrand, { compact: true }), _jsx(CompanyLogo, { company: company, size: "nav" }), _jsx("h3", { className: "modal-move-handle truncate font-semibold text-blue-900",tabIndex:0,role:"button","aria-label":`Move ${title}. Drag or use arrow keys. Home centers the window.`,title:"Drag to move. Arrow keys move the window; Home centers it.",onKeyDown:event=>{const steps={ArrowLeft:[-32,0],ArrowRight:[32,0],ArrowUp:[0,-32],ArrowDown:[0,32]};if(event.key==='Home'){event.preventDefault();setOffset({x:0,y:0});}else if(steps[event.key]){event.preventDefault();const [x,y]=steps[event.key];move(offset.x+x,offset.y+y);}},children: title })] }), _jsx("button",{type:"button",className:"btn-secondary ml-auto mr-2 px-3 py-1.5 text-xs",onClick:()=>setOffset({x:0,y:0}),children:"Center","aria-label":"Center window"}), _jsxs("button", { type: "button", onClick: onClose, className: "btn-secondary flex items-center gap-1.5 px-3 py-1.5 text-xs", "aria-label": `Close ${title}`, children: [_jsx("span", { "aria-hidden": "true", className: "text-base leading-none", children: "\u00D7" }), " Close"] })] }), _jsx("div", { className: "min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-4", children: _jsx(HorizontalScroll,{children}) }), _jsx("div", { className: "app-modal-footer relative z-20 flex shrink-0 justify-end border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur print:hidden sm:px-5", children: _jsx("button", { type: "button", onClick: onClose, className: "btn-secondary", "aria-label": `Close ${title}`, children: "Close" }) })] }) }) }), document.body);
}
