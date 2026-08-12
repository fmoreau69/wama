"""
Mesure la divergence entre deux transcriptions d'un même audio — SANS rien piloter.

POURQUOI UNE COMMANDE AVANT UN BRANCHEMENT. « Métrique d'abord, boucle ensuite, autonomie en
dernier » (ROADMAP §16.7-4). On veut pouvoir REGARDER le signal sur de vrais fichiers, et le
recalibrer, avant qu'il ne colore une heatmap ou n'ordonne des modèles. Un signal branché avant
d'être vu est un signal qu'on ne saura plus débrancher.

    # deux transcriptions WAMA du meme media
    python manage.py divergence_asr --transcript 12 --contre 15

    # une transcription WAMA contre un fichier externe (jeu de test §8.5)
    python manage.py divergence_asr --transcript 12 --fichier /chemin/externe.json

    python manage.py divergence_asr --transcript 12 --contre 15 --json
"""
import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("Divergence inter-systemes entre deux transcriptions du meme audio "
            "(signal objectif, aucun avis de LLM).")

    def add_arguments(self, parser):
        parser.add_argument('--transcript', type=int, required=True,
                            help="Id du Transcript de REFERENCE.")
        parser.add_argument('--contre', type=int,
                            help="Id d'un second Transcript du meme media.")
        parser.add_argument('--fichier',
                            help="Fichier JSON de segments [{start_time,end_time,text}, ...].")
        parser.add_argument('--niveau', default='attention',
                            choices=['accord', 'attention', 'divergence'],
                            help="Niveau minimal des zones listees (defaut: attention).")
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **o):
        from wama.common.services.divergence import divergence_segments, zones_a_verifier
        from wama.transcriber.models import Transcript

        if not o.get('contre') and not o.get('fichier'):
            raise CommandError("Preciser --contre <id> ou --fichier <chemin>.")

        def _segments(t):
            """Segments d'un Transcript — la version CORRIGEE prime si elle existe."""
            return t.corrected_segments_json or t.segments_json or []

        try:
            ref = Transcript.objects.get(pk=o['transcript'])
        except Transcript.DoesNotExist:
            raise CommandError(f"Transcript #{o['transcript']} introuvable.")

        if o.get('contre'):
            try:
                autre = Transcript.objects.get(pk=o['contre'])
            except Transcript.DoesNotExist:
                raise CommandError(f"Transcript #{o['contre']} introuvable.")
            segments_b, source_b = _segments(autre), f"Transcript #{autre.pk}"
        else:
            try:
                with open(o['fichier'], encoding='utf-8') as f:
                    charge = json.load(f)
            except (OSError, ValueError) as e:
                raise CommandError(f"Fichier illisible : {e}")
            segments_b = charge.get('segments') if isinstance(charge, dict) else charge
            source_b = o['fichier']

        resultat = divergence_segments(_segments(ref), segments_b)

        if o['json']:
            self.stdout.write(json.dumps(resultat, indent=2, ensure_ascii=False))
            return

        glob = resultat['divergence_globale']
        self.stdout.write(f"Reference   : Transcript #{ref.pk}")
        self.stdout.write(f"Comparaison : {source_b}\n")
        if glob is None:
            self.stdout.write(self.style.ERROR(
                "Aucune comparaison possible (segments absents des deux cotes)."))
            return

        self.stdout.write(f"Divergence globale (ponderee par la duree) : "
                          f"{self.style.WARNING(f'{glob:.1%}')}")
        self.stdout.write(f"Couverture : {resultat['couverture']:.0%} des segments de reference "
                          f"ont un vis-a-vis  ({resultat['segments_sans_vis_a_vis']} sans)")

        repartition = {}
        for s in resultat['segments']:
            repartition[s['niveau']] = repartition.get(s['niveau'], 0) + 1
        self.stdout.write("Repartition : " + '  '.join(
            f"{k}={v}" for k, v in sorted(repartition.items())))

        zones = zones_a_verifier(resultat, o['niveau'])
        self.stdout.write(f"\n{len(zones)} zone(s) a verifier en priorite "
                          f"(niveau >= {o['niveau']}) :\n")
        for s in zones[:20]:
            d = '—' if s['divergence'] is None else f"{s['divergence']:.0%}"
            self.stdout.write(f"  [{s['start_time']:>7.1f}s] {s['niveau']:14s} {d:>5s}")
            self.stdout.write(f"      ref : {(s['texte_reference'] or '')[:95]}")
            self.stdout.write(f"      cmp : {(s['texte_comparaison'] or '(rien en face)')[:95]}")
        if len(zones) > 20:
            self.stdout.write(f"  … et {len(zones) - 20} autre(s).")

        self.stdout.write(self.style.NOTICE(
            "\nCe signal dit OU les deux systemes se contredisent, JAMAIS lequel a raison : "
            "une divergence peut venir d'une erreur de l'un comme d'un passage objectivement "
            "difficile. C'est une zone a regarder, pas un verdict."))
