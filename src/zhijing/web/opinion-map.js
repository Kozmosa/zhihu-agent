(() => {
  'use strict';

  const make = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  };
  const button = (text, fn, className = '') => {
    const node = make('button', text, className); node.type = 'button';
    node.addEventListener('click', fn); return node;
  };
  const safeUrl = value => {
    try {
      const url = new URL(value);
      if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) return url;
    } catch { /* A pasted answer may have no source URL. */ }
    return null;
  };
  const questionId = value => {
    const url = safeUrl(value);
    return url?.protocol === 'https:' && ['www.zhihu.com', 'zhihu.com'].includes(url.hostname)
      ? url.pathname.match(/^\/question\/(\d+)\/?$/)?.[1] || null : null;
  };
  const answerQuestion = source => {
    const url = safeUrl(source.provenance?.canonical_url || source.url);
    return url && ['www.zhihu.com', 'zhihu.com'].includes(url.hostname)
      ? url.pathname.match(/^\/question\/(\d+)\/answer\/\d+\/?$/)?.[1] || null : null;
  };
  const isAnswer = source => source.provenance?.content_type === 'answer' || Boolean(answerQuestion(source))
    || (!source.provenance && source.origin !== 'zhihu');
  const extent = source => ({fulltext: '标记为全文', excerpt: '摘录', unknown: '完整性未确认'}[source.content_extent] || '完整性未确认');
  const sourceLink = source => {
    const url = safeUrl(source.url || source.provenance?.canonical_url);
    if (!url) return null;
    const link = make('a', '查看来源 ↗'); link.href = url.href;
    link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
  };

  function mount(root, {token, compact = false, onOpenSource, onOpenQuestionImport} = {}) {
    root.classList.add('opinion-map');
    if (compact) root.classList.add('opinion-map-compact');
    const state = {active: false, revision: 0, controller: null, busy: false, sources: [], selected: new Set(),
      offset: 0, hasMore: false, loaded: false, searchRows: [], result: null, flowCleanup: null};
    const intro = make('header', undefined, 'om-intro');
    intro.append(make('span', '围绕问题，看见不同答案', 'om-eyebrow'), make('h1', '知识地图'),
      make('p', '把不同作者的回答按观点归类，比较共同点、分歧和适用条件。'));
    const form = make('form', undefined, 'om-question-form');
    const questionLabel = make('label', '你想弄清什么问题？');
    const question = make('textarea'); question.rows = 2; question.maxLength = 2000; question.required = true;
    question.placeholder = '输入问题，或粘贴知乎问题链接'; question.setAttribute('aria-label', '知识地图问题');
    questionLabel.append(question);
    const actions = make('div', undefined, 'om-question-actions');
    const search = button('搜索相关回答', searchAnswers);
    const collect = button('读取这个问题的回答', openCollector);
    collect.hidden = true;
    actions.append(search, collect);
    const help = make('p', '搜索用于寻找候选回答；请核对与问题的相关性，再勾选归类。', 'om-hint');
    form.append(questionLabel, actions, help);

    const candidates = make('section', undefined, 'om-candidates'); candidates.hidden = true;
    candidates.setAttribute('aria-label', '候选回答预览');
    const candidateHeading = make('h2', '候选回答 · 先预览再导入');
    const candidateList = make('div', undefined, 'om-source-list');
    const importButton = button('导入勾选回答', importCandidates);
    candidates.append(candidateHeading, make('p', '搜索返回的是摘录，可能来自不同问题。导入只保存本机资料，不会自动归类。', 'om-hint'), candidateList, importButton);

    const library = make('details', undefined, 'om-library'); library.open = true;
    const libraryTitle = make('summary', '选择用于归类的回答');
    const libraryTools = make('div', undefined, 'om-library-tools');
    const filter = make('input'); filter.type = 'search'; filter.placeholder = '筛选作者或标题'; filter.maxLength = 200;
    filter.setAttribute('aria-label', '筛选用于归类的回答');
    const reload = button('刷新', () => loadSources(true));
    libraryTools.append(filter, reload);
    const selection = make('div', undefined, 'om-selection');
    const selectVisible = button('勾选当前列表', () => {
      for (const source of visibleSources()) { if (state.selected.size >= 50) break; state.selected.add(source.id); }
      invalidateResult(); renderSources();
    });
    const clear = button('清空选择', () => { state.selected.clear(); invalidateResult(); renderSources(); });
    const selectionCount = make('span', '已选 0 篇'); selectionCount.setAttribute('aria-live', 'polite');
    selection.append(selectVisible, clear, selectionCount);
    const sourceList = make('div', undefined, 'om-source-list');
    const libraryNote = make('p', '', 'om-hint');
    const more = button('加载更多资料', () => loadSources(false)); more.hidden = true;
    library.append(libraryTitle, libraryTools, selection, sourceList, libraryNote, more);
    const runRow = make('div', undefined, 'om-run-row');
    const run = button('按观点归类', classify, 'primary');
    const stop = button('停止等待', () => { cancel(); message('已停止等待；已发出的分析请求可能仍在服务端完成。'); }); stop.hidden = true;
    runRow.append(run, stop, make('span', '仅分析所选回答 · 最多 50 篇', 'om-hint'));
    const progress = make('p', '', 'om-status'); progress.setAttribute('role', 'status'); progress.setAttribute('aria-live', 'polite');
    const results = make('section', undefined, 'om-results'); results.setAttribute('aria-label', '观点分类结果');
    root.replaceChildren(intro, form, candidates, library, runRow, progress, results);

    function message(text, error = false) { progress.textContent = text; progress.classList.toggle('om-error', error); }
    function controls() {
      search.disabled = collect.disabled = reload.disabled = more.disabled = state.busy;
      run.disabled = state.busy || !question.value.trim() || !state.selected.size;
      importButton.disabled = state.busy || !state.searchRows.some(row => row.checkbox.checked && !row.imported);
      stop.hidden = !state.busy;
      selectVisible.disabled = clear.disabled = state.busy;
      sourceList.querySelectorAll('input').forEach(input => { input.disabled = state.busy; });
      state.searchRows.forEach(row => { row.checkbox.disabled = state.busy || row.imported; });
      selectionCount.textContent = '已选 ' + state.selected.size + ' 篇';
      root.setAttribute('aria-busy', String(state.busy));
    }
    function cancel() {
      state.revision++; state.controller?.abort(); state.controller = null; state.busy = false; controls();
    }
    function invalidateResult() { state.flowCleanup?.(); state.flowCleanup = null; state.result = null; results.replaceChildren(); }
    async function request(path, body, signal) {
      const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', cache: 'no-store', signal,
        headers: body === undefined ? {} : {'Content-Type': 'application/json', 'X-Zhijing-Token': token},
        body: body === undefined ? undefined : JSON.stringify(body)});
      let data;
      try { data = await response.json(); } catch { throw new Error('服务返回内容无法读取，请稍后重试。'); }
      if (!response.ok) {
        const messages = {
          opinion_model_required: '观点归类需要分析服务。请联系管理员启用后重试；思维导图仍可离线使用。',
          opinion_no_sources: '没有可分析的回答，请先导入或重新选择回答。',
          opinion_source_question_mismatch: '所选回答不属于这个知乎问题，请刷新并重新选择。',
          opinion_invalid_question: '请填写问题文字或完整的知乎问题链接。',
          model_unavailable: '分析服务暂不可用，请稍后重试或联系管理员。',
          model_timeout: '分析等待超时，请减少回答数量后重试。',
          model_invalid_response: '观点或引用未通过核对，请重试；也可以减少所选回答。',
          model_input_too_large: '所选回答超出分析长度，请减少回答数量。',
          model_context_exceeded: '所选回答超出分析长度，请减少回答数量。',
          zhihu_not_configured: '知乎搜索服务尚未就绪。可以先选择已导入回答，或联系管理员。',
          zhihu_auth_failed: '知乎搜索验证失败，请联系管理员。',
          zhihu_rate_limited: '搜索额度或频率受限，请稍后再试。',
          invalid_config_token: '页面连接已更新，请重新打开。',
          source_not_found: '所选资料已不可用，请刷新回答列表。',
        };
        throw new Error(messages[data.error?.code] || (response.status === 422
          ? '请检查问题与所选回答是否匹配；问题链接只可归类该问题下的回答。'
          : '本次未能完成，请稍后重试。'));
      }
      return data;
    }
    async function operation(pending, work) {
      if (state.busy || !state.active) return;
      const revision = ++state.revision, controller = new AbortController();
      state.controller = controller; state.busy = true; controls(); message(pending);
      const current = () => state.active && revision === state.revision;
      try { await work(controller.signal, current); }
      catch (error) {
        if (current() && error.name !== 'AbortError') message(error instanceof TypeError ? '无法连接本机服务，请确认知境仍在运行。' : error.message, true);
      } finally { if (current()) { state.busy = false; state.controller = null; controls(); } }
    }
    function visibleSources() {
      const qid = questionId(question.value.trim()), keyword = filter.value.trim().toLocaleLowerCase();
      return state.sources.filter(source => isAnswer(source) && (!qid || answerQuestion(source) === qid)
        && (!keyword || (source.author_name + ' ' + source.title).toLocaleLowerCase().includes(keyword)));
    }
    function sourceRow(source, checked, changed) {
      const article = make('article', undefined, 'om-source');
      const label = make('label', undefined, 'om-source-label');
      const checkbox = make('input'); checkbox.type = 'checkbox'; checkbox.checked = checked;
      const names = make('span'); names.append(make('strong', source.author_name || '未署名'), make('span', source.title || '回答', 'om-source-title'));
      label.append(checkbox, names); article.append(label);
      const meta = make('div', undefined, 'om-source-meta'); meta.append(make('span', extent(source), 'om-tag'));
      if (!answerQuestion(source) && !source.provenance) meta.append(make('span', '手动资料 · 请确认为回答', 'om-hint'));
      const link = sourceLink(source); if (link) meta.append(link); article.append(meta);
      if (source.text) {
        const preview = make('details'); preview.append(make('summary', '预览已导入文字'), make('p', source.text, 'om-original')); article.append(preview);
      }
      checkbox.addEventListener('change', () => changed(checkbox));
      return {article, checkbox, source, imported: false};
    }
    function renderSources() {
      const sources = visibleSources(); sourceList.replaceChildren();
      for (const source of sources) {
        const row = sourceRow(source, state.selected.has(source.id), checkbox => {
          if (checkbox.checked && state.selected.size >= 50) { checkbox.checked = false; message('一次最多选择 50 篇回答。'); return; }
          if (checkbox.checked) state.selected.add(source.id); else state.selected.delete(source.id);
          invalidateResult(); controls();
        });
        sourceList.append(row.article);
      }
      if (!sources.length) sourceList.append(make('p', questionId(question.value.trim())
        ? '已加载资料中没有该问题的回答。点击上方读取，预览后导入。' : '暂无可选回答。可以搜索、导入，或修改筛选条件。', 'om-empty'));
      libraryNote.textContent = '已加载 ' + state.sources.length + ' 篇资料，当前显示 ' + sources.length + ' 篇候选回答。请确认回答对应问题；文章不参与归类。';
      more.hidden = !state.hasMore; controls();
    }
    async function loadSources(reset = false) {
      return operation('正在读取本机回答…', async (signal, current) => {
        const offset = reset ? 0 : state.offset;
        const items = await request('/api/v1/sources?limit=100&offset=' + offset, undefined, signal);
        if (!current()) return;
        if (!Array.isArray(items)) throw new Error('回答列表无法读取，请刷新后重试。');
        const combined = reset ? items : [...state.sources, ...items];
        state.sources = [...new Map(combined.map(item => [item.id, item])).values()];
        state.offset = offset + items.length; state.hasMore = items.length === 100; state.loaded = true;
        if (reset) { state.selected = new Set([...state.selected].filter(id => state.sources.some(source => source.id === id))); invalidateResult(); }
        renderSources(); message('选择围绕同一问题的回答，比较不同作者的观点。');
      });
    }
    async function searchAnswers() {
      const value = question.value.trim();
      if (!value || value.length > 200) { message('请输入不超过 200 字的搜索问题；较长问题可直接选择已有回答归类。', true); return; }
      if (safeUrl(value) || /^https?:/i.test(value)) { message('知乎问题链接请使用“读取这个问题的回答”，不会替换为关键词搜索。', true); return; }
      return operation('正在搜索相关回答摘录…', async (signal, current) => {
        const data = await request('/api/v1/zhihu/search', {query: value, count: 10}, signal);
        if (!current()) return;
        const items = (Array.isArray(data.items) ? data.items : []).filter(isAnswer);
        const omitted = (data.items?.length || 0) - items.length;
        state.searchRows = []; candidateList.replaceChildren(); candidates.hidden = false;
        for (const source of items) {
          const row = sourceRow(source, false, controls); state.searchRows.push(row); candidateList.append(row.article);
        }
        if (!items.length) candidateList.append(make('p', '没有找到可供归类的回答摘录。可改用问题链接读取回答。', 'om-empty'));
        message('找到 ' + items.length + ' 篇候选回答摘录。' + (omitted ? ' 已略过 ' + omitted + ' 篇非回答内容。' : '') + '请核对问题和正文后再导入。');
      });
    }
    async function importCandidates() {
      const rows = state.searchRows.filter(row => row.checkbox.checked && !row.imported);
      if (!rows.length) return;
      return operation('正在保存勾选回答…', async (signal, current) => {
        // Saving is explicit. A tab switch can stop waiting, but does not undo a completed import.
        const saved = await request('/api/v1/sources/import', {items: rows.map(row => row.source)}, signal);
        if (!Array.isArray(saved) || !saved.every(source => typeof source?.id === 'string')) throw new Error('保存结果无法确认，请刷新资料列表。');
        document.dispatchEvent(new CustomEvent('zhijing:sources-imported', {detail: {saved, origin: 'opinion-map'}}));
        if (!current()) return;
        for (const row of rows) { row.imported = true; row.checkbox.checked = false; row.article.append(make('span', '已导入', 'om-tag')); }
        acceptImported(saved); renderSources(); message('已导入 ' + saved.length + ' 篇回答并选中，可点击“按观点归类”。');
      });
    }
    function acceptImported(saved) {
      const qid = questionId(question.value.trim());
      for (const source of saved) {
        if (!state.sources.some(item => item.id === source.id)) state.sources.unshift(source);
        if (isAnswer(source) && (!qid || answerQuestion(source) === qid) && state.selected.size < 50) state.selected.add(source.id);
      }
      invalidateResult(); renderSources();
    }
    function openCollector() {
      const value = question.value.trim();
      if (!questionId(value)) { message('请填写 https://www.zhihu.com/question/数字 形式的问题链接。', true); return; }
      if (typeof onOpenQuestionImport === 'function') onOpenQuestionImport(value);
      else message('请使用页面的“导入知乎问题”入口，粘贴此问题链接。');
    }
    async function classify() {
      const value = question.value.trim();
      if (!value || !state.selected.size) { message('先填写问题并选择要归类的回答。', true); return; }
      if ((safeUrl(value) || /^https?:/i.test(value)) && !questionId(value)) { message('请填写问题文字，或知乎问题链接。', true); return; }
      invalidateResult();
      return operation('正在对照原文、归纳不同观点…', async (signal, current) => {
        const data = await request('/api/v1/opinion-map', {question: value, source_ids: [...state.selected], limit: 50}, signal);
        if (!current()) return;
        state.result = data; renderResult(data); library.open = false;
        message('已归类 ' + data.classified_sources + ' 篇回答；请展开观点核对作者与原文依据。');
      });
    }
    function authorCard(position) {
      const card = make('article', undefined, 'om-author-card');
      const title = make('div', undefined, 'om-author-title');
      title.append(make('strong', position.author_name || '未署名'), make('span', extent(position), 'om-tag'));
      if (position.author_identity_known === false) title.append(make('span', '作者身份未确认', 'om-tag'));
      if (position.stance) title.append(make('span', position.stance, 'om-stance'));
      card.append(title, make('p', position.title, 'om-answer-title'), make('p', position.summary, 'om-position'));
      if (position.partial_analysis) card.append(make('p', '本次仅分析已导入文字中的 ' + position.analyzed_chars + ' / ' + position.total_chars + ' 字符。', 'om-hint'));
      const evidence = make('details', undefined, 'om-evidence');
      evidence.append(make('summary', '原文依据 · ' + (position.evidence?.length || 0) + ' 处'));
      for (const citation of position.evidence || []) {
        const quote = make('blockquote', citation.excerpt); evidence.append(quote);
        if (Number.isInteger(citation.chunk_index)) evidence.append(make('span', '资料段落 ' + (citation.chunk_index + 1), 'om-hint'));
      }
      card.append(evidence);
      const links = make('div', undefined, 'om-card-links'); const link = sourceLink(position); if (link) links.append(link);
      if (typeof onOpenSource === 'function') links.append(button('在知境中阅读', async () => {
        const revision = state.revision;
        try { await onOpenSource(position.source_id); }
        catch { if (state.active && revision === state.revision) message('这条资料暂时无法打开，请刷新资料列表。', true); }
      }));
      card.append(links); return card;
    }
    function renderResult(data) {
      results.replaceChildren();
      const overview = make('div', undefined, 'om-overview');
      overview.append(make('h2', data.question), make('p', '本次 ' + data.included_sources + ' 篇回答 · ' + data.groups.length + ' 类观点 · ' + data.known_author_count + ' 位可识别作者'));
      if (data.unknown_author_sources) overview.append(make('p', data.unknown_author_sources + ' 篇回答的作者身份未确认，未合并统计为同一作者。', 'om-hint'));
      overview.append(make('p', data.analysis_notice || '仅反映本次所选回答，不代表问题下全部回答或作者的完整立场。', 'om-hint'));
      if (data.truncated) overview.append(make('p', '本次分析有内容或数量限制，未覆盖所选资料的全部文字。', 'om-hint'));
      results.append(overview);
      const groupSections = new Map();
      if (globalThis.ZhijingOpinionFlow && data.groups.length) {
        const graph = make('div'); results.append(graph);
        state.flowCleanup = globalThis.ZhijingOpinionFlow.render(graph, data, {compact,
          onSelectGroup: (id, scroll = false) => {
            const section = groupSections.get(id); if (!section) return;
            section.open = true;
            if (scroll) section.scrollIntoView?.({block: 'nearest', behavior: 'smooth'});
          }});
      }
      for (const [index, group] of data.groups.entries()) {
        const section = make('details', undefined, 'om-group'); section.open = index === 0;
        groupSections.set(group.id, section);
        const summary = make('summary'); summary.append(make('span', String(index + 1).padStart(2, '0'), 'om-group-number'), make('strong', group.label), make('span', group.answer_count + ' 篇', 'om-tag'));
        section.append(summary, make('p', group.summary, 'om-group-summary'));
        for (const position of group.positions) section.append(authorCard(position));
        results.append(section);
      }
      if (data.unclassified?.length) {
        const section = make('details', undefined, 'om-unclassified');
        section.append(make('summary', '暂不归类 · ' + data.unclassified.length + ' 篇回答'));
        for (const source of data.unclassified) {
          const item = make('article', undefined, 'om-author-card');
          item.append(make('strong', source.author_name || '未署名'), make('p', source.title), make('p', source.reason, 'om-hint'));
          const link = sourceLink(source); if (link) item.append(link); section.append(item);
        }
        results.append(section);
      }
      results.append(make('p', '同一回答可包含多个观点；分组篇数不用于推断多数人立场。', 'om-hint'));
    }
    question.addEventListener('input', () => {
      if (state.busy) cancel();
      invalidateResult(); candidates.hidden = true; state.searchRows = [];
      const qid = questionId(question.value.trim()); search.hidden = Boolean(qid); collect.hidden = !qid;
      help.textContent = qid ? '仅读取和归类这个问题下的回答。登录后可复用登录状态，导入前可以预览。'
        : '搜索用于寻找候选回答；请核对与问题的相关性，再勾选归类。';
      if (qid) state.selected = new Set([...state.selected].filter(id => state.sources.some(source => source.id === id && answerQuestion(source) === qid)));
      renderSources(); message('');
    });
    filter.addEventListener('input', renderSources);
    form.addEventListener('submit', event => { event.preventDefault(); if (questionId(question.value.trim())) openCollector(); else searchAnswers(); });
    const imported = event => {
      if (event.detail?.origin === 'opinion-map' || !Array.isArray(event.detail?.saved)) return;
      if (state.busy) cancel(); acceptImported(event.detail.saved);
      if (state.active) message('新导入回答已选中，可按观点归类。');
    };
    document.addEventListener('zhijing:sources-imported', imported);
    const pagehide = () => cancel(); window.addEventListener('pagehide', pagehide);
    controls();
    return {
      setActive(active) {
        if (state.active === Boolean(active)) return;
        state.active = Boolean(active);
        if (!state.active) { if (state.busy) { cancel(); message('已停止等待。返回后可重新发起操作，已导入资料保留。'); } }
        else if (!state.loaded) loadSources(true);
      },
      destroy() { state.active = false; cancel(); invalidateResult(); document.removeEventListener('zhijing:sources-imported', imported); window.removeEventListener('pagehide', pagehide); root.replaceChildren(); },
    };
  }
  globalThis.ZhijingOpinionMap = {mount};
})();
