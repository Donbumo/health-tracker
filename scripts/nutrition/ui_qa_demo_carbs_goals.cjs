/* Fictitious QA only. Requires the loopback server from qa_demo_carbs_goals.py. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const origin = process.env.QA_ORIGIN || 'http://127.0.0.1:5197';
  assert.equal(new URL(origin).hostname, '127.0.0.1');
  const output = process.env.QA_OUTPUT;
  assert(output, 'Set QA_OUTPUT to an artifact directory outside production storage');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const page = await browser.newPage();
  const failures = [];
  page.on('pageerror', e => failures.push(e.message));
  await page.goto(`${origin}/login`);
  await page.locator('[name="username"]').fill('demo@healthtracker.test');
  await page.locator('[name="password"]').fill('Fictitious-acceptance-QA-password-only');
  await Promise.all([page.waitForURL(url => !url.pathname.includes('login')), page.locator('input[type="submit"][name="submit"]').click()]);
  const results = [];
  for (const width of [360, 390, 430, 768, 1024, 1366]) {
    for (const theme of ['light', 'dark']) {
      await page.setViewportSize({width, height: 1000});
      await page.emulateMedia({colorScheme: theme});
      await page.goto(`${origin}/dashboard?from=2026-11-12&to=2026-11-18`);
      const metrics = page.locator('.macro-row');
      assert.equal(await metrics.count(), 6);
      const total = metrics.filter({hasText: 'Carbohidratos totales'});
      assert.match(await total.innerText(), /266[.,]1 g/);
      assert.match(await total.innerText(), /7\/7 días con datos · 7 con objetivo/);
      assert.equal(await total.locator('progress').count(), 1);
      const net = metrics.filter({hasText: 'Carbohidratos netos'});
      assert.match(await net.innerText(), /Sin datos/);
      assert.match(await net.innerText(), /0\/7 días con datos · 0 con objetivo/);
      assert.equal(await net.locator('progress').count(), 0);
      const geometry = await page.evaluate(() => ({
        width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        clipped: [...document.querySelectorAll('.macro-row strong, .macro-row > div, .goal-list li')]
          .filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.className || e.tagName),
      }));
      assert(geometry.scrollWidth <= width, JSON.stringify(geometry));
      assert.deepEqual(geometry.clipped, []);
      await total.scrollIntoViewIfNeeded();
      await page.screenshot({path: path.join(output, `dashboard-${width}-${theme}.png`), fullPage: true});
      await page.evaluate(() => window.scrollTo(0, 0));
      for (const section of ['nutrition', 'goals']) {
        const clip = await page.locator(`section[aria-labelledby="${section}-title"]`).boundingBox();
        await page.screenshot({path: path.join(output, `${section}-${width}-${theme}.png`), clip, fullPage: true});
      }
      const goalCount = await page.locator('.goal-list li').count();
      await page.goto(`${origin}/daily-nutrition`);
      const detail = await page.locator('td a[href^="/daily-nutrition/"]').first().getAttribute('href');
      for (const route of ['/daily-nutrition', detail, '/daily-balance?date=2026-11-18']) {
        const response = await page.goto(`${origin}${route}`);
        assert.equal(response.status(), 200);
        assert.match(await page.locator('main').innerText(), /Carbohidratos totales/);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      }
      results.push({width, theme, ...geometry, metrics: 6, goals: goalCount, legacyViews: 3});
    }
  }
  assert.deepEqual(failures, []);
  fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify({passed: results.length, output, pageErrors: failures}));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
