/* Presentation-only calculations. Never writes a prescription or a performance. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GymView = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const number = value => value === null || value === undefined || (typeof value === 'string' && !value.trim()) || typeof value === 'boolean'
    ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  function bounds(target = {}) {
    const exact = number(target.reps);
    const min = exact ?? number(target.reps_min), max = exact ?? number(target.reps_max);
    return min !== null && max !== null && min > 0 && max >= min ? {min, max} : null;
  }
  function range(sets) {
    const confirmed = sets.filter(set => set.actual);
    const comparable = confirmed.filter(set => bounds(set.target) && number(set.actual.reps) !== null &&
      (!set.actual.mode || set.actual.mode === 'direct_total'));
    if (!comparable.length) return {state:'empty', label:confirmed.length ? 'Sin rango comparable' : 'Por registrar', action:confirmed.length ? 'Esta modalidad no tiene un rango de reps comparable aquí.' : 'Confirma una serie para ver tu rango.', count:0, position:null, ready:false};
    const latest = comparable.at(-1), target = bounds(latest.target), reps = number(latest.actual.reps);
    const below = comparable.some(set => number(set.actual.reps) < bounds(set.target).min);
    const above = comparable.some(set => number(set.actual.reps) > bounds(set.target).max);
    const atTop = comparable.every(set => number(set.actual.reps) >= bounds(set.target).max);
    const effortMet = set => {
      const rir = number(set.target.rir), rpe = number(set.target.rpe);
      if (rir === null && rpe === null) return false;
      return (rir === null || (number(set.actual.rir) !== null && number(set.actual.rir) >= rir)) &&
        (rpe === null || (number(set.actual.rpe) !== null && number(set.actual.rpe) <= rpe));
    };
    const ready = comparable.length === sets.length && atTop && comparable.every(set => number(set.actual.load) > 0 && effortMet(set));
    const state = below ? 'below' : ready ? 'ready' : above ? 'above' : atTop ? 'top' : 'within';
    const labels = {below:'Debajo del rango', ready:'Candidato a progresar', above:'Por encima', top:'Tope del rango', within:'Dentro del rango'};
    const actions = {below:'Revisa carga, técnica y fatiga antes de ajustar.', ready:'Revisa una posible subida. No se modifica tu rutina.', above:'Superaste las reps objetivo. Revisa el esfuerzo antes de subir.', top:'Las series evaluadas alcanzan el tope del objetivo.', within:'Las series evaluadas están dentro del objetivo.'};
    return {state, label:labels[state], action:actions[state], count:comparable.length, reps, target,
      position:Math.max(0, Math.min(100, 100 * reps / (target.max + 2))), ready};
  }
  function session(exercises) {
    let completed = 0, total = 0, finished = 0, volume = 0, partial = false, hasVolume = false;
    const categories = {within:0, ready:0, below:0, above:0, pending:0};
    exercises.forEach(exercise => {
      total += exercise.sets.length;
      const saved = exercise.sets.filter(set => set.actual);
      completed += saved.length;
      if (exercise.sets.length && saved.length === exercise.sets.length) finished++;
      saved.forEach(set => {
        const load = number(set.actual.load), reps = number(set.actual.reps);
        if (load === null || reps === null || (set.actual.mode && set.actual.mode !== 'direct_total')) partial = true;
        else { volume += load * reps; hasVolume = true; }
      });
      const result = range(exercise.sets);
      if (result.ready) categories.ready++;
      else if (result.state === 'below') categories.below++;
      else if (result.state === 'above') categories.above++;
      else if (['within','top'].includes(result.state)) categories.within++;
      else categories.pending++;
    });
    return {completed, total, finished, remaining:exercises.length - finished, volume:hasVolume ? volume : null,
      partial, percentage:total ? Math.round(completed / total * 100) : 0, categories};
  }
  function safeMedia(value, origin) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value, origin);
      if (url.username || url.password || url.hash) return null;
      if (url.origin === origin && url.pathname.startsWith('/static/')) return {url:url.href, external:false};
      if (url.protocol === 'https:' && url.origin !== origin) return {url:url.href, external:true};
    } catch (_) { /* Invalid URLs use the local fallback. */ }
    return null;
  }
  function catalogEntry(raw) {
    if (!raw || typeof raw !== 'object' || typeof raw.name !== 'string') return null;
    const text = value => typeof value === 'string' ? value.slice(0, 500) : '';
    const list = value => Array.isArray(value) ? value.filter(item => typeof item === 'string').slice(0, 12).map(text) : [];
    return {source:text(raw.source), author:text(raw.author), source_url:text(raw.source_url), license:text(raw.license), license_url:text(raw.license_url), changes:text(raw.changes), external_exercise_id:text(raw.external_exercise_id), name:text(raw.name),
      aliases:list(raw.aliases), primary_muscles:list(raw.primary_muscles), secondary_muscles:list(raw.secondary_muscles),
      equipment:list(raw.equipment), instructions:list(raw.instructions), media_url:text(raw.media_url),
      thumbnail_url:text(raw.thumbnail_url), tags:list(raw.tags), difficulty:text(raw.difficulty),
      force:text(raw.force), mechanic:text(raw.mechanic), media_type:['image','video'].includes(raw.media_type) ? raw.media_type : 'image'};
  }
  const nameKey = name => String(name).normalize('NFKC').trim().toLocaleLowerCase('es').replace(/\s+/g,' ');
  return {number, bounds, range, session, safeMedia, catalogEntry, nameKey};
});
