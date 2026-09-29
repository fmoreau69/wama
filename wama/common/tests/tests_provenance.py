"""PROVENANCE D'UNE ENTRÉE — le lien source ⟷ copie de travail.

Décision Fabien du 2026-09-07, motivée dans `MEDIA_STORAGE_TIERING §8.7`. Ces tests tiennent
les quatre invariants qui ont justifié la brique — chacun correspond à un geste demandé et
impossible jusqu'ici.
"""
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

User = get_user_model()


class ProvenanceMixin:
    def setUp(self):
        self.user = User.objects.create_user('prov_test', password='x')
        self.racine = Path(tempfile.mkdtemp())

    def _fichier(self, nom='wama_temoin_prov.txt', contenu=b'bonjour'):
        f = self.racine / nom
        f.write_bytes(contenu)
        return f

    def _element(self):
        """Un élément RÉEL porteur d'un FileField — le describer est le plus simple."""
        from wama.describer.models import Description
        return Description.objects.create(user=self.user, detected_type='text')


class EnregistrementTest(ProvenanceMixin, TestCase):

    def test_la_brique_de_COPIE_enregistre_seule_quand_elle_connait_l_element(self):
        """Le cœur du contrat : une app n'écrit JAMAIS sa provenance elle-même.

        Si `copy_into_app_input` cessait d'enregistrer, chaque app devrait le faire — et on
        retrouverait les graphies divergentes que ce dépôt ferme partout ailleurs.
        """
        from wama.common.utils.media_paths import copy_into_app_input
        from wama.common.utils.provenance import provenance_of

        elem = self._element()
        src = self._fichier()
        with override_settings(MEDIA_ROOT=str(self.racine)):
            copy_into_app_input(src, 'describer', self.user.id, 'input',
                                for_instance=elem, field='input_file')
        p = provenance_of(elem, 'input_file')
        self.assertIsNotNone(p, 'la copie n’a pas enregistré la provenance')
        self.assertEqual('temp', p.kind)
        self.assertEqual('wama_temoin_prov.txt', p.original_name)
        self.assertEqual(len(b'bonjour'), p.size)
        self.assertEqual(64, len(p.sha256), 'empreinte non calculée sur un petit fichier')

    def test_une_seule_provenance_par_entree_la_seconde_REMPLACE(self):
        """Elle décrit un ÉTAT (d'où vient l'entrée AUJOURD'HUI), pas un journal. Empiler
        rendrait l'index inverse ambigu — quelle ligne dit la vérité ?"""
        from wama.common.models import InputProvenance
        from wama.common.utils.provenance import record_import

        elem = self._element()
        record_import(elem, 'input_file', self._fichier('a.txt'))
        record_import(elem, 'input_file', self._fichier('b.txt'))
        lignes = InputProvenance.objects.filter(object_id=elem.pk, field='input_file')
        self.assertEqual(1, lignes.count())
        self.assertEqual('b.txt', lignes.first().original_name)

    def test_deux_CHAMPS_du_meme_element_ont_chacun_leur_provenance(self):
        """L'avatarizer a un visage ET une voix : la clé porte le champ, sinon la seconde
        entrée écraserait la première."""
        from wama.common.models import InputProvenance
        from wama.common.utils.provenance import record_import

        elem = self._element()
        record_import(elem, 'input_file', self._fichier('visage.png'))
        record_import(elem, 'output_file', self._fichier('voix.wav'))
        self.assertEqual(2, InputProvenance.objects.filter(object_id=elem.pk).count())

    def test_un_echec_d_enregistrement_ne_fait_JAMAIS_echouer_l_import(self):
        """Règle de tête de module, même famille que « une copie `-o` qui échoue ne fait pas
        échouer le job » : perdre la trace est regrettable, perdre le fichier ne l'est pas."""
        from wama.common.utils.provenance import record_provenance

        class SansUtilisateur:                       # ni `user`, ni `pk` exploitable
            pk = None
            _meta = type('M', (), {'app_label': 'x'})()

        self.assertIsNone(record_provenance(SansUtilisateur(), 'f', kind='temp', ref='r'))


class IndexInverseTest(ProvenanceMixin, TestCase):
    """La question que le gestionnaire de fichiers n'a jamais pu poser : « qui référence ce
    fichier ? » C'est elle qui lève la seule objection restée debout contre le pointage
    (`§8.7` (a)) — non pas en interdisant la suppression, mais en la rendant INFORMÉE."""

    def test_on_retrouve_TOUTES_les_cards_qui_designent_une_source(self):
        from wama.common.utils.provenance import record_import, ref_for, referenced_by

        src = self._fichier('partagee.txt')
        a, b = self._element(), self._element()
        record_import(a, 'input_file', src)
        record_import(b, 'input_file', src)

        trouvees = referenced_by('temp', ref_for(src))
        self.assertEqual(2, len(trouvees))
        self.assertEqual({a.pk, b.pk}, {t.object_id for t in trouvees})

    def test_une_source_que_personne_ne_designe_rend_une_liste_VIDE(self):
        from wama.common.utils.provenance import referenced_by
        self.assertEqual([], referenced_by('temp', 'jamais/importe.txt'))

    def test_la_DEDUPLICATION_retrouve_une_copie_deja_faite_du_MEME_utilisateur(self):
        """« Même source, même copie » — le geste qu'`Envoyer vers` rend nécessaire : chaîner
        describer → imager → enhancer produit aujourd'hui TROIS copies des mêmes octets.

        ⚠ `same_source` RÉPOND, elle ne déduplique pas : réutiliser la copie appartient à
        l'appelant, parce qu'une card en cours de traitement ne doit pas voir son entrée
        partagée sous ses pieds.
        """
        from wama.common.utils.provenance import record_import, ref_for, same_source

        src = self._fichier('source_unique.txt')
        a = self._element()
        record_import(a, 'input_file', src)

        self.assertIsNotNone(same_source('temp', ref_for(src), self.user))
        autre = User.objects.create_user('prov_autre', password='x')
        self.assertIsNone(same_source('temp', ref_for(src), autre),
                          'la dédup ne doit JAMAIS traverser les utilisateurs')


class RegleDeReferenceTest(ProvenanceMixin, TestCase):

    def test_une_source_sous_MEDIA_ROOT_est_designee_par_son_chemin_RELATIF(self):
        """Les deux moitiés de la brique (`copy_into_app_input` et `record_import`) doivent
        calculer la MÊME adresse — deux règles divergentes et l'index inverse cesse de
        retrouver ses sources."""
        from wama.common.utils.provenance import ref_for

        src = self._fichier('dedans.txt')
        with override_settings(MEDIA_ROOT=str(self.racine)):
            self.assertEqual('dedans.txt', ref_for(src))

    def test_une_source_HORS_media_garde_son_chemin_brut(self):
        """Un montage vit hors `MEDIA_ROOT` : on le désigne tel quel plutôt que d'inventer."""
        from wama.common.utils.provenance import ref_for
        with override_settings(MEDIA_ROOT=str(self.racine / 'ailleurs')):
            chemin = self._fichier('dehors.txt')
            self.assertEqual(str(chemin), ref_for(chemin))

    def test_l_empreinte_n_est_PAS_calculee_au_dela_du_seuil(self):
        """Lire 8 Go depuis un montage SMB pour une trace coûterait plus qu'elle ne rapporte.
        Une empreinte vide veut dire « non calculée », jamais « fichier vide »."""
        from wama.common.utils.provenance import sha256_of

        src = self._fichier('gros.bin', b'x' * 5000)
        self.assertEqual('', sha256_of(src, limite=100))
        self.assertEqual(64, len(sha256_of(src, limite=10000)))
