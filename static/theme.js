/* ProfessorIA™ — Theme toggle */
(function () {
  var KEY = 'pia-theme';
  var current = localStorage.getItem(KEY) || 'light';

  /* Migração: usuários que tinham 'dark' salvo passam para 'system',
     que respeita a preferência do SO sem o botão lua removido. */
  if (current === 'dark') {
    current = 'system';
    localStorage.setItem(KEY, 'system');
  }

  function actual(t) {
    return t === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : t;
  }

  function apply(t) {
    var a = actual(t);
    document.documentElement.setAttribute('data-theme', a);
    /* "only light" blocks Brave/Chrome forced-dark override */
    document.documentElement.style.colorScheme = a === 'dark' ? 'dark' : 'only light';
  }

  apply(current);

  document.addEventListener('DOMContentLoaded', function () {
    var nav = document.querySelector('nav');
    if (!nav) return;

    var wrap = document.createElement('div');
    wrap.id = 'theme-toggle';
    wrap.innerHTML =
      '<button data-v="light"  title="Claro">&#9728;</button>' +
      '<button data-v="system" title="Sistema">&#11041;</button>';

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
      if (window.__sceneUpdate) window.__sceneUpdate(actual(current));
    });

    sync();
    nav.appendChild(wrap);
  });

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
    if (current === 'system') apply('system');
  });
})();
