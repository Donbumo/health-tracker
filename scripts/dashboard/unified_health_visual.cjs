/* Real Flask, QA-only: no production URLs, domain writes, native zoom or axe. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = process.argv[2];
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
const out = path.resolve('design/unified-health-summary/flask-qa');
fs.mkdirSync(out, {recursive:true});
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  const checks = [], errors = [], posts = [];
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if(r.method() === 'POST') posts.push(new URL(r.url()).pathname); });
    await page.goto(base+'/login');
    await page.locator('[name=username]').fill('QA-unified-health');
    await page.locator('[name=password]').fill('fictional-unified-QA-password');
    await Promise.all([page.waitForURL(u => u.pathname !== '/login'), page.locator('[type=submit]').click()]);
    for (const theme of ['dark','light']) {
      await page.emulateMedia({colorScheme:theme});
      for (const width of [360,390,430,768,1024,1366]) {
        await page.setViewportSize({width,height:900});
        const response = await page.goto(base+'/dashboard?as_of=2040-02-05&period=7');
        assert.equal(response.status(),200);
        await page.locator('[data-dashboard-chart=energy] svg').waitFor();
        assert.equal(await page.locator('[data-dashboard-chart=balance] svg').count(),1);
        const layout = await page.evaluate(() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          cards:[...document.querySelectorAll('.health-card')].map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width}})}));
        assert.ok(layout.scroll <= width+1, JSON.stringify(layout));
        if(width <= 600) {
          assert.equal(layout.cards[0].y,layout.cards[1].y);
          assert.ok(layout.cards[2].y > layout.cards[0].y);
          assert.ok(layout.cards[2].width > layout.cards[0].width*1.9);
        }
        const values = await page.locator('.health-value').allTextContents();
        assert.match(values[0], /2,280/); assert.match(values[1], /2,660/); assert.match(values[2], /-380/);
        if([390,1366].includes(width)) {
          await page.screenshot({path:path.join(out,`${width}-${theme}.png`),fullPage:true});
          if(width===390) await page.screenshot({path:path.join(out,`390-${theme}-viewport.png`)});
        }
        checks.push({width,theme,status:200,overflow:false,mobileCardLayout:width<=600?'2+1':'desktop',values:values.map(v=>v.trim())});
      }
    }
    await page.setViewportSize({width:390,height:900});
    for(const [label,date] of [['partial','2040-02-01'],['conflict','2040-02-04'],['empty','2041-01-01'],['zero','2040-02-06']]) {
      await page.goto(base+`/dashboard?as_of=${date}&period=7`);
      await page.locator('.health-card').first().waitFor();
      const text = await page.locator('.health-cards').innerText();
      if(label==='partial') assert.match(text,/Subtotal conocido · parcial/);
      if(label==='conflict') assert.match(text,/Conflicto pendiente/);
      if(label==='empty') assert.match(text,/Sin dato/);
      if(label==='zero') assert.match(text,/Cero conocido/);
      checks.push({scenario:label,date,text});
      await page.screenshot({path:path.join(out,`390-light-${label}.png`),fullPage:true});
    }
    for(const period of [7,30,90]) {
      await page.goto(base+`/dashboard?as_of=2040-02-05&period=${period}`);
      await page.locator('[data-dashboard-chart=energy] svg').waitFor();
      const rows=await page.locator('#dashboard-chart-data').textContent().then(JSON.parse);
      assert.equal(rows.trends.energy.length,period);
      await page.locator('.chart-table').first().locator('summary').click();
      assert.equal(await page.locator('.unified-health tbody tr').count(),period);
      const table=await page.locator('.unified-health .table-wrap').evaluate(n=>({scroll:n.scrollWidth,width:n.clientWidth}));
      assert.ok(table.scroll>table.width);
      checks.push({period,tableRows:period,internalTableScroll:true});
    }
    await page.locator('#health-date').fill('2040-02-06');
    await page.locator('.health-date-form button').click();
    await page.waitForURL(/as_of=2040-02-06/);
    assert.match(await page.locator('.health-cards').innerText(),/Cero conocido/);
    for(const [label,href] of [['Nutrición','/nutrition/'],['Energía','/energy'],['Fuentes y decisiones','/energy/sources']]) {
      const link=page.locator('.health-links a',{hasText:label});
      const address=await link.getAttribute('href');assert.ok(address.startsWith(href));
      assert.equal((await context.request.get(base+address)).status(),200);
    }
    // Basic keyboard use: native form, period links, detail links and table wrapper.
    await page.locator('#health-date').focus();
    for(let step=0;step<5 && !(await page.locator('.health-date-form button').evaluate(n=>n===document.activeElement));step++) await page.keyboard.press('Tab');
    assert.equal(await page.locator('.health-date-form button').evaluate(n=>n===document.activeElement),true);
    assert.deepEqual(errors,[]); assert.deepEqual(posts,['/login']);
    fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({scope:'real Flask; synthetic SQLite QA only',browser:browser.version(),checks,errors,posts},null,2)+'\n');
    console.log(JSON.stringify({checks:checks.length,errors,posts,out}));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
