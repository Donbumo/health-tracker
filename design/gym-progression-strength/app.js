/* Presentation-only prototype. No fetch, storage, analytics, APIs or domain calculations. */
(function () {
  'use strict';
  const F = window.GymDesignFixtures;
  const main = document.querySelector('main');
  const modal = document.querySelector('#modal');
  let scenario = 'positive';
  let day = 0;
  let period = '8';
  let returnFocus = null;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const arrow = '<span class="arrow" aria-hidden="true">↗</span>';
  const fixture = '<span class="fixture-label">Ejemplo de diseño</span>';
  const noHistory = () => ['no-history', 'new-program', 'review'].includes(scenario);
  const insufficient = () => noHistory() || scenario === 'insufficient';
  const page = () => location.hash.startsWith('#progress') ? 'progress' : location.hash === '#summary' ? 'summary' : 'home';
  function exercise() {
    let key = location.hash.split('/')[1] || 'bench';
    if (!['bench', 'row'].includes(key)) key = 'bench';
    if (scenario === 'maintain') key = 'row';
    let ex = {...F.exercises[key]};
    if (scenario === 'below') ex = {...F.exercises.bench, ...F.exercises.curl, detailImage:null, sessions: 6, volume:'500', bestSet:'25 kg × 10', estimate:null, proposed:'8', unit:'reps', reason:'Un objetivo visual para la próxima sesión: sumar una repetición con la misma carga. No se ha evaluado una regla.', evidence:['Última sesión: 25 kg × 7 / 7 / 6','Rango de la rutina: 8–10 reps · RIR objetivo 2'], instruction:'Variante del catálogo: curl de pie con barra.'};
    if (scenario === 'top-range') ex = {...ex,sets:[8,8,8],volume:'1,920',evidence:['Última sesión: 80 kg × 8 / 8 / 8','Rango: 6–8 reps · RIR objetivo 2','Fixture al tope del rango; no activa una regla']};
    if (scenario === 'review') ex = {...ex,name:'Press de mi rutina',externalId:null,canonicalName:null,image:null,detailImage:null,state:'review'};
    if (['insufficient','no-history','new-program'].includes(scenario)) ex.state = 'insufficient_data';
    return ex;
  }
  function badge(state, label) {
    const value = F.proposals[state] || F.proposals.insufficient_data;
    return `<span class="badge ${value.tone}"><i aria-hidden="true">${value.icon}</i>${esc(label || value.label)}</span>`;
  }
  function image(ex, large = false) {
    if (!ex.image || scenario === 'no-image' || scenario === 'review') return large ? '<div class="hero-photo no-media"><span aria-hidden="true">↔</span>Sin imagen disponible</div>' : '<span class="thumb fallback-thumb" role="img" aria-label="Sin imagen disponible">↔</span>';
    const img = `<img class="${large ? '' : 'thumb'}" src="${esc(ex.image)}" alt="${esc(ex.canonicalName)} · referencia del catálogo" width="${large ? '300' : '56'}" height="${large ? '183' : '56'}">`;
    return large ? `<div class="hero-photo">${img}</div>` : img;
  }
  function credit() { return '<p class="media-credit">Imágenes: <a href="https://github.com/yuhonas/free-exercise-db" target="_blank" rel="noreferrer">Free Exercise DB</a> · <a href="assets/LICENSE.md" target="_blank">Unlicense</a> · Copia del catálogo local.</p>'; }
  function empty(title, text, action='') { return `<div class="empty"><span class="empty-icon" aria-hidden="true">◷</span><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`; }
  const coach = '<aside class="coach-note"><span aria-hidden="true">✧</span><div><strong>Coach AI</strong><small>Próximamente</small><p>Podrá explicar tus tendencias usando estas mismas progresiones.</p></div></aside>';
  function row(ex, target = '') { return `<${target ? 'a' : 'div'} ${target ? `href="${target}"` : ''} class="exercise-row">${image(ex)}<div class="exercise-copy"><strong>${esc(ex.name)}</strong><span>${noHistory() ? 'Aún sin sesión anterior' : `${ex.load} kg × ${ex.reps} <span class="sr-only">repeticiones</span> · anterior`}</span></div>${target ? arrow : ''}</${target ? 'a' : 'div'}>`; }
  function home() {
    const d = F.program.days[day];
    return `<section class="page-heading"><div><p class="eyebrow">Cada sesión cuenta</p><h1>Mi entrenamiento</h1><p class="subtitle">Tu progreso, tu próxima sesión y lo que está cambiando.</p></div><div class="hero-actions"><button class="button" data-action="start">Iniciar ${d.id} →</button><button class="button ghost" data-action="program">Ver programa</button></div></section>
    <section class="week" aria-labelledby="week-title"><div class="section-head"><h2 id="week-title">Esta semana <span class="muted">/ 28 sep – 4 oct</span></h2>${fixture}</div><div class="panel weekly-stats">
      <div class="stat"><strong>${scenario === 'new-program' ? '0' : '3'} <small>/ 5</small></strong><span>Sesiones completadas</span>${scenario === 'new-program' ? '' : '<div class="mini-track" aria-hidden="true"><i></i></div>'}</div>
      <div class="stat"><strong>${scenario === 'new-program' ? '—' : '47'}</strong><span>Series realizadas</span></div><div class="stat"><strong>${scenario === 'new-program' ? '—' : '18.4'} <small>t</small></strong><span>Volumen comparable</span></div><div class="stat accent"><strong>${scenario === 'new-program' ? '—' : '+6.4'}<small>${scenario === 'new-program' ? '' : '%'}</small></strong><span>${scenario === 'new-program' ? 'Aún sin comparación' : 'Volumen vs semana anterior'}</span></div></div></section>
    <div class="home-grid"><div class="stack"><section class="panel session-panel" aria-labelledby="next-session-title"><div class="program-name"><span>Hipertrofia <span class="muted">· 5 días</span></span><span class="active-dot">PROGRAMA ACTIVO</span></div><div class="day-picker" role="group" aria-label="Día del programa">${F.program.days.map((v,i)=>`<button data-day="${i}" aria-pressed="${day===i}" aria-label="${v.id}, ${v.name}">${v.id}</button>`).join('')}</div><div class="session-heading"><div><p class="tiny-label">${day === 0 ? 'Tu próxima sesión' : 'Vista del programa'}</p><h2 id="next-session-title">${d.name}</h2></div><span class="day-monogram" aria-hidden="true">${d.id}</span></div><div class="session-facts"><span><strong>${d.exercises}</strong> ejercicios</span><span><strong>${d.sets}</strong> series</span><span><strong>~${d.minutes}</strong> min · estimados QA</span></div><div class="preview-list">${d.preview.map(key=>row(F.exercises[key],key==='bench'?'#progress':key==='row'?'#progress/row':'')).join('')}</div><div class="session-footer"><span class="micro muted">${scenario==='new-program'?'Tu primera sesión empieza aquí':`Última vez · ${d.previous}`}</span><button class="text-button" data-action="program">Ver programa</button></div><button class="button full" data-action="start">Iniciar ${d.id} <span aria-hidden="true">→</span></button>${credit()}</section>
    <section aria-labelledby="highlights-title"><div class="section-head"><h2 id="highlights-title">Progresando</h2><a class="text-button" href="#progress">Ver progreso ${arrow}</a></div>${noHistory() ? empty('Tu progreso empieza aquí','Completa una sesión para ver tus primeras referencias.') : `<div class="progress-list">${['bench','row'].map(key=>{const ex=F.exercises[key];return `<article class="panel exercise-tile"><div class="tile-top">${image(ex)}<span class="arrow muted" aria-hidden="true">${key==='bench'?'↗':'＝'}</span></div>${badge(ex.state)}<h3>${ex.name}</h3><p class="set-value">${ex.load} <small>kg ×</small> ${ex.reps}</p><p class="change">${ex.change}</p><a href="#progress${key==='row'?'/row':''}" class="text-button" aria-label="Ver progreso de ${ex.name}">Ver progreso ${arrow}</a></article>`;}).join('')}</div><div class="state-strip"><div><strong class="cyan-text">＋</strong> Buscando más reps <b>1</b></div><div><strong>!</strong> Por revisar <b>1</b></div></div>`}</section></div>
    <div class="stack"><section class="panel panel-pad strength-panel"><div class="section-head"><h2>Fuerza</h2><span class="fixture-label">Estimación · QA</span></div>${noHistory()?empty('Aún sin referencia','Tu primer entrenamiento dará inicio al historial.'):`<p class="micro muted">Press banca <span aria-hidden="true">/</span> e1RM</p><div class="strength-value">101 <small>kg</small></div><p class="micro cyan-text">+4.3% <span class="muted">en 8 semanas · fixture</span></p><svg class="spark" viewBox="0 0 280 64" role="img" aria-label="Tendencia ilustrativa de fuerza estimada; no es una medición"><path d="M0 60H280" stroke="var(--line)"/><path d="M2 48L30 48L54 43L78 43L102 35L127 35L151 26L177 26L202 20L228 20L253 10L278 10" stroke="currentColor" stroke-width="2.5" fill="none"/><circle cx="278" cy="10" r="4" fill="currentColor"/></svg><div class="strength-meta"><span class="micro muted">Top set reciente</span><strong class="micro">80 kg × 8</strong></div><a href="#progress" class="text-button">Explorar evolución ${arrow}</a><p class="micro muted">Estimación ilustrativa. No se calcula en esta fase.</p>`}</section>
    <section class="panel panel-pad"><div class="section-head"><h2>Consistencia</h2>${fixture}</div>${scenario==='new-program'?empty('Una sesión a la vez','Empieza tu programa; aquí verás tu constancia.'):`<div class="consistency-count"><strong>3</strong><span>sesiones esta semana</span></div><div class="week-bars" role="img" aria-label="Últimas cuatro semanas: 3, 2, 4 y 3 sesiones"><div class="week-bar"><div class="bar-value height-3">3</div><span>7 sep</span></div><div class="week-bar"><div class="bar-value height-2">2</div><span>14 sep</span></div><div class="week-bar"><div class="bar-value height-4">4</div><span>21 sep</span></div><div class="week-bar"><div class="bar-value height-3 current">3</div><span>Esta semana</span></div></div><p class="micro muted"><strong>12 sesiones</strong> en las últimas 4 semanas.</p>`}</section>${coach}</div></div>`;
  }
  function points(ex) {
    if (noHistory()) return [];
    if (scenario==='insufficient') return [{date:'2026-09-29',best_load_kg:'80'}];
    if (scenario==='below') return [{date:'2026-09-07',best_load_kg:'25'},{date:'2026-09-14',best_load_kg:'25'},{date:'2026-09-21',best_load_kg:'25'},{date:'2026-09-29',best_load_kg:'25'}];
    if (ex.externalId===F.exercises.row.externalId) return [{date:'2026-08-10',best_load_kg:'67.5'},{date:'2026-08-24',best_load_kg:'70'},{date:'2026-09-07',best_load_kg:'70'},{date:'2026-09-21',best_load_kg:'70'},{date:'2026-09-29',best_load_kg:'70'}];
    return F.points.filter(p=>p.date >= ({'8':'2026-08-04','3':'2026-07-03','6':'2026-04-03'}[period]));
  }
  const shortDate = iso => new Date(iso+'T12:00:00Z').toLocaleDateString('es-MX',{day:'numeric',month:'short',timeZone:'UTC'}).replace('.','');
  function chart(ex) {
    const rows = points(ex);
    if(rows.length < 2) return empty(rows.length ? 'Una sesión es el comienzo' : 'Todavía no hay historial','Necesitamos al menos 2 sesiones para mostrar evolución. No hay una tendencia disponible.');
    // Only chart projection of existing best_load_kg; not a strength/progression calculation.
    const values=rows.map(p=>Number(p.best_load_kg));
    const low=Math.floor((Math.min(...values)-5)/5)*5, high=Math.ceil((Math.max(...values)+5)/5)*5;
    const start=Date.parse(rows[0].date), end=Date.parse(rows[rows.length-1].date);
    const coords=rows.map((p)=>[52+((Date.parse(p.date)-start)/(end-start))*520,190-(Number(p.best_load_kg)-low)/(high-low)*160]);
    const line=coords.map(v=>v.join(',')).join(' ');
    return `<svg class="chart" viewBox="0 0 600 240" role="img" aria-labelledby="chart-title chart-desc"><title id="chart-title">Carga máxima por sesión, en kilogramos</title><desc id="chart-desc">Datos ficticios. ${rows.map(r=>`${shortDate(r.date)}: ${r.best_load_kg} kg`).join('; ')}. También disponibles debajo como texto.</desc><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--lime)" stop-opacity=".16"/><stop offset="100%" stop-color="var(--lime)" stop-opacity="0"/></linearGradient></defs>${[low,(low+high)/2,high].map(v=>{const y=190-(v-low)/(high-low)*160;return `<line class="grid-line" x1="48" y1="${y}" x2="581" y2="${y}"/><text x="0" y="${y+4}">${v}</text>`;}).join('')}<polygon points="52,190 ${line} 572,190" fill="url(#chart-fill)"/><polyline class="line" points="${line}"/>${coords.map((v,i)=>`<circle class="point" cx="${v[0]}" cy="${v[1]}" r="${i===coords.length-1?'5':'3'}"><title>${shortDate(rows[i].date)} · ${rows[i].best_load_kg} kg</title></circle>`).join('')}<text x="52" y="226">${shortDate(rows[0].date)}</text><text x="312" y="226" text-anchor="middle">${shortDate(rows[Math.floor(rows.length/2)].date)}</text><text x="572" y="226" text-anchor="end">${shortDate(rows[rows.length-1].date)}</text></svg><p class="chart-caption">Carga máxima de cada sesión · kg · datos ficticios</p><details class="data-details"><summary>Ver datos de la gráfica</summary><div class="data-list">${rows.map(p=>`<div><span>${shortDate(p.date)}</span><strong>${p.best_load_kg} kg</strong></div>`).join('')}</div></details>`;
  }
  function proposal(ex) {
    if(scenario==='review')return `<section class="panel panel-pad"><div class="section-head"><h2>Revisar ejercicio</h2>${badge('review')}</div>${empty('Vincula la variante correcta','El nombre de tu rutina se conserva. No mezclaremos historiales sin una identidad confirmada.','<button class="button secondary" data-action="mapping">Vincular ejercicio</button>')}</section>`;
    if(insufficient() || scenario==='no-proposals') return `<section class="panel panel-pad"><div class="section-head"><h2>Próxima progresión</h2>${fixture}</div>${empty('Sin propuesta por ahora',insufficient()?'Sigue registrando sesiones. Conservamos tu historial sin sugerir un cambio.':'No hay cambios para revisar. Tu rutina sigue siendo la referencia.')}</section>`;
    return `<section class="panel proposal" aria-labelledby="proposal-title"><p class="eyebrow">Tu siguiente paso</p><h2 id="proposal-title">Próxima progresión</h2><div class="proposal-values"><strong>${ex.state==='increase_reps'?ex.reps:ex.load}<small> ${ex.unit==='reps'?'reps':'kg'}</small></strong><span aria-hidden="true">→</span><strong>${ex.proposed}<small> ${ex.unit==='reps'?'reps':'kg'}</small></strong></div>${fixture}<p>${esc(ex.reason)}</p><div class="proposal-evidence"><p class="tiny-label">Referencia disponible</p>${ex.evidence.map(v=>`<p>${esc(v)}</p>`).join('')}</div><button class="button full" data-action="proposal">${F.proposals[ex.state].action} ${arrow}</button><p class="micro muted">Propuesta conceptual · Regla sin evaluar.<br>Requiere revisión y confirmación.</p></section>`;
  }
  function history(ex) {
    if(noHistory()) return empty('Tu historial aparecerá aquí','Las sesiones completadas conservarán carga, reps y esfuerzo.');
    let rows=F.history;
    if(scenario==='top-range')rows=[{date:'29 sep',load:'80',sets:[8,8,8],rir:[2,2,2],volume:'1,920'},...F.history.slice(1)];
    if(ex.externalId===F.exercises.row.externalId)rows=[{date:'29 sep',load:'70',sets:[10,9,8],rir:[2,2,2],volume:'1,890'},{date:'21 sep',load:'70',sets:[10,9,8],rir:[2,2,2],volume:'1,890'}];
    if(scenario==='below')rows=[{date:'29 sep',load:'25',sets:[7,7,6],rir:[2,2,1],volume:'500'},{date:'21 sep',load:'25',sets:[7,6,6],rir:[2,2,2],volume:'475'}];
    if(scenario==='insufficient')rows=rows.slice(0,1);
    return `<div class="history-cards">${rows.map(r=>`<article class="history-card"><time class="history-date">${r.date}</time><div class="history-body"><strong>${r.load} kg <span class="muted">·</span> ${r.sets.join(' / ')} reps</strong><p>RIR ${r.rir.join(' / ')}</p></div><span class="history-volume">${r.volume}<br><small>kg · volumen</small></span></article>`).join('')}</div>`;
  }
  function progress() {
    const ex=exercise();
    return `<a class="back-link" href="#home"><span aria-hidden="true">←</span> Mi entrenamiento</a><section class="exercise-hero"><div>${badge(ex.state)}<h1>${esc(ex.name)}</h1><div class="metadata"><span>${scenario==='review'?'Identidad por confirmar':esc(ex.muscles)}</span><span>${esc(ex.equipment)}</span><span>${esc(ex.mechanic)}</span></div><button class="text-button" data-action="demo">Ver demostración <span aria-hidden="true">↗</span></button></div>${image(ex,true)}</section>
    <div class="exercise-layout"><div class="stack progress-main"><section class="panel panel-pad current-panel"><div><p class="tiny-label">Estado actual · top set reciente</p><div class="current-value">${noHistory()?'—':`${ex.load} <small>kg ×</small> ${ex.reps}`}</div><p class="micro muted">${noHistory()?'Aún sin sesión registrada':'Última sesión · 29 sep'}</p><div class="target-chips"><span>Rango <strong>${ex.range} reps</strong></span><span>RIR objetivo <strong>${ex.rir}</strong></span></div></div>${noHistory()?'':`<div class="last-sets"><span class="tiny-label">Últimas series<br>${ex.load} kg</span><div class="set-chips">${ex.sets.map(n=>`<span>${n}<span class="sr-only"> repeticiones</span></span>`).join('')}</div>`}</section>
    <section class="panel chart-panel"><div class="section-head"><h2>Tu evolución</h2>${fixture}</div><p class="micro muted">Carga por sesión</p>${insufficient()?'':`<p class="chart-value">${ex.load} <small>kg en la última sesión</small></p>`}<div class="segmented" role="group" aria-label="Periodo de evolución">${[['8','8 semanas'],['3','3 meses'],['6','6 meses']].map(([v,label])=>`<button data-period="${v}" aria-pressed="${period===v}">${label}</button>`).join('')}</div>${chart(ex)}</section>
    <div class="metrics-grid" aria-label="Métricas del historial"><div class="metric"><span>Mejor carga</span><strong>${noHistory()?'—':ex.load+' kg'}</strong><small>Máxima registrada · QA</small></div><div class="metric"><span>Mejor set</span><strong>${noHistory()?'—':ex.bestSet}</strong><small>Reps y carga del mismo set</small></div><div class="metric"><span>Volumen reciente</span><strong>${noHistory()?'—':ex.volume+' kg'}</strong><small>Última sesión comparable</small></div><div class="metric"><span>Sesiones</span><strong>${noHistory()?'0':scenario==='insufficient'?'1':ex.sessions}</strong><small>Referencia del fixture</small></div></div></div>
    <div class="stack progress-side">${proposal(ex)}<section class="panel panel-pad"><div class="section-head"><h2>Tu rango de reps</h2></div>${noHistory()?empty('Aún sin series','El rango es un objetivo de la rutina, no un nivel de fuerza.'):`<p class="micro muted">Objetivo ${ex.range} reps <span aria-hidden="true">/</span> Última serie</p><div class="range-scale" role="img" aria-label="${scenario==='below'?'6 repeticiones, por debajo del rango de 8 a 10':scenario==='top-range'?'8 repeticiones, tope del rango de 6 a 8':'Última serie dentro del rango objetivo'}"><span class="${scenario==='below'?'marked':''}"></span><span></span><span class="in-range"></span><span class="in-range ${scenario==='below'||scenario==='top-range'?'':'marked'}"></span><span class="in-range ${scenario==='top-range'?'marked':''}"></span><span></span></div><div class="range-labels"><span>Por debajo</span><span>${ex.range}</span><span>Por encima</span></div><p class="range-reading"><strong>${ex.sets[ex.sets.length-1]} reps</strong> ${scenario==='below'?'Buscando más reps':scenario==='top-range'?'Tope del rango':'Dentro del rango'}</p><p class="micro muted">Rango de la rutina · No es un nivel de fuerza.</p>`}</section></div>
    <section class="history-section"><div class="section-head"><h2>Sesiones recientes</h2><span class="micro muted">${noHistory()?'0':scenario==='insufficient'?'1':'Últimas sesiones'}</span></div>${history(ex)}${credit()}</section>${coach}</div>`;
  }
  function summary() {
    return `<a href="#home" class="back-link"><span aria-hidden="true">←</span> Mi entrenamiento</a><section class="panel completed-hero"><div class="completion-symbol" aria-hidden="true">✓</div><div class="completed-copy"><p class="eyebrow">Sesión de ejemplo · 29 sep</p><h1>Entrenamiento<br>completado.</h1><p class="subtitle">D1 · Pecho + espalda <span class="muted">/ Hipertrofia</span></p></div><div class="completion-metrics"><div><strong>58 <small>min</small></strong><span>Duración</span></div><div><strong>18 <small>/ 18</small></strong><span>Series completadas</span></div><div><strong>12.4 <small>t</small></strong><span>Volumen comparable · QA</span></div></div></section>
    <div class="summary-grid"><div class="stack"><section><div class="section-head"><h2>Lo que cambió hoy</h2>${fixture}</div><div class="changed-list">${[['bench','+1 rep vs última sesión','Mejoraste'],['row','Sin cambios','Mantener'],['incline','+2 kg por mancuerna','Más carga']].map(([key,delta,label])=>{const ex=F.exercises[key];return `<article class="panel changed-card">${image(ex)}<div><h3>${ex.name}</h3><p class="result">${ex.load} kg × ${ex.reps}</p><p class="delta ${key==='row'?'stable':''}">${delta}</p></div>${badge(key==='row'?'maintain':'increase_load',label)}</article>`;}).join('')}</div>${credit()}</section><section class="panel panel-pad"><div class="section-head"><h2>Hoy vs anterior</h2><span class="fixture-label">Mismo día del programa</span></div><div class="compare-labels"><span>D1 · Pecho + espalda</span><span>HOY</span><span>21 SEP</span></div>${[['Series','18','17'],['Volumen comparable','12.4 t','11.8 t'],['Duración','58 min','61 min']].map(([label,a,b])=>`<div class="comparison-row"><span>${label}</span><strong>${a}</strong><span>${b}</span></div>`).join('')}<p class="micro muted">Comparación ilustrativa. El volumen excluye cargas no comparables.</p></section></div>
    <div class="stack"><section class="panel proposal"><p class="eyebrow">Para la próxima</p><h2>${scenario==='no-proposals'?'Sin cambios por revisar':'Dos posibles siguientes pasos'}</h2><p class="micro muted">Propuestas de diseño · Sin aplicar</p>${scenario==='no-proposals'?empty('Sigue con tu rutina','No hay una progresión disponible por ahora.'):`<div class="candidate"><span class="candidate-icon" aria-hidden="true">↗</span><div><strong>Press banca</strong><p>Considerar +2.5 kg · requiere revisión</p></div></div><div class="candidate"><span class="candidate-icon cyan" aria-hidden="true">＋</span><div><strong>Curl con barra</strong><p>Buscar +1 rep con la misma carga</p></div></div><a href="#progress" class="button full">Revisar progresiones ${arrow}</a><p class="micro muted">Ningún ajuste se aplica automáticamente.</p>`}</section><section class="panel next-card"><span class="day-box">D2</span><div><p class="tiny-label">Próximo entrenamiento</p><h3>Piernas</h3><p class="micro muted">5 ejercicios · 17 series</p></div><button class="text-button" data-action="next">Ver D2 <span aria-hidden="true">→</span></button></section>${coach}<button class="button secondary full" data-action="home">Volver a mi entrenamiento</button></div></div>`;
  }
  function render(moveFocus = false) {
    const current=page();
    main.innerHTML=current==='progress'?progress():current==='summary'?summary():home();
    document.querySelectorAll('[data-page]').forEach(link=>{if(link.dataset.page===current)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
    document.title=`${current==='progress'?exercise().name:current==='summary'?'Entrenamiento completado':'Mi entrenamiento'} · Health Tracker · QA`;
    if(moveFocus){main.focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
  }
  function announce(message) { document.querySelector('#announcement').textContent=message; }
  function openDialog(title,content) {
    returnFocus=document.activeElement;
    document.querySelector('#dialog-content').innerHTML=`<p class="eyebrow">Vista de diseño · QA</p><h2 id="dialog-title">${esc(title)}</h2>${content}`;
    modal.showModal();
  }
  const actions={
    outside:()=>openDialog('El resto de Health Tracker','<p>Esta vista de diseño se centra en entrenamiento, progreso y cierre de sesión.</p><p>No navega a la cuenta ni a datos reales.</p>'),
    program:()=>openDialog('Hipertrofia · 5 días',`<p>Programa ficticio para revisar la experiencia visual.</p><div class="modal-list">${F.program.days.map((d,i)=>`<button class="button secondary" data-program-day="${i}">${d.id} · ${d.name} <span aria-hidden="true">→</span></button>`).join('')}</div>`),
    start:()=>openDialog(`Sesión QA · ${F.program.days[day].id}`,`<p>Fixture de entrenamiento completado. Las series están precargadas para revisar el cierre; no se registra una sesión.</p><div class="session-fixture-list">${F.program.days[0].preview.map(key=>row(F.exercises[key])).join('')}</div><p class="micro">El cierre diseñado utiliza D1 · Pecho + espalda.</p><div class="dialog-actions"><button class="button" data-action="complete">Finalizar entrenamiento QA →</button></div>`),
    complete:()=>{if(modal.open)modal.close();scenario='positive';document.querySelector('#scenario').value=scenario;if(location.hash==='#summary')render(true);else location.hash='summary';},
    home:()=>{location.hash='home';},
    next:()=>{day=1;location.hash='home';},
    catalog:()=>openDialog('Ejercicios del programa',`<p>Identidades seleccionadas explícitamente en el fixture. Imágenes del catálogo local.</p><div class="modal-list">${['bench','row'].map(key=>row(F.exercises[key],key==='bench'?'#progress':'#progress/row')).join('')}</div>${credit()}`),
    history:()=>openDialog('Historial de ejemplo',`<p>Press banca · sesiones ficticias.</p>${history(F.exercises.bench)}<div class="dialog-actions"><a href="#progress" class="button secondary">Ver evolución completa ${arrow}</a></div>`),
    demo:()=>{const ex=exercise();openDialog(ex.name,`${!ex.image || ['no-image','review'].includes(scenario)?empty('Sin imagen disponible','La identidad y el historial se conservan. No se sustituye por otra variante.'):`<p>${esc(ex.instruction)}</p><div class="demo-gallery"><img src="${esc(ex.image)}" alt="${esc(ex.canonicalName)} · posición inicial">${ex.detailImage?`<img src="${esc(ex.detailImage)}" alt="${esc(ex.canonicalName)} · posición final">`:''}</div>${credit()}<p class="micro muted">${esc(ex.canonicalName)} · Revisión f00c92c7dcf1</p>`}`);},
    mapping:()=>openDialog('Identidad por confirmar','<p>Este ejercicio necesita un vínculo explícito. El asistente existente resolverá la variante sin cambiar el nombre de la rutina.</p><p>No se guardan mappings desde este prototipo.</p>'),
    proposal:()=>{const ex=exercise();openDialog('Revisar cambio propuesto',`<p>${esc(ex.name)} ${badge(ex.state)}</p><div class="proposal-values"><strong>${ex.unit==='reps'?ex.reps:ex.load}<small> ${ex.unit==='reps'?'reps':'kg'}</small></strong><span aria-hidden="true">→</span><strong>${ex.proposed}<small> ${ex.unit==='reps'?'reps':'kg'}</small></strong></div><p>${esc(ex.reason)}</p><div class="dialog-evidence">${ex.evidence.map(v=>`<p>${esc(v)}</p>`).join('')}<p><strong>Regla:</strong> sin evaluar · Fixture UI</p><p><strong>Confianza:</strong> no disponible. No hay motor conectado.</p></div><p>Vista previa. Confirmar o descartar solo cambia este diálogo; tu rutina no se modifica.</p><div class="dialog-actions"><button class="button secondary" data-action="reject">Descartar ejemplo</button><button class="button" data-action="confirm">Confirmar ejemplo</button></div>`);},
    confirm:()=>{document.querySelector('#dialog-content').innerHTML='<p class="eyebrow">Interacción simulada</p><h2 id="dialog-title">Ejemplo confirmado</h2><div class="dialog-confirmed">✓ Recorrido de propuesta completado</div><p>La rutina y el historial siguen iguales. No se guardó ningún cambio.</p>';document.querySelector('.dialog-close').focus();announce('Ejemplo confirmado. No se guardó ningún cambio.');},
    reject:()=>{modal.close();announce('Ejemplo descartado. No se guardó ningún cambio.');}
  };
  document.addEventListener('click', event=>{
    if(event.target.closest('.skip-link')){event.preventDefault();main.focus();main.scrollIntoView({block:'start'});return;}
    const action=event.target.closest('[data-action]');
    if(action && actions[action.dataset.action])actions[action.dataset.action]();
    const dayButton=event.target.closest('[data-day]');
    if(dayButton){day=Number(dayButton.dataset.day);render();document.querySelector(`[data-day="${day}"]`).focus();announce(`Vista ${F.program.days[day].id}, ${F.program.days[day].name}`);}
    const periodButton=event.target.closest('[data-period]');
    if(periodButton){period=periodButton.dataset.period;render();document.querySelector(`[data-period="${period}"]`).focus();announce('Periodo de gráfica actualizado. Datos ficticios.');}
    const programButton=event.target.closest('[data-program-day]');
    if(programButton){day=Number(programButton.dataset.programDay);modal.close();if(page()==='home')render(true);else location.hash='home';}
    if(event.target.closest('dialog a[href^="#"]'))modal.close();
  });
  document.querySelector('#scenario').addEventListener('change',event=>{scenario=event.target.value;render(true);announce('Escenario ficticio actualizado.');});
  document.querySelector('#theme-toggle').addEventListener('click',()=>{
    const light=document.documentElement.dataset.theme!=='light';
    document.documentElement.dataset.theme=light?'light':'dark';
    document.querySelector('#theme-toggle').setAttribute('aria-label',`Cambiar a tema ${light?'oscuro':'claro'}`);
    document.querySelector('#theme-toggle').textContent=light?'◐':'☼';
  });
  document.querySelector('.dialog-close').addEventListener('click',()=>modal.close());
  modal.addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const controls=[...modal.querySelectorAll('button:not(:disabled),a[href],input,select,[tabindex="0"]')].filter(el=>el.getClientRects().length);
    const first=controls[0], last=controls[controls.length-1];
    if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
  });
  modal.addEventListener('close',()=>{if(returnFocus?.isConnected)returnFocus.focus();});
  document.addEventListener('error',event=>{
    if(event.target.tagName==='IMG'){const fallback=document.createElement('span');fallback.className='thumb fallback-thumb';fallback.setAttribute('role','img');fallback.setAttribute('aria-label','Sin imagen disponible');fallback.textContent='↔';event.target.replaceWith(fallback);}
  },true);
  window.addEventListener('hashchange',()=>{if(location.hash==='#main-content'){main.focus();return;}if(modal.open)modal.close();render(true);});
  render();
})();
