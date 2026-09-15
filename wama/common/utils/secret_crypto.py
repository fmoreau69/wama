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
import logging

from django.db import models

logger = logging.getLogger(__name__)

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


class EncryptedTextField(models.TextField):
    """Champ texte CHIFFRÉ au repos : l'ORM lit et écrit le CLAIR, la base ne voit que le jeton.

    ⚠ Aucune recherche sur la valeur, SAUF le vide : un jeton Fernet change à chaque chiffrement,
    `filter(api_key='sk-…')` ne trouverait jamais rien. Le vide reste vide (jamais chiffré) — c'est
    ce qui garde vrai `exclude(api_key='')` pour dire « une clé est posée ».
    ⚠ Un jeton illisible se lit comme VIDE, avec une erreur au journal : la page doit s'afficher et
    l'utilisateur ressaisit sa clé. `reencrypt_stored_secrets` est ce qui évite d'en arriver là.
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        return encrypt(value)

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return decrypt(value)
        except SecretUnreadable:
            logger.error("[secret_crypto] %s.%s illisible avec la clé courante et ses fallbacks",
                         self.model._meta.label, self.name)
            return ''


def encrypted_columns() -> list:
    """(modèle, champ) de chaque `EncryptedTextField` des modèles installés. La rotation les trouve
    SEULE : un champ chiffré ajouté demain n'a rien à déclarer ailleurs."""
    from django.apps import apps
    return [(model, field) for model in apps.get_models() for field in model._meta.local_fields
            if isinstance(field, EncryptedTextField)]


def reencrypt_stored_secrets(new_secret: str, old_secrets, using: str = 'default') -> dict:
    """Rechiffre en base chaque secret stocké vers la clé dérivée de `new_secret`.

    SQL BRUT, pas l'ORM : l'ORM déchiffrerait puis rechiffrerait avec la clé COURANTE du process —
    celle qu'on quitte. À appeler dans la MÊME transaction que l'écriture de la nouvelle clé
    (`rotate_secrets`) : si la clé n'est pas écrite, les jetons ne doivent pas avoir changé.

    Rend `{'reencrypted': n, 'unreadable': [(modèle, pk), …]}`. Un jeton illisible est laissé tel
    quel — il l'était déjà avant la rotation — et signalé.
    """
    from django.db import connections
    conn = connections[using]
    qn = conn.ops.quote_name
    done, unreadable = 0, []
    with conn.cursor() as cur:
        for model, field in encrypted_columns():
            table, col, pk = qn(model._meta.db_table), qn(field.column), qn(model._meta.pk.column)
            cur.execute(f"SELECT {pk}, {col} FROM {table} WHERE {col} <> ''")
            for row_pk, token in cur.fetchall():
                try:
                    fresh = reencrypt(token, new_secret, old_secrets)
                except SecretUnreadable:
                    unreadable.append((model._meta.label, row_pk))
                    continue
                cur.execute(f"UPDATE {table} SET {col} = %s WHERE {pk} = %s", [fresh, row_pk])
                done += 1
    return {'reencrypted': done, 'unreadable': unreadable}
