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

## Décision
- **Architecture validée** : buffer local + archive distante + tiering (PAS de MEDIA_ROOT sur le share).
- **Priorité : basse** (disque pas saturé). À implémenter quand la place locale devient contraignante,
  en réutilisant `offload_file`/le montage WSL. Lié au chantier `remote_backup` modèles.
