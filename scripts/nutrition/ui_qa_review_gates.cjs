// Two focused review gates, actual Flask with fictional predecessor drafts.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-import-consumed/qa');
const base='http://127.0.0.1:8037';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const reports=[],layouts=[],errors=[];
 for(const label of ['mobile','desktop']){
  const context=await browser.newContext({viewport:{width:label==='mobile'?390:1366,height:900}});
  const page=await context.newPage();let posts=0;
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST')posts++;assert(r.url().startsWith(base)||r.url().startsWith('data:'));});
  await page.goto(base+'/login');await page.locator('[name=username]').fill('qa-gates-'+label);
  await page.locator('[name=password]').fill('fictional-review-gates-password');await page.locator('input[type=submit],button[type=submit]').click();
  posts=0;const state=await (await page.request.get(base+'/qa/state')).json();
  await page.goto(base+'/nutrition/import/'+state.key);
  assert.equal(await page.getByRole('button',{name:'Reprocesar original con importador actualizado',exact:true}).count(),1);
  if(label==='mobile')for(const width of [360,390,430,768,1024,1366]){
   await page.setViewportSize({width,height:900});const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
   assert(!overflow);layouts.push({width,overflow});
  }
  await page.setViewportSize({width:label==='mobile'?390:1366,height:900});
  await page.emulateMedia({colorScheme:label==='mobile'?'light':'dark'});
  await page.screenshot({path:path.join(out,'review-gates-old-'+label+'.png')});
  // Reupload is a technical POST, never permission to overwrite old decisions.
  await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(root,'examples/qa/nutrition-import-ux/consumed-text-portions-21.json'));
  await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();assert(page.url().endsWith(state.key));
  const oldForm=page.locator('.ni-import-compatibility form');const oldAction=await oldForm.getAttribute('action');
  const oldData={revision:await oldForm.locator('[name=revision]').inputValue(),csrf_token:await oldForm.locator('[name=csrf_token]').inputValue()};
  await page.getByRole('button',{name:'Reprocesar original con importador actualizado',exact:true}).click();
  const freshUrl=page.url();assert(!freshUrl.endsWith(state.key));
  assert.equal(await page.locator('[name=r1_name]').inputValue(),'QA nombre corregido por usuario');
  assert.equal(await page.locator('[name=r2_amount]').inputValue(),'150');
  assert.equal(await page.locator('[name=r5_equivalence_amount]').inputValue(),'473');
  assert.equal(await page.locator('[name=r5_equivalence_confirmed]').isChecked(),false);
  assert.equal(await page.locator('.ni-import-confirm button').isDisabled(),true);
  await page.locator('.ni-import-exception').filter({has:page.locator('[name=r3_name]')}).getByText('Revisar o corregir declaración y producto privado',{exact:true}).click();
  await page.locator('[name=r3_name]').fill('QA edición posterior nueva');
  for(const i of [4,5,6,7,8,10,11])await page.locator(`[name=r${i}_equivalence_confirmed]`).check();
  await page.locator('[name=r9_portion_label_confirmed]').check();
  await page.getByRole('button',{name:'Usar declaraciones suficientes del archivo',exact:true}).click();
  assert.equal(await page.locator('.ni-import-exception').count(),0);
  assert.equal(await page.locator('.ni-import-confirm button').isDisabled(),true); // retained fields still require acceptance
  const replay=await page.request.post(base+oldAction,{form:oldData,maxRedirects:0});assert.equal(replay.status(),302);assert.equal(base+replay.headers()['location'],freshUrl);
  await page.locator('[name=accept_previous]').check();await page.getByRole('button',{name:'Aceptar campos conservados',exact:true}).click();
  assert.equal(await page.locator('.ni-import-confirm button').isDisabled(),false);
  await page.locator('#import-details').evaluate(e=>e.open=true);
  assert((await page.locator('#import-details').innerText()).includes('QA edición posterior nueva'));
  assert((await page.locator('#import-details').innerText()).includes('163.5'));
  await page.locator('#import-summary').screenshot({path:path.join(out,'review-gates-ready-'+label+'.png')});
  await page.screenshot({path:path.join(out,'review-gates-preview-'+label+'.png'),fullPage:true});
  const form=page.locator('.ni-import-confirm'),action=await form.getAttribute('action');
  const repeat={revision:await form.locator('[name=revision]').inputValue(),token:await form.locator('[name=token]').inputValue(),csrf_token:await form.locator('[name=csrf_token]').inputValue(),consent_consumed:'yes'};
  await page.locator('[name=consent_consumed]').check();await page.locator('.ni-import-confirm button').click();
  assert((await page.locator('body').innerText()).includes('21 registros del archivo guardados'));
  assert.equal((await page.request.post(base+action,{form:repeat})).status(),200);
  await page.screenshot({path:path.join(out,'review-gates-saved-'+label+'.png'),fullPage:true});
  const result=await (await page.request.get(base+'/qa/result')).json();
  assert.equal(result.logs,21);assert.equal(result.products,0);assert.equal(result.receipts,1);
  assert.equal(result.previous_unchanged,true);assert.equal(Number(result.total_kcal),4042.79);assert.equal(result.corrected_name_kept,true);
  reports.push({viewport:label,expired:state.expired,legacy_revision:5,equivalences_verified:7,portion_base_verified:1,retained_fields_accepted_once:true,reprocess_replay_same_review:true,POSTs_browser:posts,additional_API_replays:2,result});
  await context.close();
 }
 const context=await browser.newContext({viewport:{width:390,height:900}}),page=await context.newPage();
 await page.goto(base+'/login');await page.locator('[name=username]').fill('qa-gates-context');await page.locator('[name=password]').fill('fictional-review-gates-password');await page.locator('input[type=submit],button[type=submit]').click();
 const state=await (await page.request.get(base+'/qa/state')).json();await page.goto(base+'/nutrition/import/'+state.key);
 assert((await page.locator('body').innerText()).includes('1 pieza de peso variable'));
 await page.locator('[name=r0_resolution]').selectOption('declared');await page.locator('[name=r0_equivalence_amount]').fill('31');
 await page.locator('[name=r0_equivalence_unit]').selectOption('g');await page.locator('[name=r0_equivalence_confirmed]').check();await page.locator('[name=r0_portion_text_reviewed]').check();
 await page.locator('.ni-import-exception').screenshot({path:path.join(out,'review-gates-contextual-mobile.png'),style:'.topbar,.skip-link{visibility:hidden!important}'});
 await page.getByRole('button',{name:'Aplicar decisiones y actualizar resumen',exact:true}).click();assert.equal(await page.locator('.ni-import-confirm button').isDisabled(),false);
 await page.locator('[name=consent_consumed]').check();await page.locator('.ni-import-confirm button').click();
 const result=await (await page.request.get(base+'/qa/result')).json();assert.equal(result.logs,1);assert.equal(result.products,0);assert.equal(Number(result.total_kcal),31);
 reports.push({case:'contextual fallback',macros_reentered:false,user_verified_mass_g:31,logs:result.logs,products:result.products,total_kcal:result.total_kcal});await context.close();
 assert.deepEqual(errors,[]);const report={status:'PASS',data:'fictional QA only; actual #29 code creates both predecessor drafts',reports,layouts,errors};
 fs.writeFileSync(path.join(out,'review-gates-browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
