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

    def test_the_confirmation_preview_announces_the_listed_files(self):
        """L'aperçu de la confirmation et le geste lisent la même chose : ce que le retrait
        libère a d'abord été proposé à « Supprimer aussi le fichier »."""
        from wama.common.services.released_files import freed_by
        for surface, _route, account, model, app_home in self._fleet():
            with self.subTest(surface=surface):
                el, files = self._witness(model, account, app_home)
                self.assertEqual(sorted(p.relative_to(self.tmp).as_posix() for p in files),
                                 freed_by([el]))
