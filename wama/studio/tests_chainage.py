"""Diagnostic de CHAÎNAGE d'un graphe studio — types, champs, et ce qu'on n'a pas le droit
de contrôler.

⚠ POURQUOI CE MODULE. `can_connect()` existe depuis longtemps et vérifie DEUX choses : la
compatibilité de type ET la satisfaction des `required_fields`. Mesuré le 2026-09-09 : elle
n'était appelée que par des tests — le canvas ne valide que les TYPES (intersection, côté
navigateur), et les champs n'étaient vérifiés nulle part.

Ce module tient les trois invariants que la mise en service a coûtés :

  ① l'ACCUMULATION est la condition, pas un raffinement — alimenter le contrôle avec les
     seuls `produced_fields` de l'amont refuse `calc_rolling → calc_per_segment`, une
     connexion que la suite déclare VALIDE (un enrichisseur ne « produit » pas les colonnes
     qu'il laisse passer) ;
  ② un lien vers un nœud `app`-bound ORDONNE, il ne transporte rien — l'exécuteur lance ces
     nœuds avec leurs `params` et ne leur passe AUCUNE frame. La première version du
     diagnostic l'ignorait et rendait 10 refus sur les 18 liens du seul pipeline réel du
     corpus, un pipeline qui tourne. *Un lien ne dit pas toujours « ceci coule vers cela » ;*
  ③ INCONNU n'est pas VIDE — un amont sans ports déclarés rend les champs non mesurables :
     on s'abstient, on ne refuse pas. Même doctrine que `AIModel.gated`.
"""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.catalog import function_catalog as fc
from wama.common.catalog.function_catalog import can_connect, champs_apres
from wama.studio.services.launch import diagnostiquer_chainage


def _noeud(nid, cle):
    return {'id': nid, 'kind': 'function', 'function': cle, 'app': None, 'params': {}}


def _lien(a, b, port=None):
    return {'from': a, 'to': b, 'to_port': port}


class ChampsApresTest(SimpleTestCase):
    """La loi d'accumulation — c'est la règle §9quater.4 appliquée aux CHAMPS."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fc.load_all()

    def test_un_enrichisseur_laisse_PASSER_les_champs_amont(self):
        # `calc_rolling` est `enricher` : granularité intacte, donc `time`/`value` survivent
        # alors même que son port ne les « produit » pas (`produced_fields == []`).
        sortie = fc.get('calc_rolling').outputs[0]
        self.assertEqual(champs_apres(sortie, 'calc_rolling', {'time', 'value'}),
                         {'time', 'value'} | set(sortie.produced_fields))

    def test_une_agregation_REPART_des_seuls_champs_produits(self):
        # `calc_per_segment` est `aggregate` : la clé temporelle change, les lignes ne sont
        # plus les mêmes — une colonne d'amont n'aurait plus de sens en face.
        sortie = fc.get('calc_per_segment').outputs[0]
        self.assertEqual(champs_apres(sortie, 'calc_per_segment', {'time', 'value'}),
                         set(sortie.produced_fields))

    def test_les_champs_CANONIQUES_du_type_sont_la_par_definition(self):
        """Un `geo_track` PORTE `time/lat/lon` — c'est ce que le type veut dire. Une fonction
        qui en rend un ne « produit » donc pas `time`, elle le transmet.

        ⚠ Mesuré le 2026-09-09 : ce seul manque expliquait **29** des 81 refus du contrôle de
        champs — `gps_map_match → generate_sections` refusé faute de `time` alors que les deux
        ports sont des `geo_track`. Ce n'étaient pas 29 déclarations à corriger, c'était UNE
        règle absente.
        """
        sortie = fc.get('gps_map_match').outputs[0]          # geo_track, produit section_id…
        entree = fc.get('generate_sections').inputs[0]       # geo_track, exige time + section_id
        self.assertNotIn('time', sortie.produced_fields,
                         "prémisse du test : l'amont ne DÉCLARE pas produire `time`")
        ok, raison = can_connect(sortie, entree, available_fields=set())
        self.assertTrue(ok, f"le type garantit `time` : {raison}")

    def test_c_est_l_ACCUMULATION_qui_debloque_un_champ_NON_canonique(self):
        """L'accumulation reste nécessaire là où la règle canonique ne peut rien : un champ
        PROPRE à une fonction, qui traverse un enrichisseur en aval.

        Chaîne : `gps_map_match` produit `section_id` (non canonique) → `ego_track_filter`
        l'enrichit SANS le produire → `generate_sections` l'exige. À un seul saut, le port de
        `ego_track_filter` ne montre que ses propres colonnes : la connexion est refusée alors
        qu'elle est valide.

        ⚠ Ce test remplace une version qui prenait `calc_rolling → calc_per_segment` : la règle
        canonique la SUBSUME désormais (`time` est canonique de `timeseries`), donc elle ne
        discriminait plus rien. *Un test qui cesse de discriminer est un test à remplacer, pas
        un test à assouplir.*
        """
        amont, milieu = fc.get('gps_map_match'), fc.get('ego_track_filter')
        aval = fc.get('generate_sections')
        self.assertEqual(milieu.category, fc.FunctionCategory.ENRICHER,
                         "prémisse : le maillon du milieu doit LAISSER PASSER")
        self.assertNotIn('section_id', milieu.outputs[0].produced_fields)

        un_saut, _ = can_connect(milieu.outputs[0], aval.inputs[0],
                                 available_fields=milieu.outputs[0].produced_fields)
        apres = champs_apres(milieu.outputs[0], 'ego_track_filter',
                             champs_apres(amont.outputs[0], 'gps_map_match', set()))
        accumule, raison = can_connect(milieu.outputs[0], aval.inputs[0], available_fields=apres)
        self.assertFalse(un_saut, "un seul saut devrait échouer — c'est le défaut à éviter")
        self.assertTrue(accumule, f"l'accumulation doit récupérer la connexion : {raison}")


class DiagnosticDeChainageTest(SimpleTestCase):
    """Le parcours de graphe — et surtout ce sur quoi il doit S'ABSTENIR."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fc.load_all()
        cls.pures = [k for k, s in fc.FUNCTION_CATALOG.items()
                     if s.binding == fc.Binding.PURE and s.inputs and s.outputs]
        cls.app_bound = [k for k, s in fc.FUNCTION_CATALOG.items()
                         if s.binding != fc.Binding.PURE]

    def test_un_aval_app_bound_fait_S_ABSTENIR_jamais_refuser(self):
        """⚠ LE FAUX POSITIF QUI A COÛTÉ LA PREMIÈRE VERSION. L'exécuteur lance un nœud
        app-bound avec ses `params` seuls — le lien est de l'ORDRE."""
        self.assertTrue(self.app_bound, "aucune fonction app-bound : test vide, donc muet")
        amont, aval = self.pures[0], self.app_bound[0]
        g = {'nodes': [_noeud('a', amont), _noeud('b', aval)], 'links': [_lien('a', 'b')]}
        verdicts = {c['verdict'] for c in diagnostiquer_chainage(g)}
        self.assertEqual(verdicts, {'abstention'},
                         "un lien vers un nœud app-bound ne se contrôle pas comme un flux")

    def test_un_amont_SANS_ports_declares_fait_s_abstenir(self):
        """INCONNU ≠ VIDE : un nœud source/app n'a pas de `PortSpec`. Le refuser reviendrait
        à traiter « je ne sais pas » comme « il n'y a rien »."""
        aval = self.pures[0]
        g = {'nodes': [{'id': 'src', 'kind': 'app', 'app': 'studio_text'}, _noeud('b', aval)],
             'links': [_lien('src', 'b')]}
        constats = diagnostiquer_chainage(g)
        self.assertTrue(constats)
        self.assertTrue(all(c['verdict'] == 'abstention' for c in constats),
                        f"attendu des abstentions, obtenu {[c['verdict'] for c in constats]}")

    def test_LE_PIPELINE_REEL_DU_CORPUS_ne_produit_AUCUN_refus(self):
        """La garde de non-régression qui compte : `cam_analyzer` TOURNE. Le jour où le
        diagnostic le refuse, c'est le diagnostic qui a tort — ou une déclaration qui a
        changé sans que personne le voie.

        ⚠ Anti-vacuité : on exige que le pipeline existe et porte des liens, sinon un corpus
        vide ferait passer ce test en silence.
        """
        f = Path(settings.BASE_DIR) / 'manifests' / 'pipelines' / 'cam_analyzer.json'
        if not f.exists():                       # corpus absent : on le DIT, on ne passe pas
            self.skipTest(f"pipeline de référence absent ({f.name}) — mesure impossible")
        body = json.loads(f.read_text(encoding='utf-8')).get('body') or {}
        graphe = {'nodes': body.get('nodes') or [], 'links': body.get('links') or []}
        self.assertGreater(len(graphe['links']), 5, "pipeline sans liens : test muet")
        refus = [c for c in diagnostiquer_chainage(graphe) if c['verdict'] == 'refus']
        self.assertEqual(refus, [], f"le pipeline réel serait refusé : {refus[:3]}")

    def test_le_diagnostic_ne_BLOQUE_rien_il_rapporte(self):
        """`launch_graph` ne l'appelle pas encore : la passe de MESURE précède la mise en
        application. Ce test tient cette frontière — le jour où on active, il tombe, et
        c'est le rappel d'aller trier les refus mesurés (150 paires sur 261 au 09/09)."""
        import inspect
        from wama.studio.services import launch
        self.assertNotIn('diagnostiquer_chainage', inspect.getsource(launch.launch_graph),
                         "le diagnostic est passé en application : trier les refus d'abord")
