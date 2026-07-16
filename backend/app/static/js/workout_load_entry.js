(() => {
  "use strict";
  const LB_TO_KG = 0.45359237;
  const componentsByMode = {
    direct_total: ["direct_total"], per_side: ["per_side"],
    bar_plus_per_side: ["bar", "per_side"],
    machine_initial_total: ["initial_total", "added_total"],
    machine_initial_per_side: ["initial_per_side", "external_per_side"],
    machine_external_per_side_initial_total: ["initial_total", "external_per_side"],
    selector_stack: ["selector_stack"], dumbbell_each: ["dumbbell_each"],
    bodyweight: ["bodyweight"], bodyweight_plus: ["bodyweight", "added_total"],
    assistance: ["bodyweight", "assistance"],
    duration_distance: ["duration_seconds", "distance_meters"],
  };

  function component(editor, name, defaultUnit) {
    const input = editor.querySelector(`[data-load-component="${name}"]`);
    const raw = input.value.trim();
    if (raw === "") return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) return null;
    const fixedUnit = name === "duration_seconds" ? "s" : name === "distance_meters" ? "m" : null;
    const unitSelect = editor.querySelector(`[data-load-component-unit="${name}"]`);
    return { value, unit: fixedUnit || (unitSelect ? unitSelect.value : defaultUnit) };
  }

  function kilograms(item) {
    return item.unit === "lb" ? item.value * LB_TO_KG : item.value;
  }

  function update(editor) {
    const mode = editor.querySelector("[data-load-mode]").value;
    const unit = editor.querySelector("[data-load-unit]").value;
    const expected = componentsByMode[mode] || [];
    editor.querySelectorAll("[data-component-field]").forEach((field) => {
      field.hidden = !expected.includes(field.dataset.componentField);
    });
    const values = Object.fromEntries(expected.map((name) => [name, component(editor, name, unit)]));
    const ready = expected.every((name) => values[name] !== null);
    let totalKg = null;
    if (ready) {
      const kg = Object.fromEntries(expected.map((name) => [name, kilograms(values[name])]));
      if (mode === "direct_total") totalKg = kg.direct_total;
      else if (mode === "per_side") totalKg = kg.per_side * 2;
      else if (mode === "bar_plus_per_side") totalKg = kg.bar + kg.per_side * 2;
      else if (mode === "machine_initial_total") totalKg = kg.initial_total + kg.added_total;
      else if (mode === "machine_initial_per_side") totalKg = (kg.initial_per_side + kg.external_per_side) * 2;
      else if (mode === "machine_external_per_side_initial_total") totalKg = kg.initial_total + kg.external_per_side * 2;
      else if (mode === "selector_stack") totalKg = kg.selector_stack;
      else if (mode === "dumbbell_each") totalKg = kg.dumbbell_each * 2;
      else if (mode === "bodyweight") totalKg = kg.bodyweight;
      else if (mode === "bodyweight_plus") totalKg = kg.bodyweight + kg.added_total;
      else if (mode === "assistance") totalKg = Math.max(kg.bodyweight - kg.assistance, 0);
      else totalKg = 0;
    }
    const output = editor.querySelector(".load-total");
    const hidden = editor.querySelector("[data-normalized-weight]");
    if (totalKg === null) {
      output.textContent = "Completa los componentes";
      hidden.value = "";
      return;
    }
    const lb = totalKg / LB_TO_KG;
    hidden.value = totalKg.toFixed(2);
    output.textContent = `Total: ${totalKg.toFixed(2)} kg / ${lb.toFixed(2)} lb`;
    if (mode === "assistance") output.textContent += " (asistencia restada)";
  }

  document.querySelectorAll(".workout-load-editor").forEach((editor) => {
    editor.addEventListener("input", () => update(editor));
    editor.addEventListener("change", () => update(editor));
    editor.querySelectorAll("[data-load-adjust]").forEach((button) => {
      button.addEventListener("click", () => {
        const mode = editor.querySelector("[data-load-mode]").value;
        const name = (componentsByMode[mode] || [])[0];
        const input = name && editor.querySelector(`[data-load-component="${name}"]`);
        if (!input) return;
        input.value = Math.max(0, (Number(input.value) || 0) + Number(button.dataset.loadAdjust));
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    });
    update(editor);
  });

  document.querySelectorAll(".copy-load-sets").forEach((button) => {
    button.addEventListener("click", () => {
      const editors = Array.from(document.querySelectorAll(`.workout-load-editor[data-exercise-index="${button.dataset.exerciseIndex}"]`));
      if (editors.length < 2) return;
      const source = editors[0];
      editors.slice(1).forEach((target) => {
        target.querySelector("[data-load-mode]").value = source.querySelector("[data-load-mode]").value;
        target.querySelector("[data-load-unit]").value = source.querySelector("[data-load-unit]").value;
        source.querySelectorAll("[data-load-component]").forEach((input) => {
          target.querySelector(`[data-load-component="${input.dataset.loadComponent}"]`).value = input.value;
        });
        source.querySelectorAll("[data-load-component-unit]").forEach((select) => {
          target.querySelector(`[data-load-component-unit="${select.dataset.loadComponentUnit}"]`).value = select.value;
        });
        update(target);
      });
      source.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });

  const preference = document.getElementById("preferred-load-unit");
  if (preference) preference.addEventListener("change", () => {
    document.querySelectorAll("[data-load-unit]").forEach((select) => {
      select.value = preference.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    document.querySelectorAll("[data-load-component-unit]").forEach((select) => {
      const componentName = select.dataset.loadComponentUnit;
      const input = select.closest("[data-component-field]").querySelector(`[data-load-component="${componentName}"]`);
      if (input.value.trim() === "") select.value = preference.value;
    });
  });
})();
