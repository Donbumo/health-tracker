// Standalone prototype only: no servers, accounts, credentials or production access.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {pathToFileURL}=require('node:url');const {chromium}=require('playwright');
const out=path.join(__dirname,'qa');fs.mkdirSync(out,{recursive:true});
const base=pathToFileURL(path.join(__dirname,'index.html')).href;
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage();
 const errors=[],network=[],checks=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
 async function open(theme='dark',view='overview',day='2040-02-03',width=390){await page.setViewportSize({width,height:width<768?844:900});await page.goto(base+`?theme=${theme}&view=${view}&day=${day}`);}
 async function shot(name){await page.screenshot({path:path.join(out,name+'.png')});}
 try{
  for(const theme of ['dark','light'])for(const width of [360,390,430,768,1024,1366])for(const view of ['overview','calendar','sources','import','history']){
   await open(theme,view,view==='sources'?'2040-02-02':'2040-02-03',width);
   assert.equal(await page.locator('#'+view).isVisible(),true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme}/${width}/${view} overflow`);
   assert.equal(await page.locator('[role=tab][aria-selected=true]').count(),1);
   checks.push({theme,width,view,overflow:false});
  }
  for(const theme of ['dark','light']){
   await open(theme);assert.ok((await page.locator('.summary').boundingBox()).y+(await page.locator('.summary').boundingBox()).height<844);await shot('overview-'+theme+'-390');
   await open(theme,'overview','2040-02-03',1366);await shot('overview-'+theme+'-1366');
   await open(theme,'sources','2040-02-02');await shot('sources-conflict-'+theme+'-390');
  }
  await open();assert.ok(await page.locator('#day').evaluate(e=>parseFloat(getComputedStyle(e).fontSize)>=16));assert.ok(await page.locator('#overview svg').count()>=3);assert.ok(await page.locator('.rolling polyline').count()>0);
  const zero=await page.locator('#charts .chart').nth(2).locator('line.grid').first().getAttribute('y1');assert.ok(Number(zero)>30&&Number(zero)<165,'signed balance zero line');
  await page.locator('#today').click();assert.match(await page.locator('#day-state').innerText(),/Hoy no hay registro/);await shot('empty-today-dark-390');await page.locator('#latest').click();assert.match(await page.locator('#expense').innerText(),/2,500/);
  await open('light','overview','2040-01-30');assert.match(await page.locator('#intake-state').innerText(),/Subtotal conocido/);assert.match(await page.locator('#balance').innerText(),/—/);
  await open('dark','overview','2040-01-28');assert.match(await page.locator('#activity').innerText(),/Pasos\n0/);
  await open('light','sources','2040-01-31');assert.match(await page.locator('#source-content').innerText(),/Sin evidencia/);assert.equal(await page.locator('#source-content .source-card').count(),0);
  await open('dark','sources','2040-02-02');assert.equal(await page.locator('#resolve-form').evaluate(f=>f.checkValidity()),false);
  await page.locator('[name=resolution][value="2350"]').check();await page.getByRole('button',{name:'Revisar resolución',exact:true}).click();assert.equal(await page.locator('#confirm-resolution').isDisabled(),true);
  await page.locator('#reviewed').check();await page.locator('#confirm-resolution').click();assert.match(await page.locator('#expense').innerText(),/2,350/);assert.equal(await page.locator('#resolve-form').count(),0);
  await open('light','import');await page.locator('#import-next').click();assert.equal(await page.evaluate(()=>Boolean(data['2040-02-05'])),false);await page.locator('#import-next').click();assert.equal(await page.locator('#import-next').isDisabled(),true);
  await page.locator('.import-check').nth(0).check();assert.equal(await page.locator('#import-next').isDisabled(),true);await page.locator('.import-check').nth(1).check();await shot('import-review-light-390');await page.locator('#import-next').click();assert.equal(await page.evaluate(()=>Boolean(data['2040-02-05'])),false);await page.locator('#import-confirm').click();assert.match(await page.locator('#expense-state').innerText(),/No disponible/);assert.match(await page.locator('#activity').innerText(),/9,000/);assert.equal(await page.evaluate(()=>data['2040-02-05'].expense),null);
  await open('dark','calendar','2040-02-03',1366);await page.locator('#month-prev').click();assert.match(await page.locator('#month-title').innerText(),/enero/);await page.locator('#month-next').click();assert.equal(await page.locator('[data-date="2040-02-29"]').count(),1);await shot('calendar-dark-1366');await page.locator('[data-date="2040-02-02"]').click();assert.match(await page.locator('#calendar-detail').innerText(),/conflicto/);
  await open('light','history','2040-02-03',1366);await shot('history-light-1366');await page.locator('#history-filter').selectOption('review');assert.equal(await page.locator('#timeline .event').count(),1);
  await open();await page.locator('#tab-overview').focus();await page.keyboard.press('ArrowRight');assert.equal(await page.locator('#tab-calendar').getAttribute('aria-selected'),'true');await page.keyboard.press('End');assert.equal(await page.locator('#tab-history').getAttribute('aria-selected'),'true');await page.keyboard.press('Home');
  const focus=[];for(let i=0;i<18;i++){await page.keyboard.press('Tab');const item=await page.evaluate(()=>{let e=document.activeElement;return {tag:e.tagName,id:e.id,outline:getComputedStyle(e).outlineStyle};});focus.push(item);if(item.tag!=='BODY')assert.notEqual(item.outline,'none',JSON.stringify(item));}
  await page.locator('#export').click();assert.equal(await page.locator('#export-dialog').isVisible(),true);await page.keyboard.press('Escape');assert.equal(await page.locator('#export-dialog').isVisible(),false);
  await page.locator('#theme').click();assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
  const result={scope:'local standalone synthetic design; no application/server or production writes',base_application_commit:'9e2f2dc7fea728bfec3c8abf1aed6bc7bb428852',viewport_checks:checks.length,checks,screenshots:10,keyboard:'Tab, visible focus, arrow/Home/End tabs, native radio/checkbox, Escape dialog PASS',states:'known/partial/conflict/unknown/zero, empty today with latest, signed balance and visible moving means PASS',review_confirmation:'disabled until explicit review; originals remain separate; prototype only',import:'preview and review do not change local data; confirmation creates partial activity, no inferred expenditure',external_requests:network.length,javascript_errors:errors,production_tests:'not repeated; prototype only',status:'PASS'};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({viewport_checks:checks.length,screenshots:10,external_requests:0,javascript_errors:0,status:'PASS'}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
