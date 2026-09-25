/* ==========================================================================
   WAMA — moteur de présentation « canvas zoomable » (2026-09-25)

   Un seul plan (#world) porte toutes les .frame, chacune posée par ses
   attributs data-x / data-y (centre), data-s (échelle), data-r (rotation, deg).
   La caméra vole d'une frame à l'autre : translation + zoom en espace
   logarithmique, avec un « recul » proportionnel à la distance (le geste
   Prezi : on s'éloigne pour voir le chemin, on replonge sur la cible).

   API publique : window.WamaPrez = { go(i), goId(id), next(), prev(), overview() }
   Événement : 'wama:step' sur document, detail = { index, frame, settled }
   — settled=true une fois la caméra arrivée (c'est là que les scènes 3D
   s'accrochent à leur .scene-slot).
   ========================================================================== */
(function () {
  'use strict';

  const W = 1600, H = 900;          // taille de base d'une frame
  const MARGIN = 0.94;              // part de l'écran occupée par la frame active
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const world = document.getElementById('world');
  const frames = Array.from(world.querySelectorAll('.frame'));
  const steps = frames.filter(f => !f.hasAttribute('data-nostep'));

  const cam = { x: 0, y: 0, z: 0, r: 0 };   // z = log(échelle)
  let current = -1, anim = null, inOverview = false;

  // ── Pose des frames ───────────────────────────────────────────────────
  function place(f) {
    const x = +f.dataset.x || 0, y = +f.dataset.y || 0;
    const s = +f.dataset.s || 1, r = +f.dataset.r || 0;
    f.style.transform = `translate(${x - W / 2}px, ${y - H / 2}px) rotate(${r}deg) scale(${s})`;
  }
  frames.forEach(place);

  // ── Caméra ────────────────────────────────────────────────────────────
  function fitScale(w, h) {
    return Math.min(window.innerWidth / w, window.innerHeight / h) * MARGIN;
  }
  function targetFor(f) {
    const s = +f.dataset.s || 1;
    return { x: +f.dataset.x || 0, y: +f.dataset.y || 0,
             z: Math.log(fitScale(W * s, H * s)), r: +f.dataset.r || 0 };
  }
  function overviewTarget() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    frames.forEach(f => {
      const s = +f.dataset.s || 1, x = +f.dataset.x || 0, y = +f.dataset.y || 0;
      const hw = W * s / 2, hh = H * s / 2;
      x0 = Math.min(x0, x - hw); x1 = Math.max(x1, x + hw);
      y0 = Math.min(y0, y - hh); y1 = Math.max(y1, y + hh);
    });
    // Marge supplémentaire : la barre de navigation ne doit pas masquer les bords du plan.
    return { x: (x0 + x1) / 2, y: (y0 + y1) / 2 + 30 / fitScale(x1 - x0, y1 - y0), z: Math.log(fitScale(x1 - x0, y1 - y0) * 0.9), r: 0 };
  }
  function apply() {
    const s = Math.exp(cam.z);
    world.style.transform =
      `translate(${window.innerWidth / 2}px, ${window.innerHeight / 2}px) ` +
      `scale(${s}) rotate(${-cam.r}deg) translate(${-cam.x}px, ${-cam.y}px)`;
    document.dispatchEvent(new CustomEvent('wama:camera', { detail: { x: cam.x, y: cam.y, s } }));
  }
  const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

  function flyTo(t, done) {
    if (anim) cancelAnimationFrame(anim.raf);
    const from = { ...cam };
    let dr = t.r - from.r; dr = ((dr + 540) % 360) - 180;
    const dist = Math.hypot(t.x - from.x, t.y - from.y);
    // Largeur visible (en unités monde) au plus serré des deux cadrages.
    const view = window.innerWidth / Math.exp(Math.max(from.z, t.z));
    const bump = Math.min(2.2, Math.max(0, Math.log(dist / view + 1) * 0.9));
    const dur = reduceMotion ? 0 : Math.min(2200, 900 + bump * 450);
    const t0 = performance.now();
    document.body.classList.add('moving');
    function step(now) {
      const k = dur ? Math.min(1, (now - t0) / dur) : 1, e = ease(k);
      cam.x = from.x + (t.x - from.x) * e;
      cam.y = from.y + (t.y - from.y) * e;
      cam.z = from.z + (t.z - from.z) * e - bump * Math.sin(Math.PI * e);
      cam.r = from.r + dr * e;
      apply();
      if (k < 1) { anim.raf = requestAnimationFrame(step); return; }
      anim = null; cam.r = t.r;
      document.body.classList.remove('moving');
      done && done();
    }
    anim = { raf: requestAnimationFrame(step) };
  }

  // ── Navigation ────────────────────────────────────────────────────────
  const hudTitle = document.getElementById('hud-title');
  const hudCount = document.getElementById('hud-count');
  const hudDots = document.getElementById('hud-dots');
  const progress = document.getElementById('progress');

  function emit(settled) {
    document.dispatchEvent(new CustomEvent('wama:step', {
      detail: { index: current, frame: inOverview ? null : steps[current], settled } }));
  }
  function go(i, { instant = false } = {}) {
    i = Math.max(0, Math.min(steps.length - 1, i));
    const prevFrame = steps[current];
    current = i; inOverview = false;
    const f = steps[i];
    frames.forEach(x => x.classList.toggle('active', x === f));
    hudTitle.textContent = f.dataset.title || '';
    hudCount.textContent = `${String(i + 1).padStart(2, '0')} / ${String(steps.length).padStart(2, '0')}`;
    progress.style.width = `${(i / (steps.length - 1)) * 100}%`;
    hudDots.querySelectorAll('i[data-i]').forEach(d => d.classList.toggle('on', +d.dataset.i === i));
    try { history.replaceState(null, '', '#' + (f.id || (i + 1))); } catch (e) { /* file:// */ }
    emit(false);
    const t = targetFor(f);
    if (instant || prevFrame === undefined) { Object.assign(cam, t); apply(); emit(true); }
    else flyTo(t, () => emit(true));
  }
  function overview() {
    if (inOverview) { go(current); return; }
    inOverview = true; frames.forEach(x => x.classList.remove('active'));
    hudTitle.textContent = 'Vue d’ensemble — cliquez une zone pour y plonger';
    emit(false);
    flyTo(overviewTarget(), () => emit(true));
  }
  const next = () => go(current + 1), prev = () => go(current - 1);
  const goId = id => { const i = steps.findIndex(f => f.id === id); if (i >= 0) go(i); };

  // Points de progression, séparés par section (data-section sur la 1re frame d'une section).
  steps.forEach((f, i) => {
    if (i > 0 && f.dataset.section) { const sep = document.createElement('i'); sep.className = 'sec'; hudDots.appendChild(sep); }
    const d = document.createElement('i'); d.dataset.i = i; d.title = f.dataset.title || '';
    d.addEventListener('click', () => go(i)); hudDots.appendChild(d);
  });

  frames.forEach(f => f.addEventListener('click', e => {
    if (f.classList.contains('active') || e.target.closest('a,button,input')) return;
    const i = steps.indexOf(f); if (i >= 0) go(i);
  }));

  document.getElementById('btn-prev').addEventListener('click', prev);
  document.getElementById('btn-next').addEventListener('click', next);
  document.getElementById('btn-overview').addEventListener('click', overview);
  document.getElementById('btn-full').addEventListener('click', toggleFull);
  const help = document.getElementById('help');
  document.getElementById('btn-help').addEventListener('click', () => help.classList.toggle('on'));

  function toggleFull() {
    if (!document.fullscreenElement) document.documentElement.requestFullscreen?.();
    else document.exitFullscreen?.();
  }

  document.addEventListener('keydown', e => {
    if (e.target.closest('input,textarea,select')) return;
    switch (e.key) {
      case 'ArrowRight': case 'PageDown': case ' ': e.preventDefault(); next(); break;
      case 'ArrowLeft': case 'PageUp': e.preventDefault(); prev(); break;
      case 'Home': go(0); break;
      case 'End': go(steps.length - 1); break;
      case 'o': case 'O': case 'Escape': overview(); break;
      case 'f': case 'F': toggleFull(); break;
      case '?': help.classList.toggle('on'); break;
    }
  });

  // Glisser horizontal (tactile) = suivant / précédent.
  let tx = null;
  window.addEventListener('touchstart', e => { tx = e.touches[0].clientX; }, { passive: true });
  window.addEventListener('touchend', e => {
    if (tx === null) return;
    const dx = e.changedTouches[0].clientX - tx; tx = null;
    if (Math.abs(dx) > 60 && !e.target.closest('#scene-layer')) (dx < 0 ? next : prev)();
  });

  window.addEventListener('resize', () => {
    if (anim) return;
    if (inOverview) Object.assign(cam, overviewTarget()); else Object.assign(cam, targetFor(steps[current]));
    apply(); emit(true);
  });

  window.WamaPrez = { go, goId, next, prev, overview, steps };

  // Lien profond saisi à la main (#transcriber…) : la page ne se recharge pas, on y vole.
  window.addEventListener('hashchange', () => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (steps[current] && steps[current].id !== id) goId(id);
  });

  // Démarrage : ancre d'URL (#id ou #n), sinon première frame.
  const h = decodeURIComponent(location.hash.slice(1));
  let start = steps.findIndex(f => f.id === h);
  if (start < 0 && /^\d+$/.test(h)) start = +h - 1;
  go(start >= 0 ? start : 0, { instant: true });

  // ── Fond : constellation en parallaxe (canvas 2D, sans dépendance) ─────
  const bg = document.getElementById('bg-layer');
  const ctx = bg.getContext('2d');
  const stars = [];
  let dpr = 1;
  function resizeBg() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    bg.width = innerWidth * dpr; bg.height = innerHeight * dpr;
  }
  resizeBg(); window.addEventListener('resize', resizeBg);
  const hues = ['56,225,255', '139,123,255', '244,114,182', '251,191,36', '200,210,255'];
  for (let i = 0; i < 260; i++) {
    stars.push({ x: Math.random(), y: Math.random(), d: 0.15 + Math.random() * 0.85,
                 c: hues[i % 7 === 0 ? (i % 4) : 4], a: 0.2 + Math.random() * 0.6,
                 tw: Math.random() * Math.PI * 2 });
  }
  let camView = { x: 0, y: 0, s: 1 };
  document.addEventListener('wama:camera', e => { camView = e.detail; });
  function drawBg(now) {
    const w = bg.width, h = bg.height;
    ctx.clearRect(0, 0, w, h);
    const pts = [];
    for (const st of stars) {
      // Parallaxe : plus l'étoile est « proche » (d grand), plus elle suit la caméra.
      const px = ((st.x * w - camView.x * st.d * 0.08 * dpr) % w + w) % w;
      const py = ((st.y * h - camView.y * st.d * 0.08 * dpr) % h + h) % h;
      const a = st.a * (0.65 + 0.35 * Math.sin(now / 1400 + st.tw));
      const r = (0.4 + st.d * 1.3) * dpr;
      ctx.fillStyle = `rgba(${st.c},${a})`;
      ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2); ctx.fill();
      if (st.d > 0.7) pts.push([px, py]);
    }
    ctx.lineWidth = 0.6 * dpr;
    const lim = 150 * dpr;
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      const dx = pts[i][0] - pts[j][0], dy = pts[i][1] - pts[j][1], dd = Math.hypot(dx, dy);
      if (dd < lim) {
        ctx.strokeStyle = `rgba(139,123,255,${0.16 * (1 - dd / lim)})`;
        ctx.beginPath(); ctx.moveTo(pts[i][0], pts[i][1]); ctx.lineTo(pts[j][0], pts[j][1]); ctx.stroke();
      }
    }
    if (!reduceMotion) requestAnimationFrame(drawBg);
  }
  requestAnimationFrame(drawBg);
})();
