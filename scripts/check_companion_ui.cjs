// Contract and race checks for the independent companion handlers. No network or real data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'src/zhijing/web/companion.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'src/zhijing/web/companion.js'), 'utf8');
const toolNames = ['reading', 'author', 'cards', 'facts', 'knowledge'];
const token = 'synthetic-companion-session';
const storageKey = 'zhijing.companion.source.' + token;
const cases = [];
const copy = value => JSON.parse(JSON.stringify(value));

function source(index) {
  return {id: 'source-' + index, title: '资料 ' + index, author_id: 'author-' + index,
    author_name: '同一个昵称', text: '  完整保留的合成资料 ' + index + '\nActive recall helps learning.\n',
    origin: 'manual', content_extent: 'unknown'};
}

function environment({savedId, storageFails = false} = {}) {
  const nodes = new Map(), created = [], requests = [], downloads = [], gates = new Map(), failures = new Map();
  const stored = new Map(savedId ? [[storageKey, savedId]] : []);
  const sources = Array.from({length: 25}, (_, index) => source(index + 1));
  sources[1].content_extent = 'excerpt';
  sources[1].origin = 'zhihu';
  let inflight = 0, sequence = 0;
  class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.events = {}; this.attributes = {}; this.value = ''; this.textContent = ''; created.push(this); }
    set id(value) { this._id = value; nodes.set(value, this); }
    get id() { return this._id; }
    register() { if (this.id) nodes.set(this.id, this); this.children.forEach(item => item.register()); }
    unregister() { if (this.id) nodes.delete(this.id); this.children.forEach(item => item.unregister()); }
    append(...items) { for (const item of items) { item.parentNode = this; item.register(); this.children.push(item); } }
    replaceChildren(...items) { this.children.forEach(item => item.unregister()); this.children = []; this.textContent = ''; this.append(...items); }
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(item => item !== this); this.unregister(); }
    addEventListener(name, callback) { this.events[name] = callback; }
    setAttribute(name, value) { this.attributes[name] = value; }
    focus() { document.activeElement = this; }
    click() { if (this.tagName === 'a') downloads.push({href: this.href, name: this.download}); return this.events.click?.(); }
    set innerHTML(_) { throw new Error('Source text must never become HTML'); }
  }
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const item = new Element(match[1]); item.id = match[3];
    item.hidden = /\bhidden\b/.test(match[2]); item.open = /\bopen\b/.test(match[2]);
  }
  const body = new Element('body');
  const documentListeners = new Map();
  const document = {body, currentScript: {dataset: {configToken: token}},
    addEventListener: (name, listener) => { if (!documentListeners.has(name)) documentListeners.set(name, []); documentListeners.get(name).push(listener); },
    dispatchEvent: event => Promise.all((documentListeners.get(event.type) || []).map(listener => listener(event))),
    getElementById: id => nodes.get(id) || null, createElement: tag => new Element(tag)};
  const sessionStorage = {
    getItem: key => { if (storageFails) throw Error('disabled'); return stored.get(key) || null; },
    setItem: (key, value) => { if (storageFails) throw Error('disabled'); stored.set(key, value); },
    removeItem: key => { if (storageFails) throw Error('disabled'); stored.delete(key); },
  };
  const evidence = {source_id: 'source-1', author_id: 'author-1', title: '<img onerror=bad()> 原文',
    chunk_index: 0, excerpt: '<script>不可执行的原文</script>', url: 'javascript:bad()'};
  const fixture = (url, body) => {
    if (url.pathname === '/api/v1/sources' && !body) return sources.slice(Number(url.searchParams.get('offset') || 0), Number(url.searchParams.get('offset') || 0) + Number(url.searchParams.get('limit')));
    if (url.pathname.startsWith('/api/v1/sources/') && url.pathname !== '/api/v1/sources/import') {
      const found = sources.find(item => item.id === decodeURIComponent(url.pathname.split('/').at(-1)));
      if (!found) throw Object.assign(Error('missing'), {httpStatus: 404});
      return found;
    }
    if (url.pathname === '/api/v1/sources/import') {
      const items = body.items.map(item => ({...item, id: 'import-' + (++sequence), content_extent: 'unknown'}));
      sources.unshift(...items); return items;
    }
    if (url.pathname === '/api/v1/reading/analyze') return {summary: '摘要 ' + body.source_id,
      notice: '当前采用分句与首句摘录，未进行语义推理；导读问题为模板。',
      sections: [{index: 0, heading: '方法', text: evidence.excerpt, key_points: ['主动回忆'], guiding_question: '如何使用？'}]};
    if (url.pathname === '/api/v1/author/ask') return {answer: '依据 ' + body.primary_source_id + ' ' + '合成回答。'.repeat(160),
      citations: [evidence, {...evidence, url: 'https://example.org/source'}],
      identity_notice: '助手不代表作者本人。', citation_notice: '回答仅依据已导入资料。'};
    if (url.pathname === '/api/v1/cards/generate') return {notice: '卡片由原文摘录整理，请核对原文。',
      cards: [1, 2, 3].map(index => ({front: '问题 ' + index, back: '答案 ' + index, evidence_excerpt: '原文 ' + index}))};
    if (url.pathname === '/api/v1/facts/review') return {scope: '仅检查已导入资料，不等同于客观事实判定。', analysis_notice: '当前采用规则整理。',
      reviews: body.claims.map(claim => ({claim, status: 'related_evidence', explanation: '存在相关资料，仍需核对。', evidence: [evidence]}))};
    if (url.pathname === '/api/v1/knowledge-map') return {classification: '主题分类关系，并非事实证明。', analysis_notice: '按资料主题整理。', truncated: true,
      total_sources: 25, nodes: Array.from({length: 8}, (_, index) => ({id: 'n' + index, data: {label: '概念 ' + index, kind: 'topic', description: '原文概念', evidence: [evidence]}})),
      edges: [{source: 'n0', target: 'n1', label: '相关', data: {explanation: '同一资料提及', evidence: [evidence]}}]};
    throw Error('Unexpected endpoint: ' + url.pathname);
  };
  class TestURL extends URL {
    static createObjectURL(blob) { downloads.push({blob}); return 'blob:companion-fixture'; }
    static revokeObjectURL() {}
  }
  const sandbox = {document, sessionStorage, URL: TestURL, URLSearchParams,
    crypto: {randomUUID: () => 'synthetic-' + (++sequence)}, setTimeout: callback => callback(),
    fetch: async (relative, options) => {
      assert(relative.startsWith('/api/v1/'), 'Only local application endpoints are permitted');
      const url = new URL(relative, 'http://127.0.0.1');
      const body = options.body ? JSON.parse(options.body) : undefined;
      requests.push({path: url.pathname, relative, options, body});
      if (body) assert.equal(options.headers['X-Zhijing-Token'], token);
      const gate = gates.get(url.pathname), failure = failures.get(url.pathname);
      gates.delete(url.pathname); failures.delete(url.pathname);
      inflight++;
      try {
        if (gate) await gate;
        if (failure) return {ok: false, status: 503, json: async () => ({error: {code: failure, message: 'MUST NOT DISPLAY secret-fixture'}})};
        if (url.pathname === '/api/v1/cards/export/tsv') return {ok: true, blob: async () => new Blob(['front\tback'])};
        try { return {ok: true, json: async () => copy(fixture(url, body))}; }
        catch (error) { if (!error.httpStatus) throw error; return {ok: false, status: error.httpStatus, json: async () => ({})}; }
      } finally { inflight--; }
    }};
  vm.runInNewContext(script, sandbox);
  const get = id => { assert(nodes.has(id), 'Missing fixture element: ' + id); return nodes.get(id); };
  const text = item => [item.textContent || '', ...item.children.map(text)].join('\n');
  const idle = async () => { for (let count = 0; count < 100; count++) { await new Promise(resolve => setTimeout(resolve, 1)); if (!inflight) { await Promise.resolve(); return; } } throw Error('Fixture did not settle'); };
  const event = (id, name, fields = {}) => get(id).events[name]({preventDefault() {}, ...fields});
  const click = async id => { await event(id, 'click'); await idle(); };
  const submit = async tool => { await event('tool-form-' + tool, 'submit'); await idle(); };
  const select = async id => { get('companion-source').value = id; await event('companion-source', 'change'); };
  const defer = pathname => { let resolve; gates.set(pathname, new Promise(done => { resolve = done; })); return resolve; };
  return {nodes, get, text, requests, downloads, sources, stored, failures, created, idle, event, click, submit, select, defer, document};
}

(async () => {
  assert(!html.includes('/assets/workspace.js'), 'The companion must not load workspace handlers');
  const ui = environment(); await ui.idle();
  assert.equal(ui.get('tool-pane-author').hidden, false);
  for (const tool of toolNames) assert.equal(ui.get('tool-run-' + tool).disabled, true);
  assert(!ui.requests.some(item => item.body));
  assert.equal(ui.get('companion-source').children.length, 21);
  await ui.click('companion-source-next');
  assert.equal(ui.get('companion-source').children.length, 6);
  await ui.select('source-25');
  await ui.click('companion-source-prev');
  assert.equal(ui.get('companion-source').value, 'source-25');
  assert.equal(ui.stored.get(storageKey), 'source-25');
  cases.push('default author, source gating, complete pagination and ID-only selection');

  await ui.select('source-2');
  assert.match(ui.text(ui.get('companion-source-note')), /摘要.*不包含完整正文/);
  await ui.submit('reading');
  assert.match(ui.text(ui.get('tool-result-reading')), /未进行语义推理/);
  assert.match(ui.text(ui.get('tool-result-reading')), /不可执行的原文/);
  assert(!ui.created.some(item => item.tagName === 'script'));
  cases.push('excerpt and reading evidence preserved as text');

  const before = ui.requests.length;
  await ui.submit('author'); assert.equal(ui.requests.length, before);
  ui.get('tool-question').value = '方法有什么依据？';
  const releaseAnswer = ui.defer('/api/v1/author/ask');
  const pendingAnswer = ui.event('tool-form-author', 'submit');
  await ui.event('tool-form-author', 'submit');
  assert.equal(ui.requests.filter(item => item.path === '/api/v1/author/ask').length, 1);
  releaseAnswer(); await pendingAnswer; await ui.idle();
  const answerRequest = ui.requests.find(item => item.path === '/api/v1/author/ask').body;
  assert.equal(answerRequest.primary_source_id, 'source-2');
  assert.equal(answerRequest.author_id, 'author-2');
  assert.match(ui.text(ui.get('tool-result-author')), /不代表作者本人/);
  assert.equal(ui.get('tool-result-author').children.at(-1).children[0].textContent, '回答与引用说明');
  assert.match(ui.text(ui.get('tool-result-author')), /展开完整内容/);
  assert(!ui.created.some(item => item.href?.startsWith('javascript:')));
  assert(ui.created.some(item => item.href === 'https://example.org/source' && item.rel === 'noopener noreferrer'));
  cases.push('question validation, duplicate guard, real citation fields and safe links');

  await ui.submit('cards');
  assert.equal(ui.requests.find(item => item.path === '/api/v1/cards/generate').body.count, 3);
  assert(!ui.text(ui.get('tool-card-face')).includes('答案 1'));
  await ui.click('tool-card-reveal'); assert.match(ui.text(ui.get('tool-card-face')), /答案 1/);
  ui.get('tool-result-cards').scrollTop = 200;
  await ui.click('tool-card-next'); assert(!ui.text(ui.get('tool-card-face')).includes('答案'));
  assert.equal(ui.get('tool-result-cards').scrollTop, 0);
  assert.equal(ui.get('tool-card-counter').textContent, '2 / 3');
  await ui.click('tool-card-export');
  assert.equal(ui.downloads.at(-1).name, 'zhijing-cards.tsv');
  assert.equal(ui.requests.find(item => item.path.endsWith('/export/tsv')).body.cards.length, 3);
  assert.match(ui.get('tool-status-cards').textContent, /保存窗口/);
  ui.failures.set('/api/v1/cards/generate', 'model_unavailable'); await ui.submit('cards');
  assert.equal(ui.nodes.has('tool-card-export'), false);
  assert(!ui.get('tool-status-cards').textContent.includes('secret-fixture'));
  cases.push('three-card navigation, reveal, TSV request and failed regeneration clears exports');

  ui.get('tool-claims').value = '主张一\n主张二'; await ui.submit('facts');
  const factRequest = ui.requests.find(item => item.path === '/api/v1/facts/review').body;
  assert.deepEqual(factRequest.exclude_source_ids, ['source-2']);
  assert(!('author_id' in factRequest));
  assert.match(ui.text(ui.get('tool-result-facts')), /未联网.*客观事实/);
  const factsBefore = ui.requests.length;
  ui.get('tool-claims').value = '1\n2\n3\n4\n5\n6'; await ui.submit('facts');
  assert.equal(ui.requests.length, factsBefore);
  await ui.submit('knowledge');
  const mapRequest = new URL(ui.requests.find(item => item.path === '/api/v1/knowledge-map').relative, 'http://127.0.0.1');
  assert.equal(mapRequest.searchParams.get('limit'), '20');
  assert.equal(mapRequest.searchParams.get('author_id'), 'author-2');
  assert.match(ui.text(ui.get('tool-result-knowledge')), /未覆盖全部/);
  assert.match(ui.text(ui.get('tool-result-knowledge')), /展开其余 3 个节点/);
  assert(!ui.created.some(item => item.tagName === 'svg'));
  cases.push('facts exclude current across full library; compact author map and truncation');

  ui.get('companion-import-text').value = '  ' + '仅正文'.repeat(12) + '\n第二行保留。';
  await ui.event('companion-import-form', 'submit'); await ui.idle();
  const quickImport = ui.requests.filter(item => item.path === '/api/v1/sources/import').at(-1).body.items[0];
  assert.equal(quickImport.title, '仅正文'.repeat(10));
  assert.equal(quickImport.author_name, '未署名');
  assert.equal(quickImport.text, ui.get('companion-import-text').value);
  const quickCount = ui.requests.filter(item => item.path === '/api/v1/sources/import').length;
  ui.get('companion-import-text').value = 'x'.repeat(100001);
  await ui.event('companion-import-form', 'submit');
  assert.equal(ui.requests.filter(item => item.path === '/api/v1/sources/import').length, quickCount);
  cases.push('body-only paste derives a short title and unnamed author; oversized paste rejected');

  const importText = '  用户粘贴的正文\n保留空白。  ';
  ui.get('companion-import-title').value = '资料标题';
  ui.get('companion-import-name').value = '相同昵称';
  ui.get('companion-import-text').value = importText;
  await ui.event('companion-import-form', 'submit'); await ui.idle();
  const firstImport = ui.requests.filter(item => item.path === '/api/v1/sources/import').at(-1).body.items[0];
  assert.equal(firstImport.text, importText);
  assert.equal(ui.get('companion-import').open, false);
  await ui.event('companion-import-form', 'submit'); await ui.idle();
  const secondImport = ui.requests.filter(item => item.path === '/api/v1/sources/import').at(-1).body.items[0];
  assert.notEqual(firstImport.author_id, secondImport.author_id);
  assert.equal(ui.get('tool-result-reading').children.length, 0);
  cases.push('paste fidelity and independent author groups for repeated nicknames');

  await ui.click('companion-source-prev'); await ui.select('source-1');
  let release = ui.defer('/api/v1/reading/analyze');
  let old = ui.event('tool-form-reading', 'submit');
  await ui.select('source-2'); await ui.select('source-1');
  release(); await old;
  assert.equal(ui.get('tool-result-reading').children.length, 0);
  release = ui.defer('/api/v1/reading/analyze');
  ui.failures.set('/api/v1/reading/analyze', 'model_unavailable');
  old = ui.event('tool-form-reading', 'submit');
  await ui.select('source-2'); await ui.select('source-1');
  await ui.event('tool-form-reading', 'submit');
  release(); await old;
  assert.equal(ui.get('tool-status-reading').textContent, '已整理');
  assert.match(ui.text(ui.get('tool-result-reading')), /source-1/);
  cases.push('A-to-B-to-A stale success and failure cannot replace current results');

  const restored = environment({savedId: 'source-25'}); await restored.idle();
  assert.equal(restored.get('companion-source').value, 'source-25');
  assert.equal(restored.get('tool-pane-author').hidden, false);
  assert(!restored.requests.some(item => item.body));
  const missing = environment({savedId: 'not-found'}); await missing.idle();
  assert.equal(missing.stored.has(storageKey), false);
  assert.equal(missing.get('tool-run-author').disabled, true);
  const privateMode = environment({storageFails: true}); await privateMode.idle();
  await privateMode.select('source-1'); assert.equal(privateMode.get('tool-run-author').disabled, false);
  await ui.event('tool-tab-author', 'keydown', {key: 'End'});
  assert.equal(ui.get('tool-tab-knowledge').attributes['aria-selected'], 'true');
  assert.equal(ui.document.activeElement.id, 'tool-tab-knowledge');
  cases.push('validated ID restoration, missing/disabled storage and keyboard tabs');
  const updating = environment(); await updating.idle();
  const releaseList = updating.defer('/api/v1/sources');
  const pendingList = updating.event('companion-refresh', 'click');
  const savedAnswer = {...source(100), id: 'question-imported-answer'};
  updating.sources.unshift(savedAnswer);
  await updating.document.dispatchEvent({type: 'zhijing:sources-imported', detail: {saved: [savedAnswer]}});
  releaseList(); await pendingList; await updating.idle();
  assert.equal(updating.get('companion-source').value, savedAnswer.id);
  assert(updating.get('companion-source').children.some(item => item.value === savedAnswer.id));
  assert.equal(updating.requests.filter(item => item.path === '/api/v1/sources').length, 3, 'Import during list refresh must queue a fresh list request');
  cases.push('external question import refreshes and selects even during an in-flight source list');
  console.log(JSON.stringify({passed: true, scope: 'Independent companion JS handlers with synthetic API responses; no browser rendering or network', cases}, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
