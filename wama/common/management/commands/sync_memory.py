"""
Alimente la mémoire depuis les faits déjà en base. Doc : `WAMA_MEMORY.md §7`.

    python manage.py sync_memory --dry-run          # ne montre que ce qui changerait
    python manage.py sync_memory                    # projette (ZÉRO appel de modèle)
    python manage.py sync_memory --depuis 2026-08-01
    python manage.py sync_memory --reindex          # ⚠ SOLLICITE LE GPU (embeddings par lot)

Deux étages volontairement SÉPARÉS, et c'est le point de conception : la projection est mécanique
et gratuite, la vectorisation charge un modèle. Les fondre en une seule commande imposerait le GPU
à qui ne veut que rafraîchir les souvenirs — d'où `--reindex` en option explicite, jamais par
défaut (règle d'exploitation : pas de chargement Ollama enchaîné sans action explicite).
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Projette RunOutcome vers la mémoire (mécanique, sans modèle). "
            "--reindex calcule en plus les vecteurs manquants (sollicite le GPU).")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="N'écrit rien ; affiche ce qui changerait.")
        parser.add_argument('--depuis', type=str, default=None,
                            help='Ne considérer que les gestes depuis cette date (AAAA-MM-JJ).')
        parser.add_argument('--limite', type=int, default=None,
                            help="Nombre maximum d'objets traités.")
        parser.add_argument('--rag', action='store_true',
                            help="(RETIRÉ 2026-08-21) L'entrée au RAG est un geste utilisateur.")
        parser.add_argument('--dev-ai', action='store_true',
                            help="Reprend wama-dev-ai/memory.json en souvenirs NON APPROUVÉS.")
        parser.add_argument('--reindex', action='store_true',
                            help='⚠ Calcule les vecteurs manquants — CHARGE bge-m3 sur Ollama.')
        parser.add_argument('--modeles-obsoletes', action='store_true',
                            help='Avec --reindex : reprend aussi les lignes vectorisées par un '
                                 "autre modèle (bascule d'embedder).")

    def handle(self, *args, **opts):
        from datetime import datetime

        from django.utils import timezone

        from wama.common.memory.project import project_run_outcomes
        from wama.common.memory.store import reindex

        depuis = None
        if opts['depuis']:
            try:
                depuis = timezone.make_aware(datetime.strptime(opts['depuis'], '%Y-%m-%d'))
            except ValueError:
                self.stderr.write(self.style.ERROR(
                    f"--depuis attend AAAA-MM-JJ, reçu {opts['depuis']!r}"))
                return

        self.stdout.write('── Projection RunOutcome → mémoire (aucun modèle appelé) ──')
        r = project_run_outcomes(depuis=depuis, limite=opts['limite'], dry_run=opts['dry_run'])
        self.stdout.write(
            f"  objets traités : {r['objets']}\n"
            f"  créés          : {r['crees']}\n"
            f"  réécrits       : {r['reecrits']}\n"
            f"  inchangés      : {r['inchanges']}")
        if r['ignores_sans_user']:
            # Un geste sans propriétaire ne peut être rappelé par personne : `scoped_visible_q`
            # ne le rendrait à aucun utilisateur. L'écrire créerait une ligne morte.
            self.stdout.write(self.style.WARNING(
                f"  ignorés (sans utilisateur, non rappelables) : {r['ignores_sans_user']}"))
        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('  (--dry-run : rien écrit)'))

        if opts['rag']:
            # ⚠ RETIRÉ le 2026-08-21, et le refus est VOLONTAIREMENT un message plutôt qu'une
            # suppression du flag : la commande doit expliquer POURQUOI l'option a disparu, pas
            # répondre « unrecognized arguments » à qui suit une vieille doc. Le balayage
            # indexait les sorties de TOUS les utilisateurs sans qu'aucun n'ait rien demandé
            # (939 fragments, purgés) — l'entrée au RAG est un GESTE, cf. WAMA_MEMORY.md §7ter.
            self.stderr.write(self.style.ERROR(
                "--rag a été RETIRÉ (2026-08-21) : le balayage global indexait les sorties de "
                "tous les utilisateurs sans leur geste. L'entrée au RAG passe désormais par "
                "wama.common.memory.index.add_to_rag() — action explicite de l'utilisateur, "
                "niveau choisi ('user' | 'unit'). Cf. WAMA_MEMORY.md §7ter."))
            return

        if opts['dev_ai']:
            from wama.common.memory.dev_ai import import_memory
            self.stdout.write('\n── Reprise de wama-dev-ai/memory.json ──')
            d = import_memory(dry_run=opts['dry_run'])
            if d.get('erreur'):
                self.stderr.write(self.style.ERROR(f"  lecture impossible : {d['erreur']}"))
            else:
                self.stdout.write(
                    f"  source           : {d['fichier']} (maj {d['date_source']})\n"
                    f"  entrées lues     : {d['lus']}\n"
                    f"  créées           : {d['crees']}\n"
                    f"  déjà présentes   : {d['deja_presents']}")
                if d['crees']:
                    self.stdout.write(self.style.WARNING(
                        "  ⚠ NON APPROUVÉES, donc INVISIBLES au rappel : une revue humaine est "
                        "requise.\n    Le fichier date du "
                        f"{d['date_source']} — vérifier avant d'approuver."))

        if not opts['reindex']:
            self.stdout.write(
                '\n  Vecteurs NON calculés. `--reindex` quand la machine est libre '
                '(les souvenirs et fragments restent trouvables en lexical entre-temps).')
            return

        self.stdout.write('\n── Réindexation vectorielle (CHARGE bge-m3) ──')
        v = reindex(modeles_obsoletes=opts['modeles_obsoletes'], dry_run=opts['dry_run'])
        if not v['embedder_available']:
            self.stderr.write(self.style.ERROR(
                "  embedder indisponible — Ollama démarré ? `ollama pull bge-m3` fait ?"))
            return
        self.stdout.write(f"  vectorisés : {v['traites']}   échecs : {v['echecs']}   "
                          f"restants : {v['restants']}")
