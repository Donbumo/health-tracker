const test = require("node:test");
const assert = require("node:assert/strict");

const {
  ENERGY_SERIES_KEYS,
  calculateBarLayout,
  energyFocusState,
  filterBalanceValue,
  toggleEnergySeries,
} = require("../../app/static/js/dashboard_charts.js");

const approximatelyEqual = (left, right, epsilon = 1e-9) =>
  Math.abs(left - right) <= epsilon;

test("visible bars share one centered band and a uniform width", () => {
  const layout = calculateBarLayout(36, 3);

  assert.equal(layout.length, 3);
  assert.ok(layout.every((bar) => approximatelyEqual(bar.width, layout[0].width)));
  assert.ok(approximatelyEqual(layout[0].offset + layout.at(-1).offset + layout.at(-1).width, 0));
  assert.ok(layout.at(-1).offset + layout.at(-1).width - layout[0].offset <= 36);
});

test("remaining bars recenter when visible series change", () => {
  const oneBar = calculateBarLayout(40, 1);
  const twoBars = calculateBarLayout(40, 2);

  assert.ok(approximatelyEqual(oneBar[0].offset, -oneBar[0].width / 2));
  assert.ok(approximatelyEqual(twoBars[0].offset + twoBars[1].offset + twoBars[1].width, 0));
  assert.ok(twoBars[0].offset < 0);
  assert.ok(twoBars[1].offset > 0);
});

test("dense 90-day slots keep every bar inside its daily band", () => {
  const slotWidth = 236 / 90;
  const layout = calculateBarLayout(slotWidth, 3);
  const groupWidth = layout.at(-1).offset + layout.at(-1).width - layout[0].offset;

  assert.ok(groupWidth <= slotWidth);
  assert.ok(layout.every((bar) => bar.width > 0));
});

test("quick focuses select the expected series and balance sign", () => {
  assert.deepEqual(energyFocusState("all"), {
    visibleKeys: ENERGY_SERIES_KEYS,
    balanceSign: "all",
  });
  assert.deepEqual(energyFocusState("bars").visibleKeys, ["consumed", "expended", "balance"]);
  assert.deepEqual(energyFocusState("lines").visibleKeys, ["consumed_rolling_7d", "expended_rolling_7d"]);
  assert.deepEqual(energyFocusState("balance"), { visibleKeys: ["balance"], balanceSign: "all" });
  assert.deepEqual(energyFocusState("deficit"), { visibleKeys: ["balance"], balanceSign: "deficit" });
  assert.deepEqual(energyFocusState("surplus"), { visibleKeys: ["balance"], balanceSign: "surplus" });
});

test("deficit and surplus focuses exclude the opposite sign and zero", () => {
  assert.equal(filterBalanceValue(-250, "deficit"), -250);
  assert.equal(filterBalanceValue(250, "deficit"), null);
  assert.equal(filterBalanceValue(0, "deficit"), null);
  assert.equal(filterBalanceValue(250, "surplus"), 250);
  assert.equal(filterBalanceValue(-250, "surplus"), null);
  assert.equal(filterBalanceValue(0, "surplus"), null);
});

test("manual toggles preserve canonical ordering and allow any combination", () => {
  let visible = toggleEnergySeries(ENERGY_SERIES_KEYS, "expended");
  visible = toggleEnergySeries(visible, "consumed_rolling_7d");

  assert.deepEqual(visible, ["consumed", "balance", "expended_rolling_7d"]);
  assert.deepEqual(toggleEnergySeries(visible, "expended"), [
    "consumed",
    "expended",
    "balance",
    "expended_rolling_7d",
  ]);
});
