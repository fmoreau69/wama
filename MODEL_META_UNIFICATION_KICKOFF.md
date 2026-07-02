# MODEL_META_UNIFICATION_KICKOFF.md — Document d'attaque (session fraîche / Fable5)

> **But de ce document** : donner à une session neuve TOUT le contexte pour poursuivre l'unification
> de la **gestion des méta-informations des modèles** (tirage dropdown + méta-infos + descriptions
> courte/longue) dans WAMA, sans avoir à refaire l'audit. Rédigé le **2026-07-02** en sortie d'une
> session Opus. Tout ce qui est ci-dessous a été **vérifié empiriquement** (runtime WSL2, DB réelle),
> sauf mention « à vérifier ».
>
> **Règle de travail (Fabien)** : vérifier avant d'affirmer ; ne rien supprimer sans certitude (tracer
> dans `REMOVAL_LEDGER.md`) ; build → test humain (pas de JS à l'aveugle, node absent de l'env) ;
> consigner les décisions EN ENTIER (pourquoi + implications).

---

## 1. La décision d'architecture (validée Fabien 2026-07-02)

**Cible = « fichier + DB qui synchronisent leurs données ».**
- **Fichier (source versionnée)** : chaque app **déclare** ses modèles/moteurs — descriptions,
  capacités, VRAM — dans ses fichiers (contrat `BaseModelBackend` : attributs de classe ;
  `<app>/utils/model_config.py`). C'est cohérent avec la philosophie manifeste (chaque app déclare).
- **DB (catalogue central)** : `AIModel` (app Django `wama/model_manager/`) est peuplé **par sync**
  depuis ces déclarations. C'est la **source unique de LECTURE**.
- **Les apps/backends LISENT depuis le catalogue** (DB), pas depuis les fichiers locaux directement.

> Le sens est : **fichier → (sync) → DB → (lecture) → apps**. On NE lit PAS les fichiers locaux à
> l'affichage. Le sync fichier→DB est légitime (c'est le « + DB qui synchronise »), ce que Fabien
> refuse c'est que les apps aillent piocher dans le local au lieu du catalogue.

### Système DORMANT à NE PAS réveiller
`AI-models/manager.py` (`WAMAModelManager`) + `AI-models/registry.json` = **idée initiale de Fabien**
(regroupement des modèles dans `AI-models/`), **remplacée** par l'app Django `model_manager` + UI.
Vérifié : `registry.json` **n'existe pas**, `WAMAModelManager` **n'est importé nulle part** dans
`wama/`. → **Système mort. Ne pas le ressusciter.** La source de vérité vivante = **Django
`model_manager` / `AIModel`.** (`AI-models/` reste le **dossier de stockage des poids**, ça oui.)

---

## 2. Architecture vivante (les briques réelles à utiliser)

| Brique | Fichier | Rôle |
|---|---|---|
| **Catalogue DB** | `wama/model_manager/models.py::AIModel` | source unique de lecture. Champs clés : `model_key` (`{source}:{id}`), `model_type`, `source`, `description` (LONG), `description_short` (COURT), `vram_gb`, `capabilities` (dict), `extra_info` (dict, dont `eta`) |
| **Découverte** | `model_manager/services/model_registry.py::_discover_<app>_models()` | construit `ModelInfo` (par app) depuis les fichiers d'app |
| **Sync → DB** | `model_manager/services/model_sync.py::full_sync()` | écrit `ModelInfo` → `AIModel`. **Dérive** `description_short` = 1re phrase du long SI non fourni explicitement |
| **Contrat backend** | `common/backends/base.py::BaseModelBackend` | attributs de classe `description`, `description_long`, `recommended_vram_gb`, `supports_*` |
| **Sélection VRAM** | `model_manager/services/model_selector.py::select_model()` | lit `capabilities` (canonique). Adoption par app = TODO (cf. PROJECT_STATUS §2 étape 3) |
| **Vocabulaire capacités** | `common/utils/model_capabilities.py` | `CANONICAL_CAPABILITIES` + `normalize_capabilities()` (créé cette session) |
| **Tirage dropdown** | `model_selector.get_registry_models(source)` | (choices, info) depuis le catalogue |
| **Tirage descriptions** | `common/static/common/js/wama-model-help.js` (`WamaModelHelp`) | affiche COURT sous le select (+ ` · X Go VRAM` **appendée depuis vram_gb**) + ⓘ overlay = LONG si ≠ court. 2 sources meta : `.init/setMeta` (apps moteur, depuis backend) OU `.fetchCatalogMeta(source)` (apps catalogue, depuis DB) |
| **Garde-fou** | `model_manager/checks.py` | Django check : `registre ⊆ DB` pour ModelSource/ModelType (créé cette session) |

---

## 3. ÉTAT DES LIEUX — le « gros trou dans la raquette » (vérifié empiriquement)

Le problème central : **les descriptions/méta vivent dans les fichiers d'app, éparpillées, et les apps
ne lisent PAS toutes depuis le catalogue.** Deux « tirages » ne sont pas unifiés :

### 3.1 Tirage des MODÈLES (dropdown)
| Source du dropdown | Apps |
|---|---|
| Catalogue (`get_registry_models`) | **imager, anonymizer** (2/10) |
| Backends de l'app (`get_backends_info`) — variante MOTEUR légitime | transcriber, reader, synthesizer, enhancer, composer |
| À vérifier / autre | describer, avatarizer, converter |

### 3.2 Tirage des DESCRIPTIONS (`WamaModelHelp`)
| Utilise WamaModelHelp | Apps |
|---|---|
| ✅ Oui | transcriber, enhancer, imager, composer, reader (**5/10**) |
| ❌ Non (n'affiche pas de description modèle) | **anonymizer, avatarizer, converter, describer, synthesizer** |

### 3.3 Où vivent les descriptions AUJOURD'HUI (les fichiers)
| App | Fichier | Champ |
|---|---|---|
| transcriber | `transcriber/backends/{whisper,vibevoice,qwen_asr}_backend.py` | attributs `description` + `description_long` (bons, français) |
| imager | `imager/utils/model_config.py` | `description` |
| synthesizer | `synthesizer/utils/model_config.py` | `REGISTRY_MODEL_DESCRIPTIONS` (ajouté cette session) |
| enhancer | backends/config | champ `short` |
| anonymizer (SAM3) | `model_registry.py::_discover_anonymizer_models` (l.~483) | **hardcodé dans le registre** (R9) |

### 3.4 Format de référence des descriptions = TRANSCRIBER
**DEUX champs SÉPARÉS et INDÉPENDANTS** (PAS « court. détail » concaténé) :
- `description` (COURT) : one-liner concis, 1-2 clauses, **SANS VRAM** (le JS l'append). Ex. Whisper :
  `large-v3 — rapide, polyvalent, multilingue. Diarisation via pyannote.`
- `description_long` (LONG) : **paragraphe autonome** (n'est pas « court + suite »). Ex. :
  `Whisper large-v3 (faster-whisper / CTranslate2) : transcription multilingue rapide et robuste… ~10 Go VRAM. Bon défaut polyvalent.`
- **La VRAM vient TOUJOURS du catalogue `vram_gb`**, jamais du texte du court (sinon double affichage).

---

## 4. Ce qui a été FAIT cette session (vérifié, commité ou en working tree)

Tout est tracé dans **`REMOVAL_LEDGER.md`** (registre des suppressions différées + corrections F1-F6, R8-R10).

1. **Capacités canoniques** : `common/utils/model_capabilities.py` (vocabulaire + `normalize_capabilities`)
   branché au **sync** (`model_sync.py`) → catalogue canonique, 0 clé legacy. Idée reçue corrigée :
   les apps « immatures UI » (anonymizer/imager/enhancer) ont de **bonnes** capabilities ; les trous
   étaient avatarizer/composer/reader/ollama.
2. **Capabilities injectées** (factuelles) : composer `{modalities:['audio'],task,languages:['en']}`,
   reader `{ocr}`, avatarizer `{lip-sync}`. **0 trou sauf ollama (DÉFÉRÉ — géré par wama-dev-ai)**.
3. **F2/migration 0008** : `ModelSource` DB + composer/reader.
4. **F4** : `model_key` composer/reader préfixés `{source}:{id}` (convention des 7 autres apps) +
   purge des entrées nues orphelines. Débloque `_resolve_model` (pilier traduction).
5. **F3** : `model_selector._supports` lit `capabilities` (canonique) au lieu de `extra_info`.
6. **F5** : garde-fou `checks.py` (`registre ⊆ DB`). Merge structurel écarté (2 enums ModelSource :
   DB `TextChoices` + registre `Enum` — migrations Django exigent des littéraux statiques).
7. **F1** : `APP_CATALOG.conventions` remis au réel — `inspector=True` sur **8 apps** (vérifié lignes
   WamaInspector), `modes=True` enhancer, `settings_modal_item=True` imager. **Le tracker `/apps/`
   ne sous-déclare plus.**
8. **F6** : `transcriber` `modes=None` (N/A) — Speak = affordance de card (`show_live`), pas un mode
   WamaModes (design card-centric intentionnel).
9. **Descriptions** : VRAM retirée de 8 `description_short` (imager×7 + synthesizer higgs) → la VRAM
   vient du catalogue. **R9-synthesizer** : descriptions déplacées dans `synthesizer/model_config.py`
   (`REGISTRY_MODEL_DESCRIPTIONS`, court+long SÉPARÉS), le registre les LIT. Vérifié : overlay=OUI.
10. **wama-dev-ai** : `config.py` rendu surchargeable par `OLLAMA_HOST` (Ollama est sur l'HÔTE Windows,
    injoignable en 127.0.0.1 depuis WSL ; `start_wama_prod.sh` le fait déjà pour WAMA).

### ⚠️ Erreurs/obsolescences à corriger dans les docs (détectées cette session)
- **`PROJECT_STATUS.md` §2bis/§15** : scores de conformité **périmés** (disait imager=6, avatarizer=6 ;
  après F1 c'est **imager 9/21, avatarizer 8/20**). Scores actuels (2026-07-02) :
  transcriber 16/21(76%) · describer/enhancer/reader 15(68%) · converter 15/24(62%) · synthesizer
  13/21(61%) · anonymizer 13/22(59%) · composer 12/21(57%) · imager 9/21(42%) · avatarizer 8/20(40%).
  → remplacer par un pointeur vers `/apps/` (`get_conformity_summary()`), source live.
- Mon idée initiale « format Court. Détail. (dérivation par split) » était **FAUSSE** — le vrai format
  transcriber = 2 champs séparés. Corrigé pour synthesizer ; **ne pas reproduire le split ailleurs**.

---

## 5. QUESTIONNEMENTS & PROPOSITIONS OUVERTES (à trancher)

1. **Apps MOTEUR : catalogue = miroir des backends.** Le catalogue transcriber contient des **stubs
   anglais périmés** (`whisper-tiny/base/small/medium/large` = « Best accuracy, slowest », VRAM-in-text)
   qui NE correspondent PAS aux vrais moteurs (whisper=large-v3, vibevoice, qwen) et ne sont **pas
   affichés** (transcriber affiche depuis les classes backend). **R10.** Proposition : `_discover_
   transcriber_models` **lit les descriptions depuis les classes backend** (source unique, contrat
   `BaseModelBackend`) → catalogue = miroir fidèle ; **supprimer les 5 variantes whisper périmées**.
   ⚠️ Piège vérifié : instancier le `TranscriberBackendManager` au sync donne **0 backend** (registration
   paresseuse) → importer les **classes** backend directement (sûr, testé) plutôt que le manager.
2. **Puis apps LISENT le catalogue** : une fois le catalogue fidèle, faire lire transcriber (et les
   autres moteurs) DEPUIS le catalogue via `WamaModelHelp.fetchCatalogMeta` au lieu de `setMeta` local.
   But : un seul chemin de lecture. (Décision : garder l'affichage identique, changer juste la source.)
3. **Câbler `WamaModelHelp` dans les 5 apps qui ne l'ont pas** (anonymizer, avatarizer, converter,
   describer, synthesizer) — sinon les descriptions écrites ne s'affichent pas (cas vécu : synthesizer).
4. **R9 SAM3** : déplacer la description SAM3 hardcodée (`_discover_anonymizer_models` l.483) vers
   `anonymizer` config.
5. **Descriptions longues homogènes** : une fois 1-3 faits, écrire court+long (champs séparés) pour
   tous les modèles. Périmètre convenu : « tout, imager en pilote » ; anonymizer = 46 YOLO quasi
   identiques (long uniforme acceptable).
6. **Ordre recommandé** : (a) R10 transcriber = pilote moteur (catalogue lit backends + purge stubs) →
   (b) câbler WamaModelHelp partout → (c) apps lisent le catalogue → (d) contenu court/long partout →
   (e) tirage dropdown unifié (describer/avatarizer sur catalogue). Chaque étape : build + **test
   humain navigateur** (survol ⓘ), puis consigner.

---

## 6. Pièges & garde-fous (vérifiés cette session)

- **Process WSL2** : après TOUTE édition de `model_registry.py`/`model_sync.py`, **redémarrer le
  serveur** — sinon la sync du process live (ancien code en mémoire) **recrée les données périmées**
  (observé 2×). Le refresh UI du model_manager = `full_sync`.
- **Runtime** : tout tourne en WSL2 (`wsl.exe -e bash -lc '… ./venv_linux/bin/python …'`). manage.py
  Windows agit sur la vraie base via forwarding. Ollama = sur l'HÔTE Windows (172.29.240.1:11434).
- **Vérifier les sorties de wama-dev-ai** : le wrapper Bash peut afficher exit 0 alors que
  `run_audit.py` a échoué (lire le log). Délégation utile en NOCTURNE (serveur idle = VRAM libre) ;
  en journée l'audit OOM (EOF 500) faute de VRAM.
- **La VRAM vient du catalogue** (`vram_gb`), jamais du texte des descriptions.
- **Descriptions = 2 champs séparés** (court + long autonome), jamais concaténation/split.

---

## 7. Documents de référence (lus et cohérents entre eux)
- `BACKEND_CARTOGRAPHY.md` — contrat `BaseModelBackend`, `BackendManager`, familles de backends.
- `PROJECT_STATUS.md` — photo des chantiers (⚠️ §2bis/§15 scores périmés, cf. §4 ci-dessus). §2 étape 3
  = centralisation modèle (adaptateurs + migration per-model) = TODO tracé.
- `GENERALIZATION_PLAN.md` — trajectoire manifeste ; F. modèles = fondation complète, rollout par app.
- `UI_MECHANISMS_CONSOLIDATION.md` — inventaire des mécanismes UI (params.py, WamaParams, inspecteur).
- `REMOVAL_LEDGER.md` — **à jour** : R1-R10 (à supprimer plus tard) + F1-F6 (corrections faites).
- `PROMPT_PIPELINE.md` — pilier traduction/enrichissement/RAG (piloté par `capabilities['languages']`).
- Mémoire : `memory/project_ui_mechanisms_consolidation.md`, `project_nightly_tests_plan.md`.

---

## 8. Résumé pour démarrer (TL;DR pour Fable5)
> WAMA veut **une source unique de méta-modèles** : les apps déclarent (fichiers) → sync → **catalogue
> `AIModel`** → les apps **lisent le catalogue**. Aujourd'hui c'est à moitié fait : le dropdown vient du
> catalogue pour 2/10, les descriptions via `WamaModelHelp` pour 5/10, et le catalogue transcriber a des
> **stubs anglais périmés** non affichés. **Premier chantier concret = R10** : faire lire au catalogue
> transcriber les descriptions des **classes backend** (source unique) et **supprimer les 5 stubs whisper
> périmés**, en pilote — puis généraliser (câbler WamaModelHelp partout, apps lisent le catalogue, écrire
> court/long séparés partout). Ne PAS réveiller `AI-models/manager.py`. Vérifier empiriquement, redémarrer
> le serveur WSL2 après chaque édition du registre, tester le rendu au navigateur.
