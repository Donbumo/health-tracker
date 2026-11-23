const copyButton = document.querySelector("#ni-copy-prompt");
if (copyButton) {
    copyButton.hidden = false;
    copyButton.addEventListener("click", async () => {
        const prompt = document.querySelector("#ni-exchange-prompt");
        const status = document.querySelector("#ni-copy-status");
        try {
            await navigator.clipboard.writeText(prompt.value);
            status.textContent = "Prompt copiado.";
        } catch {
            prompt.closest("details").open = true;
            prompt.focus();
            prompt.select();
            status.textContent = "Seleccionaste el prompt. Usa la opción Copiar de tu dispositivo.";
        }
    });
}
