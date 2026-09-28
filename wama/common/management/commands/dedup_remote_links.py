"""
Sauvegarde distante des modèles : remplacer les COPIES PLEINES de liens de snapshot HF — laissées
par les sauvegardes d'avant le 2026-09-28 — par des entrées du manifeste de liens.

POURQUOI. Jusqu'au 28/09, `mirror_tree` suivait les liens `snapshots/<rev>/…` → `blobs/<hash>` d'un
cache HuggingFace : un dépôt sauvegardé pour la PREMIÈRE fois par ce moteur voyait chaque poids
recopié une seconde fois (mesuré par la simulation du 28/09 : 58 Go sur 4 dépôts ; les dépôts plus
anciens portaient déjà de vrais liens au distant). Le moteur reproduit désormais les liens
(`mirror_sync`, section « liens internes »), mais les doubles déjà partis sont restés : l'archive
est cumulative, le miroir ne purge JAMAIS.

Cette commande est donc un geste PONCTUEL et EXPLICITE, hors du miroir — et elle ne perd rien :
chaque double est d'abord inscrit dans `LINKS_MANIFEST` (à la racine distante), puis remplacé par
un VRAI lien vers son blob, qui reste. Le tirage (`restore_backup`) rend un lien dans les deux cas —
y compris pour un modèle déjà désinstallé en local.

RÈGLES DE SÉCURITÉ — un fichier n'est retiré que s'il est PROUVÉ doublon d'un blob du même dépôt :
  • `described` : le manifeste le décrit déjà comme lien, et le blob visé existe à la même taille ;
  • `matched`   : UN SEUL blob du dépôt a la même taille ET les mêmes octets de tête et de queue
                  (le fichier entier en deçà de deux sondes) ;
  • tout le reste est GARDÉ : `unique` (aucun blob de cette taille — c'est la seule copie),
    `ambiguous` (plusieurs blobs concordent), `mismatch` (le manifeste désigne un blob absent ou
    d'une autre taille). Un fichier gardé n'est jamais une perte ; un fichier retiré à tort l'est.

Simulation par défaut ; `--apply` écrit le manifeste PUIS retire, en revérifiant chaque blob juste
avant. Opération longue sur un montage réseau (un parcours complet + deux lectures par candidat).
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from wama.common.services.mirror_sync import (
    LINKS_MANIFEST, read_links_manifest, remote_is_available, resolve_remote_root,
    write_links_manifest)

#: Classes RETIRABLES — toutes les autres sont gardées.
REMOVABLE = ('described', 'matched')


def _same_probes(a: Path, b: Path, size: int, probe: int) -> bool:
    """Mêmes octets de tête et de queue (le fichier entier s'il fait moins de deux sondes)."""
    with open(a, 'rb') as fa, open(b, 'rb') as fb:
        if size <= 2 * probe:
            return fa.read() == fb.read()
        if fa.read(probe) != fb.read(probe):
            return False
        fa.seek(size - probe)
        fb.seek(size - probe)
        return fa.read(probe) == fb.read(probe)


def scan(root: Path) -> tuple[dict, list]:
    """UN parcours du distant : (liens décrits par TOUS les manifestes, dépôts `models--*`)."""
    described, repos = {}, []
    for current, dirs, files in os.walk(root):
        here = Path(current)
        if LINKS_MANIFEST in files:
            base = here.relative_to(root)
            for link, value in read_links_manifest(here / LINKS_MANIFEST).items():
                described[(base / link).as_posix()] = value
        if here.name.startswith('models--') and 'snapshots' in dirs and 'blobs' in dirs:
            repos.append(here)
    return described, repos


def plan(root: Path, probe: int = 1 << 20) -> list[dict]:
    """Classe chaque fichier PLEIN des `snapshots/` distants. Lecture seule."""
    described, repos = scan(root)
    entries = []
    for repo in repos:
        blobs_by_size = defaultdict(list)
        for blob in (repo / 'blobs').iterdir():
            if blob.is_file() and not blob.is_symlink() and not blob.name.endswith('.incomplete'):
                blobs_by_size[blob.stat().st_size].append(blob)
        for path in (repo / 'snapshots').rglob('*'):
            if path.is_symlink() or not path.is_file():
                continue
            size = path.stat().st_size
            rel = path.relative_to(root).as_posix()
            blob, cls = None, 'unique'
            if rel in described:
                target = Path(os.path.normpath(path.parent / described[rel]))
                ok = target.is_file() and target.stat().st_size == size
                blob, cls = (target, 'described') if ok else (None, 'mismatch')
            elif blobs_by_size.get(size):
                hits = [b for b in blobs_by_size[size] if _same_probes(path, b, size, probe)]
                if len(hits) == 1:
                    blob, cls = hits[0], 'matched'
                elif hits:
                    cls = 'ambiguous'
            entries.append({'path': path, 'rel': rel, 'size': size, 'blob': blob, 'class': cls,
                            'repo': repo.relative_to(root).as_posix()})
    return entries


def apply(root: Path, entries: list[dict]) -> dict:
    """Inscrit les liens au manifeste (filet : un arrêt entre retrait et lien ne perd rien), PUIS
    remplace chaque double par un VRAI lien vers son blob — la forme que portent déjà les dépôts
    plus anciens du distant (montage 9p `metadata`). Blob revérifié juste avant chaque retrait."""
    removable = [e for e in entries if e['class'] in REMOVABLE]
    values = {e['rel']: os.path.relpath(e['blob'], e['path'].parent) for e in removable}
    write_links_manifest(root, values)
    removed = freed = linked = 0
    errors = []
    for e in removable:
        try:
            if not (e['blob'].is_file() and e['blob'].stat().st_size == e['size']):
                errors.append(f"{e['rel']}: blob disparu ou modifié — gardé")
                continue
            e['path'].unlink()
            removed += 1
            freed += e['size']
        except OSError as exc:
            errors.append(f"{e['rel']}: {exc}")
            continue
        try:
            os.symlink(values[e['rel']], e['path'])
            linked += 1
        except OSError:
            pass                  # le manifeste le décrit : le tirage le recréera
    return {'removed': removed, 'freed_bytes': freed, 'linked': linked, 'errors': errors}


def summarize(entries: list[dict]) -> dict:
    by_class = defaultdict(lambda: [0, 0])
    by_repo = defaultdict(int)
    for e in entries:
        by_class[e['class']][0] += 1
        by_class[e['class']][1] += e['size']
        if e['class'] in REMOVABLE:
            by_repo[e['repo']] += e['size']
    return {'classes': {k: {'files': v[0], 'bytes': v[1]} for k, v in by_class.items()},
            'removable_bytes': sum(v[1] for k, v in by_class.items() if k in REMOVABLE),
            'by_repo': dict(sorted(by_repo.items(), key=lambda kv: -kv[1]))}


class Command(BaseCommand):
    help = ("Sauvegarde distante des modèles : remplace les copies pleines de liens de snapshot HF "
            "par des entrées du manifeste de liens (simulation sans --apply).")

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Écrire le manifeste puis retirer les doubles prouvés.")
        parser.add_argument('--probe-mb', type=float, default=1.0,
                            help="Taille des sondes de tête et de queue comparées (Mo).")
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **opts):
        root = Path(resolve_remote_root('MODELS', env_var='WAMA_MODEL_BACKUP_PATH'))
        if not remote_is_available(root):
            raise CommandError(f"espace distant indisponible : {root}")
        entries = plan(root, probe=int(opts['probe_mb'] * (1 << 20)))
        report = summarize(entries)
        if opts['apply']:
            report['applied'] = apply(root, entries)
        if opts['json']:
            self.stdout.write(json.dumps(report, indent=1, ensure_ascii=False))
            return
        gb = lambda n: f"{n / 1e9:.1f} Go"                                  # noqa: E731
        self.stdout.write(f"Distant : {root}")
        for cls, v in sorted(report['classes'].items()):
            mark = 'RETIRABLE' if cls in REMOVABLE else 'gardé'
            self.stdout.write(f"  {cls:10} {v['files']:6} fichiers  {gb(v['bytes']):>10}  ({mark})")
        self.stdout.write(f"Récupérable : {gb(report['removable_bytes'])}")
        for repo, size in list(report['by_repo'].items())[:15]:
            self.stdout.write(f"  {gb(size):>10}  {repo}")
        if 'applied' in report:
            a = report['applied']
            self.stdout.write(f"APPLIQUÉ : {a['removed']} retirés, {gb(a['freed_bytes'])} rendus, "
                              f"{len(a['errors'])} erreurs {a['errors'][:5]}")
        else:
            self.stdout.write("SIMULATION — rien écrit, rien retiré (--apply pour exécuter).")
