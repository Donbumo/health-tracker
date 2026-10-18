// Fictional Flask QA only; never authenticates to the personal local app/NAS.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:8025';
const output = path.resolve(__dirname, '../../design/daily-energy-issue-18/qa');
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();
  const errors = [], checks = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(base + '/login');
    await page.locator('[name=username]').fill('QA-energy18');
    await page.locator('[name=password]').fill('fictional-energy18-qa-password');
    await page.locator('input[type=submit],button[type=submit]').click();
    const routes = [
      ['list', '/daily-energy'], ['detail', '/daily-energy/1'],
      ['edit', '/daily-energy/1/edit'], ['conflict', '/daily-energy/3'],
      ['delete', '/daily-energy/1/delete'],
    ];
    for (const theme of ['dark', 'light']) for (const width of [360,390,430,768,1024,1366]) {
      await page.emulateMedia({ colorScheme: theme });
      await page.setViewportSize({ width, height:844 });
      for (const [name, route] of routes) {
        const response = await page.goto(base + route);
        assert.equal(response.status(), 200, route);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${name} ${width}`);
        await page.keyboard.press('Tab');
        const focus = await page.evaluate(() => ({ tag:document.activeElement.tagName, outline:getComputedStyle(document.activeElement).outlineStyle }));
        assert.notEqual(focus.tag, 'BODY');
        assert.notEqual(focus.outline, 'none');
        const screenshot = (width===390 && ['edit','conflict'].includes(name)) || (width===390 && theme==='light' && name==='delete') || (width===1366 && theme==='light' && name==='detail');
        if (screenshot) await page.screenshot({ path:path.join(output,`${name}-${theme}-${width}.png`), fullPage:true });
        checks.push({ name,width,theme,status:'pass',overflow:false,keyboard:'visible focus' });
      }
    }
    await page.goto(base + '/daily-energy/1/edit');
    await page.locator('[name=date]').focus();
    const tabOrder=['total_calories','clear_total_calories','active_calories','clear_active_calories',
      'resting_calories','clear_resting_calories','steps','clear_steps','distance_meters','clear_distance_meters','notes','clear_notes','submit'];
    for (const name of tabOrder) {
      // Native date inputs have internal day/month/year keyboard segments.
      for (let segment=0;segment<6;segment++) {
        await page.keyboard.press('Tab');
        const active=await page.evaluate(()=>document.activeElement.name);
        if (active===name || active!=='date' || name!=='total_calories') break;
      }
      assert.equal(await page.evaluate(()=>document.activeElement.name),name);
      assert.notEqual(await page.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle),'none');
      if (name==='clear_steps') {
        await page.keyboard.press('Space');assert(await page.locator('[name=clear_steps]').isChecked());
        await page.keyboard.press('Space');assert.equal(await page.locator('[name=clear_steps]').isChecked(),false);
      }
    }
    await page.locator('[name=steps]').fill('1300');
    await page.locator('[name=submit]').click();
    assert.equal(new URL(page.url()).pathname, '/daily-energy/1');
    assert((await page.locator('main').innerText()).includes('1300'));
    assert((await page.locator('main').innerText()).includes('2400'));
    await page.goto(base + '/daily-energy/1/delete');
    await page.locator('[name=confirm]').check();
    await page.locator('[name=submit]').click();
    assert.equal(new URL(page.url()).pathname, '/daily-energy');
    assert.equal(await page.getByRole('link',{name:'2040-02-03',exact:true}).count(),0);
    assert.equal(errors.length,0,errors.join('\n'));
    const report = { scope:'Real Flask, fictional QA only',checks:checks.length,cases:checks,keyboard_fields:tabOrder,keyboard_checkbox:'Space toggles clear_steps; no accidental clear',edit:'CSRF form updates steps; expenditure preserved',delete:'explicit confirmation removes only the selected day',browserErrors:errors };
    fs.writeFileSync(path.join(output,'ui-report.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({ checks:checks.length,edit:'pass',delete:'pass',browserErrors:errors.length }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error);process.exit(1); });
