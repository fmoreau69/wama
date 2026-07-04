# Audit de globalisation — Transcriber & Composer (2026-07-03)

> Audit read-only (agent) demandé par Fabien : « Transcriber est-il intégralement globalisé ?
> Puis comparer avec Composer pour vérifier son uniformisation. » Vérifié par Claude.
> Ce fichier est la CONSIGNE de référence des restes à globaliser sur les 2 apps « à finir à 100 % ».
> Complète `TRANSCRIBER_REFERENCE_AUDIT.md` (checklist 19 points) — ne le remplace pas.

**Couverture** : transcriber index.html (intégral), views.py (~95 %), js/index.js (~85 %) ;
composer index.html + _generation_card.html + views.py (intégral), js/index.js (~95 %).

---

## A. TRANSCRIBER — hardcodes restants à globaliser

### A1. Card d'entrée / file
1. ~~Script de repositionnement card « Nouvel élément » (index.html:284-288)~~ — **RÉGLÉ 2026-07-03** :
   la card reste en tête d'onglet (plus de déplacement DOM), look pointillés globalisé
   (`.wama-new-item-card`, wama-inspector.css).
2. ~~CSS card « nouveau » local (index.html:62-74)~~ — **RÉGLÉ 2026-07-03** (CSS commun ; l'ancien
   local était en partie du CSS mort, battu par le style inline de la brique).
3. **CSS « pile Solitaire » du batch replié** — index.html:27-58 (`:has(.collapse...:not(.show))`,
   box-shadows empilées, `::after "🃏 cliquer pour désempiler"`). Cible les sélecteurs du CONTRAT
   commun → à déplacer dans wama-inspector.css (seules les couleurs `.is-batch` restent app).
4. **Câblage WamaBatchImport + afterCreate** — index.html:290-306 : boilerplate identique par app.
   Cible : défaut `afterCreate` dans batch-import.js (option `autoStartUrlTemplate`).

### A2. Cards (LE plus gros gisement)
5. **Card individuelle écrite à la main ×2 dans le même template** — index.html:359-498 (card
   autonome) et 610-727 (fille de batch) : deux copies quasi identiques. Cible : partial
   `transcriber/_transcript_card.html` (pattern converter/composer).
6. **Card mère de batch hand-made** — index.html:504-604 (`.synthesis-card.is-batch` + méta +
   actions). Cible : brique commune `_batch_card.html` (déjà identifiée CARD_DESIGN §8).
7. **Dropdown formats de téléchargement dupliqué ×4** — index.html:449-469 + 683-703,
   index.js:469-479 + 1288-1294. Cible : partial `_download_formats_dropdown.html` + liste de
   formats déclarée (format_policy.py existe côté Python).
8. **Preview compacte dupliquée ×2** — index.html:486-497 et 715-726 → absorbée par le partial (5).
9. **`appendCard()` : card reconstruite en JS (~80 l.) qui DIVERGE du serveur** — index.js:259-343.
   Violation CARD_DESIGN (« partial server-side + update JS en place, PAS de rebuild »).
   Cible : endpoint « card rendue » (partial) ou reload.
10. **`rebuildActions()`** — index.js:430-502 : 3ᵉ copie du markup d'actions + save/restore manuel
    de 9 data-attributes. Absorbée par (5)+(9).

### A3. Inspecteur
11. **Bandeau inspecteur hand-codé** — index.html:77-83 alors que `common/_inspector_banner.html`
    existe (composer l'utilise). Cible : include.
12. **`_renderBatchActions` en chaînes JS** — index.js:1282-1307 (le commentaire reconnaît le
    pis-aller). Cible : brique.
13. **Sync manuelle card↔inspecteur via data-*** — index.js:774-807 + 1322-1335 : recopie
    champ-par-champ de 9 propriétés + innerHTML colonne options. = chantier
    UI_MECHANISMS_CONSOLIDATION : l'état d'item doit avoir UNE représentation (schéma).

### A4. Modale
14. Modale paramètres schéma-driven ✅ (WamaParams + pied commun). Restes : **backups
    `{% comment %}`** à purger — index.html:89-187 (ancien volet) et 769-773 (poids mort → dérive).
15. **Modale « Info prétraitement »** — index.html:872-898 : styles inline fond blanc/texte noir à
    contre-courant du thème (feedback_text_contrast). Contenu légitime ; enveloppe + style à
    passer en classe commune.
16. **Modale résultat** — index.html:783-869 + JS 835-958 : styles inline dupliqués template↔JS ;
    mini-rendu markdown→HTML (index.js:878-886) générique → candidat helper commun.

### A5. Vue (views.py)
17. **`_get_ffprobe_path()` réimplémente ffmpeg_utils** — views.py:39-64 au lieu de
    `get_ffprobe_exe()` (common/utils/ffmpeg_utils.py:91). Cible : import direct.
18. **`_describe_audio()`** — views.py:67-120 : sonde ffprobe générique (durée/codec/kHz/canaux).
    Cible : `common/utils/media_probe.py` (+ `_format_duration` views.py:31-36).
19. **`_wrap_transcript_in_batch` + `_auto_wrap_orphans`** — views.py:123-127, 231-268 : pattern
    batch-of-1 dupliqué (composer views.py:28-53, synthesizer). Cible : `batch_common.py`.
20. **Agrégats de batch dans IndexView** — views.py:284-305 vs composer 71-78 (mêmes compteurs).
    Cible : `build_batches_list()` commun (contrat queue_view.py).
21. **Reset-avant-relance dupliqué ×3** — start 589-598, start_all 1268-1275, batch_start
    1461-1478 ; aucun n'utilise le pattern anti-race `select_for_update` de CLAUDE.md.
    Cible : `process_control.restart_instance()`.
22. **Prefs utilisateur via clés cache artisanales** — views.py:332-338, 398-403, 1609-1650
    (`user_{id}_transcriber_*`, 3 vues préprocessing dont doublons). Cible : util commun de
    user-settings par app (schéma-driven).
23. **`batch_template()`** — views.py:1343-1356 : contenu en dur ; besoin de toutes les apps batch.
    Cible : générateur commun dans batch_parsers.py (format déclaré).
24. **SRT généré 3× en interne** — download `_srt_ts` local 1095-1109 vs `_build_transcript_bytes`
    1034-1053 vs download_srt 1774-1818. Nettoyage + candidat document_export.
25. **`clear_all()` unlink direct** — views.py:1294-1311 sans `safe_delete_file` (incohérent avec
    delete() l.1202).

### A6. JS divers
26. **`showToast()` factice** (index.js:104-112, alert) vs composer (vrai toast 881-890) → brique
    commune `WamaApp.toast`.
27. **Maps badge/couleur de statut recopiées** — index.js:375-378, composer 675-676 → constante
    `wama-app-base.js`.
28. **Modale item réutilisée en mode batch : 2 implémentations** — index.js:663-675 + flag
    `_settingsBatchId` vs composer 484-500 + `_composerBatchSettingsId`. Cible : helper commun.

## B. COMPOSER — hardcodes restants à globaliser

### B1. Barre de progression globale (écart majeur)
1. ~~Markup hand-made~~ — **RÉGLÉ 2026-07-04** : include `_global_progress.html`.
2. ~~Logique client hand-made~~ — **RÉGLÉ 2026-07-04** : `updateGlobalBar` + 8 appels supprimés,
   `wama-global-progress.js` branché.
3. ~~Endpoint serveur MORT~~ — **RÉGLÉ 2026-07-04** : réécrit au contrat
   {total, done, running, failed, overall_progress} + `WAMA_GLOBAL_PROGRESS_URL` posé.

### B2. Cards
4. **`appendGenerationCard()` JS divergente du partial** — index.js:786-855 : `.progress` Bootstrap
   vs `.wama-progress-track` serveur ; il manque wama-card, ⚙, dupliquer. Le poll cherche
   `.wama-progress-fill` (655) → **barre des cards fraîchement ajoutées JAMAIS mise à jour** (bug).
   Cible : endpoint « card rendue ».
5. **Injection JS de boutons au SUCCESS** — index.js:711-737 (2ᵉ copie du markup, styles inline
   `#a78bfa` dupliqués). Même cible.
6. **Détection d'état par TEXTE de badge** — index.js:152-157, 164-175, 743-748
   (`badge.textContent === 'En cours'`) au lieu de `card.dataset.status` (présent). Fragile.
7. **Styles inline card** — _generation_card.html:14 (`background:#1e2124`) + bouton export (106,
   répété index.js:732) → classes CSS communes.

### B3. Batch
8. **Header de batch violet minimal** — index.html (~116-148, `background:#2d1b69` inline), sans le
   squelette « card mère = card fille » (transcriber) : il manque ▶ Lancer le batch, compteurs
   ✓/✗/en-cours, barre agrégée. Cible : brique `_batch_card.html` commune (comme A2-6).
9. ~~N'utilise PAS `common/js/batch-import.js`~~ — **RÉGLÉ 2026-07-03** : WamaBatchImport branché
   (init template avec `{% url %}`), endpoints `batch_preview` + `batch_start` créés,
   `import_batch` ne lance PLUS rien (créer ≠ démarrer ; avant : lancement inconditionnel serveur
   + double lancement client). Bonus brique : clic dropzone = ouvrir le sélecteur.

### B4. Plomberie JS (wama-app-base ABSENT)
10. Conséquences : polling hand-rolled (605-640) au lieu de WamaApp.Poller ; CSRF par regex cookie
    (8 + inline) ; **URLs en dur** partout (generate/start_all/clear_all/delete/batch/*/export/
    settings/progress/stop|start + inline). Transcriber passe par `{% url %}` → config JS.
    Cible : `window.COMPOSER_APP` + WamaApp.getUrl.
11. **État vide dupliqué template↔JS** — index.html empty-hint ET index.js:857-879 (HTML voisin
    mais pas identique). Cible : WamaApp.emptyState.
12. showToast bespoke CSS inline (881-890) → brique commune (cf. A6-26).
13. **Estimation durée côté client** — index.js:16-34 + `window.COMPOSER_MODELS` : miroir de
    model_config.py + « remaining-time » maison concurrent de WamaEta. Cible : `eta_estimator`
    serveur (comme transcriber views.py:992-1003) + WamaEta seuls.
14. **`updateModelOptions`/`checkMelodyVisibility` par préfixe d'id de modèle** — index.js:78-96 +
    383 : capacité en dur alors que WamaInputMatch est branché. Reliquat contraire à
    feedback_ui_from_model_capabilities (R17 du ledger).

### B5. Vue
15. `_auto_wrap_orphans`/`_wrap_generation_in_batch` — views.py:28-53 (cf. A5-19).
16. Compteurs de batch — views.py:71-78 (cf. A5-20) — *contrat queue_view posé le 2026-07-03*.
17. ~~`import_batch` lance TOUT immédiatement~~ — **RÉGLÉ 2026-07-03** (cf. B3-9 : création
    PENDING seule, `batch_start` séparé).
18. **`update_settings` et `stop` sans `@require_POST`** — views.py:342, 303 (transcriber stop:617
    pareil) → mutation possible en GET. Décorateur/uniformisation.
19. `clear_all` supprime audio_output à la main — views.py:745-757 (cf. A5-25).
20. **`export_to_library`** — views.py:512-550 : « exporter vers la médiathèque » = capacité
    générique → brique côté media_library dès la 2ᵉ app consommatrice.

## C. ÉCARTS Transcriber ↔ Composer

| Mécanisme | Transcriber | Composer |
|---|---|---|
| Partial de card server-rendered | ❌ inline ×2 | ✅ `_generation_card.html` |
| `_card_state`/`_card_progress` | ✅ | ❌ hand-made |
| `_cycle_button.html` serveur | ❌ (seulement au rebuild JS) | ✅ + wire/autoSync |
| `_inspector_banner.html` | ❌ hand-codé (77-83) | ✅ |
| Volet inspecteur | WamaParams.render + callbacks bespoke | initFromSchema (référence) — 2 chemins concurrents (TÂCHE 1) |
| `_global_progress` + JS commun | ✅ | ❌ + endpoint mort |
| `wama-app-base.js` | ✅ | ❌ absent |
| `batch-import.js` (preview) | ✅ | ❌ hand-rolled |
| URLs via `{% url %}`→config | ✅ | ❌ en dur |
| `_new_item_card`/`_queue_toolbar`/`_settings_modal_footer`/`queue_view`/`wama-eta`/`wama-model-help`/WamaParams modale | ✅✅ | ✅✅ |
| `wama-input-match.js` | n/a (pas de référence requise) | ✅ |
| Card mère batch complète (▶ batch, compteurs, barre agrégée) | ✅ (hand-made) | ❌ bandeau violet minimal |
| ETA seed serveur | ✅ | ❌ facteurs client |
| Manipulation directe (remove_from_batch/reorder/move/consolidate) | ✅ endpoints | ❌ absents |
| Modale batch = modale item mode batch | ✅ | ✅ (2 impls JS à fusionner) |

**Priorités d'uniformisation** : (1) composer → wama-app-base + _global_progress + batch-import
(briques prêtes, gains immédiats) ; (2) transcriber → partial de card (débloque la fin des rebuilds
JS des DEUX apps) ; (3) brique `_batch_card.html` commune (les deux headers batch sont faux chacun
à leur façon).

## D. Spécificités LÉGITIMES (ne PAS globaliser)

**Transcriber** : éditeur de correction /edit/ + support (views.py:691-971, edit.js) ; Speak temps
réel (save_realtime, zone live — affordance déclarée `show_live`) ; préprocessing audio (contenu ;
le STYLE de la modale d'aide est à corriger, A4-15) ; extraction audio des vidéos (déjà sur
video_utils) ; onglets du résultat + diarisation colorée ; liste des formats d'export (le RENDU du
menu est à factoriser, A2-7) ; logique de repli backend (`used_backend`).

**Composer** : estimation par modèle comme CONCEPT (mécanique → eta_estimator commun) ; affichage
« ~20s » près du slider ; slot mélodie (déjà déclaré via show_reference + WamaInputMatch = le bon
modèle) ; prompt vide = aléatoire (métier) ; export médiathèque en tant que FONCTION (1ʳᵉ du genre,
brique dès la 2ᵉ app) ; _audio_waveform/WamaAudioPlayer déjà briques.

**Signal transverse** : inspecteur/modale largement schéma-driven ; **la CARD reste le point dur**
— 3 à 4 copies du même markup par app (template ×2, appendCard, rebuild/injections SUCCESS).
La brique qui manque le plus : **partial de card + endpoint « card rendue » + updater JS commun**
(badge/barre/état depuis `data-status`), puis `_batch_card.html`.
