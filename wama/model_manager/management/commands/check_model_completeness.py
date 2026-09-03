"""
Fiche de COMPLÉTUDE des modèles INSTALLÉS — ce que le catalogue ne sait pas encore d'eux.

    python manage.py check_model_completeness           # carte des trous
    python manage.py check_model_completeness --json
    python manage.py check_model_completeness --yolo    # déplie la famille YOLO

Raison d'être (2026-09-03, 🔚 point d'entrée de l'instance bancs/prospection du 02/09) :
« vérifier les informations de l'ENSEMBLE des modèles installés — tâche, licence, VRAM
déclarée vs mesurée, backend présent — pour lister les TROUS ». Personne ne le faisait.
La chaîne de contrôle existante s'arrête juste avant :

  - `verify_models`            : catalogue ↔ disque (téléchargé ou non) — l'EXISTENCE ;
  - `check_model_taxonomy`     : types/sources/TÂCHES tous déclarés — le VOCABULAIRE ;
  - `check_model_declarations` : tags écrits en dur ↔ catalogue — les RENVOIS ;
  - **la complétude par modèle installé : PERSONNE.** Un modèle peut être sur le disque,
    catalogué, de taxonomie juste, et rester inutilisable faute de licence connue, de VRAM
    crédible ou de backend — sans que rien ne le dise.

⚠ La TÂCHE n'est PAS revérifiée ici : `check_model_taxonomy` en est propriétaire (il la
confronte à l'énumération déclarée, ce qu'un simple test de présence ne ferait pas). Un
second contrôle de la même chose finirait par en contredire un autre. Ce rapport la
rappelle en une ligne et renvoie.

⚠⚠ LE VERDICT DE BACKEND EST VENV-DÉPENDANT — mesuré le 2026-09-03. Depuis le raffinement
`missing_packages()` de l'inventaire (commit 02001d2d : « l'inventaire n'annonce que
l'EXÉCUTABLE »), `known_engines()` ne rend que les moteurs dont le runtime pip est présent
DANS LE VENV COURANT. Le même appel a rendu `kokoro-onnx` MANQUANT depuis venv_win et
PRÉSENT depuis venv_linux — sur le même catalogue, à la même seconde. Le runtime qui fait
foi est **venv_linux** (les workers y tournent). D'où l'en-tête qui nomme le venv : un
rapport de grisage sans son venv ne veut rien dire. *Même famille que
`manifest_export --check`, dont le corpus est extrait par `importlib.metadata`.*

⚠ CE CONTRÔLE NE GARDE RIEN (exit 0 toujours). Aucun de ses constats n'est « interdit » :
un backend écrit dont le runtime attend un GO humain est un état LÉGITIME (Qwen3-TTS), une
VRAM estimée est un plancher honnête en attendant un banc. Un gate rouge en permanence
finit par être relu comme la normale — le défaut exact que `/reprise` documente sur son
attendu de suite de tests. C'est une CARTE DE DETTE, comme `WAMA_MECANISMES` ; elle se lit,
elle ne bloque pas.
"""
import json

from django.core.management.base import BaseCommand


def est_yolo(m):
    return 'yolo' in f"{m.model_key or ''} {m.name or ''}".lower()


class Command(BaseCommand):
    help = "Carte des informations manquantes sur les modèles installés (licence, VRAM, backend)."

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help="Sortie JSON brute.")
        parser.add_argument('--yolo', action='store_true',
                            help="Déplie la famille YOLO (repliée par défaut : ~47 lignes de "
                                 "même forme, déclarées en famille).")

    def handle(self, *args, **options):
        import sys
        from wama.model_manager.models import AIModel
        from wama.common.backends.manager import backend_missing, known_engines

        qs = AIModel.objects.filter(is_downloaded=True, is_proposed=False).order_by('model_key')
        tous = list(qs)
        yolo = [m for m in tous if est_yolo(m)]
        lignes = tous if options['yolo'] else [m for m in tous if not est_yolo(m)]

        moteurs = sorted(known_engines())
        rapport = {
            'venv': sys.prefix,
            'moteurs_inventories': moteurs,
            'installes': len(tous),
            'yolo_replies': 0 if options['yolo'] else len(yolo),
            'axes': {},
        }

        sans_licence, vram_absente, vram_estimee = [], [], []
        backend_rouge, backend_hors_verdict = [], []
        sans_tache = []

        for m in lignes:
            if not (m.license or '').strip():
                sans_licence.append(m)
            if not m.vram_gb:
                vram_absente.append(m)
            elif (m.extra_info or {}).get('vram_estimated'):
                vram_estimee.append(m)
            if not (m.capabilities or {}).get('task'):
                sans_tache.append(m)

            engine = ((m.composition or {}).get('runtime') or {}).get('engine') or ''
            if m.backend_ref or (engine and not backend_missing(m)):
                continue
            (backend_rouge if engine else backend_hors_verdict).append(m)

        axes = (
            ('sans_licence', sans_licence,
             "licence inconnue — bloque toute décision de diffusion (LICENSING.md)"),
            ('vram_absente', vram_absente,
             "aucune VRAM déclarée — le modèle échappe à la sélection VRAM-aware"),
            ('vram_estimee', vram_estimee,
             "VRAM ESTIMÉE des poids, jamais mesurée — plancher en attente d'un banc"),
            ('backend_rouge', backend_rouge,
             "moteur DÉCLARÉ qu'aucun inventaire ne sert → grisé, exclu du tirage auto"),
            ('backend_hors_verdict', backend_hors_verdict,
             "ni moteur déclaré ni backend_ref → HORS du périmètre du verdict (garde "
             "permissive, voulue). ⚠ N'ÉQUIVAUT PAS À « cassé » : ces modèles sont soit "
             "non rattachés à une app (absents des selects, filtrés par `source`), soit "
             "routés par le gestionnaire de backends propre à leur app"),
        )
        for cle, items, _ in axes:
            rapport['axes'][cle] = [m.model_key for m in items]
        rapport['sans_tache'] = [m.model_key for m in sans_tache]

        if options['json']:
            self.stdout.write(json.dumps(rapport, indent=2, ensure_ascii=False))
            return

        self.stdout.write("=" * 78)
        self.stdout.write(f"COMPLÉTUDE DES MODÈLES INSTALLÉS — {len(lignes)} ligne(s)")
        if not options['yolo'] and yolo:
            self.stdout.write(f"  (+ {len(yolo)} YOLO repliées — `--yolo` pour les déplier)")
        self.stdout.write(f"  venv     : {sys.prefix}")
        self.stdout.write(f"  moteurs  : {', '.join(moteurs) or '(aucun inventaire enregistré)'}")
        self.stdout.write("  ⚠ le verdict de backend suit le VENV (cf. docstring) — "
                          "venv_linux fait foi.")
        self.stdout.write("=" * 78)

        for cle, items, pourquoi in axes:
            if not items:
                self.stdout.write(self.style.SUCCESS(f"\n✓ {cle} : aucun"))
                continue
            style = self.style.ERROR if cle == 'backend_hors_verdict' else self.style.WARNING
            self.stdout.write(style(f"\n⚠ {cle} : {len(items)}"))
            self.stdout.write(f"    {pourquoi}")
            for m in items:
                engine = ((m.composition or {}).get('runtime') or {}).get('engine') or '-'
                self.stdout.write(
                    f"      {m.model_key:<58} vram={m.vram_gb or 0:<6} "
                    f"lic={(m.license or '-')[:22]:<22} moteur={engine}")

        if sans_tache:
            self.stdout.write(self.style.WARNING(
                f"\n⚠ sans tâche : {len(sans_tache)} — "
                f"{', '.join(m.model_key for m in sans_tache)}"))
        self.stdout.write("    (la tâche appartient à `check_model_taxonomy` — rappel, "
                          "pas un second contrôle)")

        self.stdout.write("\nCarte de dette, pas un gate : exit 0 quoi qu'il arrive "
                          "(cf. docstring).")
