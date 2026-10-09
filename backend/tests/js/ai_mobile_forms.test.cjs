"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const css = fs.readFileSync(path.join(__dirname, "../../app/static/css/app.css"), "utf8");

test("AI editable controls cover absent/text/number/date/time types within draft scope", () => {
  const selector = '.ai-draft input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([type="submit"]):not([type="button"]):not([type="reset"])';
  const block = css.slice(css.indexOf(selector)).split("}")[0];
  assert.ok(css.includes(selector));
  assert.ok(block.includes(".ai-draft select,"));
  assert.ok(block.includes(".ai-draft textarea {"));
  for (const declaration of ["box-sizing: border-box", "width: 100%", "min-height: 44px", "font-size: 16px", "font: inherit", "background: var(--surface)", "color: var(--text)"]) {
    assert.ok(block.includes(declaration), declaration);
  }
  // This exclusion selector also matches input:not([type]) and type="time";
  // it cannot accidentally size hidden inputs, checkbox/radio or submit controls.
  for (const excluded of ["hidden", "checkbox", "radio", "submit", "button", "reset"]) {
    assert.ok(selector.includes(`:not([type="${excluded}"])`));
  }
});

test("vertical draft layout, larger textareas, touch labels and visible focus remain", () => {
  assert.match(css, /\.ai-draft form, \.ai-draft fieldset, \.ai-draft form > label, \.ai-draft fieldset label \{ display: grid;/);
  assert.ok(css.includes(".ai-draft textarea { min-height: 7rem; }"));
  assert.match(css, /\.checkbox \{[^}]*min-height: 44px/);
  assert.match(css, /input:focus-visible[^}]*outline: 3px solid var\(--focus\)/);
});

test("stylesheet version changes the cache-first PWA request key", () => {
  const base = fs.readFileSync(path.join(__dirname, "../../app/templates/base.html"), "utf8");
  assert.ok(base.includes("filename='css/app.css', v='ai-operator-mobile-1'"));
  assert.ok(!base.includes("ai-operator-2-0-1"));
});
