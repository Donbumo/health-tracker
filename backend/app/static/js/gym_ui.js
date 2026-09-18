/* Neutral media and day navigation. No business writes and no third-party requests by default. */
(() => {
  'use strict';
  const view = window.GymView;
  if (!view) return;
  let entries = [];
  function entryFor(element) {
    try { return view.resolveMedia(JSON.parse(element.dataset.mediaBinding || '{}'), entries); }
    catch (_) { return null; }
  }
  let opener;
  function openDialog(dialog, source) {
    if (!dialog || typeof dialog.showModal !== 'function') return;
    opener = source; dialog.showModal();
  }
  document.querySelectorAll('[data-open-dialog]').forEach(button => button.addEventListener('click', () => openDialog(document.getElementById(button.dataset.openDialog), button)));
  document.querySelectorAll('.gym-dialog').forEach(dialog => {
    dialog.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => dialog.close()));
    dialog.addEventListener('click', event => { if (event.target === dialog) { const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); } });
    dialog.addEventListener('close', () => { dialog.querySelectorAll('video').forEach(video => video.pause()); opener?.focus(); });
  });
  document.querySelectorAll('[data-program]').forEach(program => {
    const links = [...program.querySelectorAll('[data-day-link]')], panels = [...program.querySelectorAll('[data-day-panel]')];
    function choose(id) {
      if (!panels.some(panel => panel.id === id)) return;
      panels.forEach(panel => { panel.hidden = panel.id !== id; });
      links.forEach(link => { const active = link.hash === `#${id}`; link.classList.toggle('is-selected', active); if (active) link.setAttribute('aria-current', 'true'); else link.removeAttribute('aria-current'); });
    }
    links.forEach(link => link.addEventListener('click', event => { event.preventDefault(); choose(link.hash.slice(1)); history.replaceState(null, '', link.hash); }));
    const hash = location.hash.slice(1);
    choose(panels.some(panel => panel.id === hash) ? hash : panels[0]?.id);
    window.addEventListener('hashchange', () => choose(location.hash.slice(1)));
  });
  if (location.hash === '#import') document.getElementById('import')?.setAttribute('open', '');
  function text(tag, value, className) { const node = document.createElement(tag); node.textContent = value; if (className) node.className = className; return node; }
  function loadImage(wrapper, url) {
    const image = wrapper.querySelector('img');
    image.hidden = false;
    wrapper.dataset.mediaState = 'loading';
    wrapper.classList.add('is-loading');
    image.addEventListener('load', () => { wrapper.classList.remove('is-loading'); wrapper.classList.add('has-media'); wrapper.dataset.mediaState = 'loaded'; image.hidden = false; }, {once:true});
    image.addEventListener('error', () => { wrapper.classList.remove('is-loading','has-media'); wrapper.dataset.mediaState = 'asset_error'; image.hidden = true; }, {once:true});
    image.src = url;
    if (image.complete && image.naturalWidth) { wrapper.classList.remove('is-loading'); wrapper.classList.add('has-media'); wrapper.dataset.mediaState = 'loaded'; image.hidden = false; }
  }
  function decorate() {
    document.querySelectorAll('[data-exercise-name]').forEach(card => {
      const entry = entryFor(card);
      if (!entry) return;
      card.dataset.mediaSource = entry.source;
      card.dataset.externalExerciseId = entry.external_exercise_id;
      const meta = card.querySelector('[data-exercise-meta]');
      if (meta) meta.textContent = [...entry.primary_muscles, ...entry.equipment].slice(0, 3).join(' · ') || 'Referencia del catálogo';
      const tags = card.querySelector('[data-exercise-tags]');
      if (tags) tags.replaceChildren(...entry.tags.slice(0, 2).map(tag => text('span', tag, 'gym-tag')));
    });
    document.querySelectorAll('[data-media-name]').forEach(wrapper => {
      const entry = entryFor(wrapper);
      const media = view.safeMedia(entry?.thumbnail_url, location.origin);
      if (media && !media.external) loadImage(wrapper, media.url);
    });
    document.querySelectorAll('[data-day-panel]').forEach(panel => {
      const cards = [...panel.querySelectorAll('[data-exercise-name]')];
      const found = cards.map(card => entryFor(card));
      const muscles = new Set(found.flatMap(entry => entry?.primary_muscles || []));
      const label = panel.querySelector('[data-day-muscles]');
      if (label) { label.textContent = muscles.size ? `${muscles.size}${found.some(entry => !entry) ? '+' : ''}` : '—'; label.title = [...muscles].join(', ') || 'Sin metadatos disponibles'; }
    });
  }
  const dialog = document.getElementById('gym-media-dialog');
  document.querySelectorAll('[data-open-media]').forEach(button => button.addEventListener('click', () => {
    if (!dialog) return;
    const name = button.dataset.openMedia, entry = entryFor(button);
    dialog.querySelector('#gym-media-title').textContent = name;
    const content = dialog.querySelector('#gym-media-content'); content.replaceChildren(); content.classList.remove('is-loading'); content.setAttribute('aria-busy', 'false');
    const caption = dialog.querySelector('#gym-media-caption');
    const credit = dialog.querySelector('#gym-media-credit'); credit.replaceChildren();
    if (entry?.author) {
      credit.append(text('span', `${entry.author} · `));
      for (const [label,url] of [[entry.license,entry.license_url],['Fuente original',entry.source_url]]) {
        const safe = view.safeMedia(url,location.origin);
        if (safe) { const link = text('a',label); link.href = safe.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; credit.append(link,document.createTextNode(' · ')); }
      }
      credit.append(text('span',entry.changes));
    }
    const tags = dialog.querySelector('#gym-media-tags');
    tags.replaceChildren(...[...(entry?.primary_muscles || []), ...(entry?.equipment || []), entry?.difficulty].filter(Boolean).map(value => text('span', value, 'gym-tag')));
    const instructions = dialog.querySelector('#gym-media-instructions');
    instructions.replaceChildren(...(entry?.instructions || []).map(value => text('li', value)));
    const media = view.safeMedia(entry?.media_url || entry?.thumbnail_url, location.origin);
    function show() {
      if (!media) { content.replaceChildren(text('p', 'No hay una imagen verificada para esta variante. Tu entrenamiento sigue disponible.', 'gym-media-unavailable')); return; }
      const element = document.createElement(entry?.media_type === 'video' && media ? 'video' : 'img');
      content.classList.add('is-loading'); content.setAttribute('aria-busy', 'true');
      function loaded() { content.classList.remove('is-loading'); content.setAttribute('aria-busy', 'false'); }
      element.addEventListener('load', loaded, {once:true});
      element.addEventListener('loadedmetadata', loaded, {once:true});
      if (element.tagName === 'VIDEO') { element.controls = true; element.preload = 'metadata'; element.playsInline = true; }
      else { element.alt = entry ? `Ilustración de referencia: ${name}` : 'Ilustración general de entrenamiento'; element.decoding = 'async'; }
      element.referrerPolicy = 'no-referrer';
      element.addEventListener('error', () => { loaded(); content.replaceChildren(text('p', 'El medio no está disponible. Puedes continuar tu entrenamiento.', 'gym-media-unavailable')); }, {once:true});
      element.src = media.url; content.replaceChildren(element);
    }
    if (media?.external) {
      caption.textContent = 'Este medio se carga desde un sitio externo solo si lo solicitas.';
      const load = text('button', 'Cargar medio externo', 'button'); load.type = 'button'; load.addEventListener('click', show, {once:true}); content.append(load);
    } else { show(); caption.textContent = entry ? 'Referencia visual estática · confirma la variante y el equipo de tu programa.' : 'Aún sin medio asociado. Tu ejercicio y tus series siguen disponibles.'; }
    openDialog(dialog, button);
  }));
  const catalogURL = document.querySelector('script[data-gym-catalog]')?.dataset.gymCatalog;
  if (catalogURL) fetch(catalogURL, {credentials:'same-origin'}).then(response => response.ok ? response.json() : null).then(data => {
    if (!Array.isArray(data?.entries)) return;
    entries = data.entries.slice(0, 500).map(view.catalogEntry).filter(Boolean);
    decorate();
  }).catch(() => { /* The default visual is sufficient when the catalog is unavailable. */ });
})();
