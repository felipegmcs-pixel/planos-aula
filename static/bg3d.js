/* ProfessorIA — 3D Particle Background (Three.js r158 CDN)
   Drop <canvas id="bg3d"></canvas> + <script src="/static/bg3d.js"></script>
   into any page. Automatically adapts to dark/light theme.
*/
(function () {
  'use strict';

  function isDark() {
    return document.documentElement.getAttribute('data-theme') === 'dark' ||
      (!document.documentElement.getAttribute('data-theme') &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  function loadThree(cb) {
    if (window.THREE) { cb(); return; }
    var s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/three@0.158.0/build/three.min.js';
    s.onload = cb;
    document.head.appendChild(s);
  }

  function init() {
    var canvas = document.getElementById('bg3d');
    if (!canvas) return;

    var THREE = window.THREE;
    var W = window.innerWidth, H = window.innerHeight;

    var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(W, H);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(60, W / H, 0.1, 1000);
    camera.position.z = 80;

    /* ── Floating particles ── */
    var COUNT = 320;
    var geo = new THREE.BufferGeometry();
    var pos = new Float32Array(COUNT * 3);
    var vel = new Float32Array(COUNT * 3);
    var sizes = new Float32Array(COUNT);

    for (var i = 0; i < COUNT; i++) {
      pos[i * 3]     = (Math.random() - 0.5) * 200;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 200;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 120;
      vel[i * 3]     = (Math.random() - 0.5) * 0.012;
      vel[i * 3 + 1] = (Math.random() - 0.5) * 0.012;
      vel[i * 3 + 2] = (Math.random() - 0.5) * 0.006;
      sizes[i] = Math.random() * 2.2 + 0.4;
    }

    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    /* ── Connecting lines (icosahedron wireframe) ── */
    var icoGeo = new THREE.IcosahedronGeometry(38, 2);
    var icoMat = new THREE.MeshBasicMaterial({
      color: isDark() ? 0x4338ca : 0x1E40AF,
      wireframe: true,
      transparent: true,
      opacity: isDark() ? 0.12 : 0.15
    });
    var ico = new THREE.Mesh(icoGeo, icoMat);
    scene.add(ico);

    /* ── Torus ring ── */
    var torusGeo = new THREE.TorusGeometry(55, 0.4, 8, 80);
    var torusMat = new THREE.MeshBasicMaterial({
      color: isDark() ? 0x7c3aed : 0x1E40AF,
      transparent: true,
      opacity: isDark() ? 0.09 : 0.15
    });
    var torus = new THREE.Mesh(torusGeo, torusMat);
    torus.rotation.x = Math.PI / 3;
    scene.add(torus);

    /* ── Particle material ── */
    var ptMat = new THREE.PointsMaterial({
      color: isDark() ? 0x818cf8 : 0x1E40AF,
      size: 1.1,
      transparent: true,
      opacity: isDark() ? 0.55 : 0.25,
      sizeAttenuation: true
    });
    var pts = new THREE.Points(geo, ptMat);
    scene.add(pts);

    /* ── Mouse parallax ── */
    var mouse = { x: 0, y: 0 };
    window.addEventListener('mousemove', function (e) {
      mouse.x = (e.clientX / window.innerWidth - 0.5) * 2;
      mouse.y = (e.clientY / window.innerHeight - 0.5) * 2;
    });

    /* ── Resize ── */
    window.addEventListener('resize', function () {
      W = window.innerWidth; H = window.innerHeight;
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
      renderer.setSize(W, H);
    });

    /* ── Theme change ── */
    var observer = new MutationObserver(function () {
      var dark = isDark();
      icoMat.color.set(dark ? 0x4338ca : 0x1E40AF);
      icoMat.opacity = dark ? 0.12 : 0.15;
      torusMat.color.set(dark ? 0x7c3aed : 0x1E40AF);
      torusMat.opacity = dark ? 0.09 : 0.15;
      ptMat.color.set(dark ? 0x818cf8 : 0x1E40AF);
      ptMat.opacity = dark ? 0.55 : 0.25;
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    /* ── Animate ── */
    var t = 0;
    function animate() {
      requestAnimationFrame(animate);
      t += 0.005;

      // Particle drift
      for (var i = 0; i < COUNT; i++) {
        pos[i * 3]     += vel[i * 3];
        pos[i * 3 + 1] += vel[i * 3 + 1];
        pos[i * 3 + 2] += vel[i * 3 + 2];
        // Wrap around
        if (Math.abs(pos[i * 3])     > 100) vel[i * 3]     *= -1;
        if (Math.abs(pos[i * 3 + 1]) > 100) vel[i * 3 + 1] *= -1;
        if (Math.abs(pos[i * 3 + 2]) > 60)  vel[i * 3 + 2] *= -1;
      }
      geo.attributes.position.needsUpdate = true;

      // Slow rotation + mouse parallax
      ico.rotation.x = t * 0.08 + mouse.y * 0.06;
      ico.rotation.y = t * 0.12 + mouse.x * 0.06;
      torus.rotation.z = t * 0.04;
      torus.rotation.y = mouse.x * 0.04;
      pts.rotation.y = t * 0.018;
      pts.rotation.x = t * 0.009;

      // Camera subtle drift
      camera.position.x += (mouse.x * 4 - camera.position.x) * 0.03;
      camera.position.y += (-mouse.y * 3 - camera.position.y) * 0.03;
      camera.lookAt(scene.position);

      renderer.render(scene, camera);
    }
    animate();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { loadThree(init); });
  } else {
    loadThree(init);
  }
})();
