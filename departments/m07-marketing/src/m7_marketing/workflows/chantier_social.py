from pathlib import Path

import yaml

from opsys import taxonomie

from ..brand import profil_client as brand_profil_client
from ..content import approval
from ..content.factory import build_content_item
from ..social.postiz_adapter import AdapterDisabled, Canal, NotAutorise, PostizAdapter, SocialPost

_HERE = Path(__file__).resolve().parent  # m7_marketing/workflows
_PKG = _HERE.parent  # m7_marketing

__all__ = ["orchestrer_chantier_vers_social"]

# PLAN T0.13-b : un chantier porte la nature de ses travaux sous l'une de DEUX formes, comme le
# LeadQualifie dont il vient. La version est EXPLICITE (jamais devinée) : sans `schema_version`, un chantier
# v1 (`type_travaux`, énuméré ci-dessous, celui du contrat gelé sans `autre`) ; avec `schema_version: 2`, un
# chantier v2 (`service`, code d'un service déclaré par le profil d'entreprise, `opsys.taxonomie`). Un
# chantier sans version qui porte `service`, ou un chantier v2 qui porte `type_travaux`, est refusé :
# aucune des deux clés n'est déduite de l'autre.
TYPES_TRAVAUX_V1 = ("renovation_totale", "extension", "ravalement", "isolation_thermique")
VERSION_CHANTIER_V2 = 2


def _nature_des_travaux(chantier: dict) -> tuple[str, str]:
    """`(libellé pour le titre, mot-clé)` de la nature des travaux du chantier, validée selon la version
    qu'il déclare. Lève `ValueError` nommé (fail-closed) : jamais un repli sur une valeur par défaut."""
    if "schema_version" not in chantier:
        if "service" in chantier:
            raise ValueError(
                "service n'existe pas en v1 : déclare 'schema_version: 2' (chantier v2) ou remplace "
                "'service' par 'type_travaux' (chantier v1) — la version n'est jamais devinée"
            )
        types_valides = set(TYPES_TRAVAUX_V1)
        type_travaux = chantier.get("type_travaux")
        if type_travaux not in types_valides:
            raise ValueError(
                f"type_travaux invalide : {type_travaux!r} "
                f"(attendus : {', '.join(sorted(types_valides))})"
            )
        return type_travaux.replace("_", " ").capitalize(), type_travaux

    version = chantier["schema_version"]
    if type(version) is not int or version != VERSION_CHANTIER_V2:
        raise ValueError(f"schema_version invalide : {version!r} (attendu : {VERSION_CHANTIER_V2})")
    if "type_travaux" in chantier:
        raise ValueError("un chantier v2 porte 'service', pas 'type_travaux' : aucune des deux clés n'est déduite")
    service, verdict = taxonomie.valider_service(chantier.get("service"))
    if verdict is not None:
        raise ValueError(f"service invalide : {verdict['code']} : {verdict['detail']}")
    return service.libelle, service.code


def _charger_brand():
    """Charge le profil de marque du CLIENT, fail-closed (PLAN T4.3, M7-audit.md §2.1) : jamais
    le gabarit par défaut. Lève `ValueError` nommé si le fichier est absent ou si le profil n'est
    pas encore configuré (encore `brand.profil_client.PLACEHOLDER_NOM`)."""
    profil, motif = brand_profil_client.charger_profil_client()
    if profil is None:
        raise ValueError(motif)
    return profil


def orchestrer_chantier_vers_social(
    chemin_chantier: str,
    timestamp: str,
    acteur_propose: str,
    acteur_approuve: str,
    adapter_config: dict | None = None,
) -> dict:
    """Point d'entrée unique du workflow chantier -> contenu social.

    Args:
        chemin_chantier: Chemin vers le fichier chantier.yaml.
        timestamp: Horodatage ISO-8601 fourni par l'appelant.
        acteur_propose: Identifiant de l'acteur proposant le contenu.
        acteur_approuve: Identifiant de l'acteur approuvant le contenu (doit être différent).
        adapter_config: Configuration pour PostizAdapter (défaut: {"enabled": True, "dry_run": False}).

    Returns:
        Un dictionnaire contenant chantier_slug, etapes et metriques.

    Raises:
        ValueError: Si la fixture n'a pas ``fictif: true``, ou si la nature de ses travaux est
            invalide pour la version qu'elle déclare (``type_travaux`` v1, ``service`` v2).
    """
    # ------------------------------------------------------------------
    # 1. Chargement et validation de la fixture
    # ------------------------------------------------------------------
    chemin = Path(chemin_chantier)
    with open(chemin, encoding="utf-8") as f:
        chantier = yaml.safe_load(f)

    if not chantier.get("fictif"):
        raise ValueError("La fixture doit avoir 'fictif: true'")

    # Nature des travaux : type_travaux (chantier v1, énuméré fermé) ou service (chantier v2, taxonomie).
    travaux_titre, travaux_mot_cle = _nature_des_travaux(chantier)

    slug = chemin.parent.name  # slug du chantier (ex: residence-quebec-2026)

    # Initialisation des métriques et de la liste d'étapes
    metriques = {
        "chantiers_traites": 0,
        "contenus_proposes": 0,
        "publications_bloquees_gated": 0,
    }
    etapes: list[dict] = []

    # ------------------------------------------------------------------
    # 2. Étape charge (le chargement a réussi, on trace l'étape)
    # ------------------------------------------------------------------
    etapes.append(
        {
            "nom": "charge",
            "statut": "SUCCES",
            "detail": "Chantier chargé avec succès",
        }
    )

    # ------------------------------------------------------------------
    # 3. Étape compose — inclut le chargement fail-closed du profil de marque du CLIENT
    # (PLAN T4.3, M7-audit.md §2.1) : jamais le gabarit par défaut, sans ajouter d'étape au
    # chemin de succès (le contrat "5 étapes" de ce workflow reste inchangé).
    # ------------------------------------------------------------------
    try:
        brand = _charger_brand()
        sujet = {
            "titre": f"{travaux_titre} à {chantier['ville']}",
            "description": chantier["description_factuelle"],
            "mots_cles": [travaux_mot_cle, chantier["ville"]],
        }
        item = build_content_item(
            brand,
            surface="google_aio",
            type="post_social",
            sujet=sujet,
            timestamp=timestamp,
        )
        etapes.append({"nom": "compose", "statut": "SUCCES", "detail": item})
    except Exception as e:
        etapes.append({"nom": "compose", "statut": "ECHEC", "detail": str(e)})
        metriques["chantiers_traites"] = 1
        return {
            "chantier_slug": slug,
            "etapes": etapes,
            "metriques": metriques,
        }

    # ------------------------------------------------------------------
    # 4. Étape propose
    # ------------------------------------------------------------------
    try:
        item = approval.propose(item, acteur_propose, timestamp)
        etapes.append(
            {"nom": "propose", "statut": "SUCCES", "detail": item}
        )
        metriques["contenus_proposes"] = 1
    except Exception as e:
        etapes.append({"nom": "propose", "statut": "ECHEC", "detail": str(e)})
        metriques["chantiers_traites"] = 1
        return {
            "chantier_slug": slug,
            "etapes": etapes,
            "metriques": metriques,
        }

    # ------------------------------------------------------------------
    # 5. Étape approuve
    # ------------------------------------------------------------------
    try:
        item = approval.approve(item, acteur_approuve, timestamp)
        etapes.append(
            {"nom": "approuve", "statut": "SUCCES", "detail": item}
        )
    except Exception as e:
        etapes.append({"nom": "approuve", "statut": "ECHEC", "detail": str(e)})
        metriques["chantiers_traites"] = 1
        return {
            "chantier_slug": slug,
            "etapes": etapes,
            "metriques": metriques,
        }

    # ------------------------------------------------------------------
    # 6. Étape publication (gating)
    # ------------------------------------------------------------------
    if adapter_config is None:
        adapter_config = {"enabled": True, "dry_run": False}

    try:
        adapter = PostizAdapter(adapter_config)
        post = SocialPost(
            canal=Canal.GBP.value,
            texte=item["body"],
            media=chantier.get("photos", []),
            niveau_validation=1,
        )
        pub_result = adapter.publier(post)
        etapes.append(
            {"nom": "publication", "statut": "SUCCES", "detail": pub_result}
        )
    except NotAutorise as e:
        etapes.append(
            {
                "nom": "publication",
                "statut": "BLOQUE",
                "detail": f"NotAutorise capturé : {e}",
            }
        )
        metriques["publications_bloquees_gated"] = 1
    except AdapterDisabled as e:
        etapes.append(
            {
                "nom": "publication",
                "statut": "ECHEC",
                "detail": f"AdapterDisabled : {e}",
            }
        )
        # publications_bloquees_gated reste à 0
    except Exception as e:
        etapes.append(
            {
                "nom": "publication",
                "statut": "ECHEC",
                "detail": str(e),
            }
        )
        # publications_bloquees_gated reste à 0

    metriques["chantiers_traites"] = 1
    return {
        "chantier_slug": slug,
        "etapes": etapes,
        "metriques": metriques,
    }
