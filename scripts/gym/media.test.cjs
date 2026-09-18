const test=require('node:test'),assert=require('node:assert/strict');
const view=require('../../backend/app/static/js/gym_core.js');
test('media binds the stable owner identity and asset, not the displayed name',()=>{
 const a=view.catalogEntry({name:'Press banca',media_asset_id:'asset:bench'});
 const b={internal_exercise_id:'fictional-owned-id',media_asset_id:'asset:bench',status:'available',name:'Renamed'};
 assert.equal(view.resolveMedia(b,[a]),a);
 for(const status of ['ambiguous','unresolved','no_media']) assert.equal(view.resolveMedia({...b,status},[a]),null);
 assert.equal(view.resolveMedia({...b,internal_exercise_id:''},[a]),null);
 assert.equal(view.resolveMedia(b,[a,a]),null);
 assert.equal(view.resolveMedia({...b,media_asset_id:'missing'},[a]),null);
});
