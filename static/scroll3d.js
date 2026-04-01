(function () {
  'use strict';

  const CONTAINER_ID = 'particle-canvas-container';
  const NODE_COUNT   = 100;
  const MAX_DIST     = 130;
  const NODE_RADIUS  = 2.2;
  const SPEED        = 0.35;
  const MOUSE_RADIUS = 160;
  const MOUSE_FORCE  = 0.018;
  const COLOR_NODE   = '96,165,250';  // blue-400
  const COLOR_LINE   = '30,64,175';   // blue-800

  let canvas, ctx, W, H, nodes = [], mouse = { x: -9999, y: -9999 };

  function Node() {
    this.x  = Math.random() * W;
    this.y  = Math.random() * H;
    const a = Math.random() * Math.PI * 2;
    this.vx = Math.cos(a) * SPEED * (0.4 + Math.random() * 0.6);
    this.vy = Math.sin(a) * SPEED * (0.4 + Math.random() * 0.6);
    this.r  = NODE_RADIUS * (0.7 + Math.random() * 0.6);
  }

  function init(container) {
    canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;';
    container.style.position = 'relative';
    container.appendChild(canvas);
    ctx = canvas.getContext('2d');

    resize(container);

    const ro = new ResizeObserver(function () { resize(container); });
    ro.observe(container);

    container.addEventListener('mousemove', function (e) {
      const rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
    });
    container.addEventListener('mouseleave', function () {
      mouse.x = -9999;
      mouse.y = -9999;
    });

    loop();
  }

  function resize(container) {
    W = container.clientWidth  || 400;
    H = container.clientHeight || 400;
    canvas.width  = W;
    canvas.height = H;
    nodes = Array.from({ length: NODE_COUNT }, function () { return new Node(); });
  }

  function loop() {
    requestAnimationFrame(loop);
    ctx.clearRect(0, 0, W, H);

    // Update positions
    for (var i = 0; i < nodes.length; i++) {
      var n  = nodes[i];
      var dx = mouse.x - n.x;
      var dy = mouse.y - n.y;
      var d  = Math.sqrt(dx * dx + dy * dy);

      if (d < MOUSE_RADIUS && d > 0) {
        var force = (1 - d / MOUSE_RADIUS) * MOUSE_FORCE;
        n.vx += (dx / d) * force;
        n.vy += (dy / d) * force;
      }

      var spd = Math.sqrt(n.vx * n.vx + n.vy * n.vy);
      if (spd > SPEED * 2) {
        n.vx = (n.vx / spd) * SPEED * 2;
        n.vy = (n.vy / spd) * SPEED * 2;
      }

      n.x += n.vx;
      n.y += n.vy;

      if (n.x < -10)    n.x = W + 10;
      else if (n.x > W + 10) n.x = -10;
      if (n.y < -10)    n.y = H + 10;
      else if (n.y > H + 10) n.y = -10;
    }

    // Draw connecting lines
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var a  = nodes[i], b = nodes[j];
        var dx = a.x - b.x, dy = a.y - b.y;
        var d  = Math.sqrt(dx * dx + dy * dy);
        if (d < MAX_DIST) {
          var alpha = (1 - d / MAX_DIST) * 0.45;
          ctx.beginPath();
          ctx.strokeStyle = 'rgba(' + COLOR_LINE + ',' + alpha + ')';
          ctx.lineWidth   = 0.8;
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }

    // Draw nodes
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + COLOR_NODE + ',0.85)';
      ctx.fill();
    }
  }

  function start() {
    var container = document.getElementById(CONTAINER_ID);
    if (!container) return;
    init(container);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
