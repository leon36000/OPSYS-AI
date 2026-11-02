"""Journal append-only, hash-chaîné, des versions d'apprentissage des durées de M3 (cycle de vie pur).

Le support (``stockage.maillons("m03-estimation", "apprentissage_durees")``) est choisi par l'adaptateur ; ce module ne
connaît qu'un objet « journal » (liste ou registre durable : ``len``, itération, ``append(maillon, rang_attendu=)``)
et ne lit aucune horloge (``maintenant_utc`` est injecté). Patron des journaux voisins (``calibration_versions``) :
chaque maillon porte ``rang``, ``type_entree``, ``charge``, ``hash_precedent`` et ``hash_maillon`` ; relire le
journal le valide ENTIÈREMENT (chaîne, formes, identité des versions recalculée) et un journal altéré rend un
refus, jamais un état partiel.

Cinq types d'entrées :

* ``version_calculee`` : une candidate (rapport de ``apprentissage_durees.calculer_cohorte`` + identité). Son
  ``version_id`` est l'empreinte de son contenu : le même calcul sur les mêmes observations ne s'écrit qu'une fois ;
* ``version_activee`` : sa mise en vigueur, ``auto`` (règle déclarée, sans personne, jamais en mode ombre) ou ``humain``
  (une personne a approuvé : ``approbateur``) ;
* ``version_retiree`` : le retour arrière en UNE opération ; la version précédente de la cohorte redevient la version
  en vigueur (ou le barème, s'il n'y en a pas). Le journal n'efface rien ;
* ``complexite_declaree`` : la difficulté d'un chantier, déclarée par une personne dans une échelle de l'entreprise
  (le chantier n'est inscrit que par son empreinte) ;
* ``performance_calculee`` : l'instantané des indices de rapidité par (équipe, type), à l'usage de M4.

Après un retrait par une personne, la cohorte est GELÉE pour l'automatique (``gel_apres_retrait_humain``) jusqu'à
la prochaine approbation humaine : la machine ne remet jamais en vigueur ce qu'une personne vient de retirer.

Une candidate périmée (calculée alors qu'une autre version était en vigueur) ne s'active pas : ``version_perimee``.
Le retour arrière exige de nommer la version qu'on croit en vigueur (``version_attendue``) : deux personnes ne se
marchent pas dessus.
"""

from __future__ import annotations

import re
from typing import Any

from .apprentissage_durees import decisions, empreinte

__all__ = [
    "activer", "declarer_complexite", "derniere_performance", "enregistrer_calcul",
    "enregistrer_performance", "etat", "evenements", "lire_version", "retirer", "version_active",
]

_TYPES = (
    "version_calculee", "version_activee", "version_retiree", "complexite_declaree", "performance_calculee",
)
_MODES_ACTIVATION = ("auto", "humain")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ENTREES = 5000
_ZERO = "0" * 64
_CLES_MAILLON = {"rang", "type_entree", "charge", "hash_precedent", "hash_maillon"}
_CLES_CALCUL = {
    "version_id", "cohorte", "taux_baseline", "taux_applique", "facteur", "intervalle", "n_chantiers",
    "n_observations", "decision", "raisons", "derive", "regime_depuis_utc", "parent_version_id",
    "politique_sha256", "observations_sha256", "calcule_le", "exclues", "mode_au_calcul",
}
_CLES_ACTIVATION = {
    "version_id", "cohorte", "mode_activation", "approbateur", "taux_baseline", "taux_applique",
    "parent_version_id", "active_le",
}
_CLES_RETRAIT = {"version_id", "cohorte", "retablit_version_id", "par", "raison", "retire_le"}
_CLES_COMPLEXITE = {"chantier_sha256", "complexite", "declare_par", "declare_le"}
_CLES_PERFORMANCE = {"equipes", "strates", "politique_sha256", "calcule_le", "snapshot_sha256"}


def _cle(cohorte: dict[str, Any]) -> str:
    return f"{cohorte['type_service']}\x1f{cohorte['unite_quantite']}"


def _cohorte_valide(cohorte: Any) -> bool:
    return (
        isinstance(cohorte, dict) and set(cohorte) == {"type_service", "unite_quantite"}
        and all(isinstance(v, str) and 0 < len(v) <= 128 for v in cohorte.values())
    )


def _hash_valide(valeur: Any) -> bool:
    return isinstance(valeur, str) and _HASH.fullmatch(valeur) is not None


def _personne(valeur: Any) -> bool:
    return isinstance(valeur, str) and 0 < len(valeur) <= 128 and valeur == valeur.strip()


def _charge_valide(type_entree: str, charge: Any) -> bool:
    if not isinstance(charge, dict):
        return False
    if type_entree == "version_calculee":
        sans_id = {cle: valeur for cle, valeur in charge.items() if cle != "version_id"}
        return (
            set(charge) == _CLES_CALCUL and _cohorte_valide(charge["cohorte"])
            and charge["decision"] in decisions() and _hash_valide(charge["version_id"])
            and charge["version_id"] == empreinte(sans_id)
            and (charge["parent_version_id"] is None or _hash_valide(charge["parent_version_id"]))
            and isinstance(charge["raisons"], list) and isinstance(charge["taux_applique"], str)
            and isinstance(charge["taux_baseline"], str)
        )
    if type_entree == "version_activee":
        return (
            set(charge) == _CLES_ACTIVATION and _cohorte_valide(charge["cohorte"])
            and _hash_valide(charge["version_id"])
            and charge["mode_activation"] in _MODES_ACTIVATION
            and (_personne(charge["approbateur"]) if charge["mode_activation"] == "humain"
                 else charge["approbateur"] is None)
            and (charge["parent_version_id"] is None or _hash_valide(charge["parent_version_id"]))
        )
    if type_entree == "version_retiree":
        return (
            set(charge) == _CLES_RETRAIT and _cohorte_valide(charge["cohorte"]) and _hash_valide(charge["version_id"])
            and (charge["retablit_version_id"] is None or _hash_valide(charge["retablit_version_id"]))
            and _personne(charge["par"]) and isinstance(charge["raison"], str) and 0 < len(charge["raison"]) <= 300
        )
    if type_entree == "complexite_declaree":
        return (
            set(charge) == _CLES_COMPLEXITE and _hash_valide(charge["chantier_sha256"])
            and isinstance(charge["complexite"], str) and _personne(charge["declare_par"])
        )
    if type_entree == "performance_calculee":
        return (
            set(charge) == _CLES_PERFORMANCE and isinstance(charge["equipes"], list)
            and isinstance(charge["strates"], list) and _hash_valide(charge["snapshot_sha256"])
            and charge["snapshot_sha256"] == empreinte({"equipes": charge["equipes"], "strates": charge["strates"]})
        )
    return False


def evenements(journal: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Relit et valide tout le journal : ``(maillons, None)`` ou ``(None, raison)``."""
    try:
        if len(journal) > _MAX_ENTREES:
            return None, "journal_limite_depassee"
        entrees = list(journal)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None, "journal_illisible"
    precedent = _ZERO
    for rang, maillon in enumerate(entrees):
        if not isinstance(maillon, dict) or set(maillon) != _CLES_MAILLON:
            return None, "journal_forme_invalide"
        if maillon["rang"] != rang or type(maillon["rang"]) is not int or maillon["hash_precedent"] != precedent:
            return None, "journal_ordre_ou_chaine_invalide"
        if maillon["type_entree"] not in _TYPES or not _charge_valide(maillon["type_entree"], maillon["charge"]):
            return None, "journal_charge_invalide"
        corps = {cle: maillon[cle] for cle in ("rang", "type_entree", "charge", "hash_precedent")}
        if maillon["hash_maillon"] != empreinte(corps):
            return None, "journal_hash_invalide"
        precedent = maillon["hash_maillon"]
    return entrees, None


def _ajouter(
    journal: Any, events: list[dict[str, Any]], type_entree: str, charge: dict[str, Any],
) -> tuple[Any, str | None]:
    corps = {
        "rang": len(events), "type_entree": type_entree, "charge": charge,
        "hash_precedent": events[-1]["hash_maillon"] if events else _ZERO,
    }
    maillon = {**corps, "hash_maillon": empreinte(corps)}
    if not _charge_valide(type_entree, charge):
        return None, "charge_invalide"
    if len(events) >= _MAX_ENTREES:
        return None, "journal_limite_depassee"
    try:
        if isinstance(journal, list):
            journal.append(maillon)
        else:
            journal.append(maillon, rang_attendu=len(events))
    except Exception as exc:  # noqa: BLE001 - un conflit d'écriture durable devient un refus nommé, jamais une exception
        return None, f"ecriture_concurrente:{type(exc).__name__}"
    return maillon, None


# --------------------------------------------------------------------------------------------------- état
def etat(journal: Any) -> tuple[dict[str, Any] | None, str | None]:
    """État rejoué : versions connues, pile d'activation par cohorte (la dernière est en vigueur), déclarations de
    complexité (la plus récente par chantier), dernier instantané de performance."""
    events, raison = evenements(journal)
    if raison or events is None:
        return None, raison
    versions: dict[str, dict[str, Any]] = {}
    piles: dict[str, list[dict[str, Any]]] = {}
    gels: set[str] = set()
    complexites: dict[str, str] = {}
    performance: dict[str, Any] | None = None
    for maillon in events:
        charge = maillon["charge"]
        genre = maillon["type_entree"]
        if genre == "version_calculee":
            versions[charge["version_id"]] = charge
        elif genre == "version_activee":
            piles.setdefault(_cle(charge["cohorte"]), []).append(charge)
            if charge["mode_activation"] == "humain":
                gels.discard(_cle(charge["cohorte"]))
        elif genre == "version_retiree":
            pile = piles.get(_cle(charge["cohorte"]), [])
            if not pile or pile[-1]["version_id"] != charge["version_id"]:
                return None, "journal_retrait_incoherent"
            pile.pop()
            gels.add(_cle(charge["cohorte"]))
        elif genre == "complexite_declaree":
            complexites[charge["chantier_sha256"]] = charge["complexite"]
        elif genre == "performance_calculee":
            performance = charge
    return {"versions": versions, "piles": piles, "gels": gels, "complexites": complexites,
            "performance": performance, "evenements": events}, None


def version_active(journal: Any, type_service: str, unite_quantite: str) -> tuple[dict[str, Any] | None, str | None]:
    """``(version en vigueur ou None, raison)``. La version rendue fusionne la candidate et son activation."""
    contenu, raison = etat(journal)
    if raison or contenu is None:
        return None, raison
    pile = contenu["piles"].get(_cle({"type_service": type_service, "unite_quantite": unite_quantite}), [])
    if not pile:
        return None, None
    activation = pile[-1]
    candidate = contenu["versions"].get(activation["version_id"])
    if candidate is None:
        return None, "journal_activation_sans_candidate"
    return {**candidate, "mode_activation": activation["mode_activation"], "approbateur": activation["approbateur"],
            "active_le": activation["active_le"], "taux_applique": activation["taux_applique"],
            "taux_baseline": activation["taux_baseline"]}, None


def lire_version(journal: Any, version_id: str) -> dict[str, Any] | None:
    contenu, raison = etat(journal)
    if raison or contenu is None:
        return None
    return contenu["versions"].get(version_id)


def derniere_performance(journal: Any) -> tuple[dict[str, Any] | None, str | None]:
    contenu, raison = etat(journal)
    if raison or contenu is None:
        return None, raison
    return contenu["performance"], None


# ------------------------------------------------------------------------------------------------ écritures
def enregistrer_calcul(
    journal: Any, rapport: dict[str, Any], *, politique_sha256: str, maintenant_utc: str, mode: str,
) -> dict[str, Any]:
    """Inscrit une candidate issue de ``calculer_cohorte`` (décisions ``stable`` et ``insuffisante`` incluses : le
    journal montre aussi ce qu'on a décidé de ne pas changer). Idempotent : une candidate de même contenu (donc mêmes
    observations, politique, version parente) rend l'existante."""
    contenu, raison = etat(journal)
    if raison or contenu is None:
        return {"statut": "refuse", "raisons": [raison or "journal_illisible"]}
    cohorte = rapport.get("cohorte")
    if not _cohorte_valide(cohorte) or rapport.get("decision") not in decisions():
        return {"statut": "refuse", "raisons": ["rapport_invalide"]}
    pile = contenu["piles"].get(_cle(cohorte), [])
    taux = rapport.get("taux_appris")
    charge = {
        "cohorte": cohorte, "taux_baseline": rapport["taux_baseline"], "taux_applique": taux or "0",
        "facteur": rapport.get("facteur") or "0", "intervalle": rapport.get("intervalle") or {},
        "n_chantiers": int(rapport.get("n_chantiers_estimation", rapport.get("n_chantiers", 0))),
        "n_observations": int(rapport.get("n_observations", 0)), "decision": rapport["decision"],
        "raisons": list(rapport.get("raisons", [])), "derive": rapport.get("derive") or {},
        "regime_depuis_utc": rapport.get("regime_depuis_utc"),
        "parent_version_id": pile[-1]["version_id"] if pile else None,
        "politique_sha256": politique_sha256, "observations_sha256": rapport.get("observations_sha256") or _ZERO,
        "calcule_le": maintenant_utc, "exclues": rapport.get("exclues") or {}, "mode_au_calcul": mode,
    }
    # Le moment du calcul fait partie du contenu (donc de ``version_id``) mais pas de l'IDENTITÉ : relancer le calcul
    # sur les mêmes observations, la même politique et la même version parente ne crée pas une seconde version.
    identite = _identite(charge)
    for existante in contenu["versions"].values():
        if _identite(existante) == identite:
            return {"statut": "existante", "version": existante}
    charge_finale = {"version_id": empreinte(charge), **charge}
    maillon, raison = _ajouter(journal, contenu["evenements"], "version_calculee", charge_finale)
    if raison:
        return {"statut": "refuse", "raisons": [raison]}
    return {"statut": "inscrite", "version": maillon["charge"]}


def _identite(charge: dict[str, Any]) -> str:
    return empreinte({cle: valeur for cle, valeur in charge.items()
                      if cle not in ("calcule_le", "mode_au_calcul", "version_id")})


def activer(
    journal: Any, version_id: str, *, mode_activation: str, approbateur: str | None, maintenant_utc: str,
    auto_autorise: bool,
) -> dict[str, Any]:
    """Met une candidate en vigueur. ``auto`` : seulement une décision ``auto_applicable`` ET ``auto_autorise`` (le
    mode du département n'est pas l'ombre ; c'est l'adaptateur qui le sait) et jamais avec un approbateur.
    ``humain`` : une personne nommée ; une décision ``auto_applicable`` ou ``approbation_requise`` ; jamais
    ``insuffisante``, ``stable`` ni ``refusee_hors_bornes``. Dans les deux cas la candidate doit avoir été calculée
    alors que la version en vigueur était celle qui l'est encore (``version_perimee`` sinon)."""
    contenu, raison = etat(journal)
    if raison or contenu is None:
        return {"accepte": False, "raisons": [raison or "journal_illisible"]}
    if mode_activation not in _MODES_ACTIVATION:
        return {"accepte": False, "raisons": ["mode_activation_invalide"]}
    candidate = contenu["versions"].get(version_id) if _hash_valide(version_id) else None
    if candidate is None:
        return {"accepte": False, "raisons": ["version_inconnue"]}
    if mode_activation == "auto":
        if approbateur is not None:
            return {"accepte": False, "raisons": ["approbateur_interdit_en_auto"]}
        if not auto_autorise:
            return {"accepte": False, "raisons": ["auto_non_autorise_dans_ce_mode"]}
        if candidate["decision"] != "auto_applicable":
            return {"accepte": False, "raisons": ["decision_non_auto_applicable"]}
        if _cle(candidate["cohorte"]) in contenu["gels"]:
            # Une personne a retiré une version de cette cohorte : la machine ne remet rien en vigueur d'elle-même
            # tant qu'une personne n'a pas approuvé une version (le retour arrière est une décision humaine).
            return {"accepte": False, "raisons": ["gel_apres_retrait_humain"]}
    else:
        if not _personne(approbateur):
            return {"accepte": False, "raisons": ["approbateur_humain_requis"]}
        if candidate["decision"] not in ("auto_applicable", "approbation_requise"):
            return {"accepte": False, "raisons": ["decision_non_activable"]}
    pile = contenu["piles"].get(_cle(candidate["cohorte"]), [])
    if pile and pile[-1]["version_id"] == version_id:
        return {"accepte": True, "version_id": version_id, "deja_active": True}
    en_vigueur = pile[-1]["version_id"] if pile else None
    if candidate["parent_version_id"] != en_vigueur:
        return {"accepte": False, "raisons": ["version_perimee"]}
    charge = {
        "version_id": version_id, "cohorte": candidate["cohorte"], "mode_activation": mode_activation,
        "approbateur": approbateur if mode_activation == "humain" else None,
        "taux_baseline": candidate["taux_baseline"], "taux_applique": candidate["taux_applique"],
        "parent_version_id": en_vigueur, "active_le": maintenant_utc,
    }
    maillon, raison = _ajouter(journal, contenu["evenements"], "version_activee", charge)
    if raison:
        return {"accepte": False, "raisons": [raison]}
    return {"accepte": True, "version_id": version_id, "deja_active": False, "parent_version_id": en_vigueur,
            "rang": maillon["rang"]}


def retirer(
    journal: Any, cohorte: dict[str, Any], *, version_attendue: str, par: str, raison: str, maintenant_utc: str,
) -> dict[str, Any]:
    """Retour arrière en une opération : la version en vigueur de la cohorte, qui doit être ``version_attendue``, est
    retirée et la précédente (ou le barème) redevient la référence."""
    contenu, refus = etat(journal)
    if refus or contenu is None:
        return {"accepte": False, "raisons": [refus or "journal_illisible"]}
    if not _cohorte_valide(cohorte) or not _hash_valide(version_attendue):
        return {"accepte": False, "raisons": ["arguments_invalides"]}
    if not _personne(par) or not isinstance(raison, str) or not 0 < len(raison.strip()) <= 300:
        return {"accepte": False, "raisons": ["personne_et_raison_requises"]}
    pile = contenu["piles"].get(_cle(cohorte), [])
    if not pile:
        return {"accepte": False, "raisons": ["aucune_version_en_vigueur"]}
    if pile[-1]["version_id"] != version_attendue:
        return {"accepte": False, "raisons": ["version_en_vigueur_differente"]}
    retablie = pile[-2]["version_id"] if len(pile) >= 2 else None
    charge = {"version_id": version_attendue, "cohorte": cohorte, "retablit_version_id": retablie, "par": par,
              "raison": raison.strip(), "retire_le": maintenant_utc}
    maillon, refus = _ajouter(journal, contenu["evenements"], "version_retiree", charge)
    if refus:
        return {"accepte": False, "raisons": [refus]}
    return {"accepte": True, "version_retiree": version_attendue, "version_retablie": retablie, "rang": maillon["rang"]}


def declarer_complexite(
    journal: Any, *, chantier_id: str, complexite: str, par: str, maintenant_utc: str, echelle: list[str],
) -> dict[str, Any]:
    """Déclare la difficulté d'un chantier dans l'échelle de l'entreprise. La déclaration la plus récente fait foi ;
    le journal garde les précédentes. Le chantier n'est inscrit que par son empreinte."""
    contenu, raison = etat(journal)
    if raison or contenu is None:
        return {"accepte": False, "raisons": [raison or "journal_illisible"]}
    if not isinstance(chantier_id, str) or not chantier_id.strip() or len(chantier_id) > 128:
        return {"accepte": False, "raisons": ["chantier_id_invalide"]}
    if complexite not in echelle:
        return {"accepte": False, "raisons": ["complexite_hors_echelle"], "echelle": list(echelle)}
    if not _personne(par):
        return {"accepte": False, "raisons": ["declarant_requis"]}
    empreinte_chantier = empreinte_chantier_id(chantier_id)
    if contenu["complexites"].get(empreinte_chantier) == complexite:
        return {"accepte": True, "deja_declaree": True}
    charge = {"chantier_sha256": empreinte_chantier, "complexite": complexite, "declare_par": par,
              "declare_le": maintenant_utc}
    maillon, refus = _ajouter(journal, contenu["evenements"], "complexite_declaree", charge)
    if refus:
        return {"accepte": False, "raisons": [refus]}
    return {"accepte": True, "deja_declaree": False, "rang": maillon["rang"]}


def empreinte_chantier_id(chantier_id: str) -> str:
    return empreinte({"chantier": chantier_id})


def enregistrer_performance(
    journal: Any, rapport: dict[str, Any], *, politique_sha256: str, maintenant_utc: str,
) -> dict[str, Any]:
    """Inscrit l'instantané des indices de rapidité (``performance_equipes``) ; identique au dernier : rien."""
    contenu, raison = etat(journal)
    if raison or contenu is None:
        return {"statut": "refuse", "raisons": [raison or "journal_illisible"]}
    corps = {"equipes": rapport["equipes"], "strates": rapport["strates"]}
    instantane = empreinte(corps)
    dernier = contenu["performance"]
    if (
        dernier is not None and dernier["snapshot_sha256"] == instantane
        and dernier["politique_sha256"] == politique_sha256
    ):
        return {"statut": "existante", "snapshot_sha256": instantane}
    charge = {**corps, "politique_sha256": politique_sha256, "calcule_le": maintenant_utc,
              "snapshot_sha256": instantane}
    maillon, refus = _ajouter(journal, contenu["evenements"], "performance_calculee", charge)
    if refus:
        return {"statut": "refuse", "raisons": [refus]}
    return {"statut": "inscrite", "snapshot_sha256": instantane, "rang": maillon["rang"]}
