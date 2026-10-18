/**
 * Calendrier de l'utilisateur — WAMA_MEMORY.md §9bis.1.
 *
 * Monte FullCalendar (vendorisé, MIT) sur `#wama-calendar` et lui fait charger ses événements
 * depuis `data-events-url` à chaque changement de fenêtre. Aucune donnée n'est écrite dans la
 * page : les événements sont DÉRIVÉS côté serveur (`common/services/calendar.py`).
 *
 * Clic sur un ÉLÉMENT : sa card au volet droit, comme le JOURNAL (2026-10-18, Fabien) — l'inspecteur
 * commun (`WamaInspector`) remplit l'aperçu et la fiche par `data-preview-url`, et l'unique action
 * ouvre l'élément dans son app (`WamaQueue.openCard`, sélectionné à l'arrivée). Un lot, une purge
 * n'ont pas de card : leur clic ouvre la file de l'app, comme avant. Pas de volet réimplémenté ici.
 */
(function () {
    'use strict';

    var host = document.getElementById('wama-calendar');
    if (!host || !window.FullCalendar) { return; }

    var toggle = document.getElementById('wama-calendar-maintenance');
    var exportLink = document.getElementById('wama-calendar-ics');
    var VIEW_KEY = 'wama_calendar_view';
    // Un événement qui est la card d'un élément (et non un lot, une purge, la maintenance).
    var ITEM_CLASS = 'wama-cal-item';

    // La barre de filtrage commune (cible vivante) : ré-appliquée UNE fois par rendu, pas une
    // fois par événement — `eventDidMount` est appelé pour chacun.
    var filterBar = document.querySelector('[data-wama-filter-bar][data-cible-vivante]');
    var refreshPending = false;
    function scheduleFilterRefresh() {
        if (!filterBar || refreshPending || !window.WamaFilterBar) { return; }
        refreshPending = true;
        setTimeout(function () {
            refreshPending = false;
            WamaFilterBar.refresh(filterBar);
        }, 0);
    }

    function withMaintenance() {
        return !toggle || toggle.checked;
    }

    function storedView() {
        try { return localStorage.getItem(VIEW_KEY) || 'timeGridWeek'; } catch (e) { return 'timeGridWeek'; }
    }

    function syncExportLink(range) {
        if (!exportLink) { return; }
        var params = new URLSearchParams();
        if (range) {
            params.set('start', range.startStr);
            params.set('end', range.endStr);
        }
        if (!withMaintenance()) { params.set('maintenance', '0'); }
        var query = params.toString();
        exportLink.href = host.dataset.icsUrl + (query ? '?' + query : '');
    }

    function tooltipOf(event) {
        var p = event.extendedProps || {};
        var parts = [event.title];
        if (p.app) { parts.push('App : ' + (p.appLabel || p.app)); }
        if (p.status) { parts.push('État : ' + p.status); }
        if (p.running) {
            parts.push(p.durationSource === 'measured' ? 'En cours — fin prévue au débit observé'
                                                       : 'En cours — fin non estimable');
        }
        if (p.kind === 'expiry') { parts.push('Passage de la purge de rétention'); }
        if (p.queuePosition != null) {
            parts.push(p.queueState === 'running' || p.queuePosition === 0
                ? 'File GPU : en cours'
                : 'File GPU : ' + p.queuePosition + (p.queuePosition === 1 ? 're' : 'e') + ' en attente');
        }
        if (p.kind === 'batch') { parts.push('Création du lot'); }
        if (p.kind === 'install') {
            parts.push(p.installRunning ? 'Installation en cours' : (p.status === 'FAILURE'
                ? 'Échec' + (p.error ? ' : ' + p.error : '') : 'Terminée'));
            if (p.via) { parts.push('Demandée par : ' + p.via); }
        }
        if (p.reserves && p.reserves.length) {
            parts.push('Plage réservée (' + p.reserves.join(', ') + ')');
        }
        if (p.durationSource === 'measured') {
            parts.push(p.scope === 'instance' ? 'Durée mesurée sur les dernières exécutions'
                                              : 'Durée d\'exécution mesurée');
        } else if (p.durationSource === 'declared' && !p.kind && !p.running) {
            parts.push('Durée indicative (non mesurée)');
        }
        return parts.join('\n');
    }

    var calendar = new FullCalendar.Calendar(host, {
        locale: 'fr',
        initialView: storedView(),
        firstDay: 1,
        nowIndicator: true,
        height: 'auto',
        allDaySlot: false,          // aucun événement « journée entière » : tout est horodaté
        eventTimeFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
        slotLabelFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
        slotMinTime: '00:00:00',
        scrollTime: '07:00:00',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek'
        },
        events: function (info, success, failure) {
            var params = new URLSearchParams({ start: info.startStr, end: info.endStr });
            if (!withMaintenance()) { params.set('maintenance', '0'); }
            fetch(host.dataset.eventsUrl + '?' + params.toString(), { credentials: 'same-origin' })
                .then(function (r) {
                    if (!r.ok) { throw new Error('HTTP ' + r.status); }
                    return r.json();
                })
                .then(success)
                .catch(function (err) {
                    failure(err);
                    if (window.WamaApp && WamaApp.toast) {
                        WamaApp.toast('Calendrier indisponible : ' + err.message, 'danger');
                    }
                });
        },
        datesSet: function (info) {
            try { localStorage.setItem(VIEW_KEY, info.view.type); } catch (e) { /* mode privé */ }
            syncExportLink(info);
        },
        eventDidMount: function (info) {
            var p = info.event.extendedProps || {};
            info.el.setAttribute('title', tooltipOf(info.event));
            // Contrat de la barre de filtrage COMMUNE : facettes en `data-f-<clé>`, texte en
            // `data-f-text`. Les valeurs sont celles que la vue DÉCLARE (`calendar_view`).
            info.el.setAttribute('data-f-app', p.app || '');
            // Une couche de l'instance apportée par une app (`register_instance_layer`) se range
            // sous sa propre valeur ; le reste de l'instance, sous « Maintenance de WAMA ».
            info.el.setAttribute('data-f-nature', p.layer
                || (p.scope === 'instance' ? 'maintenance' : (p.nature || '')));
            info.el.setAttribute('data-f-statut', p.status || '');
            info.el.setAttribute('data-f-text', [info.event.title, p.app, p.appLabel, p.status].join(' '));
            // Un ÉLÉMENT porte le contrat de card de l'inspecteur, celui des cards du journal
            // (`_journal_card.html`) : `data-id`, `data-status` (face montrée), `data-preview-url`.
            if (p.previewUrl && p.itemId != null) {
                info.el.classList.add(ITEM_CLASS);
                info.el.setAttribute('data-id', String(p.itemId));
                info.el.setAttribute('data-app', p.app || '');
                info.el.setAttribute('data-status', p.status || '');
                info.el.setAttribute('data-app-url', p.appUrl || '');
                info.el.setAttribute('data-app-label', p.appLabel || p.app || '');
                info.el.setAttribute('data-preview-url', p.previewUrl);
            }
            scheduleFilterRefresh();
        },
        eventClick: function (info) {
            var p = info.event.extendedProps || {};
            if (!p.appUrl) { return; }                       // maintenance : rien à ouvrir
            info.jsEvent.preventDefault();
            if (inspector && info.el.classList.contains(ITEM_CLASS)) {
                // Un événement de grille est un lien (`<a>`), que l'inspecteur ne prend pas : on
                // le sélectionne ici. Ailleurs dans une ligne de la vue liste, son clic délégué
                // l'a déjà fait.
                if (info.jsEvent.target.closest('a')) { inspector.selectItem(String(p.itemId), info.el); }
                return;
            }
            if (window.WamaQueue) { WamaQueue.openCard(p.appUrl, p.itemId); }   // lot, purge : la file
        }
    });

    // L'inspecteur COMMUN sur la grille, comme sur la liste du journal : il délègue la sélection à
    // son conteneur, que FullCalendar peut redessiner librement.
    var inspector = window.WamaInspector ? WamaInspector.init({
        queueContainer: host,
        cardSelector: '.' + ITEM_CLASS,
        keepMediaSection: true,                      // l'invite tant que rien n'est cliqué
        showOnInspect: ['actions-section'],          // aucune action sans élément
        itemLabel: function (id) { return "l'élément #" + id; },
        renderItemActions: function (actionsHost, card) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm btn-outline-secondary';
            btn.innerHTML = '<i class="fas fa-arrow-right me-1"></i> Ouvrir dans ';
            btn.appendChild(document.createTextNode(card.dataset.appLabel || ''));
            btn.addEventListener('click', function () {
                if (window.WamaQueue) { WamaQueue.openCard(card.dataset.appUrl, card.dataset.id); }
            });
            actionsHost.appendChild(btn);
        },
    }) : null;
    // Entrée sur un élément sélectionné : l'ouvrir dans son app (`wama:card-activate`).
    host.addEventListener('wama:card-activate', function (e) {
        var card = e.target.closest && e.target.closest('.' + ITEM_CLASS);
        if (card && window.WamaQueue) { WamaQueue.openCard(card.dataset.appUrl, card.dataset.id); }
    });

    if (toggle) {
        toggle.addEventListener('change', function () {
            calendar.refetchEvents();
            syncExportLink(calendar.view ? {
                startStr: calendar.view.activeStart.toISOString(),
                endStr: calendar.view.activeEnd.toISOString()
            } : null);
        });
    }

    // ABONNEMENT : le lien à jeton, créé au premier clic, régénérable (= révocation).
    var subscribe = document.getElementById('wama-calendar-subscribe');
    var feedModal = document.getElementById('wama-calendar-feed-modal');
    function requestFeed(regenerate) {
        var body = new FormData();
        if (regenerate) { body.append('regenerate', '1'); }
        var token = (window.WamaApp && WamaApp.csrfToken) ? WamaApp.csrfToken() : '';
        return fetch(subscribe.dataset.feedUrl, {
            method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': token }, body: body,
        }).then(function (r) { return r.json(); }).then(function (res) {
            document.getElementById('wama-calendar-feed-url').value = res.url || '';
            return res;
        });
    }
    if (subscribe && feedModal && window.bootstrap) {
        subscribe.addEventListener('click', function () {
            requestFeed(false).then(function () {
                bootstrap.Modal.getOrCreateInstance(feedModal).show();
            });
        });
        document.getElementById('wama-calendar-feed-copy').addEventListener('click', function () {
            var input = document.getElementById('wama-calendar-feed-url');
            if (navigator.clipboard) { navigator.clipboard.writeText(input.value); }
            else { input.select(); document.execCommand('copy'); }
            if (window.WamaApp && WamaApp.toast) { WamaApp.toast('Lien copié', 'success'); }
        });
        document.getElementById('wama-calendar-feed-regenerate').addEventListener('click', function () {
            requestFeed(true).then(function () {
                if (window.WamaApp && WamaApp.toast) {
                    WamaApp.toast('Nouveau lien : l’ancien ne fonctionne plus', 'warning');
                }
            });
        });
    }

    calendar.render();
    window.WamaCalendar = calendar;
})();
