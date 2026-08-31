"""Tests du converter — nés de l'audit du 2026-08-31 (deux bugs MUETS confirmés).

Le fichier n'existait pas : le converter était couvert par la grille (adoption) et les
scénarios nocturnes (gestes), jamais par un test de comportement de vue. Les deux défauts
ci-dessous ont vécu précisément dans cet angle mort — aucun ne levait d'erreur.
"""
import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse


class BatchDownloadTest(TestCase):
    """`batch_download` : le ZIP doit CONTENIR les sorties.

    Défaut confirmé le 2026-08-31 : `os.path` était utilisé (views.py:526-527) alors
    qu'`import os` ne vivait que dans `download_all` — chaque itération levait un
    `NameError` avalé par `except Exception: pass`, et le ZIP partait TOUJOURS VIDE,
    sans message. Un `except` large autour d'un corps qui référence un nom absent est
    exactement la famille « garde muette » : ce test tient l'invariant par le CONTENU.
    """

    def test_le_zip_d_un_lot_contient_les_sorties_reussies(self):
        from django.contrib.auth import get_user_model
        from wama.converter.models import ConversionBatch, ConversionJob

        user = get_user_model().objects.create_user('conv_zip_test', password='x')
        self.client.force_login(user)
        batch = ConversionBatch.objects.create(user=user, total=1)
        job = ConversionJob.objects.create(
            user=user, batch=batch, status='SUCCESS',
            input_filename='a.png', media_type='image', output_format='jpg')
        job.output_file.save('sortie.jpg', SimpleUploadedFile('sortie.jpg', b'JPGDATA'))

        r = self.client.post(reverse('converter:batch_download', args=[batch.id]))
        self.assertEqual(r.status_code, 200)
        zf = zipfile.ZipFile(io.BytesIO(b''.join(r.streaming_content)))
        self.assertEqual(len(zf.namelist()), 1,
                         'ZIP de lot VIDE — le NameError muet (import os) est revenu')
        self.assertTrue(zf.namelist()[0].endswith('.jpg'))


class SauverCommeProfilTest(TestCase):
    """Le lecteur de la modale « Sauver comme profil » doit lire ce que WamaParams ÉMET.

    Défaut confirmé le 2026-08-31 : `converter.js:867` appelait `readModalForm()` qui
    lit des `[data-key]` — un attribut que `wama-params.js` n'émet nulle part (0
    occurrence) → `output_format` toujours vide → toast « Format de sortie requis »
    systématique : le bouton était MORT à l'usage. Un test Python ne peut pas cliquer,
    mais il peut tenir les deux invariants de la correction : le handler appelle le
    lecteur SCHÉMA-driven, et l'hypothèse « data-key n'existe pas » reste vraie (si un
    jour WamaParams émettait data-key, ce test rappelle de réexaminer les deux lecteurs).
    """

    def _js(self, chemin):
        from pathlib import Path
        import wama
        return (Path(wama.__file__).parent.parent / chemin).read_text(encoding='utf-8')

    def test_le_bouton_profil_lit_via_le_schema_et_data_key_reste_absent_de_wamaparams(self):
        js = self._js('wama/converter/static/converter/js/converter.js')
        # Depuis le NETTOYAGE du 31/08 (REMOVAL_LEDGER) : la voie legacy est RETIRÉE
        # (buildModalFormHTML + readModalForm, branche inatteignable) — le fork qui avait
        # créé le bug n'existe plus, les deux lecteurs sont la MÊME fonction schéma.
        i = js.index('jobSettingsSaveProfileBtn')
        self.assertIn('readModalViaSchema()', js[i:i + 700],
                      'le handler « Sauver comme profil » ne lit plus via le schéma')
        for mort in ('readModalForm', 'buildModalFormHTML', 'readCurrentModal'):
            vivants = [l for l in js.splitlines() if mort in l and 'RETIRÉE' not in l]
            self.assertEqual(vivants, [], f'{mort} : le mort est revenu')
        params = self._js('wama/common/static/common/js/wama-params.js')
        self.assertNotIn('data-key', params,
                         'WamaParams émet désormais data-key : réexaminer readModalForm '
                         '(le mort pourrait revivre — ou être retiré pour de bon)')
