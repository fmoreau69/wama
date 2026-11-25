# Construit la page WAMA du document de travail « Licences et dépôt de WAMA » (menu « Présentations & annexes »
# › Rapports, `wama.common.reports.REPORTS`) — le pendant rédigé de la présentation `licensing/`, écrit pour une
# discussion juridique. Les FAITS viennent de l'audit des licences (`license_audit` : inventaire, familles,
# traversée par app, dépendances lues), jamais recopiés à la main ; la POLITIQUE et les décisions sont celles de
# `docs/construction/exploitation/LICENSING.md`. Le texte qui les relie est écrit ici.
#
# ⚠ Aucun média d'utilisateur n'est NOMMÉ (le dépôt est public) : ils sont comptés, c'est tout.
#
# Usage (racine du dépôt) — lit la base, n'écrit que le gabarit :
#     python manage.py shell < scripts/reports/build_licensing_report.py
import datetime as dt
import sys
from collections import Counter, defaultdict
from pathlib import Path

from django.urls import reverse

from wama.common.services import license_audit as audit

HERE = Path('scripts/reports')
sys.path.insert(0, str(HERE))
from shell_page import date_fr, esc, fill_shell, nb  # noqa: E402

OUT = Path('wama/templates/includes/wama_rapport_licensing.html')

# ── Les mesures ─────────────────────────────────────────────────────────────────────────────
lines = audit.inventaire()
facts = audit.briefing(lines)
apps = audit.par_app(lines)
outside = audit.transitives()
family = facts['family']
REG = audit.REGISTRES


def plural(n, one, many):
    return f'{nb(n)} {one if n == 1 else many}'


def short(name):
    """Le nom d'un modèle sans son slogan de catalogue (« MusicGen Medium — best quality… »)."""
    return str(name).split(' — ')[0].strip()


def table(headers, rows):
    head = ''.join(f'<th>{h}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows)
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def named(items, limit=14):
    """Les éléments citables d'un groupe, dédoublonnés, et le compte de ce qui n'est pas nommé."""
    names = []
    for registry in ('library', 'service', 'model'):          # ce que WAMA importe d'abord
        for line in items:
            if line['registre'] == registry and short(line['nom']) not in names:
                names.append(short(line['nom']))
    shown = ', '.join(esc(n) for n in names[:limit])
    if len(names) > limit:
        shown += f' et {len(names) - limit} autres'
    media = sum(1 for line in items if line['registre'] == 'media')
    if media:
        shown += (' ; ' if shown else '') + plural(media, 'média', 'médias')
    return shown or '—'


def by_licence(rank):
    """Les lignes d'une famille, groupées par licence — `[(identifiant, lignes)]`, la plus fournie d'abord."""
    groups = defaultdict(list)
    for line in lines:
        if line['q']['rang'] == rank:
            groups[line['q']['id'] or 'non établie'].append(line)
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def registries_of(items):
    count = Counter(line['registre'] for line in items)
    return ', '.join(plural(n, REG[r][:-1].lower(), REG[r].lower()) for r, n in count.most_common())


def family_chart():
    """Une barre par famille, de la plus permissive à l'interdite ; en couleur, celles qui restreignent."""
    rows, top = facts['families'], max(f['count'] for f in facts['families']) or 1
    left, width, step = 220, 560, 34
    parts = [f'<svg viewBox="0 0 900 {len(rows) * step + 8}" role="img" aria-label="Éléments par famille de '
             f'licence" style="width:100%;height:auto;font-family:var(--sans)">']
    for i, f in enumerate(rows):
        y = 8 + i * step
        w = max(2, f['count'] / top * width)
        tone = 'var(--accent)' if f['rank'] >= audit.NON_COMMERCIAL else 'var(--muted-bar)'
        parts.append(
            f'<text x="{left - 12}" y="{y + 15}" text-anchor="end" style="fill:var(--ink);font-size:14px">'
            f'{esc(f["label"])}</text>'
            f'<rect x="{left}" y="{y}" width="{w:.1f}" height="20" rx="3" style="fill:{tone}"/>'
            f'<text x="{left + w + 10:.1f}" y="{y + 15}" style="fill:var(--ink-soft);font-size:14px">'
            f'{nb(f["count"])}</text>')
    parts.append('</svg>')
    return ''.join(parts)


family_rows = [(f'<strong>{esc(f["label"])}</strong>', esc(f['explanation']), nb(f['count']),
                *(nb(f['registries'][r]) for r in REG)) for f in facts['families']]

agpl_libraries = ', '.join(esc(n) for n in facts['agpl']['libraries']) or '—'
strong_rows = [(f'<code>{esc(ident)}</code>', registries_of(items), named(items, limit=6))
               for ident, items in by_licence(audit.COPYLEFT_FORT)]
nc_rows = [(f'<code>{esc(ident)}</code>', registries_of(items), named(items))
           for ident, items in by_licence(audit.NON_COMMERCIAL)]
forbidden_rows = [(f'<code>{esc(ident)}</code>', named(items)) for ident, items in by_licence(audit.INTERDITE)]
qualify_rows = [(f'<code>{esc(ident)}</code>', registries_of(items), named(items))
                for ident, items in by_licence(audit.A_QUALIFIER)]
unknown = [line for line in lines if line['q']['rang'] == audit.INCONNUE]

label_of = {a['key']: a['label'] for a in facts['apps']}
app_rows = []
for a in apps:
    worst = a['pire']
    heavy = [e for e in a['licences'] if e['q']['rang'] >= audit.COPYLEFT_FORT]
    carried = ' ; '.join(f'<code>{esc(e["id"])}</code> ×{e["n"]} ({", ".join(esc(short(x)) for x in e["exemples"])}'
                         f'{"…" if e["n"] > len(e["exemples"]) else ""})' for e in heavy) or '—'
    app_rows.append((f'<strong>{esc(label_of.get(a["app"], a["app"]))}</strong>',
                     esc(worst['famille']) if worst else '—', carried, nb(a['requires'])))

outside_families = ', '.join(f'{esc(name.lower())} {nb(n)}' for name, n in
                             sorted(outside['families'].items(), key=lambda kv: -kv[1]))
outside_strong = ', '.join(esc(e['nom']) for e in outside['exceptions']
                           if e['q']['rang'] == audit.COPYLEFT_FORT) or 'aucune'

URL = {
    'slides': reverse('licensing'),
    'licences': reverse('common:licenses_catalog'),
    'scene': reverse('common:scene', args=['licenses']),
    'models_scene': reverse('common:scene', args=['models']),
    'models': reverse('model_manager:index'),
    'libraries': reverse('model_manager:libraries_catalog'),
    'sources': reverse('common:sources_catalog'),
    'policy': reverse('common:doc_read', args=['licensing']),
}

body = f'''
<p>Ce document prépare une discussion juridique sur deux sujets liés : la <strong>licence</strong> sous laquelle
WAMA est publié, et le <strong>dépôt</strong> du logiciel. Il rassemble ce que WAMA mesure lui-même — chaque
modèle, chaque librairie, chaque média y porte sa licence — et ce que disent les textes, lus par un ingénieur.
Les points marqués « à confirmer » sont ceux où l'interprétation appartient au droit ; ils sont repris à la fin,
dans la liste des questions à trancher. Une <a href="{URL['slides']}">présentation en diapositives</a> en donne
la version courte.</p>

<h2>En bref</h2>
<ul>
<li>WAMA est publié sous <strong>GNU AGPL-3.0</strong>. Cette licence n'est pas « non commerciale » : elle
permet tout usage, commercial compris, et oblige à partager les modifications — y compris quand le logiciel est
offert comme un service en ligne.</li>
<li>Elle ne relève pas d'une préférence. WAMA utilise {plural(len(facts['agpl']['libraries']), 'librairie', 'librairies')}
et {plural(facts['agpl']['models'], 'modèle', 'modèles')} sous AGPL-3.0 ; leur licence veut que l'ensemble soit
distribué sous AGPL, et interdit d'y ajouter une restriction.</li>
<li>Une licence <strong>non commerciale</strong> ne gêne pas le travail de recherche. Elle compte à trois
endroits : ce qu'on fait des <em>résultats</em>, ce qu'on <em>redistribue</em>, et ce qu'on pourrait un jour
<em>valoriser</em>.</li>
<li>Passer WAMA lui-même sous une licence <strong>Creative Commons non commerciale</strong> n'est ni possible
sans retirer des composants essentiels, ni utile : le titulaire des droits dispose déjà de ce qu'elle
apporterait.</li>
<li>Les <strong>droits d'exploitation</strong> du logiciel appartiennent à l'université, la
<strong>paternité</strong> à son auteur. Le choix de licence doit donc être entériné par l'établissement.</li>
<li>Le <strong>dépôt</strong> commence par la déclaration du logiciel à l'établissement ; viennent ensuite
l'archive ouverte, le dépôt probatoire et, pour le nom, la marque.</li>
</ul>

<h2>Trois objets, trois régimes</h2>
<p>La plupart des malentendus sur « la licence de WAMA » viennent de ce qu'on parle de trois choses à la fois.</p>
<p><strong>Le code de WAMA</strong> — ce qui est écrit au laboratoire et publié dans le dépôt. Sa licence est
choisie par le titulaire des droits : c'est l'AGPL-3.0, portée par le fichier <code>LICENSE</code>, et le fichier
<code>COPYRIGHT</code> nomme le titulaire et l'auteur.</p>
<p><strong>Ce que WAMA embarque ou utilise</strong> — des librairies, des modèles d'intelligence artificielle
(leurs « poids »), des médias. Chacun garde la licence que son éditeur lui a donnée. WAMA ne les relicencie pas :
il doit les respecter, et c'est pour cela qu'il les inventorie.</p>
<p><strong>Ce que WAMA produit</strong> — une transcription, une image, une voix, une vidéo anonymisée. Un
résultat n'est pas couvert par la licence du code : il a traversé les licences des modèles qui l'ont produit, et
ce sont elles qui disent ce qu'on peut en faire.</p>
<p>La licence du code ne règle donc ni les modèles ni les résultats, et une clause attachée à un modèle ne
change pas la licence du code.</p>

<h2>Qui détient quoi</h2>
<p>WAMA est écrit par un agent public dans l'exercice de ses fonctions. Le droit d'auteur français se dédouble
alors, et ce partage commande la suite : qui choisit la licence, qui signe un dépôt, qui est nommé.</p>
{table(('Ce qui est détenu', 'Par qui', 'Ce que cela veut dire ici', 'Texte'), (
    ("<strong>Droits patrimoniaux</strong> : reproduire, adapter, distribuer — donc choisir la licence",
     "l'Université Gustave Eiffel",
     "le choix de l'AGPL-3.0 est une proposition d'ingénierie tant que l'établissement ne l'a pas entériné ; "
     "c'est lui qui signerait un dépôt probatoire ou une cession",
     "Code de la propriété intellectuelle, art. L113-9, al. 1 et 3"),
    ("<strong>Droit moral</strong>, dont la paternité", "l'auteur, Fabien Moreau",
     "être nommé comme auteur, y compris dans une version exploitée par un tiers ; inaliénable. Pour un "
     "logiciel, les autres attributs sont réduits : pas de droit de retrait, opposition à la modification "
     "très encadrée",
     "CPI, art. L121-1 et L121-7"),
    ("<strong>Intéressement</strong> en cas de valorisation", "partagé",
     "50 % de la base (produits hors taxes perçus par la personne publique, moins les frais directs, "
     "pondérés par la contribution de l'agent) jusqu'à un plafond de traitement, 25 % au-delà ; versé "
     "chaque année, y compris après le départ de l'agent",
     "Code de la recherche, art. D532-2 à D532-6"),
))}
<p>Une disposition mérite d'être connue : « lorsque la personne publique décide de ne pas procéder à la
valorisation de la création […], les agents […] peuvent en disposer librement, dans les conditions prévues par
une convention conclue avec cette personne publique » (art. D532-2, dernier alinéa). Déclarer le logiciel à
l'établissement est ce qui déclenche cet arbitrage : la déclaration ouvre les options, elle n'en ferme aucune.</p>
<p>Trois points restent à confirmer. Le troisième alinéa de l'article L113-9 étend la dévolution « aux agents de
l'Etat, des collectivités publiques et des établissements publics à caractère administratif » : une université
est un établissement public à caractère scientifique, culturel et professionnel — relève-t-elle de cet alinéa ?
C'est la lecture que pratiquent les établissements ; elle mérite d'être confirmée. Ensuite, l'article vise « les logiciels et leur documentation », et le code
définit le logiciel « y compris le matériel de conception préparatoire » (art. L112-2, 13°) : les documents de
conception et de vision de WAMA, écrits en marge du code, suivent-ils ce régime ou celui, plus favorable à
l'agent, des autres œuvres (art. L111-1) ? Enfin, tant que l'historique du dépôt ne compte qu'un auteur — c'est
le cas —, la titularité est simple ; elle cessera de l'être à la première contribution externe.</p>

<h2>La licence de WAMA : AGPL-3.0</h2>
<p>L'AGPL est une licence libre à réciprocité. Trois choses la résument.</p>
<p><strong>Ce qu'elle permet.</strong> Utiliser le logiciel pour tout usage, commercial compris ; l'étudier, le
modifier, le redistribuer. Rien dans l'AGPL ne distingue un laboratoire d'une entreprise.</p>
<p><strong>Ce qu'elle oblige.</strong> Celui qui distribue une version modifiée la distribue sous la même
licence, sources comprises (art. 5). Et celui qui la fait fonctionner comme un service en réseau doit offrir
à ses utilisateurs le moyen d'en obtenir les sources (art. 13) : c'est ce qui distingue l'AGPL de la GPL, et ce
qui la rend adaptée à une application web.</p>
<p><strong>Ce qu'elle n'empêche pas.</strong> Qu'un tiers installe WAMA et vende un service fondé dessus, à
condition de publier ses sources. Ni que le titulaire des droits, qui n'est pas lié par sa propre licence,
concède en parallèle le même code sous une licence propriétaire : c'est la « double licence », un modèle courant.</p>
<p><strong>Pourquoi celle-là.</strong> Parce que WAMA utilise déjà du code sous AGPL. L'inventaire mesure
aujourd'hui {plural(len(facts['agpl']['libraries']), 'librairie', 'librairies')} sous AGPL-3.0
({agpl_libraries}) et {plural(facts['agpl']['models'], 'modèle', 'modèles')} de vision publiés sous la même
licence. Selon la lecture de leurs éditeurs et de la Free Software Foundation, un programme qui importe une
librairie sous AGPL forme avec elle un ensemble qui doit être distribué « as a whole, under this License »
(art. 5), sans qu'on puisse « impose any further restrictions » (art. 10). Deux conséquences :</p>
<ul>
<li>une licence <em>plus permissive</em> pour WAMA (MIT, Apache) supposerait de retirer ces composants, qui
portent la détection dans plusieurs apps ;</li>
<li>une licence <em>plus restrictive</em> — non commerciale, par exemple — est exclue par la leur.</li>
</ul>
<p>C'est aussi de là que vient, pour WAMA, l'obligation de l'article 13 : servi à des utilisateurs distants, il
doit leur offrir un lien vers ses sources. Ce lien n'est pas encore dans l'interface ; il est dû dès que WAMA
est ouvert au-delà du poste de développement.</p>
{table(('Licence à réciprocité forte', 'Où', 'Éléments'), strong_rows)}
<p>À confirmer : que l'import d'une librairie fasse, en droit français, de l'ensemble une œuvre dérivée au sens
de la licence — c'est la lecture dominante, pas une décision de justice ; et que les poids d'un modèle, qui ne
sont pas dans le dépôt mais téléchargés à l'installation, relèvent de la même analyse que le code.</p>

<h2>Le non-commercial : où est le problème</h2>
<p>Une licence non commerciale autorise la recherche et l'enseignement : c'est exactement l'usage du
laboratoire. Elle n'est donc pas un obstacle au travail quotidien, et WAMA en utilise sciemment. Elle pèse
ailleurs, à trois endroits.</p>
<p><strong>Sur les résultats.</strong> Ce qu'un modèle non commercial a produit reste borné à un usage non
commercial : une publication, un cours, une expérimentation, oui ; un livrable vendu, une prestation, non. La
frontière n'est pas toujours nette. Creative Commons définit le non-commercial comme ce qui n'est pas
« primarily intended for or directed towards commercial advantage or monetary compensation » : c'est l'usage
qui compte, pas la nature de celui qui s'en sert. Une recherche menée avec un partenaire industriel, ou financée
par un contrat, est le cas à faire trancher. Les licences ne disent d'ailleurs pas toutes la même chose :
certaines laissent les sorties libres et ne bornent que le modèle.</p>
<p><strong>Sur la redistribution.</strong> Du code sous licence non commerciale ne peut pas être distribué
mêlé à du code AGPL, pour la raison donnée plus haut. WAMA en utilise un — un moteur de restauration de
visages — et le tient hors du dépôt : il est téléchargé à l'installation, jamais versionné. Cette séparation
doit tenir dans toute distribution future.</p>
<p><strong>Sur une valorisation.</strong> Si l'établissement voulait un jour exploiter WAMA commercialement,
chaque modèle non commercial serait à remplacer par un équivalent libre, ou à licencier auprès de son éditeur.
L'inventaire rend ce travail visible ; il ne le supprime pas.</p>
<p>L'inventaire compte aujourd'hui {plural(family['non_commercial']['count'], 'élément non commercial', 'éléments non commerciaux')} :</p>
{table(('Licence', 'Où', 'Éléments'), nc_rows)}
<p>Un cas est plus strict que le non-commercial : une licence qui <strong>exclut le territoire</strong>. Elle ne
concède aucun droit dans l'Union européenne, recherche comprise. WAMA la classe au-dessus de tout le reste :</p>
{table(('Licence', 'Éléments'), forbidden_rows) if forbidden_rows else '<p>Aucun élément dans ce cas aujourd’hui.</p>'}
<p>La décision de retirer ou de désactiver ce modèle est en attente ; elle ne demande pas d'interprétation.</p>

<h2>Faut-il passer WAMA en Creative Commons non commerciale ?</h2>
<p>La question est légitime : si l'on veut que WAMA serve la recherche et pas un concurrent, pourquoi ne pas
l'écrire dans la licence ? Cinq raisons conduisent à répondre non.</p>
<ol>
<li><strong>Les licences Creative Commons ne sont pas faites pour le logiciel.</strong> Creative Commons l'écrit
elle-même : « We recommend against using Creative Commons licenses for software. » Elle renvoie aux licences
de logiciel libres ou open source, et donne ses raisons : ses licences ne disent rien de la distribution du
code source, rien des brevets, et ne sont pas compatibles avec les grandes licences de logiciel.</li>
<li><strong>Elle serait incompatible avec ce que WAMA utilise.</strong> Une clause non commerciale est une
restriction supplémentaire, que l'AGPL des composants liés interdit (art. 7 et 10). Il faudrait retirer ces
composants, ou acheter à leurs éditeurs une licence commerciale — pour publier un logiciel non commercial.</li>
<li><strong>WAMA ne serait plus un logiciel libre.</strong> Interdire un champ d'usage sort de la définition du
logiciel libre comme de l'open source. Or le Code des relations entre le public et l'administration fixe les
licences sous lesquelles une administration peut publier un logiciel (art. D323-2-1) : des licences
« permissives » (BSD, Apache, CeCILL-B, MIT) et des licences « avec obligation de réciprocité » (Mozilla
Public License, GNU General Public License, CeCILL, European Union Public License, Eclipse Public License).
La liste détaillée, publiée sur data.gouv.fr comme l'article le prévoit, nomme la GNU Affero General Public
License v3.0 — celle de WAMA — et ne compte aucune licence Creative Commons pour le logiciel. Toute autre
licence demande une homologation, prononcée par décision du Premier ministre (art. D323-2-2). <em>À
confirmer : l'application de ce régime à un établissement d'enseignement supérieur et de recherche — la page
officielle précise que l'obligation ne vaut que lorsque l'administration peut établir elle-même la
licence.</em></li>
<li><strong>Elle n'apporterait rien au titulaire.</strong> L'université peut déjà concéder une licence
commerciale à qui en veut une. Et l'AGPL empêche déjà qu'un tiers reprenne WAMA dans un produit fermé. Ce
qu'une clause non commerciale ajouterait, c'est d'interdire à un tiers d'offrir WAMA en service <em>même en
publiant ses sources</em> — au prix d'écarter les partenaires dont l'activité est en partie commerciale, et
qui ne sauraient plus s'ils ont le droit de l'utiliser.</li>
<li><strong>Elle ne vaudrait que pour l'avenir.</strong> Les droits accordés par l'AGPL sont irrévocables tant
que ses conditions sont respectées (art. 2) : les versions déjà publiées resteraient utilisables sous AGPL.</li>
</ol>
<p>Si l'objectif est de <em>réserver</em> une exploitation commerciale à l'établissement, le chemin est connu et
ne demande pas de changer de licence : garder l'AGPL, garder un seul titulaire des droits (un accord de
contribution avant toute contribution externe), et proposer une licence commerciale à côté. Le droit français
offre aussi une licence à réciprocité rédigée pour lui, CeCILL. Sa version 2.1 organise sa compatibilité
(art. 5.3.4) : du code sous CeCILL peut être inclus dans un code sous GNU GPL, GNU Affero GPL ou EUPL,
l'ensemble étant alors distribué sous cette licence-là. WAMA resterait donc régi par l'AGPL, du fait des
composants liés. <em>À confirmer : l'intérêt d'une telle option pour l'établissement.</em></p>

<h2>Ce qu'un résultat traverse, app par app</h2>
<p>Au moment de publier un résultat, la question utile est : quelle est la licence la plus contraignante de ce
que l'app a utilisé ? WAMA la calcule depuis la composition que chaque app déclare. « Inconnue » signifie qu'au
moins un élément requis n'a pas encore de licence établie : elle est classée plus contraignante que le
non-commercial, parce qu'une licence qu'on n'a pas lue ne permet rien.</p>
{table(('App', 'La plus contraignante', 'Ce qui pèse (réciprocité forte et au-delà)', 'Éléments requis'), app_rows)}
<p>Ce tableau dit ce que l'app <em>peut</em> traverser, pas ce qu'un résultat donné a traversé : cela dépend du
modèle choisi pour le produire. Une transcription faite avec un modèle sous licence permissive n'hérite pas des
contraintes d'un autre modèle de la même app.</p>

<h2>L'état de l'inventaire</h2>
<p>WAMA tient {nb(facts['total'])} éléments sous licence, dont {nb(facts['known'])} à la licence établie. Rien
n'est saisi dans une table à part : la page des licences lit les registres des modèles, des librairies, des
médias et des services distants à chaque affichage.</p>
<figure class="chart"><figcaption><strong>Éléments par famille de licence</strong>
<span>De la plus permissive à l'interdite. En couleur : les familles qui restreignent l'usage ou demandent une
lecture.</span></figcaption>{family_chart()}</figure>
{table(('Famille', 'Ce qu’elle veut dire', 'Total', *REG.values()), family_rows)}
<p><strong>À qualifier</strong> — des licences « maison », à lire une par une :</p>
{table(('Licence', 'Où', 'Éléments'), qualify_rows)}
<p><strong>Inconnues</strong> — {registries_of(unknown)}. Les médias sont des fichiers que leur propriétaire doit
renseigner dans la médiathèque. Les modèles sont surtout des détecteurs de visages et de plaques dont l'origine
n'est pas établie. S'y ajoutent des librairies dont le dépôt amont reste à lire, et des services distants qui
ne publient pas de conditions d'usage. On ne déduit jamais une licence d'un nom de fichier.</p>
<p><strong>Les dépendances indirectes.</strong> Au-delà de ce que WAMA importe lui-même, l'environnement
d'exécution contient {nb(outside['total'])} distributions tirées par d'autres : {outside_families}. WAMA les lit
sans les inscrire, et ne signale que les exceptions ({nb(len(outside['exceptions']))}) — parmi elles les
bibliothèques propriétaires du constructeur de la carte graphique, et quelques licences à réciprocité forte
({outside_strong}). Cette lecture vaut tant que WAMA ne distribue que son code ; distribuer une image prête à
l'emploi, binaires compris, poserait une question de plus.</p>

<h2>Le dépôt de WAMA</h2>
<p><strong>Le premier geste est la déclaration.</strong> Les droits d'exploitation appartenant à l'université,
le dépôt commence par une déclaration de logiciel auprès de sa direction de la valorisation. C'est elle qui
entérine la licence, établit les titulaires et signe ce qui doit l'être. Trois dépôts viennent ensuite, qui ne
se concurrencent pas : chacun prouve autre chose.</p>
{table(('Dépôt', 'Ce qu’il apporte', 'Au nom de', 'Coût'), (
    ("<strong>HAL et Software Heritage</strong>",
     "l'archivage pérenne du code source, un identifiant citable (SWHID), une date publique. C'est le dépôt "
     "attendu d'un logiciel de recherche ; il se prépare par un fichier <code>codemeta.json</code> (nom, "
     "licence, auteurs) et un fichier des auteurs",
     "les auteurs, rattachés à leur établissement", "gratuit"),
    ("<strong>Agence pour la protection des programmes</strong>",
     "un dépôt probatoire : la preuve du contenu et de la date, avec un certificat horodaté (numéro IDDN), "
     "opposable en cas de litige ou lors d'une cession. Utile si une exploitation est envisagée",
     "l'établissement, titulaire des droits",
     "un abonnement annuel préalable (830 € HT par an pour la formule affichée), puis 195 € HT par dépôt "
     "standard — grille publique de l'agence"),
    ("<strong>Enveloppe Soleau</strong> (INPI, en ligne)",
     "la date d'un document — par exemple l'état des documents de conception à un moment donné. Ce n'est "
     "pas un titre de propriété",
     "le déposant",
     "15 € jusqu'à 50 Mo, puis 10 € par tranche de 50 Mo, pour cinq ans ; conservation prolongeable "
     "jusqu'à vingt ans"),
))}
<p>Côté WAMA, quatre choses sont à préparer : la liste des auteurs, la fiche <code>codemeta.json</code>, le lien
« Source » dans l'interface, et la mise au net de l'inventaire pour les éléments encore inconnus.</p>

<h2>Peut-on déposer l'idée ?</h2>
<p>Non, et c'est vrai partout : les idées sont de libre parcours. Le principe de WAMA — décrire une fois,
réutiliser partout, une interface qui se construit à partir de descriptions — n'est pas appropriable en tant
que tel. Ce qui se protège ou s'oppose est autour :</p>
<ul>
<li><strong>l'expression</strong> : le code, les documents de conception, l'interface sont protégés par le droit
d'auteur, sans formalité ;</li>
<li><strong>la date</strong> : elle se prouve, par un dépôt public horodaté ou une enveloppe Soleau ;</li>
<li><strong>la publication</strong> : publier la vision — un article, un dépôt dans une archive ouverte — crée
l'art antérieur, et empêche qu'un tiers se l'approprie ensuite ;</li>
<li><strong>le nom</strong> : « WAMA » peut se déposer comme marque, au nom de l'établissement, après une
recherche d'antériorité (190 € pour une classe en dépôt électronique, 40 € par classe supplémentaire, selon
l'INPI) ;</li>
<li><strong>le brevet</strong> n'est pas une voie : un logiciel « en tant que tel » n'est pas brevetable en
Europe.</li>
</ul>

<h2>Questions à trancher</h2>
<p><strong>Sur la licence</strong></p>
<ol>
<li>L'AGPL-3.0 est-elle entérinée par l'établissement ? Par quelle procédure, et qui signe ?</li>
<li>L'import d'une librairie sous AGPL fait-il de WAMA une œuvre dérivée, en droit français ? Si oui, WAMA
entier relève de l'AGPL, lien vers les sources compris.</li>
<li>Les poids d'un modèle, téléchargés à l'installation et jamais distribués avec WAMA, relèvent-ils de la
même analyse que le code ? Leur licence borne-t-elle seulement l'usage et les résultats ?</li>
<li>Une double licence — AGPL et licence commerciale — est-elle envisageable pour l'établissement ? Que
suppose-t-elle pour les composants d'autrui ?</li>
</ol>
<p><strong>Sur le non-commercial</strong></p>
<ol start="5">
<li>Recherche partenariale, contrat avec un industriel, prestation : où commence le « commercial » au sens des
licences des modèles ?</li>
<li>Un résultat produit par un modèle non commercial peut-il entrer dans un livrable de projet financé ? Dans
un jeu de données publié ?</li>
<li>Le modèle dont la licence exclut l'Union européenne : confirmer qu'il doit être retiré.</li>
<li>Deux services distants utilisés ne publient pas de conditions d'usage : que leur demander, et à qui ?</li>
</ol>
<p><strong>Sur les titulaires et le dépôt</strong></p>
<ol start="9">
<li>L'université, établissement public à caractère scientifique, culturel et professionnel, relève-t-elle bien
de la dévolution que l'article L113-9 étend aux « établissements publics à caractère administratif » ?</li>
<li>Les documents de conception et de vision suivent-ils le régime du logiciel (« et leur documentation »,
« matériel de conception préparatoire ») ou celui des autres œuvres de l'agent ?</li>
<li>Qui dépose, et au nom de qui : archive ouverte, dépôt probatoire, marque ?</li>
<li>Si l'établissement ne valorise pas : quelle convention permet à l'auteur d'en disposer ?</li>
<li>Avant toute contribution externe : quel accord de contribution, pour que l'établissement reste seul
titulaire ?</li>
<li>Le dépôt est public depuis plusieurs années : les points d'historique sont à aborder de vive voix (leurs
éléments sont réunis hors du dépôt).</li>
</ol>

<h2>Pour aller plus loin dans WAMA</h2>
<ul>
<li><a href="{URL['slides']}">La présentation « Licences et dépôt »</a> — la version courte de ce document, en
diapositives, avec la constellation intégrée.</li>
<li><a href="{URL['licences']}">La page des licences</a> — l'inventaire vivant : chaque élément, sa licence, sa
famille, et la traversée par app.</li>
<li><a href="{URL['scene']}">La constellation des licences</a> — les mêmes faits en trois dimensions : une étoile
par licence, les apps reliées à ce qu'elles traversent.</li>
<li><a href="{URL['models_scene']}">La constellation des modèles</a> et <a href="{URL['models']}">la gestion des
modèles</a> — le parc des modèles et la fiche de chacun.</li>
<li><a href="{URL['libraries']}">Les librairies</a> et <a href="{URL['sources']}">les sources externes</a> — ce
que WAMA importe, et les services distants avec leurs conditions d'usage.</li>
<li><a href="{URL['policy']}">La politique des licences</a> (<code>LICENSING.md</code>) — les décisions, le code
tiers embarqué, la marche à suivre pour le dépôt.</li>
</ul>

<h2>Textes cités</h2>
{table(('Texte', 'Ce qu’on en tire', 'Lecture'), (
    ("GNU Affero General Public License, version 3 — art. 2, 5, 7, 10, 13",
     "droits irrévocables ; licence de l'ensemble ; pas de restriction supplémentaire ; sources offertes aux "
     "utilisateurs d'un service en réseau",
     "relu sur le texte publié par la Free Software Foundation (le fichier <code>LICENSE</code> du dépôt)"),
    ("Code de la propriété intellectuelle — art. L111-1, L112-2 (13°), L113-9, L121-1, L121-7",
     "droits patrimoniaux à l'employeur, étendus aux agents publics ; logiciel « y compris le matériel de "
     "conception préparatoire » ; paternité à l'auteur ; droit moral réduit pour le logiciel",
     "relu sur le code consolidé, édition du 18 novembre 2026 ; leur application à l'établissement reste "
     "à confirmer"),
    ("Code de la recherche — art. D532-2 à D532-6 (décret n° 2023-1321 du 27 décembre 2023)",
     "prime d'intéressement ; libre disposition par convention si la personne publique ne valorise pas",
     "relu sur le code consolidé, édition du 24 novembre 2026"),
    ("Code des relations entre le public et l'administration — art. D323-2-1 et D323-2-2",
     "licences sous lesquelles une administration publie un logiciel ; homologation des autres",
     "relu sur le code consolidé, édition du 23 novembre 2026, et sur la liste publiée par data.gouv.fr ; "
     "son application à l'établissement reste à confirmer"),
    ("Creative Commons — licence BY-NC 4.0 (définition de « NonCommercial ») et foire aux questions (logiciel)",
     "le non-commercial se juge à l'usage ; les licences Creative Commons sont déconseillées pour le logiciel",
     "relus sur le site de Creative Commons, cités dans leur langue"),
    ("Licence CeCILL, version 2.1 — art. 5.3.4",
     "licence à réciprocité de droit français ; compatibilité avec GNU GPL, GNU Affero GPL et EUPL",
     "relue sur le texte publié par ses auteurs"),
    ("Agence pour la protection des programmes — grille tarifaire",
     "abonnement annuel préalable à tout dépôt ; dépôt standard à 195 € HT", "page de l'agence, relue ce jour"),
    ("INPI — enveloppe Soleau en ligne et dépôt de marque",
     "enveloppe : 15 € jusqu'à 50 Mo pour cinq ans ; marque : 190 € pour une classe, 40 € par classe "
     "supplémentaire",
     "pages de l'INPI publiées le 18 février 2025 et le 5 décembre 2024"),
))}
'''

page = fill_shell(
    title='Licences et dépôt de WAMA',
    kicker='Document de travail · licences · propriété intellectuelle',
    sub=f'Sous quelle licence publier, ce que permettent les licences traversées, comment déposer · généré le {date_fr(dt.date.today())}',
    comment=("  Document de travail « Licences et dépôt de WAMA » — GÉNÉRÉ par\n"
             "  `scripts/reports/build_licensing_report.py` depuis l'audit des licences (`license_audit` :\n"
             "  inventaire, familles, traversée par app, dépendances lues). Ne pas l'éditer à la main : relancer\n"
             "  le script. La politique et les décisions vivent dans LICENSING.md ; la version courte est la\n"
             "  présentation `licensing/` (`wama_licensing.html`). Même enveloppe que les autres rapports.\n"),
    foot=("Généré depuis l'audit des licences de WAMA (modèles, librairies, médias, services distants, "
          "composition déclarée des apps). Ce document prépare une discussion ; il ne vaut pas avis juridique. "
          "La politique et les décisions en attente sont dans LICENSING.md."),
    body=body)
OUT.write_text(page, encoding='utf-8')
print('written', OUT, len(page), 'bytes')
print('families', {f['key']: f['count'] for f in facts['families']}, '| agpl', facts['agpl'], '| forbidden',
      facts['forbidden'])
