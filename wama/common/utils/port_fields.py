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
  1. la DÉCLARATION du modèle d'élément, `WAMA_PORT_FIELDS = {port: champ}` — à côté de
     `WAMA_INGEST`, même nature (une donnée du modèle, lue par les briques). Elle ne porte QUE les
     ports dont le champ ne porte pas le nom : c'est la liste des écarts hérités, qui ne doit que
     baisser ;
  2. sinon un champ HOMONYME du port (les apps nées d'un manifeste nomment déjà leurs colonnes
     ainsi : `reference_layout` du Writer, `work_result` du transcriber) ;
  3. sinon '' — le port n'a pas de champ (porté par un réglage, une capture en direct…).

UN CHAMP POUR PLUSIEURS PORTS (l'avatar de l'avatarizer : la photo de MuseTalk ou l'objet 3D de
TalkingHead dans `avatar_upload`) : la valeur ne revient qu'au port que le fichier FOURNIT d'après
sa nature (`input_match.work_token_for`, la traduction que lit déjà le tirage du modèle) — le
stockage hérité ne fait pas mentir le lecteur. ⚠ C'est une lecture du stockage d'AUJOURD'HUI, pas
une forme à imiter : la cible qui ne bloque aucune évolution est que la valeur d'un port ne demande
AUCUNE colonne (une nature de plus = un port de plus, sans migration) — `INPUT_MODEL_MATCHING §6.13`.
"""
from __future__ import annotations


def port_field_map(model) -> dict:
    """`{port: champ}` que le modèle d'élément DÉCLARE (`WAMA_PORT_FIELDS`), ou {}."""
    return dict(getattr(model, 'WAMA_PORT_FIELDS', None) or {})


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
    porte ; None quand le port n'a pas de champ, que le champ est vide, ou que le champ, partagé
    par plusieurs ports, porte un fichier d'une autre nature que celle du port."""
    field = port_field(element, port)
    if not field:
        return None
    value = getattr(element, field, None)
    if not value:
        return None
    sharing = ports_sharing(element, field)
    if len(sharing) > 1:
        # Le jeton que le fichier FOURNIT, d'après sa nature — la traduction que le tirage du
        # modèle lit déjà (`input_match.work_token_for`, 2026-09-30) ; un fichier sans jeton dédié
        # revient au premier port déclaré.
        from wama.common.utils.input_match import work_token_for
        token = work_token_for(getattr(value, 'name', value))
        owner = token if token in sharing else sharing[0]
        if owner != port:
            return None
    return value
