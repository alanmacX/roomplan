'use strict';
window.homeAPI = (() => {
  let dialog = null;

  const request = async (path, method = 'GET', data) => {
    const r = await fetch('/api' + path, {
      method,
      cache: 'no-store',
      ...(data ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) } : {})
    });
    const payload = await r.json();
    if (!r.ok) {
      const e = new Error(payload.error || '请求未能完成。');
      e.status = r.status;
      throw e;
    }
    return payload;
  };

  function signIn(allowClose = false) {
    if (dialog) return dialog;
    dialog = new Promise(resolve => {
      const d = document.createElement('dialog');
      d.className = 'demo-login glass modal-sheet';
      d.innerHTML = `
        <form class="modal-body">
          <div class="modal-head">
            <h2>选择成员身份</h2>
            ${allowClose ? '<button type="button" class="close-circle" data-cancel aria-label="关闭">✕</button>' : ''}
          </div>
          <div class="seg-bar" id="pinRoleBar">
            <button type="button" data-pin="2468" aria-pressed="true">管理员</button>
            <button type="button" data-pin="1357" aria-pressed="false">长辈</button>
            <button type="button" data-pin="0000" aria-pressed="false">访客</button>
          </div>
          <label class="field-box">
            <span>口令</span>
            <input name="pin" type="password" value="2468" required autocomplete="current-password" placeholder="输入口令">
          </label>
          <p class="err-text" role="status"></p>
          <div class="modal-foot">
            <button type="submit" class="btn-primary" style="width:100%">进入</button>
          </div>
        </form>`;
      document.body.append(d);
      if (!allowClose) d.addEventListener('cancel', e => e.preventDefault());
      else d.addEventListener('close', () => { d.remove(); dialog = null; resolve(false); });

      const form = d.querySelector('form');
      const pinInput = form.elements.pin;
      d.querySelectorAll('[data-pin]').forEach(btn => {
        btn.onclick = () => {
          pinInput.value = btn.dataset.pin;
          d.querySelectorAll('[data-pin]').forEach(x => x.setAttribute('aria-pressed', String(x === btn)));
        };
      });
      const cancelBtn = d.querySelector('[data-cancel]');
      if (cancelBtn) cancelBtn.onclick = () => { d.close(); };

      form.onsubmit = async e => {
        e.preventDefault();
        const submitBtn = form.querySelector('[type=submit]');
        submitBtn.disabled = true;
        try {
          const res = await request('/login', 'POST', { pin: pinInput.value.trim() });
          d.close();
          d.remove();
          dialog = null;
          resolve(res);
        } catch (err) {
          d.querySelector('.err-text').textContent = err.message;
          submitBtn.disabled = false;
          pinInput.select();
        }
      };
      d.showModal();
    });
    return dialog;
  }

  const ready = location.protocol === 'file:' ? Promise.resolve(false) : (async () => {
    let status;
    try { status = await request('/status'); } catch { return false; }
    if (status.service !== 'smart-home-demo') return false;
    return status.signedIn ? status : signIn(false);
  })();

  async function api(path, method = 'GET', data) {
    try {
      return await request(path, method, data);
    } catch (err) {
      if (err.status !== 401) throw err;
      await signIn(false);
      return request(path, method, data);
    }
  }

  const resource = (key, suffix = '') => '/plans/' + key + suffix;

  return {
    ready,
    switchRole: () => signIn(true),
    status: () => request('/status'),
    types: () => api('/types'),
    registerType: body => api('/types', 'POST', body),
    get: key => api(resource(key)),
    save: (key, plan, rev, replace = false, force = false) => api(resource(key), 'PUT', { plan, rev, replace, force }),
    importBatch: (key, format, content) => api(resource(key, '/import'), 'POST', { format, content }),
    exportCsvUrl: key => `/api/plans/${encodeURIComponent(key)}/export?format=csv`,
    scene: (key, mode) => api(resource(key, '/scene'), 'POST', { mode }),
    saveScene: (key, body) => api(resource(key, '/scenes'), 'POST', body),
    environment: (key, data) => api(resource(key, '/environment'), 'POST', data),
    command: (key, id, capability, value, outcome = 'ok') =>
      api(resource(key, '/devices/' + encodeURIComponent(id) + '/command'), 'POST', { capability, value, outcome }),
    history: (key, id) => api(resource(key, '/devices/' + encodeURIComponent(id) + '/history')),
    mount: (key, u, v) => api(resource(key, '/mount'), 'POST', { u, v }),
    remove: (key, id, force = false) =>
      api(resource(key, '/devices/' + encodeURIComponent(id) + (force ? '?force=1' : '')), 'DELETE'),
    butlerChat: (key, body) => api(resource(key, '/butler/chat'), 'POST', body),
    butlerConfirm: (key, confirm_token) => api(resource(key, '/butler/confirm'), 'POST', { confirm_token }),
  };
})();
