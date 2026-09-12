"""Le cam_analyzer écrit-il, et POINTE-t-il, au domicile de l'utilisateur ?

⚠ POURQUOI CETTE GARDE EXISTE ALORS QU'IL Y EN A DÉJÀ TROIS DANS `wama/common/`.
Le portage du 2026-09-12 vers `app_media_dir` (P2b) a laissé **deux** sites du cam_analyzer,
trouvés à la clôture du 12/09 — et les trois gardes communes les ont tous les deux laissés
passer, pour la MÊME raison :

    `AucuneEcritureNeRecomposeUnCheminDAppTest.IDIOME` exige `MEDIA_ROOT` **sur la ligne**.

  * `models.py::depth_output_dir` composait `cam_analyzer/<uid>/depth/…` sur une ligne, et
    n'appliquait `MEDIA_ROOT` que **deux lignes plus bas** — l'idiome ne voit qu'une ligne ;
  * `tasks.py` déclarait le chemin RELATIF de la vidéo annotée (`cam_analyzer/<uid>/output/…`),
    celui que le front concatène à `/media/`. Il n'y a **jamais** de `MEDIA_ROOT` sur ce
    chemin-là : il ne sert pas à écrire, il sert à POINTER.

Et les deux défauts n'avaient pas la même gravité, ce qui est la leçon utile :
`depth_output_dir` était **latent** (0 `DepthFrame` en base, la passe est GPU et n'a jamais
tourné ici) ; la vidéo annotée était **active** — le fichier partait au nouveau domicile
pendant que le lien de l'UI pointait sur l'ancien. *Un chemin d'ÉCRITURE se trahit au premier
run ; un chemin de LECTURE se trahit à la première visite, et personne ne relit un lien.*

Cette garde-ci ne demande donc PAS `MEDIA_ROOT` : elle regarde le nom de l'app collé à une
expression d'utilisateur, où qu'il soit. Elle ne couvre que le cam_analyzer — l'angle mort
de la garde commune est signalé au handoff du 12/09 à l'instance qui porte `media_paths`.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

RACINE_APP = Path(__file__).resolve().parent


class DepthOutputDirTest(SimpleTestCase):
    """Le dossier des cartes de profondeur dérive de la brique commune."""

    def test_le_dossier_de_profondeur_vit_sous_le_domicile_de_l_utilisateur(self):
        import uuid

        from django.contrib.auth import get_user_model

        from .models import AnalysisSession, CameraView, depth_output_dir

        session = AnalysisSession()
        session.id = uuid.uuid4()
        session.user = get_user_model()(id=7)
        camera = CameraView()
        camera.session = session
        camera.position = 'front'

        rendu = depth_output_dir(camera).replace('\\', '/')
        self.assertTrue(
            rendu.startswith('users/7/cam_analyzer/depth/'),
            f"la profondeur s'écrirait hors du domicile de l'utilisateur : {rendu}")
        self.assertIn(str(session.id), rendu)
        self.assertTrue(rendu.endswith('/front'), rendu)

    def test_le_repli_user_id_zero_est_mort_parce_que_le_champ_est_obligatoire(self):
        """`depth_output_dir` porte un repli `… else 0` — il est INATTEIGNABLE, et tant mieux.

        ⚠ Écrit après coup, ce test a d'abord été rédigé pour VÉRIFIER le repli : il rend
        `RelatedObjectDoesNotExist`, pas `0`. Django lève sur l'accès à une clé étrangère
        non renseignée — le `if session.user else 0` ne peut donc jamais choisir sa branche
        droite. Le repli n'est pas un bug tant que le champ reste obligatoire ; il le
        DEVIENDRAIT le jour où quelqu'un poserait `null=True`, en faisant écrire les cartes
        de profondeur dans un domicile `users/0/` qui n'appartient à personne.
        *Un repli ne se lit pas, il se mesure : celui-ci ne protège rien, c'est le SCHÉMA
        qui protège.*
        """
        from .models import AnalysisSession

        champ = AnalysisSession._meta.get_field('user')
        self.assertFalse(
            champ.null,
            "AnalysisSession.user est devenu nullable : le repli `else 0` de "
            "depth_output_dir est désormais ATTEIGNABLE et écrirait dans users/0/")


class AucunCheminCamAnalyzerEcritALaMainTest(SimpleTestCase):
    """Aucun module du cam_analyzer ne colle `cam_analyzer` à un identifiant d'utilisateur.

    ⚠ Volontairement SANS `MEDIA_ROOT` dans le motif — c'est exactement ce que la garde
    commune exige et c'est par là que les deux sites du 12/09 sont passés.
    """

    #: le nom de l'app en littéral, puis une expression d'utilisateur à moins de 25 caractères ;
    #: ou la forme f-string `cam_analyzer/{…}` (chemin relatif rendu au front).
    IDIOME = re.compile(r"""['"]cam_analyzer['"].{0,25}(user|str\(user)|cam_analyzer/\{""")

    def test_aucun_module_ne_compose_de_chemin_cam_analyzer_par_utilisateur(self):
        fautifs = []
        for py in RACINE_APP.rglob('*.py'):
            if 'migrations' in py.parts or py.name.startswith(('tests_', 'test_')):
                continue
            for no, ligne in enumerate(
                    py.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                if self.IDIOME.search(ligne) and 'app_media_dir' not in ligne:
                    fautifs.append(f'{py.relative_to(RACINE_APP).as_posix()}:{no}')
        self.assertEqual(
            [], fautifs,
            "un chemin média du cam_analyzer est composé à la main : il écrira — ou pointera — "
            "dans l'ANCIEN arbre pendant que le parc est au domicile, et rien ne le signalera : "
            + ', '.join(fautifs))
