"""Catalogue fermé des refus des opérations comptables, du rapprochement bancaire, du dossier CPA, des conseillers et du
RAG fiscal (`docs/architecture/M5-SOPHIE.md`), à part de `validation.CODES_M5_LIST`.

Même raison que `verdicts_grand_livre.py`, `verdicts_calcul.py` et `verdicts_fiscal.py` : `validation.py` fait partie du
code de paie épinglé par empreinte (`contracts/admission_paie_preparatoire.v1.json`) ; y ajouter des codes ferait tomber
le diagnostic d'admission de la paie. Même forme de verdict (`{code, detail}`), même fermeture : un code hors catalogue
lève. Module pur.

Un refus n'est jamais un résultat dégradé : une donnée manquante dit ce qu'il faut déclarer ou demander, jamais une
valeur par défaut inventée.
"""

from __future__ import annotations

__all__ = ["CODES_OPERATIONS", "construire_verdict"]

CODES_OPERATIONS = [
    # ---- opérations comptables (relances, notes de crédit, dépenses, pièces, paiements préparés, périodes)
    "REJ-OPS-STOCKAGE-NON-DURABLE",  # registre durable des opérations absent : une opération ne se simule pas
    "REJ-OPS-CHAINE-INVALIDE",  # registre des opérations altéré (chaîne, empreinte, maillon étranger)
    "REJ-OPS-ENTREE-INVALIDE",  # champ absent, mal typé, trop long ou multiligne
    "REJ-OPS-DATE-INVALIDE",  # date qui n'est pas AAAA-MM-JJ réelle, ou intervalle inversé
    "REJ-OPS-MONTANT-INVALIDE",  # montant qui n'est pas un texte décimal au cent, strictement positif
    "REJ-OPS-HUMAIN-REQUIS",  # geste qui se décide par une personne identifiée : un agent seul est refusé
    "REJ-OPS-CONFIGURATION-A-DECLARER",  # décision du propriétaire absente : le refus dit quoi déclarer
    "REJ-OPS-FACTURE-INTROUVABLE",  # facture client ou fournisseur absente du registre de M5
    "REJ-OPS-FACTURE-NON-EMISE",  # facture client qui n'est ni envoyée ni payée : pas de note de crédit possible
    "REJ-OPS-FACTURE-ANNULEE",  # facture fournisseur annulée : plus de dette, plus d'opération
    "REJ-OPS-NOTE-CREDIT-EXCEDE",  # note de crédit au-delà de ce que la facture permet encore de créditer
    "REJ-OPS-DOUBLON",  # même clé d'opération, autre contenu
    "REJ-OPS-PERIODE-CLOSE",  # opération datée dans une période déjà close
    "REJ-OPS-PERIODE-INVALIDE",  # mois mal formé
    "REJ-OPS-PERIODE-NON-PRETE",  # préclôture : au moins un bloquant ; la clôture reste humaine
    "REJ-OPS-PIECE-INVALIDE",  # pièce justificative mal formée (empreinte, nom, type)
    "REJ-OPS-PIECE-INTROUVABLE",  # l'opération visée par la pièce n'existe pas
    "REJ-OPS-PAIEMENT-INVALIDE",  # paiement préparé impossible (montant, échéance, facture)
    "REJ-OPS-PAIEMENT-DEJA-PREPARE",  # un paiement préparé couvre déjà cette facture fournisseur
    "REJ-OPS-PAIEMENT-RAPPROCHEMENT",  # le rapprochement PO, réception et facture n'est pas conforme : paiement refusé
    "REJ-OPS-JUGEMENT-INVALIDE",  # jugement ou estimation mal formé
    "REJ-OPS-COMPTE-A-DECLARER",  # compte du plan que le propriétaire doit désigner (jamais supposé)
    "REJ-OPS-LIMITE-INVALIDE",  # pagination invalide
    # ---- relevés bancaires et rapprochement
    "REJ-BANQUE-FICHIER-INVALIDE",  # fichier démesuré, vide, illisible, encodage inconnu ou nom non confiné
    "REJ-BANQUE-FICHIER-INTROUVABLE",  # nom de fichier absent du dossier confiné des relevés
    "REJ-BANQUE-FORMAT-INCONNU",  # ni CSV ni OFX reconnu
    "REJ-BANQUE-COLONNES-INTROUVABLES",  # colonne de date ou de montant introuvable : donner le mapping
    "REJ-BANQUE-LIGNE-INVALIDE",  # ligne dont la date ou le montant est illisible (numéro de ligne dit)
    "REJ-BANQUE-MONTANT-AMBIGU",  # « 1,234 » : milliers ou décimales ? jamais deviné
    "REJ-BANQUE-DATE-AMBIGUE",  # 03/04/2026 : jour/mois ou mois/jour ? donner le format
    "REJ-BANQUE-DOUBLON-REFERENCE",  # même identifiant de transaction (FITID) deux fois
    "REJ-BANQUE-DEVISE-INVALIDE",  # devise autre que CAD
    "REJ-BANQUE-SOLDE-INCOHERENT",  # solde de fin déclaré ≠ solde recalculé des lignes
    "REJ-BANQUE-FENETRE-INVALIDE",  # fenêtre de dates hors bornes
    "REJ-BANQUE-RAPPROCHEMENT-INTROUVABLE",  # rapprochement inconnu
    "REJ-BANQUE-DEJA-CONFIRME",  # rapprochement déjà confirmé par un humain
    "REJ-BANQUE-ECART-NON-NUL",  # confirmation d'un rapprochement dont l'écart n'est pas nul, sans motif
    "REJ-BANQUE-REJEU-DIVERGENT",  # le rejeu ne redonne pas le reçu enregistré
    # ---- dossier CPA et fin d'année
    "REJ-DOSSIER-PERIODE-INVALIDE",  # période du dossier mal formée ou inversée
    "REJ-DOSSIER-INTROUVABLE",  # dossier inconnu
    "REJ-DOSSIER-ALTERE",  # un fichier ne correspond plus à l'empreinte du scellé
    "REJ-DOSSIER-EXPORT-IMPOSSIBLE",  # dossier d'export non confiné, existant ou non inscriptible
    "REJ-DOSSIER-SCELLE-CONFLIT",  # même dossier, contenu différent
    # ---- conseillers (dette, financement, investissement ; fiscal et comptable)
    "REJ-CONSEIL-ENTREE-INVALIDE",  # scénario, hypothèse ou champ mal formé
    "REJ-CONSEIL-SCENARIO-TROP-NOMBREUX",  # plus de scénarios que la borne
    "REJ-CONSEIL-RECOMMANDATION-TITRES",  # demande de recommandation de titres : refusée (NC 31-103)
    "REJ-CONSEIL-REGLE-NON-RENSEIGNEE",  # règle fiscale non renseignée : source officielle requise
    # variante planifiée du constat du cash libre (m5_constater_cash_libre_planifie) : seul le planificateur la
    # déclenche (à part de `validation.py`, épinglé par empreinte avec le code de paie)
    "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT",
    "REJ-CONSEIL-SUJET-INCONNU",  # sujet hors du catalogue des analyses
    "REJ-CONSEIL-MODE-INVALIDE",  # mode absent ou hors de {officiel, essai}
    "REJ-CONSEIL-DONNEE-MANQUANTE",  # donnée de l'entreprise absente : le refus dit laquelle
    "REJ-CONSEIL-SOURCE-NON-APPROUVEE",  # mode officiel : la source (règle, calendrier, texte) n'est pas approuvée
    # ---- RAG fiscal et comptable
    "REJ-RAGFISC-REQUETE-INVALIDE",  # question hors des bornes
    "REJ-RAGFISC-BASE-INDISPONIBLE",  # base de connaissances ou transaction indisponible
    "REJ-RAGFISC-APPAREIL-FERME",  # la base de connaissances n'est ouverte à aucun appareil
]
_CODES = frozenset(CODES_OPERATIONS)


class CodeOperationsInconnu(ValueError):
    pass


def construire_verdict(code: str, detail: str = "") -> dict[str, str]:
    if code not in _CODES:
        raise CodeOperationsInconnu(f"code de refus inconnu : {code!r}")
    return {"code": code, "detail": detail}
