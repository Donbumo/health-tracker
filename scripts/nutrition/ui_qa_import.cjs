// Scoped real Flask/Edge QA. Fictional loopback accounts only.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-import-ux/qa');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const checks=[],errors=[],external=[];
 async function session(base){
  const context=await browser.newContext();await context.route('**/*',route=>{if(!route.request().url().startsWith(base)&&!route.request().url().startsWith('data:')){external.push(route.request().url());return route.abort();}return route.continue();});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(base+'/login');await page.locator('[name=username]').fill('import-ux-qa');await page.locator('[name=password]').fill('fictional-import-ux-password');await page.locator('input[type=submit],button[type=submit]').click();return {context,page};
 }
 const before=await session('http://127.0.0.1:8036'),old=JSON.parse(fs.readFileSync(path.join(out,'baseline-state.json')));
 for(const width of [390,1366]){await before.page.setViewportSize({width,height:900});await before.page.goto('http://127.0.0.1:8036/nutrition/import/'+old.key+'?step=1');await before.page.screenshot({path:path.join(out,`before-${width}.png`),fullPage:false});}
 await before.context.close();
 const base='http://127.0.0.1:8035',s=await session(base),page=s.page;
 const state=JSON.parse(fs.readFileSync(path.join(out,'ui-state.json'))),url=base+'/nutrition/import/'+state.key;
 for(const theme of ['light','dark'])for(const width of [360,390,430,768,1024,1366]){
  await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:900});
  const response=await page.goto(url);assert.equal(response.status(),200);assert.equal(response.headers()['cache-control'],'private, no-store');
  assert.equal(await page.locator('.ni-import-exception').count(),3);assert.equal(await page.locator('.ni-steps').count(),0);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,theme+' '+width);
  assert.equal(await page.locator('.ni-import-confirm button').isDisabled(),true);
  assert.equal(await page.locator('#import-details[open]').count(),0);
  const primary=await page.locator('.ni-import-confirm button').boundingBox();assert(primary.y+primary.height<=900,'Primary action must be visible without scrolling: '+width);
  assert.equal(await page.locator('table:not(:has(caption))').count(),0);
  if(width===390||width===1366){await page.screenshot({path:path.join(out,`summary-${theme}-${width}.png`),fullPage:false});await page.locator('#import-exceptions').screenshot({path:path.join(out,`exceptions-${theme}-${width}.png`),style:'.topbar,.skip-link{visibility:hidden!important}'});}
  await page.locator('#import-decisions button').focus();assert.notEqual(await page.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle),'none');
  checks.push({theme,width,status:200,exceptions:3,overflow:false,no_store:true,focus:'visible'});
 }
 const download=await page.locator('.ni-original-controls a').getAttribute('href');const original=await page.request.get(base+download);assert.equal(original.status(),200);
 assert.equal(require('node:crypto').createHash('sha256').update(await original.body()).digest('hex'),require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(root,'examples/qa/nutrition-import-ux/mixed-13.json'))).digest('hex'));
 // Count only the user's import submits/navigation. Login, viewport checks and data entry excluded.
 let posts=0,actions=0;const postUrls=[];page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/nutrition/import')){posts++;postUrls.push(new URL(r.url()).pathname.replace(/import\/[^/]+/,'import/<draft>'));}});
 await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(root,'examples/qa/nutrition-import-ux/mixed-13.json'));await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();actions++;
 await page.locator('input[name=q]').fill('QA');await page.getByRole('button',{name:'Buscar candidatos',exact:true}).click();actions++;
 await page.locator('[name=r10_p0_amount]').fill('100');await page.locator('[name=r11_p1_ref]').selectOption({label:'QA pollo cocido · QA cooked · qa_import_ux · r1'});await page.locator('[name=r12_carbohydrate]').selectOption('unknown');
 await page.getByRole('button',{name:'Aplicar decisiones y actualizar resumen',exact:true}).click();actions++;
 assert.equal(await page.locator('.ni-import-exception').count(),0);assert.equal(await page.locator('.ni-import-confirm button').isEnabled(),true);
 await page.setViewportSize({width:390,height:900});await page.screenshot({path:path.join(out,'ready-390.png'),fullPage:false});
 const form=page.locator('.ni-import-confirm');const replay={revision:await form.locator('[name=revision]').inputValue(),token:await form.locator('[name=token]').inputValue(),csrf_token:await form.locator('[name=csrf_token]').inputValue()};const action=await form.getAttribute('action');
 await page.getByRole('button',{name:'Confirmar y guardar plan prescrito',exact:true}).click();actions++;
 assert((await page.locator('.ni-shell').innerText()).includes('13 registros del archivo guardados'));assert((await page.locator('.ni-shell').innerText()).includes('0 pendientes'));
 await page.screenshot({path:path.join(out,'result-390.png'),fullPage:false});
 assert.equal(posts,3);assert.equal(actions,4);
 const duplicate=await page.request.post(base+action,{form:replay});assert.equal(duplicate.status(),200);assert((await duplicate.text()).includes('esta confirmación no creó datos adicionales'));
 // An ordinary ten-record file needs upload plus one global confirmation.
 await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(root,'examples/qa/nutrition-import-ux/normal-10.json'));await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();assert.equal(await page.locator('.ni-import-exception').count(),0);await page.getByRole('button',{name:'Confirmar y guardar plan prescrito',exact:true}).click();assert((await page.locator('.ni-shell').innerText()).includes('10 registros del archivo guardados'));
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 fs.writeFileSync(path.join(out,'ui-report.json'),JSON.stringify({data:'fictional isolated Flask only',checks,baseline_screenshots:[390,1366],mixed_file:{records:13,ingredients:26,initial_ready:10,exceptions:3,POSTs:3,submit_navigation_actions:4,search_GET_actions:1,individual_confirmations:0,saved_records:13,pending:0,replay:'PASS; existing receipt, no additional records'},original_download_sha256:'PASS',normal_file:{records:10,POSTs:2,submit_navigation_actions:2,individual_confirmations:0},errors,external_requests:external},null,2)+'\n');
 console.log(JSON.stringify({responsive_checks:checks.length,mixed_POSTs:3,mixed_actions:4,normal_actions:2,replay:'PASS',errors,external}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
