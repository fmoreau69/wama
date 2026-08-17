# Prospection avatars parlants open-source — 2026-08-17

> **Référence du domaine : `ROADMAP.md §Études/veille` (entrée « Avatars parlants interactifs
> type Praktika »)** — ce document est le RAPPORT COMPLET de la prospection (agent web,
> licences vérifiées **au fichier LICENSE des repos**, pas au badge GitHub), conservé pour y
> revenir (demande Fabien 18/08). Arbitrage : TalkingHead = 1ʳᵉ voie du mode avatar de
> l'AI-Assistant (la moins conséquente), **sans exclure** les autres candidats.

Contexte : WAMA (labo recherche universitaire FR, RTX 4090 24 Go, Python/Django, MuseTalk +
CodeFormer déjà intégrés). Deux cas d'usage — PAS l'apprentissage de langues :
**(a)** génération OFFLINE de vidéos de consignes avec un avatar type « scientist » ;
**(b)** mode AVATAR PARLANT temps réel pour l'AI-Assistant (l'alternative texte+TTS existe).

Légende : **[vérifié repo]** = LICENSE/stats lus sur le repo · **[annoncé README]** = chiffres
des auteurs, non reproduits.

## 1. Frameworks temps réel interactifs — cas (b)

| Candidat | Repo | Licence | Points clés |
|---|---|---|---|
| **LiveTalking** | github.com/lipku/LiveTalking | **Apache-2.0** [vérifié] (README demande un filigrane sur vidéos publiées — clause hors licence) | Moteurs : **musetalk** (déjà dans WAMA), wav2lip, ernerf, Ultralight. [annoncé] musetalk **72 FPS/4090**. **WebRTC natif**, RTMP, caméra virtuelle ; TTS pluggables (EdgeTTS/GPT-SoVITS/CosyVoice) ; API HTTP, interruption, multi-sessions, Docker. 8,8k ⭐, PyTorch 2.9.1/CUDA 12.8 (proche venv WAMA) — actif. **Le plus aligné WAMA** (réutilise MuseTalk + fournit la couche streaming manquante). |
| **OpenAvatarChat** (Alibaba HumanAIGC) | github.com/HumanAIGC-Engineering/OpenAvatarChat | **Apache-2.0** [vérifié] | Tout-en-un modulaire : VAD silero → ASR (SenseVoice/Qwen-Omni) → **LLM OpenAI-compatible (→ Ollama local)** → TTS (CosyVoice) → avatar (**MuseTalk**, LiteAvatar 2D, **LAM** gaussien 3D rendu CLIENT, FlashHead). [annoncé] réponse ~2,2 s ; duplex + interruption. 3,7k ⭐, très actif. Monolithique — à piller en COMPOSANTS (LAM, gradio-webrtc). |
| **Ditto-talkinghead** (Ant, ACM MM 2025) | github.com/antgroup/ditto-talkinghead | **Apache-2.0** [vérifié] | Photo+audio → tête parlante temps réel via **TensorRT** (base LivePortrait). Pas de chiffre de latence au repo [vérifié : absent] ; moteurs TRT « Ampere_Plus » (4090 Ada couverte, conversion ONNX→TRT à refaire). Sans couche WebRTC → à emboîter dans LiveTalking. 862 ⭐. |
| DUIX Mobile | github.com/duixcom/Duix-Mobile | label « Other » [vérifié API] — LICENSE custom NON lu | [annoncé] <1,5 s, rendu on-device Snapdragon. SDK mobile/embarqué → **hors cible** serveur Django. 8,2k ⭐. |

## 2. Génération offline haute qualité — cas (a)

| Candidat | Repo | Licence | Points clés |
|---|---|---|---|
| **EchoMimicV3(-Flash)** (Ant, AAAI 2026) | github.com/antgroup/echomimic_v3 | **Apache-2.0** [vérifié] | 1,3B, tête+**corps**, audio EN/ZH, prompt-guidé. [annoncé] testé **RTX 4090D 24 Go**, quantifié **12 Go**. Flash 01/2026 (8 steps, 768²). Au-dessus de MuseTalk (génération complète vs inpainting). **Successeur naturel dans l'avatarizer.** 1,0k ⭐. |
| EchoMimicV2 (CVPR 2025) | github.com/antgroup/echomimic_v2 | Apache-2.0 | Demi-corps, 16 Go ; supplanté par V3, plus mûr (4,6k ⭐). |
| **MultiTalk** (MeiGen, NeurIPS 2025) | github.com/MeiGen-AI/MultiTalk | **Apache-2.0** [vérifié] | Base Wan2.1-**14B** ; multi-personnes, chant, **cartoon**, 15 s, 480/720p. [annoncé] 480p sur UNE 4090 (`--num_persistent_param_in_dit 0`), INT8, TeaCache, LoRA 4-8 steps. Très actif (05/2026). ⚠ poids ~30-60 Go disque. 3,0k ⭐. |
| **StableAvatar** | github.com/Francis-Rings/StableAvatar | **MIT** [vérifié] | Base Wan2.1-**1,3B** légère. [annoncé] ~18 Go (3 Go offload) ; 5 s de 480×832 en ~3 min/4090 ; **longueur illimitée SANS post-processing** (pas de CodeFormer requis) → idéal consignes longues. 1,3k ⭐, actif. |
| FantasyTalking (ACM MM 2025) | github.com/Fantasy-AMAP/fantasy-talking | Apache-2.0 [vérifié] | Wan 14B 720p, script `infer_24G.sh` (20 Go, 32,8 s/it) — très lent. 1,6k ⭐. |
| Sonic (Tencent, CVPR 2025) | github.com/jixiaozhong/Sonic | **CC BY-NC-SA 4.0** [vérifié] = NC, **acceptable labo** | Base SVD, bonne qualité portrait ; testé 32 Go [annoncé] → juste sur 24 Go (fork ComfyUI passe). Peu actif depuis 05/2025. 3,3k ⭐. |
| Hallo2 (ICLR 2025) | github.com/fudan-generative-vision/hallo2 | « MIT » **mais** module SR = **S-Lab 1.0 NC** [vérifié README] (même contrainte que CodeFormer WAMA) | Long-durée/4K uniques ; **anglais seul**, image carrée frontale, testé A100, quasi plus maintenu, CUDA 11.8 figé. |
| Hallo3 | github.com/fudan-generative-vision/hallo3 | « MIT » + hérite licence **CogVideoX-5B** [vérifié] | Testé **H100 only**, anglais seul → écarté pour la 4090. |
| ⛔ **HunyuanVideo-Avatar** (Tencent) | github.com/Tencent-Hunyuan/HunyuanVideo-Avatar | **ÉLIMINATOIRE : la licence Tencent Hunyuan EXCLUT l'UE** — « THIS LICENSE AGREEMENT DOES NOT APPLY IN THE EUROPEAN UNION… » ; usage UE « unlicensed » [**vérifié : LICENSE décodé via l'API**] | Inutilisable au labo, quelle que soit la qualité. **Réflexe : vérifier tout modèle Hunyuan.** (HunyuanPortrait : video-driven + SVD research only → hors cible.) |
| V-Express (Tencent AI Lab) | github.com/tencent-ailab/V-Express | code libre, **poids NC research only** [vérifié README] | ~8 Go mais ~44 min pour 31 s [annoncé], mort depuis 10/2024 → écarté. |
| AniPortrait | github.com/Zejun-Yang/AniPortrait | Apache-2.0 | Figé 04/2024, SD 1.5 — dépassé. |
| LivePortrait (Kuaishou) | github.com/KwaiVGI/LivePortrait | MIT + **InsightFace embarqué NC research** [vérifié LICENSE] | **Video-driven seulement** ; audio via dérivés : **JoyVASA** (github.com/jdh-algo/JoyVASA, MIT vérifié, 8 Go, PAS temps réel, encodeur hubert-chinese seul opérationnel) ou Ditto. 18,9k ⭐. |

## 3. Avatars 3D/stylisés côté navigateur — la voie « Praktika »

**TalkingHead (met4citizen)** — github.com/met4citizen/TalkingHead — **MIT** [vérifié], 1,5k ⭐,
v1.7, actif.
- Avatar 3D corps entier **dans le navigateur** (three.js/WebGL) : **zéro VRAM serveur**, aucun
  conflit avec les files Celery/gouverneur.
- Modèles **GLB Ready Player Me** (rig Mixamo + 52 blendshapes ARKit + 15 visèmes Oculus).
  RPM = service tiers (conditions propres) ; alternative : GLB « scientist » via
  MPFB/Blender/VRoid.
- **Lip-sync à règles AVEC module FRANÇAIS** (en/de/fr/fi/lt) — rare et décisif.
- **API streaming temps réel** (`streamStart`/`streamAudio`, AudioWorklet PCM 16 bits) : se
  branche sur tout TTS fournissant audio(+timestamps de mots) → le mode texte+TTS de
  l'assistant devient texte+TTS+avatar quasi gratuitement. Compagnons : HeadTTS (Kokoro
  navigateur), HeadAudio (lip-sync audio sans transcription).
- Live2D : SDK propriétaire (pas open-source) → écarté au profit de la chaîne GLB/three.js.
  LAM (via OpenAvatarChat) = l'équivalent photoréaliste gaussien rendu client.

## Synthèse

**Top 3 cas (a) — consignes offline** : ① EchoMimicV3(-Flash) (Apache, conçu 24 Go, tête+corps)
② StableAvatar (MIT, léger, vidéos longues sans post-processing) ③ MultiTalk (Apache, cartoon/
multi-personnages, disque lourd). Repêchage qualité : Sonic (NC OK labo). **Interdit UE :
HunyuanVideo-Avatar.**

**Top 3 cas (b) — assistant temps réel** : ① **TalkingHead met4citizen** (MIT, navigateur =
zéro GPU serveur, visèmes FR, streaming ; effort = JS/intégration, pas ML — **1ʳᵉ voie actée,
non exclusive**) ② LiveTalking (Apache, MuseTalk réutilisé, 72 FPS/4090, WebRTC ; coût = GPU
mobilisé par session → arbitrage resource_governor) ③ OpenAvatarChat (source de composants).

**Pièges d'intégration** :
- **Licences à double étage** (label GitHub ≠ réalité : LivePortrait/Hallo2/Hallo3/V-Express) —
  toujours décoder LICENSE + README ; consigner licence+auteur en base (politique
  `/common/licences/`).
- **Exclusion territoriale UE** chez Tencent Hunyuan (vérifiée ici) — réflexe permanent.
- **Empilement CUDA divergent** : candidats anciens (Hallo2 CUDA 11.8, AniPortrait 11.7) =
  venv séparé ; Ditto = TensorRT 8.6 ; LiveTalking (2.9/12.8) proche du venv WAMA.
- **Poids Wan 14B** (MultiTalk, FantasyTalking) ≈ 30-60 Go — impacte AI-models/ et le tirage
  de sauvegarde.
- **GPU partagé** : un avatar photoréaliste temps réel occupe la 4090 pendant la session —
  argument structurel pour le rendu navigateur (TalkingHead/LAM) côté assistant.
- **Langue** : Hallo anglais-only ; EchoMimic EN/ZH ; le FR est mieux servi par wav2vec2
  multilingue ou les visèmes TalkingHead (module `fr`).
- **Style cartoon « scientist »** : MultiTalk le revendique ; EchoMimicV3/StableAvatar sont
  entraînés sur de l'humain réel — essais requis avant de promettre un avatar stylisé.
