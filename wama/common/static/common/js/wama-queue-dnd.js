/**
 * wama-queue-dnd.js — MANIPULATION DIRECTE de la file (CARD_DESIGN §3bis).
 *
 * Sélection multiple (clic / Ctrl / Maj) + glisser-déposer, pour TOUTES les apps de file.
 * Auto-monté sur chaque conteneur portant `data-wama-dnd` (posé par `{% queue_dnd_attrs %}`).
 * Aucune app n'écrit une ligne : elle déclare ses URLs au gabarit, et hérite du geste.
 *
 * ══ LES QUATRE GESTES ═══════════════════════════════════════════════════════════════════
 *
 *   card(s) → SUR une card de lot (mère ou fille)  →  move_to_batch   (entrer dans le lot)
 *   card(s) → SUR une card unitaire                →  merge           (former un NOUVEAU lot)
 *   fille(s) de lot → ENTRE deux entrées de file   →  remove_from_batch (sortir du lot)
 *   card(s) → ENTRE deux entrées / entre deux filles → reorder_queue / reorder (ordonner)
 *
 * La règle qui les sépare tient en une phrase : **déposer SUR une card change l'APPARTENANCE,
 * déposer ENTRE deux cards change l'ORDRE.** Tout le reste (multi-sélection, lot d'origine,
 * niveau) n'est que du contexte. C'est ce qui permet d'offrir quatre opérations sans le moindre
 * mode, bouton ou modificateur à retenir.
 *
 * ══ POURQUOI PAS SORTABLEJS (révision de CARD_DESIGN §3bis, 2026-09-04) ═════════════════
 *
 * §3bis prescrivait SortableJS. Cette décision date d'avant deux exigences qui la périment :
 *   • la MULTI-SÉLECTION (Ctrl/Maj) — le plugin MultiDrag existe mais ne compose pas avec des
 *     listes imbriquées, et nos lots EN SONT (une file contient des groupes qui contiennent
 *     des cards) ;
 *   • le dépôt SUR une card pour fusionner — SortableJS modélise le déplacement ENTRE listes,
 *     pas la fusion sur un élément ; il aurait fallu l'écrire par-dessus de toute façon.
 * S'ajoute une contrainte du dépôt : aucun asset tiers n'y est vendorisé (règle « pas de CDN »,
 * `reference_offline_assets_local`), donc adopter la lib, c'était aussi ouvrir ce chantier-là.
 * Le drag natif HTML5 fait exactement les quatre gestes, sans dépendance.
 *
 * ══ CLAVIER ═════════════════════════════════════════════════════════════════════════════
 *
 *   Ctrl/Cmd + A   tout sélectionner (dans UNE file — cf. `fileActive`)
 *   Échap          relâcher la sélection
 *
 * ══ CE QUE LA BRIQUE NE FAIT PAS ════════════════════════════════════════════════════════
 *
 * Le drag est souris-centré (§3bis « vigilance ») : ni tactile, ni clavier. Les mêmes
 * opérations restent atteignables par les actions de groupe de l'inspecteur, qui LISENT cette
 * même sélection — c'est là que le clavier les trouvera. Ne pas ajouter de second chemin ici.
 */

(function () {
    'use strict';

    // ── Utilitaires ──────────────────────────────────────────────────────────────────────
    function csrf() { const m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : ''; }

    function post(url, fields) {
        const fd = new FormData();
        Object.keys(fields || {}).forEach(function (k) { fd.append(k, fields[k]); });
        return fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: fd })
            .then(function (r) {
                if (r.status === 204) return { success: true };
                return r.json().catch(function () { return { success: r.ok }; });
            });
    }

    // Une URL de la forme `/app/move-to-batch/0/` — le 0 est le gabarit de pk, convention déjà
    // utilisée par les `APP.urls` des 12 apps (`{% url 'app:start' 0 %}`).
    function withPk(urlTemplate, pk) { return urlTemplate.replace(/\/0\/?$/, '/' + pk + '/'); }

    function toast(msg, type) {
        if (window.WamaApp && WamaApp.toast) { WamaApp.toast(msg, type || 'info'); return; }
        if (type === 'error') alert(msg);
    }

    // ── Anatomie d'une file ──────────────────────────────────────────────────────────────
    //
    // Ces quatre fonctions sont TOUT ce que la brique sait du DOM, et rien ici n'est propre à
    // une app : le squelette vient de `common/_queue_entry.html`, qui rend les 13 files.
    //
    // ⚠ `entries()` ne descend PAS dans les lots. Une « entrée de file » est ce qui se déplace
    // au niveau supérieur : un groupe de lot ENTIER, ou une card unitaire. Confondre les deux
    // niveaux est le défaut qui rendrait `reorder_queue` incohérent — il ordonne des BATCHS.

    function entries(queue) {
        return Array.prototype.slice.call(queue.children).filter(function (el) {
            // Lot déplié, ou card unitaire dans son enrobage porteur d'id de lot.
            if (el.classList.contains('batch-group')) return true;
            if (el.classList.contains('wama-queue-entry')) return true;
            // Repli : une card ajoutée en direct par le JS d'une app (sans passer par le
            // rendu serveur) n'a pas d'enrobage. Elle compte comme entrée pour le
            // réarrangement à l'écran, mais `batchIdOf` la laissera hors du POST — on ne
            // peut pas ordonner un lot dont on ignore l'id. Elle se replacera au
            // rechargement suivant, qui la rendra enrobée.
            return el.classList.contains('wama-card')
                && !el.classList.contains('wama-new-item-card')
                && !el.classList.contains('wama-new-card')
                && !!el.dataset.id;
        });
    }

    function cards(queue) {
        return Array.prototype.slice.call(queue.querySelectorAll('.wama-card[data-id]'))
            .filter(function (c) {
                return !c.classList.contains('is-batch')
                    && !c.classList.contains('wama-new-item-card')
                    && !c.classList.contains('wama-new-card');
            });
    }

    /** Le groupe de lot d'une card, ou null si elle est unitaire. */
    function groupOf(card) { return card.closest('.batch-group'); }

    /** L'entrée de file (= niveau supérieur) qui contient cet élément. */
    function entryOf(el) {
        return el.closest('.batch-group, .wama-queue-entry') || el.closest('.wama-card[data-id]');
    }

    /**
     * L'id de BATCH d'une entrée — ce que `reorder_queue` ordonne.
     *
     * Deux graphies parce qu'il y a deux formes d'entrée, pas par tolérance : un lot déplié
     * porte `data-batch-id` sur `.batch-group` (gabarit historique), une card unitaire porte
     * `data-entry-batch-id` sur son enrobage (ajouté le 2026-09-04 — la card seule ne
     * nommait NULLE PART le lot dont elle est l'unique membre).
     */
    function batchIdOf(entry) {
        return entry.dataset.batchId || entry.dataset.entryBatchId || null;
    }

    // ══ SÉLECTION ════════════════════════════════════════════════════════════════════════
    //
    // UNE SEULE sélection dans WAMA (arbitrage Fabien, 2026-09-04) : celle-ci EST celle de
    // l'inspecteur. Un clic simple garde le comportement d'avant (1 card, volet droit rempli) ;
    // Ctrl/Maj l'étendent, et l'inspecteur bascule alors en « N éléments sélectionnés ».
    //
    // ⚠ La brique ne touche PAS au highlight de l'inspecteur (`inspector-selected`) : deux
    // classes qui veulent dire la même chose finiraient par diverger. Elle pose la sienne
    // (`wama-dnd-selected`) pour l'ANCRE multiple et ÉMET un événement ; c'est l'inspecteur qui
    // décide de ce qu'il affiche. Le sens est partagé, l'affichage reste à son propriétaire.

    const SEL = 'wama-dnd-selected';

    function stateOf(queue) {
        if (!queue._wamaDnd) queue._wamaDnd = { anchor: null };
        return queue._wamaDnd;
    }

    function selectedCards(queue) {
        return cards(queue).filter(function (c) { return c.classList.contains(SEL); });
    }

    function selectedIds(queue) {
        return selectedCards(queue).map(function (c) { return c.dataset.id; });
    }

    function announce(queue) {
        const sel = selectedCards(queue);
        // L'inspecteur (et qui voudra) écoute : la brique dit CE QUI EST SÉLECTIONNÉ, elle ne
        // dicte pas ce qu'on en affiche.
        queue.dispatchEvent(new CustomEvent('wama:selection-change', {
            bubbles: true,
            detail: { ids: sel.map(function (c) { return c.dataset.id; }), cards: sel, queue: queue },
        }));
    }

    function setSelection(queue, cardEls, mode) {
        if (mode === 'remplacer') {
            cards(queue).forEach(function (c) { c.classList.remove(SEL); });
        }
        cardEls.forEach(function (c) { c.classList.add(SEL); });
        announce(queue);
    }

    function clearSelection(queue) {
        cards(queue).forEach(function (c) { c.classList.remove(SEL); });
        stateOf(queue).anchor = null;
        announce(queue);
    }

    function handleSelectionClick(queue, card, ev) {
        const st = stateOf(queue);
        if (ev.shiftKey && st.anchor) {
            // MAJ = toute la plage entre l'ancre et la cible, dans l'ORDRE VISIBLE.
            // ⚠ `cards()` traverse les lots repliés : la plage inclut leurs filles, ce qui est
            // le comportement voulu (elles font partie de la file, cf. la même décision dans
            // `wama-queue.js::_pileFor` — filtrer sur la visibilité avait rendu les cards d'un
            // lot replié injoignables).
            const list = cards(queue);
            const a = list.indexOf(st.anchor), b = list.indexOf(card);
            if (a >= 0 && b >= 0) {
                const range = list.slice(Math.min(a, b), Math.max(a, b) + 1);
                setSelection(queue, range, ev.ctrlKey || ev.metaKey ? 'ajouter' : 'remplacer');
                return true;
            }
        }
        if (ev.ctrlKey || ev.metaKey) {
            card.classList.toggle(SEL);
            st.anchor = card;
            announce(queue);
            return true;
        }
        // Clic simple : sélection unique. On laisse l'événement suivre son cours — c'est lui
        // qui remplit l'inspecteur, et le lui retirer casserait le geste central de WAMA.
        setSelection(queue, [card], 'remplacer');
        st.anchor = card;
        return false;
    }

    // ══ INDICATEUR DE DÉPÔT ══════════════════════════════════════════════════════════════
    //
    // Deux retours visuels DISTINCTS parce que les deux gestes le sont : une barre INSÉRÉE
    // entre deux éléments (on change l'ordre), un cadre AUTOUR d'une card (on change
    // l'appartenance). Un seul indicateur pour les deux rendrait le geste indevinable —
    // l'utilisateur ne saurait pas, au moment de lâcher, ce qui va se passer.

    function marker() {
        let m = document.getElementById('wamaDndMarker');
        if (!m) {
            m = document.createElement('div');
            m.id = 'wamaDndMarker';
            m.className = 'wama-dnd-marker';
        }
        return m;
    }

    function clearFeedback() {
        const m = document.getElementById('wamaDndMarker');
        if (m && m.parentNode) m.parentNode.removeChild(m);
        document.querySelectorAll('.wama-dnd-over').forEach(function (el) {
            el.classList.remove('wama-dnd-over');
        });
        document.querySelectorAll('.wama-dnd-refuse').forEach(function (el) {
            el.classList.remove('wama-dnd-refuse');
        });
    }

    // ── Où le curseur tombe-t-il ? ───────────────────────────────────────────────────────
    //
    // Retourne une CIBLE décrivant le geste qui aura lieu si on lâche ici :
    //   {type:'sur',   card}                 → appartenance (move_to_batch / merge)
    //   {type:'entre', parent, avant, niveau} → ordre (reorder_queue / reorder)
    //
    // Le seuil : le tiers HAUT et le tiers BAS d'une card valent « entre », le tiers médian
    // vaut « sur ». Un demi/demi (le réflexe) ne laisserait AUCUNE zone au geste de fusion, qui
    // est pourtant le plus demandé des quatre.

    function targetUnder(queue, x, y) {
        const el = document.elementFromPoint(x, y);
        if (!el || !queue.contains(el)) {
            // Hors de toute card mais dans la file : on ordonne, en fin de file.
            return { type: 'entre', parent: queue, avant: null, niveau: 'queue' };
        }
        const cardEl = el.closest('.wama-card[data-id], .wama-card.is-batch');
        if (!cardEl) {
            const grp = el.closest('.batch-group');
            if (grp) return { type: 'sur', card: grp.querySelector('.wama-card.is-batch') || grp };
            return { type: 'entre', parent: queue, avant: null, niveau: 'queue' };
        }
        const r = cardEl.getBoundingClientRect();
        const third = r.height / 3;
        if (y > r.top + third && y < r.bottom - third) return { type: 'sur', card: cardEl };

        const beforeCard = y <= r.top + third;
        // Fille de lot → on ordonne DANS le lot. Sinon → on ordonne la file.
        const collapse = cardEl.closest('.collapse[data-wama-batch-key]');
        if (collapse && !cardEl.classList.contains('is-batch')) {
            return { type: 'entre', parent: collapse, niveau: 'batch',
                     avant: beforeCard ? cardEl : cardEl.nextElementSibling };
        }
        const entryEl = entryOf(cardEl) || cardEl;
        return { type: 'entre', parent: queue, niveau: 'queue',
                 avant: beforeCard ? entryEl : entryEl.nextElementSibling };
    }

    // ══ MONTAGE D'UNE FILE ═══════════════════════════════════════════════════════════════

    function mount(queue) {
        if (queue._wamaDndMonte) return;
        queue._wamaDndMonte = true;

        const urls = {
            reorder:     queue.dataset.dndReorderUrl || null,
            reorderQueue: queue.dataset.dndReorderQueueUrl || null,
            move:        queue.dataset.dndMoveUrl || null,
            remove:      queue.dataset.dndRemoveUrl || null,
            merge:       queue.dataset.dndMergeUrl || null,
        };

        // ── Sélection ────────────────────────────────────────────────────────────────────
        queue.addEventListener('click', function (ev) {
            // Un clic sur un bouton, un lien ou un champ n'est PAS un geste de sélection.
            // Sans ce garde, Ctrl+clic sur ⚙ aurait sélectionné la card en plus d'ouvrir la
            // modale — et Maj+clic sur ▶ aurait lancé toute une plage.
            if (ev.target.closest('button, a, input, select, textarea, label, [data-bs-toggle]')) return;
            const card = ev.target.closest('.wama-card[data-id]');
            if (!card || card.classList.contains('is-batch')) return;
            if (handleSelectionClick(queue, card, ev)) {
                // Étendue : on garde l'événement pour nous (l'inspecteur ne doit pas
                // retomber sur une sélection unique derrière notre dos).
                ev.preventDefault();
                ev.stopPropagation();
            }
        }, true);

        // Échap : on relâche. Même touche que la désélection de l'inspecteur — un seul geste
        // d'abandon, puisqu'il n'y a qu'une sélection.
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape' && selectedCards(queue).length) clearSelection(queue);
        });

        // ── Drag ─────────────────────────────────────────────────────────────────────────
        // `draggable` est posé par le JS et non par les gabarits : c'est une CAPACITÉ de la
        // brique, pas une propriété des cards. Les 12 gabarits n'ont ainsi rien à déclarer, et
        // une file sans `data-wama-dnd` reste inerte.
        function arm() {
            cards(queue).forEach(function (c) { c.draggable = true; });
            const headerCards = queue.querySelectorAll('.wama-card.is-batch');
            Array.prototype.forEach.call(headerCards, function (m) { m.draggable = false; });
        }
        arm();
        new MutationObserver(arm).observe(queue, { childList: true, subtree: true });

        let carried = [];      // cards en cours de déplacement

        queue.addEventListener('dragstart', function (ev) {
            const card = ev.target.closest('.wama-card[data-id]');
            if (!card || card.classList.contains('is-batch')) return;
            // Glisser une card HORS sélection déplace CETTE card et repart d'une sélection
            // propre : c'est ce que fait tout gestionnaire de fichiers, et l'inverse
            // (emporter une sélection invisible qu'on croyait oubliée) surprend toujours.
            if (!card.classList.contains(SEL)) setSelection(queue, [card], 'remplacer');
            carried = selectedCards(queue);
            queue.classList.add('wama-dnd-active');
            try {
                ev.dataTransfer.effectAllowed = 'move';
                // Un payload est OBLIGATOIRE sous Firefox, sinon aucun `drop` n'est émis.
                ev.dataTransfer.setData('text/plain', carried.map(function (c) { return c.dataset.id; }).join(','));
            } catch (e) { /* certains navigateurs verrouillent dataTransfer */ }
        });

        queue.addEventListener('dragend', function () {
            queue.classList.remove('wama-dnd-active');
            clearFeedback();
            carried = [];
        });

        queue.addEventListener('dragover', function (ev) {
            if (!carried.length) return;
            ev.preventDefault();
            ev.dataTransfer.dropEffect = 'move';
            clearFeedback();

            const target = targetUnder(queue, ev.clientX, ev.clientY);
            if (target.type === 'sur') {
                // Déposer sur une card qu'on porte soi-même ne veut rien dire.
                if (carried.indexOf(target.card) >= 0) return;
                // ⚠ On ne touche PAS à `title` pour dire le refus : la card en a déjà un
                // (« Double-cliquez pour voir le résultat »…) et l'écraser le perdrait
                // définitivement — un retour visuel transitoire ne doit rien détruire de
                // permanent. La classe suffit à l'écran, le motif exact arrive au toast.
                target.card.classList.add(refusalFor(target, urls) ? 'wama-dnd-refuse' : 'wama-dnd-over');
                return;
            }
            const m = marker();
            m.classList.toggle('is-in-batch', target.niveau === 'batch');
            target.parent.insertBefore(m, target.avant);
        });

        queue.addEventListener('drop', function (ev) {
            if (!carried.length) return;
            ev.preventDefault();
            // ⚠ NETTOYER AVANT DE VISER. `cibleSous` interroge `elementFromPoint`, et le
            // marqueur d'insertion du dernier `dragover` est encore SOUS le curseur : le
            // laisser en place faisait viser le marqueur au lieu de la card, donc retomber
            // dans la branche « hors de toute card » — un dépôt sur une card se serait
            // comporté comme un dépôt en fin de file. Défaut invisible au relevé du code,
            // évident dès qu'on lâche la souris.
            clearFeedback();
            const target = targetUnder(queue, ev.clientX, ev.clientY);
            const movedCards = carried.slice();
            queue.classList.remove('wama-dnd-active');
            carried = [];
            if (target.type === 'sur' && movedCards.indexOf(target.card) >= 0) return;
            run(queue, urls, target, movedCards);
        });
    }

    /** Motif de refus d'un dépôt SUR une card, ou '' si le geste est possible.
     *
     * ⚠ Ne dit RIEN de la compatibilité des natures : elle est décidée côté SERVEUR, par le
     * `group_key` que l'app déclare (`queue_manipulation._refus_de_groupe`). La recopier ici
     * demanderait de publier la règle au DOM et créerait une seconde source — exactement ce
     * que le jumelage `nature_of`/`group_key` vient d'éviter. Le refus arrive donc en 409 et
     * se dit au toast : un aller-retour, mais UNE seule règle.
     */
    function refusalFor(target, urls) {
        const onBatchHeader = target.card.classList.contains('is-batch');
        const inBatch = !!target.card.closest('.batch-group');
        if (onBatchHeader || inBatch) return urls.move ? '' : "Déplacement dans un lot indisponible ici";
        return urls.merge ? '' : "Formation de lot indisponible ici";
    }

    // ══ EXÉCUTION ════════════════════════════════════════════════════════════════════════
    //
    // ⚠ SÉQUENTIEL, jamais en parallèle. Ces endpoints se marchent dessus : `move_to_batch`
    // recalcule le total du lot et peut le SUPPRIMER s'il se vide, et les signaux `batch_sync`
    // tournent à chaque écriture. Deux POST concurrents sur le même lot produisent un total
    // faux — ou un 404 sur le lot que le premier vient d'effacer. Le coût (N allers-retours
    // pour N cards) est celui d'un geste rare et délibéré, pas d'une boucle de polling.

    function run(queue, urls, target, carriedCards) {
        if (!carriedCards.length) return;
        const ids = carriedCards.map(function (c) { return c.dataset.id; });

        // ── APPARTENANCE : déposer SUR une card ──────────────────────────────────────────
        if (target.type === 'sur') {
            const group = target.card.closest('.batch-group');
            if (group) {
                // → ENTRER dans un lot existant (mère ou fille : c'est le même lot).
                if (!urls.move) return fail("Déplacement dans un lot indisponible ici");
                const bid = group.dataset.batchId;
                if (!bid) return fail("Lot cible introuvable");
                return chain(ids, function (id) {
                    return post(withPk(urls.move, id), { batch_id: bid });
                }).then(function (refusal) {
                    if (refusal) return fail(refusal);
                    succeed(ids.length + " élément(s) ajouté(s) au lot");
                });
            }
            // → FORMER un NOUVEAU lot : la card cible + les cards portées, dans l'ordre où
            // l'utilisateur les voit (cible d'abord), pas dans l'ordre où il les a cliquées.
            if (!urls.merge) return fail("Formation de lot indisponible ici");
            const targetId = target.card.dataset.id;
            const allIds = [targetId].concat(ids.filter(function (i) { return i !== targetId; }));
            if (allIds.length < 2) return;
            // ⚠ Champs RÉPÉTÉS, jamais CSV : `_ids_de_la_requete` lit `ids[]`/`ids` en liste ou
            // un corps JSON — un CSV lui donnerait UN id non numérique, donc zéro élément et un
            // `{"consolidated": false}` parfaitement SILENCIEUX.
            const fd = new FormData();
            allIds.forEach(function (i) { fd.append('ids', i); });
            return fetch(urls.merge, {
                method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: fd,
            }).then(function (r) { return r.json().catch(function () { return {}; }); })
              .then(function (d) {
                  if (d && d.consolidated) return succeed("Lot formé (" + allIds.length + " éléments)");
                  fail(d && d.reason ? d.reason
                                      : "ces éléments ne peuvent pas former un lot ensemble");
              });
        }

        // ── ORDRE : déposer ENTRE deux cards ─────────────────────────────────────────────
        if (target.niveau === 'batch') {
            // Réordonner DANS un lot — en y faisant ENTRER au passage ce qui vient d'ailleurs.
            const collapse = target.parent;
            const group = collapse.closest('.batch-group');
            const bid = group && group.dataset.batchId;
            if (!bid) return;
            const outsiders = carriedCards.filter(function (c) { return groupOf(c) !== group; });
            const enterBatch = (outsiders.length && urls.move)
                ? chain(outsiders.map(function (c) { return c.dataset.id; }), function (id) {
                      return post(withPk(urls.move, id), { batch_id: bid });
                  })
                : Promise.resolve(null);
            return enterBatch.then(function (refusal) {
                if (refusal) return fail(refusal);
                // Une entrée dans le lot CHANGE les totaux et la card mère : seul le serveur
                // sait les recomposer. Un simple réordonnancement, lui, se voit à l'écran.
                if (outsiders.length) return succeed(outsiders.length + " élément(s) ajouté(s) au lot");
                applyToDom(target, carriedCards);
                if (!urls.reorder) return;
                const order = Array.prototype.slice
                    .call(collapse.querySelectorAll('.wama-card[data-id]'))
                    .map(function (c) { return c.dataset.id; });
                return post(urls.reorder, { batch_id: bid, order: order.join(',') })
                    .then(function (d) { if (d && d.reordered === false) fail("ordre refusé"); });
            });
        }

        // Niveau FILE. Ce qui sort d'un lot en sort VRAIMENT (remove_from_batch).
        const toDetach = carriedCards.filter(groupOf);
        if (toDetach.length) {
            if (!urls.remove) return fail("Sortie de lot indisponible ici");
            return chain(toDetach.map(function (c) { return c.dataset.id; }), function (id) {
                return post(withPk(urls.remove, id), {});
            }).then(function (refusal) {
                if (refusal) return fail(refusal);
                // Sortir RECOMPOSE la file côté serveur : le lot d'origine peut disparaître,
                // un batch-of-1 naît, la card mère change de compte. Aucun réarrangement DOM
                // ne rend cet état fidèlement — on recharge, comme `queue-actions.js` le fait
                // sur `batch_changed`.
                succeed(toDetach.length + " élément(s) sorti(s) du lot");
            });
        }

        // Pur réordonnancement de la file : l'écran est déjà juste, on ne recharge PAS.
        applyToDom(target, carriedCards);
        if (!urls.reorderQueue) return;
        const order = entries(queue).map(batchIdOf).filter(Boolean);
        if (!order.length) return;
        return post(urls.reorderQueue, { order: order.join(',') })
            .then(function (d) {
                if (!d || d.reordered === false) return;
                switchToManualSort();
            });
    }

    /** Applique le déplacement au DOM (UI optimiste — §3bis : « ne pas écraser un drag en cours »). */
    function applyToDom(target, carriedCards) {
        // Une card unitaire se déplace AVEC son enrobage d'entrée, sinon on la sortirait de
        // ce qui porte son id de lot — et l'ordre envoyé au serveur perdrait cette entrée.
        carriedCards.forEach(function (c) {
            const node = (target.niveau === 'queue' && c.parentElement
                           && c.parentElement.classList.contains('wama-queue-entry'))
                ? c.parentElement : c;
            target.parent.insertBefore(node, target.avant);
        });
    }

    /** Enchaîne des POST, s'arrête au premier refus, rend le motif (ou null). */
    function chain(ids, fn) {
        return ids.reduce(function (p, id) {
            return p.then(function (refusal) {
                if (refusal) return refusal;
                return fn(id).then(function (d) {
                    if (d && (d.moved === false || d.unwrapped === false
                              || d.consolidated === false)) {
                        return d.reason || 'refusé';
                    }
                    return null;
                });
            });
        }, Promise.resolve(null));
    }

    function fail(reason) { toast("Déplacement impossible — " + reason, 'error'); }

    /** Succès qui CHANGE la composition des lots → le serveur seul sait rendre le nouvel état. */
    function succeed(message) {
        try { sessionStorage.setItem('wama_dnd_message', message); } catch (e) {}
        location.reload();
    }

    /**
     * Bascule la file sur le tri « Manuel ».
     *
     * L'ordre manuel n'a d'effet à l'AFFICHAGE que sous ce tri : sans cette bascule, le geste
     * « marcherait » puis disparaîtrait au rechargement suivant — une manipulation qui ment,
     * pire qu'une manipulation absente.
     *
     * On passe par le sélecteur de la barre d'outils, seul détenteur du geste (il pose
     * `?sort=…`, que la vue persiste en session). Déjà sur « Manuel » → RIEN à faire : l'écran
     * et le serveur sont d'accord, et recharger effacerait le réarrangement qu'on vient de
     * montrer.
     */
    function switchToManualSort() {
        const sel = document.querySelector('.wama-queue-toolbar select[onchange*="sort="]');
        if (!sel || sel.value === 'manual' || !sel.querySelector('option[value="manual"]')) return;
        sel.value = 'manual';
        sel.dispatchEvent(new Event('change'));
    }

    // ── Message reporté après rechargement ───────────────────────────────────────────────
    function deferredMessage() {
        let m = null;
        try { m = sessionStorage.getItem('wama_dnd_message'); sessionStorage.removeItem('wama_dnd_message'); }
        catch (e) { return; }
        if (m) toast(m, 'success');
    }

    // ══ Ctrl+A — TOUT SÉLECTIONNER ═══════════════════════════════════════════════════════
    //
    // Posé UNE fois sur le document, pas une fois par file : plusieurs apps en affichent deux
    // (enhancer média+audio, imager image+vidéo), et un écouteur par file aurait sélectionné
    // dans les DEUX d'un coup — dont celle de l'onglet caché, invisible à l'utilisateur.
    //
    // ⚠ On lit `ev.key`, JAMAIS `ev.code`. Sur un clavier AZERTY — celui de ce labo — le A
    // est physiquement à la place du Q QWERTY : `ev.code` y vaut `KeyQ`. `ev.key` rend le
    // caractère RÉELLEMENT produit par la disposition, donc 'a' partout.

    /** La file à laquelle un raccourci s'applique. */
    function activeQueue() {
        const queues = Array.prototype.slice.call(document.querySelectorAll('[data-wama-dnd]'));
        if (!queues.length) return null;
        // 1. Celle qui porte déjà une sélection — on poursuit là où l'utilisateur travaille.
        const withSelection = queues.find(function (q) { return q.querySelector('.' + SEL); });
        if (withSelection) return withSelection;
        // 2. Sinon la file VISIBLE. Même règle que les flèches de `wama-queue.js` : sur une
        //    page à onglets, une seule file est à l'écran, et c'est celle-là qui répond.
        const visibleQueues = queues.filter(function (q) { return q.offsetParent !== null; });
        return visibleQueues[0] || queues[0];
    }

    function initSelectAll() {
        document.addEventListener('keydown', function (ev) {
            if (!(ev.ctrlKey || ev.metaKey) || ev.altKey || ev.shiftKey) return;
            if ((ev.key || '').toLowerCase() !== 'a') return;
            // Ne JAMAIS voler le Ctrl+A d'une saisie : dans un champ, il veut dire « tout le
            // texte », et c'est ce que l'utilisateur attend jusque dans une file.
            const t = ev.target;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
            const q = activeQueue();
            if (!q) return;
            const everyCard = cards(q);
            // File vide : on ne préempte RIEN. Avaler le raccourci pour ne rien sélectionner
            // priverait de la sélection de page sans aucune contrepartie.
            if (!everyCard.length) return;
            ev.preventDefault();
            setSelection(q, everyCard, 'remplacer');
            // Ancre en TÊTE : un Maj+clic qui suit réduit alors la sélection du haut jusqu'à
            // la card cliquée — le geste attendu après un « tout sélectionner ».
            stateOf(q).anchor = everyCard[0];
        });
    }

    // ── Init ─────────────────────────────────────────────────────────────────────────────
    function init() {
        document.querySelectorAll('[data-wama-dnd]').forEach(mount);
        initSelectAll();
        deferredMessage();
    }

    window.WamaQueueDnd = {
        selectedCards: function (queue) { return selectedIds(queue || document.querySelector('[data-wama-dnd]')); },
        clear: function (queue) { clearSelection(queue || document.querySelector('[data-wama-dnd]')); },
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
