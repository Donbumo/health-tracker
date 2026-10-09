/* Disposable scripts/gym/qa_app.py only; every record below is fictional QA. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

(async () => {
  const output=process.argv[2] || fs.mkdtempSync(path.join(os.tmpdir(),'gym-redesign-qa-'));
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:390,height:844},colorScheme:'dark',reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage(), base='http://127.0.0.1:8011', errors=[], measures=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(base+'/login');
  await page.locator('[name=username]').fill('gym-qa');
  await page.locator('[name=password]').fill('fictional-gym-qa-password');
  await page.locator('button[type=submit],input[type=submit]').first().click();
  await page.waitForURL(url=>!url.pathname.includes('login'));
  async function inspect(name) {
    for (const theme of ['dark','light']) {
      await page.emulateMedia({colorScheme:theme});
      for (const width of [360,390,430,768,1024,1366]) {
        await page.setViewportSize({width,height:844});
        const metrics=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
          smallInputs:[...document.querySelectorAll('.gym input:not([type=hidden]),.gym select')].filter(el=>el.checkVisibility()&&(parseFloat(getComputedStyle(el).fontSize)<16||el.getBoundingClientRect().height<44)).length,
          smallTargets:[...document.querySelectorAll('.gym button,.gym .button,.gym summary,.gym .gym-text-link')].filter(el=>el.checkVisibility()&&(el.getBoundingClientRect().height<44)).length}));
        assert.ok(metrics.scroll<=width+1,`${name}/${theme}: overflow at ${width}`);
        assert.equal(metrics.smallInputs,0,`${name}/${theme}: inputs`);
        assert.equal(metrics.smallTargets,0,`${name}/${theme}: targets`);
        measures.push({name,theme,...metrics});
        if ([390,1366].includes(width)) {
          await page.screenshot({path:path.join(output,`${name}-${theme}-${width}.png`),fullPage:true});
          if (name==='workout') await page.screenshot({path:path.join(output,`${name}-${theme}-${width}-viewport.png`)});
        }
      }
    }
    await page.emulateMedia({colorScheme:'dark'});
    await page.setViewportSize({width:390,height:844});
  }
  await page.goto(base+'/gym/programs/new#import');
  await inspect('import');
  const qaName='QA · Rediseño visual '+Date.now();
  await page.locator('#import-name').fill(qaName);
  await page.locator('#structured-text').fill('Día,Ejercicio,Series,Reps,Carga,RIR,Descanso\nD1,QA Press banca,3,6-8,80kg,2,90\nD1,QA Remo,2,8,40kg,2,60\nDVO2,QA Variante libre,2,8,20kg,2,60');
  await page.getByRole('button',{name:'Preparar preview',exact:true}).click();
  await page.getByRole('heading',{name:'Revisar '+qaName,exact:true}).waitFor();
  for (const select of await page.locator('#gym-mapping select').all()) {
    if (!await select.inputValue()) await select.selectOption('new');
  }
  await page.getByRole('button',{name:'Revisar mappings corregidos',exact:true}).click();
  await page.getByRole('heading',{name:'Revisar '+qaName,exact:true}).waitFor();
  await inspect('preview');
  await page.getByRole('button',{name:'Confirmar programa',exact:true}).click();
  await page.waitForURL(/training-plans/);
  const program=page.locator('[data-program]').filter({has:page.getByRole('heading',{name:qaName,exact:true})});
  await program.locator('[data-day-link]').filter({hasText:'DVO2'}).click();
  await program.getByRole('button',{name:'Ver medio de QA Variante libre'}).click();
  await page.locator('#gym-media-dialog[open]').waitFor();
  assert.match(await page.locator('#gym-media-caption').textContent(),/sin medio asociado/);
  await page.keyboard.press('Escape');
  await program.locator('[data-day-link]').filter({hasText:'D1'}).click();
  await inspect('program');
  await program.getByRole('button',{name:'Iniciar entrenamiento D1',exact:true}).click();
  await page.waitForURL(/gym\/sessions\//);
  const workout=page.url();
  await inspect('workout');
  await page.locator('[data-continue]').click();
  assert.equal(await page.locator(':focus').getAttribute('name'),'load');
  await page.locator('[data-open-media]').first().click();
  await page.locator('#gym-media-dialog[open]').waitFor();
  assert.ok(await page.locator('#gym-media-content img').evaluate(el=>el.complete&&el.naturalWidth>0));
  await page.screenshot({path:path.join(output,'media-dark-390.png')});
  await page.keyboard.press('Escape');
  assert.equal(await page.locator(':focus').getAttribute('data-open-media'),'QA Press banca');
  const first=page.locator('.gym-set').first();
  await first.getByRole('button',{name:'Usar sugerencia',exact:true}).click();
  assert.equal(await page.locator('[data-kpi=completed]').textContent(),'0');
  const saveURL=await first.getAttribute('action');
  let release;
  const gate=new Promise(resolve=>{release=resolve;});
  await page.route('**'+saveURL,async route=>{await gate;await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'QA: fallo simulado, vuelve a intentar'})});});
  await first.getByRole('button',{name:'✓ Completar serie',exact:true}).click();
  assert.ok(await first.locator('[name=load]').isDisabled());
  assert.equal(await page.locator('[data-kpi=completed]').textContent(),'0');
  release();
  await first.locator('.set-status').filter({hasText:'QA: fallo simulado'}).waitFor();
  assert.equal(await first.locator('[name=load]').isDisabled(),false);
  assert.equal(await page.locator('[data-kpi=completed]').textContent(),'0');
  await page.unroute('**'+saveURL);
  await page.reload();
  assert.equal(Number(await first.locator('[name=load]').inputValue()),80);
  await first.locator('[name=reps]').fill('8');
  await first.getByRole('button',{name:'✓ Completar serie',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.gym-set').classList.contains('is-completed'));
  assert.equal(await page.locator('[data-kpi=volume]').textContent(),'640');
  assert.equal(await page.locator('[data-kpi=completed]').textContent(),'1');
  await page.locator('#gym-rest').waitFor();
  await page.getByRole('button',{name:'Minimizar descanso'}).click();
  assert.ok(await page.locator('#gym-rest').evaluate(el=>el.classList.contains('is-minimized')));
  await page.getByRole('button',{name:'Cerrar descanso'}).click();
  for (const index of [1,2]) {
    const form=page.locator('.gym-set').nth(index);
    await form.getByRole('button',{name:'Repetir',exact:true}).click();
    await form.getByRole('button',{name:'✓ Completar serie',exact:true}).click();
    await page.waitForFunction(count=>document.querySelectorAll('.gym-set.is-completed').length===count,index+1);
    await page.getByRole('button',{name:'Cerrar descanso'}).click();
  }
  assert.equal(await page.locator('[data-range-count=ready]').textContent(),'1');
  assert.equal(await page.locator('[data-kpi=percentage]').textContent(),'60%');
  await page.locator('[data-next-exercise]').click();
  assert.equal(await page.locator('.gym-exercise[open]').count(),1);
  assert.equal(await page.locator('.gym-exercise[open]').getAttribute('data-exercise-name'),'QA Remo');
  await page.locator('.gym-exercise').first().locator('summary').first().click();
  await page.locator('.gym-range').first().scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,'range-confirmed-dark-390.png')});
  await page.getByRole('button',{name:'Opciones de la sesión'}).click();
  await page.getByRole('button',{name:'Guardar progreso en edición'}).click();
  assert.match(await page.locator('[data-draft-message]').textContent(),/este dispositivo/);
  await page.getByRole('link',{name:'Reanudar después',exact:true}).click();
  await page.goto(workout);
  assert.equal(await page.locator('.gym-set.is-completed').count(),3);
  await page.getByRole('button',{name:'Finalizar',exact:true}).first().click();
  await page.getByRole('button',{name:'Finalizar entrenamiento',exact:true}).click();
  await page.getByRole('heading',{name:'Resumen del entrenamiento',exact:true}).waitFor();
  await inspect('finished');
  // Compatible presentation fixtures: external media stay opt-in, failed video is recoverable.
  let requested=0, releaseMedia;
  const mediaGate=new Promise(resolve=>{releaseMedia=resolve;});
  const catalog=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../backend/app/static/media/gym-catalog.json'),'utf8'));
  catalog.entries[0].media_url='https://qa-catalog.invalid/clip.webm';
  catalog.entries[0].thumbnail_url='https://qa-catalog.invalid/thumb.png';
  catalog.entries[0].media_type='video';
  await page.route('**/media/gym-catalog.json*',route=>route.fulfill({contentType:'application/json',body:JSON.stringify(catalog)}));
  await page.route('https://qa-catalog.invalid/**',async route=>{requested++;await mediaGate;await route.fulfill({status:404,body:'QA unavailable media'});});
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('[data-exercise-name]').dataset.mediaSource);
  assert.equal(requested,0);
  await page.locator('[data-open-media]').first().click();
  await page.getByRole('button',{name:'Cargar medio externo',exact:true}).click();
  await page.locator('#gym-media-content video').waitFor();
  assert.ok(await page.locator('#gym-media-content video').evaluate(video=>video.controls&&video.preload==='metadata'&&!video.autoplay));
  assert.equal(await page.locator('#gym-media-content').getAttribute('aria-busy'),'true');
  releaseMedia();
  await page.locator('.gym-media-unavailable').waitFor();
  assert.equal(requested,1);
  await page.keyboard.press('Escape');
  await page.unroute('https://qa-catalog.invalid/**');
  catalog.entries[0].media_url='https://qa-catalog.invalid/demo.gif';
  catalog.entries[0].media_type='image';
  await page.route('https://qa-catalog.invalid/demo.gif',route=>route.fulfill({contentType:'image/gif',body:Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7','base64')}));
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('[data-exercise-name]').dataset.mediaSource);
  await page.locator('[data-open-media]').first().click();
  await page.getByRole('button',{name:'Cargar medio externo',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#gym-media-content img')?.naturalWidth===1);
  await page.keyboard.press('Escape');
  const nojs=await browser.newContext({javaScriptEnabled:false,storageState:await context.storageState(),viewport:{width:390,height:844}});
  const plain=await nojs.newPage();
  await plain.goto(workout);
  assert.equal(await plain.locator('.gym-set.is-completed').count(),3);
  assert.equal(await plain.locator('[data-kpi=percentage]').textContent(),'60%');
  await plain.goto(base+'/training-plans');
  assert.ok(await plain.locator('[data-program]').filter({has:plain.getByRole('heading',{name:qaName,exact:true})}).getByRole('button',{name:'Iniciar entrenamiento DVO2',exact:true}).isVisible());
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({status:'passed',checks:measures.length,errors,measures,journey:'Both themes, responsive sizing, text import, arbitrary day names, media/fallback/focus, failed save/freeze/retry, draft recovery, confirmed volume/range, timer, next exercise, resume, finish, no-JS'},null,2));
  console.log(JSON.stringify({status:'passed',output,checks:measures.length}));
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
