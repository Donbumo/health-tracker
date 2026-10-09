// Fictional local Flask QA only. Start qa_app.py first; no production requests.
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../../design/nutrition-intelligence-2/production-qa');
const state=JSON.parse(fs.readFileSync(path.join(root,'qa-state.json'),'utf8'));
const base='http://127.0.0.1:8025';
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext();const page=await context.newPage();
  const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!r.url().startsWith(base)&&!r.url().startsWith('data:'))external.push(r.url());});
  await page.goto(base+'/login');await page.locator('[name=username]').fill('nutrition-qa');
  await page.locator('[name=password]').fill('fictional-nutrition-qa-password');
  await page.locator('input[type=submit],button[type=submit]').click();
  const views={today:'/nutrition/?date=2026-10-09',add:'/nutrition/add',search:'/nutrition/foods',
    detail:'/nutrition/foods/'+encodeURIComponent(state.food)+'?draft='+state.draft,
    review:'/nutrition/drafts/'+state.draft,micros:'/nutrition/micronutrients?date=2026-10-09',
    saved:'/nutrition/saved',my_food:'/nutrition/my-food',legacy:'/nutrition/?date=2026-10-08'};
  let combinations=0;
  for(const theme of ['dark','light'])for(const width of [360,390,430,768,1024,1366]){
    await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:width<768?844:900});
    for(const [name,url]of Object.entries(views)){
      const response=await page.goto(base+url);assert.equal(response.status(),200,name);
      assert(await page.locator('.ni-shell').count(),name);
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
      assert(!overflow,`${name} ${width} ${theme} overflow`);
      const bad=await page.locator('.ni-shell input:not([type=hidden]),.ni-shell select').evaluateAll(list=>list.filter(e=>parseFloat(getComputedStyle(e).fontSize)<16).length);
      assert.equal(bad,0,'mobile input fonts');
      const smallTargets=await page.locator('.ni-shell a,.ni-shell button,.ni-shell input:not([type=hidden]),.ni-shell select,.ni-shell summary').evaluateAll(list=>list.filter(e=>{
        const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.height<44;
      }).map(e=>e.tagName));
      assert.deepEqual(smallTargets,[],`${name} ${width} touch targets`);
      await page.keyboard.press('Tab');
      const focus=await page.evaluate(()=>({tag:document.activeElement.tagName,outline:getComputedStyle(document.activeElement).outlineStyle}));
      assert.notEqual(focus.tag,'BODY');assert.notEqual(focus.outline,'none');
      if(width===390||width===1366)await page.screenshot({path:path.join(root,`${name}-${theme}-${width}.png`),fullPage:true});
      if(width===390&&name==='review'&&theme==='dark')await page.screenshot({path:path.join(root,'review-viewport-dark-390.png')});
      if(width===390&&name==='micros'&&theme==='light')await page.screenshot({path:path.join(root,'micros-viewport-light-390.png')});
      combinations++;
    }
  }
  for(const theme of ['dark','light'])for(const width of [390,1366]){
    await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:844});
    for(const [name,url] of Object.entries({balance:'/daily-balance?date=2026-10-07',daily:'/?date=2026-10-07'})){
      const response=await page.goto(base+url);assert.equal(response.status(),200);
      assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)));
      const text=await page.locator('main').innerText();assert.match(text,/subtotal/i);
      assert.match(text,/incompleto|Día incompleto/i);
      await page.keyboard.press('Tab');assert.notEqual(await page.evaluate(()=>document.activeElement.tagName),'BODY');
      await page.screenshot({path:path.join(root,`${name}-${theme}-${width}.png`),fullPage:true});combinations++;
    }
  }
  await page.setViewportSize({width:390,height:844});await page.goto(base+views.review);
  assert.match(await page.locator('.ni-pending').innerText(),/4 pendientes/);
  assert(await page.getByRole('button',{name:'Confirmar y registrar consumo',exact:true}).isDisabled());
  await page.getByRole('button',{name:'Confirmar identidad y cantidad',exact:true}).first().focus();
  await page.keyboard.press('Enter');await page.waitForLoadState('networkidle');
  assert.match(await page.locator('.ni-pending').innerText(),/3 pendientes/);
  while(await page.getByRole('button',{name:'Confirmar identidad y cantidad',exact:true}).count()){
    await page.getByRole('button',{name:'Confirmar identidad y cantidad',exact:true}).first().click();
    await page.waitForLoadState('networkidle');
  }
  assert.match(await page.locator('.ni-pending').innerText(),/0 pendientes/);
  assert(await page.getByRole('button',{name:'Confirmar y registrar consumo',exact:true}).isEnabled());
  for(const theme of ['dark','light'])for(const width of [390,1366]){
    await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:844});
    await page.screenshot({path:path.join(root,`review-ready-${theme}-${width}.png`),fullPage:true});
  }
  await page.goto(base+views.micros);
  const vitamin=page.locator('[data-nutrient=vitamin_d]');assert.equal(await vitamin.getAttribute('data-state'),'partial');
  assert.match(await vitamin.innerText(),/Subtotal conocido/);assert.match(await vitamin.innerText(),/No indica cumplimiento/);
  assert.equal(await page.locator('[data-state=partial] progress').count(),0);
  await page.goto(base+views.my_food);await page.locator('[name=name]').fill('Mi alimento QA sintético');
  await page.locator('[name=energy]').fill('0');await page.locator('[name=protein]').fill('3.25');
  await page.getByRole('button',{name:'Revisar antes de guardar'}).click();
  assert.match(await page.locator('.ni-shell').innerText(),/Energía: 0 kcal/);
  await page.getByRole('button',{name:'Confirmar y guardar alimento'}).click();
  assert.match(await page.locator('.ni-shell h1').innerText(),/QA/);
  assert.equal(errors.length,0);assert.equal(external.length,0);
  const results={combinations,functional_checks:12,errors,external_requests:external,screenshots:48,viewport_extras:2,touch_targets_min_px:44,widths:[360,390,430,768,1024,1366],themes:['dark','light']};
  fs.writeFileSync(path.join(root,'results.json'),JSON.stringify(results,null,2));
  const figures=['today','add','search','detail','review','review-ready','micros','saved','my_food','legacy','balance','daily'].map(name=>`<section><h2>${name}</h2><div>${['dark','light'].flatMap(theme=>[390,1366].map(width=>`<a href="${name}-${theme}-${width}.png"><img loading="lazy" src="${name}-${theme}-${width}.png" alt="${name} ${theme} ${width}"></a>`)).join('')}</div></section>`).join('');
  fs.writeFileSync(path.join(root,'gallery.html'),`<!doctype html><meta charset="utf-8"><title>Nutrition Intelligence · QA productiva ficticia</title><style>body{font-family:system-ui;background:#111;color:#eee;padding:24px}section div{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}img{width:100%;height:400px;object-fit:contain;object-position:top}a{color:#cdf89a}@media(max-width:700px){section div{grid-template-columns:repeat(2,minmax(0,1fr))}}</style><h1>QA productiva · datos ficticios</h1><p>Flask/Jinja real · SQLite efímera · 390/1366 · dark/light</p>${figures}`);
  console.log(JSON.stringify(results));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
