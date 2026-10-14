---
name: video-gestes
description: Filmer les gestes utilisateurs rejoués par les tests nocturnes (scénarios Playwright `ui_smoke*`) et en monter une vidéo accélérée et légendée — pour une présentation ou une démo. Utiliser quand l'utilisateur demande « une vidéo des tests », « filmer les gestes », « refaire la vidéo de la présentation », ou veut montrer ce que fait la campagne nocturne.
---

# /video-gestes — filmer la campagne nocturne sans toucher au dépôt

> ⚠ CANDIDAT (n=1, 2026-10-14). Résultat : `wama/static/presentation/videos/` (diapositive
> `#tests-gestes` de la présentation), 2 min, 30 gestes, 1080p H.264.

## Ce qu'il faut savoir avant de promettre une durée
- La campagne quotidienne compte **~300 gestes navigateur** (20 familles × 13 apps + ~40
  transverses), **~90 min** de temps réel pour ceux qui passent (relevé le 2026-10-14 sur
  `logs/nightly_tests/nightly_20261014_065510.json` — se remesure à chaque fois). Tout mettre en 2 min = ×45,
  illisible : on **choisit ~30 gestes variés** (une famille par clip, apps tournantes).
- Le rapport de la nuit (`logs/nightly_tests/nightly_<date>.json`, `stage_target == 'ui'`) dit
  lesquels passent et leur durée — choisir parmi les **OK** de la dernière nuit.

## Le geste
1. **GPU libre d'abord** (`feedback_pas_de_geste_ui_pendant_gpu`) : `nvidia-smi` +
   `celery -A wama inspect active` — un traitement en cours, on attend.
2. **Enregistrer** (WSL, cwd = dépôt, ~30 s par geste ; en tâche de fond) :
   `venv_linux/bin/python .claude/skills/video-gestes/record_gestures.py <dossier_sortie> <id1,id2,…>`
   Le script enveloppe `Browser.new_context` à l'exécution : `record_video_dir` + un **curseur
   rouge** (le headless n'en dessine pas). Il joue chaque scénario par `nightly_tests.run_one`,
   écrit `manifest.json` (ok, durée, vidéos), puis balaie les témoins (`sweep_test_witnesses`).
3. **Monter** : éditer `plan.json` (titre, fin, un clip par id avec légende), puis
   `python3 .claude/skills/video-gestes/edit_video.py <dossier_sortie> plan.json <sortie.mp4> 120`
   — `mpdecimate` retire les images figées (attentes réseau), chaque clip est accéléré pour tenir
   le budget (≥ 2,8 s, sinon la légende ne se lit pas), légende + vitesse EFFECTIVE (brute ÷ montrée).
4. **Regarder** une planche (`ffmpeg … -vf "fps=1/2.2,scale=384:-1,tile=6x5"`) avant de livrer.

## Pièges vécus (2026-10-14)
- **`browser.close()` tronque la vidéo à 1 Mio exactement** : l'encodeur est coupé. Le script
  ferme les contextes d'abord (`Browser.close` enveloppé). Un `.webm` de 1 048 576 octets = ce piège.
- Le libellé « ×1 » mentait : la décimation accélère déjà ~×4. Afficher la vitesse effective.
- Deux gestes OK la nuit ont échoué pendant l'enregistrement (`reader.panel_reflect` : requête
  restée en vol ; `media_library.natures_3d` : bouton de fermeture de l'aperçu introuvable) —
  les écarter du plan, et les SIGNALER, pas les taire.
- `<app>.ui` peut déclencher le triage VLM (diff de capture > 2 %, le curseur compte) : c'est une
  charge GPU Ollama — rester sur un GPU libre.
- **Ne PAS déposer la vidéo à la racine de `media/`** : `check_media_integrity` la compte
  « égarée » (budget à 2, le contrôle nocturne rougit). Une vidéo de présentation est un
  statique de la présentation.
