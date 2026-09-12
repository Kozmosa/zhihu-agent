'use strict';

const token = document.currentScript.dataset.configToken;
const $ = id => document.getElementById(id);
const modes = {extractive: '离线摘录', ollama: 'Ollama 模型', openai: 'API 模型'};
const tasks = ['reading', 'author', 'cards', 'facts', 'knowledge'];
const state = {selected: null, sources: [], page: 0, more: false, filter: '', busy: false, cards: [], mode: 'extractive', zhihuConfigured: false, zhihuResults: [], chatSourceId: null, chatRevision: 0, chatMessageCount: 0};
const pageSize = 20;
const mobileLayout = globalThis.matchMedia?.('(max-width: 720px)');

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
  $('zhihu-secret').value = '';
  $('import-panel').hidden = false;
  focusPanel('import-panel', 'import-title');
}

function openZhihuPanel() {
  if (state.busy) return;
  $('import-panel').hidden = true;
  $('zhihu-panel').hidden = false;
  return job('zhihu-status', '正在读取知乎配置…', async () => {
    const result = await request('/api/v1/zhihu/status');
    showZhihuConfiguration(result.configured);
    status('zhihu-status', '');
    focusPanel('zhihu-panel', state.zhihuConfigured ? 'zhihu-query' : 'zhihu-secret');
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
  document.querySelectorAll('button').forEach(button => { button.disabled = state.busy; });
  document.querySelectorAll('.requires-source').forEach(button => { button.disabled = state.busy || !state.selected; });
  $('prev-page').disabled = state.busy || state.page === 0;
  $('next-page').disabled = state.busy || !state.more;
  $('export-tsv').disabled = $('export-apkg').disabled = state.busy || !state.cards.length;
  $('run-zhihu-search').disabled = state.busy || !state.zhihuConfigured;
  $('clear-zhihu-secret').disabled = state.busy || !state.zhihuConfigured;
  $('chat-send').disabled = state.busy || !state.selected;
  $('chat-launcher').disabled = $('chat-close').disabled = false;
  state.zhihuResults.forEach(result => { result.button.disabled = state.busy || result.imported; });
}

async function request(path, body, binary = false) {
  let response;
  try {
    response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
      headers: body === undefined ? {} : {'Content-Type': 'application/json', 'X-Zhijing-Token': token},
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error('无法连接本地服务，请确认服务仍在运行。');
  }
  if (response.ok && binary) return response.blob();
  let data;
  try { data = await response.json(); } catch { throw new Error('服务响应无法解析，请检查服务日志。'); }
  if (!response.ok) {
    if (data.error?.message) throw new Error(data.error.message);
    if (Array.isArray(data.detail)) {
      const names = {title: '标题', text: '正文', author_id: '作者 ID', author_name: '作者名称', url: '来源链接', topics: '主题标签', claims: '主张', question: '问题', query: '搜索关键词', access_secret: 'Access Secret', count: '数量', deck_name: '牌组名称'};
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
  $('service-mode').textContent = modes[state.mode] || state.mode;
  $('model-notice').textContent = state.mode === 'extractive'
    ? '当前为离线模式：规则与原文摘录，无模型请求。可在“模型配置”中启用 API。'
    : '当前已启用模型：相关原文、证据和问题会发送至你配置的模型服务。每项操作可能产生 API 用量。';
}

function tab(name) {
  for (const task of tasks) {
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

function updateChatContext() {
  const source = state.selected;
  if (state.chatSourceId !== (source?.id ?? null)) {
    state.chatSourceId = source?.id ?? null;
    state.chatRevision += 1;
    // The empty-state controls live inside the log and must survive source changes.
    const empty = $('chat-empty');
    $('chat-messages').replaceChildren(empty);
    state.chatMessageCount = 0;
    $('chat-question').value = '';
    status('chat-status', '');
  }
  $('chat-context').textContent = source
    ? (source.content_extent === 'excerpt' ? '仅依据摘要 · ' : '当前资料 · ') + source.title
    : '请先选择一篇资料，再开始问答。';
  $('chat-context').title = source
    ? source.title + (source.content_extent === 'excerpt' ? '：仅依据已导入摘要回答，不包含完整正文。' : '：依据已导入资料回答。')
    : '请先选择一篇资料，再开始问答。';
  $('chat-empty').hidden = state.chatMessageCount > 0;
  $('chat-pick-source').hidden = Boolean(source);
  controls();
}

function openChat() {
  updateChatContext();
  $('chat-window').hidden = false;
  $('chat-launcher').setAttribute('aria-expanded', 'true');
  $('chat-question').focus({preventScroll: true});
}

function closeChat() {
  $('chat-window').hidden = true;
  $('chat-launcher').setAttribute('aria-expanded', 'false');
  $('chat-launcher').focus({preventScroll: true});
}

function chatMessage(role, text) {
  const article = element('article', undefined, 'chat-message ' + role);
  article.append(element('div', text, 'chat-message-body'));
  $('chat-messages').append(article);
  state.chatMessageCount += 1;
  $('chat-empty').hidden = true;
  return article;
}

function scrollChat() {
  $('chat-messages').scrollTop = $('chat-messages').scrollHeight;
}

function submitChat() {
  return job('chat-status', '正在根据资料回答…', async () => {
    if (!state.selected) throw new Error('请先在资料库选择一篇资料，再开始问答。');
    const source = state.selected, revision = state.chatRevision;
    const question = $('chat-question').value.trim();
    if (!question || question.length > 2000) throw new Error('请填写 1 至 2,000 字符的问题。');
    chatMessage('user', question);
    $('chat-question').value = '';
    scrollChat();
    let result;
    try {
      await refreshMode();
      if (state.chatRevision !== revision || state.selected?.id !== source.id) return;
      result = await request('/api/v1/author/ask', {author_id: source.author_id, primary_source_id: source.id, question});
    } catch (error) {
      // A response or error from a previous source must never enter the new conversation.
      if (state.chatRevision !== revision || state.selected?.id !== source.id) return;
      if (!$('chat-question').value) $('chat-question').value = question;
      throw error;
    }
    if (state.chatRevision !== revision || state.selected?.id !== source.id) return;
    const answer = chatMessage('assistant', result.answer);
    answer.append(element('div', (modes[result.mode] || result.mode) + ' · ' + (result.identity_notice || '助手根据资料回答，不代表作者本人。'), 'chat-message-meta'));
    const references = element('details', undefined, 'chat-citations');
    references.append(element('summary', '查看引用'));
    citations(references, result.citations);
    if (result.citation_notice) references.append(element('p', result.citation_notice, 'chat-message-meta'));
    answer.append(references);
    status('chat-status', '回答完成。');
    scrollChat();
  });
}

function select(source) {
  state.selected = source;
  state.cards = [];
  $('workspace-empty').hidden = true;
  $('selected-title').textContent = source.title;
  const contentScoped = isContentScoped(source);
  $('selected-meta').textContent = source.author_name + (contentScoped ? ' · 知乎搜索资料' : ' · 作者 ID：' + source.author_id) + ' · ' + source.text.length + ' 字符';
  $('source-preview-label').textContent = source.content_extent === 'excerpt' ? '查看已导入摘要' : source.content_extent === 'fulltext' ? '查看完整原文' : '查看已导入内容';
  $('selected-extent').hidden = source.content_extent !== 'excerpt';
  $('selected-extent').textContent = source.content_extent === 'excerpt' ? '当前资料为摘要，不包含完整正文。后续分析仅依据已导入内容。' : '';
  $('author-scope-notice').textContent = contentScoped
    ? '知乎搜索未提供真实作者 ID，问答仅基于这条已导入内容，不合并同名作者的资料。助手不代表作者本人。'
    : '以当前文章为主要资料，参考同一作者的已导入内容。助手不代表作者本人。';
  $('selected-text').textContent = source.text;
  $('source-preview').hidden = false;
  safeLink($('selected-url'), source.url);
  for (const task of tasks) { $(task + '-result').replaceChildren(); status(task + '-status', ''); }
  renderSources();
  updateChatContext();
  controls();
  if (isSmallScreen()) {
    $('library-drawer').open = false;
    $('zhihu-panel').hidden = true;
    $('import-panel').hidden = true;
    $('zhihu-secret').value = '';
    $('reading-workspace').scrollIntoView?.({block: 'start'});
  }
}

function isContentScoped(source) {
  return source.origin === 'zhihu' && !source.provenance?.external_author_id && source.author_id.startsWith('zhihu-content:');
}

function renderSources() {
  const list = $('source-list');
  list.replaceChildren();
  if (!state.sources.length) list.append(element('div', state.filter ? '这个作者 ID 下没有资料。可清空筛选，或导入资料。' : '资料库还是空的。点击“导入资料”开始。', 'empty'));
  for (const source of state.sources) {
    const button = element('button', undefined, 'source-item');
    button.type = 'button';
    button.setAttribute('aria-pressed', String(state.selected?.id === source.id));
    button.append(element('strong', source.title), element('small', source.author_name + ' · ' + source.text.length + ' 字符' + (source.content_extent === 'excerpt' ? ' · 摘要' : '')));
    button.addEventListener('click', () => { if (!state.busy) select(source); });
    list.append(button);
  }
  $('page-number').textContent = '第 ' + (state.page + 1) + ' 页';
}

async function loadSources(page = state.page, filter = state.filter) {
  // Fetch one extra item to decide whether another page exists.
  const params = new URLSearchParams({offset: String(page * pageSize), limit: String(pageSize + 1)});
  if (filter) params.set('author_id', filter);
  const rows = await request('/api/v1/sources?' + params);
  state.page = page;
  state.filter = filter;
  state.more = rows.length > pageSize;
  state.sources = rows.slice(0, pageSize);
  renderSources();
  status('library-status', '');
}

function requireSource() {
  if (!state.selected) throw new Error('请先在左侧选择一篇资料。');
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
    const attribution = item.author_id.startsWith('zhihu-content:') ? '该条知乎资料' : '作者 ID：' + item.author_id;
    card.append(element('small', attribution + ' · 资料段落 ' + (item.chunk_index + 1)));
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
  status(task + '-status', '完成 · ' + (modes[result.mode] || result.mode) + (extra ? '\n' + extra : ''), 'success');
}

function renderReading(result) {
  const root = $('reading-result');
  root.append(element('h3', '文章摘要'), element('p', result.summary, 'prose'), element('p', result.notice, 'scope-note'));
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
  root.append(element('p', result.citation_notice, 'scope-note'));
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

const factLabels = {mentioned_in_corpus: '语料中有相同表述', related_evidence: '存在相关证据', insufficient_evidence: '证据不足', supported_by_evidence: '证据支持', refuted_by_evidence: '证据反驳', mixed_evidence: '证据存在分歧'};
function renderFacts(result) {
  const root = $('facts-result');
  root.append(element('p', result.scope + '\n' + result.analysis_notice, 'scope-note prose'));
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

function svg(tag, attributes = {}, text) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderGraph(result) {
  const root = $('knowledge-result');
  root.append(element('p', result.classification + '\n' + result.analysis_notice, 'scope-note prose'));
  if (!result.nodes.length) { root.append(element('div', '当前范围还没有知识节点。请先导入资料，或调整范围。', 'empty')); return; }
  const preview = result.nodes.slice(0, 60);
  const positions = new Map(preview.map((node, index) => [node.id, {x: 40 + (index % 3) * 300, y: 35 + Math.floor(index / 3) * 115}]));
  const height = Math.ceil(preview.length / 3) * 115 + 30;
  const canvas = svg('svg', {width: 960, height, viewBox: '0 0 960 ' + height, role: 'group', 'aria-label': '知识关系图，点击节点查看解释；也可使用下方节点列表'});
  canvas.append(svg('title', {}, '知识地图'));
  const defs = svg('defs');
  const marker = svg('marker', {id: 'relation-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse'});
  marker.append(svg('path', {d: 'M 0 0 L 10 5 L 0 10 z', fill: '#a9b8a3'}));
  defs.append(marker); canvas.append(defs);
  for (const edge of result.edges) {
    const start = positions.get(edge.source), end = positions.get(edge.target);
    if (!start || !end) continue;
    const sx = start.x + 125, sy = start.y + 62, ex = end.x + 125, ey = end.y;
    const path = svg('path', {d: `M ${sx} ${sy} C ${sx} ${sy + 25}, ${ex} ${ey - 25}, ${ex} ${ey}`, class: 'graph-edge', 'marker-end': 'url(#relation-arrow)'});
    path.append(svg('title', {}, edge.label)); canvas.append(path);
  }
  const detail = element('div', '选择一个节点，查看解释与原文证据。', 'graph-detail');
  const picker = element('select'); picker.id = 'graph-node-picker';
  const label = element('label', '查看节点'); label.htmlFor = picker.id;
  picker.append(element('option', '请选择节点…')); picker.children[0].value = '';
  const showNode = node => {
    detail.replaceChildren(element('h3', node.data.label), element('p', node.data.description || (node.data.kind === 'answer' ? '资料节点，来自已导入文章。' : '主题分类节点。'), 'prose'));
    citations(detail, node.data.evidence);
    if (node.data.source_id) {
      const open = element('button', '选中这篇资料'); open.type = 'button';
      open.addEventListener('click', () => job('knowledge-status', '正在读取资料…', async () => {
        const source = await request('/api/v1/sources/' + encodeURIComponent(node.data.source_id));
        select(source); tab('reading');
      }));
      detail.append(open);
    }
  };
  result.nodes.forEach((node, index) => { const option = element('option', node.data.label); option.value = String(index); picker.append(option); });
  picker.addEventListener('change', () => { if (picker.value !== '') showNode(result.nodes[Number(picker.value)]); });
  preview.forEach(node => {
    const point = positions.get(node.id);
    const group = svg('g', {class: 'graph-node', 'data-kind': node.data.kind, tabindex: 0, role: 'button', 'aria-label': node.data.label, transform: `translate(${point.x},${point.y})`});
    group.append(svg('rect', {width: 250, height: 62, rx: 10}), svg('title', {}, node.data.label));
    group.append(svg('text', {x: 15, y: 27}, node.data.label.slice(0, 16)), svg('text', {x: 15, y: 47}, node.data.label.slice(16, 31) + (node.data.label.length > 31 ? '…' : '')));
    const activate = () => { picker.value = String(result.nodes.indexOf(node)); showNode(node); };
    group.addEventListener('click', activate);
    group.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); activate(); } });
    canvas.append(group);
  });
  const scroller = element('div', undefined, 'graph-scroll'); scroller.append(canvas);
  root.append(scroller);
  if (result.nodes.length > preview.length) root.append(element('p', '图示显示前 60 个节点，下方列表包含全部节点。', 'muted small'));
  root.append(label, picker, detail, element('h3', '关系与证据'));
  const relations = element('div', undefined, 'relation-list');
  const byId = new Map(result.nodes.map(node => [node.id, node]));
  for (const edge of result.edges) {
    const title = (byId.get(edge.source)?.data.label || edge.source) + ' → ' + (byId.get(edge.target)?.data.label || edge.target) + ' · ' + edge.label;
    const button = element('button', title); button.type = 'button';
    button.addEventListener('click', () => {
      detail.replaceChildren(element('h3', title), element('p', edge.data?.explanation || '根据资料主题标签建立的分类关系。', 'prose'));
      if (edge.data?.evidence?.length) citations(detail, edge.data.evidence);
    });
    relations.append(button);
  }
  if (!result.edges.length) relations.append(element('p', '当前没有可展示的关系。', 'muted'));
  root.append(relations);
}

async function runTask(task, work) {
  return job(task + '-status', '正在处理，请稍候…', async () => {
    $(task + '-result').replaceChildren();
    if (task === 'cards') state.cards = [];
    await refreshMode();
    const result = await work();
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
  $('source-filter').value = '';
  status('import-status', `已保存 ${saved.length} 条资料，已选中第一条。`, 'success');
  try { await loadSources(0, ''); } catch (error) { status('library-status', '资料已保存，但列表刷新失败：' + error.message, 'error'); }
}

function showZhihuConfiguration(configured) {
  state.zhihuConfigured = configured === true;
  $('zhihu-config-state').textContent = state.zhihuConfigured
    ? '知乎凭证已配置，可以搜索。每次搜索最多返回 10 条摘要。'
    : '尚未配置知乎凭证。请展开下方配置，输入 Access Secret 后再搜索。';
  if (!state.zhihuConfigured) $('zhihu-config-panel').open = true;
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
    status('cards-status', '已生成下载文件，请在浏览器下载列表查看。' + (format === 'apkg' ? '打开 APKG 可导入 Anki。' : ''), 'success');
  });
}

for (const task of tasks) {
  $('tab-' + task).addEventListener('click', () => tab(task));
  $('tab-' + task).addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = tasks.indexOf(task);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tasks.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tasks.length) % tasks.length;
    tab(tasks[next]); $('tab-' + tasks[next]).focus();
  });
}
$('open-import').addEventListener('click', openImportPanel);
$('empty-import').addEventListener('click', openImportPanel);
$('close-import').addEventListener('click', () => { $('import-panel').hidden = true; });
$('open-zhihu').addEventListener('click', openZhihuPanel);
$('empty-search').addEventListener('click', openZhihuPanel);
$('chat-launcher').addEventListener('click', () => { if ($('chat-window').hidden) openChat(); else closeChat(); });
$('chat-close').addEventListener('click', closeChat);
$('chat-form').addEventListener('submit', event => { event.preventDefault(); return submitChat(); });
$('chat-question').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    return submitChat();
  }
});
document.addEventListener?.('keydown', event => {
  if (event.key === 'Escape' && !$('chat-window').hidden) { event.preventDefault(); closeChat(); }
});
$('chat-pick-source').addEventListener('click', () => {
  closeChat();
  if (state.sources.length) {
    $('library-drawer').open = true;
    $('library-drawer').scrollIntoView?.({block: 'start'});
    return;
  }
  return openZhihuPanel();
});
$('close-zhihu').addEventListener('click', () => { $('zhihu-panel').hidden = true; $('zhihu-secret').value = ''; });
$('zhihu-config-form').addEventListener('submit', event => {
  event.preventDefault();
  return job('zhihu-config-status', '正在保存知乎凭证…', async () => {
    const accessSecret = $('zhihu-secret').value.trim();
    if (!accessSecret) throw new Error('请填写 Access Secret。');
    const result = await request('/api/v1/zhihu/config', {access_secret: accessSecret});
    $('zhihu-secret').value = '';
    showZhihuConfiguration(result.configured);
    if (!state.zhihuConfigured) throw new Error('凭证未能保存，请重试。');
    status('zhihu-config-status', '已保存到当前服务会话。搜索时会验证凭证是否有效。', 'success');
    $('zhihu-query').focus();
  });
});
$('zhihu-search-form').addEventListener('submit', event => {
  event.preventDefault();
  return job('zhihu-status', '正在搜索知乎摘要…', async () => {
    if (!state.zhihuConfigured) throw new Error('请先配置知乎 Access Secret。');
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
$('clear-zhihu-secret').addEventListener('click', () => job('zhihu-config-status', '正在清除会话凭证…', async () => {
  const result = await request('/api/v1/zhihu/config', {access_secret: ''});
  $('zhihu-secret').value = '';
  showZhihuConfiguration(result.configured);
  if (state.zhihuConfigured) throw new Error('凭证未能清除，请重试。');
  status('zhihu-config-status', '当前服务会话中的知乎凭证已清除。已保存资料仍可使用。', 'success');
}));
$('reload-sources').addEventListener('click', () => job('library-status', '正在刷新…', async () => { await refreshMode(); await loadSources(); }));
$('source-filter-form').addEventListener('submit', event => { event.preventDefault(); return job('library-status', '正在筛选…', () => loadSources(0, $('source-filter').value.trim())); });
$('prev-page').addEventListener('click', () => job('library-status', '正在读取…', () => loadSources(Math.max(0, state.page - 1))));
$('next-page').addEventListener('click', () => job('library-status', '正在读取…', () => loadSources(state.page + 1)));
$('import-form').addEventListener('submit', event => {
  event.preventDefault();
  return job('import-status', '正在保存资料…', async () => {
    const text = $('import-text').value;
    if (!text.trim()) throw new Error('请填写非空正文。');
    const topics = $('import-topics').value.split(/[,，]/).map(value => value.trim()).filter(Boolean);
    if (topics.length > 20 || topics.some(value => value.length > 200)) throw new Error('主题标签最多 20 个，每个最多 200 字符。');
    const item = {title: $('import-title').value.trim(), author_name: $('import-author-name').value.trim(), author_id: $('import-author-id').value.trim(), text, topics, origin: 'manual'};
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
$('knowledge-form').addEventListener('submit', event => { event.preventDefault(); return runTask('knowledge', () => {
  const params = new URLSearchParams({limit: $('graph-limit').value});
  const author = authorScope('graph-scope'); if (author) params.set('author_id', author);
  return request('/api/v1/knowledge-map?' + params);
}); });
$('export-tsv').addEventListener('click', () => exportCards('tsv'));
$('export-apkg').addEventListener('click', () => exportCards('apkg'));

const requestedTask = globalThis.location?.hash.slice(1);
if (tasks.includes(requestedTask)) tab(requestedTask);
syncLibraryDrawer();
mobileLayout?.addEventListener?.('change', syncLibraryDrawer);
updateChatContext();
job('library-status', '正在读取资料库…', async () => { await refreshMode(); await loadSources(); });
