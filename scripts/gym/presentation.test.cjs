const {test} = require('node:test');
const assert = require('node:assert/strict');
const view = require('../../backend/app/static/js/gym_core.js');
const target = {reps_min:6, reps_max:8, rir:2};
const set = (reps, rir=2, load=80, prescription=target) => ({target:prescription, actual:{load,reps,rir,mode:'direct_total'}});

test('suggestions, missing efforts and unfinished exercises never qualify for progression', () => {
  const pending = {target,suggestion:{load:80,reps:8,rir:2}};
  assert.equal(view.range([pending]).state,'empty');
  assert.equal(view.session([{sets:[pending]}]).completed,0);
  assert.equal(view.session([{sets:[pending]}]).volume,null);
  assert.equal(view.range([set(8),pending]).ready,false);
  assert.equal(view.range([set(8,null)]).ready,false);
  assert.equal(view.range([set(8,2,0)]).ready,false);
  assert.equal(view.range([set(8,2,80,{reps:8})]).ready,false);
});
test('range uses every confirmed set and requires explicit effort at the top', () => {
  assert.equal(view.range([set(5),set(8)]).state,'below');
  assert.equal(view.range([set(7)]).state,'within');
  assert.equal(view.range([set(8,1)]).state,'top');
  assert.equal(view.range([set(9,1)]).state,'above');
  assert.equal(view.range([set(8),set(9)]).state,'ready');
  assert.equal(view.range([set(8,0,80,{reps:8,rir:0})]).ready,true);
  assert.equal(view.range([{target:{reps:8,rpe:8},actual:{load:50,reps:8,rpe:8}}]).ready,true);
  assert.equal(view.range([{target:{reps:8,rpe:8},actual:{load:50,reps:8,rpe:9}}]).ready,false);
});
test('bounds, zero effort and missing values stay distinct', () => {
  assert.equal(view.number(' '),null);
  assert.equal(view.number('0'),0);
  assert.equal(view.number(false),null);
  assert.equal(view.bounds({reps_min:8,reps_max:6}),null);
  assert.equal(view.bounds({reps_min:6}),null);
  assert.deepEqual(view.bounds({reps:8}),{min:8,max:8});
});
test('partial volume excludes noncomparable load modes without losing completed sets', () => {
  const result=view.session([{sets:[set(8),{target,actual:{mode:'bodyweight',reps:8,load:80}}]},{sets:[{target}]}]);
  assert.equal(result.completed,2); assert.equal(result.finished,1);
  assert.equal(result.remaining,1); assert.equal(result.volume,640); assert.equal(result.partial,true);
  assert.equal(result.percentage,67); assert.equal(result.categories.pending,1);
  assert.equal(view.range([{target,actual:{mode:'assistance',load:10,reps:8,rir:2}}]).ready,false);
  assert.equal(view.session([{sets:[set(10,1)]}]).categories.within,0);
  assert.equal(view.session([{sets:[set(10,1)]}]).categories.above,1);
});
test('media allowlist rejects executable URLs and credential-bearing or private app paths', () => {
  const origin='https://tracker.example';
  for (const url of ['javascript:alert(1)','data:image/svg+xml,hi','http://external.example/image.png','https://user:pass@external.example/x','/exports/private.png','/static/../exports/private.png']) assert.equal(view.safeMedia(url,origin),null);
  assert.deepEqual(view.safeMedia('/static/images/demo.svg',origin),{url:origin+'/static/images/demo.svg',external:false});
  assert.deepEqual(view.safeMedia('https://catalog.example/demo.gif',origin),{url:'https://catalog.example/demo.gif',external:true});
});
test('neutral media contract preserves supported fields only', () => {
  const entry=view.catalogEntry({source:'qa',external_exercise_id:'example',name:'Press',aliases:['  PRESS  ',3],primary_muscles:['Pecho'],instructions:['Referencia'],media_type:'video',user_id:99});
  assert.equal(entry.user_id,undefined); assert.equal(entry.media_type,'video');
  assert.deepEqual(entry.aliases,['  PRESS  ']); assert.equal(view.nameKey(entry.aliases[0]),'press');
  assert.equal(view.catalogEntry(null),null);
});
