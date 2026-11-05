/*
 * WamaAssistantChat — LE chat de l'assistant, partout dans WAMA.
 *
 * POURQUOI UNE SEULE BRIQUE. Jusqu'au 2026-09-26 deux codes affichaient la MÊME conversation :
 * ~200 lignes écrites dans le gabarit de l'accueil, et cette brique pour le volet droit. Deux
 * rendus d'un seul fil, donc deux endroits où corriger une bulle, deux façons de vocaliser, et
 * la certitude qu'ils divergent. Demande de Fabien (26/09) : « une brique commune complète qui
 * conserve bien les améliorations pour la vocalisation, et la porter sur la page d'accueil ».
 *
 * DEUX DENSITÉS, UN SEUL COMPORTEMENT (`data-density`) :
 *   • `full`    — l'accueil : bulles larges, bouton « Écouter » par réponse,
 *                 étapes d'outils dépliables avec leur résultat, mot d'attente déclaré ;
 *   • `compact` — le volet droit : le même fil, en 330 px de large.
 * Le modèle qui a répondu s'affiche au pied de chaque réponse dans les deux (`markModel`).
 * Ce qui change est de l'APPARENCE. Le fil, les gardes, la voix et le flux sont identiques —
 * c'est précisément ce que deux implémentations ne pouvaient pas garantir.
 *
 * LE FLUX (levier 5, `WAMA_LLM §1bis`). Si `data-stream-url` est déclarée, le tour passe par
 * SSE : la réponse s'écrit au fur et à mesure, les étapes d'outils apparaissent dès qu'elles
 * sont jouées, et la VOIX commence à la première phrase achevée au lieu d'attendre la fin.
 * ⚠ Repli AUTOMATIQUE sur le POST classique si le navigateur ne sait pas lire un flux, si le
 * serveur répond autre chose, ou si la connexion casse en route : le tour synchrone reste le
 * chemin de référence, jamais une voie morte.
 *
 * LA VOCALISATION N'EST PAS ICI. Elle est dans `wama-assistant-voice.js`, qui appelle le
 * service TTS — lequel applique côté SERVEUR le nettoyage qui compte (retrait des emojis,
 * respirations sur les fins de ligne et les incises, tableaux aplatis : `views._clean_text_for_tts`
 * et `_rendre_audible`). Cette brique ne fait que LUI DONNER le texte, entier ou au fil du flux.
 */
(function (global) {
  'use strict';

  var INPUT_MAX_HEIGHT_PX = 96;
  //: Sans lecture vocale (voix coupée), délai avant d'ouvrir la page demandée (`open_page`) :
  //: le temps de lire la réponse — elle reste dans le fil, rechargé sur la page suivante.
  var NAVIGATE_DELAY_MS = 1500;

  /** Un chemin de CETTE instance (`/anonymizer/`) — jamais une adresse externe ni `//hôte` :
   *  une page ouverte par un résultat d'outil ne doit pas pouvoir quitter WAMA. */
  function isLocalPath(url) {
    return typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/'
      && url.charAt(1) !== '\\';
  }

  //: Icône par outil — confort de lecture des étapes. Un outil absent prend l'icône générique :
  //: la table n'a donc jamais besoin d'être exhaustive, et un outil neuf ne casse rien.
  var TOOL_ICONS = {
    list_user_files: '📂', add_to_anonymizer: '➕', start_anonymizer: '▶️',
    get_anonymizer_status: '📊', sam3_examples: '💡', create_image: '🎨',
    start_imager: '▶️', get_imager_status: '📊', add_to_enhancer: '✨',
    start_enhancer: '▶️', get_enhancer_status: '📊', add_to_audio_enhancer: '🎙️',
    start_audio_enhancer: '▶️', get_audio_enhancer_status: '📊', synthesize_text: '🗣️',
    start_synthesizer: '▶️', get_synthesizer_status: '📊', add_to_describer: '🔍',
    start_describer: '▶️', get_describer_status: '📊', add_to_transcriber: '🎤',
    start_transcriber: '▶️', get_transcriber_status: '📊', add_to_reader: '📄',
    start_reader: '▶️', get_reader_status: '📊', list_media_assets: '🗃️',
    get_media_asset_url: '🔗', charger_competence: '🎓', ask_claude_code: '🧑‍💻',
    find_user_files: '🔎', remember_fact: '🧠', open_page: '🧭',
  };

  function csrfToken() {
    if (global.WamaApp && global.WamaApp.csrfToken) return global.WamaApp.csrfToken();
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Sous-ensemble de Markdown, SÛR : on échappe d'abord, on enrichit ensuite, et seules les
  // adresses que le contrôle des liens de la réponse VÉRIFIE deviennent cliquables — http(s) et
  // fichiers `/media/` (2026-11-04 : le statut rend des adresses RELATIVES, que la réponse écrit
  // en `[📥 Télécharger](/media/…)` ; elles restaient en texte brut). Même motif que
  // `assistant_engine._URL_IN_TEXT`, qui retire du texte tout lien qu'aucun outil n'a donné ;
  // ni espace ni guillemet dans l'adresse : rien ne sort de l'attribut `href`.
  var LINK = /\[([^\]]+)\]\(((?:https?:\/\/|\/media\/)[^\s)\]>"'`]+)\)/g;
  function toHtml(text) {
    var h = escapeHtml(text);
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(LINK, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return h.replace(/\n/g, '<br>');
  }

  function Chat(root) {
    this.root = root;
    this.cfg = {
      density: root.dataset.density || 'compact',
      chatUrl: root.dataset.chatUrl,
      streamUrl: root.dataset.streamUrl || '',
      threadUrl: root.dataset.threadUrl || '',
      threadEl: root.dataset.threadEl || '',
      clearUrl: root.dataset.clearUrl || '',
      followUpsUrl: root.dataset.followUpsUrl || '',
      jobsUrl: root.dataset.jobsUrl || '',
      settingsUrl: root.dataset.settingsUrl || '',
      paramsScript: root.dataset.paramsScript || '',
      capsScript: root.dataset.capsScript || '',
      greeting: root.dataset.greeting || '',
      greetingHtml: root.dataset.greetingHtml || '',
      waiting: root.dataset.waiting || '',
      waitingAfterMs: parseInt(root.dataset.waitingAfterMs || '0', 10),
    };
    this.full = this.cfg.density === 'full';
    this.feed = root.querySelector('[data-assistant-feed]');
    this.input = root.querySelector('textarea');
    this.sendBtn = root.querySelector('[data-assistant-send]');
    this.statusEl = root.querySelector('[data-assistant-status]');
    this.waitTimer = null;
    this.deposits = [];               // fichiers GLISSÉS sur le chat, en attente d'envoi
    this.turn = Promise.resolve();    // le dernier tour lancé : le suivant l'attend (`send`)
    this.bind();
    this.loadThread();
  }

  Chat.prototype.bind = function () {
    var self = this;
    this.input.addEventListener('input', function () { self.autoGrow(); });
    this.input.addEventListener('keydown', function (e) {
      // Entrée envoie, Maj+Entrée saute une ligne — même geste dans les deux densités.
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); self.send(); }
    });
    this.sendBtn.addEventListener('click', function () { self.send(); });
    var form = this.root.querySelector('form');
    if (form) form.addEventListener('submit', function (e) { e.preventDefault(); self.send(); });
    if (global.WamaAssistantVoice) {
      global.WamaAssistantVoice.bindButton(this.root.querySelector('[data-assistant-voice]'));
    }
    var gear = this.root.querySelector('[data-assistant-settings]');
    if (gear) gear.addEventListener('click', function () { self.openSettings(); });
    this.bindDeposit();
    this.autoGrow();
  };

  // ── Réglages : la modale ⚙ COMMUNE des apps (2026-10-18) ──────────────────────
  // Le même schéma que la section « Paramètres » du volet de l'accueil (`assistant/params.py`,
  // contexte `item` pour la modale), lu par la route de réglages (GET : schéma, groupes,
  // valeurs) et enregistré par elle (POST du formulaire de `WamaParams.settingsModal`). C'est le
  // chemin du mode simplifié — volets masqués — et du mini-chat des autres pages, qui n'avait
  // aucun accès aux réglages. `wama-params.js` n'est pas global (chaque surface qui rend un
  // schéma le charge) : chargé ici à la première ouverture, par la plomberie commune
  // (`WamaApp.loadScript`).
  Chat.prototype.openSettings = function () {
    var url = this.cfg.settingsUrl;
    if (!url) return Promise.resolve(null);
    var ready = global.WamaParams ? Promise.resolve()
      : (this.cfg.paramsScript ? global.WamaApp.loadScript(this.cfg.paramsScript)
                               : Promise.reject(new Error('WamaParams')));
    // La règle des voix du champ « Voix » (`cap_from` en mode `voices`, 2026-10-28) : sans elle,
    // le champ offrirait la voix d'un moteur sous un autre. Son absence n'empêche pas la modale.
    var caps = (global.WamaModelCaps || !this.cfg.capsScript) ? Promise.resolve()
      : global.WamaApp.loadScript(this.cfg.capsScript).catch(function () {});
    return Promise.all([ready, caps]).then(function () {
      return fetch(url, { headers: { 'Accept': 'application/json' } });
    }).then(function (r) { return r.json(); }).then(function (d) {
      return global.WamaParams.settingsModal({
        id: 'Assistant', title: "Réglages de l'assistant", titleIcon: 'fa-gear',
        schema: d.schema, groups: d.groups, values: d.values, context: 'item',
        saveUrl: url, csrf: csrfToken(),
        // Le volet de l'accueil, s'il est rendu, se recale sur ce qui vient d'être enregistré.
        onSaved: function () {
          if (document.dispatchEvent && global.CustomEvent) {
            document.dispatchEvent(new CustomEvent('wama:assistant-settings'));
          }
        },
      });
    }).catch(function () {
      if (global.WamaApp && global.WamaApp.toast) global.WamaApp.toast('Réglages indisponibles', 'error');
    });
  };

  // ── Fichiers GLISSÉS sur le chat (2026-10-18, le geste de Discord) ───────────────────
  // Déposés dans l'espace de l'utilisateur par le geste PARTAGÉ (`WamaFM.upload` →
  // `/filemanager/api/upload/` → `enregistrer_fichier_utilisateur`, celui de Discord et de l'API),
  // montrés en pastilles sous la saisie, puis envoyés AVEC le message (ou seuls : le serveur fait
  // demander « Que puis-je en faire ? », `assistant_engine.message_with_deposits`). L'assistant
  // inspecte et propose : fichier de travail, de référence, lot, RAG…
  // Un fichier glissé depuis l'ARBRE de fichiers (volet gauche, mode normal) est déjà dans cet
  // espace : le chat se déclare cible de l'arbre (`data-fm-designate`) et reçoit son CHEMIN
  // (`filemanager:designate`) — rien n'est re-téléversé.
  // « JOINDRE » (2026-10-27, Fabien : sur un téléphone, « charger des fichiers via le bouton de
  // l'assistant, sans besoin de passer par le filemanager ou de faire un drag&drop ») : le
  // sélecteur du système — sur un téléphone, il propose aussi la galerie et l'appareil photo —,
  // puis le MÊME dépôt que le glisser. C'est ce qui rendait le mode simplifié nécessaire.
  Chat.prototype.bindDeposit = function () {
    var self = this;
    var root = this.root;
    var attach = root.querySelector('[data-assistant-attach]');
    if (attach) {
      var picker = document.createElement('input');
      picker.type = 'file';
      picker.multiple = true;
      picker.hidden = true;
      picker.setAttribute('data-assistant-picker', '');
      root.appendChild(picker);
      attach.addEventListener('click', function () { picker.click(); });
      picker.addEventListener('change', function () {
        var files = Array.prototype.slice.call(picker.files || []);
        picker.value = '';
        self.deposit(files);
      });
    }
    root.setAttribute('data-fm-designate', '');
    root.addEventListener('filemanager:designate', function (e) {
      self.designate((e.detail && e.detail.files) || []);
    });
    root.addEventListener('dragover', function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') === -1) return;
      e.preventDefault();
      root.classList.add('wama-assistant-dragover');
    });
    root.addEventListener('dragleave', function (e) {
      if (!root.contains(e.relatedTarget)) root.classList.remove('wama-assistant-dragover');
    });
    root.addEventListener('drop', function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
      e.preventDefault();
      root.classList.remove('wama-assistant-dragover');
      self.deposit(Array.prototype.slice.call(e.dataTransfer.files));
    });
  };

  Chat.prototype.deposit = function (files) {
    var self = this;
    if (!files.length || !global.WamaFM || !global.WamaFM.upload) return Promise.resolve([]);
    this.setStatus('Dépôt de ' + files.length + ' fichier(s)…');
    return global.WamaFM.upload(files, csrfToken()).then(function (d) {
      var uploaded = (d && d.uploaded) || [];
      uploaded.forEach(function (u) { self.deposits.push({ path: u.path, name: u.name }); });
      self.renderDeposits();
      self.setStatus(uploaded.length ? '' : ('Dépôt impossible : ' + ((d && d.error) || 'erreur')));
      self.input.focus();
      return uploaded;
    }).catch(function () { self.setStatus('Dépôt impossible : erreur réseau'); return []; });
  };

  /** Fichiers DÉSIGNÉS par leur chemin (`[{path, name?}]`, glissés depuis l'arbre). */
  Chat.prototype.designate = function (files) {
    var self = this;
    files.forEach(function (f) {
      if (!f || !f.path) return;
      if (self.deposits.some(function (d) { return d.path === f.path; })) return;
      self.deposits.push({ path: f.path, name: f.name || String(f.path).split('/').pop() });
    });
    this.renderDeposits();
    this.input.focus();
  };

  Chat.prototype.renderDeposits = function () {
    var self = this;
    if (!this.depositsEl) {
      this.depositsEl = document.createElement('div');
      this.depositsEl.className = 'wama-assistant-deposits';
      var row = this.input.parentNode;
      row.parentNode.insertBefore(this.depositsEl, row);
    }
    this.depositsEl.innerHTML = '';
    this.deposits.forEach(function (d, i) {
      var chip = document.createElement('span');
      chip.className = 'badge bg-secondary me-1 mb-1 wama-assistant-deposit';
      chip.title = d.path;
      chip.textContent = '📎 ' + d.name + ' ';
      var x = document.createElement('button');
      x.type = 'button';
      x.className = 'btn-close ms-1';
      x.style.fontSize = '.6em';
      x.title = 'Ne pas joindre';
      x.addEventListener('click', function () { self.deposits.splice(i, 1); self.renderDeposits(); });
      chip.appendChild(x);
      self.depositsEl.appendChild(chip);
    });
    this.depositsEl.hidden = !this.deposits.length;
  };

  Chat.prototype.autoGrow = function () {
    this.input.style.height = 'auto';
    var h = Math.min(this.input.scrollHeight, INPUT_MAX_HEIGHT_PX);
    this.input.style.height = h + 'px';
    this.input.style.overflowY = this.input.scrollHeight > INPUT_MAX_HEIGHT_PX ? 'auto' : 'hidden';
  };

  Chat.prototype.scrollToEnd = function () { this.feed.scrollTop = this.feed.scrollHeight; };

  Chat.prototype.setStatus = function (text) {
    if (this.statusEl) this.statusEl.textContent = text || '';
  };

  // ── Rendu ────────────────────────────────────────────────────────────────────
  Chat.prototype.bubble = function (content, role, model) {
    var wrap = document.createElement('div');
    wrap.className = 'wama-assistant-line wama-assistant-line-' + role;
    var bubble = document.createElement('div');
    bubble.className = 'wama-assistant-msg wama-assistant-msg-' + role;
    if (role === 'assistant') bubble.innerHTML = toHtml(content);
    else bubble.textContent = content;
    if (role === 'assistant') this.markModel(bubble, model);
    wrap.appendChild(bubble);
    // « Écouter » : un geste EXPLICITE, donc il lit même quand la voix est coupée.
    if (this.full && role === 'assistant') {
      var self = this;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm btn-link text-secondary p-0 ms-1 align-top';
      btn.title = 'Écouter';
      btn.innerHTML = '<i class="fas fa-volume-up" style="font-size:.8em"></i>';
      btn.addEventListener('click', function () {
        if (global.WamaAssistantVoice) {
          global.WamaAssistantVoice.speak(self.textOf(bubble), { force: true });
        }
      });
      wrap.appendChild(btn);
    }
    return wrap;
  };

  /** Le MODÈLE qui a répondu, au pied de la réponse — dans les DEUX densités (2026-10-30,
   *  Fabien : « il faut toujours indiquer le modèle utilisé »). Il n'était posé qu'en `full` : au
   *  volet droit, il ne restait que la ligne d'état, que le tour suivant écrase. Un seul geste
   *  pour la bulle rendue d'un bloc et pour celle que le flux a remplie. */
  Chat.prototype.markModel = function (bubble, model) {
    if (!model) return;
    var badge = document.createElement('div');
    badge.className = 'wama-assistant-model';
    badge.textContent = model;
    bubble.appendChild(badge);
  };

  /** Bulle d'ERREUR d'un tour. Le modèle CHOISI est saturé (2026-10-13) : le serveur PROPOSE le
   *  relais que le choix automatique prendrait (`fallback`) — un clic renvoie le même message
   *  avec ce modèle, pour ce message seul ; le réglage de l'utilisateur ne change pas. */
  Chat.prototype.errorBubble = function (result, message) {
    var line = this.bubble((result && result.error) || 'Erreur', 'error');
    var relay = result && result.fallback;
    var files = this.lastFiles || [];        // le relais renvoie aussi les fichiers déposés
    if (relay && relay.model_key && message) {
      var self = this;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm btn-outline-secondary ms-2 align-top';
      btn.textContent = 'Répondre avec ' + (relay.label || relay.model_key);
      btn.addEventListener('click', function () {
        btn.disabled = true;
        self.send({ message: message, model: relay.model_key, files: files });
      });
      line.appendChild(btn);
    }
    return line;
  };

  Chat.prototype.textOf = function (bubble) {
    var clone = bubble.cloneNode(true);
    var badge = clone.querySelector('.wama-assistant-model');
    if (badge) badge.remove();
    return clone.innerText || clone.textContent || '';
  };

  Chat.prototype.toolSteps = function (steps) {
    var div = document.createElement('div');
    div.className = 'wama-assistant-steps';
    var full = this.full;
    (steps || []).forEach(function (step) {
      var icon = TOOL_ICONS[step.tool] || '🔧';
      var failed = !!(step.result && step.result.error);
      if (!full) {
        var line = document.createElement('div');
        line.className = failed ? 'wama-assistant-step-ko' : '';
        line.textContent = icon + ' ' + step.tool + (failed ? ' ❌' : ' ✅');
        if (failed) line.title = String(step.result.error);
        div.appendChild(line);
        return;
      }
      // Densité pleine : le résultat est consultable, replié par défaut.
      var details = document.createElement('details');
      var summary = document.createElement('summary');
      summary.className = failed ? 'wama-assistant-step-ko' : '';
      summary.textContent = failed
        ? icon + ' ' + step.tool + ' → ❌ ' + step.result.error
        : icon + ' ' + step.tool + ' → ✅';
      var pre = document.createElement('pre');
      pre.textContent = JSON.stringify(step.result, null, 2);
      details.appendChild(summary);
      details.appendChild(pre);
      div.appendChild(details);
    });
    return div;
  };

  // ── Progression des JOBS lancés par un tour (2026-10-20) ─────────────────────
  // Demande de Fabien : « que l'utilisateur sache où en est le statut du job sans avoir à
  // redemander pour un traitement long ». Sous la réponse qui a lancé un traitement, la MÊME
  // lecture que sa card : le serveur rend l'état de chaque élément (`ai_chat_jobs` →
  // `tool_api.job_progress` : progression vivante, place dans la file GPU), la forme est celle du
  // bloc commun des cards (`common/_card_progress.html` : badge, barre, %, ETA), l'ETA vient de
  // `WamaEta` (débit observé, l'a priori de l'élément en amorce), et la boucle est `WamaApp.Poller`.
  // Le libellé et la couleur d'un état sont ceux du serveur (`WamaApp.statusLabel` / `statusBadge`,
  // `state_presentation`), la place dans la file GPU est la pastille même de la card
  // (`WamaSchedule.queueChip`) — rien n'est réécrit ici.
  // À la fin d'un élément, la relève de la cloche est demandée tout de suite : sa fin est racontée
  // par le chemin existant (`job_follow_ups`), une fois, au lieu d'attendre le tour de la cloche.
  var JOB_POLL_MS = 3000;
  var jobBlockSeq = 0;

  // Un LOT lancé se suit sous sa propre clé (`ai_chat_jobs` : `batch:famille:id`).
  function jobKey(job) { return (job.kind === 'batch' ? 'batch:' : '') + job.family + ':' + job.id; }

  function statusLabel(status) {
    return (global.WamaApp && global.WamaApp.statusLabel) ? global.WamaApp.statusLabel(status) : status;
  }

  function statusBadge(status) {
    return (global.WamaApp && global.WamaApp.statusBadge) ? global.WamaApp.statusBadge(status)
                                                          : 'bg-secondary';
  }

  Chat.prototype.jobRow = function (job) {
    var row = document.createElement('div');
    row.className = 'wama-assistant-job';
    row.dataset.jobKey = jobKey(job);
    row.innerHTML =
      '<div class="d-flex align-items-center gap-2 small">' +
      '<span class="badge status-badge"></span>' +
      '<span class="wama-assistant-job-name text-truncate"></span>' +
      '<small class="ms-auto progress-text"></small></div>' +
      '<div class="wama-progress-track mt-1"><div class="wama-progress-fill"></div></div>' +
      '<span class="wama-eta d-block small"></span>';
    row.querySelector('.wama-assistant-job-name').textContent = job.label || jobKey(job);
    this.paintJob(row, job);
    this.mountFaces(row, job);
    return row;
  };

  // LES FACES de l'élément sous sa barre (2026-10-28, Fabien : « intégrer la preview dans l'échange
  // avec l'assistant pour avoir le rendu preview — entrée/during/comparaison/sortie ») : l'afficheur
  // COMMUN du volet (`WamaMediaPreview.faceViewer`), à l'adresse d'aperçu commune que le serveur
  // joint à la ligne (`job_progress.preview_url`). Pendant le calcul, la face qui se construit ;
  // à la fin, la Sortie ; les onglets pour l'Entrée, Comparer, l'Évaluation ; double-clic : la
  // visionneuse. Rien sans adresse (famille hors de l'aperçu commun) ni sans la brique.
  Chat.prototype.mountFaces = function (row, job) {
    var P = global.WamaMediaPreview;
    if (!job.preview_url || !P || !P.faceViewer) return;
    var host = document.createElement('div');
    host.className = 'wcv3-preview wama-assistant-job-preview';
    row.appendChild(host);
    row._faces = facesIn(host, job.preview_url, function () { return row.dataset.jobStatus || ''; });
  };

  function facesIn(host, url, status, sequence) {
    var faces = global.WamaMediaPreview.faceViewer(host, url,
      { compact: true, status: status, sequence: sequence });
    // Au tour suivant : la ligne est bâtie AVANT d'entrer dans l'échange (`appendJobs`, fil
    // rechargé), et l'afficheur ne suit pas un hôte hors de la page — démarré ici, il montrait
    // l'Entrée sans jamais suivre la face Pendant (vu au geste sur la page servie, 2026-10-28).
    setTimeout(function () { faces.refresh(); }, 0);
    return faces;
  }

  // ── Un LOT lancé : UNE ligne, quelle que soit sa taille (2026-11-05) ────────────────────────
  // Fabien : « mettre à jour la barre de progression de lot et à la fin de chaque card fille
  // remplacer la preview par la suivante, en laissant un lien de téléchargement et d'accès aux
  // cards […] sans surcharger le fil ». Le serveur rend l'état de la card mère (`tool_api.
  // batch_progress` : la vue `batch_status` du bouton) ; la barre et les compteurs sont ceux de sa
  // card (`_batch_card.html` : terminées / total, ✓ ⟳ ✗), l'ETA est l'agrégat des filles par le
  // ticker de lot de `WamaEta` (`data-eta-ids`, celui de la card mère). UN seul aperçu, l'afficheur
  // de faces commun avec tous ses onglets : il suit la dernière fille finie ; ◀ ▶ et la liste
  // choisissent une fille (le suivi s'arrête, « Suivre » le reprend) ; la visionneuse (double-clic)
  // passe d'une fille à l'autre comme entre les cards d'une file. Le ZIP est le bouton ⬇ du lot.
  Chat.prototype.batchRow = function (job) {
    var self = this;
    var row = document.createElement('div');
    row.className = 'wama-assistant-job wama-assistant-batch';
    row.dataset.jobKey = jobKey(job);
    row.innerHTML =
      '<div class="d-flex align-items-center gap-2 small">' +
      '<span class="badge status-badge"></span>' +
      '<i class="fas fa-layer-group"></i>' +
      '<span class="wama-assistant-job-name text-truncate"></span>' +
      '<small class="ms-auto progress-text"></small></div>' +
      '<small class="d-block">' +
      '<span class="text-success" title="Terminés"><i class="fas fa-check"></i> <span data-batch-field="success_count"></span></span>' +
      '<span class="text-warning ms-1" title="En cours" data-batch-show="running_count"><i class="fas fa-spinner"></i> <span data-batch-field="running_count"></span></span>' +
      '<button type="button" class="btn btn-link btn-sm p-0 ms-1 text-danger wama-assistant-batch-failures" title="Échecs — voir le premier" data-batch-show="failure_count"><i class="fas fa-times"></i> <span data-batch-field="failure_count"></span></button>' +
      '<span class="text-body-secondary"> / <span data-batch-field="total"></span></span></small>' +
      '<div class="wama-progress-track mt-1"><div class="wama-progress-fill"></div></div>' +
      '<span class="wama-eta d-block small"></span>' +
      '<div class="d-flex align-items-center gap-1 mt-1 wama-assistant-batch-nav">' +
      '<button type="button" class="btn btn-sm btn-link p-0" data-batch-step="-1" title="Fille précédente"><i class="fas fa-chevron-left"></i></button>' +
      '<select class="form-select form-select-sm wama-assistant-batch-child" title="Choisir une card fille"></select>' +
      '<button type="button" class="btn btn-sm btn-link p-0" data-batch-step="1" title="Fille suivante"><i class="fas fa-chevron-right"></i></button>' +
      '<button type="button" class="btn btn-sm btn-link p-0 ms-1 wama-assistant-batch-follow" title="Montrer chaque fille à sa fin">Suivre</button></div>' +
      '<div class="wcv3-preview wama-assistant-job-preview"></div>' +
      '<div class="small mt-1 wama-assistant-batch-links">' +
      '<a class="wama-assistant-batch-zip" target="_blank" rel="noopener"><i class="fas fa-download"></i> Télécharger le lot (ZIP)</a>' +
      '<a class="ms-2 wama-assistant-batch-page" target="_blank" rel="noopener"><i class="fas fa-external-link-alt"></i> Ouvrir le lot dans l\'app</a></div>';
    row.querySelector('.wama-assistant-job-name').textContent = job.label || jobKey(job);
    row._batch = { family: job.family, follow: true, shown: null, children: {}, order: [] };
    var select = row.querySelector('.wama-assistant-batch-child');
    select.addEventListener('change', function () { self.showChild(row, Number(select.value), false); });
    Array.prototype.forEach.call(row.querySelectorAll('[data-batch-step]'), function (btn) {
      btn.addEventListener('click', function () {
        var order = row._batch.order;
        var next = order[order.indexOf(row._batch.shown) + Number(btn.dataset.batchStep)];
        if (next != null) self.showChild(row, next, false);
      });
    });
    row.querySelector('.wama-assistant-batch-follow').addEventListener('click', function () {
      row._batch.follow = true;
      self.showChild(row, latestChild(row._batch), true);
    });
    row.querySelector('.wama-assistant-batch-failures').addEventListener('click', function () {
      var failed = row._batch.order.filter(function (id) {
        var c = row._batch.children[id];
        return c.terminal && !c.ok;
      });
      if (failed.length) self.showChild(row, failed[0], false);
    });
    this.paintBatch(row, job);
    return row;
  };

  /** La fille à montrer quand on suit le lot : la dernière finie, sinon la première qui tourne,
   *  sinon la première — pure, gardée en V8. */
  function latestChild(batch) {
    if (batch.lastEnded != null) return batch.lastEnded;
    var order = batch.order, children = batch.children;
    var ended = order.filter(function (id) { return children[id].terminal; });
    if (ended.length) return ended[ended.length - 1];
    var moving = order.filter(function (id) { return children[id].status === 'RUNNING'; });
    return moving.length ? moving[0] : (order.length ? order[0] : null);
  }

  /** Montre la fille `id` dans l'aperçu unique du lot. `auto` : par le suivi (il continue) ; sinon
   *  l'utilisateur a choisi, le suivi s'arrête. */
  Chat.prototype.showChild = function (row, id, auto) {
    var batch = row._batch, child = batch.children[id];
    if (!child) return;
    if (!auto) batch.follow = false;
    row.querySelector('.wama-assistant-batch-follow').hidden = batch.follow;
    var select = row.querySelector('.wama-assistant-batch-child');
    select.value = String(id);
    var at = batch.order.indexOf(id);
    row.querySelector('[data-batch-step="-1"]').disabled = at <= 0;
    row.querySelector('[data-batch-step="1"]').disabled = at >= batch.order.length - 1;
    if (batch.shown === id) return;
    batch.shown = id;
    var P = global.WamaMediaPreview;
    var host = row.querySelector('.wama-assistant-job-preview');
    if (row._faces) row._faces.stop();
    if (P && P.releaseMedia) P.releaseMedia(host);
    host.innerHTML = '';
    row._faces = null;
    if (!child.preview_url || !P || !P.faceViewer) return;
    var self = this;
    row._faces = facesIn(host, child.preview_url,
      function () { return (batch.children[id] || {}).status || ''; },
      function () {
        return { urls: batch.order.map(function (k) { return batch.children[k].preview_url; }),
                 index: batch.order.indexOf(id),
                 onMove: function (i) { self.showChild(row, batch.order[i], false); } };
      });
  };

  /** Peint le lot ; rend vrai quand il vient de finir (plus rien n'y bouge). */
  Chat.prototype.paintBatch = function (row, job) {
    var batch = row._batch, counts = job.counts || {};
    var badge = row.querySelector('.status-badge');
    badge.className = 'badge status-badge ' + statusBadge(job.status);
    badge.textContent = statusLabel(job.status);
    row.querySelector('.progress-text').textContent = (counts.success || 0) + '/' + (job.total || 0);
    // Les repères de la card mère (`_batch_card.html` : `data-batch-field` / `data-batch-show`),
    // remplis des comptes de `batch_status` (`counts.success`…).
    ['success', 'running', 'failure'].forEach(function (key) {
      row.querySelector('[data-batch-field="' + key + '_count"]').textContent = counts[key] || 0;
    });
    row.querySelector('[data-batch-field="total"]').textContent = job.total || 0;
    Array.prototype.forEach.call(row.querySelectorAll('[data-batch-show]'), function (el) {
      el.hidden = !counts[el.dataset.batchShow.replace(/_count$/, '')];
    });
    var fill = row.querySelector('.wama-progress-fill');
    fill.style.width = Math.max(0, Math.min(100, job.progress || 0)) + '%';
    fill.classList.toggle('active', !job.terminal);
    fill.classList.toggle('is-frozen', !!(job.terminal && counts.failure));
    // Les filles : leur état, leurs ETA (le ticker de lot de `WamaEta` les agrège), la liste.
    var select = row.querySelector('.wama-assistant-batch-child');
    var shownId = batch.shown;
    var shownBefore = shownId != null ? (batch.children[shownId] || {}).status : null;
    var ended = null, ids = [];
    batch.order = (job.items || []).map(function (child) {
      var before = batch.children[child.id];
      if (before && !before.terminal && child.terminal) ended = child.id;
      batch.children[child.id] = child;
      var etaId = 'chat:' + batch.family + ':' + child.id;
      ids.push(etaId);
      if (global.WamaEta) global.WamaEta.update(etaId, { progress: child.progress, status: child.status });
      return child.id;
    });
    if (ended != null) batch.lastEnded = ended;
    var eta = row.querySelector('.wama-eta');
    eta.dataset.etaIds = job.terminal ? '' : ids.join(',');
    if (job.terminal) eta.textContent = '';
    select.innerHTML = '';
    batch.order.forEach(function (id) {
      var option = document.createElement('option');
      option.value = String(id);
      option.textContent = batch.children[id].label + ' · ' + statusLabel(batch.children[id].status);
      select.appendChild(option);
    });
    var zip = row.querySelector('.wama-assistant-batch-zip');
    zip.hidden = !job.download_url;
    if (job.download_url) zip.href = job.download_url;
    var page = row.querySelector('.wama-assistant-batch-page');
    page.hidden = !job.page_url;
    if (job.page_url) page.href = job.page_url;
    var wasTerminal = row.dataset.terminal === '1';
    row.dataset.terminal = job.terminal ? '1' : '';
    // L'aperçu : la dernière fille finie tant qu'on suit ; sinon la fille choisie, rejouée sur sa
    // face par défaut quand son état change (comme une ligne seule, `paintJob`).
    if (batch.follow) {
      this.showChild(row, latestChild(batch), true);
    } else if (batch.shown != null) {
      this.showChild(row, batch.shown, false);
    }
    // La même fille, dont l'état a changé (elle démarre, elle finit) : sa face par défaut rejouée.
    if (row._faces && shownId != null && batch.shown === shownId
        && (batch.children[shownId] || {}).status !== shownBefore) {
      row._faces.refresh();
    }
    return !!job.terminal && !wasTerminal;
  };

  /** Au-delà des lignes suivies d'un tour : combien d'autres, et leur file (2026-11-05). */
  Chat.prototype.moreRow = function (job) {
    var row = document.createElement('div');
    row.className = 'wama-assistant-job wama-assistant-more small';
    var link = document.createElement('a');
    link.href = job.page_url || '#';
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = '+ ' + job.count + ' autre' + (job.count > 1 ? 's' : '') + ' — ouvrir la file';
    row.appendChild(link);
    return row;
  };

  Chat.prototype.paintJob = function (row, job) {
    var pct = job.terminal && job.ok ? 100 : Math.max(0, Math.min(100, job.progress || 0));
    var badge = row.querySelector('.status-badge');
    badge.className = 'badge status-badge ' + statusBadge(job.status);
    badge.textContent = statusLabel(job.status);
    // Un élément qui ATTEND : la pastille « En file » de sa card (place, début et fin prévus).
    var oldChip = row.querySelector('.wama-queue-chip');
    if (oldChip) oldChip.remove();
    // Même règle que la card (`WamaSchedule.decorate`) : une entrée `queued`, jamais `running`.
    if (!job.terminal && job.queue && job.queue.state === 'queued' && global.WamaSchedule
        && global.WamaSchedule.queueChip) {
      row.appendChild(global.WamaSchedule.queueChip(job.queue));
    }
    row.querySelector('.progress-text').textContent = pct + '%';
    var fill = row.querySelector('.wama-progress-fill');
    fill.style.width = pct + '%';
    fill.classList.toggle('active', job.status === 'RUNNING');
    fill.classList.toggle('is-frozen', job.status === 'FAILURE');
    var eta = row.querySelector('.wama-eta');
    if (global.WamaEta && eta) {
      var id = 'chat:' + jobKey(job);
      var est = global.WamaEta.update(id, { progress: pct, status: job.status,
                                           seedSeconds: job.estimated_seconds });
      global.WamaEta.render(eta, est);
      if (job.terminal) global.WamaEta.reset(id);
    }
    row.dataset.terminal = job.terminal ? '1' : '';
    // L'état que lisent les faces ; tout CHANGEMENT d'état rejoue leur face par défaut — en cours :
    // Pendant suivi ; fini : la Sortie, même pour une app qui ne publie rien pendant le calcul (son
    // suiveur s'arrête alors sans annoncer de fin). `refresh` arrête d'abord le suiveur : une fois.
    var before = row.dataset.jobStatus;
    row.dataset.jobStatus = job.status || '';
    if (row._faces && before !== undefined && before !== row.dataset.jobStatus) row._faces.refresh();
  };

  /** Le bloc de suivi d'une réponse : une ligne par élément lancé, en cours ou déjà fini (sa
   *  Sortie), une par LOT lancé (`batchRow`), et « + N autres » au-delà des lignes suivies
   *  (`moreRow`). Rendu vide (`null`) sans job ou sans adresse de suivi ; suivi jusqu'à ce que
   *  tous soient finis — pas du tout s'ils le sont déjà. */
  Chat.prototype.jobsBlock = function (jobs) {
    if (!jobs || !jobs.length || !this.cfg.jobsUrl) return null;
    var self = this;
    var block = document.createElement('div');
    block.className = 'wama-assistant-jobs';
    block.dataset.jobsBlock = String(++jobBlockSeq);
    jobs.forEach(function (job) {
      block.appendChild(job.kind === 'batch' ? self.batchRow(job)
                        : job.kind === 'more' ? self.moreRow(job) : self.jobRow(job));
    });
    if (jobs.some(function (job) { return !job.terminal; })) this.followJobs(block);
    return block;
  };

  Chat.prototype.appendJobs = function (jobs) {
    var block = this.jobsBlock(jobs);
    if (block) { this.feed.appendChild(block); this.scrollToEnd(); }
  };

  Chat.prototype.followJobs = function (block) {
    if (!global.WamaApp || !global.WamaApp.Poller) return;
    var self = this;
    this.jobBlocks = this.jobBlocks || {};
    this.jobBlocks[block.dataset.jobsBlock] = block;
    if (!this.jobPoller) {
      this.jobPoller = new global.WamaApp.Poller({
        interval: JOB_POLL_MS,
        request: function (id) {
          var target = self.jobBlocks[id];
          var keys = Array.prototype.map.call(
            target ? target.querySelectorAll('[data-job-key]') : [],
            function (row) { return row.dataset.jobKey; });
          return fetch(self.cfg.jobsUrl + '?items=' + encodeURIComponent(keys.join(',')),
                       { headers: { Accept: 'application/json' } })
            .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
        },
        onData: function (id, data) { self.updateJobs(id, (data && data.jobs) || []); },
      });
    }
    this.jobPoller.start(block.dataset.jobsBlock);
  };

  Chat.prototype.updateJobs = function (id, jobs) {
    var block = this.jobBlocks && this.jobBlocks[id];
    // Bloc retiré (fil effacé, rechargé) : plus rien à suivre.
    if (!block || !block.isConnected) { this.stopJobs(id); return; }
    var self = this, ended = false, seen = {};
    jobs.forEach(function (job) {
      var row = block.querySelector('[data-job-key="' + jobKey(job) + '"]');
      if (!row) return;
      seen[jobKey(job)] = true;
      if (row._batch) {
        if (self.paintBatch(row, job)) ended = true;      // un lot se raconte à SA fin
        return;
      }
      var wasTerminal = row.dataset.terminal === '1';
      self.paintJob(row, job);
      if (job.terminal && !wasTerminal) ended = true;
    });
    // Un élément que le serveur ne rend plus (supprimé entre-temps) : sa ligne s'arrête, et le dit.
    Array.prototype.forEach.call(block.querySelectorAll('[data-job-key]:not([data-terminal="1"])'),
      function (row) {
        if (seen[row.dataset.jobKey]) return;
        row.dataset.terminal = '1';
        var badge = row.querySelector('.status-badge');
        badge.className = 'badge status-badge bg-secondary';
        badge.textContent = 'Introuvable';
        row.querySelector('.wama-progress-fill').classList.remove('active');
      });
    var running = block.querySelectorAll('[data-job-key]:not([data-terminal="1"])').length;
    if (!running) this.stopJobs(id);
    // Une fin : la relève de la cloche tout de suite (la notification s'écrit en fin de tâche).
    if (ended && global.WamaApp && global.WamaApp.checkNotifications) {
      setTimeout(function () { global.WamaApp.checkNotifications(); }, 1500);
    }
  };

  Chat.prototype.stopJobs = function (id) {
    if (this.jobPoller) this.jobPoller.stop(id);
    if (this.jobBlocks) delete this.jobBlocks[id];
  };

  Chat.prototype.stopAllJobs = function () {
    if (this.jobPoller) this.jobPoller.stopAll();
    this.jobBlocks = {};
  };

  /** L'accueil DÉCLARÉ. Un `<template>` plutôt qu'un attribut : le message de bienvenue est
   *  rendu par le serveur (il VARIE selon l'état de connexion) et peut contenir des liens ;
   *  le faire transiter par un attribut `data-` imposerait un double échappement fragile. */
  Chat.prototype.showGreeting = function () {
    var empty = document.createElement('div');
    empty.className = 'wama-assistant-empty';
    var modele = this.root.querySelector('template[data-assistant-greeting]');
    if (modele) empty.appendChild(modele.content.cloneNode(true));
    else empty.textContent = this.cfg.greeting || 'Posez une question à l’assistant.';
    this.feed.appendChild(empty);
  };

  Chat.prototype.dropGreeting = function () {
    var placeholder = this.feed.querySelector('.wama-assistant-empty');
    if (placeholder) placeholder.remove();
  };

  Chat.prototype.render = function (entries) {
    var self = this;
    this.stopAllJobs();
    this.feed.innerHTML = '';
    var lastModel = null;
    (entries || []).forEach(function (entry) {
      if (entry.type === 'tool_steps') self.feed.appendChild(self.toolSteps(entry.steps));
      else if (entry.type === 'user') self.feed.appendChild(self.bubble(entry.content, 'user'));
      else if (entry.type === 'assistant') {
        self.feed.appendChild(self.bubble(entry.content, 'assistant', entry.model));
        // Un traitement lancé par cette réponse (`_chat_thread`) : sa barre, ou sa Sortie s'il est fini.
        var block = self.jobsBlock(entry.jobs);
        if (block) self.feed.appendChild(block);
        lastModel = entry.model || lastModel;
      } else if (entry.type === 'error') self.feed.appendChild(self.bubble(entry.content, 'error'));
    });
    if (!entries || !entries.length) this.showGreeting();
    if (lastModel) this.setStatus(lastModel);
    this.scrollToEnd();
  };

  Chat.prototype.loadThread = function () {
    var self = this;
    // L'accueil porte déjà son fil dans la page (`json_script`) : ne pas le redemander.
    if (this.cfg.threadEl) {
      var el = document.getElementById(this.cfg.threadEl);
      try { this.render(el ? JSON.parse(el.textContent) : []); } catch (e) { this.render([]); }
      return;
    }
    if (!this.cfg.threadUrl) { this.render([]); return; }
    fetch(this.cfg.threadUrl, { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (d) { self.render(d.entries || []); })
      .catch(function () { self.render([]); });
  };

  Chat.prototype.clear = function () {
    var self = this;
    var done = function () {
      self.stopAllJobs();
      self.feed.innerHTML = ''; self.showGreeting(); self.setStatus('');
    };
    if (!this.cfg.clearUrl) { done(); return Promise.resolve(); }
    return fetch(this.cfg.clearUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken() } })
      .catch(function () {})          // l'écran se vide quand même ; le fil revient au rechargement
      .then(done);
  };

  // ── Attente ──────────────────────────────────────────────────────────────────
  // Le mot d'attente s'affiche APRÈS un délai, tous deux DÉCLARÉS côté serveur : un modèle qui
  // se charge met plusieurs secondes et l'attente ressemble alors à une panne ; l'afficher tout
  // de suite ferait clignoter l'interface quand la réponse arrive vite.
  Chat.prototype.startWaiting = function () {
    var self = this;
    this.dropGreeting();
    var wrap = document.createElement('div');
    wrap.className = 'wama-assistant-line wama-assistant-line-assistant';
    wrap.innerHTML = '<div class="wama-assistant-msg wama-assistant-msg-assistant '
      + 'wama-assistant-waiting"><i class="fas fa-spinner fa-spin"></i>'
      + '<span class="wama-assistant-wait-word"></span></div>';
    this.feed.appendChild(wrap);
    this.waitingEl = wrap;
    this.scrollToEnd();
    if (this.cfg.waiting && this.cfg.waitingAfterMs > 0) {
      clearTimeout(this.waitTimer);
      this.waitTimer = setTimeout(function () {
        var el = wrap.querySelector('.wama-assistant-wait-word');
        if (el) el.textContent = self.cfg.waiting;
      }, this.cfg.waitingAfterMs);
    }
  };

  // DÉCOMPTE (2026-10-04) : le serveur annonce l'attente APPRISE pour le modèle retenu (ETA
  // commune, moyenne par modèle et par matériel) ; on la décompte à la place du mot d'attente.
  // Rien n'est annoncé tant que rien n'a été mesuré, ni pour une attente trop courte.
  Chat.prototype.showCountdown = function (seconds) {
    var word = this.waitingEl && this.waitingEl.querySelector('.wama-assistant-wait-word');
    if (!word || !(seconds > 0)) return;
    clearTimeout(this.waitTimer);
    clearInterval(this.countdownTimer);
    var deadline = Date.now() + seconds * 1000;
    function draw() {
      var left = Math.ceil((deadline - Date.now()) / 1000);
      word.textContent = left > 0 ? 'Réponse dans environ ' + left + ' s' : 'Encore un instant…';
    }
    draw();
    this.countdownTimer = setInterval(draw, 1000);
  };

  Chat.prototype.stopWaiting = function () {
    clearTimeout(this.waitTimer);
    clearInterval(this.countdownTimer);
    if (this.waitingEl) { this.waitingEl.remove(); this.waitingEl = null; }
  };

  // ── Envoi ────────────────────────────────────────────────────────────────────
  // Rend la PROMESSE du tour (résolue quand la réponse est écrite — pas quand elle est dite) :
  // la conversation vocale (`wama-assistant-listen.js`) enchaîne dessus. Rien à envoyer →
  // promesse résolue tout de suite.
  // `relay` ({message, model}) : renvoi d'un message avec le modèle proposé (`errorBubble`) — la
  // saisie en cours n'est pas touchée.
  Chat.prototype.send = function (relay) {
    var message = relay ? relay.message : (this.input.value || '').trim();
    // Les fichiers déposés partent avec CE message (un relais garde ceux du message relayé).
    var files = relay ? (relay.files || []) : this.deposits.map(function (d) { return d.path; });
    if (!message && !files.length) return Promise.resolve(false);
    // La saisie reste ouverte pendant un tour (2026-10-27, Fabien : « quand l'assistant
    // réfléchit, je ne peux plus lui écrire ») : un message envoyé pendant qu'il réfléchit ou
    // parle le REPREND — le tour en cours s'interrompt et celui-ci le remplace, la règle de la
    // conversation vocale. Le nouveau tour attend que l'ancien se soit dénoué.
    if (this.isBusy()) this.abort();
    this.dropGreeting();
    var names = relay ? files.map(function (p) { return p.split('/').pop(); })
      : this.deposits.map(function (d) { return d.name; });
    var shown = names.length ? names.map(function (n) { return '📎 ' + n; }).join('\n') +
      (message ? '\n' + message : '') : message;
    this.feed.appendChild(this.bubble(shown, 'user'));
    if (!relay) {
      this.input.value = '';
      this.deposits = [];
      this.renderDeposits();
      this.autoGrow();
    }
    if (global.WamaAssistantVoice) global.WamaAssistantVoice.stop();
    var self = this;
    var model = relay ? relay.model : null;
    this.turn = Promise.resolve(this.turn).then(function () {
      self.lastFiles = files;
      self.busy(true);
      self.startWaiting();
      self.controller = global.AbortController ? new AbortController() : null;
      self.pendingPage = null;        // une page retenue par un tour précédent ne se suit plus
      return self.cfg.streamUrl ? self.sendStreaming(message, model)
        : self.sendBlocking(message, model);
    }).catch(function (e) {
      self.stopWaiting();
      self.pendingPage = null;        // tour interrompu ou en échec : on ne quitte pas la page
      // Interrompu par l'utilisateur (`abort`, il a repris la parole) : pas une panne.
      if (e && e.name === 'AbortError') return;
      self.feed.appendChild(self.bubble('Erreur réseau : ' + e.message, 'error'));
    }).then(function () {
      self.controller = null;
      self.busy(false);
      self.scrollToEnd();
      self.input.focus();
      return true;
    });
    return this.turn;
  };

  /** Interrompt le tour EN COURS (requête et lecture du flux) — l'utilisateur reprend la
   *  parole. Ce qui est déjà écrit reste affiché ; le serveur, lui, peut finir son tour et
   *  l'enregistrer au fil. */
  Chat.prototype.abort = function () {
    if (this.controller) { try { this.controller.abort(); } catch (_) {} }
  };

  Chat.prototype.isBusy = function () { return !!this.controller; };

  Chat.prototype.signal = function () {
    return this.controller ? this.controller.signal : undefined;
  };

  // Un tour en cours se DIT, il ne ferme rien : la saisie et l'envoi restent ouverts (`send`).
  Chat.prototype.busy = function (on) {
    this.root.setAttribute('aria-busy', on ? 'true' : 'false');
  };

  /** Un résultat d'outil peut demander à la SURFACE de faire quelque chose — replier ou déployer
   *  les volets (`fold_side_panels`, le repli commun `WamaPanels` ; il remplace le mode
   *  simplifié, retiré le 2026-10-27), ou OUVRIR UNE PAGE (`open_page`, 2026-10-11). Il vaut
   *  pour les deux densités, puisque c'est la même brique.
   *  ⚠ La page n'est pas ouverte ici : quitter la page couperait la réponse et sa voix. Elle
   *  est RETENUE, puis suivie quand le tour est écrit et dit (`followPendingPage`). */
  Chat.prototype.applyActions = function (steps) {
    var self = this;
    (steps || []).forEach(function (step) {
      var r = step && step.result;
      if (!r) return;
      if (r.action === 'panels' && global.WamaPanels) global.WamaPanels.setAll(!!r.folded);
      if (r.action === 'navigate' && isLocalPath(r.url)) self.pendingPage = r.url;
      if (r.action === 'hands') wishHands(!!r.on);
    });
  };

  /** Les MAINS (`use_hand_mode`, 2026-10-30) : l'icône ✋ de la barre, cliquée comme par
   *  l'utilisateur. Sans scène 3D sur la page l'icône est cachée : le souhait est RETENU dans
   *  l'onglet, et la scène ouverte ensuite (`open_page`) l'exauce une fois
   *  (`wama-hands-ui.js::registerHandTarget`, même clé). */
  var HANDS_WISH_KEY = 'wama.hands.wish';
  function wishHands(on) {
    var btn = document.getElementById('wamaHandsToggle');
    var item = btn && btn.closest('li');
    if (btn && item && !item.hidden) {
      if (btn.classList.contains('active') !== on) btn.click();
      return;
    }
    try { global.sessionStorage.setItem(HANDS_WISH_KEY, on ? 'on' : 'off'); } catch (e) { /* stockage refusé */ }
  }

  /** Suit la page retenue par `applyActions` une fois `spoken` résolue (la lecture vocale
   *  finie) ; sans voix, après un court délai pour laisser lire la réponse. Le fil serveur
   *  suit : le chat de la nouvelle page le recharge (`threadUrl`). */
  Chat.prototype.followPendingPage = function (spoken) {
    var url = this.pendingPage;
    this.pendingPage = null;
    if (!url) return;
    Promise.resolve(spoken).then(function (said) {
      setTimeout(function () { global.location.assign(url); }, said ? 0 : NAVIGATE_DELAY_MS);
    });
  };

  /** Corps d'un tour : le message, le modèle imposé pour lui seul s'il y en a un, et les
   *  fichiers déposés (chemins de l'espace de l'utilisateur, `message_with_deposits`). */
  function turnBody(message, model, files) {
    var body = { message: message };
    if (model) body.model = model;
    if (files && files.length) body.files = files;
    return JSON.stringify(body);
  }

  Chat.prototype.sendBlocking = function (message, model) {
    var self = this;
    return fetch(this.cfg.chatUrl, {
      method: 'POST', signal: this.signal(),
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: turnBody(message, model, this.lastFiles),
    }).then(function (r) {
      // ⚠ Brique commune : un 502/504 rend du HTML, et `response.json()` seul faisait lire
      // « Unexpected token '<' » à l'utilisateur au lieu de la raison (mesuré le 23/09).
      return (global.WamaApp && global.WamaApp.jsonOrExplain)
        ? global.WamaApp.jsonOrExplain(r) : r.json();
    }).then(function (data) {
      self.stopWaiting();
      if (data.success === false || (!data.success && data.error)) {
        self.feed.appendChild(self.errorBubble(data, message));
        self.tellTurnFollowUps(data.follow_ups);    // déjà racontées au fil : les montrer aussi
        return;
      }
      if (data.tool_steps && data.tool_steps.length) {
        self.feed.appendChild(self.toolSteps(data.tool_steps));
        self.applyActions(data.tool_steps);
      }
      self.feed.appendChild(self.bubble(data.response, 'assistant', data.model));
      self.appendJobs(data.jobs);
      if (data.model) self.setStatus(data.model);
      var said = [data.response].concat(self.tellTurnFollowUps(data.follow_ups));
      var spoken = global.WamaAssistantVoice ? global.WamaAssistantVoice.speak(said.join('\n\n')) : null;
      self.followPendingPage(spoken);
    });
  };

  /**
   * Tour EN FLUX. La bulle de réponse naît vide et se remplit ; la voix suit au fil des phrases.
   * ⚠ C'est l'événement `done` qui FAIT FOI : il porte la réponse complète et l'étiquette du
   * modèle, donc l'affichage se réaligne dessus. Sans ce recalage, un fragment perdu laisserait
   * à l'écran un texte différent de celui qui est enregistré dans le fil.
   */
  Chat.prototype.sendStreaming = function (message, model) {
    var self = this;
    if (!global.fetch || !global.ReadableStream || !global.TextDecoder) {
      return this.sendBlocking(message, model);
    }
    var voix = global.WamaAssistantVoice ? global.WamaAssistantVoice.speakStream() : null;
    var bulle = null, texte = '', recu = false;

    function ecrire(fragment) {
      if (!bulle) {
        self.stopWaiting();
        var ligne = self.bubble('', 'assistant');
        bulle = ligne.querySelector('.wama-assistant-msg');
        self.feed.appendChild(ligne);
      }
      texte += fragment;
      bulle.innerHTML = toHtml(texte);
      self.scrollToEnd();
      if (voix) voix.push(fragment);
    }

    return fetch(this.cfg.streamUrl, {
      method: 'POST', signal: this.signal(),
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: turnBody(message, model, this.lastFiles),
    }).then(function (resp) {
      var type = resp.headers.get('Content-Type') || '';
      // Le serveur n'a pas ouvert de flux (garde GPU, erreur, route absente) : on retombe sur
      // le tour synchrone plutôt que d'échouer — le repli est la raison d'être de ce test.
      if (!resp.ok || type.indexOf('text/event-stream') === -1) {
        if (voix) voix.end();
        return self.sendBlocking(message, model);
      }
      var lecteur = resp.body.getReader();
      var decodeur = new TextDecoder();
      var tampon = '';

      function traiter(bloc) {
        if (bloc.indexOf('data:') !== 0) return;             // commentaire SSE (keep-alive)
        var evt;
        try { evt = JSON.parse(bloc.slice(5).trim()); } catch (e) { return; }
        if (evt.type === 'delta') { recu = true; ecrire(evt.text || ''); }
        else if (evt.type === 'eta') { self.showCountdown(evt.seconds); }
        else if (evt.type === 'step') {
          self.stopWaiting();
          self.feed.insertBefore(self.toolSteps([evt.step]), bulle ? bulle.parentNode : null);
          self.applyActions([evt.step]);
          self.scrollToEnd();
        } else if (evt.type === 'done') {
          var r = evt.result || {};
          self.stopWaiting();
          if (r.error) {
            self.feed.appendChild(self.errorBubble(r, message));
            self.tellTurnFollowUps(r.follow_ups);   // déjà racontées au fil : les montrer aussi
            return;
          }
          if (!recu) {                                       // cloud : aucun fragment, tout arrive ici
            self.feed.appendChild(self.bubble(r.response, 'assistant', r.model));
            if (voix) voix.push(r.response || '');
          } else if (bulle) {
            texte = r.response || texte;
            bulle.innerHTML = toHtml(texte);
            self.markModel(bulle, r.model);
          }
          self.appendJobs(r.jobs);
          if (r.model) self.setStatus(r.model);
          self.tellTurnFollowUps(r.follow_ups).forEach(function (text) {
            if (voix) voix.push('\n\n' + text);
          });
        } else if (evt.type === 'error') {
          self.stopWaiting();
          self.feed.appendChild(self.bubble(evt.error || 'Erreur', 'error'));
        }
      }

      function pomper() {
        return lecteur.read().then(function (res) {
          if (res.done) return;
          tampon += decodeur.decode(res.value, { stream: true });
          var blocs = tampon.split('\n\n');
          tampon = blocs.pop();
          blocs.forEach(traiter);
          return pomper();
        });
      }
      return pomper().then(function () { self.followPendingPage(voix ? voix.end() : null); });
    }).catch(function (e) {
      // Un tour en ÉCHEC (réseau, flux rompu) ferme aussi son tour de parole : resté ouvert, la
      // voix se croyait encore audible et l'écoute de la conversation restait sourde (2026-10-27).
      if (voix) voix.end();
      throw e;
    });
  };

  /** Une FIN DE TÂCHE racontée dans le fil (2026-10-18) : rendue comme un tour de l'assistant —
   *  l'étape « statut » réellement jouée, puis la réponse. `speak` : ce chat la dit à voix haute
   *  (un seul des chats de la page), sauf si l'assistant parle ou répond déjà — une fin de tâche
   *  ne coupe pas une réponse en cours, elle reste écrite au fil. */
  Chat.prototype.tellFollowUp = function (followUp, speak) {
    this.dropGreeting();
    if (followUp.tool_steps && followUp.tool_steps.length) {
      this.feed.appendChild(this.toolSteps(followUp.tool_steps));
    }
    this.feed.appendChild(this.bubble(followUp.response, 'assistant', followUp.model));
    this.scrollToEnd();
    var voice = global.WamaAssistantVoice;
    if (speak && voice && !this.isBusy() && !voice.isSpeaking()) voice.speak(followUp.response);
  };

  /** Les fins de tâche ARRIVÉES pendant le tour, rendues avec sa réponse (`follow_ups`, la vue
   *  les a racontées au fil) : écrites à sa suite ; leurs textes sont rendus pour que la voix les
   *  dise APRÈS la réponse, dans la même lecture. */
  Chat.prototype.tellTurnFollowUps = function (followUps) {
    var self = this;
    return (followUps || []).map(function (followUp) {
      self.tellFollowUp(followUp, false);
      return followUp.response || '';
    });
  };

  // ── Fins de tâche : la cloche les relève, le fil les raconte (2026-10-18) ───────────────
  // Fabien : « l'assistant ne semble pas recevoir de trigger quand un travail est terminé, alors
  // qu'une notification arrive ». La cloche (`wama-app-base.js`) annonce chaque relève par
  // `wama:notifications` ; les fins de tâche y sont postées au serveur, qui raconte dans le fil
  // celles d'une tâche lancée DEPUIS ce fil (`common/services/job_follow_ups.py`, la brique de la
  // passerelle pour les canaux). Une seule demande par relève, quel que soit le nombre de chats.
  var JOB_NOTICE_KINDS = ['job_done', 'job_failed'];

  function onNotifications(evt) {
    var chat = null;
    for (var i = 0; i < instances.length; i++) {
      if (instances[i].cfg.followUpsUrl) { chat = instances[i]; break; }
    }
    if (!chat || !global.fetch) return;
    var items = (evt && evt.detail && evt.detail.items) || [];
    var ids = [];
    items.forEach(function (item) {
      if (item && JOB_NOTICE_KINDS.indexOf(item.kind) !== -1) ids.push(item.id);
    });
    if (!ids.length) return;
    fetch(chat.cfg.followUpsUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify({ ids: ids }),
    }).then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
      ((data && data.follow_ups) || []).forEach(function (followUp) {
        instances.forEach(function (c) { c.tellFollowUp(followUp, c === chat); });
      });
    }).catch(function () { /* hors ligne : le fil serveur l'a gardé, il se relira */ });
  }

  // ── Montage ──────────────────────────────────────────────────────────────────
  var instances = [];
  if (document.addEventListener) document.addEventListener('wama:notifications', onNotifications);

  function mount() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-wama-chat]'), function (root) {
      if (root._wamaChat) return;
      root._wamaChat = new Chat(root);
      instances.push(root._wamaChat);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();

  global.WamaAssistantChat = {
    mount: mount,
    instances: instances,
    first: function () { return instances[0] || null; },
    // Pour les tests V8 (`tests_assistant_reach`) : les gestes du prototype s'éprouvent sans DOM.
    _Chat: Chat,
    _toHtml: toHtml,
    _latestChild: latestChild,
  };
})(window);
