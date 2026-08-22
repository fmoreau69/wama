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

## 1.4 Le compte `anonymous` — DEUX notions qui s'annulaient (fermé le 2026-08-22)

**Décision Fabien (2026-08-22) : WAMA n'est pas ouvert.** On s'y connecte par LDAP et
l'inscription est validée à la main. Le compte anonyme ne doit donc **rien** pouvoir faire, et
aucune app n'est déclarée `public` — la ligne « converter public » un temps envisagée est
**abandonnée**.

### Ce qui n'allait pas, et qui n'était écrit nulle part

WAMA porte **deux** notions d'anonyme, et elles étaient opposées :

| | tier résolu | rôles | `accessible()` |
|---|---|---|---|
| `AnonymousUser` (requête non connectée) | `anonymous` | — | False partout |
| utilisateur **`anonymous` en base** (le repli des vues) | `utilisateur` | **les 4 rôles** | **True partout** |

`get_or_create_anonymous_user()` — le repli qu'appellent les vues via `_user(request)` — rend le
**second**. `user_tier()` teste `is_authenticated`, propriété qui vaut **toujours `True`** sur une
instance `User` de la base : le compte anonyme était donc indiscernable d'un vrai utilisateur.

Conséquence mesurée : `@app_access` laissait passer un visiteur non connecté (POST anonyme sur
`transcriber/upload/` → **400 pour fichier manquant, pas 403** : la vue s'exécutait). La matrice
d'accès était décorative sur ces chemins, et **la seule garde qui mordait réellement était le
`@login_required` du converter** — c'est-à-dire sur l'app qu'on voulait justement ouvrir. La
situation était exactement inversée par rapport à l'intention.

### La fermeture, en deux gestes (base, réversibles)

1. **retrait des 4 rôles** du compte `anonymous` → 14 apps accessibles sur 16 → **2** ;
2. **tier `anonymous`** posé sur son profil → **0**. Sans ce second geste il gardait les apps
   COMMUNES (`converter`, `media_library`), qui passent par la branche « app commune » — jamais
   par la branche `anonymous`.

Contrôle : `wama_nightly_test` 14/16 et un admin 16/16 restent inchangés.

> **Rien dans le code n'attribue ces rôles** : le compte est créé sans groupe et `is_active=False`
> (`accounts/views.py:511`). Ils avaient été posés à la main. Le geste ne sera donc pas défait au
> redémarrage — mais rien ne l'empêche non plus d'être refait par la matrice d'administration.

## 1.5 Trous d'application relevés au passage (2026-08-22, mesurés)

- **Les pages d'index ne sont pas gardées** : `/converter/` et `/transcriber/` répondent **200**
  à un visiteur non connecté alors qu'`accessible()` dit False. L'algorithme existe mais n'est
  branché sur aucun index — seules certaines *actions* le sont.
- **Gardes d'action hétérogènes sur `upload`** : converter `@login_required + @app_access` ;
  transcriber et enhancer `@app_access` ; describer, reader, synthesizer `@require_POST` seul ;
  **anonymizer, imager, composer, avatarizer : aucune garde**.
- **Aucune garde SSRF sur l'ingest d'URL** (`fetch_url_content`, `upload_media_from_url`) : ni
  liste blanche, ni blocage des IP privées, ni restriction de schéma. Un utilisateur peut faire
  fetcher au serveur une adresse interne. Vaut aussi pour les comptes authentifiés — durcissement
  à faire indépendamment de la question de l'ouverture.
- **Aucun contrôle de contenu à l'upload** : pas d'antivirus, pas de vérification du type réel,
  pas de borne de taille dans `settings.py`.

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

---

## 7. Partage d'objets (cards, sessions wama-lab) — état réel et cible (2026-07-31)

> **Besoin** : partager une card / une session, **en lecture seule par défaut**, l'écriture ne
> s'obtenant que **sur demande acceptée**. Premier usage concret : partager **1 card par app** avec
> l'utilisateur de test du nocturne (`wama_nightly_test`), ce qui permet de tester la chaîne
> complète **sans réingérer de fichiers d'entrée** (décision Fabien 31/07 — le partage *sert* les
> tests au lieu d'être un chantier parallèle).

### 7.1 Ce qui EXISTE (et qui est bon)

| Brique | Fichier | État |
|---|---|---|
| `OrgUnit` — arbre LDAP/SUPANN | `common/models.py` | ✅ |
| `Project` — collaboration **traversant l'arbre** (partenaires hors établissement) | `common/models.py` | ✅ |
| `ProjectMembership` — rôles `lead`/`member`/`partner`/**`viewer` (lecture seule)** | `common/models.py` | ✅ |
| `ScopedVisibility` — `private`/`unit`/`project`/`public` + filtre `visible_to_q(user)` | `common/models.py` | ✅ écrit |

### 7.2 Ce qui MANQUE (les trois trous, mesurés)

1. **L'ADOPTION.** `ScopedVisibility` n'est hérité que par **2 modèles** : `media_library.UserAsset`
   et `common.UserFunction`. **Aucun** modèle de card d'app, ni les sessions wama-lab ; leurs vues
   filtrent `user=user` en dur. Mécanisme **présent mais inerte** — le doublon silencieux contre
   lequel le cadrage du 31/07 met en garde. **C'est le vrai chantier.**
2. **L'AXE ÉCRITURE.** `visibility` dit qui **voit**. Il n'existe **aucun** droit d'écriture par
   objet. `ProjectMembership.role` distingue `viewer` de `member`, mais c'est un rôle **de projet**,
   pas un droit **sur un objet**.
3. **LE WORKFLOW demande → acceptation.** Inexistant.

### 7.3 Cible : UNE table générique, pas un troisième axe

`ObjectGrant` : cible en clé générique (`content_type` + `object_id`), bénéficiaire = **user OU
project OU org_unit**, `level = read|write`, `state = requested|granted|refused`, `granted_by`,
`expires_at`.

- **La demande ET le droit sont la même ligne** : demander l'écriture = un grant `requested/write`
  que le propriétaire bascule en `granted`. Pas de second modèle à synchroniser.
- **Une seule table pour tout** : cards des apps, sessions wama-lab, objets futurs. **Zéro code par
  app** (règle de centralisation).
- **Traçabilité gratuite** : `AccessLog` (accounts) existe déjà.

### 7.4 Le danger, et sa parade

Les droits par objet **fuient dans toutes les requêtes** : une seule vue qui oublie le filtre ouvre
tout. Parade : rendre le chemin correct **le seul disponible** (manager `Model.objects.visible_to(user)`)
**et en faire un critère de la grille de conformité** — l'adoption devient alors **mesurée**, pas
espérée. C'est ce qui distingue cette cible de `ScopedVisibility`, écrit puis oublié sur 2 modèles.

### 7.4bis État d'adoption — MESURÉ par la grille (31/07)

Deux critères F7 ont été ajoutés à `check_app_conformity`, donc **plus aucune app ne peut
prétendre au partage sans l'avoir branché** :

| Critère | Ce qu'il mesure |
|---|---|
| `shareable_models` | La card **ET** son batch héritent de `ScopedVisibility`. 🔶 si un seul des deux — la file étant construite à partir des BATCHES, une card partagée sans son batch **n'apparaît pas**. |
| `scoped_reads` | Les vues de lecture passent par les accès **nommés** (`visible_or_404` / `visible_to`). |

Photo au 31/07 : ✅ **converter, enhancer, transcriber** · 🔶 **imager** (mixin sur la card, pas
sur son batch — et lectures volontairement non portées, cf. §7.5) · ❌ anonymizer, avatarizer,
composer, describer, reader, synthesizer.

**Geste de portage d'une app** (désormais mécanique, ~15 min) :
1. `class Card(…, ScopedVisibility)` + `objects = ScopedManager()` ;
2. **idem sur le modèle de BATCH** (sinon le partage ne remonte pas dans la file) ;
3. `makemigrations` + `migrate` ;
4. chemins de LECTURE (progress, download, status…) → `visible_or_404` ; tout ce qui mute reste
   inchangé — le partage est en lecture seule **par construction**, pas par vigilance.

### 7.5 Ordre de mise en place (décidé 31/07)

1. **Adopter `ScopedVisibility` sur les modèles de cards** + manager + critère de conformité.
2. **Ensuite seulement** `ObjectGrant` et l'écriture sur demande.

Construire l'escalade d'écriture sur une visibilité inerte reviendrait à empiler du neuf sur du
non-branché.

**Reste à faire (au 31/07, fin de session)** :
- porter les 6 apps ❌ ci-dessus (geste mécanique du §7.4bis) ;
- **`cam_analyzer` : les SESSIONS de wama-lab ne sont pas regardées du tout** — leur structure
  diffère des cards (pas de batch, pas la même file). Reporté explicitement (décision Fabien
  31/07), à traiter comme un cas propre, pas par analogie ;
- **imager** : mixin sur son batch + chemins de lecture, quand l'app sera portée sur
  l'uniformisation (dernière de la grille, 56 % — ne pas industrialiser l'état partiel) ;
- il n'existe **aucune interface de partage** : passer par l'admin Django, ou écrire la commande
  de gestion prévue (`partager_card --app … --user wama_nightly_test`) pour le nocturne ;
- puis `ObjectGrant` (§7.3), en **extension de `scoped_visible_q`** — jamais un second chemin.

### 7.6 Prior art

**Twenty** = la bonne référence : la leçon déjà retenue (*les permissions déclarées sont un
prérequis à l'ingestion automatique par LLM*) impose que **le manifeste déclare** qu'un modèle est
partageable et à quelle granularité — pas chaque app qui le code. Le partage se branche donc sur le
chantier manifestes. **Hermes n'apporte rien ici** : son runtime a été écarté (second ordonnanceur
GPU en production), seule l'idée des skills avait été retenue ; il n'a pas de modèle de permissions
à emprunter.
