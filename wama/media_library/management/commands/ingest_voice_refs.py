"""Verse les voix de RÉFÉRENCE du synthesizer dans la médiathèque, comme `SystemAsset(voice)`.

    python manage.py ingest_voice_refs            # PLAN seul, n'écrit rien
    python manage.py ingest_voice_refs --apply    # crée les lignes, déplace les fichiers, retire le dossier

POURQUOI (Fabien, 12/09 : *« Les voix sont des médias, les médias communs vont dans la
médiathèque par défaut »* — plan `MEDIA_STORAGE_TIERING §9.4`, marche 4). Jusqu'ici la
TAXONOMIE des voix vivait dans l'ARBORESCENCE (`<langue>/<âge>/<genre>_<âge>[_<n>]_<iso>.wav`)
et cinq lecteurs la parcouraient. Elle devient des ATTRIBUTS (`attributes` — construction A′,
`natures.py`), et le fichier un asset commun sous `media_library/system/`.

⚠ LA CLÉ RESTE L'IDENTIFIANT D'AVANT. `SystemAsset.name` = l'ancien id de preset
    (`french/adult/male_adult_1_fr`, `default`, `female_1`…) — c'est ce que les lignes en base
    STOCKENT (`VoiceSynthesis.voice_preset`, 98 lignes ; `AvatarJob`, 5) : frontière des données,
    elles continuent de résoudre par ce nom. Les nouvelles sélections se font par `sa_<id>`.

⚠ PROVENANCE : le fichier sur disque peut venir de VoxPopuli, d'un échantillon XTTS-v2 ou de
    LJSpeech (trois sources du catalogue, la première qui réussit gagne) — elle n'a jamais été
    tracée PAR FICHIER. On n'invente donc ni `source_url` ni `license` : ils restent VIDES et
    la commande le DIT. Les téléchargements futurs (`download_missing_voice_refs`) les posent.

⚠ ORDRE et IDEMPOTENCE : ligne AVANT déplacement (le stockage Django COPIE, l'original n'est
    retiré qu'une fois la ligne posée) ; un nom déjà porté par un `SystemAsset` est SAUTÉ.
    Même règle qu'`ingest_gallery_assets`.
"""
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

#: Dossiers historiques — le second ne contient plus que son README depuis le 12/09.
SOURCE = 'synthesizer/voice_references'
ANCIEN = 'synthesizer/default_voices'


def voice_id_of(path: Path, racine: Path) -> str:
    """`<racine>/french/adult/male_adult_1_fr.wav` → `french/adult/male_adult_1_fr` (l'id d'avant)."""
    return str(path.relative_to(racine)).replace('\\', '/').removesuffix('.wav')


class Command(BaseCommand):
    help = "Verse `synthesizer/voice_references/` dans la médiathèque comme SystemAsset(voice)"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Exécute réellement (sinon : PLAN seul, rien n'est écrit)")

    def handle(self, *args, **opts):
        from wama.common.tts.voice_refs import attributes_from_voice_id, ingest_voice_file
        from wama.media_library.models import SystemAsset

        racine = Path(settings.MEDIA_ROOT)
        dossier = racine / SOURCE
        appliquer = opts['apply']

        fichiers = sorted(dossier.rglob('*.wav')) if dossier.is_dir() else []
        deja = set(SystemAsset.objects.filter(asset_type='voice').values_list('name', flat=True))
        plan = [(voice_id_of(f, dossier), f) for f in fichiers]
        a_faire = [(vid, f) for vid, f in plan if vid not in deja]
        sans_attributs = [vid for vid, _ in a_faire if not attributes_from_voice_id(vid)]

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            "VOIX DE RÉFÉRENCE → MÉDIATHÈQUE — " + ("EXÉCUTION" if appliquer else "PLAN (rien n'est écrit)")))
        self.stdout.write(f"  dossier source      : {SOURCE}")
        self.stdout.write(f"  fichiers trouvés    : {len(fichiers)}")
        self.stdout.write(f"  déjà en médiathèque : {len(plan) - len(a_faire)}   (sautés)")
        self.stdout.write(f"  à verser            : {len(a_faire)}")
        for vid, f in a_faire:
            attrs = attributes_from_voice_id(vid)
            self.stdout.write(f"      {f.stat().st_size / 1e6:6.2f} Mo  {vid:40s} {attrs}")
        if sans_attributs:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {len(sans_attributs)} id(s) sans attribut déductible : {sans_attributs}"))
        self.stdout.write(self.style.WARNING(
            "  ⚠ provenance non tracée par fichier : `source_url` et `license` restent VIDES "
            "(à renseigner — §9.6)"))

        if not appliquer:
            self.stdout.write("")
            self.stdout.write("  → relancer avec --apply pour exécuter")
            return

        verses, echecs = 0, []
        for vid, f in a_faire:
            try:
                asset = ingest_voice_file(
                    vid, f,
                    description=f"Voix de référence versée le 2026-09-13 depuis `{SOURCE}/{vid}.wav` "
                                "(taxonomie langue/âge/genre → attributs).")
                # Le stockage a COPIÉ : on retire l'original une fois la ligne posée, jamais avant.
                if asset is not None and Path(asset.file.path).is_file() and Path(asset.file.path) != f:
                    f.unlink()
                verses += 1
            except Exception as exc:
                echecs.append((vid, f"{type(exc).__name__}: {exc}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"  versées : {verses} / {len(a_faire)}"))
        for vid, e in echecs:
            self.stdout.write(self.style.ERROR(f"    {vid} — {e}"))

        # Le dossier ne porte plus que des README (documentation d'une arborescence qui n'existe
        # plus) et des sous-dossiers vides : on le retire ENTIER, ainsi que l'ancien `default_voices/`.
        if not echecs:
            for rel in (SOURCE, ANCIEN):
                d = racine / rel
                if not d.is_dir():
                    continue
                restes = [p for p in d.rglob('*') if p.is_file() and p.suffix.lower() == '.wav']
                if restes:
                    self.stdout.write(self.style.ERROR(
                        f"  ⚠ {rel}/ contient encore {len(restes)} wav non versé(s) — conservé"))
                    continue
                shutil.rmtree(d)
                self.stdout.write(f"  dossier retiré      : {rel}/")
