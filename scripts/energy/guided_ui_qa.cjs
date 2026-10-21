// C on real local Flask, fictional fixtures only. Never point to NAS/production.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.ENERGY_QA_URL;assert.match(base||'',/^http:\/\/127\.0\.0\.1:\d+$/);
const out=path.resolve(__dirname,'../../design/energy-experience-2-0-c/qa');fs.mkdirSync(out,{recursive:true});
const document={schema_version:'1.0',record_type:'daily_energy',user_id:1,source_type:'uploaded',data:{date:'2040-03-05',source:'QA C guía',steps:0,active_expenditure_kcal:450,notes:'QA ficticia C; no cuenta real.'}};
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage();
 const checks=[],errors=[],http=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)http.push(r.status()+' '+new URL(r.url()).pathname)});
 async function open(route){const r=await page.goto(base+route);assert.equal(r.status(),200);assert.equal(r.headers()['cache-control'],'private, no-store');}
 async function upload(doc=document){await open('/energy/import');await page.locator('[name=file]').setInputFiles({name:'QA-C-energy.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(doc,null,2))});await page.getByRole('button',{name:'Vista previa sin guardar',exact:true}).click();if(doc===document)assert.match(await page.locator('.eg-page').innerText(),/Observación parcial/);}
 async function step(action){await page.locator(`button[name=action][value=${action}]`).click();}
 async function review(){await open('/energy/review?date=2040-02-04');await page.locator('[name=choice_total_calories]').selectOption('manual');await page.locator('[name=value_total_calories]').fill('2150');}
 async function record(theme,width,view){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme}/${width}/${view} overflow`);assert.equal(await page.locator('.eg-page').isVisible(),true);checks.push({theme,width,view,status:'PASS'});if([390,1366].includes(width))await page.screenshot({path:path.join(out,`${view}-${theme}-${width}.png`)});}
 try{
  await page.goto(base+'/login');await page.locator('[name=username]').fill('QA-energy-provenance');await page.locator('[name=password]').fill('fictional-energy-provenance-password');await page.locator('[type=submit]').click();
  for(const theme of ['dark','light']){
   await page.emulateMedia({colorScheme:theme,reducedMotion:'reduce'});
   for(const width of [360,390,430,768,1024,1366]){
    await page.setViewportSize({width,height:width<768?844:900});
    await open('/energy/import');await record(theme,width,'identify');
    await upload();await record(theme,width,'preview');await step('review');await record(theme,width,'operations');await step('approve');await record(theme,width,'confirmation');
    assert.equal(await page.locator('[name=confirm]').isChecked(),false);
    await review();await record(theme,width,'decide');await step('review');assert.match(await page.locator('.eg-page').innerText(),/2150/);await record(theme,width,'decision-operations');await step('approve');await record(theme,width,'decision-confirmation');
   }
   for(const width of [390,1366]){await page.setViewportSize({width,height:width<768?844:900});await upload({...document,data:{date:'2040-02-04',source:'QA propuesta',total_expenditure_kcal:2200}});await step('review');const field=page.locator('.eg-field').first();assert.match(await field.innerText(),/Misma fuente antes: 2100/);assert.match(await field.innerText(),/Archivo: 2200/);assert.match(await field.innerText(),/Conflicto pendiente/);await field.scrollIntoViewIfNeeded();await record(theme,width,'import-conflict');}
   await page.setViewportSize({width:390,height:844});await review();
   await page.locator('[name=choice_total_calories]').focus();for(let i=0;i<10;i++){await page.keyboard.press('Tab');const focus=await page.evaluate(()=>{const e=document.activeElement;return {tag:e.tagName,style:getComputedStyle(e).outlineStyle}});if(focus.tag!=='BODY')assert.notEqual(focus.style,'none');}
  }
  // Confirm only after all read-only screenshots; then check real HTTP replay.
  await upload();await step('review');await step('approve');
  const post=await page.locator('form.eg-review').evaluate(form=>Object.fromEntries(new FormData(form)));post.action='confirm';post.confirm='yes';
  await page.locator('[name=confirm]').check();await step('confirm');assert.equal(new URL(page.url()).pathname,'/energy/sources');assert.match(await page.locator('.ep-page').innerText(),/QA C guía/);
  await open('/energy/history');const count=await page.locator('.ep-count').innerText();assert.equal((await page.request.post(base+'/energy/import',{form:post})).status(),200);await open('/energy/history');assert.equal(await page.locator('.ep-count').innerText(),count);
  await review();await step('review');await step('approve');await page.locator('[name=confirm]').check();await step('confirm');assert.match(await page.locator('.ep-page').innerText(),/2150/);assert.doesNotMatch(await page.locator('.ep-page').innerText(),/Gasto total: Conflicto pendiente/);
  const other=await browser.newPage();await other.goto(base+'/login');await other.locator('[name=username]').fill('QA-energy-provenance-other');await other.locator('[name=password]').fill('fictional-energy-provenance-other-password');await other.locator('[type=submit]').click();assert.equal((await other.request.get(base+'/energy/review?date=2040-03-05')).status(),404);await other.close();
  assert.deepEqual(errors,[]);assert.deepEqual(http,[]);
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',scope:'real Flask HTTP; temporary SQLite; fictional QA only; no NAS',viewport_checks:checks.length,checks,screenshots:32,javascript_errors:errors,http_errors:http,keyboard:'Native inputs/selects/buttons, Tab and visible focus PASS',flows:'Four enforced stages, preview no writes, actual CSRF confirmation, import original, source-before/canonical-conflict/incoming distinction, HTTP replay unchanged audit count, manual conflict decision and second-owner 404 PASS',limits:'Physical mobile and full accessibility audit remain separate; D extreme-date navigation unchanged'},null,2)+'\n');
  console.log(JSON.stringify({status:'PASS',viewport_checks:checks.length,screenshots:32,javascript_errors:0,http_errors:0}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
