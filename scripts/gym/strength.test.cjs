const { test } = require('node:test');
const assert = require('node:assert/strict');
const { bind } = require('../../backend/app/static/js/gym_strength.js');

test('chart exposes the selected point to keyboard and pointer without interpreting HTML', () => {
  const output = { textContent: '', set innerHTML(_) { throw new Error('Unsafe HTML'); } };
  const listeners = {};
  const button = {
    dataset: { chartPoint: '04/10/2026 · 80 kg · <b>fictional QA</b>' },
    addEventListener: (name, handler) => { listeners[name] = handler; }
  };
  bind({ querySelector: () => output, querySelectorAll: () => [button] });
  listeners.focus();
  assert.equal(output.textContent, button.dataset.chartPoint);
  button.dataset.chartPoint = '05/10/2026 · 82.5 kg · direct_total';
  listeners.click();
  assert.equal(output.textContent, button.dataset.chartPoint);
});

test('empty chart needs no tooltip or interactive points', () => {
  bind({ querySelector: () => null, querySelectorAll: () => { throw new Error('No chart'); } });
});
