'use strict';

const token = document.currentScript.dataset.configToken;
const $ = id => document.getElementById(id);
const desktopPage = document.body.dataset?.desktop === 'true';
const sourceStorageKey = 'zhijing.chat.source.' + document.currentScript.dataset.sessionId;
const tasks = ['reading', 'author', 'cards', 'facts', 'knowledge'];
const tabs = ['reading', 'author', 'cards', 'facts', 'opinions', 'knowledge'];
const state = {selected: null, selectionRevision: 0, sources: [], page: 0, more: false, filter: '', busy: false, cards: [], mode: 'extractive', zhihuConfigured: false, zhihuResults: []};
const webImport = {configured: false, results: [], signature: '', origin: 'web', batchId: '', controller: null, retry: false};
const companion = {paired: false, items: []};
const webCriteriaIds = ['web-mode', 'web-url', 'web-min-votes', 'web-max-items'];
const pageSize = 20;
const library = {view: 'question', group: null, groups: [], query: '', checked: new Set()};
const mobileLayout = globalThis.matchMedia?.('(max-width: 720px)');
let mapCleanup = null, mapRevision = 0;
let opinionOpenRevision = 0;
const opinionPanel = globalThis.ZhijingOpinionMap?.mount($('workspace-opinions'), {
  token,
  onOpenSource: async id => {
    const revision = ++opinionOpenRevision;
    const source = await request('/api/v1/sources/' + encodeURIComponent(id));
    if (revision !== opinionOpenRevision || $('pane-opinions').hidden) return;
    select(source); tab('reading');
  },
  onOpenQuestionImport: value => {
    $('workspace-question-import').click();
    const input = $('question-import-url');
    if (input && !input.disabled) { input.value = value; input.focus(); }
  },
});

function clearMap() {
  mapRevision += 1;
  const cleanup = mapCleanup;
  mapCleanup = null;
  if (typeof cleanup === 'function') cleanup();
}

function isSmallScreen() {
  return mobileLayout?.matches ?? (globalThis.innerWidth ?? Infinity) <= 720;
}

function syncLibraryDrawer() {
  $('library-drawer').open = !isSmallScreen();
}

function focusPanel(panelId, inputId) {
  $(inputId).focus({preventScroll: true});
  if (isSmallScreen()) $(panelId).scrollIntoView?.({block: 'start'});
}

function openImportPanel() {
  if (state.busy) return;
  $('zhihu-panel').hidden = true;
  closeWebImportPanel();
  $('import-panel').hidden = false;
  focusPanel('import-panel', 'import-title');
}

function openZhihuPanel() {
  if (state.busy) return;
  closeWebImportPanel();
  $('import-panel').hidden = true;
  $('zhihu-panel').hidden = false;
  return job('zhihu-status', '正在读取搜索服务状态…', async () => {
    const result = await request('/api/v1/zhihu/status');
    showZhihuConfiguration(result.configured);
    status('zhihu-status', '');
    focusPanel('zhihu-panel', 'zhihu-query');
  });
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function status(id, text, kind = '') {
  $(id).textContent = text;
  $(id).className = 'status ' + kind;
}

function controls() {
  const chatRoot = document.getElementById('chat-root');
  const questionImport = document.getElementById('question-import-dialog');
  document.querySelectorAll('button').forEach(button => { if (!chatRoot?.contains(button) && !questionImport?.contains(button) && !button.closest('.knowledge-map') && !button.closest('.opinion-map')) button.disabled = state.busy; });
  document.querySelectorAll('.requires-source').forEach(button => { if (!button.closest('.knowledge-map')) button.disabled = state.busy || !state.selected; });
  $('prev-page').disabled = state.busy || state.page === 0;
  $('next-page').disabled = state.busy || !state.more;
  $('export-tsv').disabled = $('export-apkg').disabled = state.busy || !state.cards.length;
  $('run-zhihu-search').disabled = state.busy || !state.zhihuConfigured;
  state.zhihuResults.forEach(result => { result.button.disabled = state.busy || result.imported; });
  $('library-view').disabled = state.busy;
  $('library-delete').disabled = state.busy || !library.checked.size;
  $('library-select-page').disabled = state.busy || !state.sources.length;
  $('library-select-page').checked = Boolean(state.sources.length) && state.sources.every(source => library.checked.has(source.id));
  $('library-select-page').indeterminate = Boolean(library.checked.size) && !$('library-select-page').checked;
  $('library-delete').textContent = library.checked.size ? `删除选中（${library.checked.size}）` : '删除选中';
  for (const id of [...webCriteriaIds, 'web-cookie']) $(id).disabled = state.busy;
  $('clear-web-cookie').disabled = state.busy || !webImport.configured;
  $('cancel-web-preview').hidden = !webImport.controller;
  $('cancel-web-preview').disabled = !webImport.controller || webImport.controller.signal.aborted;
  const selected = webImport.results.filter(result => result.checkbox.checked && !result.imported).length;
  const completed = webImport.results.filter(result => result.imported).length;
  $('web-selection-bar').hidden = !webImport.results.length;
  $('web-selection-count').textContent = `已选 ${selected} 篇 · 已确认导入 ${completed} 篇 / 共 ${webImport.results.length} 篇`;
  $('web-import-selected').disabled = state.busy || !selected;
  $('web-import-selected').textContent = (webImport.retry ? '重试所选' : '导入所选') + (selected ? `（${selected}）` : '');
  $('web-select-all').disabled = state.busy || completed === webImport.results.length;
  $('web-clear-selection').disabled = state.busy || !selected;
  webImport.results.forEach(result => { result.checkbox.disabled = state.busy || result.imported; });
}

async function request(path, body, binary = false, signal) {
  let response;
  try {
    response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
      headers: body === undefined ? {'X-Zhijing-Token': token} : {'Content-Type': 'application/json', 'X-Zhijing-Token': token},
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('无法连接本地服务，请确认服务仍在运行。');
  }
  if (response.ok && binary) return response.blob();
  let data;
  try { data = await response.json(); } catch { throw new Error('服务响应无法解析，请检查服务日志。'); }
  if (!response.ok) {
    const messages = {
      model_unavailable: '分析服务暂不可用，请稍后重试或联系管理员。',
      model_timeout: '分析等待超时，请稍后重试。',
      model_invalid_response: '分析未返回完整结果，请重试或联系管理员。',
      model_output_truncated: '模型达到输出上限，未完成生成。请减少生成数量（制卡可先试 1～3 张），或在模型设置中提高最大输出 Token；使用思考模型时也可尝试关闭思考。',
      cards_format_invalid: '模型返回的卡片格式或字段长度不符合要求。请先试生成 1～3 张，或换用支持 JSON 输出的模型。',
      cards_evidence_invalid: '卡片证据无法在资料原文中找到，本次未生成卡片。请重试或换用其他模型。',
      model_input_too_large: '当前资料过长，请分段导入后重试。',
      model_context_exceeded: '当前资料过长，请分段导入后重试。',
      zhihu_not_configured: '搜索服务暂未就绪，请联系管理员；也可以导入资料。',
      zhihu_auth_failed: '搜索服务连接未通过验证，请联系管理员；也可以导入资料。',
      zhihu_rate_limited: '搜索次数受限或额度不足，请稍后重试或联系管理员。',
      zhihu_query_rejected: '搜索服务未接受本次关键词，请修改后重试。',
      invalid_config_token: '页面连接已更新，请重新打开后再试。',
    };
    if (messages[data.error?.code]) throw new Error(messages[data.error.code]);
    if (data.error?.code?.startsWith('model_')) throw new Error('本次整理未能完成，请重试或联系管理员。');
    if (data.error?.message) throw new Error(userNotice(data.error.message));
    if (Array.isArray(data.detail)) {
      const names = {title: '标题', text: '正文', author_id: '作者 ID', author_name: '作者名称', url: '来源链接', topics: '主题标签', claims: '主张', question: '问题', query: '搜索关键词', access_secret: 'Access Secret', count: '数量', deck_name: '牌组名称', cookie: '登录状态', mode: '读取范围', min_votes: '最低赞同数', max_items: '最多读取回答数'};
      const fields = [...new Set(data.detail.flatMap(error => error.loc || []).filter(key => names[key]).map(key => names[key]))];
      throw new Error((fields.length ? fields.join('、') : '输入内容') + '未通过校验，请检查是否为空、格式或长度是否超限。');
    }
    throw new Error('请求失败，请检查输入或服务状态。');
  }
  return data;
}

async function job(id, pending, work) {
  if (state.busy) return;
  state.busy = true;
  controls();
  status(id, pending);
  try { await work(); } catch (error) { status(id, error.message, 'error'); }
  finally { state.busy = false; controls(); }
}

async function refreshMode() {
  const health = await request('/health');
  state.mode = health.model_provider;
  $('service-mode').textContent = '资料已就绪';
  $('model-notice').textContent = state.mode === 'extractive'
    ? '当前采用原文摘录与规则整理；结果需结合原文核对。'
    : '相关资料和问题将发送至分析服务；整理结果需结合原文核对。';
}

function userNotice(value) {
  return String(value || '').replaceAll('模型生成', '自动整理').replaceAll('模型分析', '自动分析')
    .replaceAll('模型根据', '根据').replaceAll('生成器', '分析过程').replaceAll('输入预算', '内容长度')
    .replaceAll('topics', '主题').replaceAll('语料', '资料');
}

function rememberSource(source) {
  try { globalThis.sessionStorage.setItem(sourceStorageKey, source.id); }
  catch { /* Reading and analysis still work when browser storage is unavailable. */ }
}

async function restoreSelectedSource() {
  if (state.selected) return;
  let previous;
  try { previous = globalThis.sessionStorage.getItem(sourceStorageKey); } catch { return; }
  if (!previous || previous.length > 200) return;
  const revision = state.selectionRevision;
  try {
    const source = await request('/api/v1/sources/' + encodeURIComponent(previous));
    if (state.selectionRevision === revision) select(source);
  } catch {
    if (state.selectionRevision !== revision) return;
    try { globalThis.sessionStorage.removeItem(sourceStorageKey); } catch { /* Optional browser state. */ }
    status('library-status', '上次选择的资料暂时无法读取，请重新选择。');
  }
}

function tab(name) {
  opinionOpenRevision++;
  opinionPanel?.setActive(name === 'opinions');
  for (const task of tabs) {
    const active = name === task;
    $('tab-' + task).setAttribute('aria-selected', String(active));
    $('tab-' + task).tabIndex = active ? 0 : -1;
    $('pane-' + task).hidden = !active;
  }
}

function safeLink(node, value) {
  node.hidden = true;
  node.removeAttribute('href');
  if (!value) return;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) return;
    node.href = url.href;
    node.target = '_blank';
    node.rel = 'noopener noreferrer';
    node.hidden = false;
  } catch { /* Keep invalid links hidden. */ }
}

function select(source, notifyChat = true) {
  clearMap();
  state.selected = source;
  state.selectionRevision += 1;
  rememberSource(source);
  state.cards = [];
  $('workspace-empty').hidden = true;
  $('selected-title').textContent = source.title;
  const contentScoped = isContentScoped(source);
  $('selected-meta').textContent = source.author_name + (contentScoped ? ' · 知乎搜索资料' : '') + ' · ' + source.text.length + ' 字符';
  $('source-preview-label').textContent = source.content_extent === 'excerpt' ? '查看已导入摘要' : source.content_extent === 'fulltext' ? '查看完整原文' : '查看已导入内容';
  const unverifiedZhihuText = source.origin === 'zhihu' && source.content_extent === 'unknown';
  $('selected-extent').hidden = source.content_extent !== 'excerpt' && !unverifiedZhihuText;
  $('selected-extent').textContent = source.content_extent === 'excerpt' ? '当前资料为摘要，不包含完整正文。后续分析仅依据已导入内容。'
    : unverifiedZhihuText ? '当前资料的正文完整性未核验。后续分析仅依据已导入内容。' : '';
  $('author-scope-notice').textContent = contentScoped
    ? '问答仅基于这条已导入内容，不自动合并其他同名作者的资料。助手不代表作者本人。'
    : '以当前文章为主要资料，参考同一作者的已导入内容。助手不代表作者本人。';
  $('selected-text').textContent = source.text;
  $('source-preview').hidden = false;
  safeLink($('selected-url'), source.url);
  for (const task of tasks) { $(task + '-result').replaceChildren(); status(task + '-status', ''); }
  renderSources();
  controls();
  if (notifyChat) document.dispatchEvent(new CustomEvent('zhijing:source-selected', {detail: source}));
  $('zhihu-panel').hidden = true;
  $('import-panel').hidden = true;
  if (isSmallScreen()) {
    $('library-drawer').open = false;
    $('zhihu-panel').hidden = true;
    $('import-panel').hidden = true;
      closeWebImportPanel();
    $('reading-workspace').scrollIntoView?.({block: 'start'});
  }
}

function isContentScoped(source) {
  return source.origin === 'zhihu' && !source.provenance?.external_author_id && source.author_id.startsWith('zhihu-content:');
}

function renderSources() {
  const list = $('source-list');
  list.replaceChildren();
  const grouping = library.view !== 'all' && library.group === null;
  $('library-selection').hidden = grouping;
  $('library-back').hidden = library.group === null;
  const questionGroup = library.view === 'question' && Boolean(library.group?.key);
  $('library-back').textContent = library.view === 'question' ? '← 返回全部问题' : '← 返回全部作者';
  $('library-scope').textContent = library.group ? library.group.name + ' · ' + library.group.count + (questionGroup ? ' 篇回答' : ' 条资料') : (library.view === 'question' ? '先选问题，再查看不同作者的回答' : '');
  $('library-search').placeholder = grouping ? (library.view === 'question' ? '搜索问题标题或问题 ID' : '搜索作者姓名或作者 ID') : '搜索问题、作者或正文';
  if (grouping) {
    if (!library.groups.length) list.append(element('p', library.query ? '没有匹配的分组。请尝试其他关键词。' : '资料库还是空的。点击“导入资料”开始。', 'empty'));
    for (const group of library.groups) {
      const button = element('button', undefined, 'source-item library-group'); button.type = 'button';
      const isQuestion = library.view === 'question' && Boolean(group.key);
      button.append(element('span', isQuestion ? '问题' : library.view === 'author' ? '作者' : '其他资料', 'library-group-kind'), element('strong', group.name), element('small', group.count + (isQuestion ? ' 篇回答 · 问题 ' + group.key + ' →' : ' 条资料' + (group.key ? ' · ' + group.key : '') + ' →')));
      button.setAttribute('aria-label', (isQuestion ? '问题：' : '') + group.name + '，' + group.count + (isQuestion ? ' 篇回答' : ' 条资料'));
      button.addEventListener('click', () => job('library-status', '正在读取分组…', async () => {
        library.group = group; library.query = ''; $('library-search').value = '';
        await loadSources(0, library.view === 'author' ? group.key : '');
      }));
      list.append(button);
    }
    $('page-number').textContent = '第 ' + (state.page + 1) + ' 页';
    return;
  }
  if (!state.sources.length) list.append(element('div', state.filter || library.group || library.query ? '当前筛选下没有资料。可返回分组、清空筛选，或导入资料。' : '资料库还是空的。点击“导入资料”开始。', 'empty'));
  for (const source of state.sources) {
    const button = element('button', undefined, 'source-item');
    button.type = 'button';
    button.setAttribute('aria-pressed', String(state.selected?.id === source.id));
    button.append(element('strong', questionGroup ? source.author_name + '的回答' : source.title), element('small', source.author_name + ' · ' + source.text.length + ' 字符' + (source.content_extent === 'excerpt' ? ' · 摘要' : source.origin === 'zhihu' && source.content_extent === 'unknown' ? ' · 完整性未核验' : '')));
    if (questionGroup) button.append(element('span', source.text.replace(/\s+/g, ' ').slice(0, 100), 'library-answer-preview'));
    button.addEventListener('click', () => { if (!state.busy) select(source); });
    const row = element('div', undefined, 'library-source-row');
    const checkbox = element('input'); checkbox.type = 'checkbox'; checkbox.checked = library.checked.has(source.id);
    checkbox.setAttribute('aria-label', '选择删除：' + source.title + ' · ' + source.author_name);
    checkbox.addEventListener('change', () => {
      if (state.busy) { checkbox.checked = library.checked.has(source.id); return; }
      if (checkbox.checked) library.checked.add(source.id); else library.checked.delete(source.id);
      controls();
    });
    row.append(checkbox, button); list.append(row);
  }
  $('page-number').textContent = '第 ' + (state.page + 1) + ' 页';
}

async function loadSources(page = state.page, filter = state.filter) {
  // Fetch one extra item to decide whether another page exists.
  const params = new URLSearchParams({offset: String(page * pageSize), limit: String(pageSize + 1)});
  if (filter) params.set('author_id', filter);
  library.checked.clear();
  if (library.view !== 'all' && library.group === null) {
    params.set('by', library.view); params.set('q', library.query); params.set('limit', String(pageSize));
    const groups = await request('/api/v1/sources/groups?' + params);
    if (!groups.items.length && page > 0) return loadSources(page - 1, '');
    library.groups = groups.items; state.sources = []; state.page = page; state.more = groups.has_more; state.filter = '';
    renderSources(); status('library-status', `${groups.total} 个${library.view === 'author' ? '作者' : '问题'}分组`); return;
  }
  if (library.view === 'question' && library.group) params.set('question_id', library.group.key);
  let rows;
  if (library.query) {
    params.set('q', library.query);
    rows = (await request('/api/v1/sources/search?' + params)).items;
  } else rows = await request('/api/v1/sources?' + params);
  if (!rows.length && page > 0) return loadSources(page - 1, filter);
  state.page = page;
  state.filter = filter;
  state.more = rows.length > pageSize;
  state.sources = rows.slice(0, pageSize);
  renderSources();
  status('library-status', '');
}

function resetLibrary(view = library.view) {
  library.view = view; library.group = null; library.query = ''; library.checked.clear();
  $('library-view').value = view; $('library-search').value = '';
}

function clearSelectedSource() {
  clearMap(); state.selected = null; state.selectionRevision++; state.cards = [];
  try { globalThis.sessionStorage.removeItem(sourceStorageKey); } catch { /* Optional. */ }
  $('workspace-empty').hidden = false; $('selected-title').textContent = '选择一份资料，开始阅读';
  $('selected-meta').textContent = ''; $('selected-text').textContent = ''; $('source-preview').hidden = true;
  $('selected-extent').hidden = true; safeLink($('selected-url'), null);
  for (const task of tasks) { $(task + '-result').replaceChildren(); status(task + '-status', ''); }
}

function requireSource() {
  if (!state.selected) throw new Error('请先选择一篇资料。');
  return state.selected;
}

function authorScope(control) {
  return $(control).value === 'author' ? requireSource().author_id : undefined;
}

function citations(parent, items) {
  if (!items?.length) { parent.append(element('p', '没有可展示的引用证据。', 'muted small')); return; }
  items.forEach((item, index) => {
    const card = element('div', undefined, 'citation');
    card.append(element('strong', '[' + (index + 1) + '] ' + item.title));
    card.append(element('small', '资料段落 ' + (item.chunk_index + 1)));
    card.append(element('blockquote', item.excerpt));
    const link = element('a', '查看来源网页 ↗');
    safeLink(link, item.url);
    card.append(link);
    parent.append(card);
  });
}

function details(parent, title, text) {
  const node = element('details');
  node.append(element('summary', title), element('div', text, 'original'));
  parent.append(node);
}

function finished(task, result, extra = '') {
  status(task + '-status', (task === 'reading' || task === 'cards' ? '已整理' : '已完成') + (extra ? '\n' + userNotice(extra) : ''), 'success');
}

function renderReading(result) {
  const root = $('reading-result');
  root.append(element('h3', '文章摘要'), element('p', result.summary, 'prose'), element('p', userNotice(result.notice), 'scope-note'));
  for (const section of result.sections) {
    const article = element('article', undefined, 'result-item');
    article.append(element('h3', (section.index + 1) + '. ' + section.heading));
    const points = element('ul');
    section.key_points.forEach(point => points.append(element('li', point)));
    article.append(points, element('p', '导读：' + section.guiding_question, 'prose'));
    details(article, '对照原文', section.text);
    root.append(article);
  }
}

function renderAnswer(result) {
  const root = $('author-result');
  root.append(element('p', result.identity_notice, 'scope-note'), element('div', result.answer, 'prose answer'), element('h3', '参考资料'));
  citations(root, result.citations);
  root.append(element('p', userNotice(result.citation_notice), 'scope-note'));
}

function renderCards(result) {
  state.cards = result.cards;
  const root = $('cards-result');
  if (!result.cards.length) root.append(element('div', '没有生成卡片。请尝试其他资料。', 'empty'));
  result.cards.forEach((card, index) => {
    const article = element('article', undefined, 'memory-card');
    article.append(element('div', 'CARD ' + String(index + 1).padStart(2, '0'), 'eyebrow'), element('h3', card.front));
    details(article, '查看答案', card.back);
    if (card.evidence_excerpt) details(article, '原文依据', card.evidence_excerpt);
    root.append(article);
  });
}

const factLabels = {mentioned_in_corpus: '资料中有相同表述', related_evidence: '存在相关证据', insufficient_evidence: '证据不足', supported_by_evidence: '证据支持', refuted_by_evidence: '证据反驳', mixed_evidence: '证据存在分歧'};
function renderFacts(result) {
  const root = $('facts-result');
  root.append(element('p', userNotice(result.scope + '\n' + result.analysis_notice), 'scope-note prose'));
  for (const review of result.reviews) {
    const article = element('article', undefined, 'result-item');
    article.append(element('div', factLabels[review.status] || review.status, 'fact-label'), element('h3', review.claim), element('p', review.explanation, 'prose'));
    if (review.conditions?.length) article.append(element('p', '适用条件：' + review.conditions.join('；'), 'prose'));
    citations(article, review.evidence);
    for (const analysis of review.evidence_analysis || []) {
      const relation = {supports: '支持', refutes: '反驳', context: '背景'}[analysis.relation] || analysis.relation;
      article.append(element('p', relation + ' · ' + analysis.citation.title + '：' + analysis.rationale, 'muted small prose'));
    }
    root.append(article);
  }
}

function renderGraph(result) {
  clearMap();
  const revision = state.selectionRevision, generation = mapRevision;
  const current = () => revision === state.selectionRevision && generation === mapRevision;
  mapCleanup = globalThis.ZhijingKnowledgeMap.render($('knowledge-result'), result, {
    compact: false,
    onOpenSource: async sourceId => {
      if (!current()) return;
      let source;
      try { source = await request('/api/v1/sources/' + encodeURIComponent(sourceId)); }
      catch (error) { if (current()) throw error; return; }
      if (!current()) return;
      select(source);
      tab('reading');
      $('selected-title').scrollIntoView?.({block: 'nearest'});
    },
  });
}

async function runTask(task, work) {
  return job(task + '-status', '正在处理，请稍候…', async () => {
    if (task === 'knowledge') clearMap();
    $(task + '-result').replaceChildren();
    if (task === 'cards') state.cards = [];
    const revision = state.selectionRevision;
    const generation = mapRevision;
    const current = () => state.selectionRevision === revision && (task !== 'knowledge' || generation === mapRevision);
    let result;
    try {
      await refreshMode();
      if (!current()) return;
      result = await work();
    } catch (error) {
      if (!current()) return;
      throw error;
    }
    if (!current()) return;
    ({reading: renderReading, author: renderAnswer, cards: renderCards, facts: renderFacts, knowledge: renderGraph})[task](result);
    let extra = task === 'cards' ? result.notice : '';
    if (task === 'knowledge') extra = `${result.nodes.length} 个节点 · ${result.edges.length} 条关系 · 范围内 ${result.total_sources} 篇资料` + (result.truncated ? '\n本次仅使用数量上限内的资料，未覆盖整个范围。' : '');
    finished(task, result, extra);
  });
}

async function saveSources(items) {
  const saved = await request('/api/v1/sources/import', {items});
  if (!saved.length) throw new Error('导入没有返回资料。');
  // The write succeeded even if refreshing the list later fails.
  select(saved[0]);
  resetLibrary();
  $('source-filter').value = '';
  status('import-status', `已保存 ${saved.length} 条资料，已选中第一条。`, 'success');
  try {
    await loadSources(0, '');
    status('library-status', `已保存 ${saved.length} 条资料，可以开始使用下方功能。`, 'success');
  } catch (error) { status('library-status', '资料已保存，但列表刷新失败：' + error.message, 'error'); }
}

function showZhihuConfiguration(configured) {
  state.zhihuConfigured = configured === true;
  $('zhihu-config-state').textContent = state.zhihuConfigured
    ? '搜索服务已就绪。每次搜索最多返回 10 条摘要。'
    : '搜索服务暂未就绪，请联系管理员；也可以导入资料。';
  controls();
}

function renderZhihuResults(items) {
  const root = $('zhihu-results');
  root.replaceChildren();
  state.zhihuResults = [];
  if (!items.length) root.append(element('div', '没有可导入的摘要。可以调整关键词后重新搜索。', 'empty'));
  for (const source of items) {
    const article = element('article', undefined, 'zhihu-result');
    article.append(element('h3', source.title, 'zhihu-result-title'));
    const meta = element('div', undefined, 'zhihu-result-meta');
    meta.append(element('span', '知乎摘要', 'badge'), element('span', source.author_name + ' · ' + source.text.length + ' 字符', 'muted small'));
    const excerpt = element('details', undefined, 'zhihu-excerpt-details');
    const summary = element('summary');
    const preview = source.text.slice(0, 180) + (source.text.length > 180 ? '…' : '');
    const toggle = element('span', '展开摘要', 'excerpt-toggle');
    summary.append(element('span', preview, 'zhihu-excerpt'), toggle);
    excerpt.append(summary, element('div', source.text, 'zhihu-excerpt-full'));
    excerpt.addEventListener('toggle', () => { toggle.textContent = excerpt.open ? '收起摘要' : '展开摘要'; });
    article.append(meta, excerpt);
    const actions = element('div', undefined, 'actions zhihu-result-actions');
    const link = element('a', '查看知乎来源 ↗');
    safeLink(link, source.url);
    const button = element('button', '导入摘要');
    button.type = 'button';
    const result = {source, imported: false, button};
    button.addEventListener('click', () => {
      if (result.imported) return;
      return job('zhihu-status', '正在导入摘要…', async () => {
        await saveSources([source]);
        result.imported = true;
        button.textContent = '已导入';
        status('zhihu-status', '摘要已保存并选中。后续分析仅依据已导入摘要。', 'success');
      });
    });
    state.zhihuResults.push(result);
    actions.append(button, link);
    article.append(actions);
    root.append(article);
  }
  controls();
}

function closeWebImportPanel() {
  $('web-import-panel').hidden = true;
  $('web-cookie').value = '';
}

function showWebConfiguration(configured) {
  webImport.configured = configured === true;
  $('web-config-state').textContent = webImport.configured
    ? '当前服务会话已配置登录状态，读取时会验证是否有效。'
    : '默认尝试公开访问，无需先配置登录状态。';
  controls();
}

function openWebImportPanel() {
  if (state.busy) return;
  $('zhihu-panel').hidden = true;
  $('import-panel').hidden = true;
  $('web-import-panel').hidden = false;
  return job('companion-status', '正在读取接收列表…', async () => {
    // A failure in the optional direct-reader settings must not hide received batches.
    const results = await Promise.allSettled([
      loadCompanionInbox(),
      request('/api/v1/zhihu/web/status').then(result => {
        showWebConfiguration(result.configured);
        status('web-config-status', '');
      }),
    ]);
    if (results[1].status === 'rejected') status('web-config-status', results[1].reason.message, 'error');
    if (results[0].status === 'rejected') throw results[0].reason;
  }).then(() => { if (!$('web-import-panel').hidden) focusPanel('web-import-panel', 'refresh-companion'); });
}

async function loadCompanionInbox() {
  const [connection, inbox] = await Promise.all([
    request('/api/v1/zhihu/companion/status'),
    request('/api/v1/zhihu/companion/inbox'),
  ]);
  if (!Array.isArray(inbox.items)) throw new Error('接收列表无法读取，请刷新后重试。');
  companion.paired = connection.paired === true;
  companion.items = inbox.items;
  $('companion-pair-state').textContent = companion.paired
    ? '已连接浏览器采集助手。前往知乎读取并发送回答后，点击“刷新接收列表”。'
    : '尚未连接。安装脚本后，在浏览器中刷新当前工作台，点击“连接当前知境”。';
  renderCompanionInbox();
  status('companion-status', inbox.items.length ? `收到 ${inbox.items.length} 批回答，等待你预览并选择导入。` : '暂时没有待导入的回答。', inbox.items.length ? 'success' : '');
}

function refreshCompanionInbox() {
  return job('companion-status', '正在刷新接收列表…', loadCompanionInbox);
}

function renderCompanionInbox() {
  const root = $('companion-inbox');
  root.replaceChildren();
  for (const batch of companion.items) {
    const article = element('article', undefined, 'companion-batch');
    article.append(element('h4', batch.label || (batch.scope === 'author' ? '同一作者的回答' : '知乎回答')));
    const date = new Date(batch.captured_at);
    article.append(element('p', `${batch.count} 篇 · ${Number.isNaN(date.getTime()) ? '采集时间未知' : date.toLocaleString('zh-CN')}`, 'muted small'));
    const link = element('a', '查看采集页面 ↗'); safeLink(link, batch.page_url);
    const actions = element('div', undefined, 'actions');
    const preview = element('button', '预览并导入'); preview.type = 'button';
    preview.addEventListener('click', () => previewCompanionBatch(batch.batch_id));
    const dismiss = element('button', '移出接收列表', 'quiet'); dismiss.type = 'button';
    dismiss.addEventListener('click', () => dismissCompanionBatch(batch.batch_id));
    actions.append(preview, dismiss);
    article.append(link, actions);
    root.append(article);
  }
  controls();
}

function previewCompanionBatch(batchId) {
  return job('web-status', '正在读取浏览器发送的回答…', async () => {
    clearWebResults();
    const result = await request('/api/v1/zhihu/companion/inbox/' + encodeURIComponent(batchId));
    if (result.batch_id !== batchId || !Array.isArray(result.items)) throw new Error('收到的回答批次不匹配，请刷新接收列表后重新选择。');
    webImport.origin = 'companion';
    webImport.batchId = batchId;
    webImport.signature = 'companion:' + batchId;
    renderWebResults(result.items);
    const report = [`${result.target_label ? result.target_label + '：' : ''}浏览器发送了 ${result.items.length} 篇可预览回答。`, '以下内容来自采集时页面实际加载的回答，尚未保存到资料库。'];
    if (result.skipped_count) report.push(`已略过 ${result.skipped_count} 条无法导入的内容。`);
    if (result.has_more) report.push('还有未加载的回答，本次采集不代表全部内容。');
    if (result.warning) report.push(result.warning);
    if (result.items.length) report.push('请核对正文，取消不需要的回答后点击“导入所选”。');
    status('web-status', report.join('\n'), result.items.length ? 'success' : '');
  });
}

function dismissCompanionBatch(batchId) {
  return job('companion-status', '正在移出接收列表…', async () => {
    const result = await request('/api/v1/zhihu/companion/inbox/' + encodeURIComponent(batchId) + '/dismiss', {});
    if (result.removed !== true) throw new Error('尚未确认移出，请刷新接收列表后重试。');
    if (webImport.origin === 'companion' && webImport.batchId === batchId) {
      clearWebResults();
      status('web-status', '该批回答已移出接收列表，已导入的资料仍保留在资料库。');
    }
    await loadCompanionInbox();
  });
}

function webCriteriaSignature() {
  return JSON.stringify(webCriteriaIds.map(id => $(id).value));
}

function clearWebResults() {
  webImport.results = [];
  webImport.signature = '';
  webImport.origin = 'web';
  webImport.batchId = '';
  webImport.retry = false;
  $('web-results').replaceChildren();
  controls();
}

function webCriteriaChanged() {
  if (state.busy || webImport.origin === 'companion') return;
  const hadResults = webImport.results.length > 0;
  clearWebResults();
  status('web-status', hadResults ? '读取条件已改变，请重新读取并预览。' : '');
}

function renderWebResults(items) {
  const root = $('web-results');
  root.replaceChildren();
  webImport.results = [];
  const questionGroups = new Map();
  if (!items.length) root.append(element('div', '本次没有符合条件且可读取正文的回答。可调整赞同数或更换链接后重试。', 'empty'));
  for (const item of items) {
    const source = item.draft;
    let questionId = null;
    try {
      const url = new URL(source.provenance?.canonical_url || source.url);
      if (url.protocol === 'https:' && ['www.zhihu.com', 'zhihu.com'].includes(url.hostname) && !url.username && !url.password && !url.port) {
        questionId = url.pathname.match(/^\/question\/(\d+)(?:\/answer\/\d+)?\/?$/)?.[1] || null;
      }
    } catch { /* Unassociated articles remain individual previews. */ }
    let group = questionId && questionGroups.get(questionId);
    if (questionId && !group) {
      const section = element('section', undefined, 'web-question-group');
      const header = element('div', undefined, 'web-question-heading');
      const count = element('span', '', 'muted small');
      header.append(element('span', '问题', 'library-group-kind'), element('h3', source.title), count);
      section.append(header); root.append(section);
      group = {section, count, size: 0}; questionGroups.set(questionId, group);
    }
    if (group) { group.size++; group.count.textContent = `${group.size} 篇回答 · 问题 ${questionId} · 勾选后导入`; }
    const article = element('article', undefined, 'zhihu-result web-result');
    const heading = element('label', undefined, 'web-result-heading');
    const checkbox = element('input'); checkbox.type = 'checkbox'; checkbox.checked = true;
    checkbox.setAttribute('aria-label', '选择回答：' + source.title + ' · ' + source.author_name);
    heading.append(checkbox, element('span', group ? source.author_name + '的回答' : source.title, 'zhihu-result-title'));
    const importedLabel = element('span', '可导入', 'badge');
    const meta = element('div', undefined, 'zhihu-result-meta');
    const votes = item.voteup_count == null ? '赞同数未知' : `${item.voteup_count} 赞同`;
    const extent = source.content_extent === 'excerpt' ? '摘要' : webImport.origin === 'companion'
      ? '页面已加载内容 · 完整性未核验' : source.content_extent === 'fulltext' ? '回答正文' : '完整性未核验';
    meta.append(importedLabel, element('span', `${source.author_name} · ${votes} · ${source.text.length} 字符`, 'muted small'), element('span', extent, 'web-extent'));
    const excerpt = element('details', undefined, 'web-text-details');
    const preview = source.text.slice(0, 220) + (source.text.length > 220 ? '…' : '');
    excerpt.append(element('summary', source.content_extent === 'excerpt' ? '查看本次读取的摘要' : '查看本次读取的回答内容'), element('div', source.text, 'zhihu-excerpt-full'));
    const link = element('a', '查看知乎原回答 ↗'); safeLink(link, source.url);
    article.append(heading, meta, element('p', preview, 'web-text-preview'), excerpt, link);
    const result = {item, checkbox, imported: false, importedLabel};
    checkbox.addEventListener('change', () => {
      if (state.busy || result.imported) return;
      controls();
    });
    webImport.results.push(result);
    (group ? group.section : root).append(article);
  }
  controls();
}

function previewWebAnswers() {
  return job('web-status', '正在读取回答正文，请稍候…', async () => {
    clearWebResults();
    const mode = $('web-mode').value, url = $('web-url').value.trim();
    const minVotes = Number($('web-min-votes').value), maxItems = Number($('web-max-items').value);
    if (!['question', 'author'].includes(mode)) throw new Error('请选择问题或作者读取范围。');
    if (!url || url.length > 2048) throw new Error('请填写有效的知乎问题或作者主页链接。');
    if (!$('web-min-votes').value.trim() || !Number.isInteger(minVotes) || minVotes < 0 || minVotes > 1000000000) throw new Error('最低赞同数必须是 0 至 1,000,000,000 的整数。');
    if (!Number.isInteger(maxItems) || maxItems < 1 || maxItems > 100) throw new Error('最多读取回答数必须是 1 至 100 的整数。');
    const signature = webCriteriaSignature();
    const controller = new AbortController();
    webImport.controller = controller;
    controls();
    try {
      const result = await request('/api/v1/zhihu/web/preview', {url, mode, min_votes: minVotes, max_items: maxItems}, false, controller.signal);
      if (controller.signal.aborted) return;
      if (signature !== webCriteriaSignature()) {
        status('web-status', '读取条件已改变，本次结果已丢弃，请重新读取。');
        return;
      }
      webImport.signature = signature;
      renderWebResults(result.items);
      const count = result.items.length;
      const report = [`${result.target_label ? result.target_label + '：' : ''}本次可导入 ${count} 篇回答。`, `已读取 ${result.pages_fetched} 页，检查 ${result.scanned_count} 条，略过 ${result.skipped_count} 条。`];
      if (result.has_more) report.push('还有未读取的回答。本次结果仅覆盖已访问范围。');
      if (result.warning) report.push(result.warning);
      if (count) report.push('已默认选中本次结果，可取消不需要的回答后导入。');
      status('web-status', report.join('\n'), count ? 'success' : '');
    } catch (error) {
      if (controller.signal.aborted || error.name === 'AbortError') {
        status('web-status', '已取消等待，尚未导入资料。本次网页读取可能仍在结束，请稍后重试。');
        return;
      }
      if (signature !== webCriteriaSignature()) {
        status('web-status', '读取条件已改变，本次结果已丢弃，请重新读取。');
        return;
      }
      throw error;
    } finally {
      webImport.controller = null;
    }
  });
}

function importWebSelection() {
  return job('web-status', '正在导入所选回答…', async () => {
    const expectedSignature = webImport.origin === 'companion' ? 'companion:' + webImport.batchId : webCriteriaSignature();
    if (!webImport.signature || webImport.signature !== expectedSignature) {
      clearWebResults();
      throw new Error('读取条件已改变，请重新预览后再导入。');
    }
    // Capture both rows and payload before awaiting: later form or selection changes
    // cannot alter which answers a running import sends or acknowledges.
    const selected = webImport.results.filter(result => result.checkbox.checked && !result.imported);
    const drafts = selected.map(result => JSON.parse(JSON.stringify(result.item.draft)));
    if (!selected.length) throw new Error('请先选择需要导入的回答。');
    let completed = 0, failure = null;
    for (let offset = 0; offset < drafts.length; offset += 20) {
      const batch = drafts.slice(offset, offset + 20);
      try {
        const saved = await request('/api/v1/sources/import', {items: batch});
        if (!Array.isArray(saved) || saved.length !== batch.length) throw new Error('当前批次的保存结果未能完整确认。');
        for (const result of selected.slice(offset, offset + batch.length)) {
          result.imported = true;
          result.checkbox.checked = false;
          result.importedLabel.textContent = '已导入';
        }
        completed += batch.length;
        controls();
        status('web-status', `本次已确认导入 ${completed} / ${drafts.length} 篇回答…`);
      } catch (error) { failure = error; break; }
    }
    webImport.retry = Boolean(failure);
    if (failure) {
      status('web-status', `本次已确认导入 ${completed} 篇，剩余 ${drafts.length - completed} 篇未确认。\n${failure.message}\n保留了未确认的选择，可点击“重试所选”。未确认批次可能已保存，重复导入相同内容不会新增重复记录。`, 'error');
    } else {
      status('web-status', `本次已确认导入 ${completed} 篇回答。可在左侧资料库选择阅读，同一作者的回答可一起用于答主问答。重复内容会复用已有记录。`, 'success');
    }
    // Even a lost response can follow a successful write; refresh without replacing
    // the batch outcome or sending its full answer payload to the chat widget.
    try { resetLibrary(); await loadSources(0, ''); $('source-filter').value = ''; }
    catch (error) { status('library-status', '导入状态见批量面板。资料列表刷新失败：' + error.message, 'error'); }
  });
}

async function saveWebCookie(clear = false) {
  return job('web-config-status', clear ? '正在清除会话登录状态…' : '正在保存登录状态…', async () => {
    try {
      const cookie = clear ? '' : $('web-cookie').value.trim();
      if (!clear && !cookie) throw new Error('请输入登录状态，或使用“清除会话登录状态”。');
      const result = await request('/api/v1/zhihu/web/config', {cookie});
      showWebConfiguration(result.configured);
      if (webImport.configured === clear) throw new Error('登录状态未能更新，请重试。');
      status('web-config-status', clear ? '当前服务会话的登录状态已清除。' : '已保存到当前服务会话。输入框已清空，读取时会验证是否有效。', 'success');
    } finally { $('web-cookie').value = ''; }
  });
}

async function exportCards(format) {
  return job('cards-status', '正在生成下载文件…', async () => {
    if (!state.cards.length) throw new Error('请先生成卡片。');
    const deck = $('deck-name').value.trim();
    if (!deck) throw new Error('请填写牌组名称。');
    const blob = await request('/api/v1/cards/export/' + format, {deck_name: deck, cards: state.cards}, true);
    const url = URL.createObjectURL(blob);
    const link = element('a'); link.href = url; link.download = 'zhijing-cards.' + format;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status('cards-status', (desktopPage ? '已生成文件，请选择保存位置。' : '已生成下载文件，请在浏览器下载列表查看。') + (format === 'apkg' ? '打开文件可导入 Anki。' : ''), 'success');
  });
}

for (const task of tabs) {
  $('tab-' + task).addEventListener('click', () => tab(task));
  $('tab-' + task).addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = tabs.indexOf(task);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tab(tabs[next]); $('tab-' + tabs[next]).focus();
  });
}
$('open-import').addEventListener('click', openImportPanel);
$('empty-import').addEventListener('click', openImportPanel);
$('close-import').addEventListener('click', () => { $('import-panel').hidden = true; });
$('open-zhihu').addEventListener('click', openZhihuPanel);
$('empty-search').addEventListener('click', openZhihuPanel);
$('open-web-import').addEventListener('click', openWebImportPanel);
$('refresh-companion').addEventListener('click', refreshCompanionInbox);
$('close-web-import').addEventListener('click', () => { if (!state.busy) closeWebImportPanel(); });
$('web-direct-panel').addEventListener('toggle', () => { if (!$('web-direct-panel').open) $('web-cookie').value = ''; });
$('web-config-panel').addEventListener('toggle', () => { if (!$('web-config-panel').open) $('web-cookie').value = ''; });
$('web-config-form').addEventListener('submit', event => { event.preventDefault(); return saveWebCookie(); });
$('clear-web-cookie').addEventListener('click', () => saveWebCookie(true));
$('web-preview-form').addEventListener('submit', event => { event.preventDefault(); return previewWebAnswers(); });
$('cancel-web-preview').addEventListener('click', () => {
  if (!webImport.controller) return;
  webImport.controller.abort();
  status('web-status', '已取消等待，尚未导入资料。本次网页读取可能仍在结束，请稍后重试。');
  controls();
});
$('web-mode').addEventListener('change', () => {
  if (state.busy) return;
  const author = $('web-mode').value === 'author';
  $('web-url-label').textContent = author ? '知乎作者主页链接' : '知乎问题链接';
  $('web-url').placeholder = author ? 'https://www.zhihu.com/people/…' : 'https://www.zhihu.com/question/…';
  $('web-min-votes').value = author ? '0' : '100';
  webCriteriaChanged();
});
for (const id of webCriteriaIds.slice(1)) $(id).addEventListener('input', webCriteriaChanged);
$('web-select-all').addEventListener('click', () => {
  if (state.busy) return;
  webImport.results.forEach(result => { result.checkbox.checked = !result.imported; });
  controls();
});
$('web-clear-selection').addEventListener('click', () => {
  if (state.busy) return;
  webImport.results.forEach(result => { result.checkbox.checked = false; });
  controls();
});
$('web-import-selected').addEventListener('click', importWebSelection);
document.addEventListener('zhijing:chat-source-selected', event => {
  const source = event.detail;
  if (source?.id && source.id !== state.selected?.id) select(source, false);
});
$('close-zhihu').addEventListener('click', () => { $('zhihu-panel').hidden = true; });
$('zhihu-search-form').addEventListener('submit', event => {
  event.preventDefault();
  return job('zhihu-status', '正在搜索知乎摘要…', async () => {
    if (!state.zhihuConfigured) throw new Error('搜索服务暂未就绪，请联系管理员；也可以导入资料。');
    const query = $('zhihu-query').value.trim(), count = Number($('zhihu-count').value);
    if (!query || query.length > 200) throw new Error('请填写 1 至 200 字符的搜索关键词。');
    if (!Number.isInteger(count) || count < 1 || count > 10) throw new Error('结果数量必须是 1 至 10 的整数。');
    $('zhihu-results').replaceChildren();
    state.zhihuResults = [];
    const result = await request('/api/v1/zhihu/search', {query, count});
    renderZhihuResults(result.items);
    const skipped = result.skipped_count ? ` 已略过 ${result.skipped_count} 条缺少有效摘要的结果。` : '';
    status('zhihu-status', result.items.length ? `找到 ${result.items.length} 条摘要，请选择要导入的内容。` + skipped : (result.empty_reason || '未找到可导入的摘要。') + skipped, result.items.length ? 'success' : '');
  });
});
$('reload-sources').addEventListener('click', () => job('library-status', '正在刷新…', async () => { await refreshMode(); await loadSources(); }));
$('source-filter-form').addEventListener('submit', event => { event.preventDefault(); return job('library-status', '正在筛选…', () => { resetLibrary('all'); return loadSources(0, $('source-filter').value.trim()); }); });
$('library-view').addEventListener('change', () => job('library-status', '正在读取分组…', async () => {
  library.view = $('library-view').value; library.group = null; library.query = ''; $('library-search').value = ''; $('source-filter').value = '';
  await loadSources(0, '');
}));
$('library-back').addEventListener('click', () => job('library-status', '正在读取分组…', async () => {
  library.group = null; library.query = ''; $('library-search').value = ''; await loadSources(0, '');
}));
$('library-search-form').addEventListener('submit', event => { event.preventDefault(); return job('library-status', '正在搜索…', async () => {
  library.query = $('library-search').value.trim(); await loadSources(0);
}); });
$('library-select-page').addEventListener('change', () => {
  if (state.busy) return;
  library.checked = new Set($('library-select-page').checked ? state.sources.map(source => source.id) : []);
  renderSources(); controls();
});
$('library-delete').addEventListener('click', () => {
  if (state.busy || !library.checked.size) return;
  const rows = state.sources.filter(source => library.checked.has(source.id));
  const description = rows.slice(0, 5).map(source => '• ' + source.title + ' · ' + source.author_name).join('\n');
  if (!window.confirm(`从资料库删除选中的 ${rows.length} 条资料？\n\n${description}${rows.length > 5 ? '\n…' : ''}\n\n删除后不再用于新的阅读、问答和检索。历史任务与导出文件保留；重新导入相同资料可恢复。`)) return;
  return job('library-status', '正在删除资料…', async () => {
    const ids = rows.map(source => source.id);
    const result = await request('/api/v1/sources/delete', {source_ids: ids});
    if (state.selected && ids.includes(state.selected.id)) clearSelectedSource();
    document.dispatchEvent(new CustomEvent('zhijing:sources-deleted', {detail: {source_ids: ids}}));
    if (library.group) library.group.count = Math.max(0, library.group.count - result.deleted_count);
    try { await loadSources(); status('library-status', `已删除 ${result.deleted_count} 条资料。`, 'success'); }
    catch { library.checked.clear(); state.sources = state.sources.filter(source => !ids.includes(source.id)); renderSources(); status('library-status', '删除已完成，列表刷新失败，请点击刷新。', 'error'); }
  });
});
$('prev-page').addEventListener('click', () => job('library-status', '正在读取…', () => loadSources(Math.max(0, state.page - 1))));
$('next-page').addEventListener('click', () => job('library-status', '正在读取…', () => loadSources(state.page + 1)));
$('import-form').addEventListener('submit', event => {
  event.preventDefault();
  return job('import-status', '正在保存资料…', async () => {
    const text = $('import-text').value;
    if (!text.trim()) throw new Error('请填写非空正文。');
    const topics = $('import-topics').value.split(/[,，]/).map(value => value.trim()).filter(Boolean);
    if (topics.length > 20 || topics.some(value => value.length > 200)) throw new Error('主题标签最多 20 个，每个最多 200 字符。');
    // A display name does not prove two texts share an author. Unspecified groups stay separate.
    const authorId = $('import-author-id').value.trim() || 'manual-' + (globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + '-' + Math.random().toString(36).slice(2));
    const item = {title: $('import-title').value.trim(), author_name: $('import-author-name').value.trim(), author_id: authorId, text, topics, origin: 'manual'};
    const url = $('import-url').value.trim(); if (url) item.url = url;
    await saveSources([item]);
  });
});
$('import-json').addEventListener('click', () => job('import-status', '正在读取导入文件…', async () => {
  const file = $('import-file').files[0];
  if (!file) throw new Error('请先选择 JSON 文件。');
  if (file.size > 10000000) throw new Error('文件超过 10 MB，请拆分后导入。');
  let data; try { data = JSON.parse(await file.text()); } catch { throw new Error('文件不是有效 JSON，请检查格式。'); }
  const items = Array.isArray(data) ? data : data?.items;
  if (!Array.isArray(items) || items.length < 1 || items.length > 20) throw new Error('请提供包含 1 至 20 条资料的 items 数组。');
  await saveSources(items);
}));
$('reading-form').addEventListener('submit', event => { event.preventDefault(); return runTask('reading', () => request('/api/v1/reading/analyze', {source_id: requireSource().id})); });
$('author-form').addEventListener('submit', event => { event.preventDefault(); return runTask('author', () => {
  const source = requireSource(), question = $('author-question').value.trim();
  if (!question) throw new Error('请先填写问题。');
  return request('/api/v1/author/ask', {author_id: source.author_id, primary_source_id: source.id, question});
}); });
$('cards-form').addEventListener('submit', event => { event.preventDefault(); return runTask('cards', () => request('/api/v1/cards/generate', {source_id: requireSource().id, count: Number($('card-count').value)})); });
$('facts-form').addEventListener('submit', event => { event.preventDefault(); return runTask('facts', () => {
  const claims = $('fact-claims').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  if (!claims.length || claims.length > 20 || claims.some(value => value.length > 2000)) throw new Error('请填写 1 至 20 条主张，每条最多 2,000 字符。');
  return request('/api/v1/facts/review', {claims, author_id: authorScope('fact-scope'), exclude_source_ids: $('exclude-current').checked && state.selected ? [state.selected.id] : []});
}); });
function resetMapScope() {
  clearMap();
  $('knowledge-result').replaceChildren();
  status('knowledge-status', '范围已调整，请重新生成思维导图。');
}
$('graph-scope').addEventListener('change', resetMapScope);
$('graph-limit').addEventListener('input', resetMapScope);
$('graph-limit').addEventListener('change', resetMapScope);
$('knowledge-form').addEventListener('submit', event => { event.preventDefault(); return runTask('knowledge', () => {
  const params = new URLSearchParams({limit: $('graph-limit').value});
  if (state.selected) params.set('primary_source_id', state.selected.id);
  const author = authorScope('graph-scope'); if (author) params.set('author_id', author);
  return request('/api/v1/knowledge-map?' + params);
}); });
$('export-tsv').addEventListener('click', () => exportCards('tsv'));
$('export-apkg').addEventListener('click', () => exportCards('apkg'));

const requestedTask = globalThis.location?.hash.slice(1);
document.addEventListener('zhijing:sources-imported', async event => {
  const saved = event.detail?.saved;
  if (!Array.isArray(saved) || !saved.length) return;
  select(saved[0]);
  resetLibrary();
  $('source-filter').value = '';
  try { await loadSources(0, ''); status('library-status', '已导入 ' + saved.length + ' 篇回答，并选中第一篇。', 'success'); }
  catch { status('library-status', '回答已保存并选中，资料列表暂未刷新；可稍后点击刷新。', 'error'); }
});
if (tabs.includes(requestedTask)) tab(requestedTask);
syncLibraryDrawer();
mobileLayout?.addEventListener?.('change', syncLibraryDrawer);
globalThis.addEventListener?.('hashchange', () => {
  if (globalThis.location?.hash === '#companion') openWebImportPanel();
});
job('library-status', '正在读取资料库…', async () => { await refreshMode(); await loadSources(); await restoreSelectedSource(); }).then(() => {
  if (globalThis.location?.hash === '#companion') return openWebImportPanel();
});
