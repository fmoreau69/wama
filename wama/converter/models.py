from django.db import models
from django.contrib.auth.models import User
from wama.common.models import BatchMixin, ProcessingTimeMixin, ScopedManager, ScopedVisibility, JOB_STATUS_CHOICES
from wama.common.utils.media_paths import UploadToUserPath


class ConversionProfile(models.Model):
    """Profil de conversion sauvegardable — reproduire des réglages entre sessions."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversion_profiles')
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    media_type = models.CharField(max_length=20)   # 'image', 'video', 'audio'
    output_format = models.CharField(max_length=20)
    options = models.JSONField(default=dict)        # format-specific options
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.output_format})"


class ConversionBatch(BatchMixin, ScopedVisibility):
    """Groupe de conversions partageant la même nature (image/vidéo/audio/…).

    Créé soit par import multi-fichiers (1 batch par nature), soit par fichier
    batch d'URLs/chemins. Les réglages de sortie (format/qualité) sont communs
    à tous les jobs du batch — d'où le regroupement par nature.

    **Unité de partage de la file** (cf. `batch_common.build_batches_list`) — lecture seule
    pour le destinataire, PROFILES_PERMISSIONS §7.

    ⚠ `BatchMixin` ajouté le 2026-08-24 : ce modèle était le SEUL lot du dépôt à ne pas
    l'avoir (10/12 l'ont), alors qu'il porte un `batch_file`. Sans lui, `delete()` ne
    déclenchait pas `cleanup_files()` — le fichier partagé d'un lot supprimé serait resté
    sur disque. Dette LATENTE et non fuite constatée : mesuré à l'ajout, **0 lot sur 53
    n'a de `batch_file` non vide** (ni ici, ni chez transcriber qui a pourtant le mixin).
    Le mixin n'apporte AUCUN champ — pas de migration.
    """

    objects = ScopedManager()

    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversion_batches')
    created_at  = models.DateTimeField(auto_now_add=True)
    batch_file  = models.FileField(upload_to=UploadToUserPath('converter', 'input'),
                                   blank=True, null=True)
    media_type  = models.CharField(max_length=20, blank=True)  # nature commune
    total       = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"ConversionBatch #{self.id} — {self.media_type} ({self.total})"


class ConversionJob(ProcessingTimeMixin, ScopedVisibility):
    """Card de conversion — partageable en lecture seule (PROFILES_PERMISSIONS §7)."""

    objects = ScopedManager()

    #: Vocabulaire COMMUN (wama.common.models) — plus de copie par app.
    STATUS_CHOICES = JOB_STATUS_CHOICES
    # Ingest URL déclaratif — consommé par la brique commune
    # common/utils/source_ingest.ensure_local_input() au démarrage de la tâche.
    WAMA_INGEST = {
        'source': 'source_url',
        'target': 'input_file',
        'mode': 'media',
        'name_field': 'input_filename',
    }

    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversion_jobs')
    input_file    = models.FileField(upload_to=UploadToUserPath('converter', 'input'), blank=True)
    source_url    = models.CharField(max_length=2000, blank=True, default='')
    input_filename = models.CharField(max_length=255)
    media_type    = models.CharField(max_length=20, blank=True)  # 'image', 'video', 'audio'

    output_file   = models.FileField(upload_to=UploadToUserPath('converter', 'output'),
                                     null=True, blank=True)
    output_format = models.CharField(max_length=20, blank=True)  # 'mp4', 'webp', …

    # ── RÉGLAGES : une colonne par param du schéma (uniformisation 2026-09-01) ──────────
    # Les 9 autres apps déclarent leurs réglages en colonnes ; le converter les rangeait
    # dans deux JSON. Le portage aligne la forme SANS changer la sémantique, et c'est cette
    # sémantique qui commande la déclaration :
    #
    #   ⚠ AUCUN `default=` significatif ici — VIDE veut dire « non réglé, le préréglage
    #   décide ». Les défauts vivent au SCHÉMA (`params.py`), où ils servent l'affichage ET
    #   la valeur effective via `param_schema.effective_settings` (défauts ← preset ←
    #   réglages posés). Poser `default=85` sur `quality` rendrait TOUS les jobs explicites
    #   et les trois préréglages n'arbitreraient plus rien, en silence (ROADMAP §23.2bis).
    #   *Une couche qui arbitre a besoin de distinguer « absent » de « posé ».*
    #
    # Les toggles font exception au `null` : `False` == non coché == absent du JSON d'avant
    # — les deux se confondent sans conséquence (aucun préréglage ne pose un miroir).
    quality        = models.IntegerField(null=True, blank=True)   # image, 1-100
    resize_w       = models.IntegerField(null=True, blank=True)   # image, 0 = inchangé
    resize_h       = models.IntegerField(null=True, blank=True)
    rotation       = models.CharField(max_length=8, blank=True, default='')   # '', 90, 180, 270
    flip_h         = models.BooleanField(default=False)
    flip_v         = models.BooleanField(default=False)
    video_quality  = models.IntegerField(null=True, blank=True)   # CRF 0-51
    fps            = models.IntegerField(null=True, blank=True)
    gif_fps        = models.IntegerField(null=True, blank=True)
    gif_width      = models.IntegerField(null=True, blank=True)
    audio_bitrate  = models.CharField(max_length=16, blank=True, default='')
    sample_rate    = models.CharField(max_length=16, blank=True, default='')
    channels       = models.CharField(max_length=4, blank=True, default='')
    normalize      = models.BooleanField(default=False)
    # Post-traitement cross-app (enhancer inline) — appliqué APRÈS la conversion.
    upscale        = models.CharField(max_length=8, blank=True, default='')
    denoise        = models.BooleanField(default=False)
    audio_enhance  = models.BooleanField(default=False)

    #: Réglages du schéma rangés dans le JSON (avant le 2026-09-01) — CONSERVÉ le temps que
    #: la migration de données soit validée en production, puis retirable (REMOVAL_LEDGER).
    #: Ne plus LIRE ni ÉCRIRE : les propriétés `options`/`cross_app_options` ci-dessous sont
    #: la source, et elles viennent des colonnes.
    options_legacy = models.JSONField(default=dict, blank=True)
    cross_app_options_legacy = models.JSONField(default=dict, blank=True)

    #: Noms des colonnes de réglage, par destination — l'ordre suit `params.py`.
    CHAMPS_OPTIONS = ('quality', 'resize_w', 'resize_h', 'rotation', 'flip_h', 'flip_v',
                      'video_quality', 'fps', 'gif_fps', 'gif_width', 'audio_bitrate',
                      'sample_rate', 'channels', 'normalize')
    CHAMPS_CROSS_APP = ('upscale', 'denoise', 'audio_enhance')

    def _reglages(self, champs) -> dict:
        """{nom: valeur} des seuls réglages POSÉS — reproduit à l'identique ce que les JSON
        contenaient : ni `None`, ni `''`, ni un interrupteur décoché (absent d'avant)."""
        out = {}
        for nom in champs:
            v = getattr(self, nom, None)
            if v is None or v == '' or v is False:
                continue
            out[nom] = v
        return out

    @property
    def options(self) -> dict:
        """Réglages posés — MÊME contrat que l'ancien JSONField, reconstruit des colonnes.
        Garder ce nom est ce qui permet aux ~8 lecteurs (tâche, backends, cross_app, chips,
        gear, status) de continuer sans une ligne de changement."""
        return self._reglages(self.CHAMPS_OPTIONS)

    @property
    def cross_app_options(self) -> dict:
        return self._reglages(self.CHAMPS_CROSS_APP)

    def poser_reglages(self, valeurs: dict) -> list:
        """Écrit des réglages sur les colonnes ; renvoie les champs TOUCHÉS (pour
        `update_fields`). Une clé absente de `valeurs` n'est pas touchée ; une valeur vide
        REMET la colonne à « non réglé » (c'est ainsi qu'on retire un réglage).

        Point d'entrée UNIQUE de l'écriture — les propriétés `options`/`cross_app_options`
        sont en lecture seule, par construction : deux façons d'écrire un même réglage, c'est
        la divergence assurée (le converter en a fait l'expérience avec ses deux JSON).
        """
        connus = set(self.CHAMPS_OPTIONS) | set(self.CHAMPS_CROSS_APP)
        touches = []
        for nom, v in (valeurs or {}).items():
            if nom not in connus:
                continue              # clé hors schéma : ignorée (jamais d'attribut inventé)
            champ = self._meta.get_field(nom)
            interne = champ.get_internal_type()
            if interne == 'BooleanField':
                v = v in (True, 'true', 'True', 1, '1')
            elif interne == 'IntegerField':
                try:
                    v = int(float(v)) if v not in (None, '') else None
                except (TypeError, ValueError):
                    continue          # illisible : on ne pose rien plutôt qu'une valeur fausse
            else:
                v = '' if v is None else str(v)
            setattr(self, nom, v)
            touches.append(nom)
        return touches

    profile       = models.ForeignKey(ConversionProfile, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='jobs')

    # Regroupement batch (multi-fichiers même nature, ou fichier batch d'urls).
    # Tout job de file appartient à un batch (batch-of-1 pour un fichier seul).
    batch           = models.ForeignKey(ConversionBatch, null=True, blank=True,
                                        on_delete=models.CASCADE, related_name='items')
    batch_row_index = models.IntegerField(default=0)

    # Quick-convert (Filemanager) — ephemeral jobs never shown in the queue,
    # output written next to the source, row dismissed after delivery.
    ephemeral     = models.BooleanField(default=False)
    # MEDIA_ROOT-relative directory where the output must be written.
    # Empty → default converter/output/<user>/. Set for in-place quick convert.
    dest_dir      = models.CharField(max_length=500, blank=True)
    # Quality preset: '', 'web', 'balanced', 'max'.
    quality_preset = models.CharField(max_length=20, blank=True)

    status        = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    task_id       = models.CharField(max_length=100, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    progress      = models.IntegerField(default=0)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.input_filename} → {self.output_format} [{self.status}]"

    @property
    def output_filename(self):
        if self.output_file:
            from pathlib import Path
            return Path(self.output_file.name).name
        return ''

    @property
    def gear_data(self):
        """data-* du bouton ⚙ (reflet de la card dans le volet) — brique COMMUNE card_gear
        dérivée du schéma ; valeurs = options + cross_app_options (JSON), repli champs de
        modèle homonymes (media_type/output_format)."""
        from wama.common.utils.card_gear import gear_data
        from .params import PARAMS
        return gear_data(self, PARAMS,
                         values={**(self.options or {}), **(self.cross_app_options or {})})
