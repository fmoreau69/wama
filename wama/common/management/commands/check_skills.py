"""
Santé du corpus de skills — le contrôle qui manquait à `/skill-forge`.

POURQUOI CETTE COMMANDE EXISTE (2026-09-09)

    `ROADMAP §16.7` a longtemps dit qu'il manquait « l'écrivain » de la mémoire procédurale.
    C'est faux depuis le 2026-07-29 : l'écrivain est `/skill-forge`. Et il est même DÉCLENCHÉ —
    `/cloture` le déroule (« distiller à la clôture est LE moment-écrivain »).

    Le défaut réel est ailleurs, et il est MESURÉ dans le dépôt : `PROJECT_STATUS:10928` note
    « **`/skill-forge` NON déroulé** (clôture tardive) — pending nommé ». Le déclencheur est une
    ÉTAPE DE RITUEL, donc il dépend de la diligence de celui qui le déroule. C'est exactement le
    raisonnement qui a fait naître `check_docs` : « un skill dépend de la DILIGENCE de celui qui
    le lance. Une commande, elle, échoue. »

    Cette commande ne distille RIEN et n'écrit RIEN. Elle rend VISIBLE ce que les conventions de
    `/skill-forge` posent déjà par écrit, pour que l'état du corpus cesse d'être une impression.

CE QU'ELLE MESURE — trois faits, tous adossés à une règle ÉCRITE dans `/skill-forge` :

  1. CANDIDATS (§3) — un skill né d'une seule résolution porte
     `⚠ CANDIDAT (n=1, <date>)`. La commande les liste avec leur ÂGE, parce que §4 dit :
     « un candidat qui dort sans 2ᵉ occurrence pendant des mois est un candidat à la fusion ou
     au retrait — le signaler à l'utilisateur, ne jamais le supprimer seul ».
  2. DÉCLENCHEUR ABSENT (§5.2) — « relire la description depuis la position du DÉCLENCHEUR :
     la phrase que dira l'utilisateur la matche-t-elle ? Un skill que rien ne déclenche
     n'existe pas ». Une description sans formulation d'usage est donc un défaut de contrat.
  3. FRONTMATTER INCOMPLET — `name` et `description` sont ce qu'un agent lit pour CHOISIR
     (divulgation progressive). Sans eux, le skill est invisible à la sélection.

⚠ CE QU'ELLE NE FAIT PAS, ET POURQUOI. Elle ne détecte pas « ce geste s'est répété, il mérite
un skill » : cette inférence demande une trace des gestes de DEV que le dépôt n'a pas encore
(`/skill-forge §4` le dit : « l'équivalent `RunOutcome` du runtime n'existe pas encore »).
Prétendre la mesurer produirait un compteur qui a l'air d'un fait — le défaut que WAMA traque
partout ailleurs. Le jour où cette trace existera, c'est ICI qu'elle s'ajoutera.

  python manage.py check_skills            # rapport
  python manage.py check_skills --strict   # sortie 1 s'il reste un défaut FRANC
"""
import datetime
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

#: Même glob que `check_docs` — un seul endroit sait où vivent les skills.
SKILLS_GLOB = '.claude/skills/*/SKILL.md'

#: Marque de candidature posée par `/skill-forge §3`. La date est capturée pour l'âge.
CANDIDAT = re.compile(r'⚠\s*CANDIDAT\s*\(n=1,\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*\)')

#: Marque de promotion, telle qu'écrite par `/renommage-api` : `PROMU (n=2 : …)`.
PROMU = re.compile(r'PROMU\s*\(n=(\d+)')

#: Ce qui fait qu'une `description` porte un DÉCLENCHEUR et pas seulement un objet.
#:
#: ⚠ CALIBRÉ SUR LE CORPUS RÉEL, après un FAUX POSITIF de ma première rédaction. J'avais
#: énuméré des préfixes littéraux (`utiliser quand`, `utiliser en`, `utiliser dès`…) et le
#: contrôle a accusé `/conformite`, dont la description dit pourtant « **Utiliser après** un
#: palier de portage ». Mesure faite ensuite sur les 14 skills : **tous** contiennent
#: « utiliser » ET « quand ». La convention est universelle ; c'était l'instrument qui ratait.
#: *Un détecteur qui manque des correspondances est pire qu'aucun détecteur — il rend un
#: chiffre.* (Même famille que le biais de `rtk grep` documenté dans `/reprise`.)
#:
#: Le verbe seul suffit donc, et il est le bon marqueur : c'est lui qui introduit la clause
#: d'emploi dans TOUTES les descriptions du dépôt. « quand » seul pourrait apparaître par
#: hasard dans la description d'un objet.
#:
#: ⚠ Ce contrôle passe à 14/14 aujourd'hui, et ce n'est PAS une raison de le retirer : c'est un
#: CLIQUET sur une règle écrite (`/skill-forge §5.2`), et l'écrivain de skills est justement
#: automatique. Il garde le corpus À VENIR, pas le corpus actuel.
DECLENCHEURS = ('utiliser',)

#: Un candidat plus vieux que ça n'a jamais rencontré sa 2ᵉ occurrence : `/skill-forge §4`
#: demande de le SIGNALER (fusion ou retrait), jamais de le supprimer.
JOURS_DORMANT = 60


def _frontmatter(texte):
    """`(métadonnées, corps)`. Sans PyYAML : seules des clés plates nous intéressent."""
    if not texte.startswith('---'):
        return {}, texte
    fin = texte.find('\n---', 3)
    if fin == -1:
        return {}, texte
    meta = {}
    for ligne in texte[3:fin].splitlines():
        cle, sep, valeur = ligne.partition(':')
        if sep:
            meta[cle.strip()] = valeur.strip()
    return meta, texte[fin + 4:]


class Command(BaseCommand):
    help = "Santé du corpus de skills : candidats dormants, déclencheurs absents, frontmatter."

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true',
                            help="Sortie 1 s'il reste un défaut FRANC (frontmatter/déclencheur).")

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        aujourd_hui = datetime.date.today()
        fichiers = sorted(base.glob(SKILLS_GLOB))

        candidats, dormants, sans_declencheur, frontmatter_casse, promus = [], [], [], [], []

        for p in fichiers:
            nom = p.parent.name
            try:
                texte = p.read_text(encoding='utf-8')
            except OSError as e:
                frontmatter_casse.append((nom, f'illisible : {e}'))
                continue

            meta, corps = _frontmatter(texte)
            description = meta.get('description', '')

            if not meta.get('name'):
                frontmatter_casse.append((nom, 'clé `name` absente'))
            if not description:
                frontmatter_casse.append((nom, 'clé `description` absente'))
            elif not any(d in description.lower() for d in DECLENCHEURS):
                # §5.2 : « un skill que rien ne déclenche n'existe pas ».
                sans_declencheur.append(nom)

            m = CANDIDAT.search(corps)
            if m:
                try:
                    pose = datetime.date.fromisoformat(m.group(1))
                    age = (aujourd_hui - pose).days
                except ValueError:
                    pose, age = None, None
                candidats.append((nom, m.group(1), age))
                if age is not None and age > JOURS_DORMANT:
                    dormants.append((nom, m.group(1), age))

            mp = PROMU.search(description) or PROMU.search(corps)
            if mp:
                promus.append((nom, mp.group(1)))

        w = self.stdout.write
        w('')
        w('=' * 84)
        w(f"SANTÉ DES SKILLS  ({len(fichiers)} skill(s) dans {SKILLS_GLOB})")
        w('=' * 84)
        w('')

        if frontmatter_casse:
            w(self.style.ERROR(f"FRONTMATTER INCOMPLET ({len(frontmatter_casse)}) — "
                               f"invisible à la sélection d'un agent :"))
            for nom, quoi in frontmatter_casse:
                w(f"  {nom:18} {quoi}")
            w('')

        if sans_declencheur:
            w(self.style.WARNING(
                f"SANS DÉCLENCHEUR ({len(sans_declencheur)}) — la description dit CE QUE c'est, "
                f"pas QUAND l'employer (/skill-forge §5.2) :"))
            for nom in sans_declencheur:
                w(f"  {nom}")
            w('')

        if candidats:
            w(f"CANDIDATS n=1 ({len(candidats)}) — distillés d'une résolution unique, "
              f"non confrontés à une 2ᵉ occurrence :")
            for nom, date, age in candidats:
                suffixe = f"{age} j" if age is not None else 'date illisible'
                w(f"  {nom:18} posé le {date}  ({suffixe})")
            w('')

        if dormants:
            w(self.style.WARNING(
                f"CANDIDATS DORMANTS ({len(dormants)}, > {JOURS_DORMANT} j) — /skill-forge §4 : "
                f"candidats à la FUSION ou au RETRAIT. À SIGNALER, jamais à supprimer seul :"))
            for nom, date, age in dormants:
                w(f"  {nom:18} {age} j sans 2ᵉ occurrence (posé le {date})")
            w('')

        if promus:
            w(f"PROMUS ({len(promus)}) — la 2ᵉ occurrence a validé le geste :")
            for nom, n in promus:
                w(f"  {nom:18} n={n}")
            w('')

        francs = len(frontmatter_casse) + len(sans_declencheur)
        w('-' * 84)
        w(f"Bilan : {francs} défaut(s) franc(s) · {len(candidats)} candidat(s) "
          f"(dont {len(dormants)} dormant(s)) · {len(promus)} promu(s) sur {len(fichiers)}.")
        if not francs:
            w(self.style.SUCCESS("Aucun défaut franc."))
        w('')
        w("⚠ Ce contrôle ne dit PAS si un geste répété mérite un skill : le dépôt n'a pas encore")
        w("  de trace des gestes de dev (/skill-forge §4). Il dit l'état de ce qui EXISTE.")

        if options['strict'] and francs:
            raise SystemExit(1)
