/* ProfessorIA™ — Theme toggle (light / dark / system) */
(function () {
  var KEY = 'pia-theme';
  var current = localStorage.getItem(KEY) || 'light';

  function actual(t) {
    return t === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : t;
  }

  function apply(t) {
    document.documentElement.setAttribute('data-theme', actual(t));
    document.documentElement.style.colorScheme = actual(t);
  }

  /* apply immediately to avoid flash */
  apply(current);

  document.addEventListener('DOMContentLoaded', function () {
    var nav = document.querySelector('nav');
    if (!nav) return;

    var wrap = document.createElement('div');
    wrap.id = 'theme-toggle';
    wrap.title = 'Tema';
    wrap.innerHTML =
      '<button data-v="light"  title="Claro">☀</button>' +
      '<button data-v="system" title="Sistema">⬡</button>' +
      '<button data-v="dark"   title="Escuro">☾</button>';

    function sync() {
      wrap.querySelectorAll('button').forEach(function (b) {
        b.classList.toggle('on', b.dataset.v === current);
      });
    }

    wrap.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-v]');
      if (!btn) return;
      current = btn.dataset.v;
      localStorage.setItem(KEY, current);
      apply(current);
      sync();
      /* update Three.js materials if scene is loaded */
      if (window.__sceneUpdate) window.__sceneUpdate(actual(current));
    });

    sync();
    nav.appendChild(wrap);
  });

  /* watch OS preference */
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
    if (current === 'system') apply('system');
  });
})();
