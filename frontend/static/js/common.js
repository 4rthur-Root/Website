(() => {
  function updateThemeButton() {
    const button = document.querySelector('.theme-toggle');
    if (!button) return;
    const theme = document.documentElement.getAttribute('data-theme');
    button.textContent = theme === 'dark' ? '🌙' : '☀️';
  }

  const savedTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  updateThemeButton();

  window.toggleTheme = function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeButton();
  };

  window.openModal = function openModal(id) {
    document.getElementById(id)?.classList.add('open');
  };

  window.closeModal = function closeModal(id) {
    document.getElementById(id)?.classList.remove('open');
  };

  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', event => {
      if (event.target === overlay) overlay.classList.remove('open');
    });
  });
})();
