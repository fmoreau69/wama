"""PROVENANCE D'UNE ENTRÉE — d'où vient le fichier qu'une card consomme.

Le LIEN qui manquait entre la source de vérité (médiathèque, temp, montage, URL) et la copie
de travail d'une card. Décision Fabien du 2026-09-07, motivée dans `MEDIA_STORAGE_TIERING §8.7`
et dans la docstring du modèle `common.models.InputProvenance`.

CE QUE CE MODULE FAIT, ET CE QU'IL NE FAIT PAS
    Il ENREGISTRE et il RELIT. Il ne copie rien, ne supprime rien, ne décide de rien : les
    briques d'import gardent leur travail, elles gagnent seulement la mémoire de ce qu'elles
    ont fait. C'est délibéré — `send_to.py` a montré la bonne forme, « ce module ne fait que
    les relier ».

⚠ AUCUNE APP N'ÉCRIT SA RÈGLE ICI. Les appelants, tels que câblés au 2026-09-22 :
    `copy_into_app_input` (quand on lui donne l'élément), le répartiteur « Envoyer vers » du
    gestionnaire de fichiers (`record_origin`, une fois pour les 11 importeurs et leurs jumelles),
    `ensure_local_input` (URL matérialisée), et les deux lots `-i` qui copient une ligne serveur
    (converter, anonymizer — un APPEL, pas une règle). ⚠ Pas encore câblés : l'upload direct
    depuis le poste (aucune source dans WAMA : il ne sert que la dédup par empreinte) et le lot
    `-i` du gabarit GÉNÉRÉ (`views_gen`). Une app qui écrirait sa provenance elle-même rouvrirait
    les graphies divergentes que ce dépôt vient de fermer ailleurs.

⚠ UN ÉCHEC D'ENREGISTREMENT NE FAIT JAMAIS ÉCHOUER UN IMPORT. La provenance est une
    information SUR le geste, pas le geste : perdre la trace est regrettable, perdre le fichier
    de l'utilisateur ne l'est pas. Même règle que la copie `-o` de `BATCH_FORMAT` (« une copie
    qui échoue ne fait PAS échouer le job »).
"""
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Taille de lecture pour l'empreinte — un fichier média se compte en Go, on ne le charge pas.
_BLOC = 1024 * 1024

#: Au-delà, on n'empreinte pas : lire 8 Go depuis un montage SMB pour une trace coûterait plus
#: que ce que la trace rapporte. L'absence d'empreinte est un FAIT enregistré, pas un échec —
#: `sha256` vide veut dire « non calculée », jamais « fichier vide ».
SEUIL_EMPREINTE_OCTETS = 512 * 1024 * 1024


def sha256_of(chemin, *, limite=SEUIL_EMPREINTE_OCTETS):
    """Empreinte d'un fichier, ou `''` s'il est trop gros / illisible. Ne lève jamais."""
    try:
        p = Path(chemin)
        if not p.is_file() or p.stat().st_size > limite:
            return ''
        h = hashlib.sha256()
        with p.open('rb') as fh:
            for bloc in iter(lambda: fh.read(_BLOC), b''):
                h.update(bloc)
        return h.hexdigest()
    except Exception:
        return ''


def record_provenance(instance, field, *, kind, ref='', original_name='',
                      source_path=None, user=None):
    """Enregistre d'où vient `instance.<field>`. Remplace la trace existante, ne l'empile pas.

    Args:
        instance : l'élément porteur de l'entrée (une card d'app).
        field    : nom du `FileField` — avec `object_type`/`object_id`, c'est exactement
                   l'adresse que `safe_delete_file` manipule déjà.
        kind     : l'un de `InputProvenance.KIND_CHOICES`.
        ref      : adresse de la SOURCE dans le vocabulaire de son `kind`.
        source_path : si donné, sert à calculer taille et empreinte (jamais obligatoire).
    Returns:
        L'objet `InputProvenance`, ou `None` si l'enregistrement a échoué (jamais d'exception).
    """
    try:
        from wama.common.models import InputProvenance

        proprietaire = user or getattr(instance, 'user', None)
        if proprietaire is None:
            return None

        taille, empreinte = 0, ''
        if source_path:
            try:
                taille = Path(source_path).stat().st_size
            except Exception:
                taille = 0
            empreinte = sha256_of(source_path)

        obj, _ = InputProvenance.objects.update_or_create(
            object_type=type(instance).__name__,
            object_id=instance.pk,
            field=field,
            defaults={
                'app': instance._meta.app_label,
                'kind': kind,
                'ref': ref or '',
                'original_name': original_name or (Path(source_path).name if source_path else ''),
                'sha256': empreinte,
                'size': taille,
                'user': proprietaire,
            },
        )
        return obj
    except Exception as exc:                       # cf. l'avertissement en tête de module
        logger.debug("record_provenance ignoré (%s.%s) : %s",
                     type(instance).__name__, field, exc)
        return None


def ref_for(source_path):
    """Adresse d'une source : son chemin relatif à `MEDIA_ROOT` s'il y vit, sinon son chemin brut.

    Une seule règle de calcul, partagée par les deux moitiés de la brique — `copy_into_app_input`
    quand elle connaît déjà l'instance, et `record_import` quand l'instance naît après la copie.
    Deux calculs divergeraient, et l'index inverse cesserait de retrouver ses sources.
    """
    try:
        from django.conf import settings
        rel = Path(source_path).resolve().relative_to(Path(settings.MEDIA_ROOT).resolve())
        return str(rel).replace('\\', '/')
    except Exception:
        return str(source_path)


def record_import(instance, field, source_path, *, kind='temp'):
    """La moitié complémentaire de `copy_into_app_input`, pour le motif « copier PUIS créer ».

    Les importeurs du gestionnaire de fichiers copient d'abord et créent l'élément ensuite :
    l'instance n'existe pas encore au moment de la copie, donc la brique ne peut pas enregistrer
    seule. Cet appelant-ci n'ajoute AUCUNE logique — il dérive `ref` par la même fonction et
    délègue. Répéter l'APPEL dans chaque importeur est acceptable (c'est ce que fait déjà
    `safe_delete_file`) ; répéter la RÈGLE ne le serait pas.
    """
    return record_provenance(instance, field, kind=kind, ref=ref_for(source_path),
                             original_name=Path(source_path).name, source_path=source_path)


def record_origin(copy_path, *, kind, ref, source_path=None):
    """La provenance de TOUTES les cards qui portent cette copie, retrouvées par son chemin.

    Pour les appelants qui ne tiennent pas l'élément : le répartiteur « Envoyer vers » ne reçoit
    de ses importeurs que le chemin de la copie (`result['path']`). Plutôt que de répéter l'appel
    dans chacun des importeurs — 1 sur 11 le faisait (2026-09-22) —, il l'enregistre ici une fois
    pour tous, jumelles comprises. Aucune logique propre : l'index des références directes
    retrouve les cards, `record_provenance` écrit. Ne lève jamais ; rend le nombre de traces.
    """
    try:
        from django.apps import apps as django_apps
        from wama.common.utils.file_references import direct_references
        written = 0
        for r in direct_references(copy_path):
            instance = django_apps.get_model(r['label']).objects.filter(pk=r['pk']).first()
            if instance is not None and record_provenance(
                    instance, r['field'], kind=kind, ref=ref,
                    original_name=Path(source_path).name if source_path else '',
                    source_path=source_path) is not None:
                written += 1
        return written
    except Exception as exc:                       # cf. l'avertissement en tête de module
        logger.debug("record_origin ignoré (%s) : %s", copy_path, exc)
        return 0


def kind_of(media_path) -> str:
    """La nature d'une source désignée par son chemin dans le gestionnaire de fichiers.

    `mounts/<id>/…` → `mount` ; `users/<u>/temp/…` → `temp` ; tout autre chemin sous
    `MEDIA_ROOT` est le fichier d'une app (l'entrée ou la sortie d'une autre card : « Envoyer
    vers » chaîne describer → imager → enhancer) → `app`.
    """
    p = str(media_path or '').replace('\\', '/')
    if p.startswith('mounts/'):
        return 'mount'
    parts = p.split('/')
    if len(parts) > 2 and parts[0] == 'users' and parts[2] == 'temp':
        return 'temp'
    return 'app'


def provenance_of(instance, field):
    """La provenance d'une entrée, ou `None`. Ne lève jamais."""
    try:
        from wama.common.models import InputProvenance
        return InputProvenance.objects.filter(
            object_type=type(instance).__name__, object_id=instance.pk, field=field).first()
    except Exception:
        return None


def referenced_by(kind, ref):
    """L'INDEX INVERSE — quelles entrées de cards désignent cette source ?

    C'est la question que le gestionnaire de fichiers doit poser AVANT de supprimer, et elle
    n'avait aucune réponse jusqu'ici. Elle lève la seule objection qui tenait encore contre le
    pointage (`§8.7` (a) : « supprimer l'original casse la card ») — non pas en empêchant la
    suppression, mais en la rendant INFORMÉE : on conserve la card et on dit à l'utilisateur
    que sa source a disparu (décision Fabien, 2026-09-11).
    """
    try:
        from wama.common.models import InputProvenance
        return list(InputProvenance.objects.filter(kind=kind, ref=ref)
                    .order_by('app', 'object_type', 'object_id'))
    except Exception:
        return []


def same_source(kind, ref, user):
    """Une copie de cette même source existe-t-elle déjà pour cet utilisateur ?

    La base de la DÉDUPLICATION par provenance (« même source, même copie »). Mesuré le
    2026-09-11 : chaîner describer → imager → enhancer par « Envoyer vers » produit aujourd'hui
    TROIS copies des mêmes octets. Rend la provenance la plus ancienne, ou `None`.

    ⚠ Ne déduplique RIEN par elle-même : elle RÉPOND. Le choix de réutiliser la copie
    existante appartient à l'appelant, parce qu'il dépend du régime (une card en cours de
    traitement ne doit pas voir son entrée partagée sous ses pieds).
    """
    try:
        from wama.common.models import InputProvenance
        return (InputProvenance.objects.filter(kind=kind, ref=ref, user=user)
                .order_by('created_at').first())
    except Exception:
        return None
