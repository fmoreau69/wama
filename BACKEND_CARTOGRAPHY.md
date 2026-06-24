# BACKEND_CARTOGRAPHY.md — Carte des backends WAMA (préalable à l'extraction d'un contrat commun)

> **But** : avant d'extraire un contrat de backend commun, cartographier l'existant pour concevoir un
> fonctionnement **générique ET non bloquant pour de nouveaux modèles** (les modèles et leurs méthodes
> de chargement/déchargement varient fortement selon les apps). **App de référence : Transcriber.**
>
> **Lien prospection/installation** : `is_available()` (libs présentes ?) est la jonction backends ↔
> tests nocturnes (skip ⊘) ↔ prospection/installation. Un nouveau modèle peut exiger de **nouvelles
> librairies** ; le contrat doit donc **déclarer ses dépendances** pour que l'installeur les pose.

## Dimensions du contrat (observées)

1. **Cycle de vie** : `is_available()` (deps présentes) · `load(model)->bool` · `is_loaded` · `unload()`
2. **Méthode métier** : le verbe varie (`transcribe`/`generate`/`enhance`/`run`/`synthesize`/`describe`/`detect`)
3. **keep_loaded** : 3 formes — singleton tenu par un *manager*, singleton *module*, ou *param d'appel*
4. **Dépendances** : libs requises (souvent implicites dans `is_available()` via try-import)

## Carte par application

| App | ABC `base.py` | Manager | `is_available` | `load→bool` | `is_loaded` | `unload` | Verbe métier | keep_loaded | Conformité réf. |
|-----|:---:|:---:|:---:|:---:|:---:|:---:|---|---|---|
| **transcriber** (RÉF) | ✅ `SpeechToTextBackend` | ✅ `TranscriberBackendManager` | ✅ cls | ✅ | ✅ prop | ✅ | `transcribe()` | manager | **100 % (référence)** |
| **imager** | ✅ `ImageGenerationBackend` | ✅ `BackendManager` | ✅ cls | ✅ | ✅ prop | ✅ | `generate()` | manager | **~95 %** (même forme → **dédupliquer le base**) |
| **enhancer** | ❌ classes nues | ❌ singleton `get_*` | ✅ cls | ❌ privé `_ensure_loaded` | ❌ (`_model is not None`) | ✅ | `enhance()` | singleton module | **~50 %** (deps OK, lifecycle privé) |
| **reader** | ❌ | ❌ | ~ (module, p.ex. glm) | ~ (Olm oui, DocTR/GLM non) | ❌ | ~ | `run()` | param/appel | **~40 %** (hétérogène) |
| **anonymizer** | ❌ (`Anonymize` + `model_selector`) | ❌ | ~ | `apply_process`/`track` | ❌ | ~ | `detect/blur` | ~ | **~35 %** |
| **composer** | ❌ | ❌ | ? | ❌ lazy | ❌ | ~ | `generate()` | ? | **~30 %** |
| **synthesizer** | ❌ (`tts_service`) | ❌ | ? | function-driven | ❌ | ? | `synthesize` | engine global | **~30 %** |
| **describer** | ❌ **function-driven** (globals `_blip_model`…) | ❌ | ❌ | globals lazy | ❌ | — | `describe_*()` | globals module | **~20 %** (+ paradigme LLM/Ollama distinct) |

(`~` = partiel/variable selon le backend interne ; `?` = à confirmer à la migration.)

## Observations structurantes

1. **Deux apps conforment déjà** la forme de référence (transcriber + imager) mais **le base ABC est
   dupliqué** → 1ʳᵉ victoire = un `BaseBackend` commun, dédupliquer imager dessus.
2. **Le commun = le CYCLE DE VIE**, pas le verbe métier. Le contrat standardise
   `is_available/load/is_loaded/unload` + **un** point d'entrée générique (`process(**kwargs)`), en
   laissant la signature métier à l'app (un wrapper `transcribe/generate/...` peut déléguer à `process`).
3. **`is_available()` est le plus partagé** → en faire le **hook de dépendances** : un backend déclare
   `REQUIRED_PACKAGES`, et `is_available()` en découle (try-import). C'est ce qui rend le système
   **non bloquant** : un nouveau modèle = sous-classe + déclaration de deps, **zéro modif du cœur**.
4. **keep_loaded à unifier** (manager-tenu + politique), aujourd'hui éclaté en 3 formes.
5. **describer = cas limite** (function-driven + LLM/Ollama) : à conformer en dernier, ou à garder hors
   du contrat « backend de modèle local » (c'est un client LLM, paradigme différent).

## Contrat commun proposé (réf. Transcriber) — voir `wama/common/backends/base.py`

```
class BaseModelBackend(ABC):
    REQUIRED_PACKAGES: list[str] = []          # libs pip → consommé par l'installeur/prospection
    recommended_vram_gb: float | None = None
    description: str = ""
    @classmethod
    def is_available(cls) -> bool: ...          # défaut : try-import REQUIRED_PACKAGES
    @classmethod
    def missing_packages(cls) -> list[str]: ... # ← jonction prospection/installation
    @abstractmethod
    def load(self, model=None) -> bool: ...
    @property
    @abstractmethod
    def is_loaded(self) -> bool: ...
    @abstractmethod
    def unload(self) -> None: ...
    @abstractmethod
    def process(self, **kwargs): ...            # verbe métier générique
```

+ un **manager commun** (`get_backend`/`get_available_backends`/`unload_all`, auto-découverte) branché
sur `model_manager.services.model_selector.select_model()` (sélection VRAM-aware déjà commune).

## Jonction prospection / installation (demande Fabien)

`missing_packages()` / `REQUIRED_PACKAGES` ferment la boucle :
- **Tests nocturnes** : `is_available()==False` → scénario **skippé** (⊘), pas en échec (déjà en place).
- **Prospection** : un modèle proposé peut être marqué « nécessite l'installation de `<libs>` » ; le
  `model_installer` pourra alors **proposer/poser** ces paquets (`pip install`) avant l'install du modèle.
- Un nouveau backend déclare ses libs → tout le reste (test/skip, install, sélection) s'enchaîne sans
  toucher au cœur.

## Ordre de migration recommandé (incrémental, non bloquant)

1. Extraire `common/backends/base.py` (`BaseModelBackend` + `missing_packages`) — **contrat seul, aucune app forcée**.
2. **imager** : dédupliquer son `base.py` sur le commun (faible risque, forme déjà alignée).
3. **enhancer** : exposer `load()/is_loaded` publics (au-dessus de `_ensure_loaded/_model`) + manager → conforme.
4. **reader / anonymizer / composer / synthesizer** : donner un manager + conformer le cycle de vie.
5. **describer** en dernier (ou hors-contrat : client LLM).
6. **Tests** : remplacer les N scénarios `model_loaded` sur-mesure par **un générique** paramétré par app/modèle.

Voir `COMMON_REFACTORING.md` (ordre des chantiers) et `memory/project_nightly_tests.md`.
