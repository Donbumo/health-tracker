/* Presentation only. All values, balances, means and valid-day counts are QA fixtures. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id);let period=7,scenario='complete';
 const fmt=(v,unit=false)=>v===null?'—':new Intl.NumberFormat('es-MX',{maximumFractionDigits:1}).format(v).replace('-', '−')+(unit?' kcal':'');
 const date=s=>{const [y,m,d]=s.split('-').map(Number);return new Intl.DateTimeFormat('es-MX',{day:'numeric',month:'short'}).format(new Date(y,m-1,d,12));};
 const labels={known:'Conocido',zero:'Cero conocido',partial:'Subtotal conocido · parcial',unknown:'Sin dato · no es cero',conflict:'Conflicto pendiente'};
 const current=()=>QA_RANGES[scenario][period];
 const paths=(samples,get,x,y)=>{let segments=[],part=[];samples.forEach((p,i)=>{const v=get(p);if(v===null){if(part.length)segments.push(part.join(' '));part=[];}else part.push(x(i)+','+y(v));});if(part.length)segments.push(part.join(' '));return segments;};
 function chart(data,balance=false){
  const a=data.points,w=balance?520:760,h=240,left=47,right=13,top=20,bottom=204;
  const series=balance?['balance']:['intake','expended'];
  const values=a.flatMap(p=>series.flatMap(k=>[p[k],p.rolling[k]])).filter(v=>v!==null);
  const lo=Math.min(0,...values),hi=Math.max(1,...values),pad=(hi-lo)*.08,min=lo<0?lo-pad:0,max=hi+pad;
  const y=v=>+(bottom-(v-min)/(max-min)*(bottom-top)).toFixed(2),step=(w-left-right)/a.length,x=i=>+(left+step*(i+.5)).toFixed(2),bar=Math.max(.6,Math.min(balance?20:10,step/(balance?1.8:3.1)));
  let s=`<svg class="chart-svg" role="img" aria-labelledby="${balance?'b':'e'}-title ${balance?'b':'e'}-desc" viewBox="0 0 ${w} ${h}"><title id="${balance?'b':'e'}-title">${balance?'Balance diario y su media móvil':'Ingesta, gasto y sus medias móviles'}</title><desc id="${balance?'b':'e'}-desc">Barras de datos conocidos, huecos sin inventar ceros y medias de siete días. Valores y estados completos en la tabla equivalente inferior. Fixture QA.</desc><defs><pattern id="partial-${balance?'balance':'intake'}" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><line x1="0" y1="0" x2="0" y2="5" stroke="var(--intake)" stroke-width="2"/></pattern></defs>`;
  const ticks=balance?[min,0,max]:[0,max/2,max];ticks.forEach(v=>{s+=`<line class="gridline" x1="${left}" y1="${y(v)}" x2="${w-right}" y2="${y(v)}"/><text class="axis-label" text-anchor="end" x="${left-8}" y="${y(v)+4}">${Math.round(v).toLocaleString('es-MX').replace('-','−')}</text>`;});
  a.forEach((p,i)=>series.forEach((k,j)=>{const v=p[k],state=balance?(v===null?'unknown':v===0?'zero':'known'):p.states[k];if(v===null)return;const xx=x(i)+(balance?0:(j?bar/1.6:-bar/1.6));const yy=Math.min(y(0),y(v)),height=Math.max(2,Math.abs(y(0)-y(v)));const fill=balance?'var(--balance)':state==='partial'?'url(#partial-intake)':`var(--${k})`;s+=`<rect x="${xx-bar/2}" y="${yy}" width="${bar}" height="${height}" rx="1" fill="${fill}" ${state==='partial'?'stroke="var(--intake)" stroke-width="1"':''} opacity="${balance ? .65 : .72}"><title>${date(p.date)} · ${k==='intake'?'Ingesta':k==='expended'?'Gasto':'Balance'}: ${fmt(v,true)} · ${labels[state]}</title></rect>`;}));
  series.forEach(k=>paths(a,p=>p.rolling[k],x,y).forEach(path=>s+=`<polyline class="rolling-${k}" points="${path}"/>`));
  const tickIndices=[...new Set([0,Math.floor((a.length-1)/3),Math.floor((a.length-1)*2/3),a.length-1])];tickIndices.forEach(i=>s+=`<text class="axis-label" x="${x(i)}" y="228" text-anchor="${i===0?'start':i===a.length-1?'end':'middle'}">${date(a[i].date)}</text>`);return s+'</svg>';
 }
 function render(){
  const d=current(),p=d.points.at(-1);
  for(const k of ['intake','expended','balance']){
   $(k+'-value').innerHTML=fmt(p[k])+'<small>kcal</small>';
   $(k+'-mean').textContent=fmt(p.rolling[k],true);
   $(k+'-denominator').textContent=p.rollingDays[k]+' de 7 días '+(k==='balance'?'comparables':'válidos');
  }
  $('intake-state').textContent=labels[p.states.intake];$('expended-state').textContent=labels[p.states.expended];
  $('balance-state').textContent=p.balance===null?'No calculable':p.balance<0?'Déficit calculable':p.balance>0?'Superávit calculable':'Balance conocido en cero';
  $('day-status').textContent=p.balance===null?'Datos no comparables':'Día comparable';
  const notes={complete:'Dos valores comparables del mismo día. El signo describe el balance; no es una valoración clínica.',partial:'1.480 kcal es un subtotal conocido. La ingesta parcial no confirma un déficit ni entra en su media de días completos.',conflict:'Hay fuentes de gasto pendientes de resolver. Se conserva la ingesta y el balance queda sin calcular.',unknown:'Este día no tiene datos. No se rellena con ceros ni se extiende una línea entre días ausentes.',zero:'Cero explícito en ingesta y gasto: dato conocido. Se conserva en el balance y en las medias.'};$('day-note').textContent=notes[scenario];
  $('energy-chart').innerHTML=chart(d);$('balance-chart').innerHTML=chart(d,true);
  $('coverage-text').textContent=`${d.coverage.balance} de ${period} días comparables · Ingesta completa ${d.coverage.intake}/${period} · Gasto conocido ${d.coverage.expended}/${period}`;
  $('period-label').textContent=date(d.points[0].date)+' — '+date(p.date)+' · QA 2040';
  $('table-caption').textContent=`${period} días · datos QA ficticios · medias de 7 días con calentamiento previo`;
  $('table-body').innerHTML=d.points.map(q=>`<tr><th scope="row">${date(q.date)}</th><td>${fmt(q.intake)}<small>${labels[q.states.intake]}</small></td><td>${fmt(q.expended)}<small>${labels[q.states.expended]}</small></td><td>${fmt(q.balance)}<small>${q.balance===null?'No comparable':'Comparable'}</small></td>${['intake','expended','balance'].map(k=>`<td>${fmt(q.rolling[k])}<small>${q.rollingDays[k]}/7 ${k==='balance'?'comparables':'válidos'}</small></td>`).join('')}</tr>`).join('');
  document.querySelectorAll('[data-period]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.period)===period)));
  $('update-status').textContent=`Propuesta actualizada: ${period} días, escenario ${$('scenario').selectedOptions[0].textContent}.`;
 }
 document.querySelectorAll('[data-period]').forEach(b=>b.addEventListener('click',()=>{period=Number(b.dataset.period);render();}));
 $('scenario').addEventListener('change',e=>{scenario=e.target.value;render();});
 $('theme').addEventListener('click',()=>{const dark=document.documentElement.dataset.theme==='dark';document.documentElement.dataset.theme=dark?'light':'dark';$('theme').textContent=dark?'Tema oscuro':'Tema claro';});
 document.querySelectorAll('[data-detail]').forEach(b=>b.addEventListener('click',()=>{const k=b.dataset.detail,p=current().points.at(-1);$('detail-title').textContent=k==='intake'?'Nutrición del día · QA':'Energía y procedencia · QA';$('detail-body').innerHTML=`<p><strong>${fmt(p[k],true)}</strong></p><p>${labels[p.states[k]]}</p>`+(k==='intake'?'<ul><li>Comidas registradas con snapshots históricos.</li><li>Los registros legacy conservan su identidad.</li><li>La proyección no se vuelve a sumar como otra comida.</li></ul>':'<ul><li>Gasto total del día canónico.</li><li>Fuentes y decisiones consultables por separado.</li><li>Las evidencias superpuestas no se suman.</li></ul>');$('detail-dialog').showModal();}));
 $('close-dialog').addEventListener('click',()=>$('detail-dialog').close());render();
})();
