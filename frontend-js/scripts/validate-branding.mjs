import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';

const result = await build({stdin:{contents:`
import { jsPDF } from 'jspdf';
import { drawPdfBrandFooter, DOCUMENT_THEME } from './src/config/documentTheme.js';
import { BRAND_LOGO_DATA } from './src/config/brandAsset.js';
import { brandedSpreadsheetHtml } from './src/utils/brandedSpreadsheet.js';
export { BRAND_LOGO_DATA, DOCUMENT_THEME, brandedSpreadsheetHtml };
export function makePdf() {
  const pdf = new jsPDF();
  for (let page=1; page<=3; page++) {
    if (page>1) pdf.addPage();
    drawPdfBrandFooter(pdf, {pageWidth:210,pageHeight:297,margin:8,footerTop:278,pageLabel:'Page '+page+' of 3'});
  }
  return pdf.output();
}`,resolveDir:process.cwd()},bundle:true,platform:'node',format:'cjs',write:false});
const compiled={exports:{}};
new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),compiled,compiled.exports);
const {BRAND_LOGO_DATA,DOCUMENT_THEME,brandedSpreadsheetHtml,makePdf}=compiled.exports;
const original=await readFile('public/branding/procuraflo-logo.png');
assert.deepEqual(Buffer.from(BRAND_LOGO_DATA.split(',')[1],'base64'),original);
assert.equal(DOCUMENT_THEME.logo,BRAND_LOGO_DATA);
const pdf=makePdf();
assert.equal((pdf.match(/CONTROLLED DOCUMENT/g)||[]).length,3);
assert.equal((pdf.match(/Supply Chain Control System/g)||[]).length,3);
assert.ok(!pdf.includes('Powered by'));
for(let n=1;n<=3;n++)assert.ok(pdf.includes('Page '+n+' of 3'));
assert.equal((pdf.match(/\/I0 Do/g)||[]).length,3);
const html=brandedSpreadsheetHtml({companyName:'A & B',title:'Report',tableHtml:'<table><tr><td>42</td></tr></table>'});
assert.ok(html.includes(BRAND_LOGO_DATA));
assert.ok(html.includes('alt="Procuraflo"'));
assert.ok(!html.includes('class="footer"'));
assert.ok(html.includes('border-radius:12px'));
assert.ok(html.includes('A &amp; B'));
assert.ok(html.includes('<td>42</td>'));
console.log('Branding PASS: original logo bytes, three PDF pages, offline spreadsheet logo and data.');

const printFooter=await readFile('src/components/PrintBrandFooter.jsx','utf8');
assert.ok(printFooter.includes('counter(page)'));
assert.ok(printFooter.includes('counter(pages)'));
assert.ok(printFooter.includes('A CONTROLLED DOCUMENT'));
assert.ok(!printFooter.includes('poweredBy'));
const footerBody=await readFile('src/components/Branding.js','utf8');
assert.ok(!footerBody.includes('print-page-number'));
assert.ok(!footerBody.includes('DOCUMENT_THEME.poweredBy'));
