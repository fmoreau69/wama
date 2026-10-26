/*
 * WamaCapture — la CAPTURE caméra / micro du navigateur, brique commune (montée par base.html).
 *
 * POURQUOI (2026-10-26, décision de Fabien : « la brique commune, méticuleusement, sans rien
 * casser, sans rien perdre »). Quatre pages ouvraient la caméra ou le micro, chacune à sa façon —
 * l'écoute de l'assistant (`wama-assistant-listen.js`), l'enregistrement de la médiathèque
 * (`library-add.js`), les mains (`wama-hands.js`) et le temps réel du Face Analyzer. Chacune avait
 * une partie de ce qu'il faut, aucune le tout : le contexte sécurisé vérifié par deux sur quatre,
 * cinq messages de refus chez l'une, un seul chez l'autre, aucun chez la troisième ; le repli sur
 * la caméra par défaut chez les mains seulement ; et une caméra ouverte pour lire les NOMS des
 * périphériques, jamais refermée (Face Analyzer : le voyant restait allumé deux fois).
 *
 * CE QUE FAIT LA BRIQUE — l'accès au périphérique, rien de ce qu'on fait du flux (le découpage de
 * la parole reste à l'écoute, les gestes aux mains) :
 *   available()                 la page peut-elle demander caméra / micro (https ou localhost) ?
 *   open(constraints, opts)     → Promise<MediaStream>. Refus : une Error dont `message` est LISIBLE
 *                               (`explain`), `reason` le nom d'origine ('insecure' hors contexte
 *                               sécurisé), `cause` l'erreur du navigateur. `opts.fallback` : une
 *                               caméra / un micro CHOISI qui ne répond plus → celui par défaut, et
 *                               `opts.onFallback(err)` le dit à la page (qui oublie son choix).
 *   close(stream)               rend les pistes (sans danger sur null, ou deux fois).
 *   devices(kind, {ask})        → [{deviceId, label}] ; `kind` 'camera' | 'microphone'. Les noms ne
 *                               sont donnés qu'après une autorisation : `ask` l'obtient par un flux
 *                               bref, REFERMÉ aussitôt. Sans `ask`, ne rejette jamais ([] au pire).
 *   permission(kind)            → Promise<'granted'|'denied'|'prompt'|'unknown'>, sans rien demander.
 *   trackSettings(stream, kind) ce que le périphérique a réellement accordé (taille, écho…).
 *   zoomRange(stream)           le zoom MATÉRIEL de la caméra {min, max, step}, ou null.
 *   setZoom(stream, value)      → Promise ; borné à la plage, sans effet si la caméra refuse.
 *   record(stream, {type})      → {state(), stop() → Promise<Blob|null>}, ou null sans MediaRecorder.
 *   explain(err, kind)          le message lisible d'un refus (celui d'`open` rendu tel quel).
 * Et en quittant la page (`pagehide`), tout flux ouvert par la brique est rendu : une page gardée
 * en cache par le navigateur ne garde pas la caméra allumée.
 *
 * Chargée par base.html AVANT ses consommateurs ; aucune dépendance.
 */
(function (global) {
  'use strict';

  // Les mots de chaque périphérique, pour des messages accordés (« la caméra est utilisée… »).
  var WORDS = {
    camera: { noun: 'La caméra', short: 'Caméra', refused: 'Caméra refusée : autorisez-la', none: 'Aucune caméra détectée sur ce poste',
              remote: 'rediriger la webcam', used: 'La caméra est utilisée', input: 'videoinput', unnamed: 'Caméra' },
    microphone: { noun: 'Le micro', short: 'Micro', refused: 'Micro refusé : autorisez-le', none: 'Aucun micro détecté sur ce poste',
                  remote: "activer l'enregistrement audio à distance", used: 'Le micro est utilisé', input: 'audioinput', unnamed: 'Micro' },
  };
  // L'adresse sécurisée de WAMA, dite dans le message quand la page est servie en http.
  var SECURE_ADDRESS = 'https://wama.univ-eiffel.fr';

  var open_ = [];                         // les flux ouverts par la brique, rendus au `pagehide`

  function words(kind) { return WORDS[kind] || WORDS.camera; }
  function kindOf(constraints) { return constraints && constraints.video ? 'camera' : 'microphone'; }

  function available() {
    return !!(global.isSecureContext && global.navigator && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function explain(err, kind) {
    if (err && err.explained) return err.message;       // déjà rendue lisible par `open`
    var w = words(kind), name = err && (err.reason || err.name);
    if (name === 'insecure') {
      return w.noun + " n'est disponible qu'en connexion sécurisée : https (" + SECURE_ADDRESS + ") ou l'adresse localhost.";
    }
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      return w.refused + " pour ce site (cadenas de la barre d'adresse › " + w.short + ').';
    }
    if (name === 'NotFoundError' || name === 'OverconstrainedError') {
      return w.none + ' (en bureau à distance : ' + w.remote + ').';
    }
    if (name === 'NotReadableError') return w.used + ' par une autre application.';
    return w.short + ' indisponible : ' + ((err && err.message) || name || 'erreur inconnue');
  }

  // L'erreur rendue aux pages : lisible, et qui garde l'origine.
  function failure(err, kind) {
    var e = new Error(explain(err, kind));
    e.reason = (err && (err.reason || err.name)) || '';
    e.cause = err;
    e.explained = true;
    return e;
  }

  function track(stream, kind) {
    if (!stream) return null;
    var list = kind === 'microphone' ? stream.getAudioTracks() : stream.getVideoTracks();
    return list[0] || null;
  }

  function close(stream) {
    if (!stream) return;
    var i = open_.indexOf(stream);
    if (i !== -1) open_.splice(i, 1);
    stream.getTracks().forEach(function (t) {
      if (t.readyState !== 'ended') { try { t.stop(); } catch (_) {} }
    });
  }

  // Le périphérique CHOISI retiré de la demande : celui par défaut (la caméra de face).
  function withoutChoice(constraints) {
    var out = {};
    Object.keys(constraints).forEach(function (k) {
      var c = constraints[k];
      if (!c || typeof c !== 'object' || !c.deviceId) { out[k] = c; return; }
      var copy = {};
      Object.keys(c).forEach(function (key) { if (key !== 'deviceId') copy[key] = c[key]; });
      if (k === 'video') copy.facingMode = 'user';
      out[k] = copy;
    });
    return out;
  }

  function chose(constraints) {
    return ['video', 'audio'].some(function (k) {
      return constraints[k] && typeof constraints[k] === 'object' && constraints[k].deviceId;
    });
  }

  function open(constraints, opts) {
    opts = opts || {};
    var kind = kindOf(constraints);
    if (!available()) return Promise.reject(failure({ reason: 'insecure' }, kind));
    var keep = function (stream) { open_.push(stream); return stream; };
    return navigator.mediaDevices.getUserMedia(constraints).then(keep, function (err) {
      var refused = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
      if (!opts.fallback || refused || !chose(constraints)) throw failure(err, kind);
      if (opts.onFallback) { try { opts.onFallback(err); } catch (_) {} }
      return navigator.mediaDevices.getUserMedia(withoutChoice(constraints)).then(keep, function (again) {
        throw failure(again, kind);
      });
    });
  }

  function devices(kind, opts) {
    var w = words(kind);
    function raw() {
      if (!global.navigator || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return Promise.resolve([]);
      return navigator.mediaDevices.enumerateDevices().catch(function () { return []; }).then(function (all) {
        return all.filter(function (d) { return d.kind === w.input; });
      });
    }
    function named(found) {
      return found.map(function (d, i) { return { deviceId: d.deviceId, label: d.label || (w.unnamed + ' ' + (i + 1)) }; });
    }
    if (!(opts && opts.ask)) return raw().then(named);
    // Les noms n'existent qu'une fois l'accès accordé : un flux bref, refermé aussitôt.
    return raw().then(function (found) {
      if (found.length && found.every(function (d) { return d.label; })) return named(found);
      return open(kind === 'microphone' ? { audio: true } : { video: true }).then(function (probe) {
        close(probe);
        return raw().then(named);
      });
    });
  }

  function permission(kind) {
    if (!global.navigator || !navigator.permissions || !navigator.permissions.query) return Promise.resolve('unknown');
    return navigator.permissions.query({ name: kind === 'microphone' ? 'microphone' : 'camera' })
      .then(function (status) { return status.state; }, function () { return 'unknown'; });
  }

  function trackSettings(stream, kind) {
    var t = track(stream, kind || 'camera');
    return (t && t.getSettings) ? t.getSettings() : {};
  }

  function zoomRange(stream) {
    var t = track(stream, 'camera');
    var caps = (t && t.getCapabilities) ? t.getCapabilities() : {};
    return caps.zoom || null;
  }

  function setZoom(stream, value) {
    var z = zoomRange(stream);
    if (!z) return Promise.resolve();
    var v = Math.min(z.max, Math.max(z.min, value == null ? z.min : value));
    return track(stream, 'camera').applyConstraints({ advanced: [{ zoom: v }] }).catch(function () {});
  }

  function record(stream, opts) {
    if (!stream || !global.MediaRecorder) return null;
    var recorder, chunks = [];
    try { recorder = new global.MediaRecorder(stream); } catch (_) { return null; }
    recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
    try { recorder.start(); } catch (_) { return null; }
    var ended = null;
    return {
      state: function () { return recorder.state; },
      stop: function () {
        if (ended) return ended;
        ended = new Promise(function (resolve) {
          if (recorder.state === 'inactive') { resolve(null); return; }
          recorder.onstop = function () {
            resolve(new Blob(chunks, { type: recorder.mimeType || (opts && opts.type) || 'audio/webm' }));
          };
          recorder.stop();
        });
        return ended;
      },
    };
  }

  if (global.addEventListener) {
    global.addEventListener('pagehide', function () { open_.slice().forEach(close); });
  }

  global.WamaCapture = {
    available: available,
    open: open,
    close: close,
    devices: devices,
    permission: permission,
    trackSettings: trackSettings,
    zoomRange: zoomRange,
    setZoom: setZoom,
    record: record,
    explain: explain,
  };
})(window);
