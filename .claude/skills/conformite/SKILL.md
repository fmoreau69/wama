---
name: conformite
description: Mesurer la conformité RÉELLE des apps WAMA (check_app_conformity, 40 critères F1-F8) et trier les écarts en plan d'action. Utiliser après un palier de portage, quand l'utilisateur demande « où en est la conformité », « re-mesure », ou pour choisir la prochaine app/critère à porter.
---

# /conformite — Mesure réelle + triage

La grille `/apps/` est MESURÉE, plus déclarée : ne JAMAIS éditer à la main les booléens
`_conv(...)` d'`app_registry.py` pour les critères mesurés (le rapport les écrase).

## 1. Mesurer
- `./venv_win/Scripts/python.exe manage.py check_app_conformity` (10 apps → écrit
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
