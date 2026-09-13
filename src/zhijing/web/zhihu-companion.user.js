// ==UserScript==
// @name         知乎伴侣·知境版
// @namespace    zhijing.local/zhihu-companion
// @version      0.8.4
// @description  读取已打开的知乎页面，批量筛选回答并送入本机知境预览；保留原版 Markdown、JSON、点击提取能力。
// @author       Kozmosa（原版 0.8.2）；知境本地适配
// @match        https://www.zhihu.com/*
// @match        https://zhihu.com/*
// @match        https://zhuanlan.zhihu.com/*
// @match        http://127.0.0.1/workspace*
// @match        http://localhost/workspace*
// @run-at       document-end
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_setClipboard
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @noframes
// ==/UserScript==

// Based on the user-provided 知乎伴侣 0.8.2 by Kozmosa, namespace
// https://github.com/Kozmosa. Original DOM/Markdown and selection helpers retained.
// Local adaptation: no login-state access; only user-triggered loopback delivery.

(() => {
'use strict';

/******************** 持久化 Keys ********************/
const KEY_EXPORT_JSON = 'ZH_EXPORT_JSON_ENABLED';
const KEY_AUTO_COPY = 'ZH_AUTO_COPY_ENABLED';

/******************** 状态变量 ********************/
// 默认开启自动复制 (true)
let exportJSONEnabled = getPersist(KEY_EXPORT_JSON, false);
let autoCopyEnabled = getPersist(KEY_AUTO_COPY, true);

let isPicking = false;
let hoverOverlay = null;
let selectOverlay = null;
let pickInstruction = null;
let currentHoverEl = null;
let selectedEl = null;
let confirmPanel = null;

const COMPANION_KEY = 'ZHIJING_COMPANION_CONNECTION_V1';
let pendingDelivery = null;
let collectionJob = null;

if (location.hostname === '127.0.0.1' || location.hostname === 'localhost') {
  if (location.protocol === 'http:' && /^\/workspace\/?$/.test(location.pathname)) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initPairingUI);
    else initPairingUI();
  }
  return;
}
if (location.protocol !== 'https:' || !['www.zhihu.com', 'zhihu.com', 'zhuanlan.zhihu.com'].includes(location.hostname)) return;

/******************** 初始化 ********************/
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initUI);
} else {
  initUI();
}

if (typeof GM_registerMenuCommand === 'function') {
  GM_registerMenuCommand('打开设置', openSettingsPanel);
  GM_registerMenuCommand('一键提取当前页', quickExtractCurrentPage);
  GM_registerMenuCommand('选择器提取内容', manualSelectorFlow);
  GM_registerMenuCommand('可视化点击提取', startVisualPick);
  GM_registerMenuCommand('当前内容送入知境', () => sendCurrentContent());
  GM_registerMenuCommand('批量收集并送入知境', openCollectionPanel);
}

/******************** UI 搭建 ********************/
function initUI() {
  if (document.getElementById('__zhihu_extract_wrap__')) return;

  const wrap = document.createElement('div');
  wrap.id = '__zhihu_extract_wrap__';
  Object.assign(wrap.style, {
    position: 'fixed',
    top: '80px',
    right: '16px',
    zIndex: 99999,
    display: 'flex',
    flexDirection: 'column',
    gap: '8px'
  });

  const btnQuick = createBtn('一键提取当前页', '#8a3ffc', quickExtractCurrentPage);
  const btnVisual = createBtn('点击提取内容', '#0a7d34', startVisualPick);
  const btnManual = createBtn('选择器提取内容', '#056de8', manualSelectorFlow);
  const btnSettings = createBtn('设置', '#5c6b7a', openSettingsPanel);

  wrap.appendChild(btnQuick);
  wrap.appendChild(btnVisual);
  wrap.appendChild(btnManual);
  wrap.appendChild(btnSettings);
  wrap.appendChild(createBtn('当前内容送入知境', '#be602a', () => sendCurrentContent()));
  wrap.appendChild(createBtn('批量收集并送入知境', '#be602a', openCollectionPanel));
  wrap.appendChild(createBtn('重试上次发送', '#5c6b7a', () => retryDelivery()));
  wrap.appendChild(createBtn('放弃上次待重试内容', '#5c6b7a', discardPendingDelivery));
  document.body.appendChild(wrap);
}

function createBtn(text, color, handler) {
  const btn = document.createElement('button');
  btn.textContent = text;
  Object.assign(btn.style, {
    background: color,
    color: '#fff',
    border: 'none',
    padding: '8px 14px',
    borderRadius: '6px',
    fontSize: '14px',
    fontFamily: 'system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto',
    cursor: 'pointer',
    boxShadow: '0 2px 6px rgba(0,0,0,0.25)'
  });

  btn.addEventListener('mouseenter', () => {
    btn.style.filter = 'brightness(1.1)';
  });

  btn.addEventListener('mouseleave', () => {
    btn.style.filter = '';
  });

  btn.addEventListener('click', handler);
  return btn;
}

/******************** 设置面板 ********************/
function openSettingsPanel() {
  if (document.getElementById('__zhihu_settings_mask__')) return;

  const mask = document.createElement('div');
  mask.id = '__zhihu_settings_mask__';
  Object.assign(mask.style, {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.45)',
    zIndex: 100000,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center'
  });

  const panel = document.createElement('div');
  Object.assign(panel.style, {
    width: '390px',
    background: '#fff',
    borderRadius: '10px',
    padding: '18px 20px 20px',
    fontFamily: 'system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto',
    boxShadow: '0 8px 24px rgba(0,0,0,0.25)',
    position: 'relative',
    maxHeight: '80vh',
    overflow: 'auto'
  });

  panel.innerHTML = `
    <h3 style="margin:0 0 12px;font-size:18px;">设置</h3>
    <div style="display:flex;flex-direction:column;gap:14px;font-size:14px;line-height:1.5;">
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
        <input type="checkbox" id="__chk_export_json__" ${exportJSONEnabled ? 'checked' : ''} />
        <span>提取后导出 JSON 文件（自动下载）</span>
      </label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
        <input type="checkbox" id="__chk_auto_copy__" ${autoCopyEnabled ? 'checked' : ''} />
        <span>提取后自动复制到剪贴板</span>
      </label>
      <div style="padding:10px;background:#f5f7fa;border-radius:6px;font-size:12px;color:#555;">
        复制逻辑：<br>
        ① 自动复制 + 导出 JSON => 复制 JSON 字符串<br>
        ② 仅自动复制 => 复制“标题/问题 + Markdown 正文”纯文本<br>
        ③ 仅导出 JSON => 只下载文件
      </div>
    </div>
    <div style="margin-top:18px;display:flex;justify-content:flex-end;gap:10px;">
      <button id="__btn_close_settings__" style="${inlineBtnStyle('#5c6b7a')}">关闭</button>
    </div>
  `;

  mask.appendChild(panel);
  document.body.appendChild(mask);

  panel.querySelector('#__chk_export_json__').addEventListener('change', e => {
    exportJSONEnabled = e.target.checked;
    setPersist(KEY_EXPORT_JSON, exportJSONEnabled);
  });

  panel.querySelector('#__chk_auto_copy__').addEventListener('change', e => {
    autoCopyEnabled = e.target.checked;
    setPersist(KEY_AUTO_COPY, autoCopyEnabled);
  });

  panel.querySelector('#__btn_close_settings__').addEventListener('click', () => {
    mask.remove();
  });

  mask.addEventListener('click', e => {
    if (e.target === mask) mask.remove();
  });
}

function inlineBtnStyle(color) {
  return `background:${color};color:#fff;border:none;padding:8px 16px;border-radius:6px;font-size:14px;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.2);`;
}

/******************** 轻量 Toast 提示 ********************/
function showToast(text, duration = 2500) {
  const oldToast = document.getElementById('__zh_toast__');
  if (oldToast) oldToast.remove();

  const toast = document.createElement('div');
  toast.id = '__zh_toast__';
  Object.assign(toast.style, {
    position: 'fixed',
    top: '24px',
    left: '50%',
    transform: 'translateX(-50%)',
    background: 'rgba(0, 0, 0, 0.85)',
    color: '#fff',
    padding: '10px 22px',
    borderRadius: '8px',
    fontSize: '14px',
    fontWeight: '500',
    zIndex: 100002,
    boxShadow: '0 4px 14px rgba(0,0,0,0.3)',
    pointerEvents: 'none',
    transition: 'opacity 0.3s ease'
  });

  toast.textContent = text;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

/******************** 一键识别当前页 ********************/
function quickExtractCurrentPage() {
  const found = findCurrentPageContainer();

  if (!found || !found.container) {
    alert('未识别到可提取内容。若页面还没加载完，请稍后重试；也可以使用“点击提取内容”或“选择器提取内容”。');
    return;
  }

  processContainer(found.container, found.selector || buildUniqueSelector(found.container));
}

function findCurrentPageContainer() {
  const candidates = [
    ['article.Post-Main', document.querySelector('article.Post-Main')],
    ['.Post-Row-Content-left-article article', document.querySelector('.Post-Row-Content-left-article article')],
    ['.Post-Row-Content-left-article', document.querySelector('.Post-Row-Content-left-article')],
    ['.Post-Main', document.querySelector('.Post-Main')],
    ['.AnswerItem', document.querySelector('.AnswerItem')],
    ['.ContentItem.AnswerItem', document.querySelector('.ContentItem.AnswerItem')],
    ['.ContentItem', Array.from(document.querySelectorAll('.ContentItem')).find(el => findContentNode(el))],
    ['main', document.querySelector('main')],
    ['body', document.body]
  ];

  for (const [selector, el] of candidates) {
    if (el && findContentNode(el)) {
      return {
        selector,
        container: ensureContentContainer(el)
      };
    }
  }

  return null;
}

/******************** 手动输入选择器 ********************/
function manualSelectorFlow() {
  const selector = prompt('请输入内容容器的 CSS 选择器（回答页可用 .AnswerItem；专栏页可用 article.Post-Main）：', '');

  if (!selector || !selector.trim()) {
    alert('未输入选择器，已取消。');
    return;
  }

  const cleanSelector = selector.trim();
  let container = null;

  try {
    container = document.querySelector(cleanSelector);
  } catch (e) {
    alert('选择器语法错误：' + e.message);
    return;
  }

  if (!container) {
    alert('未找到匹配元素，请确认页面已加载。');
    return;
  }

  processContainer(container, cleanSelector);
}

/******************** 可视化选取 ********************/
function startVisualPick() {
  if (isPicking) return;

  isPicking = true;
  selectedEl = null;
  currentHoverEl = null;

  createHoverOverlay();
  createSelectOverlay();
  createInstructionOverlay();

  document.addEventListener('mousemove', onPickMouseMove, true);
  document.addEventListener('click', onPickClick, true);
  document.addEventListener('keydown', onPickKeyDown, true);
  document.addEventListener('contextmenu', onPickCancelContext, true);
}

function exitPickAfterSelection() {
  isPicking = false;
  removeElement(hoverOverlay);
  hoverOverlay = null;
  removeElement(pickInstruction);
  pickInstruction = null;

  document.removeEventListener('mousemove', onPickMouseMove, true);
  document.removeEventListener('click', onPickClick, true);
  document.removeEventListener('keydown', onPickKeyDown, true);
  document.removeEventListener('contextmenu', onPickCancelContext, true);
}

function stopVisualPick(clearSelection = true) {
  isPicking = false;
  removeElement(hoverOverlay);
  removeElement(pickInstruction);

  if (clearSelection) {
    removeElement(selectOverlay);
    selectOverlay = null;
    selectedEl = null;
  }

  removeElement(confirmPanel);

  document.removeEventListener('mousemove', onPickMouseMove, true);
  document.removeEventListener('click', onPickClick, true);
  document.removeEventListener('keydown', onPickKeyDown, true);
  document.removeEventListener('contextmenu', onPickCancelContext, true);

  hoverOverlay = null;
  pickInstruction = null;
  confirmPanel = null;
  currentHoverEl = null;
}

function onPickMouseMove(e) {
  if (!isPicking) return;
  if (confirmPanel && confirmPanel.contains(e.target)) return;

  const target = e.target;
  const container = findBestContainer(target);

  currentHoverEl = container || target;

  highlightElement(
    currentHoverEl,
    hoverOverlay,
    'rgba(0,255,120,0.25)',
    '2px solid rgba(0,180,90,0.8)'
  );
}

function onPickClick(e) {
  if (!isPicking) return;
  if (confirmPanel && confirmPanel.contains(e.target)) return;

  e.preventDefault();
  e.stopPropagation();

  if (!currentHoverEl) return;

  selectedEl = currentHoverEl;

  highlightElement(
    selectedEl,
    selectOverlay,
    'rgba(255,120,120,0.28)',
    '2px solid rgba(200,40,40,0.85)'
  );

  exitPickAfterSelection();
  showConfirmPanel(selectedEl, e.clientX, e.clientY);
}

function onPickKeyDown(e) {
  if (!isPicking) return;
  if (e.key === 'Escape') {
    stopVisualPick();
  }
}

function onPickCancelContext(e) {
  if (!isPicking) return;
  e.preventDefault();
  stopVisualPick();
}

function createHoverOverlay() {
  hoverOverlay = document.createElement('div');
  Object.assign(hoverOverlay.style, baseOverlayStyle());
  hoverOverlay.style.pointerEvents = 'none';
  document.body.appendChild(hoverOverlay);
}

function createSelectOverlay() {
  selectOverlay = document.createElement('div');
  Object.assign(selectOverlay.style, baseOverlayStyle());
  selectOverlay.style.pointerEvents = 'none';
  document.body.appendChild(selectOverlay);
}

function createInstructionOverlay() {
  pickInstruction = document.createElement('div');
  Object.assign(pickInstruction.style, {
    position: 'fixed',
    top: '10px',
    left: '50%',
    transform: 'translateX(-50%)',
    background: 'rgba(0,0,0,0.75)',
    color: '#fff',
    padding: '6px 14px',
    borderRadius: '20px',
    fontSize: '13px',
    fontFamily: 'system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto',
    zIndex: 100000,
    boxShadow: '0 2px 8px rgba(0,0,0,0.35)'
  });

  pickInstruction.textContent = '移动鼠标高亮元素，点击选择；Esc 或右键取消';
  document.body.appendChild(pickInstruction);
}

function baseOverlayStyle() {
  return {
    position: 'fixed',
    top: 0,
    left: 0,
    width: '0px',
    height: '0px',
    background: 'rgba(0,255,120,0.25)',
    border: '2px solid rgba(0,180,90,0.8)',
    boxSizing: 'border-box',
    zIndex: 99998,
    transition: 'all 0.06s ease'
  };
}

function highlightElement(el, overlay, bg, border) {
  if (!el || !overlay) return;

  const rect = el.getBoundingClientRect();

  overlay.style.top = rect.top + 'px';
  overlay.style.left = rect.left + 'px';
  overlay.style.width = rect.width + 'px';
  overlay.style.height = rect.height + 'px';

  if (bg) overlay.style.background = bg;
  if (border) overlay.style.border = border;
}

function showConfirmPanel(el, x, y) {
  removeElement(confirmPanel);

  confirmPanel = document.createElement('div');
  confirmPanel.dataset.lock = '1';

  Object.assign(confirmPanel.style, {
    position: 'fixed',
    zIndex: 100001,
    background: '#fff',
    border: '1px solid #ccc',
    borderRadius: '8px',
    padding: '12px 14px',
    fontSize: '13px',
    fontFamily: 'system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto',
    maxWidth: '340px',
    boxShadow: '0 4px 18px rgba(0,0,0,0.25)',
    pointerEvents: 'auto'
  });

  const container = ensureContentContainer(el);
  const preview = buildPreview(container);

  confirmPanel.innerHTML = `
    <div style="font-weight:600;margin-bottom:6px;">确认选择该元素？</div>
    <div style="color:#444;line-height:1.4;">
      <div><b>类型:</b> ${escapeHTML(preview.typeLabel)}</div>
      <div style="margin-top:4px;"><b>标题/问题:</b> ${escapeHTML(preview.titlePreview)}</div>
      <div style="margin-top:4px;"><b>正文预览:</b> ${escapeHTML(preview.bodyPreview)}</div>
    </div>
    <div style="margin-top:10px;display:flex;justify-content:flex-end;gap:8px;">
      <button id="__confirm_pick__" style="${miniBtn('#056de8')}">确定</button>
      <button id="__cancel_pick__" style="${miniBtn('#666')}">取消</button>
    </div>
  `;

  document.body.appendChild(confirmPanel);

  const panelRect = confirmPanel.getBoundingClientRect();
  let left = x + 12;
  let top = y + 12;

  if (left + panelRect.width > window.innerWidth - 10) {
    left = window.innerWidth - panelRect.width - 10;
  }

  if (top + panelRect.height > window.innerHeight - 10) {
    top = window.innerHeight - panelRect.height - 10;
  }

  confirmPanel.style.left = left + 'px';
  confirmPanel.style.top = top + 'px';

  confirmPanel.querySelector('#__confirm_pick__').addEventListener('click', () => {
    const targetContainer = ensureContentContainer(selectedEl || el);
    const selector = buildUniqueSelector(targetContainer);
    stopVisualPick(true);
    processContainer(targetContainer, selector);
  });

  confirmPanel.querySelector('#__cancel_pick__').addEventListener('click', () => {
    stopVisualPick(true);
  });
}

function miniBtn(color) {
  return `background:${color};color:#fff;border:none;padding:6px 14px;border-radius:4px;cursor:pointer;font-size:12px;`;
}

/******************** 容器识别 ********************/
function findBestContainer(el) {
  if (!el) return null;

  return el.closest('article.Post-Main') ||
         el.closest('.Post-Main') ||
         el.closest('.Post-Row-Content-left-article') ||
         el.closest('.ContentItem.AnswerItem') ||
         el.closest('.AnswerItem') ||
         el.closest('.ContentItem') ||
         el.closest('.RichContent') ||
         el.closest('.Post-RichTextContainer') ||
         el;
}

function ensureContentContainer(el) {
  if (!el) return document.body;

  let cur = el;

  while (cur && cur !== document.body) {
    if (findContentNode(cur)) return cur;
    cur = cur.parentElement;
  }

  return el;
}

function detectContentType(container) {
  const byUrl = /zhuanlan\.zhihu\.com\/p\//.test(location.href) ||
                /zhuanlan\.zhihu\.com\/c_\//.test(location.href);

  if (
    byUrl ||
    container?.matches?.('article.Post-Main, .Post-Main') ||
    container?.querySelector?.('h1.Post-Title, .Post-RichTextContainer, .Post-RichText')
  ) {
    return 'article';
  }

  return 'answer';
}

function buildPreview(container) {
  const type = detectContentType(container);
  const title = type === 'article'
    ? extractArticleTitle(container)
    : maybeEnhanceQuestion(extractQuestion(container));

  const bodyNode = findContentNode(container);
  const bodyPreview = bodyNode
    ? bodyNode.textContent.replace(/\s+/g, ' ').trim().slice(0, 80)
    : '(未找到正文节点)';

  return {
    type,
    typeLabel: type === 'article' ? '专栏文章' : '知乎回答',
    titlePreview: (title || '(未解析)').slice(0, 80),
    bodyPreview
  };
}

/******************** 提取主流程 ********************/
async function processContainer(container, selectorUsed) {
  try {
    const raw = extractRaw(container);
    const {
      blocks,
      markdown,
      removedCount,
      totalCount,
      tableCount
    } = cleanAndMarkdown(raw.contentNode);

    await handleOutputs({
      selector: selectorUsed,
      type: raw.type,
      title: raw.title,
      questionText: raw.type === 'answer' ? raw.title : '',
      contentMarkdown: markdown,
      blocks,
      removedCount,
      totalCount,
      tableCount
    });
  } catch (e) {
    alert('提取错误：' + e.message);
    console.error('[知乎提取脚本] 异常：', e);
  }
}

function extractRaw(container) {
  const type = detectContentType(container);

  let title = '';

  if (type === 'article') {
    title = extractArticleTitle(container);
  } else {
    title = maybeEnhanceQuestion(extractQuestion(container));
  }

  title = title || '(未能解析出标题/问题文本)';

  const contentNode = findContentNode(container);

  if (!contentNode) {
    throw new Error(type === 'article'
      ? '未找到专栏文章正文节点'
      : '未找到回答内容节点'
    );
  }

  return {
    type,
    title,
    contentNode
  };
}

/******************** 标题 / 问题 / 正文定位 ********************/
function extractArticleTitle(container) {
  if (!container) return '';

  const selectors = [
    'h1.Post-Title',
    '.Post-Header h1',
    'meta[itemprop="headline"]',
    'meta[property="og:title"]',
    'meta[name="title"]'
  ];

  for (const selector of selectors) {
    const el = container.querySelector(selector) || document.querySelector(selector);

    if (!el) continue;

    const text = el.content || el.getAttribute('content') || el.textContent;

    if (text && text.trim()) {
      return cleanupTitle(text);
    }
  }

  return cleanupTitle(document.title || '');
}

function extractQuestion(container) {
  if (!container) return '';

  let questionText = '';

  const anchor = container.querySelector('h2 a[href*="/question/"]');
  if (anchor) questionText = anchor.textContent.trim();

  if (!questionText) {
    const metaName = container.querySelector('meta[itemprop="name"]');
    if (metaName?.content) questionText = metaName.content.trim();
  }

  if (!questionText) {
    const zop = container.getAttribute('data-zop');
    if (zop) {
      try {
        const parsed = JSON.parse(zop);
        if (parsed?.title) questionText = String(parsed.title).trim();
      } catch (_) {}
    }
  }

  if (!questionText) {
    const h2 = container.querySelector('h2');
    if (h2) questionText = h2.textContent.trim();
  }

  return cleanupTitle(questionText || '');
}

function maybeEnhanceQuestion(questionText) {
  const text = cleanupTitle(questionText || '');

  if (text && /[?？]/.test(text)) {
    return text;
  }

  const globalH1 = document.querySelector('h1.QuestionHeader-title');
  if (globalH1) {
    const gText = cleanupTitle(globalH1.textContent);
    if (gText) return gText;
  }

  const ogTitle = document.querySelector('meta[property="og:title"]')?.content;
  if (ogTitle && /[?？]/.test(ogTitle)) {
    return cleanupTitle(ogTitle);
  }

  return text;
}

function cleanupTitle(str) {
  return String(str || '')
    .replace(/\u200B/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s*-\s*知乎专栏.*$/i, '')
    .replace(/\s*-\s*知乎.*$/i, '')
    .trim();
}

function findContentNode(container) {
  if (!container) return null;

  return container.querySelector('.Post-RichTextContainer .RichText.Post-RichText') ||
         container.querySelector('.Post-RichTextContainer .RichText') ||
         container.querySelector('.Post-RichText') ||
         container.querySelector('span#content > .RichText') ||
         container.querySelector('.RichContent-inner .RichText[itemprop="text"]') ||
         container.querySelector('.RichContent-inner [itemprop="text"].RichText') ||
         container.querySelector('.RichContent .RichText[itemprop="text"]') ||
         container.querySelector('.RichContent [itemprop="text"].RichText') ||
         container.querySelector('.RichText[itemprop="text"]') ||
         container.querySelector('[itemprop="text"].RichText') ||
         container.querySelector('[itemprop="text"]') ||
         null;
}

/******************** Markdown 转换 ********************/
function cleanAndMarkdown(contentNode) {
  const clone = contentNode.cloneNode(true);

  clone.querySelectorAll(
    [
      'script',
      'style',
      'noscript',
      'svg',
      'button',
      'iframe',
      'canvas',
      '#VirtualCatalogAnchorPoint',
      '.Reward',
      '.Post-topicsAndReviewer',
      '.ContentItem-actions',
      '.Sticky',
      '.AdvertImg',
      '.pc-article-answer-big-img',
      '[class*="Advert"]'
    ].join(',')
  ).forEach(n => n.remove());

  const nodes = getTopLevelContentNodes(clone);
  const blocks = [];

  let removedCount = 0;
  let tableCount = 0;

  for (const node of nodes) {
    const isTable = node.nodeType === Node.ELEMENT_NODE && node.matches('table');
    const md = blockNodeToMarkdown(node).trim();

    if (isTable) tableCount++;

    if (!isMeaningfulMarkdownBlock(md)) {
      removedCount++;
      continue;
    }

    blocks.push(md);
  }

  return {
    blocks,
    markdown: blocks.join('\n\n'),
    removedCount,
    totalCount: nodes.length,
    tableCount
  };
}

function getTopLevelContentNodes(root) {
  const direct = Array.from(root.childNodes).filter(n => {
    if (n.nodeType === Node.TEXT_NODE) {
      return normalizeText(n.textContent).trim();
    }

    if (n.nodeType !== Node.ELEMENT_NODE) return false;
    return !shouldIgnoreElement(n);
  });

  if (direct.length === 1 && direct[0].nodeType === Node.ELEMENT_NODE) {
    const el = direct[0];
    const hasBlockChildren = Array.from(el.children).some(child => isKnownBlockElement(child));

    if ((el.tagName === 'DIV' || el.tagName === 'SPAN') && hasBlockChildren) {
      return getTopLevelContentNodes(el);
    }
  }

  return direct;
}

function isKnownBlockElement(el) {
  if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;

  return /^(P|H1|H2|H3|H4|H5|H6|TABLE|UL|OL|LI|BLOCKQUOTE|PRE|HR|DIV|SECTION|FIGURE|IMG)$/i.test(el.tagName);
}

function shouldIgnoreElement(el) {
  if (!el || el.nodeType !== Node.ELEMENT_NODE) return true;

  return el.matches(
    [
      'script',
      'style',
      'noscript',
      'svg',
      'button',
      'iframe',
      'canvas',
      '#VirtualCatalogAnchorPoint',
      '.Reward',
      '.ContentItem-actions',
      '.Sticky',
      '[class*="Advert"]'
    ].join(',')
  );
}

function blockNodeToMarkdown(node) {
  if (!node) return '';

  if (node.nodeType === Node.TEXT_NODE) {
    return normalizeText(node.textContent).trim();
  }

  if (node.nodeType !== Node.ELEMENT_NODE) return '';

  const el = node;
  const tag = el.tagName.toUpperCase();

  if (shouldIgnoreElement(el)) return '';

  if (/^H[1-6]$/.test(tag)) {
    const level = Number(tag.slice(1));
    const text = inlineMarkdown(el).trim();
    return text ? `${'#'.repeat(level)} ${text}` : '';
  }

  if (tag === 'P') {
    return inlineMarkdown(el).trim();
  }

  if (tag === 'TABLE') {
    return tableToMarkdown(el);
  }

  if (tag === 'UL' || tag === 'OL') {
    return listToMarkdown(el, tag === 'OL');
  }

  if (tag === 'LI') {
    return inlineMarkdown(el).trim();
  }

  if (tag === 'BLOCKQUOTE') {
    const text = childrenBlocksToMarkdown(el) || inlineMarkdown(el);
    return text
      .split('\n')
      .map(line => line.trim() ? `> ${line}` : '>')
      .join('\n');
  }

  if (tag === 'PRE') {
    return preToMarkdown(el);
  }

  if (tag === 'HR') {
    return '---';
  }

  if (tag === 'IMG') {
    return imageToMarkdown(el);
  }

  if (tag === 'FIGURE') {
    return figureToMarkdown(el);
  }

  if (Array.from(el.children).some(child => isKnownBlockElement(child))) {
    return childrenBlocksToMarkdown(el);
  }

  return inlineMarkdown(el).trim();
}

function childrenBlocksToMarkdown(el) {
  return Array.from(el.childNodes)
    .map(child => blockNodeToMarkdown(child).trim())
    .filter(Boolean)
    .join('\n\n');
}

function preToMarkdown(el) {
  const codeNode = el.querySelector('code');
  const code = (codeNode || el).textContent.replace(/\u200B/g, '').trim();
  const langClass = codeNode ? Array.from(codeNode.classList || []).find(c => /^language-/.test(c)) : '';
  const lang = langClass ? langClass.replace(/^language-/, '') : '';

  const runs = code.match(/`+/g) || [];
  const fence = '`'.repeat(Math.max(3, ...runs.map(run => run.length + 1)));
  return code ? fence + lang + '\n' + code + '\n' + fence : '';
}

function listToMarkdown(listEl, ordered, depth = 0) {
  const items = Array.from(listEl.children).filter(ch => ch.tagName === 'LI');
  const indent = '  '.repeat(depth);

  return items.map((li, idx) => {
    const marker = ordered ? `${idx + 1}.` : '-';
    const parts = [];

    for (const child of Array.from(li.childNodes)) {
      if (child.nodeType === Node.ELEMENT_NODE && /^(UL|OL)$/i.test(child.tagName)) {
        const nested = listToMarkdown(child, child.tagName === 'OL', depth + 1);
        if (nested) parts.push(nested);
      } else {
        const md = blockNodeToMarkdown(child).trim();
        if (md) parts.push(md);
      }
    }

    let content = parts.join('\n').trim();

    if (!content) {
      content = inlineMarkdown(li).trim();
    }

    if (!content) return '';

    const lines = content.split('\n');

    return `${indent}${marker} ${lines[0]}` + (
      lines.length > 1
        ? '\n' + lines.slice(1).map(line => {
            if (/^\s*([-*+]|\d+\.)\s+/.test(line)) return line;
            return `${indent}  ${line}`;
          }).join('\n')
        : ''
    );
  }).filter(Boolean).join('\n');
}

function tableToMarkdown(tableEl) {
  const trList = Array.from(tableEl.querySelectorAll('tr')).slice(0, 200);

  if (!trList.length) return '';

  const grid = [];
  const firstContentTr = trList.find(tr => {
    return Array.from(tr.children).some(cell => /^(TH|TD)$/i.test(cell.tagName));
  });

  const firstRowHasTh = firstContentTr
    ? Array.from(firstContentTr.children).some(cell => cell.tagName === 'TH')
    : false;

  for (let r = 0; r < trList.length; r++) {
    const tr = trList[r];
    const cells = Array.from(tr.children).filter(cell => /^(TH|TD)$/i.test(cell.tagName));

    if (!cells.length) continue;
    if (!grid[r]) grid[r] = [];

    let c = 0;

    for (const cell of cells) {
      while (grid[r][c] !== undefined) c++;

      const text = tableCellToMarkdown(cell);
      const boundedSpan = value => Number.isFinite(Number(value)) ? Math.max(1, Math.min(100, Math.floor(Number(value) || 1))) : 1;
      const rowSpan = boundedSpan(cell.getAttribute('rowspan'));
      const colSpan = boundedSpan(cell.getAttribute('colspan'));
      if (c >= 200) break;

      for (let rr = 0; rr < rowSpan; rr++) {
        const targetR = r + rr;
        if (!grid[targetR]) grid[targetR] = [];

        for (let cc = 0; cc < colSpan; cc++) {
          const targetC = c + cc;
          grid[targetR][targetC] = (rr === 0 && cc === 0) ? text : '';
        }
      }

      c += colSpan;
    }
  }

  const rawRows = grid
    .filter(row => Array.isArray(row))
    .map(row => row.map(cell => cell === undefined ? '' : cell))
    .filter(row => row.some(cell => String(cell).trim()));

  if (!rawRows.length) return '';

  const colCount = Math.max(...rawRows.map(row => row.length));
  const rows = rawRows.map(row => {
    const copy = row.slice();
    while (copy.length < colCount) copy.push('');
    return copy;
  });

  let header;
  let bodyRows;

  if (firstRowHasTh) {
    header = rows[0];
    bodyRows = rows.slice(1);
  } else {
    header = Array.from({ length: colCount }, (_, i) => `列${i + 1}`);
    bodyRows = rows;
  }

  const separator = Array.from({ length: colCount }, () => '---');

  return [
    markdownTableRow(header),
    markdownTableRow(separator),
    ...bodyRows.map(markdownTableRow)
  ].join('\n');
}

function markdownTableRow(row) {
  return '| ' + row.map(cell => cell || ' ').join(' | ') + ' |';
}

function tableCellToMarkdown(cell) {
  return cleanupInlineMarkdown(inlineMarkdown(cell))
    .replace(/\|/g, '\\|')
    .replace(/\n+/g, '<br>')
    .trim();
}

function figureToMarkdown(figure) {
  const img = figure.querySelector('img');
  const imgMd = img ? imageToMarkdown(img) : '';
  const caption = figure.querySelector('figcaption')?.textContent?.trim() || '';

  if (imgMd && caption) {
    return `${imgMd}\n\n_${escapeMarkdownInline(caption)}_`;
  }

  return imgMd || inlineMarkdown(figure).trim();
}

function imageToMarkdown(img) {
  const src =
    img.getAttribute('data-original') ||
    img.getAttribute('data-actualsrc') ||
    img.getAttribute('data-src') ||
    img.getAttribute('src') ||
    '';

  const alt = img.getAttribute('alt') || '';

  if (!src || src.startsWith('data:image/svg')) return alt;

  const safeSrc = normalizeHref(src);
  return safeSrc ? `![${escapeMarkdownInline(alt)}](${safeSrc})` : alt;
}

function inlineMarkdown(node) {
  if (!node) return '';

  if (node.nodeType === Node.TEXT_NODE) {
    return normalizeText(node.textContent);
  }

  if (node.nodeType !== Node.ELEMENT_NODE) return '';

  const el = node;
  const tag = el.tagName.toUpperCase();

  if (shouldIgnoreElement(el)) return '';

  if (el.classList.contains('ztext-math') || el.hasAttribute('data-tex')) {
    const tex = el.getAttribute('data-tex') || el.textContent;
    return tex ? ` $${tex.trim()}$ ` : '';
  }

  if (tag === 'BR') return '\n';

  if (tag === 'IMG') {
    return imageToMarkdown(el);
  }

  if (tag === 'PRE') {
    return preToMarkdown(el);
  }

  const childText = Array.from(el.childNodes).map(inlineMarkdown).join('');
  const text = cleanupInlineMarkdown(childText);

  if (!text) return '';

  if (tag === 'B' || tag === 'STRONG') {
    return `**${text}**`;
  }

  if (tag === 'I' || tag === 'EM') {
    return `*${text}*`;
  }

  if (tag === 'CODE') {
    return '`' + text.replace(/`/g, '\\`') + '`';
  }

  if (tag === 'A') {
    if (el.matches('.RichContent-EntityWord')) {
      return text;
    }

    const href = el.getAttribute('href');

    if (!href) return text;

    const safeHref = normalizeHref(href);
    return safeHref ? `[${escapeMarkdownInline(text)}](${safeHref})` : text;
  }

  return childText;
}

function normalizeText(str) {
  return String(str || '')
    .replace(/\u200B/g, '')
    .replace(/\r\n?/g, '\n')
    .replace(/[ \t\f\v]+/g, ' ');
}

function cleanupInlineMarkdown(str) {
  return String(str || '')
    .replace(/\u200B/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
}

function isMeaningfulMarkdownBlock(md) {
  const text = String(md || '').trim();

  if (!text) return false;

  if (/^\|.+\|/m.test(text)) return true;
  if (/^#{1,6}\s+/.test(text)) return true;
  if (/^```/.test(text)) return true;
  if (/^---$/.test(text)) return true;
  if (/!\[.*?\]\(.+?\)/.test(text)) return true;

  const compact = text.replace(/\s+/g, '');

  if (/^[\-\–\—=·•_*#>|:]+$/.test(compact)) return false;
  if (compact.length <= 2 && /^[\p{P}\p{S}]+$/u.test(compact)) return false;

  return true;
}

function escapeMarkdownInline(str) {
  return String(str || '').replace(/([\[\]()])/g, '\\$1');
}

function normalizeHref(href) {
  try {
    const url = new URL(href, location.href);
    if (!href || !['http:', 'https:'].includes(url.protocol) || url.username || url.password) return '';
    return url.href.replace(/[()<>]/g, char => '%' + char.charCodeAt(0).toString(16).toUpperCase());
  } catch (_) { return ''; }
}

/******************** 输出 / 导出 / 复制 ********************/
async function handleOutputs(data) {
  const {
    selector,
    type,
    title,
    questionText,
    contentMarkdown,
    blocks,
    removedCount,
    totalCount,
    tableCount = 0
  } = data;

  const finalMarkdown = contentMarkdown || '';
  const fullMarkdown = `# ${title}\n\n${finalMarkdown}`;

  const jsonObj = {
    type,
    title,
    question: type === 'answer' ? questionText : '',
    markdown: fullMarkdown,
    content_markdown: finalMarkdown,
    article_markdown: type === 'article' ? finalMarkdown : '',
    answer_markdown: type === 'answer' ? finalMarkdown : '',
    answer_text: type === 'answer' ? finalMarkdown : '',
    blocks,
    paragraphs: blocks,
    stats: {
      kept: blocks.length,
      removed: removedCount,
      total: totalCount,
      tables: tableCount,
      selector,
      url: location.href,
      timestamp: new Date().toISOString()
    }
  };

  const jsonStr = JSON.stringify(jsonObj, null, 2);

  const plainCopy = type === 'article'
    ? `# ${title}\n\n${finalMarkdown}`
    : `## ${title}\n\n${finalMarkdown}`;

  if (exportJSONEnabled) {
    try {
      exportJSONFile(jsonStr, title);
    } catch (e) {
      console.error('[知乎伴侣] 导出 JSON 失败：', e);
    }
  }

  let copySuccess = false;
  if (autoCopyEnabled) {
    const toCopy = exportJSONEnabled ? jsonStr : plainCopy;
    try {
      copySuccess = await copyToClipboard(toCopy);
      if (copySuccess) {
        console.log('[知乎伴侣] 已成功写入剪贴板！');
      }
    } catch (err) {
      console.warn('[知乎伴侣] 复制失败：', err);
    }
  }

  // 使用非阻塞 Toast 提示替代原有阻塞式 alert
  const tips = [];
  if (autoCopyEnabled && copySuccess) tips.push('已复制到剪贴板');
  if (exportJSONEnabled) tips.push('已导出 JSON');
  if (tips.length === 0) tips.push('提取成功');

  showToast(`🎉 ${tips.join('，')}！`);

}

function sanitizeFilename(str) {
  return String(str || '')
    .replace(/[\/\\?%*:|"<>]/g, '')
    .replace(/\s+/g, '_')
    .slice(0, 80) || 'zhihu_content';
}

function exportJSONFile(jsonStr, title) {
  const blob = new Blob([jsonStr], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const ts = new Date().toISOString().replace(/[:.]/g, '-');

  a.href = url;
  a.download = `${sanitizeFilename(title)}_${ts}.json`;

  document.body.appendChild(a);
  a.click();

  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 0);
}

/******************** 剪贴板复制核心增强 ********************/
async function copyToClipboard(text) {
  // 1. 优先使用油猴 API (最稳定，完全绕过页面失焦与知乎事件拦截)
  if (typeof GM_setClipboard === 'function') {
    GM_setClipboard(text, 'text');
    return true;
  }

  // 2. 现代原生 Clipboard API (需页面在安全上下文且聚焦)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.warn('[知乎伴侣] navigator.clipboard 失败，降级执行:', err);
    }
  }

  // 3. 增强版 textarea 降级方案 (防止样式隐藏导致 execCommand 失效)
  return new Promise((resolve) => {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.all = 'unset';
      ta.style.position = 'fixed';
      ta.style.top = '0';
      ta.style.left = '0';
      ta.style.clip = 'rect(0, 0, 0, 0)';
      ta.style.whiteSpace = 'pre';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      ta.setSelectionRange(0, text.length);
      const successful = document.execCommand('copy');
      document.body.removeChild(ta);
      resolve(successful);
    } catch (e) {
      console.error('[知乎伴侣] 降级复制异常:', e);
      resolve(false);
    }
  });
}

/******************** 选择器生成 ********************/
function buildUniqueSelector(el) {
  if (!el || el === document || el === document.documentElement) return 'html';

  if (el.id) {
    const idSel = `#${cssEscape(el.id)}`;

    try {
      if (document.querySelectorAll(idSel).length === 1) return idSel;
    } catch (_) {}
  }

  const pathSegments = [];
  let cur = el;

  while (cur && cur.nodeType === 1 && cur !== document.body && cur !== document.documentElement) {
    let segment = cur.nodeName.toLowerCase();

    const classList = Array.from(cur.classList || []);
    const stableClass = classList.find(c => {
      return c &&
        c.length > 1 &&
        !/^\d+$/.test(c) &&
        !/^css-/.test(c) &&
        !/[A-Z]/.test(c);
    });

    if (stableClass) {
      segment += '.' + cssEscape(stableClass);
    } else {
      const siblings = Array
        .from(cur.parentNode.children)
        .filter(ch => ch.nodeName === cur.nodeName);

      if (siblings.length > 1) {
        const index = siblings.indexOf(cur) + 1;
        segment += `:nth-of-type(${index})`;
      }
    }

    pathSegments.unshift(segment);

    const candidate = pathSegments.join(' > ');

    try {
      if (document.querySelectorAll(candidate).length === 1) return candidate;
    } catch (_) {}

    cur = cur.parentElement;

    if (cur === document.body) {
      pathSegments.unshift('body');
      break;
    }
  }

  return pathSegments.join(' > ') || 'body';
}

function cssEscape(str) {
  if (window.CSS && typeof window.CSS.escape === 'function') {
    return window.CSS.escape(str);
  }

  return String(str).replace(/([ !"#$%&'()*+,./:;<=>?@\[\\\]^`{|}~])/g, '\\$1');
}

/******************** 工具函数 ********************/
/******************** 知境本地接收桥接 ********************/
function loopbackBase(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) || url.username || url.password || url.search || url.hash || !['', '/'].includes(url.pathname)) return null;
    return url.origin;
  } catch (_) { return null; }
}

function initPairingUI() {
  const official = document.querySelector('script[src="/assets/workspace.js"][data-config-token]');
  if (!official || !official.dataset.configToken || document.getElementById('__zhijing_pair__')) return;
  const button = createBtn('连接当前知境', '#be602a', async () => {
    button.disabled = true;
    try {
      if (typeof GM_setValue !== 'function') throw new Error('请使用油猴运行脚本。');
      const base = loopbackBase(location.origin);
      if (!base) throw new Error('仅可连接本机知境。');
      const response = await fetch(base + '/api/v1/zhihu/companion/pair', {
        method: 'POST', credentials: 'omit', redirect: 'error',
        headers: { 'Content-Type': 'application/json', 'X-Zhijing-Token': official.dataset.configToken },
        body: '{}'
      });
      if (!response.ok) throw new Error('连接失败，请确认已启动新版知境并刷新此页面。');
      const data = await response.json();
      if (typeof data.token !== 'string' || data.token.length < 20 || data.token.length > 512) throw new Error('连接响应无效。');
      GM_setValue(COMPANION_KEY, { base_url: base, token: data.token });
      button.textContent = '已连接知境';
      showToast('已连接。现在打开知乎问题页或作者回答页即可采集。', 5000);
    } catch (error) {
      showToast(error.message || '连接失败，请刷新知境页面后重试。', 6000);
    } finally { button.disabled = false; }
  });
  button.id = '__zhijing_pair__';
  Object.assign(button.style, { position: 'fixed', bottom: '24px', right: '24px', zIndex: 100002 });
  document.body.appendChild(button);
}

function getConnection() {
  const value = typeof GM_getValue === 'function' ? GM_getValue(COMPANION_KEY, null) : null;
  if (!value || !loopbackBase(value.base_url) || typeof value.token !== 'string' || value.token.length < 20 || value.token.length > 512) {
    throw new Error('先在知境的「浏览器采集」中打开浏览器连接页，点击「连接当前知境」，再返回知乎。');
  }
  return { base_url: loopbackBase(value.base_url), token: value.token };
}

function zhihuURL(value) {
  try {
    const url = new URL(value, location.href);
    if (url.protocol !== 'https:' || !['www.zhihu.com', 'zhihu.com', 'zhuanlan.zhihu.com'].includes(url.hostname) || url.username || url.password || url.port) return null;
    url.search = ''; url.hash = '';
    if (url.hostname === 'zhihu.com') url.hostname = 'www.zhihu.com';
    return url;
  } catch (_) { return null; }
}

function pageScope() {
  const page = zhihuURL(location.href);
  if (!page) throw new Error('请在知乎问题页、回答页、作者回答页或专栏文章页采集。');
  let match;
  if (page.hostname === 'www.zhihu.com' && (match = page.pathname.match(/^\/question\/(\d{1,30})(?:\/answer\/\d{1,30})?\/?$/))) return { page_url: page.href, scope: 'question', scope_id: match[1] };
  if (page.hostname === 'www.zhihu.com' && (match = page.pathname.match(/^\/(?:people|org)\/([A-Za-z0-9][A-Za-z0-9_-]{0,99})(?:\/answers)?\/?$/))) return { page_url: page.href, scope: 'author', scope_id: match[1] };
  if (page.hostname === 'zhuanlan.zhihu.com' && /^\/p\/\d{1,30}\/?$/.test(page.pathname)) return { page_url: page.href, scope: 'page', scope_id: null };
  throw new Error('请打开具体问题页、作者主页／回答页或专栏文章页。');
}

function readZop(container) {
  try { return JSON.parse(container.getAttribute('data-zop') || '{}'); }
  catch (_) { return {}; }
}

function answerIdentity(container, scope) {
  const candidates = [];
  const meta = container.querySelector('meta[itemprop="url"]');
  if (meta) candidates.push(meta.content);
  for (const anchor of container.querySelectorAll('a[itemprop="url"][href], .ContentItem-time a[href], .ContentItem-meta a[href], h2 a[href]')) candidates.push(anchor.getAttribute('href'));
  let questionId = null;
  for (const candidate of candidates) {
    const url = zhihuURL(candidate);
    if (!url || url.hostname !== 'www.zhihu.com') continue;
    const answer = url.pathname.match(/^\/question\/(\d{1,30})\/answer\/(\d{1,30})\/?$/);
    if (answer) return { question_id: answer[1], external_id: answer[2], url: `https://www.zhihu.com/question/${answer[1]}/answer/${answer[2]}` };
    const question = url.pathname.match(/^\/question\/(\d{1,30})\/?$/);
    if (question) questionId = question[1];
  }
  const zop = readZop(container);
  const rawExternalId = zop.itemId || container.getAttribute('data-answer-id') || '';
  if (typeof rawExternalId === 'number' && !Number.isSafeInteger(rawExternalId)) return null;
  const externalId = String(rawExternalId);
  questionId = questionId || (scope.scope === 'question' ? scope.scope_id : null);
  if (/^\d{1,30}$/.test(externalId) && questionId && (!zop.type || /^answer$/i.test(String(zop.type)))) return { question_id: questionId, external_id: externalId, url: `https://www.zhihu.com/question/${questionId}/answer/${externalId}` };
  return null;
}

function authorIdentity(container) {
  const anchor = container.querySelector('.AuthorInfo-head a[href], .AuthorInfo-name a[href], .AuthorInfo a.UserLink-link[href], [itemprop="author"] a[href], a.Post-Author[href]');
  let authorURL = anchor && zhihuURL(anchor.getAttribute('href'));
  if (!authorURL || authorURL.hostname !== 'www.zhihu.com' || !/^\/(?:people|org)\/[A-Za-z0-9][A-Za-z0-9_-]{0,99}\/?$/.test(authorURL.pathname)) authorURL = null;
  const nameNode = container.querySelector('.AuthorInfo-name, [itemprop="author"] [itemprop="name"], .Post-Author');
  const name = normalizeText(nameNode?.textContent || readZop(container).authorName || anchor?.textContent || '').trim().slice(0, 200);
  return { author_name: name || '未知作者', author_url: authorURL ? authorURL.origin + authorURL.pathname.replace(/\/$/, '') : null };
}

function readVotes(container) {
  const meta = container.querySelector('meta[itemprop="upvoteCount"]');
  if (meta && /^\d+$/.test(meta.content) && Number.isSafeInteger(Number(meta.content)) && Number(meta.content) <= 1e12) return { voteup_count: Number(meta.content), voteup_is_approximate: false };
  const button = container.querySelector('.VoteButton--up');
  const raw = button ? [button.getAttribute('aria-label'), button.getAttribute('title'), button.textContent].filter(Boolean).join(' ') : '';
  const match = raw.replace(/,/g, '').match(/(\d+(?:\.\d+)?)\s*(亿|万|[kKwW])?/);
  if (!match) return { voteup_count: null, voteup_is_approximate: false };
  const unit = match[2] || '';
  const multiplier = unit === '亿' ? 100000000 : /万|w/i.test(unit) ? 10000 : /k/i.test(unit) ? 1000 : 1;
  const count = Math.round(Number(match[1]) * multiplier);
  return { voteup_count: Number.isSafeInteger(count) && count <= 1e12 ? count : null, voteup_is_approximate: Boolean(unit || /[+＋]/.test(raw)) };
}

function expandButtons(container) {
  return Array.from(container.querySelectorAll('button.ContentItem-more, button.RichContent-more, .RichContent-inner + button, button[data-za-detail-view-element_name="展开"]'))
    .filter(button => !button.disabled && /展开|阅读全文|显示全部/.test(button.textContent || '') && !/收起/.test(button.textContent || ''));
}

function contentExtent(container) {
  if (container.querySelector('.RichContent.is-collapsed, .RichContent-inner.is-collapsed, .PurchaseButton, .PaidContent, .KfeCollection-PurchaseBtn, [class*="PayWall"], [class*="Paywall"]') || expandButtons(container).length) return 'excerpt';
  // DOM presence alone cannot prove that a site's entire answer was provided.
  return 'unknown';
}

function collectItem(container, scope) {
  const isArticle = container.matches('article.Post-Main, .Post-Main, .Post-Row-Content-left-article');
  let identity;
  if (isArticle) {
    const page = zhihuURL(location.href);
    const match = page?.hostname === 'zhuanlan.zhihu.com' && page.pathname.match(/^\/p\/(\d{1,30})\/?$/);
    if (!match) return null;
    identity = { external_id: match[1], question_id: null, url: `https://zhuanlan.zhihu.com/p/${match[1]}` };
  } else {
    if (!container.matches('.AnswerItem, .ContentItem.AnswerItem')) return null;
    identity = answerIdentity(container, scope);
    if (!identity) return null;
  }
  if (scope.scope === 'question' && identity.question_id !== scope.scope_id) return null;
  const author = authorIdentity(container);
  if (scope.scope === 'author' && (!author.author_url || new URL(author.author_url).pathname.split('/').filter(Boolean).pop() !== scope.scope_id)) return null;
  const node = findContentNode(container);
  if (!node) return null;
  const text = cleanAndMarkdown(node).markdown.trim();
  if (!text) return null;
  let title = isArticle ? extractArticleTitle(container) : extractQuestion(container);
  if (!title && scope.scope === 'question') title = cleanupTitle(document.querySelector('h1.QuestionHeader-title')?.textContent || '');
  return { content_type: isArticle ? 'article' : 'answer', ...identity, title: (title || '未提供题目').slice(0, 200), ...author,
    text, content_extent: contentExtent(container), ...readVotes(container), captured_at: new Date().toISOString() };
}

function contentContainers() {
  const article = document.querySelector('article.Post-Main, .Post-Main, .Post-Row-Content-left-article');
  if (article && location.hostname === 'zhuanlan.zhihu.com') return [article];
  return Array.from(new Set(document.querySelectorAll('.AnswerItem, .ContentItem.AnswerItem')));
}

function gatherItems(scope, minimumVotes = 0, maxItems = 100, cache = new Map()) {
  let skipped = 0;
  for (const container of contentContainers()) {
    const item = collectItem(container, scope);
    if (!item || item.content_extent === 'excerpt' || (minimumVotes > 0 && (item.voteup_count === null || item.voteup_count < minimumVotes))) { skipped++; continue; }
    const key = item.content_type + ':' + item.external_id;
    const previous = cache.get(key);
    if (!previous || (previous.content_extent === 'excerpt' && item.content_extent !== 'excerpt') || item.text.length > previous.text.length) cache.set(key, item);
  }
  return { items: Array.from(cache.values()).sort((a, b) => (b.voteup_count || 0) - (a.voteup_count || 0)).slice(0, maxItems), skipped };
}

function uuid() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function receivePayload(connection, payload) {
  if (typeof GM_xmlhttpRequest !== 'function') return Promise.reject(new Error('请使用支持 GM_xmlhttpRequest 的油猴运行脚本。'));
  const base = loopbackBase(connection.base_url);
  if (!base) return Promise.reject(new Error('接收地址必须为本机知境。'));
  return new Promise((resolve, reject) => {
    GM_xmlhttpRequest({
      method: 'POST', url: base + '/api/v1/zhihu/companion/receive',
      anonymous: true, redirect: 'error', timeout: 20000,
      headers: { 'Content-Type': 'application/json', 'X-Zhijing-Companion': connection.token },
      data: JSON.stringify(payload),
      onload: response => {
        if (response.finalUrl && response.finalUrl !== base + '/api/v1/zhihu/companion/receive') { reject(new Error('接收地址发生跳转，已停止。')); return; }
        if (response.status < 200 || response.status >= 300) {
          const messages = {
            401: '连接已失效，请在知境连接页重新连接后重试。',
            403: '连接已失效，请在知境连接页重新连接后重试。',
            413: '本批内容过多。请点击「放弃上次待重试内容」后减少篇数重新采集。',
            422: '内容格式或来源未被接受。可放弃上次待重试内容，更新脚本并重新采集。',
            429: '知境接收列表已满。请回知境导入并移除已处理批次，再点击「重试上次发送」。'
          };
          reject(new Error(messages[response.status] || `知境接收失败（${response.status}），本次内容已保留，可重试。`)); return;
        }
        try {
          const data = JSON.parse(response.responseText);
          if (typeof data.batch_id !== 'string' || !Number.isInteger(data.count)) throw new Error();
          resolve(data);
        } catch (_) { reject(new Error('知境响应无效，本次内容已保留，可重试。')); }
      },
      onerror: () => reject(new Error('无法连接知境。请启动知境后点击「重试上次发送」。')),
      ontimeout: () => reject(new Error('发送超时，本次内容已保留；点击「重试上次发送」不会重复创建同一批次。'))
    });
  });
}

function showReturnLink(base, count) {
  let link = document.getElementById('__zhijing_return__');
  if (!link) {
    link = document.createElement('a'); link.id = '__zhijing_return__';
    Object.assign(link.style, { background: '#fff4e8', color: '#8b431e', padding: '10px', borderRadius: '6px', maxWidth: '190px', fontSize: '13px' });
    (document.getElementById('__zhihu_extract_wrap__') || document.body).appendChild(link);
  }
  link.href = base + '/workspace#companion'; link.target = '_blank'; link.rel = 'noopener noreferrer';
  link.textContent = `已发送 ${count} 篇，返回知境接收列表预览导入`;
}

async function deliver(scope, items) {
  const connection = getConnection();
  if (!items.length) throw new Error('没有符合条件的已加载内容。请展开回答或加载更多后重试。');
  if (items.some(item => item.content_extent === 'excerpt')) throw new Error('该内容仍折叠或为付费预览，请在网页正常展开后再发送。');
  if (items.length > 100 || items.some(item => item.text.length > 100000) || items.reduce((sum, item) => sum + item.text.length, 0) > 2000000) throw new Error('本次正文超过接收上限（单篇 10 万字、合计 200 万字），请减少采集篇数；内容没有被截断。');
  if (pendingDelivery) throw new Error('上次发送尚未确认成功，请先点击「重试上次发送」，避免丢失待重试内容。');
  const payload = { request_id: uuid(), ...scope, items };
  if (new Blob([JSON.stringify(payload)]).size > 12000000) throw new Error('本次数据超过 12 MB 接收上限，请减少采集篇数。');
  pendingDelivery = { payload, inFlight: false };
  return retryDelivery(true, connection);
}

async function retryDelivery(propagate = false, connection = null) {
  try {
    if (!pendingDelivery) throw new Error('没有待重试的内容。');
    if (pendingDelivery.inFlight) throw new Error('正在发送，请稍候。');
    const connected = connection || getConnection();
    const pending = pendingDelivery;
    pending.inFlight = true;
    try {
      const result = await receivePayload(connected, pending.payload);
      if (pendingDelivery === pending) pendingDelivery = null;
      showReturnLink(connected.base_url, result.count);
      showToast(`已送入知境 ${result.count} 篇，请返回知境预览并选择导入。`, 6000);
      return result;
    } finally { pending.inFlight = false; }
  } catch (error) {
    if (propagate) throw error;
    showToast(error.message || '发送失败，请重试。', 6000);
  }
}

function discardPendingDelivery() {
  if (!pendingDelivery) { showToast('没有待重试的内容。'); return; }
  if (pendingDelivery.inFlight) { showToast('正在发送，请等待本次接收结果。'); return; }
  if (!confirm('放弃浏览器中上次待重试的内容？已被知境接收的批次仍保留。之后可以重新采集。')) return;
  pendingDelivery = null;
  showToast('已清空待重试内容，可以重新采集。');
}

async function sendCurrentContent() {
  try {
    const scope = pageScope();
    getConnection();
    const containers = contentContainers();
    const current = zhihuURL(location.href)?.pathname.match(/^\/question\/\d+\/answer\/(\d+)\/?$/);
    let items = containers.map(container => collectItem(container, scope)).filter(Boolean);
    if (current) items = items.filter(item => item.external_id === current[1]);
    await deliver(scope, items.slice(0, 1));
  } catch (error) { showToast(error.message || '采集失败。', 6000); }
}

function openCollectionPanel() {
  if (document.getElementById('__zhijing_collect_panel__')) return;
  const panel = document.createElement('div'); panel.id = '__zhijing_collect_panel__';
  Object.assign(panel.style, { position: 'fixed', right: '220px', top: '80px', width: '320px', maxWidth: '80vw', maxHeight: '80vh', overflow: 'auto', padding: '18px', background: '#fff', color: '#333', border: '1px solid #ccc', borderRadius: '10px', zIndex: 100002, boxShadow: '0 4px 20px #0003', font: '14px/1.6 system-ui' });
  panel.innerHTML = '<strong>批量收集并送入知境</strong><p>读取当前问题或作者页实际加载的内容。结果先送入知境预览。</p><label>最低赞同 <input id="__zj_votes__" type="number" min="0" max="1000000000" value="0" style="width:100px"></label><br><label>最多篇数 <input id="__zj_limit__" type="number" min="1" max="100" value="20" style="width:100px"></label><p><label><input id="__zj_scroll__" type="checkbox"> 自动展开并滚动加载（最多 20 轮、45 秒）</label></p><p style="font-size:12px">折叠、付费或未确认完整的内容会标注完整性；作者页只收集该作者本人；问题页可收集多位作者。遇到登录或验证请在网页正常完成。</p>';
  const scopeLabel = document.createElement('p'); scopeLabel.id = '__zj_scope__';
  const connectionLabel = document.createElement('p'); connectionLabel.id = '__zj_connection__';
  const updateScope = () => {
    try {
      const scope = pageScope();
      const title = (document.querySelector('.QuestionHeader-title')?.textContent || '').trim();
      scopeLabel.textContent = scope.scope === 'question' ? '当前问题：' + (title || scope.scope_id) + '（可收集多位作者的回答）' : scope.scope === 'author' ? '当前作者：' + scope.scope_id + '（仅收集本人回答，送入知境后按问题预览）' : '当前专栏文章';
    } catch (error) { scopeLabel.textContent = error.message; }
  };
  updateScope();
  try { connectionLabel.textContent = '已保存连接：' + getConnection().base_url + ' · 发送时验证'; }
  catch { connectionLabel.textContent = '尚未连接知境。请先在知境的「浏览器采集」中打开连接页。'; }
  panel.append(scopeLabel, connectionLabel);
  const status = document.createElement('p'); status.setAttribute('role', 'status');
  const start = createBtn('开始收集并发送', '#be602a', async () => {
    if (collectionJob) { status.textContent = '另一次采集正在进行。'; return; }
    const minimumVotes = Number(panel.querySelector('#__zj_votes__').value);
    const maxItems = Number(panel.querySelector('#__zj_limit__').value);
    if (!Number.isInteger(minimumVotes) || minimumVotes < 0 || minimumVotes > 1000000000 || !Number.isInteger(maxItems) || maxItems < 1 || maxItems > 100) { status.textContent = '请输入有效赞同数，以及 1～100 的篇数。'; return; }
    const job = { cancelled: false, cache: new Map() }; collectionJob = job; start.disabled = true;
    const inputs = [...panel.querySelectorAll('input')]; inputs.forEach(input => { input.disabled = true; });
    updateScope();
    try {
      getConnection();
      const scope = pageScope();
      const auto = panel.querySelector('#__zj_scroll__').checked;
      const deadline = Date.now() + 45000;
      let collected = { items: [], skipped: 0 };
      let stagnant = 0, previousSignature = '';
      for (let step = 0; step < (auto ? 20 : 1); step++) {
        if (job.cancelled || Date.now() >= deadline) break;
        if (pageScope().page_url !== scope.page_url) throw new Error('页面已切换，本次采集已停止，请在新页面重试。');
        if (auto) {
          let unfolded = 0;
          for (const container of contentContainers()) {
            for (const button of expandButtons(container)) {
              if (unfolded >= 10 || job.cancelled) break;
              button.click(); unfolded++;
            }
          }
          if (unfolded) await new Promise(resolve => setTimeout(resolve, 800));
        }
        if (job.cancelled) break;
        collected = gatherItems(scope, minimumVotes, maxItems, job.cache);
        status.textContent = `已筛选 ${collected.items.length} / ${maxItems} 篇回答（已去重）；第 ${step + 1} 轮。`;
        if (!auto || collected.items.length >= maxItems) break;
        const signature = job.cache.size + ':' + document.documentElement.scrollHeight;
        stagnant = signature === previousSignature ? stagnant + 1 : 0; previousSignature = signature;
        if (stagnant >= 3) break;
        window.scrollBy({ top: Math.max(600, Math.round(window.innerHeight * 0.85)), behavior: 'instant' });
        await new Promise(resolve => setTimeout(resolve, 1200));
      }
      if (job.cancelled) { status.textContent = '已取消，未发送本次内容。'; return; }
      const result = await deliver(scope, collected.items);
      connectionLabel.textContent = '连接正常：已送达知境';
      const questions = new Set(collected.items.map(item => item.question_id).filter(Boolean));
      status.textContent = `已发送 ${result.count} 篇${questions.size ? '，涉及 ' + questions.size + ' 个问题' : ''}。请回知境按问题预览并勾选导入；本次仅覆盖已加载且符合条件的内容。`;
    } catch (error) { status.textContent = error.message || '采集失败，请重试。'; }
    finally { if (collectionJob === job) collectionJob = null; start.disabled = false; inputs.forEach(input => { input.disabled = false; }); }
  });
  const cancel = createBtn('取消／关闭', '#5c6b7a', () => {
    if (collectionJob) { collectionJob.cancelled = true; status.textContent = '正在取消采集；若已开始发送，请等待接收结果。'; }
    else panel.remove();
  });
  panel.append(status, start, document.createTextNode(' '), cancel); document.body.appendChild(panel);
}

function getPersist(key, def = false) {
  try {
    if (typeof GM_getValue === 'function') {
      return GM_getValue(key, def);
    }

    return def;
  } catch (_) {
    return def;
  }
}

function setPersist(key, val) {
  try {
    if (typeof GM_setValue === 'function') {
      GM_setValue(key, val);
    }
  } catch (e) {
    console.warn('[知乎伴侣] 持久化失败：', key, e);
  }
}

function removeElement(el) {
  if (el && el.parentNode) {
    el.parentNode.removeChild(el);
  }
}

function escapeHTML(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
})();
