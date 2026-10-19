'use strict';
// Entirely fictional fixtures. This prototype never reads files, fetches or writes to a server.
const seed={
 '2040-01-28':{intake:null,intakeState:'unknown',expense:null,active:null,resting:null,steps:0,distance:0},
 '2040-01-29':{intake:2600,intakeState:'known',expense:2300,active:500,resting:1800,steps:6000,distance:4500},
 '2040-01-30':{intake:1450,intakeState:'partial',expense:2400,active:600,resting:1800,steps:7200,distance:5400},
 '2040-02-01':{intake:2200,intakeState:'known',expense:2550,active:700,resting:1850,steps:8600,distance:6700},
 '2040-02-02':{intake:1900,intakeState:'known',expense:null,expenseConflict:true,active:null,resting:null,steps:7400,distance:5500},
 '2040-02-03':{intake:2200,intakeState:'known',expense:2500,active:600,resting:1900,steps:8200,distance:6400}
};
let data=structuredClone(seed), selected='2040-02-03',view='overview',period=7,importStep=0,proposal=null;
const initialEvents=[{kind:'review',date:'3 feb · 10:45',title:'Fuente retirada de la vista diaria',body:'La evidencia y el original siguen disponibles en el historial.'},{kind:'import',date:'3 feb · 10:42',title:'Registro de gasto importado',body:'Se conserva el documento original. No sustituye otras fuentes.'},{kind:'import',date:'3 feb · 09:10',title:'Pasos y distancia recibidos',body:'Fuente de actividad parcial; no incluye gasto.'},{kind:'review',date:'1 feb · 18:20',title:'Revisión confirmada por campo',body:'Se conserva el valor de cada fuente y la decisión posterior.'}];
initialEvents.forEach((e,i)=>{e.isoDate=i===3?'2040-02-01':'2040-02-03';e.source=i===2?'Reloj QA':'Archivo QA';});initialEvents[0].kind='retire';
let events=structuredClone(initialEvents),historyPage=1;
const $=id=>document.getElementById(id), num=value=>new Intl.NumberFormat('es-MX',{maximumFractionDigits:0}).format(value);
const utc=s=>new Date(s+'T12:00:00Z'),iso=date=>date.toISOString().slice(0,10),shift=(s,n)=>{let d=utc(s);d.setUTCDate(d.getUTCDate()+n);return iso(d);};
const label=s=>new Intl.DateTimeFormat('es-MX',{day:'numeric',month:'short',timeZone:'UTC'}).format(utc(s));
const get=s=>data[s]||{intake:null,intakeState:'unknown',expense:null,steps:null,distance:null,active:null,resting:null};
const balance=d=>d.intakeState==='known'&&d.expense!==null?d.intake-d.expense:null;
const mean=a=>{a=a.filter(v=>v!==null);return a.length?a.reduce((s,n)=>s+n,0)/a.length:null;};
const comparable=(d,key)=>key==='intake'?(d.intakeState==='known'?d.intake:null):key==='balance'?balance(d):d[key];
let toastTimer;
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3200);}
function changeView(next,focus=false){view=next;for(const name of ['overview','calendar','sources','import','history']){$(name).hidden=name!==view;$('tab-'+name).setAttribute('aria-selected',String(name===view));}if(focus)$('tab-'+next).focus();}
function setDay(day){selected=day;$('day').value=day;proposal=null;render();}
function metric(id,value,state){$(id).innerHTML=(value===null?'—':num(value))+'<small>kcal</small>';$(id+'-state').innerHTML=state;}
function render(){
 const d=get(selected),b=balance(d),empty=d.expense===null&&d.steps===null&&d.intake===null;
 metric('intake',d.intake,d.intakeState==='partial'?'<span class="warning">Subtotal conocido<br>Ingesta parcial</span>':d.intake!==null?'Ingesta conocida':'Sin registro');
 metric('expense',d.expense,d.expenseConflict?'<span class="warning">Conflicto pendiente</span>':d.expense!==null?'Gasto conocido':'No disponible');
 metric('balance',b,b!==null?'Ingesta − gasto':d.intakeState==='partial'?'No calculable<br>Ingesta parcial':d.expenseConflict?'No calculable<br>Gasto en conflicto':'No calculable');
 $('day-state').innerHTML=empty?(selected==='2040-02-04'?'<strong>Hoy no hay registro.</strong> ':'<strong>Sin registro para esta fecha.</strong> ')+'<button class="text-button" id="latest">Último · 3 feb · gasto 2,500 kcal</button>':d.expenseConflict?'<strong>1 campo pendiente.</strong> Los valores contradictorios no se usan en el balance.':d.intakeState==='partial'?'<strong>Ingesta parcial.</strong> Se muestra sólo el subtotal disponible.':d.expense===null?'<strong>Actividad parcial.</strong> Los pasos no permiten inferir gasto.':'<strong>'+label(selected)+' · Gasto conocido.</strong> Sus fuentes se conservan por separado.';
 if($('latest'))$('latest').onclick=()=>setDay('2040-02-03');
 $('activity').innerHTML=[['Activas',d.active===null?'—':num(d.active)+' kcal'],['Reposo',d.resting===null?'—':num(d.resting)+' kcal'],['Pasos',d.steps===null?'—':num(d.steps)],['Distancia',d.distance===null?'—':(d.distance/1000).toLocaleString('es-MX')+' km']].map(([key,value])=>'<div><dt>'+key+'</dt><dd>'+value+'</dd></div>').join('');
 $('origin-summary').innerHTML=empty?'<p>Sin evidencia para este día. Consulta el último registro o añade uno.</p>':d.expenseConflict?'<p>Dos fuentes discrepan en gasto. Puedes revisar el campo sin cambiar las evidencias originales.</p>':'<div class="source-mini"><span>'+(d.importedActivity?'Archivo de actividad QA':'Reloj · actividad')+'</span><b>Pasos y distancia</b></div>'+(d.expense!==null?'<div class="source-mini"><span>Importación · gasto</span><b>Total disponible</b></div>':'<p class="note">Sin fuente de gasto para esta fecha.</p>');
 renderCharts();renderCalendar();renderSources();renderImport();renderHistory();
}
function pathSegments(values,x,y){const result=[];let part=[];values.forEach((v,i)=>{if(v===null){if(part.length)result.push(part);part=[];}else part.push([x(i),y(v)]);});if(part.length)result.push(part);return result.map(part=>'<polyline points="'+part.map(p=>p.join(',')).join(' ')+'"/>').join('');}
function renderCharts(){
 const dates=Array.from({length:period},(_,i)=>shift(selected,i-period+1));
 const labels={intake:'Ingesta · contexto Nutrition',expense:'Gasto total',balance:'Balance comparable',active:'Calorías activas',resting:'Calorías de reposo',steps:'Pasos',distance:'Distancia'};
 function plot(key){
  const unit=key==='steps'?'pasos':key==='distance'?'m':'kcal';
  const daily=dates.map(s=>comparable(get(s),key)),subtotal=key==='intake'?dates.map(s=>get(s).intakeState==='partial'?get(s).intake:null):dates.map(()=>null);
  const windows=dates.map(s=>Array.from({length:7},(_,i)=>comparable(get(shift(s,i-6)),key))),rolling=windows.map(mean);
  const values=[...daily,...subtotal,...rolling].filter(v=>v!==null),lo=Math.min(0,...values),hi=Math.max(0,...values);
  if(!values.length)return ['expense','intake','balance'].includes(key)?'<article class="chart"><h3>'+labels[key]+'</h3><p>Sin datos conocidos. Ausentes y conflictos no son cero.</p></article>':'';
  const low=lo<0?lo*1.1:0,high=hi>0?hi*1.1:lo<0?0:1,x=i=>44+(i+.5)/period*230,y=v=>165-(v-low)/(high-low)*135,bw=Math.min(20,180/period);
  const bars=daily.map((v,i)=>v===null?'':'<rect class="daily-bar" x="'+(x(i)-bw/2)+'" y="'+Math.min(y(0),y(v))+'" width="'+bw+'" height="'+Math.max(2,Math.abs(y(0)-y(v)))+'"><title>'+label(dates[i])+': '+num(v)+' '+unit+(v===0?' · cero conocido':'')+'</title></rect>').join('');
  const partials=subtotal.map((v,i)=>v===null?'':'<circle class="partial-point" cx="'+x(i)+'" cy="'+y(v)+'" r="4"><title>Subtotal parcial '+num(v)+' '+unit+'</title></circle>').join('');
  const gaps=daily.map((v,i)=>v!==null||subtotal[i]!==null?'':'<text x="'+x(i)+'" y="178" text-anchor="middle">'+(key==='expense'&&get(dates[i]).expenseConflict?'!':'×')+'</text>').join('');
  const count=daily.filter(v=>v!==null).length,n=windows.at(-1).filter(v=>v!==null).length;
  return '<article class="chart" data-series="'+key+'"><h3>'+labels[key]+'</h3><p class="chart-value">'+(mean(daily)===null?'—':num(mean(daily)))+' <small>'+unit+' · media conocida</small></p><svg viewBox="0 0 292 205" role="img" aria-label="'+labels[key]+', barras diarias y línea media móvil"><line class="grid" x1="44" x2="274" y1="'+y(0)+'" y2="'+y(0)+'"/><text x="2" y="30">'+num(high)+'</text><text x="2" y="'+y(0)+'">0</text>'+bars+'<g class="rolling">'+pathSegments(rolling,x,y)+'</g>'+partials+gaps+'<text x="44" y="200">'+label(dates[0])+'</text><text x="274" y="200" text-anchor="end">'+label(selected)+'</text></svg><p class="mini">'+count+'/'+period+' días conocidos · media móvil al día: '+(rolling.at(-1)===null?'—':num(rolling.at(-1)))+' '+unit+' · '+n+'/7 días conocidos</p><p class="note">Fuente: '+(['intake','balance'].includes(key)?'Nutrition comparable / canónico':'QA '+(key==='steps'||key==='distance'?'actividad':'gasto'))+'</p></article>';
 }
 $('charts').innerHTML=['expense','intake','balance'].map(plot).join('');
 $('activity-charts').innerHTML=['expense','active','resting','steps','distance'].map(plot).join('');
 const known=dates.filter(s=>get(s).expense!==null).length;
 $('coverage').textContent=known+' de '+period+' días con gasto conocido. Cobertura es disponibilidad, no precisión. Media móvil con denominador visible; huecos sin rellenar y parciales fuera del balance.';
}
function renderCalendar(){
 const current=utc(selected),year=current.getUTCFullYear(),month=current.getUTCMonth(),first=iso(new Date(Date.UTC(year,month,1,12))),days=new Date(Date.UTC(year,month+1,0)).getUTCDate();
 $('month-title').textContent=new Intl.DateTimeFormat('es-MX',{month:'long',year:'numeric',timeZone:'UTC'}).format(current);
 const offset=(utc(first).getUTCDay()+6)%7;
 let content=['L','M','X','J','V','S','D'].map(s=>'<span class="weekday">'+s+'</span>').join('')+'<span></span>'.repeat(offset);
 for(let n=1;n<=days;n++){
  const date=first.slice(0,8)+String(n).padStart(2,'0'),d=get(date),state=d.expenseConflict?'conflict':d.expense!==null?'known':d.steps!==null||d.intake!==null?'partial':'empty',icon={known:'✓',partial:'≈',conflict:'!',empty:'—'}[state];
  content+='<button class="'+state+(date===selected?' selected':'')+'" data-date="'+date+'" aria-label="'+date+', '+{known:'gasto conocido',partial:'dato parcial',conflict:'conflicto pendiente',empty:'sin datos'}[state]+'" aria-pressed="'+(date===selected)+'"><span>'+n+'</span><small>'+icon+'</small></button>';
 }
 $('calendar-grid').innerHTML=content;
 $('calendar-grid').querySelectorAll('button').forEach(b=>b.onclick=()=>setDay(b.dataset.date));
 const d=get(selected);
 $('calendar-detail').innerHTML='<h3>'+label(selected)+'</h3><p>'+(d.expenseConflict?'Gasto en conflicto; balance no calculable.':d.expense!==null?'Gasto conocido: '+num(d.expense)+' kcal.':d.steps!==null?'Actividad registrada; gasto no disponible.':'Sin datos registrados.')+'</p><button class="text-button" id="calendar-open">Abrir resumen del día ↗</button>';
 $('calendar-open').onclick=()=>{changeView('overview',true);};
}
function renderSources(){
 const d=get(selected),conflict=d.expenseConflict;
 if(d.expense===null&&d.steps===null&&!conflict){$('source-content').innerHTML='<article class="panel"><h3>Sin evidencia de energía para esta fecha</h3><p>Consulta otro día o importa un registro. No se generan fuentes ni valores por defecto.</p></article>';return;}
 let body='';
 if(conflict){
  body='<article class="alert"><h3>Gasto total · 1 campo pendiente</h3><p>Ambos valores se conservan. No se elige una fuente automáticamente.</p>';
  if(proposal===null)body+='<form id="resolve-form"><label class="choice"><input type="radio" name="resolution" value="2350" required>Reloj · 2,350 kcal</label><label class="choice"><input type="radio" name="resolution" value="2500">Archivo importado · 2,500 kcal</label><button class="primary" type="submit">Revisar resolución</button></form>';
  else body+='<div class="review-box"><p><b>Revisar: '+num(proposal)+' kcal</b><br>Gasto total del '+label(selected)+'. Las evidencias originales se conservan.</p><label class="choice"><input type="checkbox" id="reviewed">He revisado fecha, campo y cantidad.</label></div><div class="button-row"><button class="secondary" id="back-resolution">Volver</button><button class="primary" id="confirm-resolution" disabled>Confirmar resolución</button></div>';
  body+='</article>';
 }
 body+='<article class="panel"><div class="source-card"><div><h3>Reloj · actividad</h3><p>'+(d.steps!==null?num(d.steps)+' pasos':'Sin pasos para esta fecha')+' · '+(d.distance!==null?(d.distance/1000).toLocaleString('es-MX')+' km':'Distancia desconocida')+'</p></div><span class="pill">Fuente parcial</span><details><summary>Ver procedencia y valores</summary><p>Actividad recibida del dispositivo. '+(conflict?'Gasto original: 2,350 kcal.':'El archivo de actividad no incluye gasto.')+' Ausencia de dato no significa cero.</p></details></div>';
 if(d.expense!==null||conflict)body+='<div class="source-card"><div><h3>Archivo importado · gasto</h3><p>'+(d.expense!==null?num(d.expense)+' kcal':conflict?'2,500 kcal propuestos':'Sin gasto para esta fecha')+' · Original conservado</p></div><span class="pill">'+(conflict?'Pendiente de revisión':'Evidencia conservada')+'</span><details><summary>Ver procedencia y valores</summary><p>Documento original disponible para revisión. Nunca reemplaza los datos de otra fuente.</p></details></div>';
 if(selected==='2040-02-03')body+='<div class="source-card retired"><div><h3>Fuente retirada</h3><p>Fuera de la vista diaria. Original y eventos conservados.</p></div><span class="pill">Sólo historial</span><details><summary>Ver el registro histórico</summary><p>Ejemplo ficticio de una retirada confirmada. No se vuelve a sumar ni se reactiva al importar un archivo anterior.</p></details></div>';
 body+='</article>';
 $('source-content').innerHTML=body.replace('Reloj · actividad',d.importedActivity?'Archivo de actividad QA':'Reloj · actividad').replace('Actividad recibida del dispositivo.',d.importedActivity?'Actividad recibida del archivo QA.':'Actividad recibida del dispositivo.');
 if($('resolve-form'))$('resolve-form').onsubmit=event=>{event.preventDefault();proposal=Number(new FormData(event.target).get('resolution'));renderSources();$('reviewed').focus();};
 if($('reviewed')){$('reviewed').onchange=()=>{$('confirm-resolution').disabled=!$('reviewed').checked;};$('back-resolution').onclick=()=>{proposal=null;renderSources();};$('confirm-resolution').onclick=()=>{data[selected].expense=proposal;data[selected].expenseConflict=false;events.unshift({isoDate:selected,source:'Archivo QA',kind:'review',date:label(selected)+' · Demostración',title:'Resolución revisada',body:'Se conserva cada valor original. Sólo cambia la decisión del día en este ejemplo local.'});proposal=null;render();toast('Resolución simulada. No se guardó en ninguna cuenta.');};}
}
function renderImport(){
 $('steps').querySelectorAll('li').forEach((li,i)=>li.classList.toggle('active',i===importStep));
 const content=[
  '<div class="drop-area"><h3>Registro de actividad</h3><p>JSON o CSV compatible. Revisa fecha, unidades y fuente antes de confirmar.</p><button class="primary" id="import-next">Usar ejemplo ficticio</button></div><p class="note">En este prototipo no se seleccionan ni se leen archivos personales.</p>',
  '<h3>Vista previa · sin cambios guardados</h3><div class="pair"><span>Fecha</span><b>5 feb 2040</b></div><div class="pair"><span>Fuente</span><b>Archivo de actividad QA</b></div><div class="pair"><span>Datos disponibles</span><b>9,000 pasos · 6.6 km</b></div><div class="pair"><span>Gasto</span><b>No incluido</b></div><p class="note">Los pasos no se convierten en gasto. Un dato ausente no borra un valor existente.</p><div class="button-row"><button class="secondary" id="import-back">Volver</button><button class="primary" id="import-next">Revisar campos</button></div>',
  '<h3>Revisión · 2 comprobaciones pendientes</h3><label class="choice"><input type="checkbox" class="import-check">La fecha y la fuente corresponden al registro.</label><label class="choice"><input type="checkbox" class="import-check">Revisé pasos y distancia en metros.</label><p class="note">9,000 pasos · 6,600 m. No hay calorías en este archivo.</p><div class="button-row"><button class="secondary" id="import-back">Volver</button><button class="primary" id="import-next" disabled>Ir a confirmación</button></div>',
  '<h3>Confirmar un registro parcial</h3><p>5 feb 2040 · Actividad QA. Se conservará el original y se registrará una sola evidencia de pasos y distancia.</p><div class="review-box"><b>9,000 pasos · 6.6 km</b><p>El gasto seguirá desconocido y el balance no será calculable.</p></div><div class="button-row"><button class="secondary" id="import-back">Volver</button><button class="primary" id="import-confirm">Confirmar ejemplo</button></div>'
 ];
 $('import-content').innerHTML=content[importStep];
 if($('import-next'))$('import-next').onclick=()=>{importStep++;renderImport();};
 if($('import-back'))$('import-back').onclick=()=>{importStep--;renderImport();};
 document.querySelectorAll('.import-check').forEach(c=>c.onchange=()=>{const pending=[...document.querySelectorAll('.import-check')].filter(c=>!c.checked).length;$('import-next').disabled=pending>0;$('import-content').querySelector('h3').textContent='Revisión · '+pending+' comprobaciones pendientes';});
 if($('import-confirm'))$('import-confirm').onclick=()=>{data['2040-02-05']={importedActivity:true,intake:null,intakeState:'unknown',expense:null,steps:9000,distance:6600,active:null,resting:null};events.unshift({isoDate:'2040-02-05',source:'Archivo QA',kind:'import',date:'5 feb · Demostración',title:'Registro parcial confirmado',body:'Pasos y distancia. Gasto desconocido; no se infieren calorías.'});importStep=0;setDay('2040-02-05');changeView('overview',true);toast('Ejemplo confirmado sólo en este prototipo local.');};
}
function renderHistory(){
 const filter=$('history-filter').value,source=$('history-source').value,from=$('history-from').value,to=$('history-to').value;
 const list=events.filter(e=>(filter==='all'||e.kind===filter)&&(source==='all'||e.source===source)&&(!from||e.isoDate>=from)&&(!to||e.isoDate<=to)),pages=Math.max(1,Math.ceil(list.length/2));
 historyPage=Math.min(historyPage,pages);$('timeline').innerHTML=list.slice((historyPage-1)*2,historyPage*2).map(e=>'<article class="event"><time>'+e.date+'</time><h3>'+e.title+'</h3><p>'+e.body+'</p><p class="note">'+(e.source||'Archivo QA')+' · '+e.kind+'</p></article>').join('')||'<p>Sin eventos para estos filtros.</p>';
 $('history-page').textContent='Página '+historyPage+' de '+pages+' · '+list.length+' eventos';$('history-prev').disabled=historyPage===1;$('history-next').disabled=historyPage===pages;
}
$('history-prev').onclick=()=>{historyPage--;renderHistory();};$('history-next').onclick=()=>{historyPage++;renderHistory();};
for(const id of ['history-filter','history-source','history-from','history-to'])$(id).onchange=()=>{historyPage=1;renderHistory();};
for(const [id,delta] of [['month-prev',-1],['month-next',1]])$(id).onclick=()=>{const d=utc(selected);d.setUTCDate(1);d.setUTCMonth(d.getUTCMonth()+delta);setDay(iso(d));};

document.querySelectorAll('[data-view]').forEach(b=>b.onclick=event=>{event.preventDefault();changeView(b.dataset.view);});
document.querySelectorAll('[data-notice]').forEach(b=>b.onclick=event=>{event.preventDefault();toast(b.dataset.notice);});
document.querySelectorAll('[role=tab]').forEach((b,i,all)=>b.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const n=event.key==='Home'?0:event.key==='End'?all.length-1:(i+(event.key==='ArrowRight'?1:-1)+all.length)%all.length;changeView(all[n].dataset.view,true);}});
$('theme').onclick=()=>{document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark';};
$('day').onchange=()=>{if($('day').value)setDay($('day').value);};$('prev').onclick=()=>setDay(shift(selected,-1));$('next').onclick=()=>setDay(shift(selected,1));$('today').onclick=()=>setDay('2040-02-04');
$('period').onchange=()=>{period=Number($('period').value);renderCharts();};$('conflict-example').onclick=()=>setDay('2040-02-02');
$('reset').onclick=()=>{data=structuredClone(seed);events=structuredClone(initialEvents);importStep=0;setDay('2040-02-03');changeView('overview');toast('Ejemplo restablecido.');};
$('export').onclick=()=>$('export-dialog').showModal();$('close-export').onclick=()=>$('export-dialog').close();
const params=new URLSearchParams(location.search);if(params.get('theme')==='light')document.documentElement.dataset.theme='light';if(/^\d{4}-\d{2}-\d{2}$/.test(params.get('day')||'')&&!Number.isNaN(utc(params.get('day')).valueOf()))selected=params.get('day');$('day').value=selected;
render();changeView(['overview','calendar','sources','import','history'].includes(params.get('view'))?params.get('view'):'overview');
