"""Préparation commerciale canonique à la frontière de l'estimation durable.

M2 garde sa décision métier ; le validateur pur M3 reste structurel. Ce pont lit
l'instance courante sous la même garde que les producteurs M2, sans écrire dans M2.
"""

from sqlalchemy import Connection

from . import stockage
from .stockage.maillons import _verrouiller_m2_principal


def verifier_preparation_estimation(cnx: Connection, contrat: object, marqueur: object) -> bool:
    """Vérifie le contrat gelé et les conditions actuelles de M2 avant l'effet M3."""
    if not isinstance(contrat, dict) or not isinstance(marqueur, dict):
        return False
    lead_id = contrat.get("lead_id")
    if not isinstance(lead_id, str) or not lead_id or marqueur.get("lead_id") != lead_id:
        return False
    _verrouiller_m2_principal(cnx, partage=True)
    # Imports tardifs : charger M3 n'importe pas un autre département. La frontière
    # durable seule consomme le vérificateur canonique, pas l'orchestrateur pur.
    from m2_revenue_crm import encodage, readiness, registre

    canonique = registre.Registre(stockage.maillons("m02-revenue-crm", "principal"))
    if readiness.verifier_marqueur(marqueur, canonique) is not True:
        return False
    contrats = [
        maillon.get("contrat") for maillon in canonique.lire()
        if maillon.get("type_entree") == "lead_ingere" and maillon.get("lead_id") == lead_id
    ]
    if len(contrats) != 1 or not isinstance(contrats[0], dict):
        return False
    # Même identifiant ne signifie pas même contrat. L'encodage injectif existant
    # ignore l'ordre des clés, mais distingue les types JSON (False, 0, 2, 2.0).
    try:
        return encodage.empreinte(contrat) == encodage.empreinte(contrats[0])
    except (TypeError, ValueError, RecursionError):
        return False
