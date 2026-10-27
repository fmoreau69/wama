"""
Model Sync Service - Synchronizes models between filesystem/configs and database.

This service bridges the gap between the dynamic ModelRegistry discovery
and the PostgreSQL-backed AIModel catalog.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

from django.db import transaction
from django.utils import timezone

from wama.common.utils.model_capabilities import normalize_capabilities

logger = logging.getLogger(__name__)


def _uninstalled_after(stamp, seen_at) -> bool:
    """La marque `uninstalled_at` (ISO, posée par `uninstall_model`) est-elle postérieure au relevé ?"""
    from datetime import datetime
    if not stamp:
        return False
    try:
        return datetime.fromisoformat(str(stamp)) >= seen_at
    except (TypeError, ValueError):
        return False


@dataclass
class SyncResult:
    """Result of a sync operation."""
    success: bool
    added: int = 0
    updated: int = 0
    removed: int = 0
    errors: List[str] = field(default_factory=list)
    #: Clés des modèles CRÉÉS par cette passe. Le compteur `added` ne disait pas LESQUELS, si
    #: bien qu'un appelant voulant agir sur les nouveaux (poser leur provenance après une
    #: installation) devait photographier le catalogue avant/après pour re-dériver ce que le
    #: sync savait déjà — avec la course que ça suppose. (2026-08-12)
    added_keys: List[str] = field(default_factory=list)


class ModelSyncService:
    """
    Service for synchronizing models between various sources and the database.

    Workflow:
    1. Uses existing ModelRegistry to discover models from all sources
    2. Syncs discovered models to AIModel database table
    3. Tracks sync history in ModelSyncLog
    """

    def __init__(self):
        self._registry = None

    def _get_registry(self):
        """Lazy load registry to avoid circular imports."""
        if self._registry is None:
            from .model_registry import ModelRegistry
            self._registry = ModelRegistry()
        return self._registry

    def full_sync(self, remove_missing: bool = False, delete_missing: bool = False) -> SyncResult:
        """
        Perform a full sync of all models from all sources.

        Args:
            remove_missing: If True, mark models not found in sources as unavailable
            delete_missing: If True, delete models not found in sources from the database
                           (takes precedence over remove_missing)

        Returns:
            SyncResult with counts and any errors
        """
        from ..models import AIModel, ModelSyncLog

        log = ModelSyncLog.objects.create(sync_type='full')
        result = SyncResult(success=True)

        try:
            # Discover all models from sources
            discovery_started = timezone.now()
            registry = self._get_registry()
            registry._models.clear()  # Force fresh discovery
            discovered_models = registry.discover_all_models()
            logger.info(f"Discovered {len(discovered_models)} models from sources")

            # Track which model_keys we've seen
            seen_keys: Set[str] = set()

            with transaction.atomic():
                for model_key, model_info in discovered_models.items():
                    seen_keys.add(model_key)

                    try:
                        created, updated = self._sync_model(model_key, model_info,
                                                            seen_at=discovery_started)
                        if created:
                            result.added += 1
                            result.added_keys.append(model_key)
                        elif updated:
                            result.updated += 1
                    except Exception as e:
                        error_msg = f"Error syncing {model_key}: {e}"
                        logger.error(error_msg)
                        result.errors.append(error_msg)

                # ⚠ UNE DÉCOUVERTE INCOMPLÈTE NE PROUVE AUCUNE DISPARITION.
                #
                # Incident du 2026-08-22 : la déclaration de SAM3 a levé dans le processus qui
                # faisait le sync (exception avalée par un `except: pass` du registre). SAM3 est
                # donc sorti de `discovered_models`, s'est retrouvé « absent des sources », et sa
                # ligne de catalogue a été EFFACÉE — alors que le modèle était installé, en cache
                # et opérationnel. Le seul signe visible fut un `-1` dans le journal de sync ;
                # la référence de manifeste n'est devenue pendante que des heures plus tard.
                #
                # La réconciliation ne peut donc s'appuyer sur la découverte QUE si celle-ci s'est
                # déroulée entièrement. Sinon on ne sait pas distinguer « retiré du disque » de
                # « pas su le lire », et seule la première justifie une suppression.
                echecs = list(getattr(registry, 'discovery_errors', ()) or ())
                if echecs and (delete_missing or remove_missing):
                    message = (f"réconciliation SUSPENDUE : découverte incomplète "
                               f"({len(echecs)} échec(s)) — {'; '.join(echecs[:3])}")
                    logger.error(message)
                    result.errors.append(message)
                    delete_missing = remove_missing = False

                # Un snapshot catalogué par le balayage GÉNÉRIQUE puis DÉCLARÉ par une app n'est
                # plus produit par la découverte (la dédup par dépôt/famille l'écarte), mais sa
                # ligne `huggingface:` restait : sans `--clean`, rien ne la retirait. Mêmes poids,
                # deux cards — vécu deux fois sur FastWan (16/09 retiré à la main, revu le 23/09).
                # Ce n'est pas une DISPARITION (les poids sont là) mais une SUPPRESSION PAR
                # RELÈVE : on ne la fait donc que si une ligne découverte porte le même dépôt,
                # et seulement sur une découverte complète (même règle que ci-dessus).
                if not echecs:
                    result.removed += self._drop_superseded_snapshots(discovered_models,
                                                                      seen_keys)
                # Une ligne que la découverte REFUSE désormais par règle n'a jamais été un modèle
                # (manifeste interne du démon Ollama) : ce n'est pas une disparition, la retirer ne
                # dépend donc pas d'une découverte complète.
                result.removed += self._drop_ollama_runner_aliases()
                # Le relevé du DÉMON Ollama (et lui seul) prouve un retrait fait hors de WAMA.
                listed = getattr(registry, 'ollama_listed', None)
                if listed is not None:
                    self._mark_ollama_removed_outside(listed, discovery_started)

                # Handle models no longer in sources
                if delete_missing:
                    # Delete models that no longer exist on disk.
                    # NB : exclure les candidats de prospection (is_proposed) — ils ne sont
                    # pas sur disque par nature et ne doivent pas être réconciliés.
                    # Les modèles DISTANTS, eux, sont réconciliés comme les autres depuis le
                    # 2026-09-18 : la découverte cloud les relit depuis les clés d'API
                    # (`_discover_cloud_models`), donc « absent de la découverte » veut dire
                    # « plus aucune clé ne l'ouvre ».
                    missing_models = (AIModel.objects.exclude(model_key__in=seen_keys)
                                      .exclude(is_proposed=True))
                    removed_count = missing_models.count()
                    if removed_count > 0:
                        deleted_keys = list(missing_models.values_list('model_key', flat=True))
                        logger.info(f"Deleting {removed_count} models no longer on disk: {deleted_keys[:5]}...")
                        missing_models.delete()
                    result.removed += removed_count
                elif remove_missing:
                    # Just mark as unavailable (legacy behavior)
                    removed_count = AIModel.objects.exclude(
                        model_key__in=seen_keys
                    ).exclude(is_proposed=True).update(is_available=False)
                    result.removed += removed_count

            log.status = 'completed'
            log.models_added = result.added
            log.models_updated = result.updated
            log.models_removed = result.removed
            log.completed_at = timezone.now()
            log.save()

            logger.info(
                f"Full sync completed: +{result.added}, ~{result.updated}, -{result.removed}"
            )

            # Les poids PAR COMPOSANT des modèles installés (décision A) suivent chaque synchro :
            # c'est elle qui suit une installation. Signature inchangée = rien n'est refait. Un
            # échec ici ne défait pas la synchro — le relevé a sa tâche beat pour se rattraper.
            try:
                logger.info(f"Weights persisted for {self.persist_weights()} model(s)")
            except Exception as e:
                logger.warning(f"persist_weights après synchro : {e}")

        except Exception as e:
            logger.error(f"Full sync failed: {e}")
            result.success = False
            result.errors.append(str(e))

            log.status = 'failed'
            log.error_message = str(e)
            log.completed_at = timezone.now()
            log.save()

        return result

    def sync_cloud_models(self) -> SyncResult:
        """Synchronise les SEULS modèles distants (`ModelRegistry.discover_cloud_models`) — la
        même écriture que `full_sync`, ligne par ligne (`_sync_model`), mais SANS aucune
        réconciliation : une découverte partielle ne prouve aucune disparition. Le retrait de
        ce que plus aucune clé n'ouvre reste à `cloud_models.retire_unlisted`. (2026-10-02 :
        l'enregistrement d'une clé déclenchait la synchronisation complète, ~5 min.)"""
        from ..models import ModelSyncLog

        log = ModelSyncLog.objects.create(sync_type='incremental')
        result = SyncResult(success=True)
        try:
            discovered = self._get_registry().discover_cloud_models()
            with transaction.atomic():
                for model_key, model_info in discovered.items():
                    try:
                        created, updated = self._sync_model(model_key, model_info)
                        if created:
                            result.added += 1
                            result.added_keys.append(model_key)
                        elif updated:
                            result.updated += 1
                    except Exception as e:
                        result.errors.append(f"Error syncing {model_key}: {e}")
            log.status = 'completed'
            log.models_added, log.models_updated = result.added, result.updated
        except Exception as e:
            logger.error(f"Cloud sync failed: {e}")
            result.success = False
            result.errors.append(str(e))
            log.status, log.error_message = 'failed', str(e)
        log.completed_at = timezone.now()
        log.save()
        return result

    @staticmethod
    def _drop_superseded_snapshots(discovered_models, seen_keys) -> int:
        """Supprime les lignes du balayage générique (`extra_info.hf_snapshot`) absentes de
        cette découverte ET dont le dépôt est désormais porté par une ligne découverte —
        l'entrée d'app fait autorité (cf. `_discover_installed_hf_snapshots`). Rend le compte."""
        from ..models import AIModel
        from wama.common.external_sources import hf_platform_ref
        from wama.common.utils.model_locations import declared_component_repos
        claimed = {info.hf_repo for info in discovered_models.values() if info.hf_repo}
        # Relevé aussi par son PARENT : un dépôt déclaré composant d'un autre modèle (2026-10-03,
        # le VAE de YuE2 tiré comme générateur de musique) — même geste, même garde.
        claimed |= declared_component_repos()
        if not claimed:
            return 0
        stale = (AIModel.objects.filter(model_key__startswith='huggingface:',
                                        extra_info__hf_snapshot=True, is_proposed=False,
                                        platform_ref__in={hf_platform_ref(r) for r in claimed})
                 .exclude(model_key__in=seen_keys))
        keys = list(stale.values_list('model_key', flat=True))
        if keys:
            logger.info("Snapshots génériques relevés par une app, retirés : %s", keys)
            stale.delete()
        return len(keys)

    @staticmethod
    def _drop_ollama_runner_aliases() -> int:
        """Supprime les lignes `ollama:` dont le nom est un manifeste INTERNE du démon
        (`is_ollama_runner_alias`) — entrées avant le filtre de la découverte, elles ne sont
        plus jamais relues, donc plus jamais recalées : `ollama:llamacpp:96f38c…`, doublon de
        qwen3.5:4b, est resté « téléchargé » et tirable du 07/10 au 12/10. Rend le compte."""
        from ..models import AIModel
        from .model_registry import is_ollama_runner_alias
        keys = [k for k in AIModel.objects.filter(model_key__startswith='ollama:', is_proposed=False)
                                          .values_list('model_key', flat=True)
                if is_ollama_runner_alias(k.partition(':')[2])]
        if keys:
            logger.info("Manifestes internes d'Ollama pris pour des modèles, retirés : %s", keys)
            AIModel.objects.filter(model_key__in=keys).delete()
        return len(keys)

    @staticmethod
    def _mark_ollama_removed_outside(listed, seen_at) -> list:
        """Marque DÉSINSTALLÉES les lignes `ollama:` « téléchargées » que le démon ne liste plus :
        un `ollama rm` fait hors de WAMA. Sans cela la ligne restait « téléchargée », donc tirable,
        tant qu'une synchro `--clean` ne passait pas — et `--clean` marque indisponible TOUT ce
        qu'une découverte n'a pas vu, bien au-delà d'Ollama.

        Même marque que `uninstall_model` (ligne gardée, `uninstalled_at`) : le modèle se
        repropose, son manifeste quitte le corpus, et une réinstallation la retire (la découverte
        réécrit `extra_info`). `listed` n'est fourni que si le DÉMON a répondu ; une ligne touchée
        depuis le relevé (`updated_at >= seen_at`, une installation qui vient de finir) est
        laissée. Rend les clés marquées."""
        from ..models import AIModel
        from .install_history import record
        rows = (AIModel.objects.filter(model_key__startswith='ollama:', is_proposed=False,
                                       is_downloaded=True, updated_at__lt=seen_at)
                .exclude(execution='cloud'))
        gone = [r for r in rows if r.model_key.partition(':')[2] not in listed]
        if not gone:
            return []
        stamp = timezone.now().isoformat()
        for row in gone:
            info = dict(row.extra_info or {})
            info['uninstalled_at'] = stamp
            AIModel.objects.filter(pk=row.pk).update(is_downloaded=False, is_loaded=False,
                                                     extra_info=info)
            record('model', row.model_key, name=row.name, action='uninstall', via='ollama rm',
                   result={'ok': True, 'kind': 'ollama', 'outside_wama': True})
        keys = [r.model_key for r in gone]
        logger.info("Modèles retirés d'Ollama hors de WAMA, marqués désinstallés : %s", keys)
        from .model_installer import forget_in_corpus
        forget_in_corpus(keys)
        return keys

    def _sync_model(self, model_key: str, model_info, seen_at=None) -> Tuple[bool, bool]:
        """
        Sync a single model to the database.

        `seen_at` : l'instant où la découverte a relevé le disque. Une ligne DÉSINSTALLÉE après
        cet instant n'est pas réécrite — le relevé est plus vieux que le retrait (2026-10-11 :
        une synchro partie avant la désinstallation de PaddleOCR-VL l'a remise « téléchargée »
        sept minutes après, fichiers absents, marque `uninstalled_at` effacée).

        Returns:
            Tuple of (created, updated)
        """
        from ..models import AIModel, EXECUTION_LOCAL

        # Description courte : explicite si fournie, sinon dérivée du long (1re phrase,
        # tronquée à 200c) → le catalogue a toujours un court exploitable pour l'UI.
        long_desc = model_info.description or ''
        short_desc = getattr(model_info, 'description_short', '') or ''
        if not short_desc and long_desc:
            short_desc = long_desc.split('. ')[0].strip()
            if len(short_desc) > 200:
                short_desc = short_desc[:197].rstrip() + '…'

        defaults = {
            'name': model_info.name,
            'model_type': model_info.model_type.value,
            'source': model_info.source.value,
            'description': long_desc,
            'description_short': short_desc,
            'vram_gb': model_info.vram_gb or 0,
            'ram_gb': model_info.ram_gb or 0,
            'is_downloaded': model_info.is_downloaded,
            'is_loaded': model_info.is_loaded,
            # `is_available` VOLONTAIREMENT absent : le champ vaut True par défaut, donc une
            # ligne NEUVE naît disponible — mais le sync ne le REMET pas à True sur une ligne
            # existante. Un `False` y est une DÉCISION HUMAINE (« ce modèle n'est pas adapté »,
            # cf. face_yolov8m-seg_60, modèle adetailer qui trouve 0 visage sur une scène de
            # rue), et la découverte n'a pas autorité pour l'écraser — même principe que
            # `platform_ref`/`quality_index` (2026-08-12). L'ABSENCE de fichier reste traitée par
            # `remove_missing`, qui pose False ; réactiver un modèle écarté est donc explicite.
            'format': model_info.format or '',
            'preferred_format': model_info.preferred_format or '',
            'can_convert_to': model_info.can_convert_to or [],
            'backend_ref': model_info.backend_ref or '',
            # Où il s'exécute et ce qu'il coûte : dits par la découverte depuis que les modèles
            # distants sont découverts comme les autres (2026-09-18) ; local et gratuit par défaut.
            'execution': getattr(model_info, 'execution', '') or EXECUTION_LOCAL,
            'cost_tier': getattr(model_info, 'cost_tier', '') or '',
            'extra_info': model_info.extra_info or {},
            # Canonicalisation CENTRALISÉE des capacités (vocabulaire unique) au point d'entrée du
            # catalogue : dérive `languages`/`supports_*`, mappe les clés legacy (native_diarization→
            # supports_diarization) et laisse les clés inconnues intactes. Ainsi le catalogue DB est
            # canonique quel que soit ce qu'émet `_discover_*` (résidu source tracé dans REMOVAL_LEDGER
            # R1/R2, à nettoyer en fin de parcours). Cf. common/utils/model_capabilities.py.
            'last_synced_at': timezone.now(),
        }

        # ── Champs que la découverte n'a PAS autorité pour EFFACER ────────────────────────────
        # `hf_id` et `quality_index` étaient dans `defaults` avec un repli `or ''` / `or None` :
        # à chaque sync, tout modèle dont la découverte n'en porte pas (les 70 issus du scan
        # disque) voyait sa valeur REMISE À VIDE. Conséquences mesurées le 2026-08-12 :
        #   • une provenance vérifiée posée par `backfill_platform_refs --poser` ne survivait pas
        #     au sync suivant — la porte d'entrée était donc inopérante ;
        #   • `quality_index` contredisait sa propre docstring (« une valeur posée à la main
        #     PRIME »), qui était vraie jusqu'au prochain `sync_models`.
        # On n'écrit donc QUE lorsque la découverte a réellement quelque chose à dire. Un modèle
        # dont l'amont perd son identité se corrige explicitement, pas par effet de bord.
        # (`license` n'a jamais été dans `defaults` — il survivait déjà.)
        # `platform_ref` remplace `hf_id` ici (2026-10-27, décision de Fabien : « ne garder que
        # `platform_ref` ») : c'est le même fait, que la déclaration porte désormais sous ce nom —
        # écrit quand la découverte le DIT, jamais effacé par son silence. La colonne `hf_id` n'est
        # plus écrite que par la projection du manifeste, et part avec elle.
        if model_info.platform_ref:
            defaults['platform_ref'] = model_info.platform_ref
        # A priori DÉCLARÉ avec sa source (`model_quality.DECLARED_PRIORS`, 2026-10-03) quand la
        # découverte n'en dit rien — versionné, sourcé, au lieu d'une valeur posée à la main en base.
        from .model_quality import declared_prior
        _qualite = getattr(model_info, 'quality_index', None) or declared_prior(model_key)
        if _qualite:
            defaults['quality_index'] = _qualite
        # `capabilities` REJOINT cette famille (2026-08-31) — c'était le DERNIER champ que la
        # découverte effaçait sans avoir rien à dire, et ça bloquait toute la route F4b.
        # Un modèle installé par la prospection et catalogué par le balayage GÉNÉRIQUE des
        # snapshots HF n'est déclaré par aucune app : sa découverte émet `{}`. En écrivant ce
        # `{}` dans `defaults`, chaque sync effaçait les capacités posées par son MANIFESTE —
        # le modèle restait donc invisible d'un filtre par capacité, à jamais (mesuré le
        # 2026-08-31 sur Kokoro-ONNX / chatterbox / Audio8 : catalogués, licenciés, avec
        # `composition`, et sans une seule capacité).
        # Règle INCHANGÉE pour tout le reste : quand la découverte SAIT (une app déclare le
        # modèle), elle écrit et fait autorité — c'est elle qui connaît les flags des backends.
        # Ce qui change : un `{}` ne veut pas dire « aucune capacité », il veut dire « je n'en
        # sais rien » — et on n'efface pas un fait sur une absence de savoir.
        # Et depuis le 2026-09-18 la découverte n'écrase plus que les CLÉS qu'elle émet : ce qu'un
        # manifeste a posé (modalités, langues, entrées d'un modèle orphelin) survit au sync, comme
        # `composition` ou `license`. Sur ses propres clés, elle fait autorité — d'où les drapeaux
        # Ollama écrits vrais OU faux (`_capacites_canoniques`), pour qu'une capacité perdue ne
        # survive pas par absence.
        _caps = normalize_capabilities(getattr(model_info, 'capabilities', None) or {})
        if _caps:
            _prior = (AIModel.objects.filter(model_key=model_key)
                      .values_list('capabilities', flat=True).first()) or {}
            defaults['capabilities'] = {**_prior, **_caps}
        # `composition` : MÊME RÈGLE, et pour la même raison (2026-09-01). La découverte sait
        # désormais dire le moteur d'exécution d'un modèle déclaré par une app
        # (`SYNTHESIZER_MODELS[*]['engine']` → `runtime.engine`), mais elle n'en sait toujours
        # rien pour les modèles orphelins : ceux-là tiennent leur `composition` de leur MANIFESTE
        # (anatomie des composants, moteur), et un `{}` de découverte ne doit pas l'effacer.
        # C'est exactement la règle « ne jamais écraser un fait curé par une absence » que la
        # clôture du 31/08 signalait comme MANQUANTE pour le kind `library` — elle vaut ici aussi.
        _compo = getattr(model_info, 'composition', None) or {}
        if _compo:
            defaults['composition'] = _compo

        # PROVENANCE de `vram_gb` (décision A, 16/09) : dite par le rédacteur (`ModelInfo`), écrite
        # ICI, au point unique par lequel toute découverte passe — 19 rédacteurs, une seule
        # écriture. Seulement quand un chiffre est posé : « 0 » veut dire inconnu, il n'a pas de
        # provenance. Un `ModelInfo` d'avant ce champ (jumelles, tests) vaut `declared`.
        if defaults['vram_gb']:
            defaults['extra_info'] = {**defaults['extra_info'],
                                      'vram_provenance': getattr(model_info, 'vram_provenance', '')
                                      or 'declared'}

        # Add local_path if available in extra_info
        if model_info.extra_info and 'path' in model_info.extra_info:
            defaults['local_path'] = str(model_info.extra_info['path'])

        # Get disk_gb from extra_info if available.
        # Les trois clés sont TOUTES émises par la découverte, selon la branche : `disk_gb`
        # (ollama), `size_mb` (enhancer/ONNX), `size_bytes` (anonymizer/YOLO, model_registry:502).
        # `size_bytes` manquait ici → les 48 modèles de l'anonymizer sortaient à disk_gb=0 alors
        # que la taille était portée. Mesuré le 2026-08-12 : 19/101 renseignés, dont 0 anonymizer.
        if model_info.extra_info:
            if 'disk_gb' in model_info.extra_info:
                defaults['disk_gb'] = model_info.extra_info['disk_gb']
            elif 'size_mb' in model_info.extra_info:
                defaults['disk_gb'] = model_info.extra_info['size_mb'] / 1024
            elif 'size_bytes' in model_info.extra_info:
                defaults['disk_gb'] = (model_info.extra_info['size_bytes'] or 0) / (1024 ** 3)

        # Log what we're syncing
        logger.info(
            f"[ModelSync] Syncing {model_key}: "
            f"format={defaults.get('format', 'EMPTY')!r}, "
            f"preferred_format={defaults.get('preferred_format', 'EMPTY')!r}, "
            f"vram_gb={defaults.get('vram_gb', 0)}"
        )

        # Préserver les clés "collantes" de extra_info écrites hors découverte (détecteur de MAJ
        # check_model_updates, décisions admin) : le sync réécrit extra_info → sans ça il les efface.
        # `exclusion` rejoint les clés collantes (2026-08-12) : elle porte la RAISON d'un
        # `is_available=False` décidé par un humain. Sans elle, la décision survivait mais sa
        # justification était effacée au sync suivant — un modèle écarté sans qu'on sache
        # pourquoi finit par être réactivé « au cas où ».
        # `vram_measured` (2026-09-14) : l'empreinte MESURÉE au chargement, rendue au catalogue par
        # `persist_measured_vram`. La découverte n'en sait rien — elle l'effacerait à chaque synchro,
        # et la mesure redeviendrait l'information « produite à chaque chargement puis jetée ».
        # `weights` (2026-09-19, décision A) : le POIDS PAR COMPOSANT lu dans les fichiers installés,
        # rendu par `persist_weights` — même nature que la mesure : produit hors découverte.
        # `publications` (2026-10-10) : les articles que la carte de l'éditeur rattache au modèle,
        # projetés par le manifeste — la découverte ne les connaît pas.
        _sticky = ('update_check', 'recommended', 'exclusion', 'vram_measured', 'weights',
                   'publications')
        _existing = AIModel.objects.filter(model_key=model_key).values_list('extra_info', flat=True).first()
        if seen_at and _uninstalled_after((_existing or {}).get('uninstalled_at'), seen_at):
            logger.info(f"[ModelSync] {model_key}: désinstallé après le relevé — ligne laissée")
            return False, False
        if _existing:
            _merged = dict(defaults.get('extra_info') or {})
            for _k in _sticky:
                if _k in _existing and _k not in _merged:
                    _merged[_k] = _existing[_k]
            # Le modèle CANONIQUE d'une quantification (`base_model` + `base_model_relation`,
            # vocabulaire du Hub, 2026-10-27) : posé par le manifeste à l'installation d'un GGUF,
            # que la découverte d'Ollama ne connaît pas. Collant comme `publications`, mais par
            # PAIRE et seulement s'il porte sa relation : le `base_model` d'une LoRA (sa dorsale)
            # vient de la déclaration de l'app, qui garde l'autorité dessus.
            if 'base_model_relation' in _existing and 'base_model_relation' not in _merged:
                for _k in ('base_model', 'base_model_relation'):
                    if _k in _existing:
                        _merged[_k] = _existing[_k]
            defaults['extra_info'] = _merged

        obj, created = AIModel.objects.update_or_create(
            model_key=model_key,
            defaults=defaults
        )
        self._reconcile_engine_flags(obj)

        # If not created, it was updated
        updated = not created

        logger.debug(f"[ModelSync] {model_key}: created={created}, updated={updated}")
        return created, updated

    def _reconcile_engine_flags(self, obj) -> bool:
        """Le MOTEUR fait autorité sur ce qu'il DÉCLARE — pour TOUTE ligne dont il se résout.

        La règle existait (`merged_capabilities`, ex-`_capabilities_projectable`, 2026-08-31 : *« c'est la DÉCOUVERTE
        qui fait autorité — elle lit les flags sur les classes de backend »*), mais elle ne
        s'exerçait que sur les modèles qu'une APP déclare (`_tts_caps`, 4 moteurs). Une ligne
        PROSPECTÉE (`huggingface:…`) recevait ses capacités de son manifeste, puis plus rien
        ne relisait jamais la classe — même quand elle se résout.

        Conséquence mesurée le 2026-09-12 : `Audio8` au catalogue `supports_cloning=True`,
        son backend `False` (délibéré, motivé dans sa docstring) ; `Qwen3-TTS` muet au
        catalogue, `False` au backend. L'UI offrait les voix clonées, les moteurs les
        ignoraient en silence. *Un filtre qui s'absente ne lève pas ; il rend l'UI permissive.*

        Ce qui délimite l'autorité : `apply_engine_flags` ne touche que ce que la classe
        DÉCLARE dans son propre corps — le défaut du contrat commun n'écrase jamais un
        manifeste. Sans classe résolue (chatterbox : moteur sans code chargé), rien ne change.
        Rend True si la ligne a été réécrite.
        """
        try:
            from wama.common.backends.manager import backend_for_model
            from wama.common.utils.model_capabilities import apply_engine_flags
            cls = backend_for_model(obj)
        except Exception as e:                   # jamais bloquant pour la synchro
            logger.debug(f"[ModelSync] {obj.model_key}: moteur non résolu ({e})")
            return False
        if cls is None:
            return False
        avant = dict(obj.capabilities or {})
        apres = apply_engine_flags(avant, cls)
        if apres == avant:
            return False
        obj.capabilities = apres
        obj.save(update_fields=['capabilities'])
        logger.info(f"[ModelSync] {obj.model_key}: capacités réalignées sur {cls.__name__} "
                    f"(supports_cloning {avant.get('supports_cloning')!r} → "
                    f"{apres.get('supports_cloning')!r})")
        return True

    def sync_file_change(
        self,
        file_path: Path,
        is_added: bool,
        source: str = None
    ) -> bool:
        """
        Sync a single file change (from watchdog).

        Args:
            file_path: Path to the model file
            is_added: True if file was added, False if removed
            source: Source identifier (will be auto-detected if None)

        Returns:
            True if sync was successful
        """
        from ..models import AIModel, ModelSyncLog

        try:
            if source is None:
                source = self._path_to_source(file_path)

            if source is None:
                logger.debug(f"Could not determine source for {file_path}")
                return False

            model_key = f"{source}:{file_path.stem}"

            if is_added:
                # Create or update model entry
                model_info = self._create_model_info_from_path(file_path, source)
                if model_info:
                    self._sync_model(model_key, model_info)
                    logger.info(f"Synced new model: {model_key}")
            else:
                # Mark model as not downloaded (don't delete - keep in catalog)
                AIModel.objects.filter(model_key=model_key).update(
                    is_downloaded=False,
                    is_loaded=False,
                    updated_at=timezone.now()
                )
                logger.info(f"Marked model as not downloaded: {model_key}")

            return True

        except Exception as e:
            logger.error(f"Error syncing file change for {file_path}: {e}")
            return False

    def _path_to_source(self, path: Path) -> Optional[str]:
        """Determine source from file path."""
        path_str = str(path).lower()

        if 'enhancer' in path_str or 'upscal' in path_str:
            return 'enhancer'
        elif 'anonymizer' in path_str or 'yolo' in path_str or 'sam' in path_str:
            return 'anonymizer'
        elif 'imager' in path_str or 'diffusion' in path_str or 'wan' in path_str:
            return 'imager'
        elif 'transcriber' in path_str or 'whisper' in path_str:
            return 'transcriber'
        elif 'synthesizer' in path_str or 'tts' in path_str or 'coqui' in path_str:
            return 'synthesizer'
        elif 'describer' in path_str or 'blip' in path_str or 'bart' in path_str:
            return 'describer'
        elif 'vision' in path_str:
            return 'anonymizer'
        elif 'speech' in path_str:
            return 'transcriber'

        return None

    def _create_model_info_from_path(self, path: Path, source: str):
        """Create a ModelInfo-like object from file path."""
        from .model_registry import ModelInfo, ModelType, ModelSource

        # Map source string to enums
        source_mapping = {
            'enhancer': (ModelSource.WAMA_ENHANCER, ModelType.UPSCALING),
            'anonymizer': (ModelSource.WAMA_ANONYMIZER, ModelType.VISION),
            'imager': (ModelSource.WAMA_IMAGER, ModelType.DIFFUSION),
            'transcriber': (ModelSource.WAMA_TRANSCRIBER, ModelType.SPEECH),
            'synthesizer': (ModelSource.WAMA_SYNTHESIZER, ModelType.SPEECH),
            'describer': (ModelSource.WAMA_DESCRIBER, ModelType.VLM),
        }

        model_source, model_type = source_mapping.get(
            source,
            (ModelSource.WAMA_IMAGER, ModelType.DIFFUSION)
        )

        # Get file info
        try:
            file_size_mb = path.stat().st_size / (1024 * 1024)
        except OSError:
            file_size_mb = 0

        format_type = path.suffix.lstrip('.').lower()

        # Determine preferred format from policy
        from wama.common.utils.format_policy import get_preferred_format
        category = source if source != 'anonymizer' else 'vision'
        preferred = get_preferred_format(category)

        return ModelInfo(
            id=f"{source}:{path.stem}",
            name=path.stem,
            model_type=model_type,
            source=model_source,
            description=f"Discovered model ({file_size_mb:.1f}MB)",
            is_downloaded=True,
            format=format_type,
            preferred_format=preferred,
            extra_info={
                'path': str(path),
                'size_mb': file_size_mb,
                'auto_discovered': True,
            }
        )

    def update_download_status(self, model_key: str, is_downloaded: bool) -> bool:
        """Update the download status of a model."""
        from ..models import AIModel

        try:
            updated = AIModel.objects.filter(model_key=model_key).update(
                is_downloaded=is_downloaded,
                updated_at=timezone.now()
            )
            return updated > 0
        except Exception as e:
            logger.error(f"Error updating download status for {model_key}: {e}")
            return False

    def update_loaded_status(self, model_key: str, is_loaded: bool) -> bool:
        """Update the loaded status of a model."""
        from ..models import AIModel

        try:
            update_fields = {
                'is_loaded': is_loaded,
                'updated_at': timezone.now()
            }
            if is_loaded:
                update_fields['last_used_at'] = timezone.now()

            updated = AIModel.objects.filter(model_key=model_key).update(**update_fields)
            return updated > 0
        except Exception as e:
            logger.error(f"Error updating loaded status for {model_key}: {e}")
            return False

    def persist_measured_vram(self) -> int:
        """
        Rend au CATALOGUE les empreintes VRAM mesurées au chargement (2026-09-14).

        La mesure existait depuis le 29/07 (`_wrap_load` : delta `torch.cuda.memory_allocated`)
        mais ne servait qu'au registre à TTL du gouverneur, puis était jetée : `vram_gb` restait
        déclaré ou estimé, et `vram_estimated` ne se levait jamais. Le gouverneur recueille
        désormais chaque mesure (`record_measured_vram`) dans TOUS les process — service TTS
        compris, qui n'a pas d'ORM — et ce geste la résout vers sa clé catalogue. Depuis le
        2026-10-20, les modèles de l'Ollama hôte aussi (`ModelRegistry.measure_ollama_load`,
        détenteur `ollama-host#ollama:<nom>`, dont le suffixe EST la clé).

        ⚠ `vram_gb` N'EST PAS TOUCHÉ : il reste la valeur déclarée/estimée que la découverte
        réécrit et que le tirage lit. La mesure vit à part, en clé collante
        (`extra_info['vram_measured']` : `last_gb`, `max_gb`, `n` relevés persistés, `at`). C'est
        une empreinte AU CHARGEMENT, pas un pic d'exécution — un chargement avec offload mesure
        moins.

        Une mesure dont la clé ne se résout pas reste au gouverneur : nouvel essai au passage
        suivant, jusqu'à son expiration. Rend le nombre de lignes du catalogue mises à jour.
        """
        from datetime import datetime, timezone as dt_timezone

        from wama.common.services.resource_governor import (
            forget_measured_vram, measured_vram, model_keys_of)
        from ..models import AIModel

        ecrites, rendues = 0, {}
        for owner, (gb, stamp) in measured_vram().items():
            cles = model_keys_of(owner)
            if not cles:
                continue
            for cle in cles:
                with transaction.atomic():
                    obj = AIModel.objects.select_for_update().filter(model_key=cle).first()
                    if obj is None:
                        continue
                    info = dict(obj.extra_info or {})
                    prec = info.get('vram_measured') or {}
                    info['vram_measured'] = {
                        'last_gb': round(gb, 2),
                        'max_gb': round(max(gb, float(prec.get('max_gb') or 0)), 2),
                        'n': int(prec.get('n') or 0) + 1,
                        'at': datetime.fromtimestamp(stamp, tz=dt_timezone.utc).isoformat(),
                    }
                    AIModel.objects.filter(pk=obj.pk).update(extra_info=info)
                    ecrites += 1
            rendues[owner] = stamp
        # Oublier seulement ce qui a été rendu — et seulement si aucune mesure plus récente n'a
        # remplacé la ligne entre la lecture et l'écriture (comparaison d'horodatage).
        forget_measured_vram(rendues)
        return ecrites

    def persist_weights(self, keys=None) -> int:
        """
        Rend au CATALOGUE le POIDS PAR COMPOSANT des modèles installés (décision A de Fabien,
        16/09 : « deux chiffres par modèle — poids par composant lus dans les fichiers sans
        charger, et pic selon la stratégie »). Ici le PREMIER chiffre, celui des fichiers.

        UN SEUL lecteur des poids, celui de l'installation : `prospector.local_inventory` (les
        blobs du snapshot, chacun une fois) → `model_installer.components_for_spec` (la
        composition DÉCLARÉE de la ligne tranche les rôles ; sans elle, la convention de dépôt,
        marquée `source='repo'` — une borne, pas une empreinte). Ce geste n'ajoute AUCUNE règle
        de pesée : il relie une ligne à son snapshot (`local_path` s'il en nomme un, sinon
        `model_locations.installed_snapshots`) et écrit le résultat.

        ⚠ `vram_gb` N'EST PAS TOUCHÉ (comme pour la mesure) : `weights` vit à part, en clé
        collante — `components` (Go par rôle), `total_gb` (tout sur la carte), `largest_gb` (le
        déchargement séquentiel n'en tient qu'un à la fois), `source`, `variants`/`unresolved`
        s'il y a lieu, `precision` ({rôle: {params, dtypes}}, en-têtes safetensors — 2026-09-20),
        `at`, `signature`. Marge d'activations et stratégie restent à
        `memory_manager` ; la cascade du tirage (mesuré → source → estimé) lira ici.

        Pas de réécriture inutile : la `signature` (fichiers, octets, composition) est gardée
        avec le relevé ; tant qu'elle ne bouge pas, ni la dérivation ni l'écriture ne sont
        refaites — et les dépôts FRÈRES déclarés (pyannote, codeformer, DeepFace : une requête
        HF chacun) ne sont interrogés qu'au changement. `keys` : restreindre à ces clés.
        Rend le nombre de lignes écrites.
        """
        import hashlib
        import json
        from datetime import datetime, timezone as dt_timezone
        from pathlib import Path

        from wama.common.external_sources import HUGGINGFACE
        from wama.common.utils.model_locations import installed_snapshots
        from ..models import AIModel, EXECUTION_LOCAL
        from .model_installer import components_for_spec
        from .prospector import local_inventory, local_revision, precision_of_files

        qs = AIModel.objects.filter(is_downloaded=True, is_proposed=False, execution=EXECUTION_LOCAL,
                                    platform_ref__startswith=f'{HUGGINGFACE}:')
        if keys is not None:
            qs = qs.filter(model_key__in=list(keys))
        rows = list(qs.only('pk', 'model_key', 'platform_ref', 'local_path', 'composition', 'extra_info'))
        if not rows:
            return 0
        index = installed_snapshots()
        written = 0
        for obj in rows:
            root = None
            local = Path(obj.local_path) if obj.local_path else None
            if local is not None and local.name.startswith('models--') and local.is_dir():
                root = local
            root = root or index.get(obj.hf_repo.lower())
            files = local_inventory(root) if root else None
            if not files:
                continue
            composition = obj.composition or {}
            # `v2` (2026-09-20) : la précision par composant rejoint le relevé — un relevé d'avant
            # se refait une fois, puis se tait de nouveau.
            signature = 'v2:{}:{}:{}'.format(
                len(files), sum(s for _, s in files),
                hashlib.sha1(json.dumps(composition, sort_keys=True).encode()).hexdigest()[:10])
            previous = (obj.extra_info or {}).get('weights') or {}
            if previous.get('signature') == signature:
                continue
            spec = {'kind': 'hf', 'ref': obj.hf_repo}
            if composition:
                spec['composition'] = composition
            derived = components_for_spec(spec, files=files)
            declared_unmatched = False
            if not derived and composition:
                # La déclaration ne désigne AUCUN fichier de ce snapshot — mesuré le 2026-09-20 sur
                # SDXL : installé en fp16 (`unet/diffusion_pytorch_model.fp16.safetensors`), déclaré
                # sur les fichiers pleine précision. C'est le cas « variante installée ≠ anatomie
                # déclarée » ; on pèse par la convention de dépôt et on le DIT, plutôt que de laisser
                # un relevé périmé ou de se taire.
                derived = components_for_spec({'kind': 'hf', 'ref': obj.hf_repo}, files=files)
                declared_unmatched = bool(derived)
            if not derived:
                continue
            # La PRÉCISION par composant (paramètres, dtypes) lue dans les en-têtes des fichiers
            # que la dérivation a retenus — c'est ce qui rend le pic par précision calculable
            # (17,43 Md × 2 octets = 32,5 Go en BF16, 16,2 en 8 bits). Les chemins eux-mêmes ne
            # sont pas gardés : ils se retrouvent à la demande, le relevé reste compact.
            record = {k: v for k, v in derived.items() if k != 'files'}
            if declared_unmatched:
                record['declared_unmatched'] = True
            precision = precision_of_files(local_revision(root), derived.get('files'))
            if precision:
                record['precision'] = precision
            with transaction.atomic():
                fresh = AIModel.objects.select_for_update().filter(pk=obj.pk).first()
                if fresh is None:
                    continue
                info = dict(fresh.extra_info or {})
                info['weights'] = {**record, 'signature': signature, 'root': str(root),
                                   'at': datetime.now(dt_timezone.utc).isoformat()}
                AIModel.objects.filter(pk=obj.pk).update(extra_info=info)
                written += 1
        return written

    def get_stats(self) -> Dict:
        """Get catalog statistics."""
        from ..models import AIModel

        total = AIModel.objects.filter(is_available=True).count()
        downloaded = AIModel.objects.filter(is_available=True, is_downloaded=True).count()
        loaded = AIModel.objects.filter(is_available=True, is_loaded=True).count()

        by_source = {}
        for source in AIModel.objects.filter(is_available=True).values_list(
            'source', flat=True
        ).distinct():
            by_source[source] = {
                'total': AIModel.objects.filter(source=source, is_available=True).count(),
                'downloaded': AIModel.objects.filter(
                    source=source, is_available=True, is_downloaded=True
                ).count(),
            }

        by_type = {}
        for model_type in AIModel.objects.filter(is_available=True).values_list(
            'model_type', flat=True
        ).distinct():
            by_type[model_type] = AIModel.objects.filter(
                model_type=model_type, is_available=True
            ).count()

        return {
            'total': total,
            'downloaded': downloaded,
            'loaded': loaded,
            'by_source': by_source,
            'by_type': by_type,
        }


# Singleton instance
_sync_service: Optional[ModelSyncService] = None


def get_sync_service() -> ModelSyncService:
    """Get the singleton ModelSyncService instance."""
    global _sync_service
    if _sync_service is None:
        _sync_service = ModelSyncService()
    return _sync_service
