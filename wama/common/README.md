# WAMA Common App

Application Django contenant les composants partagés entre toutes les applications WAMA.

## Structure

```
common/
├── static/common/
│   └── js/
│       └── console.js          # Console JavaScript générique
├── templates/common/
│   └── app_base.html           # Template de base pour toutes les apps
├── utils/
│   ├── __init__.py
│   └── console_utils.py        # Utilitaires pour la console (Redis/Cache/Celery logs)
├── migrations/
├── __init__.py
├── apps.py
└── README.md
```

## Composants

### 1. Template `app_base.html`

Template de base générique pour toutes les applications WAMA.

**Blocs disponibles:**
- `title` - Titre de la page
- `extra_scripts` - Scripts jQuery File Upload (optionnel)
- `app_scripts` - Scripts spécifiques à l'application
- `console_content_id` - ID du conteneur de console
- `console_hint_id` - ID du hint de la console
- `console_url` - URL de l'endpoint console
- `app_menu` - Menu de navigation de l'application
- `app_content` - Contenu principal de l'application

**Exemple d'utilisation dans une app:**

```django
{% extends 'common/app_base.html' %}
{% load static %}

{% block app_scripts %}
<script src="{% static 'myapp/js/main.js' %}"></script>
{% endblock %}

{% block console_content_id %}myapp-console-content{% endblock %}
{% block console_url %}{% url 'myapp:console' %}{% endblock %}

{% block app_menu %}
<a href="{% url 'myapp:index' %}">Index</a>
<a href="{% url 'myapp:about' %}">About</a>
{% endblock %}

{% block app_content %}
<!-- Votre contenu ici -->
{% endblock %}
```

### 2. JavaScript `console.js`

Console JavaScript générique qui:
- Détecte automatiquement tous les conteneurs avec `data-console-url`
- Rafraîchit les logs toutes les 4 secondes
- Échappe le HTML pour la sécurité
- Scroll automatique vers le bas

**Utilisation:**
Le script est automatiquement inclus via `app_base.html`. Il suffit d'avoir un élément avec l'attribut `data-console-url`.

### 3. Utils `console_utils.py`

Fonctions utilitaires pour gérer les logs de console:

**Fonctions:**
- `push_console_line(user_id, message)` - Ajoute une ligne au cache Redis
- `get_console_lines(user_id, limit=100)` - Récupère les logs utilisateur
- `get_celery_worker_logs(limit=100)` - Récupère les logs Celery depuis le fichier

**Exemple d'utilisation:**

```python
from wama.common.utils.console_utils import push_console_line, get_console_lines

# Dans un worker Celery
push_console_line(user.id, "Processing started...")

# Dans une vue
def console_content(request):
    user = request.user
    console_lines = get_console_lines(user.id, limit=100)
    return JsonResponse({'output': console_lines})
```

## Avantages

1. **DRY (Don't Repeat Yourself):** Un seul template et JS au lieu de 3+ copies identiques
2. **Maintenance facile:** Une modification affecte toutes les apps
3. **Cohérence:** Toutes les apps ont le même look & feel
4. **Extensibilité:** Facile d'ajouter de nouvelles apps WAMA
5. **Centralisation:** Tous les utilitaires communs au même endroit

## Migration depuis les apps

Les apps `anonymizer`, `synthesizer`, et `transcriber` utilisent maintenant ce template commun:

**Avant:**
- Chaque app avait son propre `base.html` (quasi-identique)
- Chaque app avait son propre `console.js` (identique sauf l'ID)
- `console_utils.py` était dans `anonymizer/utils/`

**Après:**
- Un seul `common/templates/common/app_base.html`
- Un seul `common/static/common/js/console.js`
- `console_utils.py` centralisé dans `common/utils/`
- Chaque app hérite et personnalise via les blocs Django
