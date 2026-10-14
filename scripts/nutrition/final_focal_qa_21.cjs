// Final authorized scope only: first viewport and relevant catalog queries.
// Uses the existing synthetic Flask QA server; no writes or external calls.
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../../design/nutrition-intelligence-2-1/qa');
const base='http://127.0.0.1:8025';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();const errors=[],external=[],checks=[],searches=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(!request.url().startsWith(base))external.push(new URL(request.url()).origin);});
  await page.goto(base+'/login');await page.locator('[name=username]').fill('nutrition-qa');
  await page.locator('[name=password]').fill('fictional-nutrition-qa-password');
  await page.locator('input[type=submit],button[type=submit]').click();
  const cases=[['day','2026-10-12','energía completa'],['empty','2026-10-14','Último registro · 2026-10-12'],
   ['partial','2026-10-08','energía parcial'],['legacy','2026-09-13','energía parcial'],
   ['zero','2026-09-25','0 kcal']];
  for(const theme of ['dark','light'])for(const width of [390,1366]){
   await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:844});
   for(const [name,date,expected] of cases){
    const response=await page.goto(base+'/nutrition/?date='+date);assert.equal(response.status(),200);
    const first=page.getByRole('region',{name:'Resumen nutricional inicial'});
    // section with aria-label has an implicit region role.
    assert((await first.innerText()).replace(/\s+/g,' ').includes(expected),name);
    const box=await first.boundingBox();assert(box&&box.y>=0&&box.y+box.height<=844,`${name}: complete summary in first viewport`);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    const nav=await page.getByRole('navigation',{name:'Nutrición',exact:true}).boundingBox();assert(box.y+box.height<=nav.y);
    assert.equal(await page.locator('.ni-date-nav input[name=date]').count(),1);
    await first.getByRole('link',{name:'Añadir comida'}).focus();await page.keyboard.press('Tab');
    assert.notEqual(await page.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle),'none');
    const screenshot=`final-first-${name}-${theme}-${width}.png`;
    if(width===390)await page.screenshot({path:path.join(root,screenshot)});
    checks.push({case:name,date,width,theme,status:'pass',summary_bottom:Math.round(box.y+box.height),
     overflow:false,keyboard:'visible focus',screenshot:width===390?screenshot:null});
   }
  }
  const queries=['arroz integral','arroz integral cocido','arroz integral crudo','brown rice',
   'harina de arroz integral','brown rice pasta','arroz blanco cocido','tortilla de maíz','totopos',
   'pollo crudo','pollo cocido','frijoles','avena','bimbo'];
  for(const query of queries){
   const timings=[];let matches;
   for(let trial=0;trial<3;trial++){
    const started=performance.now();const response=await page.goto(base+'/nutrition/foods?q='+encodeURIComponent(query));
    assert.equal(response.status(),200);timings.push(Math.round((performance.now()-started)*100)/100);
    matches=await page.locator('.ni-link').evaluateAll(items=>items.map(item=>({name:item.querySelector('h2').textContent,
      ref:new URL(item.href).pathname.split('/').pop(),description:item.innerText})));
   }
   assert(matches.length>0,query);
   if(['arroz integral','arroz integral cocido','arroz integral crudo','brown rice'].includes(query)){
    assert(!/flour|harina|pasta|noodle|fideo|babyfood|with | and /i.test(matches[0].name),query+': simple grain first');
    assert(/brown|integral/i.test(matches[0].name));assert(!/white/i.test(matches[0].name));
   }
   if(query==='harina de arroz integral')assert(/flour|harina/i.test(matches[0].name));
   if(query==='brown rice pasta')assert(/pasta/i.test(matches[0].name));
   searches.push({query,candidates_in_first_page:matches.length,top_5:matches.slice(0,5),http_page_timings_ms:timings});
  }
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  const report={date:'2026-10-14',data:'Synthetic account; real public catalog. No writes.',
   checks,queries:searches,errors,external_requests:external,measurement:'Three full Flask HTML page loads per query; not raw SQL latency.'};
  fs.writeFileSync(path.join(root,'final-focal-report.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({viewport_checks:checks.length,mobile_captures:checks.filter(c=>c.screenshot).length,
   queries:searches.length,plain_rice:searches[0].top_5.map(m=>m.name),errors,external}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
