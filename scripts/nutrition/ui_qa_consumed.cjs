// Real Flask + Edge; exclusively synthetic loopback records, no production access.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-import-consumed/qa');
const base='http://127.0.0.1:8036';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const reports=[],layouts=[],errors=[];
 for(const label of ['mobile','desktop']){
  const context=await browser.newContext({viewport:{width:label==='mobile'?390:1366,height:900}});
  const page=await context.newPage();let posts=0;
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST')posts++;assert(r.url().startsWith(base)||r.url().startsWith('data:'));});
  await page.goto(base+'/login');await page.locator('[name=username]').fill('qa-consumed-'+label);
  await page.locator('[name=password]').fill('fictional-consumed-password');await page.locator('input[type=submit],button[type=submit]').click();
  posts=0;await page.goto(base+'/nutrition/import');
  await page.locator('#ni-upload').setInputFiles(path.join(root,'examples/qa/nutrition-import-ux/consumed-21.json'));
  await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();
  assert((await page.locator('.ni-import-counts').innerText()).includes('20'));
  assert.equal(await page.locator('.ni-import-exception').count(),20);
  if(label==='mobile')for(const width of [360,390,430,768,1024,1366])for(const theme of ['light','dark']){
   await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);assert(!overflow,{width,theme});
   layouts.push({width,theme,overflow});
  }
  await page.setViewportSize({width:label==='mobile'?390:1366,height:900});
  await page.emulateMedia({colorScheme:label==='mobile'?'light':'dark'});
  await page.screenshot({path:path.join(out,'initial-'+label+'.png'),fullPage:false});
  // Each search POST preserves all other input decisions; no global q.
  await page.locator('[name="r1_p-1_query"]').fill('pollo');
  await page.locator('[name="r2_p-1_query"]').fill('arroz');
  await page.locator('[name="r3_resolution"]').selectOption('declared');
  await page.locator('button[name=search][value="r1_p-1_query"]').click();
  assert.equal(await page.locator('[name="r2_p-1_query"]').inputValue(),'arroz');
  const select=page.locator('[name="r1_p-1_ref"]');
  const choice=select.locator('option').filter({hasText:'QA pollo cocido'});await select.selectOption(await choice.getAttribute('value'));
  for(const i of [4,5,6,7,8])await page.locator(`[name="r${i}_equivalence_confirmed"]`).check();
  // Desktop also creates exactly one private product, inside final transaction.
  if(label==='desktop')await page.locator('[name="r6_resolution"]').selectOption('private');
  // Bulk accepts declared-only rows; selection above wins over bulk for row 2.
  await page.getByRole('button',{name:'Usar declaraciones suficientes del archivo',exact:true}).click();
  assert.equal(await page.locator('.ni-import-exception').count(),0);
  assert.equal(await page.locator('.ni-import-confirm button').isDisabled(),false);
  await page.locator('#import-details').evaluate(e=>e.open=true);
  assert((await page.locator('#import-details').innerText()).includes('163.5'));
  await page.locator('#import-summary').screenshot({path:path.join(out,'ready-'+label+'.png')});
  await page.screenshot({path:path.join(out,'preview-'+label+'.png'),fullPage:true});
  const form=page.locator('.ni-import-confirm');
  const replay={revision:await form.locator('[name=revision]').inputValue(),token:await form.locator('[name=token]').inputValue(),csrf_token:await form.locator('[name=csrf_token]').inputValue(),consent_consumed:'yes'};
  const action=await form.getAttribute('action');
  await page.locator('[name=consent_consumed]').check();await page.locator('.ni-import-confirm button').click();
  assert((await page.locator('body').innerText()).includes('21 registros del archivo guardados'));
  const response=await page.request.post(base+action,{form:replay});assert.equal(response.status(),200);
  assert((await response.text()).includes('21 registros del archivo guardados'));
  await page.screenshot({path:path.join(out,'saved-'+label+'.png'),fullPage:true});
  const domain=await (await page.request.get(base+'/qa/result')).json();assert.equal(domain.logs,21);assert.equal(domain.products,label==='desktop'?1:0);assert.equal(domain.receipts,1);assert.equal(domain.candidate_bound,true);
  reports.push({domain,viewport:label,detected:21,initial_ready:1,initial_decision:20,saved:21,pending:0,private_products:label==='desktop'?1:0,independent_queries:true,existing_candidate_selected:true,confirmed_equivalences:5,declared_without_mass:true,replay_HTTP:200,POSTs_browser:posts,POSTs_including_replay:posts+1,Cache_Control:response.headers()['cache-control']});
  await context.close();
 }
 assert.deepEqual(errors,[]);const report={status:'PASS',data:'fictional QA only',reports,layouts,errors};
 fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
