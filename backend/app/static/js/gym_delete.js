"use strict";
const deletionDialog = document.querySelector(".gym-delete-dialog");
if (deletionDialog && typeof deletionDialog.showModal === "function") {
  deletionDialog.removeAttribute("open");
  deletionDialog.showModal();
  document.getElementById("delete-title").focus();
  deletionDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    window.location.assign(deletionDialog.querySelector("[data-delete-cancel]").href);
  });
}
const partialAction = document.getElementById("partial-action");
const partialConfirmation = document.getElementById("partial-confirmation");
if (partialAction && partialConfirmation) {
  const updateConfirmation = () => {
    const discard = partialAction.value === "discard";
    partialConfirmation.required = discard;
    if (discard) partialConfirmation.pattern = "DESCARTAR";
    else partialConfirmation.removeAttribute("pattern");
  };
  partialAction.addEventListener("change", updateConfirmation);
  updateConfirmation();
}
