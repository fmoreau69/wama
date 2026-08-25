"""Brique de nommage des fichiers de sortie — `common/utils/output_naming.py`.

⚠ Le premier devoir de ces tests est de prouver que le portage NE CHANGE RIEN au rendu :
l'anonymizer et l'enhancer produisaient déjà `<stem>_<process>_<modèle><ext>`, et un fichier
dont le nom change est un fichier que l'utilisateur ne retrouve plus.
"""
from django.test import SimpleTestCase

from wama.common.utils.output_naming import compose_output_name, output_tag


class NommageDeSortieTests(SimpleTestCase):

    # ── Famille FICHIER : le rendu doit être celui d'AVANT, à l'octet ────────────
    def test_anonymizer_rend_exactement_la_graphie_historique(self):
        # Avant : f"{name}_blurred_{model_suffix}{ext}"  (core/anonymize.py:300 et :312)
        self.assertEqual(
            compose_output_name(app='anonymizer', model='yolov8n', source_name='reunion.mp4'),
            'reunion_blurred_yolov8n.mp4')

    def test_enhancer_rend_exactement_la_graphie_historique(self):
        # Avant : f"{base_name}_enhanced_{enhancement.ai_model}{ext}"  (tasks.py:400, :531)
        self.assertEqual(
            compose_output_name(app='enhancer', model='realesrgan', source_name='clip.mp4'),
            'clip_enhanced_realesrgan.mp4')

    def test_le_chemin_complet_en_entree_ne_garde_que_le_nom(self):
        self.assertEqual(
            compose_output_name(app='anonymizer', model='m', source_name='/a/b/c/photo.JPG'),
            'photo_blurred_m.JPG')

    def test_famille_fichier_sans_identifiant_reste_la_forme_historique(self):
        """L'identifiant est FACULTATIF ici : le plus souvent la souche suffit, le stockage
        Django ayant déjà rendu le nom d'entrée unique à l'upload."""
        self.assertEqual(
            compose_output_name(app='enhancer', model='m', source_name='a.mp4'),
            'a_enhanced_m.mp4')

    def test_famille_fichier_avec_identifiant_pour_les_entrees_NON_uniques(self):
        """Cas du converter : l'entrée peut venir d'un dossier MONTÉ, où deux jobs sur le même
        fichier produiraient le même nom. Remplace l'horodatage, unique mais muet."""
        self.assertEqual(
            compose_output_name(app='converter', source_name='rapport.docx',
                                item_id=42, ext='pdf'),
            'rapport_converted_42.pdf')

    # ── Famille PROMPT : l'identifiant de card remplace le nom d'origine ─────────
    def test_famille_prompt_porte_l_identifiant_de_card(self):
        self.assertEqual(
            compose_output_name(app='imager', model='flux', item_id=12, ext='png'),
            'gen12_flux.png')

    def test_sans_identifiant_le_nom_reste_compose_mais_n_est_plus_unique(self):
        """Documenté volontairement : c'est le défaut que `composer` porte encore."""
        self.assertEqual(compose_output_name(app='composer', model='musicgen', ext='.wav'),
                         'audio_musicgen.wav')

    # ── Multi-fichiers : le suffixe n'apparaît QUE s'il y en a plusieurs ─────────
    def test_une_seule_sortie_ne_porte_AUCUN_index(self):
        self.assertEqual(
            compose_output_name(app='imager', model='flux', item_id=3, ext='png',
                                index=1, total=1),
            'gen3_flux.png')

    def test_plusieurs_sorties_portent_un_index_1_based(self):
        # Cas réel : imager.num_images va de 1 à 4.
        noms = [compose_output_name(app='imager', model='flux', item_id=3, ext='png',
                                    index=i, total=4) for i in range(1, 5)]
        self.assertEqual(noms, ['gen3_flux_1.png', 'gen3_flux_2.png',
                                'gen3_flux_3.png', 'gen3_flux_4.png'])
        self.assertEqual(len(set(noms)), 4, "deux sorties d'une même card se marcheraient dessus")

    # ── Robustesse : ce qui casserait un chemin ou une URL ───────────────────────
    def test_un_identifiant_de_modele_HF_ne_cree_pas_de_sous_dossier(self):
        nom = compose_output_name(app='imager', model='Shakker-Labs/FLUX.1-dev-LoRA',
                                  item_id=1, ext='png')
        self.assertNotIn('/', nom, "le `/` d'un id HuggingFace créerait un dossier fantôme")
        self.assertEqual(nom, 'gen1_FLUX.1-dev-LoRA.png')

    def test_le_nom_D_ORIGINE_est_PRESERVE_accents_et_espaces_compris(self):
        """⚠ Décision du 2026-08-25. Une 1ʳᵉ version normalisait la souche : « Réunion équipe »
        devenait « Reunion-equipe ». La règle de la famille FICHIER est que l'utilisateur
        retrouve SON nom — et sur un labo francophone les accents sont le cas COURANT, pas
        un cas limite. L'ancien code les préservait depuis toujours sans incident.
        """
        self.assertEqual(
            compose_output_name(app='anonymizer', model='m',
                                source_name='Réunion équipe (2026).mp4'),
            'Réunion équipe (2026)_blurred_m.mp4')

    def test_mais_ce_qui_casserait_un_chemin_est_retire(self):
        nom = compose_output_name(app='anonymizer', model='m', source_name='a<b>c:d|e?f*g.mp4')
        for interdit in '<>:"|?*':
            self.assertNotIn(interdit, nom, f"{interdit!r} casse un chemin Windows")
        self.assertEqual(nom, 'abcdefg_blurred_m.mp4')

    def test_un_nom_tres_long_est_borne(self):
        nom = compose_output_name(app='anonymizer', model='m', source_name='a' * 400 + '.mp4')
        self.assertLessEqual(len(nom), 130, "un nom sans borne casse URL et Content-Disposition")
        self.assertTrue(nom.endswith('.mp4'), "l'extension doit survivre à la troncature")

    def test_une_extension_sans_point_est_acceptee(self):
        self.assertEqual(compose_output_name(app='composer', model='m', item_id=1, ext='wav'),
                         'audio1_m.wav')

    # ── Le mot de process est DÉCLARÉ, pas écrit dans les tâches ────────────────
    def test_le_tag_se_declare_dans_le_catalogue_et_prime_sur_le_repli(self):
        from unittest import mock
        from wama.common import app_registry
        faux = dict(app_registry.APP_CATALOG)
        faux['anonymizer'] = dict(faux.get('anonymizer') or {}, output_tag='anonymized')
        with mock.patch.object(app_registry, 'APP_CATALOG', faux):
            self.assertEqual(output_tag('anonymizer'), 'anonymized')
        # Sans déclaration, on retombe sur la graphie historique — jamais sur un trou.
        self.assertEqual(output_tag('anonymizer'), 'blurred')

    def test_une_app_inconnue_obtient_quand_meme_un_nom(self):
        self.assertEqual(
            compose_output_name(app='app_qui_nexiste_pas', model='m', item_id=2, ext='.txt'),
            'app_qui_nexiste_pas2_m.txt')
