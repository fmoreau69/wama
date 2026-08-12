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

---

## 8. ⚠ Biais du guidage par cohérence — fidélité vs fluidité (constaté 2026-07-29)

### 8.1 Constat (ancré dans le code, pas une hypothèse)

`analyze_segments_coherence` (`wama/common/utils/llm_utils.py:441`) demande au LLM de signaler :
« répétitions, phrases tronquées/incomplètes, hallucinations, **incohérences sémantiques**, mots
douteux ». Sur un **entretien**, répétitions + phrases tronquées + incohérences sémantiques sont la
définition même de la parole réelle : le guidage signale donc systématiquement ce qu'il faut
**préserver**. `verify_text_coherence` (`llm_utils.py:332`) va plus loin — son champ `suggestion`
renvoie une « version corrigée » : elle ne signale pas, elle **réécrit**.

### 8.2 Le défaut est STRUCTUREL, pas un défaut de prompt

Ces deux fonctions ne reçoivent **que du texte, jamais l'audio**. Elles ne peuvent donc pas, même en
principe, distinguer « l'ASR a halluciné » de « la personne a réellement dit ça maladroitement ».
Elles mesurent la **fluidité** et l'utilisent comme proxy de la **fidélité** — or les deux sont
**anticorrélées** sur de l'entretien : plus le texte est fidèle, plus il paraît incohérent.
Reformuler le prompt ne corrige pas ça, ça déplace le biais. Il faut un signal **ancré sur l'audio**.

⚠ Enjeu SHS : sur de l'entretien de recherche, hésitations, autocorrections et répétitions **sont des
données**. Un LLM qui les lisse en silence est un problème d'**intégrité méthodologique**, pas un
désagrément d'UI. Défaut du labo ⇒ verbatim préservé, nettoyage **opt-in**.

### 8.3 Signal à substituer : divergence inter-systèmes

Deux ASR indépendants ne se trompent pas de la même façon mais entendent la même chose :
- **divergence** ⇒ forte probabilité d'erreur réelle → c'est là qu'il faut envoyer l'humain ;
- **convergence, même sur du texte « incohérent »** ⇒ la personne l'a réellement dit (deux systèmes
  indépendants n'hallucinent pas la même hésitation).

Signal **objectif, ancré sur l'audio sans réécoute**, sans avis de LLM. Généralisable sans outil
externe : 2 passes ASR (modèles différents, ou même modèle à paramètres différents).

> **✅ Primitive livrée le 2026-08-13** — `wama/common/services/divergence.py` (brique commune :
> le besoin dépasse le transcriber, cf. la vision plus bas) + `manage.py divergence_asr` pour
> **regarder le signal avant qu'il ne pilote quoi que ce soit** (« métrique d'abord, boucle
> ensuite » — ROADMAP §16.7-4). **Rien n'est encore branché sur la heatmap.**
>
> Trois pièges trouvés en la mesurant sur les vrais transcripts, à connaître avant de s'en servir :
> 1. **L'apostrophe doit être un séparateur.** « aujourd'hui » vs « aujourd hui » sortait à 33 %
>    de divergence — un écart de tokenisation, pas d'écoute. Corrigé (0 %).
> 2. **Un passage sans vis-à-vis compte comme divergence TOTALE.** L'exclure faisait qu'un
>    système ratant la moitié de l'audio affichait une divergence *basse*.
> 3. **La GRANULARITÉ fausse tout si on n'y prend pas garde.** Sur `#172`, l'ASR a 748 segments
>    et la version humaine 106 (regroupés) : comparer chaque segment fin au gros segment qui le
>    contient rendait **72 %** pour un texte identique. La brique échange donc les rôles quand un
>    côté est plus de 2× plus fin, et le signale (`reference_echangee`). Après correction : **0 %**.
>
> ⚠ **Conséquence sur le protocole §8.5** : comparer l'ASR à la correction humaine ne mesure PAS
> la même chose que comparer deux ASR. La correction réécrit le découpage et l'horodatage
> (`_rebuild_segments_from`), si bien que la divergence y mesure surtout un re-segmentage. Pour
> calibrer les seuils sur des erreurs d'ÉCOUTE, il faut des cas où l'ASR s'est trompé de MOT —
> or sur les 6 transcripts corrigés du dépôt, **trois** (#46, #134, #142) ont un texte
> strictement identique à l'ASR (l'éditeur enregistre une « correction » même sans modification).

**Ordre de priorité de la heatmap à adopter** — ⚠ **inverse la règle actuelle** (§ « l'éditeur bascule
la heatmap sur la cohérence, priorité sur la confiance ») :
1. **Divergence inter-systèmes** — signal dur ;
2. **Confiance ASR** — déjà le repli documenté quand le LLM échoue ;
3. **Cohérence LLM** — en dernier, cantonnée à une classe **étroite et déclarée** : bascule de langue,
   boucle de répétition du *même token* (pathologie ASR connue), segment final tronqué.
   **Jamais « incohérence sémantique ».**

### 8.4 Profils = politique déclarée, pas variante de prompt

`verify_text_coherence` a déjà un `content_hint` (avec un label `'meeting'`) mais il ne change que la
**formulation** du prompt, pas le **comportement** : il dit au LLM de quoi il parle, pas ce qui compte
comme erreur ni s'il a le droit de réécrire. C'est le trou. Un profil porte 4 décisions :

| Profil | Qu'est-ce qu'une erreur | Réécriture LLM | Guidage |
|---|---|---|---|
| **Entretien / verbatim** | uniquement ce que l'audio ne soutient pas | **interdite** | divergence + confiance |
| **Réunion / CR** | tout ce qui gêne la lecture | autorisée | cohérence pertinente |
| **Conférence / cours** | disfluences oui ; terminologie et noms propres non | partielle | divergence + confiance |
| **Sous-titrage** | longueur, découpage, lisibilité | contrainte | segmentation |

Alimente la barre de guidage prévue en Phase 4 (slider rigueur + interrupteurs
silences/hésitations/redondances) : les interrupteurs deviennent des **conséquences du profil**.
⚠ Le contrat de `common/prompt_skills/` est explicitement « enrichissement de prompt génératif,
sortie = le prompt enrichi seul » : un skill de contrôle qualité **n'y entre pas tel quel** — le
traiter comme un `kind` distinct plutôt que de le faire rentrer au chausse-pied.

### 8.5 Protocole de mesure (cas de test à 4 fichiers)

Jeu de test disponible : **audio source + transcription outil externe + transcription WAMA +
version finale corrigée à la main**. Il apporte deux choses distinctes :
- **(a) référence corrigée** = vérité terrain → WER WAMA vs WER outil externe, et **localisation** des
  vraies erreurs ;
- **(b) seconde transcription** = le signal §8.3, mesurable de bout en bout.

**Le plus petit pas qui tranche** : commande de management (aucun changement d'UI) calculant le diff
`segments_json` → `corrected_segments_json` et confrontant les 3 signaux (divergence / confiance /
cohérence LLM) → **précision** (parmi les segments signalés, combien réellement corrigés) et
**rappel** (parmi les corrections réelles, combien signalées) de chacun. C'est l'A/B objectif exigé
par la règle « jamais de bascule sur impression visuelle seule ».

> Hypothèse à réfuter : la cohérence LLM sort en précision **et** rappel faibles — elle signale des
> disfluences authentiques et rate les vrais mots mal reconnus, qui sont souvent parfaitement
> plausibles en contexte.

✅ **Pas de nouvelle table nécessaire pour la 1re boucle** : `corrected_segments_json` (migration 0010)
contient déjà la version humaine. Il manque le diff et le scoring par-dessus. C'est aussi la 1re
instance concrète de la brique `RunOutcome`/`ResultFeedback` visée en ROADMAP §16.7.
