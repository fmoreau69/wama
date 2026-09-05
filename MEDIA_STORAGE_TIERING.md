# MEDIA_STORAGE_TIERING.md — Délocalisation des médias (étude + décision)

> **Statut : ÉTUDE / à implémenter plus tard.**
> ⚠️ **Prémisse périmée (re-mesuré 2026-08-04)** : la mention « pas urgent — disque local pas
> saturé » ne tient plus. `D:` est à **96 % (23,7 Go libres sur 543)**, dont **91 Go de modèles
> Ollama** (`D:\.ollama\models`, hors `AI-models/`). L'urgence relative de ce chantier est donc à
> réévaluer — mesurer avec `SystemMonitor.get_disk_info(drive='D')` avant de conclure.
> Contexte : `media/` local = **21 Go / 2 640 fichiers** (re-mesuré 2026-08-10).
> Question (Fabien) : délocaliser les médias sur cet espace pour gagner de la place locale ?
>
> 🔴 **PRÉMISSE CHANGÉE LE 2026-08-10 — lire avant d'implémenter ce chantier.**
> `\\vrlescot\SAVES\DEEP_LEARNING\MEDIAS` n'est plus un espace inoccupé : c'est désormais un
> **miroir de sauvegarde VIVANT**, alimenté chaque nuit à 02:30 (`common.backup_media`) et par le
> bouton « Backup Médias ». Il contient aussi `~Archives/` (ancien contenu mis de côté par Fabien).
> Le tiering ne peut donc plus s'y installer comme sur un terrain vierge — voir la section
> « Articulation avec la sauvegarde » ajoutée en bas. Référence : `PROJECT_STATUS.md` §42.

## Verdict performance

**❌ NE PAS faire de `MEDIA_ROOT` un pointeur/jonction/symlink vers le share SMB.**
- SMB (drvfs en WSL) est **lent en I/O aléatoire et gros fichiers** vs SSD/NVMe local.
- Le traitement média (encode/décode vidéo, diffusion, audio, upscaling) lit/écrit de gros fichiers en
  boucle → travailler directement sur le share = lenteur + saturation réseau.
- **Fragilité** : une coupure réseau ferait échouer les opérations Django `FileField` (`save`, `exists`,
  `size`, `open`) → erreurs en pleine chaîne. Le share doit être **write-once (archive)**, pas un dir de
  travail vivant (verrouillage SMB faible → conflits écriture WSL ↔ Windows).

## Architecture recommandée : TIERING (buffer local + archive distante)

C'est l'intuition « dossier tampon » de Fabien, et **le même pattern que le backup modèles** :

```
LOCAL  media/ (MEDIA_ROOT)         = BUFFER : médias EN COURS + RÉCENTS (travail rapide, NVMe)
DISTANT …/MEDIAS/  (mount WSL)     = ARCHIVE : sorties terminées / entrées anciennes (froid)
```

1. **Archivage** : à la complétion d'un job (ou après N jours d'inactivité), **déplacer** la sortie
   (et éventuellement l'entrée) vers l'archive distante + **libérer** le local. → réutilise
   `model_manager/services/remote_backup.py::offload_file()` (backup → vérif taille → suppression locale,
   garde-fou si vérif échoue), **généralisé au média** (layout miroir sous `MEDIAS/<app>/<user>/…`).
2. **Rapatriement à la demande** : à l'accès (preview / download / re-traitement), **copier** le fichier
   de l'archive vers le buffer local, puis servir/traiter en local.
3. **Index DB** : marqueur `archived=True` + `remote_path` sur le FileField/`UserAsset`, pour que l'UI
   affiche « archivé » + propose la restauration. (Évite de scanner le réseau pour lister.)
4. **Éviction du buffer** : LRU par date/âge + seuil de place (ne garder localement que les N derniers
   Go ou les médias < X jours).

## Réutilisation de l'existant (encore moins de neuf qu'annoncé — mis à jour 2026-08-10)
- **Montage WSL en place** : `\\vrlescot\SAVES` → `/mnt/shares/SAVES` (drvfs/fstab) →
  `MEDIAS = /mnt/shares/SAVES/DEEP_LEARNING/MEDIAS`.
  ~~ajouter `WAMA_MEDIA_ARCHIVE_PATH` dans `start_wama_prod.sh`~~ → **inutile** : la résolution du
  chemin est auto-détectée (WSL vs Windows) par `mirror_sync.resolve_remote_root`, et une variable
  d'écrasement existe déjà (`WAMA_MEDIA_BACKUP_PATH`) si besoin d'un montage non standard.
- ~~**`offload_file()` / `mirror_dest()` : à généraliser (aujourd'hui spécifiques aux modèles)**~~
  → **LA GÉNÉRALISATION EXISTE** depuis le 2026-08-10 : `common/services/mirror_sync.py` est le
  moteur unique du projet (`mirror_tree`, `copy_file`, `remote_is_available`, `resolve_remote_root`,
  `purge_keep_latest`). `offload_file()` reste, lui, spécifique — c'est la brique
  *backup + vérification de taille + suppression locale*, et **c'est exactement ce dont le tiering a
  besoin** ; seul son habillage « par modèle » (`model_type`, `format_type`) serait à desserrer.
  ⚠ Ne pas réécrire de boucle de copie : il n'y en a plus qu'une dans le projet.
- **Médiathèque (`media_library`)** : foyer naturel de l'UI « archivé / restaurer » (UserAsset a déjà un
  modèle d'assets).

## Risques / réserves
- **Verrous SMB** : archive = write-once (déplacement de fichiers terminés), jamais un working dir.
- **RGPD** : OK — SAVES est le NAS du labo (données restent sur l'infra labo, cf. principe « données chez
  vous »). Pas de cloud externe.
- **Gain réel** : ≈ la part « froide » (sorties terminées + entrées anciennes). L'en-cours reste local.
  Sur 16,5 Go, estimer la part archivable avant d'investir.
- **Serveur prod (Linux dédié, cf. [`memory/project_deployment_roadmap`])** : là, le stockage média sera
  sur les disques/NAS du serveur → ce tiering vise surtout **la machine de dev actuelle** (pression disque).

## Réglages utilisateur (page profil) — ✅ LIVRÉS (référence : `PROFILES_PERMISSIONS.md` §2/§3)

> Section d'origine SUPPRIMÉE (2026-07-25, plan doc B7) : les « 2 mécanismes à ajouter » sont
> livrés depuis, sous d'autres noms — `UserProfile.media_retention_days` + purge beat quotidien
> avec pré-avis (`common/services/retention.py`) et `notify_email`/`notify_on` +
> `common/utils/notifications.py` (câblés sur les 10 apps, cf. PROJECT_STATUS §16). Les anciens
> noms `retention_days_input/output` et `notify_by_email` n'existent pas dans le code.
>
> **Nuance à trancher conservée (unique à ce doc)** : à l'expiration de la rétention, **archiver
> vers le distant plutôt que supprimer** (défaut « indéfiniment ») — c'est l'articulation avec le
> tiering ci-dessous.

## Articulation avec la SAUVEGARDE des médias (ajouté 2026-08-10 — à trancher avant d'implémenter)

Depuis que `MEDIAS/` est un miroir de sauvegarde vivant, deux usages visent le même dossier et il
faut décider lequel gouverne. Ce qui se combine bien, et ce qui entre en conflit :

- ✅ **Offload → miroir : compatible.** Le miroir n'itère que sur les fichiers LOCAUX et ne supprime
  jamais rien à distance. Un fichier délocalisé (donc absent en local) reste donc à distance sans
  que la sauvegarde ne le touche. Aucun risque de « re-suppression ».
- 🔴 **Tirage → tiering : CONFLIT DIRECT.** `manage.py restore_backup --domain media` rapatrie
  **tout** ce qui est distant vers `media/`. Sur une installation où le tiering a délocalisé des
  médias froids, un tirage annulerait le gain de place d'un coup.
  → À trancher : soit le tirage reçoit un mode « squelette » (ne restaurer que ce qui est référencé
  comme local en base), soit le tiering utilise un sous-dossier distant DISTINCT
  (ex. `MEDIAS_ARCHIVE/`) que le tirage ignore. **La 2ᵉ option est la plus simple et la plus
  lisible** — deux dossiers, deux rôles, aucune règle conditionnelle.
- ⚠ **`~Archives/`** est déjà exclu du tirage (`exclude={'~Archives'}` dans `restore_backup`) : le
  précédent existe donc, et un `MEDIAS_ARCHIVE/` s'excluerait de la même façon.
- ⚠ **Rétention et sauvegarde se croisent** : la purge de 04:00 supprime les médias expirés, la
  sauvegarde tourne à 02:30 — donc **avant**, volontairement, pour archiver ce qui va disparaître.
  Le tiering doit s'insérer dans cette fenêtre sans la casser.

## Ce que `media/` a le droit de contenir — doctrine + état MESURÉ au 2026-08-25

> Question de Fabien : « `media/` ne devrait contenir que les input/output d'applications et les
> fichiers utilisateurs ». Adopté comme **règle**, et confronté au réel le jour même. Le dossier
> pesait 21 Go pour 3779 fichiers ; **trois natures étrangères** y vivaient.

**Règle.** `media/` contient trois choses, et rien d'autre :
`<app>/<user>/input/`, `<app>/<user>/output/`, `users/`.
Tout le reste — fichiers de travail d'un pipeline, médias de test, résidus — est **hors périmètre**
et doit vivre ailleurs : `media_tests/` pour les tests (cf. `wama/common/runners.py`), un dossier
**temporaire** pour les intermédiaires de traitement.

### ① Médias de TEST — soldé le 2026-08-25

**1069 fichiers** écrits par la suite de tests, dispersés dans les dossiers d'app et **jusque dans
les dossiers d'utilisateurs réels** (les ids d'une base de test entrent en collision avec les
vrais : `regis.blanchet` en avait 100). Cause : aucun `override_settings(MEDIA_ROOT=…)`.
→ Corrigé par `TEST_RUNNER` (`wama/common/runners.py`) ; les 1069 étaient partis en quarantaine
(`media_tests_quarantaine/` — dossier depuis résorbé, absent du disque au relevé du 27/08 ; le
journal de déplacement est parti avec lui). Détail : `PROJECT_STATUS §REPRISE 25/08`.

### ② Fichiers de TRAVAIL de l'avatarizer — ✅ SOLDÉ (les 2 correctifs livrés, relevé 2026-08-27)

Mesuré : `media/avatarizer/` = **1,69 Go / 2101 fichiers**, dont **99,6 % de PNG** (1724 Mo).
Ce ne sont pas des sorties : ce sont les images **intermédiaires de CodeFormer**
(`cropped_faces/`, `restored_faces/`, `final_results/`, 687 chacune).

**Deux défauts distincts, qui se composent :**

| # | défaut | preuve |
|---|---|---|
| **A** | `workers.py:221` passe `job_output_dir` comme dossier de sortie à CodeFormer, qui y déverse toutes ses frames. **Aucun nettoyage.** Le livrable (la vidéo) est dans `job_<id>/v15/*.mp4` | `job_11` : **2063 fichiers, 1715,7 Mo** pour une vidéo de **0,70 Mo** |
| **B** | `views.delete()` ne retire que les 3 `FileField` (`safe_delete_file`) — le dossier `job_<id>/` n'est **jamais** supprimé | **13 dossiers `job_*` orphelins** (card supprimée) contre 4 rattachés ; les 1715,7 Mo appartiennent à une card **qui n'existe plus** |

⚠ La fuite n'a joué qu'une fois parce que CodeFormer n'a tourné qu'une fois. **À usage courant de
l'amélioration faciale, c'est ~1,7 Go par génération.**

**Correctifs — LIVRÉS (constat du 25/08 ci-dessus conservé comme mesure d'époque) :**
1. ✅ la brique commune **`wama/common/utils/work_dir.py`** est extraite et adoptée par 7 modules
   (describer, enhancer, reader/glm_ocr…) ;
2. ✅ la suppression de card **purge le dossier de job** (`avatarizer/views.py` →
   `work_dir.purge_job_dir`).

### ③ Conséquence DIRECTE sur la sauvegarde `\\vrlescot\SAVES\DEEP_LEARNING\MEDIAS`

> **Le ménage local NE se propage PAS.** C'est écrit plus haut et c'est voulu : « le miroir n'itère
> que sur les fichiers LOCAUX et ne supprime jamais rien à distance ».

Donc, en l'état : les **1069 fichiers de test** déjà sauvegardés et les **1,7 Go d'intermédiaires**
restent sur le share, et y resteront. Un miroir qui ne supprime jamais est le bon défaut (il protège
d'un `rm` accidentel), mais il implique que **toute purge locale doit être décidée une seconde fois
pour le distant**. À faire APRÈS la purge locale, jamais avant, et jamais automatiquement.

### ④ `check_media_integrity` — ✅ LIVRÉ (commande en place, déclarée au registre des mécanismes qui pointe ce doc comme domicile ; conception d'origine ci-dessous)

Un *kind* de manifeste `media` a été ÉCARTÉ : un manifeste décrit ce qui se **reconstruit** depuis
une déclaration, `manifests/` est **versionné** (or `media/` porte des données personnelles de labo
SHS), et `manifest_export --check` serait périmé au moindre dépôt — un contrôle toujours rouge ne
protège plus rien. Un corpus curé, lui, relève du *kind* **`dataset`** qui existe déjà.

Ce qu'il faut est un **audit MESURÉ**, dans la famille de `check_docs` / `license_audit` /
`check_app_conformity`, à déclarer dans `mecanismes.py`. Les quatre états à rendre :

| état | définition | relevé 25/08 |
|---|---|---|
| **référencé** | une ligne de base pointe dessus | 332 |
| **orphelin** | aucune ligne ne le référence | 2378 |
| **résidu de test** | nom issu d'un producteur de test **identifié dans le code** ET non référencé | 0 (déplacés) |
| 🔴 **référencé mais ABSENT** | la base pointe vers un fichier qui n'existe pas | **33** — jamais signalé jusqu'ici |

⚠⚠ **Méthode obligatoire : DEUX signaux indépendants, jamais le nom seul.** Mesuré le 25/08 :
« orphelin » seul désigne 2378 fichiers dont l'immense majorité sont de vraies sorties de workers
(elles ne passent pas par un `FileField`) ; et le nom seul aurait emporté
`synthesizer/5/input/test_synthesizer.txt`, un dépôt manuel de **Sophie**.
⚠ Et le motif doit être exact : le suffixe de dé-collision de Django existe ici sous **deux** formes
(7 alphanum `_6P3kGCJ`, 8 hex `_c5e24b5d`) — n'en reconnaître qu'une laissait 476 fichiers sur place.

## Décision
- **Architecture validée** : buffer local + archive distante + tiering (PAS de MEDIA_ROOT sur le share).
- **Réglages profil** : rétention (input/output, défaut indéfiniment, archive>suppression) + notification
  email (défaut OFF, SMTP à configurer). Champs sur `UserProfile`, UI page profil.
- **Priorité : basse** (disque pas saturé). À implémenter quand la place locale devient contraignante,
  en réutilisant `offload_file`/le montage WSL. Lié au chantier `remote_backup` modèles.

---

## 8. VOIES D'IMPORT — la matrice fonctionnelle MESURÉE (2026-09-05)

> Demandée par Fabien : *« 5 à 6 fonctionnements parallèles à confronter/questionner […] faire
> la cartographie complète de tout ça et la consigner »*. Ce document est LE domicile du sujet
> (décision 05/09 : un domaine = un fichier ; la table de `CLAUDE.md` est mise à jour en
> conséquence — il couvrait déjà « ce que `media/` a le droit de contenir » et l'audit
> d'intégrité, les voies d'import en sont la suite naturelle). `BATCH_FORMAT.md` reste la
> spec du FORMAT de lot, `WAMA_VERIFICATION.md §3` le catalogue des GESTES exécutables.
>
> Tout ce qui suit a été **lu dans le code le 05/09** (5 balayages parallèles, ancres
> vérifiées une à une sur les affirmations qui changent une décision). Aucune ligne n'est une
> intention. Quand un point n'a pas été exécuté en navigateur, c'est dit.

### 8.1 Les 6 cas de Fabien — verdict par cas

| # | cas | ce que Fabien supposait | ce que le code FAIT | ancres |
|---|---|---|---|---|
| **1** | explorateur Windows → app | copie dans `app/input` | ✅ **COPIE** — `UploadToUserPath` ; collision → suffixe uuid8 (`_c5e24b5d`) | `common/utils/media_paths.py:160-188`, `:77-98` |
| **2** | médiathèque → app | *« les fichiers restent dans la médiathèque, pas d'import dans app/input, tu confirmes ? »* | ❌ **FAUX pour le geste courant** : le bouton « Médiathèque » d'une card fait `fetch(file_url)` → `blob` → `new File` → **re-upload** = COPIE autonome dans `app/input`, **sans aucun lien** avec l'asset. Double transfert, double stockage. Sur 5 consommateurs de `MediaPicker`, **1 seul** (Studio) lit le 2ᵉ argument `asset` — et subit quand même le téléchargement du blob, fait AVANT `onSelect`. ✅ **VRAI pour 2 voies serveur** : nœud Studio `media_import` (`asset_path`) et voix `ua_<id>` du synthesizer, lus EN PLACE | `common/static/common/js/media-picker.js:177-192` ; `_new_item_card.html:119` ; `studio/tasks.py:57-68` ; `synthesizer/utils/voice_utils.py:188-196` |
| **3** | dossier utilisateur (filemanager) → app | temp + copie dans `app/input` | ✅ **COPIE** (`shutil.copy2`) — l'original reste dans `users/<u>/temp/` **pour toujours** : `users/*/temp` n'est dans **aucune rétention** ; vidage manuel seul | `media_paths.py:117-157` (`copy_into_app_input`) ; `common/services/retention.py:24-31` |
| **4** | dossier connecté (montage) → app | copie dans `app/input` | ✅ **référence tant qu'on REGARDE, copie dès qu'on IMPORTE** — arbre/aperçu/service lus en place sur le montage ; « Envoyer vers » copie. La card ne garde **aucune trace** du montage d'origine. `check_media_integrity` ne voit pas les montages | `filemanager/views.py:304-335`, `:338-394`, `:2362-2389`, `:1263-1283` |
| **5** | lot avec chemin d'entrée et de sortie | *« importés dans app/input, ou traités depuis l'origine et exportés dans la destination ? »* | **Entrée : TROIS régimes** (8.3). **Sortie : `-o` n'est JAMAIS une destination** — nulle part ; nom seulement (composer, synthesizer), **perdu** sur imager, avatarizer et les 6 apps média. `BATCH_FORMAT.md:23-29` le dit ; les règles `:56-79` (résolution vers un `MountedFolder`) sont **de la doc pure, zéro code** | `BATCH_FORMAT.md:23-29` ; `imager/utils/prompt_parser.py:250-303` (filtre qui perd `-o`) |
| **6** | prompt → fichier d'entrée (« uniformisation faite ») | le prompt devient un fichier d'entrée | ❌ **n'existe pas** : le prompt est un CHAMP (`TextField`) partout sauf synthesizer (DOCX matérialisé parce que son modèle exige un `FileField`). Le commun déclare l'inverse : `intake.py:56` *« le port de PROMPT n'est pas un port de FICHIER »*. Ce qui a été uniformisé le 30/08 : le **vocabulaire** (`text`→`prompt`, `document`) et la **preview** (face Entrée = texte inline, `preview_utils.py:112-128`) — *vu de la card* le prompt est l'entrée, physiquement il ne va jamais dans `input/`. Live transcriber : audio → `input/`, texte → champ | `synthesizer/views.py:379-473` ; `composer/models.py:25` ; `imager/models.py:221` ; `transcriber/views.py:696-735` |

### 8.2 La matrice VOIE × APP — ce que chaque geste produit sur le disque

Légende : **C** = copie dans `media/<app>/<u>/input/` · **R** = référence (le fichier reste où il est) · **·** = geste non offert · **⚠** = comportement divergent

| voie \ app | anonymizer | converter | describer | enhancer | reader | transcriber | avatarizer | composer | synthesizer | imager |
|---|---|---|---|---|---|---|---|---|---|---|
| clic / drop explorateur | C ⚠¹ | C | C | C | C | C | C (attache) | C (lot seul) | C | C (attache) |
| drop de DOSSIER | C | C | C | C | C | C | · | · | C | · |
| médiathèque (bouton card) | C | C | C | C | C | C | C | C | C | C |
| URL | C au lancement | **C à la création** ⚠ | C au lancement | C au lancement | · | C au lancement | C au lancement | C au lancement | · | C au lancement |
| « Envoyer vers » filemanager | C | C | C | C | C | C | **·** (pas d'importeur) | **·** (pas d'importeur) | C | C |
| drag jstree → card | C | C | C | C | C | C | ⚠² re-download | C | C | **⚠² rien** (aucun listener) |
| montage → app | C | C | C | C | C | C | · | · | C | C |
| lot : `-i` chemin local | ⚠³ accepté, meurt au lancement | C (sous MEDIA_ROOT) | ⚠³ | ⚠³ | ⚠³ | ⚠³ | **R** (`audio_input.name = relpath`) | · | · | · |
| lot : `-i` URL | C au lancement | C à la création | C au lancement | C au lancement | C au lancement | C au lancement | · | · | · | · |
| lot : `-o` | perdu | perdu | perdu | perdu | perdu | perdu | perdu | nom | nom du .txt | **perdu** |
| lot : `-r` référence | · | · | · | · | · | · | requis (galerie) | ⚠ parsé, fichier NON rattaché | ⚠ produit, jamais lu | ⚠ produit, filtré |
| N fichiers d'un coup | 1 lot/nature | 1 lot/nature | 1 lot | 1 lot | 1 lot (serveur) | **⚠⁴ N cards isolées** | · | · | 1 lot | · |
| « conversion rapide » | · | **R + sortie à côté** ⚠⁵ | · | · | · | · | · | · | · | · |
| `server_path` (fichier déjà sur le serveur) | · | · | · | · | · | · | · | · | **R** ⚠⁶ + 🔴 traversée | · |

Notes numérotées :
1. **anonymizer** écrit le fichier lui-même (`views.py:212-229`) et fabrique la chaîne de chemin à la main (`:163`) au lieu du `upload_to` ; sa branche « `.txt` = liste de chemins serveur » (`:77-111`) lit des chemins **sans garde MEDIA_ROOT** — le gabarit généré, lui, garde (`views_gen.py:491-494`).
2. **Trois canaux de drag concurrents** : `WamaImport` ignore un drag jstree (pas de `dataTransfer.files`) ; `filemanager.js:1784` rattrape et POSTe `paths[]` ; mais imager/avatarizer/cam_analyzer reçoivent l'événement `filemanager:filedrop` — avatarizer et cam_analyzer **re-téléchargent le blob depuis `/media/` puis ré-uploadent** (donc échec sur un fichier de montage, non servi sous `/media/`), et **imager n'a aucun listener** : le drag ne fait rien, en silence (déjà `CARD_DESIGN §11.10` défaut 1).
3. **Régime paresseux** (anonymizer, describer, enhancer, reader, transcriber) : la ligne est stockée en `source_url` et résolue **au lancement** par `ensure_local_input`, qui ne sait que TÉLÉCHARGER — `url_guard.py:77-79` refuse tout schéma hors http/https. `C:\medias\a.mp4` passe la création (`batch_parsers.py:241-246`, « adressable ») et **échoue à l'exécution**.
4. **transcriber** : `index.js:127-133` boucle les uploads puis `location.reload()` — **aucune consolidation** ; son commentaire `:123-125` (« consolide en UN batch ») est **faux**. Résultat : N lots-de-1 par `auto_wrap_orphans`.
5. **converter « conversion rapide »** (`converter/views.py:1068-1079`) : `input_file = str(rel_path)` (n'importe où sous MEDIA_ROOT, typiquement `users/<u>/temp/`), sortie écrite **à côté de la source**, ligne éphémère. Assumé et documenté (`:1012-1019`) — c'est un **2ᵉ modèle disque** dans le parc, et un montage y est refusé (400, `:1051-1055`).
6. **synthesizer `import_individual_from_path`** (`synthesizer/views.py:1185`) : `text_file.name = server_path` — la card **POINTE** sur le fichier du temp utilisateur. Vider son temp casse la synthèse. **C'est déjà le modèle « pointeur » — sans la vérification qui va avec.**

### 8.3 Les régimes de résolution d'une ENTRÉE distante (lot ou URL)

| régime | apps | à la création | au lancement |
|---|---|---|---|
| **A — paresseux** | anonymizer · describer · enhancer · reader · transcriber | `source_url` stocké, FileField vide | `ensure_local_input` → tempdir → `target.save()` → `input/` |
| **B — impatient** | converter | téléchargement/copie **immédiate** dans `input/` | rien |
| **B′ — hybride (codegen)** | toute app générée | URL → paresseux ; chemin local → copie immédiate | `ensure_local_input` pour l'URL |
| **C — référence** | avatarizer (`-i`) · synthesizer (`server_path`) · converter (rapide) | le chemin est **assigné tel quel** | rien |

`ensure_local_input` = `common/utils/source_ingest.py:59-118`, piloté par `WAMA_INGEST` du modèle, idempotent, appelé en tête de tâche (`task_skeleton.py:234-235` + 5 workers).

### 8.4 Déduplication — il n'y en a AUCUNE, et ce qui en tient lieu

| ce qui existe | ce que c'est vraiment | ancre |
|---|---|---|
| suffixe uuid8 (`UploadToUserPath`) et `_1`, `_2` (`copy_into_app_input`) | **anti-collision de NOM** — deux dépôts du même fichier = **deux copies** | `media_paths.py:77-98`, `:148-156` |
| `unique_together (user, name, asset_type)` → 409 | dédup par **NOM SAISI**, médiathèque seule ; les sinks Studio la contournent en renommant `« base (2) »` | `media_library/models.py:106` ; `studio/tasks.py:78-81` |
| `safe_delete_file` compte les autres lignes | **comptage de références À LA SUPPRESSION**, même modèle + même champ seulement — ne voit ni un autre modèle (`UserFile`), ni un autre champ, ni les suppressions du filemanager (`api_delete`, `api_move`) qui **fabriquent les « référencés mais ABSENTS »** | `queue_duplication.py:49-67` ; `filemanager/views.py:707-712`, `:918` |
| duplication de card | **le fichier est PARTAGÉ, jamais copié** (« Files are NEVER copied on duplication ») | `queue_duplication.py:20`, `:89-115` |
| `hashlib` dans le dépôt | 10 usages, **aucun sur un média d'entrée** (mémoire, RAG, caches, mtime jstree, config, poids de modèles) | balayage 05/09 |

**Conséquence mesurée** : une même vidéo passée par le temp puis importée dans 3 apps existe en **4 exemplaires durables** (temp jamais purgé + 3 inputs, dont 5 apps hors rétention).

### 8.5 Pointeurs — ce que le modèle de données permet, et l'état de l'index existant

- **Aucun modèle d'app ne porte un chemin externe** : toutes les entrées sont des `FileField` sous `MEDIA_ROOT`. Les seuls `local_path` du dépôt sont `MountedFolder` (un montage) et `AIModel` (un modèle).
- `source_url` **n'est pas un pointeur persistant** : c'est un état transitoire consommé par l'ingest.
- **Un index de pointeurs EXISTE déjà et DÉRIVE déjà** : `filemanager.UserFile` indexe `users/<u>/temp/` en base. Audit live du 05/09 : **609 fichiers · 330 référencés · 29 référencés mais ABSENTS · 30 « pointeurs seuls »** — dont **20 lignes `UserFile.file`** vers des fichiers supprimés du disque sans que la ligne ne suive. C'est précisément le mode de défaillance d'une gestion par pointeur sans vérification.
- **Aucune vérification « déplacé/supprimé → proposer le retrait »** n'existe : ni pour un montage injoignable (nœud d'erreur dans l'arbre, ligne conservée, aucune tâche périodique), ni pour un fichier sous `media/` supprimé par le filemanager (aucun contrôle des cards qui le référencent). Le seul instrument est `check_media_integrity`, **a posteriori**, et **aveugle aux montages**.

### 8.6 🔴 Défauts trouvés en chemin — à régler indépendamment de toute décision

| # | défaut | gravité | ancre |
|---|---|---|---|
| D1 | **Traversée de chemin** : `Path(MEDIA_ROOT) / server_path` sans `resolve()` ni confinement — un `../../…` lit n'importe quel fichier du serveur et injecte son texte dans une card | 🔴 **sécurité** | `synthesizer/views.py:1169`, `:1313` |
| D2 | confinement MEDIA_ROOT par **préfixe de chaîne** (`startswith`) après `resolve()` — un dossier frère `media_backup/` passerait ; `Path.is_relative_to` est la garde juste | ⚠ sécurité | `converter/views.py:752-753` ; `views_gen.py:491-492` ; `avatarizer/views.py:873-874` |
| D3 | anonymizer lit des chemins serveur arbitraires depuis un `.txt` **sans garde** | ⚠ sécurité | `anonymizer/views.py:77-111` |
| D4 | transcriber : dépôt multiple ≠ lot, commentaire faux | fonctionnel | `transcriber/js/index.js:118-134` |
| D5 | imager : drag jstree sans listener (silence) | fonctionnel | `filemanager.js:1805-1811` |
| D6 | régime A : chemin local accepté à la création, mort au lancement, **sans message à la création** | fonctionnel | `batch_parsers.py:241-246` × `url_guard.py:77-79` |
| D7 | `-r` inopérant depuis un lot sur composer/synthesizer/imager, alors que `BATCH_FORMAT.md:197-209` l'annonce « opt » | doc ≠ code | `composer/views.py:395-401` ; `synthesizer/views.py:1367-1377` ; `prompt_parser.py:250-303` |
| D8 | upload filemanager **avec arborescence** ÉCRASE (aucun `get_unique_filename` sur cette branche) | fonctionnel | `filemanager/views.py:616-618` |
| D9 | `users/*/temp` et 5 apps **hors rétention** | volume | `retention.py:24-31` |
| D10 | `MediaPicker` télécharge le blob AVANT `onSelect`, même pour le consommateur qui ne veut qu'un chemin | perf | `media-picker.js:177-192` |

### 8.7 Les DEUX questions de Fabien — éléments pour trancher (positions Claude, à valider)

**« Est-ce qu'un fichier d'entrée doit TOUJOURS aller dans `app/input` ? »**
Aujourd'hui : presque toujours, avec **3 exceptions vivantes** (converter rapide, synthesizer `server_path`, avatarizer `-i`) et **2 par référence d'asset** (Studio, voix `ua_`). Ce que la copie ACHÈTE, mesuré dans le code : (a) l'indépendance — supprimer/déplacer l'original ne casse pas la card, c'est ce qui rend les 29 pointeurs morts *rares* et non systémiques ; (b) un périmètre de droits simple — `<app>/<user>/` est le scoping ; (c) la sauvegarde et la rétention n'ont qu'UN arbre à connaître ; (d) le traitement lit du NVMe local, jamais un SMB (`§Verdict performance`). Ce qu'elle COÛTE : le volume (×4 mesuré), l'absence de lien asset ↔ card, et une médiathèque qui ne sert à rien de plus qu'un dossier.

**« Peut-on généraliser : le fichier reste à sa place, le filemanager gère des pointeurs avec vérification + proposition de retrait ? »**
Position : **pas comme remplacement de la copie — comme sa COMPLÉMENTAIRE, et le code dit déjà où passe la frontière.**
- Ce qui plaide POUR : le modèle pointeur existe déjà trois fois et *fonctionne* quand la source est stable (galerie, voix `ua_`, Studio) ; le volume ×4 est réel ; la médiathèque et le filemanager sont aujourd'hui des **culs-de-sac** (rien ne remonte de l'app vers eux, rien ne les relie à une card).
- Ce qui plaide CONTRE la généralisation : le seul index de pointeurs existant (`UserFile`) **dérive déjà** (20 lignes mortes) ; un pointeur vers un **montage** = traitement GPU qui lit du SMB (le verdict performance de ce doc), une coupure réseau en pleine tâche, et une source que l'utilisateur peut déplacer *pendant* le traitement ; le scoping des droits n'est plus donné par le chemin ; la sauvegarde ne sait pas suivre un pointeur ; et **surtout** : les cards en cours de traitement, le temps réel, la duplication (fichier partagé) supposent tous une entrée qui ne bouge pas.
- La frontière que le code trace déjà : **la SOURCE de vérité (médiathèque, montage, temp) reste où elle est et se RÉFÉRENCE ; l'ENTRÉE D'UNE CARD est une copie de travail, jetable par la rétention.** Ce qui manque n'est pas d'abolir la copie, c'est **le LIEN** : un champ de provenance sur la card (`source_kind` + `source_ref` : asset id / `mounts/<id>/…` / `users/<u>/temp/…`) — qui permettrait la dédup par provenance (même source → même copie), le retour app → médiathèque sans re-copie, la réparation d'un pointeur mort depuis sa source, et la « proposition de retrait » que Fabien demande, adossée à `check_media_integrity` étendu aux montages.
- Le vrai gisement de volume n'est pas la copie de travail : c'est **le temp jamais purgé et les 5 apps hors rétention** (D9) — soldable sans changer le modèle.

**Ce qui doit être TESTÉ avant d'aller plus loin** (demande Fabien : *« compléter les tests pour ne pas laisser passer des trous »*) — la matrice 8.2 EST la liste des cases : chaque case C/R doit avoir son scénario dans `WAMA_VERIFICATION §3` (geste 1 et geste 14 couvrent déjà clic/drop, dossier, URL, « Envoyer vers », lot ; **manquent** : médiathèque → card, drag jstree → card, montage → app, N fichiers = 1 lot, `-o`/`-r` de lot, `server_path`, conversion rapide, et le geste inverse app → médiathèque).
