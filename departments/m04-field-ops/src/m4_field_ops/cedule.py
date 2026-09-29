"""Cédule déterministe de M4 (règles pures, sans horloge ni aléa).

PLAN T0.13-b : une intervention à céduler porte la nature de ses travaux sous l'une de DEUX formes, selon
la version du LeadQualifie dont elle vient (lue à l'inscription, jamais devinée) : `type_travaux` (v1 gelé,
énuméré fermé `TYPES_TRAVAUX`) ou `service` (v2, code d'un service déclaré par le profil de l'entreprise,
`opsys.taxonomie`). Jamais les deux, jamais l'un déduit de l'autre ; la cédule rend la même clé qu'elle a reçue.
"""
from datetime import datetime

from opsys import taxonomie

from . import encodage, horodatage, verdicts

TYPES_TRAVAUX = ("renovation_totale", "extension", "ravalement", "isolation_thermique", "autre")

# Formes exactes d'une intervention à céduler : v1 (`type_travaux`) ou v2 (`service`).
CLES_INTERVENTION_V1 = frozenset({"intervention_id", "lead_id", "type_travaux", "ville"})
CLES_INTERVENTION_V2 = frozenset({"intervention_id", "lead_id", "service", "ville"})

__all__ = [
    "TYPES_TRAVAUX", "CLES_INTERVENTION_V1", "CLES_INTERVENTION_V2", "tokeniser_ville", "generer_cedule",
    "services_declares",
]


def services_declares():
    """`(codes, None)` : les codes des services déclarés par le profil d'entreprise de l'instance
    (`opsys.taxonomie`), dans l'ordre de la déclaration ; `((), verdict)` sinon, où le verdict
    `{code, detail}` de la taxonomie dit quoi configurer. Ne lève jamais, jamais de repli."""
    services, verdict = taxonomie.charger_services()
    return tuple(service.code for service in services), verdict


def tokeniser_ville(sel, ville):
    """
    Retourne un jeton opaque pour la ville, ne révélant jamais son nom en clair.

    Args:
        sel (str): sel cryptographique
        ville (str): nom de la ville

    Returns:
        str: empreinte hexadécimale
    """
    return encodage.empreinte("ville", sel, ville)


def generer_cedule(interventions, techniciens, fenetres, sel):
    """
    Génère une cédule déterministe par règles pures (sans horloge ni aléa).

    Les entrées sont fournies par l'appelant ; les décisions reposent sur
    un tri strict multi‑critères ratifié et un débordement explicite en
    « non_cedulees » lorsque la capacité est dépassée.

    Args:
        interventions (list): liste d'interventions (dicts)
        techniciens (list): liste d'identifiants de techniciens (str)
        fenetres (list): liste de fenêtres (dicts avec "debut"/"fin")
        sel (str): sel cryptographique pour la tokenisation des villes

    Returns:
        tuple: (cedule, None) ou (None, verdict_dict)
    """
    # ------------------------------------------------------------------
    # Étape 0 – validation des conteneurs de premier niveau
    # ------------------------------------------------------------------
    if not isinstance(interventions, list):
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
    if not isinstance(techniciens, list):
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
    if not isinstance(fenetres, list):
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")

    # ------------------------------------------------------------------
    # Étape 1 – validation du sel
    # ------------------------------------------------------------------
    if not isinstance(sel, str):
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
    if sel == "":
        return None, verdicts.construire_verdict("REJ-CHAMP-VIDE")

    # ------------------------------------------------------------------
    # Étape 2 – validation unitaire des interventions
    # ------------------------------------------------------------------
    ids_vus = []
    profil = None
    for inter in interventions:
        if not isinstance(inter, dict):
            return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
        # La forme dit la version : `type_travaux` (v1) ou `service` (v2), exactement l'une des deux.
        cles = set(inter.keys())
        if cles == CLES_INTERVENTION_V1:
            cle_travaux = "type_travaux"
        elif cles == CLES_INTERVENTION_V2:
            cle_travaux = "service"
        else:
            return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
        for cle in ("intervention_id", "lead_id", cle_travaux, "ville"):
            if not isinstance(inter[cle], str):
                return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
            if inter[cle] == "":
                return None, verdicts.construire_verdict("REJ-CHAMP-VIDE")
        if cle_travaux == "type_travaux":
            if inter["type_travaux"] not in TYPES_TRAVAUX:
                return None, verdicts.construire_verdict("REJ-ENUM-INVALIDE")
        else:
            # Le profil d'entreprise est lu une seule fois par appel, à la première intervention v2.
            if profil is None:
                profil = taxonomie.charger_services()
            declares, verdict_profil = profil
            if verdict_profil is not None:
                verdict_service = verdict_profil
            else:
                _, verdict_service = taxonomie.valider_service(inter["service"], declares)
            if verdict_service is not None:
                return None, verdicts.construire_verdict(
                    "REJ-ENUM-INVALIDE", detail=f"{verdict_service['code']} : {verdict_service['detail']}",
                )
        ids_vus.append(inter["intervention_id"])

    # Doublons d’IDs d’intervention
    if len(ids_vus) != len(set(ids_vus)):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="identifiant d’intervention dupliqué"
        )

    # ------------------------------------------------------------------
    # Étape 3 – validation des techniciens
    # ------------------------------------------------------------------
    techs_vus = []
    for t in techniciens:
        if not isinstance(t, str):
            return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
        if t == "":
            return None, verdicts.construire_verdict("REJ-CHAMP-VIDE")
        techs_vus.append(t)
    if len(techs_vus) != len(set(techs_vus)):
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")

    # ------------------------------------------------------------------
    # Étape 4 – validation des fenêtres
    # ------------------------------------------------------------------
    for f in fenetres:
        if not isinstance(f, dict) or set(f.keys()) != {"debut", "fin"}:
            return None, verdicts.construire_verdict("REJ-FENETRE-INVALIDE")
        try:
            horodatage.valider_horodatage(f["debut"])
        except ValueError:
            return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")
        try:
            horodatage.valider_horodatage(f["fin"])
        except ValueError:
            return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")
        debut_dt = datetime.fromisoformat(f["debut"])
        fin_dt = datetime.fromisoformat(f["fin"])
        if debut_dt >= fin_dt:
            return None, verdicts.construire_verdict("REJ-FENETRE-INVALIDE")

    # ------------------------------------------------------------------
    # Étape 5 – cas particuliers de disponibilité
    # ------------------------------------------------------------------
    if interventions and (not techniciens or not fenetres):
        return None, verdicts.construire_verdict(
            "REJ-FENETRE-INVALIDE", detail="aucune ressource disponible pour céduler"
        )

    # Cédule vide légale (aucun travail en attente)
    if not interventions:
        return {"assignations": [], "non_cedulees": []}, None

    # ------------------------------------------------------------------
    # Algorithme de cédule – tri ratifié multi‑critères et round‑robin
    # ------------------------------------------------------------------
    # Tri des interventions par (token_ville, type_travaux ou service, lead_id). Le dernier critère (la clé
    # portée, v1 avant v2) ne départage que deux interventions de versions différentes au même code :
    # pour des interventions toutes v1, l'ordre est celui d'avant T0.13-b.
    interventions_triees = sorted(
        interventions,
        key=lambda i: (
            tokeniser_ville(sel, i["ville"]),
            i["service"] if "service" in i else i["type_travaux"],
            i["lead_id"],
            "service" in i,
        ),
    )
    # Tri des techniciens
    techniciens_tries = sorted(techniciens)
    # Tri chronologique des fenêtres (datetime, pas chaîne)
    fenetres_triees = sorted(
        fenetres,
        key=lambda f: (datetime.fromisoformat(f["debut"]), datetime.fromisoformat(f["fin"])),
    )

    assignations = []
    non_cedulees = []

    for idx, inter in enumerate(interventions_triees):
        ville_token = tokeniser_ville(sel, inter["ville"])
        cle_travaux = "service" if "service" in inter else "type_travaux"
        rang_tech = idx % len(techniciens_tries)
        idx_fen = idx // len(techniciens_tries)
        if idx_fen < len(fenetres_triees):
            fen = fenetres_triees[idx_fen]
            assignations.append(
                {
                    "intervention_id": inter["intervention_id"],
                    "lead_id": inter["lead_id"],
                    cle_travaux: inter[cle_travaux],
                    "ville_tokenisee": ville_token,
                    "technicien_id": techniciens_tries[rang_tech],
                    "fenetre": {"debut": fen["debut"], "fin": fen["fin"]},
                }
            )
        else:
            non_cedulees.append(
                {
                    "intervention_id": inter["intervention_id"],
                    "lead_id": inter["lead_id"],
                    cle_travaux: inter[cle_travaux],
                    "ville_tokenisee": ville_token,
                }
            )

    cedule = {"assignations": assignations, "non_cedulees": non_cedulees}
    return cedule, None
