---
name: brique
description: Extraire une logique dupliquée vers wama/common/ (brique commune) puis la faire adopter — le geste central de la règle « zéro duplication ». Utiliser quand du code se répète entre 2+ apps, quand l'utilisateur dit « centralise », « extrais en brique », « factorise », ou avant de copier-coller quoi que ce soit entre apps.
---

# /brique — Extraction vers common/ + adoption

Règle CLAUDE.md : tout code utilisé par plus d'une app va dans `wama/common/`. Si tu t'apprêtes
à copier-coller entre apps, c'est LE signal d'extraire d'abord.

## 1. Avant d'écrire — la brique existe-t-elle déjà ?

> ⛔ **Étape non négociable, elle prend 2 minutes.** Sautée le 2026-07-31 : j'ai raisonné pendant
> trois apps avant de découvrir que la file est construite par `batch_common.build_batches_list()`
> + `queue_view.py` — donc UN seul domicile pour les 10 apps, pas dix. Lire la facette F d'abord.

```bash
ls wama/common/utils/ wama/common/services/ wama/common/static/common/js/
grep -nE "^#{2,3} " WAMA_APP_GENERATION_ROUTE.md        # repérer la facette F concernée
```

- **Lire d'abord la carte des mécanismes `WAMA_MECANISMES.md`** (table GÉNÉRÉE depuis le
  registre `wama/common/mecanismes.py`) : elle dit quels mécanismes existent, où ils habitent,
  et lesquels sont des **briques mortes (`⚠ 0` consommateur)** — une brique à 0 consommateur
  s'ADOPTE, elle ne se réinvente pas (vécu : `couvrir_classes` 8 jours morte, `qc.py`).
- Grep `wama/common/utils/`, `templates/common/`, `static/common/js/` + l'index
  `WAMA_APP_CONVENTIONS §12.2` + `WAMA_APP_GENERATION_ROUTE.md` (facette concernée).
- Grep `app_registry.py` avant toute nouvelle taxonomie (piège récidivé 3× : MEDIA_CATEGORIES,
  normalize_types existaient déjà).
- Ne pas réveiller le code DORMANT (`AI-models/manager.py`, registry.json).

## 2. Extraire (construction propre, pas de surcharge)
- Partir de la MEILLEURE implémentation existante (souvent transcriber/reader), pas d'une moyenne.
- La brique est déclarative/paramétrable (kwargs, hooks `reset=`/`derive=`/`extra=`) — jamais de
  `if app == 'x'` dedans.
- Python → `common/utils/` ou `common/services/` ; template → `templates/common/_*.html` ;
  JS → s'ajoute à `wama-app-base.js` ou fichier dédié `static/common/js/`.
- Spécificités légitimes d'app : elles se DÉCLARENT (capacité, schéma, adapter), elles ne se
  codent pas en dur dans la brique.

## 3. Adopter immédiatement (une brique sans consommateur = dette)

> ⚠ **Piège distinct : brique JUSTE, prise FAUSSE.** Une brique correcte peut être branchée à la
> main (identifiants de champs en dur dans le JS d'une app, récepteur `post_save` recopié par app,
> logique réimplémentée dans chaque vue). Elle marche, mais **ne se propage pas** : le porter vers
> la 2e app demande de recopier le câblage. Test : *« que doit écrire la prochaine app ? »* — si
> la réponse est « plus de trois lignes », le branchement doit être **déduit d'une déclaration**
> (ex. `PROMPT_TARGETS[...]['model']` → récepteur générique ; convention `dom_id` de `params.py`).
> Vécu 2026-07-31 : ~20 lignes par app, généralisées ensuite en mixin + récepteur + helper.

- Regarder **comment les autres apps consomment** une brique voisine (déclaration ? schéma ?)
  avant de choisir le mode de branchement. 8 apps sur 10 passent par `WamaParams` — s'en écarter
  doit être un choix motivé, pas un défaut.
- Recâbler l'app source + au moins un 2e consommateur dans la même passe si possible.
- Supprimer le code local remplacé (pas de double chemin) ; si la suppression doit attendre une
  validation navigateur → l'inscrire dans `REMOVAL_LEDGER.md` (R*).
- JS/CSS modifiés → copier vers `staticfiles/<app>/` ; Python → restart WSL2 à signaler.

## 4. Tracer
- **Mécanisme transversal créé/déplacé → entrée dans le registre `wama/common/mecanismes.py`**
  (jamais une ligne à la main dans `WAMA_MECANISMES.md` — la table est générée), puis
  `python manage.py doc_facts` pour régénérer et `doc_facts --check` pour vérifier.
- La brique + son taux d'adoption → `WAMA_APP_GENERATION_ROUTE.md` (facette F1-F8 concernée).
- Si mesurable → ajouter/ajuster le critère dans `conformity_checker.py` (cf. /conformite §3).
- Palier → `/palier` (PROJECT_STATUS + commit par chemins explicites).
