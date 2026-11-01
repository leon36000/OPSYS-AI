"""Catalogue fermé des refus de la base fiscale, du harnais de paie, du catalogue de subventions et de la garde
investissement (`docs/architecture/BASE-FISCALE.md`), à part de `validation.CODES_M5_LIST`.

Même raison que `verdicts_grand_livre.py` et `verdicts_calcul.py` : `validation.py` fait partie du code de paie épinglé
par empreinte (`contracts/admission_paie_preparatoire.v1.json`, `generation.fichiers`) ; y ajouter des codes ferait
tomber le diagnostic d'admission de la paie. Même forme de verdict (`{code, detail}`), même fermeture : un code hors
catalogue lève. Module pur.

Un refus n'est jamais un résultat dégradé : un paramètre non renseigné, non approuvé ou hors de sa période ne produit
AUCUNE valeur par défaut, aucun « dernier taux connu ».
"""

from __future__ import annotations

__all__ = ["CODES_FISCAL", "construire_verdict"]

CODES_FISCAL = [
    # ---- base de règles fiscales versionnée
    "REJ-BASEFISC-FORMAT-INVALIDE",  # fichier illisible, trop gros, hors UTF-8, YAML invalide ou clé dupliquée
    "REJ-BASEFISC-SCHEMA-INVALIDE",  # schéma inconnu, clé inconnue ou manquante, type inattendu
    "REJ-BASEFISC-VALEUR-INVALIDE",  # valeur qui n'est pas un texte décimal canonique, ou hors des bornes de son unité
    "REJ-BASEFISC-DATE-INVALIDE",  # date qui n'est pas AAAA-MM-JJ réelle, ou période inversée
    "REJ-BASEFISC-SOURCE-ABSENTE",  # paramètre renseigné sans aucune source officielle
    "REJ-BASEFISC-SOURCE-INCOMPLETE",  # source sans organisme/titre, ou revue sans URL https et date de consultation
    "REJ-BASEFISC-TROU-DE-DATES",  # trou entre deux versions d'un même paramètre
    "REJ-BASEFISC-CHEVAUCHEMENT",  # deux versions d'un même paramètre valent le même jour
    "REJ-BASEFISC-EMPREINTE-DIVERGENTE",  # contenu modifié sans que l'empreinte suive : modification silencieuse
    "REJ-BASEFISC-REVUE-INVALIDE",  # revue mal formée, ou datée avant la saisie
    "REJ-BASEFISC-STATUT-INCOHERENT",  # statut déclaré différent de celui que les revues valides prouvent
    "REJ-BASEFISC-PARAMETRE-INCONNU",  # identifiant absent de la base
    "REJ-BASEFISC-HORS-COUVERTURE",  # aucune version du paramètre ne couvre la date demandée
    "REJ-BASEFISC-NON-RENSEIGNE",  # paramètre déclaré sans valeur : source officielle requise
    "REJ-BASEFISC-NON-APPROUVE",  # mode officiel : le paramètre n'a pas deux réviseurs distincts
    "REJ-BASEFISC-MODE-INVALIDE",  # mode absent ou hors de {officiel, essai} : jamais de mode par défaut
    # ---- harnais de validation de la paie (cas_paie.v1)
    "REJ-PAIEVAL-FORMAT-INVALIDE",  # fichier de cas illisible, trop gros ou YAML invalide
    "REJ-PAIEVAL-CAS-INVALIDE",  # cas mal formé (clé inconnue, type, ligne inconnue, montant non décimal)
    "REJ-PAIEVAL-DOUBLON",  # identifiant de cas ou entrées canoniques en double
    "REJ-PAIEVAL-PROVENANCE-NON-VERIFIEE",  # source, saisie, revue ou capture qui ne prouve pas l'origine officielle
    "REJ-PAIEVAL-FICTIF-REFUSE",  # cas `fictif_pour_tests_du_harnais` présenté à la qualification
    "REJ-PAIEVAL-ECART",  # un cas rejoué s'écarte d'au moins un cent d'une ligne attendue
    "REJ-PAIEVAL-MOTEUR-REFUSE",  # le moteur refuse l'entrée du cas (hors périmètre ou invalide)
    "REJ-PAIEVAL-CAMPAGNE-INSUFFISANTE",  # moins de 300 cas officiels à provenance vérifiée
    # ---- catalogue de subventions et de crédits
    "REJ-SUBV-CATALOGUE-INVALIDE",  # fichier ou structure du catalogue invalide
    "REJ-SUBV-MESURE-INVALIDE",  # mesure mal formée (source, période, montant, documents, vérification)
    "REJ-SUBV-CRITERE-INVALIDE",  # critère déclaratif mal formé, champ ou opérateur inconnu, source de critère absente
    "REJ-SUBV-FAITS-INVALIDES",  # faits fournis mal typés ou inconnus du vocabulaire du catalogue
    "REJ-SUBV-DATE-INVALIDE",  # date du jour absente ou invalide : M5 n'a pas d'horloge
    "REJ-SUBV-MODE-INVALIDE",  # mode absent ou hors de {officiel, essai}
    "REJ-SUBV-FICTIF-REFUSE",  # mesure fictive dans un catalogue chargé en mode officiel
    # ---- garde investissement (NC 31-103)
    "REJ-INVEST-RECOMMANDATION-PERSONNALISEE",  # recommandation personnalisée de titres : refusée, jamais calculée
    "REJ-INVEST-TEXTE-INVALIDE",  # texte absent, non textuel ou démesuré
]
_CODES = frozenset(CODES_FISCAL)


class CodeFiscalInconnu(ValueError):
    pass


def construire_verdict(code: str, detail: str = "") -> dict[str, str]:
    if code not in _CODES:
        raise CodeFiscalInconnu(f"code de refus fiscal inconnu : {code!r}")
    return {"code": code, "detail": detail}
