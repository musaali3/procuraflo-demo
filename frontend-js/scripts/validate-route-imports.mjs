import {existsSync,readFileSync,readdirSync} from 'node:fs';
import {dirname,extname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const src=join(root,'src');
const appPath=join(src,'App.js');
const app=readFileSync(appPath,'utf8');
const failures=[];
const imports=[...app.matchAll(/import\(["'](.+?)["']\)/g)].map(match=>match[1]);
for(const target of imports){
  if(!['.js','.jsx'].includes(extname(target)))failures.push(`Lazy import is not explicit: ${target}`);
  const absolute=resolve(dirname(appPath),target);
  if(!existsSync(absolute))failures.push(`Lazy import target does not exist: ${target}`);
  else if(!/export\s+default/.test(readFileSync(absolute,'utf8')))failures.push(`Lazy page has no default export: ${target}`);
}
const routes=new Set([...app.matchAll(/path:\s*["']([^"']+)["']/g)].map(match=>match[1]));
const navigable=[];
for(const file of [join(src,'components','Sidebar.js'),join(src,'pages','Dashboard.js')]){
  const text=readFileSync(file,'utf8');
  for(const match of text.matchAll(/(?:to:|destination\s*=|:\s*)\s*[`"'](\/[A-Za-z0-9_?=&%/.-]*)/g))navigable.push([file,match[1].split('?')[0]]);
}
for(const [file,path]of navigable)if(path!=='/'&&!routes.has(path))failures.push(`Navigation target has no route (${file}): ${path}`);
const pages=[];
function walk(folder){for(const entry of readdirSync(folder,{withFileTypes:true})){const path=join(folder,entry.name);if(entry.isDirectory())walk(path);else if(/Page\.(js|jsx)$/.test(entry.name))pages.push(path)}}walk(join(src,'pages'));
const duplicateKeys=new Map();
for(const page of pages){const key=page.replace(/\.(js|jsx)$/,'').toLowerCase();duplicateKeys.set(key,(duplicateKeys.get(key)||0)+1)}
for(const [key,count]of duplicateKeys)if(count>1)failures.push(`Duplicate canonical page source: ${key}`);
if(failures.length){console.error(failures.join('\n'));process.exit(1)}
console.log(`Route integrity PASS: ${imports.length} lazy imports, ${routes.size-1} registered routes, ${navigable.length} navigation targets, 0 failures.`);
