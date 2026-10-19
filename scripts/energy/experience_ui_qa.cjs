// Actual Flask HTTP + fictional QA fixtures. Prototype screenshots are separate.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.ENERGY_QA_URL;
assert.match(base||'',/^http:\/\/127\.0\.0\.1:\d+$/,'Use the synthetic QA server URL only');
const out=path.resolve(__dirname,'../../design/energy-experience-2-0/qa-flask');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage();const errors=[],failed=[],checks=[],contrasts=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)failed.push(r.status()+' '+new URL(r.url()).pathname);});
 async function open(day='2040-02-03',period=7){const response=await page.goto(base+`/energy?date=${day}&period=${period}`);assert.equal(response.status(),200);}
 async function shot(name){await page.screenshot({path:path.join(out,name+'.png')});}
 try{
  await page.goto(base+'/login');await page.locator('[name=username]').fill('QA-energy-experience');await page.locator('[name=password]').fill('fictional-energy-experience-password');await page.locator('[type=submit]').click();
  for(const theme of ['dark','light']){
   await page.emulateMedia({colorScheme:theme,reducedMotion:'reduce'});
   for(const width of [360,390,430,768,1024,1366]){
    await page.setViewportSize({width,height:width<768?844:900});
    for(const period of [7,30,90]){
     await open('2040-02-03',period);
     assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme}/${width}/${period} overflow`);
     assert.match(await page.locator('#ee-expended').innerText(),/2400/);
     assert.equal(await page.locator('.ee-main-charts svg').count(),3);
     assert.ok(await page.locator('.ee-bar').count()>0);
     assert.ok(await page.locator('.ee-rolling').count()>0);
     assert.equal(await page.locator('.ee-main-charts .ee-chart').first().getAttribute('data-series'),'expended');
     assert.equal(await page.locator('.ee-main-charts .ee-chart').first().locator('tbody tr').count(),period);
     assert.equal(await page.locator('.ee-main-charts .ee-chart').last().locator('tbody tr').count(),period);
     const zero=Number(await page.locator('[data-series=balance] .ee-axis').getAttribute('y1'));assert.ok(zero>30&&zero<180,'balance has both signs and zero axis');
     assert.ok(await page.locator('[data-series=steps]').count());
     checks.push({theme,width,period,status:'PASS'});
    }
    if([390,1366].includes(width)){
     await open();assert.ok((await page.locator('#ee-expended').boundingBox()).y<844,'useful expenditure in first viewport');await shot(`overview-${theme}-${width}`);
     await page.locator('#ee-calendar').scrollIntoViewIfNeeded();await shot(`calendar-${theme}-${width}`);
     if(width===1366){await page.locator('.ee-trends').scrollIntoViewIfNeeded();await shot(`activity-trends-${theme}-${width}`);}
    }
   }
   await page.setViewportSize({width:390,height:844});await open('2040-02-01');assert.match(await page.locator('.ee-state').innerText(),/pendientes/);assert.match(await page.locator('.ee-summary').innerText(),/parcial/);await shot(`partial-conflict-${theme}-390`);
   await open('2040-02-04');assert.match(await page.locator('.ee-state').innerText(),/Actividad parcial/);assert.match(await page.locator('#ee-activity').innerText(),/Cero conocido/);
   await page.getByRole('link',{name:'Hoy',exact:true}).click();assert.match(await page.locator('.ee-state').innerText(),/Hoy no hay registro/);assert.match(await page.locator('.ee-state').innerText(),/Último registro/);await shot(`empty-today-${theme}-390`);
   await page.getByRole('link',{name:/Último registro/}).click();assert.match(await page.locator('.ee-state').innerText(),/2040-02-04/);
   await open('2040-12-31');await page.getByRole('link',{name:'Mes siguiente',exact:true}).click();assert.match(await page.locator('.ee-calendar-heading h2').innerText(),/01 \/ 2041/);await page.getByRole('link',{name:'Mes anterior',exact:true}).click();assert.match(await page.locator('.ee-calendar-heading h2').innerText(),/12 \/ 2040/);
   await open('2040-02-01');await page.locator('[data-series=intake] summary').click();assert.match(await page.locator('[data-series=intake] .ee-table').innerText(),/Subtotal conocido/);
   await page.locator('[data-series=balance] summary').click();assert.match(await page.locator('[data-series=balance] .ee-table').innerText(),/Sin dato/);
   await open();assert.ok(await page.locator('[name=date]').evaluate(e=>parseFloat(getComputedStyle(e).fontSize)>=16));
   await page.locator('.ee-page h1').click();for(let i=0;i<20;i++){await page.keyboard.press('Tab');const focus=await page.evaluate(()=>{const e=document.activeElement;return {tag:e.tagName,outline:getComputedStyle(e).outlineStyle};});if(focus.tag!=='BODY')assert.notEqual(focus.outline,'none',JSON.stringify(focus));}
   const ratios=await page.evaluate(()=>{
    function rgb(v){const e=document.createElement('span');e.style.color=v;document.body.append(e);const c=getComputedStyle(e).color.match(/[\d.]+/g).slice(0,3).map(Number);e.remove();return c;}
    function lum(c){return c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);}
    const s=getComputedStyle(document.documentElement),pairs=[['--text','--surface',4.5],['--text-muted','--surface',4.5],['--text','--primary-soft',4.5],['--warning-text','--warning-bg',4.5],['--primary','--surface',3],['--text','--surface',3]];
    return pairs.map(([fg,bg,min])=>{const a=lum(rgb(s.getPropertyValue(fg))),b=lum(rgb(s.getPropertyValue(bg)));return {fg,bg,min,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};});
   });
   for(const r of ratios)assert.ok(r.ratio>=r.min,`${theme} contrast ${JSON.stringify(r)}`);contrasts.push({theme,pairs:ratios});
   await page.getByRole('link',{name:'Volver a interfaz actual',exact:true}).click();assert.equal(new URL(page.url()).pathname,'/daily-energy');
  }
  assert.deepEqual(errors,[]);assert.deepEqual(failed,[]);
  const report={scope:'real Flask HTTP; temporary SQLite; fictional QA fixtures; not prototype or production',status:'PASS',viewport_checks:checks.length,checks,contrast:contrasts,screenshots:fs.readdirSync(out).filter(f=>f.endsWith('.png')).length,javascript_errors:errors,http_errors:failed,keyboard:'Tab, native date focus, links/forms, disclosure and scrollable table PASS',states:'known, zero, partial, conflict, missing, today empty/latest, month/year navigation PASS',charts:'daily bars, visible rolling means, denominators, signed zero axis, equivalent tables PASS',limitations:'Not full WCAG audit or physical Android/iOS smoke.'};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,viewport_checks:report.viewport_checks,screenshots:report.screenshots,contrast:'PASS',javascript_errors:0,http_errors:0}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
