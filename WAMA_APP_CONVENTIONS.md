# WAMA — Conventions & Normes des Applications

> **Version :** 1.0 — 2026-03-19
> **Audience :** Développeurs humains, Claude Code, wama-dev-ai
> **Portée :** Toutes les applications Django de WAMA (`wama/<app>/`)
> **Relation :** Complète `CLAUDE.md` — lire les deux avant tout développement

---

## Légende

| Symbole | Signification |
|---------|--------------|
| ✅ | Conforme dans toutes les apps concernées |
| ⚠️ | Partiellement conforme — voir détails |
| 🚧 | À uniformiser — des apps ne respectent pas encore cette convention |
| 📋 | Planifié — pas encore implémenté dans aucune app |
| ❌ | Non conforme identifié — correction prioritaire |

---

## 0. Checklist — Création d'une nouvelle application

Créer dans l'ordre. Ne pas sauter d'étape.

```
[ ] 0.  Choisir un nom court (snake_case) : reader, imager, composer…
[ ] 1.  Créer wama/<app>/ avec la structure fichiers standard (§1)
[ ] 2.  Déclarer dans settings.py : INSTALLED_APPS + MODEL_PATHS (si AI)
[ ] 3.  Ajouter include() dans wama/urls.py
[ ] 4.  Créer le modèle principal (§2) + migration
[ ] 5.  Créer les URL patterns standard (§3)
[ ] 6.  Créer les vues standard (§3)
[ ] 7.  Créer templates/ : base.html + index.html + _item_card.html
[ ] 8.  Créer static/<app>/js/<app>.js (JS côté client)
[ ] 9.  Copier dans staticfiles/<app>/ après chaque modif JS/CSS
[ ] 10. Ajouter le lien dans wama/templates/includes/header.html (ordre alpha, §16)
[ ] 11. Ajouter la card dans wama/templates/home.html (ordre alpha, §16)
[ ] 12. Enregistrer les modèles AI dans model_registry.py (si AI)
[ ] 13. Ajouter les outils API dans wama/tool_api.py + wama/urls.py (§17)
[ ] 14. Ajouter les icônes TOOL_ICONS dans home.html
[ ] 15. Ajouter à la table de conformité §15 de ce document
[ ] 16. Ajouter l'entrée dans appFolderMap de filemanager.js (§8.5) — auto-dépliement sidebar
[ ] 17. Ajouter l'app dans app_registry.py (APP_CATALOG) avec conventions conformity flags
```

---

## 1. Structure des Fichiers

Chaque application suit cette arborescence **obligatoire** :

```
wama/<app>/
├── __init__.py
├── apps.py                          # AppConfig : name = 'wama.<app>'
├── models.py                        # Modèle principal (voir §2)
├── admin.py                         # ModelAdmin basique
├── urls.py                          # app_name = 'wama.<app>' (voir §3)
├── views.py                         # Vues standard (voir §3)
├── tasks.py                         # Tâches Celery (si traitement async)
│
├── backends/                        # Implémentations AI (si applicable)
│   ├── __init__.py
│   └── <nom>_backend.py
│
├── utils/                           # Utilitaires spécifiques à l'app
│   ├── __init__.py
│   └── model_config.py              # Chemins + catalogue modèles AI (si applicable)
│
├── templates/<app>/
│   ├── base.html                    # Étend common/app_modern_base.html
│   ├── index.html                   # Vue principale (surcharge base.html)
│   └── _item_card.html              # Partial server-side pour la card
│
├── static/<app>/
│   └── js/<app>.js                  # JS principal de l'app
│
└── migrations/
    └── 0001_initial.py
```

**Important :** Après toute modification JS/CSS, copier dans `staticfiles/<app>/`.

---

## 2. Modèle de Données Standard

Chaque application possède un **modèle principal** (`XxxItem` ou équivalent métier)
et optionnellement un **modèle batch** (`XxxBatch`).

### 2.1 Champs obligatoires du modèle item

```python
class MyItem(models.Model):

    # ── Identité ───────────────────────────────────────────────────────────────
    user        = models.ForeignKey(User, on_delete=models.CASCADE)
    # input_file OU input_url OU input_text selon le type d'app
    input_file  = models.FileField(upload_to=upload_to_user_input('<app>'))
    original_filename = models.CharField(max_length=255, blank=True, default='')

    # ── Paramètres (définis par l'app) ─────────────────────────────────────────
    # … model, language, backend, mode, format, etc.

    # ── État de traitement ─────────────────────────────────────────────────────
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'En attente'
        RUNNING = 'RUNNING', 'En cours'
        DONE    = 'DONE',    'Terminé'
        ERROR   = 'ERROR',   'Erreur'

    status      = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    task_id     = models.CharField(max_length=255, blank=True, default='')
    progress    = models.IntegerField(default=0)         # 0-100
    error_message = models.TextField(blank=True, default='')

    # ── Résultat ───────────────────────────────────────────────────────────────
    # output_file OU result_text selon le type d'app
    # used_model / used_backend : modèle effectivement utilisé (si sélection auto)

    # ── Méta ───────────────────────────────────────────────────────────────────
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
```

### 2.2 Modèle batch (recommandé pour toutes les apps — §9)

```python
class MyBatch(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE)
    batch_file  = models.FileField(upload_to=upload_to_user_input('<app>'), blank=True)
    total       = models.IntegerField(default=1)
    created_at  = models.DateTimeField(auto_now_add=True)

class MyItem(models.Model):
    batch       = models.ForeignKey(MyBatch, null=True, blank=True, on_delete=models.SET_NULL)
    # … reste des champs standard
```

---

## 3. URLs & Vues Standard

### 3.1 URL patterns obligatoires

```python
# wama/<app>/urls.py
app_name = 'wama.<app>'

urlpatterns = [
    # ── Pages ──────────────────────────────────────────────────────────────────
    path('',                        views.IndexView.as_view(), name='index'),

    # ── Import ─────────────────────────────────────────────────────────────────
    path('upload/',                 views.upload,              name='upload'),
    # + 'import-from-filemanager/' si intégration filemanager (§8)

    # ── Actions sur un item ────────────────────────────────────────────────────
    path('start/<int:pk>/',         views.start,               name='start'),
    path('progress/<int:pk>/',      views.progress,            name='progress'),
    path('download/<int:pk>/',      views.download,            name='download'),
    path('delete/<int:pk>/',        views.delete,              name='delete'),
    path('duplicate/<int:pk>/',     views.duplicate,           name='duplicate'),
    path('settings/<int:pk>/',      views.update_settings,     name='update_settings'),

    # ── Actions globales ───────────────────────────────────────────────────────
    path('start-all/',              views.start_all,           name='start_all'),
    path('clear-all/',              views.clear_all,           name='clear_all'),
    path('download-all/',           views.download_all,        name='download_all'),
    path('global-progress/',        views.global_progress,     name='global_progress'),

    # ── Batch ──────────────────────────────────────────────────────────────────
    path('batch/preview/',          views.batch_preview,       name='batch_preview'),
    path('batch/create/',           views.batch_create,        name='batch_create'),
    path('batch/<int:pk>/start/',   views.batch_start,         name='batch_start'),
    path('batch/<int:pk>/download/',views.batch_download,      name='batch_download'),
    path('batch/<int:pk>/delete/',  views.batch_delete,        name='batch_delete'),
    path('batch/<int:pk>/duplicate/',views.batch_duplicate,    name='batch_duplicate'),

    # ── Console ────────────────────────────────────────────────────────────────
    path('console/',                views.console_content,     name='console'),
]
```

### 3.2 Pattern de vue `start` (anti-race-condition obligatoire)

```python
@require_POST
def start(request, pk):
    user = _get_user(request)
    with transaction.atomic():
        item = get_object_or_404(
            MyItem.objects.select_for_update(), pk=pk, user=user
        )
        if item.status == 'RUNNING':
            return JsonResponse({'error': 'Déjà en cours'}, status=409)
        if item.task_id:
            try:
                from celery import current_app
                current_app.control.revoke(item.task_id, terminate=False)
            except Exception:
                pass
        item.status = 'RUNNING'
        item.task_id = ''
        item.result_text = ''        # ou output_file selon l'app
        item.error_message = ''
        item.progress = 0
        item.save()
    task = my_task.delay(item.id)
    item.task_id = task.id
    item.save(update_fields=['task_id'])
    return JsonResponse({'ok': True, 'task_id': task.id})
```

### 3.3 Sérialisation standard (`_item_to_dict`)

```python
def _item_to_dict(item) -> dict:
    cached = cache.get(f'<app>_progress_{item.id}')
    return {
        'id':           item.id,
        'filename':     item.filename,         # @property
        # … paramètres spécifiques …
        'status':       item.status,
        'progress':     cached.get('pct', item.progress) if cached else item.progress,
        'progress_msg': cached.get('msg', '') if cached else '',
        'eta_seconds':  cached.get('eta', None) if cached else None,  # §7
        'has_result':   bool(item.result_text or item.output_file),
        'result_preview': …,
        'used_backend': item.used_backend,
        'error_message': item.error_message,
        'created_at':   item.created_at.isoformat(),
    }
```

---

## 4. Template — Layout & Onglets

### 4.1 Hiérarchie obligatoire

```
common/app_modern_base.html   ← base de toutes les apps
    └── <app>/base.html       ← définit app_icon, app_title, about, help, footer
        └── <app>/index.html  ← queue content, settings panel, JS config
```

### 4.2 Blocs disponibles dans `app_modern_base.html`

| Bloc | Usage |
|------|-------|
| `extra_css` | CSS spécifiques à l'app |
| `app_styles` | Styles inline |
| `app_icon` | Icône FontAwesome dans le header |
| `app_title` | Titre de l'application |
| `app_description` | Sous-titre |
| `queue_content` | Contenu de l'onglet File d'attente |
| `console_content_id` | ID du div console (défaut : `console-content`) |
| `console_app_name` | Nom de l'app pour les logs (défaut : `system`) |
| `about_content` | Contenu de l'onglet À propos |
| `help_content` | Contenu de l'onglet Aide |
| `app_right_panel_settings` | Panneau droit — section paramètres |
| `app_right_panel_actions` | Panneau droit — boutons d'action globaux |
| `app_scripts` | JS inline (config window.*) |
| `javascript` | Scripts JS (inclure les fichiers .js ici) |
| `extra_modals` | Modales Bootstrap supplémentaires |

### 4.3 Onglets obligatoires

La base fournit 4 onglets automatiquement. Chaque app **doit** remplir les 4 :

| Onglet | Bloc | Contenu attendu |
|--------|------|----------------|
| File d'attente | `queue_content` | Zone de drop + liste des cards |
| Console | *(fourni par la base)* | Logs Celery filtrés par app |
| À propos | `about_content` | Description, modèles utilisés, technologie |
| Aide | `help_content` | Guide d'utilisation, conseils, FAQ |

---

## 5. File d'attente — Format des Cards

### 5.1 Structure d'une card (ordre obligatoire)

```
┌─────────────────────────────────────────────────────────────────┐
│  [icône]  NOM DU FICHIER / TITRE               [badges statut]  │
│           Paramètres clés : modèle, langue, format…             │
├─────────────────────────────────────────────────────────────────┤
│  ████████████░░░░░░  68%  •  En cours  •  ~12s restants         │
│  "Étape : extraction page 3/5…"                                  │
├─────────────────────────────────────────────────────────────────┤
│  Aperçu du résultat (tronqué, clic pour développer)             │
├─────────────────────────────────────────────────────────────────┤
│  [⚙] [▶] [⬇] [⧉] [🗑]    ← boutons d'action (§6)             │
└─────────────────────────────────────────────────────────────────┘
```

**Composants requis :**

| Zone | Contenu | Obligatoire |
|------|---------|-------------|
| En-tête | Nom fichier/titre cliquable (`source-preview-btn`), badge statut, badges paramètres clés | ✅ |
| Infos secondaires | Modèle/backend utilisé, options principales | ✅ |
| Barre de progression | % + statut + ETA (§7) — visible si RUNNING | ✅ |
| Message de progression | Étape courante ("page 2/5…") | ✅ |
| Aperçu résultat | Texte tronqué ou miniature — visible si DONE | ✅ |
| Message d'erreur | Alert Bootstrap danger — visible si ERROR | ✅ |
| Boutons d'action | Voir §6 | ✅ |

### 5.4 Nom de fichier — couleur et prévisualisation source au clic

**Couleur :** Le nom de fichier doit toujours être visible. Utiliser `text-light` (jamais omettre la classe couleur sur fond sombre).

**Preview source au clic :** L'icône + le nom de fichier doivent être cliquables pour afficher une prévisualisation du **fichier source** (image ou PDF) dans une modale Bootstrap.

```html
<!-- En-tête de card — icône + nom cliquables -->
<span role="button" class="source-preview-btn d-flex align-items-center gap-1"
      data-id="{{ item.id }}" data-filename="{{ item.filename }}"
      title="Aperçu du fichier source">
    <i class="fas fa-file-alt text-info me-1"></i>
    <span class="fw-semibold text-light text-truncate" style="max-width:240px;">{{ item.filename }}</span>
</span>
```

**Backend :** Vue `source_file(request, pk)` servant le fichier en `inline` (Content-Disposition: inline) pour affichage navigateur :
```python
response = FileResponse(item.input_file.open('rb'), content_type=mime)
response['Content-Disposition'] = f'inline; filename="{basename}"'
```

**JS :** Listener délégué sur `document` pour `.source-preview-btn` (couvre les cards statiques ET dynamiques) :
```javascript
document.addEventListener('click', e => {
    const btn = e.target.closest('.source-preview-btn');
    if (!btn) return;
    openSourcePreview(btn.dataset.id, btn.dataset.filename);
});
```

**Modal** (dans `{% block extra_modals %}`) : `modal-xl modal-dialog-centered` avec `<img>` pour images et `<embed type="application/pdf">` pour PDFs.

**Règles :**
- Images (`jpg/jpeg/png/webp/gif/bmp/tiff`) → `<img class="img-fluid">`
- PDF → `<embed type="application/pdf" style="height:78vh">`
- Autres formats → message + lien de téléchargement
- La modal vide immédiatement son contenu à l'ouverture (spinner) puis charge à la demande

**Conformité par app :**
| App | Preview source | Remarque |
|-----|---------------|---------|
| Reader | ✅ | Images + PDFs |
| Transcriber | 📋 | Audio — utiliser `<audio controls>` |
| Describer | 📋 | Images/vidéos — utiliser player vidéo |
| Enhancer | 📋 | Images/vidéos/audio |
| Anonymizer | 📋 | Vidéos/images |
| Imager | N/A | Génération — pas de source |
| Synthesizer | N/A | Texte — pas de fichier source |
| Composer | N/A | Génération |

### 5.2 Implémentation double (server-side + client-side)

Chaque card est rendue **deux fois** avec la même structure :
- **Server-side** : `templates/<app>/_item_card.html` (rendu au chargement initial)
- **Client-side** : fonction `buildCard(item)` dans `<app>.js` (rendu après upload/polling)

Les deux doivent rester **synchronisées**.

### 5.3 Classe CSS obligatoire

```html
<div class="<app>-card card bg-dark border-secondary mb-2"
     data-id="{{ item.id }}"
     data-status="{{ item.status }}">
  {% include '<app>/_item_card.html' with item=item %}
</div>
```

---

## 6. Boutons d'Action — Ordre & Contenu

### 6.1 Ordre obligatoire (de gauche à droite)

| Position | Bouton | Style | data-action | Règles |
|----------|--------|-------|-------------|--------|
| 1 | **Paramètres** | `btn-outline-secondary` | `settings` | Ouvre modale de config |
| 2 | **Démarrer / Relancer** | `btn-outline-success` (start) / `btn-outline-secondary` (restart) / `btn-outline-warning disabled` (running) | `start` / `restart` | Adaptatif selon statut |
| 3 | **Télécharger** | `btn-outline-info` | — (lien `<a>`) | Disabled si pas de résultat |
| 4 | **Dupliquer** | `btn-outline-secondary` | `duplicate` | Partage le fichier source (§12) |
| 5 | **Supprimer** | `btn-outline-danger` | `delete` | `safe_delete_file()` (§12) |

**Boutons supplémentaires** (spécifiques à l'app) : insérés **avant** le bouton Paramètres (position 0)
ou **entre** Télécharger et Dupliquer (position 3.5), selon leur nature.

Exemples : Aperçu (👁), Segmentation (SAM3), Export SRT, Lire l'audio…

### 6.2 Template snippet standard

```html
<div class="d-flex gap-1 flex-shrink-0">

  <!-- 1. Paramètres -->
  <button class="btn btn-sm btn-outline-secondary" data-action="settings" title="Paramètres">
    <i class="fas fa-cog"></i>
  </button>

  <!-- 2. Démarrer / Relancer -->
  {% if item.status == 'PENDING' or item.status == 'ERROR' %}
  <button class="btn btn-sm btn-outline-success" data-action="start" title="Lancer">
    <i class="fas fa-play"></i>
  </button>
  {% elif item.status == 'RUNNING' %}
  <button class="btn btn-sm btn-outline-warning" disabled title="En cours">
    <i class="fas fa-spinner fa-spin"></i>
  </button>
  {% else %}
  <button class="btn btn-sm btn-outline-secondary" data-action="restart" title="Relancer">
    <i class="fas fa-redo"></i>
  </button>
  {% endif %}

  <!-- 3. Télécharger -->
  {% if item.has_result %}
  <a href="{% url '<app>:download' item.id %}" class="btn btn-sm btn-outline-info" title="Télécharger">
    <i class="fas fa-download"></i>
  </a>
  {% else %}
  <button class="btn btn-sm btn-outline-info" disabled title="Pas encore de résultat">
    <i class="fas fa-download"></i>
  </button>
  {% endif %}

  <!-- 4. Dupliquer -->
  <button class="btn btn-sm btn-outline-secondary" data-action="duplicate" title="Dupliquer">
    <i class="fas fa-copy"></i>
  </button>

  <!-- 5. Supprimer -->
  <button class="btn btn-sm btn-outline-danger" data-action="delete" title="Supprimer">
    <i class="fas fa-trash"></i>
  </button>

</div>
```

### 6.3 Téléchargement multi-format — Split Button Dropdown

Quand un item peut être exporté en **plusieurs formats** (TXT, SRT, PDF, DOCX…),
utiliser un **split button dropdown Bootstrap** — un bouton principal (format par défaut)
+ une flèche qui déroule les formats alternatifs.
**Ne pas ajouter un bouton séparé par format.**

```html
<!-- 3. Télécharger (multi-format) — remplace le lien <a> simple -->
{% if item.has_result %}
<div class="btn-group btn-group-sm">
  <!-- Bouton principal : format par défaut (ex: TXT) -->
  <a href="{% url '<app>:download' item.id %}" class="btn btn-outline-info" title="Télécharger">
    <i class="fas fa-download"></i>
  </a>
  <!-- Flèche dropdown -->
  <button type="button" class="btn btn-outline-info dropdown-toggle dropdown-toggle-split"
          data-bs-toggle="dropdown" aria-expanded="false">
    <span class="visually-hidden">Autres formats</span>
  </button>
  <ul class="dropdown-menu dropdown-menu-dark dropdown-menu-end">
    <li>
      <a class="dropdown-item" href="{% url '<app>:download' item.id %}?format=txt">
        <i class="fas fa-file-alt me-2"></i>TXT
      </a>
    </li>
    <li>
      <a class="dropdown-item" href="{% url '<app>:download' item.id %}?format=pdf">
        <i class="fas fa-file-pdf me-2 text-danger"></i>PDF
      </a>
    </li>
    <li>
      <a class="dropdown-item" href="{% url '<app>:download' item.id %}?format=docx">
        <i class="fas fa-file-word me-2 text-primary"></i>DOCX
      </a>
    </li>
  </ul>
</div>
{% else %}
<button class="btn btn-sm btn-outline-info" disabled title="Pas encore de résultat">
  <i class="fas fa-download"></i>
</button>
{% endif %}
```

**Vue backend** — la vue `download(request, pk)` lit le paramètre `?format=` :

```python
def download(request, pk):
    item = get_object_or_404(MyModel, pk=pk, user=get_user(request))
    fmt = request.GET.get('format', 'txt')   # défaut : format texte brut

    if fmt == 'pdf':
        # WeasyPrint : HTML → PDF via template Django
        from weasyprint import HTML
        from django.template.loader import render_to_string
        html = render_to_string('myapp/pdf/result.html', {'item': item})
        pdf_bytes = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        return HttpResponse(pdf_bytes, content_type='application/pdf',
                            headers={'Content-Disposition': f'attachment; filename="{item.pk}.pdf"'})

    elif fmt == 'docx':
        from docx import Document
        doc = Document()
        doc.add_heading(item.filename, 0)
        doc.add_paragraph(item.result_text)
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return FileResponse(buf, as_attachment=True, filename=f'{item.pk}.docx')

    else:  # txt (défaut)
        return HttpResponse(item.result_text, content_type='text/plain; charset=utf-8',
                            headers={'Content-Disposition': f'attachment; filename="{item.pk}.txt"'})
```

**Librairies** (ajouter dans `requirements.txt`) :
- `weasyprint` — HTML/CSS → PDF (qualité publication ; dépendances système : GTK/Pango sur Windows, libpango sur Linux)
- `fpdf2` — alternative légère 100% Python (layout programmatique, sans dépendances système)
- `python-docx` — génération DOCX

**Règle de sélection** :
- Contenu narratif riche (compte-rendu, synthèse scientifique) → **WeasyPrint** (template HTML+CSS dédié par format)
- Export simple sans mise en page → **fpdf2**
- Format Word requis → **python-docx**

---

## 7. Barre de Progression & ETA

### 7.1 Ce qui doit être affiché

Chaque item RUNNING affiche **obligatoirement** :

```
[████████████░░░░░░░░░]  62%  •  En cours  •  ~8s restants
  Étape courante : "Extraction page 3 sur 5…"
```

| Élément | Source |
|---------|--------|
| Barre Bootstrap | `progress-bar bg-warning progress-bar-striped progress-bar-animated` |
| Pourcentage | `item.progress` (0-100) depuis le cache `<app>_progress_<id>` |
| Badge statut | `statusBadge(item.status)` |
| ETA individuel | `item.eta_seconds` depuis le cache (calculé dans la tâche Celery) |
| Message d'étape | `item.progress_msg` depuis le cache |

### 7.2 ETA — Estimation de durée

**Trois niveaux d'ETA à exposer :**

| Niveau | Description | Où l'afficher |
|--------|-------------|---------------|
| **Item** | Temps restant pour l'item courant | Dans la card, sous la barre |
| **Batch** | Temps restant pour tout le batch | Dans l'en-tête du groupe batch |
| **Queue** | Temps total restant pour toute la file | Dans la barre globale (header) |

**Stockage dans la tâche Celery :**

```python
def _set_progress(item_id, pct, msg='', eta_seconds=None):
    cache.set(f'<app>_progress_{item_id}', {
        'pct':         pct,
        'msg':         msg,
        'eta':         eta_seconds,
        'updated_at':  time.time(),
    }, timeout=3600)
```

**Calcul de l'ETA (pattern recommandé) :**

```python
# Dans la tâche Celery, après chaque étape :
elapsed = time.time() - start_time
if pct > 0:
    total_estimated = elapsed / (pct / 100)
    eta = total_estimated - elapsed
else:
    eta = None
_set_progress(item_id, pct, msg=f"Page {i}/{n}…", eta_seconds=eta)
```

**Formatage JS :**

```javascript
function formatEta(seconds) {
    if (!seconds || seconds < 0) return '';
    if (seconds < 60) return `~${Math.round(seconds)}s`;
    return `~${Math.round(seconds / 60)}min`;
}
```

> **État actuel :** 🚧 L'ETA n'est implémenté dans aucune app — à ajouter progressivement.

---

## 8. Import de Fichiers

### 8.1 Modes d'import obligatoires

| Mode | Description | Status |
|------|-------------|--------|
| **Drag & drop** | Zone cliquable + glisser-déposer | ⚠️ Manquant dans Imager |
| **Parcourir** | `<input type="file" multiple>` | ✅ Toutes les apps |
| **Dossier récursif** | `<input webkitdirectory>` | 📋 Non implémenté |
| **FileManager** | Import depuis `/filemanager/` — sélection multiple ou dossier entier | 🚧 Partiel |
| **URL** | Saisie d'URL directe | ⚠️ Transcriber (YouTube), Describer, Enhancer seulement |
| **Batch file** | Fichier CSV/TXT/PDF/DOCX glissé dans la zone drag & drop — **détection automatique, pas de bouton séparé** | ✅ Toutes les apps avec batch |

### 8.2 Zone de drop standard

```html
<div id="dropZone" class="<app>-drop-zone mb-3 border border-secondary rounded p-4 text-center"
     style="cursor:pointer; border-style:dashed!important; transition: border-color .2s, background .2s;">
  <i class="fas fa-file-arrow-up fa-2x text-secondary mb-2"></i>
  <p class="mb-1 text-secondary">Glissez vos fichiers ici ou cliquez pour importer</p>
  <small class="text-muted"><!-- types acceptés --></small>
  <input type="file" id="fileInput" multiple accept="…" style="display:none">
</div>
```

### 8.3 Import depuis FileManager

Le FileManager expose `/filemanager/api/import/` et `/filemanager/api/mkdir/`.
Fonctionnalités disponibles :
- **Fichier unique** : clic droit → "Envoyer vers…" → submenu par app compatible
- **Sélection multiple** : sélectionner plusieurs fichiers (click + Ctrl/Shift) → clic droit → "Envoyer vers…"
- **Dossier entier** : clic droit sur un dossier → "Envoyer vers…" → envoie tous les fichiers compatibles
- **Nouveau dossier** : clic droit → "Nouveau dossier" → crée un sous-dossier dans le dossier courant

Chaque app écoute l'événement `wama:fileimported` sur `document` pour mettre à jour sa file :
```javascript
document.addEventListener('wama:fileimported', e => {
    const result = e.detail;
    if (result && result.app === 'myapp' && result.id) {
        fetch(urlFor('progress', result.id))
            .then(r => r.json())
            .then(item => upsertCard(item));
    }
});
```

> **État actuel :** ✅ Implémenté pour fichier unique. 🚧 Multi-select et import dossier en cours.

### 8.4 Import dossier récursif

```html
<!-- Bouton additionnel dans la drop zone -->
<input type="file" id="folderInput" webkitdirectory style="display:none">
<button onclick="document.getElementById('folderInput').click()"
        class="btn btn-sm btn-outline-secondary mt-2">
  <i class="fas fa-folder-open me-1"></i> Importer un dossier
</button>
```

> **État actuel :** 📋 Non implémenté — à ajouter dans toutes les apps.

### 8.5 Auto-dépliement FileManager selon l'app active

Le FileManager se déplie automatiquement sur le dossier de l'app courante à l'ouverture de la sidebar.
La logique est dans `autoExpandCurrentAppFolder()` de `filemanager.js`.

**Règle obligatoire pour chaque nouvelle app :**
Ajouter une entrée dans `appFolderMap` de `filemanager.js` **et** `staticfiles/filemanager/js/filemanager.js` :

```javascript
// Dans autoExpandCurrentAppFolder() → appFolderMap
'monapp': ['monapp', 'monapp_input', 'monapp_output'],
```

Les IDs de nœuds correspondent aux `id` déclarés dans `views.py` (`get_tree_data()`).

> **État actuel :** ✅ Implémenté pour toutes les apps sauf Avatarizer (pas de sidebar standard).

---

## 9. Système de Batch

### 9.1 Principe

**Toutes les apps doivent utiliser le système batch.** Même un upload individuel
est un batch de 1 (pattern du Synthesizer). Cela garantit :
- Uniformité de l'interface
- Duplication de batch possible partout
- Suivi global de la progression

### 9.2 Modèle batch standard (dans `wama/common/`)

> **État actuel :** 🚧 Chaque app a son propre modèle batch. À terme, extraire un
> `BaseBatch` abstrait dans `wama/common/models.py`.

Pattern recommandé (voir Synthesizer comme référence) :
- `MyBatch` (total, batch_file, created_at)
- `MyItem.batch = FK(MyBatch, null=True)`
- `_wrap_in_batch(item)` → crée un batch-de-1 si item isolé
- `_auto_wrap_orphans(user)` → migration lazy des anciens items

### 9.3 Utilitaires de duplication batch (dans `wama/common/`)

```python
# wama/common/utils/batch_utils.py
def duplicate_batch(batch, item_class, item_reset_fields, item_clear_fields):
    """Duplique un batch et tous ses items. Partage les fichiers source."""
    new_batch = MyBatch.objects.create(user=batch.user, total=batch.total)
    for item in batch.items.all():
        duplicate_instance(
            item,
            reset_fields={'batch': new_batch, **item_reset_fields},
            clear_fields=item_clear_fields,
        )
    return new_batch
```

> **État actuel :** 🚧 `batch_utils.py` contient `duplicate_synthesizer_batch()`
> (spécifique Synthesizer). Généraliser pour toutes les apps.

### 9.4 Convention des fichiers batch

**Règles universelles :**
```
# Séparateur : | (pipe)
# Commentaires : lignes commençant par #
# Lignes vides : ignorées
# Encodage : UTF-8
# Formats supportés : .txt .md .csv .pdf .docx
```

**Deux types de batch :**

**Type A — Media list** (apps traitant des fichiers/URLs existants) :
```
chemin/vers/fichier.mp4
https://example.com/video.mp4
/chemin/absolu/doc.pdf | backend=olmocr | language=fr
```

**Type B — Content generation** (apps créant de nouveaux fichiers) :
```
# nom_fichier | contenu_principal | param3 | param4 | …
bonjour_monde      | Bonjour le monde !
presentation.wav   | Bienvenue dans WAMA | voix_claire | 1.2 | fr
```

**Schémas par app :**

| App | Type | Col 1 (req) | Col 2 (req) | Col 3 | Col 4 | Col 5 |
|-----|------|------------|------------|-------|-------|-------|
| Synthesizer | B | `output_filename` | `text` | `voice` | `speed` (0.5–2.0) | `language` |
| Composer | B | `output_filename` | `prompt` | `model` | `duration` (1–30s) | — |
| Imager | B | `output_filename` | `prompt` | `model` | `resolution` | `steps` |
| Transcriber | A | `source` (path/url) | `backend` | `language` | `format` | — |
| Describer | A | `source` (path/url) | `model` | `language` | `format` | — |
| Enhancer | A | `source` (path/url) | `backend` | `mode` | — | — |
| Anonymizer | A | `source` (path/url) | `model` | `classes` | — | — |
| Reader | A | `source` (path/url) | `backend` | `mode` | `output_format` | `language` |

### 9.5 Parseur générique (`parse_pipe_batch`)

`wama/common/utils/batch_parsers.py` fournit désormais `parse_pipe_batch(file_path, schema)`.
Chaque app déclare son schéma de colonnes — plus besoin de dupliquer la logique de parsing.

```python
# Exemple : schéma Synthesizer
SYNTH_SCHEMA = [
    {'name': 'output_filename', 'required': True,  'type': 'str',   'add_ext': '.wav'},
    {'name': 'text',            'required': True,  'type': 'str'},
    {'name': 'voice',           'required': False, 'type': 'str',   'default': None},
    {'name': 'speed',           'required': False, 'type': 'float', 'default': 1.0, 'min': 0.5, 'max': 2.0},
    {'name': 'language',        'required': False, 'type': 'str',   'default': ''},
]

tasks, warnings = parse_pipe_batch(file_path, SYNTH_SCHEMA)
```

**Descripteur de colonne :**
```python
{
    'name':    str,          # Clé dans le dict résultat
    'required': bool,        # Ligne ignorée si vide
    'type':    'str'|'float'|'int',
    'default': any,          # Valeur si colonne absente ou vide
    'min':     num,          # Clamp min (types numériques)
    'max':     num,          # Clamp max (types numériques)
    'choices': list|None,    # Valeurs autorisées
    'add_ext': str|None,     # Extension auto si absente (ex: '.wav')
}
```

> **État actuel :** ✅ `parse_pipe_batch()` disponible dans `batch_parsers.py`.
> Migration progressive des parseurs app-spécifiques vers ce schéma.

### 9.6 Batch transparent — Détection automatique à l'import

**Règle :** Pas de bouton "Importer batch" séparé. Le fichier batch est glissé dans la zone
drag & drop normale (ou importé depuis le FileManager). La détection est automatique.

**Comportement :**
- Fichier média unique → batch-de-1, même comportement
- Fichier liste (`.txt`, `.csv`, `.pdf`, `.docx`) → parsing → N items → affichage de la barre de détection
- Sélection multiple depuis FileManager → N items → même barre de détection

**Barre de détection standard (`#batchDetectBar`)** :

```html
<div id="batchDetectBar" style="display:none; background:#1a1520; border:1px solid #0dcaf0;
     border-radius:0.375rem; padding:0.5rem 0.75rem; margin-bottom:0.5rem;">
    <div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-1">
        <span class="small text-light">
            <i class="fas fa-list text-info me-1"></i>
            <span id="batchDetectedCount">0</span> fichier(s) détecté(s)
        </span>
        <div class="d-flex gap-1">
            <button class="btn btn-sm btn-outline-info py-0 px-2" id="batchPreviewBtn">
                <i class="fas fa-eye"></i> Voir
            </button>
            <button class="btn btn-sm btn-outline-danger py-0 px-1" id="batchCancelBar" title="Annuler">
                <i class="fas fa-times"></i>
            </button>
        </div>
    </div>
    <!-- Prévisualisation optionnelle -->
    <div id="batchDetectPreview" style="display:none; max-height:120px; overflow-y:auto;">
        <table class="table table-sm table-dark mb-0" style="font-size:0.78rem;">
            <thead><tr><th>Source</th><th>Paramètres</th></tr></thead>
            <tbody id="batchDetectTable"></tbody>
        </table>
    </div>
    <div class="d-flex gap-2 mt-2">
        <button class="btn btn-success btn-sm flex-grow-1" id="batchCreateAndStartBtn">
            <i class="fas fa-play"></i> Démarrer (<span id="batchCreateCount">0</span>)
        </button>
        <button class="btn btn-outline-primary btn-sm" id="batchCreateOnlyBtn">
            <i class="fas fa-plus"></i> Ajouter
        </button>
    </div>
</div>
```

**Sémantique des boutons :**
- **"Ajouter"** (`btn-outline-primary`) — ajoute tous les items à la file en statut PENDING, sans démarrer le traitement
- **"Démarrer (N)"** (`btn-success`) — ajoute tous les items ET lance immédiatement la génération de chacun

**Comportement uniforme** : qu'il y ait 1 fichier ou 100, le même chemin de code est emprunté.
Un upload individuel crée un batch-de-1 (pattern du Synthesizer — `_wrap_in_batch()`).

### 9.7 Affichage de la file — ordre et état des batch groups

**Règle d'ordre :**
Les multi-batches (total > 1) s'affichent **toujours avant** les batches individuels (total == 1).
Tri côté serveur dans `IndexView.get()` :

```python
batches_list.sort(key=lambda b: 0 if b['obj'].total > 1 else 1)
```

**Règle de repliage :**
- Les multi-batches sont **repliés par défaut** au premier affichage.
- L'état replié/déplié est **persisté par batch ID dans localStorage** (`wama_batch_{app}_{id}`).
- À chaque visite, l'utilisateur retrouve l'état qu'il a laissé.

**Template — attributs obligatoires sur le bloc collapsible :**

```html
<!-- Toggle : aria-expanded="false" par défaut (replié) -->
<div data-bs-toggle="collapse"
     data-bs-target="#batchItems{{ batch_info.obj.id }}"
     aria-expanded="false">
    ...
    <i class="fas fa-chevron-down text-muted"></i>  {# tourne via CSS #}
</div>

<!-- Contenu : "collapse" sans "show" + data-wama-batch-key -->
<div class="collapse"
     id="batchItems{{ batch_info.obj.id }}"
     data-wama-batch-key="{{ app_name }}_{{ batch_info.obj.id }}">
    ...
</div>
```

**JS — à appeler dans `init()` ou `DOMContentLoaded` de chaque app :**

```javascript
function initBatchCollapse() {
    document.querySelectorAll('.collapse[data-wama-batch-key]').forEach(function (collapseEl) {
        const key = 'wama_batch_' + collapseEl.dataset.wamaBatchKey;
        const stored = localStorage.getItem(key);

        if (stored === 'open') {
            collapseEl.classList.add('show');
            const toggleEl = document.querySelector('[data-bs-target="#' + collapseEl.id + '"]');
            if (toggleEl) toggleEl.setAttribute('aria-expanded', 'true');
        }

        collapseEl.addEventListener('show.bs.collapse', function () {
            localStorage.setItem(key, 'open');
        });
        collapseEl.addEventListener('hide.bs.collapse', function () {
            localStorage.setItem(key, 'closed');
        });
    });
}
```

**CSS — dans `app_modern.css` (déjà présent) :**

```css
.batch-group-header .fa-chevron-down { transition: transform 0.2s ease; }
.batch-group-header [aria-expanded="true"] .fa-chevron-down { transform: rotate(180deg); }
```

**Apps conformes :** Synthesizer ✅ | Reader ✅
**Apps à porter :** Transcriber | Describer | Enhancer | Composer | Imager | Anonymizer

---

## 10. Paramètres — Cohérence entre Volet, Item et Batch

### 10.1 Règle

Les paramètres de traitement doivent être configurables à **trois niveaux** :

| Niveau | Où | Persistance |
|--------|----|-------------|
| **Volet droit** (défauts) | `app_right_panel_settings` | `localStorage` |
| **Item individuel** (override) | Modale `data-action="settings"` | BDD (champs du modèle) |
| **Batch** (override global) | Modale avant création du batch | BDD (`MyBatch`) |

**Priorité :** Paramètres item > Paramètres batch > Valeurs du volet droit

### 10.2 Persistance localStorage (volet droit)

```javascript
// Dans init() du JS de l'app
['<app>BackendSelect', '<app>LanguageInput', '...'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const key = `<app>_setting_${id}`;
    const saved = localStorage.getItem(key);
    if (saved) el.value = saved;
    el.addEventListener('change', () => localStorage.setItem(key, el.value));
});
```

### 10.3 Langue préférée globale

La langue par défaut de l'utilisateur est disponible via le context processor :
```python
# Dans tous les templates
{{ preferred_language }}  # ex : 'fr', 'en', 'de'
```

Usage dans les templates :
```html
{% for val, label in language_choices %}
<option value="{{ val }}" {% if val == preferred_language %}selected{% endif %}>
    {{ label }}
</option>
{% endfor %}
```

---

## 11. Stockage des Médias

### 11.1 Chemins standard

Utiliser **toujours** les helpers de `wama/common/utils/media_paths.py` :

```python
from wama.common.utils.media_paths import (
    upload_to_user_input,
    upload_to_user_output,
    UploadToUserPath,
)

class MyItem(models.Model):
    input_file  = models.FileField(upload_to=upload_to_user_input('<app>'))
    output_file = models.FileField(upload_to=upload_to_user_output('<app>'))
    # Sous-dossier personnalisé :
    ref_file    = models.FileField(upload_to=UploadToUserPath('<app>', 'references'))
```

**Résultat :**
```
media/
└── <user_id>/
    └── <app>/
        ├── input/      ← fichiers sources uploadés
        ├── output/     ← résultats générés
        └── <custom>/   ← sous-dossiers spécifiques à l'app
```

### 11.2 Note sur la Médiathèque

> ⚠️ La mise en place de la Médiathèque (`wama/media_library/`) pourrait modifier
> la structure de stockage. **Ne pas rigidifier les chemins** dans la logique métier.
> Passer toujours par `upload_to_user_input()` etc. pour faciliter la migration future.

---

## 12. Utilitaires Communs (`wama/common/`)

### 12.1 Utilitaires de file d'attente — règles d'usage

```python
# TOUJOURS utiliser ces fonctions — ne pas dupliquer la logique
from wama.common.utils.queue_duplication import safe_delete_file, duplicate_instance

# Suppression d'un item
def delete(request, pk):
    item = get_object_or_404(MyItem, pk=pk, user=user)
    safe_delete_file(item, 'input_file')   # Ne supprime que si non partagé
    safe_delete_file(item, 'output_file')  # Toujours supprimer les outputs
    cache.delete(f'<app>_progress_{pk}')
    item.delete()

# Duplication d'un item
def duplicate(request, pk):
    item = get_object_or_404(MyItem, pk=pk, user=user)
    new_item = duplicate_instance(
        item,
        reset_fields={'status': 'PENDING', 'progress': 0, 'task_id': ''},
        clear_fields=['output_file', 'result_text', 'error_message'],
    )
    return JsonResponse(_item_to_dict(new_item))
```

### 12.2 Index des utilitaires disponibles

| Fichier | Fonctions clés | Usage |
|---------|---------------|-------|
| `queue_duplication.py` | `safe_delete_file()`, `duplicate_instance()` | Delete / Duplicate items |
| `batch_parsers.py` | `extract_batch_file_text()`, `parse_media_list_batch()` | Lecture fichiers batch |
| `batch_utils.py` | `duplicate_synthesizer_batch()` → généraliser | Duplication de batch |
| `media_paths.py` | `upload_to_user_input()`, `upload_to_user_output()`, `UploadToUserPath` | Chemins fichiers |
| `console_utils.py` | `push_console_line()`, `get_console_lines()` | Logs console UI |
| `llm_utils.py` | `get_describer_model()` | Sélection modèle LLM |
| `format_policy.py` | `validate_format()` | Validation formats médias |
| `video_utils.py` | Utilitaires vidéo | Traitement vidéo |
| `preview_utils.py` | Générateurs de miniatures | Prévisualisation |

### 12.3 Règle : si c'est commun à ≥2 apps, ça va dans `common/`

Avant d'ajouter une fonction dans `<app>/utils/`, vérifier si elle peut être
utile à d'autres apps. Si oui → `wama/common/utils/<fichier>.py`.

### 12.4 Console Logging — Conventions obligatoires

La console (onglet "Console" de chaque app) est alimentée par **`push_console_line()`**
depuis `wama/common/utils/console_utils.py`. Le widget du base template appelle
**l'endpoint centralisé `common:console`** avec `?app=<nom>` — il ne passe **pas**
par l'endpoint `<app>:console` de l'app.

**Conséquence critique :** si `app=` est absent ou incorrect dans `push_console_line()`,
les messages n'apparaissent pas dans la console de l'app (filtre par app côté serveur).

#### Pattern standard dans `tasks.py` / `workers.py`

```python
# ── Import : EN HAUT DU FICHIER (jamais lazy dans la fonction) ──────────────
from wama.common.utils.console_utils import push_console_line

# ── Wrapper _console : copier ce pattern EXACT ──────────────────────────────
def _console(user_id: int, message: str, level: str = None) -> None:
    try:
        if level is None:
            low = message.lower()
            if any(w in low for w in ('erreur', 'error', 'failed', 'échec')):
                level = 'error'
            elif any(w in low for w in ('warning', 'attention', 'warn')):
                level = 'warning'
            elif 'debug' in low:
                level = 'debug'
            else:
                level = 'info'
        push_console_line(user_id, message, level=level, app='<nom_app>')
    except Exception:
        pass
```

Remplacer `'<nom_app>'` par le nom exact de l'app : `'reader'`, `'transcriber'`,
`'synthesizer'`, `'imager'`, etc.

#### Appels directs (hors wrapper `_console`)

Si une fonction appelle `push_console_line()` directement (sans passer par `_console`),
**toujours** préciser `app=` et `level=` :

```python
# ✅ Correct
push_console_line(user_id, "Enrichissement terminé ✓", app='transcriber')
push_console_line(user_id, f"Erreur : {exc}", app='transcriber', level='error')

# ❌ Incorrect — tombe dans app='system', invisible dans la console de l'app
push_console_line(user_id, "Enrichissement terminé ✓")
```

#### Template — bloc `console_app_name`

Chaque app **doit** déclarer le bloc `console_app_name` dans son template
(généralement dans `<app>/base.html` ou `<app>/index.html`) :

```html
{% block console_app_name %}<nom_app>{% endblock %}
```

Ce bloc est lu par le JS du base template via `data-app-name`, puis transmis
comme `?app=<nom_app>` à l'endpoint `{% url 'common:console' %}`.

#### Niveaux disponibles

| Niveau | Usage |
|--------|-------|
| `'info'` | Messages normaux (démarrage, progression, succès) — visible par tous |
| `'warning'` | Avertissements non bloquants |
| `'error'` | Erreurs et échecs |
| `'debug'` | Détails techniques — visible uniquement par les rôles dev/admin |

#### Conformité par app

| App | Import top-level | `app=` passé | Level auto | Conforme |
|-----|-----------------|-------------|-----------|---------|
| Anonymizer | ✅ | ✅ | ✅ | ✅ |
| Avatarizer | ✅ | ✅ | ✅ | ✅ |
| Composer | ✅ | ✅ | ✅ | ✅ |
| Describer | ✅ | ✅ | ✅ | ✅ |
| Enhancer | ✅ | ✅ | ✅ | ✅ |
| Imager | ✅ | ✅ | ✅ | ✅ |
| Reader | ✅ | ✅ | ✅ | ✅ |
| Synthesizer | ✅ | ✅ | ✅ | ✅ |
| Transcriber | ✅ | ✅ | ✅ | ✅ |

---

## 13. Intégration RAG (Planifié)

> **État :** 📋 Non implémenté — architecture à définir.

**Vision :** Chaque application pourra injecter le contexte du RAG utilisateur dans
ses prompts modèle, pour personnaliser les résultats (vocabulaire métier, préférences,
documents de référence).

**Interface prévue :**

```python
# wama/common/utils/rag_utils.py (à créer)
def get_user_context(user, topic: str = None, max_tokens: int = 500) -> str:
    """Retourne du contexte pertinent depuis le RAG de l'utilisateur."""
    ...
```

**Usage dans une tâche Celery :**

```python
from wama.common.utils.rag_utils import get_user_context

context = get_user_context(item.user, topic='transcription')
prompt = f"Context utilisateur : {context}\n\nDocument : {text}"
```

---

## 14. Modèles AI — Voir CLAUDE.md

Les règles d'intégration des modèles HuggingFace sont documentées dans `CLAUDE.md`
sous la section **"RÈGLE OBLIGATOIRE : AJOUT D'UN NOUVEAU MODÈLE AI"**.

**Rappel mnémotechnique :**
> `settings.py → model_config.py → os.environ['HF_HUB_CACHE'] → from transformers import …`

---

## 15. État de Conformité par Application

> Mise à jour : 2026-03-21

### 15.1 Table de conformité

| Fonctionnalité | Anony. | Describer | Enhancer | Imager | Synthés. | Transcr. | Composer | Reader | Avatarizer |
|---------------|--------|-----------|----------|--------|----------|----------|----------|--------|------------|
| Tabs Queue/Console/About/Help | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Card format standard | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ |
| Bouton Paramètres (pos.1) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Bouton Start/Restart (pos.2) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Bouton Télécharger (pos.3) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Téléchargement multi-format (§6.3) | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ |
| Bouton Dupliquer (pos.4) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Bouton Supprimer (pos.5) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Barre progression % | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Message d'étape | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ⚠️ |
| **ETA individuel** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **ETA batch** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | N/A |
| **ETA queue global** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | N/A |
| Aperçu résultat (card) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Start All | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Clear All | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Download All | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Drag & drop zone** | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ |
| **Import dossier récursif** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Import FileManager** | ❌ | ⚠️ | ⚠️ | ❌ | ⚠️ | ⚠️ | ❌ | ❌ | ❌ |
| **Système Batch** | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| **Duplication Batch** | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Chemins media standard | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Model registry | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **RAG injection** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Bouton Réinitialiser** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ |
| **Barre détection batch** | ✅ | ✅ | ✅ | ✅ | ✅ | N/A | N/A | ✅ | N/A |
| **Header menu** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Home page card** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **API tool_api.py** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ❌ |

### 15.2 Priorités de mise en conformité

**Priorité 1 — Blocages fonctionnels (boutons manquants)** ✅ DONE (Vague 1)
- ~~Anonymizer : ajouter bouton Dupliquer~~ — handler JS ajouté dans `update.js`
- ~~Composer : ajouter bouton Dupliquer + Download All~~ — vues + URLs + templates + JS

**Priorité 2 — UX manquante (drag & drop)**
- Anonymizer : ajouter zone drag & drop
- Imager : ajouter zone drag & drop (pour image de référence)
- Composer : ajouter zone drag & drop (pour fichier batch)

**Priorité 3 — Feature transversale (ETA)**
- Toutes les apps : implémenter calcul ETA dans les tâches Celery + affichage JS

**Priorité 4 — Uniformisation batch**
- Transcriber, Enhancer, Anonymizer, Reader : ajouter système batch
- Extraire `BaseBatch` + `duplicate_batch()` dans `wama/common/`

**Priorité 5 — Import avancé**
- Toutes les apps : import dossier récursif
- Toutes les apps : intégration FileManager complète

**Priorité 6 — RAG**
- Après implémentation du RAG utilisateur : injection dans toutes les apps

---

## 16. Menu d'applications — Header et Page d'Accueil

### 16.1 Règle d'ordre

Toutes les applications génériques WAMA doivent apparaître :
1. Dans le menu déroulant **Applications** du header (`wama/templates/includes/header.html`)
2. Dans la section **WAMA App** de la page d'accueil (`wama/templates/home.html`)

**Ordre alphabétique strict** dans les deux emplacements.

Ordre actuel : Anonymizer → Avatarizer → Composer → Describer → Enhancer → Imager → **Reader** → Synthesizer → Transcriber

### 16.2 Structure d'un item header

```html
<li>
    <a class="dropdown-item d-flex align-items-center {% if '<app>' in request.path %}active{% endif %}"
       href="{% url '<app>:index' %}">
        <i class="fas fa-<icon> text-<color> me-2"></i> <NomApp>
    </a>
</li>
```

### 16.3 Structure d'une card home.html

```html
<!-- NomApp -->
<div class="col-md-6 col-lg-4">
  <div class="card h-100" style="background: #212529; border: 1px solid #495057;">
    <div class="card-body d-flex flex-column">
      <h5 class="card-title text-light">
        <i class="fas fa-<icon> text-<color>"></i> NomApp
      </h5>
      <p class="card-text text-light flex-grow-1">
        Description courte en anglais de ce que fait l'application.
      </p>
      <a href="{% url '<app>:index' %}" class="btn btn-<color> mt-auto">
        <i class="fas fa-arrow-right"></i> Open
      </a>
    </div>
  </div>
</div>
```

### 16.4 Applications WAMA Lab

Les applications expérimentales (`wama_lab/`) sont dans une section séparée **WAMA Lab**
dans home.html et dans un sous-groupe séparé dans le header (après un `<hr>`).
Elles suivent les mêmes règles d'ordre alphabétique dans leur groupe.

---

## 17. API Tool — Accessibilité depuis l'AI Assistant

### 17.1 Principe

Chaque application générique WAMA doit être **contrôlable depuis l'AI assistant** (wama-dev-ai ou Claude)
via des fonctions Python dans `wama/tool_api.py`, exposées en HTTP via `wama/urls.py`.

### 17.2 Fonctions minimum par application

| Fonction | Signature | Description |
|----------|-----------|-------------|
| `add_to_<app>` | `(user, file_path, **params) → dict` | Copie un fichier dans la file et crée l'entrée DB |
| `start_<app>` | `(user, item_id=None) → dict` | Lance la tâche Celery (1 item ou tous les PENDING) |
| `get_<app>_status` | `(user) → dict` | Retourne l'état des 10 derniers jobs |

**Exceptions acceptées :**
- Apps de **génération de contenu** (Imager, Composer, Synthesizer) : remplacent `add_to_<app>` par
  une fonction qui crée ET enregistre le contenu à générer (prompt/texte). Le nom peut différer
  (ex: `create_image`, `compose_music`, `synthesize_text`).
- Composer : `compose_music` crée + démarre en une seule fois — acceptable pour la génération rapide,
  mais idéalement à séparer en `add_to_composer` + `start_composer` (marqué ⚠️).

### 17.3 Contrat des retours

**`add_to_<app>`** → `{"<app>_id": int, "filename": str, ..., "status": "pending"}` ou `{"error": str}`

**`start_<app>`** → `{"task_id": str, "status": "started", "<app>_id": int}` (1 item)
                  ou `{"status": "started", "count": int, "ids": [int, ...]}` (tous)
                  ou `{"error": str}`

**`get_<app>_status`** → `{"jobs": [{"id", "filename", "status", "progress", "result_preview", ...}]}`
                        ou `{"error": str}`

### 17.4 URLs HTTP standard

```python
path('api/tools/<app>/add/',    tool_views.add_to_<app>_view,        name='tool_<app>_add'),
path('api/tools/<app>/start/',  tool_views.start_<app>_view,         name='tool_<app>_start'),
path('api/tools/<app>/status/', tool_views.get_<app>_status_view,    name='tool_<app>_status'),
```

### 17.5 Enregistrement dans TOOL_REGISTRY et TOOL_DESCRIPTIONS

Toute nouvelle fonction doit être ajoutée dans `TOOL_REGISTRY` et `TOOL_DESCRIPTIONS`
dans `tool_api.py`, ainsi que dans `TOOL_ICONS` dans `wama/templates/home.html`.

### 17.6 État de conformité API

| App | `add_to_*` | `start_*` | `get_*_status` | HTTP views | TOOL_REGISTRY |
|-----|-----------|----------|----------------|------------|---------------|
| Anonymizer | ✅ | ✅ | ✅ | ✅ | ✅ |
| Composer | ⚠️ compose_music | ⚠️ (intégré) | ✅ | — | ✅ |
| Describer | ✅ | ✅ | ✅ | — | ✅ |
| Enhancer | ✅ (img+audio) | ✅ | ✅ | — | ✅ |
| Imager | ✅ create_image | ✅ | ✅ | — | ✅ |
| Reader | ✅ | ✅ | ✅ | ✅ | ✅ |
| Synthesizer | ✅ synthesize_text | ✅ | ✅ | — | ✅ |
| Transcriber | ✅ | ✅ | ✅ | — | ✅ |

---

## 18. Contraste et Lisibilité du Texte (Thème Sombre)

### 18.1 Problème

Bootstrap 5 en thème sombre produit plusieurs classes qui **rendent le texte illisible** :
- `.text-muted` → gris trop foncé sur fond `#212529`
- `.text-white-50` → 50% d'opacité, insuffisant
- `.small` → hérite de la couleur parent, souvent grisée
- Les `<form-label>` et `<small class="form-text">` ont des couleurs insuffisantes par défaut

### 18.2 Solution globale

Le fichier **`staticfiles/common/css/app_modern.css`** (section `=== TEXT VISIBILITY ON DARK BACKGROUND ===`) contient les corrections globales :

```css
/* Toujours lisible sur fond sombre */
.text-muted           { color: #9ca3af !important; }  /* gris moyen, visible */
.text-white-50        { color: rgba(255, 255, 255, 0.7) !important; }  /* 70% au lieu de 50% */
.small                { color: #d1d5db !important; }
.form-label           { color: #e5e7eb !important; }
small.form-text       { color: #9ca3af !important; }
```

Ces règles s'appliquent automatiquement à toutes les templates via `base.html`.

### 18.3 Règles à respecter dans les templates

| Contexte | ✅ Utiliser | ❌ Éviter |
|----------|-----------|---------|
| Texte principal | `text-light` ou `text-white` | `text-muted` seul (lisible grâce au CSS global, mais peu contrasté) |
| Labels de formulaires | `fw-bold text-light` | `text-secondary` |
| Texte secondaire (méta, hints) | `text-white-50` (→ 70% via CSS) ou `text-muted` (→ #9ca3af) | couleur inline `color:#6c757d` |
| Icônes colorées | Classes Bootstrap `text-success`, `text-info`… | `opacity-50` sur icônes d'info |
| Badges | `bg-secondary` avec texte blanc | badge sans texte explicite |
| Code inline | `<code>` dans `bg-dark` → visible par défaut | `<pre>` sans `bg-dark` |

### 18.4 Ne pas reproduire ces antipatterns

```html
<!-- ❌ text-muted dans un contexte sombre sans surcharge CSS -->
<small class="text-muted" style="color:#6c757d">Texte invisible</small>

<!-- ❌ opacité partielle sur texte informatif -->
<span style="opacity:0.4">Aide contextuelle</span>

<!-- ❌ text-secondary sur fond sombre (trop peu contrasté) -->
<p class="text-secondary">Description…</p>

<!-- ✅ Correct -->
<small class="text-muted">Texte (→ #9ca3af via app_modern.css)</small>
<span class="text-white-50">Métadonnée (→ 70% via app_modern.css)</span>
<p class="text-light">Contenu principal</p>
```

### 18.5 Chemin du fichier CSS à modifier

Si un composant spécifique a un problème de contraste non résolu par les règles globales,
ajouter une règle ciblée dans `staticfiles/common/css/app_modern.css` (et la source originale
dans `wama/common/static/common/css/app_modern.css` si elle existe).

---

## §19 — Volet droit : zone d'import + paramètres (Option 2)

### Principe

Le volet droit du panneau `base.html` contient trois sections :
`Preview (aperçu)` | `Settings (paramètres)` | `Actions (boutons globaux)`

**Pour les apps avec file d'attente**, la section Aperçu est inutile (l'aperçu est intégré dans chaque card). Elle doit être **masquée** et remplacée par une **zone de dépôt** en tête de la section Paramètres.

Résultat : le volet droit devient **Import + Paramètres + Actions**, toujours visible, sans scroll de la file d'attente.

### Règles

| Règle | Détail |
|---|---|
| Masquer `#preview-section` | `#preview-section { display: none !important; }` dans le block `extra_css` de l'app |
| Zone de dépôt en tête | Premier élément dans `app_right_panel_settings`, avant les selects |
| Animation : `transform: scale()` | **Jamais** `border-width` ou `padding` — évite le reflow et le scrollbar horizontal |
| Class CSS `dragover` | Gérer via `classList.add/remove('dragover')` dans dragover/dragleave/drop |
| Contenu principal = file uniquement | Plus de drop zone dans le `queue_content` — juste `#queueContainer` |
| `overflow-x: hidden` | Sur le container principal pour prévenir tout débordement |

### HTML du drop zone (volet droit)

```html
{% block app_right_panel_settings %}
<!-- Zone d'import -->
<div id="dropZone" class="reader-drop-zone mb-3">
    <i class="fas fa-file-arrow-up fa-lg text-secondary mb-1"></i>
    <p class="mb-0 small text-secondary">Glissez ici ou cliquez</p>
    <small class="text-muted">PDF · JPG · PNG…</small>
    <input type="file" id="fileInput" multiple accept="..." style="display:none">
</div>
<hr class="border-secondary my-2">
<!-- Paramètres habituels -->
...
{% endblock %}
```

### CSS du drop zone

```css
.reader-drop-zone {                          /* ou <app>-drop-zone */
    border: 2px dashed #495057;
    border-radius: 8px;
    padding: 1rem;
    text-align: center;
    cursor: pointer;
    transition: border-color .2s, background .2s, transform .15s;
    background: rgba(255,255,255,.02);
}
.reader-drop-zone.dragover {
    border-color: #0dcaf0;
    background: rgba(13,202,240,.06);
    transform: scale(1.02);          /* ← transform, pas border/padding */
}
```

### Import depuis le filemanager (menu contextuel)

Le filemanager dispose d'un menu contextuel "Envoyer vers…" (submenu jstree).
Après import réussi, `filemanager.js` dispatche :

```javascript
document.dispatchEvent(new CustomEvent('wama:fileimported', { detail: result }));
// result : { imported, app, id, filename, path }
```

Chaque app **doit écouter** cet événement sur `document` pour mettre à jour sa file sans rechargement :

```javascript
document.addEventListener('wama:fileimported', e => {
    const result = e.detail;
    if (result && result.app === 'reader' && result.id) {
        fetch(urlFor('progress', result.id))
            .then(r => r.json())
            .then(item => upsertCard(item));
    }
});
```

### Extensions acceptées par app (pour le submenu "Envoyer vers…")

| App | Extensions |
|---|---|
| reader | pdf, jpg, jpeg, png, tiff, tif, webp, bmp |
| anonymizer | mp4, webm, mkv, avi, mov, jpg, jpeg, png, webp, gif, bmp |
| transcriber | mp3, wav, flac, ogg, m4a, aac, opus, wma, mp4, webm, mkv, avi, mov |
| describer | jpg, jpeg, png, webp, gif, bmp, mp4, webm, mov, avi, mkv |
| enhancer | images + vidéos + audio |
| synthesizer | txt, csv |

### Conformité par app

| App | Drop zone volet droit | Menu "Envoyer vers…" | Event `wama:fileimported` |
|---|---|---|---|
| Reader | ✅ | ✅ | ✅ |
| Anonymizer | ❌ à faire | ✅ (existant) | ❌ à faire |
| Transcriber | ❌ à faire | ✅ (existant) | ❌ à faire |
| Describer | ❌ à faire | ✅ (existant) | ❌ à faire |
| Enhancer | ❌ à faire | ✅ (existant) | ❌ à faire |
| Synthesizer | ❌ à faire | ✅ (existant) | ❌ à faire |

---

## §20 — Modals Bootstrap : Placement DOM, Stacking Context et Z-Index

### 20.1 Problème — La modal grisée / inutilisable

Une modal Bootstrap apparaît **grisée, figée ou inatteignable** quand elle est rendue
à l'intérieur d'un élément qui crée un **stacking context** (contexte d'empilement CSS).
Dans ce cas, le backdrop `.modal-backdrop` (z-index 1040) et la boîte `.modal`
(z-index 1050) sont confinés dans ce contexte d'empilement et ne peuvent plus
se superposer au reste de la page.

### 20.2 Déclencheurs d'un stacking context

Un élément crée automatiquement un nouveau stacking context si l'une des propriétés
CSS suivantes lui est appliquée :

| Propriété CSS | Exemple |
|---------------|---------|
| `transform` ≠ `none` | `transform: scale(1.02)` sur hover d'une card |
| `filter` ≠ `none` | `filter: drop-shadow(…)` ou `filter: blur(…)` |
| `opacity` < `1` | `opacity: 0.95` |
| `will-change: transform\|opacity` | optimisation GPU mal placée |
| `isolation: isolate` | isolation explicite |
| `contain: paint\|layout\|strict\|content` | containment CSS |
| `position: fixed` ou `position: sticky` | (crée toujours un stacking context) |
| `mix-blend-mode` ≠ `normal` | |

**Symptôme diagnostique** :
```javascript
// Dans la console DevTools — renvoie body si OK, un div sinon ❌
document.querySelector('#monModal').offsetParent
// OU vérifier visuellement dans l'arbre DOM :
// la modal doit être enfant direct de <body>, pas imbriquée
```

### 20.3 Règle obligatoire — Placement dans le DOM

```
✅ OBLIGATOIRE : toutes les modals doivent être placées dans le bloc
   {% block extra_modals %} défini dans app_modern_base.html.
   Ce bloc est rendu juste avant </body>, garantissant qu'aucun ancêtre
   ne crée de stacking context parasite.
```

```html
{# Correctement placé — en dehors de tout contexte d'empilement #}
{% block extra_modals %}
<div class="modal fade" id="maModal" tabindex="-1" aria-hidden="true">
  …
</div>
{% endblock %}
```

```html
{# ❌ INTERDIT — modal imbriquée dans une card avec transform hover #}
<div class="card" style="transition: transform .2s">
  <div class="modal fade" id="maModal">…</div>   {# invisible derrière le backdrop #}
</div>
```

### 20.4 Z-Index de référence Bootstrap 5

| Composant | Z-Index | Fichier source |
|-----------|---------|----------------|
| `.modal-backdrop` | 1040 | Bootstrap vars |
| `.modal` | 1050 | Bootstrap vars |
| `.popover` | 1070 | Bootstrap vars |
| `.tooltip` | 1080 | Bootstrap vars |
| `.toast` (WAMA) | 9999 | `app_modern.css` |

Ne jamais attribuer `z-index` > 1040 à un élément de mise en page (header, sidebar,
volet droit) sauf cas justifié documenté, sous peine de masquer les modals.

### 20.5 Antipatterns courants et corrections

```css
/* ❌ Transform hover sur une card contenant une modal */
.synthesis-card:hover { transform: translateY(-2px); }  /* crée un stacking context */

/* ✅ Correction : déplacer la modal hors de la card + utiliser box-shadow à la place */
.synthesis-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.4); }
```

```html
<!-- ❌ Modal déclenchée depuis un bouton dans une card avec filter -->
<div style="filter: drop-shadow(0 2px 4px #000)">
  <button data-bs-toggle="modal" data-bs-target="#monModal">Ouvrir</button>
  <div class="modal" id="monModal">…</div>   {# piégée dans le stacking context du filter #}
</div>

<!-- ✅ Correction : modal déplacée dans {% block extra_modals %} -->
<div style="filter: drop-shadow(0 2px 4px #000)">
  <button data-bs-toggle="modal" data-bs-target="#monModal">Ouvrir</button>
  {# PAS de modal ici #}
</div>
{% block extra_modals %}
<div class="modal" id="monModal">…</div>   {# rendu avant </body>, stacking context racine #}
{% endblock %}
```

### 20.6 Vérification en revue de code (Annexe A §18)

Avant de fusionner une PR contenant une modal :
1. La modal est-elle dans `{% block extra_modals %}` ?
2. Aucun ancêtre dans le DOM n'a `transform`, `filter`, `opacity < 1`, `will-change`, `isolation` ?
3. Le `z-index` de l'élément déclencheur n'excède pas 1039 ?
4. Le test `document.querySelector('#monModal').offsetParent === document.body` passe ?

---

## §21 — Boutons d'action globaux : Standards de couleur et libellés

### 21.1 Boutons d'action globaux (panneau droit — `app_right_panel_actions`)

Ordre et style obligatoires :

| Position | Bouton | Style Bootstrap | id | Notes |
|----------|--------|-----------------|----|-------|
| 1 | **Démarrer** | `btn-success` | `startAllBtn` | Lance tous les items PENDING |
| 2 | **Télécharger tout** | `btn-info` | `downloadAllBtn` | Télécharge tous les résultats (ZIP) |
| 3 | **Tout effacer** | `btn-outline-danger` | `clearAllBtn` | Fond transparent, texte/bord rouge |

```html
{% block app_right_panel_actions %}
<div class="d-grid gap-2">
    <button class="btn btn-success btn-sm" id="startAllBtn">
        <i class="fas fa-play"></i> Démarrer
    </button>
    <button class="btn btn-info btn-sm" id="downloadAllBtn" disabled>
        <i class="fas fa-download"></i> Télécharger tout
    </button>
    <button class="btn btn-outline-danger btn-sm" id="clearAllBtn">
        <i class="fas fa-trash"></i> Tout effacer
    </button>
</div>
{% endblock %}
```

**Rationale des couleurs :**
- `btn-success` (vert plein) → action positive principale, visible, rassurant
- `btn-info` (cyan plein) → récupération passive d'un résultat, secondaire
- `btn-outline-danger` (rouge contour, fond transparent) → action destructive irréversible — le fond transparent signale visuellement que ce bouton est "plus dangereux" que les autres et mérite une attention particulière

### 21.2 Bouton Réinitialiser (bas de `app_right_panel_settings`)

Doit être le **dernier élément** dans `{% block app_right_panel_settings %}`, après un `<hr>` :

```html
<!-- Dernier élément dans app_right_panel_settings -->
<hr class="border-secondary my-2">
<button class="btn btn-outline-secondary btn-sm w-100" id="resetOptions">
    <i class="fas fa-undo"></i> Réinitialiser
</button>
```

**Style :** `btn-outline-secondary` (gris contour) — action non-destructive mais à utiliser avec intention. Le fond transparent ne charge pas visuellement le panneau.

**Comportement JS :**
```javascript
document.getElementById('resetOptions')?.addEventListener('click', () => {
    // 1. Remettre chaque champ à sa valeur par défaut
    document.getElementById('myModelSelect').value = 'default_model';
    document.getElementById('myLanguageSelect').value = 'fr';
    // … autres champs …
    // 2. Effacer le localStorage pour ces clés
    ['myapp_setting_myModelSelect', 'myapp_setting_myLanguageSelect'].forEach(
        k => localStorage.removeItem(k)
    );
});
```

### 21.3 Boutons d'action individuels (card item — §6.1)

Pas de changement par rapport à §6.1. Les boutons globaux ne remplacent pas les boutons de card.

### 21.4 Table de conformité — Boutons globaux

| App | Démarrer | Télécharger tout | Tout effacer | Bouton Réinitialiser | Barre détection batch |
|-----|----------|-----------------|-------------|----------------------|-----------------------|
| Synthesizer | ✅ btn-success | ✅ btn-info | ✅ btn-outline-danger | ✅ | ✅ |
| Describer | ✅ | ✅ | ✅ | ✅ | ✅ |
| Transcriber | ✅ | ✅ | ✅ | ✅ | ✅ |
| Enhancer | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reader | ✅ | ✅ | ✅ | ✅ | ✅ |
| Anonymizer | ✅ | ✅ | ✅ | ✅ | N/A |
| Imager | ✅ | ✅ | ✅ | ✅ | N/A (génération) |
| Composer | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Annexe A — Passage rapide en revue (wama-dev-ai)

Lors d'un audit d'une app, vérifier dans l'ordre :

```
1. urls.py       → présence des 15+ URL patterns standard ?
2. models.py     → champs status/task_id/progress/error_message présents ?
3. views.py      → select_for_update() dans start() ?
4. views.py      → safe_delete_file() dans delete() ?
5. views.py      → duplicate_instance() dans duplicate() ?
6. templates/    → _item_card.html existe ?
7. templates/    → index.html inclut _item_card.html ?
8. JS            → buildCard() synchronisé avec _item_card.html ?
9. JS            → settings persistés en localStorage ?
10. JS           → polling stopPolling() après DONE/ERROR ?
11. header.html  → app présente en ordre alphabétique ?
12. home.html    → card présente en ordre alphabétique ?
13. tool_api.py  → add_to_*  start_*  get_*_status présents ?
14. urls.py      → routes api/tools/<app>/ enregistrées ?
15. home.html    → TOOL_ICONS mis à jour ?
16. right panel  → #preview-section masqué + drop zone en tête des paramètres ?
17. JS           → event wama:fileimported écouté sur document ?
18. modals       → dans {% block extra_modals %}, aucun ancêtre avec transform/filter/opacity<1 ?
19. download     → multi-format via split button dropdown si ≥ 2 formats (§6.3) ?
20. global btns  → Démarrer (btn-success) | Télécharger tout (btn-info) | Tout effacer (btn-outline-danger) ?
21. reset btn    → btn-outline-secondary, id="resetOptions", dernier élément de app_right_panel_settings ?
22. batch bar    → "Ajouter" (btn-outline-primary) | "Démarrer (N)" (btn-success) — pas de btn-primary ?
```

## Annexe B — Commandes utiles

```bash
# Créer une migration pour une nouvelle app
python manage.py makemigrations <app>
python manage.py migrate <app>

# Copier les static files après modif JS/CSS
cp -r wama/<app>/static/<app>/ staticfiles/<app>/

# Vérifier les URLs d'une app
python manage.py show_urls | grep <app>

# Lancer les tâches Celery pour une app
celery -A wama worker -Q wama.<app>.tasks.* --loglevel=info
```
