/* Fictional loopback QA only. Never point this script at a real user account. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

(async () => {
  const base = process.argv[2] || 'http://127.0.0.1:8017';
  assert.match(base, /^http:\/\/127\.0\.0\.1:80[0-9]{2}$/);
  const output = process.argv[3] || fs.mkdtempSync(path.join(os.tmpdir(), 'ht-coach-qa-'));
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto(base + '/login');
  await page.locator('[name=username]').fill('strength-qa');
  await page.locator('[name=password]').fill('fictional-strength-qa-password');
  await page.locator('button[type=submit],input[type=submit]').first().click();
  await page.waitForURL(url => !url.pathname.includes('/login'));

  const metrics = [];
  for (const theme of ['light', 'dark']) {
    await page.emulateMedia({ colorScheme: theme });
    for (const width of [360, 390, 430, 768, 1024, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      for (const [name, url] of [['coach', '/ai'], ['today', '/today'], ['dashboard', '/dashboard']]) {
        const response = await page.goto(base + url);
        assert.equal(response.status(), 200, `${name} ${theme} ${width}`);
        const result = await page.evaluate(() => {
          const root = document.documentElement;
          const controls = [...document.querySelectorAll('.coach-actions .button,.coach-evidence summary,.coach-preview .button,.coach-review a')]
            .filter(el => el.checkVisibility());
          return { width: innerWidth, scroll: root.scrollWidth,
            smallControls: controls.filter(el => el.getBoundingClientRect().height < 44).map(el => el.textContent.trim()) };
        });
        assert.ok(result.scroll <= width + 1, `${name} overflow ${theme} ${width}: ${JSON.stringify(result)}`);
        assert.deepEqual(result.smallControls, [], `${name} small targets ${theme} ${width}`);
        if (name === 'coach') {
          assert.equal(await page.getByRole('heading', { name: 'Qué cambió y qué revisar' }).count(), 1);
          assert.ok(await page.locator('.coach-signal').count() >= 2);
          await page.locator('.coach-evidence summary').first().click();
          assert.ok(await page.locator('.coach-evidence').first().getAttribute('open') !== null);
        }
        if ([390, 1366].includes(width) && theme === 'light') {
          await page.screenshot({ path: path.join(output, `${name}-${width}.png`), fullPage: true });
        }
        metrics.push({ name, theme, ...result });
      }
    }
  }
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'metrics.json'), JSON.stringify({ metrics, errors }, null, 2));
  await browser.close();
  process.stdout.write(JSON.stringify({ output, pages: metrics.length, errors: errors.length }) + '\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
