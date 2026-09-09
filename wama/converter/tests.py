"""Tests du converter — nés de l'audit du 2026-08-31 (deux bugs MUETS confirmés).

Le fichier n'existait pas : le converter était couvert par la grille (adoption) et les
scénarios nocturnes (gestes), jamais par un test de comportement de vue. Les deux défauts
ci-dessous ont vécu précisément dans cet angle mort — aucun ne levait d'erreur.
"""
import io
import re
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


class PreregagesQualiteTest(TestCase):
    """Les préréglages au MODÈLE ÉVÉNEMENTIEL (Fabien, 02/09 — ROADMAP §23.2quater) :
    un preset est un GESTE D'ÉCRITURE (le profil GÉNÉRAL commun à tous), plus un facteur
    au lancement. Choisir « web » ÉCRIT ses valeurs dans les colonnes au clic — l'utilisateur
    voit l'effet réel, le retouche, l'enregistre en profil s'il veut. Le dernier geste gagne.

    ⚠ HISTORIQUE : la V1 de ces tests (01/09) verrouillait l'INVERSE — « le preset agit au
    lancement sur le non-posé » (cascade effective_settings). Le modèle événementiel du
    02/09 la remplace : ne pas « réparer » un rouge d'ici en réintroduisant le preset dans
    la tâche — la tâche lit les COLONNES, et c'est le contrat.
    """

    def _job(self, **kw):
        from django.contrib.auth.models import User
        u, _ = User.objects.get_or_create(username='t_presets')
        base = dict(user=u, input_filename='x.png', media_type='image',
                    output_format='jpg', status='PENDING')
        base.update(kw)
        from wama.converter.models import ConversionJob
        return ConversionJob.objects.create(**base)

    def test_choisir_un_preset_ECRIT_ses_valeurs_dans_les_colonnes(self):
        from django.test import Client
        import json as _j
        j = self._job()
        c = Client()
        c.force_login(j.user)
        r = c.post(f'/converter/{j.id}/update/',
                   {'options_json': _j.dumps({'quality_preset': 'web'})})
        self.assertEqual(r.status_code, 200, r.content)
        j.refresh_from_db()
        self.assertEqual(j.quality, 80, 'le preset « web » doit ÉCRIRE quality=80 au clic')
        self.assertEqual(j.quality_preset, 'web', 'la trace du dernier preset applique')

    def test_un_reglage_du_MEME_envoi_prime_sur_le_preset(self):
        # Le geste fin prime : « web » (80) + quality=95 dans le même POST → 95.
        from django.test import Client
        import json as _j
        j = self._job()
        c = Client()
        c.force_login(j.user)
        r = c.post(f'/converter/{j.id}/update/',
                   {'options_json': _j.dumps({'quality_preset': 'web', 'quality': 95})})
        self.assertEqual(r.status_code, 200, r.content)
        j.refresh_from_db()
        self.assertEqual(j.quality, 95)

    def test_la_tache_lit_les_colonnes_le_preset_n_arbitre_plus_au_lancement(self):
        # Un job à quality POSÉE 72 et trace quality_preset='max' (98) : la valeur effective
        # au lancement est 72 — la trace n'écrase rien, elle n'est qu'une trace.
        from wama.common.utils.param_schema import effective_settings
        from wama.converter.params import PARAMS_JSON
        j = self._job(quality=72, quality_preset='max')
        eff = effective_settings(PARAMS_JSON, posees=j.options,
                                 contexte={'media_type': 'image'})
        self.assertEqual(eff['quality'], 72)

    def test_l_element_nait_COMPLET_les_defauts_sont_ecrits_a_la_creation(self):
        # Modèle événementiel : la création écrit les défauts applicables (chips pleines
        # dès la naissance — demande du 31/08, enfin réconciliée avec les presets).
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import Client
        PNG = bytes.fromhex(
            '89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de'
            '0000000c49444154789c63f8cfc00000000300015f0f18e20000000049454e44ae426082')
        from django.contrib.auth.models import User
        u, _ = User.objects.get_or_create(username='t_presets')
        c = Client()
        c.force_login(u)
        r = c.post('/converter/upload/',
                   {'file': SimpleUploadedFile('n.png', PNG, 'image/png'),
                    'output_format': 'jpg'})
        self.assertEqual(r.status_code, 200, r.content)
        from wama.converter.models import ConversionJob
        j = ConversionJob.objects.get(pk=r.json()['id'])
        self.assertEqual(j.quality, 85, "le défaut du schéma doit être ÉCRIT à la création")


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


class AdoptionDeLaBriqueDEntreeDeFileTest(TestCase):
    """Le converter est passé sur `common/_queue_entry.html` le 2026-09-09 — DERNIER des 10.

    Le portage a levé un verrou de nommage (`job` → `elem` dans `_job_card.html`), et c'est
    précisément le genre de geste dont les ratés ne LÈVENT RIEN : un gabarit Django qui
    déréférence un nom absent ne casse pas, il rend du VIDE. Les deux contrats ci-dessous
    sont ceux que le port pouvait emporter sans un mot ; aucun n'était gardé avant ce jour.
    """

    def _utilisateur(self, nom):
        """Un compte qui FRANCHIT le portier, jamais un superuser.

        `AppAccessMiddleware` redirige (302) un compte sans rôle : neutraliser le portier
        rendrait le test aveugle à une régression du gating (arbitrage repris de
        `nightly_tests.get_test_user()` et de la fabrique du synthesizer).
        """
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX

        u = get_user_model().objects.create_user(nom, password='x')
        for role in ('communication', 'recherche', 'ingenierie', 'administratif'):
            g, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
            u.groups.add(g)
        self.client.force_login(u)
        return u

    def test_le_wrapper_de_lot_porte_la_NATURE_du_lot(self):
        """`data-media-type` sur `.batch-group` — lu par `converter.js:378`.

        Le converter rendait ce wrapper lui-même ; la brique commune ne l'émettait pas. La
        modale de réglages d'un LOT dérive ses options de format de la NATURE, que le bouton
        de `_batch_card.html` ne porte PAS : ce wrapper en est la SEULE source (mesuré avant
        le port). Sans lui, `mt` vaut `undefined` et la modale s'ouvre sur une nature vide —
        sans erreur console, sans 500, sans rien.
        """
        from wama.converter.models import ConversionBatch, ConversionJob

        u = self._utilisateur('conv_nature')
        lot = ConversionBatch.objects.create(user=u, total=2, media_type='image')
        for n in ('un.png', 'deux.png'):
            ConversionJob.objects.create(user=u, batch=lot, input_filename=n,
                                         media_type='image')

        html = self.client.get('/converter/').content.decode('utf-8', 'replace')
        self.assertIn(f'data-batch-id="{lot.id}"', html,
                      'le lot ne porte pas son id : la brique ne rend pas son wrapper')

        # ⚠ L'assertion doit porter sur LA BALISE `.batch-group`, pas sur la page. Première
        # version écrite : `assertIn('data-media-type="image"', html)` — elle restait VERTE
        # avec l'attribut retiré de la brique, parce que le ⚙ de chaque card FILLE en émet un
        # homonyme via `gear_data` (index.html:338). Or `onBatchSettings` reçoit le bouton du
        # LOT, qui n'a pas de `gear_data` : la fille ne le secourt pas. Une garde qui se
        # satisfait d'une occurrence homonyme ailleurs dans la page ne garde rien — trouvé par
        # contre-épreuve, pas par relecture.
        ouvrante = re.search(r'<div class="batch-group[^>]*>', html)
        self.assertIsNotNone(ouvrante, 'aucun wrapper de lot rendu')
        balise = ouvrante.group(0)
        self.assertIn(f'data-batch-id="{lot.id}"', balise)
        self.assertIn('data-media-type="image"', balise,
                      "le wrapper de lot a perdu la NATURE — la modale de réglages du lot "
                      "s'ouvrira sans elle, en silence (converter.js:378). Balise rendue :\n"
                      + balise)

    def test_l_endpoint_card_html_rend_une_card_HABITEE(self):
        """La clé de contexte du partial — jumeau PAR CHAÎNE du renommage `job` → `elem`.

        `card_html` est la source unique du markup au rafraîchissement (le JS remplace le
        nœud entier). Renommer la variable DANS le gabarit sans renommer la clé qui l'alimente
        aurait rendu une card structurellement complète et TOTALEMENT VIDE — statut, nom de
        fichier, boutons : tout déréférencé sur un nom absent. Un `manage.py check` passe,
        aucun test de vue ne l'ouvrait. On exige donc du CONTENU, pas un 200.
        """
        from wama.converter.models import ConversionBatch, ConversionJob

        u = self._utilisateur('conv_card_html')
        lot = ConversionBatch.objects.create(user=u, total=1)
        job = ConversionJob.objects.create(user=u, batch=lot, status='SUCCESS',
                                           input_filename='temoin_habite.png',
                                           media_type='image', output_format='jpg')

        r = self.client.get(reverse('converter:card_html', args=[job.id]))
        self.assertEqual(200, r.status_code)
        html = r.content.decode('utf-8', 'replace')
        self.assertIn('temoin_habite.png', html,
                      'card VIDE : le gabarit lit `elem`, la vue alimente autre chose')
        self.assertIn(f'data-id="{job.id}"', html)
        self.assertIn('data-status="SUCCESS"', html)

    def test_le_gabarit_ne_recopie_plus_le_bloc_d_entree_de_file(self):
        """Le POINT du portage : plus une 11ᵉ copie, mais l'appel à la brique.

        Garde de non-retour — c'est la duplication elle-même qu'on interdit, pas son
        symptôme. Un futur correctif « local » qui réécrirait la boucle ici rendrait le
        converter à nouveau sourd aux corrections de la brique.
        """
        from pathlib import Path

        from django.conf import settings

        src = (Path(settings.BASE_DIR) / 'wama' / 'converter' / 'templates'
               / 'converter' / 'index.html').read_text(encoding='utf-8')
        self.assertIn("include 'common/_queue_entry.html'", src,
                      "le converter ne passe plus par la brique commune d'entrée de file")
        for recopie in ("{% for job in b.items %}", "{% for item in b.items %}"):
            self.assertNotIn(recopie, src,
                             f'boucle de file recopiée à la main ({recopie}) : la brique '
                             'la tient déjà')
