/* Progressive enhancement: every confirmed set also supports a normal POST. */
(() => {
  'use strict';
  let timer;
  let pending = 0;
  const valueFields = ['load', 'reps', 'rir', 'rpe'];
  const forms = [...document.querySelectorAll('.gym-set')];
  function draftKey(form) { return `gym-edit-v1:${new URL(form.action).pathname}`; }
  function persistEditing(form) {
    if (form.classList.contains('is-completed')) return;
    const values = Object.fromEntries(valueFields.map(key => [key, form.elements.namedItem(key)?.value ?? '']));
    try { localStorage.setItem(draftKey(form), JSON.stringify({at:Date.now(), values})); } catch (_) { /* Storage is optional; confirmed sets live on the server. */ }
  }
  function copy(form, values) {
    valueFields.forEach(key => {
      const input = form.elements.namedItem(key);
      if (input && !input.disabled) input.value = values[key] ?? '';
    });
  }
  forms.forEach(form => {
    try {
      const key = draftKey(form);
      const draft = JSON.parse(localStorage.getItem(key) || 'null');
      if (form.classList.contains('is-completed') || (draft && Date.now() - draft.at > 86400000)) localStorage.removeItem(key);
      else if (draft?.values) copy(form, draft.values);
    } catch (_) { /* Disabled storage must not block logging. */ }
    form.addEventListener('input', () => persistEditing(form));
    form.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button || button.disabled) return;
      if (button.dataset.copy) {
        const mode = button.dataset.copy;
        if (mode === 'repeat') {
          const exerciseForms = [...form.closest('.gym-exercise').querySelectorAll('.gym-set')];
          const previous = exerciseForms.slice(0, exerciseForms.indexOf(form)).reverse().find(item => item.classList.contains('is-completed'));
          if (previous) copy(form, Object.fromEntries(valueFields.map(key => [key, previous.elements.namedItem(key)?.value])));
          else form.querySelector('.set-status').textContent = 'Completa una serie anterior para repetirla.';
        } else copy(form, JSON.parse(form.dataset[mode] || '{}'));
      }
      if (button.dataset.adjust) {
        const input = form.elements.namedItem(button.dataset.adjust);
        if (!input || input.disabled) return;
        const fallback = JSON.parse(form.dataset.suggestion || '{}')[button.dataset.adjust];
        const base = input.value === '' ? fallback : input.value;
        if (base === null || base === undefined || base === '') { input.focus(); return; }
        input.value = Math.max(Number(input.min || 0), Math.round((Number(base) + Number(button.dataset.delta)) * 100) / 100);
      }
      persistEditing(form);
    });
    form.addEventListener('keydown', event => {
      if (event.key !== 'Enter' || !event.target.matches('input[type=number]')) return;
      event.preventDefault();
      const inputs = [...form.querySelectorAll('input[type=number]:not(:disabled)')];
      const next = inputs[inputs.indexOf(event.target) + 1];
      if (next) next.focus(); else form.requestSubmit();
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (form.dataset.saving === 'true' || form.classList.contains('is-completed')) return;
      if (!form.reportValidity()) return;
      form.dataset.saving = 'true'; pending += 1;
      const status = form.querySelector('.set-status');
      const submit = form.querySelector('button[type=submit]');
      submit.disabled = true; status.textContent = 'Guardando…';
      const data = Object.fromEntries(new FormData(form));
      const csrf = data.csrf_token; delete data.csrf_token;
      persistEditing(form);
      try {
        const response = await fetch(form.action, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(data), credentials: 'same-origin'});
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || 'No se guardó. Reabre esta sesión si tu acceso expiró.');
        form.classList.add('is-completed'); status.textContent = '✓ Guardada';
        try { localStorage.removeItem(draftKey(form)); } catch (_) { /* Optional storage. */ }
        form.querySelectorAll('input[type=number], button').forEach(input => { input.disabled = true; });
        const count = forms.filter(item => item.classList.contains('is-completed')).length;
        document.getElementById('workout-status').textContent = `${count} / ${forms.length} series confirmadas · En curso`;
        if (result.rest_seconds > 0 && !result.duplicate) {
          clearInterval(timer);
          const end = Date.now() + result.rest_seconds * 1000;
          const tick = () => {
            const remaining = Math.max(0, Math.ceil((end - Date.now()) / 1000));
            document.getElementById('rest-timer').textContent = remaining ? `Descanso: ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}` : 'Descanso terminado';
            if (!remaining) clearInterval(timer);
          };
          tick(); timer = setInterval(tick, 1000);
        }
      } catch (error) { status.textContent = error.message; submit.disabled = false; }
      finally { form.dataset.saving = 'false'; pending -= 1; }
    });
  });
  document.querySelector('.gym-finish form')?.addEventListener('submit', event => {
    if (pending) { event.preventDefault(); document.getElementById('workout-status').textContent = 'Espera a que terminen de guardarse las series.'; }
  });
  window.addEventListener('beforeunload', event => { if (pending) { event.preventDefault(); event.returnValue = ''; } });
})();
