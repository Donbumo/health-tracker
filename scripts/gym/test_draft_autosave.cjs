// Unit tests for the autosave state machine; no browser or real user data.
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../backend/app/static/js/gym_draft_save.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

function setup(responses) {
  const element = () => ({hidden:true, disabled:false, textContent:'', value:'', events:{},
    addEventListener(name, fn) { this.events[name] = fn; }, scrollIntoView() { this.scrolled = true; }});
  const nodes = Object.fromEntries(['draft-save-panel','draft-save-status','draft-save-error','draft-save-retry','draft-save-reload','draft-unresolved','draft-confirm-guidance'].map(id => [id,element()]));
  nodes['draft-save-panel'].dataset = {url:'/qa/save', revision:'1',ready:'true',csrf:'fictional-csrf'};
  const select = element(), confirm = element(), revision = element(), token = element();
  const window = {events:{},addEventListener(name, fn) { this.events[name] = fn; }};
  const document = {events:{},getElementById:id => nodes[id],
    querySelector:selector => selector === '#gym-confirm button' ? confirm : selector === '#gym-confirm input[name=token]' ? token : null,
    querySelectorAll:selector => selector === 'input[name=revision]' ? [revision] : selector === '.gym form' ? [] : [select,confirm],
    addEventListener(name,fn) { this.events[name] = fn; }};
  const calls = [];
  vm.runInNewContext(source, {document,window,setTimeout,clearTimeout,AbortController,Error,TypeError,
    fetch:async (url,options) => {
      calls.push(JSON.parse(options.body));
      const result=responses.shift();
      if (result instanceof Error) throw result;
      return {ok:true,status:200,redirected:false,json:async()=>result,...result?.response};
    }});
  return {nodes,select,confirm,revision,token,window,document,calls};
}
const ack = revision => ({revision,ready:true,saved_at:'2026-09-28T12:00:00Z',token:'fictional-decision',unresolved_count:0});
const choice = {action:'mapping',day:0,exercise:0,value:'new'};

test('acknowledges a saved revision before enabling confirmation', async () => {
  const ui=setup([ack(2)]);
  ui.window.gymDraftSave(choice);
  assert.equal(ui.select.disabled,true);
  assert.equal(ui.confirm.disabled,true);
  await flush();
  assert.equal(ui.confirm.disabled,false);
  assert.equal(ui.revision.value,2);
  assert.equal(ui.token.value,'fictional-decision');
  assert.match(ui.nodes['draft-save-status'].textContent,/^Guardado/);
});

test('network failure blocks further choices and retry preserves the pending selection', async () => {
  const ui=setup([new TypeError('network unavailable'),ack(2)]);
  ui.window.gymDraftSave(choice);await flush();
  assert.equal(ui.select.disabled,true);
  assert.equal(ui.nodes['draft-save-retry'].hidden,false);
  assert.equal(ui.nodes['draft-save-error'].scrolled,true);
  ui.window.gymDraftSave({...choice,value:'none'});
  assert.equal(ui.calls.length,1);
  ui.nodes['draft-save-retry'].events.click();await flush();
  assert.deepEqual(ui.calls[1],{revision:1,change:choice});
  assert.equal(ui.select.disabled,false);
});

test('stale revision is never retried as an overwrite and explicit reload is not trapped', async () => {
  const ui=setup([{error:'QA stale revision',response:{ok:false,status:409}}]);
  ui.window.gymDraftSave(choice);await flush();
  assert.equal(ui.nodes['draft-save-reload'].hidden,false);
  assert.equal(ui.nodes['draft-save-retry'].hidden,true);
  assert.equal(ui.confirm.disabled,true);
  let warned=false;
  ui.window.events.beforeunload({preventDefault(){warned=true;}});
  assert.equal(warned,true);
  ui.nodes['draft-save-reload'].events.click();warned=false;
  ui.window.events.beforeunload({preventDefault(){warned=true;}});
  assert.equal(warned,false);
});

test('login redirect or malformed response never marks data saved', async () => {
  for (const result of [{response:{redirected:true}},{}]) {
    const ui=setup([result]);ui.window.gymDraftSave(choice);await flush();
    assert.equal(ui.confirm.disabled,true);
    assert.equal(ui.nodes['draft-save-reload'].hidden,false);
    assert.equal(ui.nodes['draft-save-status'].textContent,'Cambios sin guardar');
    assert.equal(ui.revision.value,'');
  }
});
