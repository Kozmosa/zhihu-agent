// DOM contract checks without a browser. Does not verify rendering or browser behavior.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../src/zhijing/web/settings.html'), 'utf8');
class Element {
  constructor(id) { this.id = id; this.value = ''; this.textContent = ''; this.events = {}; this.children = []; }
  addEventListener(name, callback) { this.events[name] = callback; }
  querySelectorAll() { return []; }
  reportValidity() { return true; }
  setAttribute(name, value) { this[name] = value; }
  replaceChildren() { this.children = []; }
  append(...nodes) { this.children.push(...nodes); }
}
const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element(match[1])]));
let active = 'extractive';
let failure = false;
const requests = [];
const state = () => ({provider: active, base_url: 'https://fixture.test/v1', model: 'fixture', has_api_key: active !== 'extractive', output_format: 'json', timeout: 120, max_tokens: 4096, context_window: 32768, max_input_chars: 120000});
const sandbox = {document: {getElementById: id => {assert(nodes.has(id), `Missing element ${id}`); return nodes.get(id);}, querySelectorAll: () => [], createElement: () => new Element('')}, fetch: async (url, options) => {
  requests.push({url, options});
  if (failure) return {ok: false, json: async () => ({error: {message: 'Connection failed'}})};
  let data;
  if (url === '/health') data = {status: 'ok', version: 'test'};
  else if (url === '/api/v1/settings/model') data = state();
  else if (url === '/api/v1/reading/analyze') data = {mode: active, summary: 'Summary', notice: 'Check source', sections: [{index: 0, heading: 'Heading', text: '<script>unsafe</script>', key_points: ['Point'], guiding_question: 'Question'}]};
  else {const body = JSON.parse(options.body); if(url.endsWith('/apply')) active = body.provider; data = {provider: body.provider, message: 'OK', scope: 'Connection only'};}
  return {ok: true, json: async () => data};
}};
vm.createContext(sandbox);
vm.runInContext(html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1], sandbox);
async function settle() { for(let i=0;i<20;i++) await Promise.resolve(); }
(async () => {
  await settle();
  assert.match(nodes.get('health').textContent, /test/);
  nodes.get('api-key').value = 'synthetic-key';
  await vm.runInContext("configure('test')", sandbox);
  assert.equal(active, 'extractive');
  assert.equal(nodes.get('api-key').value, 'synthetic-key');
  await vm.runInContext("configure('apply')", sandbox);
  assert.equal(active, 'openai');
  assert.equal(nodes.get('api-key').value, '');
  assert.equal(JSON.parse(requests.find(r => r.url.endsWith('/test')).options.body).api_key, 'synthetic-key');
  nodes.get('reading-text').value = 'Some text';
  await nodes.get('read').events.click();
  const result = nodes.get('reading-result').children;
  assert.equal(result[1].children[1].textContent, 'Point');
  assert(result[1].children[3].textContent.includes('<script>unsafe</script>'));
  failure = true;
  await vm.runInContext("configure('apply')", sandbox);
  assert.equal(active, 'openai');
  assert.match(nodes.get('config-result').className, /error/);
  failure = false;
  await nodes.get('offline').events.click();
  assert.equal(active, 'extractive');
  console.log('PASS: initial status, test-only, apply, key clearing, reading output, errors, offline reset. Rendering not verified.');
})().catch(error => {console.error(error); process.exitCode = 1;});
