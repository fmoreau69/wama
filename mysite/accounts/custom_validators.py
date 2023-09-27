import gzip
import re

from pathlib import Path
from difflib import SequenceMatcher

from django.utils.translation import ngettext  # https://docs.python.org/2/library/gettext.html#gettext.ngettext
from django.core.exceptions import (FieldDoesNotExist, ImproperlyConfigured, ValidationError, )


class FrenchUserAttributeSimilarityValidator:
    """
    Validate whether the password is sufficiently different from the user's
    attributes.

    If no specific attributes are provided, look at a sensible list of
    defaults. Attributes that don't exist are ignored. Comparison is made to
    not only the full attribute value, but also its components, so that, for
    example, a password is validated against either part of an email address,
    as well as the full address.
    """
    DEFAULT_USER_ATTRIBUTES = ('username', 'first_name', 'last_name', 'email')

    def __init__(self, user_attributes=DEFAULT_USER_ATTRIBUTES, max_similarity=0.7):
        self.user_attributes = user_attributes
        self.max_similarity = max_similarity

    def validate(self, password, user=None):
        if not user:
            return

        for attribute_name in self.user_attributes:
            value = getattr(user, attribute_name, None)
            if not value or not isinstance(value, str):
                continue
            value_parts = re.split(r'\W+', value) + [value]
            for value_part in value_parts:
                if SequenceMatcher(a=password.lower(), b=value_part.lower()).quick_ratio() >= self.max_similarity:
                    try:
                        verbose_name = str(user._meta.get_field(attribute_name).verbose_name)
                        if verbose_name == 'username':
                            verbose_name = "nom d'utilisateur"
                    except FieldDoesNotExist:
                        verbose_name = attribute_name
                    raise ValidationError(
                        "Le mot de passe est trop similaire au %(verbose_name)s.",
                        code='password_too_similar',
                        params={'verbose_name': verbose_name},
                    )

    def get_help_text(self):
        return "Votre mot de passe ne peut pas être trop similaire à d'autres informations personnelles."


class FrenchMinimumLengthValidator:
    """
    Validate whether the password is of a minimum length.
    """
    def __init__(self, min_length=8):
        self.min_length = min_length

    def validate(self, password, user=None):
        if len(password) < self.min_length:
            raise ValidationError(
                ngettext(
                    "Le mot de passe doit contenir au moins %(min_length)d caractères.",
                    "Le mot de passe doit contenir au moins %(min_length)d caractères.",
                    self.min_length
                ),
                code='password_too_short',
                params={'min_length': self.min_length},
            )

    def get_help_text(self):
        return ngettext(
            "Votre mot de passe doit contenir au moins %(min_length)d caractères.",
            "Votre mot de passe doit contenir au moins %(min_length)d caractères.",
            self.min_length
        ) % {'min_length': self.min_length}


class FrenchCommonPasswordValidator:
    """
    Validate whether the password is a common password.

    The password is rejected if it occurs in a provided list of passwords,
    which may be gzipped. The list Django ships with contains 20000 common
    passwords (lowercased and deduplicated), created by Royce Williams:
    https://gist.github.com/roycewilliams/281ce539915a947a23db17137d91aeb7
    The password list must be lowercased to match the comparison in validate().
    """
    DEFAULT_PASSWORD_LIST_PATH = Path(__file__).resolve().parent / 'data/common-passwords.txt.gz'

    def __init__(self, password_list_path=DEFAULT_PASSWORD_LIST_PATH):
        try:
            with gzip.open(str(password_list_path)) as f:
                common_passwords_lines = f.read().decode().splitlines()
        except IOError:
            with open(str(password_list_path)) as f:
                common_passwords_lines = f.readlines()

        self.passwords = {p.strip() for p in common_passwords_lines}

    def validate(self, password, user=None):
        if password.lower().strip() in self.passwords:
            raise ValidationError(
                "Ce mot de passe est trop commun.",
                code='password_too_common',
            )

    def get_help_text(self):
        return "Votre mot de passe ne peut pas être un mot de passe trop commun."


class FrenchNumericPasswordValidator:
    """
    Validate whether the password is alphanumeric.
    """
    def validate(self, password, user=None):
        if password.isdigit():
            raise ValidationError(
                "Le mot de passe ne peut pas être entièrement numérique.",
                code='password_entirely_numeric',
            )

    def get_help_text(self):
        return "Le mot de passe ne peut pas être entièrement numérique."
