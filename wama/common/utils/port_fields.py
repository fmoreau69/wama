"""OÙ SE RANGE LA VALEUR D'UN PORT — le lecteur commun des entrées d'un élément (2026-11-24).

Demande de Fabien : *« trouver une façon universelle, parfaitement alignée et pérenne »* de dire la
colonne d'un port, puis *« un fonctionnement universel qui ne bloque pas les évolutions de wama »*.

LE CONSTAT (mesuré le 2026-11-24, cartographie `INPUT_MODEL_MATCHING §6.13`) : les ports
(`work_audio`, `work_image`…, rôle × nature, `app_modes.INPUT_TYPES`) sont nés le 2026-06-24, après
les colonnes des apps (`voice_reference` 2025-11-26, `reference_image` 2026-01-05, `avatar_upload`
2026-02-28…). Aucune colonne n'a été renommée, et SIX endroits ont recopié la liaison, chacun pour
lui : `WAMA_INGEST['target']`, la spec du volet (`source_text`, `source_file`), `_LINE_FIELDS` /
`COVER_FIELDS` des vues (retirés le même jour : `batch_parsers.line_file_inputs` lit ce lecteur),
des littéraux de JS, le « premier FileField » de l'extracteur et le `file_field` de l'aperçu — et
une septième, trouvée à la revérification : `studio/services/generic_runner.port_argument_name`. Trois ports rendus n'avaient aucune déclaration (l'avatar de
l'avatarizer, photo ou `.glb` ; le fichier de travail du synthesizer).

LA RÈGLE : un consommateur ne nomme JAMAIS une colonne — il demande la valeur d'un PORT à ce
lecteur. Le stockage est alors un détail que le lecteur seul connaît, et il peut changer (colonne
renommée, liste de chemins, table commune des entrées) sans qu'aucun consommateur ne le voie :
c'est la règle « le lecteur d'abord, les tables ensuite » de `ROUTE §10.7.11`, celle qui fait déjà
tenir les tables de lot par app derrière `batch_of` / `batch_elements`.

LA RÉSOLUTION, dans cet ordre :
  1. la DÉCLARATION du modèle d'élément, `register_port_fields(Modèle, {port: champ})` dans le
     `ready()` de l'app. Elle ne porte QUE les ports dont le champ ne porte pas le nom : c'est la
     liste des écarts hérités, qui ne doit que baisser. Dans `ready()` et non sur le modèle (forme
     du 24/11 au matin) — mesuré le même jour : le `apps.py` des jumelles est GÉNÉRÉ pour les douze,
     leur `models.py` pour six seulement (les six autres sont des copies figées à leur création) ;
     une déclaration du modèle n'aurait jamais atteint ces six-là. C'est la forme des pistes
     (`catalog/marks.register_tracks`) : l'extracteur la lit au registre (`inspector.port_fields`),
     `apps_gen` la rejoue dans le `ready()` généré ;
  2. sinon un champ HOMONYME du port (les apps nées d'un manifeste nomment déjà leurs colonnes
     ainsi : `reference_layout` du Writer, `work_result` du transcriber) ;
  3. sinon '' — le port n'a pas de champ (porté par un réglage, une capture en direct…) : sa valeur
     vit dans la TABLE COMMUNE DES ENTRÉES (`common.models.ElementInput`, plus bas), un rang par
     fichier. Une app DÉCLARE les ports qui y vivent (`register_port_fields(…, table=…)`).

UN CHAMP POUR PLUSIEURS PORTS : la valeur ne revient qu'au port que le fichier FOURNIT d'après sa
nature (`input_match.work_token_for`, la traduction que lit déjà le tirage du modèle, `_owned_by`)
— le stockage hérité ne fait pas mentir le lecteur. ⚠ C'est une lecture d'un stockage HÉRITÉ, pas
une forme à imiter : la cible qui ne bloque aucune évolution est que la valeur d'un port ne demande
AUCUNE colonne (une nature de plus = un port de plus, sans migration) — `INPUT_MODEL_MATCHING §6.13`.
L'avatar de l'avatarizer (photo de MuseTalk ou objet 3D de TalkingHead, tous deux dans
`avatar_upload`) en était le cas : depuis le 2026-11-25 il vit dans la table, première app à y
passer, et son ancienne colonne n'est plus lue qu'en REPLI (`legacy=`, même règle de nature) le
temps que la migration de la relance la recopie.
"""
from __future__ import annotations


#: `{'app_label.Modèle': {port: champ}}` — écrit par `register_port_fields`, au `ready()` des apps.
_LISTED: dict = {}
#: `{'app_label.Modèle': {port: colonne}}` — les ports PASSÉS dans la table commune des entrées dont
#: l'ancienne colonne existe encore : lue en REPLI tant qu'une card n'a pas de ligne (le code neuf
#: est servi avant que la relance joue la migration qui recopie la colonne), vidée quand le port
#: s'écrit dans la table. Se retire avec la colonne (`register_port_fields(…, legacy=)`).
_LEGACY: dict = {}
#: `{'app_label.Modèle': (port, …)}` — les ports qu'une app DÉCLARE vivre dans la table commune des
#: entrées (sans colonne) : la déclaration durable, que `legacy` accompagne le temps d'une transition.
_TABLE: dict = {}


def _label(model) -> str:
    if isinstance(model, str):
        return model
    model = model if isinstance(model, type) else type(model)
    return model._meta.label


def register_port_fields(model, mapping: dict, *, table=(), legacy: dict = None) -> None:
    """Déclare, pour le modèle d'élément `model` (classe, instance ou `'app.Modèle'`), le champ des
    ports qui ne portent pas son nom. Une seconde déclaration du même modèle la remplace (un
    rechargement de `ready()` ne double rien). Rien n'est vérifié ici — un `ready()` qui lève
    arrêterait tout WAMA ; la garde `tests_port_fields` refuse un port ou un champ fantôme.

    `table` (2026-11-25) : les ports qui vivent dans la table commune des entrées — la déclaration
    durable (`_TABLE`). `legacy` : `{port: colonne}` de ceux qui ont QUITTÉ leur colonne, la colonne
    existant encore — lue en repli, vidée à l'écriture (`_LEGACY`) ; un port `legacy` est un port
    de la table."""
    legacy = {str(port): str(field) for port, field in dict(legacy or {}).items()}
    _LISTED[_label(model)] = {str(port): str(field) for port, field in dict(mapping or {}).items()}
    _LEGACY[_label(model)] = legacy
    _TABLE[_label(model)] = tuple(dict.fromkeys([str(p) for p in table or ()] + list(legacy)))


def table_ports(model) -> tuple:
    """Les ports que le modèle déclare vivre dans la table commune des entrées (`table` / `legacy`)."""
    return tuple(_TABLE.get(_label(model)) or ())


def registered_table() -> dict:
    """Les ports déclarés « dans la table », par étiquette de modèle (`_TABLE`)."""
    return {label: list(ports) for label, ports in _TABLE.items() if ports}


def registered() -> dict:
    """Toutes les déclarations, par étiquette de modèle — ce que lisent l'extracteur et la garde."""
    return {label: dict(mapping) for label, mapping in _LISTED.items()}


def registered_legacy() -> dict:
    """Les anciennes colonnes des ports passés dans la table, par étiquette de modèle (`_LEGACY`)."""
    return {label: dict(mapping) for label, mapping in _LEGACY.items() if mapping}


def legacy_field(model, port: str) -> str:
    """L'ancienne colonne de `port` si elle existe encore sur le modèle, sinon ''."""
    model = model if isinstance(model, type) else type(model)
    field = (_LEGACY.get(_label(model)) or {}).get(port) or ''
    return field if field and field in _field_names(model) else ''


def element_value(element, name: str):
    """La valeur que désigne `name` sur un élément : son ATTRIBUT (champ, propriété) — ou, quand
    l'élément n'en a pas et que `name` est un PORT (`app_modes.INPUT_TYPES`), la valeur du port
    lue au lecteur (`port_value`). La règle commune des lecteurs de déclarations (2026-11-25) : la
    spec du volet (`detail_registry.spec_value`), l'aperçu (`preview_registry`) et la photo des
    réglages surveillés d'un process (`process_runs.snapshot`) nomment un champ OU un port — une
    app peut déclarer ses ports là où elle nommait sa colonne, et la colonne disparaître sans
    qu'aucun de ces lecteurs change. Un attribut existant prime toujours : rien ne change pour
    un nom qui était déjà lu."""
    marker = object()
    value = getattr(element, name, marker)
    if value is not marker:
        return value
    from wama.common.utils.app_modes import INPUT_TYPES
    if name in INPUT_TYPES and getattr(element, '_meta', None) is not None:
        return port_value(element, name)
    return None


def port_field_map(model) -> dict:
    """`{port: champ}` que le modèle d'élément déclare (`register_port_fields`), ou {}."""
    return dict(_LISTED.get(_label(model)) or {})


def _field_names(model) -> set:
    return {f.name for f in model._meta.get_fields() if getattr(f, 'concrete', False)}


def port_field(model, port: str) -> str:
    """Le champ du modèle d'élément `model` (classe ou instance) qui porte la valeur de `port` —
    déclaré, sinon homonyme, sinon ''. Un champ déclaré qui n'existe pas sur le modèle rend ''
    (la garde `tests_port_fields` le refuse : on ne lit jamais un champ fantôme)."""
    model = model if isinstance(model, type) else type(model)
    names = _field_names(model)
    listed = port_field_map(model).get(port)
    if listed:
        return listed if listed in names else ''
    return port if port in names else ''


def ports_sharing(model, field: str) -> list:
    """Les ports que le modèle range dans le MÊME champ `field` (déclarés), dans l'ordre déclaré."""
    model = model if isinstance(model, type) else type(model)
    return [p for p, f in port_field_map(model).items() if f == field]


def port_value(element, port: str):
    """La valeur de `port` sur `element` : le fichier (`FieldFile`) ou le texte du champ qui le
    porte — ou, pour un port sans colonne, le fichier de son PREMIER rang dans la table commune des
    entrées (`port_files`) ; None quand rien ne le garde, que le champ est vide, ou que le champ,
    partagé par plusieurs ports, porte un fichier d'une autre nature que celle du port."""
    field = port_field(element, port)
    if not field:
        files = port_files(element, port)
        return files[0] if files else None
    value = getattr(element, field, None)
    if not value:
        return None
    return value if _owned_by(value, port, ports_sharing(element, field)) else None


def _owned_by(value, port: str, sharing: list) -> bool:
    """Le fichier d'une colonne que gardent plusieurs ports (`sharing`) revient-il à `port` ? Au
    jeton que le fichier FOURNIT, d'après sa nature — la traduction que le tirage du modèle lit déjà
    (`input_match.work_token_for`, 2026-09-30) ; un fichier sans jeton dédié revient au premier port
    déclaré. Une colonne d'un seul port lui rend toujours son fichier."""
    if len(sharing) < 2:
        return True
    from wama.common.utils.input_match import work_token_for
    token = work_token_for(getattr(value, 'name', value))
    return (token if token in sharing else sharing[0]) == port


# ── LA TABLE COMMUNE DES ENTRÉES (`common.models.ElementInput`, 2026-11-25) ────────────────────────
# Un port sans colonne garde ses fichiers ici, un rang par fichier. Une seule vérité par port : un
# port que garde une colonne ne s'écrit jamais dans la table (`store_port_inputs` le range dans sa
# colonne, la règle d'avant). Adresse de la card : `process_runs.address`, celle de ses lignes
# d'exécution et de son pipeline étendu.

def _rows(element, port=None):
    from wama.common.models import ElementInput
    from wama.common.services.process_runs import address
    if getattr(element, 'pk', None) is None:
        return ElementInput.objects.none()
    rows = ElementInput.objects.filter(**address(element))
    return rows.filter(port=port) if port else rows


def input_rows(element, port=None) -> list:
    """Les lignes de la table commune des entrées de cette card (d'un port, ou de tous), par port
    puis par rang. `[]` pour un élément sans identifiant ; ne lève jamais."""
    try:
        return list(_rows(element, port).order_by('port', 'rank'))
    except Exception:
        return []


def port_files(element, port: str) -> list:
    """Les fichiers de `port` sur `element` : celui de sa colonne quand il en a une (0 ou 1 fichier,
    `port_value`), sinon ceux de ses lignes dans la table, par rang (N fichiers)."""
    if port_field(element, port):
        value = port_value(element, port)
        return [value] if value else []
    rows = [row.file for row in input_rows(element, port)]
    if rows:
        return rows
    value = _legacy_value(element, port)
    return [value] if value else []


def _legacy_value(element, port: str):
    """REPLI sur l'ancienne colonne d'un port passé dans la table (`legacy`) : la valeur qu'elle
    garde POUR CE PORT, ou None. Une colonne qu'ont partagée plusieurs ports rend son fichier au
    port que sa NATURE désigne (la règle de `port_value`)."""
    old = legacy_field(element, port)
    value = getattr(element, old, None) if old else None
    if not value:
        return None
    sharing = [p for p, f in ((_LEGACY.get(_label(element)) or {}).items()) if f == old]
    return value if _owned_by(value, port, sharing) else None


def store_port_inputs(element, port: str, received) -> int:
    """Range sur `element` (déjà créé) ce qu'il a REÇU sur `port` — des `ReceivedInput`
    (`media_paths.received_inputs` / `designate`), dans l'ordre. Le port a une colonne : le premier
    s'y pose, provenance comprise (`ReceivedInput.assign`, la règle d'avant). Sinon : un rang par
    fichier dans la table commune, qui REMPLACE les rangs précédents de ce port (ceux qu'ils
    portaient sont libérés, jamais effacés en silence). Un téléversement s'enregistre dans le
    dossier d'entrée de l'app de la card ; une désignation pose le chemin désigné. Rend le nombre
    de fichiers rangés."""
    from django.db import transaction
    received = [item for item in (received or []) if item is not None]
    field = port_field(element, port)
    if field:
        if received:
            received[0].assign(element, field)
        return 1 if received else 0
    from wama.common.models import ElementInput
    from wama.common.services.process_runs import address
    with transaction.atomic():
        release_inputs(element, port)
        # L'ancienne colonne d'un port passé dans la table (`legacy`) ne garde plus rien : son
        # fichier est remplacé — LIBÉRÉ comme tout fichier qu'une card lâche, la colonne vidée.
        old = legacy_field(element, port)
        if old and _legacy_value(element, port):
            from wama.common.utils.queue_duplication import release_card_file
            release_card_file(element, old)
            setattr(element, old, None)
            element.save(update_fields=[old])
        for rank, item in enumerate(received):
            row = ElementInput(**address(element), port=port, rank=rank,
                               original_name=(item.name or '')[:255], user_id=element.user_id)
            if item.designated:
                row.file = item.value
            else:
                row.file.save(item.name, item.value, save=False)
            row.save()
            # La PROVENANCE d'un fichier désigné, sous le nom du PORT (rien pour un téléversement :
            # il n'a pas de source dans WAMA) — comme `ReceivedInput.assign` pour une colonne.
            item.record(element, port)
    return len(received)


def store_by_nature(element, ports, received) -> str:
    """UNE entrée que plusieurs ports se disputent (l'avatar : photo OU objet 3D) : `received`
    (un `ReceivedInput`) se range sur celui des `ports` que sa NATURE désigne — la règle de
    `_owned_by`, un fichier sans jeton dédié allant au premier port —, et les autres ports sont
    VIDÉS (leurs fichiers libérés) : l'élément n'en garde qu'une. Rend le port choisi."""
    from wama.common.utils.input_match import work_token_for
    ports = list(ports)
    token = work_token_for(received.name)
    port = token if token in ports else ports[0]
    for other in ports:
        if other != port:
            store_port_inputs(element, other, [])
    store_port_inputs(element, port, [received])
    return port


def release_inputs(element, port=None) -> int:
    """La card part (ou un port est remplacé) : ses lignes de la table s'oublient, et chacun de
    leurs fichiers est LIBÉRÉ sous la règle de tout fichier d'une card
    (`queue_duplication.release_held_file` : il appartient à la card, aucune autre ligne ne le
    porte) — annoncé, jamais effacé en silence. Rend le nombre de fichiers libérés ; ne lève
    jamais."""
    released = 0
    try:
        from wama.common.utils.queue_duplication import release_held_file
        for row in input_rows(element, port):
            if release_held_file(element, row.file.name, holder=row, holder_field='file',
                                 origin=f'port {row.port}'):
                released += 1
            row.delete()
    except Exception:
        import logging
        logging.getLogger(__name__).warning('[port_fields] entrées de %s non libérées', element,
                                            exc_info=True)
    return released


def copy_inputs(source, target, *, own_files: bool = False) -> int:
    """La copie d'une card (`duplicate_instance`) porte les mêmes entrées : chaque ligne recopiée sur
    la copie — le MÊME fichier, partagé comme celui d'une colonne ; `own_files` (la copie d'une card
    REÇUE) : le fichier est recopié chez le propriétaire de la copie, qui ne désigne plus que les
    siens. Rend le nombre de lignes recopiées ; ne lève jamais."""
    copied = 0
    try:
        from django.core.files import File
        from wama.common.models import ElementInput
        from wama.common.services.process_runs import address
        for row in input_rows(source):
            new = ElementInput(**address(target), port=row.port, rank=row.rank,
                               original_name=row.original_name, user_id=target.user_id)
            if own_files:
                with row.file.open('rb') as handle:
                    new.file.save(row.original_name or row.file.name.rsplit('/', 1)[-1],
                                  File(handle), save=False)
            else:
                new.file = row.file.name
            new.save()
            copied += 1
    except Exception:
        import logging
        logging.getLogger(__name__).warning('[port_fields] entrées de %s non recopiées', source,
                                            exc_info=True)
    return copied
