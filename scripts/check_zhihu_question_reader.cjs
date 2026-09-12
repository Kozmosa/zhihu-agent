/* Offline DOM checks. Install Playwright for development or set PLAYWRIGHT_MODULE to its location. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const script = fs.readFileSync(path.join(__dirname, '../src/zhijing/web/zhihu-question-reader.js'), 'utf8')
  .replace('__ZHIHU_READER_REQUEST__', JSON.stringify({question_id: '123', count: 20}));
const item = (id, text = '<p>合成第一段。</p><p>合成第二段。</p>', extra = '') =>
  `<article class="AnswerItem" data-zop='{"itemId":"${id}","type":"answer"}'>
  <meta itemprop="url" content="https://www.zhihu.com/question/123/answer/${id}">
  <div class="AuthorInfo"><a class="AuthorInfo-name" href="/people/fixture?tracking=1">合成作者</a></div>
  <div class="RichContent"><div class="RichContent-inner"><div class="RichText">${text}</div></div></div>${extra}</article>`;
const documentHTML = body => `<!doctype html><meta charset="utf-8"><title>合成问题 - 知乎</title>
  <style>body {margin:20px}.AnswerItem{margin:20px 0}.is-collapsed .RichContent-inner {max-height:30px;overflow:hidden}</style>
  <h1 class="QuestionHeader-title">合成问题</h1><main class="Question-mainColumn">${body}</main>`;
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext();
  let outbound = 0;
  await context.route('**/*', route => {
    if (route.request().url() === 'https://www.zhihu.com/question/123')
      return route.fulfill({contentType: 'text/html', body: documentHTML('')});
    outbound++; return route.abort();
  });
  const page = await context.newPage();
  const checks = [];
  const check = async (name, html, verify) => {
    await page.goto('https://www.zhihu.com/question/123');
    await page.setContent(documentHTML(html));
    await verify(await page.evaluate(script));
    checks.push(name);
  };
  try {
    await check('actual paragraphs and canonical author', item('1'), result => {
      assert.equal(result.items.length, 1); assert.match(result.items[0].text, /第一段。\n+合成第二段/);
      assert.equal(result.items[0].author_url, 'https://www.zhihu.com/people/fixture');
    });
    const collapsed = item('2', '<p>摘要。</p><p>展开后的正文。</p>')
      .replace('class="RichContent"', 'class="RichContent is-collapsed"')
      .replace('</article>', '<button onclick="this.closest(\'.AnswerItem\').querySelector(\'.RichContent\').classList.remove(\'is-collapsed\');this.remove()">阅读全文</button></article>');
    await check('expand first and only read on next poll', collapsed, async result => {
      assert.equal(result.expanded, 1); assert.equal(result.items.length, 0);
      const next = await page.evaluate(script); assert.match(next.items[0].text, /展开后的正文/);
    });
    await check('cross-question metadata rejected', item('3').replace('/question/123/answer/', '/question/456/answer/'),
      result => assert.equal(result.items.length, 0));
    await check('conflicting answer identifier rejected', item('4').replace('answer/4', 'answer/5'),
      result => assert.equal(result.items.length, 0));
    await check('login header allowed', '<button>登录</button>' + item('6'), result => assert.equal(result.state, 'reading'));
    await check('login form pauses without reading', '<div class="SignFlow">登录</div>' + item('6'),
      result => { assert.equal(result.state, 'needs_login'); assert.equal(result.items.length, 0); });
    await check('visible verification pauses', '<div class="Captcha">安全验证</div>',
      result => { assert.equal(result.state, 'needs_login'); assert.equal(result.reason, 'verification'); });
    await check('access error keeps user window available', '请求异常，请稍后重试',
      result => { assert.equal(result.state, 'needs_login'); assert.equal(result.reason, 'page_unavailable'); });
    await check('paid content is skipped without clicking', item('7', '免费预览', '<button onclick="window.purchased=true">开通会员后查看</button>'),
      async result => { assert.equal(result.items.length, 0); assert.equal(await page.evaluate('!!window.purchased'), false); });
    await check('oversized and hidden answers skipped', item('8', '中'.repeat(100001)) + '<div hidden>' + item('9') + '</div>',
      result => assert.equal(result.items.length, 0));
    await check('gentle scrolling loads more ordinary DOM', item('10') + '<div style="height:2000px"></div>' +
      '<script>addEventListener("scroll",()=>{if(!window.added){window.added=true;document.querySelector("main").insertAdjacentHTML("beforeend",' +
      JSON.stringify(item('11')) + ')}},{once:true})</script>', async result => {
      assert.equal(result.items.length, 1); await page.waitForFunction('window.added');
      assert.equal((await page.evaluate(script)).items.length, 2);
    });
    process.stdout.write(JSON.stringify({passed: checks.length, checks, blocked_nonfixture_requests: outbound}) + '\n');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
