"""Catalogue fermé des refus de la facturation par jalons, de la numérotation, de l'échéance et du PDF de facture
(M5-FACT-1 et M5-FACT-2), à part de `validation.CODES_M5_LIST`.

Même raison que `verdicts_grand_livre.py` et `verdicts_operations.py` : `validation.py` fait partie du code de paie
épinglé par empreinte (`contracts/admission_paie_preparatoire.v1.json`) ; y ajouter des codes ferait tomber le
diagnostic d'admission de la paie. Même forme de verdict (`{code, detail}`), même fermeture : un code hors catalogue
lève. Module pur.

Un refus n'est jamais un résultat dégradé : une donnée déclarée absente dit CE QU'IL FAUT DÉCLARER (et où), jamais une
valeur par défaut inventée.
"""

from __future__ import annotations

__all__ = ["CODES_FACTURATION", "construire_verdict"]

CODES_FACTURATION = [
    # ---- plan de facturation par jalons
    "REJ-PLAN-STOCKAGE-NON-DURABLE",  # registre durable des plans absent : un plan ne se simule pas
    "REJ-PLAN-CHAINE-INVALIDE",  # registre des plans, des factures ou de la numérotation altéré
    "REJ-PLAN-ENTREE-INVALIDE",  # champ absent, mal typé, trop long ou multiligne
    "REJ-PLAN-DEVIS-INCONNU",  # aucun devis accepté (m3.devis_accepte) reçu pour ce devis
    "REJ-PLAN-CHANTIER-A-DECLARER",  # le devis n'a pas de chantier : le déclarer, jamais l'inventer
    "REJ-PLAN-JALONS-INVALIDES",  # nombre de jalons (2 à 12), structure ou ordre des déclencheurs invalides
    "REJ-PLAN-JALON-MONTANT-AMBIGU",  # un jalon déclare un pourcentage ET un montant, ou aucun des deux
    "REJ-PLAN-MODE-MIXTE",  # des pourcentages et des montants dans le même plan
    "REJ-PLAN-SOMME-INCORRECTE",  # les montants déclarés ne totalisent pas le prix du devis au cent
    "REJ-PLAN-SOMME-POURCENTAGES",  # les pourcentages déclarés ne totalisent pas 100
    "REJ-PLAN-JALON-NUL",  # un jalon qui vaudrait moins d'un cent
    "REJ-PLAN-DELAI-A-DECLARER",  # ni délai de paiement sur le jalon, ni conditions de paiement déclarées
    "REJ-PLAN-DEJA-DECLARE",  # le devis porte déjà un plan actif au contenu différent
    "REJ-PLAN-DEVIS-DEJA-FACTURE",  # le devis est déjà facturé en bloc : un plan n'est plus possible
    "REJ-PLAN-INTROUVABLE",  # plan inconnu (ou aucun plan actif pour ce devis)
    "REJ-PLAN-DEJA-REVOQUE",  # plan déjà révoqué
    "REJ-PLAN-REVOCATION-IMPOSSIBLE",  # au moins une facture existe pour ce plan : il ne se révoque plus
    "REJ-PLAN-JALON-INCONNU",  # rang de jalon absent du plan
    "REJ-PLAN-JALON-HORS-ORDRE",  # un jalon précédent n'a pas encore de facture
    "REJ-PLAN-JALON-DEJA-FACTURE",  # le jalon porte déjà une facture active (autre identifiant)
    "REJ-PLAN-TRAVAUX-NON-TERMINES",  # jalon « fin des travaux » sans m4.travaux_termines reçu
    "REJ-PLAN-DEPASSEMENT",  # facturer ce jalon dépasserait le prix du devis
    "REJ-PLAN-FACTURATION-PAR-JALONS",  # le devis est facturé par jalons : aucune facture globale
    # ---- numérotation et échéance
    "REJ-NUMEROTATION-A-DECLARER",  # préfixe et premier numéro non déclarés : le refus dit quoi déclarer
    "REJ-NUMEROTATION-CHAINE-INVALIDE",  # trou, doublon ou altération dans la suite des numéros
    "REJ-NUMEROTATION-PREMIER-CHANGE",  # le premier numéro déclaré ne peut plus changer une fois la suite commencée
    "REJ-CONDITIONS-A-DECLARER",  # conditions de paiement mal formées ou absentes
    "REJ-FACTURATION-DATE-INVALIDE",  # date du jour ou d'émission illisible
    # ---- PDF de facture et état de compte
    "REJ-PDF-STOCKAGE-NON-DURABLE",  # registre durable des scellés absent
    "REJ-PDF-BRIQUE-ABSENTE",  # ReportLab absent ou d'une autre version : le refus dit quoi installer
    "REJ-PDF-FACTURE-INTROUVABLE",  # facture inconnue
    "REJ-PDF-FACTURE-NON-EMISE",  # BROUILLON, ANNULEE ou sans numéro : seule la facture approuvée et numérotée
    "REJ-PDF-ENTREPRISE-A-DECLARER",  # raison sociale, adresse ou numéro de TPS/TVQ non déclaré : le refus dit lequel
    "REJ-PDF-DESTINATAIRE-INVALIDE",  # nom ou adresse du client absent ou mal formé
    "REJ-PDF-LANGUE-INVALIDE",  # langue hors de fr / bilingue
    "REJ-PDF-CARACTERE-NON-SUPPORTE",  # caractère que la police du PDF ne dessine pas
    "REJ-PDF-MONTANT-INVALIDE",  # montant qui ne tombe pas juste au cent : le PDF n'arrondit jamais
    "REJ-PDF-RENDU-IMPOSSIBLE",  # la brique PDF n'a pas pu dessiner le document
    "REJ-PDF-SCELLE-DIFFERENT",  # le rendu ne redonne pas l'empreinte déjà scellée
    "REJ-PDF-TROP-VOLUMINEUX",  # le PDF dépasse la taille permise d'un document
    "REJ-PDF-EXPORT-IMPOSSIBLE",  # dossier d'export non confiné, non ordinaire ou non inscriptible
    "REJ-PDF-FICHIER-CONFLIT",  # fichier du même nom, autres octets : un document scellé ne s'écrase pas
    "REJ-PDF-ETAT-COMPTE-VIDE",  # aucune facture émise pour ce client
    "REJ-PDF-CLIENT-INVALIDE",  # identifiant de client absent ou mal formé
]
_CODES = frozenset(CODES_FACTURATION)


class CodeFacturationInconnu(ValueError):
    pass


def construire_verdict(code: str, detail: str = "") -> dict[str, str]:
    if code not in _CODES:
        raise CodeFacturationInconnu(f"code de refus de la facturation inconnu : {code!r}")
    return {"code": code, "detail": detail}
