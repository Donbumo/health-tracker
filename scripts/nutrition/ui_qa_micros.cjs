// Focused real Flask QA, fictional owner only. Uses bundled Playwright/Edge.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const out=path.resolve(__dirname,'../../design/nutrition-intelligence-3-a/qa');
const state=JSON.parse(fs.readFileSync(path.join(out,'qa-state.json'),'utf8'));
const base='http://127.0.0.1:8031';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext();const page=await context.newPage();
 const errors=[],external=[],checks=[];
 page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{
  if(!route.request().url().startsWith(base)&&!route.request().url().startsWith('data:')){external.push(route.request().url());return route.abort();}
  return route.continue();
 });
 await page.goto(base+'/login');await page.locator('[name=username]').fill(state.username);
 await page.locator('[name=password]').fill('fictional-micros-qa-password');
 await page.locator('input[type=submit],button[type=submit]').click();
 const views={complete:'/nutrition/micronutrients?date=2026-10-26&period=30',
  partial:'/nutrition/micronutrients?date=2026-10-25&period=7',
  qualified:'/nutrition/micronutrients?date=2026-10-24&period=7',
  legacy:'/nutrition/micronutrients?date=2026-10-22&period=30',
  empty:'/nutrition/micronutrients?date=2026-10-23&period=90',
  zero:'/nutrition/micronutrients?date=2026-10-26&period=7&nutrient=vitamin_d',
  meal:'/nutrition/logs/'+state.log};
 for(const theme of ['light','dark'])for(const width of [360,390,430,768,1024,1366]){
  await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:900});
  for(const [name,url] of Object.entries(views)){
   const response=await page.goto(base+url);assert.equal(response.status(),200,name);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,`${name} ${width}: overflow`);
   assert.equal(await page.locator('.ni-micro-table:not(:has(caption))').count(),0);
   assert.equal(await page.locator('.ni-micro-table th:not([scope])').count(),0);
   await page.locator('.ni-tabs a').first().focus();await page.keyboard.press('Tab');
   assert.notEqual(await page.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle),'none');
   if(name==='zero')assert((await page.locator('circle').count())>0,'known zero must be plotted');
   if((name==='complete'||name==='partial')&&(width===390||width===1366)){
    await page.screenshot({path:path.join(out,`${name}-${theme}-${width}.png`),fullPage:true});
    await page.locator('section:has(> header #micro-trend-title)').screenshot({path:path.join(out,`${name}-trend-${theme}-${width}.png`),style:'.topbar{visibility:hidden!important}'});
   }
   if(name==='meal'&&width===390){
    await page.getByText('QA fictional complete food · ver nutrientes y procedencia',{exact:true}).click();
    await page.locator('details.ni-card').last().screenshot({path:path.join(out,`ingredient-${theme}-390.png`),style:'.topbar{visibility:hidden!important}'});
   }
   checks.push({view:name,width,theme,status:response.status(),overflow:false,table_headers:'pass',focus:'visible'});
  }
 }
 // Navigation through the actual rendered links, including immutable source revision.
 await page.goto(base+views.complete);
 await page.getByRole('link',{name:'Todos los nutrientes y fuentes de esta comida'}).click();
 assert(page.url().includes('/nutrition/logs/'));
 await page.getByRole('link',{name:'Ver receta actual'}).click();assert(page.url().includes('/recipes/'));
 await page.goto(base+views.complete);
 await page.getByRole('link',{name:'QA fictional complete food',exact:true}).click();
 assert(page.url().includes('revision=1'));assert.equal(await page.locator('h1').innerText(),'QA fictional complete food');
 await page.goto(base+'/nutrition/?date=2026-10-26');
 await page.getByRole('link',{name:'Explorar micronutrientes y aportaciones'}).click();
 assert(page.url().includes('date=2026-10-26'));
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 fs.writeFileSync(path.join(out,'ui-report.json'),JSON.stringify({data:'QA fictional only',checks,
  combinations:checks.length,flows:['history to micros','consumption to recipe','consumed catalog revision'],errors,external_requests:external},null,2)+'\n');
 console.log(JSON.stringify({combinations:checks.length,errors,external}));await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
