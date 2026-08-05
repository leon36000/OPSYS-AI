# audit/rubrique.py
import re

_MOTIF_CONTRAT_RESOLVABLE = re.compile(
    r"^(?:D-\d{3}|R-\d{3}|REG-\d{2}|CA-AUD-\d{2})$"
)

_CHAMPS_REQUIS = (
    "frontiere_t3",
    "gate_couvrant",
    "rayon",
    "contrat_gele",
)


def calculer_severite(entrees: dict) -> tuple[str, str]:
    if not isinstance(entrees, dict):
        return "indetermine", "entrees_type_invalide"

    for champ in _CHAMPS_REQUIS:
        if champ not in entrees:
            return "indetermine", f"entree_absente:{champ}"

    frontiere_t3 = entrees["frontiere_t3"]
    if type(frontiere_t3) is not bool:
        return "indetermine", "type_invalide:frontiere_t3"

    gate_couvrant = entrees["gate_couvrant"]
    if type(gate_couvrant) is not bool:
        return "indetermine", "type_invalide:gate_couvrant"

    rayon = entrees["rayon"]
    if type(rayon) is not int:
        return "indetermine", "type_invalide:rayon"
    if rayon < 0:
        return "indetermine", "valeur_invalide:rayon"

    contrat_gele = entrees["contrat_gele"]
    if not isinstance(contrat_gele, str):
        return "indetermine", "type_invalide:contrat_gele"
    if contrat_gele and not _MOTIF_CONTRAT_RESOLVABLE.fullmatch(contrat_gele):
        return "indetermine", "contrat_gele_non_resolvable"

    if frontiere_t3:
        return "critique", "regle_critique:frontiere_t3"
    if contrat_gele and rayon >= 2:
        return "critique", "regle_critique:contrat_gele_rayon_ge_2"
    if not gate_couvrant and rayon >= 3:
        return "critique", "regle_critique:gate_non_couvrant_rayon_ge_3"
    if contrat_gele:
        return "majeure", "regle_majeure:contrat_gele"
    if not gate_couvrant and rayon >= 1:
        return "majeure", "regle_majeure:gate_non_couvrant_rayon_ge_1"
    return "mineure", "regle_mineure:aucun_critere_aggravant"
