/* Design sandbox: local fixtures and memory only; no API, LLM, upload or persistence. */
(() => {
  const QA = window.NutritionQA, main = document.querySelector('main');
  const clone = value => JSON.parse(JSON.stringify(value));
  const esc = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = (v,precision=1) => {
    if(v==null)return '—';
    const format=new Intl.NumberFormat('es-MX',{maximumFractionDigits:precision}),resolution=10**-precision;
    return v>0&&v<resolution?`<${format.format(resolution)}`:format.format(v);
  };
  const foodById = id => QA.foods.find(f=>f.id===id);
  function grams(ingredient) {
    if (!Number.isFinite(ingredient.amount) || ingredient.amount <= 0) return null;
    if (ingredient.unit === 'g') return ingredient.amount;
    const serving = (ingredient.food || foodById(ingredient.foodId))?.servings.find(s=>s.id===ingredient.unit);
    return serving ? serving.grams * ingredient.amount : null;
  }
  function snapshot(ingredient) {
    const food = foodById(ingredient.foodId);
    return {...clone(ingredient),food:clone(food),normalizedGrams:grams(ingredient)};
  }
  function summarize(ingredients) {
    const entries=ingredients.map(i=>i.food ? {...i,normalizedGrams:grams(i)} : snapshot(i)), totalMass=entries.reduce((a,i)=>a+(i.normalizedGrams||0),0);
    const massComplete=entries.every(i=>i.normalizedGrams!=null);
    return Object.fromEntries(QA.definitions.map(d=>{
      const known=entries.filter(i=>i.normalizedGrams!=null && i.food.nutrients[d.id]!=null);
      const knownMass=known.reduce((a,i)=>a+i.normalizedGrams,0);
      return [d.id,{value:known.length ? known.reduce((a,i)=>a+i.food.nutrients[d.id]*i.normalizedGrams/i.food.base,0):null,
        coverage:massComplete && totalMass>0 ? knownMass/totalMass*100:null,known:known.length,total:entries.length,complete:entries.length>0 && known.length===entries.length}];
    }));
  }
  let logs = QA.initial.map(m=>({...clone(m),ingredients:m.ingredients.map(snapshot)}));
  let saved = [{...clone(QA.bowl),uses:12},{name:'Yogurt de la mañana',type:'Desayuno',ingredients:[{foodId:'yogurt',amount:150,unit:'g'}],uses:5}];
  let draft = clone(QA.bowl), selected='chicken', replaceIndex=null, editingLog=null, mode='builder', query='',filter='all', text='200 g de pollo, una taza de arroz y medio aguacate';
  const title = (eyebrow,heading,desc='') => `<div class="page-heading"><p class="eyebrow">${eyebrow}</p><h1>${heading}</h1>${desc?`<p class="muted">${desc}</p>`:''}</div>`;
  const button = (label,action,extra='',className='secondary')=>`<button class="${className}" data-action="${action}" ${extra}>${label}</button>`;
  const link = (label,to,className='secondary')=>`<a class="button ${className}" href="#${to}">${label}</a>`;
  const badge = (label,warning=false)=>`<span class="badge ${warning?'warning':''}">${label}</span>`;
  const subtotalLabel = s => s.value==null?'Sin dato conocido':'Subtotal conocido';
  const coverageMeaning = 'Disponibilidad de datos por masa. No indica cumplimiento de referencia ni garantiza completitud nutricional.';
  const macros = (summary) => `<div class="macro-grid">${['protein','carbohydrate','fat','fiber'].map(id=>`<div><span>${id==='carbohydrate'?'Carbohidratos':QA.definitions.find(d=>d.id===id).label}</span><strong>${number(summary[id].value)} <small>g</small></strong>${!summary[id].complete?`<small class="subtotal-label">${subtotalLabel(summary[id])}</small>`:''}</div>`).join('')}</div>`;
  const energy = summary => `<div class="energy"><strong>${number(summary.energy.value,0)}</strong><span>kcal ${summary.energy.complete?'':`· ${subtotalLabel(summary.energy).toLowerCase()}`}</span></div>`;
  const totalsPanel = (s,heading='Tu comida')=>`<section class="card total-card"><p class="eyebrow">${heading}</p>${energy(s)}${macros(s)}<p class="muted small">${s.fiber.complete?'Datos de fibra completos.':'Fibra: datos parciales; el subtotal no se compara con una referencia.'}</p><a class="text-link" href="#micros">Ver cobertura del día →</a></section>`;
  function today() {
    const sum=summarize(logs.flatMap(m=>m.ingredients));
    return title('JUEVES · 8 OCTUBRE 2026','Nutrición de hoy','Alimentos reales. Un día con más contexto.')+`<div class="today-grid"><div><section class="card hero"><div class="row"><p class="eyebrow">INGESTA REGISTRADA · DEMO</p>${badge('Catálogo offline')}</div>${energy(sum)}<div class="goal-grid">${['protein','carbohydrate','fat','fiber'].map(id=>{const s=sum[id],goal=QA.goals[id];return `<div data-metric="${id}" data-state="${s.complete?'complete':'partial'}"><div class="row"><span>${id==='carbohydrate'?'Carbohidratos':QA.definitions.find(d=>d.id===id).label}</span><strong>${number(s.value)}${s.complete?` / ${goal}`:''} g</strong></div>${s.complete?`<progress max="${goal}" value="${s.value}" aria-label="${id} respecto al objetivo demo"></progress>`:`<small class="subtotal-label">${subtotalLabel(s)} · sin comparación con objetivo</small>`}</div>`;}).join('')}</div><p class="muted small">Objetivos ficticios QA. No son recomendaciones.</p>${link('+ Añadir comida','add','primary')}</section><div class="section-heading"><h2>Tus comidas</h2><span>${logs.length} registros demo</span></div>${logs.length?logs.map((m,i)=>`<article class="card meal-card"><div class="row"><span class="eyebrow">${esc(m.type)}</span>${badge('Snapshot')}</div><h3>${esc(m.name)}</h3><p><strong>${number(summarize(m.ingredients).energy.value,0)} kcal</strong> · ${m.ingredients.length} ingredientes</p><p class="muted small">${m.ingredients.map(x=>`${esc(x.food.name)} · ${number(x.amount)} ${esc(x.unit)}`).join(' / ')}</p><div class="actions">${button('Repetir comida','repeat',`data-index="${i}"`)}${button('Editar','edit-log',`data-index="${i}"`)}</div></article>`).join(''):`<section class="card empty"><span class="empty-symbol">＋</span><h2>Tu día empieza aquí</h2><p class="muted">Aún no hay comidas registradas. La ingesta es desconocida.</p>${link('Añadir primera comida','add','primary')}</section>`}<section class="card"><h2>Frecuentes</h2><p class="muted">Ordenadas por usos ficticios, sin IA.</p>${saved.slice().sort((a,b)=>b.uses-a.uses).map(m=>button(`${esc(m.name)} →`,'use-saved',`data-index="${saved.indexOf(m)}"`)).join('')}</section></div><div><section class="card"><div class="row"><h2>Micronutrientes</h2>${link('Ver todos','micros')}</div><p class="muted">Cobertura de datos ≠ porcentaje de referencia.</p>${microRows(sum,['calcium','iron','vitamin_d'])}</section><section class="card insights"><p class="eyebrow">LO QUE DESTACA HOY</p><h2>Espacio para el Coach</h2><p class="muted">Aquí aparecerán señales del motor determinístico cuando esté disponible.</p>${badge('Diseño futuro')}</section><details class="card qa-controls"><summary>Escenarios de revisión QA</summary><div class="actions">${button('Día vacío','empty')}${button('Restaurar demo','reset')}</div></details></div></div>`;
  }
  function microRows(sum,ids) {
    return ids.map(id=>{const d=QA.definitions.find(d=>d.id===id),s=sum[id],reference=QA.references[id];
      return `<div class="nutrient-row ${s.complete?'':'partial'}" data-nutrient="${id}"><div class="row"><strong>${d.label}</strong><span>${number(s.value)} ${d.unit}</span></div>${!s.complete?`<p class="small subtotal-label">${subtotalLabel(s)}${s.value==null?'':' · datos parciales'}</p>`:''}<p class="small muted">Cobertura por masa: ${s.coverage==null?'no calculable':number(s.coverage,0)+'%'} · ${s.known}/${s.total} ingredientes</p><p class="small muted coverage-meaning">${coverageMeaning}</p>${!s.complete?'<p class="small muted">No hay suficientes datos para evaluar el día. No se compara con la referencia.</p>':reference?`<p class="small reference-value">${number(s.value/reference*100,0)}% de referencia ficticia QA</p>`:'<p class="small muted">Sin referencia seleccionada.</p>'}</div>`;
    }).join('');
  }
  function add() {
    return title('REGISTRO RÁPIDO','Añadir comida','Elige cómo empezar. Siempre podrás revisar.')+`<div class="split"><div><div class="choice-grid">${link('↗ Buscar alimento','search')}${link('♡ Comidas guardadas','saved')}${button('＋ Armar comida','new-builder')}</div><section class="card"><h2>¿Qué comiste?</h2><label for="meal-text">Describe alimentos y cantidades</label><textarea id="meal-text" rows="4">${esc(text)}</textarea><p class="muted small">Simulación fija QA para el ejemplo mostrado. No interpreta otros textos.</p>${button('Ver candidatos de texto demo','text-candidates','','primary')}</section><section class="card"><p class="eyebrow">FOTO → CANDIDATOS → REVISIÓN</p><h2>Una foto para empezar</h2><p class="muted">La foto sugiere alimentos; Health Tracker calcula los nutrientes.</p><label class="upload-label" for="photo">Elegir foto local</label><input id="photo" type="file" accept="image/*" capture="environment"><p id="photo-status" class="small muted">La imagen no se sube ni se analiza. Se descarta al salir.</p>${button('Ver reconocimiento demo','photo-candidates')}</section></div><section class="card total-card"><h2>Lo habitual, en dos pasos</h2><p class="muted">Elige una comida guardada y confirma. Ajustar cantidades es opcional.</p>${saved.map((m,i)=>button(esc(m.name),'use-saved',`data-index="${i}"`)).join('')}<div class="divider"></div><p class="muted">¿Tu producto no está en el catálogo?</p>${link('Crear mi alimento','user-food')}</section></div>`;
  }
  function candidates() {
    const evidence=i=>mode==='photo'?`Evidencia visual QA: ${i.foodId==='chicken'?'pieza clara; cocción no distinguible':'forma compatible, sin escala de peso'}. Confianza sin calibrar.`:'Evidencia de texto QA: alimento mencionado en el ejemplo. Preparación y porción requieren confirmación.';
    return title(mode==='photo'?'RECONOCIMIENTO SIMULADO QA':'TEXTO SIMULADO QA',mode==='photo'?'Detectamos posiblemente':'Candidatos por revisar','Estas propuestas no se registran automáticamente.')+`<div class="split"><div><section class="card ambiguity"><h2>La preparación necesita revisión</h2><p>No podemos distinguir pollo empanizado de pollo a la plancha en este escenario demo.</p><p class="muted">Selecciona el alimento y confirma la cantidad en una sola pantalla de revisión.</p></section>${draft.ingredients.map(i=>`<section class="card candidate"><div class="row"><h3>${esc(foodById(i.foodId).name)}</h3>${badge('Por revisar',true)}</div><p>${number(i.amount)} ${esc(i.unit)} · ${i.foodId==='chicken'?'Preparación incierta':'Cantidad estimada'}</p><p class="muted small">${evidence(i)}</p></section>`).join('')}${link('Revisar comida','review','primary')}</div><section class="card total-card"><h2>Primero, confirmar alimentos</h2><p class="muted">Las estimaciones siguen pendientes. El catálogo demo aporta los valores cuando aceptas la identidad.</p>${badge('Nada registrado')}</section></div>`;
  }
  function review() {
    const sum=summarize(draft.ingredients),pendingCount=draft.ingredients.filter(i=>i.pending).length,pending=pendingCount>0,valid=draft.ingredients.length>0&&draft.ingredients.every(i=>grams(i)!=null);
    return title('INGREDIENTES → CANTIDADES → NUTRIENTES',mode==='builder'?'Arma tu comida':'Revisa tu comida','Revisa cada alimento y su cantidad.')+`<div class="split review-layout"><section><div class="card meal-meta"><div><label for="meal-name">Nombre</label><input id="meal-name" value="${esc(draft.name)}" maxlength="200"></div><div><label for="meal-type">Momento</label><select id="meal-type">${['Desayuno','Comida','Cena','Snacks'].map(t=>`<option ${draft.type===t?'selected':''}>${t}</option>`).join('')}</select></div></div><div class="row ingredient-heading"><h2>Ingredientes</h2><span class="badge pending-count" role="status" aria-live="polite">${pendingCount} pendientes</span></div>${draft.ingredients.map((i,index)=>{const f=foodById(i.foodId);return `<article class="card ingredient"><div class="row"><h3>${esc(f.name)}</h3>${badge(i.pending?'Por revisar':'Revisado',!!i.pending)}</div><div class="quantity-grid"><div><label for="amount-${index}">Cantidad</label><input id="amount-${index}" data-amount="${index}" inputmode="decimal" type="number" min="0.01" max="100000" step="any" value="${i.amount}"></div><div><label for="unit-${index}">Unidad</label><select id="unit-${index}" data-unit="${index}">${[{id:'g',label:'g'},...f.servings].map(s=>`<option value="${s.id}" ${i.unit===s.id?'selected':''}>${esc(s.label)}</option>`).join('')}<option value="ml" ${i.unit==='ml'?'selected':''}>ml · sin densidad</option></select></div></div><p class="small ${grams(i)==null?'coverage-note':'muted'}">${grams(i)==null?'Cantidad no convertible. Elige gramos o una porción definida.':`${number(grams(i))} g normalizados · definición QA`}</p><div class="actions">${button('Cambiar','change-food',`data-index="${index}" aria-label="Cambiar alimento: ${esc(f.name)}"`)}${button('Eliminar','remove',`data-index="${index}" aria-label="Eliminar ingrediente: ${esc(f.name)}"`)}${i.pending?button('Confirmar identidad y cantidad','accept',`data-index="${index}"`):''}</div></article>`;}).join('')}${draft.ingredients.length?'':'<section class="card empty"><p>Añade tu primer ingrediente.</p></section>'}${link('+ Añadir ingrediente','search')}</section><div id="review-summary">${totalsPanel(sum)}<section class="card"><p class="coverage-note">${pending?`${pendingCount} ingredientes pendientes de revisión.`:!valid?'Revisa las cantidades antes de registrar.':'Comida lista para tu confirmación.'}</p>${button(editingLog==null?'Registrar comida':'Guardar cambios','register',valid&&!pending?'':'disabled','primary')}${button('Guardar comida reutilizable','save-template',valid&&!pending?'':'disabled')}<p class="small muted">Simulación en memoria. Al recargar vuelve el día demo.</p></section></div></div>`;
  }
  function results() {
    const matches=QA.foods.filter(f=>f.name.toLocaleLowerCase('es').includes(query.toLocaleLowerCase('es'))&&(filter==='all'||f.kind===filter));
    return matches.length?matches.map(f=>`<button class="food-result ${f.id===selected?'selected':''}" data-action="food-detail" data-id="${f.id}"><span><strong>${esc(f.name)}</strong><small>${esc(f.provenance.source_name)}</small><span>${number(f.nutrients.energy,0)} kcal / 100 g · ${number(f.nutrients.protein)} g proteína</span></span><span aria-hidden="true">↗</span></button>`).join(''):'<div class="card empty"><h2>Sin coincidencias</h2><p class="muted">Prueba otro nombre o crea un alimento personal.</p>'+link('Crear mi alimento','user-food')+'</div>';
  }
  function search() {
    return title('CATÁLOGO LOCAL · DEMO','Buscar alimento','Crudo y cocido tienen identidades distintas.')+`<div class="search-layout"><section><label for="food-search">Nombre del alimento</label><input id="food-search" type="search" placeholder="Prueba pollo, arroz…" value="${esc(query)}"><label for="food-filter">Origen</label><select id="food-filter"><option value="all">Todos</option><option value="catalog" ${filter==='catalog'?'selected':''}>Catálogo QA</option><option value="user" ${filter==='user'?'selected':''}>Mis alimentos</option></select><div id="search-results" aria-live="polite">${results()}</div></section><section class="desktop-detail">${detailContent()}</section></div>`;
  }
  function detailContent() {
    const f=foodById(selected);
    return `<section class="card food-detail"><div class="row">${badge(f.kind==='user'?'Mi alimento':'Catálogo QA')}${badge('Disponible offline')}</div><h2>${esc(f.name)}</h2><p class="muted">Por 100 g · alimento ${f.id==='raw'?'crudo':'del catálogo demo'}</p>${energy(summarize([{foodId:f.id,amount:100,unit:'g'}]))}${macros(summarize([{foodId:f.id,amount:100,unit:'g'}]))}<details><summary>Fuente y revisión</summary><p>${esc(f.provenance.source_name)} · ${f.revision}</p><p class="muted small">Valores ficticios. Sin verificación externa.</p></details><h3>Añadir a tu comida</h3><div class="quantity-grid"><div><label for="quick-amount">Cantidad</label><input id="quick-amount" type="number" inputmode="decimal" min="0.01" max="100000" step="any" value="180"></div><div><label for="quick-unit">Unidad</label><select id="quick-unit"><option value="g">g</option>${f.servings.map(s=>`<option value="${s.id}">${esc(s.label)}</option>`).join('')}<option value="ml">ml · sin densidad</option></select></div></div><p id="quick-preview" class="preview" aria-live="polite"></p>${button(replaceIndex==null?'Añadir ingrediente':'Sustituir ingrediente','quick-add','','primary')}<h3>Micronutrientes disponibles</h3>${['Minerales','Vitaminas','Otros'].map(group=>{const defs=QA.definitions.filter(d=>d.group===group && f.nutrients[d.id]!=null);return defs.length?`<details ${group==='Minerales'?'open':''}><summary>${group} · ${defs.length}</summary>${defs.map(d=>`<div class="row nutrient-row"><span>${d.label}</span><strong>${number(f.nutrients[d.id])} ${d.unit}</strong></div>`).join('')}</details>`:'';}).join('')||'<p class="muted">Sin micronutrientes informados.</p>'}<p class="muted small">No informado: ${QA.definitions.filter(d=>d.group!=='Macros'&&f.nutrients[d.id]==null).map(d=>d.label).join(', ')}. Desconocido no equivale a cero.</p></section>`;
  }
  function detail(){return title('ALIMENTO → CANTIDAD','Detalle de alimento')+`<div class="detail-wrap">${detailContent()}${link('Volver a buscar','search')}</div>`;}
  function savedMeals() {
    return title('HECHO UNA VEZ, LISTO PARA REPETIR','Comidas guardadas','Selecciona → revisa si quieres → registra.')+`<div class="saved-grid">${saved.slice().sort((a,b)=>b.uses-a.uses).map(m=>`<article class="card saved-card"><p class="eyebrow">${m.uses} USOS DEMO</p><h2>${esc(m.name)}</h2><p class="muted">${m.ingredients.length} ingredientes · cantidades ajustables</p>${energy(summarize(m.ingredients))}${button('Usar comida','use-saved',`data-index="${saved.indexOf(m)}"`,'primary')}<p class="small muted">Una receta nueva no modifica registros anteriores.</p></article>`).join('')}</div>`;
  }
  function micros() {
    const sum=summarize(logs.flatMap(m=>m.ingredients)),defs=QA.definitions.filter(d=>d.group!=='Macros'),complete=defs.filter(d=>sum[d.id].complete&&QA.references[d.id]),unknown=defs.filter(d=>!sum[d.id].complete||!QA.references[d.id]);
    return title('APORTE CONOCIDO + COBERTURA','Micronutrientes del día','Una referencia de ingesta no es un diagnóstico.')+`<section class="card coverage-intro"><h2>Qué significa cobertura</h2><p>Porcentaje del peso registrado cuyos alimentos informan este nutriente. No mide cuánto comiste frente a un objetivo.</p><p class="muted small">No demuestra que hayas registrado toda tu ingesta. Referencias ficticias QA sólo para revisar el diseño.</p></section><div class="split"><div><h2>A revisar · referencia demo</h2>${microRows(sum,complete.filter(d=>sum[d.id].value<QA.references[d.id]).map(d=>d.id))||'<p class="muted">Sin nutrientes evaluables bajo referencia demo.</p>'}<h2>En rango de referencia demo</h2>${microRows(sum,complete.filter(d=>sum[d.id].value>=QA.references[d.id]).map(d=>d.id))||'<p class="muted">Sin nutrientes evaluables en este escenario.</p>'}</div><section class="card"><h2>Datos o referencia insuficientes</h2>${microRows(sum,unknown.map(d=>d.id))}</section></div>`;
  }
  function userFood() {
    return title('PROVENANCE = USER','Crear mi alimento','Tu etiqueta, separada del catálogo.')+`<form id="user-food-form" class="card detail-wrap"><label for="user-name">Nombre</label><input id="user-name" required maxlength="200" placeholder="Producto local demo"><p class="muted">Base: 100 g. Deja vacíos los nutrientes desconocidos.</p>${['energy','protein','carbohydrate','fat','fiber','sodium','calcium'].map(id=>{const d=QA.definitions.find(x=>x.id===id);return `<label for="user-${id}">${d.label} (${d.unit}) · opcional</label><input id="user-${id}" type="number" min="0" max="1000000" step="any">`;}).join('')}<label for="user-serving">Peso por porción (g) · opcional</label><input id="user-serving" type="number" min="0.01" max="100000" step="any"><button class="primary" type="submit">Crear alimento demo</button><p class="muted small">Sólo en memoria; no se incorpora a ningún catálogo oficial.</p></form>`;
  }
  function go(view){if(location.hash===`#${view}`)render();else location.hash=view;}
  let noticeTimer;
  function notify(message){clearTimeout(noticeTimer);document.querySelector('#notice').textContent=message;noticeTimer=setTimeout(()=>{document.querySelector('#notice').textContent='';},4000);}
  function render(focus=true) {
    const route=location.hash.slice(1)||'today',views={today,add,candidates,review,search,detail,saved:savedMeals,micros,'user-food':userFood};
    main.innerHTML=(views[route]||today)();
    document.querySelectorAll('nav a').forEach(a=>{if(a.hash===`#${route}`)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    if(focus){main.focus({preventScroll:true});window.scrollTo(0,0);}
    quickPreview();
  }
  function quickPreview(){
    const preview=document.querySelector('#quick-preview');if(!preview)return;
    const i={foodId:selected,amount:Number(document.querySelector('#quick-amount').value),unit:document.querySelector('#quick-unit').value},g=grams(i),s=summarize([i]);
    preview.textContent=g==null?'No hay conversión conocida. Elige gramos o una porción definida.':`${number(g)} g → ${number(s.energy.value,0)} kcal · ${number(s.protein.value)} g proteína`;
    document.querySelector('[data-action="quick-add"]').disabled=g==null;
  }
  function refreshSummary(){
    // Preserve the focused quantity input; never replace it during typing.
    const s=summarize(draft.ingredients),el=document.querySelector('#review-summary .total-card');if(el)el.outerHTML=totalsPanel(s);
    const valid=draft.ingredients.length>0&&draft.ingredients.every(i=>grams(i)!=null&&!i.pending);
    document.querySelectorAll('[data-amount]').forEach(input=>{
      const i=draft.ingredients[Number(input.dataset.amount)],g=grams(i),hint=input.closest('.ingredient').querySelector('.quantity-grid + p');
      hint.textContent=g==null?'Cantidad no convertible. Elige gramos o una porción definida.':`${number(g)} g normalizados · definición QA`;
      hint.className=g==null?'small coverage-note':'small muted';
    });
    const pendingCount=draft.ingredients.filter(i=>i.pending).length;
    document.querySelector('#review-summary > section:last-child .coverage-note').textContent=pendingCount?`${pendingCount} ingredientes pendientes de revisión.`:!valid?'Revisa las cantidades antes de registrar.':'Comida lista para tu confirmación.';
    ['register','save-template'].forEach(action=>{const b=document.querySelector(`[data-action="${action}"]`);if(b)b.disabled=!valid;});
  }
  document.addEventListener('input',event=>{
    const el=event.target;
    if(el.id==='meal-text')text=el.value;
    if(el.id==='meal-name')draft.name=el.value;
    if(el.dataset.amount!=null){draft.ingredients[Number(el.dataset.amount)].amount=Number(el.value);refreshSummary();}
    if(el.id==='food-search'){query=el.value;document.querySelector('#search-results').innerHTML=results();}
    if(el.id==='quick-amount')quickPreview();
  });
  document.addEventListener('change',event=>{
    const el=event.target;
    if(el.id==='meal-type')draft.type=el.value;
    if(el.dataset.unit!=null){draft.ingredients[Number(el.dataset.unit)].unit=el.value;const id=el.id;render(false);document.getElementById(id).focus();}
    if(el.id==='food-filter'){filter=el.value;document.querySelector('#search-results').innerHTML=results();}
    if(el.id==='quick-unit')quickPreview();
    if(el.id==='photo')document.querySelector('#photo-status').textContent=el.files.length?'Foto seleccionada localmente. Los candidatos siguientes son una simulación QA fija.':'Sin foto seleccionada.';
  });
  document.addEventListener('click',event=>{
    const el=event.target.closest('[data-action]');if(!el)return;const index=Number(el.dataset.index);
    switch(el.dataset.action){
      case 'empty':logs=[];render();break;
      case 'reset':location.reload();break;
      case 'new-builder':draft={name:'Mi comida',type:'Comida',ingredients:[]};mode='builder';editingLog=null;replaceIndex=null;go('review');break;
      case 'use-saved':draft=clone(saved[index]);draft.templateIndex=index;mode='saved';editingLog=null;replaceIndex=null;go('review');break;
      case 'repeat':draft={...clone(logs[index]),ingredients:logs[index].ingredients.map(i=>({...clone(i),pending:false}))};mode='repeat';editingLog=null;go('review');break;
      case 'edit-log':draft=clone(logs[index]);editingLog=index;mode='edit';go('review');break;
      case 'photo-candidates':case 'text-candidates':
        mode=el.dataset.action==='photo-candidates'?'photo':'text';draft=clone(QA.bowl);editingLog=null;replaceIndex=null;
        if(mode==='text')draft.ingredients=[{foodId:'chicken',amount:200,unit:'g'},{foodId:'rice',amount:1,unit:'cup'},{foodId:'avocado',amount:1,unit:'half'}];
        draft.ingredients.forEach(i=>i.pending=true);go('candidates');break;
      case 'accept':draft.ingredients[index].pending=false;render(false);document.querySelector(`[data-amount="${index}"]`)?.focus();break;
      case 'remove':draft.ingredients.splice(index,1);render(false);main.focus();break;
      case 'change-food':replaceIndex=index;go('search');break;
      case 'food-detail':selected=el.dataset.id;go('detail');break;
      case 'quick-add':{
        const i={foodId:selected,amount:Number(document.querySelector('#quick-amount').value),unit:document.querySelector('#quick-unit').value};
        if(grams(i)==null)break;
        if(replaceIndex==null)draft.ingredients.push(i);else draft.ingredients[replaceIndex]=i;
        replaceIndex=null;go('review');break;
      }
      case 'save-template':if(draft.ingredients.length&&draft.ingredients.every(i=>grams(i)!=null&&!i.pending)){
        const template={name:draft.name.trim()||'Comida demo',type:draft.type,ingredients:clone(draft.ingredients),uses:0};
        if(draft.templateIndex!=null){template.uses=saved[draft.templateIndex].uses;saved[draft.templateIndex]=template;}else saved.push(template);
        notify('Comida guardada en la demo. Los snapshots anteriores se conservan.');go('saved');}break;
      case 'register':if(draft.ingredients.length&&draft.ingredients.every(i=>grams(i)!=null&&!i.pending)){
        const log={name:draft.name.trim()||'Comida demo',type:draft.type,ingredients:draft.ingredients.map(i=>i.food?clone(i):snapshot(i))};
        // Quantity edits re-scale the pinned revision, not today's catalog values.
        log.ingredients.forEach(i=>{i.normalizedGrams=grams(i);delete i.pending;});
        if(editingLog==null)logs.push(log);else logs[editingLog]=log;
        if(draft.templateIndex!=null)saved[draft.templateIndex].uses++;
        editingLog=null;notify('Comida registrada sólo en esta demo.');go('today');}break;
    }
  });
  document.addEventListener('submit',event=>{
    if(event.target.id!=='user-food-form')return;event.preventDefault();
    const nutrients={};['energy','protein','carbohydrate','fat','fiber','sodium','calcium'].forEach(id=>{const v=document.querySelector(`#user-${id}`).value;nutrients[id]=v===''?null:Number(v);});
    const id=`user-${QA.foods.length}`,serving=document.querySelector('#user-serving').value;
    QA.foods.push({id,name:document.querySelector('#user-name').value.trim(),kind:'user',base:100,unit:'g',revision:'qa-1',nutrients,
      servings:serving?[{id:'serving',label:'Mi porción QA',grams:Number(serving)}]:[],provenance:{source:'user',source_name:'Creado por ti · DEMO',source_food_id:id,source_revision:'qa-1',nutrient_revision:'qa-1',verified_at:null}});
    selected=id;notify('Alimento personal creado sólo en memoria.');go('detail');
  });
  document.querySelector('#theme').addEventListener('click',event=>{const light=document.documentElement.dataset.theme!=='light';document.documentElement.dataset.theme=light?'light':'dark';event.target.textContent=light?'Tema oscuro':'Tema claro';});
  // Read-only hooks for reproducible design QA, not a production API.
  window.NutritionDesign={grams,summarize,getLogs:()=>clone(logs),getSaved:()=>clone(saved)};
  window.addEventListener('hashchange',()=>render());render(false);
})();
