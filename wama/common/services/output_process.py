"""Le process « SORTIE » d'une card — commun à toutes les apps qui rendent un fichier.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, marche P6 (2026-10-03, décision de Fabien : « garder
l'image d'origine dans la brique de sortie, pour les cinq apps concernées à la fois »).

Une app render-based a deux temps : ce que son MOTEUR écrit (une image, une vidéo, une voix, une
musique, un média flouté…), puis ses réglages de SORTIE (agrandissement, format, qualité).
Jusque-là les deux vivaient dans la même glu : changer de format obligeait à tout rejouer. Ici le
second temps devient un process à part, le MÊME pour toutes :

    PIPELINE = register_app_pipeline('mon_app', (
        ProcessSpec('generate', …),
        output_spec(depends_on=('generate',)),
    ), …)
    PROCESSES = {'generate': _generate, 'output': output_step('audio_output', domain='audio',
                                                              app_id='mon_app')}

La glu du moteur n'a que trois gestes à connaître : `drop_previous_outputs` avant de rendre,
`generated(...)` pour son retour, et l'enveloppe de tâche appelle `forget_lost_generation`.

Ce que la brique tient pour l'app : le fichier d'origine est gardé tant que la sortie le
transforme (`output_formats.render_outputs`, champ `native_outputs` du mixin
`NativeOutputsMixin`) ; la sortie rejouée seule repart de lui ; une sortie qui échoue laisse la
génération intacte ; des originaux disparus font rejouer la génération.
"""
import os

from django.conf import settings

from wama.common.utils.file_references import relative_to_media
from wama.common.utils.output_formats import NATIVE_FIELD, OUTPUT_PARAM_NAMES, render_outputs

#: Clé du process de sortie dans le pipeline d'une app, et libellé de sa ligne sur la card.
OUTPUT_KEY = 'output'
OUTPUT_LABEL = 'Sortie'


def output_spec(depends_on, *, key: str = OUTPUT_KEY, label: str = OUTPUT_LABEL, share: int = 1):
    """Le `ProcessSpec` du process de sortie : il surveille les réglages de sortie communs
    (`OUTPUT_PARAM_NAMES`) et dépend du process qui écrit le fichier. Il a TOUJOURS lieu : c'est
    en revenant au format d'origine qu'il rend l'original tel quel."""
    from wama.common.services.process_pipeline import ProcessSpec
    return ProcessSpec(key, label=label, depends_on=tuple(depends_on),
                       watched=tuple(OUTPUT_PARAM_NAMES), share=share)


def _absolute(path) -> str:
    path = str(path)
    return path if os.path.isabs(path) else os.path.join(settings.MEDIA_ROOT, path)


def _field_of(item, field) -> str:
    return field(item) if callable(field) else field


def rendered_files(item, field) -> list:
    """Les rendus que la card porte aujourd'hui dans `field`, en chemins absolus — un champ
    fichier (un rendu) ou une liste de chemins (les images de l'imager)."""
    value = getattr(item, _field_of(item, field), None)
    if isinstance(value, (list, tuple)):
        return [_absolute(p) for p in value if p]
    return [value.path] if value else []


def output_sources(item, field) -> list:
    """Ce dont le process de sortie REPART : les originaux gardés quand il y en a (le rendu a
    été transformé), sinon les rendus eux-mêmes — ils SONT alors l'original."""
    kept = [_absolute(p) for p in (getattr(item, NATIVE_FIELD, None) or [])]
    return kept or rendered_files(item, field)


def files_fingerprint(paths) -> str:
    """Empreinte de ce que le moteur a écrit — DÉCLARÉE à la ligne d'exécution (`output_fingerprint`
    du retour de glu) plutôt que lue d'un chemin : le process de sortie déplace l'original, un
    `output_ref` se perdrait et ferait rejouer la génération."""
    from wama.common.services.revisions import text_fingerprint
    from wama.common.utils.provenance import sha256_of
    marks = []
    for path in paths:
        path = str(path)
        mark = sha256_of(path)
        if not mark:
            mark = f'size:{os.path.getsize(path)}' if os.path.isfile(path) else f'missing:{path}'
        marks.append(mark)
    return text_fingerprint('|'.join(marks))


def _replaceable(item, path, holder: str) -> bool:
    """Ce fichier peut-il être REMPLACÉ par sa card ? Les deux règles de
    `queue_duplication.safe_delete_file`, appliquées à un chemin (il vaut aussi pour une liste
    de chemins, qui n'est pas un `FileField`) : le fichier vit chez l'app de la card
    (`owns_file`), et aucune autre ligne ne le désigne. Dans le doute, non : rien ne se perd."""
    from wama.common.utils.file_references import is_referenced_elsewhere
    from wama.common.utils.queue_duplication import owns_file
    try:
        name = relative_to_media(path)
        return (owns_file(item, name)
                and not is_referenced_elsewhere(name, label=item._meta.label, pk=item.pk,
                                                field=holder))
    except Exception:
        return False


def drop_previous_outputs(item, field, keep=()) -> None:
    """Le moteur REJOUE : les originaux gardés et les rendus de la fois d'avant qu'il n'a pas
    réécrits sont retirés (un `.webp` d'un ancien réglage). Un fichier qu'une AUTRE card désigne
    encore (duplication), ou qui ne vit pas chez l'app de la card, est laissé — les deux règles
    de `queue_duplication.safe_delete_file`."""
    kept = {os.path.abspath(str(p)) for p in keep}
    name = _field_of(item, field)
    previous = [(_absolute(p), NATIVE_FIELD) for p in (getattr(item, NATIVE_FIELD, None) or [])]
    previous += [(path, name) for path in rendered_files(item, name)]
    for path, holder in previous:
        if os.path.abspath(path) in kept or not os.path.isfile(path):
            continue
        if _replaceable(item, path, holder):
            os.remove(path)


def generated(paths, **result) -> dict:
    """Le retour d'une glu de MOTEUR, complété de ce que la brique attend d'elle : plus aucun
    original gardé (ils datent de la génération d'avant), et l'empreinte de ce qui vient d'être
    écrit à la place d'un `output_ref`. `result` : le reste du retour (fields, label, models…)."""
    fields = dict(result.pop('fields', None) or {})
    fields[NATIVE_FIELD] = []
    result.pop('output_ref', None)
    return {**result, 'fields': fields, 'output_fingerprint': files_fingerprint(paths)}


def forget_lost_generation(item, field, node: str) -> bool:
    """La sortie repart des fichiers que le moteur a laissés. S'ils ne sont plus là (retirés,
    rangés ailleurs), un process moteur « à jour » ne sert plus à rien : sa ligne est oubliée, le
    lancement le rejouera. À appeler par l'enveloppe de tâche, avant le squelette."""
    sources = output_sources(item, field)
    if sources and all(os.path.isfile(p) for p in sources):
        return False
    from wama.common.services import process_runs
    process_runs.safely(lambda: process_runs.lines(item).filter(node_id=node).delete())
    return True


def output_step(field, *, domain, app_id: str, console=None, extra_fields=None,
                format_of=None):
    """La GLU du process de sortie, au contrat du squelette (`glu(item, ctx) -> dict`).

    `field`  : le champ qui porte le rendu (nom, ou `callable(item) -> nom`) ;
    `domain` : 'image' | 'video' | 'audio' | … (ou `callable(item)`) — ce que lit
               `output_formats` pour savoir si l'agrandissement vaut ;
    `console`: `callable(item, message)` pour dire ce qui est fait dans la console de l'app ;
    `extra_fields` : `callable(item, finals) -> dict` — champs propres que l'app pose avec son
               rendu (une heure de fin, des dimensions relevées sur le fichier final) ;
    `format_of` : `callable(item, source) -> format` quand le réglage de l'app n'est pas un
               format à lui seul (l'anonymizer : « le format de l'entrée ») — elle le RÉSOUT.

    Un agrandissement DEMANDÉ qui échoue lève (la card s'arrête en le disant, le moteur n'est
    pas rejoué au ▶ suivant) ; une conversion ratée garde le format d'origine et le dit."""

    def step(item, ctx):
        name = _field_of(item, field)
        sources = output_sources(item, name)
        if not sources or not all(os.path.isfile(p) for p in sources):
            raise RuntimeError("Réglages de sortie : fichier d'origine introuvable — relancer "
                               "le traitement.")
        ctx.progress(10)
        say = (lambda message: console(item, message)) if console else ctx.console
        try:
            finals, natives = render_outputs(
                sources, item, domain=domain(item) if callable(domain) else domain,
                app_id=app_id, console=say,
                output_format=format_of(item, sources[0]) if format_of else None,
                previous=[p for p in rendered_files(item, name) if _replaceable(item, p, name)])
        except Exception as exc:
            ctx.reset_progress()
            raise RuntimeError(f"Réglages de sortie : {exc}") from exc
        listed = isinstance(getattr(item, name, None), (list, tuple))
        fields = {NATIVE_FIELD: [relative_to_media(p) for p in natives],
                  name: list(finals) if listed else relative_to_media(finals[0])}
        if extra_fields is not None:
            fields.update(extra_fields(item, finals) or {})
        return {
            'fields': fields,
            'label': ', '.join(os.path.basename(p) for p in finals),
            'output_ref': relative_to_media(finals[0]),
        }

    return step
