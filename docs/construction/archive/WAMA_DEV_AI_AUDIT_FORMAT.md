# wama-dev-ai — Format des rapports d'audit

Les rapports sont écrits dans `wama-dev-ai/outputs/` au format JSON.
Ils sont relus par Claude (Anthropic) à chaque session de travail collaboratif.

## Nomenclature des fichiers

```
audit_YYYY-MM-DD.json         Audit général quotidien / à la demande
audit_ui_YYYY-MM-DD.json      Conformité UI (boutons duplication, etc.)
audit_models_YYYY-MM-DD.json  Conformité règles HuggingFace
model_watch_YYYY-MM-DD.json   Veille nouveaux modèles HF/Ollama
api_health_YYYY-MM-DD.json    Santé des endpoints WAMA (Phase 2)
```

## Structure JSON canonique

```json
{
  "wama_report": {
    "version": "1.0",
    "date": "2026-03-18",
    "agent": "wama-dev-ai",
    "audit_type": "CODE_QUALITY",
    "scope": ["wama/describer/", "wama/imager/"],
    "summary": "Résumé en 2-3 phrases.",

    "findings": [
      {
        "id": "F001",
        "severity": "HIGH",
        "category": "MODEL_RULE",
        "description": "HF_HUB_CACHE non défini avant import transformers",
        "file": "wama/describer/utils/image_describer.py",
        "line": 76,
        "evidence": "from transformers import BlipProcessor  # HF_HUB_CACHE not set"
      }
    ],

    "suggested_actions": [
      {
        "id": "A001",
        "finding_refs": ["F001"],
        "action": "Ajouter os.environ['HF_HUB_CACHE'] = cache_dir avant l'import transformers",
        "effort": "LOW",
        "status": "PENDING_HUMAN_VALIDATION"
      }
    ],

    "claude_review_notes": "Questions ou points spécifiques pour Claude."
  }
}
```

## Niveaux de sévérité

| Niveau | Signification |
|--------|---------------|
| HIGH   | Bug potentiel, violation règle obligatoire CLAUDE.md, sécurité |
| MEDIUM | Mauvaise pratique, dette technique significative |
| LOW    | Code style, amélioration mineure |
| INFO   | Observation neutre, veille |

## Catégories

| Catégorie   | Signification |
|-------------|---------------|
| SECURITY    | Faille de sécurité (injection, CSRF, auth) |
| PERF        | Performance (N+1 queries, mémoire GPU, etc.) |
| DRY         | Duplication de code |
| DEBT        | Dette technique |
| UI_MISSING  | Composant UI obligatoire manquant |
| MODEL_RULE  | Violation règle modèle HuggingFace (CLAUDE.md) |
| DEPENDENCY  | Dépendance manquante ou problématique |

## Statuts des actions

```
PENDING_HUMAN_VALIDATION  → par défaut (wama-dev-ai ne passe JAMAIS ce statut)
VALIDATED_BY_CLAUDE       → Claude a validé la proposition (human sets this)
APPLIED                   → Changement appliqué dans le code (human sets this)
REJECTED                  → Rejeté après analyse (human sets this)
DEFERRED                  → Reporté à une version ultérieure (human sets this)
```

## Niveaux de confiance (évolution dans le temps)

```
Phase 1 (actuelle) — Audit read-only
  wama-dev-ai : lecture codebase + écriture rapports
  Claude       : validation des rapports, décision d'action
  Human        : application des changements

Phase 2 — Tests API nocturnes
  wama-dev-ai : appels API WAMA en lecture (health checks, smoke tests)
  Claude       : analyse des résultats de tests

Phase 3 — Veille modèles
  wama-dev-ai : surveillance HuggingFace + Ollama, notifications admin

Phase 4 (futur) — MCP
  Sélection de modèles partagée entre WAMA et wama-dev-ai
  Model selection intelligente exposée via MCP
```
