(() => {
  'use strict';

  const token = document.currentScript.dataset.configToken;
  const storageKey = 'zhijing.chat.source.' + token;
  const modes = {extractive: '原文摘录', ollama: '资料问答', openai: '资料问答'};

  function initialize() {
    const root = document.getElementById('chat-root');
    if (!root) return;
    const $ = id => document.getElementById(id);
    const state = {selected: null, sources: [], page: 0, more: false, busy: false,
      loadingSources: false, loadingSelection: false, revision: 0, selectionVersion: 0,
      messageCount: 0, mode: 'extractive'};
    const pageSize = 20;

    function element(tag, text, className) {
      const node = document.createElement(tag);
      if (text !== undefined) node.textContent = text;
      if (className) node.className = className;
      return node;
    }

    function status(id, message, kind = '') {
      $(id).textContent = message;
      $(id).className = 'status ' + kind;
    }

    function controls() {
      $('chat-send').disabled = state.busy || state.loadingSelection || !state.selected;
      $('chat-source-select').disabled = state.loadingSources || state.loadingSelection;
      $('chat-source-refresh').disabled = state.loadingSources || state.loadingSelection;
      $('chat-source-prev').disabled = state.loadingSources || state.loadingSelection || state.page === 0;
      $('chat-source-next').disabled = state.loadingSources || state.loadingSelection || !state.more;
      $('chat-launcher').disabled = $('chat-close').disabled = $('chat-pick-source').disabled = false;
    }

    async function request(path, body) {
      let response;
      try {
        response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
          headers: body === undefined ? {} : {'Content-Type': 'application/json', 'X-Zhijing-Token': token},
          body: body === undefined ? undefined : JSON.stringify(body)});
      } catch { throw new Error('无法连接本地服务，请确认服务仍在运行。'); }
      let data;
      try { data = await response.json(); } catch { throw new Error('服务响应无法解析，请检查服务日志。'); }
      if (!response.ok) throw new Error(data.error?.message || '请求失败，请检查资料和服务状态。');
      return data;
    }

    function rememberSource(source) {
      try {
        if (source) globalThis.sessionStorage.setItem(storageKey, source.id);
        else globalThis.sessionStorage.removeItem(storageKey);
      } catch { /* The widget also works when browser storage is unavailable. */ }
    }

    function sourceOption(source, current = false) {
      const option = element('option', (current ? '当前 · ' : '') + (source.content_extent === 'excerpt' ? '[摘要] ' : '') + source.title + ' · ' + source.author_name);
      option.value = source.id;
      return option;
    }

    function renderSources() {
      const select = $('chat-source-select');
      const placeholder = element('option', state.sources.length || state.selected ? '选择问答资料…' : '资料库为空，请先到工作台导入');
      placeholder.value = '';
      placeholder.disabled = true;
      select.replaceChildren(placeholder);
      if (state.selected && !state.sources.some(source => source.id === state.selected.id)) select.append(sourceOption(state.selected, true));
      for (const source of state.sources) select.append(sourceOption(source));
      select.value = state.selected?.id || '';
      $('chat-source-page').textContent = '第 ' + (state.page + 1) + ' 页';
      controls();
    }

    function updateContext() {
      const source = state.selected;
      $('chat-context').textContent = source
        ? (source.content_extent === 'excerpt' ? '仅依据摘要 · ' : '当前资料 · ') + source.title
        : '请先选择一篇资料，再开始问答。';
      $('chat-context').title = source
        ? source.title + (source.content_extent === 'excerpt' ? '：仅依据已导入摘要回答，不包含完整正文。' : '：依据已导入资料回答。')
        : '请先选择一篇资料，再开始问答。';
      $('chat-empty').hidden = state.messageCount > 0;
      $('chat-pick-source').hidden = Boolean(source);
      controls();
    }

    function chooseSource(source, notify = true) {
      if (!source || !['id', 'title', 'author_id', 'author_name', 'text'].every(key => typeof source[key] === 'string')) return;
      state.selectionVersion += 1;
      state.loadingSelection = false;
      if (source.id !== state.selected?.id) {
        state.revision += 1;
        const empty = $('chat-empty');
        $('chat-messages').replaceChildren(empty);
        state.messageCount = 0;
        $('chat-question').value = '';
        status('chat-status', '');
      }
      state.selected = source;
      rememberSource(source);
      $('chat-source-picker').open = false;
      renderSources();
      updateContext();
      if (notify) document.dispatchEvent(new CustomEvent('zhijing:chat-source-selected', {detail: source}));
    }

    async function loadSources(page = 0) {
      if (state.loadingSources) return;
      state.loadingSources = true;
      controls();
      status('chat-source-status', '正在读取资料…');
      try {
        const params = new URLSearchParams({offset: String(page * pageSize), limit: String(pageSize + 1)});
        const rows = await request('/api/v1/sources?' + params);
        if (!Array.isArray(rows)) throw new Error('资料列表响应无效，请重试。');
        state.page = page;
        state.more = rows.length > pageSize;
        state.sources = rows.slice(0, pageSize);
        renderSources();
        status('chat-source-status', rows.length ? '' : '本页暂无资料，可到工作台导入后刷新。');
      } catch (error) { status('chat-source-status', error.message, 'error'); }
      finally { state.loadingSources = false; controls(); }
    }

    async function restoreSource(id) {
      const version = state.selectionVersion;
      state.loadingSelection = true;
      controls();
      try {
        const source = await request('/api/v1/sources/' + encodeURIComponent(id));
        if (state.selectionVersion === version) chooseSource(source);
      } catch {
        if (state.selectionVersion === version) {
          rememberSource(null);
          status('chat-source-status', '上次选择的资料暂时无法读取，请重新选择。', 'error');
        }
      } finally {
        if (state.selectionVersion === version) state.loadingSelection = false;
        controls();
      }
    }

    async function refreshMode() {
      const health = await request('/health');
      state.mode = health.model_provider;
      $('chat-mode-notice').textContent = state.mode === 'extractive'
        ? '根据已导入内容摘录回答，请对照原文理解。'
        : '问题和相关资料将发送至分析服务，请核对回答中的引用。';
    }

    function openChat() {
      updateContext();
      $('chat-window').hidden = false;
      $('chat-launcher').setAttribute('aria-expanded', 'true');
      $('chat-question').focus({preventScroll: true});
      refreshMode().catch(error => { $('chat-mode-notice').textContent = error.message; });
    }

    function closeChat() {
      $('chat-window').hidden = true;
      $('chat-launcher').setAttribute('aria-expanded', 'false');
      $('chat-launcher').focus({preventScroll: true});
    }

    function message(role, text) {
      const article = element('article', undefined, 'chat-message ' + role);
      article.append(element('div', text, 'chat-message-body'));
      $('chat-messages').append(article);
      state.messageCount += 1;
      $('chat-empty').hidden = true;
      return article;
    }

    function scrollMessages() { $('chat-messages').scrollTop = $('chat-messages').scrollHeight; }

    function citations(parent, items) {
      if (!items?.length) { parent.append(element('p', '没有可展示的引用证据。', 'chat-message-meta')); return; }
      items.forEach((item, index) => {
        const card = element('div', undefined, 'citation');
        card.append(element('strong', '[' + (index + 1) + '] ' + item.title));
        const attribution = item.author_id.startsWith('zhihu-content:') ? '该条知乎资料' : '作者 ID：' + item.author_id;
        card.append(element('small', attribution + ' · 资料段落 ' + (item.chunk_index + 1)), element('blockquote', item.excerpt));
        if (item.url) {
          try {
            const url = new URL(item.url);
            if (['http:', 'https:'].includes(url.protocol)) {
              const link = element('a', '查看来源网页 ↗');
              link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
              card.append(link);
            }
          } catch { /* Invalid citation links remain absent. */ }
        }
        parent.append(card);
      });
    }

    async function submitChat() {
      if (state.busy || state.loadingSelection) return;
      if (!state.selected) { status('chat-status', '请先选择一篇资料，再开始问答。', 'error'); return; }
      const question = $('chat-question').value.trim();
      if (!question || question.length > 2000) { status('chat-status', '请填写 1 至 2,000 字符的问题。', 'error'); return; }
      const source = state.selected, revision = state.revision;
      const current = () => state.revision === revision && state.selected?.id === source.id;
      state.busy = true;
      controls();
      message('user', question);
      $('chat-question').value = '';
      status('chat-status', '正在根据资料回答…');
      scrollMessages();
      try {
        await refreshMode();
        if (!current()) return;
        const result = await request('/api/v1/author/ask', {author_id: source.author_id, primary_source_id: source.id, question});
        if (!current()) return;
        const answer = message('assistant', result.answer);
        answer.append(element('div', (modes[result.mode] || result.mode) + ' · ' + (result.identity_notice || '助手根据资料回答，不代表作者本人。'), 'chat-message-meta'));
        const references = element('details', undefined, 'chat-citations');
        references.append(element('summary', '查看引用'));
        citations(references, result.citations);
        if (result.citation_notice) references.append(element('p', result.citation_notice, 'chat-message-meta'));
        answer.append(references);
        status('chat-status', '回答完成。');
        scrollMessages();
      } catch (error) {
        if (current()) {
          if (!$('chat-question').value) $('chat-question').value = question;
          status('chat-status', error.message, 'error');
        }
      } finally { state.busy = false; controls(); }
    }

    $('chat-launcher').addEventListener('click', () => { if ($('chat-window').hidden) openChat(); else closeChat(); });
    $('chat-close').addEventListener('click', closeChat);
    $('chat-form').addEventListener('submit', event => { event.preventDefault(); return submitChat(); });
    $('chat-question').addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault(); return submitChat();
      }
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !$('chat-window').hidden) { event.preventDefault(); closeChat(); }
    });
    $('chat-pick-source').addEventListener('click', () => {
      $('chat-source-picker').open = true;
      $('chat-source-select').focus({preventScroll: true});
    });
    $('chat-source-select').addEventListener('change', () => {
      const selected = state.sources.find(source => source.id === $('chat-source-select').value);
      if (selected) chooseSource(selected);
    });
    $('chat-source-refresh').addEventListener('click', () => loadSources(0));
    $('chat-source-prev').addEventListener('click', () => loadSources(Math.max(0, state.page - 1)));
    $('chat-source-next').addEventListener('click', () => { if (state.more) return loadSources(state.page + 1); });
    document.addEventListener('zhijing:source-selected', event => chooseSource(event.detail, false));
    document.addEventListener('zhijing:sources-deleted', event => {
      const ids = event.detail?.source_ids || [];
      state.sources = state.sources.filter(source => !ids.includes(source.id));
      if (state.selected && ids.includes(state.selected.id)) {
        state.selected = null; state.revision++; state.selectionVersion++; state.loadingSelection = false;
        state.messageCount = 0; $('chat-messages').replaceChildren($('chat-empty'));
        $('chat-question').value = '';
        try { globalThis.sessionStorage.removeItem(storageKey); } catch { /* Optional. */ }
        status('chat-status', '所选资料已删除，请重新选择。');
      }
      renderSources(); updateContext();
    });

    updateContext();
    renderSources();
    loadSources();
    refreshMode().catch(error => { $('chat-mode-notice').textContent = error.message; });
    let previousId;
    try { previousId = globalThis.sessionStorage.getItem(storageKey); } catch { /* No restoration without storage. */ }
    if (previousId && previousId.length <= 200) restoreSource(previousId);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once: true});
  else initialize();
})();
