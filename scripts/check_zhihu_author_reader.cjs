// Runs the actual DOM reader and import handlers in jsdom with synthetic pages only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require(process.argv[2] || 'jsdom');
const root = path.join(__dirname, '../src/zhijing/web');
const reader = fs.readFileSync(path.join(root, 'zhihu-question-reader.js'), 'utf8');
const checks = [];
const answer = (qid, aid, author = 'alice', title = '问题 ' + qid, extra = '') => `
<article class="AnswerItem" data-zop='{"itemId":"${aid}","type":"answer"}'>
<h2 class="ContentItem-title"><a href="/question/${qid}">${title}</a></h2>
<meta itemprop="url" content="https://www.zhihu.com/question/${qid}/answer/${aid}">
<div class="AuthorInfo"><a class="AuthorInfo-name" href="/people/${author}">同名作者</a></div>
<div class="RichContent"><div class="RichContent-inner"><div class="RichText">完整性未核验的合成正文。</div></div></div>${extra}</article>`;
function read(html, target = {mode: 'author', author_id: 'people:alice'}, url = 'https://www.zhihu.com/people/alice/answers') {
  const dom = new JSDOM('<h1>作者主页</h1>' + html, {url, runScripts: 'outside-only'});
  const {window} = dom;
  window.HTMLElement.prototype.getClientRects = function () { return this.closest('[hidden]') ? [] : [{}]; };
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', {get() {return this.textContent;}});
  window.scrollBy = () => {};
  try { return window.eval(reader.replace('__ZHIHU_READER_REQUEST__', JSON.stringify({...target, count: 20}))); }
  finally { window.close(); }
}
let result = read(answer('123', '1') + answer('456', '2'));
assert.deepEqual(Array.from(result.items, item => item.question_id), ['123', '456']);
assert.equal(result.items[1].title, '问题 456'); checks.push('same author across questions retains question titles');
result = read(answer('123', '1', 'bob') + answer('456', '2').replace('/people/alice', '/people/'));
assert.equal(result.items.length, 0); checks.push('same nickname and missing identity cannot enter author scope');
result = read(answer('123', '1').replace('question/123/answer/1', 'question/123/answer/2'));
assert.equal(result.items.length, 0); checks.push('conflicting answer identifiers rejected');
result = read(answer('123', '1').replace('href="/question/123"', 'href="/question/999"'));
assert.equal(result.items.length, 0); checks.push('title must identify the same question');
result = read(answer('123', '1', 'alice', '问题', '<button>开通会员后查看</button>'));
assert.equal(result.items.length, 0); checks.push('paid content skipped');
result = read('<div class="Captcha">验证</div>' + answer('123', '1'));
assert.equal(result.state, 'needs_login'); checks.push('verification pauses collection');
result = read(answer('123', '1'), {mode: 'author', author_id: 'people:alice'}, 'https://www.zhihu.com/people/bob/answers');
assert.equal(result.state, 'away'); checks.push('navigation to another author is not collected');
result = read(answer('123', '1') + answer('456', '2'), {question_id: '123'}, 'https://www.zhihu.com/question/123');
assert.equal(result.items.length, 1); checks.push('question mode retains strict question scope');

(async () => {
  const dom = new JSDOM('<button id="read-author" data-open-question-import data-reader-mode="author">读作者</button>', {
    url: 'http://127.0.0.1:8100/workspace', runScripts: 'outside-only',
  });
  const {window} = dom, calls = [];
  const $ = id => window.document.getElementById(id);
  Object.defineProperty(window.document, 'currentScript', {value: {dataset: {configToken: 'synthetic-token'}}});
  window.HTMLDialogElement.prototype.showModal = function () {this.open = true;};
  window.HTMLDialogElement.prototype.close = function () {this.open = false; this.dispatchEvent(new window.Event('close'));};
  window.fetch = async (url, options) => {
    calls.push({url, body: JSON.parse(options.body), headers: options.headers});
    return {ok: true, json: async () => ({id: 'synthetic-job', mode: 'author', status: 'ready', terminal: true, requested_count: 5,
      items: [{title: '如何读懂问题？', author_id: 'zhihu-author:people:alice', author_name: '作者', text: '合成回答', url: 'https://www.zhihu.com/question/123/answer/1'}]})};
  };
  const tick = () => new Promise(resolve => setTimeout(resolve, 10));
  try {
    window.eval(fs.readFileSync(path.join(root, 'question-import.js'), 'utf8'));
    $('read-author').click();
    assert.equal($('question-import-mode').value, 'author');
    assert.match($('question-import-title').textContent, /读作者/);
    $('question-import-url').value = 'https://www.zhihu.com/people/alice';
    $('question-import-form').dispatchEvent(new window.Event('submit', {cancelable: true})); await tick();
    assert.equal(calls.length, 1); assert.equal(calls[0].body.url, 'https://www.zhihu.com/people/alice');
    assert.equal(calls[0].headers['X-Zhijing-Token'], 'synthetic-token');
    assert.match($('question-import-results').textContent, /如何读懂问题/);
    assert.equal($('question-import-save').disabled, false);
    assert.equal(calls.some(call => call.url === '/api/v1/sources/import'), false);
    checks.push('author shortcut, guarded request and preview before import');
    $('question-import-mode').value = 'question'; $('question-import-mode').dispatchEvent(new window.Event('change'));
    $('question-import-url').value = 'https://www.zhihu.com/people/alice';
    $('question-import-form').dispatchEvent(new window.Event('submit', {cancelable: true})); await tick();
    assert.equal(calls.length, 1); checks.push('mode mismatch rejected without request');
  } finally {window.close();}
  console.log(JSON.stringify({passed: checks.length, scope: 'Synthetic jsdom; no live Zhihu or browser rendering', checks}));
})().catch(error => {console.error(error); process.exitCode = 1;});
