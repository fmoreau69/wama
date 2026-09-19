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

Aucun GPU, aucun réseau : un faux cache HF dans un dossier temporaire (liens symboliques —
la suite tourne sous WSL2, où ils existent), un faux safetensors écrit à la main.
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


class InventaireLocalTest(SimpleTestCase):

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
        target = self.rev / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(blob, target.parent), target)

    def test_un_blob_atteint_par_deux_chemins_ne_compte_qu_une_fois_au_moins_profond(self):
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

    def test_la_taille_est_celle_du_blob_pas_du_lien(self):
        self._link('model.safetensors', self._blob('big', 12_345))
        self.assertEqual(local_inventory(self.root), [('model.safetensors', 12_345)])

    def test_la_revision_la_plus_recente_est_prise(self):
        self._link('model.safetensors', self._blob('v1', 10))
        old = self.root / 'snapshots' / 'old000'
        old.mkdir()
        os.symlink(os.path.relpath(self._blob('v0', 5), old), old / 'model.safetensors')
        os.utime(old, (1, 1))
        self.assertEqual(local_inventory(self.root), [('model.safetensors', 10)])

    def test_un_dossier_de_poids_direct_se_lit_aussi(self):
        d = Path(self.tmp.name) / 'poids'
        (d / 'sub').mkdir(parents=True)
        (d / 'a.gguf').write_bytes(b'\0' * 7)
        (d / 'sub' / 'b.bin').write_bytes(b'\0' * 3)
        self.assertEqual(local_inventory(d), [('a.gguf', 7), ('sub/b.bin', 3)])

    def test_absent_rend_None_et_vide_rend_une_liste_vide(self):
        """Indéterminable ≠ vide : la même distinction que `_siblings`."""
        self.assertIsNone(local_inventory(Path(self.tmp.name) / 'nulle-part'))
        self.assertIsNone(local_inventory(None))
        vide = Path(self.tmp.name) / 'vide'
        vide.mkdir()
        self.assertEqual(local_inventory(vide), [])

    def test_l_inventaire_local_se_pese_par_la_MEME_derivation_que_le_distant(self):
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


class EnTeteSafetensorsTest(SimpleTestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_parametres_et_dtypes_sont_lus_dans_l_en_tete_seul(self):
        p = self.dir / 'model.safetensors'
        _safetensors(p, {'__metadata__': {'format': 'pt'},
                         'a.weight': {'dtype': 'BF16', 'shape': [4, 8], 'data_offsets': [0, 64]},
                         'a.bias': {'dtype': 'BF16', 'shape': [8], 'data_offsets': [64, 80]},
                         'b': {'dtype': 'F32', 'shape': [2, 2, 2], 'data_offsets': [80, 112]}})
        self.assertEqual(safetensors_facts(p), {'params': 32 + 8 + 8, 'dtypes': ['BF16', 'F32']})

    def test_un_fichier_illisible_rend_None_sans_lever(self):
        p = self.dir / 'pas-un.safetensors'
        p.write_bytes(b'\x01\x02')
        self.assertIsNone(safetensors_facts(p))
        self.assertIsNone(safetensors_facts(self.dir / 'absent.safetensors'))

    def test_une_longueur_d_en_tete_absurde_est_refusee(self):
        """Un en-tête annoncé à 1 To ne se lit pas en mémoire : on rend None, on ne tente pas."""
        p = self.dir / 'louche.safetensors'
        with open(p, 'wb') as fh:
            fh.write(struct.pack('<Q', 1 << 40))
            fh.write(b'{}')
        self.assertIsNone(safetensors_facts(p))
