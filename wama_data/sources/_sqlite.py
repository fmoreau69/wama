"""
Accès SQLite PARTAGÉ par les lecteurs de bases — la mécanique, jamais le schéma.

⚠ POURQUOI CE MODULE EXISTE (2026-08-24, à l'arrivée du lecteur `.wdat`). `TripReader` portait
~120 lignes d'accès SQLite — ouverture en lecture seule, décodage du texte, colonnes, instants,
bornes, et les trois niveaux d'agrégation — qui ne doivent **rien** au format de BIND. Le lecteur
du conteneur natif en avait besoin à l'identique, à deux noms de colonne près.

C'est la symétrie exacte de ce qui a été fait côté écriture le même jour (`containers/` : un moteur,
N schémas) : **la mécanique est commune, la connaissance du schéma est le seul propre de chacun.**
Ce qui reste dans un lecteur concret : `can_read`, `probe`, `read` — et rien d'autre.

⚠ Le nom commence par `_` À DESSEIN : `sources.modules_lecteurs()` découvre les modules du paquet
pour les enregistrer comme lecteurs (garde-fou G1), et ce module n'en est pas un. Le préfixe est le
contrat de cette découverte, pas une convention de politesse.

CE QUI EST HÉRITÉ ICI A ÉTÉ PAYÉ CHER — les docstrings disent le prix
    Chaque méthode porte le défaut qu'elle a coûté : la connexion qui fuyait, le texte cp1252, et
    l'agrégation bornée par le TEMPS et non par l'index. Les déplacer sans leur raison reviendrait
    à laisser le prochain lecteur les repayer.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

from . import SourceReader


def text(octets: bytes) -> str:
    """Décodeur du texte SQLite — UTF-8, repli **cp1252**.

    ⚠ DÉFAUT MESURÉ LE 2026-08-24 en relevant le schéma d'un `.trip` réel : quatre tables de la
    base d'expérimentation portent « Ajouté à partir de BIND_GUI » écrit par l'outil MATLAB sous
    Windows. Le `sqlite3` de Python décode en UTF-8 strict et lève
    `OperationalError: Could not decode to UTF-8` — **pas une exception de décodage**, donc un
    message qui n'oriente même pas vers l'encodage.

    L'ORDRE COMPTE, et c'est tout l'argument : cp1252 associe un caractère à 251 des 256 octets, si
    bien qu'essayé en premier il rendrait **du texte plausible mais faux** pour n'importe quel
    UTF-8 accentué (« Ajouté » y deviendrait « AjoutÃ© ») — sans jamais lever. L'UTF-8 en premier,
    lui, ÉCHOUE proprement sur une séquence qui n'en est pas. On teste donc le codec qui sait dire
    non, et on se replie sur celui qui dit toujours oui. Les cinq octets sans correspondance sont
    couverts par `errors='replace'`, seul cas où l'on abîme réellement un caractère.
    """
    try:
        return octets.decode('utf-8')
    except UnicodeDecodeError:
        return octets.decode('cp1252', 'replace')


class SqliteSourceReader(SourceReader):
    """Lecteur d'une base SQLite. Les sous-classes n'écrivent que `can_read`, `probe` et `read`."""

    #: Table dont la présence atteste le format. Sert au reniflage de `can_read`.
    table_temoin = ''

    # ── Reconnaissance ────────────────────────────────────────────────────────────────────────
    def can_read(self, path: Path) -> bool:
        """Extension ET contenu. Sans le second, un fichier mal nommé ferait échouer l'import
        **loin de sa cause** — au milieu de la lecture d'un flux, pas à la porte."""
        if path.suffix.lower() not in self.extensions:
            return False
        try:
            with self._open(path) as con:
                naming = {r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            return self.table_temoin in naming
        except Exception:
            return False

    @staticmethod
    @contextmanager
    def _open(path: Path):
        """Connexion LECTURE SEULE, RÉELLEMENT REFERMÉE — on n'écrit jamais dans une source importée.

        ⚠ DÉFAUT CORRIGÉ LE 2026-08-24, trouvé par un `.trip` synthétique. Le lecteur écrivait
        partout `with self._open(path) as con:` en croyant fermer. **Le gestionnaire de contexte
        d'une `sqlite3.Connection` gère la TRANSACTION, pas la fermeture** : il committe ou annule,
        puis laisse la connexion OUVERTE. Chaque `probe`, `read`, `_columns`, `_times`… en fuyait
        une — et l'on en ouvre une par appel **à dessein** (sécurité entre fils d'exécution), donc
        la fuite est proportionnelle à l'usage.

        Invisible sous Linux, où l'on supprime un fichier ouvert sans broncher. Sous Windows, le
        fichier devient indélogeable — c'est ainsi que le fixture temporaire l'a révélé, alors que
        la base réelle (jamais supprimée) ne l'aurait jamais montré.

        Écrit en `@contextmanager` : tous les appelants gardent leur `with`, et la fermeture devient
        impossible à oublier au lieu d'être à répéter.
        """
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.text_factory = text
        try:
            yield con
        finally:
            con.close()

    # ── Accès bas niveau ──────────────────────────────────────────────────────────────────────
    def _tables(self, path: Path) -> List[str]:
        with self._open(path) as con:
            return [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

    def _columns(self, path: Path, table: str) -> List[str]:
        with self._open(path) as con:
            return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]

    def _values(self, path: Path, table: str, column: str, order_by: str) -> list:
        """Une colonne entière, TRIÉE PAR LE TEMPS.

        ⚠ Remplace les deux méthodes `_times`/`_ends` du lecteur `.trip`, qui ne différaient que
        par la colonne lue — et dont la seconde portait seule la remarque qui vaut pour les deux :
        **les fins doivent sortir dans le MÊME ordre que les débuts**, donc on trie sur `order_by`
        et jamais sur la colonne lue. Une règle écrite dans une seule des deux copies est une règle
        qu'on perd en touchant l'autre.
        """
        with self._open(path) as con:
            return [r[0] for r in con.execute(
                f'SELECT "{column}" FROM "{table}" ORDER BY "{order_by}"')]

    def _extent_accessor(self, path: Path, table: str, tcol: str):
        """Rend `(t0, t1, colonne) -> (min, max)` calculé EN SQL, borné par le TEMPS.

        ⚠ Borné par le temps, PAS par l'index — leçon d'une première version mesurée inutilisable.
        Agréger par `LIMIT n OFFSET k` oblige SQLite à re-parcourir depuis le début à chaque appel :
        sur 2 M de lignes et 2000 tranches, le coût devient quadratique et la vue décimée ne rend
        jamais la main. Une borne temporelle, elle, exploite l'index sur la colonne de temps.

        La colonne est validée contre le schéma réel avant d'être interpolée dans la requête : un
        nom venant de l'appelant ne doit jamais atterrir tel quel dans du SQL.
        """
        columns = set(self._columns(path, table))

        def extent(t0: float, t1: float, column: str):
            if column not in columns or t1 <= t0:
                return (None, None)
            with self._open(path) as con:
                row = con.execute(
                    f'SELECT MIN("{column}"), MAX("{column}") FROM "{table}" '
                    f'WHERE "{tcol}" >= ? AND "{tcol}" < ?', (t0, t1)).fetchone()
            return (row[0], row[1]) if row else (None, None)

        return extent

    def _extents_accessor(self, path: Path, table: str, tcol: str):
        """Rend `(t0, t1, buckets, colonne) -> {n° de tranche: (min, max)}` — TOUTES les tranches
        en UNE requête groupée.

        Mesuré : 2000 tranches sur 2 M de lignes coûtaient 24,9 s en interrogeant tranche par
        tranche (une requête et une connexion chacune), contre ~1 s en une seule passe avec
        `GROUP BY`. Pour une vue d'interface la différence n'est pas un confort, c'est la
        viabilité. C'est aussi pourquoi le contrat prévoit cette capacité en OPTION : une source
        qui ne sait pas grouper retombe sur l'agrégation tranche par tranche, puis sur la lecture
        des lignes — trois niveaux, du plus efficace au plus universel.
        """
        columns = set(self._columns(path, table))

        def extents(t0: float, t1: float, buckets: int, column: str):
            if column not in columns or buckets <= 0 or t1 <= t0:
                return {}
            pas = (t1 - t0) / buckets
            with self._open(path) as con:
                rows = con.execute(
                    f'SELECT CAST(("{tcol}" - ?) / ? AS INTEGER) AS b, '
                    f'MIN("{column}"), MAX("{column}") FROM "{table}" '
                    f'WHERE "{tcol}" >= ? AND "{tcol}" < ? GROUP BY b',
                    (t0, pas, t0, t1)).fetchall()
            return {int(b): (lo, hi) for b, lo, hi in rows if b is not None}

        return extents

    def _row_accessor(self, path: Path, table: str, tcol: str):
        """Rend `(i0, i1) -> lignes`. Chaque appel rouvre en lecture seule : une connexion SQLite
        n'est pas sûre entre fils d'exécution, et un référentiel est destiné à être interrogé
        depuis plusieurs contextes."""
        def rows(i0: int, i1: int):
            if i1 <= i0:
                return []
            with self._open(path) as con:
                cur = con.execute(
                    f'SELECT * FROM "{table}" ORDER BY "{tcol}" LIMIT ? OFFSET ?',
                    (i1 - i0, i0))
                naming = [c[0] for c in cur.description]
                return [dict(zip(naming, r)) for r in cur.fetchall()]
        return rows

    @staticmethod
    def _frequence(value) -> Optional[float]:
        """Cadence déclarée, ou None si le champ ne dit rien d'exploitable.

        ⚠ Le champ n'est PAS fiable dans les bases réelles. Mesuré : il valait `0` pour les dix
        flux d'une passation, et **la chaîne vide** pour les flux dérivés — ce qui faisait lever
        `float('')` et rendait le flux entier illisible. Toute valeur non numérique ou non
        strictement positive signifie « non renseigné » : on rend None plutôt que de fabriquer une
        cadence, puisque `measured_fs()` sait la déduire de la donnée elle-même.
        """
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None
