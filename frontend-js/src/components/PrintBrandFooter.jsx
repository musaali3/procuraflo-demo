import {useEffect,useState} from 'react';
import {createPortal} from 'react-dom';
import {DOCUMENT_THEME} from '../config/documentTheme';
import {BRAND_LOGO_DATA} from '../config/brandAsset';
export const DOCUMENT_FOOTER_RULES = `
 @bottom-right {content:"Page " counter(page) " of " counter(pages) "\\A CONTROLLED DOCUMENT";white-space:pre;text-align:right;vertical-align:middle;font:8pt Arial,sans-serif;line-height:1.6;color:#526671;}
 @bottom-center {content:none;}
`;
let prepared;
export function printFooterRules(){
 return prepared ||= (async()=>{
  const image=new Image();image.src=BRAND_LOGO_DATA;await image.decode();
  const canvas=document.createElement('canvas');canvas.width=113;canvas.height=38;
  const context=canvas.getContext('2d');context.beginPath();context.roundRect(0,0,113,38,6);context.clip();context.drawImage(image,0,0,113,38);
  return `${DOCUMENT_FOOTER_RULES} @bottom-left {content:url("${canvas.toDataURL('image/png')}") "\\A ${DOCUMENT_THEME.tagline}";white-space:pre;text-align:left;vertical-align:middle;font:6.5pt Arial,sans-serif;color:#526671;}`;
 })();
}
export default function PrintBrandFooter(){
 const [rules,setRules]=useState(DOCUMENT_FOOTER_RULES);
 useEffect(()=>{printFooterRules().then(setRules);},[]);
 return createPortal(<style>{`@page {${rules}}`}</style>,document.body);
}
