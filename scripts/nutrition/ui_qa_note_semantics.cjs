// Issue #34: real Flask + Edge, explicitly fictional accounts/files only.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-note-semantics/qa');
const base='http://127.0.0.1:8042';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const cases=[],layouts=[],errors=[];
 for(const screen of ['desktop','mobile'])for(const scenario of ['note','note-conflict']){
  const context=await browser.newContext({viewport:{width:screen==='mobile'?390:1366,height:900},colorScheme:screen==='mobile'?'light':'dark'});
  const page=await context.newPage();let posts=0;
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('request',r=>{assert(r.url().startsWith(base)||r.url().startsWith('data:'));if(r.method()==='POST')posts++;});
  await page.goto(base+'/login');await page.locator('[name=username]').fill('qa-preview-'+scenario+'-'+screen);
  await page.locator('[name=password]').fill('fictional-preview-ui-password');
  await page.locator('input[type=submit],button[type=submit]').click();posts=0;
  await page.goto(base+'/nutrition/import');
  await page.locator('#ni-upload').setInputFiles(path.join(root,'examples/qa/nutrition-note-semantics/'+(scenario==='note'?'long-note-23.json':'conflicting-note-23.json')));
  await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();
  assert.equal(await page.locator('.ni-preview-record').count(),23);
  assert.equal(await page.locator('.ni-row-edit-form').count(),0);
  assert.equal(await page.locator('[name=consent_consumed]').isChecked(),false);
  assert.equal(await page.locator('.ni-import-confirm button').count(),1);
  assert(await page.locator('.ni-import-confirm button').isDisabled());
  assert.equal((await page.request.get(base+'/qa/preview-state')).status(),200);
  const initial=await page.evaluate(async()=>await(await fetch('/qa/preview-state')).json());
  assert.equal(initial.notes_length,5000);assert(initial.original_unchanged&&initial.original_notes_preserved);
  assert.equal(initial.logs+initial.products+initial.receipts,0);
  for(const theme of ['light','dark'])for(const width of [360,390,430,768,1024,1366]){
   await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
   const geometry=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,
    tinyInputs:[...document.querySelectorAll('input:not([type=hidden])')].filter(e=>e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<16).length,
    saveBottom:document.querySelector('.ni-save-all').getBoundingClientRect().top>=document.querySelector('.ni-batch-summary').getBoundingClientRect().bottom}));
   assert(!geometry.overflow);assert.equal(geometry.tinyInputs,0);assert(geometry.saveBottom);layouts.push({screen,scenario,width,theme,...geometry});
  }
  await page.setViewportSize({width:screen==='mobile'?390:1366,height:900});await page.emulateMedia({colorScheme:screen==='mobile'?'light':'dark'});
  await page.screenshot({path:path.join(out,scenario+'-before-'+screen+'.png')});
  if(scenario==='note'){
   assert.equal(initial.legacy_total_count,23);assert.equal(initial.file_blocks,0);
   await page.locator('.ni-import-interpretation summary').click();
   await page.locator('[name=accept_legacy_totals]').check();
   await page.getByRole('button',{name:'Aplicar interpretación agrupada',exact:true}).click();
   assert.equal(posts,2);assert.equal(await page.locator('.ni-preview-record.needs-attention').count(),0);
   assert(await page.locator('.ni-import-confirm button').isEnabled());
   assert.equal(await page.locator('[name=consent_consumed]').isChecked(),false);
   const prepared=await page.evaluate(async()=>await(await fetch('/qa/preview-state')).json());
   assert.equal(prepared.counts.ready,23);assert.equal(prepared.counts.decision,0);assert.equal(prepared.products,0);
   assert(prepared.original_notes_preserved&&prepared.original_unchanged);
   await page.screenshot({path:path.join(out,scenario+'-ready-'+screen+'.png')});
   await page.locator('#import-summary').screenshot({path:path.join(out,'ready-counts-'+screen+'.png')});
   await page.locator('.ni-preview-record').first().screenshot({path:path.join(out,'ready-row-'+screen+'.png')});
   await page.locator('[name=consent_consumed]').check();
   await page.locator('.ni-import-confirm button').focus();await page.keyboard.press('Enter');
   await page.getByRole('heading',{name:'Guardado con confirmación',exact:true}).waitFor();
   const saved=await page.evaluate(async()=>await(await fetch('/qa/preview-state')).json());
   assert.equal(saved.logs,23);assert.equal(saved.products,0);assert.equal(saved.receipts,1);assert.equal(posts,3);
   cases.push({screen,scenario,records:23,group_POSTs:1,ready_after_group:23,row_corrections:0,POSTs_including_upload_and_QA_save:posts,
    notes_length:saved.notes_length,original_notes_preserved:saved.original_notes_preserved,logs:saved.logs,products:saved.products,receipts:saved.receipts,keyboard_save:true});
  }else{
   assert.equal(initial.file_blocks,1);assert.equal(initial.legacy_total_count,0);assert.equal(initial.counts.blocked,23);
   assert.equal(initial.counts.decision,0);assert.equal(await page.locator('#file-basis-title').count(),1);
   assert.equal(await page.locator('.ni-row-problem').count(),0);assert.equal(await page.locator('[name=accept_legacy_totals]').count(),0);
   assert.equal(posts,1);await page.locator('[role=alert]').screenshot({path:path.join(out,'file-block-'+screen+'.png')});
   cases.push({screen,scenario,records:23,file_blocks:1,row_errors:0,group_POSTs:0,POSTs_including_upload:posts,logs:0,products:0,receipts:0,save_disabled:true,original_notes_preserved:initial.original_notes_preserved});
  }
  await context.close();
 }
 assert.equal(errors.length,0);await browser.close();
 fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({status:'PASS',data:'fictional only',cases,layouts,errors},null,2));
 console.log(JSON.stringify({status:'PASS',cases,layout_checks:layouts.length,errors}));
})().catch(e=>{console.error(e);process.exit(1);});
