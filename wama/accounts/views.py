import json
import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import ListView, View, DetailView, TemplateView
from django.views.generic.edit import CreateView, UpdateView
from django.views.decorators.http import require_POST
from functools import wraps

from .models import LoginForm, UserRegistrationForm, UserProfile
from ..common import external_sources, themes
from ..common.utils.secret_crypto import storage_available
from ..common.utils.volet import VOLET_AUCUN, volet

logger = logging.getLogger(__name__)


def admin_required(view_func):
    """Réserve une vue aux ADMINISTRATEURS (`is_admin` → `permissions.is_admin_tier`)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Vous devez être connecté.")
            return redirect('accounts:login')
        if not is_admin(request.user):
            messages.error(request, "Accès réservé aux administrateurs.")
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return wrapper


def is_admin(user):
    """Administrateur — LA définition (`permissions.is_admin_tier`, le niveau du profil ;
    décision de Fabien du 2026-10-21). Elle lisait le groupe hérité `admin` et le drapeau
    superutilisateur : une seconde définition, que rien n'accordait au niveau."""
    from wama.accounts.permissions import is_admin_tier
    return is_admin_tier(user)


def is_dev(user):
    """Développeur ou administrateur (`permissions.is_developer`, le niveau du profil) — elle
    lisait le groupe hérité `dev`."""
    from wama.accounts.permissions import is_developer
    return is_developer(user)


#: Le rôle tel que la page des utilisateurs le nomme (`admin` / `dev` / `user`), lu sur le niveau.
ROLE_OF_TIER = {'admin': 'admin', 'developpeur': 'dev', 'utilisateur': 'user'}
#: …et le niveau que pose un rôle choisi sur cette page (« Ajouter », « Rôle »).
TIER_OF_ROLE = {role: tier for tier, role in ROLE_OF_TIER.items()}


def get_user_role(user):
    """Le rôle principal d'un compte, DÉRIVÉ de son niveau (`permissions.user_tier`) — il lisait
    les groupes hérités `admin` / `dev` / `user`, retirés le 2026-10-21."""
    from wama.accounts.permissions import is_guest_account, user_tier
    if not user.is_authenticated or is_guest_account(user):
        return 'anonymous'
    return ROLE_OF_TIER.get(user_tier(user), 'user')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('anonymizer:upload')

    form = LoginForm(request, data=request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, "Successfully logged in!")
            # ⚠ `next` vient du CLIENT : validé avant redirection, sinon la page de login
            # devient un redirecteur ouvert (un lien forgé `?next=https://evil…` dépose
            # l'utilisateur ailleurs juste APRÈS qu'il s'est authentifié — le moment où il
            # fait le plus confiance à l'écran). Garde posée le 2026-08-31, en réparant le
            # fil `?next=` pour le QR d'appariement : les gabarits envoyaient `request.path`
            # (la page de login elle-même), aucun lien profond n'était donc honoré.
            from django.utils.http import url_has_allowed_host_and_scheme
            next_url = request.POST.get('next') or ''
            if not url_has_allowed_host_and_scheme(next_url,
                                                   allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
                next_url = ''
            return redirect(next_url or 'anonymizer:upload')
        elif not form.is_pending():
            # Un compte EN ATTENTE n'a pas fait d'erreur : le formulaire lui dit qu'il attend.
            messages.error(request, "Invalid credentials.")

    # Pages de COMPTE : aucun média, aucun paramètre d'app, aucune action de file — le volet
    # n'y portait que des cadres vides (WAMA_VOLETS §2, 17 pages / 51 cadres).
    return render(request, 'accounts/login_v2.html',
                  {'form': form, 'type_of_view': 'login', 'volet': VOLET_AUCUN})


def signup_view(request):
    form = UserRegistrationForm(request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            user = form.save()
            return render(request, 'accounts/signup_validation.html', {'volet': VOLET_AUCUN})

    return render(request, 'accounts/login.html',
                  {'form': form, 'type_of_view': 'register', 'volet': VOLET_AUCUN})


def logout_view(request):
    logout(request)
    return redirect('accounts:login')


class IndexView(ListView):
    template_name = 'anonymizer/index.html'
    queryset = User.objects.all()
    context_object_name = 'user_list'


class UserPage(DetailView):
    template_name = 'accounts/user_settings.html'
    queryset = User.objects.all()
    context_object_name = 'selected_user'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_edit'] = (self.request.user.pk == self.object.pk)
        context['volet'] = VOLET_AUCUN          # page de compte, cf. login_view
        return context


@method_decorator(login_required, name='dispatch')
class UserEdit(UpdateView):
    template_name = 'accounts/user_form.html'
    model = User
    fields = ["first_name", "last_name", "email"]

    def get_success_url(self):
        return reverse('anonymizer:upload')

    def get_object(self):
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['volet'] = VOLET_AUCUN          # formulaire de compte, cf. UserPage
        return context

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Apply dark theme styling to all form fields
        for field_name, field in form.fields.items():
            field.widget.attrs.update({
                'class': 'form-control bg-body text-body-emphasis border-secondary'
            })
            # Update labels to French
            if field_name == 'first_name':
                field.label = 'Prénom'
            elif field_name == 'last_name':
                field.label = 'Nom'
            elif field_name == 'email':
                field.label = 'Email'
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.object
        context['title'] = f'{user.first_name} {user.last_name}' if user.first_name else user.username
        context['subtitle'] = 'Modifier les informations du profil'
        return context


# `UserSettingsUpdate` (page `user/settings/edit/`) RETIRÉE le 2026-09-27 : elle éditait la table
# legacy `UserSettings` de l'anonymizer, que plus rien ne lisait — les réglages de l'anonymizer
# sont ceux de son volet (brique commune `user_settings`), comme dans les autres apps.


def login_form(request):
    """ Context processor ou fragment HTML selon usage """
    if not request.user.is_authenticated:
        return {"login_form": LoginForm()}
    return {}


# =============================================================================
# Profile Views
# =============================================================================

def _is_ldap_user(request):
    """Return True if the current session was authenticated via LDAPBackend."""
    backend = request.session.get('_auth_user_backend', '')
    return 'LDAPBackend' in backend


def _search_engine_options(user) -> list:
    """[{slug, label, usable, needs_key, usage}] — de quoi rendre le choix ET dire POURQUOI un
    moteur ne peut pas être choisi. Un select qui grise sans raison est un cul-de-sac."""
    try:
        from wama.common.search_engines import declared_engines, needs_key, usable_slugs
    except Exception:
        return []
    usable = set(usable_slugs(user))
    return [{
        'slug': s.key,
        'label': s.label,
        'usable': s.key in usable,
        'needs_key': needs_key(s.key),
        'usage': s.usage,
    } for s in declared_engines()]


@login_required
def profile_view(request):
    """Unified profile page: user info + preferred language + API token."""
    from rest_framework.authtoken.models import Token
    from wama.common.services.sharing import scope_choices
    from wama.common.tts.constants import LANGUAGE_CHOICES

    token_obj, _ = Token.objects.get_or_create(user=request.user)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    # Liaisons de canal (passerelle Discord/Tchap — ROADMAP §19). Import tardif et
    # défensif : la page de profil ne doit pas tomber si l'app passerelle est absente.
    try:
        from wama.gateway.models import ChannelLink
        liaisons = list(ChannelLink.objects.filter(user=request.user)
                        .exclude(confirmed_at__isnull=True).order_by('channel'))
    except Exception:
        liaisons = []

    return render(request, 'accounts/profile.html', {
        'token': token_obj.key,
        'profile': profile,
        'languages': LANGUAGE_CHOICES,
        # Le choix courant (`theme_choice`) vient du contexte de toute page.
        'theme_choices': themes.choices(),
        # `getattr` : un worker peut lire cette vue neuve avec un `themes` importé d'avant l'étape 7
        # (vécu le 2026-10-19 avec `Theme.logo` : des pages en 500 jusqu'au rechargement).
        'theme_generated_keys': [t.key for t in themes.THEMES if getattr(t, 'generated', False)],
        'theme_palettes': getattr(themes, 'palette_previews', list)(),
        'theme_accent': getattr(themes, 'theme_accent', lambda user: '')(request.user),
        # Thèmes de CHARTE (étape 7 voie 2) : ceux que le compte voit, et le choix tel que le
        # Profil le montre (`charter:<pk>` sous une charte).
        'theme_charters': getattr(themes, 'charter_choices', lambda user: [])(request.user),
        'theme_profile_choice': getattr(themes, 'profile_choice', themes.theme_choice)(request.user),
        # Les portées OFFERTES, à plat pour un `<select>` (`sharing.scope_choices`).
        'theme_scopes': scope_choices(request.user),
        # « Demander la promotion » d'un thème de charte : la route commune (§29 6a).
        'promotion_api': reverse('common:api_promotion_request'),
        'is_ldap': _is_ldap_user(request),
        'channel_links': liaisons,
        'rattachement': rattachement_institutionnel(profile),
        # Ses DERNIERS accès, refus compris : c'est lui qui sait si une ligne n'est pas de lui.
        'recent_access': recent_access(request.user),
        'cloud_policies': UserProfile.CLOUD_POLICIES,
        # Plafond d'hébergement : l'échelle et ses libellés ont UN domicile (`external_sources`).
        'cloud_hostings': [(level, external_sources.HOSTING_CEILING_LABELS[level])
                           for level in external_sources.HOSTING_SCALE],
        # Ce que le dernier cran fait des données, dit AVANT qu'on le choisisse (2026-10-12).
        'data_reuse_ceiling': external_sources.DATA_REUSE_CEILING,
        'data_reuse_warning': external_sources.DATA_REUSE_WARNING,
        'secret_storage_available': storage_available(),
        # Moteurs de recherche : l'inventaire vient du REGISTRE (sources `recherche` ayant un
        # adaptateur), jamais d'une liste écrite au gabarit — ajouter un moteur ne touche
        # donc ni cette vue ni la page.
        'search_engines': _search_engine_options(request.user),
        # 2026-09-15 (Fabien) : TOUT ce qui touche aux clés — jeton d'API, fournisseurs LLM,
        # connecteurs de la médiathèque — vit dans la section Paramètres du volet droit, pour ne
        # pas allonger la page. Médias et Actions n'y ont rien à montrer.
        'volet': volet(medias=False, actions=False),
    })


@login_required
def api_keys_list(request):
    """GET : fournisseurs LLM et présence d'une clé personnelle — jamais la clé elle-même."""
    from .api_keys import listing
    return JsonResponse({'providers': listing(request.user)})


@login_required
@require_POST
def api_key_save(request, slug):
    """POST {api_key} : enregistre (chiffrée) ou efface (vide) la clé personnelle d'un fournisseur."""
    # Toute source à clé personnelle, plus les seuls LLM (2026-09-26) : les moteurs de
    # recherche posent leur clé par le MÊME écran et la MÊME route.
    from .api_keys import forget_opened_models, is_keyed_source, store_key
    from .models import UserApiKey

    if not is_keyed_source(slug, request.user):
        return JsonResponse({'error': 'Fournisseur introuvable'}, status=404)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    api_key = (data.get('api_key') or '').strip()

    if not api_key:
        UserApiKey.objects.filter(user=request.user, source=slug).delete()
        forget_opened_models(slug)
        return JsonResponse({'success': True, 'has_key': False})
    # Le geste COMMUN aux deux écrans de clés (profil, page Sources externes) : longueur,
    # stockage chiffré disponible, enregistrement, lecture des modèles ouverts.
    row = (UserApiKey.objects.filter(user=request.user, source=slug).first()
           or UserApiKey(user=request.user, source=slug))
    result = store_key(row, api_key)
    return JsonResponse(result, status=result.pop('status'))


@login_required
@require_POST
def cloud_policy_update(request):
    """AJAX : enregistre l'usage des modèles cloud — le NIVEAU (100 % local par défaut) et,
    depuis le 2026-10-03, le second axe : PLAFOND d'hébergement et modèles facturés à l'usage
    au tirage automatique. Seuls les réglages PRÉSENTS dans la requête sont écrits ; un seul
    invalide refuse le tout (rien n'est enregistré à moitié)."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    values = {}
    if 'cloud_policy' in data:
        if data['cloud_policy'] not in dict(UserProfile.CLOUD_POLICIES):
            return JsonResponse({'error': f"Niveau invalide : '{data['cloud_policy']}'"}, status=400)
        values['cloud_policy'] = data['cloud_policy']
    if 'cloud_hosting_max' in data:
        if data['cloud_hosting_max'] not in external_sources.HOSTING_SCALE:
            return JsonResponse({'error': f"Hébergement invalide : '{data['cloud_hosting_max']}'"},
                                status=400)
        values['cloud_hosting_max'] = data['cloud_hosting_max']
    if 'cloud_metered_auto' in data:
        values['cloud_metered_auto'] = bool(data['cloud_metered_auto'])
    if not values:
        return JsonResponse({'error': 'Aucun réglage cloud dans la requête'}, status=400)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    for name, value in values.items():
        setattr(profile, name, value)
    profile.save(update_fields=list(values))
    return JsonResponse({'success': True, **values})


def recent_access(user, limit: int = 8) -> list:
    """Les derniers accès au compte de `user` — connexions, déconnexions et REFUS sur son nom —
    tels que le journal les garde (`AccessLog`, six mois). Montrés au profil : le titulaire est
    le seul à pouvoir dire « ce n'était pas moi »."""
    from django.db.models import Q

    from .models import AccessLog
    return list(AccessLog.objects.filter(Q(user=user) | Q(username__iexact=user.username))
                .order_by('-timestamp')[:limit])


def rattachement_institutionnel(profile):
    """L'appartenance organisationnelle du profil, RÉSOLUE contre l'arbre `OrgUnit`.

    Ces champs arrivent de l'annuaire (SUPANN, à chaque connexion — `accounts/ldap.py`) et
    n'étaient affichés NULLE PART : le profil de Fabien portait ses trois rattachements depuis
    des mois sans qu'on puisse les voir. Les montrer n'est pas cosmétique — c'est ce qui
    explique à l'utilisateur pourquoi le niveau « RAG du labo » lui est ouvert… ou refusé.

    Chaque rattachement est marqué RECONNU (une `OrgUnit` existe, donc le partage au labo
    fonctionne) ou INCONNU. Un code inconnu n'est pas forcément une erreur de WAMA : mesuré le
    2026-08-22, « {EIFFEL}CFR - LESCOT » est porté par le profil mais absent de `ou=structures`.
    Le dire évite de chercher un bug ici.
    """
    from wama.accounts.ldap import split_namespace
    from wama.common.models import OrgUnit

    codes = list(profile.org_affiliations or [])
    if profile.org_entity_code and profile.org_entity_code not in codes:
        codes.insert(0, profile.org_entity_code)
    connues = {u.code: u for u in OrgUnit.local().filter(code__in=codes)}

    def _readable(code, nom=''):
        """Libellé pour un humain : le nom de l'unité s'il en a un, sinon le code SANS son
        préfixe d'autorité SUPANN (`{IFSTTAR}LESCOT` → « LESCOT »). Le code brut reste
        affiché à côté — on ne le remplace pas, on cesse d'en faire le titre."""
        namespace, value = split_namespace(code)
        if nom and nom != code:
            return nom, namespace
        # Un code réduit à son seul préfixe (`{IFSTTAR}`, la racine de la chaîne) n'a pas
        # de valeur après le namespace : c'est le namespace qui EST le nom lisible.
        return (value or namespace or code), namespace

    rattachements = []
    for code in codes:
        unite = connues.get(code)
        label, namespace = _readable(code, unite.name if unite else '')
        rattachements.append({
            'code': code,
            'libelle': label,
            'autorite': namespace,          # l'annuaire émetteur du code, quand il est préfixé
            'nom': unite.name if unite else '',
            'type': unite.get_unit_type_display() if unite else '',
            'reconnu': unite is not None,
            'principal': code == profile.org_entity_code,
            # La chaîne d'ancêtres EST le mécanisme d'héritage du RAG : un document partagé au
            # labo est visible depuis une équipe fille. L'afficher rend l'héritage lisible.
            'chaine': [_readable(u.code, u.name)[0] for u in unite.ancestors()] if unite else [],
        })

    # ⚠⚠ CE QUE LE PARTAGE FAIT, DEMANDÉ AU MÉCANISME — pas affirmé ici (2026-09-26).
    # Cette fonction concluait « partage_possible » dès qu'UN rattachement était reconnu, et la
    # page l'annonçait à l'utilisateur. Mesuré sur le compte de Fabien (3 rattachements) :
    # `lab_share_target` REFUSE — « plusieurs affiliations : nommer l'unité cible ». La page
    # promettait donc l'inverse de ce que le code fait. On appelle la règle au lieu de la
    # redire : un seul domicile, et l'écran ne peut plus diverger.
    target, reason = None, ''
    try:
        from wama.common.memory.index import lab_share_target
        target, reason = lab_share_target(profile.user)
    except Exception:                    # brique mémoire indisponible : on n'affirme rien
        logger.debug('cible de partage labo indéterminable', exc_info=True)

    return {
        'etablissement': profile.establishment,
        'etablissement_libelle': _readable(profile.establishment)[0],
        'etablissement_autorite': split_namespace(profile.establishment)[0],
        'affiliation_ldap': profile.ldap_affiliation,
        'rattachements': rattachements,
        'reconnus': [r for r in rattachements if r['reconnu']],
        'partage_possible': [r for r in rattachements if r['reconnu']],
        #: L'unité qui recevrait un partage labo SANS qu'on la nomme, ou None + la raison.
        'partage_cible': target,
        'partage_raison': reason,
        'partage_a_designer': target is None and any(r['reconnu'] for r in rattachements),
        'hierarchie': profile.org_hierarchy or [],
    }


@login_required
@require_POST
def change_password(request):
    """AJAX: change password for local (non-LDAP) accounts only."""
    from django.contrib.auth.forms import PasswordChangeForm
    from django.contrib.auth import update_session_auth_hash

    if _is_ldap_user(request):
        return JsonResponse(
            {'error': 'Modification du mot de passe non disponible pour les comptes LDAP.'},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    form = PasswordChangeForm(request.user, data)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        return JsonResponse({'success': True})

    errors = {field: [str(e) for e in errs] for field, errs in form.errors.items()}
    # Surface the first human-readable error
    first_error = next(
        (e for errs in errors.values() for e in errs), 'Validation échouée'
    )
    return JsonResponse({'error': first_error, 'fields': errors}, status=400)


@login_required
@require_POST
def language_update(request):
    """AJAX: save preferred language to UserProfile."""
    from wama.common.tts.constants import LANGUAGE_CHOICES

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    lang = data.get('language', 'fr')
    valid_codes = [c[0] for c in LANGUAGE_CHOICES]
    if lang not in valid_codes:
        return JsonResponse({'error': f"Langue invalide : '{lang}'"}, status=400)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.preferred_language = lang
    profile.save(update_fields=['preferred_language'])
    return JsonResponse({'success': True, 'language': lang})


@login_required
@require_POST
def units_update(request):
    """AJAX: enregistre le système d'unités d'AFFICHAGE (D27) — la donnée reste dans SON unité."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    system = data.get('unit_system', 'metric')
    valid = {c[0] for c in UserProfile._meta.get_field('unit_system').choices}
    if system not in valid:
        return JsonResponse({'error': f"Système d'unités invalide : '{system}'"}, status=400)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.unit_system = system
    profile.save(update_fields=['unit_system'])
    return JsonResponse({'success': True, 'unit_system': system})


@login_required
@require_POST
def theme_update(request):
    """AJAX: enregistre le THÈME du compte — un thème déclaré (`common/themes.py`) ou
    « Automatique », qui suit le mode du système — et, pour un thème personnalisé, sa couleur
    d'accent (`accent`). Réglage durable, lu sur toute page. Rend le bloc GÉNÉRÉ (`css`, '' pour
    un autre thème) : le Profil le pose sur place."""
    from wama.common import themes as declared
    from wama.common.themes import save_theme_choice

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    try:
        accent = data.get('accent')
        choice = save_theme_choice(request.user, data.get('theme'), *(() if accent is None else (accent,)))
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'success': True, 'theme': choice, **_theme_reply(request.user, declared)})


def _theme_reply(user, declared):
    """Ce que le Profil pose sur place après un choix : le thème à poser (`key`), la couleur
    d'accent et le bloc GÉNÉRÉ du compte. `getattr` : même raison que dans `profile`."""
    stored = declared.theme_choice(user)
    accent = getattr(declared, 'theme_accent', lambda user: '')(user)
    css = getattr(declared, 'account_generated_css', lambda user, choice: '')(user, stored)
    return {'key': declared.resolve(stored).key, 'accent': accent, 'css': css}


@login_required
@require_POST
def theme_charter_read(request):
    """AJAX (multipart, champ `charter`) : LIT une charte graphique — les couleurs écrites, et la
    proposition du modèle de langue (principale, nom, base, police) — sans rien enregistrer.
    L'utilisateur valide ensuite (`theme_charter_save`)."""
    import os
    import tempfile

    from wama.common import theme_charter
    from wama.common.theme_generator import generate

    upload = request.FILES.get('charter')
    if upload is None:
        return JsonResponse({'error': 'Aucun fichier reçu.'}, status=400)
    stem, ext = os.path.splitext(upload.name or '')
    if ext.lower() not in theme_charter.CHARTER_EXTENSIONS:
        return JsonResponse({'error': f"Format non lu : {ext or '?'} (PDF, Word, texte)."}, status=400)
    if upload.size > theme_charter.MAX_CHARTER_BYTES:
        return JsonResponse({'error': 'Fichier trop lourd pour une charte.'}, status=400)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'charter' + ext.lower())
        with open(path, 'wb') as out:
            for chunk in upload.chunks():
                out.write(chunk)
        try:
            found = theme_charter.read_charter(path, fallback_name=stem.replace('_', ' '))
        except (ValueError, RuntimeError) as exc:
            return JsonResponse({'error': f'Lecture impossible : {exc}'}, status=400)
    candidates = [{'hex': c['hex'], 'context': c['context'], 'count': c['count'],
                   'obtained': {base: generate(base, c['hex'])['--wama-accent-text'] for base in ('light', 'dark')}}
                  for c in found['candidates']]
    return JsonResponse({'success': True, 'filename': upload.name, 'candidates': candidates,
                         'proposal': found['proposal']})


@login_required
@require_POST
def theme_charter_save(request):
    """AJAX : enregistre le thème VALIDÉ d'une charte — une ligne `UserTheme` privée au compte,
    partagée si une portée est donnée — et le pose comme thème du compte."""
    from wama.common import themes as declared
    from wama.common.models import UserTheme
    from wama.common.services.sharing import RefusDePartage, share_scope
    from wama.common.theme_charter import check_seeds

    try:
        data = json.loads(request.body)
        seeds = check_seeds(data.get('name'), data.get('base'), data.get('accent'), data.get('font', ''))
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    colours = [c for c in (data.get('colours') or []) if isinstance(c, str)][:64]
    row = UserTheme.objects.create(
        owner=request.user, **seeds,
        source={'charter': str(data.get('filename') or '')[:200], 'colours': colours,
                'reader': str(data.get('reader') or '')[:16], 'proposed': data.get('proposal') or {},
                'created_by': request.user.get_username()})
    try:
        if (data.get('scope') or 'private') != 'private':
            share_scope(request.user, row, data.get('scope'))
    except RefusDePartage as exc:
        return JsonResponse({'error': f'Thème enregistré, mais non partagé : {exc}', 'pk': row.pk}, status=400)
    choice = declared.save_theme_choice(request.user, f'{declared.CHARTER_PREFIX}{row.pk}')
    return JsonResponse({'success': True, 'theme': choice, 'pk': row.pk,
                         **_theme_reply(request.user, declared)})


@login_required
@require_POST
def theme_charter_manage(request):
    """AJAX : `share` (une portée, par le service commun), `delete` (son auteur, ou un admin),
    `promote` (un ADMIN seul, décision b du §29 : le thème devient SYSTÈME, sans propriétaire,
    l'auteur gardé pour l'attribution ; la demande en attente est accordée). « Demander la
    promotion » passe par la route commune (`common:api_promotion_request`)."""
    from wama.common.manifests.ownership import may_remove, promote_element
    from wama.common.services.sharing import RefusDePartage, share_scope
    from wama.common.themes import charter_themes

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    row = charter_themes(request.user).filter(pk=data.get('pk') if str(data.get('pk', '')).isdigit() else -1).first()
    if row is None:
        return JsonResponse({'error': 'Thème inconnu.'}, status=404)
    action = data.get('action')
    if action == 'share':
        try:
            done = share_scope(request.user, row, data.get('scope'))
        except RefusDePartage as exc:
            return JsonResponse({'error': str(exc)}, status=403)
        return JsonResponse({'success': True, 'visibility': done['visibility']})
    if action == 'delete':
        if not may_remove(request.user, row):
            return JsonResponse({'error': "Seul son auteur, ou un administrateur, le retire."}, status=403)
        row.delete()
        return JsonResponse({'success': True})
    if action == 'promote':
        try:
            promote_element(request.user, row)
        except PermissionError as exc:
            return JsonResponse({'error': str(exc)}, status=403)
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        return JsonResponse({'success': True})
    return JsonResponse({'error': f'Action inconnue : {action!r}'}, status=400)


@login_required
@require_POST
def notifications_update(request):
    """AJAX: enregistre les préférences de notification — quand notifier, par e-mail, et le son
    dans WAMA (2026-10-06). Une préférence absente de la requête garde sa valeur."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    valid_on = {'both', 'completion', 'failure', 'none'}
    notify_on = data.get('notify_on', 'both')
    if notify_on not in valid_on:
        return JsonResponse({'error': f"Valeur invalide : '{notify_on}'"}, status=400)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.notify_email = bool(data.get('notify_email', True))
    profile.notify_on = notify_on
    profile.notify_sound = bool(data.get('notify_sound', profile.notify_sound))
    profile.save(update_fields=['notify_email', 'notify_on', 'notify_sound'])
    return JsonResponse({'success': True, 'notify_email': profile.notify_email,
                         'notify_on': profile.notify_on, 'notify_sound': profile.notify_sound})


@login_required
@require_POST
def search_engine_update(request):
    """AJAX {engine} : le moteur de recherche web de CET utilisateur ('' = celui de l'instance).

    Validé contre les moteurs UTILISABLES par lui — pas contre la liste complète : choisir un
    moteur dont on n'a pas la clé produirait une préférence qui échoue à chaque recherche, et
    l'utilisateur n'aurait aucun moyen de comprendre pourquoi.
    """
    from wama.common.search_engines import usable_slugs

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    engine = (data.get('engine') or '').strip()
    if engine and engine not in usable_slugs(request.user):
        return JsonResponse({'error': "Moteur indisponible : inconnu, ou sa clé n'est pas "
                                      "posée sur votre profil."}, status=400)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.search_engine = engine
    profile.save(update_fields=['search_engine'])
    return JsonResponse({'success': True, 'engine': engine})


@login_required
@require_POST
def layout_update(request):
    """AJAX: enregistre la géométrie de file — disposition (list/grid) et/ou pile.

    Un seul endpoint pour les deux : la pile est un MODIFICATEUR de la disposition
    (CARD_DESIGN §11 v3.5), pas un réglage d'une autre nature. Les deux clés sont
    indépendantes et facultatives — on n'écrit que ce qui est envoyé.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    changed = []

    if 'card_layout' in data:
        layout = data.get('card_layout', 'list')
        if layout not in ('list', 'grid'):
            return JsonResponse({'error': f"Valeur invalide : '{layout}'"}, status=400)
        profile.card_layout = layout
        changed.append('card_layout')

    if 'card_stacked' in data:
        profile.card_stacked = bool(data.get('card_stacked'))
        changed.append('card_stacked')

    if 'card_design' in data:
        design = data.get('card_design')
        valid = [c[0] for c in UserProfile.CARD_DESIGNS]
        if design not in valid:
            return JsonResponse({'error': f"Design inconnu : '{design}'"}, status=400)
        profile.card_design = design
        changed.append('card_design')

    if not changed:
        return JsonResponse({'error': 'Aucune clé reconnue'}, status=400)
    profile.save(update_fields=changed)
    return JsonResponse({'success': True, 'card_layout': profile.card_layout,
                         'card_stacked': profile.card_stacked,
                         'card_design': profile.card_design})


@login_required
@require_POST
def inspector_autoplay_update(request):
    """AJAX: enregistre la préférence de lecture auto de l'aperçu dans l'inspecteur."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    enabled = bool(data.get('inspector_autoplay', False))
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.inspector_autoplay = enabled
    profile.save(update_fields=['inspector_autoplay'])
    return JsonResponse({'success': True, 'inspector_autoplay': enabled})


@login_required
@require_POST
def retention_update(request):
    """AJAX: enregistre les DEUX durées de conservation (0 = illimité) — les cards et leurs fichiers
    (`media_retention_days`), le dossier temporaire (`temp_retention_days`, 2026-10-02, D9). Une
    clé absente garde sa valeur : un appelant qui ne connaît que la première ne remet pas l'autre
    à zéro."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    fields = []
    for key in ('media_retention_days', 'temp_retention_days'):
        if key not in data:
            continue
        try:
            setattr(profile, key, max(0, int(data.get(key) or 0)))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Valeur invalide'}, status=400)
        fields.append(key)
    if fields:
        profile.save(update_fields=fields)
    return JsonResponse({'success': True, 'media_retention_days': profile.media_retention_days,
                         'temp_retention_days': profile.temp_retention_days,
                         'effective': profile.effective_retention_days(),
                         'effective_temp': profile.effective_temp_retention_days()})


@login_required
@require_POST
def token_regenerate(request):
    """AJAX: delete existing DRF token and create a new one."""
    from rest_framework.authtoken.models import Token

    Token.objects.filter(user=request.user).delete()
    token = Token.objects.create(user=request.user)
    return JsonResponse({'success': True, 'token': token.key})


def _champ(request, name: str) -> str:
    """
    Lit un champ que la requête soit en JSON ou en formulaire.

    La page de profil poste en JSON (helper `postJson`) ; un client en ligne de commande
    postera plus volontiers un formulaire. Accepter les deux évite le « ça marche dans le
    navigateur mais pas au curl » — et coûte trois lignes.

    ⚠ Le corps lisait `nom` alors que la signature déclare `name` (renommage partiel du
    2026-08-30) : chaque appel levait une NameError, donc la confirmation d'appariement de
    canal et la déliaison répondaient 500. Aucun test n'appelait ces vues — corrigé et gardé
    le 2026-09-15 (`accounts/tests/tests_channel_views.py`).
    """
    if request.content_type and 'application/json' in request.content_type:
        try:
            return (json.loads(request.body or '{}').get(name) or '').strip()
        except (json.JSONDecodeError, AttributeError):
            return ''
    return (request.POST.get(name) or '').strip()


@login_required
@require_POST
def channel_link_confirm(request):
    """
    AJAX : scelle une liaison de canal à partir du code obtenu dans la discussion.

    C'EST ICI QUE LA PREUVE D'IDENTITÉ EST APPORTÉE (passerelle, `ROADMAP.md` §19.1) : le
    compte lié est celui de la session courante, jamais un compte nommé dans le canal. Un
    code intercepté dans une discussion ne permet donc que de se lier SOI-MÊME à l'identité
    de canal de celui qui l'a demandé — ce qui ne donne aucun accès.
    """
    from wama.gateway.services import PairingError, confirm_link

    try:
        lien = confirm_link(request.user, _champ(request, 'code'))
    except PairingError as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'success': True,
        'channel': lien.get_channel_display(),
        'label': lien.external_label or lien.external_id,
    })


@login_required
@require_POST
def channel_unlink(request):
    """AJAX : supprime une de SES liaisons de canal (jamais celle d'autrui)."""
    from wama.gateway.services import unlink

    supprime = unlink(request.user, _champ(request, 'channel'),
                      _champ(request, 'external_id'))
    if not supprime:
        return JsonResponse({'error': 'Liaison introuvable.'}, status=404)
    return JsonResponse({'success': True})


def add_user(username, first_name, last_name, email):
    """ Crée un utilisateur si inexistant """
    if not User.objects.filter(username=username).exists():
        user = User.objects.create_user(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email
        )
        user.set_unusable_password()
        user.save()
        print(f"The user {username} has been created successfully.")
    else:
        print(f"The user {username} already exists.")


#: Nom du compte de service qui porte les requêtes non authentifiées. Une constante parce que
#: trois endroits doivent désigner LE MÊME compte : cette fabrique, la garde de
#: `grant_default_roles` et le test qui verrouille l'invariant — et, depuis le 2026-10-01, la
#: nature des comptes (`permissions.account_kind`), où elle est désormais définie.
from wama.accounts.permissions import ANONYMOUS_USERNAME  # noqa: E402  (ré-export : ses lecteurs l'importent d'ici)

#: Mémo de process : l'invariant n'a besoin d'être reposé qu'une fois par worker (cf. docstring).
_CLOSURE_VERIFIEE = False


def enforce_anonymous_closure(user):
    """Repose l'invariant du compte anonyme : tier `anonymous`, AUCUN rôle métier.

    Pourquoi ça vit dans le CODE et plus en base seulement (mesuré le 2026-08-27) : la fermeture
    du 2026-08-22 avait été faite à la main sur la base vivante. Or `UserProfile.account_tier`
    a pour défaut `utilisateur` — donc tout compte anonyme RECRÉÉ (installation neuve via
    `init_wama`, restauration d'une sauvegarde antérieure) revenait ouvert, et
    `grant_default_roles` lui rendait les 4 rôles puisqu'il vise les comptes SANS rôle.

    Mesuré sur les 11 apps du catalogue : tier `utilisateur` + 0 rôle → 1 app ouverte
    (converter, seule app commune) ; tier `utilisateur` + tous les rôles → **10 apps sur 11**,
    c'est-à-dire l'état d'avant le correctif. Les deux axes doivent donc être reposés, pas un.

    Idempotent, et sans coût sur le chemin chaud : `get_or_create_anonymous_user()` est appelée
    à chaque requête non authentifiée (une vingtaine de sites rien que dans anonymizer), donc la
    vérification est faite UNE fois par process (`_CLOSURE_VERIFIEE`) au lieu de deux requêtes
    par requête HTTP. Une dérive introduite à la main pendant qu'un worker tourne est rattrapée
    au redémarrage et par le test qui verrouille l'invariant.
    """
    from wama.accounts.permissions import GROUP_PREFIX
    # On passe par l'ACCESSEUR `user.profile`, pas par un `get_or_create` qui rendrait une AUTRE
    # instance Python : le signal `post_save` a déjà rempli le cache de relation du user, et
    # `user_tier()` lit ce cache. Corriger la copie en base sans corriger la copie en mémoire
    # laissait le tier à `utilisateur` pour toute la requête qui vient de créer le compte —
    # défaut trouvé par les tests, pas par la relecture (le premier jet faisait exactement ça).
    profil = getattr(user, 'profile', None)     # RelatedObjectDoesNotExist hérite d'AttributeError
    if profil is None:
        profil, _ = UserProfile.objects.get_or_create(user=user)
    if profil.account_tier != 'anonymous':
        profil.account_tier = 'anonymous'
        profil.save(update_fields=['account_tier'])
    roles = user.groups.filter(name__startswith=GROUP_PREFIX)
    if roles.exists():
        user.groups.remove(*roles)
    return user


def get_or_create_anonymous_user():
    """
    Récupère ou crée un utilisateur anonyme désactivé, FERMÉ (voir `enforce_anonymous_closure`).
    """
    user, created = User.objects.get_or_create(
        username=ANONYMOUS_USERNAME,
        defaults={
            'first_name': 'Anonymous',
            'last_name': 'User',
            'email': 'anonymous@univ-eiffel.fr',
            'is_active': False,
        }
    )
    global _CLOSURE_VERIFIEE
    if created:
        user.set_unusable_password()
        user.save()
        print("Anonymous user created.")
    if created or not _CLOSURE_VERIFIEE:
        enforce_anonymous_closure(user)
        _CLOSURE_VERIFIEE = True
    return user


# =============================================================================
# User Management Views (Admin only)
# =============================================================================

@admin_required
def user_management(request):
    """Display the user management page."""
    from wama.accounts.permissions import (ACCOUNT_KINDS, GROUP_PREFIX, ROLE_DESCRIPTIONS, ROLES,
                                           account_kind)

    users = User.objects.all().order_by('username').prefetch_related('groups')
    groups = Group.objects.all().order_by('name')

    # Une SECTION par nature de compte (2026-10-01, demande de Fabien) : les personnes, puis les
    # comptes de test et le compte système — `account_kind`, défini une fois.
    sections = {kind: [] for kind in ACCOUNT_KINDS}
    for user in users:
        # Rôles MÉTIER actifs (axe B, cumulatifs, Groups 'role:*') — indépendants du tier ci-dessus.
        active_metier = {g.name[len(GROUP_PREFIX):] for g in user.groups.all()
                         if g.name.startswith(GROUP_PREFIX)}
        sections[account_kind(user)].append({
            'user': user,
            'role': get_user_role(user),
            'groups': [g.name for g in user.groups.all()],
            'metier_cells': [{'key': k, 'label': label, 'active': k in active_metier}
                             for k, label in ROLES.items()],
        })

    # Barre COMMUNE de filtre / tri / recherche (`common/_filter_bar.html`, mode client) : les
    # facettes se déclarent avec leurs libellés, le tri lit `data-s-<clé>` sur chaque ligne.
    role_labels = {'admin': 'Admin', 'dev': 'Développeur', 'user': 'Utilisateur',
                   'anonymous': 'Anonyme'}
    context = {
        'sections': [{'kind': kind, 'label': label, 'users': sections[kind]}
                     for kind, label in ACCOUNT_KINDS.items()],
        'facets': [
            # Clé `tier` et non `role` : `data-f-role` est l'attribut RÉSERVÉ de la brique
            # (recherche, tri) — une facette `role` le poserait sur chaque ligne.
            {'cle': 'tier', 'label': 'Rôle', 'options': role_labels},
            {'cle': 'statut', 'label': 'Statut', 'options': {'actif': 'Actif', 'inactif': 'Inactif'}},
        ],
        'sorts': [('username:asc', 'Nom'), ('joined:desc', 'Inscription récente'),
                  ('login:desc', 'Dernière connexion')],
        'groups': groups,
        'available_roles': ['admin', 'dev', 'user'],
        # Catalogue des métiers pour l'en-tête de colonnes (tooltip = description).
        'metier_roles': [(k, label, ROLE_DESCRIPTIONS.get(k, '')) for k, label in ROLES.items()],
        'volet': VOLET_AUCUN,                   # tableau d'administration, cf. login_view
    }
    return render(request, 'accounts/user_management.html', context)


@admin_required
def user_constellation(request):
    """La constellation 3D des utilisateurs (2026-10-20, demande de Fabien) — ouverte depuis la
    gestion des utilisateurs. La page ne porte aucune donnée : elle lit `user_constellation_data`.

    `?embed=1` : la MÊME page sans barre ni volet, pour la frame « Droits · Constellation » de la
    présentation (`includes/wama_presentation.html`), qui l'intègre en iframe — et noms masqués
    par défaut, la présentation se projetant devant d'autres personnes."""
    return render(request, 'accounts/user_constellation.html',
                  {'volet': VOLET_AUCUN, 'embed': request.GET.get('embed') == '1'})


@admin_required
def user_constellation_data(request):
    """Les FAITS de la constellation (`accounts.constellation`) — réservés à l'administration :
    ils disent de chaque compte ses droits, ses partages et son activité."""
    from wama.accounts.constellation import constellation
    return JsonResponse(constellation())


@admin_required
@require_POST
def user_toggle_metier_role(request, user_id):
    """AJAX : bascule UN rôle métier (axe B, cumulatif, indépendant du tier) pour un utilisateur.
    Miroir de `app_access_toggle` (mêmes Groups 'role:*', même contrat request/response) mais côté
    utilisateur plutôt que côté politique d'app — permet d'affecter PLUSIEURS métiers à une personne
    (imager+communication, transcriber+recherche, etc.), ce que le rôle de tier seul ne permet pas."""
    from wama.accounts.permissions import ROLES, GROUP_PREFIX
    user = get_object_or_404(User, id=user_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'JSON invalide'}, status=400)

    role = data.get('role')
    if role not in ROLES:
        return JsonResponse({'success': False, 'error': f"Métier inconnu : {role}"}, status=400)

    group, _ = Group.objects.get_or_create(name=GROUP_PREFIX + role)
    if data.get('enabled'):
        user.groups.add(group)
    else:
        user.groups.remove(group)
    return JsonResponse({'success': True})


@admin_required
def app_access_matrix(request):
    """Tableau d'accès app×rôle éditable (cases à cocher)."""
    from wama.accounts.models import AppAccessPolicy
    from wama.accounts.permissions import (ROLES, ROLE_DESCRIPTIONS, GROUP_PREFIX,
                                           TIER_CHOICES, APP_GROUP_ORDER, all_gated_apps,
                                           app_group)
    from wama.common.app_registry import app_identity

    # [(key, label, help)] pour les en-têtes de colonnes (tooltip).
    role_keys = [(k, label, ROLE_DESCRIPTIONS.get(k, '')) for k, label in ROLES.items()]

    by_group = {}
    # Seuls les outils GARDÉS : une ligne restée en base pour un droit retiré (`model_manager`,
    # devenu une page des Registres le 2026-10-13) ne déciderait plus rien — l'afficher
    # éditable laisserait croire le contraire.
    gated = all_gated_apps()
    for pol in AppAccessPolicy.objects.filter(app_id__in=gated).prefetch_related('roles').order_by('app_id'):
        active = {g.name[len(GROUP_PREFIX):] for g in pol.roles.all() if g.name.startswith(GROUP_PREFIX)}
        # Le nom et la description DÉCLARÉS par l'app — sa card, sinon sa surface ou sa
        # déclaration d'outil sans page (2026-10-13 : une table de secours recopiait la
        # description ici, et dérivait) : son identité commune (`app_registry.app_identity`,
        # 2026-10-16). Le nom depuis le 2026-10-20 : la ligne affichait la clé.
        identity = app_identity(pol.app_id)
        by_group.setdefault(app_group(pol.app_id), []).append({
            'app_id': pol.app_id,
            'label': identity['label'],
            'description': identity['description'],
            'public': pol.public,
            'min_tier': pol.min_tier,
            'cells': [{'role': k, 'active': (k in active)} for k, _ in ROLES.items()],
        })
    # Sections ordonnées (puis tout groupe non prévu).
    ordered = APP_GROUP_ORDER + [g for g in by_group if g not in APP_GROUP_ORDER]
    groups = [{'name': g, 'rows': by_group[g]} for g in ordered if by_group.get(g)]

    context = {
        'groups': groups,
        'role_keys': role_keys,
        'ncols': len(role_keys) + 3,  # nom + rôles + anonyme + tier
        # 'anonymous' est le plancher → inutile comme tier MINIMAL (équivalent à « aucun »).
        'tier_choices': [(v, l) for v, l in TIER_CHOICES if v != 'anonymous'],
        'volet': VOLET_AUCUN,                   # matrice pleine largeur, cf. login_view
    }
    return render(request, 'accounts/app_access_matrix.html', context)


@admin_required
@require_POST
def app_access_toggle(request):
    """AJAX: modifie une cellule du tableau d'accès (role/public/min_tier d'une app)."""
    from wama.accounts.models import AppAccessPolicy
    from wama.accounts.permissions import ROLES, GROUP_PREFIX
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    app_id = data.get('app_id')
    if not app_id:
        return JsonResponse({'error': 'app_id manquant'}, status=400)
    pol, _ = AppAccessPolicy.objects.get_or_create(app_id=app_id)

    field = data.get('field')
    if field == 'role':
        role = data.get('role')
        if role not in ROLES:
            return JsonResponse({'error': f"Rôle inconnu : {role}"}, status=400)
        group, _ = Group.objects.get_or_create(name=GROUP_PREFIX + role)
        if data.get('enabled'):
            pol.roles.add(group)
        else:
            pol.roles.remove(group)
    elif field == 'public':
        pol.public = bool(data.get('enabled'))
        pol.save(update_fields=['public'])
    elif field == 'min_tier':
        pol.min_tier = data.get('value', '') or ''
        pol.save(update_fields=['min_tier'])
    else:
        return JsonResponse({'error': 'champ invalide'}, status=400)

    return JsonResponse({'success': True})


@admin_required
def user_add(request):
    """Add a new user."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        password = request.POST.get('password', '')
        role = request.POST.get('role', 'user')

        # Validation
        if not username:
            return JsonResponse({'success': False, 'error': 'Le nom d\'utilisateur est requis'})

        if User.objects.filter(username=username).exists():
            return JsonResponse({'success': False, 'error': 'Ce nom d\'utilisateur existe déjà'})

        if email and User.objects.filter(email=email).exists():
            return JsonResponse({'success': False, 'error': 'Cet email est déjà utilisé'})

        try:
            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password if password else None,
                first_name=first_name,
                last_name=last_name,
            )

            if not password:
                user.set_unusable_password()
                user.save()

            # Le RÔLE choisi pose le NIVEAU, et le niveau ses drapeaux Django
            # (`permissions.set_account_tier`, décision de Fabien du 2026-10-21) — plus aucun
            # groupe hérité.
            from wama.accounts.permissions import set_account_tier
            set_account_tier(user, TIER_OF_ROLE.get(role, 'utilisateur'))

            return JsonResponse({
                'success': True,
                'message': f'Utilisateur {username} créé avec succès',
                'user_id': user.id
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


@admin_required
def user_delete(request, user_id):
    """Delete a user."""
    if request.method == 'POST':
        try:
            user = get_object_or_404(User, id=user_id)

            # Prevent deleting yourself
            if user == request.user:
                return JsonResponse({'success': False, 'error': 'Vous ne pouvez pas vous supprimer vous-même'})

            # Prevent deleting anonymous user
            if user.username == 'anonymous':
                return JsonResponse({'success': False, 'error': 'L\'utilisateur anonymous ne peut pas être supprimé'})

            username = user.username
            user.delete()

            return JsonResponse({
                'success': True,
                'message': f'Utilisateur {username} supprimé'
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


@admin_required
def user_update_role(request, user_id):
    """Update a user's role."""
    if request.method == 'POST':
        try:
            user = get_object_or_404(User, id=user_id)
            new_role = request.POST.get('role', 'user')

            # Prevent changing anonymous user role
            if user.username == 'anonymous':
                return JsonResponse({'success': False, 'error': 'Le rôle de l\'utilisateur anonymous ne peut pas être modifié'})

            # Prevent removing your own admin role
            if user == request.user and new_role != 'admin':
                return JsonResponse({'success': False, 'error': 'Vous ne pouvez pas retirer votre propre rôle admin'})

            # Le RÔLE pose le NIVEAU, et le niveau ses drapeaux Django (`set_account_tier`) —
            # décision de Fabien du 2026-10-21 : le niveau est la seule source. Les groupes
            # hérités `admin` / `dev` / `user` ne s'écrivent plus (ils sont retirés) ; les rôles
            # MÉTIER `role:*` ne sont pas touchés.
            from wama.accounts.permissions import set_account_tier
            set_account_tier(user, TIER_OF_ROLE.get(new_role, 'utilisateur'))

            return JsonResponse({
                'success': True,
                'message': f'Rôle de {user.username} mis à jour vers {new_role}'
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


@admin_required
def user_toggle_active(request, user_id):
    """Toggle user active status."""
    if request.method == 'POST':
        try:
            user = get_object_or_404(User, id=user_id)

            # Prevent deactivating yourself
            if user == request.user:
                return JsonResponse({'success': False, 'error': 'Vous ne pouvez pas vous désactiver vous-même'})

            # Prevent changing anonymous status
            if user.username == 'anonymous':
                return JsonResponse({'success': False, 'error': 'L\'utilisateur anonymous ne peut pas être modifié'})

            user.is_active = not user.is_active
            user.save()

            status = 'activé' if user.is_active else 'désactivé'
            return JsonResponse({
                'success': True,
                'message': f'Utilisateur {user.username} {status}',
                'is_active': user.is_active
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
