/* Local fictional QA only. Captures the complete browser viewport, never element crops. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
(async()=>{
  const output=process.argv[2]||fs.mkdtempSync(path.join(os.tmpdir(),'gym-visual-review-'));
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:390,height:844},colorScheme:'dark',reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage(),base='http://127.0.0.1:8011',errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(base+'/login');
  await page.locator('[name=username]').fill('gym-qa');
  await page.locator('[name=password]').fill('fictional-gym-qa-password');
  await page.locator('button[type=submit],input[type=submit]').first().click();
  await page.waitForURL(url=>!url.pathname.includes('login'));
  await page.goto(base+'/training-plans');
  const edit=await page.locator('[data-program]').first().getByRole('link',{name:'Editar',exact:true,includeHidden:true}).getAttribute('href');
  await page.goto(base+edit+'#import');
  await page.locator('#import-name').fill('QA · Fuerza 5 días');
  await page.locator('#structured-text').fill('Día,Ejercicio,Series,Reps,Carga,RIR,Descanso\nD1,Press banca,3,6-8,80kg,2,90\nD1,Remo con barra supino,2,8-10,50kg,2,60\nD2,Sentadilla,3,6-8,80kg,2,90\nD3,Press banca,3,8-10,70kg,2,60\nD4,QA Ejercicio sin medio,2,10,20kg,2,60\nD5,Remo con barra supino,3,8-10,50kg,2,60');
  await page.getByRole('button',{name:'Preparar preview',exact:true}).click();
  for(const select of await page.locator('#gym-mapping select').all()) if(!await select.inputValue()) await select.selectOption('new');
  await page.getByRole('button',{name:'Revisar mappings corregidos',exact:true}).click();
  await page.getByRole('button',{name:'Confirmar programa',exact:true}).click();
  await page.waitForURL(/training-plans/);
  await page.getByRole('button',{name:'Iniciar entrenamiento D1',exact:true}).first().click();
  await page.waitForURL(/gym\/sessions\//);
  async function save(index,reps,rir=2){
    const form=page.locator('.gym-set').nth(index);
    await form.locator('xpath=ancestor::details[contains(@class,"gym-exercise")]').evaluate(el=>{el.open=true;});
    await form.getByRole('button',{name:'Usar sugerencia',exact:true}).click();
    await form.locator('[name=reps]').fill(String(reps));
    await form.locator('[name=rir]').fill(String(rir));
    await form.getByRole('button',{name:'✓ Completar serie',exact:true}).click();
    await page.waitForFunction(i=>document.querySelectorAll('.gym-set')[i].classList.contains('is-completed'),index);
    if(await page.locator('#gym-rest').isVisible()) await page.locator('[data-close-timer]').click();
  }
  for(let i=0;i<5;i++) await save(i,i<3?7:8,3);
  await page.locator('[data-open-dialog="gym-finish-dialog"]').first().click();
  await page.getByRole('button',{name:'Finalizar entrenamiento',exact:true}).click();
  await page.getByRole('heading',{name:'Resumen del entrenamiento'}).waitFor();
  await page.goto(base+'/training-plans');
  await page.waitForFunction(()=>document.querySelector('.gym-thumb.has-media img')?.naturalWidth>0);
  const measures=[];
  async function measure(label){
    for(const theme of ['dark','light']) for(const width of [360,390,430,768,1024,1366]){
      await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:844});
      const result=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
        smallInputs:[...document.querySelectorAll('.gym input[type=number]')].filter(el=>el.checkVisibility()&&(parseFloat(getComputedStyle(el).fontSize)<16||el.getBoundingClientRect().height<44)).length,
        smallTargets:[...document.querySelectorAll('.gym button,.gym .button,.gym summary,.gym .gym-text-link')].filter(el=>el.checkVisibility()&&el.getBoundingClientRect().height<44).length}));
      assert.ok(result.scroll<=width+1,`${label}: overflow at ${width}`);assert.equal(result.smallInputs,0);assert.equal(result.smallTargets,0);
      measures.push({label,theme,...result});
    }
    await page.emulateMedia({colorScheme:'dark'});await page.setViewportSize({width:390,height:844});
  }
  async function capture(name){
    await page.screenshot({path:path.join(output,name+'.png')});
    await page.screenshot({path:path.join(output,name+'-pagina-completa.png'),fullPage:true});
  }
  await measure('home');await page.evaluate(()=>scrollTo(0,0));await capture('01-mi-entrenamiento');
  await page.getByRole('button',{name:'Iniciar entrenamiento D1',exact:true}).first().click();
  await page.waitForURL(/gym\/sessions\//);
  await measure('workout');
  await page.locator('.gym-exercise').evaluateAll(cards=>cards.forEach(card=>{card.open=false;}));
  await page.evaluate(()=>scrollTo(0,0));await capture('02-entrenamiento-en-curso');
  await page.locator('.gym-exercise').first().evaluate(el=>{el.open=true;});
  await page.locator('.gym-exercise').first().evaluate(el=>scrollTo(0,el.getBoundingClientRect().top+scrollY-88));
  await capture('03-ejercicio-expandido');
  await save(0,8);await save(1,7,1);
  await page.locator('.gym-range').first().evaluate(el=>{el.open=true;});
  assert.match(await page.locator('[data-range-conclusion]').first().textContent(),/faltan 1 serie/);
  assert.equal(await page.locator('[data-range-label]').first().textContent(),'Dentro del rango');
  await page.locator('.gym-range').first().evaluate(el=>scrollTo(0,el.getBoundingClientRect().top+scrollY-88));
  await capture('04-calculadora-rango');
  await save(2,7);
  assert.equal(await page.locator('[data-kpi=percentage]').textContent(),'60%');
  await page.locator('#gym-dashboard').evaluate(el=>scrollTo(0,el.getBoundingClientRect().top+scrollY-88));
  await capture('05-dashboard-gym');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({viewport:{width:390,height:844},theme:'dark',fictionalData:true,errors,measures,backendSuiteRepeated:false},null,2));
  console.log(JSON.stringify({status:'passed',output,checks:measures.length}));
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
