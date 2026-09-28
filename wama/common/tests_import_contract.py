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

#: Ce que la brique d'import POSTE différemment pour une app — DÉCLARÉ, car rien d'autre ne le
#: dit : le reader dépose en `multiple` (champ `files`), le converter refuse un dépôt sans
#: format de sortie (c'est son `beforeFile`).
UPLOAD_QUIRKS = {
    'reader': {'field': 'files'},
    'converter': {'post': {'output_format': 'png'}},
}

#: Un témoin VALIDE par NATURE d'entrée (`input_types` du catalogue). La nature d'abord, pas
#: l'extension : l'enhancer déclare l'audio au niveau de l'app, mais son `upload` ne prend que
#: l'image et la vidéo (l'audio a sa route) — sa PREMIÈRE nature déclarée est la bonne.
_WITNESSES = {'image': ('.png', _png_1x1), 'audio': ('.wav', lambda: _wav_silence()),
              'document': ('.txt', lambda: b'temoin WAMA\n'),
              'prompt': ('.txt', lambda: b'temoin WAMA\n')}


def _portees():
    """(app, rôles, champ, ext, contenu, POST) de chaque app dont le dépôt CRÉE un élément par la
    brique — DÉRIVÉ (2026-09-26 ; la liste était écrite à la main, 7 apps) : sur la brique
    (critère de grille `import_front`), hors mode ATTACHE (`depot_cree=False` : le dépôt joint
    le fichier à la card neuve, il ne crée rien), rôles lus dans la politique d'accès, témoin
    fabriqué pour la première NATURE déclarée (`input_types`) dont l'extension est acceptée."""
    from wama.accounts.permissions import DEFAULT_APP_ACCESS
    from wama.common.app_registry import APP_CATALOG
    from wama.common.services import conformity_checker as cc
    out = []
    for app, spec in APP_CATALOG.items():
        if (spec or {}).get('sandbox'):
            continue
        files = cc._AppFiles(app)
        if cc._import_front(files)[0] is not True:
            continue
        if files.find(cc.TEMPLATES, r'depot_cree\s*=\s*False'):
            continue
        declared = {e.lower() for e in spec.get('input_extensions', ())}
        witness = next((_WITNESSES[n] for n in spec.get('input_types', ())
                        if n in _WITNESSES and _WITNESSES[n][0] in declared), None)
        if witness is None:
            continue
        quirks = UPLOAD_QUIRKS.get(app, {})
        roles = list((DEFAULT_APP_ACCESS.get(app) or {}).get('roles', []))
        out.append((app, roles, quirks.get('field', 'file'), witness[0], witness[1],
                    dict(quirks.get('post', {}))))
    return out


PORTEES = _portees()

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

    def test_a_deposit_keeps_the_panel_settings_it_posts(self):
        """Contract 3 (`WAMA_VERIFICATION §8`, 2026-09-26): the right panel's settings travel
        with the deposit and land on the new element — a panel setting chosen from the SCHEMA
        (a closed-list model field, posted with a value other than its default)."""
        from wama.common.tests_item_settings_contract import _choice_fields
        from wama.common.utils.param_schema import schema_for_app
        from wama.common.utils.preview_registry import PreviewRegistry
        measured = 0
        for app, roles, champ, ext, contenu, extra in PORTEES:
            model = PreviewRegistry.get_model(app)
            schema = [p for p in schema_for_app(app) if 'panel' in (p.get('contexts') or ())]
            fields = [(n, v) for n, v in _choice_fields(model, schema) if n not in extra]
            if not fields:
                continue
            with self.subTest(app=app):
                name, values = fields[0]
                default = model._meta.get_field(name).get_default()
                target = next(v for v in values if v != default)
                self.client.force_login(self._utilisateur(app, roles))
                temoin = SimpleUploadedFile(f'wama_temoin_contrat{ext}', contenu(),
                                            content_type='application/octet-stream')
                rep = self.client.post(reverse(f'{app}:upload'),
                                       {champ: temoin, name: target, **extra})
                self.assertEqual(200, rep.status_code, rep.content[:200])
                ids = identifiants(rep.json())
                self.assertTrue(ids)
                element = model.objects.get(pk=ids[0])
                self.assertEqual(target, getattr(element, name),
                                 f'{app} : `{name}` posté par le volet non gardé au dépôt')
                # Counterpart: a deposit that posts NOTHING of it gets the default, not the
                # previous deposit's value.
                temoin = SimpleUploadedFile(f'wama_temoin_nu{ext}', contenu(),
                                            content_type='application/octet-stream')
                self.client.force_login(self._utilisateur(f'{app}_bare', roles))
                rep = self.client.post(reverse(f'{app}:upload'), {champ: temoin, **extra})
                element = model.objects.get(pk=identifiants(rep.json())[0])
                self.assertEqual(default, getattr(element, name),
                                 f'{app} : dépôt sans réglage → `{name}` devrait valoir son défaut')
                measured += 1
        self.assertGreaterEqual(measured, 1, 'aucune app mesurée')

    def test_a_file_of_an_extension_the_app_does_not_accept_is_refused(self):
        """The deposit says no to a file the app cannot take (2026-09-26 — it was checked for
        the synthesizer alone)."""
        for app, roles, champ, _ext, _contenu, extra in PORTEES:
            with self.subTest(app=app):
                self.client.force_login(self._utilisateur(app, roles))
                temoin = SimpleUploadedFile('wama_temoin_contrat.xyz', b'not a media',
                                            content_type='application/octet-stream')
                rep = self.client.post(reverse(f'{app}:upload'), {champ: temoin, **extra})
                self.assertGreaterEqual(rep.status_code, 400,
                                        f'{app} : un .xyz a été accepté ({rep.content[:150]!r})')

    def test_un_depot_sans_fichier_est_refuse_et_non_pas_avale(self):
        """La brique affiche `data.error` ou `statusText` : la vue doit DIRE le refus, pas 200 vide."""
        for app, roles, champ, _ext, _contenu, extra in PORTEES:
            with self.subTest(app=app):
                self.client.force_login(self._utilisateur(app, roles))
                rep = self.client.post(reverse(f'{app}:upload'), dict(extra))
                self.assertGreaterEqual(rep.status_code, 400, f'{app} : un dépôt vide a été accepté')


class UploadViewsReceiveDesignationsTest(TestCase):
    """Un fichier DÉSIGNÉ (tuile Médiathèque, glisser depuis l'arbre) arrive par la MÊME vue
    d'upload que le dépôt, avec les mêmes champs de volet, et l'élément créé POINTE le fichier —
    aucune copie (plan de la card v4, étape 1, 2026-09-28 ; brique `received_inputs`).

    Les 7 apps « crée » dérivées par `PORTEES` l'ont adoptée le même jour (transcriber d'abord,
    budget d'exemption descendu de 6 à 0 puis retiré). Une app ajoutée au parc entre ici seule."""

    _utilisateur = ContratUploadDesAppsPorteesTest._utilisateur

    def _designate(self, app, roles, champ, ext, contenu, extra):
        from django.conf import settings
        from wama.common.utils.file_references import direct_references
        from wama.common.utils.media_paths import DESIGNATION_FIELD
        user = self._utilisateur(app, roles)
        self.client.force_login(user)
        rel = f'users/{user.id}/temp/wama_temoin_designe_{app}{ext}'
        path = Path(settings.MEDIA_ROOT) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contenu())
        rep = self.client.post(reverse(f'{app}:upload'), {DESIGNATION_FIELD: rel, **extra})
        ok = rep.status_code == 200 and not (rep.json() if rep.headers.get('Content-Type', '')
                                            .startswith('application/json') else {}).get('error')
        pointed = ok and bool(identifiants(rep.json())) and bool(direct_references(rel))
        return rep, pointed

    def test_each_app_receives_a_designation_and_points_the_file(self):
        adopted = []
        for app, roles, champ, ext, contenu, extra in PORTEES:
            with self.subTest(app=app):
                rep, pointed = self._designate(app, roles, champ, ext, contenu, extra)
                self.assertTrue(pointed, f'{app}:upload → {rep.status_code} {rep.content[:200]!r}')
                adopted.append(app)
        self.assertTrue(adopted, 'aucune app ne reçoit de désignation : le contrat serait à vide')

    def test_a_designation_the_user_cannot_read_is_refused(self):
        from wama.common.utils.media_paths import DESIGNATION_FIELD
        for app, roles, champ, ext, contenu, extra in PORTEES:
            with self.subTest(app=app):
                self.client.force_login(self._utilisateur(app, roles))
                rep = self.client.post(reverse(f'{app}:upload'),
                                       {DESIGNATION_FIELD: '../../etc/passwd', **extra})
                self.assertGreaterEqual(rep.status_code, 400, rep.content[:200])


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
