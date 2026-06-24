# MEDIA_STORAGE_TIERING.md — Délocalisation des médias (étude + décision)

> **Statut : ÉTUDE / à implémenter plus tard** (pas urgent — disque local pas saturé).
> Contexte : `media/` local ≈ **16,5 Go**. Un espace distant existe : `\\vrlescot\SAVES\DEEP_LEARNING\MEDIAS`.
> Question (Fabien) : délocaliser les médias sur cet espace pour gagner de la place locale ?

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

## Réutilisation de l'existant (peu de neuf)
- **Montage WSL déjà en place** : `\\vrlescot\SAVES` → `/mnt/shares/SAVES` (drvfs/fstab, posé pour les
  modèles) → `MEDIAS = /mnt/shares/SAVES/DEEP_LEARNING/MEDIAS`. Env var dédiée (cf. `WAMA_MODEL_BACKUP_PATH`)
  → ajouter `WAMA_MEDIA_ARCHIVE_PATH` dans `start_wama_prod.sh`.
- **`offload_file()` / `mirror_dest()`** : à généraliser (aujourd'hui spécifiques aux modèles) en un
  helper média (mirroir relatif à `MEDIA_ROOT`).
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

## Réglages utilisateur (page profil) — 2 mécanismes à ajouter

> Les deux se déclarent **par utilisateur** sur la **page profil** (`UserProfile` a déjà
> `preferred_language`, `ui_mode` → y ajouter les champs). Étude/consignation — pas implémenté.

### A. Durée de rétention des données (input/output)
- **Champs** : `UserProfile.retention_days_input` + `retention_days_output` (séparés : on garde souvent
  les sorties plus longtemps que les entrées). Valeurs UI : **7 / 30 / 90 jours / indéfiniment**.
- **Défaut prudent : « indéfiniment »** (ne JAMAIS supprimer des données utilisateur par défaut — cf.
  règle anti-destructif). La rétention courte est **opt-in**.
- **Comportement** : un **Celery beat quotidien** parcourt, par user, les médias plus vieux que le seuil
  et — **préférer ARCHIVER (vers `MEDIAS/` distant) plutôt que supprimer** (le tiering ci-dessus) → la
  donnée n'est pas perdue, juste délocalisée. Suppression dure = uniquement si l'utilisateur choisit
  explicitement « supprimer après X jours ».
- **UI/UX** : sur le profil, 2 listes déroulantes (entrées / sorties) + un indicateur de **place occupée
  par l'utilisateur** + une note « archivé ≠ supprimé, restaurable ». Avertir avant toute purge dure.

### B. Notification email en fin de traitement
- **N'existe pas encore** (pas de `EMAIL_BACKEND`/SMTP configuré) → à créer.
- **Champ** : `UserProfile.notify_by_email` (bool, **défaut OFF** pour éviter le spam).
- **Déclenchement** : à la **complétion d'une tâche Celery** (fin de job), si opt-in → email avec le
  **lien vers le résultat**. Pour les batches/longues files : préférer un **digest** (1 email récapitulatif)
  plutôt qu'un email par item.
- **Prérequis infra** : configurer SMTP (serveur mail du labo) dans `settings.py` (`EMAIL_BACKEND`,
  `EMAIL_HOST`…) + `WAMA_*` env. Sur la machine de dev, `console.EmailBackend` (log) en attendant.
- **UI/UX** : sur le profil, un simple interrupteur « Me prévenir par email à la fin d'un traitement »
  (+ option future : seuil « seulement si le traitement a duré > N min »).

## Décision
- **Architecture validée** : buffer local + archive distante + tiering (PAS de MEDIA_ROOT sur le share).
- **Réglages profil** : rétention (input/output, défaut indéfiniment, archive>suppression) + notification
  email (défaut OFF, SMTP à configurer). Champs sur `UserProfile`, UI page profil.
- **Priorité : basse** (disque pas saturé). À implémenter quand la place locale devient contraignante,
  en réutilisant `offload_file`/le montage WSL. Lié au chantier `remote_backup` modèles.
