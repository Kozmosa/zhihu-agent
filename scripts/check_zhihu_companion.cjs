#!/usr/bin/env node
'use strict';
// Synthetic DOM/bridge checks; never loads Zhihu or a real user's browser state.
// Usage: node scripts/check_zhihu_companion.cjs [path/to/jsdom]
// Optional ZHIJING_COMPANION_FIXTURE exports a synthetic receive payload inside the workspace.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
let JSDOM;
try {
  ({ JSDOM } = require(process.argv[2] ? path.resolve(process.argv[2]) : 'jsdom'));
} catch (firstError) {
  const workspaceDependency = path.resolve(__dirname, '../../codex/tools/node/node_modules/jsdom');
  try { ({ JSDOM } = require(workspaceDependency)); }
  catch (_) {
    process.stderr.write('Install test-only jsdom, then pass its module path or set NODE_PATH.\n');
    process.exit(2);
  }
}
const scriptPath = path.resolve(__dirname, '../src/zhijing/web/zhihu-companion.user.js');
const source = fs.readFileSync(scriptPath, 'utf8');
const exposed = ['loopbackBase', 'pageScope', 'answerIdentity', 'authorIdentity', 'readVotes', 'contentExtent', 'collectItem', 'gatherItems', 'contentContainers', 'cleanAndMarkdown', 'normalizeHref', 'deliver', 'retryDelivery', 'discardPendingDelivery', 'getConnection', 'sendCurrentContent', 'openCollectionPanel'];
const instrumented = source.replace(/\}\)\(\);\s*$/, `window.__test = {${exposed.join(',')}};})();`);
const connectionKey = 'ZHIJING_COMPANION_CONNECTION_V1';
const fakeToken = 'fixture-connection-token-not-a-secret';
const tick = () => new Promise(resolve => setImmediate(resolve));
const windows = [];
let syntheticCapture;

function browser(url, html = '', options = {}) {
  const dom = new JSDOM('<!doctype html><html><head></head><body>' + html + '</body></html>', { url, runScripts: 'outside-only', pretendToBeVisual: true });
  windows.push(dom.window);
  const { window } = dom;
  const store = new Map(options.paired === false ? [] : [[connectionKey, { base_url: 'http://127.0.0.1:8765', token: fakeToken }]]);
  const requests = [], fetches = [], messages = [], clipboard = [];
  Object.defineProperty(window.document, 'cookie', { get() { throw new Error('Credential access is forbidden'); }, set() { throw new Error('Credential writes are forbidden'); } });
  for (const key of ['localStorage', 'sessionStorage']) Object.defineProperty(window, key, { get() { throw new Error('Browser storage is forbidden'); } });
  window.GM_getValue = (key, fallback) => store.has(key) ? store.get(key) : fallback;
  window.GM_setValue = (key, value) => store.set(key, value);
  window.GM_registerMenuCommand = () => {};
  window.GM_setClipboard = text => clipboard.push(text);
  window.GM_xmlhttpRequest = request => {
    requests.push(request);
    if (options.request) options.request(request, requests.length);
    else request.onload({ status: 200, finalUrl: request.url, responseText: JSON.stringify({ batch_id: 'fixture-batch', count: JSON.parse(request.data).items.length, duplicate: false }) });
  };
  window.fetch = async (url, request) => {
    fetches.push({ url, ...request });
    return { ok: true, json: async () => ({ token: fakeToken }) };
  };
  window.alert = message => messages.push(message);
  window.confirm = () => options.confirm !== false;
  window.scrollBy = () => {};
  window.eval(instrumented);
  window.document.dispatchEvent(new window.Event('DOMContentLoaded'));
  return { window, document: window.document, api: window.__test, store, requests, fetches, messages, clipboard };
}

function answer({ id = '101', question = '10', author = 'alice', authorName = '甲作者', title = '局部问题没有问号', votes = '123', content = '<p>第一段正文。<strong>重点</strong></p><p>第二段正文。</p>', collapsed = false, meta = true } = {}) {
  const data = JSON.stringify({ type: 'answer', itemId: id, title, authorName }).replaceAll("'", '&#39;');
  return `<div class="ContentItem AnswerItem" data-zop='${data}'>${meta ? `<meta itemprop="url" content="https://www.zhihu.com/question/${question}/answer/${id}">` : ''}<h2><a href="/question/${question}">${title}</a></h2><div class="AuthorInfo"><div class="AuthorInfo-name">${author ? `<a class="UserLink-link" href="/people/${author}">${authorName}</a>` : authorName}</div></div><button class="VoteButton--up">赞同 ${votes}</button><div class="RichContent${collapsed ? ' is-collapsed' : ''}"><div class="RichContent-inner"><span class="RichText" itemprop="text">${content}</span></div>${collapsed ? '<button class="ContentItem-more">阅读全文</button>' : ''}</div></div>`;
}

const tests = [];
const test = (name, run) => tests.push({ name, run });

test('metadata limits hosts and contains no credential APIs or remote dependencies', () => {
  assert.match(source, /@name\s+知乎伴侣·知境版/);
  assert.match(source, /@version\s+0\.8\.5/);
  assert.match(source, /Kozmosa（原版 0\.8\.2）/);
  assert.deepEqual([...source.matchAll(/@connect\s+(\S+)/g)].map(match => match[1]), ['127.0.0.1', 'localhost']);
  assert.doesNotMatch(source, /document\s*\.\s*cookie|localStorage|sessionStorage|@require|@grant\s+GM_cookie|headers\s*:\s*\{[^}]*\bCookie\b/s);
  assert.doesNotMatch(source, /console\.log\([^\n]*(?:finalMarkdown|jsonObj)/);
});

test('single answer retains full paragraphs, identity, author and DOM uncertainty', () => {
  const b = browser('https://www.zhihu.com/question/10/answer/101', answer());
  const item = b.api.collectItem(b.document.querySelector('.AnswerItem'), b.api.pageScope());
  assert.equal(item.external_id, '101'); assert.equal(item.question_id, '10');
  assert.equal(item.author_url, 'https://www.zhihu.com/people/alice');
  assert.equal(item.author_name, '甲作者'); assert.equal(item.title, '局部问题没有问号');
  assert.match(item.text, /第一段正文/); assert.match(item.text, /第二段正文/);
  assert.equal(item.content_extent, 'unknown'); assert.equal(item.voteup_count, 123);
  assert.equal(item.voteup_is_approximate, false); assert.match(item.captured_at, /Z$/);
});

test('question batches filter votes, remove duplicates, and reject foreign question cards', () => {
  const b = browser('https://www.zhihu.com/question/10?utm=ignored', answer({ id: '101', votes: '12' }) + answer({ id: '102', votes: '1.2 万' }) + answer({ id: '102', votes: '1.2 万' }) + answer({ id: '103', question: '11', votes: '99999' }));
  const result = b.api.gatherItems(b.api.pageScope(), 100, 20);
  assert.equal(result.items.length, 1); assert.equal(result.items[0].external_id, '102');
  assert.equal(result.items[0].voteup_count, 12000); assert.equal(result.items[0].voteup_is_approximate, true);
  assert.equal(b.api.pageScope().page_url, 'https://www.zhihu.com/question/10');
});

test('author feed keeps individual titles and exact author matching', () => {
  const html = '<h1 class="QuestionHeader-title">全局错误题目？</h1>' + answer({ id: '101', title: '第一篇无问号题目' }) + answer({ id: '102', question: '11', title: '第二篇题目' }) + answer({ id: '103', author: 'someone-else' });
  const b = browser('https://www.zhihu.com/people/alice/answers', html);
  const result = b.api.gatherItems(b.api.pageScope());
  assert.equal(result.items.length, 2);
  assert.equal(result.items[0].title, '第一篇无问号题目'); assert.equal(result.items[1].title, '第二篇题目');
  assert.deepEqual(Array.from(result.items, item => item.question_id), ['10', '11']);
});

test('unidentified cards and referenced answer hyperlinks cannot impersonate current answer', () => {
  const b = browser('https://www.zhihu.com/question/10', '<div class="AnswerItem"><span itemprop="text"><a href="/question/10/answer/999">quoted other answer</a>正文</span></div>');
  assert.equal(b.api.gatherItems(b.api.pageScope()).items.length, 0);
  assert.equal(b.api.collectItem(b.document.body, b.api.pageScope()), null);
});

test('missing author remains unknown and is excluded from author grouping', () => {
  const question = browser('https://www.zhihu.com/question/10', answer({ author: null, authorName: '' }));
  const item = question.api.gatherItems(question.api.pageScope()).items[0];
  assert.equal(item.author_url, null); assert.equal(item.author_name, '未知作者');
  const author = browser('https://www.zhihu.com/people/alice/answers', answer({ author: null, authorName: '' }));
  assert.equal(author.api.gatherItems(author.api.pageScope()).items.length, 0);
});

test('collapsed content is marked excerpt, skipped until actual expansion', async () => {
  const b = browser('https://www.zhihu.com/question/10', answer({ collapsed: true }));
  const container = b.document.querySelector('.AnswerItem');
  assert.equal(b.api.collectItem(container, b.api.pageScope()).content_extent, 'excerpt');
  assert.equal(b.api.gatherItems(b.api.pageScope()).items.length, 0);
  await assert.rejects(b.api.deliver(b.api.pageScope(), [b.api.collectItem(container, b.api.pageScope())]), /折叠/);
  container.querySelector('.RichContent').classList.remove('is-collapsed');
  container.querySelector('.ContentItem-more').remove();
  assert.equal(b.api.gatherItems(b.api.pageScope()).items.length, 1);
});

test('original Markdown converter retains semantic blocks and strips unsafe elements and URLs', () => {
  const content = '<h2>标题</h2><p>正文 <strong>粗体</strong><em>斜体</em><span data-tex="x^2">x</span><a href="/question/20">相对链接</a><a href="javascript:alert(1)">危险链接</a></p><blockquote><p>引用</p></blockquote><ul><li>条目</li></ul><pre><code class="language-js">const fence = "```";</code></pre><figure><img data-original="https://pic.zhimg.com/photo.jpg" alt="图"><figcaption>图注</figcaption></figure><img src="data:text/html,unsafe"><table><tr><th>甲</th><th>乙</th></tr><tr><td>A</td><td>B</td></tr></table><script>bad()</script><iframe src="https://example.test"></iframe>';
  const b = browser('https://www.zhihu.com/question/10', answer({ content }));
  const text = b.api.gatherItems(b.api.pageScope()).items[0].text;
  for (const expected of ['## 标题', '**粗体**', '*斜体*', '$x^2$', '> 引用', '- 条目', '````js', '![图](https://pic.zhimg.com/photo.jpg)', '| 甲 | 乙 |', '[相对链接](https://www.zhihu.com/question/20)']) assert.ok(text.includes(expected), expected);
  assert.doesNotMatch(text, /javascript:|data:text|bad\(\)|iframe/);
  assert.equal(b.api.normalizeHref('https://user:pass@example.test/a'), '');
});

test('article collection preserves article identity and Markdown', () => {
  const b = browser('https://zhuanlan.zhihu.com/p/987', '<article class="Post-Main"><h1 class="Post-Title">专栏标题</h1><div class="AuthorInfo"><div class="AuthorInfo-name"><a href="https://www.zhihu.com/people/alice">作者甲</a></div></div><div class="Post-RichTextContainer"><div class="RichText Post-RichText"><p>专栏正文</p></div></div></article>');
  const item = b.api.gatherItems(b.api.pageScope()).items[0];
  assert.equal(item.content_type, 'article'); assert.equal(item.external_id, '987'); assert.equal(item.question_id, null);
  assert.equal(item.url, 'https://zhuanlan.zhihu.com/p/987'); assert.equal(item.title, '专栏标题');
});

test('loopback allowlist rejects external, credentialed, path-bearing and HTTPS destinations', () => {
  const b = browser('https://www.zhihu.com/question/10', answer());
  for (const url of ['https://127.0.0.1:8765', 'http://127.0.0.1.evil.test', 'http://localhost@evil.test', 'http://localhost/path', 'http://localhost?x=1', 'http://localhost#token', 'http://192.168.0.1']) assert.equal(b.api.loopbackBase(url), null);
  assert.equal(b.api.loopbackBase('http://localhost:8765'), 'http://localhost:8765');
});

test('workspace pairing runs only on official exact workspace path and stores connection in GM storage', async () => {
  const html = '<script src="/assets/workspace.js" data-config-token="fixture-config-token"></script>';
  const b = browser('http://127.0.0.1:8765/workspace', html, { paired: false });
  assert.equal(b.fetches.length, 0);
  b.document.getElementById('__zhijing_pair__').click(); await tick();
  assert.equal(b.fetches.length, 1); assert.equal(b.fetches[0].url, 'http://127.0.0.1:8765/api/v1/zhihu/companion/pair');
  assert.equal(b.fetches[0].credentials, 'omit'); assert.equal(b.fetches[0].redirect, 'error');
  assert.equal(b.fetches[0].headers['X-Zhijing-Token'], 'fixture-config-token');
  assert.equal(b.store.get(connectionKey).token, fakeToken);
  assert.ok(!b.document.body.textContent.includes(fakeToken));
  const wrong = browser('http://127.0.0.1:8765/workspace/evil', html, { paired: false });
  assert.equal(wrong.document.getElementById('__zhijing_pair__'), null); assert.equal(wrong.fetches.length, 0);
});

test('failed send retains exact request_id and payload for retry; successful receive links back to preview', async () => {
  const b = browser('https://www.zhihu.com/question/10/answer/101', answer(), { request: (request, n) => n === 1 ? request.onerror() : request.onload({ status: 200, finalUrl: request.url, responseText: '{"batch_id":"retry-batch","count":1,"duplicate":true}' }) });
  const scope = b.api.pageScope(); const items = b.api.gatherItems(scope).items;
  await assert.rejects(b.api.deliver(scope, items), /无法连接知境/);
  const result = await b.api.retryDelivery(true);
  assert.equal(result.batch_id, 'retry-batch'); assert.equal(b.requests.length, 2);
  assert.equal(b.requests[0].data, b.requests[1].data);
  assert.equal(b.requests[0].anonymous, true); assert.equal(b.requests[0].redirect, 'error');
  assert.equal(b.requests[0].headers['X-Zhijing-Companion'], fakeToken);
  assert.deepEqual(Object.keys(b.requests[0].headers).sort(), ['Content-Type', 'X-Zhijing-Companion']);
  const payload = JSON.parse(b.requests[0].data);
  syntheticCapture = payload;
  assert.match(payload.request_id, /^[0-9a-f-]{36}$/); assert.ok(!b.requests[0].data.includes(fakeToken));
  assert.equal(b.document.getElementById('__zhijing_return__').href, 'http://127.0.0.1:8765/workspace#companion');
});

test('answer detail sends its own answer, not a preceding recommended answer', async () => {
  const b = browser('https://www.zhihu.com/question/10/answer/102', answer({ id: '101' }) + answer({ id: '102' }));
  await b.api.sendCurrentContent();
  const payload = JSON.parse(b.requests[0].data);
  assert.equal(payload.items.length, 1); assert.equal(payload.items[0].external_id, '102');
});

test('question page header wins over nested author metadata for all five answers', () => {
  const names = ['Jhon Smith', '忧郁的Tom', '宝塔山赵四', '猴姆', '鹅妈妈密密麻麻'];
  const html = '<h1 class="QuestionHeader-title">这才是五篇回答共同的问题？</h1>' + names.map((name, i) => answer({id:String(101+i), authorName:name})).join('');
  const b = browser('https://www.zhihu.com/question/10', html);
  for (const item of b.document.querySelectorAll('.AnswerItem')) {
    item.querySelector('h2').remove();
    item.removeAttribute('data-zop');
    item.querySelector('.AuthorInfo').innerHTML += '<span itemprop="author" itemtype="http://schema.org/Person"><meta itemprop="name" content="Jhon Smith"></span>';
  }
  const items = b.api.gatherItems(b.api.pageScope()).items;
  assert.equal(items.length, 5);
  assert(items.every(item => item.title === '这才是五篇回答共同的问题？'));
  assert.deepEqual(Array.from(items, item=>item.author_name), names);
});

test('author metadata cannot become a missing question title or overwrite another question', () => {
  const b = browser('https://www.zhihu.com/people/alice/answers', answer());
  const item = b.document.querySelector('.AnswerItem');
  item.querySelector('h2').remove(); item.removeAttribute('data-zop');
  item.querySelector('.AuthorInfo').innerHTML += '<span itemprop="author" itemtype="http://schema.org/Person"><meta itemprop="name" content="Jhon Smith"></span>';
  assert.equal(b.api.gatherItems(b.api.pageScope()).items[0].title, '未提供题目');
  const other = browser('https://www.zhihu.com/question/10', '<h1 class="QuestionHeader-title">当前问题</h1>' + answer({question:'11', title:'另一个问题'}));
  const collected = other.api.collectItem(other.document.querySelector('.AnswerItem'), {scope:'page'});
  assert.equal(collected.title,'另一个问题');
});

test('request size is rejected before any content is silently truncated or sent', async () => {
  const b = browser('https://www.zhihu.com/question/10', answer());
  const item = b.api.gatherItems(b.api.pageScope()).items[0]; item.text = '字'.repeat(100001);
  await assert.rejects(b.api.deliver(b.api.pageScope(), [item]), /10 万字/);
  assert.equal(b.requests.length, 0);
});

test('batch panel defaults to loaded DOM only and user click sends selected-limit result', async () => {
  const b = browser('https://www.zhihu.com/question/10', answer({ id: '101', votes: '10' }) + answer({ id: '102', votes: '100' }));
  b.api.openCollectionPanel();
  const panel = b.document.getElementById('__zhijing_collect_panel__');
  assert.equal(panel.querySelector('#__zj_scroll__').checked, false);
  assert.match(panel.querySelector('#__zj_scope__').textContent, /当前问题：10.*多位作者/);
  assert.match(panel.querySelector('#__zj_connection__').textContent, /发送时验证/);
  assert.doesNotMatch(panel.textContent, new RegExp(fakeToken));
  assert.equal(b.requests.length, 0, 'Opening panel must not send data');
  panel.querySelector('#__zj_votes__').value = '50'; panel.querySelector('#__zj_limit__').value = '1';
  Array.from(panel.querySelectorAll('button')).find(button => button.textContent === '开始收集并发送').click();
  await tick();
  assert.equal(b.requests.length, 1); assert.equal(JSON.parse(b.requests[0].data).items[0].external_id, '102');
  assert.match(panel.querySelector('#__zj_connection__').textContent, /连接正常/);
  assert.match(panel.querySelector('[role="status"]').textContent, /涉及 1 个问题/);
  assert.equal(panel.querySelector('#__zj_votes__').disabled, false);
});

test('author and unpaired panels describe scope honestly without network or secrets', async () => {
  const b = browser('https://www.zhihu.com/people/alice/answers', answer(), {paired: false});
  b.api.openCollectionPanel();
  const panel = b.document.getElementById('__zhijing_collect_panel__');
  assert.match(panel.querySelector('#__zj_scope__').textContent, /当前作者：alice.*按问题预览/);
  assert.match(panel.querySelector('#__zj_connection__').textContent, /尚未连接/);
  Array.from(panel.querySelectorAll('button')).find(button => button.textContent === '开始收集并发送').click();
  await tick();
  assert.equal(b.requests.length, 0);
  assert.equal(panel.querySelector('#__zj_limit__').disabled, false);
  assert.match(panel.querySelector('[role="status"]').textContent, /连接当前知境/);
});

test('queue-full errors explain resolution and explicit discard unblocks fresh collection', async () => {
  const b = browser('https://www.zhihu.com/question/10', answer(), { request: (request, n) => n === 1 ? request.onload({ status: 429, finalUrl: request.url }) : request.onload({ status: 200, finalUrl: request.url, responseText: '{"batch_id":"new-batch","count":1}' }) });
  const scope = b.api.pageScope(), items = b.api.gatherItems(scope).items;
  await assert.rejects(b.api.deliver(scope, items), /导入并移除已处理批次/);
  await assert.rejects(b.api.deliver(scope, items), /上次发送尚未确认/);
  b.api.discardPendingDelivery();
  await b.api.deliver(scope, items);
  assert.equal(b.requests.length, 2);
  assert.notEqual(JSON.parse(b.requests[0].data).request_id, JSON.parse(b.requests[1].data).request_id);
});

test('redirected receive responses are rejected without a second request', async () => {
  const b = browser('https://www.zhihu.com/question/10', answer(), { request: request => request.onload({ status: 200, finalUrl: 'https://evil.test/receive', responseText: '{"batch_id":"fake","count":1}' }) });
  await assert.rejects(b.api.deliver(b.api.pageScope(), b.api.gatherItems(b.api.pageScope()).items), /跳转/);
  assert.equal(b.requests.length, 1); assert.equal(b.document.getElementById('__zhijing_return__'), null);
});

test('automatic collection expands ordinary buttons and cancellation prevents delivery', async () => {
  const b = browser('https://www.zhihu.com/question/10', answer({ collapsed: true }));
  const originalTimeout = b.window.setTimeout.bind(b.window);
  b.window.setTimeout = callback => originalTimeout(callback, 0);
  const more = b.document.querySelector('.ContentItem-more');
  more.addEventListener('click', () => { b.document.querySelector('.RichContent').classList.remove('is-collapsed'); more.remove(); });
  b.api.openCollectionPanel();
  const panel = b.document.getElementById('__zhijing_collect_panel__');
  panel.querySelector('#__zj_scroll__').checked = true;
  panel.querySelector('#__zj_limit__').value = '1';
  Array.from(panel.querySelectorAll('button')).find(button => button.textContent === '开始收集并发送').click();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(b.requests.length, 1); assert.equal(JSON.parse(b.requests[0].data).items[0].content_extent, 'unknown');
  const cancel = browser('https://www.zhihu.com/question/10', answer());
  const timer = cancel.window.setTimeout.bind(cancel.window); cancel.window.setTimeout = callback => timer(callback, 0);
  cancel.api.openCollectionPanel();
  const cp = cancel.document.getElementById('__zhijing_collect_panel__'); cp.querySelector('#__zj_scroll__').checked = true;
  Array.from(cp.querySelectorAll('button')).find(button => button.textContent === '开始收集并发送').click();
  Array.from(cp.querySelectorAll('button')).find(button => button.textContent === '取消／关闭').click();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(cancel.requests.length, 0); assert.match(cp.textContent, /已取消/);
});

test('author DOM batch exports a two-answer cross-layer integration fixture', async () => {
  const contentOne = '<h2>合成资料一</h2><p>第一份证据，保留<strong>关键论点</strong>。</p><blockquote><p>引用原句一。</p></blockquote>';
  const contentTwo = '<p>第二份证据，保留原始结构。</p><ul><li>独立条目甲</li><li>独立条目乙</li></ul><p><a href="https://www.zhihu.com/question/20">来源链接</a></p>';
  const b = browser('https://www.zhihu.com/people/alice/answers', answer({ id: '101', question: '10', title: '合成问题一', votes: '123', content: contentOne }) + answer({ id: '102', question: '11', title: '合成问题二', votes: '456', content: contentTwo }));
  await b.api.deliver(b.api.pageScope(), b.api.gatherItems(b.api.pageScope()).items);
  syntheticCapture = JSON.parse(b.requests[0].data);
  assert.equal(syntheticCapture.scope, 'author'); assert.equal(syntheticCapture.scope_id, 'alice');
  assert.equal(syntheticCapture.items.length, 2);
  assert.ok(syntheticCapture.items.every(item => item.author_url === 'https://www.zhihu.com/people/alice'));
});

(async () => {
  let passed = 0;
  try {
    for (const { name, run } of tests) {
      await run(); passed++; process.stdout.write('PASS ' + name + '\n');
    }
    if (process.env.ZHIJING_COMPANION_FIXTURE) {
      const output = path.resolve(process.env.ZHIJING_COMPANION_FIXTURE);
      const workspace = path.resolve(__dirname, '../..');
      assert.ok(output.toLowerCase().startsWith((workspace + path.sep).toLowerCase()), 'Fixture output must remain inside the workspace');
      fs.mkdirSync(path.dirname(output), { recursive: true });
      fs.writeFileSync(output, JSON.stringify(syntheticCapture, null, 2) + '\n', 'utf8');
      process.stdout.write('Synthetic receive payload: ' + output + '\n');
    }
    process.stdout.write(`${passed} userscript DOM/bridge checks passed. Synthetic fixtures only; live Zhihu access is not established.\n`);
  } finally { for (const window of windows) window.close(); }
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
