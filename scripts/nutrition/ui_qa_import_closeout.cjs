// Focused PR29 closeout: changed states only, synthetic loopback Flask.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-import-ux/qa'),base='http://127.0.0.1:8035',state=JSON.parse(fs.readFileSync(path.join(out,'closeout-state.json')));
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const context=await browser.newContext();const page=await context.newPage();const errors=[],external=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));await context.route('**/*',r=>{if(!r.request().url().startsWith(base)&&!r.request().url().startsWith('data:')){external.push(r.request().url());return r.abort();}return r.continue();});
 await page.goto(base+'/login');await page.locator('[name=username]').fill('import-ux-qa');await page.locator('[name=password]').fill('fictional-import-ux-password');await page.locator('input[type=submit],button[type=submit]').click();
 for(const [width,theme,label] of [[390,'light','mobile'],[1366,'dark','desktop']]){
  await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
  await page.goto(base+'/nutrition/import');assert.equal(await page.locator(`a[href="/nutrition/import/${state.expired}"]`).innerText(),'Ver opciones de recuperación');
  await page.getByRole('heading',{name:'Revisiones vencidas o sin original disponible'}).locator('..').screenshot({path:path.join(out,`closeout-list-${label}.png`),style:'.topbar,.skip-link{visibility:hidden!important}'});
  for(const [view,key] of [['expired',state.expired],['noids',state.representative]]){
   const r=await page.goto(base+'/nutrition/import/'+key);assert.equal(r.status(),200);assert.equal(r.headers()['cache-control'],'private, no-store');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   if(view==='expired'){assert((await page.locator('body').innerText()).includes('decisiones anteriores y sus firmas ya no son utilizables'));assert.equal(await page.locator('.ni-import-confirm').count(),0);assert.equal(await page.getByRole('button',{name:'Crear revisión nueva desde el original'}).isVisible(),true);}
   else assert.equal(await page.locator('.ni-import-exception').count(),6);
   await page.screenshot({path:path.join(out,`closeout-${view}-${label}.png`),fullPage:false});checks.push({view,width,theme,status:200,overflow:false,no_store:true});
  }
 }
 let posts=0,actions=0,searches=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/nutrition/import'))posts++;});
 await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(root,'examples/qa/nutrition-import-ux/representative-plan.csv'));await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();actions++;
 const choices=['QA dieta pollo cocido sin aceite','QA dieta arroz blanco cocido','QA dieta ensalada lechuga y pepino sin aderezo'];
 let needSearch=false;for(let i=0;i<6;i++){const options=await page.locator(`[name="r${i}_p-1_ref"] option`).allTextContents();if(!options.some(x=>x.startsWith(choices[i%3]+' ·')))needSearch=true;}
 if(needSearch){await page.locator('input[name=q]').fill('QA dieta');await page.getByRole('button',{name:'Buscar candidatos',exact:true}).click();actions++;searches++;}
 async function choose(i){const select=page.locator(`[name="r${i}_p-1_ref"]`),labels=await select.locator('option').allTextContents();const index=labels.findIndex(x=>x.startsWith(choices[i%3]+' ·'));assert(index>0);await select.selectOption({index});}
 for(let i=0;i<3;i++)await choose(i);await page.getByRole('button',{name:'Aplicar decisiones y actualizar resumen'}).click();actions++;
 assert.equal(await page.locator('.ni-import-exception').count(),3);assert.equal(await page.locator('.ni-import-confirm button').isDisabled(),true);
 await page.getByRole('link',{name:'Importar archivo',exact:true}).click();actions++;
 await page.getByRole('link',{name:/QA plan sin IDs.csv.*retomar revisión vigente/}).click();actions++;
 assert.equal(await page.locator('.ni-import-exception').count(),3);
 await page.locator('input[name=q]').fill('QA dieta');await page.getByRole('button',{name:'Buscar candidatos',exact:true}).click();actions++;searches++;
 await page.setViewportSize({width:390,height:900});await page.screenshot({path:path.join(out,'closeout-partial-resumed-mobile.png'),fullPage:false});
 for(let i=3;i<6;i++)await choose(i);await page.getByRole('button',{name:'Aplicar decisiones y actualizar resumen'}).click();actions++;
 assert.equal(await page.locator('.ni-import-exception').count(),0);await page.getByRole('button',{name:'Confirmar y guardar plan prescrito',exact:true}).click();actions++;
 assert((await page.locator('body').innerText()).includes('6 registros del archivo guardados'));const representativePOSTs=posts;assert.equal(representativePOSTs,4);
 await page.goto(base+'/nutrition/import/'+state.expired);const recover=page.locator('.ni-import-expired form');const data={revision:await recover.locator('[name=revision]').inputValue(),csrf_token:await recover.locator('[name=csrf_token]').inputValue()};const recoverUrl=await recover.getAttribute('action');
 await page.getByRole('button',{name:'Crear revisión nueva desde el original',exact:true}).click();const recoveredUrl=page.url();assert.notEqual(recoveredUrl,base+'/nutrition/import/'+state.expired);assert.equal(await page.locator('.ni-import-exception').count(),3);
 const replay=await page.request.post(base+recoverUrl,{form:data,maxRedirects:0});assert.equal(replay.status(),302);assert.equal(base+replay.headers()['location'],recoveredUrl);
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 const report={data:'fictional QA only',modified_state_checks:checks,expired_GET_status:200,expiry_is_not_a_500:'NutritionError inherits ValueError; UX recovery fixed',recovery:{new_review:true,expired_decisions_reset:true,replay_same_review:true},representative:{format:'CSV without catalog identifiers',detected:6,ready_initial:0,decisions_initial:6,not_importable_initial:0,manual_identity_selections:6,POSTs:representativePOSTs,button_link_actions:actions,search_GET_actions:searches,partial_decisions_saved:true,exit_and_resume:true,saved_records:6,pending_final:0,consumptions_created:0,counting:'Upload, apply partial, leave to imports, resume, apply remaining, confirm; field/select changes excluded. No textual identity autolinking.'},errors,external_requests:external};
 fs.writeFileSync(path.join(out,'closeout-ui.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
