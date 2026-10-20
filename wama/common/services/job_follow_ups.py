"""
La FIN D'UNE TÂCHE racontée dans le fil d'où elle a été demandée — brique commune à toute surface
de l'assistant (canaux de la passerelle, fil web).

POURQUOI UNE BRIQUE (2026-10-18). La passerelle le faisait depuis le 2026-10-06 (`ROADMAP §19.2`,
`gateway.core.collect_job_follow_ups`) : elle relève les notifications de fin (`notify_job_end`,
qui DÉSIGNE l'élément), retrouve le fil d'origine dans le store de conversation, rejoue le geste
« statut » et poste le résultat. Le fil WEB, lui, ne recevait rien — Fabien : *« l'assistant ne
semble pas recevoir de trigger quand un travail est terminé, alors qu'une notification arrive »*.
Ce qui ne dépend pas de la surface vivait dans `gateway/core.py` ; il vit ici, et les deux surfaces
le lisent. Ce qui reste à chacune : la RELÈVE (un curseur par canal pour la passerelle, la cloche du
navigateur pour le web) et la FORME du message (pièces jointes d'un canal, liens du web).

Rien n'est inventé : la file est `common.Notification`, l'origine est LUE dans les étapes d'outils
persistées (`tool_api.items_of_step`, contrat méta-app), le résultat est un outil RÉELLEMENT joué
(`get_<famille>_status`, ou `dev_job_status` par le relais MCP pour une tâche de développement).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Les notifications racontées : les deux issues d'un traitement.
JOB_NOTICE_KINDS = ('job_done', 'job_failed')
#: Tours remontés pour trouver l'origine d'un élément.
ORIGIN_SCAN_TURNS = 200
#: Le message côté utilisateur d'un échange de fin de tâche — UNE graphie, que le fil enregistre et
#: qui sert à ne pas raconter deux fois la même fin.
NOTICE_PREFIX = '[Notification WAMA] '


def notice_text(note) -> str:
    """Le texte d'une fin de tâche : son titre (« … terminé » / « … a échoué ») et son détail."""
    lines = [f"{'✅' if note.kind == 'job_done' else '⚠'} {note.title}"]
    if note.body:
        lines.append(note.body)
    return '\n'.join(lines)


def _assistant_turns(note, surface: str):
    """Les tours de l'assistant où chercher l'origine — SANS borne de temps sur la notification
    (2026-10-18). Un tour s'enregistre à la FIN de sa réponse : une tâche plus rapide que la réponse
    qui l'a lancée (un flou d'image, 5 s) finit AVANT son tour, et la borne `created_at <= fin`
    l'écartait — mesuré sur l'élément anonymizer 1436, notification à 10:49:18, tour à 10:49:19."""
    from wama.common.models import ConversationTurn
    return (ConversationTurn.objects
            .filter(conversation__user_id=note.recipient_id, conversation__surface=surface,
                    role='assistant')
            .exclude(tool_steps=[])
            .select_related('conversation')
            .order_by('-created_at', '-pk')[:ORIGIN_SCAN_TURNS])


def origin_conversation(note, surface: str):
    """Le fil de CETTE surface où l'élément de la notification a été créé ou lancé — lu dans les
    étapes d'outils persistées (`tool_api.items_of_step`), du plus récent au plus ancien.

    L'élément est désigné par sa FAMILLE (clé du `DetailRegistry` : `audio_enhancer` et `enhancer`
    sont deux modèles d'une même app) et son id ; la famille doit bien porter le modèle nommé par
    la notification — sinon deux éléments de même numéro dans deux modèles se confondraient."""
    from wama.common.utils.detail_registry import DetailRegistry

    entry = DetailRegistry.get(note.app)
    if entry is None or entry['model'].__name__ != note.object_type:
        return None
    try:
        wanted = (note.app, int(note.object_id))
    except (TypeError, ValueError):
        return None
    return next((turn.conversation for turn in _assistant_turns(note, surface)
                 if wanted in turn_designations(turn.tool_steps)[0]), None)


def dev_origin_conversation(note, surface: str):
    """Le fil de CETTE surface dont une étape `dev_*` a rendu le `job_id` de la notification — la
    fin d'une tâche de DÉVELOPPEMENT (rôle wama-dev-ai, jumelle, Claude Code ; 2026-10-12)."""
    return next((turn.conversation for turn in _assistant_turns(note, surface)
                 if str(note.object_id) in turn_designations(turn.tool_steps)[1]), None)


def status_step(note, user) -> dict:
    """Le geste « statut », RÉELLEMENT joué : c'est l'étape que l'échange enregistre au fil. Une
    tâche de développement passe par le relais MCP — une surface n'importe jamais `dev_tools`."""
    from wama.common.utils.notifications import DEV_JOB_APP
    if note.app == DEV_JOB_APP:
        from wama.common.services import mcp_client
        args = {'job_id': note.object_id}
        return {'tool': 'dev_job_status', 'args': args,
                'result': mcp_client.call_dev_tool(user, 'dev_job_status', args)}
    from wama.tool_api import execute_tool
    tool = f'get_{note.app}_status'
    return {'tool': tool, 'args': {}, 'result': execute_tool(tool, {}, user)}


def declared_output_urls(note) -> list:
    """Les sorties DÉCLARÉES de l'élément d'une fin RÉUSSIE, en URL `/media/…` décodées
    (`send_to.sorties_de`, l'adapter de détail — l'accesseur de « Envoyer vers », de l'inspecteur
    et du Studio). Pas le statut : il ne liste que les DIX derniers éléments, et le premier d'un
    lot de vingt n'y est plus. `sorties_de` rend des chemins ENCODÉS (`FieldFile.url`) : décodés
    ici, comme le font ses autres appelants — sans quoi un nom accentué ne se joindrait pas."""
    from urllib.parse import unquote

    from django.conf import settings

    from wama.common.services.send_to import sorties_de
    from wama.common.utils.detail_registry import DetailRegistry

    if note.kind != 'job_done':
        return []
    entry = DetailRegistry.get(note.app)
    instance = entry['model'].objects.filter(pk=note.object_id).first() if entry else None
    if instance is None:
        return []
    media_url = settings.MEDIA_URL or '/media/'
    return [media_url + unquote(rel) for rel in sorties_de(note.app, instance)]


def origin_of(note, surface: str):
    """Le fil d'origine d'une notification sur cette surface, quelle que soit la nature de la
    tâche (traitement d'app ou tâche de développement) ; None si elle n'en vient pas."""
    from wama.common.utils.notifications import DEV_JOB_APP
    if note.app == DEV_JOB_APP:
        return dev_origin_conversation(note, surface)
    return origin_conversation(note, surface)


def already_told(conversation, note) -> bool:
    """Cette fin a-t-elle déjà été racontée dans ce fil ? Une notification se relève par chaque
    onglet ouvert (web) : le fil ne doit la raconter qu'une fois."""
    from wama.common.models import ConversationTurn
    return ConversationTurn.objects.filter(
        conversation=conversation, role='user', content=NOTICE_PREFIX + note.title,
        created_at__gte=note.created_at).exists()


def record(conversation, note, response: str, step: dict) -> None:
    """Enregistre au fil la fin de tâche — un échange comme un autre
    (`conversation_store.record_exchange`) : la notification côté utilisateur, la réponse avec
    l'étape d'outil RÉELLEMENT jouée côté assistant. L'historique resservi au modèle garde ainsi un
    « terminé » APPUYÉ sur un outil — un « terminé » sans outil est précisément l'exemple qui lui
    faisait inventer des résultats (`WAMA_LLM.md` §2026-10-05)."""
    from wama.common.services import conversation_store
    conversation_store.record_exchange(
        conversation, NOTICE_PREFIX + note.title,
        {'response': response, 'tool_steps': [step], 'model': 'notification WAMA'})


def told_since(surface: str, since) -> list:
    """Les fins RACONTÉES sur cette surface depuis `since`, relues du fil tel que `record` l'écrit :
    `[(conversation, note, response, step, told_at)]`, dans l'ordre du récit — `note` vaut None si
    la notification a été supprimée depuis. Le pendant d'`already_told` : ce que la surface doit
    MONTRER, pour celle qui peut perdre un envoi (un canal en panne, 2026-10-18)."""
    from wama.common.models import ConversationTurn, Notification

    told = []
    asked = (ConversationTurn.objects
             .filter(conversation__surface=surface, role='user',
                     content__startswith=NOTICE_PREFIX, created_at__gte=since)
             .select_related('conversation', 'conversation__user').order_by('created_at', 'pk'))
    for turn in asked:
        conversation = turn.conversation
        reply = conversation.turns.filter(role='assistant', pk__gt=turn.pk).order_by('pk').first()
        if reply is None:
            continue
        note = (Notification.objects
                .filter(recipient=conversation.user, kind__in=JOB_NOTICE_KINDS,
                        title=turn.content[len(NOTICE_PREFIX):], created_at__lte=turn.created_at)
                .order_by('-pk').first())
        told.append((conversation, note, reply.content, (reply.tool_steps or [{}])[0],
                     reply.created_at))
    return told


def turn_designations(steps) -> tuple:
    """Ce qu'un tour a désigné : `({(famille, id)}, {job_id})` — les éléments d'app lus par
    `tool_api.items_of_step` (le contrat méta-app, celui d'`origin_conversation`) et les tâches de
    développement lancées par un outil `dev_*` (celui de `dev_origin_conversation`)."""
    from wama.common.services import mcp_client
    from wama.tool_api import items_of_step

    items, jobs = set(), set()
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        tool = str(step.get('tool') or '')
        items.update(items_of_step(tool, step.get('args'), step.get('result')))
        result = step.get('result')
        if mcp_client.is_dev_tool(tool) and isinstance(result, dict) and result.get('job_id'):
            jobs.add(str(result['job_id']))
    return items, jobs


#: Éléments suivis au plus pour UN tour (un lancement de toute la file rend ses `ids`).
TURN_JOBS_MAX = 20


def turn_jobs(user, steps, in_flight_only: bool = True) -> list:
    """Les éléments qu'un tour a créés ou lancés, chacun dans l'état de sa card (`tool_api.
    job_progress`) — ce que la barre de progression de l'échange suit (2026-10-20). Par défaut,
    ceux qui sont ENCORE EN COURS : un élément déjà fini a sa fin racontée par la relève (`tell`).
    Les tâches de développement (`dev_*`) n'ont pas de progression déclarée : pas de barre."""
    from wama.tool_api import job_progress

    items, _dev_jobs = turn_designations(steps)
    rows = []
    for family, pk in sorted(items)[:TURN_JOBS_MAX]:
        row = job_progress(user, family, pk)
        if row and not (in_flight_only and row['terminal']):
            rows.append(row)
    return rows


def notices_of_turn(user, steps, since) -> list:
    """Les fins de tâche ARRIVÉES PENDANT un tour, pour ce qu'il a désigné — ids de notification.

    Le moment déterministe d'une tâche plus rapide que la réponse qui l'a lancée (2026-10-18) : la
    relève de la surface (cloche du web, curseur d'un canal) a pu passer AVANT l'enregistrement du
    tour, ne pas lui trouver de fil, et ne plus jamais la revoir. `conversation_turn` les lit donc
    une fois le tour enregistré ; chaque surface les raconte comme une relève (`tell`)."""
    from wama.common.models import Notification
    from wama.common.utils.notifications import DEV_JOB_APP

    items, jobs = turn_designations(steps)
    if not items and not jobs:
        return []
    ids = []
    for note in (Notification.objects
                 .filter(recipient=user, kind__in=JOB_NOTICE_KINDS, created_at__gte=since)
                 .exclude(object_id='').order_by('pk')):
        if note.app == DEV_JOB_APP:
            hit = note.object_id in jobs
        else:
            try:
                hit = (note.app, int(note.object_id)) in items
            except (TypeError, ValueError):
                hit = False
        if hit:
            ids.append(note.pk)
    return ids


def tell(note, surface: str, compose):
    """Raconte UNE fin de tâche dans son fil d'origine sur cette surface, une seule fois :
    `(conversation, response, step)`, ou None (pas lancée d'un fil, ou déjà racontée).

    Le fil est VERROUILLÉ le temps de vérifier et d'enregistrer — deux relèves de la même
    notification (deux onglets, ou la fin du tour et la relève d'un canal) : la première raconte,
    l'autre lit. `compose(note)` écrit la réponse dans la forme de la surface (liens du web, texte
    d'un canal dont les fichiers partent en pièces jointes)."""
    from django.db import transaction

    from wama.common.models import Conversation

    conversation = origin_of(note, surface)
    if conversation is None:
        return None
    with transaction.atomic():
        Conversation.objects.select_for_update().filter(pk=conversation.pk).first()
        if already_told(conversation, note):
            return None
        step = status_step(note, note.recipient)
        response = compose(note)
        record(conversation, note, response, step)
    return conversation, response, step


def web_follow_ups(user, notification_ids, absolute=lambda url: url) -> list:
    """Les fins de tâche à raconter dans le fil WEB de `user`, pour les notifications que sa cloche
    vient de relever ou que son tour vient de voir finir (`notices_of_turn`) — chacune enregistrée
    au fil (une seule fois) et rendue sous la forme d'un tour de l'assistant :
    `[{notification_id, response, tool_steps, model}]`.

    Une tâche qui n'a pas été lancée par l'assistant n'a pas de fil d'origine : rien (la cloche la
    signale déjà). `absolute` rend une URL cliquable (la vue passe `request.build_absolute_uri`) :
    le chat ne fait des liens que des adresses http(s)."""
    from wama.common.models import Notification

    def compose(note):
        lines = [notice_text(note)]
        for url in declared_output_urls(note):
            lines.append(f"[{url.rsplit('/', 1)[-1]}]({absolute(url)})")
        return '\n'.join(lines)

    ids = [int(i) for i in (notification_ids or []) if str(i).isdigit()][:50]
    notes = (Notification.objects
             .filter(pk__in=ids, recipient=user, kind__in=JOB_NOTICE_KINDS)
             .exclude(object_id='').order_by('pk'))
    told = []
    for note in notes:
        try:
            outcome = tell(note, 'web', compose)
            if outcome is None:
                continue
            conversation, response, step = outcome
            # Le chat montre LE fil web (clé vide, `views._chat_thread`). Une tâche lancée d'un
            # AUTRE fil web (fil de vérification ouvert par l'API) y est racontée — elle n'apparaît
            # pas dans une conversation où elle n'a jamais été demandée.
            if not conversation.thread_key:
                told.append({'notification_id': note.pk, 'response': response,
                             'tool_steps': [step], 'model': 'notification WAMA'})
        except Exception:
            logger.exception("[job_follow_ups] fin de tâche non racontée (notification #%s)",
                             note.pk)
    return told
