/* Fictional local QA with every off-origin request blocked. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
(async () => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'ht-catalog-visual-'));
  const browser = await chromium.launch({channel:'msedge', headless:true});
  const context = await browser.newContext({viewport:{width:390,height:844},colorScheme:'dark',serviceWorkers:'block'});
  const base = 'http://127.0.0.1:8013', errors = [], outbound = [], measures = [];
  await context.route('**/*', route => {
    if (!route.request().url().startsWith(base)) { outbound.push(route.request().url()); return route.abort(); }
    return route.continue();
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto(base + '/login');
  await page.locator('[name=username]').fill('catalog-qa');
  await page.locator('[name=password]').fill('fictional-catalog-qa-password');
  await page.locator('[type=submit]').first().click();
  await page.waitForURL(url => !url.pathname.includes('login'));
  async function audit(label) {
    // Decode lazy images before evidence capture, then return to the top.
    for (const image of await page.locator('img[src]').all()) {
      await image.scrollIntoViewIfNeeded();
      await image.evaluate(e => e.decode());
    }
    await page.evaluate(() => scrollTo(0,0));
    for (const theme of ['dark','light']) for (const width of [360,390,430,768,1024,1366]) {
      await page.emulateMedia({colorScheme:theme});
      await page.setViewportSize({width,height:844});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),false,`${label} overflow ${width}`);
      measures.push({label,width,theme});
      if (theme === 'dark' && [390,1366].includes(width)) await page.screenshot({path:path.join(output,`${label}-${width}.png`),fullPage:label!=='catalog'});
    }
    await page.emulateMedia({colorScheme:'dark'});
    await page.setViewportSize({width:390,height:844});
  }
  await page.goto(base + '/exercise-catalog');
  assert.equal(await page.locator('.catalog-card').count(),48);
  await audit('catalog');
  await page.getByRole('textbox',{name:'Buscar'}).fill('leg press');
  await page.getByRole('button',{name:'Buscar',exact:true}).click();
  await page.waitForURL(url => url.searchParams.get('q') === 'leg press');
  await page.locator('.catalog-card').first().waitFor();
  assert.ok(await page.locator('.catalog-card').count() > 1);
  await audit('search');
  await page.locator('.catalog-card a').first().click();
  for (const image of await page.locator('.catalog-gallery img').all()) await image.evaluate(e => e.decode());
  await audit('detail');
  await page.locator('[data-open-media]').first().click();
  await page.locator('#gym-media-content img').first().waitFor();
  assert.equal(await page.locator('#gym-media-content img').count(),2);
  for (const image of await page.locator('#gym-media-content img').all()) await image.evaluate(e => e.decode());
  await page.screenshot({path:path.join(output,'modal-390.png')});
  await page.getByRole('button',{name:'Cerrar medio',exact:true}).click();
  await page.goto(base + '/training-plans');
  const program = page.locator('[data-program]').filter({has:page.getByRole('heading',{name:'QA · Catálogo local',exact:true})});
  await program.locator('.has-media').first().waitFor();
  await audit('training');
  const continuing = page.getByRole('link',{name:/Continuar/}).first();
  if (await continuing.count()) await continuing.click();
  else await program.getByRole('button',{name:'Iniciar entrenamiento QA Day',exact:true}).click();
  await page.waitForURL(/gym\/sessions\//);
  await page.locator('.has-media').first().waitFor();
  await audit('session');
  await page.locator('[data-open-media]').first().click();
  await page.locator('#gym-media-content img').first().waitFor();
  assert.equal(await page.locator('#gym-media-content img').count(),2);
  await page.getByRole('button',{name:'Cerrar medio',exact:true}).click();
  await page.goto(base + '/gym/programs/new');
  // Verify import mappings also work with the server-rendered no-JS form path.
  const draft = {program:{name:'QA Import Variants'},days:[{name:'QA day',exercises:[{raw_name:'prensa',sets:[{set_number:1,reps:8}]}]}]};
  const csrf = await page.locator('[name=csrf_token]').first().inputValue();
  const preview = await context.request.post(base+'/gym/programs/new',{form:{csrf_token:csrf,draft:JSON.stringify(draft)}});
  assert.equal(preview.status(),200);
  const html = await preview.text();
  assert.match(html,/Candidato por búsqueda/);
  assert.match(html,/catalog:/);
  assert.match(html,/Crear nuevo: prensa/);
  assert.deepEqual(outbound,[]);
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({status:'passed',measures,errors,outbound,offline:true,imagesDecoded:true},null,2));
  console.log(JSON.stringify({status:'passed',output,checks:measures.length}));
  await browser.close();
})().catch(error => {console.error(error);process.exit(1);});
