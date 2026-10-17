"""`REMOVAL_LEDGER` : un numéro, une ligne (2026-10-17).

La règle ① de son en-tête (« identifiant jamais réutilisé ») a été écrite le 2026-08-27 après
quatre collisions — et quatre autres sont arrivées ensuite (R43, R64, R65, R66), relevées dès le
2026-09-13 et citées dans cinq blocs de suivi sans être soldées. Elles sont renumérotées le
2026-10-17 (R137-R140) ; ce test empêche la suivante.
"""
import re
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

LEDGER = Path(__file__).resolve().parents[3] / 'docs' / 'construction' / 'suivi' / 'REMOVAL_LEDGER.md'
ROW = re.compile(r'^\|\s*(R\d+[a-z]?)\s*\|', re.M)


def duplicated_ids(text: str) -> dict:
    return {rid: n for rid, n in Counter(ROW.findall(text)).items() if n > 1}


class RemovalLedgerTest(SimpleTestCase):

    def test_every_ledger_id_names_one_row_only(self):
        text = LEDGER.read_text(encoding='utf-8')
        self.assertGreater(len(ROW.findall(text)), 100, 'presque aucune ligne lue : garde affaiblie')
        self.assertEqual({}, duplicated_ids(text),
                         'numéro réutilisé : prendre le plus grand existant + 1 (en-tête du registre)')

    def test_the_detector_sees_a_reused_id(self):
        self.assertEqual({'R7': 2}, duplicated_ids('| R7 | a | b |\n| R8 | c |\n| R7 | d |\n'))
        self.assertEqual({}, duplicated_ids('| R7 | cite R7 dans le texte |\n'))
