"""Copie privée des tarifs choisis, jamais une preuve d'authenticité documentaire.

L'adaptateur résout les références M3/M6 et revalide les sélections dans sa
transaction. Ce validateur pur vérifie la forme fermée et la cohérence du coût
avec chaque ligne déjà calculée. Il ne consulte pas le livre de prix courant.
"""

import re
from datetime import date, datetime
from decimal import Decimal

from .modeles_soumission import Refus, _horodatage, _identifiant, _texte, valider_modele_fige

_CLES = {"modele_source", "lignes_source", "lignes_revision", "tarifs"}
_TARIF = {"reference_ligne", "ligne_modele_id", "materiau_id", "fournisseur_id", "tarif_rang",
          "tarif_empreinte", "cout_unitaire_decimal", "devise", "unite", "date_effet",
          "source_document", "marquage_source"}


def _hash(v):
    return type(v) is str and re.fullmatch(r"[0-9a-f]{64}", v) is not None


def valider(provenance, lignes, modele, horodatage):
    """Toutes les lignes du devis sourcé sont couvertes exactement une fois.

    Les identifiants de lignes sont ceux du devis; ligne_modele_id identifie la
    ligne réutilisable. Quantités et prix de vente restent exclusivement M3.
    Une provenance absente est traitée par l'appelant comme un devis manuel.
    """
    if (type(provenance) is not dict or set(provenance) != _CLES
            or not valider_modele_fige(modele)
            or provenance["modele_source"] != modele["source_id"]
            or not _hash(provenance["lignes_source"])
            or type(provenance["lignes_revision"]) is not int
            or not 1 <= provenance["lignes_revision"] <= 1000
            or type(provenance["tarifs"]) is not list
            or not 1 <= len(provenance["tarifs"]) == len(lignes) <= 20):
        return False
    try:
        _horodatage(horodatage)
    except Refus:
        return False
    jour = datetime.fromisoformat(horodatage).date()
    references = {ligne["reference_ligne"]: ligne for ligne in lignes}
    vues, modeles = set(), set()
    for tarif in provenance["tarifs"]:
        if type(tarif) is not dict or set(tarif) != _TARIF:
            return False
        ref, identifiant = tarif["reference_ligne"], tarif["ligne_modele_id"]
        if (type(ref) is not str or ref not in references or ref in vues
                or not _identifiant(identifiant, 100) or identifiant in {".", ".."}
                or identifiant in modeles
                or not _texte(tarif["materiau_id"], 200)
                or not _texte(tarif["fournisseur_id"], 200)
                or type(tarif["tarif_rang"]) is not int or tarif["tarif_rang"] < 0
                or not _hash(tarif["tarif_empreinte"])
                or tarif["devise"] != "CAD" or not _texte(tarif["unite"], 40)
                or tarif["unite"] != references[ref]["unite"]):
            return False
        cout = tarif["cout_unitaire_decimal"]
        if (type(cout) is not str or re.fullmatch(r"[0-9]{1,9}(\.[0-9]{1,6})?", cout) is None
                or Decimal(cout) <= 0 or Decimal(cout) != references[ref]["cout_unitaire"]):
            return False
        effet = tarif["date_effet"]
        try:
            if type(effet) is not str or date.fromisoformat(effet).isoformat() != effet:
                return False
            if date.fromisoformat(effet) > jour:
                return False
        except ValueError:
            return False
        document = tarif["source_document"]
        if document is not None and not _texte(document, 1000):
            return False
        marquage = "FALLBACK_PRICE_BOOK" if document is None else "SOURCE_DECLAREE"
        if tarif["marquage_source"] != marquage:
            return False
        vues.add(ref)
        modeles.add(identifiant)
    return vues == set(references)
