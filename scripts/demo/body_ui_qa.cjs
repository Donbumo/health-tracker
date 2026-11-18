// Real Flask seeded with explicitly fictional records; no NAS access.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const base=process.env.DEMO_QA_URL;
assert(base && /^http:\/\/127\.0\.0\.1:\d+$/.test(base),'Use the temporary loopback QA app');
const out=path.resolve(__dirname,'../../design/demo-body/qa');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext(),page=await context.newPage(),errors=[],bad=[],layouts=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.status()>=400)bad.push({status:r.status(),path:r.url().replace(base,'')})});
  await page.route('**/*',route=>route.request().url().startsWith(base)||route.request().url().startsWith('data:')?route.continue():route.abort());
  await page.goto(base+'/login');
  await page.locator('[name=username]').fill('demo@healthtracker.test');
  await page.locator('[name=password]').fill('fictional-demo-browser-password');
  await page.locator('[type=submit]').first().click();await page.waitForURL('**/dashboard');
  const routes=['/dashboard?from=2026-10-01&to=2026-11-18',
   '/dashboard?from=2026-11-01&to=2026-11-18&compare=month-to-date',
   '/dashboard?preset=previous-month&as_of=2026-11-18','/weigh-ins','/weigh-ins/history'];
  for(const route of routes){
   await page.goto(base+route);
   for(const width of [360,390,430,768,1024,1366]){
    await page.setViewportSize({width,height:900});
    assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),route+' overflow '+width);
    layouts.push({route,width,overflow:false});
   }
  }
  await page.goto(base+routes[0]);
  assert.equal(await page.locator('[data-dashboard-chart="weight"] svg').count(),1);
  assert.equal(await page.locator('#body-metric-select option').count(),5);
  for(const width of [390,1366]){
   await page.setViewportSize({width,height:900});
   await page.locator('section:has(#weight-title)').screenshot({path:path.join(out,'weight-'+width+'.png')});
   for(const metric of ['body_fat','muscle_mass','water','visceral_fat','bmi']){
    await page.locator('#body-metric-select').selectOption(metric);
    assert.equal(await page.locator('[data-dashboard-chart="body"] svg').count(),1);
    assert(!(await page.locator('[data-body-current]').innerText()).includes('Sin datos'));
    await page.locator('section:has(#body-title)').screenshot({path:path.join(out,metric+'-'+width+'.png')});
   }
  }
  await page.goto(base+routes[1]);
  await page.screenshot({path:path.join(out,'november-vs-october.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(bad,[]);
  const report={scope:'Only fictional local DEMO, temporary SQLite, real Flask/domain services',
   routes:routes.length,layouts:layouts.length,body_metrics:5,javascript_errors:errors,unexpected_http:bad};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
 }finally{await browser.close()}
})().catch(e=>{console.error(e.message);process.exit(1)});
