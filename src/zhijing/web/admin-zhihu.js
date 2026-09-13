(() => {
  'use strict';
  const token = document.currentScript.dataset.configToken;
  const $ = id => document.getElementById(id);
  let busy = true, configured = false;

  function controls() {
    $('save-zhihu-secret').disabled = busy;
    $('clear-zhihu-secret').disabled = busy || !configured;
    $('zhihu-secret').disabled = busy;
  }

  function status(message, error = false) {
    $('zhihu-config-status').textContent = message;
    $('zhihu-config-status').className = 'status ' + (error ? 'error' : 'success');
  }

  function showConfiguration(result) {
    configured = result.configured === true;
    $('zhihu-config-state').textContent = configured
      ? '已保存知乎搜索凭据；实际搜索时验证其有效性。'
      : '尚未配置知乎搜索凭据。用户仍可导入已有资料并使用阅读与知识功能。';
    controls();
  }

  async function request(path, body) {
    let response;
    try {
      response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
        headers: body === undefined ? {'X-Zhijing-Token': token} : {'Content-Type': 'application/json', 'X-Zhijing-Token': token},
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch { throw new Error('无法连接本地服务，请确认服务仍在运行。'); }
    let result;
    try { result = await response.json(); } catch { throw new Error('本地服务响应无法解析，请重试。'); }
    if (!response.ok) {
      if (response.status === 403) throw new Error('当前管理页面会话已失效，请刷新后重试。');
      throw new Error('操作未完成，请检查凭据格式或本地服务状态后重试。');
    }
    return result;
  }

  async function update(secret) {
    if (busy) return;
    busy = true;
    controls();
    status(secret ? '正在保存连接凭据…' : '正在清除连接凭据…');
    try {
      const result = await request('/api/v1/zhihu/config', {access_secret: secret});
      showConfiguration(result);
      if (configured !== Boolean(secret)) throw new Error('连接状态未按预期更新，请刷新后检查。');
      $('zhihu-secret').value = '';
      status(secret ? '已保存到当前服务会话。实际搜索时验证凭据有效性。' : '会话凭据已清除，已导入的资料仍可使用。');
    } catch (error) { status(error.message, true); }
    finally { busy = false; controls(); }
  }

  $('zhihu-config-form').addEventListener('submit', event => {
    event.preventDefault();
    const secret = $('zhihu-secret').value.trim();
    if (!secret) { status('请填写知乎 Access Secret。', true); return; }
    return update(secret);
  });
  $('clear-zhihu-secret').addEventListener('click', () => update(''));
  controls();
  request('/api/v1/zhihu/status').then(showConfiguration).catch(error => status(error.message, true))
    .finally(() => { busy = false; controls(); });
})();
