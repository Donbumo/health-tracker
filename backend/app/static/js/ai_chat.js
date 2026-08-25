(() => {
  "use strict";

  const form = document.querySelector(".ai-message-form");
  if (!form) return;
  form.addEventListener("submit", () => {
    const button = form.querySelector("[data-ai-submit]");
    const loading = form.querySelector("[data-ai-loading]");
    form.setAttribute("aria-busy", "true");
    if (button) {
      button.disabled = true;
      button.textContent = "Enviando…";
    }
    if (loading) loading.hidden = false;
  });
})();
