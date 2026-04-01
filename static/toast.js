/* ProfessorIA™ — Toast Notification System
   Uso:
     showToast('Mensagem', 'ok')    → verde
     showToast('Mensagem', 'erro')  → vermelho
     showToast('Mensagem', 'info')  → azul
   Flash messages do Flask são detectadas automaticamente via
   <template data-toast data-cat="ok" data-msg="Texto"> no HTML.
*/
(function () {
  'use strict';

  var DURATION = 4200; // ms

  function getContainer() {
    var c = document.getElementById('pia-toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'pia-toast-container';
      document.body.appendChild(c);
    }
    return c;
  }

  function iconSVG(cat) {
    if (cat === 'ok' || cat === 'success') {
      return '<svg class="pia-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    }
    if (cat === 'erro' || cat === 'error') {
      return '<svg class="pia-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
    }
    return '<svg class="pia-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
  }

  function dismiss(toast) {
    toast.classList.remove('pia-show');
    toast.classList.add('pia-hide');
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 320);
  }

  window.showToast = function (msg, cat) {
    cat = cat || 'info';
    var container = getContainer();
    var toast = document.createElement('div');
    toast.className = 'pia-toast pia-toast-' + cat;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'polite');
    toast.innerHTML =
      iconSVG(cat) +
      '<span style="flex:1">' + msg + '</span>' +
      '<div class="pia-toast-bar" style="animation-duration:' + DURATION + 'ms"></div>';

    toast.addEventListener('click', function () { dismiss(toast); });

    container.appendChild(toast);

    // Trigger animation on next frame
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        toast.classList.add('pia-show');
      });
    });

    // Auto-dismiss
    setTimeout(function () { dismiss(toast); }, DURATION);
  };

  // ── Coleta flash messages renderizadas como <template data-toast> ──
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('template[data-toast]').forEach(function (t) {
      var cat = t.getAttribute('data-cat') || 'info';
      var msg = t.getAttribute('data-msg') || '';
      if (msg) window.showToast(msg, cat);
    });
  });
})();
