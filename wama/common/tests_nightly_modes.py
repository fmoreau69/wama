"""Modes du runner nocturne — le mode « sans GPU » est-il RÉEL ?

⚠⚠ POURQUOI CE FICHIER (2026-09-06, question de Fabien : « on a normalement des modes dans les
tests nocturnes pour n'effectuer que des parties des tests, notamment pour écarter les tests
mettant en œuvre le GPU. On est ok ? »).

La réponse mesurée était **non, pas vraiment** : `Scenario.vram_gb` était déclaré sur chaque
scénario depuis l'origine — commenté « info de planification » — et **lu par personne**. Aucun
filtre ne s'en servait. L'exclusion du GPU reposait entièrement sur le fait de SAVOIR que les
étages `model_loaded` et `output` sont les étages GPU, et sur la discipline de passer
`--stage ui`.

*Un champ qui a l'air d'une garde sans en être une est pire qu'un champ absent : il fait croire
que la protection existe.* Ces tests sont ce qui empêche la garde de redevenir décorative.
"""

from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from wama.common.services import nightly_tests


class ModeSansGpuTest(SimpleTestCase):
    """Le plafond de VRAM filtre-t-il RÉELLEMENT, et le dit-il ?"""

    def setUp(self):
        # Registre isolé : on ne dépend pas de ce que les apps enregistrent (le parc bouge),
        # et on ne laisse rien derrière. Trois scénarios suffisent à couvrir les trois cas.
        self._registre = nightly_tests.REGISTRY
        nightly_tests.REGISTRY = []
        for ident, vram in (('t.cpu', 0.0), ('t.leger', 1.0), ('t.lourd', 10.0)):
            nightly_tests.register(
                id=ident, app='t', stage='ui', description=f'témoin {ident}',
                run=lambda ctx: (True, 'témoin'), vram_gb=vram,
            )

    def tearDown(self):
        nightly_tests.REGISTRY = self._registre

    def _lister(self, *args):
        sortie = StringIO()
        call_command('run_nightly_tests', '--dry-run', *args, stdout=sortie)
        return sortie.getvalue()

    def test_par_defaut_les_scenarios_a_vram_sont_ecartes(self):
        """Le défaut est l'EXCLUSION — décision Fabien : le passage nocturne est sans GPU."""
        texte = self._lister()
        self.assertIn('t.cpu', texte)
        self.assertNotIn('t.leger (cible', texte)
        self.assertNotIn('t.lourd (cible', texte)

    def test_l_exclusion_n_est_JAMAIS_silencieuse(self):
        """Une exclusion muette se lit comme une couverture — c'est le faux vert que tout
        `WAMA_VERIFICATION` traque. Le runner doit NOMMER ce qu'il écarte et dire comment
        le rejouer."""
        texte = self._lister()
        self.assertIn('ÉCARTÉ', texte)
        self.assertIn('t.leger', texte)
        self.assertIn('t.lourd', texte)
        self.assertIn('--with-gpu', texte, "le message doit dire comment les jouer")

    def test_avec_gpu_les_reintegre_tous(self):
        texte = self._lister('--with-gpu')
        for ident in ('t.cpu', 't.leger', 't.lourd'):
            self.assertIn(ident, texte)

    def test_un_plafond_intermediaire_trie_par_VRAM_declaree(self):
        """`--max-vram` sert le jour où l'on rouvrira le GPU progressivement : jouer les
        scénarios légers sans les lourds, plutôt que tout ou rien."""
        texte = self._lister('--max-vram', '2')
        self.assertIn('t.cpu', texte)
        self.assertIn('t.leger', texte)
        self.assertNotIn('t.lourd (cible', texte)


class DeclarationVramTest(SimpleTestCase):
    """Hygiène des déclarations sur le registre RÉEL — le filtre ne vaut que ce qu'elles valent.

    ⚠ Ce contrôle ne peut PAS attester qu'un scénario déclaré à 0 ne touche pas le GPU par un
    chemin détourné : le triage VLM d'une batterie UI a provoqué deux crashs hôte le 02/09 en
    étant, lui, parfaitement « sans VRAM déclarée ». La déclaration ENGAGE son auteur ; ce test
    vérifie seulement qu'elle est exploitable.
    """

    def test_toute_declaration_de_vram_est_un_nombre_positif(self):
        from wama.common.services.nightly_tests import REGISTRY, register_examples
        register_examples()
        # ⚠ Un contrôle sur un registre VIDE passe toujours — « 0 FAIL sur du VIDE », piège
        # déjà rencontré deux fois dans ce dépôt (project_backend_capabilities). On exige
        # d'abord d'avoir quelque chose à contrôler.
        self.assertGreater(len(REGISTRY), 50,
                           "registre quasi vide : ce test ne contrôlerait rien")
        fautifs = [s.id for s in REGISTRY
                   if not isinstance(s.vram_gb, (int, float)) or s.vram_gb < 0]
        self.assertEqual([], fautifs,
                         f"vram_gb inexploitable (le filtre les laisserait passer) : {fautifs}")

    def test_les_scenarios_qui_CHARGENT_un_modele_declarent_leur_VRAM(self):
        """Un scénario d'étage `model_loaded` charge un backend par définition : sans VRAM
        déclarée, il passerait dans un passage « sans GPU » sans que rien ne l'arrête.

        ⚠ L'étage `output` n'est PAS soumis à la même exigence, et ce n'est pas un oubli :
        `studio.pipeline.converter` va jusqu'au résultat en ffmpeg pur (CPU), et lui imposer
        une VRAM fictive l'exclurait du passage nocturne sans aucune raison. C'est la CHARGE
        qui décide, pas la profondeur.
        """
        from wama.common.services.nightly_tests import REGISTRY, register_examples
        register_examples()
        etage = [s for s in REGISTRY if s.stage == 'model_loaded']
        self.assertTrue(etage, "aucun scénario `model_loaded` : rien à contrôler ici")
        muets = [s.id for s in REGISTRY if s.stage == 'model_loaded' and not (s.vram_gb or 0)]
        self.assertEqual([], muets,
                         f"étage `model_loaded` sans vram_gb — jouerait en mode sans GPU : {muets}")
