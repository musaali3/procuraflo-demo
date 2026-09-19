import { printFooterRules } from '../components/PrintBrandFooter';
import { outputSource, outputError, documentClone, waitForImages } from './documentOutput';
export const COMPANY_COPY = { title: 'COMPANY RECORD COPY', purpose: 'Official controlled copy — retain in the company document record.' };
export async function printControlledCopySet(documentId, copies, options={}) {
    let root,style;
    try {
        const source=outputSource(documentId);
        const DOCUMENT_FOOTER_RULES=await printFooterRules();
        if(!copies?.length)throw new Error('Select at least one print copy.');
        const landscape=options.orientation==='landscape'||source.classList.contains('executive-report');
        document.getElementById('dual-copy-print-root')?.remove();document.getElementById('a4-print-rule')?.remove();
        root=document.createElement('div');root.id='dual-copy-print-root';
        style=document.createElement('style');style.id='a4-print-rule';
        style.textContent=`@page {size:A4 ${landscape?'landscape':'portrait'};margin:10mm 10mm 26mm; ${DOCUMENT_FOOTER_RULES}} @media print {#dual-copy-print-root .controlled-print-copy {page:auto!important;} #dual-copy-print-root .controlled-document-clone {page:auto!important;width:100%!important;max-width:none!important;min-width:0!important;} body.dual-copy-print {width:auto!important;min-height:0!important;} #dual-copy-print-root {position:static!important;width:100%!important;} #dual-copy-print-root .executive-report {page:auto!important;} #dual-copy-print-root :is(.page-counter,.print-page-number)::after {content:none!important;} }`;
        copies.forEach((copy,index)=>{
            const page=document.createElement('section');page.className='controlled-print-copy';
            page.append(documentClone(source));root.appendChild(page);
            if(copy.title){

                const label=JSON.stringify(copy.title);
                style.textContent+=` @page {size:A4 ${landscape?'landscape':'portrait'};margin:10mm 10mm 26mm;${DOCUMENT_FOOTER_RULES} @bottom-center {content:${label}!important;vertical-align:top;padding-top:1mm;white-space:nowrap;font:bold 8pt Arial,sans-serif;color:#526671;} }`;
            }
        });
        document.head.appendChild(style);document.body.appendChild(root);document.body.classList.add('dual-copy-print');
        await waitForImages(root);
        const footer=document.getElementById('procuraflo-print-footer');if(footer)await waitForImages(footer);
        const cleanup=()=>{root?.remove();style?.remove();document.body.classList.remove('dual-copy-print');window.removeEventListener('afterprint',cleanup);};
        window.addEventListener('afterprint',cleanup,{once:true});
        await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
        window.print();
        return {success:true};
    } catch(error) {root?.remove();style?.remove();document.body.classList.remove('dual-copy-print');return outputError(error);}
}
export function printElement(documentId) {
    return printControlledCopySet(documentId, [COMPANY_COPY]);
}
export const PO_VENDOR_COPY = { title: 'VENDOR ISSUE COPY', purpose: 'Issued to the vendor for order fulfilment, delivery and invoice reference.' };
export const GRN_VENDOR_COPY = { title: 'VENDOR ACKNOWLEDGEMENT COPY', purpose: 'Issued to the vendor as evidence of the quantities received and inspected.' };
export const MANAGEMENT_COPY = { title: 'HIGHER MANAGEMENT REVIEW COPY', purpose: 'Presented to the authorized management signatory for decision and signature.' };
export const FINANCE_COPY = { title: 'EXTERNAL HANDOFF COPY', purpose: 'Controlled supporting evidence exported by Supply Chain for the external Finance process.' };
export const FINANCE_PROCESSING_COPY = { title: 'FINANCE PROCESSING COPY', purpose: 'Primary controlled copy for invoice verification and payment processing.' };
export const VENDOR_REFERENCE_COPY = { title: 'VENDOR REFERENCE COPY', purpose: 'Supplier reference copy confirming the documents presented for payment verification.' };
export const WAREHOUSE_RECORD_COPY = { title: 'WAREHOUSE RECORD COPY', purpose: 'Internal receipt-control copy retained with the warehouse receiving record.' };
