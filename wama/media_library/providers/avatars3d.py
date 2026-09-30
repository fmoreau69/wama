"""
WAMA Media Library — Avatars 3D (GLB riggés) publiés dans des dépôts GitHub.

Source de la médiathèque pour le moteur `talkinghead` de l'avatarizer (2026-09-30, décision de
Fabien : « commencer par la galerie proposée, l'ajouter dans les sources, et permettre d'en
ajouter d'autres »). Aucune clé : l'API GitHub publique liste le dossier, le fichier se
télécharge depuis `raw.githubusercontent.com`.

AJOUTER UNE SOURCE = UNE LIGNE dans `AVATAR_REPOSITORIES` : le dépôt, le dossier, et les
licences telles que le dépôt les PUBLIE. Un fichier dont la licence n'est déclarée ni par
fichier ni pour le dépôt n'est PAS proposé — un avatar part dans des vidéos diffusées, on ne
l'importe pas sans savoir ce qu'on a le droit d'en faire.

Un avatar importé est un `object3d` (pas une nature à part) : ses attributs de visage
(`face_rig`, `visemes`) sont MESURÉS dans le fichier à l'ingest (`media_probe`), et c'est sur eux
que le moteur juge s'il peut le faire parler (`input_attributes`).
"""

import json
from dataclasses import dataclass, field
from typing import Dict, Tuple

from .base import BaseProvider, SearchResult


@dataclass(frozen=True)
class AvatarRepository:
    """Un dépôt qui publie des avatars GLB. `files` : fichier → (licence, auteur), relevés dans le
    dépôt ; `license`/`author` : ce qui vaut pour tout fichier non listé ('' = rien)."""
    repo: str
    path: str
    ref: str = 'main'
    license: str = ''
    author: str = ''
    files: Dict[str, Tuple[str, str]] = field(default_factory=dict)


#: Relevé le 2026-09-30 dans le README de TalkingHead (section « Licenses, attributions ») : seul
#: `mpfb.glb` est libre (CC0) ; les autres sont réservés à un usage NON COMMERCIAL — admis au
#: labo, à ne pas diffuser commercialement.
AVATAR_REPOSITORIES: Tuple[AvatarRepository, ...] = (
    AvatarRepository(
        'met4citizen/TalkingHead', 'avatars',
        files={
            'mpfb.glb': ('CC0', 'MPFB (MakeHuman) — Blender'),
            'brunette.glb': ('CC BY-NC 4.0', 'Ready Player Me'),
            'brunette-t.glb': ('CC BY-NC 4.0', 'Ready Player Me'),
            'avaturn.glb': ('Usage non commercial', 'Avaturn'),
            'avatarsdk.glb': ('Usage non commercial', 'AvatarSDK'),
            'vroid.glb': ('Usage non commercial', 'VRoid Studio'),
        }),
)

#: Durée de cache d'un listing : l'API GitHub anonyme accorde 60 requêtes/heure par adresse.
LISTING_TTL_S = 3600
#: Cache PROPRE AU PROCESSUS (clé → (instant, entrées)) — pas le cache Django : en WSL c'est le
#: Redis réel, qu'un test ne doit pas remplir, et qui rendrait les gardes dépendantes de l'ordre.
_LISTINGS: dict = {}


class Avatars3dProvider(BaseProvider):
    slug             = 'avatars3d'
    name             = 'Avatars 3D (dépôts GitHub)'
    supported_types  = ['object3d']
    requires_api_key = False
    download_domains = ('raw.githubusercontent.com',)

    def _listing(self, source: AvatarRepository) -> list:
        """Les entrées `.glb` du dossier, par l'API GitHub (mises en cache une heure)."""
        import time
        key = (self.base_url(), source.repo, source.path, source.ref)
        cached = _LISTINGS.get(key)
        if cached and time.monotonic() - cached[0] < LISTING_TTL_S:
            return cached[1]
        url = f'{self.base_url()}/repos/{source.repo}/contents/{source.path}?ref={source.ref}'
        with self.open_url(url, timeout=15, headers={'Accept': 'application/vnd.github+json'}) as r:
            payload = json.loads(r.read())
        if not isinstance(payload, list):
            raise ValueError(f"réponse inattendue de l'API GitHub : {str(payload)[:120]}")
        entries = [e for e in payload
                   if e.get('type') == 'file' and e.get('name', '').lower().endswith('.glb')]
        _LISTINGS[key] = (time.monotonic(), entries)
        return entries

    def search(self, query: str, asset_type: str, page: int = 1, per_page: int = 20) -> dict:
        if asset_type not in self.supported_types:
            return {'results': [], 'total': 0, 'has_more': False}
        wanted = (query or '').strip().lower()
        wanted = '' if wanted in ('*', 'avatar', 'avatars') else wanted
        results, errors = [], []
        for source in AVATAR_REPOSITORIES:
            try:
                entries = self._listing(source)
            except Exception as exc:
                errors.append(f'{source.repo} : {exc}')
                continue
            for e in entries:
                license_, author = source.files.get(e['name'], (source.license, source.author))
                if not license_:
                    continue                      # licence inconnue : jamais proposé
                title = e['name'].rsplit('.', 1)[0]
                haystack = f"{title} {license_} {author} {source.repo}".lower()
                if wanted and wanted not in haystack:
                    continue
                results.append(SearchResult(
                    provider_id=f"{source.repo}/{e['path']}", title=title, preview_url='',
                    download_url=e.get('download_url') or '', asset_type='object3d',
                    license=license_, author=author, file_size=int(e.get('size') or 0),
                    tags=f'avatar,3d,glb,{source.repo}'))
        start = (page - 1) * per_page
        out = {'results': results[start:start + per_page], 'total': len(results),
               'has_more': start + per_page < len(results)}
        if errors and not results:
            out['error'] = ' ; '.join(errors)
        return out
