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
