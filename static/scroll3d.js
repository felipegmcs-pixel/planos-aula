/* scroll3d.js — ProfessorIA TorusKnot 3D (hero column only) */
(function () {
  'use strict';

  const container = document.getElementById('canvas-container');
  if (!container) return;

  /* ── Renderer ── */
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.shadowMap.enabled = true;
  container.appendChild(renderer.domElement);

  /* ── Scene + Camera ── */
  const scene  = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 0, 5.5);

  /* ── Resize to container ── */
  function resize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(container);

  /* ── TorusKnot geometry ── */
  const geo = new THREE.TorusKnotGeometry(1.1, 0.34, 180, 24, 2, 3);

  /* Gradient vertex colors: blue at core, cyan at tips */
  const pos    = geo.attributes.position;
  const colArr = new Float32Array(pos.count * 3);
  const cBlue = new THREE.Color('#1E40AF');
  const cCyan = new THREE.Color('#67e8f9');
  const tmpV  = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    tmpV.fromBufferAttribute(pos, i);
    const t = (tmpV.length() - 0.7) / 1.0;   // 0 = inner, 1 = outer
    const c = cBlue.clone().lerp(cCyan, Math.min(Math.max(t, 0), 1));
    colArr[i * 3]     = c.r;
    colArr[i * 3 + 1] = c.g;
    colArr[i * 3 + 2] = c.b;
  }
  geo.setAttribute('color', new THREE.BufferAttribute(colArr, 3));

  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true,
    metalness: 0.75,
    roughness: 0.22,
    envMapIntensity: 1.0,
  });

  const mesh = new THREE.Mesh(geo, mat);
  scene.add(mesh);

  /* ── Wireframe overlay (subtle) ── */
  const wireMat = new THREE.MeshBasicMaterial({
    color: 0x2563EB, wireframe: true, transparent: true, opacity: 0.04,
  });
  const wireMesh = new THREE.Mesh(geo, wireMat);
  scene.add(wireMesh);

  /* ── Lights ── */
  // Ambient — very dim blue-tinted fill
  const ambient = new THREE.AmbientLight(0x0d1a3a, 1.2);
  scene.add(ambient);

  // Key light — bright blue, upper-right
  const keyLight = new THREE.PointLight(0x1E40AF, 120, 18);
  keyLight.position.set(4, 4, 4);
  scene.add(keyLight);

  // Fill light — cyan, lower-left
  const fillLight = new THREE.PointLight(0x67e8f9, 60, 14);
  fillLight.position.set(-4, -2, 3);
  scene.add(fillLight);

  // Rim light — indigo, behind
  const rimLight = new THREE.DirectionalLight(0x818cf8, 1.4);
  rimLight.position.set(0, 2, -4);
  scene.add(rimLight);

  /* ── Mouse parallax ── */
  let mouseX = 0, mouseY = 0;
  let targetX = 0, targetY = 0;

  window.addEventListener('mousemove', (e) => {
    // Normalize to [-0.5, 0.5] relative to viewport
    mouseX = (e.clientX / window.innerWidth  - 0.5) * 0.8;
    mouseY = (e.clientY / window.innerHeight - 0.5) * 0.5;
  });

  /* ── Animate ── */
  let t = 0;
  function animate() {
    requestAnimationFrame(animate);
    t += 0.008;

    // Smooth mouse tracking
    targetX += (mouseX - targetX) * 0.06;
    targetY += (mouseY - targetY) * 0.06;

    // Auto rotation + mouse tilt
    mesh.rotation.x = t * 0.32 + targetY * 0.6;
    mesh.rotation.y = t * 0.5  + targetX * 0.8;
    mesh.rotation.z = t * 0.18;

    wireMesh.rotation.copy(mesh.rotation);

    // Subtle breathing scale
    const s = 1 + Math.sin(t * 1.1) * 0.018;
    mesh.scale.setScalar(s);
    wireMesh.scale.setScalar(s);

    // Pulsing key light intensity
    keyLight.intensity = 100 + Math.sin(t * 1.8) * 25;

    renderer.render(scene, camera);
  }

  animate();
})();
