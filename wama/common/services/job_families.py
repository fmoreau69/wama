"""
Les FAMILLES SUIVIES hors des files d'app — ce que l'échange de l'assistant suit et raconte, et que
le calendrier date, pour un élément qui n'est pas une card (2026-11-06).

Demande de Fabien : l'installation d'un modèle suivie « avec message » depuis l'assistant, puis le
Studio, « quelque chose d'universel et pérenne ». La chaîne existait pour les cards d'app : l'outil
désigne l'élément (`tool_api.items_of_step`), sa ligne est celle de sa card (`tool_api.job_progress`,
déclarée par `TRIAD_SPECS`), sa fin est notifiée (`notify_job_end`) et racontée au fil d'où il a été
demandé (`job_follow_ups`). Une installation (`InstallEvent`) ou une exécution du Studio
(`StudioRun`) n'ont ni triade ni adapter de détail : sans ce registre, chacune aurait demandé un
`if` de plus dans chacun de ces lecteurs — c'est ainsi qu'y vivent les tâches de développement.

LE REGISTRE NE CONNAÎT PAS SES PRODUCTEURS (règle du registre des fonctions, `AGENTS.md`) : l'app
qui POSSÈDE le modèle de l'élément l'inscrit dans son `ready()` (`register`) — le model manager ses
installations, le Studio ses exécutions. La famille est la clé de cette app : celle de la page qui
montre l'élément et de l'`app` de la notification de sa fin.

Ce qu'une famille DÉCLARE, et ce que chaque lecteur en tire :
  • `model`  — le modèle de l'élément (chemin pointé) : la notification le désigne par son nom de
               classe, la fin racontée vérifie que c'est bien lui (`job_follow_ups.origin_turn`) ;
  • `tools`  — les outils qui le CRÉENT ou le LANCENT : leur résultat le nomme par la clé uniforme
               `item_id` (contrat méta-app, `items_of_step`) ;
  • `row`    — `fonction(user, pk) → ligne | None` : la ligne de suivi au contrat de `job_progress`
               (`family`, `id`, `label`, statut normalisé, `progress`, `terminal`, `ok`), bornée à
               ce que `user` a le droit de voir — et `started_at` si l'élément le sait (calendrier) ;
  • `status_tool` / `status_arg` — le geste « statut » RÉELLEMENT rejoué quand sa fin est racontée.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JobFamily:
    key: str
    model: str
    row: str
    status_tool: str
    status_arg: str
    tools: tuple = field(default_factory=tuple)

    def model_class(self):
        from django.utils.module_loading import import_string
        return import_string(self.model)

    def read(self, user, pk):
        """La ligne de suivi de l'élément `pk` pour `user`, ou None."""
        from django.utils.module_loading import import_string
        return import_string(self.row)(user, pk)

    def status_step(self, user, pk) -> dict:
        """Le geste « statut » de l'élément, RÉELLEMENT joué — l'étape qu'une fin racontée
        enregistre au fil (`job_follow_ups.status_step`)."""
        from wama.tool_api import execute_tool
        args = {self.status_arg: int(pk)}
        return {'tool': self.status_tool, 'args': args,
                'result': execute_tool(self.status_tool, args, user)}


_FAMILIES: dict = {}


def register(family: JobFamily) -> None:
    """Inscrit une famille — idempotent (un `ready()` peut être rejoué)."""
    _FAMILIES[family.key] = family


def get(key):
    """La famille `key`, ou None (une card d'app n'en est pas une : elle est à `TRIAD_SPECS`)."""
    return _FAMILIES.get(key or '')


def for_tool(tool_name):
    """La famille dont `tool_name` crée ou lance les éléments, ou None."""
    return next((f for f in _FAMILIES.values() if tool_name in f.tools), None)


def families() -> list:
    return list(_FAMILIES.values())
