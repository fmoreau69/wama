# WAMA_APPRENTISSAGE.md — modèles APPRIS, statistiques, et la boucle de simulation

> **Document de référence unique** du domaine « apprentissage » : comment des méthodes ML/DL,
> des analyses statistiques et des modèles comportementaux entrent dans WAMA — et surtout **ce
> qu'il faut déclarer maintenant pour ne pas se fermer la porte**.
>
> ⚠ **Ce n'est PAS un chantier ouvert.** Rien n'est implémenté, rien ne doit l'être à court terme.
> C'est un **cadre**, écrit le 2026-08-25 à la demande de Fabien, dont la finalité explicite est :
> *« je construis d'abord, mais sans bloquer ce genre d'idées »*. La seule chose à faire à court
> terme est la liste du **§3** — cinq déclarations gratuites aujourd'hui, non rattrapables ensuite.

---

## 0. État MESURÉ (2026-08-25)

| fait | mesure |
|---|---|
| entraînement dans WAMA | **zéro ligne** — `model_manager` ne sait qu'inférer |
| statistiques dans `wama_data` | **zéro** — uniquement des méthodes de traitement (`core/`, `functions/`) |
| MLflow | **rejeté** par `ROADMAP §16.2` sur la prémisse « pas d'entraînement » → **amendée le 2026-08-25**, voir §4 |
| `RunOutcome` / `ModelRuntimeStat` | existent, tracent l'**exécution** et l'**inférence** — jamais un entraînement |
| kind `model` | existe, décrit un modèle **pré-entraîné ailleurs** (`hf_id`, `vram_gb`, backend) — **aucune provenance** |
| la vision le prévoit | `docs/WAMA_Vision_Complet_v2.md` Partie VII §27-33 (Data Comprehender, « DeepMind labo », boucle de découverte) — classé **H3**, `VISION_STATUS` : « rien » |

---

## 1. Les QUATRE couches — les confondre fait mettre un réseau là où un seuil suffit

Précision de Fabien (2026-08-25) : le ML n'est **pas** demandé pour la détection des traces.

| couche | unité d'analyse | nature | ML ? |
|---|---|---|---|
| **trace** | échantillon | signal dérivé — clignotant, angle volant, enfoncement pédale, SDLP | **NON.** Déterministe. C'est le Calculator + `wama_data/functions/driving/` |
| **motif** | fenêtre | structure récurrente **non étiquetée** dans les traces | **oui — non supervisé** |
| **situation** | fenêtre | **étiquette sémantique** (dépassement, insertion, inconfort…) | **oui — supervisé** |
| **profil** | **participant** | regroupement de conducteurs (moyen, sportif, agressif, lent, mou…), puis croisement avec l'âge et autres covariables | **oui — non supervisé** |

### ⭐ Le corpus d'apprentissage existe déjà — il n'est pas à construire

L'invariant, indépendant de tout protocole : **une segmentation + une table d'indicateurs + une
étiquette**, et le producteur d'étiquettes est le **codage vidéo** (`wama_data/core/coding.py`).
Le livrable chercheur actuel *est* un jeu supervisé.

> ⚠ **Ce que ce document ne dit PAS.** Une lecture antérieure a cité « 12 tables × 26 colonnes »
> (§6.7 de `WAMA_DATA_WORLD.md`) comme si c'était la structure attendue. **Faux — correction de
> Fabien, 2026-08-25** : c'est **une instance**, dans une expérimentation précise, donnée pour
> illustrer le concept. La forme est propre à chaque protocole ; c'est justement pourquoi elle doit
> être **déclarée** et jamais supposée par une fonction d'apprentissage.

### ⚠ Le profil casse l'axe temporel

Le frame de `wama_data` est un référentiel **temporel**. Un profil est un agrégat sur un
**participant**, tous scénarios et toutes sessions confondus. Il faut donc prévoir un **axe
d'agrégation** : `fenêtre → participant → groupe`. C'est le seul élément des quatre couches qui ne
se branche pas sur l'existant sans y avoir pensé.

### ⚠ Ne pas mettre la covariable dans le regroupement

On regroupe sur le **comportement seul**, puis on **décrit** les groupes obtenus par l'âge (ou le
sexe, l'expérience…). L'inverse fabrique des grappes qui confirment ce qu'on y a mis.

---

## 2. LA RÈGLE — WAMA n'entraîne pas ; il DÉCLARE, DÉCLENCHE et RÉINGÈRE

Position de Fabien, antérieure à ce document et **maintenue** : l'entraînement est exclu de WAMA
pour des raisons d'infrastructure et de temps de traitement, et **sans plus-value côté médias** —
finetuner un modèle média ne demande aucune UI, ça se fait en processus à part, éventuellement
appelé depuis WAMA.

L'asymétrie réelle n'est **pas** « le monde Data entraîne, le monde Médias non ». C'est le **statut
de l'artefact** :

| | modèle **média** | modèle **data** |
|---|---|---|
| ce qu'il est | un **outil consommé** (inférence) | un **résultat de recherche** |
| ce qui compte | son identité, sa VRAM, son backend | sa **provenance** — citable, reproductible, diffable |
| qui l'entraîne | dehors, sans UI | dehors aussi (VM/cluster), mais la **déclaration** est dans WAMA |

> **Conséquence** : un seul mécanisme sert les deux. Le modèle média n'utilisera simplement pas les
> champs de provenance. Il n'y a donc **pas de sous-système d'apprentissage à construire** — il y a
> **des champs à ajouter au kind `model`**.

### Où vit quoi (doctrine des MONDES appliquée)

L'apprentissage n'est **pas un domaine métier** : c'est une **nature de fonction**, au même titre
que `Binding.PURE` vs app-bound. Lui créer un monde reviendrait à créer un monde « fonctions
asynchrones ». Répartition :

| quoi | où | pourquoi |
|---|---|---|
| cycle de vie d'apprentissage (provenance, métriques, connecteur MLflow) | **substrat** `wama/common/` | sert les **trois** mondes ; le loger dans Data ferait dépendre le Lab de Data — le défaut corrigé par le déport du 22/08 |
| fonctions d'analyse (motifs, clustering, classifieur de situations, profils, statistiques) | **monde Data** `wama_data/functions/` | leur E/S est le **frame temporel** ; ce sont des `FunctionSpec` ordinaires |
| apps métier consommatrices | **monde Lab** | `cam_analyzer`, un futur `driving_analyzer` |
| composition des chaînes | **Studio** | il n'héberge rien, il assemble |

### Le 4ᵉ mode du Segmenter

Le Segmenter a trois modes (autour d'un event / conditionnelle / états, `§9ter.1`). Le mode
**appris** — « segmente selon ce modèle » — s'y ajoute **sans nouveau concept** : il produit le même
objet, des plages `(start, end)` étiquetées. C'est le meilleur indice que rien de tout ceci
n'appelle un monde à part.

---

## 3. ⭐ CE QU'IL FAUT DÉCLARER MAINTENANT — gratuit aujourd'hui, non rattrapable ensuite

C'est la **seule** section actionnable à court terme.

| # | déclaration | où | pourquoi maintenant |
|---|---|---|---|
| **A1** | ⚠ **RÉVISÉE le 2026-08-25 — voir ci-dessous.** L'unité d'indépendance n'est **pas un champ scalaire** : c'est **un axe de rôle `observation`** dans le plan d'expérience déclaré (`WAMA_DATA_WORLD §13`) — ⚠ **pas `unit`** : le mot est déjà pris par `VISIBILITIES` (OrgUnit) | kind `dataset` | portée par le manifeste, c'est un **fait** que les fonctions lisent ; passée à l'analyse, c'est un paramètre qu'on oublie. Même forme que `isBase` ou la famille d'un flux : **une propriété de la donnée, portée comme donnée** |
| **A2** | **provenance réel / synthétique** + le modèle générateur, **propagée** | kind `dataset` | sans ça la boucle de simulation (§6) empoisonne le corpus en silence. **Jamais déduit d'un nom de fichier** |
| **A3** | bloc `trained_from` : `{dataset, pipeline, metrics, split}` | kind `model` | vide pour les modèles HF ; c'est ce qui fait d'un modèle data un objet scientifique |
| **A4** | régime d'exécution : **exécuté par WAMA** vs **exporté vers un tiers** | kind `model` | le simulateur exécute le modèle, pas WAMA (§6). Ce n'est pas un backend de plus, c'est un contrat d'export |
| **A5** | **axe d'agrégation** `fenêtre → participant → groupe` | modèle temporel `wama_data` | le profil n'est pas un objet temporel (§1) |

### ⚠⚠ A1 et A5 étaient TROP PETITS — corrigé le 2026-08-25

Écrits la veille, A1 (« unité d'indépendance ») et A5 (« axe d'agrégation ») supposaient que la
comparaison **par groupes de population** était un cas particulier tiré d'un exemple. **Faux** :
Fabien a précisé que c'est une pratique **quasi systématique**, au même titre que la comparaison par
scénarios chez un même participant — et que l'**arborescence des dossiers change d'une
expérimentation à l'autre**, y compris hors du domaine automobile (essais mécaniques, flux de
trafic).

> **Conséquence : A1 et A5 sont absorbés par un modèle unique — le PLAN D'EXPÉRIENCE déclaré**
> (`axes[]` : rôles `unit` / `block` / `factor` / `covariate`, relations `contains` / `crosses`).
> Spécifié dans **`WAMA_DATA_WORLD.md §13`**, qui est désormais **la** référence de ce point.

Implémenter A1 comme un champ scalaire puis le remplacer par des axes serait à refaire deux fois.
**A2, A3 et A4 sont inchangés.**

### ⚠ Ce qu'il ne faut PAS faire : un nouveau kind de manifeste

`§9quinquies.3` de `WAMA_DATA_WORLD.md` a **déjà tranché** cette question : pas un kind par famille
de capacité. Un entraînement **est** un `pipeline` (des fonctions chaînées) dont la sortie est un
`model`. Pas de kind `experiment`, pas de kind `training`.

De même : **`FunctionSpec` n'a rien à changer.** Les méthodes ML entrent comme fonctions ordinaires
— `cost` porte déjà `vram_gb`/`cpu_bound`, `binding` distingue déjà pur et app-bound (un
entraînement long serait app-bound/Celery). C'est le point important : **le schéma-driven a déjà
prévu la place**, il manque cinq champs, pas une architecture.

---

## 4. Le connecteur MLflow — un point de contact, pas une intégration

**MLflow n'est pas à recréer ni à absorber** (position Fabien, 2026-08-25). C'est un système de
suivi d'entraînement complet et mature ; WAMA n'a aucune raison d'en réimplémenter une part.

### ⚠ Le rejet de `ROADMAP §16.2` TIENT — ce qui manquait, c'est la complémentarité

L'entrée y rejette MLflow : *« ❌ Rejetés […] MLflow (AIModel=registre, **pas d'entraînement**) »*.

> **Précision de Fabien (2026-08-25), et elle est plus juste que ma première lecture** : c'est un
> **rejet d'INTÉGRATION / de RÉUTILISATION dans WAMA**, pas un rejet de **COMPLÉMENTARITÉ**.
> J'avais écrit « la prémisse est fausse, le rejet est amendé » — non : le rejet ne portait pas sur
> ce point. **Rien à amender, quelque chose à ajouter.**

Ce que le rejet dit et qui **tient intégralement** : `AIModel` reste le registre unique de ce que
WAMA sait exécuter, et **MLflow Projects** duplique les manifestes `pipeline` + le chaînage studio.

Ce qu'il ne disait pas, faute d'objet à l'époque : WAMA n'était qu'inférence média, il n'existait
aucun run d'entraînement à tracer. Le monde Data en crée — **hors de WAMA**. La complémentarité
devient donc pertinente là où l'intégration reste refusée.

### La forme exacte du connecteur

| | |
|---|---|
| **MLflow fait** | le suivi d'entraînement — runs, expériences, hyperparamètres, métriques, artefacts |
| **WAMA fait** | le catalogue de ce qu'il sait **exécuter** (`AIModel`) et la **provenance** de ce qu'il publie |
| **le connecteur est** | **unidirectionnel, en un seul point** : un run MLflow terminé → un manifeste `model` avec `trained_from` + `mlflow_run_uri` → `ingest()`. **Une fonction, pas une intégration** |

**Ce que le connecteur ne fait JAMAIS** :
- lire MLflow pour lister les modèles disponibles (c'est `AIModel`) ;
- lancer un entraînement via `mlflow run` (MLflow **Projects** duplique les manifestes `pipeline` et
  le chaînage studio — **rejeté, et ce rejet-là ne bouge pas**) ;
- miroiter le Model Registry de MLflow.

---

## 5. La couche STATISTIQUE — extension bon marché, le coût est ailleurs

Position de Fabien : `wama_data` n'intègre pour l'instant que des méthodes de **traitement** ;
l'analyse statistique est une plus-value ultérieure, *a priori* sans blocage, par ajout de
capacités/bibliothèques. **C'est juste** — un test, une ANOVA, une régression sont des
`FunctionSpec` à ports typés comme les autres.

**Sur les UI** : ne pas reproduire jamovi / JASP / une UI de bibliothèque. La valeur ajoutée de WAMA
est la **card** — un résultat statistique est un objet qui porte ses hypothèses, son *n*, sa taille
d'effet, sa correction. C'est du `to_dict()` métadonnée-driven, donc auto-généré.

**Le coût réel n'est pas le développement, c'est le garde-fou** — et il est déjà écrit dans la
vision (§28, « garde-fous méthodologiques ») :

1. distinction explicite **exploratoire vs confirmatoire** — toute découverte du système est
   étiquetée exploratoire tant qu'elle n'a pas été testée sur données indépendantes ;
2. **correction des comparaisons multiples** et tailles d'effet, pas seulement des p-values ;
3. hypothèse proposée par l'IA **validée par un chercheur** avant tout pipeline confirmatoire ;
4. **journal des analyses lancées, y compris infructueuses**, pour rendre le taux de fausses
   découvertes estimable → ⭐ **`RunOutcome` le fournit presque gratuitement**.

Sans ce cadre, une exploration automatisée est une machine à corrélations fortuites — c'est le seul
endroit où la couche statistique peut coûter cher.

### Y a-t-il quelque chose à FAIRE maintenant ? (question de Fabien, 2026-08-25)

**Une seule chose, et elle n'est pas statistique : les `axes[]`** (`WAMA_DATA_WORLD §13`).

Raison : une fonction statistique **ne peut pas être écrite** sans savoir ce qui est **niché** et ce
qui est **croisé** — comparer des groupes et comparer des scénarios chez un même participant ne sont
pas le même test, à profondeur de dossier identique. Le reste (bibliothèques, cards, garde-fous) se
pose quand la première fonction s'écrira, et **rien ne se ferme d'ici là**.

> Position de Fabien, qui est la bonne : *« on ne réinvente rien, on complète »* — à la différence
> d'une toolbox tierce dont la taxonomie était trop spécialisée pour être élargie sans la refaire.

---

## 6. ⭐ LA BOUCLE DE SIMULATION — le second consommateur (Unreal Engine)

Fait apporté par Fabien le 2026-08-25 : le laboratoire dispose de sa **propre chaîne de simulation
de conduite sous Unreal Engine**. L'extraction de situations, traces, motifs et profils vise aussi à
les **rejouer en simulation à la place d'un conducteur**, pour (a) **évaluer le réalisme** de la
reproduction de comportements et (b) **générer des données** si ce réalisme est confirmé.

Ça change la nature de ce que WAMA produit : un profil n'est plus une description, c'est un
**modèle comportemental exécutable**, et **son consommateur n'est pas WAMA**.

### 6.1 Deux régimes de modèle (→ A4)

| régime | exemple | ce que WAMA fournit |
|---|---|---|
| **exécuté par WAMA** | Whisper, SDXL, un classifieur de situations | un backend, de la VRAM, une inférence |
| **exporté vers un tiers** | un profil conducteur rejoué dans Unreal | un **contrat d'export** : format + ce que le tiers reçoit |

> ✅ **A-Q1 — réponse pressentie (Fabien, 2026-08-25, à CONFIRMER)** : le simulateur reçoit un
> **jeu de paramètres**, pour l'ego comme pour l'auto-pilote. C'est la plus simple des trois
> hypothèses et elle change le chantier : le contrat d'export est un **enregistrement de paramètres
> typé et versionné**, pas un modèle sérialisé — donc **lisible, diffable et citable**, ce qui
> était justement l'exigence de §2 sur le statut de l'artefact.
>
> Contexte favorable : **le simulateur et WAMA sont tous deux développés en interne**, il n'y a donc
> aucune boîte noire à contourner. Le laboratoire dispose en outre d'un **auto-pilote
> méta-cognitif** rattaché à un sujet d'étude — un consommateur réel, pas hypothétique.

> 🔚 **Point d'entrée annoncé** : Fabien fournit **deux jeux de données** — un de l'**ancien**
> simulateur (rétrocompatibilité d'**import** uniquement : développé en interne, désormais remplacé)
> et un du simulateur **actuel**. À traiter avec `WAMA_DATA_WORLD §13.8` — **relever d'abord les
> noms réels de tables et de colonnes**, ne rien concevoir avant.

### 6.2 La boucle se referme, donc elle peut s'empoisonner

```
réel  →  modèle  →  simulation  →  synthétique  →  corpus  →  (modèle)
```

Deux garde-fous, **MÉCANIQUES** et non des intentions (doctrine `§9bis.5`) :

1. **`synthetic: true` + modèle générateur, propagé** (→ A2). Jamais déduit d'un nom de fichier.
2. **Interdiction d'entraîner sur du synthétique produit par le modèle qu'on évalue.** C'est le
   piège d'auto-confirmation ; il doit être une **barrière**, pas une consigne.

### 6.3 Le réalisme se mesure — il ne se regarde pas

« Est-ce que ça ressemble à de la conduite » n'est pas mesurable. Deux critères objectifs :

- **distributionnel** — les traces synthétiques reproduisent-elles la *distribution* des traces
  réelles sur les indicateurs déclarés ;
- **discriminatif** — *un classifieur arrive-t-il à distinguer réel et simulé ?* S'il n'y arrive
  pas, le réalisme est établi objectivement. Standard, bon marché, et conforme à la règle « métrique
  chiffrée, jamais un A/B visuel ».

### 6.4 Le simulateur est un producteur de vérité terrain

Il émet les étiquettes **par construction**. C'est exactement l'argument déjà retenu pour GNM dans
`ROADMAP §Études` (« stimuli expérimentaux contrôlés — labels connus par construction,
reproductibilité by design »). Même créneau, même justification, et ça renforce le **Recorder**
(`WAMA_DATA_WORLD §7`) : Unreal devrait y figurer comme source, à côté de LSL / RTMaps / ROS.

---

## 7. Complémentarité avec l'appui IA de l'établissement

> ⚠ **Règle de consignation (Fabien, 2026-08-25)** : ne **jamais** citer nommément personnes,
> services ou supports internes dans les documents du dépôt. On décrit **l'offre**, jamais ses
> auteurs. Le support source reste hors dépôt (`claude/`, ignoré par git).

Support de présentation lu en 2026-08 : une offre d'appui à l'intégration du machine learning dans
les projets de recherche, émanant d'un service central de l'établissement (41 pages, 2025).

**Ce n'est pas une offre d'expertise métier en ML : c'est une offre MLOps** (outillage et pratiques
du cycle de vie). Plan : Data (qualité) → ML (entraînement) → Dev (pratiques) → MLflow → poste de
travail (VM + forge institutionnelle + IDE distant).

| apport de l'offre | équivalent WAMA | recouvrement |
|---|---|---|
| qualité des données (sélection de caractéristiques, déséquilibre de classes, mise à l'échelle, aberrantes/manquantes) | Calculator + Explorer + Visualizer — **Calculator non implémenté** | **moyen** — même geste, une UI contre un notebook |
| entraînement (gradient, learning rate, early stopping, Optuna/Hyperopt, sur/sous-apprentissage) | **rien** | **nul — c'est le trou** |
| MLflow **Tracking** | `RunOutcome`, `ModelRuntimeStat` (exécution/inférence, pas entraînement) | **faible, complémentaire** → §4 |
| MLflow **Models** + **Registry** | `AIModel`, `model_manager`, kind `model`, `select_model()` | **fort — danger de duplication** |
| MLflow **Projects** (Docker/conda + CLI) | manifestes `pipeline`, chaînage studio à ports typés | **fort — à ne PAS adopter** |
| pratiques dev (gitflow, venv, tests, lint, RGPD/licences) | 369 tests, conformité mesurée sur 72 critères, tests nocturnes, `LICENSING.md`, audit secrets + vulnérabilités | **fort — WAMA est en avance** |
| **VM + GPU institutionnel, forge institutionnelle** | une RTX 4090, **crashs hôte non résolus** | **nul — et c'est l'apport le plus concret** |

### Ce qu'il faut demander (et pas « faites-nous du ML »)

1. **une VM GPU pour l'entraînement** — calcul long, non interactif, sans UI : exactement ce qu'il
   faut sortir de cette machine (règle en vigueur : **jamais de charge GPU nocturne ici**) ;
2. **un serveur MLflow institutionnel**, ou l'accord d'en héberger un ;
3. **une relecture méthodologique de la validation** — c'est là que leur valeur est la plus haute,
   bien plus que sur l'outillage.

---

## 8. Pistes méthodologiques — naturalistique & SHS (à creuser PLUS TARD)

> Fabien, 2026-08-25 : *« j'aimerais qu'on creuse ça plus tard quand wama_data sera avancé »*.
> Consigné pour ne pas être reperdu, **pas** pour être ouvert.

- **Deux régimes selon le volume.** Sur des indicateurs agrégés (quelques centaines de lignes) :
  arbres, gradient boosting, forêts — **aucun deep learning n'a de sens**, le sur-apprentissage est
  garanti. Sur les séries brutes multi-cadence (≈88 Go par étude) : encodeur temporel (TCN, 1D-CNN,
  transformer temporel), et là le volume devient l'atout.
- **Prior art à lire avant d'écrire.** Segmentation bayésienne non paramétrique en *driving
  primitives* (HDP-HSMM — découvre les segments **et** leur nombre, sans étiquettes) ; **matrix
  profile** pour la découverte de motifs récurrents (bon marché, déterministe, interprétable) ;
  **SHRP2** comme corpus de référence de la communauté naturalistique.
- **Interprétabilité avant performance (contrainte SHS).** Un modèle qui *prédit* une situation ne
  l'*explique* pas. Privilégier les structures lisibles (arbres, gradient boosting + attribution,
  motifs symboliques) ; réserver le deep à l'apprentissage de **représentation**, dont on ré-extrait
  ensuite des groupes interprétables.
- **Validation** : découpage **par unité d'indépendance** (→ A1), jamais par ligne ; et deux fenêtres
  recouvrant le même instant ne tombent jamais dans deux splits différents.

### La finalité, dans les mots de Fabien

> *« De nombreux datasets sont exploités spécifiquement dans des projets, sur des spectres d'analyse
> réduits relativement à la quantité et à la richesse de ces données. Analyser l'ensemble à la main
> pour en extraire une connaissance plus généraliste serait impossible sans une approche
> automatisée, qui est la raison d'être de WAMA. »*

C'est le **« DeepMind labo » low cost** — déjà nommé par la vision (`WAMA_Vision_Complet_v2.md`
§32-33, boucle de découverte) et classé H3. Et c'est la raison d'être du schéma-driven : que WAMA ne
se retrouve pas limité par des capacités qu'il ne pourrait plus ingérer dans les mondes existants.

---

## 9. Ce qu'il ne faut PAS faire maintenant

- écrire un Trainer ;
- adopter MLflow (au-delà de préparer A3 pour un connecteur ultérieur) ;
- écrire une UI de statistiques ;
- créer un kind de manifeste `experiment` / `training` (→ §3) ;
- créer un monde « apprentissage » (→ §2) ;
- toucher à `FunctionSpec` (→ §3).

---

## 10. Questions en attente

| # | question | qui tranche |
|---|---|---|
| **A-Q1** | que reçoit le simulateur Unreal — politique, jeu de paramètres, distribution de trajectoires ? (§6.1) | Fabien, avant tout export |
| **A-Q2** | l'axe d'agrégation (→ A5) : nouvelle dimension du frame, ou table annexe au sens de `§9quater.4` ? | après avancement `wama_data` |
| **A-Q3** | le garde-fou anti-auto-confirmation (§6.2) vit-il dans `ingest()`, dans le `dataset`, ou dans la fonction d'entraînement ? | avec A2 |
| **A-Q4** | Unreal entre-t-il comme source du **Recorder** ou comme format de l'**Importer** ? (§6.4) | avec D5 |
| **A-Q5** | statistiques : bibliothèque unique (statsmodels/scipy) déclarée en `library`, ou capacité par fonction ? | avant la 1ʳᵉ fonction stat |

---

## Voir aussi

- `WAMA_DATA_WORLD.md` — le monde Data : chaîne, Segmenter, Calculator, conteneur `.wdat`, décisions D1-D19
- `docs/WAMA_Vision_Complet_v2.md` §27-33 — Data Comprehender, « DeepMind labo », garde-fous méthodologiques §28
- `docs/VISION_STATUS.md` §Partie VII — confrontation au réel
- `ROADMAP.md` §16.2 — outils tiers évalués (**entrée MLflow amendée le 2026-08-25**, voir §4)
- `WAMA_MANIFEST_SPEC.md` — formalisme des kinds `dataset`, `model`, `pipeline`
- `project_model_meta_unification` (mémoire) — `AIModel` = source unique du catalogue
- ⚠ **PAS** `WAMA_LLM.md` — vérifié le 2026-08-25 : ses 19 sections traitent prompts,
  skills, enrichissement, traduction, RAG et mémoire, c'est-à-dire la **chaîne LLM qui accompagne un
  traitement**. Un modèle appris n'est pas un prompt. Doute soulevé par Fabien, confirmé par lecture.

---

## Journal

- **2026-08-25** — **création.** Échange Fabien ↔ Claude sur l'intégration ML/DL pour l'analyse des
  données elles-mêmes (motifs, situations, profils conducteurs) et sur le recouvrement avec l'offre
  de l'appui IA de l'établissement. Acquis : la règle **« WAMA n'entraîne pas, il déclare/déclenche/réingère »** et son vrai
  critère (**le statut de l'artefact**, pas le monde) ; les **quatre couches** trace/motif/situation/
  profil ; les **cinq déclarations gratuites maintenant** (§3) ; le **connecteur MLflow borné** et
  l'**amendement du rejet** de `ROADMAP §16.2` ; la **boucle de simulation Unreal** avec ses deux
  garde-fous mécaniques et sa métrique de réalisme.
  - ⚠ **Deux corrections de Fabien, consignées comme telles** : (1) « 12 tables × 26 colonnes » était
    **une instance**, pas la structure attendue ; (2) le risque de fuite de données par participant
    est un enjeu **d'analyse**, pas de construction de WAMA — il n'en reste qu'un résidu, **A1**,
    qui vaut parce qu'il est gratuit maintenant et non rattrapable ensuite.
