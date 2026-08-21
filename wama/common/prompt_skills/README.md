# Skills de prompt

> ⚠ **DEUX FAMILLES COHABITENT ICI, avec des contrats OPPOSÉS.** Les confondre coûte une
> passe LLM inutile (enrichir un prompt déjà enrichi) ou un assistant sans posture.
>
> | Famille | Fichiers | Destinataire | Contrat |
> |---|---|---|---|
> | **Enrichissement** | `imager-image.md`, `composer-music.md`, `default-generative.md`… | le LLM d'**enrichissement**, au lancement d'une tâche d'app | transforme un prompt ; **sortie = le prompt enrichi SEUL** |
> | **Rôle** (2026-08-21) | `assistant-*.md` | l'**assistant lui-même**, dans son prompt système | ne transforme rien ; définit une posture, un domaine, des interdits |
>
> Les skills de rôle sont déclarés dans `common/utils/assistant_skills.py::DOMAINES` (avec
> leur besoin de contexte RAG) et injectés par `assistant_engine`. **Ajouter un domaine =
> une entrée au registre + un fichier `assistant-<clé>.md`** — aucune vue à modifier.
> Le reste de ce document décrit la famille **enrichissement**.

## ⚠ Ce dossier n'est PAS en concurrence avec `wama-dev-ai/prompts/`

Précision de Fabien (2026-08-21), après que j'aie conclu trop vite à une duplication :
**« il y a les prompts et les skills ; il y a ce qui sert au DEV et ce qui sert à
l'USAGE »**. Les deux dossiers servent des besoins distincts, pas le même besoin deux fois :

| | `wama/common/prompt_skills/` (ici) | `wama-dev-ai/prompts/` |
|---|---|---|
| Sert | l'**usage** — apps et assistant | le **dev** — l'agent CLI de développement |
| Vit dans | Django (registres, RAG, scoping) | un CLI autonome, hors Django |
| Consommé par | `prompt_pipeline`, `prompt_enrichment`, `assistant_skills` | `cli.py`, `run_audit.py`, `run_codegen.py`, `run_librarian.py` |

**Les fusionner serait une erreur** : ils n'ont ni le même cycle de vie, ni le même
destinataire, ni les mêmes contraintes d'exécution.

> ⚠ **La vraie dette est ailleurs, et elle est documentaire** : `wama-dev-ai/config.py:21`
> déclare `PROMPT_SKILLS_DIR` vers ce dossier — **cette constante n'est lue nulle part**, et
> `wama-dev-ai/README.md:151-162` documente un pont (`resolve_skill`, `skills_catalog`
> depuis wama-dev-ai) **qui n'existe pas dans le code**. Soit on le construit, soit on retire
> la promesse ; la laisser fait croire à un câblage absent.

**`skills_catalog()` n'est pas une fonction morte** — c'est la brique du futur **catalogue de
skills** (page de gestion dans le menu utilisateur, pendant de la page RAG). Elle attend son
consommateur, elle ne le remplace pas.

## Enrichissement (consignes par application)

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
