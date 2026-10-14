// Actual Flask/Jinja, fictional account only, existing localhost:8025.
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../../design/nutrition-intelligence-2-1/qa');
const fixture=path.resolve(__dirname,'../../examples/nutrition-2-1/fixtures');
const state=JSON.parse(fs.readFileSync(path.join(root,'qa-state.json'),'utf8'));
const base='http://127.0.0.1:8025';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext();const page=await context.newPage();let checks=[];const errors=[],external=[];
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',route=>{if(!route.request().url().startsWith(base)&&!route.request().url().startsWith('data:')){external.push(route.request().url());return route.abort();}return route.continue();});
 await page.goto(base+'/login');await page.locator('[name=username]').fill(state.username);await page.locator('[name=password]').fill('fictional-nutrition-qa-password');await page.locator('input[type=submit],button[type=submit]').click();
 await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(fixture,'diet-prescribed.pdf'));await page.getByRole('button',{name:'Detectar y revisar archivo'}).click();
 assert(page.url().includes('/nutrition/import/'));const pdf=page.url().replace(base,'');
 assert((await page.locator('.ni-shell').innerText()).includes('2 pendientes'));
 for(const theme of ['dark','light'])for(const width of [390,1366]){await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:844});await page.goto(base+'/nutrition/external');await page.locator('[name=q]').fill('0000000000001');await page.locator('[name=consent]').check();await page.getByRole('button',{name:'Consultar con caché'}).click();await page.screenshot({path:path.join(root,`off-proposals-${theme}-${width}.png`),fullPage:true});}
 await page.getByRole('button',{name:'Seleccionar propuesta y revisar producto privado'}).click();const off=page.url().replace(base,'');
 assert.equal(await page.locator('[name=brand]').inputValue(),'QA comercial');assert.equal(await page.locator('[name=basis_unit]').inputValue(),'ml');assert.equal(await page.locator('[name=protein]').inputValue(),'0');assert.equal(await page.locator('[name=carbohydrate_total]').inputValue(),'');
 const views={history:'/nutrition/?date=2026-10-08&period=30',empty_today:'/nutrition/?date=2026-10-13',
  dashboard_week:'/nutrition/?date=2026-10-12&period=7',dashboard_month:'/nutrition/?date=2026-10-12&period=30',
  catalog:'/nutrition/foods?q=arroz+blanco+cocido',pdf_import:pdf,
  compound_review:'/nutrition/import/'+state.import+'?step=4',photo_label:'/nutrition/import/'+state.label+'?step=3',
  upload_camera:'/nutrition/import',private_product:'/nutrition/my-food',library:'/nutrition/library',
  meal_review:'/nutrition/drafts/'+state.draft,
 import_identity:'/nutrition/import/'+state.import+'?step=1',import_composition:'/nutrition/import/'+state.import+'?step=2',import_declaration:'/nutrition/import/'+state.import+'?step=3',
 photo_confirmation:'/nutrition/import/'+state.label+'?step=4',library_products_page6:'/nutrition/library?kind=products&products_page=6',library_recipes_page6:'/nutrition/library?kind=recipes&recipes_page=6',off_prefill:off,original_retention:'/nutrition/import/'+state.retention+'?step=4',confirmed_retention:'/nutrition/import/'+state.import+'?step=4'};
 for(const theme of ['dark','light'])for(const width of [360,390,430,768,1024,1366]){
  await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:width===390?844:900});
  for(const [name,url] of Object.entries(views)){
   const response=await page.goto(base+url);assert.equal(response.status(),200,`${name} status`);
   if(name==='confirmed_retention')await page.locator('.ni-original-controls summary').click();
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);assert(!overflow,`${name} ${width} ${theme} overflow`);
   const badFonts=await page.locator('.ni-shell input:not([type=hidden]):not([type=checkbox]),.ni-shell select').evaluateAll(items=>items.filter(e=>parseFloat(getComputedStyle(e).fontSize)<16).length);assert.equal(badFonts,0);
   const targets=await page.locator('.ni-shell a,.ni-shell button,.ni-shell summary').evaluateAll(items=>items.filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.height<44;}).map(e=>e.textContent.trim().slice(0,60)));assert.deepEqual(targets,[],`${name}: targets`);
   await page.locator('.ni-tabs a').first().focus();await page.keyboard.press('Tab');
   const focus=await page.evaluate(()=>({tag:document.activeElement.tagName,outline:getComputedStyle(document.activeElement).outlineStyle}));assert.notEqual(focus.tag,'BODY');assert.notEqual(focus.outline,'none');
   if(width===390||width===1366)await page.screenshot({path:path.join(root,`${name}-${theme}-${width}.png`),fullPage:true});
   if(name==='dashboard_month'&&(width===390||width===1366))await page.locator('.ni-energy-trends').screenshot({path:path.join(root,`energy-trends-${theme}-${width}.png`),style:".topbar,.skip-link{visibility:hidden!important}"});
   if(width===390)await page.screenshot({path:path.join(root,`${name}-${theme}-${width}-viewport.png`)});
   checks.push({view:name,width,theme,status:'pass',keyboard:'visible focus',overflow:false});
  }
 }
 // Server-derived chart evidence: independently recompute every rolling window.
 const chart=JSON.parse(fs.readFileSync(path.join(root,'chart-report.json'),'utf8')).points;assert(chart.some(p=>p.state==='partial'));assert(chart.some(p=>p.intake===null));assert(chart.some(p=>p.legacy));assert(chart.some(p=>p.intake!==null&&Number(p.intake)===0));
 for(let i=0;i<chart.length;i++){const p=chart[i],window=chart.slice(Math.max(0,i-6),i+1);const expected=p.state==='complete'&&p.intake!==null&&p.expended!==null?Number(p.intake)-Number(p.expended):null;assert.equal(p.balance===null?null:Number(p.balance),expected);for(const key of ['intake','expended','balance']){const known=window.filter(r=>r[key]!==null&&(key!=='intake'||r.state==='complete'));assert.equal(p.rolling_days[key],known.length);if(known.length)assert(Math.abs(Number(p.rolling[key])-known.reduce((s,r)=>s+Number(r[key]),0)/known.length)<1e-6);else assert.equal(p.rolling[key],null);}}
 checks.push({flow:'legacy_new_partial_gap_zero_and_rolling_arithmetic',status:'pass'});
 // Real end-to-end photo review -> private product, no consumption.
 await page.goto(base+'/nutrition/import/'+state.label+'?step=4');
 await page.getByRole('button',{name:'Proponer producto privado con esta etiqueta'}).click();
 await page.getByRole('button',{name:'Confirmar identidad, cantidad y datos'}).click();
 await page.getByRole('button',{name:'Confirmar y guardar productos privados'}).click();
 assert((await page.locator('.ni-shell').innerText()).includes('Guardado con confirmación'));
 await page.screenshot({path:path.join(root,'photo-product-confirmed-light-1366.png'),fullPage:true});
 await page.goto(base+'/nutrition/library');assert((await page.locator('.ni-shell').innerText()).includes('Bebida QA avena'));
 await page.locator('article.ni-card').filter({has:page.getByRole('heading',{name:'Bebida QA avena',exact:true})}).getByRole('link',{name:'Consultar producto privado'}).click();
 assert((await page.locator('.ni-shell').innerText()).includes('Base 100 ml'));
 checks.push({flow:'photo_local_OCR_to_private_product',status:'pass',basis:'100 ml',consumption:'none'});
 // Edit the complete ml declaration through the signed review, keeping legacy
 // grams unavailable and the original OCR/import receipt unchanged.
 await page.getByRole('link',{name:'Editar declaración del producto'}).click();
 await page.locator('[name=energy]').fill('50');await page.getByRole('button',{name:'Revisar antes de guardar'}).click();
 await page.getByRole('button',{name:'Confirmar y guardar alimento'}).click();
 assert((await page.locator('.ni-shell').innerText()).includes('revisión 2'));
 await page.screenshot({path:path.join(root,'private-product-edited-light-1366.png'),fullPage:true});
 checks.push({flow:'private_ml_product_signed_revision_edit',status:'pass',revision:2});
 // Complete both actual PDF rows with real catalog IDs and explicit quantities.
 for(const [index,query,ref] of [[0,'Pechuga pollo asada',state.food],[1,'Arroz blanco cocido',state.rice]]){
  await page.goto(base+pdf);
  let article=page.locator('.ni-import-row').nth(index);
  let fields=article.locator('form:has(input[name=action][value=fields])');
  await fields.locator('[name=meal_type]').selectOption('lunch');
  await fields.locator('[name=planned_for]').fill('2026-10-05');await fields.getByRole('button',{name:'Guardar identificación'}).click();
  await page.goto(base+pdf+'?step=2&q='+encodeURIComponent(query));article=page.locator('.ni-import-row').nth(index);
  const bind=article.locator('form:has(input[name=action][value=bind])');
  await bind.locator('[name=ref]').selectOption(ref);await bind.locator('[name=amount]').fill('150');await bind.locator('[name=unit]').selectOption('g');
  await bind.getByRole('button',{name:'Vincular identidad y cantidad'}).click();
  await page.goto(base+pdf+'?step=4');article=page.locator('.ni-import-row').nth(index);await article.getByRole('button',{name:'Confirmar identidad, cantidad y datos'}).click();
 }
 assert((await page.locator('.ni-shell').innerText()).includes('0 pendientes'));
 await page.screenshot({path:path.join(root,'pdf-linked-reviewed-light-1366.png'),fullPage:true});
 await page.getByRole('button',{name:'Confirmar y guardar plan prescrito'}).click();
 assert((await page.locator('.ni-shell').innerText()).includes('Guardado con confirmación'));
 await page.screenshot({path:path.join(root,'pdf-plan-confirmed-light-1366.png'),fullPage:true});
 checks.push({flow:'PDF_to_reviewed_plan_real_food_ids',status:'pass',linked_foods:2,consumption:'none'});
 // OFF proposal remains private-form pending until signed final confirmation.
 await page.goto(base+off);await page.locator('[name=energy]').fill('50');await page.getByRole('button',{name:'Revisar antes de guardar'}).click();
 assert((await page.locator('.ni-shell').innerText()).includes('QA OFF bebida ficticia'));await page.screenshot({path:path.join(root,'off-private-pending-light-1366.png'),fullPage:true});
 await page.getByRole('button',{name:'Confirmar y guardar alimento'}).click();assert((await page.locator('.ni-shell').innerText()).includes('Base 100 ml'));await page.screenshot({path:path.join(root,'off-private-confirmed-light-1366.png'),fullPage:true});
 checks.push({flow:'OFF_synthetic_proposal_prefill_review_confirm_private_ml',status:'pass',network:'synthetic upstream fixture; no external request'});
 // Access records beyond 100 through both paging and search.
 for(const [kind,word] of [['products','producto'],['recipes','receta']]){await page.goto(base+`/nutrition/library?kind=${kind}&${kind}_page=6`);assert((await page.locator('.ni-shell').innerText()).includes(`QA biblioteca ${word} 124`));await page.goto(base+`/nutrition/library?kind=${kind}&q=`+encodeURIComponent(`QA biblioteca ${word} 124`));assert((await page.locator('.ni-shell').innerText()).includes('1 resultados'));}
 checks.push({flow:'library_more_than_100_products_and_recipes_paging_search',status:'pass',synthetic_records_each:125});
 // A confirmed source retains original evidence; cancelled unconfirmed file is explicitly removed.
 await page.goto(base+pdf+'?step=4');await page.locator('.ni-original-controls summary').click();assert((await page.locator('.ni-original-controls').innerText()).includes('Original retenido'));assert.equal(await page.getByRole('button',{name:'Eliminar original y cerrar revisión'}).count(),0);
 await page.screenshot({path:path.join(root,'confirmed-source-retained-light-1366.png'),fullPage:true});
 await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(fixture,'external.json'));await page.getByRole('button',{name:'Detectar y revisar archivo'}).click();await page.getByRole('button',{name:'Cancelar importación y conservar original'}).click();
 assert((await page.locator('.ni-shell').innerText()).includes('Revisión cancelada'));await page.locator('.ni-original-controls [name=confirmed]').check();await page.getByRole('button',{name:'Eliminar original y cerrar revisión'}).click();assert((await page.locator('.ni-shell').innerText()).includes('Original eliminado o no adjunto'));await page.screenshot({path:path.join(root,'cancelled-original-deleted-light-1366.png'),fullPage:true});
 checks.push({flow:'unconfirmed_original_delete_confirmed_retention',status:'pass'});
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 fs.writeFileSync(path.join(root,'ui-report.json'),JSON.stringify({data:'QA synthetic only',combinations:Object.keys(views).length*12,checks,errors,external_requests:external},null,2)+'\n');
 console.log(JSON.stringify({combinations:Object.keys(views).length*12,photo_product:'pass',browser_errors:errors,external_requests:external}));await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
