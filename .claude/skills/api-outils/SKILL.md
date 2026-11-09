---
name: api-outils
description: Compléter l'API de l'assistant (`tool_api.TOOL_REGISTRY` — dont dérivent l'API REST v1, le serveur MCP et l'exécuteur du Studio) à CHAQUE ajout fonctionnel — app neuve (réelle, jumelle, née d'un manifeste), geste neuf d'une card ou d'un lot, route d'action, page, process. Utiliser dès qu'un livrable ajoute quelque chose qu'un utilisateur peut FAIRE dans WAMA, quand `tests_tool_api_coverage` rougit, quand l'assistant répond « je ne peux pas » sur un geste que l'interface offre, ou quand l'utilisateur dit « compléter l'API », « l'assistant n'a pas l'outil », « expose-le à l'assistant ».
---

# /api-outils — ce que l'interface sait faire, l'assistant le sait aussi

> ⚠ CANDIDAT (n=1, 2026-11-02 — décision de Fabien : *« l'API doit être complétée
> systématiquement à chaque ajout fonctionnel. Il faut ajouter les gardes et skills permettant de
> maintenir l'API à jour »*). Vécu le jour même : le fil Discord n° 43 demandait le Writer, qui
> n'avait aucun outil ; le Translator n'en avait pas non plus, et les gestes ⏹ et ⚙ de TOUTES les
> cards non plus. Aucun test ne le disait : les gardes nommaient les dix apps à la main.

**Le principe** : l'API est UNE, `wama/tool_api.py::TOOL_REGISTRY`. L'API REST v1
(`wama/api/v1/views.py`), le serveur MCP (`common/services/mcp_server.py`) et l'exécuteur du
Studio en DÉRIVENT — compléter le registre les complète tous. Un outil appelle la VUE ou la
FABRIQUE de l'app (le même geste que le bouton), jamais un second chemin.

## 1. Quel ajout → quel outil (lire la ligne, pas la deviner)

| ajout fonctionnel | l'outil | où il se déclare |
|---|---|---|
| **app réelle** neuve | triade `add_to_<app>` / `start_<app>` / `get_<app>_status` | `start`/`status` : entrée `TRIAD_SPECS` (construite à l'import) ; `add_to_<app>` : créateur avec `app_label='<app>'` en dernier argument (sinon aucune jumelle ne pourra le recibler — `tests_tool_api_twins`) |
| **jumelle** (`generated_from`) | rien à écrire | dérivée de sa source (`_register_twin_creators`) |
| app **née d'un manifeste** | rien à écrire dans `tool_api.py` | facette `tool_api.triad_spec` du manifeste (`manifests/app_drafts/<clé>.json`, chemins `wama.<clé>.…`), puis `app_sandbox substitute <label> params` qui relit le registre (`born_registry_facts`) ; le créateur se dérive de la vue de dépôt et des ports (`_born_creator`) |
| **geste neuf** d'une card (`make_item_views`) | un verbe TRANSVERSE (`<geste>_item`) qui poste la vue par `_card_gesture` | `TOOL_REGISTRY` + ligne `GESTURE_TOOLS` de `tests_tool_api_coverage` |
| **geste neuf** d'un lot (`make_batch_views`) | un verbe TRANSVERSE (`<geste>_batch`) qui appelle la vue retenue par la fabrique (`_batch_view` ; une ÉCRITURE passe d'abord par `_batch_write_refusal`) — jamais un nom en `start_…`/`get_…_status`, pris pour une triade | idem |
| route d'action (un chemin `api/…`, d'une app OU d'une page : model manager, registres, médiathèque…) | un outil qui appelle le MÊME corps que la route (le sortir de la vue vers un service s'il y vit), ou un argument d'un outil existant ; une page de gestes tous ronds — le model manager — POSTE la vue du bouton (`_model_manager_view` : corps JSON, la garde de droit AVANT, car `user_passes_test` répond par une redirection que `_verdict` lirait comme un succès) | `TOOL_REGISTRY` (+ `TOOL_APP_OVERRIDE` si le nom ne suit pas la triade) + ligne `ROUTE_TOOLS` de `tests_tool_api_coverage` (2026-11-08 : les routes de formats du model manager n'avaient aucun outil, et aucune garde ne regardait les routes ; 2026-11-09 : les 46 autres de la page, et `VIEW_CALLS` dit quel appel atteint quelle vue, avec la méthode qu'elle accepte) |
| **page** neuve | rien, si elle est au registre de navigation | `open_page` la trouve (`navigation`) ; une page du compte qui se LIT a son `get_my_<page>` |
| process / étape d'un pipeline | rien | `start_<app>(…, process=…)` lit la fabrique (`process_views`) |
| réglage neuf au schéma | rien | `**params` du créateur et `update_item_settings` lisent le schéma |

## 2. Les règles d'un outil (chacune a sa garde)

- **Effet déclaré** : `@tool_effect(READ|WRITE|DESTROY)` — `tests_tool_effects`.
- **Garde d'app** : un outil nommé `…_<app>` est gardé par `tool_accessible` ; un verbe
  TRANSVERSE (`delete_item`, `stop_item`…) ne l'est PAS — `_refus_app(user, app)` en tête du corps
  est obligatoire (`_card_gesture` le fait).
- **Bac à sable** (décisions de Fabien du 2026-11-02) : UNE règle, celle de `accessible()` — un
  administrateur toutes les apps, un développeur les siennes et celles qu'on lui ouvre
  (`accounts.AccessGrant`), un utilisateur simple aucune. Un outil ne décide jamais à part : il
  passe par `tool_accessible` (outil nommé d'après l'app) ou `_refus_app` (verbe transverse).
- **Docstring en anglais** — son PREMIER PARAGRAPHE devient la description vue par le modèle
  (`tool_descriptions`, prompt et serveur MCP) : une ou deux phrases ENTIÈRES qui disent le geste,
  ses choix et qui y a droit ; le détail va dans les paragraphes suivants (2026-11-09 : la
  dérivation prenait la première LIGNE, 44 outils sur 144 montraient une phrase coupée —
  `EveryToolDescriptionIsAWholeSentenceTest`). Arguments typés (ils deviennent le schéma MCP :
  `tool_input_schema`) ; identifiants en anglais (`check_identifier_language`).
- **Contrat de retour** : une création rend `item_id` (`tests_tool_item_contract`) ; une erreur
  rend `{'error': …}` lisible — jamais une exception (`execute_tool` ne lève pas).
- **Confirmation** : un geste que la PAGE fait confirmer (`confirm(…)` du gabarit) exige
  `confirm=true` dans l'outil (`_unconfirmed`), comme un destructif ou un geste de masse ; une
  décision réservée (valider une proposition) dit le droit AVANT de demander l'accord.

## 3. Vérifier

1. `manage.py test wama.common.tests.tests_tool_api_coverage` — chaque app du catalogue a sa
   triade, chaque geste des fabriques a son outil, chaque route d'action a le sien
   (`ROUTE_TOOLS`), et les deux budgets — gestes et routes sans outil — sont EXACTS (ils ne
   peuvent que descendre : les baisser dans le commit qui ajoute l'outil). ⚠ « Une API sans
   consommateur » n'est jamais une question de retrait : son consommateur manquant est l'assistant.
2. Le périmètre : `tests_tool_effects`, `tests_tool_api_lectures`, `tests_mcp_server`,
   `tests_tool_item_contract`, `tests_identifier_language`.
3. `/contre-epreuve` sur la garde neuve (outil retiré du registre → ROUGE).
4. **Par l'assistant** (`feedback_eprouver_la_chaine_par_l_assistant`) : `execute_tool(<outil>,
   {…}, user)` sur un vrai élément, puis la conversation réelle ; un « je ne peux pas » se lit avec
   `/diagnostic-assistant` (l'outil existe-t-il dans `build_tools_list()` ?).
5. ⚠ Les processus chargent le registre AU DÉMARRAGE : relancer gunicorn, les workers, la
   passerelle Discord et le serveur MCP pour que l'outil soit servi.

## 4. Consigner

La ligne du livrable dans `WAMA_APP_GENERATION_ROUTE.md §11` (ou la section qui porte l'app) dit
quel outil l'expose ; `docs/dev/briques.md` se régénère (`doc_facts`) ; un geste laissé sans outil
reste dans le budget de `tests_tool_api_coverage`, avec sa ligne ⏳ — jamais tu.
