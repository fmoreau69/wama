---
name: audit-lenteurs
description: Auditer les LENTEURS de WAMA (pages, adresses interrogées en boucle par les pollers) — MESURER en processus sur la base réelle (durée, requêtes SQL, N+1, fonctions chaudes), puis faire lire le code chaud par wama-dev-ai (rôle `task`, lecture seule) sous supervision, corriger, remesurer, garder. Utiliser quand l'utilisateur dit « c'est lent », « la page met du temps », « audit des lenteurs », « pourquoi ça rame », « le serveur est poussif », ou avant/après un chantier qui touche une file, un poller ou le menu.
---

# /audit-lenteurs — mesurer, faire lire, corriger, garder

> ⚠ CANDIDAT (n=1, 2026-10-15) — distillé de la méthode mesurée du 02→13/10 (mémoire
> `reference_page_perf_debug_mnt_d`) et d'un premier audit outillé avec wama-dev-ai.

**Principe : la MESURE désigne, le modèle LIT, le superviseur TRANCHE.** Un modèle à qui l'on
demande « qu'est-ce qui est lent ? » sur un dépôt devine. Un modèle à qui l'on donne la fonction
chaude, ses lignes et le profil répond juste — et ses citations se vérifient mécaniquement.

## 0. Avant de mesurer — ce qui fausse la mesure (vécu)

- **Le serveur en service tourne `DEBUG = True`** (`wama/settings.py`, en dur) : tout cache
  « désactivé en DEBUG » est désactivé en production. Mesurer dans les mêmes conditions.
- **Depuis WSL, un `stat` sur `/mnt/d` coûte des millisecondes** : un `finders.find`, un
  `Path.exists()` par card ou par statique se paie à chaque page.
- **La 1ʳᵉ requête après relance est froide** (caches par worker) : le script réchauffe deux
  fois avant de chronométrer. Ne jamais conclure d'un premier appel.
- **La campagne nocturne `run_nightly_tests --stage ui` charge le gunicorn EN SERVICE** : une
  page peut être lente parce que le parc l'est. Vérifier qu'aucune campagne ne tourne.
- **Aucun geste pendant un calcul GPU** (mémoire `feedback_pas_de_geste_ui_pendant_gpu`).
- Un queryset déjà évalué garde son résultat : mesurer sur `qs.all()` neuf, jamais réutilisé.

## 1. Mesurer — le script du skill, en LECTURE SEULE

```bash
wsl.exe -e bash -lc 'cd /mnt/d/WAMA/web-app-for-media-automation && \
  venv_linux/bin/python -u .claude/skills/audit-lenteurs/measure_pages.py --user <login> --polled \
  --json logs/perf_audit_<date>.json > logs/perf_audit_<date>.log 2>&1'
```

- Les pages viennent du REGISTRE (`APP_CATALOG.url_name`, `surfaces()`, `account_pages()` de
  `wama/common/app_registry.py`) ; `--polled` ajoute les adresses sans argument dont le nom dit
  une interrogation en boucle (énumérées par `tests_endpoints._parameterless_routes`).
- Chaque GET tourne dans une transaction **annulée** : rien n'est écrit en base. Ce qui sort de
  la base (fil de fond, fichier) ne l'est pas — n'ajouter aucune adresse qui lance un traitement.
- `--only transcriber,imager` borne ; `--slow 0.3` fixe le seuil ; lancer **en arrière-plan**
  (plusieurs minutes pour tout le parc) et lire le `.log` à la fin.
- Mesurer avec **le compte de l'utilisateur qui se plaint** : la lenteur dépend de SES données
  (nombre de cards, gros JSONField) et de SES droits (menu).

Sortie : un tableau trié (s, requêtes SQL, statut), puis pour chaque page lente les requêtes
**répétées** (≥ 5 fois à la forme près = N+1 probable) et les fonctions DU DÉPÔT les plus
coûteuses en `cumtime`, chacune avec sa tranche `chemin:début-fin`.

### Lire le relevé (vécu le 2026-10-15)

- **Une API lente n'est une lenteur RESSENTIE que si quelque chose l'appelle** : chercher son
  appelant (`{% url "…" %}` dans les gabarits, `fetch(` dans les `.js`, appels Python) AVANT de
  la prioriser. Au 1ᵉʳ audit, l'adresse la plus lente (plus de 20 s) n'avait AUCUN consommateur :
  ce n'est pas une correction, c'est un retrait — décision de Fabien (`REMOVAL_LEDGER`).
- Une API appelée à l'OUVERTURE d'une page (`if (…) load…()` en bas du gabarit) pèse sur
  chaque visite : elle passe devant une page plus lente qu'on n'ouvre qu'à la main.
- Les jumelles du bac à sable (`<app>_NN`) apparaissent dans `--polled` : leurs statuts (501…)
  disent l'état de la jumelle, pas celui de l'app.

## 2. Trier — les signatures déjà rencontrées

| signature au profil | cause vécue | remède existant (ne pas réécrire) |
|---|---|---|
| `json.raw_decode` haut en `tottime` | gros JSONField chargé pour rien dans une file | `QUEUE_DEFERRED_FIELDS` sur le modèle ; `batch_common.without_heavy_fields(queryset)` |
| une requête ×N cards | lecture par card | lecture groupée (`process_pipeline.decorate_cards` pour les étapes) |
| `subprocess` / `.exe` Windows depuis WSL | relevé hôte à chaque appel | cache partagé `SystemMonitor._shared_reading` |
| `inspect()` Celery, attente ~2 s | réconciliation dans la requête | `reconcile_orphaned_running` en tâche de fond |
| inventaire relu par card | résolution moteur répétée | mémorisation à la source (`resolvable_entries`), vidée par `invalidate_engine_cache` |
| page rapide mais navigateur saturé | pollers en rafale | `WamaApp.Poller` (jamais `setInterval`) — garde `tests_poller_js` |

Domicile des briques : `docs/construction/architecture/WAMA_MECANISMES.md`.

## 3. Faire lire par wama-dev-ai — rôle `task`, lecture seule, supervisé

Pour chaque page lente, lancer le rôle avec les tranches que la mesure a sorties (8 au plus) :

```
dev_run_role(role="task", args={"task": "<page> prend <s> s (<n> requêtes) ; profil : <fonctions chaudes>. Explique la cause et le remède le plus simple, en citant les lignes.", "files": "<tranche1>,<tranche2>"})
```

- Depuis l'assistant ou Discord : le même appel (surface de développement). À la main :
  `python wama-dev-ai/run_task.py --task … --files …`.
- Le modèle est TIRÉ pour le compte (niveau développement). ⚠ Un compte « 100 % local » n'a
  que le local ; ILaaS/Albert exigent un compte qui les autorise (vécu le 2026-10-15).
- ⚠ Une tâche trop GROSSE pour un distant tombe en `Connection error` après quelques minutes
  (vécu ILaaS, 17 édits sur 400 lignes) : découper (moins de lignes, moins d'édits par tâche)
  plutôt que relancer telle quelle. Un `OK` court prouve que la source répond, pas qu'elle tient.
- **Superviser = vérifier, pas relire en diagonale** : le verdict `clean` dit seulement que
  chaque citation désigne une ligne réelle qui porte le texte cité. Le FOND se vérifie en
  confrontant l'explication au profil (la fonction accusée est-elle celle qui coûte ?) et au code.

## 4. Corriger — petite écriture déléguée, ou à la main

- Remède simple et local (un `only()`, un `select_related`, un champ différé) : rôle `task`
  avec `write=true` → proposition contrôlée (`old` unique, fichier qui se compile, diff).
  L'appliquer est un geste HUMAIN/superviseur : `python wama-dev-ai/run_task.py --apply <sortie>`
  (contrôles refaits sur le fichier du moment ; jamais exposé à l'assistant).
- Remède qui touche une brique commune ou plusieurs apps : à la main, via `/brique`.
- **Superviser une écriture = lire la SORTIE JSON** (`wama-dev-ai/outputs/task_*.json`), jamais
  le journal de la tâche : il tronque le diff (vécu le 2026-10-15 — 5 « oublis » qui n'en étaient
  pas). Le verdict `clean` ne voit ni la LANGUE des identifiants neufs (le modèle imite le
  français du corps existant : `rapports`, `dernier`, `cle` — à renommer avant de livrer), ni le
  style, ni l'exhaustivité.
- Une tâche qui demande de la réflexion (écrire un cache, pas renommer) peut dépasser le plafond
  d'un distant (coupures ILaaS à ~3 min 30, deux fois) : le même modèle en LOCAL
  (`provider=ollama`) n'a pas ce plafond — vérifier d'abord que le GPU est au repos.

## 5. Remesurer, puis GARDER

- Relancer le script avec `--only <page>` : le gain se chiffre avant/après, même compte.
- Une lenteur corrigée sans garde revient. Garder le **mécanisme**, pas le chrono (un chrono
  dépend de la machine) : nombre de requêtes constant entre 1 et N cards, lecture unique d'un
  cache… Modèle : `wama/common/tests/tests_page_cost.py` (prouvé par mutation — `/contre-epreuve`).
- Consigner le relevé daté et le gain dans la mémoire de référence des lenteurs ; le chiffre
  ne se recopie pas ici.
- Passe courte `/doc-sync §1` : le doc du domaine du code corrigé, et la section de `ROADMAP` qui
  portait la lenteur (statut daté, sha).
