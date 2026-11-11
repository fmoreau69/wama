"""
LE FICHIER DE TRAVAIL d'une card — le `.wdat` TRANSITOIRE, bac à sable de ses traitements.

Décision de Fabien du 2026-11-11 (`WAMA_DATA_WORLD §11.8 ⑩.2`) : *« De la même manière qu'on
construit une application en bac à sable dans WAMA, il faut passer par un `.wdat` transitoire qui
sert lui-même de bac à sable aux traitements, permettant de faire des tests à volonté, sans risque
de corruption de la bdd source, et c'est l'utilisateur qui décide de l'écriture du résultat dans la
bdd source. »* Quelle que soit la source, un process n'écrit QUE dans le fichier de travail de sa
card ; les données de l'utilisateur y TRANSITENT, elles n'entrent jamais dans la base de WAMA.

CE MODULE EST LE RANGEMENT que le monde Data inscrit au substrat
(`common/services/function_process.register_work_store`, depuis `apps.py`) : le substrat décide de
l'EMPLACEMENT du fichier (un par card, dans le dossier temporaire de son propriétaire), le monde
Data de son FORMAT. Il ne réécrit rien de ce qui existe : l'écrivain de conteneur
(`containers.write`, écriture atomique), le lecteur natif (`sources/wdat.py`), le pont
(`frames.signal_from_frame` / `frame_from_referential`).

  • une sortie à CLÉ DE TEMPS (`time`, ou `start`/`end`) devient un FLUX ; sinon une table NON
    temporelle (`Context.tables`, forme provisoire du même jour) ;
  • rejouer un process REMPLACE sa table — on teste à volonté ; les autres tables du fichier,
    ses attributs (coordonnées d'axes) et ses médias liés sont gardés tels quels ;
  • l'EMPREINTE rendue est celle du CONTENU de la table, pas du fichier, qui porte les sorties de
    tous les process de la card.

⏳ Ce qu'il ne fait pas encore (même décision, points 3-4) : recopier une table de la SOURCE
connectée de la card (aucune card n'a encore de source connectée — c'est la card du Data
Analyzer), et le geste de REPORT vers la source par comparaison.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from wama.common.catalog.data_types import DataType, TypedFrame

#: Les clés de `WamaMeta` que l'écrivain pose lui-même : relire un fichier ne les reprend pas comme
#: attributs (`created_at` serait figé, `streams` faux).
_WRITER_KEYS = frozenset({'format', 'schema_version', 'created_at', 'created_by', 'streams'})


def _time_key(frame: TypedFrame) -> str:
    """La clé de temps du cadre : `start` (segments), `time`, ou '' (table non temporelle)."""
    fields = set(frame.fields)
    if frame.data_type == DataType.SEGMENTS or 'start' in fields:
        return 'start' if 'start' in fields else ''
    return 'time' if 'time' in fields else ''


def fingerprint(frame: TypedFrame) -> str:
    """Empreinte du CONTENU d'un cadre (type, colonnes, valeurs) — ce qui périme l'aval quand la
    sortie change, et seulement alors."""
    digest = hashlib.sha256(str(frame.data_type).encode('utf-8'))
    digest.update(frame.df.to_csv(index=False).encode('utf-8'))
    return digest.hexdigest()


class WorkStore:
    """Le rangement inscrit au substrat (`function_process.register_work_store`)."""

    extension = '.wdat'

    # ── Lecture ───────────────────────────────────────────────────────────────────────────────
    def read(self, path, table: str) -> TypedFrame:
        """La table `table` du fichier de travail, en cadre typé — un flux par le pont (temps de
        session, famille portée par le catalogue), une table non temporelle telle quelle."""
        import pandas as pd

        from .frames import frame_from_referential
        from .sources import load
        from .sources.wdat import WdatReader
        path = Path(path)
        tables = WdatReader().tables(path)
        if table in tables:
            t = tables[table]
            return TypedFrame(pd.DataFrame(t['rows'], columns=t['columns']),
                              t['data_type'] or DataType.TABLE,
                              meta={'columns': {c: {'unit': u} for c, u in t['units'].items()}})
        ref = load(path, streams=[table])
        signal = ref.get(table)
        return frame_from_referential(ref, table, data_type=signal.meta.data_type or None)

    # ── Écriture ──────────────────────────────────────────────────────────────────────────────
    def write(self, path, name: str, frame: TypedFrame) -> dict:
        """Range `frame` sous le nom `name` dans le fichier de travail `path` (créé s'il n'existe
        pas), en REMPLAÇANT une table du même nom. Rend `{'table', 'fingerprint'}`."""
        from .containers import Context, write
        from .core.temporal import TemporalReferential
        from .frames import signal_from_frame
        path = Path(path)
        referential = TemporalReferential(name=path.stem)
        context = Context()
        if path.exists():
            self._keep(path, name, referential, context)
        key = _time_key(frame)
        if key:
            ordered = TypedFrame(frame.df.sort_values(key, kind='stable').reset_index(drop=True),
                                 frame.data_type, meta=frame.meta)
            signal = signal_from_frame(ordered, name,
                                       units={c: (d or {}).get('unit') for c, d in
                                              ((frame.meta or {}).get('columns') or {}).items()
                                              if (d or {}).get('unit')})
            # La famille portée comme DONNÉE (§9nonies) : celle que la fonction a rendue.
            signal.meta.data_type = frame.data_type
            referential.add(signal)
        else:
            context.tables.append({
                'name': name, 'data_type': frame.data_type, 'columns': list(frame.fields),
                'rows': frame.df.astype(object).where(frame.df.notna(), None).values.tolist(),
                'units': {c: (d or {}).get('unit') for c, d in
                          ((frame.meta or {}).get('columns') or {}).items() if (d or {}).get('unit')}})
        write(referential, path, context=context, overwrite=True)
        return {'table': name, 'fingerprint': fingerprint(frame)}

    @staticmethod
    def _keep(path: Path, replaced: str, referential, context) -> None:
        """Ce que le fichier porte déjà et qui RESTE : ses flux et ses tables sauf `replaced`, ses
        attributs, ses médias liés, ses copies projetées. Les flux sont relus PARESSEUSEMENT : leurs
        valeurs ne sont tirées qu'à l'écriture du nouveau fichier, avant qu'il ne remplace l'ancien."""
        from .sources import load, probe
        from .sources.wdat import WdatReader
        reader = WdatReader()
        info = probe(path)
        context.attributes.update({k: v for k, v in (info.attributes or {}).items()
                                   if k not in _WRITER_KEYS})
        context.media.extend(info.media or [])
        context.manifests.extend(p['body'] for p in reader.protocoles(path) if p.get('body'))
        kept = [s for s in info.streams if s != replaced]
        if kept:
            existing = load(path, streams=kept)
            for stream in existing.names:
                referential.add(existing.get(stream), offset=existing.offset(stream))
        for table_name, table in reader.tables(path).items():
            if table_name != replaced:
                context.tables.append({'name': table_name, **table})


#: Le rangement inscrit au substrat par `apps.py`.
STORE = WorkStore()
