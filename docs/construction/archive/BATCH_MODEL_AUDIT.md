# BATCH_MODEL_AUDIT.md — Modèle batch unifié WAMA

> Audit + design de référence du modèle « batch » commun aux apps de file d'attente.
> Décidé avec Fabien (2026-06-28). À lire avant de toucher au code batch.

## Principe directeur (non négociable)

**Tout est un batch.** Chaque élément de file appartient à exactement un `Batch`.
**Un batch unitaire (1 membre) s'affiche en card unique.** → transparent pour l'utilisateur,
**universel pour le développement** (un seul modèle, un seul rendu, une seule logique).

Invariants :
- 1 membre (Transcript, Synthesis, …) ↔ 1 `BatchItem` ↔ 1 `Batch`.
- Tout batch a **≥ 1 membre** (un batch vide n'existe pas → supprimé).
- `total` = **nombre réel de membres** (`items.count()`) — jamais une valeur stockée qui dérive.
- Rendu : `total == 1` → card unique ; `total > 1` → groupe batch.

## Ce que l'audit a révélé (données réelles transcriber, 2026-06-28)

3 pathologies, toutes filles du **même** défaut — `total` est un **compteur dénormalisé** :

| Pathologie | Exemple | Cause |
|---|---|---|
| `total` dérive | batch 3 : `total=3`, items=2 | recalcul fait dans certains chemins, pas d'autres |
| batches vides orphelins | 62/65/67 : `total=1`, 0 item | dernier membre supprimé sans suppression du batch |
| membre orphelin | 1 transcript hors batch | invariant « tout est batch » non tenu |

Aggravé par : modèle batch-of-1 (overhead/edge-cases), **logique dupliquée sur 8 apps**,
mutations éparpillées dans les vues (= pansements).

## Design propre — 3 niveaux

### Niveau 1 — `total` = source de vérité unique (tue la dérive)
`total` n'est plus une valeur qu'on assigne à la main. Implémenté en **champ auto-réparé** :
maintenu égal à `items.count()` par signaux (cf. niveau 2). Divergence structurellement impossible.

### Niveau 2 — cycle de vie centralisé par signaux (tue les pansements)
`common/utils/batch_sync.py` : `register_batch_sync(BatchItemModel)` branche
`post_save` + `post_delete` sur le BatchItem →
- resync `batch.total = items.count()` ;
- batch vidé (0 membre) → supprimé (+ nettoyage de son `batch_file` partagé via hook).

Capté pour **TOUS** les chemins (vue, admin, cascade, bulk) automatiquement.
→ on **retire** les `recompute_after_member_delete` manuels des 8 vues (pansements).
On garde uniquement, côté vue, la détection « le membre était batché » pour renvoyer
`batch_changed` → le front recharge et re-rend (card unique ↔ groupe).

### Niveau 3 — abstraction commune (la vraie uniformisation)
`common/models.py` : `BatchBase` + `BatchItemBase` abstraits, hérités par les 8 apps.
- `BatchBase.total` → propriété/cohérence centralisée ; `is_unitary` ; `delete()` nettoie ses fichiers.
- `register_batch_sync` appelé automatiquement à la déclaration.
- Champ membre (OneToOne CASCADE, **non-null**) reste dans le `BatchItem` concret (pointe un modèle différent par app).
- Rendu : partial commun piloté par la base (`total`/`is_unitary`).

### Niveau 0 — nettoyage des données existantes (préalable)
Commande `manage.py cleanup_batches` (lancée en WSL2 sur la vraie base) :
resync tous les `total`, supprime les batches vides, wrappe les membres orphelins.
À faire **avant** d'activer le rendu dérivé (sinon les batches vides cassent `total==1`).

## Ordre d'exécution / avancement
- ✅ **Niveaux 1+2 (signaux)** — `common/utils/batch_sync.py` (`register_batch_sync`, `sync_batch_total`,
  `resync_batches`) ; branché dans les `apps.py` des 8 apps (9 signaux : enhancer ×2) ; **pansements
  `recompute_*` retirés des vues** ; fonction morte supprimée de `batch_utils.py`. Validé : signal
  auto-corrige `total` (5→2 à la création), recale au delete, supprime le batch vidé ; 9 signaux branchés.
- ✅ **Niveau 0 (cleanup data)** — `manage.py cleanup_batches` lancé sur la vraie base (WSL2) :
  transcriber 1 recalé + 3 vides ; reader 1 vide ; **enhancer 4 vides** ; anonymizer 1 vide. Base cohérente.
- ⚠️ **Reste à activer** : **redémarrer les services WSL2** pour que les signaux tournent en prod
  (le code chargé est l'ancien jusqu'au restart ; les données, elles, sont déjà nettoyées).
- ✅ **Niveau 3 (abstraction commune)** — `wama/common/models.py::BatchMixin` (mixin **sans champ** →
  `makemigrations` = *No changes*) hérité par les 9 modèles Batch des 8 apps :
  `class BatchX(BatchMixin, models.Model)`. Apporte `is_unitary` (= `total == 1`, sans requête) et
  **centralise le nettoyage du `batch_file` dans `delete()`** (single responsibility) → `batch_sync`
  simplifié (plus de `batch_file_field`). Validé : héritage OK, signal OK, `is_unitary` OK, 0 migration.
  - **Choix assumé** : on N'a PAS extrait les *champs* (`user`, `batch_file`, `total`, `created_at`)
    dans une base abstraite Django — leurs variations légitimes (`related_name`, `upload_to`, default
    composer) imposeraient des renommages cassants + migrations pour un gain DB cosmétique. Le
    comportement (la vraie source de bugs) est, lui, 100 % centralisé.
  - Dispo pour la suite : utiliser `batch.is_unitary` dans les templates au lieu de `obj.total == 1`.

### Garde-fou appris (régression évitée)
Ne PAS dériver l'affichage du « compte réel » tant que les données ne sont pas nettoyées : des batches
vides (`real=0`) faisaient basculer `total==1` → tout en format batch. L'ordre est : **cleanup d'abord,
puis invariant garanti par signaux** — ensuite seulement l'affichage peut se fier à `total`.

## Apps concernées (modèle identique : `BatchX` + `BatchXItem(member OneToOne, related_name='batch_item')` + `items`)
transcriber, synthesizer, describer, reader, composer, avatarizer, anonymizer, enhancer (×2 : image/vidéo + audio).
