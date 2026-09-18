/* Same confirmed-set POST contract; richer presentation and optional local drafts. */
(() => {
  'use strict';
  const root = document.querySelector('.gym-workout'), view = window.GymView;
  if (!root || !view) return;
  const forms = [...root.querySelectorAll('.gym-set')];
  const cards = [...root.querySelectorAll('.gym-exercise')];
  const valueFields = ['load','reps','rir','rpe'];
  const active = root.dataset.sessionStatus === 'in_progress';
  const fmt = new Intl.NumberFormat('es-MX', {maximumFractionDigits:2});
  let pending = 0, timer, timerEnd = 0;
  function parse(value, fallback = {}) { try { return JSON.parse(value) ?? fallback; } catch (_) { return fallback; } }
  const currentValues = form => Object.fromEntries(valueFields.map(key => [key, form.elements.namedItem(key)?.value ?? '']));
  const draftKey = form => `gym-edit-v1:${new URL(form.action).pathname}`;
  function persist(form) {
    if (!active || form.classList.contains('is-completed')) return true;
    try { localStorage.setItem(draftKey(form), JSON.stringify({at:Date.now(), values:currentValues(form)})); return true; }
    catch (_) { return false; }
  }
  function copy(form, values) {
    valueFields.forEach(key => { const input = form.elements.namedItem(key); if (input && !input.disabled) input.value = values[key] ?? ''; });
  }
  function setText(selector, value, scope = root) { scope.querySelectorAll(selector).forEach(node => { node.textContent = value; }); }
  function data(card) { return {sets:[...card.querySelectorAll('.gym-set')].map(form => ({target:parse(form.dataset.target), actual:parse(form.dataset.actual, null)}))}; }
  function update() {
    const exercises = cards.map(data), summary = view.session(exercises);
    ['completed','finished','remaining'].forEach(key => setText(`[data-kpi="${key}"]`, summary[key]));
    setText('[data-kpi="volume"]', summary.volume === null ? '—' : fmt.format(summary.volume));
    setText('[data-kpi="percentage"]', `${summary.percentage}%`);
    setText('[data-volume-note]', summary.partial ? '· parcial, cargas comparables' : '· solo confirmado');
    root.querySelector('[data-progress-ring]')?.style.setProperty('--progress', summary.percentage);
    root.querySelectorAll('[data-session-progress]').forEach(progress => { progress.value = summary.completed; });
    Object.entries(summary.categories).forEach(([key,count]) => setText(`[data-range-count="${key}"]`, count));
    const dashboard = root.querySelector('#gym-dashboard');
    if (dashboard) {
      setText('[data-dashboard-completed]', summary.completed, dashboard);
      setText('[data-dashboard-volume]', summary.volume === null ? '—' : fmt.format(summary.volume), dashboard);
      setText('[data-dashboard-partial]', summary.partial ? '· parcial' : '', dashboard);
      dashboard.querySelector('[data-dashboard-volume-tile]').hidden = summary.volume === null;
      dashboard.querySelector('[data-dashboard-finished-row]').hidden = summary.completed === 0;
      dashboard.querySelectorAll('[data-dashboard-range-row]').forEach(row => { row.hidden = !summary.categories[row.dataset.dashboardRangeRow]; });
      dashboard.querySelector('[data-dashboard-focus]').hidden = !['below','above','ready'].some(key => summary.categories[key] > 0);
    }
    setText('#workout-status', `${summary.completed} / ${summary.total} series confirmadas · ${active ? 'En curso' : root.dataset.sessionStatus === 'completed' ? 'Finalizado' : 'Incompleto'}`);
    cards.forEach((card, index) => {
      const sets = exercises[index].sets, saved = sets.filter(set => set.actual).length;
      setText('[data-exercise-count]', `${saved} / ${sets.length}`, card);
      card.classList.toggle('is-finished', saved === sets.length && saved > 0);
      const result = view.range(sets), widget = card.querySelector('[data-range-widget]');
      widget.dataset.state = result.state;
      setText('[data-range-label]', result.label, widget);
      setText('[data-range-action]', result.action, widget);
      const bounds = result.target || view.bounds(sets[0]?.target);
      const goal = bounds ? `${bounds.min === bounds.max ? bounds.min : `${bounds.min}–${bounds.max}`}` : '—';
      setText('[data-range-goal]', goal, widget);
      setText('[data-range-actual]', result.reps ?? '—', widget);
      setText('[data-range-count]', `${saved} de ${sets.length} series confirmadas`, widget);
      setText('[data-range-target]', `${goal} reps`, widget);
      const evidence = widget.querySelector('[data-range-evidence]');
      if (evidence) evidence.replaceChildren(...sets.map((set,index) => {
        const item = document.createElement('li'), actual = set.actual, bound = view.bounds(set.target);
        const effort = set.target.rpe !== undefined && set.target.rir === undefined ? 'rpe' : 'rir';
        const effortLabel = effort.toUpperCase();
        const effortValue = view.number(actual?.[effort]);
        const goalEffort = view.number(set.target[effort]);
        item.textContent = actual ? `Serie ${index + 1}: ${actual.load ?? '—'} ${root.dataset.unit} × ${actual.reps ?? '—'} · ${effortLabel} ${effortValue ?? 'sin dato'}${goalEffort !== null ? ` (objetivo ${goalEffort})` : ''}${bound ? ` · rango ${bound.min}–${bound.max}` : ''}` : `Serie ${index + 1}: pendiente de confirmar`;
        return item;
      }));
      const missing = sets.length - saved;
      const missingEffort = sets.some(set => set.actual && (set.target.rir !== undefined && view.number(set.actual.rir) === null || set.target.rpe !== undefined && view.number(set.actual.rpe) === null));
      const noEffortTarget = sets.some(set => set.target.rir === undefined && set.target.rpe === undefined);
      const conclusion = missing ? `Evaluación parcial · faltan ${missing} ${missing === 1 ? 'serie' : 'series'}. Aún no se evalúa progresión.` : missingEffort ? 'Falta registrar esfuerzo. No se puede valorar una progresión.' : noEffortTarget ? 'Sin objetivo de esfuerzo: no se puede valorar una progresión.' : result.ready ? 'Candidato, no una indicación definitiva. La carga no cambia.' : result.count < sets.length ? 'Hay series no comparables. No se puede valorar una progresión.' : 'No se cumplen todos los criterios para una posible subida.';
      setText('[data-range-conclusion]', conclusion, widget);
      const marker = widget.querySelector('.gym-range-marker');
      marker.hidden = result.position === null;
      if (result.position !== null) marker.style.left = `${result.position}%`;
      if (bounds) { const band = widget.querySelector('.gym-range-band'); band.style.left = `${100 * bounds.min / (bounds.max + 2)}%`; band.style.width = `${Math.max(3,100 * (bounds.max - bounds.min) / (bounds.max + 2))}%`; }
    });
    const focus = root.querySelector('[data-exercise-focus]');
    if (focus) {
      const items = exercises.flatMap((exercise,index) => {
        const result = view.range(exercise.sets);
        if (!['below','above','ready'].includes(result.state)) return [];
        const item = document.createElement('li');
        item.textContent = `${cards[index].dataset.exerciseName} · ${result.label}`;
        return [item];
      });
      if (!items.length) { const item = document.createElement('li'); item.textContent = summary.completed ? 'Sin ejercicios fuera del rango o candidatos a progresar entre las series evaluables.' : 'Confirma series para ver qué ejercicios revisar.'; items.push(item); }
      focus.replaceChildren(...items);
    }
    const finish = root.querySelector('#gym-finish-dialog [value=completed]');
    if (finish) finish.disabled = summary.completed === 0 || pending > 0;
  }
  function nextExercise(source) {
    const current = source?.closest('.gym-exercise') || cards.find(card => card.open);
    const after = current ? cards.slice(cards.indexOf(current) + 1) : cards;
    const target = after.find(card => !card.classList.contains('is-finished')) || cards.find(card => !card.classList.contains('is-finished')) || cards.at(-1);
    if (!target) return;
    cards.forEach(card => { card.open = card === target; });
    target.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'start'});
    target.querySelector('summary').focus({preventScroll:true});
  }
  function tickRest() {
    const remaining = Math.max(0, Math.ceil((timerEnd - Date.now()) / 1000));
    setText('#rest-timer', remaining ? `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2,'0')}` : 'Listo para seguir');
    if (!remaining) clearInterval(timer);
  }
  forms.forEach(form => {
    try {
      const draft = parse(localStorage.getItem(draftKey(form)), null);
      if (form.classList.contains('is-completed') || !active || (draft && Date.now() - draft.at > 86400000)) localStorage.removeItem(draftKey(form));
      else if (draft?.values) copy(form, draft.values);
    } catch (_) { /* Confirmed series always recover from the server. */ }
    form.addEventListener('input', () => { const saved = persist(form); setText('[data-save-indicator]', saved ? 'Edición local · aún sin confirmar' : 'Edición sin respaldo local'); });
    form.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button || button.disabled) return;
      if (button.dataset.copy) {
        if (button.dataset.copy === 'repeat') {
          const previous = [...form.closest('.gym-exercise').querySelectorAll('.gym-set')].slice(0,[...form.closest('.gym-exercise').querySelectorAll('.gym-set')].indexOf(form)).reverse().find(item => item.classList.contains('is-completed'));
          if (previous) copy(form, parse(previous.dataset.actual));
          else form.querySelector('.set-status').textContent = 'Confirma la serie anterior para repetirla.';
        } else copy(form, parse(form.dataset[button.dataset.copy]));
      }
      if (button.dataset.adjust) {
        const input = form.elements.namedItem(button.dataset.adjust);
        if (!input || input.disabled) return;
        const value = view.number(input.value) ?? view.number(parse(form.dataset.suggestion)[button.dataset.adjust]);
        if (value === null) { input.focus(); return; }
        input.value = Math.max(Number(input.min || 0), Math.round((value + Number(button.dataset.delta)) * 100) / 100);
      }
      if (button.hasAttribute('data-clear-set')) { copy(form, {}); form.querySelector('.set-status').textContent = 'Campos limpios · sin confirmar'; }
      persist(form);
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
      if (!active || form.dataset.saving === 'true' || form.classList.contains('is-completed') || !form.reportValidity()) return;
      form.dataset.saving = 'true'; pending++;
      const status = form.querySelector('.set-status');
      status.textContent = 'Guardando…'; setText('[data-save-indicator]', 'Guardando serie…'); update();
      const values = Object.fromEntries(new FormData(form)); const csrf = values.csrf_token; delete values.csrf_token;
      persist(form);
      const controls = [...form.querySelectorAll('input[type=number],button')].filter(control => !control.disabled);
      controls.forEach(control => { control.disabled = true; });
      try {
        const response = await fetch(form.action, {method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':csrf}, body:JSON.stringify(values), credentials:'same-origin'});
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.saved) throw new Error(result.error || 'No se guardó. Reabre la sesión si tu acceso expiró.');
        form.classList.add('is-completed'); form.dataset.actual = JSON.stringify({...values,mode:'direct_total'}); status.textContent = '✓ Guardada';
        try { localStorage.removeItem(draftKey(form)); } catch (_) { /* Optional storage. */ }
        form.querySelectorAll('input[type=number],button').forEach(input => { input.disabled = true; });
        form.querySelector('.gym-saved-note').hidden = false;
        setText('[data-save-indicator]', '✓ Serie guardada en tu cuenta');
        if (result.rest_seconds > 0 && !result.duplicate) {
          clearInterval(timer); timerEnd = Date.now() + result.rest_seconds * 1000;
          const rest = root.querySelector('#gym-rest'); rest.hidden = false; rest.classList.remove('is-minimized');
          tickRest(); timer = setInterval(tickRest, 1000);
        }
      } catch (error) { status.textContent = error.message; controls.forEach(control => { control.disabled = false; }); setText('[data-save-indicator]', 'Pendiente de guardar · vuelve a intentar'); }
      finally { form.dataset.saving = 'false'; pending--; update(); }
    });
  });
  cards.forEach(card => {
    const previous = [...card.querySelectorAll('.gym-set')].map(form => parse(form.dataset.previous)).filter(set => view.number(set.load) !== null && view.number(set.reps) !== null);
    const best = previous.sort((a,b) => Number(b.load) - Number(a.load) || Number(b.reps) - Number(a.reps))[0];
    if (best) setText('[data-previous-top]', `Mayor carga de esta referencia: ${best.load} ${root.dataset.unit} × ${best.reps}. No representa un récord global.`, card);
  });
  root.querySelectorAll('[data-next-exercise]').forEach(button => button.addEventListener('click', () => nextExercise()));
  root.querySelector('[data-continue]')?.addEventListener('click', event => {
    event.preventDefault();
    const card = cards.find(item => !item.classList.contains('is-finished')) || cards[0];
    if (!card) return;
    card.open = true;
    const form = card.querySelector('.gym-set:not(.is-completed)');
    form?.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    form?.querySelector('input[type=number]:not(:disabled)')?.focus({preventScroll:true});
  });
  root.querySelector('[data-save-draft]')?.addEventListener('click', () => {
    const saved = forms.map(persist).every(Boolean);
    setText('[data-draft-message]', saved ? 'Edición guardada en este dispositivo. Las series pendientes todavía no cuentan.' : 'No se pudo usar el almacenamiento local. Confirma las series para guardarlas en tu cuenta.');
  });
  root.querySelector('[data-minimize-timer]')?.addEventListener('click', event => {
    const rest = root.querySelector('#gym-rest'), minimized = rest.classList.toggle('is-minimized');
    event.currentTarget.textContent = minimized ? '+' : '−'; event.currentTarget.setAttribute('aria-label', minimized ? 'Expandir descanso' : 'Minimizar descanso');
  });
  root.querySelector('[data-close-timer]')?.addEventListener('click', () => { clearInterval(timer); root.querySelector('#gym-rest').hidden = true; });
  root.querySelectorAll('.gym-finish form').forEach(form => form.addEventListener('submit', event => { if (pending) { event.preventDefault(); setText('#workout-status','Espera a que terminen de guardarse las series.'); } }));
  window.addEventListener('beforeunload', event => { if (pending) { event.preventDefault(); event.returnValue = ''; } });
  const started = root.dataset.startedAt;
  const start = Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(started) ? started : `${started}Z`);
  function elapsed() {
    const seconds = active ? Math.max(0,Math.floor((Date.now() - start) / 1000)) : Number(root.dataset.duration);
    setText('[data-elapsed], [data-dashboard-elapsed]', Number.isFinite(seconds) ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2,'0')}` : '—');
    const timeTile = root.querySelector('[data-dashboard-time-tile]');
    if (timeTile) timeTile.hidden = !Number.isFinite(seconds);
  }
  elapsed(); if (active) setInterval(elapsed, 1000);
  update();
})();
