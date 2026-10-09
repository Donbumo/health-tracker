/* Local synthetic integration QA: browser-decoded images and owner bindings. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
(async()=>{
 const output=fs.mkdtempSync(path.join(os.tmpdir(),'gym-media-evidence-'));
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},colorScheme:'dark',serviceWorkers:'block'});
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 const base='http://127.0.0.1:8012';
 await page.goto(base+'/login');await page.locator('[name=username]').fill('gym-qa');await page.locator('[name=password]').fill('fictional-gym-qa-password');await page.locator('[type=submit]').first().click();await page.waitForURL(u=>!u.pathname.includes('login'));
 await page.goto(base+'/training-plans');
 const program=page.locator('[data-program]').filter({has:page.getByRole('heading',{name:'QA · Identidades y medios',exact:true})});
 const firstDay=program.locator('[data-day-panel]').first(),cards=firstDay.locator('[data-exercise-name]');
 for(let i=0;i<3;i++){await cards.nth(i).locator('img').scrollIntoViewIfNeeded();await cards.nth(i).locator('.has-media').waitFor();assert.ok(await cards.nth(i).locator('img').evaluate(e=>e.naturalWidth>0));}
 assert.equal(await cards.nth(3).locator('.has-media').count(),0);assert.equal(await cards.nth(4).locator('.has-media').count(),0);
 const bindings=await cards.evaluateAll(es=>es.map(e=>JSON.parse(e.dataset.mediaBinding)));
 assert.equal(bindings[0].media_asset_id,'everkinetic:bench-press');assert.equal(bindings[3].status,'ambiguous');assert.equal(bindings[4].status,'no_media');
 await firstDay.locator('.gym-upcoming-media .has-media').waitFor();
 for(let i=0;i<3;i++){await cards.nth(i).locator('[data-open-media]').click();const image=page.locator('#gym-media-content img');await image.waitFor();await image.evaluate(e=>e.decode());assert.ok(await image.evaluate(e=>e.naturalWidth>0));assert.match(await page.locator('#gym-media-credit').innerText(),/CC BY-SA 3.0/);await page.getByRole('button',{name:'Cerrar medio',exact:true}).click();}
 const measures=[];
 for(const theme of ['dark','light'])for(const width of [360,390,430,768,1024,1366]){await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:844});await page.evaluate(()=>scrollTo(0,0));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);measures.push({width,theme});if(theme==='dark'&&[390,1366].includes(width))await page.screenshot({path:path.join(output,`home-${width}.png`),fullPage:true});}
 await page.emulateMedia({colorScheme:'dark'});await page.setViewportSize({width:390,height:844});
 await program.locator('[data-day-link]').nth(1).click();assert.equal(await program.locator('[data-day-panel]').nth(1).locator('.gym-upcoming-media').isVisible(),false);
 await program.locator('[data-day-link]').first().click();await program.getByRole('button',{name:'Iniciar entrenamiento D1',exact:true}).click();await page.waitForURL(/gym\/sessions\//);
 const workouts=page.locator('[data-exercise-name]');
 assert.deepEqual(await workouts.evaluateAll(es=>es.map(e=>JSON.parse(e.dataset.mediaBinding))),bindings);
 for(let i=0;i<3;i++){await workouts.nth(i).locator('img').scrollIntoViewIfNeeded();await workouts.nth(i).locator('.has-media').waitFor();}
 for(const width of [390,1366]){await page.setViewportSize({width,height:844});await page.evaluate(()=>scrollTo(0,0));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(output,`session-${width}.png`),fullPage:true});}
 assert.deepEqual(errors,[]);
 // A decoded-image failure must remove the image visually without assigning another asset.
 await page.route('**/static/images/gym/bench-press.png',route=>route.fulfill({status:200,contentType:'image/png',body:'invalid-image-fixture'}));await page.reload();
 await page.locator('[data-exercise-name]').first().locator('img').waitFor({state:'hidden'});
 assert.equal(await page.locator('[data-exercise-name]').first().locator('.has-media').count(),0);
 await page.locator('[data-exercise-name]').first().locator('[data-open-media]').click();await page.getByText('El medio no está disponible. Puedes continuar tu entrenamiento.',{exact:true}).waitFor();
 fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({status:'passed',fictionalData:true,measures,covered:3,uncovered:2,unknownPreviewTest:'backend tests',sameIdentity:true,decodedImages:true,errors},null,2));
 console.log(JSON.stringify({status:'passed',output,responsive:measures.length}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
