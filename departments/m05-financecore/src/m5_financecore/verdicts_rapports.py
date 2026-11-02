"""Catalogue fermé des refus des RAPPORTS financiers (état des résultats, bilan, budget contre réel, rentabilité par
axe, rapport de direction), du BUDGET déclaré et du PRÉ-AUDIT (M5-RAPPORTS-1, M5-PRE-AUDIT), à part de
`validation.CODES_M5_LIST`.

Même raison que `verdicts_facturation.py` : `validation.py` fait partie du code de paie épinglé par empreinte
(`contracts/admission_paie_preparatoire.v1.json`) ; y ajouter des codes ferait tomber le diagnostic d'admission de la
paie. Même forme de verdict (`{code, detail}`), même fermeture : un code hors catalogue lève. Module pur.

Un refus n'est jamais un résultat dégradé : une donnée déclarée absente dit CE QU'IL FAUT DÉCLARER (et où), jamais une
valeur par défaut inventée, jamais un zéro.
"""

from __future__ import annotations

__all__ = ["CODES_RAPPORTS", "construire_verdict"]

CODES_RAPPORTS = [
    # ---- rapports financiers (lecture du grand livre)
    "REJ-RAPPORT-STOCKAGE-NON-DURABLE",  # registre durable requis : un rapport ne se simule pas
    # grand livre, budget ou autre registre lu altéré : jamais un chiffre sur une chaîne fausse
    "REJ-RAPPORT-CHAINE-INVALIDE",
    "REJ-RAPPORT-PERIODE-INVALIDE",  # période AAAA-MM illisible, ou dates inversées / trop longues
    "REJ-RAPPORT-DATE-INVALIDE",  # date AAAA-MM-JJ illisible
    "REJ-RAPPORT-LIMITE-INVALIDE",  # pagination hors bornes
    # une écriture touche un compte que le plan courant ne connaît pas : classement impossible
    "REJ-RAPPORT-COMPTE-HORS-PLAN",
    "REJ-RAPPORT-COUTS-DIRECTS-INVALIDES",  # configuration.rapports.comptes_couts_directs mal formée ou hors plan
    "REJ-RAPPORT-AXE-INVALIDE",  # axe de rentabilité hors de la liste fermée (service, ville)
    "REJ-RAPPORT-RECU-INVALIDE",  # reçu de rapport illisible ou retouché
    "REJ-RAPPORT-REJEU-DIFFERENT",  # le rejeu du reçu ne redonne pas la même empreinte
    "REJ-RAPPORT-APPAREIL-INTERDIT",  # les rapports ne sont ouverts à aucun rôle d'appareil (portée fermée)
    # ---- budget déclaré
    "REJ-BUDGET-A-DECLARER",  # aucun budget déclaré : le refus dit quoi déclarer, jamais un budget supposé
    "REJ-BUDGET-ENTREE-INVALIDE",  # champ absent, mal typé, trop long ou multiligne
    "REJ-BUDGET-COMPTE-INVALIDE",  # compte inconnu du plan, désactivé, ou ni produit ni charge
    "REJ-BUDGET-MONTANT-INVALIDE",  # montant non décimal au cent, négatif ou démesuré
    "REJ-BUDGET-MOIS-INVALIDE",  # mois illisible
    "REJ-BUDGET-LIGNE-DOUBLE",  # le même couple compte/mois deux fois dans la déclaration
    "REJ-BUDGET-MOTIF-REQUIS",  # remplacer un budget déjà déclaré exige un motif
    "REJ-BUDGET-HUMAIN-REQUIS",  # déclarer un budget engage la direction : une personne le décide (N3)
    "REJ-BUDGET-STOCKAGE-NON-DURABLE",  # registre durable des budgets absent
    "REJ-BUDGET-VERSION-ATTENDUE",  # la version attendue ne correspond plus (déclaration concurrente)
    # ---- pré-audit
    "REJ-PREAUDIT-DATE-INVALIDE",  # aujourd_hui ou horodatage illisible
    "REJ-PREAUDIT-LIMITE-INVALIDE",  # pagination hors bornes
    "REJ-PREAUDIT-STOCKAGE-NON-DURABLE",  # registres durables requis
    "REJ-PREAUDIT-APPAREIL-INTERDIT",  # le contrôleur n'est ouvert à aucun rôle d'appareil (portée fermée)
]
_CODES = frozenset(CODES_RAPPORTS)


class CodeRapportInconnu(ValueError):
    pass


def construire_verdict(code: str, detail: str = "") -> dict[str, str]:
    if code not in _CODES:
        raise CodeRapportInconnu(f"code de refus des rapports inconnu : {code!r}")
    return {"code": code, "detail": detail}
