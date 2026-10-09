(() => {
  'use strict';
  const panel = document.getElementById('draft-save-panel');
  if (!panel) return;
  const status = document.getElementById('draft-save-status');
  const error = document.getElementById('draft-save-error');
  const retry = document.getElementById('draft-save-retry');
  const reload = document.getElementById('draft-save-reload');
  let revision = Number(panel.dataset.revision), ready = panel.dataset.ready === 'true';
  let pending = null, timer = null, busy = false, failed = false;
  const controls = () => [...document.querySelectorAll('#gym-mapping select, #gym-mapping button, #gym-editor input:not([type=hidden]), #gym-editor select, #gym-editor button, #gym-confirm button')];
  function lock(value) {
    controls().forEach(node => { node.disabled = value; });
    const confirm = document.querySelector('#gym-confirm button');
    if (confirm) confirm.disabled = value || !ready;
  }
  async function send() {
    clearTimeout(timer); timer = null;
    if (!pending || busy) return;
    busy = true; failed = false; lock(true); retry.hidden = true;
    status.textContent = 'Guardando…'; error.textContent = '';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(panel.dataset.url, {method:'POST', credentials:'same-origin', signal:controller.signal, headers:{'Content-Type':'application/json','X-CSRFToken':panel.dataset.csrf}, body:JSON.stringify({revision,change:pending})});
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        if ([401,403,409].includes(response.status)) reload.hidden = false;
        throw new Error(body.error || 'No se pudo guardar. Reintenta antes de continuar; tus últimas selecciones siguen en esta página.');
      }
      if (response.redirected || !Number.isInteger(body.revision) || typeof body.ready !== 'boolean' || typeof body.saved_at !== 'string' || typeof body.token !== 'string') {
        reload.hidden = false;
        throw new Error('No se confirmó el guardado. Reabre el borrador y verifica tu sesión antes de continuar.');
      }
      revision = body.revision; ready = body.ready; pending = null;
      document.querySelectorAll('input[name=revision]').forEach(node => { node.value = revision; });
      const token = document.querySelector('#gym-confirm input[name=token]');
      if (token) token.value = body.token;
      status.textContent = `Guardado · Último guardado: ${new Date(body.saved_at.endsWith('Z') || /[+-]\d\d:\d\d$/.test(body.saved_at) ? body.saved_at : body.saved_at+'Z').toLocaleTimeString()}`;
      error.textContent = body.error || '';
      const unresolved = document.getElementById('draft-unresolved');
      if (unresolved) unresolved.textContent = body.unresolved_count ? `${body.unresolved_count} ejercicios necesitan mapping.` : 'Las identidades están resueltas.';
      const guidance = document.getElementById('draft-confirm-guidance');
      if (guidance) guidance.textContent = ready ? 'Las selecciones están guardadas. Puedes confirmar el programa.' : 'Completa los ejercicios y objetivos pendientes para confirmar.';
    } catch (reason) {
      failed = true; status.textContent = 'Cambios sin guardar';
      error.textContent = reason.name === 'AbortError' ? 'El guardado tardó demasiado. Reintenta antes de continuar.' : reason instanceof TypeError ? 'No se pudo conectar para guardar. Reintenta antes de continuar.' : reason.message;
      retry.hidden = !reload.hidden;
      error.scrollIntoView({block:'center'});
    } finally { clearTimeout(timeout); busy = false; lock(failed); }
  }
  window.gymDraftSave = (change, debounce = false) => {
    if (busy || failed) return;
    pending = change;
    const confirm = document.querySelector('#gym-confirm button');
    if (confirm) confirm.disabled = true;
    status.textContent = 'Cambios pendientes de guardar…';
    clearTimeout(timer);
    if (debounce) timer = setTimeout(send, 400); else send();
  };
  retry.addEventListener('click', send);
  // This link explicitly discards only the rejected local attempt and reopens
  // the persisted revision. Do not trap it behind the unsaved-change warning.
  reload.addEventListener('click', () => { pending = null; failed = false; });
  window.addEventListener('beforeunload', event => { if (pending || busy || failed) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('click', event => {
    if ((busy || failed || pending) && event.target.closest('a') && !event.target.closest('#draft-save-reload')) { event.preventDefault(); error.textContent = 'Espera a que el borrador esté guardado antes de salir.'; }
  });
  document.querySelectorAll('.gym form').forEach(form => form.addEventListener('submit', event => {
    if (busy || failed || pending) { event.preventDefault(); if (!busy && !failed) send(); }
  }));
})();
