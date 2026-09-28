/**
 * Calendrier de l'utilisateur — WAMA_MEMORY.md §9bis.1.
 *
 * Monte FullCalendar (vendorisé, MIT) sur `#wama-calendar` et lui fait charger ses événements
 * depuis `data-events-url` à chaque changement de fenêtre. Aucune donnée n'est écrite dans la
 * page : les événements sont DÉRIVÉS côté serveur (`common/services/calendar.py`).
 *
 * Clic sur un item : le MÊME passage inter-pages que le journal — `wama_focus_card` +
 * `wama_focus_select` en sessionStorage, puis la page de file de l'app (`wama-queue.js`
 * met la card au point et la sélectionne). Pas de volet réimplémenté ici.
 */
(function () {
    'use strict';

    var host = document.getElementById('wama-calendar');
    if (!host || !window.FullCalendar) { return; }

    var toggle = document.getElementById('wama-calendar-maintenance');
    var exportLink = document.getElementById('wama-calendar-ics');
    var VIEW_KEY = 'wama_calendar_view';

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
        if (p.app) { parts.push('App : ' + p.app); }
        if (p.status) { parts.push('État : ' + p.status); }
        if (p.reserves && p.reserves.length) {
            parts.push('Plage réservée (' + p.reserves.join(', ') + ')');
        }
        if (p.durationSource === 'measured') {
            parts.push(p.scope === 'instance' ? 'Durée mesurée sur les dernières exécutions'
                                              : 'Durée d\'exécution mesurée');
        } else if (p.durationSource === 'declared') {
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
            info.el.setAttribute('title', tooltipOf(info.event));
        },
        eventClick: function (info) {
            var p = info.event.extendedProps || {};
            if (!p.appUrl || p.itemId == null) { return; }   // maintenance : rien à ouvrir
            info.jsEvent.preventDefault();
            try {
                sessionStorage.setItem('wama_focus_card', '.wama-card[data-id="' + p.itemId + '"]');
                sessionStorage.setItem('wama_focus_select', '1');
            } catch (e) { /* stockage indisponible : on navigue quand même */ }
            window.location.href = p.appUrl;
        }
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

    calendar.render();
    window.WamaCalendar = calendar;
})();
