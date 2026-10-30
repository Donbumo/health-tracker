// Real Flask + Edge acceptance. Every account/file is explicitly fictional QA.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'design/nutrition-import-preview/qa');
const base='http://127.0.0.1:8042';
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const cases=[],layouts=[],errors=[];
 for(const screen of ['desktop','mobile'])for(const scenario of ['clean','error','edit']){
  const context=await browser.newContext({viewport:{width:screen==='mobile'?390:1366,height:900},colorScheme:screen==='mobile'?'light':'dark'});
  const page=await context.newPage();let posts=0,clicks=0,fields=0;
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('request',r=>{assert(r.url().startsWith(base)||r.url().startsWith('data:'));if(r.method()==='POST')posts++;});
  await page.goto(base+'/login');await page.locator('[name=username]').fill('qa-preview-'+scenario+'-'+screen);
  await page.locator('[name=password]').fill('fictional-preview-ui-password');
  await page.locator('input[type=submit],button[type=submit]').click();
  posts=0;
  await page.goto(base+'/nutrition/import');
  await page.locator('#ni-upload').setInputFiles(path.join(root,'examples/qa/nutrition-import-preview/'+(scenario==='error'?'one-error-51.json':'clean-21.json')));
  await page.getByRole('button',{name:'Detectar y revisar archivo',exact:true}).click();clicks++;
  const initialUrl=page.url();
  assert.equal(await page.getByRole('heading',{name:'Revisar importación',exact:true}).count(),1);
  assert.equal(await page.locator('.ni-preview-record').count(),scenario==='error'?51:21);
  assert.equal(await page.locator('.ni-row-edit-form').count(),0);
  assert.equal(await page.locator('.ni-import-confirm button').count(),1);
  assert.equal(await page.locator('[name=consent_consumed]').isChecked(),false);
  assert.equal(await page.locator('.ni-preview-record.needs-attention').count(),scenario==='error'?1:0);
  if(scenario==='clean'){
   for(const theme of ['light','dark'])for(const width of [360,390,430,768,1024,1366]){
    await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
    const geometry=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,
      tinyInputs:[...document.querySelectorAll('input:not([type=hidden])')].filter(e=>e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<16).length,
      saveBottom:document.querySelector('.ni-save-all').compareDocumentPosition(document.querySelector('.ni-batch-summary'))===2}));
    assert(!geometry.overflow,JSON.stringify({width,theme,...geometry}));assert.equal(geometry.tinyInputs,0);assert(geometry.saveBottom);
    layouts.push({screen,width,theme,...geometry});
   }
   await page.setViewportSize({width:screen==='mobile'?390:1366,height:900});await page.emulateMedia({colorScheme:screen==='mobile'?'light':'dark'});
  }
  await page.screenshot({path:path.join(out,scenario+'-preview-'+screen+'.png'),fullPage:true});
  await page.screenshot({path:path.join(out,scenario+'-viewport-'+screen+'.png')});
  if(scenario==='error'){
   assert(await page.locator('.ni-import-confirm button').isDisabled());
   await page.locator('#record-25').getByRole('link',{name:'Corregir QA alimento ficticio 26',exact:true}).click();clicks++;
   assert.equal(await page.locator('.ni-row-edit-form').count(),1);
   await page.locator('[name=r25_basis_verified]').check();fields++;
   await page.screenshot({path:path.join(out,'error-editor-'+screen+'.png'),fullPage:true});
   await page.getByRole('button',{name:'Aplicar',exact:true}).click();clicks++;
   assert.equal(await page.locator('.needs-attention').count(),0);
   assert((await page.locator('.ni-batch-summary').innerText()).includes('10,200')||(await page.locator('.ni-batch-summary').innerText()).includes('10200'));
   assert.equal((await(await page.request.get(base+'/qa/preview-state')).json()).logs,0);
   await page.screenshot({path:path.join(out,'error-corrected-'+screen+'.png'),fullPage:true});
  }
  if(scenario==='edit'){
   await page.locator('#record-0 .ni-edit-link').click();clicks++;
   await page.locator('[name=r0_amount]').fill('150');fields++;
   await page.screenshot({path:path.join(out,'quantity-editor-'+screen+'.png'),fullPage:true});
   await page.locator('.ni-inline-editor').screenshot({path:path.join(out,'quantity-editor-detail-'+screen+'.png')});
   await page.getByRole('button',{name:'Aplicar',exact:true}).click();clicks++;
   assert((await page.locator('#record-0').innerText()).includes('300'));
   await page.locator('#record-0 .ni-edit-link').click();clicks++;
   await page.locator('#record-0').getByRole('link',{name:'Nutrientes',exact:true}).click();clicks++;
   await page.locator('[name=r0_contribution_protein]').fill('11');fields++;
   await page.screenshot({path:path.join(out,'macro-editor-'+screen+'.png'),fullPage:true});
   await page.locator('.ni-inline-editor').screenshot({path:path.join(out,'macro-editor-detail-'+screen+'.png')});
   await page.getByRole('button',{name:'Aplicar',exact:true}).click();clicks++;
   const before=(await(await page.request.get(base+'/qa/preview-state')).json()).revision;
   await page.locator('#record-1 .ni-edit-link').click();clicks++;
   await page.locator('[name=r1_amount]').fill('999');fields++;
   await page.getByRole('link',{name:'Cancelar',exact:true}).click();clicks++;
   assert.equal((await(await page.request.get(base+'/qa/preview-state')).json()).revision,before);
   assert(!(await page.locator('#record-1').innerText()).includes('999'));
  }
  assert.equal(await page.locator('.ni-row-edit-form').count(),0);
  const pre=await(await page.request.get(base+'/qa/preview-state')).json();assert.equal(pre.logs,0);assert.equal(pre.products,0);assert.equal(pre.receipts,0);
  assert.equal(pre.counts.ready,scenario==='error'?51:21);
  await page.locator('[name=consent_consumed]').check();fields++;
  // Keyboard submits the only final primary action.
  await page.locator('.ni-import-confirm button').focus();await page.keyboard.press('Enter');clicks++;
  await page.getByRole('heading',{name:'Guardado con confirmación',exact:true}).waitFor();
  assert((await page.locator('body').innerText()).includes((scenario==='error'?'51':'21')+' registros del archivo guardados'));
  const saved=await(await page.request.get(base+'/qa/preview-state')).json();
  assert.equal(saved.logs,scenario==='error'?51:21);assert.equal(saved.products,0);assert.equal(saved.receipts,1);
  if(scenario==='edit'){assert.equal(Number(saved.first_energy),300);assert.equal(Number(saved.first_protein),11);}
  await page.screenshot({path:path.join(out,scenario+'-saved-'+screen+'.png'),fullPage:true});
  cases.push({screen,scenario,button_link_activations:clicks,posts,fields_changed:fields,real_corrections:scenario==='error'?1:0,
   voluntary_row_edits:scenario==='edit'?2:0,cancelled_edits:scenario==='edit'?1:0,...saved});
  await context.close();
 }
 assert.equal(errors.length,0);await browser.close();
 fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({status:'PASS',data:'fictional only',cases,layouts,errors},null,2));
 console.log(JSON.stringify({status:'PASS',cases,layouts:layouts.length,errors}));
})().catch(e=>{console.error(e);process.exit(1)});
