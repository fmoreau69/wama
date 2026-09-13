# VISION_CRITIQUE.md — Analyse critique de WAMA_Vision_Complet.md

> Lecture critique du document de vision (53 sections), 2026-07-18, à la lumière de l'état réel du
> code (`VISION_STATUS.md`) et de l'historique du projet. But : renforcer le document, pas le
> démolir — chaque critique est assortie d'un correctif proposé.

## Verdict global

Le cœur de la vision est **solide, original et déjà partiellement prouvé par le code** : la thèse
« capitalisation de briques + composition » contre « génération permanente de code » est lucide et
à contre-courant, et les parties II-III (manifestes, studio) décrivent une architecture qui a
émergé DE la pratique (~70-80 % déclaratif réel). Ce n'est pas une fiction.

Les faiblesses ne sont pas dans les idées mais dans **ce que le document ne dit pas** : aucun
non-objectif, aucun modèle de ressources, aucune exigence de conformité/traçabilité, et une
frontière réel/visé invisible. Ce sont précisément les manques qui, historiquement, ont produit la
dispersion que le recadrage « finir quelques apps à 100 % » a dû corriger.

## Forces (à préserver)

1. **Thèse fondatrice différenciante** (§2) : capitaliser plutôt que générer — validée
   empiriquement par le repo (briques communes réutilisées ×4-10 apps).
2. **Manifeste = contrat** (§3) : le concept structure déjà le code réel (APP_CATALOG, params_spec,
   app_modes) ; la vision décrit ici une trajectoire crédible, pas un vœu.
3. **Cohérence interne** : presque tout converge vers deux objets — le manifeste (composition) et
   l'espace de connaissance (RAG/embeddings). Peu de visions de cette taille tiennent aussi bien.
4. **Distinctions conceptuelles justes** : rôle/skill (§9), enrichissement sémantique vs
   compilation de format (§14), WAMA vs ComfyUI (§19) — ce sont de bonnes frontières.

## Critique 1 — Aucun non-objectif : une vision sans système immunitaire

53 sections, zéro « ce que WAMA ne fera pas » ni « pas avant X ». Or le risque n°1 du projet est
documenté par sa propre histoire : dispersion (10 apps entre 40 et 90 % de conformité, recadrage
2026-07-02). Le document de vision, tel quel, **tire dans la direction opposée au recadrage
opérationnel** : chaque section est une invitation à ouvrir un chantier.

**Correctif** : ajouter une section « Non-objectifs et séquencement » — ex. : pas de Story
Director avant studio complet ; pas de RAG hiérarchique avant RAG mono-niveau utile ; pas de SI
labo avant médiathèque adoptée par l'équipe ; pas de connecteurs avant assistant interne robuste.

## Critique 2 — Aucun modèle de ressources ni de pérennité

Le programme décrit occuperait plusieurs équipes pendant des années : Story Director (§21-23) est
un produit à part entière ; Data Comprehender (§27-33) un deuxième ; médiathèque universitaire +
SI labo (§34-39) un troisième. Le document ne dit jamais **qui construit, qui maintient, qui
opère** — ni comment le système survit au départ de son développeur principal (bus factor ≈ 1,
assisté par IA). Pour un document destiné aussi à des lecteurs institutionnels, c'est le premier
angle d'attaque évident.

**Correctif** : un chapitre « modèle de réalisation » honnête — développement assisté par IA,
capitalisation par briques (c'est justement la thèse !), périmètre par phase dimensionné à
l'équipe réelle, et critères d'arrêt/adoption par phase.

## Critique 3 — Le RAG est le point de défaillance unique de la moitié du document

Les §9-11 (rôles, enrichissement organisationnel), 28-31 (Data Comprehender), 34-39 (médiathèque
augmentée, SI labo, réunions) et 48-50 (assistant omniprésent) dépendent tous du RAG — qui est à
zéro ligne de code. La vision conçoit **quatre niveaux de gouvernance avant d'avoir validé la
valeur d'un seul**. C'est le schéma classique de la hiérarchie dessinée avant l'usage.

**Correctif** : réécrire §11 en trajectoire : « RAG utilisateur minimal → mesure d'usage →
extension aux niveaux supérieurs si et seulement si la valeur est démontrée ». (Cohérent avec la
décision existante « RAG après le socle ».)

## Critique 4 — La partie VIII change la nature du projet sans le dire

Passer d'un outil de labo à une **infrastructure institutionnelle** (médiathèque universitaire, SI
labo, assistant de réunions) implique : RGPD (le mot n'apparaît nulle part), droit à l'image,
consentement pour l'enregistrement/transcription de réunions, SSO institutionnel, disponibilité,
support, gouvernance des données de recherche. Le document traite cette bascule comme une simple
extension technique. Pour une université, **la barrière d'adoption est là, pas dans la technique**.

**Correctif** : chapitre « conformité et confiance » (RGPD, consentement, rétention — la rétention
par profil existe déjà dans le code, autant le valoriser), et présenter la partie VIII comme une
offre de service avec son coût d'exploitation, pas comme une suite logicielle de plus.

## Critique 5 — Tension non résolue : abstraction des modèles vs reproductibilité scientifique

§53 : « les utilisateurs ne doivent pas avoir à savoir quel modèle est utilisé ». §19 : « workflows
reproductibles ». Pour de la recherche publiable, ces deux énoncés sont contradictoires tels quels :
la reproductibilité exige modèle, version, poids, paramètres, seed. La **provenance des résultats**
(qui a produit quoi, avec quoi, sur quelles données) est absente du document — étonnant pour une
plateforme de recherche.

**Correctif** : trancher — l'orchestration CHOISIT le modèle, mais tout run est journalisé
(modèle+version+params+données) et exportable en « fiche de méthode ». Ça transforme la
contradiction en argument de vente scientifique. Les briques existent déjà en germe
(StudioRun.node_states, ModelRuntimeStat, extra_info).

## Critique 6 — La partie VII ignore la validité scientifique

« Recherche de motifs → hypothèses » (§33) sans un mot sur les comparaisons multiples, les faux
positifs, ou la distinction exploratoire/confirmatoire. Un moteur qui cherche des « corrélations
inattendues » dans des données EEG/comportementales **à l'échelle** est, sans cadre statistique,
une machine à artefacts — et le public visé (chercheurs SHS) le verra immédiatement.

**Correctif** : une sous-section « garde-fous méthodologiques » : marquage exploratoire vs
confirmatoire, correction des comparaisons multiples, tailles d'effet, et l'humain qui valide
l'hypothèse avant toute « découverte ». Ça crédibilise la vision « DeepMind du labo » au lieu de
la fragiliser.

## Critique 7 — L'auto-instanciation est présentée comme trajectoire naturelle ; c'est le pari le plus risqué

§4 et §42-cas-2 supposent qu'une IA peut analyser un modèle et générer manifeste + intégration +
tests. L'expérience mesurée du 2026-07-17 (wama-dev-ai : affirmations d'absence fausses dans 4
rapports sur 6, sur des tâches étroites) montre l'écart actuel entre cette promesse et la réalité.
Le pilotage opérationnel est d'ailleurs plus sage que la vision (« scaffold EN DERNIER », Phase B
gatée, humain-dans-la-boucle systématique) — mais le document ne reflète pas cette prudence.

**Correctif** : assumer dans le texte le gating existant : auto-instanciation = étape finale d'une
route dont chaque maillon (uniformisation → manifeste formel → conformité exécutable → scaffold)
doit être validé, toujours avec revue humaine.

## Critique 8 — « Tout devient comparable par embeddings » : problème de recherche présenté comme brique

§8 et §33 affirment que vidéo, EEG, trajectoires et événements peuvent être « reliés dans un même
espace de connaissance ». L'alignement multimodal de données scientifiques hétérogènes est un
sujet de recherche ouvert, pas une intégration sur étagère. Le document mélange sans les
distinguer : le COTS (OCR, diarization, LiteLLM), l'ingénierie (manifestes, studio), et la
recherche ouverte (espace de connaissance unifié, boucle de découverte).

**Correctif** : marquer chaque section [étagère / ingénierie / recherche]. Ça protège la
crédibilité de l'ensemble : les parties « recherche » deviennent des axes de collaboration
scientifique (thèses, projets ANR) au lieu de promesses produit.

## Critique 9 — La partie V est la plus éloignée de la mission, et la moins justifiée

Un studio complet de production audiovisuelle (Story Director, storyboard, montage, mixage,
mastering) pour un laboratoire SHS/transports : le lien avec la mission existe (communication
scientifique, supports pédagogiques, restitution d'expérimentations) mais **le document ne le fait
jamais**. C'est aussi la partie la plus consommatrice en GPU et en maintenance, sans client
interne explicitement identifié.

**Correctif** : soit ancrer chaque brique de la partie V dans un cas d'usage labo nommé (vidéo de
restitution d'expérimentation, podcast, MOOC), soit la déprioriser explicitement en « exploration
opportuniste ». En l'état, c'est le flanc « gadget » offert aux critiques.

## Critique 10 — L'évaluation continue n'est pas une couche de premier rang

§47 promet des « modèles interchangeables » ; §42 décrit la veille. Mais rien ne dit **comment on
sait qu'un modèle remplaçant est meilleur** : pas de benchmarks internes par tâche, pas de jeux de
référence du labo, pas de critères de régression qualité (le nightly test naissant et `qc.py`
non câblé sont des germes, pas une politique). Sans ça, l'interchangeabilité est un slogan.

**Correctif** : ériger l'évaluation en couche transverse : chaque capacité de manifeste référence
son jeu de test et ses métriques ; la veille (§42) propose un remplacement UNIQUEMENT avec un
delta mesuré sur ces jeux.

## Critique 11 — Forme : le présent de l'indicatif masque la frontière réel/visé

« WAMA intègre un système de RAG » (§11 — zéro code), « WAMA intègre une gestion native de la
traduction » (§12 — la sortie n'est pas câblée). Pour un lecteur externe, impossible de savoir ce
qui existe ; pour l'interne, c'est la recette du drift documentaire déjà constaté (audit doc
2026-07-09 : docs qui divergent silencieusement du code).

**Correctif** : renvoi systématique à `VISION_STATUS.md` (créé le 2026-07-17) en tête du document,
et discipline verbale : présent = existant, futur/conditionnel = visé.

## Critique 12 — Sécurité de l'assistant agentique : absente

Partie XI : un assistant joignable depuis Discord/Matrix/Mattermost qui peut « lancer l'analyse »,
interroger le SI labo et les données. Rien sur : l'authentification par canal, l'injection de
prompt depuis un canal semi-public, la confirmation des actions destructives ou coûteuses, les
quotas, la journalisation d'audit. Pour un déploiement institutionnel, c'est bloquant ; pour la
crédibilité du document, c'est un trou visible en 2026.

**Correctif** : une sous-section « modèle de menace de l'assistant » : identité forte par canal,
allowlist d'actions par rôle, confirmation explicite pour tout ce qui écrit/supprime/coûte,
audit trail. (Cohérent avec la porte privacy Presidio déjà décidée pour le cloud.)

## Critique 13 — Le point de vue de l'utilisateur non-technicien manque

La vision est écrite du point de vue du système. Presque rien sur l'onboarding, la formation, le
coût cognitif d'apprendre le Studio pour un chercheur non-technicien — alors que l'historique UX
du projet (modes simplifié/avancé, modales conservées, card-centric) montre que c'est une vraie
préoccupation de conception. Le §48 (« s'intégrer aux environnements existants ») est la seule
concession à l'adoption.

**Correctif** : une section « parcours d'adoption » : ce qu'un chercheur peut faire en 5 minutes
sans formation (déposer → résultat), puis la pente douce vers le Studio. C'est aussi l'argument
qui justifie l'investissement UX déjà consenti.

## Synthèse des correctifs proposés (par ordre d'impact)

1. Ajouter **non-objectifs + séquencement** (protège contre la dispersion — le risque n°1 avéré).
2. Ajouter **provenance/reproductibilité** comme exigence transverse (résout la contradiction §53
   et crée l'argument scientifique décisif).
3. Ajouter le chapitre **conformité RGPD/consentement** (condition d'existence de la partie VIII).
4. Marquer chaque section **[étagère / ingénierie / recherche]** + renvoi à `VISION_STATUS.md`.
5. Réécrire **§11 RAG en trajectoire incrémentale** (mono-niveau d'abord).
6. **Garde-fous méthodologiques** partie VII ; **modèle de menace** partie XI.
7. **Ancrer ou déprioriser** la partie V ; assumer le **gating** de l'auto-instanciation ;
   ériger l'**évaluation continue** en couche ; ajouter **modèle de réalisation** (ressources,
   bus factor) et **parcours d'adoption**.
