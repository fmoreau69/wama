/*
 * WamaAvatarPanel — l'avatar parlant de l'assistant dans le volet droit, sur TOUTE page.
 *
 * POURQUOI CETTE BRIQUE. `wama-avatar.js` sait RENDRE (three.js/TalkingHead greffé sur le
 * canal de parole `WamaApp.Speech`) ; il ne sait ni où il vit, ni s'il doit exister. Jusqu'au
 * 2026-09-22 ce savoir était dans `home.html` seul : conteneur, chargement au clic, repli — et
 * un état « affiché » qui ne survivait ni à un changement de page ni à un rechargement.
 * Ici tout est GLOBAL : le conteneur est rendu par `base.html` (`common/_assistant_avatar.html`),
 * la préférence est DURABLE côté serveur (brique `user_settings`, app `assistant`, clés
 * `avatar` et `avatar_collapsed`, enregistrées par `/api/ai-chat/settings/`), et cette brique
 * ne fait qu'appliquer l'état qu'elle lit dans les `data-*` du conteneur.
 *
 * CE QU'ELLE NE FAIT PAS : parler. La vocalisation reste à la surface qui a un texte à dire
 * (`home.html` → `/api/tts-kokoro/` → `WamaAvatar.speak`). Un avatar chargé mais silencieux
 * sur une page d'app est l'état NORMAL : il attend une surface d'assistant transversale.
 *
 * COÛT. Le module et le GLB (~6 Mo) ne sont importés que si l'avatar doit être VISIBLE
 * (préférence active, non replié, hors mode simplifié), après le rendu de la page
 * (`requestIdleCallback`). Replié = rien n'est chargé tant qu'on ne déplie pas. Le navigateur
 * met les assets en cache : la charge réseau est payée une fois.
 *
 * API (globale, comme WamaApp/WamaParams) :
 *   WamaAvatarPanel.isEnabled()        → la préférence courante
 *   WamaAvatarPanel.setEnabled(bool)   → affiche/masque ET mémorise (Promise)
 *   WamaAvatarPanel.toggleCollapsed()  → replie/déplie ET mémorise (Promise)
 *   WamaAvatarPanel.refresh()          → ré-applique l'état (après un changement de mode d'UI)
 */
(function (global) {
  'use strict';

  var section = null, canvas = null, status = null, body = null, collapseBtn = null;
  var config = {};
  var state = { enabled: false, collapsed: false };
  var loading = null;      // Promise du chargement du module — un seul chargement par page

  function csrfToken() {
    if (global.WamaApp && global.WamaApp.csrfToken) return global.WamaApp.csrfToken();
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  /** Mémorise côté serveur — même route que les réglages de l'assistant (modèle, curseur).
   *  Échec silencieux : la page reflète déjà le choix, le tour suivant relira le dernier
   *  réglage enregistré. */
  function persist(values) {
    if (!config.settingsUrl) return Promise.resolve();
    return fetch(config.settingsUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(values),
    }).catch(function () {});
  }

  function simpleMode() {
    return document.body.classList.contains('wama-simple');
  }

  function ensureLoaded() {
    if (loading) return loading;
    status.textContent = 'Chargement de l’avatar…';
    loading = import(config.moduleUrl)
      .then(function () {
        return global.WamaAvatar.init(canvas, { glbUrl: config.glbUrl, lang: config.lang });
      })
      .then(function () { status.textContent = ''; })
      .catch(function (e) {
        console.error('[WamaAvatarPanel] chargement impossible — la voix reste disponible', e);
        loading = null;                       // permet une nouvelle tentative au prochain dépli
        status.textContent = 'L’avatar n’a pas pu être chargé — la voix reste disponible.';
      });
    return loading;
  }

  /** Charge après le rendu de la page, jamais pendant : l'avatar est optionnel, la page non. */
  function loadWhenIdle() {
    var run = function () { if (state.enabled && !state.collapsed && !simpleMode()) ensureLoaded(); };
    if (global.requestIdleCallback) global.requestIdleCallback(run, { timeout: 2000 });
    else setTimeout(run, 300);
  }

  function render() {
    if (!section) return;
    section.style.display = state.enabled ? '' : 'none';
    // L'accordéon replie TOUT le corps (avatar + mini-chat) d'un coup (Fabien, 22/09).
    body.hidden = state.collapsed;
    var icon = collapseBtn.querySelector('i');
    if (icon) {
      icon.classList.toggle('fa-chevron-up', !state.collapsed);
      icon.classList.toggle('fa-chevron-down', state.collapsed);
    }
    collapseBtn.title = state.collapsed ? 'Déplier l’assistant' : 'Replier l’assistant';
    if (state.enabled && !state.collapsed) loadWhenIdle();
  }

  function mount() {
    if (section) return true;
    section = document.getElementById('assistant-avatar-section');
    if (!section) return false;
    canvas = document.getElementById('assistant-avatar');
    status = document.getElementById('avatar-status');
    body = document.getElementById('assistant-body') || canvas;
    collapseBtn = document.getElementById('avatar-collapse');
    config = {
      moduleUrl: section.dataset.module,
      glbUrl: section.dataset.glb,
      lang: section.dataset.lang || 'fr',
      settingsUrl: section.dataset.settingsUrl,
    };
    state.enabled = section.dataset.enabled === '1';
    state.collapsed = section.dataset.collapsed === '1';
    // La VOIX (brique commune) part du même réglage durable, rendu ici en data-*.
    if (global.WamaAssistantVoice) {
      global.WamaAssistantVoice.configure({ enabled: section.dataset.voice !== '0',
                                            lang: config.lang, settingsUrl: config.settingsUrl });
    }
    collapseBtn.addEventListener('click', function () { api.toggleCollapsed(); });
    render();
    return true;
  }

  var api = {
    isEnabled: function () { mount(); return state.enabled; },
    isCollapsed: function () { mount(); return state.collapsed; },
    setEnabled: function (on) {
      if (!mount()) return Promise.resolve();
      state.enabled = !!on;
      if (!state.enabled && global.WamaAvatar) global.WamaAvatar.stop();
      render();
      return persist({ avatar: state.enabled });
    },
    toggleCollapsed: function () {
      if (!mount()) return Promise.resolve();
      state.collapsed = !state.collapsed;
      render();
      return persist({ avatar_collapsed: state.collapsed });
    },
    refresh: function () { if (mount()) render(); },
  };

  // Le conteneur (dans l'<aside> de base.html) précède les scripts : montage immédiat, avec
  // repli sur DOMContentLoaded si la brique était chargée plus tôt dans la page.
  if (!mount()) document.addEventListener('DOMContentLoaded', mount);

  global.WamaAvatarPanel = api;
})(window);
