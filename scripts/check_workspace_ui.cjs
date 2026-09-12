// Exercises the real UI handlers against an isolated HTTP server, with a minimal DOM.
// Verifies request/response contracts; does not claim browser or visual verification.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const base = process.argv[2];
if (!base) throw new Error('Pass an isolated test server URL, never a user data server.');

(async () => {
  const page = await fetch(base + '/workspace');
  assert.equal(page.status, 200);
  const html = await page.text();
  const nodes = new Map();
  const created = [];
  class Element {
    constructor(tagName) {
      this.tagName = tagName; this.children = []; this.events = {}; this.attributes = {};
      this.value = ''; this.textContent = ''; this.className = ''; this.files = []; created.push(this);
    }
    set id(value) { this._id = value; nodes.set(value, this); }
    get id() { return this._id; }
    addEventListener(name, callback) { this.events[name] = callback; }
    setAttribute(name, value) { this.attributes[name] = value; if(name === 'class') this.className = value; }
    removeAttribute(name) { delete this.attributes[name]; delete this[name]; }
    replaceChildren(...children) { this.children = children; }
    append(...children) { this.children.push(...children); }
    focus() {}
    remove() {}
    click() { if(this.events.click) return this.events.click(); }
  }
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const node = new Element(match[1]); node.id = match[3];
    node.value = match[2].match(/\bvalue="([^"]*)"/)?.[1] || '';
    node.className = match[2].match(/\bclass="([^"]*)"/)?.[1] || '';
    node.checked = /\bchecked\b/.test(match[2]);
  }
  for (const match of html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>\s*<option value="([^"]*)"/g)) nodes.get(match[1]).value = match[2];
  const requests = [], downloads = [], failures = new Map(), fixtures = new Map();
  class LocalURL extends URL {
    static createObjectURL(blob) { downloads.push(blob); return 'blob:fixture'; }
    static revokeObjectURL() {}
  }
  const body = new Element('body');
  const document = {
    currentScript: {dataset: {configToken: html.match(/data-config-token="([^"]+)"/)[1]}}, body,
    getElementById: id => { assert(nodes.has(id), 'Missing element ' + id); return nodes.get(id); },
    createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    querySelectorAll: selector => created.filter(node => selector === 'button' ? node.tagName === 'button' : node.className.split(' ').includes(selector.slice(1))),
  };
  const sandbox = {document, location: {hash: '#cards'}, URL: LocalURL, URLSearchParams, setTimeout: fn => fn(), fetch: async (url, options) => {
    requests.push({url, options});
    if (failures.has(url)) return {ok: false, json: async () => ({error: {message: failures.get(url)}})};
    if (fixtures.has(url)) return {ok: true, json: async () => fixtures.get(url)};
    return fetch(new URL(url, base), options);
  }};
  vm.createContext(sandbox);
  const script = await fetch(base + '/assets/workspace.js');
  assert.equal(script.status, 200);
  vm.runInContext(await script.text(), sandbox);
  const busy = () => vm.runInContext('state.busy', sandbox);
  async function idle() {
    const until = Date.now() + 15000;
    while(busy() && Date.now() < until) await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(busy(), false, 'UI did not finish');
  }
  const get = id => nodes.get(id);
  const submit = async id => { await get(id).events.submit({preventDefault() {}}); await idle(); };
  const click = async id => { await get(id).events.click(); await idle(); };
  const allText = node => [node.textContent, ...node.children.map(allText)].join('\n');
  await idle();
  assert.equal(get('pane-cards').hidden, false, 'A direct capability link must open the requested tab');
  assert.equal(get('pane-reading').hidden, true);
  assert.equal(get('run-reading').disabled, true);
  assert.equal(get('export-apkg').disabled, true);
  assert.match(allText(get('source-list')), /资料库还是空/);

  get('import-title').value = 'UI fixture <script>not code</script>';
  get('import-author-name').value = 'Fixture Author'; get('import-author-id').value = 'ui-author';
  const original = '  Active recall helps learning.\nSpaced repetition supports memory.\n';
  get('import-text').value = original; get('import-topics').value = 'Learning,Memory';
  await submit('import-form');
  assert.match(get('import-status').className, /success/, get('import-status').textContent);
  assert.equal(get('selected-text').textContent, original);
  assert.equal(get('run-reading').disabled, false);
  const primaryId = vm.runInContext('state.selected.id', sandbox);
  assert.equal(get('selected-title').textContent, get('import-title').value);
  assert.equal(get('source-preview-label').textContent, '查看已导入内容');

  const sample = JSON.parse(fs.readFileSync(path.join(__dirname, '../examples/sources.json'), 'utf8'));
  get('import-file').files = [{size: 500, text: async () => JSON.stringify(sample)}];
  await click('import-json');
  assert.match(get('import-status').className, /success/);
  const primary = await (await fetch(base + '/api/v1/sources/' + primaryId)).json();
  sandbox.fixturePrimary = primary;
  vm.runInContext('select(fixturePrimary)', sandbox);

  await submit('reading-form');
  assert.match(get('reading-status').className, /success/);
  assert(allText(get('reading-result')).includes('Active recall'));
  get('author-question').value = 'How does active recall help learning?';
  await submit('author-form');
  assert.match(get('author-status').className, /success/);
  assert(allText(get('author-result')).includes('Fixture Author') || allText(get('author-result')).includes('ui-author'));
  const authorBody = JSON.parse(requests.find(row => row.url === '/api/v1/author/ask').options.body);
  assert.equal(authorBody.author_id, 'ui-author'); assert.equal(authorBody.primary_source_id, primaryId);

  await submit('cards-form');
  assert.match(get('cards-status').className, /success/);
  assert.equal(get('export-apkg').disabled, false);
  await click('export-tsv'); await click('export-apkg');
  assert.equal(downloads.length, 2);
  assert((await downloads[0].text()).includes('Active recall'));
  assert.equal(Buffer.from(await downloads[1].arrayBuffer()).subarray(0, 2).toString(), 'PK');

  get('fact-claims').value = 'Active recall helps learning.';
  await submit('facts-form');
  assert.match(get('facts-status').className, /success/);
  assert(allText(get('facts-result')).length > 50);
  const factBody = JSON.parse(requests.find(row => row.url === '/api/v1/facts/review').options.body);
  assert.deepEqual(factBody.exclude_source_ids, [primaryId]);
  get('fact-claims').value = Array(21).fill('Too many claims').join('\n');
  const previousCalls = requests.filter(row => row.url === '/api/v1/facts/review').length;
  await submit('facts-form');
  assert.match(get('facts-status').className, /error/);
  assert.equal(requests.filter(row => row.url === '/api/v1/facts/review').length, previousCalls);

  await submit('knowledge-form');
  assert.match(get('knowledge-status').className, /success/);
  assert(created.some(node => node.tagName === 'svg'));
  const picker = get('graph-node-picker'); picker.value = '0'; picker.events.change();
  assert(created.some(node => node.className === 'graph-detail' && node.children.length));
  const svgNode = created.find(node => node.className === 'graph-node');
  svgNode.events.keydown({key: 'Enter', preventDefault() {}});

  failures.set('/api/v1/cards/generate', 'Fixture upstream failure');
  await submit('cards-form');
  assert.match(get('cards-status').className, /error/);
  assert.equal(get('export-apkg').disabled, true);
  failures.clear();
  const batches = Array.from({length: 20}, (_, i) => ({title: 'Page ' + i, author_id: 'pagination', author_name: 'Paging', text: 'Page body ' + i}));
  get('import-file').files = [{size: 1000, text: async () => JSON.stringify({items: batches})}];
  await click('import-json');
  assert.equal(get('next-page').disabled, false);
  await click('next-page'); assert.equal(get('prev-page').disabled, false);
  get('source-filter').value = 'no-such-author'; await submit('source-filter-form');
  assert.match(allText(get('source-list')), /没有资料/);
  assert.equal(get('next-page').disabled, true);
  assert.equal(get('prev-page').disabled, true);
  await click('tab-author'); assert.equal(get('pane-author').hidden, false);
  assert.equal(get('pane-reading').hidden, true);
  get('tab-author').events.keydown({key: 'ArrowRight', preventDefault() {}});
  assert.equal(get('pane-cards').hidden, false);
  const unsafe = new Element('a'); sandbox.unsafeLink = unsafe;
  vm.runInContext("safeLink(unsafeLink, 'javascript:alert(1)')", sandbox);
  assert.equal(unsafe.hidden, true);

  // Only Zhihu upstream responses are simulated; import, storage, and author scope use
  // the real isolated local service. No secret or request is sent to the public API.
  fixtures.set('/api/v1/zhihu/status', {configured: false});
  await click('open-zhihu');
  assert.equal(get('zhihu-panel').hidden, false);
  assert.equal(get('zhihu-config-panel').open, true);
  assert.equal(get('run-zhihu-search').disabled, true);
  assert.match(get('zhihu-config-state').textContent, /尚未配置/);
  get('zhihu-query').value = '学习方法';
  await submit('zhihu-search-form');
  assert.match(get('zhihu-status').textContent, /先配置/);
  assert.equal(requests.filter(row => row.url === '/api/v1/zhihu/search').length, 0);
  await submit('zhihu-config-form');
  assert.match(get('zhihu-config-status').className, /error/);
  assert.equal(requests.filter(row => row.url === '/api/v1/zhihu/config').length, 0);
  fixtures.set('/api/v1/zhihu/config', {configured: true});
  get('zhihu-secret').value = 'fake-local-fixture-secret';
  await submit('zhihu-config-form');
  assert.match(get('zhihu-config-status').className, /success/);
  assert.equal(get('zhihu-secret').value, '');
  assert.equal(get('run-zhihu-search').disabled, false);
  const configRequest = requests.find(row => row.url === '/api/v1/zhihu/config');
  assert.equal(JSON.parse(configRequest.options.body).access_secret, 'fake-local-fixture-secret');
  assert.equal(configRequest.options.headers['X-Zhijing-Token'], document.currentScript.dataset.configToken);
  const zhihuItems = [1, 2].map(id => ({
    title: '摘要 <script>not code</script> ' + id, author_name: '同名作者',
    author_id: 'zhihu-content:answer:' + id, text: '摘要内容 ' + id + '，不是完整正文。',
    url: 'https://www.zhihu.com/question/1/answer/' + id,
    topics: [], origin: 'zhihu', content_extent: 'excerpt', provenance: null,
  }));
  fixtures.set('/api/v1/zhihu/search', {items: zhihuItems, has_more: false, skipped_count: 1, empty_reason: ''});
  get('zhihu-count').value = '3';
  await submit('zhihu-search-form');
  assert.match(get('zhihu-status').className, /success/);
  assert.match(get('zhihu-status').textContent, /略过 1/);
  assert.equal(get('zhihu-results').children.length, 2);
  assert.match(allText(get('zhihu-results')), /摘要 <script>not code<\/script> 1/);
  assert.equal(get('zhihu-results').children[0].children[1].tagName, 'h3');
  const searchRequest = requests.find(row => row.url === '/api/v1/zhihu/search');
  assert.deepEqual(JSON.parse(searchRequest.options.body), {query: '学习方法', count: 3});
  assert.equal(searchRequest.options.headers['X-Zhijing-Token'], document.currentScript.dataset.configToken);
  const firstImport = vm.runInContext('state.zhihuResults[0].button', sandbox);
  await firstImport.click(); await idle();
  assert.match(get('zhihu-status').className, /success/, get('zhihu-status').textContent);
  assert.equal(firstImport.disabled, true);
  assert.equal(firstImport.textContent, '已导入');
  assert.equal(get('source-preview-label').textContent, '查看已导入摘要');
  assert.equal(get('selected-extent').hidden, false);
  assert.match(get('selected-extent').textContent, /不包含完整正文/);
  assert.match(get('author-scope-notice').textContent, /不合并同名作者/);
  assert.doesNotMatch(get('selected-meta').textContent, /作者 ID/);
  get('source-filter').value = 'zhihu-content:answer:1';
  await submit('source-filter-form');
  assert.match(allText(get('source-list')), /摘要/);
  const importedCount = requests.filter(row => row.url === '/api/v1/sources/import').length;
  await click('reload-sources');
  assert.equal(firstImport.disabled, true, 'Unrelated jobs must not reenable an imported result');
  await firstImport.click(); await idle();
  assert.equal(requests.filter(row => row.url === '/api/v1/sources/import').length, importedCount);
  const secondImport = vm.runInContext('state.zhihuResults[1].button', sandbox);
  await secondImport.click(); await idle();
  assert.equal(vm.runInContext('state.selected.author_id', sandbox), 'zhihu-content:answer:2');
  get('author-question').value = '这条摘要说了什么？';
  await submit('author-form');
  assert.match(get('author-status').className, /success/);
  const scopedBody = JSON.parse(requests.filter(row => row.url === '/api/v1/author/ask').at(-1).options.body);
  assert.equal(scopedBody.author_id, 'zhihu-content:answer:2');
  const searches = requests.filter(row => row.url === '/api/v1/zhihu/search').length;
  get('zhihu-count').value = '11';
  await submit('zhihu-search-form');
  assert.match(get('zhihu-status').className, /error/);
  assert.equal(requests.filter(row => row.url === '/api/v1/zhihu/search').length, searches);
  get('zhihu-count').value = '3';
  failures.set('/api/v1/zhihu/search', '知乎搜索额度已用完');
  await submit('zhihu-search-form');
  assert.match(get('zhihu-status').textContent, /额度已用完/);
  assert.equal(get('zhihu-results').children.length, 0, 'A failed search must clear stale results');
  failures.delete('/api/v1/zhihu/search');
  fixtures.set('/api/v1/zhihu/search', {items: [], has_more: false, skipped_count: 0, empty_reason: '没有匹配资料'});
  await submit('zhihu-search-form');
  assert.equal(get('zhihu-status').textContent, '没有匹配资料');
  assert.match(allText(get('zhihu-results')), /没有可导入/);
  assert.equal(vm.runInContext('state.zhihuResults.length', sandbox), 0);
  const selectedBeforeClear = vm.runInContext('state.selected.id', sandbox);
  fixtures.set('/api/v1/zhihu/config', {configured: false});
  await click('clear-zhihu-secret');
  assert.match(get('zhihu-config-status').textContent, /凭证已清除/);
  assert.equal(get('run-zhihu-search').disabled, true);
  assert.equal(get('clear-zhihu-secret').disabled, true);
  assert.equal(vm.runInContext('state.selected.id', sandbox), selectedBeforeClear);
  assert.equal(JSON.parse(requests.filter(row => row.url === '/api/v1/zhihu/config').at(-1).options.body).access_secret, '');
  get('zhihu-secret').value = 'unsaved-fake-secret';
  await click('close-zhihu');
  assert.equal(get('zhihu-secret').value, '');
  assert.equal(get('zhihu-panel').hidden, true);
  console.log(JSON.stringify({passed: true, scope: 'UI handlers plus real isolated HTTP; Zhihu responses mocked; no browser rendering', cases: ['empty library', 'manual and JSON import', 'source fidelity', 'reading', 'author scope and citations', 'cards', 'TSV and APKG downloads', 'fact exclusion and validation', 'graph interaction', 'failure clears stale exports', 'pagination and filters', 'keyboard tabs', 'unsafe URL rejected', 'Zhihu credential gating and clearing', 'Zhihu search request and text rendering', 'excerpt import and content-scoped author identity', 'imported button stays disabled', 'Zhihu count validation and upstream error', 'empty search results']}));
})().catch(error => { console.error(error); process.exitCode = 1; });
