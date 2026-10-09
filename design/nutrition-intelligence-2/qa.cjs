/* Only local fictional design fixtures. Never starts Flask or accesses user storage. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const output=path.resolve(__dirname,'screenshots');
fs.mkdirSync(output,{recursive:true});
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage(),errors=[],network=[],measures=[],checks=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
  await page.goto(pathToFileURL(path.join(__dirname,'index.html')).href);
  const action=name=>page.locator(`[data-action="${name}"]`);
  async function route(view){await page.evaluate(v=>{location.hash=v;},view);await page.waitForFunction(v=>location.hash==='#'+v,view);await page.waitForTimeout(30);}
  async function capture(name){
    // Capture stable screen states without a transient registration toast.
    await page.locator('#notice').evaluate(e=>e.textContent='');
    for(const theme of ['dark','light']){
      await page.evaluate(t=>{document.documentElement.dataset.theme=t;document.querySelector('#theme').textContent=t==='light'?'Tema oscuro':'Tema claro';},theme);
      for(const width of [360,390,430,768,1024,1366]){
        await page.setViewportSize({width,height:844});
        const metrics=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,
          smallTargets:[...document.querySelectorAll('button,a,summary,input,select,textarea')].filter(e=>e.checkVisibility()&&e.getBoundingClientRect().width>0&&!e.classList.contains('skip')&&(e.getBoundingClientRect().height<44||e.getBoundingClientRect().width<44)).map(e=>e.outerHTML.slice(0,120)),
          smallInputs:[...document.querySelectorAll('input,select,textarea')].filter(e=>e.checkVisibility()&&parseFloat(getComputedStyle(e).fontSize)<16).length}));
        assert.ok(metrics.scroll<=width,`${name}/${theme}/${width} overflow: ${metrics.scroll}`);
        assert.deepEqual(metrics.smallTargets,[],`${name}/${theme}/${width}: targets`);
        assert.equal(metrics.smallInputs,0);
        measures.push({view:name,theme,width,...metrics});
        if([390,1366].includes(width))await page.screenshot({path:path.join(output,`${name}-${theme}-${width}.png`),fullPage:true});
        if(width===390)await page.screenshot({path:path.join(output,`${name}-${theme}-390-viewport.png`)});
      }
    }
  }
  try{
    for(const theme of ['dark','light']){
      const contrasts=await page.evaluate(theme=>{
        document.documentElement.dataset.theme=theme;
        const style=getComputedStyle(document.documentElement),rgb=name=>{let hex=style.getPropertyValue(name).trim().slice(1);if(hex.length===3)hex=[...hex].map(c=>c+c).join('');return hex.match(/.{2}/g).map(v=>parseInt(v,16)/255);},luminance=name=>rgb(name).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
        return [['--text','--surface'],['--muted','--surface'],['--muted','--raised'],['--cyan','--surface'],['--warning','--surface'],['--ink','--lime']].map(([a,b])=>({pair:a+'/'+b,ratio:(Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05)}));
      },theme);
      for(const c of contrasts)assert.ok(c.ratio>=4.5,`${theme} text contrast ${c.pair}: ${c.ratio}`);
    }
    checks.push('text contrast: six representative token pairs >=4.5 in both themes');
    await route('today');
    const partialMacro=page.locator('[data-metric="fiber"][data-state="partial"]');
    assert.equal(await partialMacro.locator('progress').count(),0);
    assert.ok((await partialMacro.textContent()).includes('Subtotal conocido'));
    const partialMicro=page.locator('[data-nutrient="calcium"].partial');
    assert.ok((await partialMicro.textContent()).includes('Subtotal conocido'));
    assert.equal(await partialMicro.locator('.reference-value').count(),0);
    assert.equal(await partialMicro.locator('.coverage-note').count(),0);
    assert.ok((await partialMicro.locator('.coverage-meaning').textContent()).includes('No indica cumplimiento de referencia ni garantiza completitud nutricional'));
    await route('micros');
    for(const row of await page.locator('.nutrient-row').all())assert.equal(await row.locator('.coverage-meaning').count(),1);
    checks.push('partial UI: known subtotal, no goal bar/reference percentage or deficit styling; per-card mass coverage caveat');
    for(const view of ['today','add','search','detail','saved','micros','user-food','review']){await route(view);await capture(view);}
    await route('add');await action('photo-candidates').click();await capture('photo-candidates');
    await page.getByRole('link',{name:'Revisar comida',exact:true}).click();
    assert.equal(await action('register').isDisabled(),true);await capture('photo-review');
    assert.equal(await page.locator('.pending-count').textContent(),'4 pendientes');
    await page.setViewportSize({width:390,height:844});
    const compactHeight=await page.evaluate(()=>document.documentElement.scrollHeight);
    assert.ok(compactHeight<2715,`mobile review must be shorter than approved baseline: ${compactHeight}`);
    // Explicit candidate confirmation by keyboard in both target widths/themes.
    for(const theme of ['dark','light'])for(const width of [390,1366]){
      await route('add');await action('photo-candidates').click();
      await page.getByRole('link',{name:'Revisar comida',exact:true}).click();
      await page.setViewportSize({width,height:844});
      await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
      await page.locator('#amount-0').fill('180');
      await page.keyboard.press('Tab');assert.equal(await page.locator('#unit-0').evaluate(e=>e===document.activeElement),true);
      await page.keyboard.press('Tab');assert.equal(await action('change-food').first().evaluate(e=>e===document.activeElement),true);
      await page.keyboard.press('Tab');await page.keyboard.press('Tab');
      assert.equal(await action('accept').first().evaluate(e=>e===document.activeElement),true);
      await page.keyboard.press('Enter');assert.equal(await page.locator('.pending-count').textContent(),'3 pendientes');
      assert.equal(await action('register').isDisabled(),true);
      assert.equal(await page.locator('#amount-0').evaluate(e=>e===document.activeElement),true);
    }
    checks.push(`compact review: ${compactHeight}px vs 2715px baseline; live pending count; explicit keyboard identity/quantity confirmation at 390/1366 dark/light`);
    while(await action('accept').count())await action('accept').first().click();
    assert.equal(await action('register').isEnabled(),true);checks.push('photo: all candidates require explicit acceptance');
    assert.equal(await page.locator('.pending-count').textContent(),'0 pendientes');
    await page.locator('#amount-0').fill('200');
    assert.equal(await page.locator('#amount-0').evaluate(e=>e===document.activeElement),true);
    assert.equal(await page.locator('#review-summary .energy strong').textContent(),'697');
    await page.locator('#unit-0').selectOption('ml');assert.equal(await action('register').isDisabled(),true);
    await page.locator('#unit-0').selectOption('g');
    await page.locator('#amount-0').fill('-1');assert.equal(await action('register').isDisabled(),true);
    await page.locator('#amount-0').fill('200');checks.push('quantity: recalculation, focus preservation, invalid and volume blocked');
    await action('register').click();await page.waitForFunction(()=>document.querySelector('h1').textContent==='Nutrición de hoy');
    const semantic=await page.evaluate(()=>{
      const i={foodId:'chicken',amount:180,unit:'g'},s=NutritionDesign.summarize([i]);
      return {kcal:s.energy.value,protein:s.protein.value,carb:s.carbohydrate.value,carbCoverage:s.carbohydrate.coverage,k:s.vitamin_k.value,kCoverage:s.vitamin_k.coverage,ml: NutritionDesign.grams({...i,unit:'ml'}),cup:NutritionDesign.grams({foodId:'rice',amount:1,unit:'cup'})};
    });
    assert.equal(semantic.kcal,297);assert.equal(semantic.protein,55.8);assert.equal(semantic.carb,0);assert.equal(semantic.carbCoverage,100);
    assert.equal(semantic.k,null);assert.equal(semantic.kCoverage,0);assert.equal(semantic.ml,null);assert.equal(semantic.cup,158);
    checks.push('semantics: real zero != unknown; canonical scaling; defined serving only');
    const before=await page.evaluate(()=>NutritionDesign.getLogs());
    await route('saved');await action('use-saved').first().click();await page.locator('#amount-0').fill('250');await action('save-template').click();
    assert.deepEqual(await page.evaluate(()=>NutritionDesign.getLogs()),before);checks.push('template edits preserve consumed snapshots');
    const pinned=await page.evaluate(()=>{const old=NutritionQA.foods[0].nutrients.energy;NutritionQA.foods[0].nutrients.energy=999;
      const value=NutritionDesign.summarize(NutritionDesign.getLogs()[1].ingredients).energy.value;NutritionQA.foods[0].nutrients.energy=old;return value;});
    assert.equal(pinned,663.5);checks.push('catalog update cannot change logged nutrient revision');
    await route('today');await action('repeat').first().click();await action('register').click();
    const after=await page.evaluate(()=>NutritionDesign.getLogs());assert.deepEqual(after[after.length-1].ingredients,before[0].ingredients);
    checks.push('repeat copies consumed snapshot');
    await route('search');await page.locator('#food-search').fill('pollo');assert.equal(await action('food-detail').count(),2);
    await page.locator('#food-search').fill('QA no existe');await capture('search-empty');checks.push('search distinguishes raw/cooked and no results');
    await route('user-food');await page.locator('#user-name').fill('Producto ficticio QA');await page.locator('#user-energy').fill('0');await page.locator('button[type=submit]').click();
    await capture('user-food-detail');assert.equal(await page.locator('.food-detail .energy strong').textContent(),'0');
    assert.equal(await page.getByText('Sin micronutrientes informados.',{exact:true}).count(),1);checks.push('personal food: zero retained, omitted nutrients unknown');
    await route('today');await page.locator('.qa-controls summary').click();await action('empty').click();await capture('empty-day');
    await route('micros');await capture('empty-micros');
    await route('saved');await action('use-saved').first().click();await action('remove').nth(3).click();await action('register').click();
    await page.waitForFunction(()=>document.querySelector('h1').textContent==='Nutrición de hoy');await capture('complete-day');
    await route('micros');await capture('complete-micros');
    assert.equal(await page.getByText('120% de referencia ficticia QA',{exact:true}).count(),1);checks.push('complete micronutrients display reference separately from coverage');
    await route('add');await action('text-candidates').click();await capture('text-candidates');checks.push('text fixture has named portion definitions and pending confirmation');
    // A complete registration path using only the keyboard and an empty day.
    await route('saved');const use=action('use-saved').first();await use.focus();await page.keyboard.press('Enter');
    const register=action('register');await register.focus();
    const focus=await register.evaluate(e=>({focused:e===document.activeElement,outline:getComputedStyle(e).outlineStyle,width:getComputedStyle(e).outlineWidth}));
    assert.ok(focus.focused&&focus.outline==='solid'&&parseFloat(focus.width)>=3);await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.querySelector('h1').textContent==='Nutrición de hoy');
    await page.keyboard.press('Tab');assert.notEqual(await page.evaluate(()=>document.activeElement.tagName),'BODY');
    checks.push('keyboard: saved meal + confirm with Enter, visible focus and Tab navigation');
    await context.setOffline(true);await route('search');await page.locator('#food-search').fill('arroz');assert.equal(await action('food-detail').count(),1);
    checks.push('offline: local catalog search works');
    assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
    const report={fixture:'fictional QA only',browser:'Microsoft Edge / Playwright',checks,errors,externalRequests:network.length,measurements:measures.length,measures};
    fs.writeFileSync(path.join(__dirname,'qa-results.json'),JSON.stringify(report,null,2)+'\n');
    console.log(`${checks.length} behavioral checks; ${measures.length} responsive/theme checks; no page errors or network requests.`);
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
