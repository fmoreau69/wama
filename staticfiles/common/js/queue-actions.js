/**
 * WAMA — Gestionnaire générique d'actions de file d'attente
 *
 * DOMICILE UNIQUE des actions de card. Ce fichier héberge TOUTES les actions possibles d'une
 * card et les distribue selon le besoin de l'app : une app qui ne rend pas le bouton n'a rien à
 * désactiver, une app qui le rend n'a rien à câbler. Ajouter une action ici, jamais dans l'app.
 *
 * Actions gérées :
 *   ⧉ Dupliquer  → <button class="… duplicate-btn" data-duplicate-url="{% url 'app:duplicate' o.id %}">
 *   🗑 Supprimer  → <button class="… delete-btn"    data-delete-url="{% url 'app:delete' o.id %}">
 *   ⚙ Paramètres → <button class="… settings-btn"  data-id="{{ o.id }}">
 *                  + côté app, UNE ligne : WamaQueueActions.onSettings((id, btn) => …)
 *
 * Hooks optionnels (une spécificité se DÉCLARE) — tous deux acceptent `{within: '<sélecteur>'}`
 * pour être scopés à une famille de cards, l'ouvreur/la suite sans `within` servant de défaut :
 *   WamaQueueActions.onDeleted((id, data, btn) => …)   suite après suppression, au lieu du reload
 *
 * POURQUOI ⚙ N'EST PAS UN POST (et pourquoi la brique s'arrête au clic). Dupliquer et supprimer
 * SONT l'action : une URL, un POST, un rechargement — la brique peut tout faire. ⚙ ne fait
 * qu'OUVRIR une modale dont le contenu est propre à l'app (schéma, hooks decorate/collect/
 * onSaved de `WamaParams.settingsModal`). La brique possède donc exactement ce qui divergeait —
 * la GRAPHIE du bouton et la DÉLÉGATION du clic — et délègue l'ouverture à l'app. C'est le même
 * partage que `wama-cycle-button.js` : le bouton est commun, le verbe reste à l'app.
 *
 * Une SEULE délégation par action, posée sur le document. C'est ce qui satisfait l'intention de
 * CARD_DESIGN §3 (« un seul handler par file plutôt que N handlers ») : le mal visé y est le
 * double-fire né de N handlers accrochés par N apps, pas le fait que le sélecteur soit une
 * classe. Le nommage reste donc `.delete-btn`, symétrique de `.duplicate-btn` — deux boutons
 * voisins dans la même piste ACTIONS doivent porter le même genre de contrat (arbitrage Fabien,
 * 2026-08-22). Adopter `data-action` pour la seule suppression aurait fait cohabiter deux
 * contrats sur deux boutons côte à côte : moins homogène, pas plus.
 *
 * POURQUOI CETTE BRIQUE EXISTE (mesuré le 2026-08-22). La duplication, qui était déjà ici, est
 * uniforme sur 12 cards sur 12. La suppression, qui n'y était PAS, comptait SIX graphies pour
 * dix apps : `delete-btn` (6), `job-delete-btn` (converter ×2), `btn-delete-job` (avatarizer),
 * `js-audio-delete` et `js-delete-enhancement` (enhancer), `video-delete-btn` (imager vidéo),
 * et `data-action="delete"` sans classe (reader). Deux boutons côte à côte dans la même card,
 * l'un uniforme et l'autre éclaté : la divergence n'est pas une négligence de style, c'est la
 * conséquence mécanique de l'absence de brique.
 *
 * ⚙ A REFAIT LE MÊME PARCOURS (relevé du 2026-08-23). Six graphies pour dix apps :
 * `settings-btn` (anonymizer, composer, describer, imager image, synthesizer, transcriber),
 * `video-settings-btn` (imager vidéo), `job-settings-btn` (converter), `btn-settings-job`
 * (avatarizer), `js-open-settings` + `js-audio-settings` (enhancer), `data-action="settings"`
 * sans classe (reader). Exactement le compte de la suppression, pour exactement la même raison.
 *
 * ⚠ ET LA DIVERGENCE AVAIT DÉJÀ CONTAMINÉ UNE BRIQUE COMMUNE : le `cardSettings` par défaut de
 * `wama-inspector.js` devait porter en dur l'UNION des graphies
 * (`'.settings-btn, [data-action="settings"], .btn-settings-job, .job-settings-btn'`) pour
 * retrouver le bouton ⚙ d'une card quelle que soit l'app. Une liste de graphies d'apps écrite
 * dans le substrat est le symptôme le plus net qu'il manquait une brique ici : c'est le coût que
 * la divergence finit toujours par facturer au commun. Cette union se réduit à `.settings-btn`
 * une fois les 10 apps portées.
 */

(function () {
    'use strict';

    function getCsrf() {
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    function poster(url) {
        return fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrf(),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({}),
        });
    }

    // Un 204 (No Content) est un succès sans corps : `r.json()` y lèverait. Les vues WAMA
    // répondent tantôt en JSON, tantôt en 204 — on accepte les deux plutôt que d'imposer une
    // graphie de réponse aux 10 apps (même raison que le repli `id`/`job_id`/`pk` du trou #24).
    function lireReponse(r) {
        if (r.status === 204) return Promise.resolve({ success: true });
        return r.json().catch(function () { return { success: r.ok }; });
    }

    // ── Scoper une déclaration : par DOMAINE, jamais par sélecteur d'app ────────────────
    //
    // ⚠ REMPLACE `within: '#audio-enhancer-queue'` (2026-08-23). Ce `within` marchait, mais il
    // écrivait un id CSS d'app dans la déclaration d'une app — donc il ne se propageait pas : la
    // prochaine app à plusieurs domaines aurait dû inventer le sien. Le domaine, lui, est déjà
    // DÉCLARÉ (app_modes.py) et porté au DOM (`data-domain` sur la card et la card mère de lot),
    // donc la brique peut s'y scoper sans rien connaître d'aucune app.
    //
    // `within` reste accepté en ÉCHAPPATOIRE pour un cas qui ne serait pas un domaine — mais
    // aucun ne l'utilise, et en introduire un doit être un choix motivé, pas un réflexe.
    function domaineDe(el) {
        const hote = el && el.closest('[data-domain]');
        return hote ? hote.dataset.domain : null;
    }

    function correspond(btn, o) {
        if (o.domain && domaineDe(btn) !== o.domain) return false;
        if (o.within && !btn.closest(o.within)) return false;
        return true;
    }

    // Le plus SPÉCIFIQUE d'abord (domaine ou within), le défaut en dernier : sans cet ordre, une
    // déclaration sans scope masquerait une déclaration scopée écrite après elle.
    function choisir(liste, btn) {
        const scopes = liste.filter(function (o) { return o.domain || o.within; });
        for (let i = 0; i < scopes.length; i++) {
            if (correspond(btn, scopes[i])) return scopes[i].handler;
        }
        const defauts = liste.filter(function (o) { return !o.domain && !o.within; });
        return defauts.length ? defauts[0].handler : null;
    }

    // ── ⧉ DUPLIQUER ────────────────────────────────────────────────────────────────────
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.duplicate-btn[data-duplicate-url]');
        if (!btn) return;

        const url = btn.dataset.duplicateUrl;
        if (!url) return;

        btn.disabled = true;
        const icon = btn.querySelector('i');
        if (icon) { icon.className = 'fas fa-spinner fa-spin'; }

        poster(url)
        .then(lireReponse)
        .then(function (data) {
            if (data.duplicated || data.success) {
                // Focus la card dupliquée après rechargement (WamaQueue.focusFromSession) —
                // comportement remonté du transcriber (03/08) : la repérer facilement,
                // surtout sortie/isolée d'un batch ou si elle n'atterrit pas en tête.
                if (data.duplicated && data.duplicated !== true) {
                    try {
                        sessionStorage.setItem('wama_focus_card',
                            '.wama-card[data-id="' + data.duplicated + '"]');
                    } catch (e) { /* stockage indisponible */ }
                }
                location.reload();
            } else {
                alert(data.error || 'Duplication impossible');
                btn.disabled = false;
                if (icon) { icon.className = 'fas fa-copy'; }
            }
        })
        .catch(function () {
            alert('Erreur réseau lors de la duplication');
            btn.disabled = false;
            if (icon) { icon.className = 'fas fa-copy'; }
        });
    });

    // ── 🗑 SUPPRIMER ───────────────────────────────────────────────────────────────────
    //
    // ── Ce qui suit une suppression réussie ────────────────────────────────────────────
    //
    // ⚠ CORRECTION DU 2026-08-23 (remarque de Fabien, le jour même du premier jet). La première
    // version laissait CHAQUE app écrire sa propre suite via un hook, au motif d'une
    // « spécificité légitime ». **C'était faux, et la méthode qui m'y a mené est l'erreur que ce
    // dépôt répète de ne pas faire** : j'ai lu neuf NOMS DE FONCTIONS différents et j'en ai
    // déduit neuf comportements. Mises côte à côte, les neuf suites faisaient EXACTEMENT ceci —
    //
    //     batch_changed → recharger · retirer la card · retirer le groupe de lot s'il est vide ·
    //     remettre l'état vide · rafraîchir le compteur · signaler au gestionnaire de fichiers
    //
    // — un seul algorithme, recopié. La brique le tient donc elle-même, et l'app ne déclare plus
    // que le RÉSIDU. Le test du skill /brique (« que doit écrire la prochaine app ? ») passait de
    // douze lignes à une ou deux : c'est ce chiffre qui dit si une brique est une brique.
    //
    // CE QUI RESTE VRAIMENT À L'APP, ET POURQUOI CE N'EST PAS UNE SPÉCIFICITÉ. Arrêter le
    // polling de l'élément supprimé et rafraîchir un compteur d'en-tête. La brique ne peut pas
    // le faire tant que le poller vit dans une variable d'app — or `WamaApp.Poller` EXISTE et
    // n'est adopté que par 4 apps sur 10 (transcriber, enhancer, imager, reader ; mesuré le
    // 2026-08-23). Ce résidu n'est donc pas une divergence légitime : c'est **la trace d'un
    // mécanisme commun non encore adopté**, et il disparaîtra à mesure de son adoption. Le noter
    // ainsi, plutôt que « spécificité de l'app », est ce qui garde le chantier visible.
    const suites = [];

    function onDeleted(handler, options) {
        if (typeof handler !== 'function') return;
        const o = options || {};
        suites.push({ handler: handler, domain: o.domain || null, within: o.within || null });
    }

    // Spécifique d'abord, défaut ensuite — cf. le choix d'ouvreur côté ⚙, même règle. Le registre
    // (et non un slot unique) est indispensable : l'enhancer déclare DEUX suites, dans deux
    // fichiers JS séparés — un slot aurait laissé la seconde écraser la première en silence.
    function choisirSuite(btn) { return choisir(suites, btn); }

    function signalerAuGestionnaire() {
        if (window.WamaFM && WamaFM.deleted) WamaFM.deleted();   // l'arborescence se rafraîchit
    }

    // Séquence STANDARD — le DOM commun suffit à la conduire : `.wama-card[data-id]` est porté
    // par les 11 cards du dépôt (vérifié le 2026-08-23), `.batch-group` par tous les lots.
    // Retourne true si la page se recharge (l'appelant n'a alors plus rien à faire).
    function suiteStandard(id, btn) {
        const card = document.querySelector('.wama-card[data-id="' + id + '"]')
                  || (btn && btn.closest('.wama-card'));
        const groupe = card && card.closest('.batch-group');
        if (card) card.remove();
        // Un lot vidé de ses enfants n'a plus d'objet : le laisser afficherait un groupe fantôme.
        if (groupe && !groupe.querySelector('.wama-card[data-id]')) groupe.remove();
        if (window.WamaEta && WamaEta.reset) WamaEta.reset(id);
        signalerAuGestionnaire();
    }

    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.delete-btn[data-delete-url]');
        if (!btn) return;

        const url = btn.dataset.deleteUrl;
        if (!url) return;

        // Confirmation CENTRALISÉE : chaque app réécrivait la sienne, avec des libellés
        // différents et parfois aucune. `data-confirm` permet un message propre à l'app
        // (« supprimer aussi le fichier source ? ») ; `data-confirm="false"` la supprime
        // quand la suppression est déjà gardée en amont.
        const demande = btn.dataset.confirm;
        if (demande !== 'false'
            && !window.confirm(demande || 'Supprimer cet élément ? Cette action est définitive.')) {
            return;
        }

        btn.disabled = true;
        const icon = btn.querySelector('i');
        const iconeInitiale = icon ? icon.className : '';
        if (icon) { icon.className = 'fas fa-spinner fa-spin'; }

        poster(url)
        .then(lireReponse)
        .then(function (data) {
            if (data.deleted || data.success || data.status === 'deleted') {
                const id = btn.dataset.id;
                // Élément issu d'un LOT : le total et l'affichage de la card mère sont recalculés
                // côté serveur (un lot réduit à 1 redevient une card simple) — seul un
                // rechargement rend cet état correctement. Les 9 apps faisaient déjà exactement
                // ce test, à l'identique.
                if (data.batch_changed) { signalerAuGestionnaire(); location.reload(); return; }
                suiteStandard(id, btn);
                // Résidu déclaré par l'app (arrêt du polling, compteur d'en-tête) — voir plus haut
                // pourquoi ce n'est pas une spécificité mais un mécanisme commun non encore adopté.
                const suite = choisirSuite(btn);
                if (suite) suite(id, data, btn);
            } else {
                alert(data.error || 'Suppression impossible');
                btn.disabled = false;
                if (icon) { icon.className = iconeInitiale; }
            }
        })
        .catch(function () {
            alert('Erreur réseau lors de la suppression');
            btn.disabled = false;
            if (icon) { icon.className = iconeInitiale; }
        });
    });

    // ── ⚙ PARAMÈTRES ──────────────────────────────────────────────────────────────────
    //
    // L'app déclare SON ouvreur ; la brique tient le sélecteur et la délégation.
    //
    //   WamaQueueActions.onSettings(function (id, btn) { openSettingsModal(id); });
    //
    // `within` (optionnel) restreint l'ouvreur à un type de card — c'est ce qui permet à une app
    // à DEUX familles de cards (enhancer : audio / amélioration ; converter : job / média) d'en
    // déclarer deux sans que la brique connaisse une seule app. Le premier ouvreur dont le
    // `within` correspond gagne ; un ouvreur sans `within` sert de défaut, et il est évalué en
    // DERNIER pour ne jamais masquer un ouvreur plus spécifique déclaré après lui.
    const ouvreurs = [];

    function onSettings(handler, options) {
        if (typeof handler !== 'function') return;
        const o = options || {};
        ouvreurs.push({ handler: handler, domain: o.domain || null, within: o.within || null });
    }

    document.addEventListener('click', function (e) {
        // `.settings-btn` est un sélecteur de CLASSE : il matche le jeton exact et NE matche
        // donc ni `.batch-settings-btn` (bouton de lot, card mère) ni `save-settings-btn`
        // (pied de modale). C'est le piège de sous-chaîne du 2026-08-22 — réel côté grep et
        // côté `[class$=…]`, inexistant en CSS. Ne pas « durcir » ce sélecteur : ce serait
        // corriger un défaut qui n'existe pas ici.
        const btn = e.target.closest('.settings-btn[data-id]');
        if (!btn) return;

        const id = btn.dataset.id;
        if (!id) return;

        const ouvreur = choisir(ouvreurs, btn);
        if (ouvreur) { ouvreur(id, btn); return; }

        // Aucun ouvreur : le bouton est rendu mais rien ne l'écoute — c'est l'« écran mort »
        // que la grille d'adoption ne voit pas (WAMA_VERIFICATION §1). On le DIT, plutôt que
        // d'avaler le clic en silence.
        console.warn('[queue-actions] ⚙ cliqué (#' + id + ') mais aucune app n\'a déclaré '
                     + "d'ouvreur — appeler WamaQueueActions.onSettings(fn) au chargement.");
    });

    // ══ ACTIONS DE LOT ═══════════════════════════════════════════════════════════════════
    //
    // Le partial `common/_batch_card.html` rend les boutons de lot depuis le 22/07 : leur
    // NOMMAGE était donc uniforme par construction, `.batch-<action>-btn[data-batch-id]`. C'est
    // exactement ce qui a masqué le problème — **30 handlers écrits dans 8 apps** (mesuré le
    // 2026-08-23), pour trois actions qui font partout la même chose :
    //
    //     supprimer  → confirmation + POST + rechargement
    //     dupliquer  → POST + rechargement
    //     lancer     → POST + rechargement
    //
    // Leçon jumelle de celle des cards : au niveau ÉLÉMENT, c'est la divergence de nommage qui
    // signalait l'absence de brique ; au niveau LOT, le nommage venait d'un partial commun et
    // **rien ne signalait rien**. Un nommage uniforme peut donc cacher un comportement recopié —
    // il faut regarder les DEUX. C'est le cas le plus trompeur des deux.
    //
    // L'URL n'est plus construite en JS par chaque app : le partial l'émet
    // (`data-batch-<action>-url`), dérivée du nom d'app et de la convention de routes
    // `batch/<pk>/<action>/`. Une app dont la route n'existe pas ne rend pas l'attribut, donc la
    // brique ignore le bouton — pas de clic mort par accident.

    function actionDeLot(classe, attribut, options) {
        options = options || {};
        document.addEventListener('click', function (e) {
            const btn = e.target.closest('.' + classe + '[' + attribut + ']');
            if (!btn) return;
            const url = btn.getAttribute(attribut);
            if (!url) return;
            // La card mère est un toggle de repli : sans ça, agir sur un lot le replie aussi.
            e.stopPropagation();

            // Confirmation : celle de l'ACTION (défaut de la brique) OU celle que le bouton
            // DÉCLARE (`data-confirm`). Le second cas existe pour une action qui ne confirme
            // pas par défaut mais qu'une app veut protéger — le synthesizer confirmait sa
            // duplication de lot, seul des 8 ; porter sans cela aurait RETIRÉ une garde à
            // l'utilisateur au nom de l'uniformité. `data-confirm="false"` neutralise.
            const demande = btn.dataset.confirm;
            const texte = (demande && demande !== 'false') ? demande : options.confirmer;
            if (texte && demande !== 'false' && !window.confirm(texte)) return;

            btn.disabled = true;
            const icon = btn.querySelector('i');
            const iconeInitiale = icon ? icon.className : '';
            if (icon) { icon.className = 'fas fa-spinner fa-spin'; }

            poster(url)
            .then(lireReponse)
            .then(function (data) {
                if (data.error) {
                    alert(data.error);
                    btn.disabled = false;
                    if (icon) { icon.className = iconeInitiale; }
                    return;
                }
                // Suite DÉCLARÉE (▶ seulement) : si l'app la fournit, elle remplace le
                // rechargement — voir pourquoi juste au-dessus de `onBatchStarted`.
                if (options.suite) {
                    btn.disabled = false;
                    if (icon) { icon.className = iconeInitiale; }
                    if (options.suite(data, btn.dataset.batchId, btn)) return;
                }
                // Des fichiers ont disparu : l'arborescence du gestionnaire doit le savoir.
                // Repris de transcriber/describer/enhancer, qui l'appelaient chacun — un
                // rechargement ne le remplace pas (le filemanager vit dans une autre surface).
                if (options.signalerFichiers) signalerAuGestionnaire();
                // Un lot touche N cards, leurs compteurs, sa propre card mère et parfois son
                // existence même (lot vidé) : le recharger est ce que faisaient DÉJÀ les 8 apps,
                // et c'est le seul rendu correct sans réécrire l'agrégat côté client. Les rares
                // retraits chirurgicaux (transcriber retirait le `.batch-group` à la main) ne
                // sont PAS repris : sur un lot, l'agrégat à recalculer est trop large pour
                // qu'un retrait de nœud soit fiable — et 7 apps sur 8 rechargeaient déjà.
                location.reload();
            })
            .catch(function () {
                alert('Erreur réseau');
                btn.disabled = false;
                if (icon) { icon.className = iconeInitiale; }
            });
        });
    }

    actionDeLot('batch-delete-btn', 'data-batch-delete-url',
                { confirmer: 'Supprimer ce lot et tous ses éléments ? Cette action est définitive.',
                  signalerFichiers: true });
    actionDeLot('batch-duplicate-btn', 'data-batch-duplicate-url', {});

    // ▶ LOT — la seule des trois qui ne soit PAS uniforme, et c'est MESURÉ (2026-08-23) :
    //   rechargent      : avatarizer, converter, transcriber
    //   insèrent+pollent: composer, describer, enhancer — `(data.started||[]).forEach(id => …)`
    // Recharger partout aurait été une RÉGRESSION pour la seconde moitié : on perd le suivi en
    // direct du lot qu'on vient de lancer, ce qui est précisément ce qu'on regarde à ce
    // moment-là. Ne pas recharger du tout aurait cassé la première moitié.
    //
    // ⚠ C'est l'inverse du cas de la SUPPRESSION, où j'avais pris neuf copies d'un même
    // algorithme pour neuf spécificités. Ici la divergence est réelle, et c'est la MÊME
    // méthode qui l'établit : lire ce que le code FAIT après le POST, pas comment il s'appelle.
    // La règle qui en sort : mesurer d'abord, et n'ouvrir un hook que quand la mesure le montre.
    let apresLancementLot = null;

    function onBatchStarted(handler) {
        if (typeof handler === 'function') apresLancementLot = handler;
    }

    actionDeLot('batch-start-btn', 'data-batch-start-url', { suite: function (data, id, btn) {
        if (apresLancementLot) { apresLancementLot(data, id, btn); return true; }
        return false;   // pas de suite déclarée → rechargement (défaut sûr)
    } });

    // ⚙ du lot : comme pour l'élément, la brique tient le clic et l'app déclare son ouvreur —
    // la modale de lot reste propre à l'app (schéma, contexte 'batch').
    const ouvreursLot = [];

    function onBatchSettings(handler, options) {
        if (typeof handler !== 'function') return;
        const o = options || {};
        ouvreursLot.push({ handler: handler, domain: o.domain || null, within: o.within || null });
    }

    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.batch-settings-btn[data-batch-id]');
        if (!btn) return;
        e.stopPropagation();
        const id = btn.dataset.batchId;
        const ouvreur = choisir(ouvreursLot, btn);
        if (ouvreur) { ouvreur(id, btn); return; }
        console.warn('[queue-actions] ⚙ de lot cliqué (#' + id + ') mais aucun ouvreur déclaré — '
                     + 'appeler WamaQueueActions.onBatchSettings(fn).');
    });

    window.WamaQueueActions = { onSettings: onSettings, onDeleted: onDeleted,
                                onBatchSettings: onBatchSettings,
                                onBatchStarted: onBatchStarted };
})();
