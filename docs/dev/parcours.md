<!-- WAMA:GENERE(dev-parcours) — généré par « python manage.py doc_facts » depuis le plan de wama/common/docs_catalog.py ; ne pas éditer -->
# Parcours d'entrée

> Doc développeur **générée** : chaque section vient de la doc de construction (source citée en pied) ou des registres eux-mêmes. Pour la corriger, corriger la SOURCE — ce fichier est réécrit par `python manage.py doc_facts`.

## Lire, dans cet ordre

1. **[AGENTS — la doctrine](../../AGENTS.md)** — Source unique des règles de développement : philosophie, règles obligatoires, conventions, table des fichiers de référence. Lue par tout agent et par un humain.
2. **[Briques communes — carte](../../wama/common/README.md)** — Carte d'entrée du dossier des briques communes.
3. **[Carte des mécanismes](../construction/architecture/WAMA_MECANISMES.md)** — Index des briques transversales : où vit quoi, qui l'utilise. Sa table est générée depuis le registre des mécanismes.
4. **[Route d'auto-génération des apps](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)** — Facettes F1–F8, briques communes, chaîne dépôt → app, et ce qu'une génération ne doit plus redécouvrir. À lire avant de créer ou modifier une app.
5. **[Conventions d'app](../construction/architecture/WAMA_APP_CONVENTIONS.md)** — Conventions UI et architecture de toutes les apps, capacités d'app, checklist de création.
6. **[Manifestes — formalisme](../construction/architecture/WAMA_MANIFEST_SPEC.md)** — Le formalisme des sept kinds de manifestes : app, library, model, function, pipeline, project, dataset.
7. **[Vérification](../construction/architecture/WAMA_VERIFICATION.md)** — Comment on sait que ça marche : grille d'adoption contre grille fonctionnelle, catalogue des gestes, couverture.
8. **[Couche LLM](../construction/ia/WAMA_LLM.md)** — Prompts, skills, traduction et enrichissement, routage de modèle, surfaces de l'assistant.

## Les autres pages développeur

- **[Les registres de WAMA](registres.md)** — Quand une chose mérite un registre, les natures d'actualisation, et chaque registre de WAMA — dérivé de la doc de construction et des registres eux-mêmes.
- **[Briques communes — API](briques.md)** — Chaque mécanisme transversal avec l'API publique de son module : signatures et docstrings lues dans le code.
