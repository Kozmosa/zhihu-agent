(() => {
  'use strict';
  const token = document.currentScript.dataset.configToken;
  const endpoint = '/api/v1/zhihu/questions/jobs';
  const state = {job: null, starting: false, saving: false, cancelling: false, timer: null,
    polling: false, pollController: null, pollRevision: 0, revision: 0, rows: [], signature: '', opener: null};
  const make = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const id = (element, value) => { element.id = value; return element; };
  const button = (value, text, className) => {
    const element = id(make('button', text, className), value); element.type = 'button'; return element;
  };
  const dialog = id(make('dialog', undefined, 'qi-dialog'), 'question-import-dialog');
  dialog.setAttribute('aria-labelledby', 'question-import-title');
  const header = make('header', undefined, 'qi-header');
  const heading = make('div');
  heading.append(make('span', '从问题出发', 'qi-eyebrow'), id(make('h2', '导入知乎问题'), 'question-import-title'));
  const close = button('question-import-close', '关闭', 'qi-close');
  header.append(heading, close);
  const body = make('div', undefined, 'qi-body');
  body.append(make('p', '打开独立知乎窗口，读取页面已显示的回答正文。先预览，再保存到本机；不保证覆盖问题全部回答或每条回答的完整正文。', 'qi-intro'));
  const form = id(make('form', undefined, 'qi-form'), 'question-import-form');
  const modeLabel = make('label', '读取范围'); modeLabel.htmlFor = 'question-import-mode';
  const mode = id(make('select'), 'question-import-mode');
  for (const [value, label] of [['question', '按问题：读取多位答主'], ['author', '按作者：读取多个问题的回答']]) {
    const option = make('option', label); option.value = value; mode.append(option);
  }
  mode.value = 'question'; form.append(modeLabel, mode);
  const urlLabel = make('label', '知乎问题链接'); urlLabel.htmlFor = 'question-import-url';
  const url = id(make('input'), 'question-import-url');
  url.type = 'url'; url.required = true; url.maxLength = 2048; url.placeholder = 'https://www.zhihu.com/question/…';
  const numberLabel = make('label', '最多读取'); numberLabel.htmlFor = 'question-import-count';
  const count = id(make('input'), 'question-import-count'); count.type = 'number'; count.min = '1'; count.max = '20'; count.value = '5'; count.required = true;
  const actions = make('div', undefined, 'qi-start-row');
  const numberField = make('div', undefined, 'qi-count'); numberField.append(numberLabel, count, make('span', '篇回答'));
  const start = button('question-import-start', '打开知乎并读取', 'qi-primary'); start.type = 'submit';
  actions.append(numberField, start); form.append(urlLabel, url, actions); body.append(form);
  const reading = id(make('p', '在打开的知乎窗口登录或完成验证；回到问题后继续读取。登录状态会供下次读取复用。', 'qi-guidance'), 'question-import-guidance');
  body.append(reading);
  const progress = id(make('p', '', 'qi-status'), 'question-import-status'); progress.setAttribute('role', 'status'); progress.setAttribute('aria-live', 'polite');
  const jobActions = make('div', undefined, 'qi-job-actions');
  const refresh = button('question-import-refresh', '刷新读取状态');
  const cancel = button('question-import-cancel', '停止读取');
  jobActions.append(refresh, cancel); body.append(progress, jobActions);
  const previewHeading = make('div', undefined, 'qi-preview-heading');
  const total = id(make('h3', '回答预览'), 'question-import-total');
  const allLabel = make('label', undefined, 'qi-select-all');
  const all = id(make('input'), 'question-import-all'); all.type = 'checkbox'; all.checked = true;
  allLabel.append(all, make('span', '全选')); previewHeading.append(total, allLabel); body.append(previewHeading);
  const results = id(make('div', undefined, 'qi-results'), 'question-import-results'); body.append(results);
  const footer = make('footer', undefined, 'qi-footer');
  const scope = make('p', '仅含网页已显示正文，可能不完整。', 'qi-scope');
  const save = button('question-import-save', '导入选中', 'qi-primary');
  footer.append(scope, save); dialog.append(header, body, footer); document.body.append(dialog);

  function message(text, error = false) {
    progress.textContent = text; progress.className = 'qi-status' + (error ? ' qi-error' : '');
  }
  function active() { return Boolean(state.job && !state.job.terminal); }
  function selected() { return state.rows.filter(row => row.checkbox.checked && !row.imported); }
  function controls() {
    const locked = state.starting || state.saving || state.cancelling;
    start.disabled = locked || active(); url.disabled = count.disabled = mode.disabled = locked || active();
    cancel.hidden = !active(); cancel.disabled = locked || !active();
    refresh.hidden = !state.job; refresh.disabled = locked || state.polling || !state.job;
    const remaining = state.rows.filter(row => !row.imported);
    for (const row of state.rows) row.checkbox.disabled = state.saving || row.imported;
    all.disabled = state.saving || !remaining.length;
    all.checked = remaining.length > 0 && remaining.every(row => row.checkbox.checked);
    all.indeterminate = remaining.some(row => row.checkbox.checked) && !all.checked;
    const quantity = selected().length;
    save.disabled = locked || active() || !quantity;
    save.textContent = quantity ? '导入选中（' + quantity + '）' : '导入选中';
  }
  async function request(path, data, signal) {
    let response;
    try {
      response = await fetch(path, {method: data === undefined ? 'GET' : 'POST', cache: 'no-store', signal,
        headers: data === undefined ? {'X-Zhijing-Token': token} : {'Content-Type': 'application/json', 'X-Zhijing-Token': token},
        body: data === undefined ? undefined : JSON.stringify(data)});
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new Error('暂时无法连接本地服务，请稍后重试。');
    }
    let result;
    try { result = await response.json(); } catch { throw new Error('读取状态无法识别，请刷新后重试。'); }
    if (!response.ok) {
      const messages = {invalid_config_token: '本次连接已失效，请重新打开知境。', question_reader_unavailable: '知乎读取窗口暂不可用，请使用 Windows 桌面版。'};
      throw new Error(messages[result?.error?.code] || (response.status === 422 ? '请检查知乎问题链接及数量（1～20 篇）。'
        : response.status === 409 ? '已有读取任务正在进行，请完成或停止后再试。'
        : response.status === 404 ? '这次读取任务已失效，请重新开始。' : '本次读取未能完成，请稍后重试。'));
    }
    return result;
  }
  function sourceLink(source) {
    try {
      const target = new URL(source.url);
      if (target.protocol !== 'https:' || !['zhihu.com', 'www.zhihu.com', 'zhuanlan.zhihu.com'].includes(target.hostname)
          || target.username || target.password || (target.port && target.port !== '443')) return null;
      const link = make('a', '在知乎查看 ↗'); link.href = target.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
    } catch { return null; }
  }
  function showItems(items) {
    const drafts = Array.isArray(items) ? items.slice(0, 20).filter(item => item && typeof item.text === 'string' && item.text.trim()) : [];
    const signature = JSON.stringify(drafts);
    if (signature === state.signature) return;
    state.signature = signature;
    const previous = new Map(state.rows.map(row => [row.key, row]));
    state.rows = [];
    results.replaceChildren();
    drafts.forEach((source, index) => {
      const key = String(source.url || '') + '\n' + String(source.author_id || '');
      const before = previous.get(key);
      const article = make('article', undefined, 'qi-answer');
      const label = make('label', undefined, 'qi-answer-title');
      const checkbox = make('input'); checkbox.type = 'checkbox'; checkbox.checked = before ? before.checkbox.checked : true;
      const title = make('span', (index + 1) + '. ' + String(source.title || '知乎回答'));
      label.append(checkbox, title); article.append(label);
      const meta = make('div', undefined, 'qi-answer-meta');
      meta.append(make('span', String(source.author_name || '未署名')), make('span', '网页已显示正文', 'qi-tag'), make('span', source.text.length + ' 字符'));
      article.append(meta);
      const details = make('details'); details.open = Boolean(before?.details.open);
      details.append(make('summary', '展开回答正文'), make('div', source.text, 'qi-text')); article.append(details);
      const link = sourceLink(source); if (link) article.append(link);
      const row = {source, key, checkbox, details, article, imported: Boolean(before?.imported)};
      if (row.imported) article.append(make('span', '已导入', 'qi-imported'));
      checkbox.addEventListener('change', controls); state.rows.push(row); results.append(article);
    });
  }
  function accept(job) {
    if (!job || typeof job.id !== 'string' || !['running', 'needs_login', 'ready', 'failed', 'cancelled'].includes(job.status)) throw new Error('读取状态无法识别，请刷新后重试。');
    state.job = {...job, terminal: job.terminal === true || ['ready', 'failed', 'cancelled'].includes(job.status)};
    showItems(job.items);
    total.textContent = state.rows.length ? '回答预览 · ' + state.rows.length + ' 篇' : '回答预览';
    const labels = {running: '正在读取知乎回答…', needs_login: '请在知乎窗口登录或完成验证，回到读取页面后继续。',
      ready: '读取结束，请勾选需要保存的回答。', failed: '读取未能完成。已读取到的回答仍可预览并导入。', cancelled: '读取已停止。已读取到的回答仍可预览并导入。'};
    message(labels[job.status] + (typeof job.message === 'string' && job.message ? '\n' + job.message.slice(0, 1000) : '') +
      (state.rows.length ? '\n已读取 ' + state.rows.length + ' 篇，目标最多 ' + job.requested_count + ' 篇。' : ''), job.status === 'failed');
    if (state.job.terminal && !state.rows.length && !results.children.length) results.append(make('p', '本次没有可导入的回答正文。可以回到知乎问题页确认内容，再重新开始。', 'qi-empty'));
    controls();
  }
  function clearPolling() {
    if (state.timer !== null) clearTimeout(state.timer);
    state.timer = null; state.pollRevision++;
    state.pollController?.abort(); state.pollController = null; state.polling = false;
  }
  function schedule(delay = 1500) {
    if (!dialog.open || !active() || state.starting || state.cancelling || state.polling || state.timer !== null) return;
    state.timer = setTimeout(() => { state.timer = null; poll(); }, delay);
  }
  async function poll() {
    if (!dialog.open || !state.job || state.polling || state.starting || state.cancelling) return;
    const revision = state.revision, generation = ++state.pollRevision, jobId = state.job.id;
    const controller = new AbortController(); state.pollController = controller; state.polling = true; controls();
    let again = false;
    try {
      const result = await request(endpoint + '/' + encodeURIComponent(jobId), undefined, controller.signal);
      if (revision !== state.revision || generation !== state.pollRevision || state.job?.id !== jobId) return;
      accept(result); again = true;
    } catch (error) {
      if (error.name !== 'AbortError' && revision === state.revision && generation === state.pollRevision) message(error.message + ' 点击“刷新读取状态”重试。', true);
    } finally {
      if (generation === state.pollRevision) { state.polling = false; state.pollController = null; controls(); if (again) schedule(); }
    }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (state.starting || state.saving || state.cancelling || active()) return;
    let target;
    const quantity = Number(count.value);
    try {
      target = new URL(url.value.trim());
      if (target.protocol !== 'https:' || !['www.zhihu.com', 'zhihu.com'].includes(target.hostname) || target.username || target.password
          || (target.port && target.port !== '443') || !(mode.value === 'author'
            ? /^\/(people|org)\/[A-Za-z0-9][A-Za-z0-9_-]{0,127}(?:\/answers)?\/?$/
            : /^\/question\/\d+\/?$/).test(target.pathname)) throw new Error();
      if (!Number.isInteger(quantity) || quantity < 1 || quantity > 20) throw new Error();
    } catch { message(mode.value === 'author' ? '请填写 https://www.zhihu.com/people/作者标识 形式的主页链接，数量为 1～20 篇。' : '请填写 https://www.zhihu.com/question/数字 形式的问题链接，数量为 1～20 篇。', true); return; }
    clearPolling(); state.revision++; const revision = state.revision;
    state.starting = true; state.job = null; state.rows = []; state.signature = ''; results.replaceChildren(); total.textContent = '回答预览';
    message('正在打开独立知乎读取窗口…'); controls();
    try {
      const result = await request(endpoint, {url: target.href, count: quantity});
      if (revision !== state.revision) return; accept(result);
    } catch (error) { if (revision === state.revision) message(error.message, true); }
    finally { if (revision === state.revision) { state.starting = false; controls(); schedule(); } }
  });
  cancel.addEventListener('click', async () => {
    if (!active() || state.starting || state.cancelling || state.saving) return;
    clearPolling(); const revision = ++state.revision, jobId = state.job.id;
    state.cancelling = true; message('正在停止读取，已保存的资料不受影响…'); controls();
    try { const result = await request(endpoint + '/' + encodeURIComponent(jobId) + '/cancel', {}); if (revision === state.revision) accept(result); }
    catch (error) { if (revision === state.revision) message(error.message + ' 可再次点击“停止读取”。', true); }
    finally { if (revision === state.revision) { state.cancelling = false; controls(); schedule(); } }
  });
  save.addEventListener('click', async () => {
    if (state.saving || state.starting || state.cancelling || active()) return;
    const rows = selected(); if (!rows.length) return;
    state.saving = true; message('正在保存选中的 ' + rows.length + ' 篇回答…'); controls();
    try {
      const saved = await request('/api/v1/sources/import', {items: rows.map(row => row.source)});
      if (!Array.isArray(saved) || !saved.length || !saved.every(item => item && typeof item.id === 'string')) throw new Error('保存结果无法确认，请刷新资料库查看。');
      rows.forEach(row => { row.imported = true; row.checkbox.checked = false; row.article.append(make('span', '已导入', 'qi-imported')); });
      message('已保存 ' + saved.length + ' 篇回答。关闭此面板后可阅读第一篇。');
      document.dispatchEvent(new CustomEvent('zhijing:sources-imported', {detail: {saved}}));
    } catch (error) { message(error.message, true); }
    finally { state.saving = false; controls(); }
  });
  all.addEventListener('change', () => { for (const row of state.rows) if (!row.imported) row.checkbox.checked = all.checked; controls(); });
  function modeLabels() {
    const author = mode.value === 'author';
    document.getElementById('question-import-title').textContent = author ? '读作者 · 导入多篇回答' : '导入知乎问题';
    urlLabel.textContent = author ? '知乎作者主页链接' : '知乎问题链接';
    url.placeholder = author ? 'https://www.zhihu.com/people/…' : 'https://www.zhihu.com/question/…';
    reading.textContent = '在打开的知乎窗口登录或完成验证；回到' + (author ? '作者回答列表' : '问题页') + '后继续读取。只读取页面实际加载的回答，不保证全部历史回答覆盖。';
  }
  mode.addEventListener('change', () => { url.value = ''; modeLabels(); });
  refresh.addEventListener('click', () => { if (state.timer !== null) clearTimeout(state.timer); state.timer = null; return poll(); });
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { clearPolling(); controls(); state.opener?.focus(); });
  window.addEventListener('pagehide', clearPolling);
  window.addEventListener('pageshow', () => schedule(0));
  document.querySelectorAll('[data-open-question-import]').forEach(opener => opener.addEventListener('click', () => {
    state.opener = opener;
    if (!active() && !state.starting && !state.saving && !state.cancelling) {
      const requested = opener.dataset?.readerMode || 'question';
      if (mode.value !== requested) url.value = '';
      mode.value = requested; modeLabels();
    }
    if (!dialog.open) dialog.showModal();
    controls(); if (active()) schedule(0); else url.focus();
  }));
  controls();
})();
