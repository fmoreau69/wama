---
name: conformite
description: Mesurer la conformité RÉELLE des apps WAMA (check_app_conformity, grille couvrant les 8 facettes F1-F8) et trier les écarts en plan d'action. Utiliser après un palier de portage, quand l'utilisateur demande « où en est la conformité », « re-mesure », ou pour choisir la prochaine app/critère à porter. Le score n'est PAS l'avancement du portage : voir l'avertissement en tête du skill.
---

# /conformite — Mesure réelle + triage

La grille `/apps/` est MESURÉE, plus déclarée : ne JAMAIS éditer à la main les booléens
`_conv(...)` d'`app_registry.py` pour les critères mesurés (le rapport les écrase).

🔴 **CE QUE LE SCORE DIT — ET NE DIT PAS.** La grille GRANDIT à chaque palier de portage, et sa
taille a été recopiée FAUSSE trois fois ici : le 2026-08-26, le total annoncé ne correspondait
même plus à la somme de sa propre liste. **Aucun chiffre de grille ne s'écrit plus à la main dans
ce skill** — le bloc ci-dessous est GÉNÉRÉ (`python manage.py doc_facts --only conformite`) et
devient rouge dès que la grille bouge. Pour la mesurer soi-même :

```bash
python -c "import json;c=json.load(open('logs/conformity_report.json'))['criteria'];import collections;f=collections.Counter(v['facette'] for v in c.values());print(len(c),'critères :',dict(sorted(f.items())))"
```

<!-- WAMA:FAITS(conformite) — généré par « python manage.py doc_facts », ne pas éditer -->
- Critères de la grille : **82** — F1:4 F2:11 F3:17 F4:9 F5:29 F6:5 F7:5 F8:2 *(relevé du 2026-08-28)*
- Apps mesurées : **10** ; dénominateur par app : **67 à 82** (un critère **non applicable** sort du calcul)
<!-- /WAMA:FAITS(conformite) -->

> Les 8 facettes de `WAMA_APP_GENERATION_ROUTE.md` sont **toutes** couvertes depuis le 30/07 —
> avant cet élargissement la grille ne voyait que F1–F5 et était **aveugle** au contrat
> `BaseModelBackend`, à la déclaration VRAM, au tirage `select_model`, aux capacités canoniques,
> à l'appariement entrée↔modèle, aux prompts, aux permissions et au nœud studio.
>
> Le dénominateur **varie par app** (se lit dans `total` du rapport, cf. bloc généré) : un
> critère peut être **non applicable** et sortir du calcul — F4 entier pour le converter
> (ffmpeg/pandoc, aucun modèle IA), les critères prompt pour une app sans champ prompt. C'est
> voulu : on ne pénalise pas une absence légitime.
>
> Conséquences pratiques, à dire à l'utilisateur quand on annonce un score :
> - le score compte des **mécanismes détectés dans le code**, pas des « fonctionnalités finies » ;
>   l'inventaire narratif des briques reste **`wama/common/README.md`** ;
> - un critère mesuré **écrase** son homonyme déclaré dans `_conv(...)` ; les clés déclarées
>   SANS critère mesuré subsistent (d'où le total affiché sur `/apps/`, union des deux) ;
> - **ne jamais conclure « portage terminé » sur le score seul** — il détecte surtout les
>   régressions et les trous d'adoption.
>
> Ajouter un critère = une entrée dans `CRITERIA` (`common/services/conformity_checker.py`) qui
> retourne `(état, preuve)`, l'état `None` valant **non applicable**. Toujours fournir la preuve
> (`fichier:ligne`) : c'est elle qui rend l'écart actionnable.

## 1. Mesurer
- `./venv_win/Scripts/python.exe manage.py check_app_conformity` — ⚠ ou `venv_linux` depuis
  WSL2, qui est la voie de RÉFÉRENCE (WAMA y tourne). Le 22/08 `venv_win` a été inutilisable
  une journée, `pgvector` y manquant : `django.setup()` échouait. Si la commande casse à
  l'import, basculer sur WSL2 plutôt que de chercher un défaut de la grille. (10 apps → écrit
  `logs/conformity_report.json`, consommé par `/apps/`).
- Détail d'une app : `--app <nom> --verbose-ok` (n'écrase pas le rapport global).

## 2. Interpréter
- ✅ = brique commune consommée · 🔶 = présent mais impl locale/partielle · ❌ = absent.
- Les 🔶 sont souvent le meilleur ratio effort/gain (le mécanisme existe, il faut le brancher
  sur la brique) ; les ❌ structurants (card partial serveur, batch commun) se traitent via
  `/port-app`.
- Un critère qui semble faux → vérifier le check dans
  `common/services/conformity_checker.py` (regex best-effort) AVANT de « corriger » l'app ;
  corriger le check si c'est lui qui se trompe (ex. verrou `cache.add` reconnu 2026-07-25).

## 3. Étendre
- Nouveau critère = une entrée dans `CRITERIA` (clé, facette F1-F8, label, check) — preuve
  `fichier:ligne` obligatoire dans le retour. Si la clé existe dans `_conv`, elle l'écrase.
- Idées en attente : M-critères non implémentés de l'audit 2026-07-25 (couleurs de boutons M2,
  modale batch schéma-driven M6, `cardSelector` aligné M8, `register_batch_sync` M12…).

## 4. Consigner
- Évolution notable des scores → une ligne dans `PROJECT_STATUS` (section du chantier concerné),
  pas de recopie de la grille (elle est vivante).
