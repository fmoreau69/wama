"""Tests de `check_model_completeness` — la carte des trous des modèles INSTALLÉS.

Ce contrôle est né du 🔚 point d'entrée du 02/09 (« vérifier les informations de l'ENSEMBLE
des modèles installés »). Ce qu'il faut protéger tient en deux points, tous deux appris à
la mesure du 03/09 :

  1. **la SÉPARATION des deux situations de backend.** `backend_missing()` est PERMISSIF par
     construction : pas de moteur déclaré ⇒ pas de verdict (décision écrite dans
     `manager.py:32-35`). Le rapport distingue donc « on SAIT qu'il manque un backend »
     (`backend_rouge`, actionnable — c'est Qwen3-TTS) de « le modèle est hors du périmètre
     du verdict » (`backend_hors_verdict`). Les fondre en un seul compte ferait disparaître
     la nuance qui décide s'il y a quelque chose à faire ;
  2. **le contrôle NE GARDE RIEN** — un backend écrit dont le runtime attend un GO humain
     est un état légitime. Un gate rouge en permanence se relit comme la normale.

⚠⚠ `backend_hors_verdict` NE VEUT PAS DIRE « cassé » — rectification du 03/09 même (recadrage
Fabien : « normalement le grisage est effectif de bout en bout ». Il l'EST : `backend_missing`
→ `get_registry_models` → `data-backend-missing` → grisage client → exclusion du tirage,
chaîne vérifiée maillon par maillon). Décomposition MESURÉE des 16 du jour : **10** sont des
lignes `huggingface:*` non rattachées à une app, donc absentes de tout select (filtré par
`source`) ; **6** sont routées par le gestionnaire de backends propre à leur app
(composer/reader, antérieur à l'inventaire commun) et fonctionnent. **Aucune n'est cassée.**
Le seul constat sans réserve est table-transformer, dont le backend EXISTE (B2 n°1) sans
qu'aucune ligne ne le déclare.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from wama.model_manager.models import AIModel


def _installe(model_key, **extra):
    return AIModel.objects.create(
        model_key=model_key, name=model_key, model_type='speech', source='synthesizer',
        vram_gb=extra.pop('vram_gb', 4.0), is_downloaded=True, is_available=True,
        license=extra.pop('license', 'mit'),
        capabilities=extra.pop('capabilities', {'task': 'text-to-speech'}),
        **extra,
    )


def _rapport(**kwargs):
    import json
    sortie = StringIO()
    call_command('check_model_completeness', '--json', stdout=sortie, **kwargs)
    return json.loads(sortie.getvalue())


class CompletenessTest(TestCase):

    def test_un_modele_sans_moteur_ni_backend_ref_sort_du_perimetre_du_verdict(self):
        """`backend_missing()` rend None (pas de verdict, par permissivité VOULUE) : ni le
        select ni le tirage n'ont rien à dire de ce modèle. Ce n'est pas un défaut du
        grisage — c'est son périmètre. Le rapport est le seul endroit où cette population
        se COMPTE, ce qui permet de la décomposer (non rattachée à une app / routée par
        l'app elle-même) plutôt que de la découvrir au cas par cas."""
        _installe('test:sans-moteur', composition={})
        axes = _rapport()['axes']
        self.assertIn('test:sans-moteur', axes['backend_hors_verdict'])
        self.assertNotIn('test:sans-moteur', axes['backend_rouge'])

    def test_un_backend_ref_pose_sort_le_modele_du_hors_verdict(self):
        """`backend_ref` = « l'app assume son moteur » (doctrine de `backend_missing`).
        Le rapport doit suivre la MÊME règle que le grisage, sinon il accuserait des
        modèles que le système considère servis."""
        _installe('test:avec-backend-ref', backend_ref='ollama', composition={})
        axes = _rapport()['axes']
        self.assertNotIn('test:avec-backend-ref', axes['backend_hors_verdict'])
        self.assertNotIn('test:avec-backend-ref', axes['backend_rouge'])

    def test_un_moteur_declare_sans_inventaire_est_rouge_pas_hors_verdict(self):
        """Deux situations à ne JAMAIS confondre : « on SAIT qu'il manque un backend »
        (rouge — actionnable, c'est Qwen3-TTS, et le tirage l'exclut) et « le modèle est
        hors du périmètre du verdict » (garde permissive — rien à faire dans la plupart
        des cas). Les fondre en un seul compte ferait lire la seconde comme la première,
        c'est-à-dire annoncer des pannes là où il n'y en a pas."""
        _installe('test:moteur-inconnu',
                  composition={'runtime': {'engine': 'moteur-qui-nexiste-pas'}})
        axes = _rapport()['axes']
        self.assertIn('test:moteur-inconnu', axes['backend_rouge'])
        self.assertNotIn('test:moteur-inconnu', axes['backend_hors_verdict'])

    def test_licence_et_vram_manquantes_sont_relevees(self):
        """Une licence inconnue bloque toute décision de diffusion (LICENSING.md) et une
        VRAM nulle fait échapper le modèle à la sélection VRAM-aware — deux trous qui
        n'empêchent pas le modèle de paraître parfaitement installé."""
        _installe('test:sans-licence', license='', backend_ref='x')
        _installe('test:sans-vram', vram_gb=0, backend_ref='x')
        axes = _rapport()['axes']
        self.assertIn('test:sans-licence', axes['sans_licence'])
        self.assertIn('test:sans-vram', axes['vram_absente'])

    def test_une_vram_estimee_est_distinguee_d_une_vram_absente(self):
        """`vram_estimated` était ÉCRIT par la découverte et relu par personne. Un plancher
        estimé depuis les poids n'est pas une absence : il est utilisable, il attend juste
        un banc. Les confondre ferait réestimer ce qui l'est déjà."""
        _installe('test:vram-estimee', vram_gb=3.1, backend_ref='x',
                  extra_info={'vram_estimated': True})
        axes = _rapport()['axes']
        self.assertIn('test:vram-estimee', axes['vram_estimee'])
        self.assertNotIn('test:vram-estimee', axes['vram_absente'])

    def test_le_controle_ne_garde_rien_meme_avec_des_trous(self):
        """DÉCISION EXPLICITE, protégée ici parce qu'elle est tentante à « corriger » :
        aucun constat de ce rapport n'est interdit (un backend écrit dont le runtime attend
        un GO humain est légitime). Un gate rouge en permanence finit par être relu comme
        la normale — le défaut que `/reprise` documente sur son attendu de suite."""
        _installe('test:trou', license='', vram_gb=0, composition={})
        try:
            call_command('check_model_completeness', stdout=StringIO())
        except SystemExit as e:                      # pragma: no cover — le régression-cas
            self.fail(f"le contrôle a gardé (exit {e.code}) : c'est une CARTE, pas un gate")

    def test_les_lignes_yolo_sont_repliees_par_defaut(self):
        """~47 lignes de même forme, déclarées en famille : les déplier noierait les trous
        réels. `--yolo` reste disponible pour qui veut les voir."""
        _installe('test:yolo11n-seg', composition={})
        replies = _rapport()['yolo_replies']
        self.assertGreaterEqual(replies, 1)
        self.assertNotIn('test:yolo11n-seg', _rapport()['axes']['backend_hors_verdict'])
        self.assertIn('test:yolo11n-seg', _rapport(yolo=True)['axes']['backend_hors_verdict'])
