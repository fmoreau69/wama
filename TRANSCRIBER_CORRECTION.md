# Transcriber — Couche de correction manuelle assistée par IA (spec, 2026-06)

> Discussion en cours (à finaliser avant implémentation). Inspiré de **Whispurge**
> (éditeur de transcriptions Whisper) et **Sonal** (analyse qualitative SHS), avec une
> couche d'**IA de guidage** en plus. Contexte : labo Lescot (SHS, Univ. Gustave Eiffel).

## 1. Objectif

En sortie de transcription auto + vérification de cohérence, offrir à l'utilisateur un
**éditeur de correction manuelle** : lecteur audio + **forme d'onde**, navigation aisée,
**texte synchronisé** à l'audio, et **guidage IA** (heatmap de cohérence/erreurs sous
l'onde, façon diagramme de proximité du cam_analyzer) + options de nettoyage.

## 2. À reprendre des outils existants

- **Whispurge** (web mono-fichier) : synchro auto (surlignage du segment courant via
  `currentTime`), clic segment → seek, édition inline, **split/merge/compact**, locuteurs
  au clavier, vitesse ±, raccourcis (Espace, ↑↓…), export **.docx/.rtr(Sonal)/.Purge**.
  ❌ pas de forme d'onde, ❌ pas d'IA, ❌ pas de suppression silences/hésitations.
- **Sonal** : codage/annotation par marqueurs colorés, gestion locuteurs, pseudonymisation,
  métadonnées, filtrage/export. (Inspiration pour l'analyse qualitative SHS.)

## 3. Acquis dans Transcriber (à exploiter)

- Segments `start/end/speaker_id/text/confidence/words` ; **timestamps mot-à-mot** activés
  (faster-whisper `word_timestamps`, `words` désormais conservés dans `segments_json`).
- **Confiance par segment ET par mot** (Whisper : `avg_logprob` + `word.probability`).
- Cohérence LLM **globale** (score/notes/suggestion) — à étendre **par-segment**.
- **Composant commun forme d'onde** : `common/js/wama-audio-player.js` + `_audio_waveform.html`
  (Canvas, seek, lecture exclusive, zéro dépendance) → à **étendre** (marqueurs segments +
  bande heatmap + API sync/seek).
- Diarisation **pyannote** (backend-agnostique).

## 4. Décisions prises

- **Surface = page dédiée** `/transcriber/edit/<id>/` (pas overlay) : plein écran,
  URL bookmarkable, « revenir à son travail ». L'overlay reste pour le coup d'œil (preview).
- **Persistance** : original ASR **immuable** ; version corrigée stockée à part
  (`corrected_segments_json` + statut `correction: none/draft/done`) → compare/revert,
  l'IA référence l'original ; **auto-save débounce** pendant l'édition.
- **Guidage non destructif** (au moins au début) : suggestions accept/reject, rien n'est
  altéré sans validation. Slider **Fidèle ↔ Épuré** + options *silences / hésitations
  (euh, hum…) / redondances*.
- **Heatmap** : **cohérence seule d'abord**, **confiance ajoutée ensuite**. Vert/orange/rouge
  sous la forme d'onde ; clic zone → saut + note IA.
- **Cohérence par-segment = 1 SEUL appel LLM** (liste `{segment, sévérité, note}`),
  exécutée **à la demande** (ouverture de l'éditeur), pour ne pas ralentir la transcription.

## 5. ASR — défaut & modèles (clarifié)

- **Défaut basculé sur Whisper** `large-v3` (faster-whisper) — *fait* : `BACKEND_PRIORITY`
  réordonné `whisper, vibevoice, qwen_asr`. L'ancien défaut VibeVoice était un **artefact
  d'ordre d'implémentation** (placé devant pour sa diarisation native, redondante avec
  pyannote ; 16 GB vs 10 GB ; qualité jugée moindre).
- **word_timestamps** : *fait* (capture des `words`).
- **VibeVoice** : option (diarisation native). **Qwen3-ASR** : cassé (compat) → à réparer
  (intérêt = context biasing / hotwords).
- **À évaluer plus tard** (perf vs gain) : **WhisperX** (alignement mot wav2vec2 + pyannote,
  idéal éditeur), **NVIDIA Canary-Qwen-2.5B** (n°1 HF Open ASR, FR), **IBM Granite Speech 3.3**
  (FR). Variante rapide : **large-v3-turbo**.

## 5ter. Forme d'onde — fichiers longs & overlay (décision d'archi)

- Le lecteur commun décode tout le PCM en mémoire → **échoue sur les fichiers longs**
  (ex. m4a 87 min). Repli livré : **timeline simple seekable** (>30 Mo ou décodage
  échoué) — lecture + seek + synchro texte OK, seuls les pics d'amplitude manquent.
- **Ticks de segments + heatmap = overlays mappés sur le TEMPS** (`x = temps/durée`),
  **indépendants du décodage** → s'affichent identiquement sur l'onde décodée OU sur la
  timeline de repli. À dessiner comme **calque propre à l'éditeur** au-dessus de
  `.wama-waveform` (ne pas coupler au lecteur commun).
- **« Waveform par parties »** (décodage par fenêtres / pics pré-calculés serveur pour
  les longs fichiers) = amélioration visuelle **reportable**, découplée des features de
  correction. MIME `.m4a → audio/mp4` enregistré dans settings (lecture fiable).

## 6. UI/UX cible

Page éditeur : **forme d'onde** (playhead + ticks segments + **bande heatmap**) en haut ;
**transcript synchronisé éditable** au centre (surlignage courant, clic→seek, inline edit,
split/merge/compact, locuteur ; suggestions de nettoyage en surimpression accept/reject) ;
**barre de guidage** (slider rigueur + interrupteurs silences/hésitations/redondances).
Clavier-first (Whispurge). Sauvegarde → texte/segments corrigés → ré-export (txt/srt/pdf/docx,
+ .rtr Sonal optionnel pour interop SHS).

## 7. Phasage

1. **Éditeur core** : page + forme d'onde commune étendue (sync + ticks) + édition segments
   (inline/split/merge/compact + locuteur) + persistance corrigé/auto-save. (= Whispurge intégré)
   → **🔶 Phase 1a livrée** : page `/transcriber/edit/<id>/` (vue `edit` + `save_correction`),
   modèle `corrected_segments_json` + `correction_status` (migration 0010), forme d'onde via
   le composant commun (étendu **additivement** : `getAudio`/`seek`/`ensureInit`), liste de
   segments **synchronisée + éditable inline** (texte + locuteur), clic ▶ segment → seek,
   surlignage du segment courant, **clavier** (Espace play/pause, Tab segment suivant),
   **auto-save débounce** + bouton « Terminer » (reconstruit les lignes pour SRT). Bouton
   **« Corriger »** sur les cards SUCCESS (badge brouillon/corrigé).
   → **Phase 1b en cours** : **ticks de segments sur l'onde ✅** (calque `.seg-tick`
   mappé sur le temps, indépendant du décodage, fondation de la heatmap) ; clavier deux
   modes Navigation/Édition + shuttle JKL (échelle ◀◀16×…16×▶▶) ✅ ; repli timeline pour
   fichiers longs + MIME .m4a ✅. **Split / merge / compact ✅** (Ctrl+Entrée scinde au
   curseur ; Suppr en fin / Backspace au début fusionne ; bouton « Compacter » = même
   locuteur ; recalcul des timestamps au prorata, ticks + auto-save). **→ Phase 1b
   complète.** Prochain : **Phase 2 — heatmap cohérence par-segment** (réutilise le calque
   `.seg-tick`).
2. **Heatmap par-segment** sous l'onde + navigation. → **2a ✅ livrée** : bande
   `#segHeatmap` (zones `.hz` mappées temps), pilotée par la **confiance ASR**, clic→seek,
   tooltip, légende ; lit déjà `coh_severity`/`coh_note` pour basculer sur la cohérence.
   **2b ✅ livrée** : `analyze_segments_coherence` (1 appel LLM défensif) wiré dans le
   worker (step 8b, si `verify_coherence`) → `coh_severity`/`coh_note` dans `segments_json` ;
   l'éditeur bascule la heatmap sur la cohérence (priorité sur la confiance), tooltip = note IA.
   + **Refresh des cards corrigé** (polling résilient + reload sur SUCCESS). **→ Phase 2 complète.**
3. **Confiance** (mot/segment) — déjà la source de la heatmap 2a.
4. **Guidage** (slider rigueur + hésitations/silences/redondances) en suggestions accept/reject
   (règles FR + gaps de segments + LLM).
5. (option) export **.rtr/Sonal**.

> Performance : signaux gratuits (confiance) d'abord ; LLM par-segment en 1 passe à la demande ;
> turbo dispo. Mener le transcriber au bout AVANT de généraliser aux autres apps.
