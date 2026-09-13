(() => {
  'use strict';

  const token = document.currentScript.dataset.configToken;
  const $ = id => document.getElementById(id);
  const tools = ['reading', 'author', 'cards', 'facts', 'knowledge'];
  const storageKey = 'zhijing.companion.source.' + token;
  const pageSize = 20;
  const state = {selected: null, revision: 0, sources: [], page: 0, more: false,
    loading: false, choosing: false, importing: false, pending: {}, cards: [], cardIndex: 0,
    revealed: false, exporting: false, nextSourcePage: null};
  let mapCleanup = null, mapRevision = 0;

  function clearMap() {
    mapRevision += 1;
    const cleanup = mapCleanup;
    mapCleanup = null;
    if (typeof cleanup === 'function') cleanup();
  }

  function node(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  }

  function status(id, message, kind = '') {
    $(id).textContent = message;
    $(id).className = 'status ' + kind;
  }

  function notice(value) {
    return String(value || '').replaceAll('模型生成', '自动整理').replaceAll('模型分析', '自动分析')
      .replaceAll('模型根据', '根据').replaceAll('生成器', '分析过程').replaceAll('输入预算', '内容长度')
      .replaceAll('topics', '主题').replaceAll('语料', '资料').replace(/\b(?:Ollama|OpenAI)\b/gi, '分析服务');
  }

  async function request(path, body, binary = false) {
    let response;
    try {
      response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
        headers: body === undefined ? {} : {'Content-Type': 'application/json', 'X-Zhijing-Token': token},
        body: body === undefined ? undefined : JSON.stringify(body)});
    } catch { throw new Error('暂时无法连接知境，请稍后重试。'); }
    if (response.ok && binary) return response.blob();
    let result;
    try { result = await response.json(); } catch { throw new Error('返回内容无法读取，请重试。'); }
    if (!response.ok) {
      const messages = {model_unavailable: '分析服务暂不可用，请稍后重试或联系管理员。',
        model_timeout: '整理时间较长，请稍后重试。', model_invalid_response: '本次未能完整整理，请重试。',
        model_output_truncated: '模型达到输出上限，未完成生成。请减少生成数量（制卡可先试 1～3 张），或在模型设置中提高最大输出 Token；使用思考模型时也可尝试关闭思考。',
        cards_format_invalid: '模型返回的卡片格式或字段长度不符合要求。请先试生成 1～3 张，或换用支持 JSON 输出的模型。',
        cards_evidence_invalid: '卡片证据无法在资料原文中找到，本次未生成卡片。请重试或换用其他模型。',
        model_input_too_large: '资料较长，请分段导入后重试。',
        model_context_exceeded: '资料较长，请分段导入后重试。',
        invalid_config_token: '本次连接已失效，请关闭知境后重新打开。'};
      throw Object.assign(new Error(messages[result?.error?.code] || (response.status === 404
        ? '这条资料暂时无法找到，请刷新后重新选择。'
        : response.status === 422 ? '请检查填写内容和长度后重试。' : '本次未能完成，请稍后重试。')), {status: response.status});
    }
    return result;
  }

  function controls() {
    $('companion-source').disabled = state.loading || state.choosing || state.importing;
    $('companion-refresh').disabled = state.loading || state.choosing || state.importing;
    $('companion-source-prev').disabled = state.loading || state.choosing || state.importing || state.page === 0;
    $('companion-source-next').disabled = state.loading || state.choosing || state.importing || !state.more;
    $('companion-import-submit').disabled = state.importing;
    for (const tool of tools) $('tool-run-' + tool).disabled = !state.selected || state.choosing || state.importing || Boolean(state.pending[tool]) || (tool === 'cards' && state.exporting);
    if ($('tool-card-export')) $('tool-card-export').disabled = state.exporting || !state.cards.length;
  }

  function tab(name, focus = false) {
    for (const tool of tools) {
      const active = tool === name;
      $('tool-tab-' + tool).setAttribute('aria-selected', String(active));
      $('tool-tab-' + tool).tabIndex = active ? 0 : -1;
      $('tool-pane-' + tool).hidden = !active;
    }
    if (focus) $('tool-tab-' + name).focus();
  }

  function disclosure(parent, label, text, className = 'prose') {
    const item = node('details', undefined, 'compact-result');
    item.append(node('summary', label), node('div', text, className));
    parent.append(item);
    return item;
  }

  function longText(parent, text, limit = 700) {
    const value = String(text || '');
    if (value.length <= limit) parent.append(node('div', value, 'prose'));
    else {
      parent.append(node('div', value.slice(0, limit) + '…', 'prose'));
      disclosure(parent, '展开完整内容', value);
    }
  }

  function safeLink(parent, value) {
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol)) return;
      const link = node('a', '来源网页 ↗');
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      parent.append(link);
    } catch { /* Some manually imported sources have no website. */ }
  }

  function citations(parent, evidence) {
    if (!evidence?.length) {
      parent.append(node('p', '没有可展示的原文证据。', 'scope-note'));
      return;
    }
    evidence.forEach((citation, index) => {
      const item = node('details', undefined, 'citation');
      item.append(node('summary', '[' + (index + 1) + '] ' + citation.title));
      if (Number.isInteger(citation.chunk_index)) item.append(node('small', '资料段落 ' + (citation.chunk_index + 1)));
      item.append(node('blockquote', citation.excerpt, 'prose'));
      safeLink(item, citation.url);
      parent.append(item);
    });
  }

  function remember(source) {
    try {
      if (source) sessionStorage.setItem(storageKey, source.id);
      else sessionStorage.removeItem(storageKey);
    } catch { /* Optional state; analysis remains available without browser storage. */ }
  }

  function sourceOptions() {
    const select = $('companion-source');
    const empty = node('option', state.sources.length ? '选择一条资料…' : '还没有资料，请粘贴导入');
    empty.value = '';
    select.replaceChildren(empty);
    const choices = [...state.sources];
    if (state.selected && !choices.some(source => source.id === state.selected.id)) choices.unshift(state.selected);
    for (const source of choices) {
      const option = node('option', source.title + ' · ' + source.author_name);
      option.value = source.id;
      select.append(option);
    }
    select.value = state.selected?.id || '';
    $('companion-source-page').textContent = '第 ' + (state.page + 1) + ' 页';
  }

  function choose(source) {
    clearMap();
    state.selected = source;
    state.revision += 1;
    state.pending = {};
    state.cards = [];
    state.cardIndex = 0;
    state.revealed = false;
    state.exporting = false;
    remember(source);
    for (const tool of tools) {
      $('tool-result-' + tool).replaceChildren();
      $('tool-result-' + tool).setAttribute('aria-busy', 'false');
      status('tool-status-' + tool, '');
    }
    const context = $('companion-source-note');
    context.replaceChildren();
    if (source) {
      const scope = source.content_extent === 'excerpt'
        ? '当前是摘要，不包含完整正文；以下整理仅依据已导入内容。'
        : '以下整理依据已导入资料，引用可对照原文。';
      context.append(node('p', scope, 'scope-note'));
      const preview = disclosure(context, source.content_extent === 'excerpt' ? '查看已导入摘要' : '查看已导入内容', source.text);
      safeLink(preview, source.url);
      $('companion-import').open = false;
    } else context.append(node('p', '先选一条资料，或粘贴正文开始。', 'scope-note'));
    sourceOptions();
    controls();
  }

  async function loadSources(page = state.page) {
    if (state.loading) { state.nextSourcePage = page; return; }
    state.loading = true;
    controls();
    status('companion-status', '正在读取资料…');
    try {
      const items = await request('/api/v1/sources?' + new URLSearchParams({limit: pageSize + 1, offset: page * pageSize}));
      state.sources = items.slice(0, pageSize);
      state.more = items.length > pageSize;
      state.page = page;
      const selectedId = state.selected?.id, revision = state.revision;
      if (selectedId && !items.some(source => source.id === selectedId)) {
        try { await request('/api/v1/sources/' + encodeURIComponent(selectedId)); }
        catch (error) { if (error.status === 404 && state.revision === revision) choose(null); }
      }
      sourceOptions();
      status('companion-status', state.sources.length ? '' : '暂无资料，可以粘贴导入。');
    } catch (error) { status('companion-status', error.message, 'error'); }
    finally {
      state.loading = false; controls();
      if (state.nextSourcePage !== null) {
        const nextPage = state.nextSourcePage; state.nextSourcePage = null;
        await loadSources(nextPage);
      }
    }
  }

  async function restoreSource() {
    if (state.selected) return;
    let id;
    try { id = sessionStorage.getItem(storageKey); } catch { return; }
    if (!id || id.length > 200) return;
    const revision = state.revision;
    try {
      const source = await request('/api/v1/sources/' + encodeURIComponent(id));
      if (state.revision === revision) choose(source);
    } catch {
      if (state.revision !== revision) return;
      remember(null);
      status('companion-status', '上次选择的资料暂时无法读取，请重新选择。');
    }
  }

  function renderReading(result) {
    const root = $('tool-result-reading');
    root.append(node('h3', '阅读要点'));
    longText(root, result.summary);
    root.append(node('p', notice(result.notice), 'scope-note'));
    for (const section of result.sections || []) {
      const item = node('details', undefined, 'compact-result');
      item.append(node('summary', (section.index + 1) + '. ' + section.heading));
      const points = node('ul');
      for (const point of section.key_points || []) points.append(node('li', point));
      item.append(points, node('p', '导读：' + section.guiding_question, 'prose'));
      disclosure(item, '对照原文', section.text);
      root.append(item);
    }
  }

  function renderAnswer(result) {
    const root = $('tool-result-author');
    longText(root, result.answer);
    root.append(node('h3', '原文依据'));
    citations(root, result.citations);
    const explanation = notice([result.identity_notice, result.citation_notice].filter(Boolean).join('\n'));
    if (explanation) disclosure(root, '回答与引用说明', explanation, 'scope-note');
  }

  function showCard() {
    const card = state.cards[state.cardIndex];
    const face = $('tool-card-face');
    face.replaceChildren(node('h3', card.front));
    if (state.revealed) {
      longText(face, card.back);
      if (card.evidence_excerpt) disclosure(face, '原文依据', card.evidence_excerpt);
    }
    $('tool-card-counter').textContent = (state.cardIndex + 1) + ' / ' + state.cards.length;
    $('tool-card-prev').disabled = state.cardIndex === 0;
    $('tool-card-next').disabled = state.cardIndex === state.cards.length - 1;
    $('tool-card-reveal').textContent = state.revealed ? '收起答案' : '查看答案';
    $('tool-card-reveal').setAttribute('aria-expanded', String(state.revealed));
    $('tool-result-cards').scrollTop = 0;
    controls();
  }

  function renderCards(result) {
    state.cards = result.cards;
    state.cardIndex = 0;
    state.revealed = false;
    const root = $('tool-result-cards');
    root.append(node('p', notice(result.notice), 'scope-note'));
    if (!state.cards.length) { root.append(node('p', '当前资料未能整理出卡片。')); return; }
    const face = node('article', undefined, 'card-face'); face.id = 'tool-card-face';
    const actions = node('div', undefined, 'card-actions');
    const counter = node('span'); counter.id = 'tool-card-counter';
    const addButton = (id, text, callback) => {
      const button = node('button', text); button.type = 'button'; button.id = id;
      button.addEventListener('click', callback); actions.append(button); return button;
    };
    addButton('tool-card-prev', '上一张', () => { if (state.cardIndex > 0) { state.cardIndex--; state.revealed = false; showCard(); } });
    actions.append(counter);
    addButton('tool-card-next', '下一张', () => { if (state.cardIndex + 1 < state.cards.length) { state.cardIndex++; state.revealed = false; showCard(); } });
    addButton('tool-card-reveal', '查看答案', () => { state.revealed = !state.revealed; showCard(); });
    addButton('tool-card-export', '导出 TSV', exportCards);
    root.append(face, actions);
    showCard();
  }

  async function exportCards() {
    if (!state.cards.length || state.exporting) return;
    state.exporting = true;
    const revision = state.revision;
    controls();
    status('tool-status-cards', '正在准备文件…');
    try {
      const blob = await request('/api/v1/cards/export/tsv', {deck_name: state.selected.title, cards: state.cards}, true);
      if (revision !== state.revision) return;
      const url = URL.createObjectURL(blob), link = node('a');
      link.href = url; link.download = 'zhijing-cards.tsv';
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      status('tool-status-cards', '文件已准备，请在保存窗口选择位置。', 'success');
    } catch (error) { if (revision === state.revision) status('tool-status-cards', error.message, 'error'); }
    finally { if (revision === state.revision) { state.exporting = false; controls(); } }
  }

  function renderFacts(result) {
    const labels = {mentioned_in_corpus: '资料中有相同表述', related_evidence: '存在相关证据',
      insufficient_evidence: '证据不足', supported_by_evidence: '证据支持',
      refuted_by_evidence: '证据反驳', mixed_evidence: '证据存在分歧'};
    const root = $('tool-result-facts');
    root.append(node('p', '已查阅其他已导入资料，并排除当前这条。未联网核实客观事实。', 'scope-note'));
    root.append(node('p', notice([result.scope, result.analysis_notice].filter(Boolean).join('\n')), 'scope-note'));
    for (const review of result.reviews || []) {
      const item = node('article', undefined, 'compact-result');
      item.append(node('strong', labels[review.status] || '需结合证据判断'), node('h3', review.claim));
      longText(item, review.explanation);
      if (review.conditions?.length) item.append(node('p', '适用条件：' + review.conditions.join('；'), 'prose'));
      citations(item, review.evidence);
      for (const analysis of review.evidence_analysis || []) disclosure(item,
        ({supports: '支持', refutes: '反驳', context: '背景'}[analysis.relation] || '证据解读') + ' · ' + analysis.citation.title, analysis.rationale);
      root.append(item);
    }
  }

  function renderMap(result) {
    clearMap();
    const revision = state.revision, generation = mapRevision;
    const current = () => revision === state.revision && generation === mapRevision;
    mapCleanup = globalThis.ZhijingKnowledgeMap.render($('tool-result-knowledge'), result, {
      compact: true,
      onOpenSource: async sourceId => {
        if (!current()) return;
        let source;
        try { source = await request('/api/v1/sources/' + encodeURIComponent(sourceId)); }
        catch (error) { if (current()) throw error; return; }
        if (!current()) return;
        choose(source);
        tab('reading');
        $('companion-source').focus();
      },
    });
  }

  async function run(tool) {
    if (!state.selected || state.pending[tool] || state.choosing || state.importing || (tool === 'cards' && state.exporting)) return;
    const source = state.selected, revision = state.revision;
    let body, path;
    try {
      if (tool === 'reading') { path = '/api/v1/reading/analyze'; body = {source_id: source.id}; }
      if (tool === 'author') {
        const question = $('tool-question').value.trim();
        if (!question || question.length > 2000) throw new Error('请填写 1 至 2,000 字的问题。');
        path = '/api/v1/author/ask'; body = {author_id: source.author_id, primary_source_id: source.id, question};
      }
      if (tool === 'cards') { path = '/api/v1/cards/generate'; body = {source_id: source.id, count: 3}; }
      if (tool === 'facts') {
        const claims = $('tool-claims').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
        if (!claims.length || claims.length > 5 || claims.some(claim => claim.length > 2000)) throw new Error('每行一条主张，最多 5 条，每条不超过 2,000 字。');
        path = '/api/v1/facts/review'; body = {claims, exclude_source_ids: [source.id]};
      }
      if (tool === 'knowledge') {
        const limit = Number($('tool-knowledge-limit').value);
        if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('请选择 1 至 100 篇资料。');
        const params = new URLSearchParams({limit, primary_source_id: source.id});
        if ($('tool-knowledge-scope').value === 'author') params.set('author_id', source.author_id);
        path = '/api/v1/knowledge-map?' + params;
      }
    } catch (error) { status('tool-status-' + tool, error.message, 'error'); return; }
    const operation = {};
    state.pending[tool] = operation;
    const root = $('tool-result-' + tool);
    if (tool === 'knowledge') clearMap();
    const generation = mapRevision;
    root.replaceChildren(); root.setAttribute('aria-busy', 'true');
    if (tool === 'cards') { state.cards = []; state.exporting = false; }
    status('tool-status-' + tool, '正在整理，请稍候…');
    controls();
    try {
      const result = await request(path, body);
      if (state.revision !== revision || state.pending[tool] !== operation) return;
      if (tool === 'knowledge' && generation !== mapRevision) return;
      ({reading: renderReading, author: renderAnswer, cards: renderCards, facts: renderFacts, knowledge: renderMap})[tool](result);
      status('tool-status-' + tool, tool === 'reading' || tool === 'cards' ? '已整理' : '已完成', 'success');
    } catch (error) {
      if (state.revision === revision && state.pending[tool] === operation && (tool !== 'knowledge' || generation === mapRevision)) status('tool-status-' + tool, error.message, 'error');
    } finally {
      if (state.revision === revision && state.pending[tool] === operation) {
        delete state.pending[tool]; root.setAttribute('aria-busy', 'false'); controls();
      }
    }
  }

  for (const id of ['tool-knowledge-scope', 'tool-knowledge-limit']) $(id).addEventListener('change', () => {
    clearMap();
    $('tool-result-knowledge').replaceChildren();
    status('tool-status-knowledge', '范围已调整，请重新发现联系。');
  });

  for (const tool of tools) {
    $('tool-tab-' + tool).addEventListener('click', () => tab(tool));
    $('tool-tab-' + tool).addEventListener('keydown', event => {
      const index = tools.indexOf(tool);
      const destination = {ArrowRight: (index + 1) % tools.length, ArrowLeft: (index + tools.length - 1) % tools.length, Home: 0, End: tools.length - 1}[event.key];
      if (destination !== undefined) { event.preventDefault(); tab(tools[destination], true); }
    });
    $('tool-form-' + tool).addEventListener('submit', event => { event.preventDefault(); return run(tool); });
  }
  $('companion-source').addEventListener('change', async () => {
    const id = $('companion-source').value;
    if (!id) { choose(null); return; }
    const cached = state.sources.find(source => source.id === id) || (state.selected?.id === id ? state.selected : null);
    if (cached) { choose(cached); return; }
    choose(null);
    state.choosing = true; controls();
    const revision = state.revision;
    try { const source = await request('/api/v1/sources/' + encodeURIComponent(id)); if (revision === state.revision) choose(source); }
    catch (error) { if (revision === state.revision) status('companion-status', error.message, 'error'); }
    finally { state.choosing = false; controls(); }
  });
  $('companion-refresh').addEventListener('click', () => loadSources());
  $('companion-source-prev').addEventListener('click', () => loadSources(Math.max(0, state.page - 1)));
  $('companion-source-next').addEventListener('click', () => { if (state.more) return loadSources(state.page + 1); });
  $('companion-import-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (state.importing) return;
    const text = $('companion-import-text').value;
    if (!text.trim() || text.length > 100000) { status('companion-import-status', '请粘贴正文，最多 100,000 字。', 'error'); return; }
    const title = $('companion-import-title').value.trim() || Array.from(text.trim().split(/\r?\n/)[0]).slice(0, 30).join('') || '随手阅读';
    const name = $('companion-import-name').value.trim() || '未署名';
    state.importing = true; controls();
    status('companion-import-status', '正在保存资料…');
    try {
      const author = 'manual-' + (globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + '-' + Math.random().toString(36).slice(2));
      const saved = await request('/api/v1/sources/import', {items: [{title, author_name: name, author_id: author, text, origin: 'manual'}]});
      if (!saved.length) throw new Error('保存未返回资料，请刷新资料列表后确认。');
      choose(saved[0]);
      await loadSources(0);
      status('companion-status', '已保存并选中，可以开始使用。', 'success');
      status('companion-import-status', '已保存。', 'success');
    } catch (error) { status('companion-import-status', error.message, 'error'); }
    finally { state.importing = false; controls(); }
  });

  document.addEventListener('zhijing:sources-imported', async event => {
    const saved = event.detail?.saved;
    if (!Array.isArray(saved) || !saved.length) return;
    choose(saved[0]);
    await loadSources(0);
  });

  tab('author');
  controls();
  loadSources(0).then(restoreSource);
})();
