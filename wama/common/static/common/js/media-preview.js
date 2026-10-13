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

    // L'emplacement DÉDIÉ des bascules (faces, vues) de la modale — sous l'aperçu, hors de la zone
    // qui défile, jamais superposé au contenu (`_sidesSlot`). Masqué tant qu'il est vide.
    const SLOT_CLASS = 'wama-modal-sides-slot border-top border-secondary';
    const SLOT_STYLE = 'display:none;flex-direction:column;align-items:center;gap:.35rem;'
        + 'padding:.5rem .75rem;flex-shrink:0;';

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

    // Rendu INLINE compact d'un aperçu média (≠ visionneuse). Données = JSON de
    // common:unified_preview {name, url, mime_type, …}. autoplay gated par le profil (jamais de
    // génération : on n'affiche que l'existant — CARD_DESIGN §10.6 / décision Fabien).
    function renderInline(host, data, autoplay) {
        if (!host) return;
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
     *  « Résumé »…) → Pendant → Comparer → Sortie. Chaque bouton n'existe que si sa face existe.
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
        return out;
    }

    /** La bascule des FACES — UNE construction pour le volet et la visionneuse (le volet en avait
     *  sa copie, sans Pendant, jusqu'au 2026-10-13). `d` = la face montrée ; `opts.go(face)` ouvre
     *  une face, `opts.compare()` lance Comparer ; `opts.compact` = la densité du volet (pleine
     *  largeur, boutons serrés), sinon celle de la visionneuse (boutons larges, à la ligne s'ils
     *  sont nombreux). null quand il n'y a pas deux faces entre lesquelles basculer. */
    function sidesBar(d, opts) {
        opts = opts || {};
        const buttons = faceButtons(d);
        if (buttons.length < 2) return null;
        const bar = document.createElement('div');
        bar.className = 'btn-group btn-group-sm wama-preview-sides' + (opts.compact ? ' mt-1 w-100' : '');
        if (!opts.compact) bar.style.cssText = 'flex-wrap:wrap;justify-content:center;max-width:100%;';
        buttons.forEach(function (f) {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'btn btn-sm ' + (opts.compact ? 'py-0 px-2 flex-fill ' : 'px-3 ')
                + (f.key === d.side ? 'btn-info' : 'btn-outline-info');
            b.setAttribute('data-side', f.key);
            b.innerHTML = '<i class="fas ' + f.icon + ' me-1"></i>' + escapeHtml(f.label);
            b.addEventListener('click', function () {
                if (f.key === 'compare') { if (opts.compare) opts.compare(); }
                else if (opts.go) opts.go(f.key);
            });
            bar.appendChild(b);
        });
        return bar;
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

        // Clear previous content (keep nav buttons)
        _releaseContent(container);
        container.querySelectorAll(':scope > :not(.wama-preview-nav-btn)').forEach(function(el) { el.remove(); });
        container.appendChild(buildPreviewContent(shown));

        const metaParts = [];
        [shown, data].some(function (src) {
            if (!(src.duration || src.resolution || src.properties)) return false;
            if (src.duration) metaParts.push(src.duration);
            if (src.resolution) metaParts.push(src.resolution);
            if (src.properties) metaParts.push(src.properties);
            return true;
        });
        meta.textContent = metaParts.join(' | ');

        // Les faces de l'élément (Entrée | … | Sortie), dans leur emplacement dédié.
        _renderModalSides(modal, data);
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

    /** L'emplacement DÉDIÉ des bascules de la modale, SOUS l'aperçu et hors de la zone qui défile
     *  (2026-10-13, demande de Fabien) : la barre des faces était posée en `position:absolute`
     *  DANS l'aperçu — elle recouvrait la barre d'outils du lecteur PDF, le haut d'un texte, et
     *  l'image ou la vidéo à tout l'écran. Visible seulement quand il porte une bascule. Une modale
     *  créée avant cette version (page restée ouverte) reçoit son emplacement à la volée. */
    function _sidesSlot(modal) {
        let slot = modal.querySelector('.wama-modal-sides-slot');
        if (!slot) {
            slot = document.createElement('div');
            slot.className = SLOT_CLASS;
            slot.style.cssText = SLOT_STYLE;
            const footer = modal.querySelector('.modal-footer');
            if (footer) footer.parentNode.insertBefore(slot, footer);
            else modal.querySelector('.modal-content').appendChild(slot);
        }
        return slot;
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

    function _goSide(base, sides, side) {
        _json(faceUrl(base, side)).then(function (nd) {
            if (!nd) return;
            nd._baseUrl = base;
            nd.sides = nd.sides || sides;
            // De Comparer (ou de la Sortie) vers la Sortie : le MÊME fichier ; ailleurs, le premier.
            if (side !== 'output') _sub = 0;
            _display(nd);
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
        compareFaces(base, s).then(function (pair) {
            if (!pair) return;
            const files = _filesOf(pair.dout);
            _sub = files ? Math.min(Math.max(0, sub == null ? _sub : sub), files.length - 1) : 0;
            _showCompare(modal, { side: 'compare', sides: s, _baseUrl: base,
                                  files: files || undefined, _pair: pair });
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
        const view = compareView(pair.din, output, pair.baseLabel);
        view.classList.add('wama-modal-compare');
        container.appendChild(view);
        currentPreviewData = face;
        modal.querySelector('.modal-title').textContent = compareTitle(pair.din, output);
        // Le pied disait les propriétés de la face d'AVANT : il se tait plutôt que de mentir.
        const meta = modal.querySelector('.preview-meta');
        if (meta) meta.textContent = '';
        _renderModalSides(modal, face);
        updateNavigationUI(modal);
    }

    /**
     * Build the preview content element based on MIME type.
     */
    function buildPreviewContent(data) {
        const mimeType = data.mime_type || '';

        if (mimeType.startsWith('video/')) {
            const video = document.createElement('video');
            video.src = data.url;
            video.controls = true;
            video.autoplay = false;
            video.className = 'w-100';
            video.style.maxHeight = '70vh';
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
            img.className = 'img-fluid';
            img.style.maxHeight = '70vh';
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
            wrapper.className = 'w-100 position-relative';
            wrapper.setAttribute('data-wama-3d', '');
            wrapper.style.cssText = 'height:65vh;min-height:320px;';
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
                    const meta = document.getElementById('wamaMediaPreviewModal')?.querySelector('.preview-meta');
                    if (meta && viewer.info) {
                        const parts = [viewer.info.format.toUpperCase(), viewer.info.meshes + ' maillage(s)'];
                        if (viewer.info.animations.length) parts.push(viewer.info.animations.length + ' animation(s)');
                        meta.textContent = [meta.textContent, parts.join(' • ')].filter(Boolean).join(' | ');
                    }
                })
                .catch((err) => {
                    status.innerHTML = '<i class="fas fa-cube fa-3x text-secondary mb-3 d-block"></i>'
                        + '<p class="mb-3">Aperçu 3D indisponible ici (' + escapeHtml(String(err && err.message || err)) + ')</p>'
                        + (data.url ? '<a href="' + escapeHtml(data.url) + '" class="btn btn-primary" download><i class="fas fa-download"></i> Télécharger</a>' : '');
                });
            return wrapper;
        } else if (mimeType === 'application/pdf') {
            // Use <embed> instead of <iframe> — X-Frame-Options: deny does not apply to <embed>
            const wrapper = document.createElement('div');
            wrapper.className = 'w-100';

            const embed = document.createElement('embed');
            embed.src = data.url;
            embed.type = 'application/pdf';
            embed.className = 'w-100';
            embed.style.height = '70vh';
            wrapper.appendChild(embed);

            const fallbackLink = document.createElement('div');
            fallbackLink.className = 'text-center mt-2';
            fallbackLink.innerHTML = `<a href="${escapeHtml(data.url)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-light"><i class="fas fa-external-link-alt me-1"></i>Ouvrir dans un nouvel onglet</a>`;
            wrapper.appendChild(fallbackLink);

            return wrapper;
        } else if (mimeType.startsWith('text/html')) {
            // HTML (2026-10-13) : le document RENDU, dans un cadre sans aucune permission — la
            // règle de l'aperçu inline, de l'inspecteur et de la brique `html_preview` des
            // surfaces. La visionneuse n'avait pas ce cas : un double-clic sur l'aperçu d'un
            // document du Writer ouvrait « Preview not available ».
            const wrapper = document.createElement('div');
            wrapper.className = 'w-100';
            const frame = document.createElement('iframe');
            frame.src = data.url;
            frame.setAttribute('sandbox', '');
            frame.className = 'w-100';
            frame.style.cssText = 'height:70vh;border:0;background:#fff;border-radius:4px;';
            wrapper.appendChild(frame);
            const openLink = document.createElement('div');
            openLink.className = 'text-center mt-2';
            openLink.innerHTML = `<a href="${escapeHtml(data.url)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-light"><i class="fas fa-external-link-alt me-1"></i>Ouvrir dans un nouvel onglet</a>`;
            wrapper.appendChild(openLink);
            return wrapper;
        } else if (mimeType === 'text/plain' || (mimeType.startsWith('text/') && !mimeType.startsWith('text/html'))) {
            // Text file: fetch content and display in scrollable pre
            const wrapper = document.createElement('div');
            wrapper.className = 'w-100';

            const toolbar = document.createElement('div');
            toolbar.className = 'd-flex justify-content-end mb-2 gap-2';

            const copyBtn = document.createElement('button');
            copyBtn.className = 'btn btn-sm btn-outline-secondary';
            copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copier';

            const openBtn = document.createElement('a');
            openBtn.href = data.url;
            openBtn.target = '_blank';
            openBtn.rel = 'noopener';
            openBtn.className = 'btn btn-sm btn-outline-light';
            openBtn.innerHTML = '<i class="fas fa-external-link-alt"></i> Ouvrir';

            toolbar.appendChild(copyBtn);
            if (data.url) toolbar.appendChild(openBtn);

            const pre = document.createElement('pre');
            pre.className = 'text-light p-3 mb-0';
            pre.style.cssText = 'max-height:65vh; overflow-y:auto; background:#1e1e1e; border-radius:4px; font-size:13px; white-space:pre-wrap; word-wrap:break-word; border:1px solid #495057;';
            pre.textContent = 'Chargement…';

            copyBtn.addEventListener('click', () => {
                navigator.clipboard.writeText(pre.textContent).then(() => {
                    copyBtn.innerHTML = '<i class="fas fa-check text-success"></i> Copié';
                    setTimeout(() => { copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copier'; }, 2000);
                }).catch(() => {});
            });

            wrapper.appendChild(toolbar);
            wrapper.appendChild(pre);

            if (typeof data.content === 'string') {
                // Texte servi inline (sortie/entrée texte, docx/odt/rtf extrait) — pas de fetch
                pre.textContent = data.content;
            } else if (data.url) {
                fetch(data.url)
                    .then(r => r.ok ? r.text() : Promise.reject(r.status))
                    .then(text => { pre.textContent = text; })
                    .catch(err => { pre.textContent = `Erreur lors du chargement (${err}).`; });
            } else {
                pre.textContent = data.error ? `Aperçu indisponible : ${data.error}` : 'Aperçu indisponible.';
            }

            return wrapper;
        } else if (typeof data.content === 'string') {
            // Texte inline sans type texte déclaré
            const wrapper = document.createElement('div');
            wrapper.className = 'w-100';

            const copyBtn = document.createElement('button');
            copyBtn.className = 'btn btn-sm btn-outline-secondary mb-2';
            copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copier';

            const pre = document.createElement('pre');
            pre.className = 'text-light p-3 mb-0';
            pre.style.cssText = 'max-height:65vh; overflow-y:auto; background:#1e1e1e; border-radius:4px; font-size:13px; white-space:pre-wrap; word-wrap:break-word; border:1px solid #495057;';
            pre.textContent = data.content;

            copyBtn.addEventListener('click', () => {
                navigator.clipboard.writeText(pre.textContent).then(() => {
                    copyBtn.innerHTML = '<i class="fas fa-check text-success"></i> Copié';
                    setTimeout(() => { copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copier'; }, 2000);
                }).catch(() => {});
            });

            wrapper.appendChild(copyBtn);
            wrapper.appendChild(pre);
            return wrapper;
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
        modal.innerHTML = `
            <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
                <div class="modal-content bg-dark text-white">
                    <div class="modal-header border-secondary py-2">
                        <h6 class="modal-title text-truncate" style="max-width:70%;font-size:.95rem;"></h6>
                        <span class="wama-preview-counter text-muted small ms-2" style="display:none;white-space:nowrap;flex-shrink:0;"></span>
                        <button type="button" class="btn btn-sm btn-outline-light ms-auto me-2 py-0 wama-preview-full-toggle" title="Plein écran"><i class="fas fa-expand"></i></button>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body p-0 position-relative">
                        <!-- Boutons nav FRÈRES du container (pas dedans) — évite tout conflit z-index/flex -->
                        <button class="wama-preview-nav-btn wama-preview-nav-prev" style="display:none;" title="Précédent (←) — card précédente (↑)">${_SVG_PREV}</button>
                        <button class="wama-preview-nav-btn wama-preview-nav-next" style="display:none;" title="Suivant (→) — card suivante (↓)">${_SVG_NEXT}</button>
                        <div class="preview-container d-flex justify-content-center align-items-center" style="min-height:300px;background:#111;"></div>
                    </div>
                    <!-- Emplacement DÉDIÉ des bascules (faces, vues) — SOUS l'aperçu, hors de la zone
                         qui défile : jamais superposé au contenu (2026-10-13, cf. _sidesSlot). -->
                    <div class="${SLOT_CLASS}" style="${SLOT_STYLE}"></div>
                    <div class="modal-footer border-secondary py-2">
                        <small class="preview-meta text-muted w-100 text-center"></small>
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
     * Global delegated handler for .copy-result-btn buttons.
     * Any element with class "copy-result-btn" and data-target="<elementId>"
     * will copy the textContent of that element to clipboard.
     */
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.copy-result-btn');
        if (!btn) return;
        const el = document.getElementById(btn.dataset.target);
        if (!el) return;
        navigator.clipboard.writeText(el.textContent || el.innerText).then(() => {
            btn.innerHTML = '<i class="fas fa-check text-success"></i>';
            setTimeout(() => { btn.innerHTML = '<i class="fas fa-copy"></i>'; }, 2000);
        }).catch(() => {
            const range = document.createRange();
            range.selectNodeContents(el);
            window.getSelection().removeAllRanges();
            window.getSelection().addRange(range);
        });
    });

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
        stepTarget: stepTarget, duringUrl: duringUrl, faceUrl: faceUrl,
        // rendu en ligne
        renderInline: renderInline, hydrateCardPreviews: hydrateCardPreviews,
        // faces
        sidesBar: sidesBar, compareFaces: compareFaces, compareView: compareView,
        variantToggle: variantToggle, followDuring: followDuring,
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
