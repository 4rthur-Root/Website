(() => {
  const config = document.getElementById('admin-config');
  const TITLES = {
    overview: '📊 Overview', shares: '📁 Shares', fail2ban: '🛡️ Fail2ban',
    logs: '📋 Logs', users: '👥 Users', audit: '🔍 Audit log',
    backup: '💾 Backups', security: '🔐 Security'
  };

  window.showTab = function showTab(id, updateHash = true) {
    document.querySelectorAll('.tab-section').forEach(section => section.classList.remove('active'));
    document.querySelectorAll('.admin-nav-item').forEach(button => button.classList.remove('active'));
    document.getElementById('tab-' + id)?.classList.add('active');
    document.getElementById('nav-' + id)?.classList.add('active');
    const title = document.getElementById('tab-title');
    if (title) title.textContent = TITLES[id] || id;
    if (updateHash) history.replaceState(null, '', '#' + id);
    if (id === 'audit') window.loadAudit();
  };

  // Restore the last opened tab after a reload (the refresh button and the
  // fail2ban auto-reload both use location.reload(), which keeps the hash).
  const initialTab = (location.hash || '').replace('#', '');
  if (initialTab && document.getElementById('tab-' + initialTab)) {
    showTab(initialTab, false);
  }

  window.filterLogs = function filterLogs() {
    const input = document.getElementById('log-filter');
    const value = input ? input.value.toLowerCase() : '';
    document.querySelectorAll('.auth-entry').forEach(row => {
      row.style.display = !value || row.dataset.line.includes(value) ? '' : 'none';
    });
  };

  window.showUserLogs = function showUserLogs(username) {
    document.getElementById('logs-modal-title').textContent = '📋 Logs - ' + username;
    document.getElementById('logs-modal-content').innerHTML = '<div style="padding:20px;color:var(--text-muted)">Loading...</div>';
    openModal('user-logs-modal');
    fetch('/admin/users/logs/' + encodeURIComponent(username)).then(response => response.json()).then(data => {
      if (data.ok) {
        const html = data.logs.split('\n').filter(line => line.trim()).map(line =>
          `<div class="log-line ${line.includes('NT_STATUS') && !line.includes('OK') ? 'log-fail' : ''}">${line}</div>`
        ).join('') || '<div style="padding:16px;color:var(--text-muted)">No logs.</div>';
        document.getElementById('logs-modal-content').innerHTML = html;
      } else {
        document.getElementById('logs-modal-content').innerHTML = `<div class="log-line log-fail" style="padding:16px">Error: ${data.error}</div>`;
      }
    });
  };

  window.openChangePwd = function openChangePwd(username) {
    document.getElementById('change-pwd-user').value = username;
    document.getElementById('change-pwd-sub').textContent = 'User: ' + username;
    openModal('change-pwd-modal');
  };

  window.openDelete = function openDelete(username) {
    document.getElementById('delete-name-label').textContent = username;
    document.getElementById('delete-user-input').value = username;
    openModal('delete-modal');
  };

  window.loadAudit = function loadAudit() {
    fetch(config.dataset.auditUrl).then(response => response.json()).then(data => {
      if (!data.ok || !data.entries.length) return;
      document.getElementById('audit-body').innerHTML = data.entries.map(line => {
        const parts = line.split(' | ');
        const action = (parts[2] || '').trim();
        const color = action.includes('DELETE') ? 'var(--accent-red)'
          : action.includes('ADD') ? 'var(--accent-green)'
          : action.includes('BAN') ? 'var(--accent-orange)'
          : action.includes('PWD') || action.includes('PASSWORD') ? 'var(--accent-orange)'
          : action.includes('LOGIN') ? 'var(--accent-blue)'
          : 'var(--text-secondary)';
        return `<div class="audit-row">
          <div style="color:var(--text-muted)">${parts[0] || ''}</div>
          <div style="color:var(--accent-blue);font-weight:600">${(parts[1] || '').trim()}</div>
          <div style="font-weight:700;color:${color}">${action}</div>
          <div style="color:var(--text-primary)">${(parts[3] || '').trim()}</div>
          <div style="color:var(--text-muted)">${(parts[4] || '').trim()}</div>
        </div>`;
      }).join('');
    });
  };

  window.loadBackup = function loadBackup() {
    fetch(config.dataset.backupUrl).then(response => response.json()).then(data => {
      const element = document.getElementById('backup-log');
      element.innerHTML = data.ok
        ? (data.log.split('\n').filter(line => line.trim()).map(line => `<div class="log-line">${line}</div>`).join('') || '<div style="padding:16px;color:var(--text-muted)">Log is empty.</div>')
        : `<div class="log-line log-fail">Error: ${data.error}</div>`;
    });
  };

  setInterval(() => {
    fetch(config.dataset.refreshUrl).then(response => response.json()).then(data => {
      if (!data.ok || !data.fail2ban) return;
      const count = data.fail2ban.current_banned ? data.fail2ban.current_banned.length : 0;
      const badge = document.querySelector('.f2b-badge-blink');
      if (count > 0 && !badge) location.reload();
    }).catch(() => {});
  }, 30000);
})();
