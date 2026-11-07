// Actual Flask and Edge; exclusively invented files and accounts.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-basis-string/qa/browser');
const base='http://127.0.0.1:8042',fixtures=process.env.QA_STRING_FIXTURES_DIR;assert(fixtures);fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),cases=[],layouts=[],errors=[];
 for(const screen of ['desktop','mobile'])for(const scenario of ['clean','conflict','unknown','qualifiers','invalid']){
  const context=await browser.newContext({viewport:{width:screen==='desktop'?1366:390,height:900}}),page=await context.newPage();let semanticPosts=0;
  page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{assert(r.url().startsWith(base)||r.url().startsWith('data:'));assert(!r.url().endsWith('/confirm'));if(r.method()==='POST'&&r.url().endsWith('/decisions'))semanticPosts++});
  await page.goto(base+'/login');await page.locator('[name=username]').fill('qa-string14-'+scenario+'-'+screen);
  await page.locator('[name=password]').fill('fictional-preview-ui-password');await page.locator('input[type=submit],button[type=submit]').click();
  await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(fixtures,'string-'+scenario+'.json'));
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/nutrition/import');
  await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();assert.equal((await response).status(),scenario==='invalid'?422:302);
  let state=await(await page.request.get(base+'/qa/string-basis-state')).json();assert.equal(state.logs+state.products+state.receipts,0);
  if(scenario==='invalid'){
   assert.equal(state.uploads+state.drafts,0);assert((await page.locator('main').innerText()).includes('basis_interpretation'));
  }else{
   assert.equal(await page.locator('.ni-preview-record').count(),14);assert.equal(await page.locator('.ni-source-declared').count(),56);
   assert.equal(state.counts.decision,14);assert.equal(state.groupable,['conflict','unknown'].includes(scenario)?13:14);
   assert(state.all_totals_exact);assert.equal(state.summary.energy.value,null);
   assert(!(await page.locator('[name=consent_consumed]').isChecked()));assert(await page.locator('.ni-import-confirm button').isDisabled());
   await page.locator('.ni-row-details>summary').first().click();assert((await page.locator('.ni-row-details').first().innerText()).includes('Nota editorial sobre la base:'));
  }
  for(const phase of scenario==='invalid'?['error']:['before','after']){
   if(phase==='after'){
    await page.locator('.ni-import-basis>summary').click();await page.locator('[name=accept_declared_bases]').check();
    await page.getByRole('button',{name:'Aplicar bases declaradas',exact:true}).click();
    state=await(await page.request.get(base+'/qa/string-basis-state')).json();const partial=['conflict','unknown'].includes(scenario);
    assert.equal(state.counts.ready,partial?13:14);assert.equal(state.counts.decision,partial?1:0);assert.equal(state.counts.invalid,0);
    assert(state.all_totals_exact);assert.equal(Object.keys(state.summary).length,30);assert.equal(state.actions.length,1);
    assert.equal(state.logs+state.products+state.receipts,0);assert(!(await page.locator('[name=consent_consumed]').isChecked()));
    assert.equal(await page.locator('.ni-import-confirm button').isEnabled(),!partial);
    if(scenario==='qualifiers'){assert.equal(state.summary.energy.value,'0');for(const k of ['vitamin_d','iron','zinc'])assert.equal(state.summary[k].value,null)}
   }
   for(const theme of ['light','dark'])for(const width of [360,390,430,768,1024,1366]){
    await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
    const geometry=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,tinyInputs:[...document.querySelectorAll('input:not([type=hidden])')].filter(e=>e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<16).length}));
    assert(!geometry.overflow,JSON.stringify({screen,scenario,phase,width,theme,geometry}));assert.equal(geometry.tinyInputs,0);layouts.push({screen,scenario,phase,width,theme,...geometry});
   }
   await page.setViewportSize({width:screen==='desktop'?1366:390,height:900});await page.screenshot({path:path.join(out,scenario+'-'+phase+'-'+screen+'.png')});
   if(scenario!=='invalid')await page.locator('#import-summary').screenshot({path:path.join(out,scenario+'-'+phase+'-counts-'+screen+'.png')});
  }
  assert.equal(semanticPosts,scenario==='invalid'?0:1);cases.push({screen,scenario,upload_status:scenario==='invalid'?422:302,
   ready:state.counts?.ready||0,pending:state.counts?.decision||0,nutrients:scenario==='invalid'?0:30,exact_decimal_totals:scenario==='invalid'?null:state.all_totals_exact,semantic_POSTs:semanticPosts,domain_writes:0,consent:false});await context.close();
 }
 assert.equal(errors.length,0);await browser.close();fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({status:'PASS',data:'entirely fictional',cases,layouts,errors},null,2));console.log(JSON.stringify({status:'PASS',cases:cases.length,layouts:layouts.length,errors}));
})().catch(e=>{console.error(e);process.exit(1)});
