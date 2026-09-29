"""Les travaux de l'avatarizer citent un avatar de GALERIE par son NOM (`avatar_gallery_name`).

Cette référence ne se voit pas par le chemin : quand la médiathèque rend un avatar système à son
auteur (`media_library.services.return_system_asset`, 2026-09-29), c'est ici qu'on la fait
suivre. Les travaux de l'auteur passent sur le fichier rendu (`avatar_upload`, un pointeur) et
restent relançables ; ceux d'un AUTRE utilisateur ne sont jamais touchés — ils sont comptés, et
la médiathèque refuse alors l'opération.
"""


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
