// Actual Flask + Edge, exclusively fictional QA accounts and source21 files.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-source-21/qa/quality-review');
const base='http://127.0.0.1:8042';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const cases=[],layouts=[],errors=[];
 for(const screen of ['desktop','mobile'])for(const scenario of ['clean','conflict','partial','mixed']){
  const context=await browser.newContext({viewport:{width:screen==='mobile'?390:1366,height:900},colorScheme:screen==='mobile'?'light':'dark'});
  const page=await context.newPage();let posts=0;
  page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{assert(r.url().startsWith(base)||r.url().startsWith('data:'));if(r.method()==='POST')posts++});
  await page.goto(base+'/login');await page.locator('[name=username]').fill('qa-source21-'+scenario+'-'+screen);
  await page.locator('[name=password]').fill('fictional-preview-ui-password');await page.locator('input[type=submit],button[type=submit]').click();posts=0;
  await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(root,'examples/qa/nutrition-source-21/'+({clean:'recoverable-21',conflict:'one-conflict',partial:'partial-net',mixed:'mixed-quality'}[scenario])+'.json'));
  await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();
  assert.equal(await page.locator('.ni-preview-record').count(),21);assert.equal(await page.locator('.ni-preview-group').count(),4);
  assert.equal(await page.locator('.ni-row-edit-form').count(),0);assert.equal(await page.locator('[name=consent_consumed]').isChecked(),false);
  assert.equal(await page.locator('.ni-preview-record.needs-attention').count(),scenario==='conflict'?1:0);
  assert((await page.locator('#record-0 .ni-row-details').textContent()).includes('No contabilizados:'));
  let initial=await(await page.request.get(base+'/qa/source21-state')).json();assert.equal(initial.logs+initial.products+initial.receipts,0);
  if(scenario==='mixed'){
   assert.deepEqual(initial.qualities.slice(0,5),['Estimado','Estimado','Estimado','Estimado','Contiene estimaciones']);
   assert(initial.qualities.slice(5).every(q=>q===''));
   assert.equal(await page.locator('#record-4 .ni-quality').innerText(),'Contiene estimaciones');
   await page.locator('#record-4 .ni-row-details>summary').click();
   for(const [name,label] of [['Fibra','Estimado'],['Proteína','Calidad declarada: verificada']]){
    const nutrient=page.locator('#record-4 .ni-row-details .ni-nutrient-details>div').filter({has:page.locator('dt',{hasText:new RegExp('^'+name+'$')})}).first();
    assert((await nutrient.innerText()).includes(label));
   }
   await page.locator('#record-4 .ni-row-details').screenshot({path:path.join(out,'mixed-quality-detail-'+screen+'.png')});
   await page.locator('#record-4 .ni-row-details>summary').click();
  }
  if(scenario==='conflict'){
   await page.locator('#record-1 .ni-edit-link').click();await page.locator('[name=r1_basis_unit]').selectOption('g');await page.locator('[name=r1_basis_verified]').check();
   await page.getByRole('button',{name:'Aplicar',exact:true}).click();assert.equal(await page.locator('.needs-attention').count(),0);
  }
  for(const theme of ['light','dark'])for(const width of [360,390,430,768,1024,1366]){
   await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
   const geometry=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,
    tinyInputs:[...document.querySelectorAll('input:not([type=hidden])')].filter(e=>e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<16).length,
    saveBottom:document.querySelector('.ni-save-all').getBoundingClientRect().top>=document.querySelector('.ni-batch-summary').getBoundingClientRect().bottom}));
   assert(!geometry.overflow);assert.equal(geometry.tinyInputs,0);assert(geometry.saveBottom);layouts.push({screen,scenario,width,theme,...geometry});
  }
  await page.setViewportSize({width:screen==='mobile'?390:1366,height:900});await page.emulateMedia({colorScheme:screen==='mobile'?'light':'dark'});
  await page.screenshot({path:path.join(out,scenario+'-preview-'+screen+'.png')});await page.locator('#import-summary').screenshot({path:path.join(out,scenario+'-counts-'+screen+'.png')});
  await page.locator('#record-0 .ni-row-details>summary').click();assert((await page.locator('#record-0').innerText()).includes('Calcio'));
  await page.locator('#record-0 .ni-row-details').screenshot({path:path.join(out,scenario+'-micros-'+screen+'.png')});
  const prepared=await(await page.request.get(base+'/qa/source21-state')).json();assert.equal(prepared.counts.ready,21);assert.equal(prepared.groups,4);
  assert.equal(Object.keys(prepared.summary).length,30);
  assert.equal(prepared.logs+prepared.products+prepared.receipts,0);assert(await page.locator('.ni-import-confirm button').isEnabled());
  assert.equal(prepared.summary.net_carbs.value,'168');if(scenario==='partial')assert.equal(prepared.summary.vitamin_d.value,null);
  await page.locator('[name=consent_consumed]').check();await page.locator('.ni-import-confirm button').focus();await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'Guardado con confirmación',exact:true}).waitFor();
  const saved=await(await page.request.get(base+'/qa/source21-state')).json();assert.equal(saved.logs,21);assert.equal(saved.products,0);assert.equal(saved.receipts,1);
  assert.deepEqual(saved.summary,prepared.summary);assert.equal(posts,scenario==='conflict'?3:2);
  cases.push({screen,scenario,records:21,groups:4,initial_counts:initial.counts,ready_after_correction:prepared.counts.ready,
   posts,products:0,receipts:1,logs:21,all_nutrient_summary_parity:true,nutrients:30,
   qualities:scenario==='mixed'?initial.qualities:null});await context.close();
 }
 assert.equal(errors.length,0);await browser.close();fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({status:'PASS',data:'entirely fictional',cases,layouts,errors},null,2));console.log(JSON.stringify({status:'PASS',cases,layouts:layouts.length,errors}));
})().catch(e=>{console.error(e);process.exit(1)});
