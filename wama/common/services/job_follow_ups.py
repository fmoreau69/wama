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


def family_model(family):
    """Le modèle des éléments d'une FAMILLE : celui de son adapter de détail (une card d'app), ou
    celui que déclare une famille suivie hors des files (`job_families` : une installation, un run
    du Studio, 2026-11-06) ; None sinon."""
    from wama.common.services import job_families
    from wama.common.utils.detail_registry import DetailRegistry

    entry = DetailRegistry.get(family)
    if entry is not None:
        return entry['model']
    tracked = job_families.get(family)
    return tracked.model_class() if tracked is not None else None


def origin_turn(note, surface: str):
    """Le TOUR de cette surface où l'élément de la notification a été créé ou lancé — lu dans les
    étapes d'outils persistées (`tool_api.items_of_step`), du plus récent au plus ancien.

    L'élément est désigné par sa FAMILLE (clé du `DetailRegistry` : `audio_enhancer` et `enhancer`
    sont deux modèles d'une même app ; ou famille suivie, `family_model`) et son id ; la famille doit
    bien porter le modèle nommé par la notification — sinon deux éléments de même numéro dans deux
    modèles se confondraient."""
    model = family_model(note.app)
    if model is None or model.__name__ != note.object_type:
        return None
    try:
        wanted = (note.app, int(note.object_id))
    except (TypeError, ValueError):
        return None
    return next((turn for turn in _assistant_turns(note, surface)
                 if wanted in turn_designations(turn.tool_steps)[0]), None)


def origin_conversation(note, surface: str):
    """Le fil de cette surface où l'élément de la notification a été créé ou lancé (`origin_turn`)."""
    turn = origin_turn(note, surface)
    return turn.conversation if turn is not None else None


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
    from wama.common.services import job_families
    tracked = job_families.get(note.app)
    if tracked is not None:
        return tracked.status_step(user, note.object_id)
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


def already_told(conversation, note, title: str = None, since=None) -> bool:
    """Cette fin a-t-elle déjà été racontée dans ce fil ? Une notification se relève par chaque
    onglet ouvert (web) : le fil ne doit la raconter qu'une fois. `title`/`since` : la fin d'un
    LOT, racontée une fois par lancement (depuis le tour qui l'a lancé)."""
    from wama.common.models import ConversationTurn
    return ConversationTurn.objects.filter(
        conversation=conversation, role='user', content=NOTICE_PREFIX + (title or note.title),
        created_at__gte=since or note.created_at).exists()


def record(conversation, note, response: str, step: dict, title: str = None) -> None:
    """Enregistre au fil la fin de tâche — un échange comme un autre
    (`conversation_store.record_exchange`) : la notification côté utilisateur, la réponse avec
    l'étape d'outil RÉELLEMENT jouée côté assistant. L'historique resservi au modèle garde ainsi un
    « terminé » APPUYÉ sur un outil — un « terminé » sans outil est précisément l'exemple qui lui
    faisait inventer des résultats (`WAMA_LLM.md` §2026-10-05). `title` : celui d'une fin de LOT."""
    from wama.common.services import conversation_store
    conversation_store.record_exchange(
        conversation, NOTICE_PREFIX + (title or note.title),
        {'response': response, 'tool_steps': [step], 'model': conversation_store.NOTICE_SOURCE})


#: L'outil que joue la fin racontée d'un LOT : l'état et le ZIP du lot, le bouton ⬇ de sa card mère.
BATCH_END_TOOL = 'get_batch_result'
#: Échecs nommés dans la fin d'un lot ; au-delà, leur nombre et le lot dans l'app.
BATCH_END_FAILURES_SHOWN = 5


def outputs_to_join(note, step) -> list:
    """Les sorties qu'une surface JOINT à une fin racontée (pièces jointes d'un canal) : celles de
    l'élément — aucune pour la fin d'un LOT, dont les résultats sont un ZIP donné en lien (joindre
    ceux de la dernière fille finie ferait croire qu'ils sont ceux du lot)."""
    if note is None or (step or {}).get('tool') == BATCH_END_TOOL:
        return []
    return declared_output_urls(note)


def turn_batches(steps) -> set:
    """Les LOTS qu'un tour a lancés : `{(surface, id du lot)}` (`tool_api.batch_of_step`)."""
    from wama.tool_api import batch_of_step
    found = set()
    for step in steps or []:
        if isinstance(step, dict):
            batch = batch_of_step(str(step.get('tool') or ''), step.get('result'))
            if batch:
                found.add(batch)
    return found


def launched_batch(note, turn):
    """`(surface, id du lot)` si l'élément de la notification est une card fille d'un lot que
    `turn` a LANCÉ (`launch_batch`) — sa fin est alors celle du lot, racontée une fois (2026-11-05,
    Fabien : « aller jusqu'au bout d'un lot sans surcharger le fil de discussion »). None pour un
    élément lancé seul, même s'il vit dans un lot."""
    from wama.common.utils.batch_common import batch_of
    from wama.common.utils.detail_registry import DetailRegistry
    batches = turn_batches(turn.tool_steps) if turn is not None else set()
    if not batches:
        return None
    entry = DetailRegistry.get(note.app)
    element = entry['model'].objects.filter(pk=note.object_id).first() if entry else None
    lot = batch_of(element) if element is not None else None
    return (note.app, lot.pk) if lot is not None and (note.app, lot.pk) in batches else None


def batch_end_title(state) -> str:
    """Le titre de la fin d'un lot — le libellé de son app (`app_identity`) et le titre du lot, dans
    la forme du titre d'une fin d'élément (`notifications._job_title`)."""
    from wama.common.app_registry import app_identity
    failures = (state.get('counts') or {}).get('failure') or 0
    end = 'terminé' if not failures else f"terminé avec {failures} échec{'s' if failures > 1 else ''}"
    return f"{app_identity(state['family'])['label']} — lot « {state['label']} » {end}"


def batch_end_text(state, step) -> str:
    """La fin d'un LOT dans le fil : son titre, ses comptes, ses échecs NOMMÉS (le premier geste qui
    reste à poser), le ZIP de ses résultats et le lot dans l'app — des adresses ABSOLUES
    (`navigation.absolute_url`, celles de `get_batch_result`) : la même fin se lit sur le web et
    sur un canal."""
    from wama.common.services.navigation import absolute_url
    counts = state.get('counts') or {}
    failures = counts.get('failure') or 0
    lines = [f"{'⚠' if failures else '✅'} {batch_end_title(state)}",
             f"{counts.get('success') or 0} terminé(s), {failures} en échec, sur {state['total']}."]
    failed = [c for c in state['items'] if c['terminal'] and not c['ok']]
    for child in failed[:BATCH_END_FAILURES_SHOWN]:
        lines.append(f"⚠ {child['label']}" + (f" : {child['error']}" if child.get('error') else ''))
    if len(failed) > BATCH_END_FAILURES_SHOWN:
        lines.append(f"… et {len(failed) - BATCH_END_FAILURES_SHOWN} autre(s) échec(s).")
    links = []
    link = ((step or {}).get('result') or {}).get('link')
    if link:
        links.append(f"[📥 Télécharger le lot (ZIP)]({link})")
    if state.get('page_url'):
        links.append(f"[Ouvrir le lot dans l'app]({absolute_url(state['page_url'])})")
    if links:
        lines.append(' · '.join(links))
    return '\n'.join(lines)


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


#: Éléments suivis au plus pour UN tour (un lancement de toute la file rend ses `ids`) — au-delà,
#: une ligne dit combien d'autres et mène à leur file. Un LOT n'y compte que pour une ligne.
TURN_JOBS_MAX = 20


def turn_jobs(user, steps) -> list:
    """Les éléments qu'un tour a créés ou lancés, chacun dans l'état de sa card (`tool_api.
    job_progress`) — la ligne que l'échange montre sous la réponse (2026-10-20) : barre, puis faces
    de l'aperçu. En cours OU FINIS (2026-11-04, Fabien) : jusque-là seuls les éléments en cours
    étaient rendus, si bien qu'une tâche plus rapide que la réponse (une image, une conversion)
    n'avait aucun aperçu, et qu'au rechargement du fil chaque résultat perdait le sien. Sa fin
    reste racontée par la relève (`tell`) ; la ligne d'un élément fini s'ouvre sur la Sortie.
    Les tâches de développement (`dev_*`) n'ont pas de progression déclarée : pas de ligne.

    Un LOT lancé (2026-11-05) est UNE ligne (`tool_api.batch_progress` : la barre de sa card mère,
    ses filles montrées une à la fois), quelle que soit sa taille — ses cards filles n'en ont pas
    d'autre. Au-delà de `TURN_JOBS_MAX` éléments seuls, une ligne par famille dit combien d'autres
    et mène à leur file (`kind: 'more'`) : elles tournent, la réponse ne les tait plus."""
    from wama.common.services.journal import family_queue_url
    from wama.tool_api import batch_progress, job_progress

    items, _dev_jobs = turn_designations(steps)
    rows = [row for row in (batch_progress(user, family, pk)
                            for family, pk in sorted(turn_batches(steps))) if row]
    in_batches = {(row['family'], child['id']) for row in rows for child in row['items']}
    alone = sorted(items - in_batches)
    for family, pk in alone[:TURN_JOBS_MAX]:
        row = job_progress(user, family, pk)
        if row:
            rows.append(row)
    more = {}
    for family, _pk in alone[TURN_JOBS_MAX:]:
        more[family] = more.get(family, 0) + 1
    rows.extend({'kind': 'more', 'family': family, 'count': count, 'terminal': True,
                 'page_url': family_queue_url(family)} for family, count in sorted(more.items()))
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
    d'un canal dont les fichiers partent en pièces jointes).

    La fin d'une card fille d'un LOT lancé (`launched_batch`, 2026-11-05) n'est pas racontée seule :
    le lot l'est, UNE fois, quand plus rien n'y bouge — par la notification de la fille qui le
    termine, avec l'outil qui rend son état et son ZIP (`BATCH_END_TOOL`). Ce que la surface a
    ajouté à sa forme (`compose`) ne s'y applique pas : la fin d'un lot est la même partout."""
    from django.db import transaction

    from wama.common.models import Conversation
    from wama.common.utils.notifications import DEV_JOB_APP

    if note.app == DEV_JOB_APP:
        turn, conversation = None, dev_origin_conversation(note, surface)
    else:
        turn = origin_turn(note, surface)
        conversation = turn.conversation if turn is not None else None
    if conversation is None:
        return None
    batch = launched_batch(note, turn)
    with transaction.atomic():
        Conversation.objects.select_for_update().filter(pk=conversation.pk).first()
        if batch is not None:
            return _tell_batch(conversation, note, batch, turn)
        if already_told(conversation, note):
            return None
        step = status_step(note, note.recipient)
        response = compose(note)
        record(conversation, note, response, step)
    return conversation, response, step


def _tell_batch(conversation, note, batch, turn):
    """La fin d'un LOT, sous le verrou du fil (`tell`) : rien tant qu'une fille bouge ; puis une
    fois par lancement (`already_told` depuis le tour qui l'a lancé) — deux filles finies au même
    instant n'en font qu'une."""
    from wama.tool_api import batch_progress, execute_tool
    family, batch_id = batch
    state = batch_progress(note.recipient, family, batch_id)
    if state is None or not state['terminal']:
        return None
    title = batch_end_title(state)
    if already_told(conversation, note, title=title, since=turn.created_at):
        return None
    args = {'app': family, 'batch_id': batch_id}
    step = {'tool': BATCH_END_TOOL, 'args': args,
            'result': execute_tool(BATCH_END_TOOL, args, note.recipient)}
    response = batch_end_text(state, step)
    record(conversation, note, response, step, title=title)
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
                from wama.common.services import conversation_store
                told.append({'notification_id': note.pk, 'response': response,
                             'tool_steps': [step], 'model': conversation_store.NOTICE_SOURCE})
        except Exception:
            logger.exception("[job_follow_ups] fin de tâche non racontée (notification #%s)",
                             note.pk)
    return told
