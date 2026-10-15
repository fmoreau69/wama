/**
 * WAMA Common — Media Preview : LA brique d'aperçu de WAMA, une seule pour toutes les surfaces.
 *
 * Ce qu'elle porte, et qui la tire (window.WamaMediaPreview) :
 *   • le RENDU EN LIGNE d'une face (`renderInline` : image, vidéo, lecteur audio commun, PDF, HTML
 *     isolé, texte, grille d'une sortie multiple) — l'aperçu DANS les cards (`hydrateCardPreviews`),
 *     le VOLET droit (`wama-inspector.js`), la fenêtre de sélection de la médiathèque
 *     (`media-picker.js`), la page du synthesizer ;
 *   • les FACES d'un élément : la bascule Entrée | <process> | Pendant | Comparer | Sortie
 *     (`sidesBar`, la MÊME au volet et dans la visionneuse), Comparer (`compareFaces` +
 *     `compareView`), la face Pendant suivie en direct (`followDuring`, `variantToggle`, `duringUrl`) ;
 *   • la VISIONNEUSE (modale `#wamaMediaPreviewModal`) et son PLEIN ÉCRAN — la modale agrandie pour
 *     un élément ; la surcouche image (`#wamaFullscreenOverlay`) ne sert qu'aux galeries sans élément ;
 *   • la NAVIGATION, une seule : une SÉQUENCE d'éléments (les cards de la file, les fichiers d'un
 *     dossier du gestionnaire, les éléments de la médiathèque) et, dans un élément, ses FICHIERS
 *     (les N images d'une génération). ←/→ (et les boutons ‹ ›) vont fichier par fichier puis à
 *     l'élément voisin ; ↑/↓ sautent d'élément en élément. La face regardée (Entrée, Sortie…) est
 *     gardée d'une card à l'autre.
 *
 * Jusqu'au 2026-10-13 la brique était en deux morceaux : le rendu en ligne, Comparer et la face
 * Pendant vivaient dans `wama-inspector.js` (la visionneuse les empruntait à `WamaInspector`), et le
 * volet RECOPIAIT la bascule des faces (sans Pendant). `WamaInspector` garde leurs anciens noms en
 * renvois vers ceux-ci (`renderInlinePreview`, `compareView`…) : aucun appelant ne casse.
 *
 * Gestes communs (délégués sur le document — ils survivent au re-rendu des cards) :
 *   • clic sur `.preview-media-link[data-preview-url]` → la visionneuse, sur l'ÉLÉMENT ;
 *   • double-clic sur `.wama-card-preview` → idem (une app peut ouvrir SON détail en écoutant
 *     `wama:card-expand` et en appelant preventDefault()).
 * Ouvert depuis une card, la séquence est celle des cards de sa file (filtre et onglet respectés) ;
 * refermée sur une autre card, la visionneuse la désigne (`wama:preview-card`) et le volet la
 * sélectionne.
 *
 * Appels directs : `showPreviewModal(data)` (une face seule), `showPreviewModalWithNav(data, items,
 * index)` (une liste de faces), `WamaMediaPreview.openSequence({count, index, load, data, onMove})`
 * (une liste chargée à la demande — le gestionnaire de fichiers), `WamaMediaPreview.openForCard(data,
 * card, fichier)`. Une face = le JSON de `common:unified_preview` : {name, url | content, mime_type,
 * files?, side?, sides?, duration?, resolution?, properties?}.
 */

(function() {
    'use strict';

    // SVG icons — pas de dépendance Font Awesome
    const _SVG_PREV  = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>`;
    const _SVG_NEXT  = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>`;
    const _SVG_CLOSE = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
    const _SVG_EXPAND = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>`;

    // L'emplacement DÉDIÉ des bascules (faces en onglets, vues) de la modale — AU-DESSUS de
    // l'aperçu depuis le 2026-10-14 (sous lui avant), hors de la zone qui défile, jamais superposé
    // au contenu (`_sidesSlot`). Masqué tant qu'il est vide ; sa mise en forme est dans la feuille.
    const SLOT_CLASS = 'wama-modal-sides-slot';
    const SLOT_STYLE = 'display:none;';

    /** Une card d'élément de la file (la card mère d'un lot n'en est pas une). */
    const CARD_SEL = '.wama-card[data-id]:not(.is-batch)';

    // La face montrée par la visionneuse (le payload ENTIER : une sortie multiple garde ses `files`).
    let currentPreviewData = null;

    // ── Navigation : UNE séquence d'éléments, et les fichiers de l'élément montré ──────────────
    // `_seq` = {count, index, load(i, face) → face|Promise, onMove(i, face)?, cards?, origin?}, ou
    // null (une face seule). `_sub` = le fichier montré d'une sortie multiple (`files`).
    let _seq = null;
    let _sub = 0;
    let _navToken = 0;      // une réponse arrivée après un pas plus récent est ignorée

    function init() {
        initMediaPreview();
        setupKeyboardHandlers();
        _watchCardPreviews();
    }

    function escapeHtml(text) {
        return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function _sepQS(u) { return u.indexOf('?') === -1 ? '?' : '&'; }

    /** L'adresse d'une FACE d'un élément (`?side=`). */
    function faceUrl(base, side) { return base + _sepQS(base) + 'side=' + side; }

    function _json(url) {
        return fetch(url).then(function (r) { return r.ok ? r.json() : null; });
    }

    /** L'adresse d'aperçu d'un élément, sans face ni vue (`?side=`, `&variant=`) — pure. */
    function _itemAddress(endpoint) {
        const parts = String(endpoint || '').split('?');
        const kept = (parts[1] || '').split('&').filter(function (p) {
            return p && !/^(side|variant)=/.test(p);
        });
        return parts[0] + (kept.length ? '?' + kept.join('&') : '');
    }

    /** La modale sait-elle montrer ce payload ? Un fichier (`url`) ou un TEXTE servi inline
     *  (`content`) — la clé que rend le serveur pour toute face texte (`preview_utils.file_face`,
     *  sortie `result_text`, entrée `source_text`) et que lit le volet. Pure (gardée en V8,
     *  `tests_preview_entry`). ⚠ La modale lisait `text_content` jusqu'au 2026-10-12 : toute face
     *  TEXTE ouverte d'une card (Describer, Reader, Transcriber) tombait sur « No media URL ». */
    function showable(data) {
        return !!(data && (data.url || typeof data.content === 'string'));
    }

    /** « N mots » d'un texte, '' s'il est vide — compté par la brique commune
     *  (`WamaApp.wordCount`, repli identique). Ce que portaient les onglets des modales de
     *  résultat du describer et du transcriber ; toute face TEXTE l'affiche (2026-10-13). Pure. */
    function wordsLabel(text) {
        const count = (window.WamaApp && window.WamaApp.wordCount)
            ? window.WamaApp.wordCount(String(text || ''))
            : String(text || '').trim().split(/\s+/).filter(Boolean).length;
        return count ? count + ' mot' + (count > 1 ? 's' : '') : '';
    }

    /** Le RAPPORT DE COHÉRENCE d'une face (`ProcessSpec.result_format='coherence'`, forme de
     *  `llm_utils.build_coherence_report`) en HTML : score coloré par son niveau, remarques,
     *  version proposée EN REGARD du texte vérifié — ce que montraient les modales propres du
     *  describer et du transcriber (2026-10-13 : « on ne doit rien perdre, on complète le
     *  commun »). `compact` (volet) : les deux textes l'un sous l'autre. Tout texte est échappé ;
     *  un niveau inconnu prend la couleur neutre. Pure (gardée en V8, `tests_pipeline_faces`). */
    function coherenceHtml(report, compact) {
        const r = report || {};
        const level = ['success', 'warning', 'danger'].indexOf(r.level) >= 0 ? r.level : 'secondary';
        const notes = (r.notes || []).map(function (note) {
            return '<li class="text-light small">' + escapeHtml(note) + '</li>';
        }).join('');
        const column = function (title, text, kind) {
            return '<div class="' + (compact ? 'mb-2' : 'col-md-6') + '"><div class="card wama-coherence-' + kind + '">' +
                '<div class="card-header py-1 small text-muted">' + title + '</div>' +
                '<div class="card-body p-2"><pre class="wama-coherence-text">' + escapeHtml(text) + '</pre></div></div></div>';
        };
        const sides = r.suggestion
            ? column('Texte original', r.original || '', 'original') + column('Correction proposée', r.suggestion, 'proposed')
            : '';
        return '<div class="wama-coherence">' +
            '<div class="d-flex align-items-center mb-2">' +
            '<span class="badge bg-' + level + (compact ? '' : ' fs-5') + ' me-3">' + escapeHtml(r.score) + '/100</span>' +
            '<span class="text-light">Score de cohérence</span></div>' +
            (notes ? '<ul class="mt-2">' + notes + '</ul>' : '') +
            (sides ? (compact ? '<div class="mt-2">' + sides + '</div>' : '<div class="row mt-3">' + sides + '</div>') : '') +
            '</div>';
    }

    /** Couleurs des locuteurs, attribuées dans l'ordre d'apparition — la palette de la modale du
     *  transcriber (2026-10-13). */
    const SPEAKER_COLORS = ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f',
                            '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac'];

    /** Des TOURS DE PAROLE (`ProcessSpec.result_format='segments'`, `[{speaker, time_range,
     *  text}]`) en HTML : le locuteur dans sa couleur, sa plage, ses mots — la diarisation de la
     *  modale du transcriber. `compact` (volet) : les mots sous le locuteur. Tout texte échappé.
     *  Pure (gardée en V8, `tests_pipeline_faces`). */
    function segmentsHtml(segments, compact) {
        const colors = {};
        let next = 0;
        return '<div class="wama-segments">' + (segments || []).map(function (s) {
            const who = String((s && s.speaker) || '');
            if (!(who in colors)) colors[who] = SPEAKER_COLORS[next++ % SPEAKER_COLORS.length];
            return '<div class="d-flex align-items-start mb-2 px-1' + (compact ? ' flex-column' : '') + '">' +
                '<div class="wama-segment-who"><span class="badge me-1" style="background-color:' + colors[who] +
                ';color:#fff;font-size:.75rem;">' + escapeHtml(who) + '</span>' +
                '<small class="text-muted">' + escapeHtml(s && s.time_range) + '</small></div>' +
                '<div class="' + (compact ? '' : 'ms-2 ') + 'text-light wama-segment-text">' +
                escapeHtml(s && s.text) + '</div></div>';
        }).join('') + '</div>';
    }

    /** Les TÉLÉCHARGEMENTS de l'élément (`sides.downloads` : les formats que l'app déclare,
     *  `preview_utils._downloads`) en liens — ceux du bouton ⬇ de la card (la modale du
     *  transcriber avait TXT et SRT, 2026-10-13). Pure (gardée en V8). */
    function downloadsHtml(downloads) {
        return (downloads || []).map(function (d) {
            return '<a class="btn btn-sm btn-outline-info py-0" href="' + escapeHtml(d.url) + '" download ' +
                'title="Télécharger ' + escapeHtml(d.label) + '"><i class="' + escapeHtml(d.icon) + '"></i> ' +
                escapeHtml(d.label) + '</a>';
        }).join('');
    }

    /** Le DESSIN d'une face à résultat structuré — rapport de cohérence, tours de parole,
     *  évaluation contre la référence (rendu commun `WamaEvaluation.renderItem`) — ou null :
     *  la face se lit alors comme son texte (`content`). */
    function _structured(data, compact) {
        const el = document.createElement('div');
        if (data && data.coherence && typeof data.coherence === 'object') {
            el.innerHTML = coherenceHtml(data.coherence, compact);
        } else if (data && Array.isArray(data.segments)) {
            el.innerHTML = segmentsHtml(data.segments, compact);
        } else if (data && data.evaluation && typeof data.evaluation === 'object' && window.WamaEvaluation) {
            if (!window.WamaEvaluation.renderItem(el, data.evaluation)) return null;
        } else {
            return null;
        }
        return el;
    }

    /** Le texte dont une face structurée compte les mots : la version proposée (sinon l'original)
     *  d'un rapport, les mots des tours ; '' pour une évaluation (des taux, pas un texte). */
    function _structuredWords(data) {
        if (data.coherence) return data.coherence.suggestion || data.coherence.original || '';
        if (Array.isArray(data.segments)) return data.segments.map(function (s) { return (s && s.text) || ''; }).join(' ');
        return '';
    }

    // ════════════════════════════════════════════════════════════════════════════════════════
    // RENDU EN LIGNE — cards, volet, fenêtre de sélection (déplacé de wama-inspector.js le 2026-10-13)
    // ════════════════════════════════════════════════════════════════════════════════════════

    // ── DENSITÉ d'un aperçu texte, DÉCLARÉE par l'hôte (2026-08-22) ───────────────────────
    // Un volet et une CARD n'ont pas la même densité : le volet peut dérouler 3000 caractères
    // dans un <pre> scrollable, une card veut un extrait NU de quelques centaines de signes.
    // Cette différence était jusqu'ici résolue en RÉÉCRIVANT l'extrait dans chaque gabarit —
    // describer 400 (.result-preview), reader 400 (.reader-preview + filtre compact_preview),
    // transcriber 160 (.wama-card-preview) : trois longueurs, trois classes, trois bouts de
    // markup pour un seul et même geste. L'hôte la DÉCLARE désormais, le commun la rend.
    //   data-preview-mode="excerpt"     → extrait nu (pas de <pre>, pas de légende)
    //   data-preview-max-chars="400"    → longueur, propre à la card
    // Absent = comportement d'AVANT, à l'identique (volet et adoptants du 18/08 intacts).
    const TEXT_MAX_PANEL = 3000, TEXT_MAX_CARD = 400;

    function _previewDensity(host) {
        const d = (host && host.dataset) || {};
        const mode = d.previewMode || 'rich';
        let max = parseInt(d.previewMaxChars, 10);
        if (!(max > 0)) max = (mode === 'excerpt') ? TEXT_MAX_CARD : TEXT_MAX_PANEL;
        return { mode: mode, max: max };
    }

    // Compactage pour extrait de card : syntaxe markdown retirée, blancs écrasés. MIROIR CLIENT
    // du filtre `compact_preview` de reader (reader_tags.py:8) — même traitement, mêmes étapes,
    // dans le même ordre. Il devient inutile dans les gabarits : un extrait rendu par le commun
    // ne peut plus dépendre d'un filtre que seul reader possède.
    function _compactText(t) {
        return String(t == null ? '' : t)
            .replace(/^#{1,6}\s+/gm, '')
            .replace(/\*{1,3}|_{1,3}/g, '')
            .replace(/^\s*[-*+]\s+/gm, '')
            .replace(/\|/g, ' ')
            .replace(/`+/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    // ── Sortie MULTIPLE : grille de vignettes (2026-08-22) ────────────────────────────────
    // Rend la clé canonique `result_files` (N fichiers issus d'UN traitement — imager génère N
    // images). Remplace les boucles d'<img> écrites par app. La liste vient de la DONNÉE, jamais
    // d'un balayage du DOM (imager collectait un sélecteur qui rendait 0, constaté 22/08).
    // Clic sur une vignette (2026-10-13) : la visionneuse de l'ÉLÉMENT, sur CE fichier — ses faces,
    // ses autres fichiers et les cards voisines au clavier ; sans élément (`_baseUrl`), la liste seule.
    function _renderPreviewGrid(host, data) {
        const files = data.files;
        host.innerHTML = '';
        const grid = document.createElement('div');
        grid.className = 'wama-preview-grid d-flex flex-wrap gap-2';
        files.forEach(function (f, i) {
            const mime = (f.mime_type || '').toLowerCase();
            let tile;
            if (mime.indexOf('video/') === 0) {
                tile = document.createElement('video');
                tile.src = f.url;
                tile.preload = 'metadata';
            } else {
                tile = document.createElement('img');
                tile.src = f.url;
                tile.alt = f.name || '';
            }
            tile.className = 'wama-preview-tile img-thumbnail bg-dark border-secondary';
            tile.title = f.name || '';
            tile.setAttribute('data-file-index', String(i));
            tile.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();          // ne pas voler le clic de sélection de la card
                if (data._baseUrl) openForCard(data, _cardOf(host) || _cardOfBase(data._baseUrl), i);
                else showPreviewModalWithNav(f, files, i);
            });
            grid.appendChild(tile);
        });
        host.appendChild(grid);
        _previewCaption(host, files.length + ' fichiers');
    }

    // ── La LECTURE suit le changement de face (2026-10-15, demande de Fabien) ────────────────
    // Passer de l'Entrée à la Détection puis à la Sortie d'une vidéo la faisait repartir de 0 ; et
    // l'audio d'un lecteur commun (hors DOM) continuait de jouer, invisible, une fois sa face
    // quittée. `takeClock` relève la position et l'état du média montré, puis l'ARRÊTE ;
    // `giveClock` les rend au média de la face d'arrivée — s'il y en a un, et pour le MÊME élément
    // seulement (`base`). Une face sans média (texte) garde l'horloge : y revenir reprend à la
    // position, en pause.

    /** Le média que montre `host` : la référence de Comparer, une vidéo ou un son du DOM, sinon
     *  l'identifiant du lecteur audio commun. */
    function _hostMedia(host) {
        if (!host || !host.querySelector) return null;
        const el = host.querySelector('.wama-compare-base') || host.querySelector('video, audio');
        if (el) return { el: el };
        const player = host.querySelector('.wama-audio-player[id^="audioPlayer_"]');
        return player ? { player: player.id.replace('audioPlayer_', '') } : null;
    }

    /** {base, time, playing} du média montré par `host` (il est arrêté), ou `previous` quand la
     *  face montrée n'en a pas (on revient d'un texte : l'horloge d'avant reste valable). */
    function takeClock(host, base, previous) {
        const m = _hostMedia(host);
        let media = m && m.el;
        if (m && m.player && window.WamaAudioPlayer && window.WamaAudioPlayer.current) {
            media = window.WamaAudioPlayer.current(m.player);
        }
        if (!media) return (previous && previous.base === base) ? Object.assign({}, previous, { playing: false }) : null;
        const clock = { base: base, time: media.currentTime || 0, playing: !media.paused && !media.ended };
        try { media.pause(); } catch (e) { /* déjà arrêté */ }
        return clock;
    }

    /** Rend l'horloge au média de la face montrée par `host`, s'il s'agit du même élément. */
    function giveClock(host, clock, base) {
        if (!clock || clock.base !== base || !(clock.time > 0 || clock.playing)) return;
        const m = _hostMedia(host);
        if (!m) return;
        if (m.player) {
            if (window.WamaAudioPlayer && window.WamaAudioPlayer.seek) {
                window.WamaAudioPlayer.seek(m.player, clock.time, clock.playing);
            }
            return;
        }
        const el = m.el;
        const apply = function () {
            try { el.currentTime = Math.min(clock.time, Math.max(0, (el.duration || clock.time) - 0.05)); } catch (e) {}
            if (clock.playing && el.play) el.play().catch(function () {});
        };
        if (el.readyState >= 1) apply();
        else el.addEventListener('loadedmetadata', apply, { once: true });
    }

    /** Arrête ce que joue `host` avant que son contenu soit remplacé : un lecteur audio commun vit
     *  HORS du DOM et jouait encore après avoir disparu (2026-10-15). */
    function _releaseHost(host) {
        if (!host || !host.querySelectorAll) return;
        host.querySelectorAll('video, audio').forEach(function (m) { try { m.pause(); } catch (e) {} });
        const player = host.querySelector('.wama-audio-player[id^="audioPlayer_"]');
        if (player && window.WamaAudioPlayer && window.WamaAudioPlayer.release
                && window.WamaAudioPlayer.current && window.WamaAudioPlayer.current(player.id.replace('audioPlayer_', ''))) {
            window.WamaAudioPlayer.release(player.id.replace('audioPlayer_', ''));
        }
    }

    // Rendu INLINE compact d'un aperçu média (≠ visionneuse). Données = JSON de
    // common:unified_preview {name, url, mime_type, …}. autoplay gated par le profil (jamais de
    // génération : on n'affiche que l'existant — CARD_DESIGN §10.6 / décision Fabien).
    function renderInline(host, data, autoplay) {
        if (!host) return;
        _releaseHost(host);
        // Collection AVANT l'aiguillage par mime : `files` décrit N sorties, `mime_type` ne décrit
        // que le représentant — trancher sur le mime ferait rendre une seule vignette.
        if (Array.isArray(data.files) && data.files.length > 1) {
            _renderPreviewGrid(host, data);
            return;
        }
        const mime = (data.mime_type || '').toLowerCase();
        const url = data.url || '';
        const name = escapeHtml(data.name || '');
        let media = '';
        const u = escapeHtml(url);  // sécurise l'attribut src/href (guillemets, noms spéciaux)
        if (mime.indexOf('image/') === 0) {
            media = '<img src="' + u + '" alt="" class="wama-inspector-preview-media" style="max-width:100%;max-height:220px;border-radius:6px;">';
        } else if (mime.indexOf('video/') === 0) {
            media = '<video src="' + u + '" controls ' + (autoplay ? 'autoplay muted ' : '') +
                'class="wama-inspector-preview-media" style="max-width:100%;max-height:220px;border-radius:6px;"></video>';
        } else if (mime.indexOf('audio/') === 0) {
            const player = window.WamaAudioPlayer;
            if (player && player.create) {
                // playerId : data-player-id de l'hôte si fourni (previews DANS les cards — N players
                // simultanés), repli 'insp' (volet inspecteur, hôte unique). 18/08.
                const pid = (host.dataset && host.dataset.playerId) || 'insp';
                host.innerHTML = '';
                try {
                    host.appendChild(player.create(url, pid, { autoplay: !!autoplay }));
                    // Pics serveur (common/utils/waveform.compute_peaks) : onde dessinée SANS décoder
                    // (fichiers longs) ou qui se CONSTRUIT (streaming « pendant »). setPeaks normalise
                    // l'échelle uint8→0-1. Additif : sans data.peaks, comportement inchangé.
                    if (Array.isArray(data.peaks) && data.peaks.length && player.setPeaks) {
                        player.setPeaks(pid, data.peaks);
                    }
                }
                catch (e) { host.innerHTML = '<audio src="' + u + '" controls ' + (autoplay ? 'autoplay ' : '') + 'style="width:100%;"></audio>'; }
                _previewCaption(host, name);
                return;
            }
            media = '<audio src="' + u + '" controls ' + (autoplay ? 'autoplay ' : '') + 'style="width:100%;"></audio>';
        } else if (mime === 'application/pdf') {
            media = '<embed src="' + u + '" type="application/pdf" style="width:100%;height:220px;border-radius:6px;">';
        } else if (mime === 'text/html') {
            // HTML : iframe SANDBOXÉE (pas de script, pas de navigation) — aperçu sûr. Dans une
            // CARD, le cadre ne prend pas les gestes (2026-10-13) : un double-clic tombait dans le
            // document encadré, qui ne le rend jamais à la page — l'aperçu ne s'agrandissait pas.
            const inert = host.classList && host.classList.contains('wama-card-preview')
                ? 'pointer-events:none;' : '';
            media = '<iframe src="' + u + '" sandbox class="wama-inspector-preview-media" ' +
                'style="width:100%;height:220px;border:0;background:#fff;border-radius:6px;' + inert + '"></iframe>';
        } else if (mime.indexOf('text/') === 0) {
            const density = _previewDensity(host);
            if (density.mode === 'excerpt') {
                // EXTRAIT de card : texte nu dans l'hôte lui-même — ni <pre> scrollable ni légende,
                // qui sont la densité du volet. On écrit dans l'hôte SANS toucher à ses classes ni à
                // ses attributs : c'est ce qui préserve les gestes déjà posés par les apps dessus
                // (reader = data-action="expand" + double-clic texte intégral, transcriber = double-clic
                // overlay via .wama-card-preview, describer = .result-preview où son polling écrit le
                // texte partiel pendant le RUN). Tous ces contrats portent sur l'ÉLÉMENT, aucun sur son
                // contenu — vérifié consommateur par consommateur avant le portage.
                const excerpt = function (t) {
                    const c = _compactText(t);
                    host.textContent = c ? (c.length > density.max ? c.slice(0, density.max) + ' …' : c) : '(vide)';
                };
                if (typeof data.content === 'string') {
                    excerpt(data.content);
                } else {
                    fetch(url).then(function (r) { return r.ok ? r.text() : ''; }).then(excerpt)
                        .catch(function () { /* best-effort : la card reste lisible sans extrait */ });
                }
                return;
            }
            // Résultat STRUCTURÉ (rapport de cohérence, tours de parole, évaluation) : son dessin, à
            // la densité du volet.
            const drawn = _structured(data, true);
            if (drawn) {
                host.innerHTML = '<div class="wama-inspector-preview"><div class="small text-start mb-1" ' +
                    'style="max-height:200px;overflow:auto;"></div></div>';
                host.querySelector('.wama-inspector-preview > div').appendChild(drawn);
                _previewCaption(host, name, data);
                return;
            }
            // Résultat MIS EN FORME par le serveur (`ProcessSpec.result_format`, 2026-10-13) : son
            // HTML neutralisé à la source, à la densité du volet.
            if (typeof data.html === 'string') {
                host.innerHTML = '<div class="wama-inspector-preview"><div class="small text-white-50 text-start mb-1 wama-result-formatted" ' +
                    'style="max-height:200px;overflow:auto;word-break:break-word;"></div></div>';
                host.querySelector('.wama-result-formatted').innerHTML = data.html;
                _previewCaption(host, name, data);
                return;
            }
            // Texte (plain/markdown/csv… ; ex. le PROMPT en entrée). Contenu inline si fourni
            // (data.content, cas prompt sans fichier), sinon chargé en async depuis l'URL.
            host.innerHTML = '<div class="wama-inspector-preview"><pre class="small text-white-50 text-start mb-1" ' +
                'style="max-height:200px;overflow:auto;white-space:pre-wrap;word-break:break-word;">…</pre></div>';
            const pre = host.querySelector('pre');
            const renderText = function (t) {
                if (pre) pre.textContent = (t && t.length > TEXT_MAX_PANEL) ? t.slice(0, TEXT_MAX_PANEL) + '\n…' : (t || '(vide)');
            };
            if (typeof data.content === 'string') {
                renderText(data.content);
            } else {
                fetch(url).then(function (r) { return r.ok ? r.text() : ''; }).then(renderText)
                    .catch(function () { if (pre) pre.textContent = '(aperçu indisponible)'; });
            }
            _previewCaption(host, name, data);
            return;
        } else {
            media = '<a href="' + u + '" target="_blank" rel="noopener" class="btn btn-sm btn-outline-info">' +
                '<i class="fas fa-external-link-alt"></i> Ouvrir</a>';
        }
        host.innerHTML = '<div class="wama-inspector-preview text-center">' + media + '</div>';
        // Une face qui porte une SURCOUCHE (la « Détection » de l'anonymizer, 2026-10-05) : les
        // détections dessinées par-dessus le média, à la frame courante.
        if (data.overlay && window.WamaPreviewOverlay) {
            window.WamaPreviewOverlay.attach(host.querySelector('.wama-inspector-preview-media'), data.overlay);
        }
        _previewCaption(host, name, data);
    }

    // Légende : nom + métadonnées DÉJÀ présentes dans la réponse unified_preview
    // (durée/résolution/propriétés) — sans nouvel endpoint.
    function _previewMeta(data) {
        const bits = [];
        if (data.duration) {
            const d = Math.round(data.duration), m = Math.floor(d / 60), s = d % 60;
            bits.push(m ? (m + ' min ' + (s < 10 ? '0' : '') + s + ' s') : (s + ' s'));
        }
        if (data.resolution) bits.push(String(data.resolution));
        if (data.properties) bits.push(String(data.properties));
        return bits;
    }

    function _previewCaption(host, name, data) {
        if (name) {
            const cap = document.createElement('small');
            cap.className = 'text-white-50 d-block text-truncate mt-1';
            cap.title = name; cap.textContent = name;
            host.appendChild(cap);
        }
        (data ? _previewMeta(data) : []).forEach(function (t) {
            const el = document.createElement('small');
            el.className = 'text-muted d-block text-truncate';
            el.style.fontSize = '.7rem';
            el.title = t; el.textContent = t;
            host.appendChild(el);
        });
    }

    // ── Preview de RÉSULTAT dans les CARDS — mécanisme COMMUN n°30 (18/08, décision Fabien) ─────
    // Une card déclare UNIQUEMENT un placeholder
    //   <div class="wcv3-preview" data-card-preview="<unified_preview>?side=output"
    //        data-player-id="<pk>"></div>
    // et l'hydrateur fetch le JSON unified_preview puis rend via le MÊME `renderInline` que le
    // volet (mime-driven). L'adresse de l'élément accompagne la face : une vignette de la grille
    // ouvre la visionneuse de l'élément.
    function hydrateCardPreviews(root) {
        const scope = root || document;
        const hosts = scope.querySelectorAll('[data-card-preview]:not([data-preview-hydrated])');
        Array.prototype.forEach.call(hosts, function (host) {
            host.setAttribute('data-preview-hydrated', '1');
            const url = host.getAttribute('data-card-preview');
            _json(url)
                .then(function (d) {
                    if (!showable(d)) return;
                    d._baseUrl = _itemAddress(url);
                    renderInline(host, d, false);
                })
                .catch(function () { /* best-effort : la card reste lisible sans preview */ });
        });
    }

    // Auto : au chargement + sur toute mutation de la page (refreshCard remplace des nœuds,
    // les batchs se déplient…). Le déclencheur regarde si les nœuds AJOUTÉS portent (ou
    // contiennent) un hôte de preview, au lieu de re-scanner tout le document à chaque lot : sur
    // une page à fort brassage DOM et SANS card (filemanager et son arbre jstree, polling des
    // stats), chaque ajout de nœud déclenchait un `querySelectorAll` sur tout le document, pour
    // rien (2026-08-20, préalable au chargement global demandé par Fabien).
    const PREVIEW_HOST = '[data-card-preview]';
    function _holdsHost(n) {
        if (!n || n.nodeType !== 1) return false;
        return (n.matches && n.matches(PREVIEW_HOST)) ||
               (n.querySelector && !!n.querySelector(PREVIEW_HOST));
    }
    function _watchCardPreviews() {
        hydrateCardPreviews(document);
        try {
            new MutationObserver(function (muts) {
                for (let i = 0; i < muts.length; i++) {
                    const added = muts[i].addedNodes;
                    for (let j = 0; added && j < added.length; j++) {
                        if (_holdsHost(added[j])) { hydrateCardPreviews(document); return; }
                    }
                }
            }).observe(document.body, { childList: true, subtree: true });
        } catch (e) { /* très vieux navigateur (ou banc V8) : hydratation au chargement seulement */ }
    }

    // ════════════════════════════════════════════════════════════════════════════════════════
    // FACES d'un élément — communes au volet et à la visionneuse
    // ════════════════════════════════════════════════════════════════════════════════════════

    /** Les boutons de la bascule des faces, dans l'ordre CHRONOLOGIQUE : Entrée → faces des process
     *  du pipeline (`preview_utils._process_faces` : l'anonymizer « Détection », le transcriber
     *  « Résumé »…) → Pendant → Comparer → Sortie → ce qui MESURE la Sortie (`sides.after` :
     *  l'Évaluation contre la référence, 2026-10-13). Chaque bouton n'existe que si sa face existe.
     *  Pure (gardée en V8, `tests_preview_navigation`). */
    function faceButtons(d) {
        const s = (d && d.sides) || {};
        const out = [];
        if (s.has_input) out.push({ key: 'input', label: 'Entrée', icon: 'fa-right-to-bracket' });
        (s.faces || []).forEach(function (f) {
            out.push({ key: f.key, label: f.label, icon: f.icon || 'fa-layer-group' });
        });
        if (s.has_during || (d && d.side === 'during')) out.push({ key: 'during', label: 'Pendant', icon: 'fa-hourglass-half' });
        if (s.comparable && s.has_output) out.push({ key: 'compare', label: 'Comparer', icon: 'fa-left-right' });
        if (s.has_output) out.push({ key: 'output', label: 'Sortie', icon: 'fa-flag-checkered' });
        (s.after || []).forEach(function (f) {
            out.push({ key: f.key, label: f.label, icon: f.icon || 'fa-layer-group' });
        });
        return out;
    }

    /** La bascule des FACES — UNE construction pour le volet et la visionneuse (le volet en avait
     *  sa copie, sans Pendant, jusqu'au 2026-10-13). `d` = la face montrée ; `opts.go(face)` ouvre
     *  une face, `opts.compare()` lance Comparer ; `opts.compact` = la densité du volet, sinon celle
     *  de la visionneuse. null quand il n'y a pas deux faces entre lesquelles basculer.
     *
     *  Des ONGLETS posés AU-DESSUS du contenu (2026-10-14, demande de Fabien : l'aspect des
     *  anciennes modales du transcriber, sans revenir en arrière) — une rangée de boutons sous
     *  l'aperçu, qui débordait du volet (« Résumé » coupé, mesuré à 280 px). Quand les noms ne
     *  tiennent pas, la rangée se RESSERRE (`_fitFaceTabs`) : les onglets inactifs gardent leur
     *  icône, l'onglet actif garde son nom, le survol (ou le focus) montre le nom d'une icône. */
    function sidesBar(d, opts) {
        opts = opts || {};
        const buttons = faceButtons(d);
        if (buttons.length < 2) return null;
        const bar = document.createElement('div');
        bar.className = 'wama-face-tabs wama-preview-sides' + (opts.compact ? ' is-compact' : '');
        bar.setAttribute('role', 'tablist');
        buttons.forEach(function (f) {
            const active = f.key === d.side;
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'wama-face-tab' + (active ? ' is-active' : '');
            b.setAttribute('role', 'tab');
            b.setAttribute('aria-selected', active ? 'true' : 'false');
            b.setAttribute('aria-label', f.label);
            b.setAttribute('data-label', f.label);
            b.setAttribute('data-side', f.key);
            b.innerHTML = '<i class="fas ' + f.icon + '" aria-hidden="true"></i>'
                + '<span class="wama-face-tab-label">' + escapeHtml(f.label) + '</span>';
            b.addEventListener('click', function () {
                if (f.key === 'compare') { if (opts.compare) opts.compare(); }
                else if (opts.go) opts.go(f.key);
            });
            bar.appendChild(b);
        });
        _fitFaceTabs(bar);
        return bar;
    }

    /** Resserre la rangée d'onglets quand leurs noms ne tiennent pas dans sa largeur, et la
     *  desserre quand ils tiennent de nouveau (volet élargi, modale à tout l'écran) : `is-condensed`
     *  = icônes seules sauf l'onglet actif ; `is-scrolling` = même ainsi elle déborde, elle défile
     *  (l'onglet actif amené en vue). Mesuré à chaque changement de LARGEUR seulement : basculer
     *  les classes ne change pas la largeur de la rangée, donc pas de boucle. */
    function _fitFaceTabs(bar) {
        if (!window.ResizeObserver) return;
        let width = -1;
        new window.ResizeObserver(function () {
            const w = bar.clientWidth;
            if (!w || w === width) return;
            width = w;
            bar.classList.remove('is-condensed', 'is-scrolling');
            if (bar.scrollWidth <= w + 1) return;
            bar.classList.add('is-condensed');
            if (bar.scrollWidth <= w + 1) return;
            bar.classList.add('is-scrolling');
            const on = bar.querySelector('.is-active');
            if (on) bar.scrollLeft = Math.max(0, on.offsetLeft - (w - on.offsetWidth) / 2);
        }).observe(bar);
    }

    /** Les deux faces de Comparer : la RÉFÉRENCE déclarée par le serveur (`compare_base`, la
     *  dernière face qui montre l'entrée), sinon l'entrée — contre la sortie. Rend une promesse de
     *  {din, dout, baseLabel}, ou null si l'une manque. Commune au volet et à la visionneuse. */
    function compareFaces(base, sides) {
        const s = sides || {};
        const baseSide = s.compare_base || 'input';
        const baseLabel = baseSide === 'input' ? 'Entrée'
            : ((s.faces || []).filter(function (f) { return f.key === baseSide; })[0] || {}).label || baseSide;
        return Promise.all([_json(faceUrl(base, baseSide)), _json(faceUrl(base, 'output'))])
            .then(function (a) {
                const din = a[0], dout = a[1];
                return (din && dout && din.url && dout.url) ? { din: din, dout: dout, baseLabel: baseLabel } : null;
            });
    }

    // ── Aperçu « pendant » : ses VARIANTES (2026-10-04) ──────────────────────────────────────
    // L'adresse de la face PENDANT, avec la vue choisie — pure (gardée en V8, `tests_cap_from_js`).
    function duringUrl(baseUrl, variant) {
        const u = baseUrl + (baseUrl.indexOf('?') === -1 ? '?' : '&') + 'side=during';
        return variant ? u + '&variant=' + encodeURIComponent(variant) : u;
    }

    // Le bouton [Détection | Floutage] : une entrée par vue publiée, l'active en plein.
    function variantToggle(variants, active, onPick) {
        const bar = document.createElement('div');
        bar.className = 'btn-group btn-group-sm wama-preview-variants mt-1 w-100';
        (variants || []).forEach(function (v) {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'btn py-0 px-2 flex-fill ' + (v.key === active ? 'btn-info' : 'btn-outline-info');
            b.textContent = v.label || v.key;
            b.setAttribute('data-variant', v.key);
            b.addEventListener('click', function () { onPick(v.key); });
            bar.appendChild(b);
        });
        return bar;
    }

    // ── Comparer : la SORTIE superposée à la RÉFÉRENCE, un curseur (2026-10-06) ──────────────
    // Commun au volet et à la modale (la modale juxtaposait deux vidéos ; Fabien : « une
    // superposition avec le slider comme dans le volet »). Images ou vidéos : le calque Sortie est
    // rogné depuis la gauche, les deux médias ont la même géométrie ; deux vidéos jouent ensemble
    // (la référence porte les contrôles) ; la référence porte sa surcouche (détections dessinées).
    function compareView(inD, outD, baseLabel) {
        const view = document.createElement('div');
        view.className = 'wama-compare-view';
        const wrap = document.createElement('div');
        wrap.className = 'wama-compare';
        // Les deux vidéos jouent ENSEMBLE : échappatoire de la lecture exclusive (wama-app-base).
        wrap.setAttribute('data-wama-multiplay', '');
        const isVideo = (inD.mime_type || '').indexOf('video/') === 0;
        const label = escapeHtml(baseLabel || 'Entrée');
        if (isVideo) {
            wrap.innerHTML =
                '<video class="wama-compare-base" src="' + escapeHtml(inD.url) + '" controls muted playsinline></video>' +
                // Le calque porte AUSSI les contrôles (2026-10-06) : il couvrait ceux de la référence sur
                // toute la partie rognée. Il ne capte aucun clic (`pointer-events: none`) et a la boîte
                // de la référence : on voit ses contrôles, on clique ceux de la référence, juste dessous ;
                // les deux vidéos étant synchronisées, l'état montré est le même.
                '<div class="wama-compare-top"><video src="' + escapeHtml(outD.url) + '" controls muted playsinline></video></div>' +
                '<span class="wama-compare-badge in">' + label + '</span>' +
                '<span class="wama-compare-badge out">Sortie</span>';
        } else {
            wrap.innerHTML =
                '<img class="wama-compare-base" src="' + escapeHtml(inD.url) + '" alt="' + label + '">' +
                '<div class="wama-compare-top"><img src="' + escapeHtml(outD.url) + '" alt="Sortie"></div>' +
                '<span class="wama-compare-badge in">' + label + '</span>' +
                '<span class="wama-compare-badge out">Sortie</span>';
        }
        view.appendChild(wrap);
        const range = document.createElement('input');
        range.type = 'range';
        range.min = 0; range.max = 100; range.value = 50;
        range.className = 'form-range wama-compare-range';
        view.appendChild(range);
        const base = wrap.querySelector('.wama-compare-base');
        const top = wrap.querySelector('.wama-compare-top');
        const topMedia = top.querySelector('img, video');
        function sync() {
            topMedia.style.width = base.clientWidth + 'px';
            topMedia.style.height = base.clientHeight + 'px';
            top.style.width = range.value + '%';
        }
        base.addEventListener(isVideo ? 'loadedmetadata' : 'load', sync);
        range.addEventListener('input', sync);
        // La taille de la référence change (plein écran, volet redimensionné) : le calque suit.
        if (window.ResizeObserver) new window.ResizeObserver(sync).observe(base);
        if (base.complete || (isVideo && base.readyState >= 1)) sync();
        const overlay = window.WamaPreviewOverlay;
        if (isVideo && overlay) overlay.syncVideos(base, topMedia);
        if (inD.overlay && overlay) {
            overlay.attach(base, inD.overlay);
            const holder = base.parentNode;
            holder.style.display = 'block';
            wrap.insertBefore(holder, wrap.firstChild);
        }
        return view;
    }

    // Une card est-elle EN COURS (son `data-status`) ? Le volet a la card ; la modale la retrouve
    // par l'adresse d'aperçu de l'élément (`data-preview-url` commence par elle).
    function isRunningCard(card) {
        const st = card && card.dataset && card.dataset.status;
        return st === 'RUNNING' || st === 'PROCESSING';
    }
    function cardOfPreview(baseUrl) {
        const all = document.querySelectorAll('[data-preview-url]');
        for (let i = 0; i < all.length; i++) {
            if ((all[i].getAttribute('data-preview-url') || '').indexOf(baseUrl) === 0) {
                return all[i].closest ? all[i].closest('[data-status]') : null;
            }
        }
        return null;
    }

    // ── Suivre la face PENDANT (2026-10-06) : UN suiveur, pour le volet ET la modale ──────────
    // Il interroge `?side=during` (vue choisie gardée), ne rend que ce qui a CHANGÉ (sans quoi un
    // média partiel recréait son lecteur et redémarrait toutes les 1,3 s — 2026-08-13), et dit la
    // fin : élément plus en cours (`isRunning`), ou partiels retirés après en avoir montré. Une app
    // qui ne publie rien : arrêt, sans fin annoncée. La modale en avait sa copie (2026-10-05,
    // retirée le lendemain à la question de Fabien « rien réinventé ? »).
    //   opts = { variant, isRunning(), onFrame(données), onEnd(données|null), every }
    //   rend { stop(), choose(variante) }
    function followDuring(baseUrl, opts) {
        opts = opts || {};
        const state = { variant: opts.variant || null, sig: '', stopped: false };
        // Boucle commune `WamaApp.Poller` : tour suivant après la réponse, pause en onglet caché.
        const poller = new window.WamaApp.Poller({
            urlTemplate: function () {
                if (opts.isRunning && !opts.isRunning()) { end(null); return null; }
                return duringUrl(baseUrl, state.variant);
            },
            interval: opts.every || 1300,
            immediate: true,
            maxFails: Infinity,
            // Une réponse HTTP en erreur dit « rien à suivre » (arrêt) ; une coupure réseau, un tour perdu.
            onError: function (id, err) { if (/^HTTP /.test((err && err.message) || '')) stop(); },
            onData: function (id, d) {
                if (state.stopped) return;
                if (!d || !d.sides || !d.sides.during_capable) { stop(); return; }   // ne publie rien
                // Rien de publié À CET INSTANT : pas encore, ou entre deux process (l'anonymizer retire
                // ses partiels entre la détection et le floutage). La fin se lit à l'état de l'élément
                // (`isRunning`) ; sans lui, la disparition des partiels après en avoir montré la dit.
                if (!d.sides.has_during) { if (!opts.isRunning && state.sig) end(d); return; }
                const sig = JSON.stringify([d.url || '', d.mime_type || '', (d.peaks || []).length,
                                            (typeof d.content === 'string') ? d.content.length : -1,
                                            d.variant || '', (d.variants || []).length]);
                if (sig === state.sig) return;
                state.sig = sig;
                if (opts.onFrame) opts.onFrame(d);
            },
        });
        function stop() { state.stopped = true; poller.stop('during'); }
        function end(d) { stop(); if (opts.onEnd) opts.onEnd(d || null); }
        poller.start('during');
        return {
            stop: stop,
            choose: function (variant) { state.variant = variant; state.sig = ''; poller.poke('during'); },
        };
    }

    // ════════════════════════════════════════════════════════════════════════════════════════
    // GESTES qui ouvrent la visionneuse
    // ════════════════════════════════════════════════════════════════════════════════════════

    /** La face d'un élément à son adresse (`endpoint`), son adresse d'ÉLÉMENT jointe (`_baseUrl`,
     *  sans elle la visionneuse n'a pas ses faces). Un élément EN COURS qui publie son aperçu : la
     *  face qui se construit. Rejette si l'aperçu est indisponible. */
    function _fetchItem(endpoint) {
        const base = _itemAddress(endpoint);
        return fetch(endpoint)
            .then(function (response) {
                if (!response.ok) throw new Error('Preview unavailable');
                return response.json();
            })
            .then(function (data) {
                data._baseUrl = base;
                if (data.sides && data.sides.has_during && data.side !== 'during') {
                    return _json(duringUrl(base, null)).then(function (d) {
                        if (d && d.side === 'during') { d._baseUrl = base; return d; }
                        return data;
                    });
                }
                return data;
            });
    }

    /**
     * Fetch a preview endpoint and show the viewer. Shared by the click trigger
     * (.preview-media-link) and the double-click trigger on card previews (.wama-card-preview).
     * Depuis une card : la séquence des cards de sa file (←/→, ↑/↓).
     */
    function openPreview(endpoint, indicatorEl) {
        if (!endpoint) {
            console.warn('[MediaPreview] No preview URL specified');
            return;
        }
        if (indicatorEl) indicatorEl.style.opacity = '0.5';
        _fetchItem(endpoint)
            .then(function (data) {
                const card = _cardOf(indicatorEl);
                if (card) openForCard(data, card, 0);
                else showPreviewModal(data);
            })
            .catch(function(err) {
                showPreviewError(err.message);
            })
            .finally(function() {
                if (indicatorEl) indicatorEl.style.opacity = '1';
            });
    }

    // ══ DÉLÉGATION, et non N liaisons — corrigé le 2026-09-06 ═══════════════════════════
    //
    // ⚠⚠ DÉFAUT RÉEL, trouvé par le scénario nocturne `<app>.processing` : l'aperçu MOURAIT
    // dès qu'une card était re-rendue. Les écouteurs étaient posés NŒUD PAR NŒUD à
    // `DOMContentLoaded` ; or le polling remplace la card entière quand son statut change —
    // c'est-à-dire précisément au moment où un résultat devient consultable. Le nouveau nœud
    // n'était lié par personne, et le double-clic ne faisait plus RIEN. Sans erreur, sans
    // journal.
    //
    // Trois apps s'en tiraient en rappelant `initMediaPreview()` après leur re-rendu
    // (anonymizer, enhancer, reader) ; **les neuf autres ne le faisaient pas**. Un mécanisme
    // dont la survie dépend de ce que chaque app pense à le ré-armer n'est pas un mécanisme
    // commun — c'est une convention, et une convention se perd. `queue-actions.js` documente
    // le remède en tête de fichier : UNE délégation posée sur le document, qui re-résout la
    // cible à chaque événement et se moque de savoir quand les nœuds ont été remplacés.
    //
    // Même famille que la sélection du drag&drop (`wama-queue-dnd.js::stateOf`), trouvée le
    // même jour : *tout ce qui s'accroche à une card doit survivre au rendu serveur.*
    let _delegated = false;

    function _delegate() {
        if (_delegated) return;
        _delegated = true;

        document.addEventListener('click', function (event) {
            const btn = event.target.closest('.preview-media-link');
            if (!btn) return;
            event.preventDefault();
            event.stopPropagation();
            openPreview(btn.dataset.previewUrl, btn);
        });

        document.addEventListener('dblclick', function (event) {
            const el = event.target.closest('.wama-card-preview');
            if (!el) return;
            event.preventDefault();
            event.stopPropagation();
            // Une VIGNETTE de la grille a déjà ouvert la visionneuse sur SON fichier au premier
            // clic : le double-clic ne la rouvre pas sur le premier.
            if (event.target.closest('.wama-preview-tile')) return;
            // L'app peut ouvrir SON détail (ex. modal de résultat transcriber)
            // en écoutant 'wama:card-expand' et en appelant preventDefault().
            const ev = new CustomEvent('wama:card-expand', {
                bubbles: true, cancelable: true,
                detail: { id: el.dataset.id || null, url: el.dataset.previewUrl || null, el: el }
            });
            const notHandled = el.dispatchEvent(ev);
            // Sinon (apps média) : overlay commun via data-preview-url.
            if (notHandled && el.dataset.previewUrl) {
                openPreview(el.dataset.previewUrl, el);
            }
        });
    }

    /**
     * Pose la délégation (une fois) et DÉCORE les aperçus présents (curseur, infobulle).
     *
     * Reste exporté et idempotent : trois apps l'appellent après leur re-rendu et doivent
     * continuer de fonctionner. Ce qu'elles gagnent est que ce rappel n'est plus NÉCESSAIRE
     * au comportement — il ne fait plus que rafraîchir la décoration.
     */
    function initMediaPreview() {
        _delegate();
        document.querySelectorAll('.wama-card-preview').forEach(function (el) {
            if (el.dataset.previewBound === '1') return;
            el.dataset.previewBound = '1';
            el.style.cursor = 'zoom-in';
            if (!el.title) el.title = 'Double-cliquez pour agrandir';
        });
    }

    // ════════════════════════════════════════════════════════════════════════════════════════
    // NAVIGATION — une séquence d'éléments, et les fichiers de l'élément montré
    // ════════════════════════════════════════════════════════════════════════════════════════

    /** Où mène un pas : `pos` = {index, count, sub, files} (élément montré sur `count`, fichier
     *  montré sur `files`), `dir` = ±1, `byCard` = d'élément en élément (↑/↓) plutôt que fichier par
     *  fichier (←/→). Rend {index, sub} — `sub` = -1 : le DERNIER fichier de l'élément d'arrivée
     *  (on recule : on arrive par la fin) —, ou null au bord. Sans séquence, ↑/↓ parcourent les
     *  fichiers. Pure (gardée en V8, `tests_preview_navigation`). */
    function stepTarget(pos, dir, byCard) {
        const count = pos.count || 1, files = pos.files || 1, sub = pos.sub || 0;
        if (count < 2) byCard = false;
        if (!byCard && files > 1) {
            const next = sub + dir;
            if (next >= 0 && next < files) return { index: pos.index, sub: next };
        }
        const index = pos.index + dir;
        if (count < 2 || index < 0 || index >= count) return null;
        return { index: index, sub: (dir < 0 && !byCard) ? -1 : 0 };
    }

    /** Les fichiers d'une sortie MULTIPLE montrés un par un (la visionneuse n'en montrait que le
     *  représentant). Comparer en porte aussi : la référence confrontée au fichier montré
     *  (2026-10-13 — Comparer prenait toujours le premier). */
    function _filesOf(data) {
        return (data && Array.isArray(data.files) && data.files.length > 1) ? data.files : null;
    }

    /** Le titre de Comparer : les DEUX fichiers confrontés (« source.jpg ↔ floutee.jpg ») — il
     *  gardait celui de la face d'avant, l'entrée ou « 4 fichiers » selon le chemin pris. Pure
     *  (gardée en V8, `tests_preview_navigation`). */
    function compareTitle(reference, output) {
        return ((reference && reference.name) || 'Entrée') + ' ↔ ' + ((output && output.name) || 'Sortie');
    }

    function _position() {
        const files = _filesOf(currentPreviewData);
        return { count: _seq ? _seq.count : 1, index: _seq ? _seq.index : 0,
                 sub: _sub, files: files ? files.length : 1 };
    }

    /** « 2 / 5 · fichier 3 / 4 » : l'élément dans la séquence, puis le fichier dans l'élément. */
    function _counterText(pos) {
        const parts = [];
        if (pos.count > 1) parts.push((pos.index + 1) + ' / ' + pos.count);
        if (pos.files > 1) parts.push((pos.count > 1 ? 'fichier ' : '') + (pos.sub + 1) + ' / ' + pos.files);
        return parts.join(' · ');
    }

    function _setSequence(seq) {
        _seq = (seq && seq.count > 1) ? seq : null;
        _navToken++;
    }

    /** La card d'un élément d'interface (un geste, l'hôte d'un aperçu), ou null. */
    function _cardOf(el) {
        return (el && el.closest) ? el.closest(CARD_SEL) : null;
    }

    /** La card d'un élément désigné par son adresse d'aperçu (le volet ne tient que l'adresse). */
    function _cardOfBase(base) {
        if (!base) return null;
        const all = document.querySelectorAll('[data-preview-url]');
        for (let i = 0; i < all.length; i++) {
            if ((all[i].getAttribute('data-preview-url') || '').indexOf(base) === 0) {
                const card = _cardOf(all[i]);
                if (card) return card;
            }
        }
        return null;
    }

    /** L'adresse d'aperçu d'une card : son aperçu de résultat, sinon son entrée. */
    function _cardPreviewUrl(card) {
        const el = card.querySelector('.wama-card-preview[data-preview-url]')
            || card.querySelector('.preview-media-link[data-preview-url]')
            || (card.matches('[data-preview-url]') ? card : card.querySelector('[data-preview-url]'));
        return el ? el.getAttribute('data-preview-url') : null;
    }

    /** Les cards entre lesquelles navigue la visionneuse ouverte depuis `card` : celles de sa file,
     *  dans l'ordre de la page, qui ont un aperçu — ni celles qu'un FILTRE écarte
     *  (`.wama-f-hors-filtre`, comme les flèches du volet), ni celles d'un autre ONGLET (l'imager
     *  et l'enhancer ont une file par domaine). Une card d'un lot REPLIÉ reste joignable. */
    function cardSequence(card) {
        const pane = card.closest('.tab-pane');
        const scope = pane || document;
        return Array.prototype.filter.call(scope.querySelectorAll(CARD_SEL), function (c) {
            if (c.closest('.wama-f-hors-filtre')) return false;
            if (!pane && c.closest('.tab-pane:not(.active)')) return false;
            return !!_cardPreviewUrl(c);
        });
    }

    /** La card telle qu'elle est À PRÉSENT dans la page (le suivi la remplace entière quand son
     *  état change — on la retrouve par son identifiant). */
    function _liveCard(card) {
        if (!card || card.isConnected) return card;
        return document.querySelector('.wama-card[data-id="' + card.dataset.id + '"]:not(.is-batch)') || card;
    }

    /** La face d'une card voisine : la MÊME que celle qu'on regardait (le serveur replie sur
     *  l'entrée ou la sortie si elle n'existe pas là) ; Comparer → la sortie, comparée ensuite ;
     *  Pendant → l'aperçu de la card, et sa face Pendant si elle en publie une. */
    function _loadCard(card, face) {
        const live = _liveCard(card);
        const url = live && _cardPreviewUrl(live);
        if (!url) return Promise.resolve(null);
        const base = _itemAddress(url);
        if (!face || face === 'during') return _fetchItem(url);
        return _json(faceUrl(base, face === 'compare' ? 'output' : face)).then(function (d) {
            if (!showable(d)) return _fetchItem(url);
            d._baseUrl = base;
            return d;
        });
    }

    /** La visionneuse d'un ÉLÉMENT ouvert depuis sa card : ←/→ et ↑/↓ passent aux cards voisines
     *  de la file ; `sub` = le fichier montré d'une sortie multiple. */
    function openForCard(data, card, sub) {
        const cards = card ? cardSequence(card) : [];
        const index = cards.indexOf(card);
        _setSequence(index >= 0 ? {
            count: cards.length, index: index, origin: index, cards: cards,
            load: function (i, face) { return _loadCard(cards[i], face); },
        } : null);
        _sub = sub || 0;
        _display(data);
    }

    /** Une séquence chargée À LA DEMANDE (le gestionnaire de fichiers : un aperçu par fichier du
     *  dossier). `load(i)` rend la face du i-ème, ou sa promesse ; `onMove(i, face)` dit à
     *  l'appelant où l'on est. `data` = la face déjà en main pour `index`, sinon chargée. */
    function openSequence(opts) {
        _setSequence({ count: opts.count, index: opts.index || 0, load: opts.load, onMove: opts.onMove });
        _sub = 0;
        if (opts.data) { _display(opts.data); return; }
        Promise.resolve(opts.load(opts.index || 0)).then(function (d) { if (d) _display(d); });
    }

    /** Une liste de faces déjà en main (médiathèque, fichiers d'une grille sans élément). */
    function showPreviewModalWithNav(data, items, currentIndex) {
        items = items || [];
        _setSequence({ count: items.length, index: (typeof currentIndex === 'number') ? currentIndex : 0,
                       load: function (i) { return items[i]; } });
        _sub = 0;
        _display(data);
    }

    /** Un pas de navigation : un autre fichier du même élément, ou l'élément voisin (chargé, la
     *  face regardée gardée). Une réponse arrivée après un pas plus récent est ignorée. */
    function _navigate(dir, byCard) {
        const target = stepTarget(_position(), dir, byCard);
        if (!target) return;
        const modal = document.getElementById('wamaMediaPreviewModal');
        if (!_seq || target.index === _seq.index) {
            _sub = target.sub;
            if (currentPreviewData && currentPreviewData.side === 'compare') {
                if (modal) _showCompare(modal, currentPreviewData);    // le fichier suivant, comparé
            } else if (currentPreviewData) {
                _display(currentPreviewData);
            }
            return;
        }
        const seq = _seq;
        const face = currentPreviewData && currentPreviewData.side;
        seq.index = target.index;
        if (modal) updateNavigationUI(modal);
        const token = ++_navToken;
        Promise.resolve(seq.load(target.index, face)).then(function (d) {
            if (token !== _navToken || seq !== _seq || !d) return;
            const n = Array.isArray(d.files) ? d.files.length : 0;
            _sub = target.sub < 0 ? Math.max(0, n - 1) : 0;
            if (seq.onMove) seq.onMove(target.index, d);
            _display(d);
            if (face === 'compare' && modal && d._baseUrl && d.sides && d.sides.comparable) {
                _modalCompare(modal, d._baseUrl, d.sides, _sub);      // le fichier d'arrivée, comparé
            }
        }).catch(function () { /* l'élément voisin n'a pas d'aperçu : on reste sur celui-ci */ });
    }

    /** Refermée sur une AUTRE card que celle d'où on l'a ouverte, la visionneuse la désigne : le
     *  volet la sélectionne (`wama-inspector.js`), et ses flèches reprennent de là. */
    function _announceCard() {
        if (!_seq || !_seq.cards || _seq.index === _seq.origin) return;
        const card = _liveCard(_seq.cards[_seq.index]);
        if (card && card.isConnected) {
            card.dispatchEvent(new CustomEvent('wama:preview-card',
                { bubbles: true, detail: { id: card.dataset.id } }));
        }
    }

    /**
     * Le clavier de la visionneuse et de la surcouche plein écran : ←/→ fichier par fichier puis
     * élément voisin, ↑/↓ d'élément en élément, Échap ferme la surcouche. SEUL écouteur de ces
     * touches quand la visionneuse est ouverte : le volet et la file s'abstiennent tant qu'une
     * modale est ouverte, et le gestionnaire de fichiers n'a plus le sien (il détournait la
     * navigation d'une card vers ses fichiers — mesuré le 2026-10-13).
     */
    const NAV_KEYS = {
        ArrowLeft: { dir: -1, byCard: false }, ArrowRight: { dir: 1, byCard: false },
        ArrowUp: { dir: -1, byCard: true }, ArrowDown: { dir: 1, byCard: true },
    };

    function setupKeyboardHandlers() {
        document.addEventListener('keydown', function(e) {
            const t = e.target;
            // Une saisie (champ, curseur de Comparer, zone éditable) garde ses touches.
            if (t && t.closest && t.closest('input, textarea, select, [contenteditable="true"]')) return;
            const overlay = document.getElementById('wamaFullscreenOverlay');
            const modal = document.getElementById('wamaMediaPreviewModal');
            if (!overlay && !(modal && modal.classList.contains('show'))) return;
            if (overlay && e.key === 'Escape') {
                e.preventDefault();
                closeFullscreen();
                return;
            }
            const key = NAV_KEYS[e.key];
            if (!key) return;
            e.preventDefault();
            _navigate(key.dir, key.byCard);
        });
    }

    // ════════════════════════════════════════════════════════════════════════════════════════
    // VISIONNEUSE
    // ════════════════════════════════════════════════════════════════════════════════════════

    /** Une face seule, sans navigation. */
    function showPreviewModal(data) {
        _setSequence(null);
        _sub = 0;
        _display(data);
    }

    /** La face d'une sortie multiple réellement montrée : son fichier courant, qui garde l'élément
     *  (adresse, faces) pour la bascule et le plein écran. */
    function _shownFile(data) {
        const files = _filesOf(data);
        if (!files) return data;
        _sub = Math.min(Math.max(0, _sub), files.length - 1);
        return Object.assign({}, files[_sub], { _baseUrl: data._baseUrl, sides: data.sides, side: data.side });
    }

    /** Ce que montrait la visionneuse s'arrête et se libère avant d'être remplacé. */
    function _releaseContent(container) {
        if (!container) return;
        container.querySelectorAll('video, audio').forEach(function (m) { try { m.pause(); } catch (e) {} });
        if (window.WamaAudioPlayer) window.WamaAudioPlayer.destroy('modal-audio');
        // Visionneuse 3D : libérer le contexte WebGL (un navigateur n'en accorde qu'une poignée).
        container.querySelectorAll('[data-wama-3d]').forEach(function (h) { if (h._dispose) h._dispose(); });
    }

    function _display(data) {
        if (!showable(data)) {
            showPreviewError((data && data.error) || 'Aperçu indisponible pour cet élément');
            return;
        }
        // Une autre face que celle qui se CONSTRUIT : le suivi en direct s'arrête.
        if (!data._duringTick) _stopModalDuring();

        currentPreviewData = data;
        const shown = _shownFile(data);

        let modal = document.getElementById('wamaMediaPreviewModal');
        if (!modal) {
            modal = createPreviewModal();
            document.body.appendChild(modal);
        }

        const title = modal.querySelector('.modal-title');
        const container = modal.querySelector('.preview-container');
        const meta = modal.querySelector('.preview-meta');

        title.textContent = shown.name || data.name || 'Preview';
        title.title = title.textContent;
        // Le fichier montré, dans un nouvel onglet (les liens sous le PDF et le HTML, et « Ouvrir »
        // de la barre d'un texte, réunis ici le 2026-10-14).
        const open = modal.querySelector('.wama-preview-open');
        if (open) {
            open.hidden = !shown.url;
            open.href = shown.url || '#';
        }

        // Clear previous content (keep nav buttons)
        _releaseContent(container);
        container.querySelectorAll(':scope > :not(.wama-preview-nav-btn)').forEach(function(el) { el.remove(); });
        _setKind(modal, viewerKind(shown));
        container.appendChild(buildPreviewContent(shown));
        // Un son : son onde tout de suite, par les pics que le serveur joint (comme le volet) — elle
        // n'apparaissait qu'au premier clic sur lecture.
        if (Array.isArray(shown.peaks) && shown.peaks.length && window.WamaAudioPlayer
                && window.WamaAudioPlayer.setPeaks && container.querySelector('#audioPlayer_modal-audio')) {
            window.WamaAudioPlayer.setPeaks('modal-audio', shown.peaks);
        }

        const metaParts = [];
        [shown, data].some(function (src) {
            if (!(src.duration || src.resolution || src.properties)) return false;
            if (src.duration) metaParts.push(src.duration);
            if (src.resolution) metaParts.push(src.resolution);
            if (src.properties) metaParts.push(src.properties);
            return true;
        });
        meta.textContent = metaParts.join(' · ');

        // Les faces de l'élément (Entrée | … | Sortie), dans leur emplacement dédié.
        _renderModalSides(modal, data);
        _renderModalDownloads(modal, data);
        _syncFooter(modal);
        // La face PENDANT se suit EN DIRECT dans la modale comme dans le volet (2026-10-05,
        // demande de Fabien : voir les détections de l'anonymizer en grand pendant le traitement).
        if (data.side === 'during' && data._baseUrl && !data._duringTick) _startModalDuring(modal, data);

        updateNavigationUI(modal);
        // Si la surcouche plein écran (galeries) est ouverte, la synchroniser.
        syncFullscreenIfOpen(shown);

        // Mettre en pause les players inline
        if (window.WamaAudioPlayer) window.WamaAudioPlayer.pauseAll();

        // getOrCreateInstance : réutilise l'instance existante (évite l'empilement de backdrops)
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    // ── Face PENDANT suivie en direct (2026-10-05) ─────────────────────────────────────────────
    // Par le suiveur COMMUN (`followDuring` : même adresse, même cadence que le volet, vue choisie
    // gardée, fin lue à l'état de la card). L'élément terminé → sa SORTIE, comme dans le volet.
    let _modalDuring = null;   // le suiveur en cours

    function _stopModalDuring() {
        if (_modalDuring) _modalDuring.stop();
        _modalDuring = null;
    }

    function _startModalDuring(modal, data) {
        _stopModalDuring();
        if (!window.WamaApp || !window.WamaApp.Poller) return;
        const base = data._baseUrl;
        const card = cardOfPreview(base);
        _modalDuring = followDuring(base, {
            variant: data.variant || null,
            isRunning: card ? function () { return isRunningCard(card); } : null,
            onFrame: function (d) {
                d._baseUrl = base;
                d._duringTick = true;
                _display(d);
            },
            onEnd: function () {
                _json(faceUrl(base, 'output'))
                    .then(function (o) { if (o && o.side === 'output') { o._baseUrl = base; _display(o); } });
            },
        });
    }

    /** L'emplacement DÉDIÉ des bascules de la modale, hors de la zone qui défile (2026-10-13,
     *  demande de Fabien) : la barre des faces était posée en `position:absolute` DANS l'aperçu —
     *  elle recouvrait la barre d'outils du lecteur PDF, le haut d'un texte, et l'image ou la vidéo
     *  à tout l'écran. AU-DESSUS de l'aperçu depuis le 2026-10-14 : les faces sont des onglets.
     *  Visible seulement quand il porte une bascule. Une modale créée avant cette version (page
     *  restée ouverte) reçoit son emplacement à la volée. */
    function _sidesSlot(modal) {
        let slot = modal.querySelector('.wama-modal-sides-slot');
        if (!slot) {
            slot = document.createElement('div');
            slot.className = SLOT_CLASS;
            slot.style.cssText = SLOT_STYLE;
            const body = modal.querySelector('.modal-body');
            body.parentNode.insertBefore(slot, body);
        }
        return slot;
    }

    /** La NATURE de ce que montre la visionneuse — elle règle sa largeur et son fond (feuille) :
     *  `media` (image, vidéo, PDF, HTML, 3D) prend la place, `text` garde une largeur de lecture,
     *  `audio` reste étroit. Pure (gardée en V8, `tests_preview_navigation`). */
    function viewerKind(data) {
        const mime = String((data && data.mime_type) || '').toLowerCase();
        if (data && data.side === 'compare') return 'media';
        if (mime.indexOf('audio/') === 0) return 'audio';
        if (/^(image|video|model)\//.test(mime) || mime === 'application/pdf' || mime.indexOf('text/html') === 0) return 'media';
        if (mime.indexOf('text/') === 0 || (data && typeof data.content === 'string')) return 'text';
        return 'media';
    }

    function _setKind(modal, kind) {
        modal.setAttribute('data-kind', kind);
        const dialog = modal.querySelector('.modal-dialog');
        dialog.classList.toggle('modal-xl', kind === 'media');
        dialog.classList.toggle('modal-lg', kind !== 'media');
    }

    /** Le pied (propriétés du fichier, téléchargements) se retire quand il n'a rien à dire. */
    function _syncFooter(modal) {
        const footer = modal && modal.querySelector('.modal-footer');
        if (!footer) return;
        const meta = footer.querySelector('.preview-meta');
        const downloads = footer.querySelector('.wama-preview-downloads');
        const said = (meta && meta.textContent.trim()) || (downloads && downloads.style.display !== 'none');
        footer.style.display = said ? '' : 'none';
    }

    function _syncSidesSlot(modal) {
        const slot = _sidesSlot(modal);
        slot.style.display = slot.children.length ? 'flex' : 'none';
    }

    /** La bascule des faces de la visionneuse (et de son plein écran) — la brique commune
     *  `sidesBar`, celle du volet. Il faut l'adresse de l'élément (`_baseUrl`) pour changer de
     *  face. Posée dans l'emplacement dédié (`_sidesSlot`). */
    function _renderModalSides(modal, data) {
        const slot = _sidesSlot(modal);
        const old = slot.querySelector('.wama-modal-sides');
        if (old) old.remove();
        const base = data._baseUrl, s = data.sides;
        const bar = base ? sidesBar(data, {
            go: function (side) { _goSide(base, s, side); },
            compare: function () { _modalCompare(modal, base, s); },
        }) : null;
        if (bar) {
            bar.classList.add('wama-modal-sides');
            slot.insertBefore(bar, slot.firstChild);
        }
        _renderModalVariants(modal, data);
    }

    /** Les TÉLÉCHARGEMENTS de l'élément, au pied de la visionneuse (là où la modale du
     *  transcriber avait « Télécharger TXT / SRT ») : les formats que l'app déclare, quelle que
     *  soit la face montrée. Rien sans élément (un fichier du gestionnaire, une galerie). */
    function _renderModalDownloads(modal, data) {
        const footer = modal.querySelector('.modal-footer');
        if (!footer) return;
        let holder = footer.querySelector('.wama-preview-downloads');
        if (!holder) {
            holder = document.createElement('div');
            holder.className = 'wama-preview-downloads';
            footer.appendChild(holder);
        }
        const list = (data.sides && data.sides.downloads) || [];
        holder.innerHTML = list.length ? '<i class="fas fa-download wama-preview-downloads-icon" title="Télécharger"></i>'
            + downloadsHtml(list) : '';
        holder.style.display = list.length ? '' : 'none';
    }

    // L'horloge de lecture de l'élément montré par la visionneuse (`takeClock`) : elle passe d'une
    // face à l'autre, jamais d'un élément à l'autre.
    let _modalClock = null;

    function _modalContainer() {
        const modal = document.getElementById('wamaMediaPreviewModal');
        return modal && modal.querySelector('.preview-container');
    }

    function _goSide(base, sides, side) {
        _modalClock = takeClock(_modalContainer(), base, _modalClock);
        _json(faceUrl(base, side)).then(function (nd) {
            if (!nd) return;
            nd._baseUrl = base;
            nd.sides = nd.sides || sides;
            // De Comparer (ou de la Sortie) vers la Sortie : le MÊME fichier ; ailleurs, le premier.
            if (side !== 'output') _sub = 0;
            _display(nd);
            giveClock(_modalContainer(), _modalClock, base);
        });
    }

    /** Les VUES publiées pendant le traitement (l'anonymizer : Détection | Floutage) — la barre
     *  COMMUNE `variantToggle`, posée À PART sous celle des faces : une vue de la face Pendant
     *  n'est pas une face (la face « Détection » porte le même nom). */
    function _renderModalVariants(modal, data) {
        const slot = _sidesSlot(modal);
        let holder = slot.querySelector('.wama-modal-variants');
        const variants = data.side === 'during' ? (data.variants || []) : [];
        if (variants.length < 2) {
            if (holder) holder.remove();
            _syncSidesSlot(modal);
            return;
        }
        if (!holder) {
            holder = document.createElement('div');
            holder.className = 'wama-modal-variants';
            slot.appendChild(holder);          // SOUS la barre des faces, dans le même emplacement
        }
        holder.innerHTML = '';
        holder.appendChild(variantToggle(variants, data.variant, function (key) {
            if (_modalDuring) _modalDuring.choose(key);
        }));
        _syncSidesSlot(modal);
    }

    /** Comparer dans la modale et son plein écran : la SORTIE superposée à la référence, un
     *  curseur — la fabrique COMMUNE `compareView`, sur les faces de `compareFaces` (celles du
     *  volet). La modale juxtaposait deux médias jusqu'au 2026-10-06 (Fabien : « une
     *  superposition avec le slider »). Une sortie MULTIPLE est comparée fichier par fichier
     *  (2026-10-13) : `sub` = le fichier montré au clic (par défaut celui de la vue courante) ;
     *  ←/→ passent aux autres fichiers EN RESTANT dans Comparer, puis à la card voisine. */
    function _modalCompare(modal, base, s, sub) {
        _modalClock = takeClock(_modalContainer(), base, _modalClock);
        compareFaces(base, s).then(function (pair) {
            if (!pair) return;
            const files = _filesOf(pair.dout);
            _sub = files ? Math.min(Math.max(0, sub == null ? _sub : sub), files.length - 1) : 0;
            _showCompare(modal, { side: 'compare', sides: s, _baseUrl: base,
                                  files: files || undefined, _pair: pair });
            giveClock(_modalContainer(), _modalClock, base);
        });
    }

    /** Rend Comparer pour la face `face` (ses deux faces chargées, `_pair`) sur le fichier `_sub`. */
    function _showCompare(modal, face) {
        const container = modal.querySelector('.preview-container');
        const pair = face._pair;
        if (!container || !pair) return;
        const files = _filesOf(face);
        const output = files ? Object.assign({}, pair.dout, files[_sub]) : pair.dout;
        _stopModalDuring();
        _releaseContent(container);
        Array.prototype.forEach.call(container.querySelectorAll(':scope > :not(.wama-preview-nav-btn)'),
            function (el) { el.remove(); });
        _setKind(modal, 'media');
        const view = compareView(pair.din, output, pair.baseLabel);
        view.classList.add('wama-modal-compare');
        container.appendChild(view);
        currentPreviewData = face;
        modal.querySelector('.modal-title').textContent = compareTitle(pair.din, output);
        const open = modal.querySelector('.wama-preview-open');
        if (open) open.hidden = true;           // deux fichiers confrontés : aucun à ouvrir seul
        // Le pied disait les propriétés de la face d'AVANT : il se tait plutôt que de mentir.
        const meta = modal.querySelector('.preview-meta');
        if (meta) meta.textContent = '';
        _syncFooter(modal);
        _renderModalSides(modal, face);
        updateNavigationUI(modal);
    }

    /** Les natures de texte qui se lisent en police à chasse fixe (colonnes, code) ; tout autre
     *  texte (transcription, description, markdown) se lit en police de texte. */
    const CODE_TEXT = /^text\/(csv|tab-separated-values|x-|xml|javascript|css)|json/;

    /** Une face TEXTE dans son cadre (2026-10-14, l'aspect des anciennes modales de résultat du
     *  transcriber et du describer) : une barre (le nombre de mots, Copier) et un corps qui défile
     *  seul, à la hauteur que laisse l'écran. Le corps est le texte NU (`<pre>`), le HTML mis en
     *  forme par le serveur (`ProcessSpec.result_format`, neutralisé à la source par
     *  `docs_catalog.render_markdown`) ou le dessin d'un résultat STRUCTURÉ (`_structured` :
     *  rapport de cohérence, tours de parole, évaluation). Copier garde le texte d'origine.
     *  Remplace deux branches à styles en ligne (fond #1e1e1e, 13 px, 65vh). */
    function _textPane(data, mimeType) {
        const pane = document.createElement('div');
        pane.className = 'wama-text-pane';

        const toolbar = document.createElement('div');
        toolbar.className = 'wama-text-toolbar';
        // Le nombre de mots de la face (les onglets des anciennes modales de résultat le portaient).
        const words = document.createElement('span');
        words.className = 'wama-preview-words';
        const setWords = (text) => {
            words.textContent = wordsLabel(text);
            words.style.display = words.textContent ? '' : 'none';
        };
        setWords('');
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'wama-text-action';
        const copyLabel = '<i class="fas fa-copy" aria-hidden="true"></i><span>Copier</span>';
        copyBtn.innerHTML = copyLabel;
        toolbar.appendChild(words);
        toolbar.appendChild(copyBtn);

        const drawn = _structured(data, false);
        const formatted = !drawn && typeof data.html === 'string';
        const body = document.createElement((formatted || drawn) ? 'div' : 'pre');
        body.className = 'wama-text-body'
            + (drawn ? ' is-structured' : formatted ? ' wama-result-formatted' : ' is-plain')
            + (!drawn && !formatted && CODE_TEXT.test(mimeType || '') ? ' is-code' : '');
        body.textContent = 'Chargement…';

        copyBtn.addEventListener('click', () => {
            navigator.clipboard.writeText((formatted || drawn) ? data.content : body.textContent).then(() => {
                copyBtn.innerHTML = '<i class="fas fa-check" aria-hidden="true"></i><span>Copié</span>';
                copyBtn.classList.add('is-done');
                setTimeout(() => { copyBtn.innerHTML = copyLabel; copyBtn.classList.remove('is-done'); }, 2000);
            }).catch(() => {});
        });

        pane.appendChild(toolbar);
        pane.appendChild(body);

        if (drawn) {
            body.textContent = '';
            body.appendChild(drawn);
            setWords(_structuredWords(data));
        } else if (formatted) {
            body.innerHTML = data.html;
            setWords(data.content);
        } else if (typeof data.content === 'string') {
            // Texte servi inline (sortie/entrée texte, docx/odt/rtf extrait) — pas de fetch
            body.textContent = data.content;
            setWords(data.content);
        } else if (data.url) {
            fetch(data.url)
                .then(r => r.ok ? r.text() : Promise.reject(r.status))
                .then(text => { body.textContent = text; setWords(text); })
                .catch(err => { body.textContent = `Erreur lors du chargement (${err}).`; });
        } else {
            body.textContent = data.error ? `Aperçu indisponible : ${data.error}` : 'Aperçu indisponible.';
        }
        copyBtn.hidden = !(typeof data.content === 'string' || data.url);
        return pane;
    }

    /**
     * Build the preview content element based on MIME type.
     */
    function buildPreviewContent(data) {
        const mimeType = data.mime_type || '';

        if (mimeType.startsWith('video/')) {
            // Taille : la place que laisse l'écran (`--wv-stage`, media-preview.css), proportions
            // gardées — plus de hauteur figée en ligne (70vh débordait sur un écran bas).
            const video = document.createElement('video');
            video.src = data.url;
            video.controls = true;
            video.autoplay = false;
            video.className = 'wama-viewer-media';
            // Une face à SURCOUCHE (détections) : posée une fois la vidéo dans la page.
            if (data.overlay && window.WamaPreviewOverlay) {
                setTimeout(function () { window.WamaPreviewOverlay.attach(video, data.overlay); }, 0);
            }
            return video;
        } else if (mimeType.startsWith('audio/')) {
            if (window.WamaAudioPlayer) {
                const wrapper = document.createElement('div');
                wrapper.className = 'p-3 w-100';
                wrapper.appendChild(window.WamaAudioPlayer.create(data.url, 'modal-audio', { height: 80 }));
                return wrapper;
            }
            // Fallback si WaveSurfer non chargé
            const audioContainer = document.createElement('div');
            audioContainer.className = 'wama-audio-preview text-center w-100 p-4';
            const audio = document.createElement('audio');
            audio.src = data.url;
            audio.controls = true;
            audio.className = 'w-100';
            audioContainer.appendChild(audio);
            return audioContainer;
        } else if (mimeType.startsWith('image/')) {
            // Create wrapper with fullscreen button
            const wrapper = document.createElement('div');
            wrapper.className = 'preview-image-wrapper wama-reveal-host';   // bouton révélé au survol (wama-touch.css)
            wrapper.ondblclick = function() {
                _expand(data);
            };

            const img = document.createElement('img');
            img.src = data.url;
            img.className = 'wama-viewer-media';
            img.alt = data.name || 'Image preview';
            wrapper.appendChild(img);
            if (data.overlay && window.WamaPreviewOverlay) {
                setTimeout(function () { window.WamaPreviewOverlay.attach(img, data.overlay); }, 0);
            }

            const fullscreenBtn = document.createElement('button');
            fullscreenBtn.className = 'preview-fullscreen-btn wama-reveal';
            fullscreenBtn.title = 'Plein écran (double-clic)';
            fullscreenBtn.innerHTML = _SVG_EXPAND;
            fullscreenBtn.onclick = function(e) {
                e.stopPropagation();
                _expand(data);
            };
            wrapper.appendChild(fullscreenBtn);

            return wrapper;
        } else if (mimeType.startsWith('model/')) {
            // Objet 3D (glTF/GLB, FBX) — visionneuse three.js chargée À LA DEMANDE par l'importmap
            // commune (`wama/3d-viewer`). Une page sans importmap n'a pas déclaré savoir rendre du
            // 3D : l'import échoue et l'on retombe sur le téléchargement, sans erreur console.
            const wrapper = document.createElement('div');
            wrapper.className = 'w-100 position-relative wama-viewer-frame';
            wrapper.setAttribute('data-wama-3d', '');
            const status = document.createElement('div');
            status.className = 'text-muted small text-center p-3';
            status.textContent = 'Chargement de l’objet 3D…';
            wrapper.appendChild(status);
            const format = (String(data.name || data.url || '').match(/\.([a-z0-9]+)(?:[?#]|$)/i) || [])[1];
            import('wama/3d-viewer')
                .then((mod) => mod.mount(wrapper, data.url, { format: format }))
                .then((viewer) => {
                    status.remove();
                    wrapper._dispose = viewer.dispose;
                    const modal = document.getElementById('wamaMediaPreviewModal');
                    const meta = modal?.querySelector('.preview-meta');
                    if (meta && viewer.info) {
                        const parts = [viewer.info.format.toUpperCase(), viewer.info.meshes + ' maillage(s)'];
                        if (viewer.info.animations.length) parts.push(viewer.info.animations.length + ' animation(s)');
                        meta.textContent = [meta.textContent, parts.join(' • ')].filter(Boolean).join(' · ');
                        _syncFooter(modal);
                    }
                })
                .catch((err) => {
                    status.innerHTML = '<i class="fas fa-cube fa-3x text-secondary mb-3 d-block"></i>'
                        + '<p class="mb-3">Aperçu 3D indisponible ici (' + escapeHtml(String(err && err.message || err)) + ')</p>'
                        + (data.url ? '<a href="' + escapeHtml(data.url) + '" class="btn btn-primary" download><i class="fas fa-download"></i> Télécharger</a>' : '');
                });
            return wrapper;
        } else if (mimeType === 'application/pdf') {
            // Use <embed> instead of <iframe> — X-Frame-Options: deny does not apply to <embed>.
            // « Ouvrir dans un nouvel onglet » est dans l'en-tête de la visionneuse (2026-10-14).
            const embed = document.createElement('embed');
            embed.src = data.url;
            embed.type = 'application/pdf';
            embed.className = 'wama-viewer-frame';
            return embed;
        } else if (mimeType.startsWith('text/html')) {
            // HTML (2026-10-13) : le document RENDU, dans un cadre sans aucune permission — la
            // règle de l'aperçu inline, de l'inspecteur et de la brique `html_preview` des
            // surfaces. La visionneuse n'avait pas ce cas : un double-clic sur l'aperçu d'un
            // document du Writer ouvrait « Preview not available ».
            const frame = document.createElement('iframe');
            frame.src = data.url;
            frame.setAttribute('sandbox', '');
            frame.className = 'wama-viewer-frame wama-viewer-frame--page';
            return frame;
        } else if (mimeType.startsWith('text/') || typeof data.content === 'string') {
            return _textPane(data, mimeType);
        } else {
            // Fallback: show download link (only if URL available)
            const fallback = document.createElement('div');
            fallback.className = 'text-center p-4';
            const downloadLink = data.url
                ? `<a href="${escapeHtml(data.url)}" class="btn btn-primary" download><i class="fas fa-download"></i> Download</a>`
                : '';
            fallback.innerHTML = `
                <i class="fas fa-file fa-5x text-secondary mb-4"></i>
                <p class="mb-3">Preview not available for this file type</p>
                ${downloadLink}
            `;
            return fallback;
        }
    }

    /**
     * Sync the open fullscreen overlay (galleries) to the shown face: its image, name, counter
     * and the state of its buttons. A non-image leaves the overlay so the modal shows it.
     */
    function syncFullscreenIfOpen(item) {
        const fullscreenOverlay = document.getElementById('wamaFullscreenOverlay');
        if (!fullscreenOverlay || !item) return;
        if (!item.mime_type || !item.mime_type.startsWith('image/')) {
            closeFullscreen();
            return;
        }
        if (!item.url) return;
        const fsImg = fullscreenOverlay.querySelector('img');
        const fsName = fullscreenOverlay.querySelector('.filename');
        const fsCounter = fullscreenOverlay.querySelector('.wama-preview-counter');
        if (fsImg) fsImg.src = item.url;
        if (fsName) fsName.textContent = item.name || 'Image';
        const pos = _position();
        if (fsCounter) fsCounter.textContent = _counterText(pos);
        _syncNavButtons(fullscreenOverlay, pos);
        // Réinitialiser le mode zoom à chaque changement d'image
        fullscreenOverlay.classList.remove('wama-fs-actual');
    }

    function _syncNavButtons(root, pos) {
        const hasNav = pos.count > 1 || pos.files > 1;
        const prevBtn = root.querySelector('.wama-preview-nav-prev');
        const nextBtn = root.querySelector('.wama-preview-nav-next');
        if (prevBtn) {
            prevBtn.style.display = hasNav ? '' : 'none';
            prevBtn.classList.toggle('disabled', !stepTarget(pos, -1, false));
        }
        if (nextBtn) {
            nextBtn.style.display = hasNav ? '' : 'none';
            nextBtn.classList.toggle('disabled', !stepTarget(pos, 1, false));
        }
        // Les flèches ont leurs MARGES, de part et d'autre de l'aperçu (2026-10-15, Fabien : posées
        // sur lui, elles masquaient le bouton de lecture d'un son, le bord d'une image).
        const body = root.querySelector && root.querySelector('.modal-body');
        if (body) body.classList.toggle('has-nav', hasNav);
        return hasNav;
    }

    /**
     * Update the navigation buttons and counter visibility/state.
     */
    function updateNavigationUI(modal) {
        const pos = _position();
        const counter = modal.querySelector('.wama-preview-counter');
        const hasNav = _syncNavButtons(modal, pos);
        if (counter) {
            counter.textContent = hasNav ? _counterText(pos) : '';
            counter.style.display = hasNav ? '' : 'none';
        }
    }

    /**
     * Create the preview modal element.
     */
    function createPreviewModal() {
        const modal = document.createElement('div');
        modal.id = 'wamaMediaPreviewModal';
        modal.className = 'modal fade';
        modal.tabIndex = -1;
        // Mise en forme : `media-preview.css` (§ VISIONNEUSE) — la largeur suit la nature montrée
        // (`_setKind`), la hauteur de l'aperçu celle que laisse l'écran (`--wv-stage`).
        modal.innerHTML = `
            <div class="modal-dialog modal-xl modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <div class="wama-viewer-heading">
                            <h6 class="modal-title"></h6>
                            <span class="wama-preview-counter" style="display:none;"></span>
                        </div>
                        <div class="wama-viewer-actions">
                            <a class="wama-viewer-icon wama-preview-open" href="#" target="_blank" rel="noopener" title="Ouvrir dans un nouvel onglet" hidden><i class="fas fa-arrow-up-right-from-square"></i></a>
                            <button type="button" class="wama-viewer-icon wama-preview-full-toggle" title="Plein écran"><i class="fas fa-expand"></i></button>
                            <button type="button" class="wama-viewer-icon" data-bs-dismiss="modal" aria-label="Fermer" title="Fermer (Échap)"><i class="fas fa-xmark"></i></button>
                        </div>
                    </div>
                    <!-- Emplacement DÉDIÉ des bascules (faces en onglets, vues) — AU-DESSUS de
                         l'aperçu, hors de la zone qui défile : jamais superposé au contenu
                         (2026-10-13 sous l'aperçu, au-dessus depuis le 2026-10-14, cf. _sidesSlot). -->
                    <div class="${SLOT_CLASS}" style="${SLOT_STYLE}"></div>
                    <div class="modal-body">
                        <!-- Boutons nav FRÈRES du container (pas dedans) — évite tout conflit z-index/flex -->
                        <button class="wama-preview-nav-btn wama-preview-nav-prev" style="display:none;" title="Précédent (←) — card précédente (↑)">${_SVG_PREV}</button>
                        <button class="wama-preview-nav-btn wama-preview-nav-next" style="display:none;" title="Suivant (→) — card suivante (↓)">${_SVG_NEXT}</button>
                        <div class="preview-container"></div>
                    </div>
                    <div class="modal-footer">
                        <small class="preview-meta"></small>
                    </div>
                </div>
            </div>
        `;

        modal.querySelector('.wama-preview-full-toggle').addEventListener('click', function (e) {
            e.stopPropagation();
            const dialog = modal.querySelector('.modal-dialog');
            _setModalFull(modal, !dialog.classList.contains('modal-fullscreen'));
        });
        modal.querySelector('.wama-preview-nav-prev').addEventListener('click', function(e) {
            e.stopPropagation();
            _navigate(-1, false);
        });
        modal.querySelector('.wama-preview-nav-next').addEventListener('click', function(e) {
            e.stopPropagation();
            _navigate(1, false);
        });
        // Fermeture : UN écouteur, posé avec la modale (il était reposé à chaque ouverture et
        // s'accumulait). La card sur laquelle on referme est désignée au volet.
        modal.addEventListener('hidden.bs.modal', function() {
            _stopModalDuring();
            _setModalFull(modal, false);
            _releaseContent(modal.querySelector('.preview-container'));
            _announceCard();
            currentPreviewData = null;
            _modalClock = null;
            _setSequence(null);
            _sub = 0;
        });

        return modal;
    }

    /** La modale à TOUT l'écran, ou rendue à sa taille (2026-10-05) : elle garde ses faces, sa
     *  comparaison et le suivi en direct — le plein écran d'un élément est la modale agrandie. */
    function _setModalFull(modal, on) {
        const dialog = modal && modal.querySelector('.modal-dialog');
        if (!dialog) return;
        dialog.classList.toggle('modal-fullscreen', !!on);
        const toggle = modal.querySelector('.wama-preview-full-toggle');
        if (toggle) {
            toggle.title = on ? 'Quitter le plein écran' : 'Plein écran';
            toggle.innerHTML = '<i class="fas ' + (on ? 'fa-compress' : 'fa-expand') + '"></i>';
        toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
        }
    }

    /** Agrandir une image : un ÉLÉMENT (il a des faces) → la modale à tout l'écran ; une image
     *  de galerie sans élément → la surcouche image (zoom taille réelle, navigation). */
    function _expand(data) {
        if (data && data._baseUrl && data.sides) {
            _setModalFull(document.getElementById('wamaMediaPreviewModal'), true);
            return;
        }
        openFullscreen(data.url, data.name);
    }

    /**
     * Open fullscreen overlay for an image (galleries without an item).
     */
    function openFullscreen(imageUrl, imageName) {
        closeFullscreen();

        const overlay = document.createElement('div');
        overlay.id = 'wamaFullscreenOverlay';
        overlay.onclick = function(e) {
            if (e.target === overlay) closeFullscreen();
        };

        overlay.innerHTML = `
            <button class="fullscreen-close-btn" title="Fermer (Échap)">${_SVG_CLOSE}</button>
            <button class="wama-preview-nav-btn wama-preview-nav-prev" title="Précédent (←)">${_SVG_PREV}</button>
            <button class="wama-preview-nav-btn wama-preview-nav-next" title="Suivant (→)">${_SVG_NEXT}</button>
            <img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(imageName || 'Image')}" title="Cliquer pour basculer taille réelle / adapté">
            <div class="fullscreen-info">
                <span class="filename">${escapeHtml(imageName || 'Image')}</span>
                <span class="wama-preview-counter"></span>
            </div>
        `;

        overlay.querySelector('.fullscreen-close-btn').addEventListener('click', function(e) {
            e.stopPropagation();
            closeFullscreen();
        });

        // Clic sur l'image → toggle taille réelle / adapté à l'écran
        overlay.querySelector('img').addEventListener('click', function(e) {
            e.stopPropagation();
            overlay.classList.toggle('wama-fs-actual');
        });

        overlay.querySelector('.wama-preview-nav-prev').addEventListener('click', function(e) {
            e.stopPropagation();
            _navigate(-1, false);
        });
        overlay.querySelector('.wama-preview-nav-next').addEventListener('click', function(e) {
            e.stopPropagation();
            _navigate(1, false);
        });
        const pos = _position();
        overlay.querySelector('.wama-preview-counter').textContent = _counterText(pos);
        _syncNavButtons(overlay, pos);

        document.body.appendChild(overlay);
        document.body.style.overflow = 'hidden';
    }

    /**
     * Close fullscreen overlay.
     */
    function closeFullscreen() {
        const overlay = document.getElementById('wamaFullscreenOverlay');
        if (overlay) {
            overlay.remove();
            document.body.style.overflow = '';
        }
    }

    /**
     * Show an error message in the preview.
     */
    function showPreviewError(message) {
        // Try to use toast if available
        if (window.FileManager && window.FileManager.showToast) {
            window.FileManager.showToast(message, 'danger');
            return;
        }

        // Try Bootstrap toast
        if (typeof showToast === 'function') {
            showToast(message, 'danger');
            return;
        }

        // Fallback to console
        console.error('Preview error:', message);
    }

    /**
     * Show a simple text modal with a copy button.
     * Can be called from any app for displaying result/OCR text.
     * @param {string} text    - The text to display
     * @param {string} title   - Modal title (filename, label…)
     */
    function showTextModal(text, title) {
        showPreviewModal({ content: text || '', name: title || 'Texte', mime_type: 'text/plain' });
    }

    // Export functions to window for external use
    window.initMediaPreview = initMediaPreview;
    window.showPreviewModal = showPreviewModal;
    window.showPreviewModalWithNav = showPreviewModalWithNav;
    window.showTextModal = showTextModal;
    window.openWamaFullscreen = openFullscreen;
    window.closeWamaFullscreen = closeFullscreen;
    // LA brique (les fonctions pures sont gardées en V8 : `tests_cap_from_js`,
    // `tests_preview_entry`, `tests_preview_navigation`).
    window.WamaMediaPreview = {
        // pures
        itemAddress: _itemAddress, showable: showable, faceButtons: faceButtons, compareTitle: compareTitle,
        wordsLabel: wordsLabel, coherenceHtml: coherenceHtml, segmentsHtml: segmentsHtml,
        downloadsHtml: downloadsHtml,
        stepTarget: stepTarget, duringUrl: duringUrl, faceUrl: faceUrl,
        // rendu en ligne
        renderInline: renderInline, hydrateCardPreviews: hydrateCardPreviews,
        // faces
        sidesBar: sidesBar, viewerKind: viewerKind, compareFaces: compareFaces, compareView: compareView,
        variantToggle: variantToggle, followDuring: followDuring,
        takeClock: takeClock, giveClock: giveClock, releaseMedia: _releaseHost,
        isRunningCard: isRunningCard, cardOfPreview: cardOfPreview,
        // visionneuse et navigation
        show: showPreviewModal, showWithNav: showPreviewModalWithNav,
        openSequence: openSequence, openForCard: openForCard, cardSequence: cardSequence,
    };

    // Auto-initialisation EN DERNIER : toutes les déclarations (`const`, `let`) sont alors faites —
    // appelée plus haut, une page déjà chargée (ou le banc V8) tombait dans leur zone morte.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
