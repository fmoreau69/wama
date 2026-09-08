"""Un premier lancement qui va TÉLÉCHARGER les poids le DIT à l'utilisateur.

POURQUOI (2026-09-08, constat de Fabien) : « à la première utilisation les poids sont
automatiquement téléchargés ; il faudrait vérifier si un message prévient l'utilisateur avant le
lancement de la tâche, sur la card, dans le cycle de vie ». Vérifié : le téléchargement existait
(37 appels `from_pretrained`/`snapshot_download`), **l'annonce non** — ni squelette, ni backend,
ni card. Quatre modèles catalogués sont dans ce cas (mochi-1-preview, qwen-image-edit,
flux2-klein-4b, musicgen-melody) : les lancer donnait une tâche figée, sans un mot, le temps de
récupérer des dizaines de Go.

⚠ Ce module SÈME ses cas : le catalogue de la base de TEST est vide, et un invariant qui
l'interroge mesurerait ce vide (défaut vécu deux fois cette session). L'état réel se lit avec
`check_backend_links` / la cartographie.
"""
from django.test import TestCase

from wama.common.utils.model_readiness import SEUIL_ANNONCE_GO, annoncer_telechargement


class AnnonceTelechargementTest(TestCase):

    def _semer(self, cle, *, telecharge, disk_gb=0.0, nom=''):
        from wama.model_manager.models import AIModel
        return AIModel.objects.create(
            model_key=cle, name=nom or cle, model_type='image',
            source=cle.split(':')[0], is_downloaded=telecharge, disk_gb=disk_gb)

    def _capter(self, cle):
        vues = []
        dit = annoncer_telechargement(cle, console=vues.append)
        return dit, vues

    def test_poids_absents__on_previent(self):
        self._semer('imager:jamais-utilise', telecharge=False, nom='Mochi')
        dit, vues = self._capter('imager:jamais-utilise')
        self.assertTrue(dit)
        self.assertEqual(len(vues), 1)
        self.assertIn('Mochi', vues[0])
        self.assertIn('téléchargement', vues[0].lower())

    def test_poids_presents__on_se_TAIT(self):
        """Le contre-exemple qui compte : un avertissement permanent n'avertit plus de rien.
        C'est le défaut qu'on retire de l'imager vidéo (message en dur à chaque lancement)."""
        self._semer('imager:deja-la', telecharge=True)
        dit, vues = self._capter('imager:deja-la')
        self.assertFalse(dit)
        self.assertEqual(vues, [])

    def test_modele_inconnu_du_catalogue__on_ne_dit_rien(self):
        """On ne parle que de ce qu'on SAIT : pas de ligne, pas d'annonce."""
        dit, vues = self._capter('imager:jamais-catalogue')
        self.assertFalse(dit)
        self.assertEqual(vues, [])

    def test_la_taille_n_est_annoncee_que_si_elle_est_CONNUE(self):
        """`disk_gb` vaut 0 tant qu'un modèle n'a jamais été téléchargé — on n'invente pas un
        volume (l'ancien message en dur annonçait « ~5-10GB » pour tout modèle vidéo)."""
        self._semer('imager:sans-taille', telecharge=False, disk_gb=0.0)
        _, sans = self._capter('imager:sans-taille')
        self.assertNotIn('~', sans[0])

        self._semer('imager:avec-taille', telecharge=False, disk_gb=18.0)
        _, avec = self._capter('imager:avec-taille')
        self.assertIn('~18 Go', avec[0])

    def test_une_taille_negligeable_n_est_pas_annoncee(self):
        self._semer('imager:minuscule', telecharge=False, disk_gb=SEUIL_ANNONCE_GO / 2)
        _, vues = self._capter('imager:minuscule')
        self.assertNotIn('~', vues[0])

    def test_une_console_qui_leve_ne_casse_JAMAIS_la_tache(self):
        """Prévenir est un confort, pas une condition — la règle de toute la couche console."""
        self._semer('imager:console-cassee', telecharge=False)

        def _explose(_):
            raise RuntimeError('console indisponible')

        self.assertTrue(annoncer_telechargement('imager:console-cassee', console=_explose))

    def test_sans_console_on_ne_leve_pas(self):
        self._semer('imager:sans-console', telecharge=False)
        self.assertTrue(annoncer_telechargement('imager:sans-console'))

    def test_cle_vide_ne_leve_pas(self):
        self.assertFalse(annoncer_telechargement(''))
        self.assertFalse(annoncer_telechargement(None))


class SqueletteAnnonceTest(TestCase):
    """Le squelette commun sait le déclarer — comme `vram_needed`, et OPTIONNEL."""

    def test_le_squelette_accepte_model_key(self):
        import inspect
        from wama.common.utils.task_skeleton import run_item_task
        params = inspect.signature(run_item_task).parameters
        self.assertIn('model_key', params)
        self.assertIsNone(params['model_key'].default,
                          'la déclaration doit être OPTIONNELLE : une app qui ne la pose pas '
                          'garde exactement le comportement d’avant')
