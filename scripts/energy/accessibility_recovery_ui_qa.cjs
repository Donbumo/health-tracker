/* Real HTTP recovery UI after an unusable signature. No audible results inferred. */
const {chromium}=require('playwright'),axe=require('axe-core'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const base=process.env.ENERGY_QA_URL;if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Explicit loopback QA URL required');
const root=path.resolve('design/energy-experience-2-0-d/assisted');fs.mkdirSync(path.join(root,'screenshots'),{recursive:true});
const report={scope:'fictional Flask QA only; no native Windows input',method:'Real HTTP invalid-signature 409; deterministic expired-signature coverage separately in Flask focal tests',audible:'NOT TESTED',nativeZoom:'NOT TESTED',cases:[]};
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true});try{
 for(const theme of ['light','dark'])for(const width of [390,1366]){
  const ctx=await b.newContext({viewport:{width,height:900},colorScheme:theme});const login=await ctx.request.get(base+'/login');const csrf=(await login.text()).match(/name="csrf_token"[^>]*value="([^"]+)"/)[1];await ctx.request.post(base+'/login',{form:{username:'QA-energy-D',password:'fictional-energy-D-password',csrf_token:csrf}});
  const p=await ctx.newPage();await p.goto(base+'/energy?date=2040-02-03');assert(await p.locator('body').textContent().then(t=>t.includes('QA ficticia D')));
  await p.goto(base+'/energy/review?date=2040-02-03');await p.locator('#eg-choice-total_calories').selectOption('manual');await p.locator('#eg-value-total_calories').fill('2460');await p.locator('#eg-choice-notes').selectOption('manual');await p.locator('#eg-value-notes').fill('<QA preserved draft>');
  await p.locator('button[name=action][value=review]').click();await p.locator('button[name=action][value=approve]').click();await p.locator('[name=review_token]').evaluate(e=>e.value='QA-invalid-signature');await p.locator('[name=confirm]').check();
  const [response]=await Promise.all([p.waitForResponse(r=>new URL(r.url()).origin===base&&new URL(r.url()).pathname==='/energy/review'&&r.request().method()==='POST'),p.locator('button[name=action][value=confirm]').click()]);assert.equal(response.status(),409);
  assert.equal(await p.locator('#eg-value-total_calories').inputValue(),'2460');assert.equal(await p.locator('#eg-value-notes').inputValue(),'<QA preserved draft>');assert.equal(await p.locator('[name=review_token]').count(),0);
  assert(await p.locator('[role=alert]').evaluate(e=>e===document.activeElement));assert((await p.content()).includes('&lt;QA preserved draft&gt;'));
  await p.addScriptTag({content:axe.source});const a=await p.evaluate(()=>axe.run({runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}}));assert.equal(a.violations.length,0,a.violations.map(x=>x.id).join(','));
  const size=await p.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(size.scroll<=size.width+1);
  const screenshot=`draft-409-${width}-${theme}.png`;await p.screenshot({path:path.join(root,'screenshots',screenshot),fullPage:true});
  await p.getByRole('link',{name:'Revisar la propuesta conservada'}).press('Enter');assert.equal(await p.evaluate(()=>document.activeElement.id),'eg-review-draft');
  await p.locator('button[name=action][value=review]').click();assert((await p.title()).includes('Paso 3'));assert.equal(await p.locator('[name=review_token]').count(),1);
  await p.locator('.eg-actions .button-secondary').click();await p.goto(base+'/energy?date=2040-02-03');assert.equal((await p.locator('#ee-expended').innerText()).replace(/\s+/g,' ').trim(),'2450 kcal');
  report.cases.push({theme,width,http:409,draftRetained:true,escaped:true,noAutomaticToken:true,errorFocused:true,errorLinkFocusesDraft:true,explicitFreshReview:true,cancelPreservesCanonical:true,overflow:false,axeViolations:[],axeIncomplete:a.incomplete.map(x=>x.id),screenshot});await ctx.close();
 }
 report.status='PASS';
}finally{await b.close();fs.writeFileSync(path.join(root,'recovery-ui.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,cases:report.cases.length,audible:report.audible,nativeZoom:report.nativeZoom}));}})().catch(e=>{console.error(e.stack);process.exit(1)});
