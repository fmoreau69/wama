/**
 * WamaPreviewOverlay — ce qui se superpose à un aperçu, et la comparaison de deux vidéos.
 *
 * Né le 2026-10-05 (demande de Fabien : voir la détection de l'anonymizer APRÈS le traitement,
 * et la comparer au floutage « comme le mode comparaison des autres apps ») :
 *
 *   • `attach(mediaEl, overlay)` — dessine un document `detections` (type de donnée commun,
 *     `common/utils/detections.py` : boîtes, contours, libellés) par-dessus une image ou une
 *     vidéo, à la frame COURANTE de la lecture. Rien n'est réencodé : la vue « Détection » est
 *     l'entrée + le document, dessinés dans le navigateur. `overlay` = { url, boxes, labels,
 *     confidence } (servi par la face d'aperçu de l'app, `preview_utils`).
 *   • `syncVideos(master, slave)` — la seconde vidéo suit la première (lecture, pause,
 *     position) : c'est ce qui rend Comparer possible sur des vidéos.
 *
 * Les fonctions pures (`frameAt`, `contentRect`) sont gardées en V8 (`tests_cap_from_js`).
 */
(function (global) {
  'use strict';

  var cache = {};

  function load(url) {
    if (!cache[url]) {
      cache[url] = fetch(url, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (doc) {
          var by = {};
          (doc.frames || []).forEach(function (f) { by[f.i] = f.d || []; });
          doc._byFrame = by;
          return doc;
        });
    }
    return cache[url];
  }

  // L'indice de frame d'un instant de lecture (une image : toujours 0).
  function frameAt(doc, seconds) {
    if (!doc || doc.media !== 'video' || !doc.fps) return 0;
    return Math.max(0, Math.floor((seconds || 0) * doc.fps + 1e-6));
  }

  // Où l'image est RÉELLEMENT dessinée dans l'élément (`object-fit: contain`, bandes comprises).
  function contentRect(boxW, boxH, naturalW, naturalH) {
    if (!naturalW || !naturalH || !boxW || !boxH) return { x: 0, y: 0, scale: 1 };
    var scale = Math.min(boxW / naturalW, boxH / naturalH);
    return { x: (boxW - naturalW * scale) / 2, y: (boxH - naturalH * scale) / 2, scale: scale };
  }

  var SEEN = '#ffc800';

  function draw(ctx, found, rect, opts) {
    ctx.lineWidth = 2;
    ctx.strokeStyle = SEEN;
    ctx.fillStyle = 'rgba(255, 200, 0, 0.25)';
    ctx.font = '12px sans-serif';
    (found || []).forEach(function (d) {
      (d.polygons || []).forEach(function (poly) {
        if (!poly.length) return;
        ctx.beginPath();
        poly.forEach(function (p, i) {
          var x = rect.x + p[0] * rect.scale, y = rect.y + p[1] * rect.scale;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      });
      var b = d.box || [0, 0, 0, 0];
      var x1 = rect.x + b[0] * rect.scale, y1 = rect.y + b[1] * rect.scale;
      if (opts.boxes !== false) {
        ctx.strokeRect(x1, y1, (b[2] - b[0]) * rect.scale, (b[3] - b[1]) * rect.scale);
      }
      var text = [opts.labels !== false ? d.label : '',
                  opts.confidence !== false && d.conf != null ? Number(d.conf).toFixed(2) : '']
        .filter(Boolean).join(' ');
      if (text) {
        ctx.fillStyle = SEEN;
        ctx.fillText(text, x1, Math.max(12, y1 - 4));
        ctx.fillStyle = 'rgba(255, 200, 0, 0.25)';
      }
    });
  }

  function attach(mediaEl, overlay) {
    if (!mediaEl || !overlay || !overlay.url || mediaEl._wamaOverlay) return;
    var holder = document.createElement('span');
    holder.className = 'wama-preview-overlay';
    holder.style.cssText = 'position:relative;display:inline-block;max-width:100%;line-height:0;';
    mediaEl.parentNode.insertBefore(holder, mediaEl);
    holder.appendChild(mediaEl);
    var canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:absolute;left:0;top:0;pointer-events:none;';
    holder.appendChild(canvas);
    var state = { doc: null, raf: null };
    mediaEl._wamaOverlay = state;
    var video = mediaEl.tagName === 'VIDEO';

    function render() {
      var w = mediaEl.clientWidth, h = mediaEl.clientHeight;
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      var ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, w, h);
      if (!state.doc) return;
      var nw = video ? mediaEl.videoWidth : mediaEl.naturalWidth;
      var nh = video ? mediaEl.videoHeight : mediaEl.naturalHeight;
      // Le document est en pixels de la SOURCE (sa largeur) : l'échelle part de là.
      var rect = contentRect(w, h, nw, nh);
      if (state.doc.width && nw) rect.scale *= nw / state.doc.width;
      draw(ctx, state.doc._byFrame[frameAt(state.doc, video ? mediaEl.currentTime : 0)], rect,
           overlay);
    }

    function loop() {
      render();
      if (video && !mediaEl.paused && !mediaEl.ended) state.raf = global.requestAnimationFrame(loop);
      else state.raf = null;
    }

    load(overlay.url).then(function (doc) { state.doc = doc; render(); })
      .catch(function () { holder.title = 'Détections indisponibles'; });
    ['loadedmetadata', 'loadeddata', 'load', 'seeked', 'timeupdate'].forEach(function (ev) {
      mediaEl.addEventListener(ev, render);
    });
    if (video) {
      mediaEl.addEventListener('play', function () { if (!state.raf) loop(); });
    }
    if (global.ResizeObserver) new global.ResizeObserver(render).observe(mediaEl);
  }

  function syncVideos(master, slave) {
    if (!master || !slave) return;
    slave.muted = true;
    var align = function () {
      if (Math.abs((slave.currentTime || 0) - (master.currentTime || 0)) > 0.12) {
        slave.currentTime = master.currentTime;
      }
    };
    master.addEventListener('play', function () { align(); slave.play().catch(function () {}); });
    master.addEventListener('pause', function () { slave.pause(); align(); });
    master.addEventListener('seeked', align);
    master.addEventListener('timeupdate', align);
    master.addEventListener('ratechange', function () { slave.playbackRate = master.playbackRate; });
  }

  global.WamaPreviewOverlay = {
    attach: attach, syncVideos: syncVideos, frameAt: frameAt, contentRect: contentRect,
  };
})(window);
