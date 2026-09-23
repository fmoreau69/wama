/**
 * WAMA — onglet « Évaluation » : la mesure d'un résultat contre sa RÉFÉRENCE.
 *
 * Rendu COMMUN (2026-09-23) de ce que rend l'endpoint commun
 * `/common/api/result-reference/<surface>/element/<pk>/` (`result_evaluation.item_evaluation`).
 * Il ne connaît aucune app : une surface qui DÉCLARE son évaluation (`register_evaluation`) et
 * pose l'onglet dans sa spec de détail (`result_tabs`, clé `evaluation`) n'a qu'à appeler
 * `WamaEvaluation.fill(surface, pk, container, tabButton)`.
 *
 * Ce qui est montré, et pourquoi : le TAUX ne suffit pas à juger une mesure. On montre aussi
 * ses comptes (substitutions, suppressions, insertions, longueurs) et ce que la lecture de la
 * référence a ÉCARTÉ (titres, en-têtes d'export) — sans quoi un taux surprenant ne s'explique
 * pas. Le geste pour poser ou retirer la référence est dans le menu de la card (« … »).
 */
(function (global) {
    'use strict';

    function escape(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    /** Même écriture que la ligne de lot rendue par le serveur (`floatformat:1`, locale du site) :
     *  la langue et le format d'affichage sont une décision ouverte (ROADMAP §10.A) — on ne la
     *  tranche pas ici en codant une virgule d'un côté seulement. */
    function percent(value) {
        if (value == null) return '—';
        return (value * 100).toFixed(1) + ' %';
    }

    var READING_LABELS = {
        format: 'Format lu',
        turns: 'Tours de parole lus',
        timed: 'Horodatée',
        windows: 'Extraits (fenêtres de temps)',
        outside_speech: 'Lignes écartées (hors parole)',
    };

    function readingRows(reading) {
        return Object.keys(READING_LABELS).filter(function (k) { return k in (reading || {}); })
            .map(function (k) {
                var v = reading[k];
                if (typeof v === 'boolean') v = v ? 'oui' : 'non';
                return '<dt>' + READING_LABELS[k] + '</dt><dd>' + escape(v) + '</dd>';
            }).join('');
    }

    /** Remplit `container` avec la mesure `item` ; rend false s'il n'y a rien à montrer. */
    function renderItem(container, item) {
        if (!container) return false;
        if (!item) { container.innerHTML = ''; return false; }
        if (item.pending) {
            container.innerHTML = '<p class="text-light py-3 mb-0"><i class="fas fa-hourglass-half"></i> '
                + 'Référence <strong>' + escape(item.reference_name) + '</strong> posée — '
                + 'la mesure suivra le prochain résultat.</p>';
            return true;
        }
        var rows = (item.metrics || []).map(function (m) {
            return '<tr><td>' + escape(m.label) + '</td>'
                + '<td class="wama-evaluation-rate">' + percent(m.value) + '</td>'
                + '<td>' + escape(m.substitutions) + '</td><td>' + escape(m.deletions) + '</td>'
                + '<td>' + escape(m.insertions) + '</td><td>' + escape(m.reference_length) + '</td>'
                + '<td>' + escape(m.hypothesis_length) + '</td></tr>';
        }).join('');
        var measured = item.measured_at ? new Date(item.measured_at).toLocaleString() : '';
        container.innerHTML =
            '<p class="text-light mb-2"><i class="fas fa-scale-balanced text-info"></i> '
            + '<strong>' + escape(item.model_label) + '</strong> comparé à '
            + '<strong>' + escape(item.reference_name) + '</strong></p>'
            + '<table class="wama-evaluation-metrics"><thead><tr>'
            + '<th>Mesure</th><th>Taux</th><th title="mots remplacés">Substitutions</th>'
            + '<th title="dits dans la référence, absents du résultat">Suppressions</th>'
            + '<th title="présents dans le résultat, absents de la référence">Insertions</th>'
            + '<th>Longueur de la référence</th><th>Longueur du résultat</th>'
            + '</tr></thead><tbody>' + rows + '</tbody></table>'
            + '<dl class="wama-evaluation-meta row mb-0">'
            + readingRows(item.reading)
            + '<dt>Modèle (clé catalogue)</dt><dd>' + escape(item.model_key || '—') + '</dd>'
            + '<dt>Protocole de mesure</dt><dd>' + escape(item.protocol)
            + ' — casse et ponctuation ignorées, hésitations comptées</dd>'
            + '<dt>Mesuré le</dt><dd>' + escape(measured) + '</dd>'
            + '</dl>';
        // `row` de Bootstrap : chaque paire dt/dd sur une ligne lisible.
        container.querySelectorAll('.wama-evaluation-meta dt').forEach(function (dt) {
            dt.className = 'col-sm-5';
        });
        container.querySelectorAll('.wama-evaluation-meta dd').forEach(function (dd) {
            dd.className = 'col-sm-7 mb-1';
        });
        return true;
    }

    /** Charge la mesure d'un élément et remplit l'onglet ; montre le bouton seulement s'il y a
     *  quelque chose à dire (même règle que les onglets Résumé et Cohérence). */
    function fill(surface, pk, container, tabButton) {
        if (tabButton) tabButton.style.display = 'none';
        return fetch('/common/api/result-reference/' + encodeURIComponent(surface)
                     + '/element/' + encodeURIComponent(pk) + '/', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                var shown = renderItem(container, d && d.item);
                if (tabButton) tabButton.style.display = shown ? '' : 'none';
                return shown;
            })
            .catch(function () { return false; });
    }

    global.WamaEvaluation = { renderItem: renderItem, fill: fill };
})(window);
