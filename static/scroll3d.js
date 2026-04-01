/* scroll3d.js — ProfessorIA neural network + GSAP ScrollTrigger */
(function () {
  'use strict';

  /* ── THREE setup ── */
  const canvas   = document.getElementById('neural-canvas');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x000000, 0);

  const scene  = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 100);
  camera.position.z = 4.5;

  /* ── Resize ── */
  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  /* ── Build neural cloud ── */
  const POINT_COUNT = 1400;
  const positions   = new Float32Array(POINT_COUNT * 3);
  const colors      = new Float32Array(POINT_COUNT * 3);
  const basePos     = new Float32Array(POINT_COUNT * 3);
  const explVec     = new Float32Array(POINT_COUNT * 3);

  const cBlue   = new THREE.Color('#1E40AF');
  const cViolet = new THREE.Color('#a78bfa');
  const cCyan   = new THREE.Color('#67e8f9');

  for (let i = 0; i < POINT_COUNT; i++) {
    const theta = Math.acos(1 - 2 * (i + 0.5) / POINT_COUNT);
    const phi   = Math.PI * (1 + Math.sqrt(5)) * i;
    const r     = 1.4 + Math.random() * 0.9;

    const x = r * Math.sin(theta) * Math.cos(phi);
    const y = r * Math.cos(theta);
    const z = r * Math.sin(theta) * Math.sin(phi);

    basePos[i * 3] = x; basePos[i * 3 + 1] = y; basePos[i * 3 + 2] = z;
    positions[i * 3] = x; positions[i * 3 + 1] = y; positions[i * 3 + 2] = z;

    const len = Math.sqrt(x * x + y * y + z * z) || 1;
    explVec[i * 3]     = x / len + (Math.random() - 0.5) * 0.4;
    explVec[i * 3 + 1] = y / len + (Math.random() - 0.5) * 0.4;
    explVec[i * 3 + 2] = z / len + (Math.random() - 0.5) * 0.4;

    const t = (y + 2.3) / 4.6;
    const c = t < 0.5
      ? cBlue.clone().lerp(cViolet, t * 2)
      : cViolet.clone().lerp(cCyan, (t - 0.5) * 2);

    colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
  }

  const ptGeo = new THREE.BufferGeometry();
  ptGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  ptGeo.setAttribute('color',    new THREE.BufferAttribute(colors, 3));

  const ptMat = new THREE.PointsMaterial({
    size: 0.028, vertexColors: true, transparent: true,
    opacity: 1.0, sizeAttenuation: true, depthWrite: false,
  });

  const points = new THREE.Points(ptGeo, ptMat);

  /* ── Connections ── */
  const DIST_THRESH = 0.38;
  const linePairs   = [];

  for (let i = 0; i < POINT_COUNT; i++) {
    let count = 0;
    for (let j = i + 1; j < POINT_COUNT; j++) {
      if (count >= 5) break;
      const dx = basePos[i * 3] - basePos[j * 3];
      const dy = basePos[i * 3 + 1] - basePos[j * 3 + 1];
      const dz = basePos[i * 3 + 2] - basePos[j * 3 + 2];
      if (dx * dx + dy * dy + dz * dz < DIST_THRESH * DIST_THRESH) {
        linePairs.push(i, j);
        count++;
      }
    }
  }

  const lineCount  = linePairs.length / 2;
  const linePos    = new Float32Array(lineCount * 6);
  const lineColors = new Float32Array(lineCount * 6);

  for (let k = 0; k < lineCount; k++) {
    const a = linePairs[k * 2], b = linePairs[k * 2 + 1];
    linePos[k * 6]     = basePos[a * 3];     linePos[k * 6 + 1] = basePos[a * 3 + 1]; linePos[k * 6 + 2] = basePos[a * 3 + 2];
    linePos[k * 6 + 3] = basePos[b * 3];     linePos[k * 6 + 4] = basePos[b * 3 + 1]; linePos[k * 6 + 5] = basePos[b * 3 + 2];
    lineColors[k * 6]     = (colors[a * 3]     + colors[b * 3])     * 0.5;
    lineColors[k * 6 + 1] = (colors[a * 3 + 1] + colors[b * 3 + 1]) * 0.5;
    lineColors[k * 6 + 2] = (colors[a * 3 + 2] + colors[b * 3 + 2]) * 0.5;
    lineColors[k * 6 + 3] = lineColors[k * 6];
    lineColors[k * 6 + 4] = lineColors[k * 6 + 1];
    lineColors[k * 6 + 5] = lineColors[k * 6 + 2];
  }

  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute('position', new THREE.BufferAttribute(linePos, 3));
  lineGeo.setAttribute('color',    new THREE.BufferAttribute(lineColors, 3));

  const lineMat = new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0.22, depthWrite: false,
  });

  const lines = new THREE.LineSegments(lineGeo, lineMat);

  const group = new THREE.Group();
  group.add(lines);
  group.add(points);
  scene.add(group);

  /* ── GSAP state proxy ── */
  const state = {
    rotY:      0,
    rotX:      0,
    cameraZ:   4.5,
    explosion: 0,
    lineOp:    0.22,
    pointOp:   1.0,
    canvasOp:  1.0,   // master opacity for full canvas fade
  };

  gsap.registerPlugin(ScrollTrigger);

  /* ── Main scroll timeline (S1 → S4, inside #scroll-wrapper) ── */
  const tl = gsap.timeline({
    scrollTrigger: {
      trigger: '#scroll-wrapper',
      start:   'top top',
      end:     'bottom bottom',
      scrub:   1.5,
    }
  });

  /* S1 → S2: zoom in, lines brighten */
  tl.to(state, { rotY: Math.PI * 1.5, cameraZ: 2.6, lineOp: 0.5, ease: 'none' }, 0);

  /* S2 → S3: explode */
  tl.to(state, { explosion: 1, cameraZ: 7.0, lineOp: 0.0, pointOp: 0.5, ease: 'none' }, 0.33);

  /* S3 → S4: regroup */
  tl.to(state, { explosion: 0, rotY: Math.PI * 3.5, cameraZ: 4.0, lineOp: 0.35, pointOp: 1.0, ease: 'none' }, 0.66);

  /* ── Showcase section: slow idle, soften network ── */
  ScrollTrigger.create({
    trigger: '#s5',
    start:   'top 60%',
    end:     'bottom 40%',
    scrub:   2,
    onUpdate(self) {
      // Fade from 1 → 0.35 as showcase enters, back to 1 as it leaves
      const p = self.progress;
      state.canvasOp = p < 0.5
        ? gsap.utils.interpolate(1.0, 0.35, p * 2)
        : gsap.utils.interpolate(0.35, 0.55, (p - 0.5) * 2);
    },
  });

  /* ── Pricing section: network fades to near-zero for readability ── */
  ScrollTrigger.create({
    trigger: '#s6',
    start:   'top 70%',
    end:     'top top',
    scrub:   2,
    onUpdate(self) {
      state.canvasOp = gsap.utils.interpolate(0.55, 0.08, self.progress);
    },
  });

  /* When pricing is fully past, keep at low opacity */
  ScrollTrigger.create({
    trigger: '#s6',
    start:   'top top',
    onEnter()  { state.canvasOp = 0.08; },
    onLeaveBack() { /* restored by the scrub above */ },
  });

  /* ── Idle micro-rotation ── */
  let idleT = 0;

  function animate() {
    requestAnimationFrame(animate);
    idleT += 0.005;

    camera.position.z = state.cameraZ;
    group.rotation.y  = state.rotY + idleT * 0.08;
    group.rotation.x  = state.rotX + Math.sin(idleT * 0.3) * 0.04;

    /* Explosion displacement */
    const exp = state.explosion;
    if (exp > 0) {
      for (let i = 0; i < POINT_COUNT; i++) {
        positions[i * 3]     = basePos[i * 3]     + explVec[i * 3]     * exp * 4.0;
        positions[i * 3 + 1] = basePos[i * 3 + 1] + explVec[i * 3 + 1] * exp * 4.0;
        positions[i * 3 + 2] = basePos[i * 3 + 2] + explVec[i * 3 + 2] * exp * 4.0;
      }
      ptGeo.attributes.position.needsUpdate = true;
    } else if (positions[0] !== basePos[0]) {
      for (let i = 0; i < POINT_COUNT * 3; i++) positions[i] = basePos[i];
      ptGeo.attributes.position.needsUpdate = true;
    }

    /* Apply opacities — canvasOp acts as master multiplier */
    const master = Math.max(0, Math.min(1, state.canvasOp));
    lineMat.opacity = state.lineOp  * master;
    ptMat.opacity   = state.pointOp * master;

    renderer.render(scene, camera);
  }

  animate();
})();
