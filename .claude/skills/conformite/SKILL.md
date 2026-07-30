---
name: conformite
description: Mesurer la conformité RÉELLE des apps WAMA (check_app_conformity, 40 critères couvrant F1-F5 SEULEMENT — F6/F7/F8 non mesurées) et trier les écarts en plan d'action. Utiliser après un palier de portage, quand l'utilisateur demande « où en est la conformité », « re-mesure », ou pour choisir la prochaine app/critère à porter. Le score n'est PAS l'avancement du portage : voir l'avertissement en tête du skill.
---

# /conformite — Mesure réelle + triage

La grille `/apps/` est MESURÉE, plus déclarée : ne JAMAIS éditer à la main les booléens
`_conv(...)` d'`app_registry.py` pour les critères mesurés (le rapport les écrase).

> 🔴 **CE QUE LE SCORE /40 NE DIT PAS.** Répartition réelle des critères (mesurée 2026-07-30) :
> **F1:3 · F2:5 · F3:6 · F4:1 · F5:25 · F6:0 · F7:0 · F8:0.** La grille est donc surtout une
> mesure de **F5 (paramètres/inspecteur)**, et ne voit RIEN de : contrat `BaseModelBackend`,
> déclaration VRAM au gouverneur, tirage `select_model`, capacités canoniques, appariement
> entrée↔modèle, enrichissement de prompt, navette, ETA.
>
> Conséquences pratiques, à dire à l'utilisateur quand on annonce un score :
> - un « 17/40 » ne signifie pas « 17 mécanismes sur 40 portés » — l'inventaire réel des briques
>   est dans **`wama/common/README.md`**, et il en compte davantage ;
> - une session peut faire gagner beaucoup à une app **sans bouger le score d'un point** (vécu :
>   imager, 30/07 — contrat, VRAM, tirage, capacités, tous invisibles à la grille) ;
> - donc **ne jamais conclure « portage terminé » sur le score seul**. Le score sert à détecter
>   les régressions F1–F5.
>
> ⏳ Combler la grille (critères F4 réels + F6/F7/F8) est un chantier ouvert : chaque nouveau
> critère = une entrée dans `CRITERIA` avec sa preuve.

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
