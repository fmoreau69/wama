# REPRISE — 2026-08-10 (session SAUVEGARDE / TIRAGE / crashs hôte)

> Handoff d'une session **infra**, disjointe du portage des apps. Elle n'a touché **aucun fichier
> d'app** : périmètre = `common/services/`, `model_manager/` (backup), `settings.py`, docs et skills.
> La session suivante (portage des apps généralistes) peut démarrer sans rien reprendre d'ici —
> ce document sert à **ne pas re-litiger** ce qui a été tranché, et à connaître les 3 points ouverts.

---

## 1. Livré — chaîne de sauvegarde complète (4 domaines + tirage)

| Domaine | Sauvegarde | Tirage | Planification |
|---|---|---|---|
| Secrets (`.env`) | `common.backup_config` | `restore_backup --domain config` | 02:20 |
| Médias | `common.backup_media` + bouton « Backup Médias » | `restore_backup --domain media` | 02:30 |
| Base | `manage.py backup_db` + bouton | `manage.py restore_db` | 03:30 |
| Modèles | `model_manager.backup_all_models` + bouton | `restore_backup --domain models` | manuel |

Ordre imposé pour une **réinstallation** : `config` → `db` → `models` → `media` → `sync_models`.
Détail complet : **`PROJECT_STATUS.md` §42**.

### Le point structurant : UN SEUL moteur
`common/services/mirror_sync.py` — `mirror_tree`, `copy_file`, `remote_is_available`,
`resolve_remote_root`, `purge_keep_latest`, `run_mirror_job`. **Il n'existe plus aucune autre
implémentation de copie ou de miroir dans le projet.** Le tirage est le même appel, source et
destination inversées. Côté JS, `createMirrorBackupUI` (template model_manager) porte une seule
fois rendu + polling + démarrage, paramétré par un préfixe DOM.

**3 doubles routes ont été supprimées** (exigence explicite de Fabien : « je ne veux pas de double
route, ce sont des pièges que l'on sème trop régulièrement ») : la primitive de copie, le parcours
récursif de `backup_directory`, l'enveloppe des tâches + le corps des 4 vues.

### Invariants à ne pas casser
- **Sens unique** : le miroir n'itère que sur la source ; rien n'est jamais supprimé à destination.
  Le distant est une **archive cumulative**. Ne JAMAIS ajouter de passe de purge « pour synchroniser ».
- `~Archives` (NAS médias) est préservé **par construction** au sens sauvegarde ; `exclude` n'est
  nécessaire **qu'au tirage**, et il y est posé.
- `mirror_tree` **refuse une destination inexistante** (garde anti-dossier-poubelle quand l'UNC
  n'est pas monté). Un appelant qui vise un SOUS-dossier distant doit le créer lui-même, **après**
  avoir vérifié la disponibilité de la racine.
- Saut incrémental sur **taille identique**, pas sur la date (mtime incohérent entre ext4/9p/NAS).

---

## 2. 🔴 Les 3 points OUVERTS

1. **`restore_db` n'a JAMAIS été exécuté pour de vrai.** `--dry-run` validé sur un vrai dump
   (934 objets), SQL généré vérifié, garde-fous testés — mais la restauration elle-même est
   indémontrable sans détruire la base de travail.
   → **Moyen propre de fermer ce trou** : restaurer sur le **Postgres Windows (port 5433)**, qui ne
   contient qu'un schéma + seed sans données de travail. ~10 min, sans risque.
2. **Tirage des modèles non lancé sur le vrai arbre** (~325 Go). Même moteur que les médias, validé
   sur le NAS dans les deux sens — mais le volume réel n'a pas été parcouru.
3. **Création du RÔLE Postgres sur machine vierge** : non testable depuis ici. `restore_db` détecte
   l'erreur et affiche le `CREATE ROLE` à exécuter, c'est tout ce qui peut être garanti.

---

## 3. Pièges corrigés — et deux erreurs de ma part, assumées

- ❌ **J'ai affirmé que « Backup Models » ne fonctionnait pas hors production.** Faux : gunicorn et
  celery sont lancés PAR `start_wama_prod.sh` et héritent de son export `WAMA_MODEL_BACKUP_PATH`.
  Le bouton a toujours marché. Ce que j'observais venait de mon propre `manage.py shell`.
  **C'était le 3ᵉ passage sur ce piège, déjà consigné le 27/07.**
- ❌ **J'ai affirmé que le dump ne recréait pas la base.** Faux : `pg_restore --create` la fabrique
  depuis l'en-tête de l'archive. Mesuré en générant le SQL des deux dumps, avec et sans
  `pg_dump --create` : **instruction identique**. Le flag ajouté a été **retiré**.
  ⚠ **Ne pas le rajouter.** Seul le **rôle** manque réellement.
- ✅ **Seuil `check_docs` resserré 3 → 2** (`wama/common/nightly_scenarios.py::CASSE_ASSUMES`).
  Le contrat « 3 CASSÉ assumés » était faux depuis le 06/08 (`_settings_modal.html` livré autrement)
  et, comparant en `<=`, il était devenu **aveugle à une vraie 3ᵉ dérive**.
  **Les 2 restantes sont des références EN AVANT légitimes**, vérifiées :
  `common/_result_tabs.html` (R18 — duplication toujours présente : `transcriber/index.html:307` et
  `describer/index.html:109`) et `wama/common/middleware.py` (i18n, ROADMAP).
- ✅ **`MEDIA_STORAGE_TIERING.md`** — 3 points périmés corrigés **et un conflit non vu** : `MEDIAS/`
  n'est plus un espace vierge mais un miroir vivant. L'offload du tiering reste compatible, **mais
  le tirage rapatrierait tout et annulerait le gain de place**. Deux issues tracées dans le doc.

---

## 4. État du portage des apps — point d'entrée de la session suivante

Photo **mesurée** (`logs/conformity_report.json`, généré le 2026-08-07 16:23 — **antérieur** aux
modifications imager du 10/08, donc à re-mesurer) :

```
describer    83 %   synthesizer  85 %   composer  86 %   reader     86 %   imager      91 %
anonymizer   92 %   avatarizer   93 %   converter 94 %   enhancer   94 %   transcriber 94 %
```

- **Re-mesurer d'abord** : `python manage.py check_app_conformity` (skill `/conformite`).
  Le score n'est **pas** l'avancement du portage — voir l'avertissement en tête du skill.
- Handoffs du portage, toujours valables : **`REPRISE_2026-08-06_IMAGER.md`** (imager + briques
  communes) et **`REPRISE_2026-08-06.md`** (cam_analyzer, chantier distinct NON terminé).
- Règle de cadrage (Fabien, 31/07) : les apps sont **antérieures** à la centralisation → porter =
  **TRADUIRE et REMPLACER, jamais juxtaposer**. Le danger est le doublon silencieux.

---

## 5. Contrôles au vert en fin de session

| Contrôle | Résultat |
|---|---|
| `manage.py check` | 0 problème |
| `check_docs` | 240 références, **0 périmée**, 2 cassées (les 2 assumées ci-dessus) |
| `doc_facts --check` | 3 blocs à jour (le bloc `outils` a été régénéré : mes 2 commandes manquaient) |
| Suites de non-régression | 36 contrôles verts (moteur, `exclude`, `on_file`, contrat `BackupResult`, `backup_all_models`, rendu réel de la page, tirage `config`, garde-fous `restore_db`) |
| Tirage médias **réel** contre le NAS | 2640 distants, 0 à copier, 2640 identiques, 0 échec |

⚠ **Non joué** : aucun smoke navigateur — le MCP Playwright était déconnecté toute la session.
Le rendu serveur de `/model-manager/` a été vérifié à la place (HTTP 200 + marqueurs présents).

---

## 6. Contexte machine — à ne pas oublier

L'hôte a subi **7 coupures d'alimentation** entre le 31/07 et le 07/08 (dont 3 le 07/08, et une
qui a laissé la machine éteinte 3 jours). Diagnostic : **panne sous l'OS**, alimentation de 1600 W
donc sous-dimensionnement exclu ; pistes restantes = vieillissement du bloc ou instabilité à faible
charge. **0 dégât matériel ou de données mesuré.**
Règles opérationnelles à respecter : **pas de charge GPU WSL2 déclenchée par l'assistant**, pas
d'enchaînements de chargements Ollama hôte, **pas de job GPU nocturne**.
Détail : `memory/reference_wsl_gpu_windows_update_regression`.
