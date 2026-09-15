"""
Chiffrement RÉVERSIBLE des secrets d'utilisateur stockés en base — clés d'API de fournisseurs
cloud (ROADMAP §8d Phase 3, étape 4 ; décisions de Fabien du 2026-09-15).

POURQUOI RÉVERSIBLE : WAMA doit RELIRE la clé pour appeler le fournisseur à la place de
l'utilisateur. Un hachage (comme pour un mot de passe) ne le permettrait pas. Ce n'est donc PAS
la bonne brique pour un secret que WAMA ne fait que VÉRIFIER (le jeton d'API DRF, cherché par sa
valeur) : celui-là ne passe pas par ici.

LA CLÉ : DÉRIVÉE DE `SECRET_KEY` (décision Fabien : pas de clé de plus dans `.env`), par HKDF avec
une étiquette d'usage propre — on ne chiffre pas avec la valeur qui signe les sessions, mais avec
une clé qui en dérive et ne sert qu'à ça.

⚠ LA ROTATION DE `SECRET_KEY` EST LE PIÈGE. `rotate_secrets` déplace l'ancienne clé dans
`SECRET_KEY_FALLBACKS` et n'en garde que TROIS (`rotate_secrets.py:199`). Le déchiffrement essaie la
clé courante puis les fallbacks, ce qui suffit juste après une rotation ; mais une donnée chiffrée
avec une clé sortie des fallbacks deviendrait illisible, SANS ERREUR au moment de la rotation. D'où
`reencrypt()`, que la rotation appelle sur chaque secret stocké : après elle, plus rien ne dépend
d'une ancienne clé.

⚠ REFUS de chiffrer avec une clé non sûre : `settings.py` retombe sur un placeholder
`django-insecure-…` quand `.env` ne pose pas `DJANGO_SECRET_KEY` (dépôt PUBLIC : ce placeholder est
lisible par tous). Des clés chiffrées avec lui seraient lisibles par n'importe qui.
"""
from __future__ import annotations

import base64

#: Étiquette d'usage de la dérivation. La changer rendrait illisibles les secrets existants : elle
#: est versionnée, jamais modifiée en place.
PURPOSE = b'wama.user-secrets.v1'
#: Préfixe des clés Django NON sûres (convention de Django lui-même, et placeholder de settings.py).
INSECURE_PREFIX = 'django-insecure'


class SecretStorageUnavailable(RuntimeError):
    """Chiffrement refusé : aucune clé sûre (placeholder de développement). Message pour l'humain."""


class SecretUnreadable(ValueError):
    """Déchiffrement impossible : ni la clé courante ni les fallbacks ne le lisent."""


def _fernet(secret: str):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=PURPOSE,
                   info=b'fernet').derive((secret or '').encode('utf-8'))
    return Fernet(base64.urlsafe_b64encode(derived))


def _is_insecure(secret: str) -> bool:
    return not secret or secret.startswith(INSECURE_PREFIX)


def _keys(current: str | None = None, fallbacks=None) -> list:
    from django.conf import settings
    current = settings.SECRET_KEY if current is None else current
    fallbacks = list(getattr(settings, 'SECRET_KEY_FALLBACKS', []) or []) if fallbacks is None else list(fallbacks)
    return [current] + [k for k in fallbacks if k and k != current]


def storage_available() -> bool:
    """Peut-on enregistrer un secret maintenant ? (clé courante sûre)"""
    return not _is_insecure(_keys()[0])


def encrypt(plaintext: str) -> str:
    """Chiffre avec la clé COURANTE. Lève `SecretStorageUnavailable` sur une clé non sûre."""
    current = _keys()[0]
    if _is_insecure(current):
        raise SecretStorageUnavailable(
            "Enregistrement des clés d'API indisponible : DJANGO_SECRET_KEY n'est pas définie "
            "dans .env (clé de développement publique).")
    return _fernet(current).encrypt((plaintext or '').encode('utf-8')).decode('ascii')


def decrypt(token: str) -> str:
    """Déchiffre par la clé courante, puis par les `SECRET_KEY_FALLBACKS`."""
    from cryptography.fernet import InvalidToken, MultiFernet
    try:
        return MultiFernet([_fernet(k) for k in _keys()]).decrypt(
            (token or '').encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError) as exc:
        raise SecretUnreadable("secret illisible avec la clé courante et ses fallbacks") from exc


def reencrypt(token: str, new_secret: str, old_secrets) -> str:
    """Rechiffre `token` avec la clé dérivée de `new_secret`, en le lisant par `new_secret` ou
    l'une des `old_secrets`. Appelé par la rotation de `SECRET_KEY`, qui connaît la nouvelle clé
    AVANT que les réglages du process ne la voient."""
    from cryptography.fernet import InvalidToken, MultiFernet
    if _is_insecure(new_secret):
        raise SecretStorageUnavailable("rechiffrement refusé : nouvelle clé non sûre")
    readers = [_fernet(k) for k in [new_secret, *old_secrets] if k]
    try:
        plaintext = MultiFernet(readers).decrypt((token or '').encode('ascii'))
    except (InvalidToken, ValueError) as exc:
        raise SecretUnreadable("secret illisible : aucune des clés fournies ne le lit") from exc
    return _fernet(new_secret).encrypt(plaintext).decode('ascii')
