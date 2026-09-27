const test=require('node:test'),assert=require('node:assert/strict');
const view=require('../../backend/app/static/js/gym_core.js');
test('local catalog galleries stay within the media namespace',()=>{
 const origin='https://tracker.example';
 const url='/exercise-media/free-exercise-db/QA/0?revision=qa';
 assert.deepEqual(view.safeMedia(url,origin),{url:origin+url,external:false});
 assert.equal(view.safeMedia('/exercise-media/../exports/private.png',origin),null);
 const entry=view.catalogEntry({name:'QA',gallery:[url,42,url.replace('/0?','/1?')]});
 assert.equal(entry.gallery.length,2);
});
test('media binds the stable owner identity and asset, not the displayed name',()=>{
 const a=view.catalogEntry({name:'Press banca',media_asset_id:'asset:bench'});
 const b={internal_exercise_id:'fictional-owned-id',media_asset_id:'asset:bench',status:'available',name:'Renamed'};
 assert.equal(view.resolveMedia(b,[a]),a);
 for(const status of ['ambiguous','unresolved','no_media']) assert.equal(view.resolveMedia({...b,status},[a]),null);
 assert.equal(view.resolveMedia({...b,internal_exercise_id:''},[a]),null);
 assert.equal(view.resolveMedia(b,[a,a]),null);
 assert.equal(view.resolveMedia({...b,media_asset_id:'missing'},[a]),null);
});
