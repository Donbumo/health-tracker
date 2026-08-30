(() => {
  "use strict";

  const form = document.querySelector(".ai-message-form");
  if (form) {
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
  }

  document.querySelectorAll("[data-ai-followup]").forEach((link) => {
    link.addEventListener("click", (event) => {
      const prompt = link.querySelector("[data-ai-followup-prompt]");
      const textarea = form && form.querySelector("textarea[name='content']");
      if (!prompt || !textarea || textarea.disabled) return;
      event.preventDefault();
      textarea.value = prompt.textContent.trim();
      textarea.focus();
      textarea.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
})();
