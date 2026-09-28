from datetime import datetime

from . import encodage, horodatage, verdicts

TYPES_TRAVAUX = ("renovation_totale", "extension", "ravalement", "isolation_thermique", "autre")

__all__ = ["TYPES_TRAVAUX", "tokeniser_ville", "generer_cedule"]


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
    for inter in interventions:
        if not isinstance(inter, dict):
            return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
        if set(inter.keys()) != {"intervention_id", "lead_id", "type_travaux", "ville"}:
            return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
        for cle in ("intervention_id", "lead_id", "type_travaux", "ville"):
            if not isinstance(inter[cle], str):
                return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE")
            if inter[cle] == "":
                return None, verdicts.construire_verdict("REJ-CHAMP-VIDE")
        if inter["type_travaux"] not in TYPES_TRAVAUX:
            return None, verdicts.construire_verdict("REJ-ENUM-INVALIDE")
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
    # Tri des interventions par (token_ville, type_travaux, lead_id)
    interventions_triees = sorted(
        interventions,
        key=lambda i: (
            tokeniser_ville(sel, i["ville"]),
            i["type_travaux"],
            i["lead_id"],
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
        rang_tech = idx % len(techniciens_tries)
        idx_fen = idx // len(techniciens_tries)
        if idx_fen < len(fenetres_triees):
            fen = fenetres_triees[idx_fen]
            assignations.append(
                {
                    "intervention_id": inter["intervention_id"],
                    "lead_id": inter["lead_id"],
                    "type_travaux": inter["type_travaux"],
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
                    "type_travaux": inter["type_travaux"],
                    "ville_tokenisee": ville_token,
                }
            )

    cedule = {"assignations": assignations, "non_cedulees": non_cedulees}
    return cedule, None
