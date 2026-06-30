# PROFILES_PERMISSIONS.md — Profils, rôles, permissions d'accès, notifications, rétention

> Formalisation (2026-06-25) à partir de l'intention de Fabien. Couvre **3 chantiers liés** :
> (1) **permissions d'accès aux apps par profil**, (2) **notifications email**, (3) **durée de
> conservation des médias**. Statut : **proposition de modèle à valider** avant implémentation
> (fondateur + sécurité). Métadonnée-driven, fidèle à la philosophie WAMA.

## 1. Permissions — modèle à DEUX AXES ORTHOGONAUX

Le point clé de clarification : ce que Fabien a appelé « sous-profils » mélange en fait **deux axes
indépendants**. Les séparer rend le modèle simple et extensible.

### Axe A — **Profil de compte** (tier) : *quel niveau de pouvoir système*
Valeur **unique**, **hiérarchique**. Gouverne les **capacités système**, pas les apps métier.

| Tier | Gouverne |
|------|----------|
| `anonymous` | accès démo aux apps marquées **publiques** ; pas (ou peu) de persistance |
| `utilisateur` | compte standard ; accède aux apps de **ses rôles métier** (axe B) + apps communes |
| `développeur` | **toutes les apps** + outils dev/diagnostic (model_manager, prospection, studio, tests) |
| `admin` | tout + **gestion des utilisateurs/rôles** + politique de rétention + supervision |

### Axe B — **Rôles métier** : *quels domaines d'apps*
**Multi-valués, cumulatifs** (un user peut en avoir plusieurs). Gouvernent **quelles apps** sont
visibles/utilisables. Extensible (liste ouverte).

| Rôle | Apps (proposition initiale) |
|------|------------------------------|
| `communication` | imager, composer, synthesizer, avatarizer, **monteur**, **mixage/mastering**, enhancer, converter |
| `recherche` | transcriber, describer, reader, anonymizer, **biblio** (à venir), translator (à venir) |
| `ingénierie` | model_manager, converter, prospection, outils diagnostic |
| `administratif` | exports/reporting, gestion documentaire (à préciser) |
| *(commun)* | filemanager, media_library, profil/compte → **accessibles à tout compte authentifié** (aucun rôle requis) |

> Une app peut figurer dans **plusieurs rôles** (ex. converter ∈ communication ∩ ingénierie). L'accès
> se fait par **intersection non vide** (voir §1.2).

### 1.2 Résolution d'accès (algorithme, métadonnée-driven)
Chaque app **déclare** dans `APP_CATALOG` :
- `roles: [...]` — rôles métier qui ouvrent l'app (vide = app **commune**, ouverte à tout authentifié) ;
- `public: bool` — visible aux `anonymous` (démo) ;
- `min_tier: 'utilisateur'|'développeur'|'admin'` — exigence de tier minimal (optionnel, ex. model_manager → développeur).

```
accessible(user, app):
    if app.min_tier and tier(user) < app.min_tier:        # garde de tier
        return False
    if tier(user) in {développeur, admin}:                # bypass : devs/admins voient tout
        return True
    if user is anonymous:
        return app.public
    if not app.roles:                                     # app commune
        return True
    return roles(user) ∩ app.roles ≠ ∅                    # au moins un rôle correspondant
```

**Cumul** : avoir plusieurs rôles = **union** des apps. **Tous les rôles = toutes les apps métier**
(découle naturellement de l'union — pas besoin de cas spécial). → réponse à la question ouverte de
Fabien : **oui**, cumul de tous les rôles ⇒ accès à tout (et de toute façon admin/développeur
bypassent par le tier).

### 1.3 Implémentation proposée (Django-natif + métadonnée)
- **Tier** : champ `UserProfile.account_tier` (choices). (admin/développeur peuvent aussi s'appuyer
  sur `is_superuser`/`is_staff` existants, mais un champ explicite est plus lisible.)
- **Rôles métier** : **Django `Group`** (M2M natif user↔groups, admin UI gratuite pour assigner).
  Un groupe par rôle (`role:communication`, `role:recherche`, …).
- **Mapping app→rôles** : déclaré dans `APP_CATALOG` (`roles`/`public`/`min_tier`) — **source unique**.
- **Enforcement** (3 points, une seule logique partagée `accessible()`) :
  1. **Lanceur d'apps / nav** : ne lister que les apps accessibles.
  2. **Décorateur de vue** `@app_access('imager')` sur les vues d'app (défense en profondeur).
  3. **Studio** : `api/studio-nodes/` **filtré** par accès (on ne propose que les nœuds autorisés).
- **Context processor** : exposer `accessible_apps` aux templates (déjà un `user_role()` existant à étendre).

## 2. Notifications email (axe indépendant)
Préférences **par utilisateur** sur `UserProfile` :
- `notify_email` (bool, défaut on), `notify_on` ∈ {`completion`, `failure`, `both`, `none`}, option
  `digest` (récap quotidien plutôt qu'à chaque tâche).
- **Déclenchement** : hook dans le cycle des tâches Celery (à la complétion/échec d'un job long),
  via un helper commun `notify_user(user, event, context)` (respecte les préférences).
- **Transport** : `EMAIL_BACKEND` Django (SMTP UGE) ; gabarits email communs (sujet/corps i18n).
- **Indépendant des permissions** → peut être livré en premier, faible risque.

## 3. Conservation des médias (rétention)
- Champ `UserProfile.media_retention_days` (0 = illimité). **Défaut par tier/rôle** possible
  (ex. utilisateur 90 j, communication 180 j…), **plafond** fixé par l'admin (un user peut **raccourcir**
  mais pas dépasser le max politique).
- **Purge** : tâche **Celery beat** quotidienne → supprime les médias (input/output) dont
  `created_at + retention < now`, en respectant `safe_delete_file` (refs partagées) et en **excluant**
  les éléments épinglés/favoris (à prévoir).
- **Préavis** : notification email J‑N avant suppression (réutilise §2).
- **Médiathèque** : les `UserAsset` peuvent avoir leur propre politique (assets « gardés » exemptés).

## 4. Questions ouvertes / recommandations
1. **Terminologie** : adopter **« Profil de compte » (tier)** + **« Rôles métier » (cumulatifs)** ;
   abandonner « sous-profil » (ambigu). → *recommandé*.
2. **Cumul de tous les rôles = tout** : **oui** (union). *recommandé*.
3. **anonymous** : autorise-t-on une persistance limitée ou strictement éphémère ? → *proposer éphémère*.
4. **développeur vs admin** : développeur = tous les **outils** ; admin = tous les outils **+ gestion
   humains/politiques**. Les deux bypassent le gating d'apps. → *recommandé*.
5. **Rétention** : défaut global unique vs défaut par tier/rôle ? → *commencer simple : défaut global +
   override par user borné par un plafond admin* ; raffiner par rôle plus tard.

## 5. Phasage proposé (du moins au plus couplé)
1. **Notifications email** (indépendant, faible risque) — champs profil + `notify_user()` + hook Celery.
2. **Rétention** — champ profil + beat de purge + préavis (réutilise les notifs).
3. **Permissions** (fondateur) — `UserProfile.account_tier`, Groups de rôles, `APP_CATALOG.roles/public/min_tier`,
   `accessible()` + 3 points d'enforcement. **À faire après validation du modèle** (impact transversal/sécurité).

> Reste cohérent avec : `WAMA_APP_CONVENTIONS.md`, `accounts/` (`UserProfile` + `user_role()`),
> `media_library/`, `STUDIO_VISION.md` (les rôles gateront aussi les nœuds studio).

## 6. État d'implémentation (2026-06-25)
**Fait (phase 1, testé) :**
- `UserProfile.account_tier` (migration 0005) ; rôles métier = **Django Groups `role:*`**.
- `AppAccessPolicy` (DB, **éditable**) + admin Django (`filter_horizontal` rôles) = tableau d'accès éditable (MVP).
- `accounts/permissions.py` : `accessible()` / `accessible_apps()` / `user_tier()` / `user_roles()` + décorateur `app_access` (prêt, **pas encore appliqué**).
- Seed : `python manage.py seed_access` (4 rôles + 13 politiques ; `--reset` pour réinitialiser).
- Enforcement **actif** : **header (menu d'apps, toutes pages)** filtré par `accessible_apps` ; **studio** (`api/studio-nodes/`) filtré. Context processor expose `account_tier`/`user_roles_set`/`accessible_apps`.
- Anonymizer ∈ communication (+ recherche + administratif) — flouter marques/visages en com.

**Fait (phase 2, testé) :**
- Cartes du **dashboard `home.html`** filtrées par `accessible_apps` (chaînage `{% if %}`/`{% endif %}`).
- **`AppAccessMiddleware`** (`accounts/middleware.py`, enregistré) : blocage défense-en-profondeur de
  TOUTES les vues d'app (FBV/CBV) par préfixe d'URL. anonymous → login_required ; admin/dev bypass ;
  API/AJAX → 403 JSON ; nav → redirect home + message. Testé (recherche-user /imager/ → 302 ; AJAX → 403).
- **Déploiement soft** : `grant_default_roles` (tous les rôles aux users existants non-superuser).

**Fait (notifications email, testé) :**
- Config email pilotée par env (`WAMA_EMAIL_*`) + **console en DEBUG** ; `UserProfile.notify_email`/
  `notify_on` (migration 0006) + `wants_notification()`.
- Brique commune `common/utils/notifications.py` : `notify_user()` + `notify_job(user, app, item, success, …)`
  (fail-safe, respecte les préférences). Gating testé. **Câblé dans Transcriber** (succès + échec).

**Fait (UI + propagation, testé) :**
- **Page profil** : carte « Notifications email » (toggle `notify_email` + select `notify_on`) +
  endpoint `accounts:profile-notifications` (AJAX). Testé (rendu + POST persiste).
- **`notify_job` propagé** : transcriber, composer, enhancer (image/vidéo + audio), imager
  (image + vidéo) — points succès + échec, fail-safe.

**Fait (rétention médias, testé) :**
- `UserProfile.media_retention_days` (0=illimité, migration 0007) + `effective_retention_days()`
  (plafond `WAMA_MAX_RETENTION_DAYS`). Page profil : carte « Conservation des médias » + endpoint
  `accounts:profile-retention`. Admin : colonne ajoutée.
- Service `common/services/retention.py` : registre déclaratif `RETENTION_MODELS` + purge par
  **introspection des FileField** (`safe_delete_file`) + chemins JSON (imager `generated_images`).
  `purge_expired_media(dry_run)` + `upcoming_expirations(days)`. Testé (synthesis backdatée → purgée).
- Commande `manage.py purge_media [--dry-run]` + **tâche beat quotidienne** `common.purge_expired_media`
  (04:00, queue default) avec **pré-avis email J‑N** (`WAMA_RETENTION_NOTICE_DAYS`, défaut 3).

**Fait (matrice + propagation complète, testé) :**
- **UI matrice rôles×apps** : `accounts:app-access-matrix` (admin) — table app×rôle (cases à cocher) +
  public + tier min., **AJAX par cellule** (`app-access-toggle`). Lien depuis la page Utilisateurs.
- **`notify_job` propagé aux 10 apps** : transcriber, composer, enhancer (img/vid+audio), imager
  (img+vid), synthesizer, describer, reader, anonymizer, avatarizer, converter (succès + échec).

**Fait (mineur, testé) :**
- **Imager : signal `post_save`** (`imager/signals.py`, `apps.ready()`) → notifie sur transition vers
  état terminal (couvre succès + **tous les échecs inline** d'un seul endroit ; les 2 appels explicites
  retirés). Testé (progress→0, FAILURE→1, re-save→1).
- **Exemption purge** : hook `pin` dans `RETENTION_MODELS` (`qs.exclude(pin=True)`) — dormant tant
  qu'aucun modèle n'a de champ d'épinglage ; prêt à brancher (`'pin': 'is_pinned'`).

**⚠️ Opérationnel :**
- **Redémarrer le serveur WSL2** pour charger le nouveau code (migration + seed déjà appliqués sur la base partagée).
- **Les utilisateurs non-admin sans rôle ne voient que les apps communes** (converter). Leur **assigner des rôles** via l'admin, sinon accès réduit. (Décision possible : seed « soft » donnant tous les rôles aux users existants — non fait, à ta demande.)
- admin/superuser & développeur **bypassent** → tu n'es pas verrouillé.
