/* ============================================================================
 * SentinelAI — orb.js
 * The center visual of the SENTINEL PRIME HUD.
 *
 * A layered Three.js star-field orb with SVG reticle rings, a core glow, and
 * an inner status label. Six states drive particle behaviour, ring speed and
 * colour:  idle | listening | thinking | speaking | alert | earn.
 *
 * Depends on a global `THREE` (load three.min.js before this file).
 * Builds itself inside #orb-root on DOMContentLoaded (or call SentinelOrb.init).
 *
 * Public API:
 *   window.SentinelOrb = {
 *     init(containerId?),      // mount (auto-called for #orb-root)
 *     setState(state),         // idle|listening|thinking|speaking|alert|earn
 *     pulse(),                 // one-shot wave from the core
 *     alert(msg),              // -> alert state + flashes a message
 *     setVolume(v),            // 0..1 mic/output level (reactive scale)
 *     getState()
 *   }
 * ========================================================================== */
(function () {
  'use strict';

  // ─── State colour + behaviour table ──────────────────────────────────────
  // colors are THREE-friendly hex ints; label is the inner status text.
  var STATES = {
    idle:      { core: 0x00d4ff, particle: 0x00d4ff, label: 'SENTINEL ONLINE', ring: 1.0,  glow: 0.55, swirl: 0.04,  expand: 0.0,  drift: 1.0 },
    listening: { core: 0x00fff7, particle: 0x00fff7, label: 'LISTENING...',    ring: 2.2,  glow: 0.85, swirl: 0.02,  expand: 1.0,  drift: 0.2 },
    thinking:  { core: 0xa855f7, particle: 0xbf80ff, label: 'PROCESSING...',   ring: 0.55, glow: 0.7,  swirl: 0.16,  expand: 0.2,  drift: 0.3 },
    speaking:  { core: 0xeaf6ff, particle: 0x9fe8ff, label: 'RESPONDING...',   ring: 2.8,  glow: 1.0,  swirl: 0.05,  expand: 0.3,  drift: 0.4, wave: true },
    alert:     { core: 0xff6b35, particle: 0xff7a45, label: 'ALERT',           ring: 3.2,  glow: 1.0,  swirl: 0.2,   expand: 0.6,  drift: 0.2, erratic: true },
    earn:      { core: 0xffd700, particle: 0xffd766, label: 'EARN MODE',       ring: 1.6,  glow: 0.9,  swirl: 0.1,   expand: 0.4,  drift: 0.4, orbit: true }
  };

  var PARTICLE_COUNT = 1200;

  var ctx = {
    mounted: false,
    state: 'idle',
    target: STATES.idle,
    // smoothed runtime values
    cur: { ring: 1.0, glow: 0.55, swirl: 0.04, expand: 0.0, drift: 1.0, r: 0, g: 0.83, b: 1.0 },
    volume: 0,
    pulseT: 0,            // decaying one-shot pulse energy
    time: 0,
    raf: null,
    three: null,         // {scene,camera,renderer,points,positions,base,vel,material}
    els: {}              // dom refs
  };

  // ─── Soft circular sprite for additive particles ─────────────────────────
  function makeSprite() {
    var c = document.createElement('canvas');
    c.width = c.height = 64;
    var g = c.getContext('2d');
    var grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.25, 'rgba(255,255,255,0.85)');
    grad.addColorStop(0.6, 'rgba(255,255,255,0.25)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    var tex = new THREE.Texture(c);
    tex.needsUpdate = true;
    return tex;
  }

  // ─── Layer 3: SVG reticle rings ───────────────────────────────────────────
  function buildRings(root) {
    var wrap = document.createElement('div');
    wrap.className = 'sentinel-orb-rings';
    wrap.innerHTML = [
      '<svg viewBox="0 0 400 400" class="orb-ring-svg">',
      // Ring 1 — 20s CW, dashed, triangle markers
      '  <g class="orb-ring orb-ring-1">',
      '    <circle cx="200" cy="200" r="178" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="2 10" opacity="0.55"/>',
      '    <polygon points="200,16 195,28 205,28" fill="currentColor"/>',
      '    <polygon points="200,384 195,372 205,372" fill="currentColor"/>',
      '    <polygon points="16,200 28,195 28,205" fill="currentColor"/>',
      '    <polygon points="384,200 372,195 372,205" fill="currentColor"/>',
      '  </g>',
      // Ring 2 — 12s CCW, node dots
      '  <g class="orb-ring orb-ring-2">',
      '    <circle cx="200" cy="200" r="150" fill="none" stroke="currentColor" stroke-width="1" opacity="0.25"/>',
      '    <circle class="orb-node" cx="200" cy="50"  r="3" fill="currentColor"/>',
      '    <circle class="orb-node" cx="350" cy="200" r="3" fill="currentColor"/>',
      '    <circle class="orb-node" cx="200" cy="350" r="3" fill="currentColor"/>',
      '    <circle class="orb-node" cx="50"  cy="200" r="3" fill="currentColor"/>',
      '    <circle class="orb-node" cx="305" cy="95"  r="2.4" fill="currentColor"/>',
      '    <circle class="orb-node" cx="95"  cy="305" r="2.4" fill="currentColor"/>',
      '  </g>',
      // Ring 3 — 35s CW, thin solid
      '  <g class="orb-ring orb-ring-3">',
      '    <circle cx="200" cy="200" r="120" fill="none" stroke="currentColor" stroke-width="0.6" opacity="0.4"/>',
      '  </g>',
      // Ring 4 — 8s CCW, only visible on active states
      '  <g class="orb-ring orb-ring-4">',
      '    <circle cx="200" cy="200" r="96" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="40 18" opacity="0.7"/>',
      '  </g>',
      '</svg>'
    ].join('\n');
    root.appendChild(wrap);
    return wrap;
  }

  // ─── Layer 4 + 5: core glow + status text + waveform ──────────────────────
  function buildOverlays(root) {
    var glow = document.createElement('div');
    glow.className = 'sentinel-orb-core';
    root.appendChild(glow);

    var label = document.createElement('div');
    label.className = 'sentinel-orb-label';
    label.innerHTML = '<span class="orb-label-text">SENTINEL ONLINE</span>' +
                      '<span class="orb-label-sub"></span>';
    root.appendChild(label);

    var wave = document.createElement('div');
    wave.className = 'sentinel-orb-wave';
    var bars = '';
    for (var i = 0; i < 28; i++) bars += '<i></i>';
    wave.innerHTML = bars;
    root.appendChild(wave);

    return { glow: glow, label: label.querySelector('.orb-label-text'),
             sub: label.querySelector('.orb-label-sub'), wave: wave,
             waveBars: wave.querySelectorAll('i') };
  }

  // ─── Layer 2: Three.js star field ─────────────────────────────────────────
  function buildThree(root) {
    if (typeof THREE === 'undefined') {
      console.warn('[SentinelOrb] THREE not loaded — orb runs without particle layer.');
      return null;
    }
    var w = root.clientWidth || 480;
    var h = root.clientHeight || 480;

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 100);
    camera.position.z = 14;

    var renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h);
    renderer.domElement.className = 'sentinel-orb-canvas';
    root.appendChild(renderer.domElement);

    var positions = new Float32Array(PARTICLE_COUNT * 3);
    var base = new Float32Array(PARTICLE_COUNT * 3);   // home radius/dir
    var vel = new Float32Array(PARTICLE_COUNT);        // per-particle phase/speed
    for (var i = 0; i < PARTICLE_COUNT; i++) {
      // dense center, sparse edges: bias radius by cubing a uniform
      var u = Math.random();
      var r = 1.2 + Math.pow(u, 0.5) * 6.2;            // 1.2 .. 7.4
      var theta = Math.random() * Math.PI * 2;
      var phi = Math.acos(2 * Math.random() - 1);
      var x = r * Math.sin(phi) * Math.cos(theta);
      var y = r * Math.sin(phi) * Math.sin(theta);
      var z = r * Math.cos(phi);
      base[i * 3] = x; base[i * 3 + 1] = y; base[i * 3 + 2] = z;
      positions[i * 3] = x; positions[i * 3 + 1] = y; positions[i * 3 + 2] = z;
      vel[i] = 0.4 + Math.random() * 1.2;
    }

    var geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    var material = new THREE.PointsMaterial({
      size: 0.18,
      map: makeSprite(),
      color: new THREE.Color(STATES.idle.particle),
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true
    });

    var points = new THREE.Points(geom, material);
    scene.add(points);

    return { scene: scene, camera: camera, renderer: renderer, points: points,
             geom: geom, positions: positions, base: base, vel: vel, material: material };
  }

  // ─── Per-frame particle behaviour ─────────────────────────────────────────
  function stepParticles(t3, dt) {
    var s = ctx.cur;
    var t = ctx.time;
    var pos = t3.positions;
    var base = t3.base;
    var vel = t3.vel;
    var expand = s.expand + ctx.volume * 0.6;
    var swirl = s.swirl;
    var erratic = ctx.target.erratic ? 1 : 0;
    var orbit = ctx.target.orbit ? 1 : 0;

    for (var i = 0; i < PARTICLE_COUNT; i++) {
      var ix = i * 3, iy = ix + 1, iz = ix + 2;
      var bx = base[ix], by = base[iy], bz = base[iz];

      // swirl around Z (clockwise) — rotate base direction over time
      var ang = swirl * t * vel[i];
      var ca = Math.cos(ang), sa = Math.sin(ang);
      var rx = bx * ca - by * sa;
      var ry = bx * sa + by * ca;
      var rz = bz;

      // expansion / contraction breathing
      var br = 1 + expand * 0.5 + Math.sin(t * 1.6 + vel[i] * 6) * 0.04 * s.drift;
      var tx = rx * br, ty = ry * br, tz = rz * br;

      // earn: gentle orbital bob like coins
      if (orbit) { ty += Math.sin(t * 2 + i) * 0.25; }
      // alert: jitter
      if (erratic) {
        tx += (Math.random() - 0.5) * 0.5;
        ty += (Math.random() - 0.5) * 0.5;
      }

      // ease current position toward target (idle => slow drift)
      var k = 0.08 + (1 - s.drift) * 0.12;
      pos[ix] += (tx - pos[ix]) * k;
      pos[iy] += (ty - pos[iy]) * k;
      pos[iz] += (tz - pos[iz]) * k;
    }
    t3.geom.attributes.position.needsUpdate = true;

    // overall scale: speaking wave + volume reactive + pulse
    var waveScale = ctx.target.wave ? (1 + Math.sin(t * 9) * 0.05) : 1;
    var pulseScale = 1 + ctx.pulseT * 0.35;
    var volScale = 1 + ctx.volume * 0.18;
    var sc = waveScale * pulseScale * volScale;
    t3.points.scale.set(sc, sc, sc);
    t3.points.rotation.z += dt * 0.05;

    // colour ease
    t3.material.color.setRGB(s.r, s.g, s.b);
    t3.material.opacity = 0.78 + s.glow * 0.22;
  }

  // ─── Main loop ────────────────────────────────────────────────────────────
  function loop() {
    ctx.raf = requestAnimationFrame(loop);
    if (document.hidden) return;
    var now = performance.now() / 1000;
    var dt = Math.min(0.05, now - (ctx._last || now));
    ctx._last = now;
    ctx.time += dt;

    // ease cur -> target
    var T = ctx.target;
    var tc = new THREE.Color ? null : null;
    ease('ring', T.ring, 0.08);
    ease('glow', T.glow, 0.08);
    ease('swirl', T.swirl, 0.05);
    ease('expand', T.expand, 0.06);
    ease('drift', T.drift, 0.06);
    // colour channels
    var col = ctx._targetCol;
    ctx.cur.r += (col.r - ctx.cur.r) * 0.07;
    ctx.cur.g += (col.g - ctx.cur.g) * 0.07;
    ctx.cur.b += (col.b - ctx.cur.b) * 0.07;

    // decay pulse + volume
    ctx.pulseT *= 0.92;
    if (ctx.pulseT < 0.001) ctx.pulseT = 0;

    // drive rings (animation-duration via CSS var ratio)
    if (ctx.els.rings) {
      ctx.els.rings.style.setProperty('--orb-ring-speed', (1 / Math.max(0.2, ctx.cur.ring)).toFixed(3));
    }
    // core glow color + intensity
    if (ctx.els.core) {
      var hex = rgbToCss(ctx.cur);
      ctx.els.core.style.background =
        'radial-gradient(circle, ' + hex + ' 0%, ' + rgbaCss(ctx.cur, 0.35) + ' 35%, transparent 70%)';
      ctx.els.core.style.opacity = (0.4 + ctx.cur.glow * 0.6).toFixed(3);
    }
    if (ctx.els.root) {
      ctx.els.root.style.color = rgbToCss(ctx.cur); // drives SVG currentColor
    }

    // waveform bars (listening/speaking)
    if (ctx.els.waveBars) {
      var active = ctx.state === 'listening' || ctx.state === 'speaking';
      ctx.els.wave.style.opacity = active ? '1' : '0.15';
      for (var b = 0; b < ctx.els.waveBars.length; b++) {
        var base = active ? (0.25 + ctx.volume * 0.7) : 0.12;
        var hgt = base + Math.abs(Math.sin(ctx.time * 6 + b * 0.5)) * (active ? 0.75 : 0.12);
        ctx.els.waveBars[b].style.transform = 'scaleY(' + hgt.toFixed(3) + ')';
      }
    }

    if (ctx.three) stepParticles(ctx.three, dt);
    if (ctx.three) ctx.three.renderer.render(ctx.three.scene, ctx.three.camera);
  }

  function ease(key, target, k) { ctx.cur[key] += (target - ctx.cur[key]) * k; }

  function rgbToCss(c) {
    return 'rgb(' + (c.r * 255 | 0) + ',' + (c.g * 255 | 0) + ',' + (c.b * 255 | 0) + ')';
  }
  function rgbaCss(c, a) {
    return 'rgba(' + (c.r * 255 | 0) + ',' + (c.g * 255 | 0) + ',' + (c.b * 255 | 0) + ',' + a + ')';
  }
  function hexToRgb(hex) {
    return { r: ((hex >> 16) & 255) / 255, g: ((hex >> 8) & 255) / 255, b: (hex & 255) / 255 };
  }

  // ─── Public API ───────────────────────────────────────────────────────────
  function setState(state) {
    if (!STATES[state]) { console.warn('[SentinelOrb] unknown state', state); return; }
    ctx.state = state;
    ctx.target = STATES[state];
    ctx._targetCol = hexToRgb(ctx.target.particle);
    if (ctx.els.label) ctx.els.label.textContent = ctx.target.label;
    if (ctx.els.root) {
      ctx.els.root.className = ctx.els.root.className
        .replace(/\borb-[a-z]+\b/g, '').trim() + ' orb-' + state;
    }
    if (state !== 'alert' && ctx.els.sub) ctx.els.sub.textContent = '';
  }

  function pulse() { ctx.pulseT = 1.0; }

  function alertMsg(msg) {
    setState('alert');
    if (ctx.els.sub) ctx.els.sub.textContent = msg || '';
    pulse();
  }

  function setVolume(v) { ctx.volume = Math.max(0, Math.min(1, v || 0)); }

  function init(containerId) {
    if (ctx.mounted) return;
    var root = document.getElementById(containerId || 'orb-root');
    if (!root) { console.warn('[SentinelOrb] container not found:', containerId || 'orb-root'); return; }
    root.classList.add('sentinel-orb-root', 'orb-idle');

    ctx.els.root = root;
    ctx.three = buildThree(root);
    ctx.els.rings = buildRings(root);
    var ov = buildOverlays(root);
    ctx.els.core = ov.glow;
    ctx.els.label = ov.label;
    ctx.els.sub = ov.sub;
    ctx.els.wave = ov.wave;
    ctx.els.waveBars = ov.waveBars;

    ctx._targetCol = hexToRgb(STATES.idle.particle);
    ctx.mounted = true;

    window.addEventListener('resize', function () {
      if (!ctx.three) return;
      var w = root.clientWidth, h = root.clientHeight;
      ctx.three.camera.aspect = w / h;
      ctx.three.camera.updateProjectionMatrix();
      ctx.three.renderer.setSize(w, h);
    });

    setState('idle');
    loop();
  }

  window.SentinelOrb = {
    init: init,
    setState: setState,
    pulse: pulse,
    alert: alertMsg,
    setVolume: setVolume,
    getState: function () { return ctx.state; }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      if (document.getElementById('orb-root')) init('orb-root');
    });
  } else {
    if (document.getElementById('orb-root')) init('orb-root');
  }
})();
