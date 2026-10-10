(() => {
  window.togglePwd = function togglePwd() {
    const input = document.getElementById('pwd-input');
    if (input) input.type = input.type === 'password' ? 'text' : 'password';
  };

  window.toggleDemo = function toggleDemo() {
    const list = document.getElementById('demo-list');
    const arrow = document.getElementById('demo-arrow');
    if (!list || !arrow) return;
    const visible = list.style.display !== 'none';
    list.style.display = visible ? 'none' : 'grid';
    arrow.textContent = visible ? '▶' : '▼';
  };

  window.fillLogin = function fillLogin(username) {
    const usernameInput = document.querySelector('[name=username]');
    const passwordInput = document.querySelector('[name=password]');
    if (usernameInput) usernameInput.value = username;
    passwordInput?.focus();
  };
})();
