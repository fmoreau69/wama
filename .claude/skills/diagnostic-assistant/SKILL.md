---
name: diagnostic-assistant
description: Diagnostiquer une réponse FAUSSE de l'assistant WAMA (web, API ou Discord) en lisant le fil PERSISTÉ — ce qu'il a dit vs les `tool_steps` qu'il a réellement exécutés. Utiliser quand l'utilisateur rapporte « l'assistant m'a répondu n'importe quoi », « il dit que c'est fait et ça ne l'est pas », « il refuse alors qu'il devrait pouvoir », « lien qui ne marche pas », ou colle un échange de l'assistant.
---

# /diagnostic-assistant — lire ce que l'assistant a FAIT, pas ce qu'il a dit

> ⚠ CANDIDAT (n=1, 2026-09-26). Le geste a été déroulé **neuf fois** dans la session du 23→26/09
> et a trouvé neuf défauts distincts derrière un seul symptôme rapporté. Il sera promu à la
> première session qu'il aura guidée de bout en bout.

**Le principe** : une réponse d'assistant est une SORTIE de modèle, pas une trace d'exécution.
Ce que l'assistant *raconte* et ce qu'il a *exécuté* sont deux choses, et seule la seconde est
mesurable — elle est persistée. *Diagnostiquer le récit, c'est déboguer une fiction.*

## 1. Lire le fil, pas le message collé

Les tours vivent en base (`Conversation` / `ConversationTurn`, `common/services/conversation_store.py`),
avec le champ qui compte : **`tool_steps`** — chaque outil appelé, ses arguments, son résultat.

```python
from wama.common.models import Conversation
c = Conversation.objects.filter(surface='discord').order_by('-updated_at').first()
for t in c.turns.order_by('created_at'):
    print(t.role, t.model, t.content[:400])
    for s in (t.tool_steps or []):
        print('   TOOL>', s.get('tool'), s.get('args'), '->', s.get('result'))
```

`surface` vaut `web`, `api`, `discord`… ; un fil = `(user, surface, thread_key)`.

## 2. Les quatre lectures qui tranchent (dans cet ordre)

1. **Le tour a-t-il appelé un outil ?** `tool_steps` vide + une réponse affirmative = le modèle
   a INVENTÉ. Ne pas chercher plus loin côté backend.
2. **L'outil a-t-il rendu ce que le modèle raconte ?** Comparer mot à mot le `result` et la
   phrase. Un `status: queued` raconté « lancé » est un défaut de CONTRAT, pas de modèle.
3. **L'outil a-t-il échoué ?** Un `{'error': …}` que le modèle transforme en « je ne peux pas »
   est le motif le plus fréquent : *une erreur illisible se propage en fausse incapacité*.
   Lire l'erreur ENTIÈRE — si elle est tronquée, c'est déjà un défaut à corriger.
4. **Quel MODÈLE a répondu ?** Le champ `model` du tour (`wama-dev-ai (qwen3.5:4b)`,
   `… · dev`). Un modèle inattendu renvoie au tirage (`resolve_turn_model`), au bridage de
   domaine du fil (`last_loaded_domain`) ou à la bascule de contexte.

## 3. Puis remonter la chaîne, maillon par maillon

Ne jamais s'arrêter au premier défaut : dans la session fondatrice, **chacun en cachait un
autre**. Le fichier n'arrivait pas → parce que la lecture des sorties ignorait la forme réelle
des outils → et une fois corrigée, la tâche n'avait jamais tourné → et une fois lancée, le flou
valait 2 au lieu de 25.

- l'outil rend-il ce que le contrat promet ? (`tool_api`, la triade)
- la tâche a-t-elle tourné ? (statut de l'item EN BASE, pas le récit)
- le résultat est-il celui attendu ? (ouvrir le fichier de sortie, le regarder)

## 4. Pièges VÉCUS

- 🔴 **Le worker et la passerelle chargent le code AU DÉMARRAGE.** Deux runs ont été perdus à
  mesurer l'ancien code après un correctif. Après toute modification de tâche, de backend ou
  d'outil : relancer le worker Celery concerné ; de la passerelle : relancer `run_gateway`.
- 🔴 **`pkill -f "run_gateway"` tue son propre shell** (sa ligne de commande contient le motif).
  Lancer le `pkill` dans un appel SÉPARÉ, et relancer avec `setsid nohup … &`.
- ⚠ **L'historique du fil est une SOURCE pour le modèle.** Une fabrication qui y entre est
  resservie à chaque tour et ré-émise, même après correction du prompt. Regarder les tours
  ANTÉRIEURS avant de conclure que le correctif ne marche pas.
- ⭐ **REJOUER le tour, AVEC et SANS son historique** (2026-10-05, ce geste a tranché « le
  modèle ou le fil ? »). `run_assistant_turn(user, msg, provider=…, model=…, history=…,
  surface=…)` avec `wama.tool_api.execute_tool` remplacé par un double qui bouchonne les
  outils `add`/`start` (`tool_role`) et laisse passer les lectures — jamais de tâche réelle
  sur le compte id=1. Plusieurs tirages : un taux, pas un tirage. Même modèle, même message,
  outil sans historique et fabrication avec = le FIL est en cause, pas le modèle.
- ⚠ **Une réponse « je ne peux pas » se vérifie contre `build_tools_list()`** : l'outil
  existe-t-il ? Trois refus sur quatre de la session fondatrice portaient sur des outils que
  l'assistant AVAIT.
- ⚠ Les horodatages : `ConversationTurn.created_at` est en UTC, les journaux applicatifs en
  heure locale. Deux heures d'écart font conclure qu'un correctif « était en place » alors
  qu'il ne l'était pas.

## 5. Ce que le diagnostic doit produire

Un défaut mesuré se solde par **un contrôle, pas par une consigne de prompt** — c'est la leçon
centrale de la session fondatrice : quatre correctifs d'information n'ont pas tenu, ce qui a
tenu est ce que la SORTIE vérifie (`_strip_unsourced_urls`) et ce que la DONNÉE porte
(`relay_next_step`). Voir `WAMA_LLM.md §2026-09-23`.
