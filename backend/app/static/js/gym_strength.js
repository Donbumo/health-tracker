(function (root) {
  'use strict';

  function bind(doc) {
    var output = doc.querySelector('[data-chart-tooltip]');
    if (!output) return;

    doc.querySelectorAll('[data-chart-point]').forEach(function (button) {
      function showPoint() {
        output.textContent = button.dataset.chartPoint;
      }
      button.addEventListener('focus', showPoint);
      button.addEventListener('click', showPoint);
    });
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { bind: bind };
  if (root.document) bind(root.document);
})(typeof window !== 'undefined' ? window : globalThis);
