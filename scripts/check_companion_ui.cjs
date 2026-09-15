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
const sessionId = 'synthetic-public-session-id';
const storageKey = 'zhijing.companion.source.' + sessionId;
const cases = [];
const copy = value => JSON.parse(JSON.stringify(value));

function source(index) {
  return {id: 'source-' + index, title: '资料 ' + index, author_id: 'author-' + index,
    author_name: '同一个昵称', text: '  完整保留的合成资料 ' + index + '\nActive recall helps learning.\n',
    origin: 'manual', content_extent: 'unknown'};
}

function environment({savedId, storageFails = false} = {}) {
  const nodes = new Map(), created = [], requests = [], downloads = [], gates = new Map(), failures = new Map();
  const mapRenders = [];
  const opinionMounts = [];
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
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\sid="([^"]+)"[^>]*)>/g)) {
    const item = new Element(match[1]); item.id = match[3];
    item.hidden = /\bhidden\b/.test(match[2]); item.open = /\bopen\b/.test(match[2]);
  }
  for (const match of html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
    const options = [...match[2].matchAll(/<option\b([^>]*)>/g)];
    const selected = options.find(option => /\bselected\b/.test(option[1])) || options[0];
    nodes.get(match[1]).value = selected?.[1].match(/\bvalue="([^"]*)"/)?.[1] || '';
  }
  const body = new Element('body');
  const documentListeners = new Map();
  const document = {body, currentScript: {dataset: {configToken: token, sessionId}},
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
      total_sources: 25, included_sources: 20, content_extent_counts: {fulltext: 0, excerpt: 1, unknown: 19}, nodes: Array.from({length: 8}, (_, index) => ({id: 'n' + index, data: {label: '概念 ' + index, kind: 'topic', description: '原文概念', evidence: [evidence]}})),
      edges: [{source: 'n0', target: 'n1', label: '相关', data: {explanation: '同一资料提及', evidence: [evidence]}}]};
    throw Error('Unexpected endpoint: ' + url.pathname);
  };
  class TestURL extends URL {
    static createObjectURL(blob) { downloads.push({blob}); return 'blob:companion-fixture'; }
    static revokeObjectURL() {}
  }
  const sandbox = {document, sessionStorage, URL: TestURL, URLSearchParams,
    ZhijingOpinionMap: {mount(root, options) {
      const record = {root, options, active: false}; opinionMounts.push(record);
      return {setActive: active => { record.active = active; }};
    }},
    // The shared map owns its own DOM tests. This stub verifies the host lifecycle
    // and receives the full response unchanged, including evidence and coverage.
    ZhijingKnowledgeMap: {render(root, result, options) {
      const record = {root, result, options, cleanups: 0}; mapRenders.push(record);
      const wrapper = new Element('div'); wrapper.className = 'knowledge-map'; root.append(wrapper);
      return () => { record.cleanups++; };
    }},
    crypto: {randomUUID: () => 'synthetic-' + (++sequence)}, setTimeout: callback => callback(),
    fetch: async (relative, options) => {
      assert(relative.startsWith('/api/v1/'), 'Only local application endpoints are permitted');
      const url = new URL(relative, 'http://127.0.0.1');
      const body = options.body ? JSON.parse(options.body) : undefined;
      requests.push({path: url.pathname, relative, options, body});
      assert.equal(options.headers['X-Zhijing-Token'], token);
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
  return {nodes, get, text, requests, downloads, sources, stored, failures, created, idle, event, click, submit, select, defer, document, mapRenders, opinionMounts};
}

(async () => {
  assert(!html.includes('/assets/workspace.js'), 'The companion must not load workspace handlers');
  assert(html.indexOf('/assets/knowledge-map.js') < html.indexOf('/assets/companion.js'));
  assert.match(html, /src="\/assets\/knowledge-map.js" nonce="__CSP_NONCE__"/);
  assert(html.includes('/assets/knowledge-map.css'));
  assert(html.indexOf('/assets/opinion-flow.js') < html.indexOf('/assets/opinion-map.js'));
  assert(html.indexOf('/assets/opinion-map.js') < html.indexOf('/assets/companion.js'));
  assert(html.includes('<span>思维导图</span>'));
  const ui = environment(); await ui.idle();
  assert.equal(ui.opinionMounts.length, 1);
  assert.equal(ui.opinionMounts[0].options.compact, true);
  await ui.click('tool-tab-opinions');
  assert.equal(ui.opinionMounts[0].active, true);
  assert.equal(ui.get('tool-pane-opinions').hidden, false);
  await ui.click('tool-tab-author');
  assert.equal(ui.opinionMounts[0].active, false);
  cases.push('new opinion map mounts inside companion and deactivates when changing tabs; mind diagram retained');
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
  assert.equal(mapRequest.searchParams.get('primary_source_id'), 'source-2');
  const firstMap = ui.mapRenders.at(-1);
  assert.equal(firstMap.options.compact, true);
  assert.equal(firstMap.root, ui.get('tool-result-knowledge'));
  assert.equal(firstMap.result.truncated, true);
  assert.equal(firstMap.result.nodes.length, 8);
  assert.equal(firstMap.result.included_sources, 20);
  assert.equal(firstMap.result.content_extent_counts.excerpt, 1);
  assert.equal(firstMap.result.edges[0].data.evidence[0].excerpt, '<script>不可执行的原文</script>');
  ui.get('tool-knowledge-scope').value = 'all'; ui.get('tool-knowledge-limit').value = '50';
  await ui.submit('knowledge');
  const allMapRequest = new URL(ui.requests.filter(item => item.path === '/api/v1/knowledge-map').at(-1).relative, 'http://127.0.0.1');
  assert.equal(allMapRequest.searchParams.has('author_id'), false);
  assert.equal(allMapRequest.searchParams.get('limit'), '50');
  assert.equal(allMapRequest.searchParams.get('primary_source_id'), 'source-2');
  assert.equal(firstMap.cleanups, 1);
  const beforeInvalid = ui.requests.length;
  for (const invalid of ['0', '101', '1.5', '']) {
    ui.get('tool-knowledge-limit').value = invalid; await ui.submit('knowledge');
    assert.equal(ui.requests.length, beforeInvalid);
  }
  ui.get('tool-knowledge-limit').value = '20';
  const liveMap = ui.mapRenders.at(-1);
  await liveMap.options.onOpenSource('source-1');
  assert.equal(ui.get('companion-source').value, 'source-1');
  assert.equal(ui.get('tool-pane-reading').hidden, false);
  assert.equal(liveMap.cleanups, 1);
  assert.equal(ui.get('tool-result-knowledge').children.length, 0);
  const beforeStaleOpen = ui.requests.length;
  await liveMap.options.onOpenSource('source-2');
  assert.equal(ui.requests.length, beforeStaleOpen, 'Disposed map must not initiate a source request');
  cases.push('fact exclusion; shared map coverage and evidence; author/all scope, bounded count, source navigation and cleanup');

  await ui.submit('knowledge');
  const activeMap = ui.mapRenders.at(-1);
  const releaseMapSource = ui.defer('/api/v1/sources/source-2');
  const openingMapSource = activeMap.options.onOpenSource('source-2');
  await ui.select('source-3'); await ui.select('source-1');
  releaseMapSource(); await openingMapSource;
  assert.equal(ui.get('companion-source').value, 'source-1', 'Old map navigation must not override A-to-B-to-A selection');
  const beforeStaleMap = ui.mapRenders.length;
  const releaseMap = ui.defer('/api/v1/knowledge-map');
  const pendingMap = ui.event('tool-form-knowledge', 'submit');
  await ui.select('source-2'); await ui.select('source-1');
  releaseMap(); await pendingMap;
  assert.equal(ui.mapRenders.length, beforeStaleMap);
  assert.equal(ui.get('tool-result-knowledge').children.length, 0);
  cases.push('shared map and source-link A-to-B-to-A responses are discarded after selection changes');

  await ui.submit('knowledge');
  const mapBeforeScopeChange = ui.mapRenders.at(-1);
  ui.get('tool-knowledge-scope').value = 'author';
  await ui.event('tool-knowledge-scope', 'change');
  assert.equal(mapBeforeScopeChange.cleanups, 1);
  assert.equal(ui.get('tool-result-knowledge').children.length, 0);
  assert.match(ui.get('tool-status-knowledge').textContent, /范围已调整/);
  const mapCountBeforeScopeRace = ui.mapRenders.length;
  const releaseScopeMap = ui.defer('/api/v1/knowledge-map');
  const scopeMap = ui.event('tool-form-knowledge', 'submit');
  ui.get('tool-knowledge-limit').value = '10'; await ui.event('tool-knowledge-limit', 'change');
  releaseScopeMap(); await scopeMap;
  assert.equal(ui.mapRenders.length, mapCountBeforeScopeRace);
  assert.match(ui.get('tool-status-knowledge').textContent, /范围已调整/);
  assert.equal(ui.get('tool-run-knowledge').disabled, false);
  cases.push('changing map scope clears the old map and discards a pending result without auto-requesting');

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
