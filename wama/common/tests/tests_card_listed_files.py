"""Retirer une card LIBÈRE aussi les fichiers de ses LISTES DE CHEMINS (2026-10-01).

Le contrat générique du retrait (`tests_queue_delete_contract`) ne construit ses témoins que sur
les `FileField`. Une sortie rangée dans une liste de chemins — déclarée à la rétention
(`RETENTION_MODELS[…]['path_lists']`, lue par `file_references.path_list_fields`) — lui échappait,
et c'est là qu'un retrait EFFAÇAIT encore à la main : les images de l'imager, par un `os.remove`
sans règle de propriété ni de partage, pendant que sa vidéo était libérée (décision D34 de
`MEDIA_STORAGE_TIERING`).

Mêmes gestes, même parc, mêmes attentes que le contrat générique — il est RÉUTILISÉ, pas
recopié : seul le témoin change, il porte en plus un fichier par liste déclarée. Aucune app n'est
nommée : une liste de plus déclarée est couverte sans toucher à ce module.
"""
from pathlib import Path

from django.db import models
from django.test import TestCase

from wama.common.tests import tests_queue_delete_contract as contract
from wama.common.utils.file_references import path_list_fields


class RemovingACardReleasesItsListedFilesTest(TestCase):

    # ⚠ Attribut de CLASSE, jamais un nom de module : une classe de test liée au niveau du module
    # serait collectée ici une seconde fois par le chargeur.
    _base = contract.DeletingACardRemovesTheFilesItOwnsTest

    setUp = _base.setUp
    _account_for = _base._account_for
    _delete_card = _base._delete_card
    _route_for = _base._route_for
    _post = _base._post
    _by_gesture = _base._by_gesture
    _not_released = _base._not_released
    _lost = _base._lost

    def _lists_of(self, model):
        return [name for declared, name in path_list_fields() if declared is model]

    def _fleet(self):
        """Le parc du contrat générique, restreint aux modèles qui déclarent une liste de chemins."""
        return [entry for entry in self._base._fleet(self) if self._lists_of(entry[3])]

    def _witness(self, model, account, folder, el=None):
        """Le témoin du contrat générique, plus UN fichier par liste déclarée — chemin ABSOLU,
        la forme que les backends écrivent réellement."""
        el, files = self._base._witness(self, model, account, folder, el=el)
        for name in self._lists_of(model):
            path = Path(self.tmp) / folder / f'temoin_{el.pk}_{name}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x')
            setattr(el, name, [str(path)])
            files.append(path)
        el.save()
        return el, files

    def test_a_path_list_is_declared(self):
        """Non-vacuité : sans liste déclarée dans le parc, les autres tests ne garderaient rien."""
        self.assertTrue(self._fleet(), 'aucune app de file ne déclare de liste de chemins')

    def test_every_deletion_gesture_releases_the_listed_files_the_app_owns(self):
        for surface, route, account, model, app_home in self._fleet():
            for gesture, files in self._by_gesture(surface, route, account, model, app_home):
                with self.subTest(surface=surface, gesture=gesture):
                    self.assertEqual([], self._lost(files), f'« {gesture} » a SUPPRIMÉ des fichiers '
                                                            'au lieu de les libérer')
                    self.assertEqual([], self._not_released(files), f'« {gesture} » n’a pas signalé '
                                     'les fichiers de l’app qu’il vient de rendre orphelins')

    def test_no_deletion_gesture_touches_a_listed_file_the_card_only_references(self):
        for surface, route, account, model, _app_home in self._fleet():
            for gesture, files in self._by_gesture(surface, route, account, model,
                                                 f'users/{account.id}/temp'):
                with self.subTest(surface=surface, gesture=gesture):
                    self.assertEqual([], self._lost(files), f'« {gesture} » a détruit des fichiers '
                                     'de l’utilisateur que la card ne faisait que RÉFÉRENCER')
                    self.assertEqual(sorted(p.name for p in files), sorted(self._not_released(files)),
                                     f'« {gesture} » signale comme libéré un fichier qui a son '
                                     'propre maître')

    def test_a_listed_file_another_card_designates_is_neither_lost_nor_released(self):
        """Une image envoyée vers une autre card par POINTAGE reste portée par elle : retirer la
        card qui l'a produite ne doit ni l'effacer ni l'annoncer orpheline."""
        for surface, route, account, model, app_home in self._fleet():
            holder_field = next((f.name for f in model._meta.concrete_fields
                                 if isinstance(f, models.FileField)), None)
            if holder_field is None:
                continue
            with self.subTest(surface=surface):
                el, files = self._witness(model, account, app_home)
                listed = [p for p in files if p.suffix == '.png']
                holder = contract._instance(model, account)
                setattr(holder, holder_field, listed[0].relative_to(self.tmp).as_posix())
                holder.save()
                self._delete_card(route, el)
                self.assertEqual([], self._lost(listed))
                self.assertEqual([listed[0].name], self._not_released(listed),
                                 'un fichier qu’une autre card désigne encore est annoncé orphelin')

    def test_a_listed_file_two_cards_list_is_released_with_the_last_one(self):
        """Deux cards qui LISTENT le même fichier le partagent : il n'est libéré qu'avec la
        dernière, et l'aperçu d'un retrait groupé le sait (`referenced_outside`)."""
        from wama.common.services.released_files import freed_by
        for surface, route, account, model, app_home in self._fleet():
            with self.subTest(surface=surface):
                first, files = self._witness(model, account, app_home)
                listed = [p for p in files if p.suffix == '.png']
                second = contract._instance(model, account)
                for name in self._lists_of(model):
                    setattr(second, name, list(getattr(first, name)))
                second.save()
                rels = [p.relative_to(self.tmp).as_posix() for p in listed]
                self.assertFalse(set(rels) & set(freed_by([first])),
                                 'l’aperçu annonce un fichier que l’autre card liste encore')
                self.assertEqual(rels, [r for r in freed_by([first, second]) if r in rels])
                self._delete_card(route, first)
                self.assertEqual([p.name for p in listed], self._not_released(listed),
                                 'un fichier que l’autre card liste encore est annoncé orphelin')
                self._delete_card(route, second)
                self.assertEqual([], self._lost(listed))
                self.assertEqual([], self._not_released(listed))

    def test_the_confirmation_preview_announces_the_listed_files(self):
        """L'aperçu de la confirmation et le geste lisent la même chose : ce que le retrait
        libère a d'abord été proposé à « Supprimer aussi le fichier »."""
        from wama.common.services.released_files import freed_by
        for surface, _route, account, model, app_home in self._fleet():
            with self.subTest(surface=surface):
                el, files = self._witness(model, account, app_home)
                self.assertEqual(sorted(p.relative_to(self.tmp).as_posix() for p in files),
                                 freed_by([el]))


class ListedFilesAreIndexedTest(TestCase):
    """L'INDEX des références (`file_references`) lit les listes de chemins comme les champs
    fichier (2026-10-02) — les gestes de D20 valent donc pour elles : un fichier listé est
    « utilisé », le déplacer fait suivre l'entrée, le supprimer la retire.

    Avant : une image de l'imager était dite « inutilisée » par le gestionnaire de fichiers, et la
    ranger dans la médiathèque (qui DÉPLACE le fichier puis repointe) la faisait disparaître de
    sa card. Générique : chaque liste déclarée est éprouvée, aucune app n'est nommée."""

    _base = contract.DeletingACardRemovesTheFilesItOwnsTest
    setUp = _base.setUp
    _account_for = _base._account_for

    def _declared(self):
        """(compte, modèle, champ liste) pour chaque liste de chemins déclarée dans le parc."""
        lists = dict((model, name) for model, name in path_list_fields())
        found = [(account, model, lists[model])
                 for _surface, _route, account, model, _home in self._base._fleet(self)
                 if model in lists]
        self.assertTrue(found, 'aucune app de file ne déclare de liste de chemins')
        return found

    def _card_listing(self, model, account, field, *names):
        """Une card dont la liste porte ces fichiers du dossier temporaire — chemins ABSOLUS."""
        el = contract._instance(model, account)
        rels = [f'users/{account.id}/temp/{name}' for name in names]
        for rel in rels:
            path = Path(self.tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x')
        setattr(el, field, [str(Path(self.tmp) / rel) for rel in rels])
        el.save()
        return el, rels

    def test_a_listed_file_is_in_use_and_the_card_is_named(self):
        from wama.common.services.released_files import status_of
        from wama.common.utils.file_references import direct_references, usage
        for account, model, field in self._declared():
            with self.subTest(model=model._meta.label):
                el, (rel, other) = self._card_listing(model, account, field, 'a.png', 'b.png')
                self.assertEqual(1, usage(rel)['count'])
                self.assertFalse(status_of(rel)['unused'])
                self.assertEqual([(model._meta.label, el.pk, field, rel)],
                                 [(r['label'], r['pk'], r['field'], r['name'])
                                  for r in direct_references(rel)])
                self.assertEqual(0, usage(f'users/{account.id}/temp/a.pn')['count'],
                                 'contre-épreuve : une sous-chaîne n’est pas une désignation')

    def test_the_question_ignores_the_row_it_is_asked_for(self):
        from wama.common.utils.file_references import is_referenced_elsewhere
        for account, model, field in self._declared():
            with self.subTest(model=model._meta.label):
                el, (rel,) = self._card_listing(model, account, field, 'seule.png')
                self.assertTrue(is_referenced_elsewhere(rel))
                self.assertFalse(is_referenced_elsewhere(rel, label=model._meta.label,
                                                         pk=el.pk, field=field))

    def test_moving_a_file_repoints_its_entry_and_keeps_its_form(self):
        from wama.common.utils.file_references import repoint
        for account, model, field in self._declared():
            with self.subTest(model=model._meta.label):
                el, (old, bystander) = self._card_listing(model, account, field, 'm.png', 'n.png')
                new = f'users/{account.id}/media_library/assets/m.png'
                self.assertEqual(1, repoint(old, new)['direct'])
                el.refresh_from_db()
                self.assertEqual([str(Path(self.tmp) / new), str(Path(self.tmp) / bystander)],
                                 [str(Path(p)) for p in getattr(el, field)],
                                 'l’entrée déplacée reste ABSOLUE, sa voisine ne bouge pas')

    def test_moving_a_folder_repoints_every_entry_below_it(self):
        from wama.common.utils.file_references import repoint
        for account, model, field in self._declared():
            with self.subTest(model=model._meta.label):
                el, (inside, outside) = self._card_listing(model, account, field,
                                                           'dossier/deep/f.png', 'ailleurs.png')
                repoint(f'users/{account.id}/temp/dossier', f'users/{account.id}/temp/moved',
                        folder=True)
                el.refresh_from_db()
                self.assertEqual(
                    [str(Path(self.tmp) / f'users/{account.id}/temp/moved/deep/f.png'),
                     str(Path(self.tmp) / outside)],
                    [str(Path(p)) for p in getattr(el, field)])

    def test_detaching_removes_the_entry_and_keeps_the_others(self):
        from wama.common.utils.file_references import detach, direct_references
        for account, model, field in self._declared():
            with self.subTest(model=model._meta.label):
                el, (gone, kept) = self._card_listing(model, account, field, 'x.png', 'y.png')
                self.assertEqual(1, detach(gone))
                el.refresh_from_db()
                self.assertEqual([str(Path(self.tmp) / kept)],
                                 [str(Path(p)) for p in getattr(el, field)])
                self.assertEqual([], direct_references(gone))
