"""Sélection explicite de coût pour un devis, sans modifier le livre de prix M6.

Les rangs viennent du stockage canonique. L'empreinte détecte un changement de
sélection; elle n'authentifie ni le document déclaré ni la base réécrite.
L'adaptateur contrôle l'identité, fournit le jour serveur et borne sa lecture SQL.
"""
import hashlib
import json
import math
import re
import unicodedata
from datetime import date
from decimal import Decimal

from .livre_prix import marquage_source_document

MAX_SOURCES = 10000


class SelectionTarifRefusee(ValueError):
    def __init__(self, raison):
        self.raison = raison
        super().__init__(raison)


def _texte(v, limite):
    return (type(v) is str and bool(v.strip()) and len(v) <= limite
            and not any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in v))


def _jour(v):
    try:
        if type(v) is not str:
            raise ValueError
        resultat = date.fromisoformat(v)
        if resultat.isoformat() != v:
            raise ValueError
        return resultat
    except ValueError:
        raise SelectionTarifRefusee("date_invalide") from None


def selectionner_tarif(lignes, fournisseur, materiau_id, fournisseur_id, unite, jour_serveur,
                      *, rang_attendu=None, empreinte_attendue=None):
    """lignes = séquence de paires (rang SQL réel, entrée du livre), ordonnée.

    Le dernier écrit pour le couple exact est retenu, même si sa date est plus
    ancienne. Un dernier tarif futur/invalide bloque : aucun repli silencieux.
    Le POST doit fournir rang_attendu ET empreinte_attendue lus au GET.
    Aucun nombre, unité, fournisseur ou quantité n'est inventé.
    """
    if (not _texte(materiau_id, 200) or not _texte(fournisseur_id, 200)
            or not _texte(unite, 40)):
        raise SelectionTarifRefusee("arguments_invalides")
    jour = _jour(jour_serveur)
    if (type(fournisseur) is not dict or fournisseur.get("fournisseur_id") != fournisseur_id
            or not _texte(fournisseur.get("nom"), 200)):
        raise SelectionTarifRefusee("fournisseur_inconnu")
    if type(lignes) not in (list, tuple) or len(lignes) > MAX_SOURCES:
        raise SelectionTarifRefusee("sources_trop_volumineuses")
    choisi = None
    precedent = -1
    for paire in lignes:
        if (type(paire) not in (list, tuple) or len(paire) != 2 or type(paire[0]) is not int
                or paire[0] < 0 or paire[0] <= precedent or type(paire[1]) is not dict):
            raise SelectionTarifRefusee("source_invalide")
        rang, entree = paire
        precedent = rang
        # Une identité illisible ne prouve pas que l'entrée appartient à un autre
        # couple. La sauter pourrait ressusciter silencieusement un ancien tarif.
        if (not _texte(entree.get("materiau_id"), 200)
                or not _texte(entree.get("fournisseur_id"), 200)):
            raise SelectionTarifRefusee("source_invalide")
        if entree.get("materiau_id") == materiau_id and entree.get("fournisseur_id") == fournisseur_id:
            choisi = (rang, entree)
    if choisi is None:
        raise SelectionTarifRefusee("tarif_absent")
    rang, entree = choisi
    if set(entree) - {"materiau_id", "fournisseur_id", "prix_unitaire", "devise", "date_effet",
                      "source_document", "unite"}:
        raise SelectionTarifRefusee("source_invalide")
    if entree.get("unite") != unite:
        raise SelectionTarifRefusee("unite_absente_ou_differente")
    if entree.get("devise") != "CAD":
        raise SelectionTarifRefusee("devise_non_supportee")
    if _jour(entree.get("date_effet")) > jour:
        raise SelectionTarifRefusee("date_future")
    prix = entree.get("prix_unitaire")
    if type(prix) not in (int, float) or (type(prix) is float and not math.isfinite(prix)):
        raise SelectionTarifRefusee("prix_invalide")
    # Vérifier les bornes avant formatage : pas de conversion coûteuse d'un entier énorme.
    if not 0 < prix < 1000000000:
        raise SelectionTarifRefusee("prix_invalide")
    cout = format(Decimal(str(prix)), "f")
    if re.fullmatch(r"[0-9]{1,9}(\.[0-9]{1,6})?", cout) is None:
        raise SelectionTarifRefusee("precision_non_supportee")
    document = entree.get("source_document")
    if document is not None and not _texte(document, 1000):
        raise SelectionTarifRefusee("source_document_invalide")
    charge = json.dumps({"rang": rang, "entree": entree}, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"), allow_nan=False)
    empreinte = hashlib.sha256(charge.encode()).hexdigest()
    if ((rang_attendu is not None or empreinte_attendue is not None)
            and (type(rang_attendu) is not int or type(empreinte_attendue) is not str
                 or rang_attendu != rang or empreinte_attendue != empreinte)):
        raise SelectionTarifRefusee("source_modifiee")
    return {"materiau_id": materiau_id, "fournisseur_id": fournisseur_id,
            "tarif_rang": rang, "tarif_empreinte": empreinte, "cout_unitaire_decimal": cout,
            "devise": "CAD", "unite": unite, "date_effet": entree["date_effet"],
            "source_document": document, "marquage_source": marquage_source_document(document)}
