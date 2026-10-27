// Actual old Flask UI; frozen base sources, synthetic loopback only.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-import-ux/qa'),base='http://127.0.0.1:8036';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1366,height:900}});let posts=0,actions=0,searches=0;
 await page.goto(base+'/login');await page.locator('[name=username]').fill('import-ux-qa');await page.locator('[name=password]').fill('fictional-import-ux-password');await page.locator('input[type=submit],button[type=submit]').click();
 page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/nutrition/import'))posts++;});
 await page.goto(base+'/nutrition/import');await page.locator('#ni-upload').setInputFiles(path.join(root,'examples/qa/nutrition-import-ux/mixed-13.json'));await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();actions++;
 const destination=page.locator('form:has(input[name=action][value=destination])');await destination.locator('[name=destination]').selectOption('plan');await destination.getByRole('button').click();actions++;
 for(let step=1;step<=4;step++){
  if(step>1){await page.locator('.ni-steps a').nth(step-1).click();actions++;}
  for(let i=0;i<13;i++){
   const row=()=>page.locator(`[data-review-row="${i}"]`);
   if(step<=3){
    const form=row().locator('form:has(input[name=action][value=fields])');
    if(step===2){await form.locator('[name=amount]').fill('200');await form.locator('[name=unit]').selectOption('g');await form.locator('[name=total_mass_g]').fill('200');await form.locator('[name=composition_complete]').check();}
    if(step===3){await form.locator('[name=basis_amount]').fill('200');await form.locator('[name=basis_unit]').selectOption('g');if(i===12)await form.locator('[name=carbohydrate_classification]').selectOption('unknown');}
    await form.getByRole('button').click();actions++;
   }
   if(step===2)for(const name of ['QA arroz cocido','QA pollo cocido']){
    // The legacy redirect discards q after every bind: each ingredient needs another search.
    await page.locator('aside input[name=q]').fill('QA');await page.getByRole('button',{name:'Buscar en catálogo local',exact:true}).click();actions++;searches++;
    const bind=row().locator('form:has(input[name=action][value=bind])');const options=await bind.locator('[name=ref] option').allTextContents();const index=options.findIndex(label=>label.startsWith(name+' ·'));assert(index>0);
    await bind.locator('[name=ref]').selectOption({index});await bind.locator('[name=amount]').fill('100');await bind.getByRole('button').click();actions++;
   }
   if(step===4){await row().locator('form:has(input[name=action][value=confirm])').getByRole('button').click();actions++;}
  }
 }
 await page.getByRole('button',{name:'Confirmar y guardar plan prescrito',exact:true}).click();actions++;
 assert((await page.locator('.ni-shell').innerText()).includes('Guardado con confirmación'));assert.equal(posts,81);assert.equal(searches,26);assert.equal(actions,110);
 const report={data:'fictional old real Flask UI only',base:'430164e4f868e0ad5743b49223f87a330107c0b0',records:13,ingredients:26,POSTs:posts,search_GET_actions:searches,stage_navigation_actions:3,submit_navigation_actions:actions,individual_row_confirmations:13,composition_checkboxes:13,destination_confirmations:1,global_confirmations:1,counting:'Button/link activations; field entry, select changes, 13 composition checkboxes and native file picker excluded from 110. Searches repeated because legacy redirects discard q.',saved_records:13};
 fs.writeFileSync(path.join(out,'baseline-browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
