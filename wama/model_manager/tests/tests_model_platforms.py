"""Les PLATEFORMES de modèles — déclarées au registre des sources (`external_sources.model_page`,
2026-10-22), lues par le lien de card, la validation du manifeste `model` et la candidature YOLO.

La table plateforme → adresse et les noms des plateformes vivaient en double dans `AIModel`
(`_URL_PAR_PLATEFORME`, `platform_label`), sous d'autres libellés que le registre (« HuggingFace »
contre « HuggingFace Hub »). Les adresses attendues ci-dessous sont celles que rendait l'ancienne
table, recopiées À LA LETTRE : le déplacement ne doit en changer aucune.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.common import external_sources
from wama.model_manager.models import AIModel

#: L'ancienne table (`models.py`, jusqu'au 2026-10-22), appliquée à un identifiant de chaque forme.
PAGES_BEFORE = {
    'huggingface:BAAI/bge-m3': 'https://huggingface.co/BAAI/bge-m3',
    'ollama:gemma4': 'https://ollama.com/library/gemma4',
    'roboflow:projet/3': 'https://universe.roboflow.com/projet/3',
    'github:ultralytics/assets': 'https://github.com/ultralytics/assets',
    'github:owner/repo/releases/tag/v1.0': 'https://github.com/owner/repo/releases/tag/v1.0',
}


class DeclaredPlatformsTest(SimpleTestCase):

    def test_the_platforms_are_the_registry_sources_with_a_model_page(self):
        self.assertEqual({'huggingface', 'ollama', 'roboflow', 'github'},
                         set(external_sources.model_platforms()))
        # `ollama:` names the SITE's page, not the local engine.
        self.assertEqual('ollama_site', external_sources.model_platforms()['ollama'].key)

    def test_every_page_address_is_the_one_the_old_table_gave(self):
        for ref, url in PAGES_BEFORE.items():
            with self.subTest(ref=ref):
                self.assertEqual(url, external_sources.model_page_url(ref))
                self.assertEqual(url, AIModel(platform_ref=ref).platform_url)

    def test_a_row_without_platform_ref_falls_back_on_what_it_already_carries(self):
        self.assertEqual('https://huggingface.co/org/m', AIModel(platform_ref='huggingface:org/m').platform_url)
        self.assertEqual('https://ollama.com/library/gemma4',
                         AIModel(model_key='ollama:gemma4:12b', name='gemma4:12b').platform_url)
        self.assertIsNone(AIModel(model_key='custom:x', name='x').platform_url)
        self.assertIsNone(external_sources.model_page_url('nowhere:x'))

    def test_the_platform_is_named_by_the_registry(self):
        for ref in PAGES_BEFORE:
            source = external_sources.model_platforms()[ref.partition(':')[0]]
            with self.subTest(ref=ref):
                self.assertEqual(source.label, AIModel(platform_ref=ref).platform_label)
        self.assertEqual(external_sources.get('huggingface').label,
                         AIModel(platform_ref='huggingface:org/m').platform_label)
        self.assertEqual('', AIModel(model_key='custom:x').platform_label)

    def test_the_model_manifest_accepts_the_declared_platforms_only(self):
        from wama.common.manifests.builtin.model import validate_model_body
        for ref in PAGES_BEFORE:
            with self.subTest(ref=ref):
                self.assertEqual([], validate_model_body({'identity': {'platform_ref': ref}}))
        errors = validate_model_body({'identity': {'platform_ref': 'nowhere:x'}})
        self.assertEqual(1, len(errors))
        self.assertIn('inconnue', errors[0])


class NoPageAddressByHandTest(SimpleTestCase):
    """L'adresse d'une fiche de modèle se lit au registre (`model_page_url`) : nul ne l'écrit en dur
    ailleurs. Trois recopies relevées à la revérification du 2026-10-22 (`sam3_manager` ×2, la
    prospection du Hub) — le motif cherché est un GABARIT, une f-string qui complète l'adresse
    d'une plateforme par un identifiant."""

    PATTERN = r"""f['"]https://(huggingface\.co|github\.com|ollama\.com/library|universe\.roboflow\.com)/\{"""

    def test_no_python_file_builds_a_platform_page_by_hand(self):
        import re
        from pathlib import Path

        from django.conf import settings

        from wama.common.sandbox import LABEL_RE
        pattern = re.compile(self.PATTERN)
        base = Path(settings.BASE_DIR)
        found = []
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in (base / root).rglob('*.py'):
                rel = path.relative_to(base).as_posix()
                # Une jumelle du bac à sable (`wama/<app>_NN/`, gitignorée) est une COPIE générée
                # de sa source, déjà balayée — même exclusion que `check_identifier_language`.
                if LABEL_RE.match(path.relative_to(base / root).parts[0]):
                    continue
                if ('/tests' in rel or '/migrations/' in rel or '/vendor/' in rel
                        or rel.endswith('common/external_sources.py')):
                    continue
                for n, line in enumerate(path.read_text(encoding='utf-8', errors='replace')
                                         .splitlines(), 1):
                    if pattern.search(line):
                        found.append(f'{rel}:{n}')
        self.assertEqual([], found)

    def test_the_pattern_sees_a_hand_written_page(self):
        import re
        self.assertTrue(re.search(self.PATTERN, "url = f'https://huggingface.co/{repo}'"))
        self.assertFalse(re.search(self.PATTERN, "model_page_url(f'huggingface:{repo}')"))


class YoloCandidatePlatformTest(TestCase):

    def test_a_yolo_candidate_carries_the_identity_its_installation_will_set(self):
        from wama.model_manager.services.model_installer import yolo_task_of
        from wama.model_manager.services.prospector import seed_yolo_candidate
        from wama.model_manager.services.provenance import identity_for_spec
        with mock.patch('wama.model_manager.services.model_installer.weight_for_spec',
                        lambda spec: 0.01):
            result = seed_yolo_candidate('yolov8n')
        self.assertTrue(result['ok'], result)
        row = AIModel.objects.get(model_key=result['model_key'])
        spec = {'kind': 'yolo', 'ref': 'yolov8n', 'task': yolo_task_of('yolov8n')}
        self.assertEqual(identity_for_spec(spec)['platform_ref'], row.platform_ref)
        self.assertEqual('https://github.com/ultralytics/assets', row.platform_url)
