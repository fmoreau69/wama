# REMOVAL_LEDGER.md — Registre des suppressions différées (résidu de portage/uniformisation)

> **Règle (Fabien, 2026-07-01)** : on **complète d'abord**, on **ne supprime rien** en cours de route,
> et on **trace ici** tout élément suspect (code mort, résidu de registre, duplication) pour le
> supprimer **proprement à la fin** de l'uniformisation de son app — une fois la chaîne A→Z complète.
> Objectif : ne rien oublier, ne rien casser, et éviter que des résidus rendent l'avancement confus.
>
> **Statuts** : ⛔ NE PAS supprimer maintenant · 🟡 prêt à supprimer (complétion faite, à valider) · ✅ supprimé.
> **Gate de suppression** : un item ne passe 🟡 que lorsque son remplaçant centralisé est en place ET vérifié.

---

## 1. Résidu de CATALOGUE (capabilities)

| # | Élément | Emplacement | Pourquoi résidu | Prérequis avant suppression | Statut |
|---|---|---|---|---|---|
| R1 | Clés `multilingual`, `languages_count` | `model_registry.py::_discover_transcriber_models` (~l.567-573) | **dérivables** de `languages` ; **lues par aucun consommateur** | `normalize_capabilities` au sync les dérive/supprime au niveau DB (fait) → nettoyer la SOURCE | ⛔ |
| R2 | Clé `native_diarization` | idem | nom non canonique (le reste du code utilise `supports_diarization`) ; lue par personne | normalize la renomme au sync (fait) → renommer la SOURCE | ⛔ |
| R3 | Dict `capabilities` transcriber entier (si on choisit minimal) | idem | écrit dans AIModel, **consommé par rien** côté transcriber (UI lit l'item + flags backend) | décision : garder les faits réels (reco) OU minimal ; ne PAS supprimer les faits `supports_*` (méta-app/sélection en auront besoin) | ⛔ |

## 2. Résidu d'UI (métadonnée-widget non remontée à la source)

| # | Élément | Emplacement | Pourquoi résidu | Prérequis avant suppression | Statut |
|---|---|---|---|---|---|
| R4 | `data-gen-factor` / `data-overhead` par `<option>` (ETA) | `composer/index.html` `#settingsModel` (~l.309-330) | métadonnée ETA en dur dans le template au lieu de sa source | peupler `AIModel.extra_info['eta']` (composer) + `WamaEta` le lit | ⛔ |
| R5 | Champs de modale **hand-built** (coquille + champs) | `synthesizer`, `avatarizer`, `composer` (`#settingsModal`/`#jobSettingsModal`) | duplique le schéma `params.py` (panel-only aujourd'hui) | extraire `WamaParams.renderSettingsModal` (depuis enhancer/reader) + porter la modale au contexte `item` | ⛔ |
| R6 | Coquilles de modale **statiques** dupliquées | `transcriber`, `describer`, `converter` (templates) | boilerplate répété (wrapper/titre/footer) | builder commun `WamaParams.renderSettingsModal` adopté | ⛔ |
| R7 | `media-picker.js` chargé **localement** | `imager`, `avatarizer` (templates) | redondant — chargé globalement dans `base.html` (mémoire) | vérifier l'absence de régression du bouton médiathèque | ⛔ |
| R10 | **Descriptions à DOUBLE source qui DIVERGENT** (apps moteur) | classes backend vs catalogue (stubs anglais whisper-tiny/…/large) | 2 sources par modèle, divergentes | **TRANSCRIBER FAIT (2026-07-02, vérifié)** : découverte importe les CLASSES backend (modules légers vérifiés ; PAS le manager — registration paresseuse=0 backend) → `description_short`=classe.description, `description`=classe.description_long ; qwen garde son court par-modèle (2 tailles/1 moteur), long = classe. 5 stubs whisper purgés (aucun sélecteur de taille, aucune FK, stat ETA existante=`transcriber:whisper` → nouvelle clé alignée). Caps canoniques à la source (R1/R2 transcriber soldés). Catalogue final = 4 entrées réelles. ⚠️ redémarrer serveur WSL2. Reste : répliquer aux autres apps moteur si divergence | 🟡 transcriber ✅ |
| R9 | **Descriptions modèle HARDCODÉES dans le registre** (au lieu du `model_config` par-app) | `_discover_synthesizer_models` + SAM3 | incohérent : imager/composer/reader lisent leur `model_config` | synthesizer FAIT (`REGISTRY_MODEL_DESCRIPTIONS`, court/long séparés) + **SAM3 FAIT** (2026-07-02 : `anonymizer/model_config.py::REGISTRY_MODEL_DESCRIPTIONS`, registre le lit) | ✅ |
| R11 | Mapping moteur↔clé-catalogue **dupliqué en JS** | `synthesizer/index.html` `WamaModelCaps.init.resolveKey` (xtts_v2→coqui-xtts hardcodé) vs `model_config.ENGINE_CATALOG_KEYS` (nouveau, source déclarée) | même pont déclaré 2× | faire lire resolveKey depuis un contexte exposé par la vue (comme tts_model_help_meta) | ⛔ |
| R12 | **VRAM-in-text dans les LABELS d'options** | `common/tts/constants.py::TTS_MODEL_CHOICES` (higgs : « 24 Go VRAM » dans le label) | double affichage avec l'aide WamaModelHelp (`· 24 Go VRAM` appendé) | retirer la VRAM du label (elle s'affiche désormais sous le select) | ⛔ |
| R13 | **Template orphelin** `anonymizer/upload/global_settings.html` | inclus par PERSONNE (vérifié grep include) ; porte un `#user_setting_model_to_use` DUPLIQUÉ de index.html | résidu — risque d'ID dupliqué si réactivé | supprimer après confirmation qu'aucune vue ne le rend | ⛔ |
| R14 | **Moteurs TTS hors catalogue** : vits, tacotron2, speedy_speech | `common/tts/constants.py::TTS_MODEL_CHOICES` vs `_discover_synthesizer_models` (ne les découvre pas) | sélectionnables dans l'UI mais invisibles du model_manager → ni description ni suivi téléchargement (constaté par Fabien : aide vide) | les ajouter à la découverte + `REGISTRY_MODEL_DESCRIPTIONS` (Coqui TTS, téléchargés au 1er usage) OU les retirer des choices s'ils sont abandonnés — décision Fabien | ⛔ |
| R8 | **Résidus ETA par-app** après centralisation depuis common | anonymizer `process.js:49`/`media_table.html:21`, `converter.js:360`, `transcriber/index.js:365` | signalé par Fabien | **VÉRIFIÉ (Claude, 2026-07-01)** : les 4 fichiers utilisent TOUS le `WamaEta` commun — **aucun résidu mort**. Preuve : transcriber:1553 documente que l'ancien `updateGlobalProgress` par-app a **déjà été retiré** à la centralisation. RAS sur ces fichiers. (Délégation wama-dev-ai abandonnée : connexion réparée mais modèle `audit` renvoie EOF 500 sur l'Ollama hôte.) | ✅ rien à supprimer |

## 3. Sources de vérité à CORRIGER (≠ suppression — mise à jour)

| # | Élément | Emplacement | Problème | Action (PAS une suppression) | Statut |
|---|---|---|---|---|---|
| F1 | Flags `inspector`/`modes`/`layout`=True **seulement transcriber** | `app_registry.py::APP_CATALOG.conventions` | périmés → l'app manager sous-déclarait l'uniformisation | `inspector=True` sur les **8 apps** qui câblent WamaInspector (avatarizer/composer/converter/describer/enhancer/reader/synthesizer/transcriber, vérifié lignes réelles) ; `modes=True` ajouté à **enhancer** (WamaModes.fetch/create) — imager déjà True ; `settings_modal_item=True` ajouté à **imager** ; ETA laissé False (réellement non implémenté, cf. CLAUDE.md) | ✅ (2026-07-01) |
| F6 | `transcriber` `modes=True` mais **n'utilise PAS WamaModes** | `app_registry.py` + `transcriber/index.html:321,352` | découvert : transcriber a **délibérément retiré le switch de mode** — Speak (temps réel) = **AFFORDANCE de card** (`show_live`), pas un mode. `modes=True` était donc faux | `modes=None` (N/A + commentaire) : la convention switch-WamaModes ne s'applique pas par design card-centric. À repasser True si « realtime=mode » est implémenté | ✅ (2026-07-02) |
| F2 | `ModelSource.choices` manque `composer`/`reader` | `model_manager/models.py` | découverte écrit ces `source` hors-enum (4+2 modèles) ; **converter = 0 modèle → N/A** | **compléter** l'enum | ✅ (migration 0008, appliquée) |
| F3 | Réconciliation C1 : `extra_info` vs `capabilities` | `model_selector._supports` | lisait `extra_info['classes']` (vide → filtre anonymizer cassé, mais **défaut latent** : aucun appelant de `select_model`) alors que `capabilities` = source | lit `capabilities` d'abord, `extra_info`/`class_list` en repli transition ; docstrings alignées | ✅ (2026-07-01) |
| F4 | `model_key` composer/reader ≠ `{source}:{id}` | `_discover_composer/reader_models` | clé de registre **nue** (`doctr`) vs convention `{source}:{id}` des 7 autres apps → `_resolve_model` (pilier traduction) ne trouvait pas les capacités → repli type silencieux | préfixer la clé de registre → alignée ; re-sync + purge des 6 entrées nues orphelines | ✅ (2026-07-01) |
| F5 | **DEUX enums `ModelSource`/`ModelType`** à synchroniser à la main | `models.py` (DB/choices, TextChoices) **vs** `model_registry.py` (découverte, Enum pur) | même concept dupliqué → dérive (le registre avait composer/reader, la DB non → F2) | **garde-fou** `checks.py` (Django system check, Warning) : `registre ⊆ DB` vérifié à chaque `manage.py check`/démarrage. Merge structurel écarté (migrations Django exigent des littéraux statiques + enums ré-exportés par views/sync). DB peut avoir des extras légitimes (`huggingface`/`custom` = cache HF gardé pour dépendances) | ✅ garde-fou (2026-07-01) |

---

## Journal
- **2026-07-01** — Création du registre. Complétion **#1** : `normalize_capabilities` branché au sync
  (`model_sync.py:168` + import) → catalogue DB canonique **sans** toucher aux `_discover_*` (R1/R2 =
  source à nettoyer en fin de parcours). `full_sync` relancé (nouveau code) → 106 modèles MAJ, **0 clé
  legacy en base**. ⚠️ process WSL2 à redémarrer sinon un refresh UI (ancien code) ré-écrit le legacy.
- **2026-07-01** — Complétion **#2 / F2** : `ModelSource` (DB) + composer/reader (migration `0008`, appliquée).
  Converter écarté (0 modèle). Découverte annexe → **F4** (model_key composer/reader ≠ `{source}:{id}`).
  Rien supprimé.
- **2026-07-01** — Complétion **#3 / F4** : préfixe `{source}:{id}` posé dans `_discover_composer/reader_models`
  → clés alignées sur la convention (7 autres apps). Re-sync (added=6) + **purge des 6 entrées nues
  orphelines** (doublons immédiats, PAS du résidu différé). `_resolve_model` (traduction) retrouve
  désormais composer/reader. Découverte annexe → **F5** (deux enums `ModelSource` DB vs registre).
- **2026-07-01** — Complétion **#4 / F3** : `model_selector._supports` lit `capabilities` (canonique) au
  lieu de `extra_info` — défaut latent (aucun appelant), filtre classes anonymizer réparé. Vérifié.
- **2026-07-01** — Complétion **#5 — capabilities des apps à trou** (base manifeste propre) : injection
  CANONIQUE + FACTUELLE dans la découverte : composer `{modalities:['audio'],task:text-to-music|audio,
  languages:['en']}` (encodeur T5 anglais), reader `{modalities:['image','document'],task:'ocr'}`,
  avatarizer `{modalities:['image','audio','video'],task:'lip-sync'}`. Re-sync → **0 trou** sauf ollama.
  ⚠️ **ollama DÉFÉRÉ** (18 vides) : backend LLM partagé, possiblement géré par **wama-dev-ai** (RAM-aware
  config.py) → NE PAS injecter sans coordonner (risque télescopage). `context_length` non inventé
  (nécessiterait `ollama show`). ⚠️ Rappel : après édition du registre, **redémarrer le serveur WSL2**
  sinon la sync du process live (ancien code) recrée les clés nues.
- **2026-07-02** — **F6** : `transcriber` `modes=True`→`None` (N/A) — Speak = affordance card, pas un mode WamaModes.
- **2026-07-02 (suite session Fable5)** — **Plan validé Fabien** : deux niveaux actés (moteur=app,
  modèle=catalogue ; centralisation finale = réflexion ultérieure) ; 1ʳᵉ passe = toutes les apps au
  niveau Transcriber + tests nocturnes, seuil conformité ~90 %, colonnes du tableau à compléter au fil.
  **Exécuté** : R10-transcriber ✅ (4 entrées réelles, desc=classes backend, caps canoniques, 5 stubs
  purgés, clé `whisper` alignée stat ETA) · R9-SAM3 ✅ · **colonne `model_help`** ajoutée à `_conv()`
  (valeurs vérifiées : True=transcriber/enhancer/imager/composer/reader, None=converter, False=describer/
  synthesizer/anonymizer/avatarizer) · **câblage WamaModelHelp SYNTHESIZER** ✅ (1er des 4) : pont déclaré
  `ENGINE_CATALOG_KEYS` (model_config) → vue `_tts_model_help_meta()` lit le CATALOGUE → template
  `#ttsModelHelp` + init (meta vérifiée : 4 moteurs, template compile). Moteurs Coqui légers
  (vits/tacotron2/speedy_speech) sans entrée catalogue → aide vide (assumé). Découvertes → R11, R12.
- **2026-07-02** — **Convention descriptions (CORRIGÉE)** : le format de référence = **transcriber**
  (`backends/*.py` : `description` + `description_long`, rendus par le composant COMMUN `WamaModelHelp`,
  index.js:1580). Ce sont **DEUX champs SÉPARÉS et INDÉPENDANTS**, PAS « court. détail » concaténé
  (mon idée initiale de dériver le court par split était FAUSSE). `description_short` = one-liner concis
  (sans VRAM, appendée par le JS) ; `description`/`long` = paragraphe AUTONOME en overlay ⓘ (peut citer
  la VRAM en prose). Appliqué à **synthesizer** (4 modèles, champs séparés, overlay=OUI vérifié).
- **2026-07-02** — **Descriptions modèle (dimensionnement)** : VRAM retirée de 8 `description_short` d'apps
  CATALOGUE (7 imager : cogvideox×2, ltx×2, mochi, flux2-klein, flux-logo ; 1 synthesizer : higgs) qui
  la codaient en dur → **double affichage** (le JS `wama-model-help.js:48` append déjà `· X Go VRAM`
  depuis `vram_gb`). **Convention actée (validée Fabien)** : la VRAM vient TOUJOURS du catalogue
  (`vram_gb`), JAMAIS du texte. Format de référence = **transcriber** : `description_short` = one-liner
  de traits (sans VRAM) ; `description` (long) = phrase(s) de détail en overlay ⓘ si ≠ court. Sources :
  imager/synthesizer descriptions hardcodées dans `_discover_synthesizer_models` (registre) pour synth,
  `model_config.py` pour imager. Vérifié : 0 VRAM-in-text restant, JS append la bonne valeur catalogue.
- **2026-07-01** — **F1 / app manager** : conformité `APP_CATALOG.conventions` remise au réel — `inspector=True`
  sur 8 apps (vérifié par lignes réelles WamaInspector), `modes=True` enhancer, `settings_modal_item=True`
  imager. `get_conformity_summary()` reflète désormais l'uniformisation réelle (le tracker ne sous-déclare
  plus l'inspecteur). ETA laissé False (non implémenté). Découvertes annexes → **F6** (transcriber modes
  ≠ WamaModes) + **R8** (résidus ETA par-app à auditer, signalés par Fabien).
