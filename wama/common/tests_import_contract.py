"""Le CONTRAT dont dépend la brique d'import commune, tenu app par app (2026-09-07).

Sept apps en place sont câblées sur `WamaImport` (`wama-import.js`). La brique ne connaît pas
les apps : elle POSTE un fichier sous un nom de champ, lit un identifiant dans la réponse, et
c'est TOUT ce qui décide si l'utilisateur voit sa card. Ce contrat vivait jusqu'ici dans le seul
JS de chaque app — et dans les scénarios nocturnes, qui exigent un serveur et un navigateur.

Ces tests le tiennent SANS navigateur, du côté serveur, exactement comme la brique le voit :
  1. la vue d'upload accepte un multipart avec le champ que la brique envoie (`file`, ou
     `files` en mode `multiple`), et répond une forme dont la brique sait extraire un id —
     le lecteur ci-dessous est la transcription Python de `identifiants()` de la brique ;
  2. l'app est bien SUR la brique (critère de grille `import_front` vert sur l'arbre réel),
     et son gabarit charge `wama-import.js` AVANT le script qui l'instancie.

Le (2) est une garde de DÉCONSTRUCTION : une session qui réécrirait une boucle `uploadFile`
dans une app portée, ou qui déplacerait la balise, sortirait ici en rouge — pas seulement au
prochain passage nocturne.

⚠ Pourquoi un utilisateur AVEC rôle : `AppAccessMiddleware` redirige (302) tout compte sans le
rôle de l'app vers l'accueil, AVANT la vue. Un test de vue franchit le portier, il ne le
contourne pas (leçon des tests du synthesizer, 25/08). Les rôles sont ceux de
`DEFAULT_APP_ACCESS` — s'ils changent, ces tests le disent.

⚠ Les témoins sont VALIDES (WAV PCM, PNG 1×1 — helpers de `ui_smoke`) : un faux fichier
mesure son propre témoin, pas l'app (leçon du 28/08).
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.services.ui_smoke import _png_1x1, _wav_silence

User = get_user_model()

#: Les 7 apps portées : rôles requis, champ POSTÉ par la brique, témoin, champs supplémentaires
#: que l'app exige (le converter refuse un dépôt sans format de sortie — c'est son `beforeFile`).
PORTEES = [
    # app           rôles               champ     ext     contenu                   POST
    ('transcriber', ['recherche'],      'file',   '.wav', lambda: _wav_silence(),   {}),
    ('converter',   [],                 'file',   '.png', _png_1x1,                 {'output_format': 'png'}),
    ('describer',   ['recherche'],      'file',   '.png', _png_1x1,                 {}),
    ('synthesizer', ['communication'],  'file',   '.txt', lambda: b'temoin WAMA\n', {}),
    ('enhancer',    ['communication'],  'file',   '.png', _png_1x1,                 {}),
    ('reader',      ['recherche'],      'files',  '.png', _png_1x1,                 {}),
    ('anonymizer',  ['communication'],  'file',   '.png', _png_1x1,                 {}),
]

# Rejouer UNE app (diagnostic) : CONTRAT_APPS=anonymizer manage.py test wama.common.tests_import_contract
import os as _os
if _os.environ.get('CONTRAT_APPS'):
    _voulues = {a.strip() for a in _os.environ['CONTRAT_APPS'].split(',')}
    PORTEES = [p for p in PORTEES if p[0] in _voulues]


def identifiants(data):
    """Transcription Python de `identifiants()` (wama-import.js) — les formes que la brique lit.

    Scalaire `id` / `job_id` / `pk` ; objet unique `media` ; listes `ids` / `created` / `added` /
    `items` d'objets à id ou de scalaires. Modifier l'un sans l'autre = contrat qui ment.
    """
    def _un(d):
        if not isinstance(d, dict):
            return None
        for k in ('job_id', 'id', 'pk'):
            v = d.get(k)
            if v not in (None, ''):
                return v
        return None
    if not isinstance(data, dict):
        return []
    un = _un(data)
    if un is not None:
        return [un]
    media = data.get('media')
    if isinstance(media, dict) and _un(media) is not None:
        return [_un(media)]
    liste = data.get('ids') or data.get('created') or data.get('added') or data.get('items')
    if not isinstance(liste, list):
        return []
    out = []
    for x in liste:
        v = _un(x) if isinstance(x, dict) else x
        if v not in (None, ''):
            out.append(v)
    return out


class ContratUploadDesAppsPorteesTest(TestCase):
    """(1) — la vue d'upload répond ce que la brique sait lire.

    ⚠ `TestCase` (transaction englobante) À DESSEIN : c'est ce qui a révélé, le 2026-09-07, que
    le `post_save` de `anonymizer.Media` fermait la connexion en plein cycle de requête
    (« the connection is closed ») en réinitialisant les réglages de TOUS les utilisateurs —
    corrigé dans `anonymizer/signals.py`, tenu par `anonymizer/tests.py`. Une vue d'upload qui
    ne survit pas à une transaction englobante a un effet de bord à trouver, pas à contourner.
    """

    def _utilisateur(self, app, roles):
        from wama.accounts.permissions import GROUP_PREFIX
        user = User.objects.create_user(username=f'import_contract_{app}', password='x')
        for role in roles:
            group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
            user.groups.add(group)
        return user

    def test_chaque_app_portee_accepte_le_depot_de_la_brique_et_repond_un_id(self):
        for app, roles, champ, ext, contenu, extra in PORTEES:
            with self.subTest(app=app):
                self.client.force_login(self._utilisateur(app, roles))
                temoin = SimpleUploadedFile(f'wama_temoin_contrat{ext}', contenu(),
                                            content_type='application/octet-stream')
                rep = self.client.post(reverse(f'{app}:upload'), {champ: temoin, **extra})
                self.assertEqual(200, rep.status_code,
                                 f'{app}:upload → {rep.status_code} {rep.content[:200]!r}')
                data = rep.json()
                self.assertFalse(data.get('error'), f'{app} : {data.get("error")}')
                ids = identifiants(data)
                self.assertTrue(ids, f'{app} : aucun identifiant lisible par la brique dans {data!r}'[:400])

    def test_un_depot_sans_fichier_est_refuse_et_non_pas_avale(self):
        """La brique affiche `data.error` ou `statusText` : la vue doit DIRE le refus, pas 200 vide."""
        for app, roles, champ, _ext, _contenu, extra in PORTEES:
            with self.subTest(app=app):
                self.client.force_login(self._utilisateur(app, roles))
                rep = self.client.post(reverse(f'{app}:upload'), dict(extra))
                self.assertGreaterEqual(rep.status_code, 400, f'{app} : un dépôt vide a été accepté')


class AdoptionDeLaBriqueTest(SimpleTestCase):
    """(2) — l'app EST sur la brique, et son gabarit la charge avant de l'instancier."""

    RACINE = Path(__file__).resolve().parents[1]

    def test_le_critere_import_front_est_vert_pour_chaque_app_portee(self):
        from wama.common.services import conformity_checker as cc
        for app, *_ in PORTEES:
            with self.subTest(app=app):
                etat, preuve = cc._import_front(cc._AppFiles(app))
                self.assertIs(etat, True, f'{app} : {preuve}')

    def test_wama_import_js_est_charge_avant_le_script_qui_l_instancie(self):
        for app, *_ in PORTEES:
            with self.subTest(app=app):
                gabarit = self.RACINE / app / 'templates' / app / 'index.html'
                texte = gabarit.read_text(encoding='utf-8')
                pos_brique = texte.find('wama-import.js')
                self.assertGreater(pos_brique, -1, f'{app} : wama-import.js absent du gabarit')
                # Tout script d'app qui instancie WamaImport doit venir APRÈS la brique.
                for m in re.finditer(rf"static_v\s+'{app}/js/([\w.-]+\.js)'", texte):
                    js = self.RACINE / app / 'static' / app / 'js' / m.group(1)
                    if js.exists() and 'WamaImport(' in js.read_text(encoding='utf-8'):
                        self.assertLess(pos_brique, m.start(),
                                        f'{app} : {m.group(1)} instancie WamaImport avant son chargement')
