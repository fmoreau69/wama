# -*- coding: utf-8 -*-
"""Backend Table Transformer (B2, 02/09) — le contrat, la logique pure, et l'intégration
RÉELLE sur les poids installés (sautée proprement si poids ou runtime absents)."""
import unittest

from django.test import TestCase


class ContratTest(TestCase):

    def test_le_backend_honore_le_contrat_commun(self):
        from wama.common.backends.base import BaseModelBackend
        from wama.reader.backends.table_transformer_backend import TableTransformerBackend
        self.assertTrue(issubclass(TableTransformerBackend, BaseModelBackend))
        b = TableTransformerBackend()
        self.assertFalse(b.is_loaded)
        self.assertTrue(TableTransformerBackend.description)
        self.assertIsNotNone(TableTransformerBackend.recommended_vram_gb)

    def test_ce_n_est_pas_un_moteur_du_select(self):
        # La doctrine du module : ENRICHISSEUR, jamais moteur OCR — le select Backend du
        # reader ne doit PAS le proposer (il ne lit pas le texte).
        from wama.reader.models import ReadingItem
        self.assertNotIn('table-transformer',
                         [c[0] for c in ReadingItem.Backend.choices])


class GrilleVersMarkdownTest(TestCase):
    """La logique PURE (aucun modèle) : grille + mots → Markdown."""

    LIGNES = [[0, 0, 200, 20], [0, 20, 200, 40]]          # 2 rangées
    COLONNES = [[0, 0, 100, 40], [100, 0, 200, 40]]       # 2 colonnes

    def test_les_mots_tombent_dans_leur_cellule_par_leur_centre(self):
        from wama.reader.backends.table_transformer_backend import rows_cols_to_markdown
        mots = [
            {'text': 'Nom',  'bbox': [10, 5, 40, 15]},     # r0 c0
            {'text': 'Prix', 'bbox': [110, 5, 150, 15]},   # r0 c1
            {'text': 'Pomme', 'bbox': [10, 25, 60, 35]},   # r1 c0
            {'text': '2€',   'bbox': [110, 25, 130, 35]},  # r1 c1
        ]
        md = rows_cols_to_markdown(self.LIGNES, self.COLONNES, mots)
        self.assertIn('| Nom | Prix |', md)
        self.assertIn('| Pomme | 2€ |', md)
        self.assertIn('| --- | --- |', md, 'ligne de séparation Markdown attendue')

    def test_deux_mots_d_une_cellule_se_concatenent_dans_l_ordre_de_lecture(self):
        from wama.reader.backends.table_transformer_backend import rows_cols_to_markdown
        mots = [
            {'text': 'unitaire', 'bbox': [40, 5, 90, 15]},
            {'text': 'Prix',     'bbox': [5, 5, 35, 15]},   # plus à gauche → premier
        ]
        md = rows_cols_to_markdown(self.LIGNES, self.COLONNES, mots)
        self.assertIn('| Prix unitaire |', md)

    def test_sans_grille_le_rendu_est_vide_pas_une_erreur(self):
        from wama.reader.backends.table_transformer_backend import rows_cols_to_markdown
        self.assertEqual(rows_cols_to_markdown([], [], []), '')


def _poids_presents():
    import os
    if os.name == 'nt':
        # ⚠ Mesuré le 02/09 : le cache HF de ces poids a été créé sous WSL — ses SYMLINKS
        # sont illisibles depuis Windows (OSError « Can't load image processor » alors que
        # les fichiers existent). L'exécution réelle vit côté worker WSL2 ; la suite
        # venv_win saute ce test AVEC sa raison au lieu d'un rouge de plateforme.
        return False
    try:
        from wama.reader.backends.table_transformer_backend import (
            HF_DETECTION, HF_STRUCTURE, TableTransformerBackend, _cache_dir_for)
        return (TableTransformerBackend.is_available()
                and _cache_dir_for(HF_DETECTION) and _cache_dir_for(HF_STRUCTURE))
    except Exception:
        return False


class IntegrationReelleTest(TestCase):
    """CHARGE les poids installés (CPU, ~110M ×2) et détecte un tableau dessiné.

    Sauté proprement si runtime ou poids absents — un test d'intégration qui casserait sur
    un poste sans les poids serait un rouge permanent, pas une mesure."""

    @unittest.skipUnless(_poids_presents(), 'runtime transformers/torch ou poids absents')
    def test_une_page_realiste_est_detectee_et_rendue_en_markdown(self):
        # ⚠ FIXTURE RÉALISTE obligatoire (mesuré le 02/09) : un DETR entraîné sur de VRAIS
        # documents (PubTables) ne voit PAS une grille de traits nus sur fond blanc — la
        # première fixture (lignes seules) rendait 0 détection ; celle-ci (marges, titre,
        # paragraphe, tableau DENSE avec texte par cellule) rend un score de 0,999.
        import tempfile
        from PIL import Image, ImageDraw
        from wama.reader.backends.table_transformer_backend import TableTransformerBackend

        page = Image.new('RGB', (816, 1056), 'white')       # ~A4 à 96 dpi
        d = ImageDraw.Draw(page)
        d.text((72, 60), 'Rapport des ventes — septembre 2026', fill='black')
        for k in range(4):
            d.text((72, 100 + k * 16),
                   'Lorem ipsum dolor sit amet consectetur adipiscing elit sed do.',
                   fill='black')
        x0, y0, x1, y1 = 72, 220, 744, 520
        rangs = [y0 + i * 60 for i in range(6)]
        cols = [x0, 280, 480, x1]
        for y in rangs + [y1]:
            d.line([(x0, y), (x1, y)], fill='black', width=2)
        for x in cols:
            d.line([(x, y0), (x, y1)], fill='black', width=2)
        contenu = [('Produit', 'Quantité', 'Prix'), ('Pommes', '120', '2,40 €'),
                   ('Poires', '85', '3,10 €'), ('Cerises', '40', '6,80 €'),
                   ('Prunes', '95', '2,90 €')]
        mots = []
        for i, ligne in enumerate(contenu):
            for j, txt in enumerate(ligne):
                px, py = cols[j] + 12, rangs[i] + 22
                d.text((px, py), txt, fill='black')
                mots.append({'text': txt, 'bbox': [px, py, px + 8 * len(txt), py + 14]})
        d.text((72, 560), 'Conclusion : les volumes progressent de 12 %.', fill='black')

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            page.save(f.name)
            chemin = f.name

        b = TableTransformerBackend()
        try:
            tables = b.extract_tables(chemin, words=mots, seuil=0.5)
        finally:
            b.unload()
            import os
            os.unlink(chemin)

        self.assertGreaterEqual(len(tables), 1, 'aucun tableau détecté sur la page réaliste')
        t = tables[0]
        self.assertEqual(t['n_cols'], 3, 'les 3 colonnes dessinées doivent être vues')
        self.assertGreaterEqual(t['n_rows'], 2)
        self.assertIn('Produit', t['markdown'])
        self.assertIn('|', t['markdown'])
