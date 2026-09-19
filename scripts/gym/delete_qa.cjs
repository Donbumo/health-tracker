/* Disposable HTTP fixtures from delete_qa_app.py; never production. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
(async () => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'gym-delete-evidence-'));
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const context = await browser.newContext({viewport:{width:390,height:844}, colorScheme:'dark', serviceWorkers:'block'});
    const page = await context.newPage(), errors = [], measures = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {if(m.type() === 'error') errors.push(m.text());});
    const base = 'http://127.0.0.1:8013';
    await page.goto(base + '/login');
    await page.locator('[name=username]').fill('gym-qa');
    await page.locator('[name=password]').fill('fictional-gym-qa-password');
    await page.locator('[type=submit]').first().click();
    await page.waitForURL(u => !u.pathname.includes('login'));
    for (const [name, blocked] of [['QA historial','historial'], ['QA en curso','en curso'], ['QA sin uso',null]]) {
      await page.goto(base + '/training-plans');
      const card = page.locator('[data-program]').filter({has:page.getByRole('heading',{name,exact:true})});
      await card.getByText('Gestionar mi programa', {exact:false}).click();
      assert.equal(await card.getByText('Archivar rutina',{exact:true}).isVisible(), true);
      await card.getByRole('link',{name:'Eliminar rutina',exact:true}).click();
      if (blocked) {
        assert.match(await page.locator('[role=status]').innerText(), new RegExp(blocked));
        assert.equal(await page.locator('#delete-confirmation').count(),0);
      }
      for(const theme of ['dark','light']) for(const width of [360,390,430,768,1024,1366]) {
        await page.emulateMedia({colorScheme:theme});
        await page.setViewportSize({width,height:844});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        measures.push({name,theme,width});
        if(theme === 'dark' && width === 390) await page.screenshot({path:path.join(output,`${name.replaceAll(' ','-')}-390.png`),fullPage:true});
      }
    }
    await page.setViewportSize({width:390,height:844});
    const deletionUrl = page.url();
    await page.getByRole('link',{name:'Cancelar',exact:true}).click();
    assert.equal(await page.getByRole('heading',{name:'QA sin uso',exact:true}).count(),1);
    await page.goto(deletionUrl);
    const input = page.locator('#delete-confirmation');
    assert.ok(parseFloat(await input.evaluate(e=>getComputedStyle(e).fontSize)) >= 16);
    await input.fill('NO');
    await page.getByRole('button',{name:'Eliminar rutina definitivamente'}).click();
    assert.equal(page.url(),deletionUrl);
    await input.fill('ELIMINAR');
    await page.getByRole('button',{name:'Eliminar rutina definitivamente'}).click();
    await page.waitForURL('**/training-plans');
    assert.equal(await page.getByRole('heading',{name:'QA sin uso',exact:true}).count(),0);
    assert.equal(await page.getByRole('heading',{name:'QA historial',exact:true}).count(),1);
    for(const route of ['/dashboard','/ai','/training-sessions']) {
      const response = await page.goto(base + route);
      assert.equal(response.status(),200);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),false);
    }
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({passed:true,fictionalData:true,measures,errors},null,2));
    console.log(JSON.stringify({passed:true,responsive:measures.length,output}));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
