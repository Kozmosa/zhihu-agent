(() => {
  'use strict';
  const request = __ZHIHU_READER_REQUEST__;
  const hosts = new Set(['www.zhihu.com', 'zhihu.com', 'm.zhihu.com']);
  const visible = node => !!node && node.getClientRects().length > 0 &&
    getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).display !== 'none';
  const tidy = text => String(text || '').replace(/\r\n?/g, '\n').trim();
  const url = value => {
    try {
      const result = new URL(value, location.href);
      return hosts.has(result.hostname) && ['https:', 'http:'].includes(result.protocol) &&
        !result.username && !result.password && !result.port ? result : null;
    } catch { return null; }
  };
  const here = url(location.href);
  const result = {state: 'loading', items: [], expanded: 0, skipped: 0, scroll_y: Math.round(scrollY),
    height: document.documentElement.scrollHeight};
  if (!here) { result.state = 'away'; return result; }
  // A normal header's login button is not a login wall. Only visible forms or challenge UI pause.
  const challenge = /\/(?:account\/unhuman|captcha|security-verification)(?:\/|$)/.test(here.pathname) ||
    [...document.querySelectorAll('.Unhuman, #captcha, .Captcha, .CaptchaContainer')].some(visible);
  const login = /^\/(?:signin|signup)(?:\/|$)/.test(here.pathname) ||
    [...document.querySelectorAll('.SignFlow, .SignContainer-content, .Modal-content .LoginForm')].some(visible);
  if (challenge || login) {
    result.state = 'needs_login'; result.reason = challenge ? 'verification' : 'login'; return result;
  }
  const pageTitle = tidy(document.title);
  const unavailable = ![...document.querySelectorAll('.AnswerItem')].some(visible) &&
    (/^(?:403|访问受限|请求异常|安全验证|知乎安全验证|访问验证)(?:\b|\s|[·—-]|$)/.test(pageTitle) ||
      (document.body?.innerText.length < 4000 && /(?:请求异常|访问受限|访问过于频繁|请完成安全验证|请求存在异常)/.test(document.body?.innerText || '')));
  if (unavailable) { result.state = 'needs_login'; result.reason = 'page_unavailable'; return result; }
  const pageMatch = here.pathname.match(/^\/question\/([0-9]{1,30})(?:\/answer\/[0-9]{1,30})?\/?$/);
  if (!pageMatch || pageMatch[1] !== request.question_id) { result.state = 'away'; return result; }
  result.state = 'reading';
  const title = tidy(document.querySelector('.QuestionHeader-title')?.innerText ||
    document.querySelector('h1')?.innerText || document.title).slice(0, 2000) || '知乎问题';
  const clicked = window.__zhijingReaderExpanded || (window.__zhijingReaderExpanded = new WeakSet());
  const seen = new Set();
  for (const answer of document.querySelectorAll('.AnswerItem')) {
    if (!visible(answer)) continue;
    let zop = {};
    try { zop = JSON.parse(answer.getAttribute('data-zop') || '{}'); } catch { /* DOM metadata is optional. */ }
    const rawId = String(zop.itemId || '');
    let answerId = '';
    let conflicting = false;
    const links = answer.querySelectorAll('meta[itemprop="url"], .ContentItem-time a[href*="/answer/"], a[itemprop="url"]');
    for (const link of links) {
      const permalink = url(link.getAttribute('content') || link.getAttribute('href'));
      const match = permalink?.pathname.match(/^\/question\/([0-9]{1,30})\/answer\/([0-9]{1,30})\/?$/);
      if (!match) continue;
      if (match[1] !== request.question_id || (answerId && answerId !== match[2])) conflicting = true;
      answerId = match[2];
    }
    if (conflicting || (answerId && rawId && rawId !== answerId)) continue;
    if (!answerId && /^[0-9]{1,30}$/.test(rawId) && (!zop.type || /answer/i.test(zop.type)) &&
      answer.closest('.Question-mainColumn, .QuestionAnswers-answers, .Answers-defaultList')) answerId = rawId;
    if (!/^[0-9]{1,30}$/.test(answerId) || seen.has(answerId)) continue;
    const rich = answer.querySelector('.RichContent');
    const body = answer.querySelector('.RichContent-inner .RichText') ||
      answer.querySelector('.RichContent-inner') || answer.querySelector('.RichContent > .RichText');
    if (!visible(body)) continue;
    const gate = [...answer.querySelectorAll('.PaidContent, .PurchaseButton, .ContentItem-paid, .KfeCollection-PurchaseBtn, button, a.Button')]
      .some(node => visible(node) && /购买后|付费阅读|开通.*会员|会员专享|解锁.*内容/.test(tidy(node.innerText).slice(0, 120)));
    if (gate) { result.skipped++; continue; }
    const expand = [...answer.querySelectorAll('button, a.ContentItem-more')]
      .find(node => visible(node) && /^(?:展开)?阅读全文\s*(?:[⌄∨▼›»]|展开)?$/.test(tidy(node.innerText)));
    const style = getComputedStyle(body);
    const clipped = (['hidden', 'clip'].includes(style.overflowY) || ['hidden', 'clip'].includes(style.overflow)) &&
      body.scrollHeight > body.clientHeight + 3;
    if (rich?.classList.contains('is-collapsed') || expand || clipped || rich?.getAttribute('aria-expanded') === 'false') {
      if (expand && !clicked.has(expand) && result.expanded < 2) {
        clicked.add(expand); expand.click(); result.expanded++;
      }
      continue; // Read the body in a later poll, after normal expansion has completed.
    }
    const text = tidy(body.innerText);
    if (!text || text.length > 100000) { result.skipped++; continue; }
    const author = answer.querySelector('.AuthorInfo-name') || answer.querySelector('.AuthorInfo');
    let authorUrl = '';
    for (const link of answer.querySelectorAll('.AuthorInfo a[href], .AuthorInfo-name[href]')) {
      const candidate = url(link.getAttribute('href'));
      if (candidate && /^\/(people|org)\/[A-Za-z0-9][A-Za-z0-9_-]{0,127}\/?$/.test(candidate.pathname)) {
        authorUrl = 'https://www.zhihu.com' + candidate.pathname.replace(/\/$/, ''); break;
      }
    }
    seen.add(answerId);
    result.items.push({answer_id: answerId, question_id: request.question_id, title,
      author_name: tidy(author?.innerText).slice(0, 2000) || '未署名', author_url: authorUrl,
      text, url: `https://www.zhihu.com/question/${request.question_id}/answer/${answerId}`});
    if (result.items.length >= Math.min(20, request.count)) break;
  }
  if (!result.expanded && result.items.length < request.count) {
    window.scrollBy({top: Math.min(600, Math.max(200, innerHeight * 0.65)), behavior: 'instant'});
  }
  result.scroll_y = Math.round(scrollY);
  result.height = document.documentElement.scrollHeight;
  return result;
})();
