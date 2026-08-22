"""
Synchronise l'arbre `OrgUnit` depuis l'annuaire SUPANN (`ou=structures`).

LE MAILLON QUI MANQUAIT. Mesuré le 2026-08-22 : l'authentification LDAP fonctionne depuis
longtemps ET la remontée SUPANN peuple bien le profil (`org_affiliations` de Fabien portait
ses trois codes), mais **`OrgUnit` était VIDE** — et rien dans le dépôt ne le peuplait.
`resolve_org_hierarchy` existait sans appelant depuis sa création. Conséquence concrète : le
niveau « RAG du labo » était refusé au clic (`_resoudre_unite` cherche un `OrgUnit` par code et
n'en trouvait aucun), alors que toutes les informations nécessaires étaient à portée.

Ce que fait la commande, en LECTURE SEULE côté annuaire :
  1. collecte les codes d'entité portés par les profils (ou ceux passés en argument) ;
  2. remonte la chaîne `supannCodeEntiteParent` jusqu'à la racine pour CHACUN ;
  3. crée/met à jour les `OrgUnit` correspondants, **parents d'abord**, puis rattache ;
  4. rafraîchit `org_entity_name` / `org_hierarchy` sur les profils concernés.

Idempotente : relancer ne crée rien de neuf et ne casse aucun rattachement existant.
Les unités saisies à la main (`source='manual'`) ne sont JAMAIS écrasées — l'annuaire est
autoritaire sur ce qu'il connaît, pas sur ce qu'un humain a ajouté à côté.
"""
from django.core.management.base import BaseCommand

# `supannTypeEntite` est propre à l'établissement (observé à l'UGE : « {EIFFEL}CR-LR »), il n'y
# a donc pas de table standard à appliquer. On classe sur des FRAGMENTS de code, et on retombe
# sur 'autre' sans bruit : le type ne sert qu'à l'AFFICHAGE — l'héritage RAG, lui, ne dépend que
# de `parent`. Se tromper de libellé est cosmétique ; se tromper de parent ne le serait pas.
_FRAGMENTS_TYPE = (
    ('EQ', 'equipe'), ('LR', 'labo'), ('LAB', 'labo'), ('UMR', 'labo'),
    ('DEP', 'departement'), ('DPT', 'departement'),
    ('SERV', 'service'), ('SV', 'service'), ('DIR', 'service'),
    ('UNIV', 'universite'), ('INST', 'institut'), ('CR', 'departement'),
)


def deviner_type(type_supann: str, code: str) -> str:
    """Type d'unité, best-effort. Le TYPE est cosmétique ; ne jamais bloquer une synchro dessus."""
    haystack = f'{type_supann or ""}|{code or ""}'.upper()
    for fragment, type_wama in _FRAGMENTS_TYPE:
        if fragment in haystack:
            return type_wama
    return 'autre'


class Command(BaseCommand):
    help = "Peuple l'arbre OrgUnit depuis ou=structures (SUPANN). Lecture seule côté LDAP."

    def add_arguments(self, parser):
        parser.add_argument('--code', action='append', default=[],
                            help='Code d\'entité à synchroniser (répétable). '
                                 'Par défaut : tous ceux portés par les profils.')
        parser.add_argument('--all', action='store_true',
                            help="Synchronise TOUTE la branche structures (612 entités à l'UGE) "
                                 "et non les seules chaînes utiles.")
        parser.add_argument('--dry-run', action='store_true',
                            help='Montre ce qui serait écrit, sans rien écrire.')

    def handle(self, *args, **options):
        from django.conf import settings

        from wama.accounts.models import UserProfile
        from wama.common.models import OrgUnit

        base = getattr(settings, 'LDAP_STRUCTURES_BASE_DN', None)
        if not base:
            self.stderr.write(self.style.ERROR(
                'LDAP_STRUCTURES_BASE_DN non configuré — rien à synchroniser.'))
            return

        dry = options['dry_run']
        codes = list(options['code'])
        if not codes and not options['all']:
            # Source par défaut : ce que l'annuaire a DÉJÀ écrit sur les profils. On ne
            # synchronise pas 612 entités pour en utiliser deux.
            vus = set()
            for prof in UserProfile.objects.all():
                vus.update(prof.org_affiliations or [])
                if prof.org_entity_code:
                    vus.add(prof.org_entity_code)
            codes = sorted(vus)
        if not codes and not options['all']:
            self.stdout.write('Aucun code d\'entité sur les profils — rien à faire. '
                              '(Les profils se peuplent à la connexion LDAP.)')
            return

        try:
            conn = self._connecter(settings)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Connexion LDAP impossible : {e}'))
            return

        fiches, introuvables = {}, []
        try:
            if options['all']:
                for dn, attrs in self._chercher(conn, base, '(supannCodeEntite=*)'):
                    fiche = self._fiche(attrs)
                    if fiche:
                        fiches[fiche['code']] = fiche
            else:
                for code in codes:
                    trouve = self._remonter(conn, base, code, fiches)
                    if not trouve:
                        introuvables.append(code)
        finally:
            try:
                conn.unbind_s()
            except Exception:
                pass

        self.stdout.write(f'{len(fiches)} entité(s) résolue(s) depuis l\'annuaire.')
        if introuvables:
            # On le DIT au lieu de l'avaler : un code présent sur un profil mais absent de
            # l'annuaire est une anomalie d'annuaire (vécu : « {EIFFEL}CFR - LESCOT », porté par
            # le profil de Fabien, n'existe pas dans ou=structures). Le taire ferait chercher
            # un bug dans WAMA.
            self.stdout.write(self.style.WARNING(
                f'{len(introuvables)} code(s) porté(s) par un profil mais ABSENT(S) de '
                f'l\'annuaire : {", ".join(repr(c) for c in introuvables)}'))

        if dry:
            for f in fiches.values():
                self.stdout.write(f"  [dry] {f['code']!r} — {f['nom']!r} "
                                  f"type={deviner_type(f['type'], f['code'])} "
                                  f"parent={f['parent'] or '—'}")
            return

        # ── Écriture en DEUX temps : les nœuds d'abord, les liens ensuite ────────────────
        # Un parent peut apparaître après son enfant dans le dict ; créer puis rattacher évite
        # d'avoir à trier topologiquement (et de boucler sur un cycle d'annuaire).
        crees = maj = 0
        for f in fiches.values():
            unite, cree = OrgUnit.objects.get_or_create(
                code=f['code'],
                defaults={'name': f['nom'], 'unit_type': deviner_type(f['type'], f['code']),
                          'source': 'ldap'})
            if cree:
                crees += 1
                continue
            if unite.source == 'manual':
                continue                       # saisie humaine : l'annuaire ne l'écrase pas
            champs = []
            if f['nom'] and unite.name != f['nom']:
                unite.name, _ = f['nom'], champs.append('name')
            t = deviner_type(f['type'], f['code'])
            if unite.unit_type != t:
                unite.unit_type, _ = t, champs.append('unit_type')
            if champs:
                unite.save(update_fields=champs)
                maj += 1

        liens = 0
        for f in fiches.values():
            if not f['parent']:
                continue
            unite = OrgUnit.objects.filter(code=f['code']).first()
            parent = OrgUnit.objects.filter(code=f['parent']).first()
            # `unite != parent` : une fiche d'annuaire qui se déclare son propre parent
            # produirait une boucle infinie dans `ancestors()` (garde à 20, mais autant ne pas
            # l'écrire du tout).
            if unite and parent and unite.parent_id != parent.id and unite != parent:
                unite.parent = parent
                unite.save(update_fields=['parent'])
                liens += 1

        self.stdout.write(self.style.SUCCESS(
            f'OrgUnit : {crees} créée(s), {maj} mise(s) à jour, {liens} rattachement(s).'))

        # ── Rafraîchit les profils : nom lisible + hiérarchie ────────────────────────────
        # Sans ça, il faudrait se reconnecter pour que `_apply_ldap_org` les remplisse — or
        # c'est précisément la synchro qui vient de rendre l'information disponible.
        touches = 0
        for prof in UserProfile.objects.select_related('user').all():
            code = prof.org_entity_code
            if not code:
                continue
            unite = OrgUnit.objects.filter(code=code).first()
            if not unite:
                continue
            hier = [{'code': u.code, 'name': u.name, 'type': u.unit_type}
                    for u in unite.ancestors()]
            if prof.org_entity_name != unite.name or prof.org_hierarchy != hier:
                prof.org_entity_name = unite.name
                prof.org_hierarchy = hier
                prof.save(update_fields=['org_entity_name', 'org_hierarchy'])
                touches += 1
        self.stdout.write(self.style.SUCCESS(f'Profils rafraîchis : {touches}.'))

    # ── Annuaire ────────────────────────────────────────────────────────────────────────
    def _connecter(self, settings):
        import ldap
        conn = ldap.initialize(settings.AUTH_LDAP_SERVER_URI)
        conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 10)
        conn.set_option(ldap.OPT_TIMEOUT, 15)
        bind_dn = getattr(settings, 'AUTH_LDAP_BIND_DN', '') or ''
        if bind_dn:
            conn.simple_bind_s(bind_dn, getattr(settings, 'AUTH_LDAP_BIND_PASSWORD', ''))
        else:
            conn.simple_bind_s()          # anonyme — suffisant à l'UGE (vérifié 2026-08-22)
        return conn

    _ATTRS = ['description', 'ou', 'supannTypeEntite',
              'supannCodeEntiteParent', 'supannCodeEntite']

    def _chercher(self, conn, base, filtre):
        import ldap
        return conn.search_s(base, ldap.SCOPE_SUBTREE, filtre, self._ATTRS)

    def _fiche(self, attrs):
        def val(cle):
            v = attrs.get(cle)
            return v[0].decode('utf-8', 'ignore') if v else ''
        code = val('supannCodeEntite')
        if not code:
            return None
        return {'code': code,
                # `description` d'abord, `ou` en repli, le code en dernier ressort : certaines
                # fiches héritées (branche {IFSTTAR}) n'ont pas de libellé du tout.
                'nom': val('description') or val('ou') or code,
                'type': val('supannTypeEntite'),
                'parent': val('supannCodeEntiteParent')}

    def _remonter(self, conn, base, code, fiches):
        """Remonte la chaîne parent d'un code et range chaque fiche. Rend False si introuvable."""
        import ldap.filter
        vu, courant, garde, trouve = set(), code, 0, False
        while courant and garde < 12:
            garde += 1
            if courant in fiches or courant in vu:
                break                       # déjà connu : la chaîne au-dessus l'est aussi
            vu.add(courant)
            res = self._chercher(
                conn, base, f'(supannCodeEntite={ldap.filter.escape_filter_chars(courant)})')
            if not res:
                break
            fiche = self._fiche(res[0][1])
            if not fiche:
                break
            fiches[fiche['code']] = fiche
            trouve = True
            courant = fiche['parent']
        return trouve
