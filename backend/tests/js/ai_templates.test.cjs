"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const {
  choosePeriod,
  matchesCapability,
  matchesTemplate,
  normalizeText,
  updateStructuredPeriod,
} = require("../../app/static/js/ai_templates.js");

test("template search is accent-insensitive and respects category", () => {
  assert.equal(normalizeText("Energía y Nutrición"), "energia y nutricion");
  assert.equal(matchesTemplate("Tendencia de energía", "energy", "energia", "energy"), true);
  assert.equal(matchesTemplate("Tendencia de energía", "energy", "peso", "energy"), false);
  assert.equal(matchesTemplate("Tendencia de energía", "energy", "energia", "body"), false);
  assert.equal(matchesTemplate("Tendencia de energía", "energy", "", "all"), true);
});

test("period selector uses requested period only when the template allows it", () => {
  assert.equal(choosePeriod("7d,30d,90d", "30d", "7d"), "7d");
  assert.equal(choosePeriod("today", "today", "90d"), "today");
  assert.equal(choosePeriod("30d,90d", "30d", "today"), "30d");
});

test("adaptive capabilities filter by domain and keep structured query fields", () => {
  assert.equal(matchesCapability("training", "training", "progress", "progress"), true);
  assert.equal(matchesCapability("training", "nutrition", "progress", "progress"), false);
  assert.equal(matchesCapability("training", "training", "summary", "progress"), false);
  assert.equal(
    updateStructuredPeriod(
      "/ai?intent=progress&domain=training&metric=volume&period=30d",
      { origin: "http://localhost" },
      "90d",
    ),
    "/ai?intent=progress&domain=training&metric=volume&period=90d",
  );
});
