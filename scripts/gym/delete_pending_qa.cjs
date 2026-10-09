/* Synthetic local fixtures from delete_pending_qa_app.py only. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
(async () => {
 const output = fs.mkdtempSync(path.join(os.tmpdir(), 'gym-pending-final-'));
 const browser = await chromium.launch({channel:'msedge', headless:true});
 try {
  const context = await browser.newContext({viewport:{width:390,height:844},colorScheme:'dark',serviceWorkers:'block'});
  const page = await context.newPage(), errors=[], measures=[];
  page.on('pageerror', error=>errors.push(error.message));
  page.on('console', msg=>{if(msg.type()==='error') errors.push(msg.text());});
  const base='http://127.0.0.1:8014';
  await page.goto(base+'/login');
  await page.locator('[name=username]').fill('pending-qa');
  await page.locator('[name=password]').fill('fictional-pending-qa-password');
  await page.locator('[type=submit]').first().click();
  await page.waitForURL(url=>!url.pathname.includes('login'));
  const open = async name => {
   await page.goto(base+'/training-plans');
   const card=page.locator('[data-program]').filter({has:page.getByRole('heading',{name,exact:true})});
   await card.getByText('Gestionar mi programa',{exact:false}).click();
   await card.getByRole('link',{name:'Eliminar rutina',exact:true}).click();
   assert.equal(await page.locator('dialog').evaluate(e=>e.matches(':modal')),true);
  };
  const measure = async label => {
   for(const theme of ['dark','light']) for(const width of [360,390,430,768,1024,1366]) {
    await page.emulateMedia({colorScheme:theme}); await page.setViewportSize({width,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,label);
    const dialog=page.locator('dialog');
    if(await dialog.count()) assert.equal(await dialog.evaluate(e=>e.scrollWidth>e.clientWidth),false);
    for(const input of await page.locator('input:not([type=hidden]), select').all()) {
     assert.ok(parseFloat(await input.evaluate(e=>getComputedStyle(e).fontSize))>=16);
     assert.ok((await input.boundingBox()).height>=44);
    }
    measures.push({label,theme,width});
    if(width===390) await page.screenshot({path:path.join(output,`${label}-${theme}-390.png`),fullPage:true});
   }
   await page.setViewportSize({width:390,height:844});
  };
  await open('QA integral'); await measure('integral');
  await page.getByRole('link',{name:'Cancelar',exact:true}).click();
  assert.equal(await page.getByRole('heading',{name:'QA integral',exact:true}).count(),1);
  await open('QA integral');
  await page.locator('#delete-confirmation').fill('ELIMINAR');
  await page.getByRole('button',{name:'Eliminar rutina definitivamente'}).click();
  await page.waitForURL('**/training-plans');
  assert.equal(await page.getByRole('heading',{name:'QA integral',exact:true}).count(),0);
  await open('QA parcial'); await measure('parcial');
  await page.locator('#partial-action').selectOption('discard');
  await page.locator('#delete-confirmation').fill('ELIMINAR');
  await page.getByRole('button',{name:'Eliminar rutina definitivamente'}).click();
  assert.equal(await page.locator('#partial-confirmation').evaluate(e=>e.validity.valueMissing),true);
  await page.locator('#partial-action').selectOption('preserve');
  await page.getByRole('button',{name:'Eliminar rutina definitivamente'}).click();
  await page.waitForURL('**/training-plans');
  assert.equal(await page.getByRole('heading',{name:'QA parcial',exact:true}).count(),0);
  await open('QA individual');
  await page.getByRole('link',{name:'Gestionar pendientes individualmente'}).click();
  await measure('pendientes');
  // Resolve each artifact independently. A linked agenda is resolved after its session.
  for(const name of ['Descartar borrador','Descartar sesión y series','Descartar agenda']) {
   const button=page.getByRole('button',{name,exact:true});
   await button.locator('..').locator('[name=confirmation]').fill('DESCARTAR');
   await button.click(); await page.waitForURL('**/pending');
  }
  assert.match(await page.locator('main').innerText(),/No quedan pendientes/);
  await page.goto(base+'/training-plans');
  assert.equal(await page.getByRole('heading',{name:'QA individual',exact:true}).count(),1);
  for(const route of ['/dashboard','/training-sessions','/ai']) assert.equal((await page.goto(base+route)).status(),200);
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({passed:true,measures,errors},null,2));
  console.log(JSON.stringify({passed:true,responsive:measures.length,output}));
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
