// Real Flask B review, fictional local account; no production calls.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const out=path.resolve(__dirname,'../../design/nutrition-intelligence-3-b/qa');
const state=JSON.parse(fs.readFileSync(path.join(out,'qa-state.json'),'utf8'));
const base='http://127.0.0.1:8032';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext();const page=await context.newPage();const errors=[],external=[],checks=[];
 page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{
  if(!route.request().url().startsWith(base)&&!route.request().url().startsWith('data:')){external.push(route.request().url());return route.abort();}
  return route.continue();
 });
 await page.goto(base+'/login');await page.locator('[name=username]').fill('equivalents-qa');
 await page.locator('[name=password]').fill('fictional-equivalents-qa-password');await page.locator('input[type=submit],button[type=submit]').click();
 const entry=`/nutrition/my-food/${state.key}/equivalents`;
 const compare=entry+`?q=pollo&candidate=${encodeURIComponent(state.candidate)}&amount=150&unit=g&date=2026-10-26`;
 for(const theme of ['light','dark'])for(const width of [360,390,430,768,1024,1366]){
  await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:900});
  for(const [name,url] of Object.entries({candidates:entry+'?q=pollo',comparison:compare,empty:entry+'?q=QA-NO-SUCH-FOOD'})){
   const response=await page.goto(base+url);assert.equal(response.status(),200);
   assert.equal(response.headers()['cache-control'],'private, no-store');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,`${name} ${width}: overflow`);
   assert.equal(await page.locator('input[name=confirm_identity]:checked').count(),0);
   if(name==='comparison'){
    assert((await page.locator('body').innerText()).includes('No se completa ningún nutriente automáticamente'));
    assert.equal(await page.locator('.ni-micro-table:not(:has(caption))').count(),0);
    if(width===390||width===1366)await page.locator('#equivalent-comparison').screenshot({path:path.join(out,`comparison-${theme}-${width}.png`),style:'.topbar{visibility:hidden!important}'});
   }
   if(name==='candidates'&&(width===390||width===1366))await page.screenshot({path:path.join(out,`candidates-${theme}-${width}.png`),fullPage:true});
   await page.locator('.ni-tabs a').first().focus();await page.keyboard.press('Tab');assert.notEqual(await page.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle),'none');
   checks.push({view:name,theme,width,status:200,overflow:false,focus:'visible',confirmation:'unchecked'});
  }
 }
 await page.goto(base+compare);
 await page.locator('[name=confirm_identity]').check();await page.getByRole('button',{name:'Preparar este alimento como otro borrador'}).click();
 assert(page.url().includes('/nutrition/drafts/'));
 assert((await page.locator('.ni-pending').innerText()).includes('1 pendientes'));
 await page.goto(base+'/nutrition/foods/user:'+state.key);
 assert((await page.locator('.ni-shell').innerText()).includes('revisión 1'));
 assert((await page.locator('.ni-shell').innerText()).includes('QA pechuga declarada'));
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 fs.writeFileSync(path.join(out,'ui-report.json'),JSON.stringify({data:'QA fictional only; public catalog',combinations:checks.length,checks,
  explicit_selection:'pending official draft; original revision 1 preserved',errors,external_requests:external},null,2)+'\n');
 console.log(JSON.stringify({combinations:checks.length,explicit_selection:'PASS',errors,external}));await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
