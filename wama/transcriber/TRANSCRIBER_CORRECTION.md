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

⏳ **Ajout 2026-09-16 (Fabien) — ce que le modèle PIPELINE apportera ici, et ce qu'il n'apportera
pas.** Le transcriber porte déjà le bon socle : ASR immuable + correction à part, donc relancer la
transcription **ne détruit pas** la correction (`transcriber/views.py:50-60`). Ce qui manque est le
NOM de l'état intermédiaire : quand une nouvelle génération existe, l'éditeur ne propose que
« charger la dernière transcription (cela remplacera votre correction) » (`transcriber/views.py:653-663`,
`templates/transcriber/edit.html:232-236`) — garder une correction périmée, ou la perdre.
Avec le modèle du 15/09 (`WAMA_APP_GENERATION_ROUTE.md §10.6`), la correction devient un **process**
dont l'amont est l'ASR : relancer l'ASR la marque **`STALE`** (« ta correction ne correspond plus à
cette transcription »), sans rien écraser — conforme au « guidage non destructif » ci-dessus — et
chaque étape (diarisation, résumé, cohérence) se relance seule au lieu de tout refaire.
⚠ **Ce que `STALE` ne règle PAS** : reporter les corrections déjà faites sur la nouvelle génération
(fusion/rebasage). C'est un chantier PROPRE au transcriber, non engagé, à décider séparément
(aligner les segments par temps/texte, rejouer les corrections, signaler les conflits).

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
   **2c ✅ livrée (2026-09-24) — outil Bornes** (décisions de Fabien du 2026-09-23 : une borne
   par jonction, deux gestes, jamais un mot coupé ni perdu, un outil dédié, pas de touches I/O).
   Calcul COMMUN et sans modèle (`word_anchoring.move_boundary` / `split_turn`, vue
   `retime_segments` qui fournit les mots ASR pour réancrer un texte corrigé) ; le geste reste dans
   `edit.js` tant que le transport commun n'est pas conçu (`WAMA_DATA_WORLD §5`). Au passage, la
   scission et les fusions **gardent les mots horodatés** au lieu de les jeter (`words: undefined`)
   et une scission au curseur prend l'heure entre deux mots, plus au prorata des caractères.
   ⏳ Non fait : les « modes d'écriture » en lecture (Write/Touch/Latch façon Pro Tools), discutés
   le 2026-09-23, restent une idée.
3. **Confiance** (mot/segment) — déjà la source de la heatmap 2a.
4. **Guidage** (slider rigueur + hésitations/silences/redondances) en suggestions accept/reject
   (règles FR + gaps de segments + LLM).
5. (option) export **.rtr/Sonal**.

> Performance : signaux gratuits (confiance) d'abord ; LLM par-segment en 1 passe à la demande ;
> turbo dispo. Mener le transcriber au bout AVANT de généraliser aux autres apps.

---

## 8. ⚠ Biais du guidage par cohérence — fidélité vs fluidité (constaté 2026-07-29)

### 8.1 Constat (ancré dans le code, pas une hypothèse)

`analyze_segments_coherence` (`wama/common/utils/llm_utils.py` — ancre symbolique, les numéros de
ligne de ce module dérivent) demande au LLM de signaler :
« répétitions, phrases tronquées/incomplètes, hallucinations, **incohérences sémantiques**, mots
douteux ». Sur un **entretien**, répétitions + phrases tronquées + incohérences sémantiques sont la
définition même de la parole réelle : le guidage signale donc systématiquement ce qu'il faut
**préserver**. `verify_text_coherence` (même module) va plus loin — son champ `suggestion`
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

## 9. Corriger une transcription — le guide
<!-- WAMA:SECTION(audience=utilisateur; type=guide; nature=constat; etat=✅; porte=apps/transcriber) -->
<!-- Écrit et confronté au code le 2026-09-14 (1ʳᵉ source de la doc utilisateur, ROADMAP §25.1 ⑤) :
     wama/transcriber/templates/transcriber/edit.html, wama/transcriber/static/transcriber/js/edit.js
     (gestionnaire clavier, heatmap, auto-save), wama/transcriber/views.py (save_correction). -->

Une fois la transcription terminée, sa card porte un bouton **Éditer** (icône crayon). Il ouvre
l'éditeur : la forme d'onde, une bande colorée qui signale les passages douteux, et la liste des
segments, synchronisée avec la lecture. Le survol du bouton dit où en est la correction :
brouillon en cours, ou corrigée.

### 9.1 Deux modes : naviguer, puis éditer

À l'ouverture, l'éditeur est en **navigation** : le clavier pilote l'audio et la sélection des
segments. `Entrée` ouvre le texte du segment sélectionné — c'est le mode **édition**, où les
touches servent à taper ; `Échap` revient à la navigation.

| touche | en navigation | en édition |
|---|---|---|
| `Espace` | lecture / pause | (tape un espace) |
| `J` · `K` · `L` | un cran vers l'arrière · arrêt · un cran vers l'avant (plus rapide à chaque appui) | — |
| `←` · `→` | recule · avance de 5 secondes | — |
| `↑` · `↓` | segment précédent · suivant | — |
| `Tab` · `Maj+Tab` | la lecture saute au segment suivant · précédent | champ suivant · précédent |
| `Alt+↑` · `Alt+↓` | segment précédent · suivant | segment précédent · suivant |
| `Alt+L` | verrouille ou libère le suivi de lecture | idem |
| `Ctrl+Entrée` | coupe le segment à la tête de lecture | coupe le segment à l'endroit du curseur |
| `C` | outil **Bornes** (voir ci-dessous) ; `Échap` pour le quitter | — |
| `Suppr` en fin de texte | — | fusionne avec le segment suivant |
| `Retour arrière` en début de texte | — | fusionne avec le segment précédent |
| `Ctrl+Z` · `Ctrl+Maj+Z` | annule · rétablit | idem |

### 9.1bis Déplacer une borne, couper un segment

Sur la forme d'onde, un trait marque chaque **borne** : la fin d'un segment est le début du
suivant. Les passages hachurés sont des silences qu'aucun segment ne couvre. Le bouton **Bornes**
(ou la touche `C`) active l'outil :

- **glisser une borne** la déplace ; les mots passent d'un segment à l'autre selon leur heure ;
- **cliquer dans un segment** le coupe en deux à cet endroit (ciseaux) ;
- glisser ailleurs que sur une borne déplace la vue, comme sans l'outil.

Une borne se pose toujours **entre deux mots**, jamais au milieu d'un mot, et chaque segment garde
au moins un mot : aucun mot n'est perdu. Si vous avez corrigé le texte d'un segment, ses mots
sont d'abord recalés sur la transcription automatique. Chaque geste s'annule avec `Ctrl+Z`.
`Échap` quitte l'outil.

### 9.2 La bande de qualité

Chaque segment y a sa couleur : vert, orange ou rouge. Si la vérification de cohérence a été
demandée, la couleur vient de l'IA et le survol affiche sa remarque ; sinon, elle vient de la
confiance de la reconnaissance vocale. Un clic sur une zone y place la lecture et sélectionne le
segment.

### 9.3 Enregistrer, terminer

Les modifications s'enregistrent seules, peu après la frappe ; l'indicateur de la barre d'outils
affiche « À jour » quand c'est fait, et le texte téléchargeable suit la correction. **Compacter**
fusionne les segments consécutifs d'un même locuteur. **Terminer la correction** marque la
transcription comme corrigée et reconstruit ses sous-titres.

### 9.3bis Évaluer une transcription contre une référence

Si vous disposez d'une transcription juste — corrigée à la main, par exemple un export Sonal —,
WAMA peut mesurer l'écart entre elle et la transcription automatique. Dans le menu d'une card
(bouton « … » ou clic droit), **Résultat de référence… → Joindre…** : choisissez le fichier
(SRT, VTT, TXT, DOCX, PDF ou Markdown). Seul le texte placé sous un locuteur (`Speaker 1 :`…) est
comparé ; titres, en-têtes et notes sont écartés.

L'onglet **Évaluation** de la card affiche alors le taux d'erreur par mot (WER) et par caractère
(CER), avec le détail : mots remplacés, oubliés, ajoutés. Les hésitations (« euh ») comptent : ce
sont des paroles. La casse et la ponctuation ne comptent pas.

Pour **comparer plusieurs moteurs** sur le même audio : dupliquez la card dans son lot (« Dupliquer
dans le batch »), choisissez un autre moteur sur le double, relancez, puis posez la référence sur
le lot entier (menu de la card du lot : **Référence du lot…**). Une ligne sous la card du lot
classe les moteurs, le meilleur en tête. Une transcription faite par un autre outil se compare de
la même façon : sur un double de la card, **Résultat existant… → Reprendre un fichier…**.

Sans référence, la même ligne indique l'**accord entre moteurs** : le pourcentage de désaccord de
chacun avec les autres, sur le même audio. Il montre où regarder, pas qui a raison — aucun moteur
n'y est déclaré meilleur. À partir de trois moteurs, celui qui s'écarte le plus est signalé en
orange.

### 9.4 Le guidage de nettoyage
<!-- WAMA:SECTION(audience=utilisateur; type=guide; nature=intention; etat=⏳; porte=apps/transcriber) -->

Une barre de guidage proposera des nettoyages — silences, hésitations, redondances — à accepter
ou refuser un par un : rien ne sera modifié sans validation (§4, Phase 4 du §7). Ses réglages
découleront du profil de transcription choisi — entretien verbatim, réunion, conférence,
sous-titrage (§8.4).

## 10. Transcriptions produites ailleurs — référence et résultat existant (chantier ouvert le 2026-09-23)

> Demande de Fabien (2026-09-23) : évaluer les modèles ASR contre une transcription corrigée à
> la main (exports Sonal), et pouvoir reprendre une transcription faite ailleurs pour la corriger
> sur l'audio sans retranscrire. C'est la porte d'entrée `Q6` de `WAMA_QUALITE.md`.

**Deux rôles, pas deux mécanismes** — les ports du RÉSULTAT (`INPUT_MODEL_MATCHING §6.7`) :
une card = 1 audio + au plus 1 **résultat existant** (`work_result` : il tient lieu de
transcription) + au plus 1 **résultat de référence** (`reference_result` : la sortie lui est
comparée). On compare toujours le texte de la card à sa référence. Comparer N moteurs = un LOT de
N cards sur le même audio, le moteur étant le seul axe qui varie (`ROUTE §10.6`) ; la référence
se pose au niveau du lot, qui l'applique à ses cards — pas de « card de référence ».

**10.1 Lecture ✅** — `utils/transcript_documents.py::read_transcript_document` : SRT et VTT
(temps exacts, locuteur `[Nom]` de l'export WAMA ou `<v Nom>`), et documents à tours de parole
TXT/MD/DOCX/PDF par l'extracteur COMMUN (`batch_parsers.extract_batch_file_text`).
**Règle : n'est de la parole que ce qui suit un label de locuteur** ; un séparateur (`=====`) ou
un en-tête d'extrait Sonal clôt le tour ; le reste (titre, en-tête d'export, titres d'extraits,
résumé d'un export WAMA) est rendu à part (`outside_speech`) et jamais compté. Un document SANS
aucun label est tout entier de la parole. Les extraits Sonal (`1 - 00:00 > 10:56 [thème]`)
deviennent des FENÊTRES grossières, pas des temps de segments — ils serviront à l'alignement.
Labels reconnus, volontairement étroits : `Speaker N :`, `SPEAKER_NN:`, `Locuteur N :`,
`Intervenant N :`, `[Nom]  0:12—0:40` (exports WAMA). Tests : `tests_transcript_documents` (12,
contenus inventés — le dépôt est public).
✅ **Confirmé par Fabien (2026-09-23)** : dans un export Sonal, la ligne entre l'en-tête d'extrait
et le premier locuteur est un ajout d'édition de l'utilisateur, pas de la transcription — hors
parole, comme la règle le traite. Toute la parole est un paragraphe introduit par `Speaker x :`.

**10.2 Mesure ✅ (2026-09-23)** — brique COMMUNE `common/services/result_evaluation.py` (le
transcriber n'a écrit que sa DÉCLARATION, `apps.py:register_evaluation`) : WER et CER
(`text_metrics`, casse et ponctuation ignorées, hésitations COMPTÉES — verbatim), conservés par
élément dans la table commune `ResultEvaluation` (décision Q2 de Fabien : une table commune, pour
que l'indice interne des modèles l'agrège). **On mesure la sortie ASR (`segments_json`), jamais la
correction humaine** qui écrase `text`. Mesure en fin de traitement si une référence est posée ;
une relance efface la mesure, garde la référence. Le modèle mesuré est la clé CATALOGUE exacte
(`Transcript.model_key`, posée par le worker avant `unload()` — `catalogue_key_for` tranche entre
les variantes d'un moteur).

**10.3 Lot d'évaluation ✅ (avec référence)** — la référence se pose sur la card OU sur le lot (menu
« … » / clic droit : « Résultat de référence… », « Référence du lot… » ; un seul fichier, partagé).
Onglet **« Évaluation »** de la card (taux, substitutions / suppressions / insertions, longueurs, ce
que la lecture a écarté) ; **ligne fine sur la card mère** : modèles classés par taux de CORPUS
(Σ erreurs / Σ mots de référence), le meilleur marqué — sauf si les références diffèrent, ce qui
est DIT. **Lot SANS référence ✅ (2026-09-23)** : même ligne, « Accord entre moteurs » — pour les
cards d'une MÊME entrée (même fichier audio : les doubles le partagent), le désaccord deux à deux
M1 (`divergence_segments`, moyenné dans les deux sens) et, par moteur, la médiane de ses
désaccords (M6). Jamais de « meilleur » : sans vérité, un désaccord ne dit pas qui se trompe ; à
partir de trois moteurs, le plus ISOLÉ est signalé (ambre). Un résultat existant non horodaté est
« non comparé » (M1 aligne sur le temps). Calculé à l'affichage, mis en cache par empreinte des
résultats ; un lot ordinaire (un fichier par card) ne coûte rien. M1 est devenue linéaire en
pratique à résultat IDENTIQUE (`tests_divergence`) : 1 h d'audio en 0,03 s au lieu d'un filtre
quadratique.

**10.4 Résultat existant ✅** — « Résultat existant… » sur une card : la transcription faite
AILLEURS devient son résultat (`external:<nom>`), mesurée comme un modèle. Geste type pour comparer
un outil externe : dupliquer la card audio dans le lot, reprendre le fichier sur le double. ▶ la
RÉ-importe (jamais d'ASR à sa place). Un document horodaté (SRT, VTT) s'écrit comme une sortie ASR ;
**sans temps** (Sonal, texte), aucun temps n'est inventé : le texte s'**aligne** sur l'audio
(§10.5 — ancrage sur l'ASR, puis aligneur acoustique).

**10.5 Alignement d'un texte sans temps — deux étages (plan acté par Fabien le 2026-09-23)**

Le problème n'est pas le choix d'un modèle mais l'ÉCHELLE : un aligneur acoustique aligne un
extrait court (Qwen3-ForcedAligner : 5 min par appel ; un aligneur CTC : une table temps × texte
impossible sur 1 h). Il faut d'abord des ANCRES qui découpent le texte. Le découpage des audios
longs EXISTE déjà (`workers._transcribe_maybe_chunked`, sous le contrat `max_audio_seconds` du
commun) : l'aligneur sera un moteur de plus sous ce contrat, et c'est l'étage A qui dit à chaque
morceau d'audio quels mots du texte lui reviennent.

- **Étage A ✅ (2026-09-23) — ancrage sur les mots de l'ASR, sans modèle** (brique commune
  `common/services/word_anchoring.py`) : chaque mot du texte retrouve l'heure du même mot entendu
  par l'ASR (plus longue sous-suite commune des mots) ; un mot CORRIGÉ se place dans la durée réelle
  des mots que l'ASR avait entendus à sa place (`estimated`) ; un mot que l'ASR n'a pas entendu
  (« euh » souvent) se place entre ses voisins (`interpolated`). Branché sur l'import d'un
  **résultat existant** sans temps (§10.4) : ancres = la sortie ASR de la card avant l'import, sinon
  d'une card SŒUR sur le même audio (un double du lot) ; un texte ancré s'écrit comme une sortie
  ASR (segments + lignes, donc éditeur, SRT, comparaison entre moteurs). Les extraits Sonal servent
  de contrôle (tours ancrés hors de leur extrait = signalés en console). Au relancement, la card
  garde ses ancres.
  **Mesuré sur données réelles** (versions corrigées privées de leurs temps, ré-ancrées sur leur
  ASR) : #172 et #173 100 % de mots retrouvés, écart nul au temps connu ; #135 (la seule vraie
  correction du dépôt, 14 859 mots) 99,7 %, écart médian et p95 nuls, maximum 4,96 s — sur un
  passage corrigé, où le temps ENREGISTRÉ vient peut-être du prorata de l'éditeur ; 1,4 s de calcul.
- **Étage B ✅ (2026-09-24) — aligneur acoustique.**
  - **Contrat commun** `common/backends/forced_alignment_base.py::ForcedAlignmentBackend`, frère de
    `speech_to_text_base` : `align(fenêtre audio, mots) → heure de chaque mot` (None pour un mot
    sans lettre prononçable), `max_audio_seconds`, gouverneur VRAM hérité de `BaseModelBackend`.
    La LANGUE n'y est pas : c'est le modèle qui la porte, au catalogue.
  - **Premier moteur** `Wav2Vec2AlignerBackend` : Viterbi CTC (`torchaudio.functional.
    forced_align`), lettres → trames → mots, fenêtre d'une minute au plus. Le cœur
    (`align_emission`) se teste sans réseau, sur une émission fabriquée.
  - **Au catalogue, piloté par métadonnée** : `transcriber:wav2vec2-fr-aligner`
    (`jonatasgrosman/wav2vec2-large-xlsr-53-french`, Apache-2.0, ~1,3 Go,
    `MODEL_PATHS['speech']['alignment']`). Tâche **`alignment`**, nouvelle au vocabulaire
    (`ModelTask`, catégorie `speech`, entrées `work_audio` + `work_result`), donc absente des
    sélecteurs d'ASR. L'aligneur se CHOISIT par tâche et par langue de l'audio
    (`workers._aligner_model` → `select_model`) : un aligneur d'une autre langue s'ajoute dans
    `model_config.ALIGNMENT_MODELS`, sans toucher au code.
  - **Fenêtres** (`word_anchoring.refine_turns`, sans modèle) : chaque passage incertain est aligné
    avec ses deux voisins pour GARDES — un voisin sûr borne la fenêtre à son propre mot. Un passage
    plus long que la capacité se coupe ENTRE deux mots, aux heures estimées ; une fenêtre qui
    échoue garde l'estimation de l'étage A. Les mots repris deviennent **`aligned`**, avec leur
    confiance acoustique dans `probability`.
  - **Déclenchement** : automatique, après l'import d'un résultat existant qui garde des mots
    incertains (`transaction.on_commit` → `align_existing_result`, file GPU). Le résultat est
    utilisable dès l'étage A ; l'étage B l'améliore ensuite. Sans aucune sortie ASR de l'audio,
    Whisper transcrit d'abord pour fournir les ancres, et sa sortie ne sert qu'à ancrer.
  - **Mesuré avec les vrais poids** (CPU, parole française INVENTÉE synthétisée par Kokoro, trois
    phrases séparées par des silences connus) : bornes de phrase à ±0,06 s de la vérité ; une
    phrase volontairement mal estimée (étalée sur 3,7 s de trop) est recalée à 3,29–4,93 s, pour
    une vérité de 3,24–4,96 s.
  - ⚠ **Écart au plan, assumé** : le découpage des audios longs de l'ASR
    (`_split_audio_chunks`, coupes à intervalle fixe) n'a PAS été modifié. L'aligneur lit ses
    fenêtres directement (`audio_decode.decode_window`), et les coupes « entre deux mots » se
    décident dans `refine_turns`, où les mots sont connus. Couper l'audio d'un ASR entre deux mots
    demanderait ces mots AVANT l'ASR (une détection de voix, par exemple) : c'est un autre chantier,
    et ce chemin sert la production. La limite v1 du découpage de l'ASR reste donc ouverte.
  - ⏳ **Pas de réglage utilisateur** pour l'instant : les modales du Transcriber sont encore
    câblées à la main (`index.js`, et non `WamaParams.settingsModal`). Ajouter un interrupteur
    obligerait à toucher 8 endroits du code de production. Il viendra par le schéma
    (`params.py`), une fois la modale portée au cycle commun.
- **Écartés, avec la raison (prospection du 2026-09-23)** : Qwen3-ForcedAligner-0.6B (Apache-2.0,
  français) exige `qwen-asr` — simulation : `accelerate` 1.6 → 1.12, `nvidia-nccl-cu12` déplacé,
  + DyNet/nagisa/soynlp — et sa variante `-hf` un transformers installé depuis les sources ;
  MMS_FA (torchaudio) : licence CC-BY-NC 4.0.
  ⚠ Relevé au passage : `nvidia-nccl-cu12` est en 2.30.4 dans `venv_linux` quand torch exige 2.27.5
  — dérive préexistante, signalée, non corrigée.
