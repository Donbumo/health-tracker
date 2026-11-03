// Actual Flask/Edge UI, exclusively fictional Issue #38 input and accounts.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-pending-basis/qa');
const fixtures=process.env.QA_BASIS_FIXTURES_DIR,base='http://127.0.0.1:8042';assert(fixtures);fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),cases=[],layouts=[],errors=[];
 for(const screen of ['desktop','mobile'])for(const scenario of ['clean','conflict']){
  const context=await browser.newContext({viewport:{width:screen==='desktop'?1366:390,height:900}}),page=await context.newPage();let posts=0;
  page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{assert(r.url().startsWith(base)||r.url().startsWith('data:'));if(r.method()==='POST')posts++});
  await page.goto(base+'/login');await page.locator('[name=username]').fill('qa-basis18-'+scenario+'-'+screen);
  await page.locator('[name=password]').fill('fictional-preview-ui-password');await page.locator('input[type=submit],button[type=submit]').click();posts=0;
  await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(fixtures,scenario+'.json'));
  await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();
  assert.equal(await page.locator('.ni-preview-record').count(),18);assert.equal(await page.locator('.ni-preview-group').count(),4);
  assert.equal(await page.locator('.ni-source-declared').count(),72);assert(!(await page.locator('.ni-preview-main').allTextContents()).join(' ').includes('Sin dato'));
  assert(!(await page.locator('[name=consent_consumed]').isChecked()));assert(await page.locator('.ni-import-confirm button').isDisabled());
  let state=await(await page.request.get(base+'/qa/basis18-state')).json();assert.equal(state.counts.decision,18);assert.equal(state.summary.energy.value,null);
  assert.equal(state.groupable,scenario==='clean'?18:17);assert.equal(state.logs+state.products+state.receipts,0);assert(state.all_totals_exact);
  for(const phase of ['before','after']){
   if(phase==='after'){
    await page.locator('.ni-import-basis>summary').click();await page.locator('[name=accept_declared_bases]').check();
    await page.getByRole('button',{name:'Aplicar bases declaradas',exact:true}).click();
    state=await(await page.request.get(base+'/qa/basis18-state')).json();assert.equal(state.counts.ready,scenario==='clean'?18:17);
    assert.equal(state.counts.decision,scenario==='clean'?0:1);assert.equal(state.actions.length,1);assert.equal(state.actions[0].count,scenario==='clean'?18:17);
    assert(state.all_totals_exact);assert.equal(Object.keys(state.summary).length,30);assert.equal(state.logs+state.products+state.receipts,0);
    assert(!(await page.locator('[name=consent_consumed]').isChecked()));assert.equal(await page.locator('.ni-import-confirm button').isEnabled(),scenario==='clean');
    assert.equal(await page.locator('.ni-source-declared').count(),scenario==='clean'?0:4);
   }
   for(const theme of ['light','dark'])for(const width of [360,390,430,768,1024,1366]){
    await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
    const geometry=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,tinyInputs:[...document.querySelectorAll('input:not([type=hidden])')].filter(e=>e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<16).length}));
    assert(!geometry.overflow);assert.equal(geometry.tinyInputs,0);layouts.push({screen,scenario,phase,width,theme,...geometry});
   }
   await page.setViewportSize({width:screen==='desktop'?1366:390,height:900});await page.emulateMedia({colorScheme:screen==='desktop'?'dark':'light'});
   await page.screenshot({path:path.join(out,scenario+'-'+phase+'-'+screen+'.png')});
   await page.locator('#import-summary').screenshot({path:path.join(out,scenario+'-'+phase+'-counts-'+screen+'.png')});
  }
  assert.equal(posts,2);cases.push({screen,scenario,records:18,groups:4,ready:state.counts.ready,pending:state.counts.decision,
   nutrients:30,all_totals_exact:true,semantic_POSTs:1,individual_edits:0,consent:false,domain_writes:0});await context.close();
 }
 assert.equal(errors.length,0);await browser.close();fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({status:'PASS',data:'entirely fictional',cases,layouts,errors},null,2));console.log(JSON.stringify({status:'PASS',cases,layouts:layouts.length,errors}));
})().catch(e=>{console.error(e);process.exit(1)});
