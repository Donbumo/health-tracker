/* D: real local Flask + fictional fixtures only. NODE_PATH supplies Playwright/axe. */
const {chromium}=require('playwright'),axe=require('axe-core'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const base=process.env.ENERGY_QA_URL;
if(!base || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw Error('Explicit loopback QA URL required');
const out=path.resolve('design/energy-experience-2-0-d'),screens=path.join(out,'screenshots');fs.mkdirSync(screens,{recursive:true});
const report={scope:'synthetic Flask QA only; no NAS',axe:axe.version,layouts:[],scans:[],keyboard:[],semantics:[],performance:[],screenshots:[],limits:[]};
const routes=[['known','/energy?date=2040-02-03&period=30'],['partial-conflict','/energy?date=2040-02-01&period=7'],['unknown','/energy?date=2041-01-01&period=90'],['minimum','/energy?date=1900-01-01&period=7'],['maximum','/energy?date=9998-12-31&period=90'],['sources','/energy/sources?date=2040-02-03'],['retired','/energy/sources?date=2040-01-29'],['history','/energy/history'],['import','/energy/import'],['review','/energy/review?date=2040-02-01'],['query-error','/energy?date=bad&period=all'],['sources-error','/energy/sources?date=bad'],['history-error','/energy/history?from=2040-02-03&to=2040-01-01']];
let browser,p,cdp;
async function layout(name,theme,width,extras={}){
 const result=await p.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth,main:!!document.querySelector('.ee-page'),h1:document.querySelector('h1')?.innerText}));
 assert(result.main,name);assert(result.scroll<=result.width+1,`${name} overflow ${result.scroll}/${result.width}`);
 report.layouts.push({name,theme,width,...result,...extras});
}
async function scan(name,theme,width){
 await p.addScriptTag({content:axe.source});const r=await p.evaluate(async()=>axe.run({runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}}));
 report.scans.push({name,theme,width,passes:r.passes.length,violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),incomplete:r.incomplete.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))});
 assert.equal(r.violations.length,0,`${name} ${theme} ${width}: ${r.violations.map(v=>v.id)}`);
}
async function snap(name,theme,width,fullPage=false){const file=`${name}-${width}-${theme}.png`;await p.screenshot({path:path.join(screens,file),fullPage});report.screenshots.push(file);}
async function tabTo(selector,max=250){
 for(let i=0;i<max;i++){
   if(await p.locator(selector).evaluateAll(els=>els.includes(document.activeElement)))return i;
   await p.keyboard.press('Tab');
 }throw Error(`Keyboard did not reach ${selector}`);
}
async function ax(name){const tree=await cdp.send('Accessibility.getFullAXTree');const roles={};for(const n of tree.nodes.filter(n=>!n.ignored)){const role=n.role?.value;roles[role]=(roles[role]||0)+1;}
 const imgs=tree.nodes.filter(n=>!n.ignored&&n.role?.value==='image').map(n=>({name:!!n.name?.value,description:!!n.description?.value}));assert(imgs.every(i=>i.name&&i.description));
 report.semantics.push({name,roles,images:imgs,actualScreenReader:false});}
async function advance(action){await tabTo(`button[name=action][value=${action}]`);await Promise.all([p.waitForNavigation(),p.keyboard.press('Enter')]);}
const doc={schema_version:'1.0',record_type:'daily_energy',user_id:1,source_type:'uploaded',data:{date:'2040-03-01',source:'QA D keyboard original',steps:0}};
(async()=>{
 browser=await chromium.launch({channel:'msedge',headless:true});p=await browser.newPage({viewport:{width:1366,height:900}});cdp=await p.context().newCDPSession(p);
 await p.goto(base+'/login');await p.locator('[name=username]').fill('QA-energy-D');await p.locator('[name=password]').fill('fictional-energy-D-password');await p.locator('[type=submit]').click();
 for(const theme of ['light','dark']){
  await p.emulateMedia({colorScheme:theme});
  for(const width of [320,360,390,430,768,1024,1366]){
   await p.setViewportSize({width,height:width<768?844:900});
   for(const [name,route] of routes){await p.goto(base+route);await layout(name,theme,width);
    if(width===390||width===1366){await scan(name,theme,width);if(['known','minimum','maximum','sources','history','import','review','query-error','sources-error','history-error'].includes(name))await snap(name,theme,width);}
   }
  }
  for(const width of [390,1366]){
   await p.setViewportSize({width,height:900});await p.goto(base+'/energy/import');await p.locator('[type=file]').setInputFiles({name:'QA-D-keyboard.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(doc))});
   await tabTo('.eg-page button[type=submit]');await Promise.all([p.waitForNavigation(),p.keyboard.press('Enter')]);
   for(const step of [2,3,4]){assert((await p.title()).includes(`Paso ${step}`));await layout(`import-step-${step}`,theme,width);await scan(`import-step-${step}`,theme,width);if(width===390)await snap(`import-step-${step}`,theme,width,step===4);await ax(`import-step-${step}`);if(step<4)await advance(step===2?'review':'approve');}
   const box=p.locator('[name=confirm]');await tabTo('[name=confirm]');await p.keyboard.press('Space');assert(await box.isChecked());await p.keyboard.press('Space');assert(!(await box.isChecked()));
   report.keyboard.push({name:'import four steps, Tab/Enter/Space confirmation, cancel without write',theme,width,status:'PASS'});
   await tabTo('.eg-actions a.button-secondary');await Promise.all([p.waitForNavigation(),p.keyboard.press('Enter')]);assert(p.url().endsWith('/energy/import'));
   await p.goto(base+'/energy/review?date=2040-02-01');await tabTo('#eg-choice-steps');await p.keyboard.press('End');await p.keyboard.press('ArrowUp');assert.equal(await p.locator('#eg-choice-steps').inputValue(),'manual');await p.keyboard.press('Tab');assert.equal(await p.evaluate(()=>document.activeElement.id),'eg-value-steps');await p.keyboard.type('2.5');
   await advance('review');assert.equal(await p.locator('#eg-value-steps').getAttribute('aria-invalid'),'true');assert(await p.locator('[role=alert]').evaluate(e=>e===document.activeElement));await layout('review-error',theme,width);await scan('review-error',theme,width);await snap('review-error',theme,width);await ax('review-field-error');
   await tabTo('a[href="#eg-value-steps"]');await p.keyboard.press('Enter');assert.equal(await p.evaluate(()=>document.activeElement.id),'eg-value-steps');await p.keyboard.press('Control+A');await p.keyboard.type('0');await advance('review');assert((await p.title()).includes('Paso 3'));await scan('review-step-3',theme,width);await advance('approve');assert((await p.title()).includes('Paso 4'));await scan('review-step-4',theme,width);await snap('review-confirm',theme,width,true);await ax('review-confirm');
   report.keyboard.push({name:'field error focus, error link, correction, review and explicit confirmation',theme,width,status:'PASS'});
  }
 }
 // Full keyboard traversal with sticky headers and reversible controls, no positive tabindex.
 for(const width of [390,1366]){await p.setViewportSize({width,height:900});await p.goto(base+'/energy?date=2040-02-03&period=7');await p.keyboard.press('Tab');assert(await p.locator('.skip-link').evaluate(e=>e===document.activeElement));await p.keyboard.press('Enter');assert.equal(await p.evaluate(()=>document.activeElement.id),'main-content');
  await tabTo('.ee-chart summary');await p.keyboard.press('Enter');assert(await p.locator('.ee-chart details').first().getAttribute('open')!==null);await p.keyboard.press('Tab');assert(await p.locator('.ee-table').first().evaluate(e=>e===document.activeElement));await p.keyboard.press('ArrowRight');await p.waitForTimeout(180);if(width===390)assert(await p.locator('.ee-table').first().evaluate(e=>e.scrollLeft>0));await p.keyboard.press('Shift+Tab');assert(await p.locator('.ee-chart summary').first().evaluate(e=>e===document.activeElement));await ax('chart-and-open-table');await scan('table-open','dark',width);await snap('table-open','dark',width);
  await p.goto(base+'/energy/import');const seen=new Set();let focus=[];for(let i=0;i<100;i++){await p.keyboard.press('Tab');await p.waitForTimeout(220);const v=await p.evaluate(()=>{const e=document.activeElement,r=e.getBoundingClientRect(),s=getComputedStyle(e);return {key:e.tagName+'#'+e.id+'.'+e.className+' '+(e.getAttribute('name')||'')+' '+e.getAttribute('href'),tag:e.tagName,outline:s.outlineStyle,width:parseFloat(s.outlineWidth),top:r.top,bottom:r.bottom,left:r.left,right:r.right,viewport:innerHeight,tabindex:e.getAttribute('tabindex')};});if(seen.has(v.key)&&v.tag==='A'&&v.key.includes('skip-link'))break;seen.add(v.key);focus.push(v);assert(!(Number(v.tabindex)>0));if(v.tag!=='BODY'){assert(v.outline!=='none'&&v.width>=2,`invisible focus ${v.key}`);assert(v.bottom>0&&v.top<v.viewport,`offscreen focus ${JSON.stringify(v)}`);}}
  report.keyboard.push({name:'complete tab cycle, skip, focus visible, Shift+Tab and table arrow scroll',width,status:'PASS',focusTargets:focus.length});
  if(width===390){await p.goto(base+'/energy');await tabTo('.mobile-menu>summary');await p.keyboard.press('Enter');await p.keyboard.press('Tab');assert(await p.locator('.mobile-menu-panel a').first().evaluate(e=>e===document.activeElement));await p.keyboard.press('Shift+Tab');await p.keyboard.press('Enter');assert.equal(await p.locator('.mobile-menu').getAttribute('open'),null);report.keyboard.push({name:'mobile navigation opens/closes with keyboard, no focus trap',width,status:'PASS'});}
 }
 // 200% layout equivalent and independent text resize + 320 CSS px reflow. Not pinch zoom.
 for(const theme of ['light','dark']){await p.emulateMedia({colorScheme:theme});await p.setViewportSize({width:683,height:450});for(const [name,route] of routes){await p.goto(base+route);await layout(name,theme,683,{method:'1366x900 layout equivalent at 200%; 683x450 CSS px'});}await snap('zoom200-layout',theme,683);
  await p.setViewportSize({width:390,height:844});for(const [name,route] of routes){await p.goto(base+route);await p.addStyleTag({content:'html {font-size:200% !important}'});await layout(name,theme,390,{method:'independent root text resize 200%'});}await snap('text200',theme,390);
 }
 for(const route of ['/energy/history','/energy/history?page=200','/energy/history?page=99999','/energy/history?source=QA%20volumen%201','/energy/history?operation=import']){const ms=[];let count;for(let n=0;n<5;n++){const start=performance.now();const res=await p.goto(base+route);assert.equal(res.status(),200);ms.push(Math.round((performance.now()-start)*10)/10);count=await p.locator('.ep-event').count();assert(count<=25);}report.performance.push({route,samplesMs:ms,renderedEvents:count,maxMs:Math.max(...ms)});}
 // A -> B -> C -> B -> A; links and original use the official routes.
 await p.goto(base+'/energy?date=2040-02-03');await p.getByRole('link',{name:'Fuentes y decisiones',exact:true}).click();await p.getByRole('link',{name:'Revisar decisiones por campo'}).click();await p.getByRole('link',{name:'Cancelar sin confirmar'}).click();await p.getByRole('link',{name:'Volver al resumen canónico'}).click();assert(p.url().includes('/energy?date=2040-02-03'));report.keyboard.push({name:'A → B → C → B → A route loop',status:'PASS',method:'real links'});
 report.limits=['No actual NVDA/Narrator session; browser AX tree is structural evidence only.','200% uses layout equivalent and separate text resize; no claim of browser UI zoom.','Automated axe/manual inspection do not certify full WCAG conformance.'];
 report.status='PASS';
})().catch(e=>{report.status='FAIL';report.error=e.message;console.error(e.stack);process.exitCode=1}).finally(async()=>{fs.mkdirSync(path.join(out,'qa'),{recursive:true});fs.writeFileSync(path.join(out,'qa','accessibility.json'),JSON.stringify(report,null,2)+'\n');if(browser)await browser.close();console.log(JSON.stringify({status:report.status,layouts:report.layouts.length,axeScans:report.scans.length,keyboard:report.keyboard.length,captures:report.screenshots.length,error:report.error}));});
