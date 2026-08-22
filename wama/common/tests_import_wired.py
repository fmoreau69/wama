"""Critère `import_wired` (trou #26 de la route) — preuve qu'il attrape le défaut HISTORIQUE.

Un critère qui passe au vert partout le jour où on l'écrit ne prouve rien : il peut être vert
parce que tout va bien, ou vert parce qu'il ne regarde pas au bon endroit. Les deux se
ressemblent exactement dans un rapport. Ces tests le mettent donc face à la forme EXACTE qui a
laissé converter_01 inerte le 2026-08-22 — gabarit qui rend la card d'entrée commune sans
jamais charger la moindre voie d'import — et exigent un ROUGE.

Ils gardent aussi les deux faux verdicts commis en écrivant le critère (mêmes dates), parce
qu'un critère se régresse aussi facilement qu'un écran :
  ① markup cherché seulement dans l'app → 10 apps déclarées « sans card d'entrée » alors que la
     card est INCLUSE depuis `common/` ;
  ② motif écrit sur `{% static %}` et `batch_import.js` alors que le projet écrit `{% static_v %}`
     et `batch-import.js` → converter déclaré en échec alors que son scénario d'import est vert.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import SimpleTestCase


def _mesure(nom: str, fichiers: dict) -> tuple:
    """Monte une app FICTIVE sur disque et lui applique le critère.

    On écrit de vrais fichiers plutôt que de simuler `_AppFiles` : le critère lit des gabarits,
    et c'est justement sa lecture qu'on veut éprouver (un mock de la lecture testerait le mock).
    """
    from wama.common.services import conformity_checker as cc
    with TemporaryDirectory() as tmp:
        racine = Path(tmp)
        for rel, contenu in fichiers.items():
            cible = racine / nom / rel
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_text(contenu, encoding='utf-8')
        with mock.patch.object(cc, 'WAMA_ROOT', racine):
            return cc._import_wired(cc._AppFiles(nom))


CARD = "{% include 'common/_new_item_card.html' %}"


class ImportWiredTests(SimpleTestCase):

    def test_depot_rendu_sans_aucune_voie_chargee_est_ROUGE(self):
        """LE cas de converter_01 (2026-08-22) : la card est là, rien ne la lit.

        C'est le défaut le plus silencieux de la route — aucune erreur console, puisque rien
        n'est chargé, donc rien ne plante. Si ce test passe au vert, le critère est inutile.
        """
        etat, preuve = _mesure('appfictive', {
            'templates/appfictive/index.html': f"<h1>App</h1>\n{CARD}\n",
        })
        self.assertIs(etat, False)
        self.assertIn("AUCUNE voie d'import", preuve)

    def test_un_COMMENTAIRE_qui_cite_app_scripts_ne_sauve_pas(self):
        """Le gabarit généré porte un `{% comment %}` qui CITE `app_scripts` pour l'expliquer.

        Un critère qu'un commentaire fait passer au vert devine au lieu de mesurer — c'est
        exactement ce qui avait rendu `inspector_adapters` faux (19/08). D'où `find_code`.
        """
        etat, _ = _mesure('appfictive', {
            'templates/appfictive/index.html':
                f"{CARD}\n{{% comment %}}il faudrait un block app_scripts ici{{% endcomment %}}\n",
        })
        self.assertIs(etat, False)

    def test_inclusion_de_la_brique_commune_est_VERT(self):
        etat, preuve = _mesure('appfictive', {
            'templates/appfictive/index.html':
                f"{CARD}\n{{% block app_scripts %}}"
                f"{{% include 'common/_app_scripts.html' %}}{{% endblock %}}\n",
        })
        self.assertIs(etat, True)
        self.assertTrue(preuve)

    def test_idiome_REEL_du_projet_static_v_et_batch_import_a_tiret(self):
        """Garde du faux négatif n°② : `{% static_v %}` et `batch-import.js`.

        Écrit sur `{% static %}` / `batch_import.js`, le motif déclarait le converter en échec
        alors que son scénario d'import de bout en bout était VERT le matin même.
        """
        for ligne in ("<script src=\"{% static_v 'appfictive/js/appfictive.js' %}\"></script>",
                      "<script src=\"{% static_v 'common/js/batch-import.js' %}\"></script>"):
            with self.subTest(ligne=ligne):
                etat, _ = _mesure('appfictive', {
                    'templates/appfictive/index.html': f"{CARD}\n{ligne}\n",
                })
                self.assertIs(etat, True)

    def test_le_JS_existe_mais_n_est_PAS_charge_reste_ROUGE(self):
        """La distinction qui fait tout le critère : exister ≠ être chargé.

        converter_01 avait bien son JS dans `static/` — il n'était simplement jamais inclus.
        Un critère qui regarde `static/**/*.js` conclurait « présent » et raterait le défaut.
        """
        etat, _ = _mesure('appfictive', {
            'templates/appfictive/index.html': f"{CARD}\n",
            'static/appfictive/js/appfictive.js': "console.log('jamais charge');\n",
        })
        self.assertIs(etat, False)

    def test_surface_sans_card_d_entree_est_NON_APPLICABLE(self):
        """Gestionnaire de modèles, studio : pas de dépôt, donc rien à écouter.

        `None` et non `False` : une barrière qui crie au loup hors périmètre finit non relue.
        Même exemption que le scénario nocturne `<app>.import`, pour que les deux mesures
        racontent la même histoire.
        """
        etat, preuve = _mesure('appfictive', {
            'templates/appfictive/index.html': "<h1>Tableau de bord</h1>\n",
        })
        self.assertIsNone(etat)
        self.assertIn("aucune card d'entrée", preuve)
