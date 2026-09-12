'use strict';

const token = document.currentScript.dataset.configToken;
const $ = id => document.getElementById(id);
const desktopPage = document.body.dataset?.desktop === 'true';
const sourceStorageKey = 'zhijing.chat.source.' + token;
const tasks = ['reading', 'author', 'cards', 'facts', 'knowledge'];
const state = {selected: null, selectionRevision: 0, sources: [], page: 0, more: false, filter: '', busy: false, cards: [], mode: 'extractive', zhihuConfigured: false, zhihuResults: []};
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
  $('import-panel').hidden = false;
  focusPanel('import-panel', 'import-title');
}

function openZhihuPanel() {
  if (state.busy) return;
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
  document.querySelectorAll('button').forEach(button => { if (!chatRoot?.contains(button) && !questionImport?.contains(button)) button.disabled = state.busy; });
  document.querySelectorAll('.requires-source').forEach(button => { button.disabled = state.busy || !state.selected; });
  $('prev-page').disabled = state.busy || state.page === 0;
  $('next-page').disabled = state.busy || !state.more;
  $('export-tsv').disabled = $('export-apkg').disabled = state.busy || !state.cards.length;
  $('run-zhihu-search').disabled = state.busy || !state.zhihuConfigured;
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
    const messages = {
      model_unavailable: '分析服务暂不可用，请稍后重试或联系管理员。',
      model_timeout: '分析等待超时，请稍后重试。',
      model_invalid_response: '分析未返回完整结果，请重试或联系管理员。',
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
      const names = {title: '标题', text: '正文', author_id: '作者分组', author_name: '作者名称', url: '来源链接', topics: '主题标签', claims: '主张', question: '问题', query: '搜索关键词', count: '数量', deck_name: '牌组名称'};
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

function select(source, notifyChat = true) {
  state.selected = source;
  state.selectionRevision += 1;
  rememberSource(source);
  state.cards = [];
  $('workspace-empty').hidden = true;
  $('selected-title').textContent = source.title;
  const contentScoped = isContentScoped(source);
  $('selected-meta').textContent = source.author_name + (contentScoped ? ' · 知乎搜索资料' : '') + ' · ' + source.text.length + ' 字符';
  $('source-preview-label').textContent = source.content_extent === 'excerpt' ? '查看已导入摘要' : source.content_extent === 'fulltext' ? '查看完整原文' : '查看已导入内容';
  $('selected-extent').hidden = source.content_extent !== 'excerpt';
  $('selected-extent').textContent = source.content_extent === 'excerpt' ? '当前资料为摘要，不包含完整正文。后续分析仅依据已导入内容。' : '';
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
    $('reading-workspace').scrollIntoView?.({block: 'start'});
  }
}

function isContentScoped(source) {
  return source.origin === 'zhihu' && !source.provenance?.external_author_id && source.author_id.startsWith('zhihu-content:');
}

function renderSources() {
  const list = $('source-list');
  list.replaceChildren();
  if (!state.sources.length) list.append(element('div', state.filter ? '这个作者分组下没有资料。可清空筛选，或导入资料。' : '资料库还是空的。点击“导入资料”开始。', 'empty'));
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

function svg(tag, attributes = {}, text) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderGraph(result) {
  const root = $('knowledge-result');
  root.append(element('p', userNotice(result.classification + '\n' + result.analysis_notice), 'scope-note prose'));
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
    const revision = state.selectionRevision;
    let result;
    try {
      await refreshMode();
      if (state.selectionRevision !== revision) return;
      result = await work();
    } catch (error) {
      if (state.selectionRevision !== revision) return;
      throw error;
    }
    if (state.selectionRevision !== revision) return;
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
$('knowledge-form').addEventListener('submit', event => { event.preventDefault(); return runTask('knowledge', () => {
  const params = new URLSearchParams({limit: $('graph-limit').value});
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
  $('source-filter').value = '';
  try { await loadSources(0, ''); status('library-status', '已导入 ' + saved.length + ' 篇回答，并选中第一篇。', 'success'); }
  catch { status('library-status', '回答已保存并选中，资料列表暂未刷新；可稍后点击刷新。', 'error'); }
});
if (tasks.includes(requestedTask)) tab(requestedTask);
syncLibraryDrawer();
mobileLayout?.addEventListener?.('change', syncLibraryDrawer);
job('library-status', '正在读取资料库…', async () => { await refreshMode(); await loadSources(); await restoreSelectedSource(); });
