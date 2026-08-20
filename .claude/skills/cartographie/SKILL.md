---
name: cartographie
description: Cartographier un corpus externe (framework tiers) et le confronter à la philosophie WAMA, sans rien implémenter. Utiliser quand on veut intégrer/s'inspirer d'un système existant (BIND, pynd, autre), quand l'utilisateur dit « cartographie », « passe N », « confronte à l'existant », ou avant tout chantier d'intégration.
prompt: cartography
agent: wama-dev-ai
---

# /cartographie — Cartographier un corpus externe avant d'intégrer

Objectif : **poser la connaissance AVANT d'implémenter**. On n'écrit pas une ligne de WAMA tant que
la passe n'a pas produit des faits prouvés. La règle de Fabien (2026-08-20) : *« je ne veux pas
qu'on implémente des petites parties pour se rendre compte qu'on doit refaire l'essentiel »*.

## Séparation des rôles — ce que ce skill NE contient pas

| | où | quoi |
|---|---|---|
| **la méthode** | `wama-dev-ai/prompts/cartography.txt` (frontmatter `prompt:`) | comment penser : preuves obligatoires, règle anti-invention, format de sortie |
| **le séquençage** | ce fichier | quoi faire, dans quel ordre, avec quelles préconditions |
| **l'accès** | `wama-dev-ai/corpus.py` | quels corpus, quel périmètre, quels formats |

Ne JAMAIS recopier la méthode ici : le prompt en est la source unique, et il est réutilisable par
d'autres skills.

## 1. Préconditions (à vérifier, pas à supposer)

- Le corpus est déclaré dans `wama-dev-ai/corpus.py` (`CORPORA`) avec son périmètre `include`/`exclude`.
  Sinon : le déclarer d'abord — **jamais copier les fichiers dans le dépôt** (doublon qui dérive).
- `python wama-dev-ai/corpus.py` → le corpus répond « OK n fichiers retenus ». Si « INJOIGNABLE » :
  partage démonté / VPN, s'arrêter là.
- **VRAM libre** : la garde RAM écarte silencieusement qwen3.8 (19 Go) si de la VRAM traîne, et
  descend la chaîne jusqu'à un modèle plus petit — on obtiendrait une cartographie médiocre SANS
  aucun signal. Si WAMA tourne, le service TTS tient kokoro : arrêter WAMA (WSL2) avant.
- Le document de destination existe et déclare son tableau des passes (ex. `WAMA_DATA_WORLD.md §9`).

## 2. Découpage en passes

Une passe = un sous-système + un livrable écrit. Ne jamais lancer « cartographie tout » : le
rapport devient un résumé plat sans preuves. Ordre qui a marché sur BIND :

0. inventaire structurel (déterministe, moi) — volumes, arborescence, ce qu'on EXCLUT et pourquoi ;
1. noyau de données / modèle (lecture dirigée, moi) — c'est là que se prennent les décisions ;
2. noyau d'extension / plugins (lecture dirigée, moi) ;
3. implémentations réelles (wama-dev-ai — volumineux, read-only) ;
4. portages/variantes du même système (wama-dev-ai) ;
5. confrontation à WAMA + plan ordonné (moi).

**Ce que je garde pour moi** : les passes qui DÉCIDENT (1, 2, 5). **Ce que je délègue** : les passes
de VOLUME (3, 4), où l'offload préserve le contexte de session.

## 3. Lancer une passe déléguée

```
venv_win\Scripts\python.exe wama-dev-ai\run_audit.py ^
  --prompt cartography --model architect --non-interactive ^
  --task "Passe N : <sous-système>. Lis <DOC>.md d'abord. Cherche <questions précises>."
```

- `--model architect` (ou `dev`) : `qwen38` est **en tête** de ces chaînes. **Ne jamais
  `--force-model`** — ça court-circuite la garde VRAM, et qwen3.8 + son contexte ne tient pas
  toujours sur 24 Go partagés.
- Vérifier au démarrage : `[Model] Selected: qwen38 …`. Autre chose = VRAM occupée, arrêter et purger.
- Le modèle est chargé UNE fois (`keep_alive=-1`) et libéré par le run en `finally`.
- Sortie : `wama-dev-ai/outputs/`.

## 4. Relire la sortie — jamais telle quelle

wama-dev-ai a produit des **affirmations d'absence fausses 4 fois sur 6**. Donc :

- vérifier par sondage 3 à 5 `findings` contre les sources réelles (le prompt impose
  `file` + `line` + `evidence` — s'ils manquent, le finding est à rejeter) ;
- lire `coverage.files_skipped` : une cartographie qui ne dit pas ce qu'elle n'a pas lu se fait
  lire comme exhaustive ;
- basculer en `open_questions` tout ce qui n'a pas de preuve ;
- traiter `wama_comparison` comme des **hypothèses**, jamais comme des décisions.

## 5. Consigner

Dans le document de référence du domaine (**pas un nouveau `.md`**) :

- les faits établis, avec leur référence rejouable (`corpus:chemin`) et la ligne ;
- **ce que la passe a CORRIGÉ de nos hypothèses** — c'est la valeur principale, et ça se perd si on
  ne l'écrit pas explicitement ;
- les trous identifiés côté WAMA (ce que le corpus a et que nous n'avons pas) ;
- les décisions nouvelles (Dn) avec qui tranche et quand ;
- le tableau des passes mis à jour (✅/⏳) et une entrée de journal datée.

## 6. Fin de passe

- Rien d'implémenté — le vérifier explicitement avant de clore.
- Commit local par chemins explicites (jamais `git add -A`), push seulement sur demande.
- Annoncer la passe suivante et ce qu'elle conditionne.
