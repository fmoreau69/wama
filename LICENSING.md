# LICENSING.md — Licence de WAMA, licences traversées, dépôt officiel

> **Document de référence unique** du domaine « licences & dépôt » (règle : un domaine = un
> fichier). La vue **mesurée** et vivante reste la page `/common/licences/`
> (`wama/common/services/license_audit.py`) — ce document consigne la POLITIQUE, les décisions
> et la procédure de dépôt ; il ne duplique pas l'inventaire vivant.

---

## 1. Licence de WAMA : AGPL-3.0 (posée le 2026-08-21 — à valider par la valorisation UGE)

Le fichier `LICENSE` porte le texte intégral de la **GNU AGPL-3.0**, et le fichier
`COPYRIGHT` nomme le titulaire des droits et l'auteur.

**Pourquoi l'AGPL-3.0 et pas autre chose :**

1. **C'est déjà la clause la plus contraignante du code que WAMA lie.** 36 poids/backends
   ultralytics (YOLO 11/26, YOLOv12) sont AGPL-3.0 ; WAMA les importe et les sert **en
   réseau** — exactement le cas que l'AGPL couvre. Publier WAMA sous une licence plus
   permissive (MIT/Apache) serait juridiquement intenable sans retirer ces backends ;
   plus contraignant n'existe pas côté open source.
2. **La cible « non commercial » ne peut pas se greffer sur le code.** Une clause NC est
   incompatible avec l'AGPL des composants liés (on ne peut pas redistribuer du code AGPL
   sous des termes plus restrictifs). L'effet recherché — empêcher l'appropriation
   commerciale — est en pratique atteint par : (a) le copyleft réseau de l'AGPL, qui oblige
   tout exploitant d'un service dérivé à republier ses sources ; (b) les licences **des
   modèles embarqués**, qui restent NC là où l'éditeur l'a décidé (voir §2). Le déploiement
   WAMA au Lescot reste, lui, un usage de recherche.
3. **Compatible recherche publique.** L'AGPL figure parmi les licences admises par le décret
   n° 2017-638 (code source administratif) et est banale dans les dépôts HAL/Software
   Heritage.

**Ce que l'AGPL nous OBLIGE à faire, concrètement (art. 13).** WAMA est une application web :
dès qu'un utilisateur interagit avec elle à distance, la licence impose de **lui offrir un
moyen d'obtenir le code source** de la version qui tourne. Ce n'est pas théorique et c'est
peu coûteux — un lien « Source » dans le pied de page vers le dépôt suffit. À faire au
moment où WAMA est servi au-delà du poste de dev (cf. §7).

**Statut : décision d'ingénierie, pas encore décision d'établissement.** Seuls les **droits
patrimoniaux** (exploitation) sont dévolus à l'employeur pour un logiciel créé par un agent
public dans ses fonctions ; la **qualité d'auteur reste à la personne**, et une exploitation
commerciale éventuelle ouvrirait à l'auteur un droit à intéressement. Ce partage est détaillé
au **§8** — ce n'est PAS « tout à l'université ». Le choix de licence relevant de
l'exploitation, il doit être **entériné par l'Université Gustave Eiffel** (direction de la
valorisation / DRIVE) avant toute publication « officielle » ou dépôt — voir §5. D'ici là,
l'AGPL-3.0 posée ici est la seule option cohérente avec les composants liés.

## 2. Ce que la licence du code ne couvre PAS : les modèles et médias

Un résultat produit par WAMA traverse les licences de ses modèles — c'est la question à poser
**avant de publier un résultat**, et la page `/common/licences/` y répond par app (calcul
depuis les `requires` des manifestes). État au 2026-08-21 :

| Contrainte | Éléments | Conséquence |
|---|---|---|
| **Interdite en UE** | `hunyuan-image-2.1` (Tencent Hunyuan Community License : « excluding the territory of the European Union ») | **Aucun droit, même en recherche.** Décision à prendre : retirer/désactiver le modèle (§6). |
| **Non commercial** | MusicGen/AudioGen ×4 (cc-by-nc-4.0), FLUX.1-dev + LoRA logo (les **sorties** restent libres), XTTS v2 (CPML — Coqui dissoute : aucune licence commerciale achetable), CogVideoX (recherche libre ; commercial = enregistrement), depthpro (apple-amlr) | Résultats : recherche/enseignement seulement. |
| **Copyleft fort** | 36 poids ultralytics/YOLOv12 (agpl-3.0) | Couvert par le choix AGPL du §1. |
| **Communautaires qualifiées** (classées permissives, précédent OpenRAIL) | SAM3 (SAM License), Higgs Audio v2 (< 100 k utilisateurs/an, attribution « Built with Higgs Materials… »), LTXV (< 10 M$ CA), translategemma (Gemma Terms of Use) | OK à l'échelle du labo ; attribution à tenir. |

Les identifiants qualifiés (`hunyuan-community`, `cpml-1.0`, `flux-1-dev-non-commercial`,
`ltxv-open-weights`, `sam-license`, `higgs-community`, `gemma-terms`, `cogvideox-license`)
sont catalogués dans `license_audit.py::_CATALOGUE` avec leur famille — y compris la famille
**« Interdite (territoire) »**, classée au-dessus d'« Inconnue ». `backfill_platform_refs
--licences` ne ré-écrase plus une qualification par le placeholder HF `other`.

## 3. Code tiers VENDORISÉ (hors registres — inventorié le 2026-08-21)

L'audit `/common/licences/` ne voit que les registres (modèles, librairies Python, médias).
Le code **copié dans le repo** a été inventorié à part :

- **Front vendorisé** (`wama/static/vendors/`) : Bootstrap, three.js (+ fflate, meshoptimizer),
  TalkingHead, jsTree, animate.css, bootstrap-wysiwyg, jQuery (+ File Upload) — tous **MIT** ;
  Font Awesome Free (CC BY 4.0 icônes / OFL fontes / MIT code) ; Leaflet (BSD-2 amont, en-tête
  sans nom de licence) ; `leaflet-rotate.js` → **licence non établie** (aucun en-tête).
- **`wama/avatarizer/codeformer/`** : **NTU S-Lab License 1.0 = NON COMMERCIAL** — la clause
  la plus contraignante du code embarqué ; elle couvre le mode « Qualité » de l'avatarizer.
  Sous-composants sans LICENSE propre (BasicSR, YOLOv5-face — amont GPL-3.0, ops StyleGAN2) →
  à qualifier avant toute redistribution. NB : dossier présent comme **gitlink sans
  `.gitmodules`** — son contenu n'est pas versionné dans ce dépôt (idem MuseTalk, gitignoré,
  MIT).
- **`brunette.glb`** (avatar de test TalkingHead, gitignoré) : CC BY-NC 4.0.
- Reste non établi : binaires gitleaks (amont MIT).

## 4. État mesuré de l'inventaire (photo 2026-08-21, après complétion)

`119` éléments — `102` licences établies (65 avant complétion), `0` « à qualifier »,
`2` attributions sans auteur (les 2 poids `*-lindevs`). Restent inconnus :

- **8 poids `yolov8*_face_plate_*.pt`** : origine non établie — on ne devine pas une licence
  depuis un nom de fichier ; il faudra apparier nom+taille contre un dépôt amont
  (`backfill_platform_refs --poser CLE=PLATFORM_REF`).
- **9 médias utilisateur** (voix perso, sorties MusicGen, fixtures smoke) : à renseigner par
  leur propriétaire depuis la médiathèque (pas un fait externe à chercher).

## 5. Dépôt officiel de WAMA — la marche à suivre

**Préalable qui commande tout : l'employeur.** WAMA étant l'œuvre d'un agent public dans ses
fonctions, les **droits patrimoniaux** appartiennent à l'**Université Gustave Eiffel** (art.
L113-9 CPI) — la qualité d'auteur, elle, reste à Fabien Moreau (§8). Le premier geste n'est
donc ni l'APP ni l'INPI : c'est **contacter la direction de la valorisation / DRIVE de l'UGE**
(déclaration de logiciel — la plupart des établissements ont un formulaire « déclaration
d'invention/de logiciel »). C'est elle qui signe un dépôt APP ou une cession, et qui entérine
la licence du §1. **Déclarer n'engage à rien** : c'est même le geste qui *ouvre* les options
de valorisation (§8), pas celui qui les ferme.

Ensuite, trois dispositifs **complémentaires** (pas concurrents) :

1. **HAL + Software Heritage — recommandé en premier, gratuit, standard recherche.** Dépôt
   du code source via HAL (type « logiciel ») : archivage pérenne dans Software Heritage,
   identifiant **SWHID** citable, métadonnées `codemeta.json`, conforme à la politique
   science ouverte nationale et UGE. C'est LE dépôt « officiel » attendu d'un logiciel de
   labo, et il établit une **antériorité publique horodatée**.
2. **APP (Agence pour la Protection des Programmes)** : dépôt probatoire privé (séquestre du
   code, constat d'huissier numérique). Utile si l'UGE envisage une exploitation/valorisation
   contractuelle ; payant, se fait au nom de l'établissement.
3. **Enveloppe Soleau (INPI, ~15 €)** : preuve de date simple, 2×5 ans, pour un jalon
   ponctuel (ex. l'état des documents de conception à une date donnée). Ce n'est **pas** un
   titre de propriété.

## 6. « Déposer l'idée / la philosophie » — ce qui est possible

En droit français (et à peu près partout), **les idées sont de libre parcours** : la
philosophie WAMA (système global métadonnée-driven, homogénéité UI auto-générée, briques
communes…) n'est **pas appropriable en tant que telle**. Ce qui est protégeable ou opposable :

| Levier | Ce qu'il protège | Geste |
|---|---|---|
| **Droit d'auteur** (automatique) | l'**expression** : le code, les docs (`WAMA_*.md`, vision), l'UI. ⚠ Il se dédouble : **exploitation** à l'UGE, **paternité** à l'auteur (§8) — et pour les **docs de vision**, écrits hors logiciel, la dévolution automatique de L113-9 ne s'applique pas de la même façon | rien à faire pour l'existence du droit, mais la preuve de date compte → dépôts du §5 |
| **Preuve d'antériorité** | la date à laquelle l'idée était formalisée | enveloppe Soleau sur les docs de vision/conception ; le dépôt HAL/SWH horodate aussi |
| **Publication défensive** | empêche un tiers de breveter le concept | publier la vision (article, préprint HAL, communication) — la divulgation crée l'art antérieur |
| **Marque** | le **nom** « WAMA » et son identité | dépôt INPI (~190 €/classe) au nom de l'UGE ; faire d'abord une recherche d'antériorité (des homonymes existent probablement) |
| **Brevet** | quasi inapplicable : un logiciel « en tant que tel » n'est pas brevetable en Europe, sauf effet technique spécifique | n'en parler à la valorisation que si un procédé technique singulier émerge |

Résumé honnête : le couple **publication (HAL/SWH + article de vision)** + **marque sur le
nom** est ce qui « dépose une idée » de la façon la plus solide qui existe réellement.

## 7. Décisions en attente (à trancher par Fabien / l'UGE)

- [ ] Déclarer WAMA à la valorisation UGE ; faire entériner l'AGPL-3.0 (§1).
- [ ] **hunyuan-image-2.1** : retirer ou désactiver (aucun droit en UE, §2).
- [ ] Dépôt HAL/Software Heritage (ajouter un `codemeta.json` au moment du dépôt).
- [ ] Marque « WAMA » : recherche d'antériorité INPI, puis dépôt éventuel.
- [ ] Renseigner licence/auteur des 9 médias utilisateur ; établir l'origine des 8
      `face_plate` et des 2 `lindevs` (§4) ; qualifier `leaflet-rotate` (§3).
- [ ] **Lien « Source » dans le pied de page** — obligation AGPL art. 13, due dès que WAMA est
      servi à des utilisateurs distants (§1).
- [ ] Points d'historique à aborder avec la DRIVE lors de la déclaration — éléments de
      contexte réunis **hors dépôt** (`_backup_history_2026-08-21/NOTE_INTERNE_*.md`).
- [x] **FAIT le 2026-08-21** — mention de copyright à deux étages : fichier **`COPYRIGHT`**
      (© Université Gustave Eiffel, titulaire des droits patrimoniaux + Fabien Moreau, auteur)
      et bloc équivalent dans le README. ⚠ Le `LICENSE` seul ne nommait **personne** : le texte
      AGPL de la FSF est générique et n'attribue rien — c'était un gabarit non complété
      (relevé par Fabien). Reste optionnel : les en-têtes par fichier source.
- [ ] Créer `AUTHORS` + `codemeta.json` : l'historique git ne compte **qu'un auteur**
      aujourd'hui — la paternité est nette, c'est un actif à préserver avant toute
      contribution externe (§8, question du CLA).
- [ ] Demander au support GitHub la **purge des objets inatteignables** (maintenance de dépôt).

---

## 8. Propriété intellectuelle : qui détient quoi (ce n'est PAS « tout à l'université »)

> Section ouverte le 2026-08-21 après un recadrage de Fabien : ma première rédaction disait
> « le logiciel appartient à l'employeur », ce qui écrase une distinction réelle.

**Le droit d'auteur se dédouble.**

| Étage | Titulaire | Ce que ça veut dire ici |
|---|---|---|
| **Droits patrimoniaux** (reproduction, adaptation, distribution → *choix de la licence*) | **l'Université Gustave Eiffel**, par dévolution automatique (art. L113-9 CPI, étendu aux agents publics) | c'est pourquoi l'AGPL du §1 doit être entérinée par la DRIVE, et pourquoi c'est l'UGE qui signerait un dépôt APP ou une cession |
| **Droit moral** — notamment le **droit de paternité** | **l'auteur, Fabien Moreau**, à titre personnel | inaliénable et incessible : vous devez être **nommé comme auteur**, y compris dans une version exploitée commercialement par un tiers. (Pour le logiciel, l'art. L121-7 restreint les autres attributs du droit moral — pas de droit de repentir, opposition à modification très encadrée.) |
| **Intéressement en cas de valorisation** | **partagé** — l'auteur agent public a un droit à une part des produits | ce n'est pas une faveur de l'établissement, c'est réglementaire — barème ci-dessous |

**Le barème d'intéressement, texte en vigueur** (vérifié sur Légifrance le 2026-08-21 —
⚠ le décret n° 96-858 du 2 octobre 1996, encore cité un peu partout, est **ABROGÉ** depuis le
1ᵉʳ janvier 2024) : **Code de la recherche, art. D532-2 à D532-6**, issus du **décret
n° 2023-1321 du 27 décembre 2023**.

- **Assiette** (art. D532-4) : somme **hors taxes des produits perçus chaque année** par la
  personne publique du fait de la valorisation, **après déduction des frais directs**,
  affectée d'un **coefficient représentant la contribution de l'agent**.
- **Taux** : **50 %** de cette base jusqu'au traitement brut annuel correspondant au *2ᵉ
  chevron du groupe hors échelle D*, puis **25 %** au-delà. Versement **annuel**, avances
  possibles.
- **Durée** (art. D532-6) : la prime **continue d'être versée après le départ de l'agent**
  — mutation, démission, retraite — pendant toute la durée d'exploitation ; et à ses ayants
  droit l'année du décès.
- **Pluralité d'auteurs** (art. D532-5) : les coefficients sont arrêtés **définitivement
  avant le premier versement** — donc à négocier au bon moment, pas après.

> 🔑 **Disposition à connaître (art. D532-2, dernier alinéa)** : « **Lorsque la personne
> publique décide de ne pas procéder à la valorisation** de la création […], les agents
> mentionnés à l'alinéa précédent **peuvent en disposer librement**, dans les conditions
> prévues par une convention conclue avec cette personne publique. »
> Autrement dit : si l'UGE décide de ne pas valoriser WAMA, la voie d'une exploitation par
> vous-même n'est pas fermée — elle passe par une **convention** avec l'établissement. C'est
> une raison de plus de déclarer tôt (§5) : la déclaration est ce qui déclenche l'arbitrage.

**Ce que cela change pour une éventuelle exploitation commerciale** (objectif non retenu à ce
jour, mais réflexion non figée) :

1. **L'AGPL ne ferme pas la porte.** Le titulaire des droits patrimoniaux peut publier en
   AGPL **et** vendre des licences propriétaires du même code : c'est la *double licence*,
   un modèle courant. Accorder une licence à autrui ne dépossède pas de ses droits.
2. **Les vrais verrous sont techniques, et l'inventaire de ce document les rend visibles.**
   Une version commercialisable supposerait de **remplacer ou licencier séparément** : les
   36 poids Ultralytics/YOLOv12 (AGPL — l'éditeur vend précisément une licence *Enterprise*
   pour lever cette contrainte), puis les modèles non commerciaux (XTTS, FLUX, MusicGen,
   CogVideoX). C'est faisable, mais ça se planifie ; ce n'est pas un détail de licence.
3. **Précédent maison — Pro-SiVIC.** *(historique rapporté par Fabien, non revérifié ici —
   la vérification documentaire s'est arrêtée avant d'aboutir sur ce point.)* Un logiciel de simulation développé à l'INRETS/IFSTTAR
   (devenu Université Gustave Eiffel) a donné lieu à la société **Civitec**, puis au produit
   **ESI Pro-SiVIC™** après reprise par ESI Group. L'essaimage d'un logiciel de labo vers une
   exploitation commerciale externe est donc un chemin **déjà pratiqué dans la maison** — le
   Code de la recherche (art. L531-1 et suivants) encadre la participation d'un agent public
   à une telle entreprise.
4. **Préserver la capacité de relicencier.** Tant que l'historique ne compte **qu'un auteur**
   (vérifié : c'est le cas aujourd'hui), l'UGE peut relicencier sans obstacle. Dès qu'il y a
   des contributions externes, il faut un **CLA** (accord de contribution) pour conserver
   cette liberté — sinon chaque contributeur détient une part et un changement de licence
   exige l'accord de tous.

> **Conclusion pratique** : déclarer WAMA à la DRIVE **ouvre** les options plutôt qu'elle ne
> les ferme, et l'hygiène de licences faite aujourd'hui est exactement ce qu'on vous
> demandera si la question commerciale se pose un jour.
