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
  assert(html.indexOf('/assets/knowledge-map.js') < html.indexOf('/assets/workspace.js'));
  assert.match(html, /src="\/assets\/knowledge-map.js" nonce="[^"]+"/);
  assert(html.includes('/assets/knowledge-map.css'));
  assert(html.includes('生成思维导图'));
  assert(html.indexOf('/assets/opinion-flow.js') < html.indexOf('/assets/opinion-map.js'));
  assert(html.indexOf('/assets/opinion-map.js') < html.indexOf('/assets/workspace.js'));
  const opinionMounts = [];
  const pageToken = html.match(/data-config-token="([^"]+)"/)[1];
  const apiFetch = (url, options = {}) => fetch(url, {...options, headers: {
    ...options.headers, 'X-Zhijing-Token': pageToken,
  }});
  const nodes = new Map();
  const created = [];
  class Element {
    constructor(tagName) {
      this.tagName = tagName; this.children = []; this.events = {}; this.attributes = {};
      this.value = ''; this.textContent = ''; this.className = ''; this.files = []; created.push(this);
    }
    set id(value) { this._id = value; nodes.set(value, this); }
    get id() { return this._id; }
    contains(node) { return node === this || this.children.some(child => child.contains(node)); }
    closest(selector) {
      for(let node = this; node; node = node.parentNode) {
        if(selector.startsWith('#') && node.id === selector.slice(1)) return node;
        if(selector.startsWith('.') && node.className.split(' ').includes(selector.slice(1))) return node;
      }
      return null;
    }
    addEventListener(name, callback) { this.events[name] = callback; }
    setAttribute(name, value) { this.attributes[name] = value; if(name === 'class') this.className = value; }
    removeAttribute(name) { delete this.attributes[name]; delete this[name]; }
    unregister() { if(this.id) nodes.delete(this.id); this.children.forEach(child => child.unregister()); }
    register() { if(this.id) nodes.set(this.id, this); this.children.forEach(child => child.register()); }
    replaceChildren(...children) {
      this.children.forEach(child => { child.unregister(); child.parentNode = null; });
      this.children = []; this.append(...children);
    }
    append(...children) {
      for(const child of children) {
        if(child.parentNode) child.parentNode.children = child.parentNode.children.filter(node => node !== child);
        child.parentNode = this; child.register(); this.children.push(child);
      }
    }
    focus(options) { this.focused = true; this.focusOptions = options; document.activeElement = this; }
    scrollIntoView(options) { this.scrollOptions = options; }
    remove() {
      if(this.parentNode) this.parentNode.children = this.parentNode.children.filter(node => node !== this);
      this.parentNode = null; this.unregister();
    }
    click() { if(this.events.click) return this.events.click(); }
  }
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const node = new Element(match[1]); node.id = match[3];
    node.value = match[2].match(/\bvalue="([^"]*)"/)?.[1] || '';
    node.className = match[2].match(/\bclass="([^"]*)"/)?.[1] || '';
    node.checked = /\bchecked\b/.test(match[2]);
    node.hidden = /\bhidden\b/.test(match[2]);
    node.open = /\bopen\b/.test(match[2]);
  }
  for (const match of html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>\s*<option value="([^"]*)"/g)) nodes.get(match[1]).value = match[2];
  // Preserve nesting of ID-bearing elements from the actual page. Removing a parent
  // must invalidate descendant IDs, just as document.getElementById does in a browser.
  const stack = [], voidTags = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
  for(const match of html.matchAll(/<(\/?)([a-z][a-z0-9]*)\b([^>]*)>/g)) {
    const [, closing, tag, attributes] = match;
    if(closing) {
      const index = stack.findLastIndex(entry => entry.tag === tag);
      if(index >= 0) stack.splice(index);
      continue;
    }
    const id = attributes.match(/\bid="([^"]+)"/)?.[1];
    const node = id ? nodes.get(id) : null;
    const parent = [...stack].reverse().find(entry => entry.node)?.node;
    if(node && parent) parent.append(node);
    if(!voidTags.has(tag) && !attributes.endsWith('/')) stack.push({tag, node});
  }
  assert.equal(nodes.get('chat-empty').parentNode, nodes.get('chat-messages'), 'Fixture must model the real nested chat empty state');
  const requests = [], downloads = [], failures = new Map(), fixtures = new Map(), delays = new Map(), responders = new Map();
  const mapRenders = [];
  let inFlight = 0;
  const stored = new Map();
  const sessionStorage = {getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, String(value)), removeItem: key => stored.delete(key)};
  class LocalURL extends URL {
    static createObjectURL(blob) { downloads.push(blob); return 'blob:fixture'; }
    static revokeObjectURL() {}
  }
  const body = new Element('body');
  const document = {
    events: {}, listeners: {},
    addEventListener(name, callback) {
      (this.listeners[name] ??= []).push(callback);
      this.events[name] = event => this.listeners[name].forEach(listener => listener(event));
    },
    dispatchEvent(event) { this.events[event.type]?.(event); return true; },
    currentScript: {dataset: {configToken: pageToken, sessionId: html.match(/data-session-id="([^"]+)"/)[1]}}, body,
    getElementById: id => {
      // The shared importer creates its dialog after workspace.js has initialized.
      if (id === 'question-import-dialog' && !nodes.has(id)) return null;
      assert(nodes.has(id), 'Missing element ' + id); return nodes.get(id);
    },
    createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    querySelectorAll: selector => created.filter(node => selector === 'button' ? node.tagName === 'button' : node.className.split(' ').includes(selector.slice(1))),
  };
  const windowEvents = {};
  const sandbox = {document, sessionStorage, AbortController, addEventListener: (name, listener) => { windowEvents[name] = listener; }, CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } }, location: {hash: '#cards'}, URL: LocalURL, URLSearchParams, setTimeout: fn => fn(),
    ZhijingOpinionMap: {mount(root, options) {
      const record = {root, options, active: false}; opinionMounts.push(record);
      return {setActive: active => { record.active = active; }};
    }},
    // Rendering is tested by the shared component's own browser QA. Keep this
    // host test focused on real requests, full response handoff and lifecycle.
    ZhijingKnowledgeMap: {render(root, result, options) {
      const wrapper = new Element('div'); wrapper.className = 'knowledge-map';
      const disabledButton = new Element('button'); disabledButton.disabled = true;
      const enabledButton = new Element('button'); enabledButton.disabled = false;
      wrapper.append(disabledButton, enabledButton); root.append(wrapper);
      const record = {result, options, root, disabledButton, enabledButton, cleanups: 0}; mapRenders.push(record);
      return () => { record.cleanups++; };
    }}, fetch: async (url, options) => {
    if (url.startsWith('/api/v1/')) assert.equal(options.headers['X-Zhijing-Token'], pageToken);
    requests.push({url, options});
    inFlight++;
    try {
    if (delays.has(url)) await delays.get(url);
    if (responders.has(url)) { const response = await responders.get(url)(options); if (response) return response; }
    if (failures.has(url)) return {ok: false, json: async () => ({error: typeof failures.get(url) === 'string' ? {message: failures.get(url)} : failures.get(url)})};
    if (fixtures.has(url)) return {ok: true, json: async () => fixtures.get(url)};
    return await fetch(new URL(url, base), options);
    } finally { inFlight--; }
  }};
  vm.createContext(sandbox);
  const script = await fetch(base + '/assets/workspace.js');
  assert.equal(script.status, 200);
  const collectorScript = await fetch(base + '/assets/zhihu-companion.user.js');
  assert.equal(collectorScript.status, 200, 'Packaged collector must be installable from the local asset link');
  assert.match(collectorScript.headers.get('content-type') || '', /javascript/);
  const collectorSource = await collectorScript.text();
  assert.match(collectorSource, /^\/\/ ==UserScript==/);
  assert.match(collectorSource, /@name\s+知乎伴侣·知境版/);
  assert.match(collectorSource, /@match\s+https:\/\/www\.zhihu\.com\/\*/);
  assert.match(collectorSource, /@connect\s+127\.0\.0\.1/);
  vm.runInContext(await script.text(), sandbox);
  const widgetScript = await fetch(base + '/assets/chat-widget.js');
  assert.equal(widgetScript.status, 200);
  vm.runInContext(await widgetScript.text(), sandbox);
  const busy = () => vm.runInContext('state.busy', sandbox);
  async function idle() {
    const until = Date.now() + 15000;
    do { await new Promise(resolve => setTimeout(resolve, 10)); }
    while((busy() || inFlight) && Date.now() < until);
    assert.equal(busy(), false, 'UI did not finish');
    assert.equal(inFlight, 0, 'Widget requests did not finish');
  }
  const get = id => nodes.get(id);
  const submit = async id => { await get(id).events.submit({preventDefault() {}}); await idle(); };
  const click = async id => { await get(id).events.click(); await idle(); };
  const allText = node => [node.textContent, ...node.children.map(allText)].join('\n');
  const chatMessages = () => get('chat-messages').children.filter(node => node.className.startsWith('chat-message '));
  await idle();
  assert.equal(get('pane-cards').hidden, false, 'A direct capability link must open the requested tab');
  assert.equal(opinionMounts.length, 1);
  await click('tab-opinions');
  assert.equal(opinionMounts[0].active, true);
  assert.equal(get('pane-opinions').hidden, false);
  await click('tab-cards');
  assert.equal(opinionMounts[0].active, false);
  assert.equal(get('pane-reading').hidden, true);
  assert.equal(get('run-reading').disabled, true);
  assert.equal(get('export-apkg').disabled, true);
  assert.match(allText(get('source-list')), /资料库还是空/);
  assert.equal(vm.runInContext('library.view', sandbox), 'question', 'Library opens with questions');
  assert.equal(get('library-drawer').open, true, 'Desktop library starts expanded without matchMedia');
  assert.equal(get('workspace-empty').hidden, false);
  fixtures.set('/api/v1/zhihu/status', {configured: false});
  await click('chat-launcher');
  assert.equal(get('chat-window').hidden, false);
  assert.equal(get('chat-launcher').attributes['aria-expanded'], 'true');
  assert.equal(get('chat-send').disabled, true);
  assert.equal(get('chat-question').focused, true);
  get('chat-question').value = '先测试没有资料的情况';
  await submit('chat-form');
  assert.match(get('chat-status').textContent, /先.*选择/);
  assert.equal(chatMessages().length, 0);
  assert.equal(get('chat-empty').hidden, false);
  assert.equal(get('chat-pick-source').hidden, false);
  assert.equal(requests.filter(row => row.url === '/api/v1/author/ask').length, 0);
  await click('chat-close');
  assert.equal(get('chat-window').hidden, true);
  assert.equal(get('chat-launcher').focused, true);
  await click('chat-launcher');
  document.events.keydown({key: 'Escape', preventDefault() {}});
  assert.equal(get('chat-window').hidden, true);
  await click('chat-launcher');
  await click('chat-pick-source');
  assert.equal(get('chat-window').hidden, false);
  assert.equal(get('chat-source-picker').open, true);
  assert.equal(get('chat-source-select').focused, true);
  await click('chat-close');
  await click('empty-import');
  assert.equal(get('import-panel').hidden, false);
  assert.equal(get('zhihu-panel').hidden, true);
  // Group and deletion checks use only this harness's synthetic HTTP database.
  const libraryDrafts = [
    {title: '管理测试问题', author_id: 'library-a', author_name: '管理同名作者', text: '甲回答', origin: 'zhihu', url: 'https://www.zhihu.com/question/88001/answer/99001'},
    {title: '管理测试问题', author_id: 'library-b', author_name: '管理同名作者', text: '乙回答', origin: 'zhihu', url: 'https://www.zhihu.com/question/88001/answer/99002'},
    {title: '管理测试问题', author_id: 'library-a', author_name: '管理同名作者', text: '另一问题', origin: 'zhihu', url: 'https://www.zhihu.com/question/88002/answer/99003'},
  ];
  sandbox.libraryDrafts = libraryDrafts;
  await vm.runInContext('saveSources(libraryDrafts)', sandbox); await idle();
  get('library-view').value = 'author'; await get('library-view').events.change(); await idle();
  get('library-search').value = '管理同名'; await submit('library-search-form');
  assert.equal(get('source-list').children.length, 2, 'Same display name must remain separate authors');
  await get('source-list').children[0].click(); await idle();
  assert.equal(vm.runInContext('state.sources.length', sandbox), 2);
  get('library-view').value = 'question'; await get('library-view').events.change(); await idle();
  get('library-search').value = '88001'; await submit('library-search-form');
  assert.equal(get('source-list').children.length, 1);
  await get('source-list').children[0].click(); await idle();
  assert.equal(vm.runInContext('state.sources.length', sandbox), 2, 'Question group includes multiple authors');
  assert.match(get('library-scope').textContent, /管理测试问题 · 2 篇回答/);
  assert.match(get('library-back').textContent, /返回全部问题/);
  assert.match(allText(get('source-list').children[0]), /管理同名作者的回答/);
  assert.doesNotMatch(allText(get('source-list').children[0]), /管理测试问题/);
  await get('source-list').children[0].children[1].click(); await idle();
  get('library-select-page').checked = true; get('library-select-page').events.change();
  let confirmed = false;
  sandbox.window = {confirm: text => { assert.match(text, /2 条资料/); assert.match(text, /历史任务/); return confirmed; }};
  const deletesBefore = requests.filter(row => row.url === '/api/v1/sources/delete').length;
  await click('library-delete');
  assert.equal(requests.filter(row => row.url === '/api/v1/sources/delete').length, deletesBefore, 'Cancel must send no delete request');
  failures.set('/api/v1/sources/delete', '模拟删除失败'); confirmed = true;
  await click('library-delete');
  assert.equal(vm.runInContext('state.sources.length', sandbox), 2, 'Failure must preserve the displayed sources');
  failures.delete('/api/v1/sources/delete');
  await click('library-delete');
  assert.equal(vm.runInContext('state.selected', sandbox), null);
  assert.equal(get('run-reading').disabled, true);
  assert.equal(get('export-apkg').disabled, true);
  assert.equal(get('chat-send').disabled, true);
  assert.equal(get('selected-text').textContent, '');
  assert.equal(vm.runInContext('state.sources.length', sandbox), 0);
  await click('library-back');
  assert.doesNotMatch(allText(get('source-list')), /88001/);
  assert.equal(get('import-title').focused, true);
  await click('empty-search');
  assert.equal(get('zhihu-panel').hidden, false);
  assert.equal(get('import-panel').hidden, true);
  assert.equal(get('zhihu-query').focused, true);
  await click('open-import');
  assert.equal(get('zhihu-panel').hidden, true);

  get('import-title').value = 'UI fixture <script>not code</script>';
  get('import-author-name').value = 'Fixture Author'; get('import-author-id').value = 'ui-author';
  const original = '  Active recall helps learning.\nSpaced repetition supports memory.\n';
  get('import-text').value = original; get('import-topics').value = 'Learning,Memory';
  await submit('import-form');
  assert.match(get('import-status').className, /success/, get('import-status').textContent);
  assert.equal(get('selected-text').textContent, original);
  assert.equal(vm.runInContext('library.view', sandbox), 'question', 'Import preserves question view');
  assert.equal(get('run-reading').disabled, false);
  const primaryId = vm.runInContext('state.selected.id', sandbox);
  assert.deepEqual([...stored.values()], [primaryId], 'Only the selected source ID may be stored');
  assert.equal(get('selected-title').textContent, get('import-title').value);
  assert.equal(get('source-preview-label').textContent, '查看已导入内容');
  assert.equal(get('workspace-empty').hidden, true);
  assert.equal(get('chat-empty').parentNode, get('chat-messages'));
  assert.equal(get('chat-pick-source').hidden, true);

  const sample = JSON.parse(fs.readFileSync(path.join(__dirname, '../examples/sources.json'), 'utf8'));
  get('import-file').files = [{size: 500, text: async () => JSON.stringify(sample)}];
  await click('import-json');
  assert.match(get('import-status').className, /success/);
  const primary = await (await apiFetch(base + '/api/v1/sources/' + primaryId)).json();
  sandbox.fixturePrimary = primary;
  vm.runInContext('select(fixturePrimary)', sandbox);

  await submit('reading-form');
  assert.match(get('reading-status').className, /success/);
  assert(allText(get('reading-result')).includes('Active recall'));
  get('author-question').value = 'How does active recall help learning?';
  await submit('author-form');
  assert.match(get('author-status').className, /success/);
  assert(allText(get('author-result')).includes('UI fixture'), 'References must retain the real source title');
  assert(!allText(get('author-result')).includes('作者 ID'), 'Implementation identifiers stay out of ordinary results');
  const authorBody = JSON.parse(requests.find(row => row.url === '/api/v1/author/ask').options.body);
  assert.equal(authorBody.author_id, 'ui-author'); assert.equal(authorBody.primary_source_id, primaryId);

  await click('chat-launcher');
  assert.equal(get('chat-send').disabled, false);
  assert.match(get('chat-context').textContent, /UI fixture/);
  const chatCountBefore = requests.filter(row => row.url === '/api/v1/author/ask').length;
  const chatQuestion = 'How does active recall help learning? <script>not code</script>';
  get('chat-question').value = chatQuestion;
  for (const event of [{shiftKey: true}, {isComposing: true}, {keyCode: 229}]) {
    get('chat-question').events.keydown({key: 'Enter', preventDefault() { throw new Error('Composition/Shift+Enter must keep normal input behavior'); }, ...event});
  }
  assert.equal(requests.filter(row => row.url === '/api/v1/author/ask').length, chatCountBefore);
  let enterPrevented = false;
  await get('chat-question').events.keydown({key: 'Enter', preventDefault() { enterPrevented = true; }});
  await idle();
  assert.equal(enterPrevented, true);
  assert.equal(get('chat-question').value, '');
  assert.equal(chatMessages().length, 2);
  const [chatUser, chatAnswer] = chatMessages();
  assert.equal(chatUser.className, 'chat-message user');
  assert.equal(chatUser.children[0].textContent, chatQuestion);
  assert.equal(chatAnswer.className, 'chat-message assistant');
  assert.match(allText(chatAnswer), /Active recall/i);
  const chatReferences = chatAnswer.children.find(node => node.className === 'chat-citations');
  assert.equal(chatReferences.tagName, 'details');
  assert(chatReferences.children.some(node => node.className === 'citation'));
  const chatBody = JSON.parse(requests.filter(row => row.url === '/api/v1/author/ask').at(-1).options.body);
  assert.equal(chatBody.primary_source_id, primaryId);
  assert.equal(chatBody.author_id, 'ui-author');
  assert.equal(chatBody.question, chatQuestion);
  await click('chat-close'); await click('chat-launcher');
  assert.equal(chatMessages().length, 2, 'Closing and reopening preserves the same-source conversation');
  const countBeforeInvalidChat = requests.filter(row => row.url === '/api/v1/author/ask').length;
  await submit('chat-form');
  assert.match(get('chat-status').className, /error/);
  assert.equal(requests.filter(row => row.url === '/api/v1/author/ask').length, countBeforeInvalidChat);

  let releaseChat;
  delays.set('/api/v1/author/ask', new Promise(resolve => { releaseChat = resolve; }));
  fixtures.set('/api/v1/author/ask', {answer: 'Stale source answer must be discarded', mode: 'extractive', identity_notice: 'Fixture', citations: []});
  get('chat-question').value = 'Deferred source question';
  const pendingChat = get('chat-form').events.submit({preventDefault() {}});
  assert.equal(busy(), false, 'Shared chat must not make the workspace busy');
  assert.equal(get('chat-send').disabled, true);
  assert.equal(get('chat-close').disabled, false);
  assert.equal(get('chat-launcher').disabled, false);
  const countWhileBusy = requests.filter(row => row.url === '/api/v1/author/ask').length;
  await get('chat-form').events.submit({preventDefault() {}});
  assert.equal(requests.filter(row => row.url === '/api/v1/author/ask').length, countWhileBusy);
  get('chat-close').events.click();
  assert.equal(get('chat-window').hidden, true);
  get('chat-launcher').events.click();
  assert.equal(get('chat-window').hidden, false);
  const otherChatSource = (await (await apiFetch(base + '/api/v1/sources')).json()).find(source => source.id !== primaryId);
  assert(otherChatSource);
  sandbox.fixtureChatOther = otherChatSource;
  vm.runInContext('select(fixtureChatOther)', sandbox);
  assert.equal(chatMessages().length, 0);
  assert.equal(get('chat-empty').parentNode, get('chat-messages'));
  assert.equal(get('chat-pick-source').hidden, true);
  assert.equal(get('chat-empty').hidden, false);
  assert(get('chat-context').textContent.includes(otherChatSource.title));
  releaseChat(); await pendingChat; await idle();
  assert.equal(chatMessages().length, 0, 'A pending old-source answer cannot enter the new conversation');
  assert.equal(get('chat-status').textContent, '');
  fixtures.delete('/api/v1/author/ask'); delays.delete('/api/v1/author/ask');
  vm.runInContext('select(fixturePrimary)', sandbox);
  await click('chat-close');

  // Global chat can change the source while a workspace capability is in flight.
  // Returning A -> B -> A must still discard both old successes and old errors.
  for(const staleError of [false, true]) {
    let releaseReading;
    const readingPath = '/api/v1/reading/analyze';
    delays.set(readingPath, new Promise(resolve => { releaseReading = resolve; }));
    if(staleError) failures.set(readingPath, 'Stale reading error must be discarded');
    else fixtures.set(readingPath, {summary: 'Stale reading result must be discarded', sections: [], mode: 'extractive', notice: 'Fixture'});
    const beforeReading = requests.filter(row => row.url === readingPath).length;
    const pendingReading = get('reading-form').events.submit({preventDefault() {}});
    const untilReading = Date.now() + 5000;
    while(requests.filter(row => row.url === readingPath).length === beforeReading && Date.now() < untilReading) await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(requests.filter(row => row.url === readingPath).length, beforeReading + 1);
    document.dispatchEvent(new sandbox.CustomEvent('zhijing:chat-source-selected', {detail: otherChatSource}));
    document.dispatchEvent(new sandbox.CustomEvent('zhijing:chat-source-selected', {detail: primary}));
    assert.equal(vm.runInContext('state.selected.id', sandbox), primaryId);
    releaseReading(); await pendingReading; await idle();
    assert.equal(get('reading-result').children.length, 0, 'A -> B -> A must discard an old capability result');
    assert.equal(get('reading-status').textContent, '', 'Old-source errors must not enter the current pane');
    delays.delete(readingPath); fixtures.delete(readingPath); failures.delete(readingPath);
  }

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
  const firstMap = mapRenders.at(-1);
  assert.equal(firstMap.options.compact, false);
  assert.equal(firstMap.root, get('knowledge-result'));
  assert(firstMap.result.nodes.some(node => node.data.source_id === primaryId));
  assert(firstMap.result.edges.length > 0);
  assert(firstMap.result.included_sources > 0);
  assert.equal(firstMap.result.content_extent_counts.unknown, firstMap.result.included_sources);
  const graphRequest = new URL(requests.find(row => row.url.startsWith('/api/v1/knowledge-map?')).url, base);
  assert.equal(graphRequest.searchParams.get('primary_source_id'), primaryId);
  assert.equal(graphRequest.searchParams.get('limit'), '20');
  assert.equal(graphRequest.searchParams.has('author_id'), false);
  assert.equal(firstMap.disabledButton.disabled, true, 'Host controls must preserve map-owned disabled state');
  vm.runInContext('state.busy = true; controls()', sandbox);
  assert.equal(firstMap.enabledButton.disabled, false, 'Map interactions stay available during other host tasks');
  vm.runInContext('state.busy = false; controls()', sandbox);
  get('graph-scope').value = 'author'; get('graph-limit').value = '1';
  get('graph-scope').events.change();
  assert.equal(firstMap.cleanups, 1);
  assert.equal(get('knowledge-result').children.length, 0);
  assert.match(get('knowledge-status').textContent, /范围已调整/);
  await submit('knowledge-form');
  const authorMapRequest = new URL(requests.filter(row => row.url.startsWith('/api/v1/knowledge-map?')).at(-1).url, base);
  assert.equal(authorMapRequest.searchParams.get('author_id'), primary.author_id);
  assert.equal(authorMapRequest.searchParams.get('limit'), '1');
  assert.equal(authorMapRequest.searchParams.get('primary_source_id'), primaryId);
  assert.equal(firstMap.cleanups, 1);
  const liveMap = mapRenders.at(-1);
  await liveMap.options.onOpenSource(otherChatSource.id); await idle();
  assert.equal(vm.runInContext('state.selected.id', sandbox), otherChatSource.id);
  assert.equal(get('pane-reading').hidden, false);
  assert.equal(liveMap.cleanups, 1);
  assert.equal(get('knowledge-result').children.length, 0);
  const beforeDisposedOpen = requests.length;
  await liveMap.options.onOpenSource(primaryId);
  assert.equal(requests.length, beforeDisposedOpen);
  vm.runInContext('select(fixturePrimary)', sandbox); await idle();
  get('graph-scope').value = 'all'; get('graph-limit').value = '20';

  await submit('knowledge-form');
  const navigationMap = mapRenders.at(-1);
  let releaseMapSource;
  const otherSourcePath = '/api/v1/sources/' + encodeURIComponent(otherChatSource.id);
  delays.set(otherSourcePath, new Promise(resolve => { releaseMapSource = resolve; }));
  const openingMapSource = navigationMap.options.onOpenSource(otherChatSource.id);
  vm.runInContext('select(fixtureChatOther); select(fixturePrimary)', sandbox);
  releaseMapSource(); await openingMapSource; delays.delete(otherSourcePath); await idle();
  assert.equal(vm.runInContext('state.selected.id', sandbox), primaryId, 'Map source navigation must discard A-to-B-to-A responses');
  const mapPath = '/api/v1/knowledge-map?' + new URLSearchParams({limit: '20', primary_source_id: primaryId});
  for (const staleError of [false, true]) {
    let releaseMap;
    delays.set(mapPath, new Promise(resolve => { releaseMap = resolve; }));
    if (staleError) failures.set(mapPath, 'Stale map error must be discarded');
    const mapCountBefore = mapRenders.length;
    const requestCountBefore = requests.filter(row => row.url === mapPath).length;
    const pendingMap = get('knowledge-form').events.submit({preventDefault() {}});
    const deadline = Date.now() + 5000;
    while(requests.filter(row => row.url === mapPath).length === requestCountBefore && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(requests.filter(row => row.url === mapPath).length, requestCountBefore + 1);
    vm.runInContext('select(fixtureChatOther); select(fixturePrimary)', sandbox);
    releaseMap(); await pendingMap; await idle();
    assert.equal(mapRenders.length, mapCountBefore);
    assert.equal(get('knowledge-result').children.length, 0);
    assert.equal(get('knowledge-status').textContent, '');
    delays.delete(mapPath); failures.delete(mapPath);
  }
  let releaseScopeMap;
  delays.set(mapPath, new Promise(resolve => { releaseScopeMap = resolve; }));
  const mapsBeforeScopeChange = mapRenders.length;
  const callsBeforeScopeChange = requests.filter(row => row.url === mapPath).length;
  const scopeMap = get('knowledge-form').events.submit({preventDefault() {}});
  const scopeDeadline = Date.now() + 5000;
  while(requests.filter(row => row.url === mapPath).length === callsBeforeScopeChange && Date.now() < scopeDeadline) await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(requests.filter(row => row.url === mapPath).length, callsBeforeScopeChange + 1);
  get('graph-limit').value = '10'; get('graph-limit').events.input();
  releaseScopeMap(); await scopeMap; await idle(); delays.delete(mapPath);
  assert.equal(mapRenders.length, mapsBeforeScopeChange);
  assert.match(get('knowledge-status').textContent, /范围已调整/);
  assert.equal(get('knowledge-result').children.length, 0);
  assert.equal(get('run-knowledge').disabled, false);

  failures.set('/api/v1/cards/generate', 'Fixture upstream failure');
  await submit('cards-form');
  assert.match(get('cards-status').className, /error/);
  assert.equal(get('export-apkg').disabled, true);
  failures.clear();
  for (const [code, expected] of [
    ['model_output_truncated', /模型达到输出上限/],
    ['cards_format_invalid', /卡片格式或字段长度/],
    ['cards_evidence_invalid', /证据无法在资料原文中找到/],
  ]) {
    failures.set('/api/v1/cards/generate', {code, message: 'private-provider-details'});
    await submit('cards-form');
    assert.match(get('cards-status').textContent, expected);
    assert(!get('cards-status').textContent.includes('private-provider-details'));
    assert.equal(get('export-apkg').disabled, true);
    assert.equal(get('export-tsv').disabled, true);
  }
  failures.clear();
  get('library-view').value = 'all'; await get('library-view').events.change(); await idle();
  const batches = Array.from({length: 20}, (_, i) => ({title: 'Page ' + i, author_id: 'pagination', author_name: 'Paging', text: 'Page body ' + i}));
  get('import-file').files = [{size: 1000, text: async () => JSON.stringify({items: batches})}];
  await click('import-json');
  assert.equal(get('next-page').disabled, false);
  await click('next-page'); assert.equal(get('prev-page').disabled, false);
  get('source-filter').value = 'no-such-author'; await submit('source-filter-form');
  assert.match(allText(get('source-list')), /没有资料/);
  assert.equal(get('next-page').disabled, true);
  assert.equal(get('prev-page').disabled, true);
  await click('chat-source-refresh');
  assert.equal(get('chat-source-prev').disabled, true);
  assert.equal(get('chat-source-next').disabled, false);
  await click('chat-source-next');
  assert.equal(get('chat-source-page').textContent, '第 2 页');
  assert(requests.some(row => row.url === '/api/v1/sources?offset=20&limit=21'));
  const widgetSourceId = get('chat-source-select').children.at(-1).value;
  assert(widgetSourceId);
  get('chat-source-select').value = widgetSourceId;
  await get('chat-source-select').events.change(); await idle();
  assert.equal(vm.runInContext('state.selected.id', sandbox), widgetSourceId, 'Widget selection must update the workspace');
  assert.deepEqual([...stored.values()], [widgetSourceId], 'Shared widget storage must contain only one source ID');
  assert.equal(get('chat-source-picker').open, false);
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
  assert.equal(get('zhihu-secret'), undefined, 'Credential controls must not appear on the user workspace');
  assert.equal(get('zhihu-config-form'), undefined);
  assert.equal(get('run-zhihu-search').disabled, true);
  assert.match(get('zhihu-config-state').textContent, /暂未就绪.*管理员/);
  get('zhihu-query').value = '学习方法';
  await submit('zhihu-search-form');
  assert.match(get('zhihu-status').textContent, /暂未就绪/);
  assert.equal(requests.filter(row => row.url === '/api/v1/zhihu/search').length, 0);

  // Administration runs in its own document and IIFE, never in the user-page DOM.
  const adminHTML = await (await fetch(base + '/')).text();
  const adminSection = adminHTML.match(/<section id="zhihu-admin"[\s\S]*?<\/section>/)[0];
  const adminNodes = new Map();
  for(const match of adminSection.matchAll(/\bid="([^"]+)"/g)) {
    adminNodes.set(match[1], {value: '', textContent: '', className: '', events: {}, addEventListener(name, callback) { this.events[name] = callback; }});
  }
  const adminDocument = {currentScript: {dataset: {configToken: adminHTML.match(/data-config-token="([^"]+)"/)[1]}}, getElementById: id => { assert(adminNodes.has(id), 'Missing admin element ' + id); return adminNodes.get(id); }};
  const adminSandbox = {document: adminDocument, fetch: sandbox.fetch};
  vm.createContext(adminSandbox);
  const adminScript = await fetch(base + '/assets/admin-zhihu.js');
  assert.equal(adminScript.status, 200);
  vm.runInContext(await adminScript.text(), adminSandbox);
  await idle();
  const adminGet = id => adminNodes.get(id);
  const adminSubmit = async () => { await adminGet('zhihu-config-form').events.submit({preventDefault() {}}); await idle(); };
  await adminSubmit();
  assert.match(adminGet('zhihu-config-status').className, /error/);
  assert.equal(requests.filter(row => row.url === '/api/v1/zhihu/config').length, 0);
  fixtures.set('/api/v1/zhihu/config', {configured: true});
  adminGet('zhihu-secret').value = 'fake-local-fixture-secret';
  await adminSubmit();
  assert.match(adminGet('zhihu-config-status').className, /success/);
  assert.equal(adminGet('zhihu-secret').value, '');
  fixtures.set('/api/v1/zhihu/status', {configured: true});
  await click('open-zhihu');
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
  assert.equal(get('zhihu-results').children[0].children[0].tagName, 'h3');
  const excerpt = get('zhihu-results').children[0].children.find(node => node.className === 'zhihu-excerpt-details');
  assert.equal(excerpt.tagName, 'details');
  assert.equal(excerpt.children[0].tagName, 'summary');
  assert.equal(excerpt.children[1].textContent, zhihuItems[0].text);
  excerpt.open = true; excerpt.events.toggle();
  assert.equal(excerpt.children[0].children[1].textContent, '收起摘要');
  excerpt.open = false; excerpt.events.toggle();
  assert.equal(excerpt.children[0].children[1].textContent, '展开摘要');
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
  assert.match(get('author-scope-notice').textContent, /不.*合并.*同名作者/);
  assert.doesNotMatch(get('selected-meta').textContent, /作者 ID/);
  get('source-filter').value = 'zhihu-content:answer:1';
  await submit('source-filter-form');
  assert.match(allText(get('source-list')), /摘要/);
  const importedCount = requests.filter(row => row.url === '/api/v1/sources/import').length;
  await click('reload-sources');
  assert.equal(firstImport.disabled, true, 'Unrelated jobs must not reenable an imported result');
  await firstImport.click(); await idle();
  assert.equal(requests.filter(row => row.url === '/api/v1/sources/import').length, importedCount);
  assert.equal(get('zhihu-panel').hidden, true, 'Import returns to the five capabilities');
  sandbox.innerWidth = 390;
  vm.runInContext('syncLibraryDrawer()', sandbox);
  assert.equal(get('library-drawer').open, false);
  const secondImport = vm.runInContext('state.zhihuResults[1].button', sandbox);
  await secondImport.click(); await idle();
  assert.equal(vm.runInContext('state.selected.author_id', sandbox), 'zhihu-content:answer:2');
  assert.equal(get('zhihu-panel').hidden, true, 'Mobile import returns to the reading workspace');
  assert.equal(get('import-panel').hidden, true);
  assert.equal(get('reading-workspace').scrollOptions.block, 'start');
  assert.equal(get('library-drawer').open, false);
  await click('open-import');
  assert.equal(get('import-panel').scrollOptions.block, 'start');
  fixtures.set('/api/v1/zhihu/status', {configured: true});
  await click('open-zhihu');
  assert.equal(get('zhihu-panel').scrollOptions.block, 'start');
  assert.equal(get('import-panel').hidden, true);
  sandbox.innerWidth = 1440;
  vm.runInContext('syncLibraryDrawer()', sandbox);
  assert.equal(get('library-drawer').open, true);
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
  await adminGet('clear-zhihu-secret').events.click(); await idle();
  assert.match(adminGet('zhihu-config-status').textContent, /凭据已清除/);
  fixtures.set('/api/v1/zhihu/status', {configured: false});
  await click('open-zhihu');
  assert.equal(get('run-zhihu-search').disabled, true);
  assert.equal(adminGet('clear-zhihu-secret').disabled, true);
  assert.equal(vm.runInContext('state.selected.id', sandbox), selectedBeforeClear);
  assert.equal(JSON.parse(requests.filter(row => row.url === '/api/v1/zhihu/config').at(-1).options.body).access_secret, '');
  await click('close-zhihu');
  assert.equal(get('zhihu-panel').hidden, true);
  // Web collection mocks only upstream/config endpoints; successful batches are
  // written to the isolated local service, including retries and author grouping.
  const webPreviewPath = '/api/v1/zhihu/web/preview', webConfigPath = '/api/v1/zhihu/web/config';
  const companionStatusPath = '/api/v1/zhihu/companion/status', companionInboxPath = '/api/v1/zhihu/companion/inbox';
  fixtures.set(companionStatusPath, {paired: false, pending_count: 0});
  fixtures.set(companionInboxPath, {items: []});
  fixtures.set('/api/v1/zhihu/web/status', {configured: false});
  await click('open-web-import');
  assert.equal(get('web-import-panel').hidden, false);
  assert.equal(get('zhihu-panel').hidden, true);
  assert.equal(get('import-panel').hidden, true);
  assert.equal(get('run-web-preview').disabled, false, 'Anonymous collection must not require credentials');
  assert.equal(get('web-url').disabled, false);
  assert.equal(document.activeElement, get('refresh-companion'), 'Opening the panel focuses the primary browser collector');
  assert.equal(get('web-direct-panel').open, false, 'Cookie-based direct collection is a collapsed fallback');
  assert.equal(get('web-preview-form').parentNode, get('web-direct-panel'));
  assert.equal(get('web-config-panel').parentNode, get('web-direct-panel'));
  assert.equal(get('web-results').parentNode, get('web-import-panel'), 'Received previews remain visible outside the collapsed direct reader');
  assert.match(get('companion-pair-state').textContent, /尚未连接/);
  assert.match(html, /id="install-companion"[^>]*href="\/assets\/zhihu-companion.user.js"[^>]*target="_blank"/);
  assert.equal(get('web-config-panel').open, false);
  assert.equal(get('web-min-votes').value, '100');
  assert.equal(get('web-max-items').value, '20');
  assert.equal(get('web-cookie').tagName, 'input');
  assert.match(html, /id="web-cookie" type="password"/);
  get('web-cookie').value = 'fake-web-cookie';
  failures.set(webConfigPath, 'Fixture config failure');
  await submit('web-config-form');
  assert.match(get('web-config-status').textContent, /Fixture config failure/);
  assert.equal(get('web-cookie').value, '', 'A failed config submission must clear the password input');
  failures.delete(webConfigPath);
  fixtures.set(webConfigPath, {configured: true});
  get('web-cookie').value = 'fake-web-cookie';
  await submit('web-config-form');
  assert.equal(get('web-cookie').value, '');
  assert.equal(get('clear-web-cookie').disabled, false);
  assert.equal(JSON.parse(requests.filter(row => row.url === webConfigPath).at(-1).options.body).cookie, 'fake-web-cookie');
  assert(![...stored.values()].includes('fake-web-cookie'), 'Cookie must never enter session storage');
  assert.doesNotMatch(allText(get('web-import-panel')), /fake-web-cookie/);
  fixtures.set(webConfigPath, {configured: false});
  await click('clear-web-cookie');
  assert.equal(get('clear-web-cookie').disabled, true);
  assert.equal(get('run-web-preview').disabled, false);
  assert.equal(JSON.parse(requests.filter(row => row.url === webConfigPath).at(-1).options.body).cookie, '');

  const webItems = Array.from({length: 45}, (_, i) => ({
    answer_id: String(9000 + i), question_id: '8000', voteup_count: 1000 - i,
    draft: {title: '完整回答 <script>not code</script> ' + i, author_name: '网页作者',
      author_id: 'zhihu-author:web-fixture', text: '  回答完整正文 ' + i + '\n原始段落，保留换行。\n',
      url: 'https://www.zhihu.com/question/8000/answer/' + (9000 + i), topics: [],
      origin: 'zhihu', content_extent: 'fulltext', provenance: null},
  }));
  const webPreview = {items: webItems, scanned_count: 50, skipped_count: 5, pages_fetched: 3,
    has_more: true, stop_reason: 'max_items', warning: '仅覆盖本次范围', target_label: '测试问题'};
  fixtures.set(webPreviewPath, webPreview);
  get('web-url').value = 'https://www.zhihu.com/question/8000';
  get('web-max-items').value = '45';
  const importsBeforePreview = requests.filter(row => row.url === '/api/v1/sources/import').length;
  await submit('web-preview-form');
  assert.equal(requests.filter(row => row.url === '/api/v1/sources/import').length, importsBeforePreview, 'Preview must not save answers');
  assert.deepEqual(JSON.parse(requests.filter(row => row.url === webPreviewPath).at(-1).options.body), {url: get('web-url').value, mode: 'question', min_votes: 100, max_items: 45});
  assert.equal(get('web-results').children.length, 1, 'Answers share one question heading');
  assert.equal(get('web-results').children[0].children.length, 46);
  assert.match(allText(get('web-results').children[0].children[0]), /45 篇回答/);
  assert.match(get('web-status').textContent, /检查 50 条，略过 5 条/);
  assert.match(get('web-status').textContent, /还有未读取/);
  assert.match(allText(get('web-results')), /完整回答 <script>not code<\/script> 0/);
  assert.match(allText(get('web-results')), /网页作者 · 1000 赞同/);
  assert.equal(get('web-results').children[0].children[1].children[3].children[1].textContent, webItems[0].draft.text);
  sandbox.groupPreview = [webItems[0], {...webItems[0], draft: {...webItems[0].draft, url: 'https://www.zhihu.com/question/8001/answer/9001'}}, {...webItems[0], draft: {...webItems[0].draft, url: 'https://example.com/question/8000/answer/9000'}}];
  vm.runInContext('renderWebResults(groupPreview)', sandbox);
  assert.equal(get('web-results').children.length, 3, 'Equal titles cannot merge different question IDs or untrusted URLs');
  assert.equal(get('web-results').children[2].className, 'zhihu-result web-result', 'Unassociated records remain individual');
  sandbox.originalWebItems = webItems;
  vm.runInContext('renderWebResults(originalWebItems)', sandbox);
  assert.match(get('web-selection-count').textContent, /已选 45 篇/);
  const firstWebCheckbox = vm.runInContext('webImport.results[0].checkbox', sandbox);
  firstWebCheckbox.checked = false; firstWebCheckbox.events.change();
  assert.match(get('web-selection-count').textContent, /已选 44 篇/);
  await click('web-clear-selection');
  assert.equal(get('web-import-selected').disabled, true);
  await click('web-select-all');
  assert.match(get('web-selection-count').textContent, /已选 45 篇/);

  // Lose the response after the second batch was really saved. Only the first
  // batch is acknowledged; retrying the unconfirmed batch must stay duplicate-safe.
  let importBatch = 0;
  responders.set('/api/v1/sources/import', async options => {
    importBatch++;
    if (importBatch !== 2) return undefined;
    const saved = await fetch(base + '/api/v1/sources/import', options);
    assert.equal(saved.status, 200);
    return {ok: false, json: async () => ({error: {message: 'Fixture response lost after save'}})};
  });
  await click('web-import-selected');
  assert.match(get('web-status').textContent, /已确认导入 20 篇，剩余 25 篇未确认/);
  assert.match(get('web-status').textContent, /未确认批次可能已保存/);
  assert.match(get('web-import-selected').textContent, /重试所选（25）/);
  assert.equal(vm.runInContext('webImport.results.filter(row => row.imported).length', sandbox), 20);
  assert.equal(vm.runInContext('webImport.results[0].checkbox.disabled', sandbox), true);
  assert.equal(get('web-import-panel').hidden, false, 'Batch results stay visible for partial completion review');
  responders.delete('/api/v1/sources/import');

  // Freeze a retry in flight, then mutate the backing preview to verify that
  // later chunks use the captured payload, not live selections or edited drafts.
  let releaseWebImport;
  delays.set('/api/v1/sources/import', new Promise(resolve => { releaseWebImport = resolve; }));
  const retry = get('web-import-selected').events.click();
  assert.equal(get('web-url').disabled, true);
  assert.equal(get('web-mode').disabled, true);
  assert.equal(get('web-min-votes').disabled, true);
  assert.equal(get('web-max-items').disabled, true);
  assert.equal(get('web-select-all').disabled, true);
  assert.equal(get('close-web-import').disabled, true);
  assert.equal(vm.runInContext('webImport.results[20].checkbox.disabled', sandbox), true);
  const beforeDuplicateImport = requests.filter(row => row.url === '/api/v1/sources/import').length;
  await get('web-import-selected').events.click();
  assert.equal(requests.filter(row => row.url === '/api/v1/sources/import').length, beforeDuplicateImport);
  vm.runInContext("webImport.results[44].item.draft.text = 'mutated after snapshot'", sandbox);
  releaseWebImport(); await retry; await idle(); delays.delete('/api/v1/sources/import');
  assert.match(get('web-status').textContent, /已确认导入 25 篇/);
  assert.match(get('web-selection-count').textContent, /已选 0 篇 · 已确认导入 45 篇/);
  assert.equal(get('web-import-selected').disabled, true);
  const webImportRequests = requests.filter(row => row.url === '/api/v1/sources/import').slice(importsBeforePreview);
  assert.deepEqual(webImportRequests.map(row => JSON.parse(row.options.body).items.length), [20, 20, 20, 5]);
  assert.equal(JSON.parse(webImportRequests.at(-1).options.body).items.at(-1).text, '  回答完整正文 44\n原始段落，保留换行。\n');
  const savedWeb = await (await apiFetch(base + '/api/v1/sources?author_id=zhihu-author%3Aweb-fixture&limit=100')).json();
  assert.equal(savedWeb.length, 45, 'Retry after a lost response must not duplicate stored answers');
  assert(savedWeb.every(row => row.author_id === 'zhihu-author:web-fixture' && row.content_extent === 'fulltext'));

  get('web-mode').value = 'author'; get('web-mode').events.change();
  assert.equal(get('web-min-votes').value, '0');
  assert.equal(get('web-url-label').textContent, '知乎作者主页链接');
  assert.equal(get('web-results').children.length, 0, 'Changing criteria clears old selections/results');
  get('web-url').value = 'https://www.zhihu.com/people/web-fixture';
  fixtures.set(webPreviewPath, {...webPreview, items: [{...webItems[0], voteup_count: null}]});
  await submit('web-preview-form');
  assert.match(allText(get('web-results')), /赞同数未知/);
  assert.doesNotMatch(allText(get('web-results')), /null 赞同/);
  assert.equal(JSON.parse(requests.filter(row => row.url === webPreviewPath).at(-1).options.body).mode, 'author');
  assert.equal(JSON.parse(requests.filter(row => row.url === webPreviewPath).at(-1).options.body).min_votes, 0);
  // Even a programmatic edit that bypasses input events cannot import stale results.
  get('web-min-votes').value = '5';
  const beforeStaleImport = requests.filter(row => row.url === '/api/v1/sources/import').length;
  await click('web-import-selected');
  assert.equal(requests.filter(row => row.url === '/api/v1/sources/import').length, beforeStaleImport);
  assert.match(get('web-status').textContent, /读取条件已改变/);
  assert.equal(get('web-results').children.length, 0);

  for (const cancel of [false, true]) {
    let releaseWebPreview;
    delays.set(webPreviewPath, new Promise(resolve => { releaseWebPreview = resolve; }));
    const pendingPreview = get('web-preview-form').events.submit({preventDefault() {}});
    assert.equal(get('web-url').disabled, true);
    assert.equal(get('cancel-web-preview').disabled, false);
    assert.equal(get('cancel-web-preview').hidden, false);
    if (cancel) get('cancel-web-preview').events.click();
    else get('web-url').value = 'https://www.zhihu.com/people/changed-during-request';
    releaseWebPreview(); await pendingPreview; await idle(); delays.delete(webPreviewPath);
    assert.equal(get('web-results').children.length, 0, 'Canceled or stale preview must never appear');
    assert.match(get('web-status').textContent, cancel ? /已取消/ : /条件已改变/);
    assert.equal(get('cancel-web-preview').hidden, true);
    assert.equal(get('web-url').disabled, false);
  }
  fixtures.set(webPreviewPath, {...webPreview, items: []});
  await submit('web-preview-form');
  assert.match(allText(get('web-results')), /没有符合条件/);
  assert.equal(get('web-selection-bar').hidden, true);
  const beforeInvalidPreview = requests.filter(row => row.url === webPreviewPath).length;
  get('web-max-items').value = '101';
  await submit('web-preview-form');
  assert.match(get('web-status').textContent, /1 至 100/);
  assert.equal(requests.filter(row => row.url === webPreviewPath).length, beforeInvalidPreview);
  get('web-max-items').value = '20';
  failures.set(webPreviewPath, 'Fixture Zhihu login required');
  await submit('web-preview-form');
  assert.match(get('web-status').textContent, /login required/);
  assert.equal(get('web-results').children.length, 0);
  assert.equal(get('web-selection-bar').hidden, true);
  failures.delete(webPreviewPath);
  get('web-cookie').value = 'unsaved-cookie';
  await click('open-import');
  assert.equal(get('web-cookie').value, '');
  assert.equal(get('web-import-panel').hidden, true);
  await click('open-web-import');
  get('web-cookie').value = 'unsaved-cookie';
  await click('close-web-import');
  assert.equal(get('web-cookie').value, '');
  assert.equal(get('web-import-panel').hidden, true);
  // A browser-delivered batch is a separate preview source. The direct-reader
  // form is unrelated, and receiving/previewing never writes to the library.
  const companionItems = [0, 1].map(i => ({
    answer_id: String(19000 + i), question_id: '18000', voteup_count: 300 - i,
    draft: {title: '浏览器采集 <script>not code</script> ' + i, author_name: '浏览器作者',
      author_id: 'zhihu-author:companion-fixture', text: '  页面已加载的回答 ' + i + '\n保留正文与换行。\n',
      url: 'https://www.zhihu.com/question/18000/answer/' + (19000 + i), topics: [],
      origin: 'zhihu', content_extent: 'unknown', provenance: null},
  }));
  const companionBatchId = 'browser-fixture-1';
  const companionBatchPath = companionInboxPath + '/' + companionBatchId;
  const companionSummary = {batch_id: companionBatchId, count: 2, captured_at: '2026-09-12T10:00:00Z',
    page_url: 'https://www.zhihu.com/people/companion-fixture', scope: 'author', label: '作者页面 <script>not code</script>'};
  fixtures.set(companionStatusPath, {paired: true, pending_count: 1});
  fixtures.set(companionInboxPath, {items: [companionSummary]});
  fixtures.set(companionBatchPath, {batch_id: companionBatchId, items: companionItems, scanned_count: 3,
    skipped_count: 1, pages_fetched: 0, has_more: true, stop_reason: 'visible_page',
    warning: '完整性未核验', target_label: '浏览器作者'});
  const beforeReceiving = requests.filter(row => row.url === '/api/v1/sources/import').length;
  sandbox.location.hash = '#companion'; windowEvents.hashchange(); await idle();
  assert.equal(get('web-import-panel').hidden, false, 'Returning from the script opens the collector by hash');
  assert.match(get('companion-pair-state').textContent, /已连接/);
  assert.equal(get('companion-inbox').children.length, 1);
  assert.match(allText(get('companion-inbox')), /作者页面 <script>not code<\/script>/);
  assert.match(get('companion-status').textContent, /等待你预览/);
  const companionAction = index => get('companion-inbox').children[0].children[3].children[index];
  await companionAction(0).click(); await idle();
  assert.equal(requests.filter(row => row.url === '/api/v1/sources/import').length, beforeReceiving, 'Receiving and previewing require a separate import action');
  assert.equal(get('web-results').children.length, 1);
  assert.match(allText(get('web-results')), /页面已加载内容 · 完整性未核验/);
  assert.doesNotMatch(allText(get('web-results')), /查看完整原文/);
  assert.match(get('web-status').textContent, /尚未保存/);
  assert.match(get('web-status').textContent, /还有未加载/);
  assert.match(get('web-status').textContent, /略过 1 条/);
  // Hidden direct HTTP criteria cannot invalidate a received batch or change its payload.
  get('web-url').value = 'https://www.zhihu.com/question/unrelated';
  get('web-url').events.input();
  get('web-min-votes').value = '500';
  assert.equal(get('web-results').children.length, 1);
  await click('refresh-companion');
  assert.equal(get('web-results').children.length, 1, 'Refreshing the inbox preserves the reviewed batch and choices');
  await click('web-import-selected');
  assert.match(get('web-status').textContent, /已确认导入 2 篇/);
  assert.equal(get('web-import-selected').disabled, true);
  let savedCompanion = await (await apiFetch(base + '/api/v1/sources?author_id=zhihu-author%3Acompanion-fixture&limit=100')).json();
  assert.equal(savedCompanion.length, 2);
  assert(savedCompanion.every(row => row.author_id === 'zhihu-author:companion-fixture' && row.content_extent === 'unknown'));
  assert.deepEqual(savedCompanion.map(row => row.text).sort(), companionItems.map(row => row.draft.text).sort());
  await companionAction(0).click(); await idle();
  await click('web-import-selected');
  savedCompanion = await (await apiFetch(base + '/api/v1/sources?author_id=zhihu-author%3Acompanion-fixture&limit=100')).json();
  assert.equal(savedCompanion.length, 2, 'Reopening and importing a received batch is duplicate-safe');

  failures.set(companionBatchPath, 'Fixture received batch expired');
  await companionAction(0).click(); await idle();
  assert.match(get('web-status').textContent, /received batch expired/);
  assert.equal(get('web-results').children.length, 0, 'Failed batch lookup cannot leave a previous batch selected');
  assert.equal(get('web-import-selected').disabled, true);
  failures.delete(companionBatchPath);
  const companionPreview = fixtures.get(companionBatchPath);
  fixtures.set(companionBatchPath, {...companionPreview, batch_id: 'different-batch'});
  await companionAction(0).click(); await idle();
  assert.match(get('web-status').textContent, /批次不匹配/);
  assert.equal(get('web-results').children.length, 0);
  fixtures.set(companionBatchPath, companionPreview);
  await companionAction(0).click(); await idle();
  failures.set(companionInboxPath, 'Fixture inbox unavailable');
  await click('refresh-companion');
  assert.match(get('companion-status').textContent, /inbox unavailable/);
  assert.equal(get('web-results').children.length, 1, 'Inbox refresh errors must preserve an already reviewed batch');
  failures.delete(companionInboxPath);
  fixtures.set(companionBatchPath + '/dismiss', {removed: true});
  fixtures.set(companionInboxPath, {items: []});
  await companionAction(1).click(); await idle();
  assert.equal(get('companion-inbox').children.length, 0);
  assert.equal(get('web-results').children.length, 0, 'Dismissing the active batch clears its pending selection');
  assert.equal((await (await apiFetch(base + '/api/v1/sources?author_id=zhihu-author%3Acompanion-fixture&limit=100')).json()).length, 2, 'Dismissing a batch preserves imported library sources');
  assert(!requests.some(row => /companion\/(pair|key|token)/.test(row.url)), 'Workspace must not fetch or display the browser bridge secret');
  get('source-filter').value = 'zhihu-author:companion-fixture';
  await submit('source-filter-form');
  sandbox.savedCompanionSource = savedCompanion[0];
  vm.runInContext('select(savedCompanionSource)', sandbox);
  assert.equal(get('selected-extent').hidden, false);
  assert.match(get('selected-extent').textContent, /完整性未核验/);
  assert.equal(get('source-preview-label').textContent, '查看已导入内容');
  assert.match(allText(get('source-list')), /完整性未核验/);
  for (const [key, value] of stored) {
    assert(!key.includes(pageToken) && !value.includes(pageToken), 'Browser storage must not persist the API credential');
  }
  const companionCases = ['companion served userscript metadata', 'companion paired and unpaired status', 'companion hash opens receiver', 'companion no automatic import', 'companion direct criteria independent of received batch', 'companion inbox refresh preserves reviewed choices', 'companion conservative content extent and exact text', 'companion real author grouping and duplicate-safe import', 'companion expired or mismatched batch clears stale preview', 'companion inbox failure preserves reviewed batch', 'companion dismiss preserves saved sources', 'companion no bridge secret retrieval', 'companion imported content retains completeness notice'];
  console.log(JSON.stringify({passed: true, scope: 'UI handlers plus real isolated HTTP; Zhihu and companion inbox responses mocked; no browser rendering', cases: [...companionCases, 'empty library', 'manual and JSON import', 'source fidelity', 'reading', 'author scope and citations', 'cards', 'TSV and APKG downloads', 'fact exclusion and validation', 'graph interaction', 'failure clears stale exports', 'pagination and filters', 'keyboard tabs', 'unsafe URL rejected', 'Zhihu credential gating and clearing', 'Zhihu search request and text rendering', 'excerpt import and content-scoped author identity', 'imported button stays disabled', 'Zhihu count validation and upstream error', 'empty search results', 'empty-state entry and mutually exclusive panels', 'compact excerpt disclosure', 'responsive library and return to reading', 'floating chat open close Escape and source gating', 'chat source request and safe cited response', 'chat Enter Shift and IME composition', 'chat history reset and stale response isolation', 'chat close remains usable while busy and duplicate submit blocked', 'web anonymous preview and safe full text rendering', 'web session Cookie clear on success error and close', 'web 45-answer batches and author grouping', 'web lost-response retry without duplicates', 'web immutable import and disabled controls', 'web question author defaults and bounds', 'web stale criteria and cancellation isolation', 'web empty and upstream failure reset']}));
})().catch(error => { console.error(error); process.exitCode = 1; });
