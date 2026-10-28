"""LA PORTE — les données personnelles d'un échange avant qu'il parte chez un fournisseur distant
(décisions de Fabien, 2026-10-28, `ROADMAP §16.4bis`).

    privacy_gate(user, source)      → `Gate`, ou None si rien n'est à faire pour cet hébergement
    gate.outgoing(messages)         → les messages à envoyer (LÈVE `CloudAccessRefused` si la
                                      détection n'a pas pu se faire : rien ne part)
    gate.stream(on_delta) / flush() → le flux de la réponse, données remises au fil de l'eau
    gate.incoming(text)             → la réponse, données remises (pseudonymisation)

LE GESTE est un choix de l'UTILISATEUR, par niveau d'hébergement (`UserProfile.cloud_privacy`,
carte « Modèles cloud » du profil) ; seuls les DÉFAUTS sont décidés ici :
- `pseudonymize` — chaque donnée devient `[PERSONNE_1]`, `[EMAIL_2]`… avant l'envoi, et la
  réponse est rendue avec les vraies valeurs : l'utilisateur ne perd rien, rien de personnel
  ne sort. Défaut des clouds COMMERCIAUX.
- `occult` — remplacée par son libellé `[PERSONNE]`, jamais remise.
- `none` — envoyé tel quel. Défaut du cloud privé et des clouds souverains.

DÉTECTION IMPOSSIBLE = RIEN NE PART. La détection tourne en local (service :8003, sinon dans ce
processus) ; si elle échoue (délai dépassé, un détecteur installé qui ne se charge pas), envoyer
quand même trahirait le réglage de l'utilisateur. On refuse en le disant — jamais en silence.

Ce que la porte ne couvre PAS (consigné, `ROADMAP §16.4bis`) : les IMAGES jointes à un message
(pas de détection visuelle ici), et les résultats d'outils que le CLI Claude Code obtient par
le serveur MCP au cours de SA boucle — ils ne repassent pas par cette porte.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections import OrderedDict

from wama.common.privacy.entities import DEFAULT_LANGUAGE, label_for

logger = logging.getLogger(__name__)

#: Les gestes offerts à l'utilisateur — vocabulaire UNIQUE (profil, vue, porte).
GESTURES = (
    ('none', 'Envoyer tel quel'),
    ('pseudonymize', 'Pseudonymiser : remplacées avant l\'envoi, remises dans la réponse'),
    ('occult', 'Occulter : remplacées, jamais remises'),
)

#: Les DÉFAUTS, par niveau d'hébergement d'une source (`external_sources.HOSTING_SCALE`) — la
#: seule décision qui revient à l'instance (Fabien, 2026-10-28 : « anonymisation uniquement
#: pour un cloud commercial »). Un hébergement absent prend le geste le plus protecteur.
DEFAULT_GESTURES = {'private': 'none', 'sovereign': 'none', 'third_party': 'pseudonymize'}
STRICTEST = 'pseudonymize'

#: Une valeur plus courte n'est pas propagée à ses autres occurrences (« Al », « 12 »…).
MIN_PROPAGATED = 3
#: Ce qu'un flux retient en fin de fragment, le temps de savoir si c'est un pseudonyme coupé.
_HELD_TAIL = re.compile(r'\[?[\w]{0,40}$')
#: Les paragraphes d'un texte, séparateurs gardés (indices impairs du découpage).
_PARAGRAPHS = re.compile(r'(\n\s*\n)')

_cache_lock = threading.Lock()
_cache: OrderedDict = OrderedDict()
_CACHE_MAX = 512


def privacy_levels() -> list:
    """`[(niveau, libellé)]` des hébergements qu'une source peut DÉCLARER (le cran
    `third_party_all` est un plafond, pas un hébergement : il suit la ligne commerciale)."""
    from wama.common.external_sources import CLOUD_ORIGIN_LABELS, HOSTING_SCALE
    return [(level, CLOUD_ORIGIN_LABELS[level]) for level in HOSTING_SCALE
            if level in CLOUD_ORIGIN_LABELS]


def gesture_for(user, hosting: str) -> str:
    """Le geste que `user` a choisi pour cet hébergement, sinon le défaut. Sans utilisateur
    (rôles en ligne de commande) : le défaut."""
    chosen = (getattr(getattr(user, 'profile', None), 'cloud_privacy', None) or {}) \
        if user is not None and getattr(user, 'is_authenticated', False) else {}
    gesture = chosen.get(hosting) if isinstance(chosen, dict) else None
    if gesture in dict(GESTURES):
        return gesture
    return DEFAULT_GESTURES.get(hosting, STRICTEST)


def gestures_of(profile) -> dict:
    """`{niveau: geste}` effectif d'un profil, défauts compris — ce que la page montre."""
    chosen = getattr(profile, 'cloud_privacy', None) or {}
    return {level: (chosen.get(level) if chosen.get(level) in dict(GESTURES)
                    else DEFAULT_GESTURES.get(level, STRICTEST))
            for level, _ in privacy_levels()}


def privacy_gate(user, source: str):
    """La porte d'un appel de `user` à la source déclarée `source`, ou None quand son
    hébergement est réglé sur « envoyer tel quel »."""
    from wama.common import external_sources
    declared = external_sources.by_key().get(source)
    hosting = getattr(declared, 'hosting', '') or ''
    gesture = gesture_for(user, hosting)
    if gesture == 'none':
        return None
    return Gate(gesture, getattr(declared, 'label', source) or source)


def _refused(reason: str, target: str):
    from wama.model_manager.services.cloud_models import CloudAccessRefused
    return CloudAccessRefused(
        f"La détection des données personnelles n'a pas pu se faire ({reason}) : rien n'a été "
        f"envoyé à {target}. Réessayez dans un instant, ou choisissez un modèle local.", 503)


def _key(language: str, text: str) -> str:
    return language + ':' + hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()


def _spans_of(texts: list, language: str, target: str) -> list:
    """`[[(début, fin, type)]]` par texte — par le service commun, avec un cache : l'invite
    système et l'historique reviennent à chaque tour."""
    with _cache_lock:
        missing = list(dict.fromkeys(t for t in texts if _key(language, t) not in _cache))
    if missing:
        from wama.common.privacy import service_client
        try:
            doc = service_client.detect_segments(missing, language)
        except service_client.PrivacyUnavailable as e:
            raise _refused(str(e), target) from e
        except Exception as e:                         # moteur en process qui casse : même règle
            logger.exception('[privacy] porte : détection impossible')
            raise _refused(type(e).__name__, target) from e
        if doc.get('unavailable'):
            raise _refused('détecteur non chargé : ' + ', '.join(doc['unavailable']), target)
        frames = {int(f['i']): f.get('d') or [] for f in doc.get('frames') or []}
        with _cache_lock:
            for index, text in enumerate(missing):
                _cache[_key(language, text)] = [(d['span'][0], d['span'][1], d['label'])
                                                for d in frames.get(index, []) if 'span' in d]
                _cache.move_to_end(_key(language, text))
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
    with _cache_lock:
        return [list(_cache.get(_key(language, t), [])) for t in texts]


class Gate:
    """Une porte pour UN appel : la table valeur ↔ pseudonyme vit le temps de l'appel. Chaque
    appel reconstruit la sienne sur tout l'historique, dans l'ordre d'apparition — les mêmes
    données reçoivent donc les mêmes pseudonymes d'un tour à l'autre."""

    def __init__(self, gesture: str, target: str = ''):
        self.gesture = gesture
        self.target = target or 'le fournisseur'
        self.language = DEFAULT_LANGUAGE
        self._forward: dict = {}       # valeur → pseudonyme (sans crochets)
        self._backward: dict = {}      # PSEUDONYME en majuscules → valeur
        self._counts: dict = {}
        self._pending = ''
        self._sink = None

    # ── Sortie ────────────────────────────────────────────────────────────────
    def outgoing(self, messages: list) -> list:
        """Les messages, chaque donnée personnelle de leurs textes remplacée."""
        slots = []                     # (message, index de partie | None, texte)
        for message in messages or []:
            content = message.get('content')
            if isinstance(content, str):
                slots.append((message, None, content))
            elif isinstance(content, list):
                for i, part in enumerate(content):
                    if isinstance(part, dict) and isinstance(part.get('text'), str):
                        slots.append((message, i, part['text']))
        texts = [text for _, _, text in slots]
        rewritten = self.outgoing_texts(texts)
        out, copies = [], {}
        for (message, part, _), new in zip(slots, rewritten):
            copy = copies.setdefault(id(message), dict(message))
            if part is None:
                copy['content'] = new
            else:
                if copy['content'] is message['content']:
                    copy['content'] = list(message['content'])
                copy['content'][part] = {**message['content'][part], 'text': new}
        for message in messages or []:
            out.append(copies.get(id(message), message))
        return out

    def outgoing_texts(self, texts: list) -> list:
        """Les textes, chaque donnée remplacée. Détectés PAR PARAGRAPHE : l'invite système change
        d'un tour à l'autre par quelques lignes, le cache garde tout le reste."""
        from wama.common.utils.text_language import detect_text_language
        sample = '\n'.join(t for t in texts if t)[-4000:]
        self.language = detect_text_language(sample) or DEFAULT_LANGUAGE
        split = [_PARAGRAPHS.split(t or '') for t in texts]
        chunks = [c for parts in split for c in parts[::2] if c.strip()]
        spans = dict(zip(chunks, _spans_of(chunks, self.language, self.target)))
        # La table, dans l'ordre d'apparition.
        for chunk in chunks:
            for start, end, entity in sorted(spans[chunk]):
                self._name(chunk[start:end].strip(), entity)
        result = []
        for parts in split:
            for i in range(0, len(parts), 2):
                if parts[i].strip():
                    parts[i] = self._propagate(self._replace(parts[i], spans[parts[i]]))
            result.append(''.join(parts))
        return result

    def _replace(self, chunk: str, chunk_spans: list) -> str:
        pieces, cursor = [], 0
        for start, end, _ in sorted(chunk_spans):
            if start < cursor:
                continue
            raw = chunk[start:end]
            value = raw.strip()
            pieces.append(chunk[cursor:start])
            if value in self._forward:
                lead = raw[:len(raw) - len(raw.lstrip())]
                trail = raw[len(raw.rstrip()):]
                pieces.append(f'{lead}[{self._forward[value]}]{trail}')
            else:
                pieces.append(raw)
            cursor = end
        pieces.append(chunk[cursor:])
        return ''.join(pieces)

    def _name(self, value: str, entity: str):
        if len(value) < 2 or value in self._forward:
            return
        core = label_for(entity, self.language)[1:-1]
        if self.gesture == 'pseudonymize':
            self._counts[core] = self._counts.get(core, 0) + 1
            core = f'{core}_{self._counts[core]}'
        self._forward[value] = core
        self._backward.setdefault(core.upper(), value)

    def _propagate(self, text: str) -> str:
        """Les AUTRES occurrences d'une valeur détectée ailleurs : un détecteur qui voit un nom
        une fois sur deux ne laisse pas passer la seconde (la contre-épreuve d'`occult_file`)."""
        for value in sorted((v for v in self._forward if len(v) >= MIN_PROPAGATED),
                            key=len, reverse=True):
            if value in text:
                placeholder = f'[{self._forward[value]}]'
                text = re.sub(rf'(?<![\w\[]){re.escape(value)}(?![\w\]])',
                              lambda _m: placeholder, text)
        return text

    # ── Retour ────────────────────────────────────────────────────────────────
    def incoming(self, text):
        """La réponse, chaque pseudonyme remplacé par sa valeur. Un appel d'outil rendu en JSON
        (`{"tool": …, "args": …}`) est restitué champ par champ, pour rester du JSON."""
        if not text or self.gesture != 'pseudonymize' or not self._backward:
            return text
        stripped = text.strip()
        if stripped.startswith('{') and '"tool"' in stripped:
            try:
                return json.dumps(self._restore_value(json.loads(stripped)), ensure_ascii=False)
            except ValueError:
                pass
        return self._restore(text)

    def _restore_value(self, value):
        if isinstance(value, str):
            return self._restore(value)
        if isinstance(value, list):
            return [self._restore_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self._restore_value(v) for k, v in value.items()}
        return value

    def _restore(self, text: str) -> str:
        # Tolérant à la forme : avec ou sans crochets, casse quelconque — un modèle recopie
        # souvent « Personne_1 » ou « PERSONNE_1 » sans les crochets.
        names = sorted(self._backward, key=len, reverse=True)
        pattern = re.compile(r'\[?(?<!\w)(' + '|'.join(re.escape(n) for n in names) + r')(?!\d)\]?',
                             re.IGNORECASE)
        return pattern.sub(lambda m: self._backward[m.group(1).upper()], text)

    # ── Flux ──────────────────────────────────────────────────────────────────
    def stream(self, on_delta):
        """`on_delta` d'un appel en flux, données remises au fil de l'eau. Un pseudonyme coupé
        entre deux fragments est RETENU jusqu'au suivant ; `flush()` rend le reste."""
        if on_delta is None or self.gesture != 'pseudonymize':
            return on_delta
        self._sink = on_delta

        def relay(fragment):
            self._pending += fragment
            held = _HELD_TAIL.search(self._pending)
            cut = held.start() if held and held.group(0) else len(self._pending)
            ready, self._pending = self._pending[:cut], self._pending[cut:]
            if ready:
                self._sink(self._restore(ready) if self._backward else ready)
        return relay

    def flush(self):
        if self._sink is not None and self._pending:
            pending, self._pending = self._pending, ''
            self._sink(self._restore(pending) if self._backward else pending)
