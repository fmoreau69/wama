"""Le GRAPHE porteur de valeurs : ce que reçoit un nœud du Studio (ROUTE §10.6 3.3bis règle 5).

Mesuré le 2026-10-18 : le nœud Converter montrait 1 réglage sur 19 (sa nature d'entrée, que la card
reçoit au dépôt, ne lui arrivait jamais), le nœud Avatarizer ne montrait jamais la voix — et refusait
le lancement dès qu'on lui branchait un texte —, les étapes « résumer » / « locuteurs » cachaient
leurs réglages pour toujours (leur interrupteur absent). Les schémas étaient justes ; il manquait un
PORTEUR. Ces tests le tiennent sans nommer d'autre app que celles qui l'illustrent.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.utils.param_schema import _show_if_met


def _graph(nodes, links=()):
    return {'nodes': [dict(n, x=0, y=0) for n in nodes],
            'links': [{'from': a, 'to': b, 'to_port': port} for a, b, port in links]}


def _visible(schema, values):
    return {p['name'] for p in schema if p.get('type') != 'hidden'
            and _show_if_met(p.get('show_if'), values)}


class WhatANodeReceivesTest(TestCase):

    def test_a_chosen_media_gives_its_nature_to_the_converter(self):
        from wama.studio.services.graph_flow import node_context
        ctx = node_context(_graph(
            [{'id': 'n1', 'app': 'media_import', 'params': {'asset_path': 'users/1/a/photo.png'}},
             {'id': 'n2', 'app': 'converter', 'params': {}}],
            [('n1', 'n2', 'work')]), 'n2')
        self.assertEqual('image', ctx['values']['media_type'])
        self.assertEqual({'node': 'n1'}, ctx['provided']['media_type'])
        self.assertEqual(['image'], ctx['inputs']['work']['types'])

    def test_an_unknown_nature_is_every_nature_the_port_accepts_never_none(self):
        """« Inconnu n'est pas vide » : aucun média choisi, ou aucun lien — le nœud montre les
        réglages de CHAQUE nature possible (le converter : bien plus que son seul format)."""
        from wama.converter.params import PARAMS_JSON
        from wama.studio.services.graph_flow import node_context
        unchosen = node_context(_graph(
            [{'id': 'n1', 'app': 'media_import', 'params': {}},
             {'id': 'n2', 'app': 'converter', 'params': {}}], [('n1', 'n2', 'work')]), 'n2')
        alone = node_context(_graph([{'id': 'n2', 'app': 'converter', 'params': {}}]), 'n2')
        for ctx in (unchosen, alone):
            natures = ctx['values']['media_type']
            self.assertIsInstance(natures, list)
            self.assertIn('image', natures)
            self.assertIn('video', natures)
            self.assertGreater(len(_visible(PARAMS_JSON, ctx['values'])), 15)
        self.assertNotIn('media_type', alone['provided'], 'rien n’est branché : rien n’est fourni')
        # Contre-épreuve : connue, la nature borne ce qui se montre.
        image = _visible(PARAMS_JSON, {'media_type': 'image'})
        self.assertLess(len(image), len(_visible(PARAMS_JSON, unchosen['values'])))

    def test_an_unknown_nature_stays_within_what_the_node_accepts(self):
        """Les natures possibles sont celles que le NŒUD accepte (`input_kinds` du runner), pas
        tout ce que le port de l'app accepte : le nœud enhancer est image + vidéo (`io_scope`),
        son port admet aussi l'audio."""
        from wama.studio.services.generic_runner import GENERIC_APPS
        from wama.studio.services.graph_flow import node_context
        ctx = node_context(_graph([{'id': 'e', 'app': 'enhancer', 'params': {}}]), 'e')
        self.assertEqual(list(GENERIC_APPS['enhancer']['input_kinds']), ctx['values']['media_type'])
        self.assertNotIn('audio', ctx['values']['media_type'])

    def test_a_text_node_gives_the_avatar_its_text_and_so_its_voice(self):
        from wama.avatarizer.params import PARAMS_JSON
        from wama.studio.services.graph_flow import node_context
        ctx = node_context(_graph(
            [{'id': 't', 'app': 'text_input', 'params': {'text': 'Bonjour'}},
             {'id': 'a', 'app': 'avatarizer', 'params': {}}], [('t', 'a', 'prompt')]), 'a')
        self.assertEqual('Bonjour', ctx['values']['text_content'])
        self.assertEqual({'node': 't', 'at_run': False}, ctx['provided']['text_content'])
        self.assertIn('voice_preset', _visible(PARAMS_JSON, ctx['values']))
        self.assertNotIn('voice_preset', _visible(PARAMS_JSON, {}), 'contre-épreuve : sans texte')

    def test_the_link_diagnosis_reads_the_same_traversal(self):
        """Un parcours, pas deux : les champs du diagnostic SONT ceux du parcours commun."""
        import inspect
        from wama.studio.services import launch
        source = inspect.getsource(launch.diagnostiquer_chainage)
        self.assertIn('node_flows(graph)', source)
        self.assertNotIn('champs_apres(', source, 'le diagnostic recalcule ses champs à part')

    def test_the_endpoint_says_what_a_node_receives(self):
        import json
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        user = User.objects.create_user('flow_api', password='x')
        # Un compte qui FRANCHIT le portier du Studio (ses rôles déclarés), jamais un superuser.
        for role in (DEFAULT_APP_ACCESS.get('studio') or {}).get('roles', []):
            user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(user)
        graph = _graph([{'id': 'n1', 'app': 'media_import', 'params': {'asset_path': 'a/clip.mp4'}},
                        {'id': 'n2', 'app': 'converter', 'params': {}}], [('n1', 'n2', 'work')])
        r = self.client.post('/studio/api/node-context/', json.dumps({'graph': graph, 'node': 'n2'}),
                             content_type='application/json')
        self.assertEqual(200, r.status_code, r.content)
        self.assertEqual('video', r.json()['values']['media_type'])


class AStepNodeIsCarriedByItsElementTest(TestCase):

    def test_the_step_shows_its_card_gear_switch_included_with_the_element_values(self):
        """La ⚙ de l'étape, comme sur la card : l'interrupteur qui commande le type de résumé est
        MONTRÉ ; il prend la valeur ACTUELLE de l'élément (sous ce que le nœud décide)."""
        from wama.studio.services.graph_flow import node_context
        from wama.studio.services.node_params import node_schema
        from wama.transcriber.models import Transcript
        params = node_schema('function:transcriber.summarize')['params']
        self.assertEqual('toggle', next(p for p in params if p['name'] == 'generate_summary')['type'])
        owner = User.objects.create_user('flow_summary', password='x')
        item = Transcript.objects.create(user=owner, status='SUCCESS', generate_summary=True)
        ctx = node_context(_graph([{'id': 's', 'app': 'function:transcriber.summarize',
                                    'params': {'transcript_id': str(item.pk)}}]), 's', owner)
        self.assertIs(True, ctx['defaults']['generate_summary'])
        self.assertNotIn('generate_summary', ctx['provided'], 'décidable au nœud, pas fourni')
        values = {p['name']: p.get('default') for p in params}
        values.update(ctx['defaults'])
        self.assertIn('summary_type', _visible(params, values))

    def test_the_element_designated_carries_its_nature(self):
        from wama.converter.models import ConversionJob
        from wama.converter.params import PARAMS_JSON
        from wama.studio.services.graph_flow import node_context
        from wama.studio.services.node_params import node_schema
        owner = User.objects.create_user('flow_step', password='x')
        other = User.objects.create_user('flow_other', password='x')
        job = ConversionJob.objects.create(user=owner, input_filename='a.mp4', media_type='video',
                                           output_format='mp4', status='SUCCESS')
        schema = node_schema('function:converter.convert')['params']
        self.assertIn('media_type', {p['name'] for p in schema if p['type'] == 'hidden'})
        graph = _graph([{'id': 's', 'app': 'function:converter.convert',
                         'params': {'job_id': str(job.pk)}}])
        ctx = node_context(graph, 's', owner)
        self.assertEqual('video', ctx['values']['media_type'])
        self.assertEqual({'element': job.pk}, ctx['provided']['media_type'])
        self.assertIn('fps', _visible(PARAMS_JSON, ctx['values']))
        # Contre-épreuve : l'élément d'un autre ne se lit pas — sa nature reste INCONNUE (toutes
        # celles que l'app accepte), jamais celle de l'élément d'autrui.
        theirs = node_context(graph, 's', other)
        self.assertIsInstance(theirs['values']['media_type'], list)
        self.assertNotIn('media_type', theirs['provided'])
        unset = node_context(_graph([{'id': 's', 'app': 'function:converter.convert',
                                      'params': {}}]), 's', owner)
        self.assertGreater(len(_visible(PARAMS_JSON, unset['values'])), 15)


class TheAvatarSpeaksFromTheStudioTest(TestCase):

    def test_the_text_port_arrives_in_the_declared_source_text(self):
        from wama.studio.services.generic_runner import port_argument_name, unwired_ports
        self.assertEqual('text_content', port_argument_name('avatarizer', 'prompt'))
        self.assertNotIn('prompt', unwired_ports('avatarizer'))

    def test_a_text_alone_runs_the_avatar_without_audio(self):
        """L'app accepte l'audio OU le texte (son mode se dérive des entrées) ; le nœud exigeait
        l'audio et refusait tout lien texte (« débranchez-le »)."""
        from wama.studio.services.generic_runner import build_generic_runner
        create = build_generic_runner('avatarizer')['create']
        with mock.patch('wama.tool_api.execute_tool', return_value={'item_id': 7}) as tool:
            self.assertEqual(7, create(User(id=1), {'prompt': 'Bonjour'},
                                       {'avatar_gallery_name': 'x'}))
        name, args, _user = tool.call_args[0]
        self.assertEqual('add_to_avatarizer', name)
        self.assertEqual('Bonjour', args['text_content'])
        self.assertNotIn('audio_path', args)


class TheOutputNodeFilesByWhatItReceivesTest(TestCase):

    def test_automatic_takes_the_category_of_the_file(self):
        from wama.studio.services.builtin_nodes import _asset_type_for
        self.assertEqual('image', _asset_type_for({}, 'out.png'))
        self.assertEqual('video', _asset_type_for({'asset_type': ''}, 'out.mp4'))
        self.assertEqual('audio_music', _asset_type_for({}, 'out.mp3'))

    def test_a_usage_of_another_category_is_refused_never_filed_wrong(self):
        """Le défaut fixe `video` rangeait une image comme une vidéo."""
        from wama.studio.services.builtin_nodes import _asset_type_for
        with self.assertRaises(ValueError):
            _asset_type_for({'asset_type': 'video'}, 'out.png')
        self.assertEqual('avatar', _asset_type_for({'asset_type': 'avatar'}, 'face.png'))
