(() => {
  "use strict";
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {
      // Installation is optional; web flows remain fully usable without it.
    });
  });
})();
