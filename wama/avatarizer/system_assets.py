"""Les travaux de l'avatarizer citent un avatar de GALERIE par son NOM (`avatar_gallery_name`).

Cette référence ne se voit pas par le chemin : quand la médiathèque rend un avatar système à son
auteur (`media_library.services.return_system_asset`, 2026-09-29), c'est ici qu'on la fait
suivre. Les travaux de l'auteur passent sur le fichier rendu (`avatar_upload`, un pointeur) et
restent relançables ; ceux d'un AUTRE utilisateur ne sont jamais touchés — ils sont comptés, et
la médiathèque refuse alors l'opération.
"""


#: Les NATURES où un avatar se cherche par son nom, dans l'ordre (2026-09-30) : la photo (moteur
#: MuseTalk), puis l'objet 3D (moteur TalkingHead — un avatar riggé est un `object3d`). Un nom
#: présent dans les deux désigne la photo, comme avant l'arrivée des avatars 3D.
AVATAR_NATURES = ('avatar', 'object3d')


def designate_named_avatar(name, user):
    """L'avatar `name`, désigné comme le fait la card : pointé, jamais recopié (2026-09-29).

    Le NOM reste la façon dont un lot, un nœud du Studio ou l'assistant citent un avatar ; il se
    résout parmi ce que l'utilisateur VOIT (`resolve_visible_asset` : les siens, les partagés, le
    système), photo ou objet 3D (`AVATAR_NATURES`), et le job reçoit le FICHIER (`avatar_upload`),
    comme depuis la card. Plus aucun job neuf ne stocke un nom de galerie. Lève `InputRefused`
    si l'avatar est introuvable."""
    from wama.common.utils.media_paths import InputRefused, designate
    from wama.media_library.services import resolve_visible_asset
    for nature in AVATAR_NATURES:
        path = resolve_visible_asset(user, nature, name)
        if path:
            return designate(path, user, 'avatarizer')
    raise InputRefused(f"Avatar introuvable dans la médiathèque : {name}")


def gallery_name_holder(name, user, new_path, apply):
    """Holder déclaré à `register_system_asset_name_holder('avatar', …)`."""
    from .models import AvatarJob
    named = AvatarJob.objects.filter(avatar_source='gallery', avatar_gallery_name=name)
    mine = named.filter(user=user)
    count = mine.count()
    if apply and new_path:
        mine.update(avatar_source='upload', avatar_upload=new_path, avatar_gallery_name='')
    return {'label': "avatarizer — travaux qui citent l'avatar par son nom",
            'mine': count, 'others': named.exclude(user=user).count()}
