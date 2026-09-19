"""L'inventaire LOCAL d'un modèle installé, jumeau de `prospector._siblings` (2026-09-19).

POURQUOI. `model_installer.components_of_files` pèse un inventaire `[(chemin, taille)]` sans
réseau ; à distance, l'inventaire vient de `_siblings`. Pour un modèle INSTALLÉ il n'existait
pas de jumeau local : un parcours naïf du snapshot a compté 86 Go pour LTX-Video 13B (~44 de
poids réels), parce que le snapshot porte des liens IMBRIQUÉS (`vae/transformer/…`) vers les
mêmes blobs que `transformer/…`. Un snapshot HF est un jeu de LIENS vers des blobs : on pèse les
blobs, une fois chacun, au chemin le moins profond.

Le second complément local est l'en-tête safetensors : nombre de paramètres et dtype, ce qu'un
fichier distant ne dit pas et dont le pic PAR PRÉCISION a besoin (17,43 Md × 2 octets = 32,5 Go
en BF16 pour HunyuanImage 2.1, déclaré 16).

Aucun GPU, aucun réseau : un faux cache HF dans un dossier temporaire (liens symboliques — la
suite tourne sous WSL2, où ils existent ; sous Windows sans le privilège de création de lien,
`WinError 1314`, les cas à liens se SAUTENT au lieu de rougir, mesuré par l'instance sœur le
19/09), un faux safetensors écrit à la main.
"""
import json
import os
import struct
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from wama.model_manager.services.prospector import local_inventory, safetensors_facts


def _safetensors(path: Path, tensors: dict):
    """Écrit un `.safetensors` MINIMAL : en-tête JSON + zéro donnée (l'en-tête seul est lu)."""
    header = json.dumps(tensors).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<Q', len(header)))
        fh.write(header)


def _symlink(case: SimpleTestCase, blob: Path, target: Path):
    """Lien RELATIF `target → blob`, comme dans un cache HF. Là où le système refuse les liens
    (Windows sans `SeCreateSymbolicLinkPrivilege`), le cas testé n'existe pas : on saute — on ne
    fabrique pas un faux cache sans liens, qui ne testerait plus la déduplication."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(os.path.relpath(blob, target.parent), target)
    except OSError as exc:                       # WinError 1314 : privilège absent
        case.skipTest(f"liens symboliques indisponibles ici ({exc})")


class LocalInventoryTest(SimpleTestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'models--org--nom'
        self.blobs = self.root / 'blobs'
        self.rev = self.root / 'snapshots' / 'abc123'
        self.blobs.mkdir(parents=True)
        self.rev.mkdir(parents=True)

    def _blob(self, name: str, size: int) -> Path:
        p = self.blobs / name
        p.write_bytes(b'\0' * size)
        return p

    def _link(self, rel: str, blob: Path):
        _symlink(self, blob, self.rev / rel)

    def test_a_blob_reached_by_two_paths_counts_once_at_the_shallowest(self):
        """Le cas LTX : `vae/transformer/…` lie les MÊMES blobs que `transformer/…`."""
        b = self._blob('aaa', 3000)
        self._link('transformer/diffusion_pytorch_model.safetensors', b)
        self._link('vae/transformer/diffusion_pytorch_model.safetensors', b)
        self._link('vae/diffusion_pytorch_model.safetensors', self._blob('bbb', 500))
        self._link('model_index.json', self._blob('ccc', 40))
        inv = local_inventory(self.root)
        self.assertEqual(inv, [('model_index.json', 40),
                               ('transformer/diffusion_pytorch_model.safetensors', 3000),
                               ('vae/diffusion_pytorch_model.safetensors', 500)])

    def test_the_size_is_the_blob_s_not_the_link_s(self):
        self._link('model.safetensors', self._blob('big', 12_345))
        self.assertEqual(local_inventory(self.root), [('model.safetensors', 12_345)])

    def test_the_most_recent_revision_is_taken(self):
        self._link('model.safetensors', self._blob('v1', 10))
        old = self.root / 'snapshots' / 'old000'
        old.mkdir()
        _symlink(self, self._blob('v0', 5), old / 'model.safetensors')
        os.utime(old, (1, 1))
        self.assertEqual(local_inventory(self.root), [('model.safetensors', 10)])

    def test_a_bare_weights_folder_is_read_too(self):
        d = Path(self.tmp.name) / 'poids'
        (d / 'sub').mkdir(parents=True)
        (d / 'a.gguf').write_bytes(b'\0' * 7)
        (d / 'sub' / 'b.bin').write_bytes(b'\0' * 3)
        self.assertEqual(local_inventory(d), [('a.gguf', 7), ('sub/b.bin', 3)])

    def test_absent_yields_None_and_empty_yields_an_empty_list(self):
        """Indéterminable ≠ vide : la même distinction que `_siblings`."""
        self.assertIsNone(local_inventory(Path(self.tmp.name) / 'nulle-part'))
        self.assertIsNone(local_inventory(None))
        vide = Path(self.tmp.name) / 'vide'
        vide.mkdir()
        self.assertEqual(local_inventory(vide), [])

    def test_the_local_inventory_is_weighed_by_the_SAME_derivation_as_the_remote(self):
        """Le point de la jumelle : aucune seconde règle de pesée — celle de la sœur."""
        try:
            from wama.model_manager.services.model_installer import components_of_files
        except ImportError:                      # pragma: no cover — ordre des commits
            # Deux instances, deux fichiers : la dérivation (`model_installer`, autre session)
            # et l'inventaire (ici) ont été écrits le même soir. Si celui-ci atterrit le
            # premier, la garde croisée attend l'autre au lieu de rougir HEAD.
            self.skipTest("components_of_files pas encore commité (autre session)")
        go = 1024 ** 3
        self._link('transformer/diffusion_pytorch_model-00001-of-00002.safetensors',
                   self._blob('t1', go))
        self._link('transformer/diffusion_pytorch_model-00002-of-00002.safetensors',
                   self._blob('t2', go))
        self._link('vae/transformer/diffusion_pytorch_model-00001-of-00002.safetensors',
                   self.blobs / 't1')                       # doublon imbriqué, même blob
        self._link('vae/diffusion_pytorch_model.safetensors', self._blob('v', go // 2))
        r = components_of_files(local_inventory(self.root))
        self.assertEqual(r['components'], {'transformer': 2.0, 'vae': 0.5})
        self.assertEqual(r['largest_gb'], 2.0)


class SafetensorsHeaderTest(SimpleTestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_params_and_dtypes_are_read_from_the_header_alone(self):
        p = self.dir / 'model.safetensors'
        _safetensors(p, {'__metadata__': {'format': 'pt'},
                         'a.weight': {'dtype': 'BF16', 'shape': [4, 8], 'data_offsets': [0, 64]},
                         'a.bias': {'dtype': 'BF16', 'shape': [8], 'data_offsets': [64, 80]},
                         'b': {'dtype': 'F32', 'shape': [2, 2, 2], 'data_offsets': [80, 112]}})
        self.assertEqual(safetensors_facts(p), {'params': 32 + 8 + 8, 'dtypes': ['BF16', 'F32']})

    def test_an_unreadable_file_yields_None_without_raising(self):
        p = self.dir / 'pas-un.safetensors'
        p.write_bytes(b'\x01\x02')
        self.assertIsNone(safetensors_facts(p))
        self.assertIsNone(safetensors_facts(self.dir / 'absent.safetensors'))

    def test_an_absurd_header_length_is_refused(self):
        """Un en-tête annoncé à 1 To ne se lit pas en mémoire : on rend None, on ne tente pas."""
        p = self.dir / 'louche.safetensors'
        with open(p, 'wb') as fh:
            fh.write(struct.pack('<Q', 1 << 40))
            fh.write(b'{}')
        self.assertIsNone(safetensors_facts(p))
