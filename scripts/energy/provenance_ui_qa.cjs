// Synthetic B fixtures on a real Flask server. Never use a production account.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.ENERGY_QA_URL;assert.match(base||'',/^http:\/\/127\.0\.0\.1:\d+$/);
const out=path.resolve(__dirname,'../../design/energy-experience-2-0-b/qa');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage();
 const errors=[],http=[],checks=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)http.push(r.status()+' '+new URL(r.url()).pathname);});
 async function open(route){const response=await page.goto(base+route);assert.equal(response.status(),200);assert.equal(response.headers()['cache-control'],'private, no-store');}
 try{
  await page.goto(base+'/login');await page.locator('[name=username]').fill('QA-energy-provenance');await page.locator('[name=password]').fill('fictional-energy-provenance-password');await page.locator('[type=submit]').click();
  const views=[['sources','/energy/sources?date=2040-02-03'],['history','/energy/history'],['decision','/energy/history?source=QA+reloj&operation=edit_day'],['retired-day','/energy/sources?date=2040-02-02']];
  for(const theme of ['dark','light']){
   await page.emulateMedia({colorScheme:theme,reducedMotion:'reduce'});
   for(const width of [360,390,430,768,1024,1366]){
    await page.setViewportSize({width,height:width<768?844:900});
    for(const [view,route] of views){
     await open(route);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme}/${width}/${view} overflow`);
     assert.equal(await page.locator('.ep-page').isVisible(),true);
     if(view==='sources'){assert.match(await page.locator('.ep-page').innerText(),/2450/);assert.ok(await page.locator('.ep-retired').count());}
     if(view==='history'){assert.equal(await page.locator('.ep-event').count(),25);assert.match(await page.locator('.ep-count').innerText(),/página 1/);assert.equal(await page.locator('[rel=next]').count(),1);}
     if(view==='decision')assert.match(await page.locator('.ep-timeline').innerText(),/decisión confirmada/);
     if(view==='retired-day')assert.match(await page.locator('.ep-page').innerText(),/Día retirado/);
     checks.push({theme,width,view,status:'PASS'});
     if([390,1366].includes(width)){
      await page.screenshot({path:path.join(out,`${view}-${theme}-${width}.png`)});
      if(view==='sources'){await page.locator('.ep-source').filter({has:page.getByRole('heading',{name:'QA reloj',exact:true})}).locator('.ep-download').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,`original-${theme}-${width}.png`)});}
     }
    }
   }
   await page.setViewportSize({width:390,height:844});await open('/energy/history?source=QA+historial&operation=import');
   await page.locator('[rel=next]').click();assert.match(await page.locator('.ep-count').innerText(),/página 2/);assert.match(page.url(),/source=QA\+historial/);assert.match(page.url(),/operation=import/);
   await open('/energy/history?source=QA+historial&page=5');assert.ok(await page.locator('.ep-event').count()>0);assert.equal(await page.locator('[rel=next]').count(),0);
   await open('/energy/history?operation=conflict');assert.match(await page.locator('.ep-event').innerText(),/Propuesta conservada/);assert.match(await page.locator('.ep-event').innerText(),/2200/);
   await open('/energy/sources?date=2040-02-04');assert.match(await page.locator('.ep-page').innerText(),/Conflicto pendiente/);
   await open('/energy/history');await page.locator('.ep-filter-panel summary').click();
   await page.locator('[name=from]').fill('2040-02-03');await page.locator('[name=to]').fill('2040-02-03');await page.locator('[name=source]').selectOption({label:'QA reloj'});await page.locator('[name=operation]').selectOption('import');await page.getByRole('button',{name:'Aplicar filtros',exact:true}).click();assert.equal(await page.locator('.ep-event').count(),2);
   await page.locator('.ep-filter-panel summary').click();assert.equal(await page.locator('[name=source]').inputValue(),'QA reloj');
   await page.locator('.ep-filter-panel summary').focus();for(let i=0;i<12;i++){await page.keyboard.press('Tab');const focus=await page.evaluate(()=>{let e=document.activeElement;return {tag:e.tagName,outline:getComputedStyle(e).outlineStyle};});if(focus.tag!=='BODY')assert.notEqual(focus.outline,'none',JSON.stringify(focus));}
   await open('/energy/sources?date=2040-02-03');
   const form=page.locator('.ep-source').filter({has:page.getByRole('heading',{name:'QA reloj',exact:true})}).locator('.ep-download');const reference=await form.locator('[name=reference]').inputValue(),csrf=await form.locator('[name=csrf_token]').inputValue();
   const download=await page.request.post(base+'/energy/original',{form:{reference,csrf_token:csrf}});assert.equal(download.status(),200);assert.match(download.headers()['content-disposition'],/^attachment/);assert.equal(download.headers()['x-content-type-options'],'nosniff');assert.equal(JSON.parse((await download.body()).toString()).record_type,'daily_energy');
   const other=await browser.newPage();other.on('pageerror',e=>errors.push(e.message));await other.goto(base+'/login');await other.locator('[name=username]').fill('QA-energy-provenance-other');await other.locator('[name=password]').fill('fictional-energy-provenance-other-password');await other.locator('[type=submit]').click();
   await other.goto(base+'/energy/sources?date=2040-02-03');assert.match(await other.locator('.ep-page').innerText(),/QA secret foreign/);assert.doesNotMatch(await other.locator('.ep-page').innerText(),/QA reloj/);assert.equal((await other.request.post(base+'/energy/original',{form:{reference,csrf_token:await other.locator('[name=csrf_token]').first().inputValue()}})).status(),404);await other.close();
   await page.getByRole('link',{name:'Volver al resumen canónico',exact:true}).click();assert.equal(new URL(page.url()).pathname,'/energy');assert.match(await page.locator('#ee-expended').innerText(),/2450/);
  }
  assert.deepEqual(errors,[]);assert.deepEqual(http,[]);
  const report={scope:'real Flask HTTP; temporary SQLite and synthetic B owners/files only',status:'PASS',viewport_checks:checks.length,checks,screenshots:20,javascript_errors:errors,http_errors:http,keyboard:'Tab, native date focus, selects, disclosure and links PASS',flows:'canonical/evidence navigation, combined filters, pages beyond 100, retired day, source retirement, decisions, verified original and real second-owner login/download 404 PASS',privacy:'fictional QA only; no production account or NAS access',limitations:'Focal accessibility; integral audit and boundary-date navigation remain D.'};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:'PASS',viewport_checks:checks.length,screenshots:20,javascript_errors:0,http_errors:0}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
