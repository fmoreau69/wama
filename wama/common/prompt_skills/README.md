# Skills de prompt (consignes d'enrichissement par application)

> Contrat consommé par `common/utils/prompt_skills.py` (voir sa docstring pour la résolution
> `<app>-<domain>` → `<app>` → `default-<kind>`). Sources d'appel : pipeline de prompts
> (`prompt_pipeline` hook A), enrichissement à la demande (`prompt_enrichment.enrich_on_demand`,
> ex. bouton ✨ imager), assistant IA / wama-dev-ai (`skills_catalog()` — fichiers lisibles sans
> Django).

## Format d'un skill

- **Le fichier `.md` EST le system prompt** envoyé au LLM d'enrichissement (anglais, LLM local).
- Il DOIT imposer : préserver exactement le sujet/l'intention de l'utilisateur ; sortie = le
  prompt enrichi SEUL (pas de préambule, pas de guillemets, pas d'explication).
- Il NE DOIT PAS parler de langue d'émission ni de glossaire : la clause de langue et la
  préservation des mots-clés forcés par l'utilisateur sont ajoutées PAR LE CODE
  (`prompt_enrichment`) — règles du mécanisme, pas des skills.
- Un exemple few-shot court améliore nettement les petits modèles locaux (garder 1 exemple).

## Nommage

`<app>-<domain>.md` (ex. `imager-image.md`, `imager-video.md`, `composer-music.md`),
repli `<app>.md`, défaut `default-<kind>.md` (ex. `default-generative.md`).
Le domain vient de `PROMPT_TARGETS` (`domain` statique ou `domain_field` sur l'instance),
repli sur le `model_type` du modèle cible.

## Ajouter un skill pour une nouvelle app

1. Déclarer le champ-prompt dans `common/utils/app_metadata.py::PROMPT_TARGETS`
   (`enrich=True` + `domain`/`domain_field` si plusieurs domaines).
2. Créer `<app>[-<domain>].md` ici. C'est tout — aucune app ne code ses consignes en dur.
