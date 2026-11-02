"""PDF déterministe de la facture client et de l'état de compte (M5-FACT-2).

Le PDF est la MISE EN PAGE d'une facture que le code a déjà calculée et qu'une personne a approuvée (N4) : il ne calcule
rien. Chaque montant (lignes, sous-total, TPS, TVQ, total, récapitulatif du contrat) est REPRIS du maillon de la facture
ou du plan, en `Decimal`, et seulement mis en forme à la québécoise (« 1 234,56 $ ») ; un montant qui exigerait un
arrondi
est refusé, jamais arrondi. Aucun modèle de langage ne produit un chiffre.

Ce que le PDF dit de l'ENTREPRISE vient de DONNÉES DÉCLARÉES par le propriétaire
(`configuration.facturation.entreprise` :
raison sociale, adresse, numéros d'inscription à la TPS et à la TVQ) ; le destinataire (nom et adresse du client, que M5
ne garde jamais) est fourni à l'appel. Une donnée absente BLOQUE et dit quoi déclarer : jamais un numéro inventé, jamais
un gabarit à trous. Le numéro d'inscription d'une taxe n'est exigé que si la facture porte cette taxe.

Brique : ReportLab (BSD-3-Clause, Python pur ; extra `soumission` de `pyproject.toml`, déjà intégré pour le PDF de
soumission de M3 : voir `docs/research/INGREDIENTS.md`), importée paresseusement, version épinglée vérifiée à
l'exécution. Absente : un verdict qui dit quoi installer, jamais un HTML renommé en PDF.

Déterminisme : mode `invariant` de ReportLab, date de création TIRÉE de l'émission de la facture (jamais de l'horloge),
polices standard non incorporées, aucun aléa : mêmes entrées, mêmes octets (pour une même version de ReportLab et de
zlib). Le PDF ne porte ni statut ni paiement : il reste identique après le paiement, donc son empreinte SHA-256, scellée
au registre `documents_facturation`, se rejoue. Le texte libre (client, libellés) est une DONNÉE : échappé avant
d'entrer
dans un paragraphe (ReportLab interprète des balises dont `<img src=...>`, qui ouvre un fichier local) et vérifié contre
le jeu de caractères de la police.

Le PDF n'EST PAS un envoi : ce module rend des octets, il ne les transmet à personne (l'envoi au client est N3/N4,
humain). Module pur : aucun import `opsys`, aucune horloge, aucun accès réseau.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html import escape
from importlib import import_module, metadata
from typing import Any

from . import encodage, facturation, verdicts_facturation

__all__ = [
    "NOM_BRIQUE",
    "TYPE_MIME",
    "VERSION_BRIQUE",
    "VERSION_GABARIT",
    "contenu_etat_compte",
    "contenu_facture",
    "empreinte_contenu",
    "formater_montant",
    "lire_destinataire",
    "lire_entreprise",
    "pdf_installe",
    "rendre",
    "sceller",
]

NOM_BRIQUE = "reportlab"
VERSION_BRIQUE = "4.5.1"  # épinglée : les octets du PDF changent d'une version à l'autre
TYPE_MIME = "application/pdf"
VERSION_GABARIT = "m5.facture_pdf.v1"
_ESPACE_INSECABLE = " "
_CENT = Decimal("0.01")
_SEPARATEURS_FR_CA = str.maketrans({",": _ESPACE_INSECABLE, ".": ","})
_ENCODAGE_POLICE = "cp1252"
_BLANCS = "\t\n\r\u000b\u000c"
_MOIS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_TPS = re.compile(r"^(\d{9})\s?RT\s?(\d{4})$")
_TVQ = re.compile(r"^(\d{10})\s?TQ\s?(\d{4})$")
_A_DECLARER_ENTREPRISE = (
    "déclarer configuration.facturation.entreprise : raison_sociale (texte), adresse (1 à 4 lignes), numero_tps "
    "(forme 123456789 RT0001) et numero_tvq (forme 1234567890 TQ0001) — les numéros d'inscription de l'entreprise, "
    "à reprendre de ses avis d'inscription ; jamais inventés"
)
# Les taxes que M5 sait nommer sur une facture : l'identifiant du taux versionné (`contracts/taux_fiscaux.v1.yaml`) vers
# (libellé français, libellé anglais, champ du profil qui porte le numéro d'inscription).
_TAXES_CONNUES = {
    "tps_federale": ("TPS", "GST", "numero_tps"),
    "tvq_quebec": ("TVQ", "QST", "numero_tvq"),
}
_ETIQUETTES = {
    "facture": ("Facture", "Invoice"),
    "numero": ("Numéro de facture", "Invoice number"),
    "emission": ("Date d'émission", "Issue date"),
    "echeance": ("Date d'échéance", "Due date"),
    "conditions": ("Conditions de paiement", "Payment terms"),
    "comptant": ("Payable à la réception", "Due on receipt"),
    "net": ("Net {n} jours", "Net {n} days"),
    "contrat": ("Référence du contrat (devis)", "Contract reference (quote)"),
    "jalon": ("Jalon {k} de {n}", "Milestone {k} of {n}"),
    "facture_a": ("Facturé à", "Bill to"),
    "description": ("Description", "Description"),
    "quantite": ("Quantité", "Quantity"),
    "prix_unitaire": ("Prix unitaire", "Unit price"),
    "montant": ("Montant", "Amount"),
    "sous_total": ("Sous-total avant taxes", "Subtotal before taxes"),
    "total": ("Total", "Total"),
    "recap": ("Récapitulatif du contrat", "Contract summary"),
    "prix_contrat": ("Prix du contrat avant taxes", "Contract price before taxes"),
    "facture_a_ce_jour": (
        "Facturé à ce jour, cette facture incluse (avant taxes)",
        "Invoiced to date, this invoice included (before taxes)",
    ),
    "solde": ("Solde restant à facturer (avant taxes)", "Balance left to invoice (before taxes)"),
    "devise": ("Montants en dollars canadiens (CAD).", "Amounts in Canadian dollars (CAD)."),
    "page": ("Page", "Page"),
    "etat_compte": ("État de compte", "Account statement"),
    "au": ("Au", "As of"),
    "facture_court": ("Facture", "Invoice"),
    "total_facture": ("Total", "Total"),
    "credits": ("Crédits", "Credits"),
    "paye": ("Payé", "Paid"),
    "solde_court": ("Solde", "Balance"),
    "statut": ("Statut", "Status"),
    "a_payer": ("À payer", "Due"),
    "en_retard": ("En retard de {n} j", "{n} d overdue"),
    "payee": ("Payée", "Paid"),
    "total_facture_periode": ("Total facturé", "Total invoiced"),
    "total_paye": ("Total payé", "Total paid"),
    "total_du": ("Solde dû", "Balance due"),
    "dont_retard": ("dont en retard", "of which overdue"),
}


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_facturation.construire_verdict(code, detail=detail)


# ---------------------------------------------------------------------------------------------------------- la brique
def _version_brique() -> tuple[str | None, str]:
    try:
        version = metadata.version(NOM_BRIQUE)
    except metadata.PackageNotFoundError:
        return None, f"{NOM_BRIQUE} absent"
    if version != VERSION_BRIQUE:
        return None, f"{NOM_BRIQUE} {version} trouvé, {VERSION_BRIQUE} exigé"
    return version, ""


def pdf_installe() -> tuple[bool, str]:
    """`(True, version)` si la brique PDF est utilisable, sinon `(False, raison)`. Jamais d'exception."""
    version, raison = _version_brique()
    if version is None:
        return False, raison
    try:
        import_module("reportlab.platypus")
    except ImportError:
        return False, f"{NOM_BRIQUE} installé mais non importable"
    return True, version


# ------------------------------------------------------------------------------------------------ mise en forme fr-CA
def formater_montant(valeur: Any) -> str:
    """`Decimal('1234.5')` -> `'1 234,50 $'` (espaces insécables). Lève `ValueError` si la valeur n'est pas un `Decimal`
    fini ou exigerait un arrondi : un montant est repris tel que le code l'a calculé, jamais arrondi en silence."""
    if not isinstance(valeur, Decimal) or not valeur.is_finite() or valeur.adjusted() > 14:
        raise ValueError("montant non affichable")
    try:
        au_cent = valeur.quantize(_CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as erreur:
        raise ValueError("montant non affichable") from erreur
    if au_cent != valeur:
        raise ValueError("montant à plus de deux décimales : aucun arrondi n'est fait ici")
    if au_cent.is_zero():
        au_cent = abs(au_cent)
    return format(au_cent, ",.2f").translate(_SEPARATEURS_FR_CA) + _ESPACE_INSECABLE + "$"


def _quantite(valeur: Decimal) -> str:
    if not valeur.is_finite() or valeur.adjusted() > 14 or valeur.as_tuple().exponent < -6:
        raise ValueError("quantité non affichable")
    return format(valeur, ",f").translate(_SEPARATEURS_FR_CA)


def _montant_ou_verdict(valeur: Any, champ: str) -> tuple[str | None, dict[str, str] | None]:
    try:
        return formater_montant(valeur if isinstance(valeur, Decimal) else Decimal(str(valeur))), None
    except (ValueError, InvalidOperation):
        return None, _verdict(
            "REJ-PDF-MONTANT-INVALIDE", f"{champ} doit tomber juste au cent : le PDF reprend le montant sans l'arrondir"
        )


def _inscription(libelle_fr: str, libelle_en: str, numero: str, langue: str) -> str:
    """« N° TPS 123456789 RT0001 » ; bilingue : « N° TPS / GST no. 123456789 RT0001 »."""
    if langue == "fr":
        return f"N° {libelle_fr} {numero}"
    return f"N° {libelle_fr} / {libelle_en} no. {numero}"


def _date_lisible(jour: date) -> str:
    return f"{'1er' if jour.day == 1 else jour.day} {_MOIS[jour.month - 1]} {jour.year}"


def _etiquette(cle: str, langue: str, **valeurs: Any) -> str:
    francais, anglais = _ETIQUETTES[cle]
    texte = francais if langue == "fr" else f"{francais} / {anglais}"
    return texte.format(**valeurs) if valeurs else texte


def _date_selon_langue(jour: date, langue: str) -> str:
    return _date_lisible(jour) if langue == "fr" else jour.isoformat()


def _date_pdf(instant: datetime) -> str:
    minutes = int(instant.utcoffset().total_seconds() // 60)
    signe = "-" if minutes < 0 else "+"
    heures, reste = divmod(abs(minutes), 60)
    return (
        f"D:{instant.year:04d}{instant.month:02d}{instant.day:02d}"
        f"{instant.hour:02d}{instant.minute:02d}{instant.second:02d}{signe}{heures:02d}'{reste:02d}'"
    )


# ------------------------------------------------------------------------------------------------- texte libre = donnée
def _dessinable(caractere: str) -> bool:
    if unicodedata.category(caractere) == "Cc":
        return False
    try:
        caractere.encode(_ENCODAGE_POLICE)
    except UnicodeEncodeError:
        return False
    return True


def _texte(valeur: Any, champ: str, code: str, *, maximum: int = 120) -> tuple[str | None, dict[str, str] | None]:
    """Un texte d'UNE ligne, prêt à dessiner : NFC, blancs ramenés à une espace, borné, contrôlé contre la police du PDF
    (jamais un carré « ■ » silencieux). Refus : nomme le champ et les points de code fautifs, jamais la valeur."""
    if not isinstance(valeur, str) or not valeur.strip():
        return None, _verdict(code, f"{champ} : texte non vide exigé")
    normalise = unicodedata.normalize("NFC", valeur).strip()
    if len(normalise) > maximum:
        return None, _verdict(code, f"{champ} : {maximum} caractères au plus")
    fautifs: list[str] = []
    morceaux: list[str] = []
    for caractere in normalise:
        if caractere in _BLANCS:
            morceaux.append(" ")
        elif _dessinable(caractere):
            morceaux.append(caractere)
        else:
            point = f"U+{ord(caractere):04X}"
            if point not in fautifs:
                fautifs.append(point)
    if fautifs:
        return None, _verdict(
            "REJ-PDF-CARACTERE-NON-SUPPORTE",
            f"{champ} : caractères que la police du PDF ne dessine pas ({', '.join(fautifs[:8])}) ; "
            "remplacer par des caractères du français (Windows-1252)",
        )
    return "".join(morceaux), None


def _adresse(valeur: Any, champ: str, code: str) -> tuple[list[str] | None, dict[str, str] | None]:
    if not isinstance(valeur, (list, tuple)) or not 1 <= len(valeur) <= 4:
        return None, _verdict(code, f"{champ} : liste de 1 à 4 lignes")
    lignes: list[str] = []
    for index, ligne in enumerate(valeur, start=1):
        propre, refus = _texte(ligne, f"{champ} ligne {index}", code, maximum=80)
        if refus is not None:
            return None, refus
        lignes.append(propre)
    return lignes, None


def lire_entreprise(
    brut: Any, taxes_presentes: Sequence[str] = ()
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le profil de facturation de l'entreprise (`configuration.facturation.entreprise`), ou le refus qui dit QUOI
    déclarer. Raison sociale et adresse sont toujours exigées ; le numéro d'inscription d'une taxe l'est seulement si la
    facture porte cette taxe (`taxes_presentes` : identifiants des taux)."""
    declaration = brut if isinstance(brut, Mapping) else {}
    manques: list[str] = []
    raison, refus_raison = _texte(declaration.get("raison_sociale"), "raison_sociale", "REJ-PDF-ENTREPRISE-A-DECLARER")
    if raison is None:
        if refus_raison["code"] == "REJ-PDF-CARACTERE-NON-SUPPORTE":
            return None, refus_raison
        manques.append("raison_sociale")
    adresse, refus_adresse = _adresse(declaration.get("adresse"), "adresse", "REJ-PDF-ENTREPRISE-A-DECLARER")
    if adresse is None:
        if refus_adresse["code"] == "REJ-PDF-CARACTERE-NON-SUPPORTE":
            return None, refus_adresse
        manques.append("adresse")
    numeros: dict[str, str] = {}
    for taxe_id in taxes_presentes:
        connue = _TAXES_CONNUES.get(taxe_id)
        if connue is None:
            continue
        champ = connue[2]
        valeur = declaration.get(champ)
        motif = _TPS if champ == "numero_tps" else _TVQ
        trouve = motif.fullmatch(valeur.strip().upper()) if isinstance(valeur, str) else None
        if trouve is None:
            manques.append(champ)
            continue
        suffixe = "RT" if champ == "numero_tps" else "TQ"
        numeros[champ] = f"{trouve.group(1)} {suffixe}{trouve.group(2)}"
    if manques:
        return None, _verdict(
            "REJ-PDF-ENTREPRISE-A-DECLARER",
            f"manque ou forme invalide : {', '.join(manques)}. " + _A_DECLARER_ENTREPRISE,
        )
    profil: dict[str, Any] = {"raison_sociale": raison, "adresse": adresse, **numeros}
    for facultatif in ("courriel", "telephone"):
        valeur = declaration.get(facultatif)
        if valeur is not None:
            propre, refus = _texte(valeur, facultatif, "REJ-PDF-ENTREPRISE-A-DECLARER", maximum=80)
            if refus is not None:
                return None, refus
            profil[facultatif] = propre
    return profil, None


def lire_destinataire(brut: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le nom et l'adresse du client, fournis à l'appel (M5 ne les garde pas : un identifiant opaque seulement)."""
    if not isinstance(brut, Mapping) or set(brut) != {"nom", "adresse"}:
        return None, _verdict("REJ-PDF-DESTINATAIRE-INVALIDE", "destinataire : {nom, adresse (1 à 4 lignes)} exigés")
    nom, refus = _texte(brut["nom"], "destinataire.nom", "REJ-PDF-DESTINATAIRE-INVALIDE")
    if refus is not None:
        return None, refus
    adresse, refus = _adresse(brut["adresse"], "destinataire.adresse", "REJ-PDF-DESTINATAIRE-INVALIDE")
    if refus is not None:
        return None, refus
    return {"nom": nom, "adresse": adresse}, None


def _langue_valide(langue: Any) -> dict[str, str] | None:
    if langue not in ("fr", "bilingue"):
        return _verdict("REJ-PDF-LANGUE-INVALIDE", "langue : « fr » ou « bilingue » (français et anglais)")
    return None


# ------------------------------------------------------------------------------------------------- contenu structuré
def _decimal(valeur: Any) -> Decimal | None:
    if isinstance(valeur, Decimal):
        return valeur
    try:
        return Decimal(str(valeur))
    except InvalidOperation:
        return None


def contenu_facture(
    etat: Mapping[str, Any],
    plan: Mapping[str, Any] | None,
    entreprise_brute: Any,
    destinataire_brut: Any,
    langue: Any,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le CONTENU structuré (ce que le PDF affichera, rien d'autre) de la facture approuvée et numérotée `etat`, ou le
    refus. Le même contenu produit toujours les mêmes octets ; son empreinte est celle du scellé."""
    refus = _langue_valide(langue)
    if refus is not None:
        return None, refus
    if etat.get("statut") not in ("ENVOYEE", "PAYEE") or not isinstance(etat.get("numero_facture"), str):
        return None, _verdict(
            "REJ-PDF-FACTURE-NON-EMISE",
            f"facture {etat.get('facture_id')!r} : le PDF ne rend qu'une facture approuvée (N4) ET numérotée "
            "(statut ENVOYEE ou PAYEE, numérotation déclarée avant l'émission)",
        )
    emission = facturation.jour_de(etat.get("date_envoi"))
    if emission is None or datetime.fromisoformat(etat["date_envoi"]).utcoffset() is None:
        return None, _verdict("REJ-PDF-FACTURE-NON-EMISE", "facture émise sans date d'envoi lisible avec fuseau")
    taxes_facture = list(etat.get("taxes", ()))
    entreprise, refus = lire_entreprise(entreprise_brute, [t["id"] for t in taxes_facture])
    if refus is not None:
        return None, refus
    destinataire, refus = lire_destinataire(destinataire_brut)
    if refus is not None:
        return None, refus

    lignes: list[dict[str, str]] = []
    for index, ligne in enumerate(etat["lignes"], start=1):
        description, refus = _texte(
            ligne["description"], f"ligne {index} description", "REJ-PDF-CARACTERE-NON-SUPPORTE", maximum=300
        )
        if refus is not None:
            return None, refus
        unite, refus = _texte(ligne["unite"], f"ligne {index} unité", "REJ-PDF-CARACTERE-NON-SUPPORTE", maximum=40)
        if refus is not None:
            return None, refus
        try:
            quantite = _quantite(_decimal(ligne["quantite"]))
        except (ValueError, TypeError):
            return None, _verdict("REJ-PDF-MONTANT-INVALIDE", f"ligne {index} : quantité non affichable")
        prix, refus = _montant_ou_verdict(ligne["prix_unitaire"], f"ligne {index} prix_unitaire")
        if refus is not None:
            return None, refus
        montant, refus = _montant_ou_verdict(ligne["montant"], f"ligne {index} montant")
        if refus is not None:
            return None, refus
        lignes.append(
            {
                "description": description,
                "quantite": f"{quantite}{_ESPACE_INSECABLE}{unite}",
                "prix_unitaire": prix,
                "montant": montant,
            }
        )

    sous_total, refus = _montant_ou_verdict(etat["montant_avant_taxes"], "montant_avant_taxes")
    if refus is not None:
        return None, refus
    total, refus = _montant_ou_verdict(etat["montant_apres_taxes"], "montant_apres_taxes")
    if refus is not None:
        return None, refus
    taxes_contenu: list[dict[str, str]] = []
    for taxe in taxes_facture:
        libelle_fr, libelle_en, champ = _TAXES_CONNUES.get(taxe["id"], (None, None, None))
        if libelle_fr is None:
            libelle_fr, refus = _texte(taxe["nom"], "nom de la taxe", "REJ-PDF-MONTANT-INVALIDE", maximum=80)
            if refus is not None:
                return None, refus
            libelle_en = libelle_fr
        montant, refus = _montant_ou_verdict(taxe["montant"], f"taxe {taxe['id']}")
        if refus is not None:
            return None, refus
        pourcentage = format((Decimal(str(taxe["taux"])) * 100).normalize(), "f").translate(_SEPARATEURS_FR_CA)
        taxes_contenu.append(
            {
                "libelle": libelle_fr if langue == "fr" else f"{libelle_fr} / {libelle_en}",
                "taux": f"{pourcentage}{_ESPACE_INSECABLE}%",
                "montant": montant,
                "inscription": _inscription(libelle_fr, libelle_en, entreprise[champ], langue) if champ else None,
            }
        )

    echeance = facturation.jour_de(etat.get("echeance"))
    delai = etat.get("delai_paiement_jours")
    if echeance is not None and type(delai) is int:
        conditions = _etiquette("comptant", langue) if delai == 0 else _etiquette("net", langue, n=delai)
    else:
        conditions = None
    jalon = None
    recapitulatif = None
    if etat.get("plan_id") is not None:
        if plan is None or plan.get("plan_id") != etat["plan_id"]:
            return None, _verdict(
                "REJ-PDF-FACTURE-INTROUVABLE", f"plan {etat['plan_id']!r} de cette facture de jalon introuvable"
            )
        jalon = _etiquette("jalon", langue, k=etat["jalon_rang"], n=etat["jalons_total"])
        facture_jusqua = sum(
            (Decimal(j["montant_avant_taxes"]) for j in plan["jalons"] if j["rang"] <= etat["jalon_rang"]),
            Decimal("0"),
        )
        prix_contrat = Decimal(plan["total_avant_taxes"])
        valeurs = {}
        for cle, nombre in (
            ("prix_contrat", prix_contrat),
            ("facture_a_ce_jour", facture_jusqua),
            ("solde", prix_contrat - facture_jusqua),
        ):
            valeurs[cle], refus = _montant_ou_verdict(nombre, cle)
            if refus is not None:
                return None, refus
        recapitulatif = valeurs
    reference, refus = _texte(etat["devis_id"], "devis_id", "REJ-PDF-CARACTERE-NON-SUPPORTE", maximum=128)
    if refus is not None:
        return None, refus
    numero, refus = _texte(etat["numero_facture"], "numero_facture", "REJ-PDF-FACTURE-NON-EMISE", maximum=40)
    if refus is not None:
        return None, refus
    return {
        "type": "facture",
        "gabarit": VERSION_GABARIT,
        "langue": langue,
        "entreprise": entreprise,
        "destinataire": destinataire,
        "numero": numero,
        "emission": emission.isoformat(),
        "emission_lisible": _date_selon_langue(emission, langue),
        "echeance": echeance.isoformat() if echeance is not None else None,
        "echeance_lisible": _date_selon_langue(echeance, langue) if echeance is not None else None,
        "conditions": conditions,
        "reference_contrat": reference,
        "jalon": jalon,
        "libelle_jalon": etat.get("libelle_jalon"),
        "lignes": lignes,
        "sous_total": sous_total,
        "taxes": taxes_contenu,
        "total": total,
        "recapitulatif": recapitulatif,
        "date_pdf": _date_pdf(datetime.fromisoformat(etat["date_envoi"])),
    }, None


def contenu_etat_compte(
    client_id: str,
    factures: Sequence[Mapping[str, Any]],
    credits_ttc: Mapping[str, Decimal],
    au: date,
    entreprise_brute: Any,
    destinataire_brut: Any,
    langue: Any,
    horodatage: str,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le contenu structuré de l'état de compte d'un client à la date `au` : ses factures émises (ENVOYEE ou PAYEE) avec
    leurs crédits (notes de crédit proposées), ce qui est payé, le solde, et le retard calculé à `au` (jamais
    deviné)."""
    refus = _langue_valide(langue)
    if refus is not None:
        return None, refus
    entreprise, refus = lire_entreprise(entreprise_brute)
    if refus is not None:
        return None, refus
    destinataire, refus = lire_destinataire(destinataire_brut)
    if refus is not None:
        return None, refus
    emises = [f for f in factures if f.get("statut") in ("ENVOYEE", "PAYEE") and f.get("client_id") == client_id]
    if not emises:
        return None, _verdict("REJ-PDF-ETAT-COMPTE-VIDE", "aucune facture émise (envoyée ou payée) pour ce client")
    emises.sort(key=lambda f: (str(f.get("date_envoi")), str(f.get("numero_facture") or f["facture_id"])))
    lignes: list[dict[str, str]] = []
    facture_total = paye_total = du_total = retard_total = Decimal("0")
    for etat in emises:
        montant = etat.get("montant_apres_taxes")
        emission = facturation.jour_de(etat.get("date_envoi"))
        if not isinstance(montant, Decimal) or emission is None:
            return None, _verdict(
                "REJ-PDF-MONTANT-INVALIDE", f"facture {etat['facture_id']!r} : montant ou date illisible"
            )
        credit = credits_ttc.get(etat["facture_id"], Decimal("0"))
        paye = montant - credit if etat["statut"] == "PAYEE" else Decimal("0")
        solde = montant - credit - paye
        vue = facturation.statut_effectif(etat, au)
        if etat["statut"] == "PAYEE":
            statut = _etiquette("payee", langue)
        elif vue["statut_effectif"] == "EN_RETARD":
            statut = _etiquette("en_retard", langue, n=vue["jours_de_retard"])
            retard_total += solde
        else:
            statut = _etiquette("a_payer", langue)
        facture_total += montant
        paye_total += paye
        du_total += solde
        cellules = {}
        for cle, nombre in (("total", montant), ("credits", credit), ("paye", paye), ("solde", solde)):
            cellules[cle], refus = _montant_ou_verdict(nombre, f"{etat['facture_id']} {cle}")
            if refus is not None:
                return None, refus
        identifiant, refus = _texte(
            str(etat.get("numero_facture") or etat["facture_id"]), "numéro", "REJ-PDF-FACTURE-NON-EMISE", maximum=128
        )
        if refus is not None:
            return None, refus
        lignes.append(
            {
                "facture": identifiant,
                "emission": _date_selon_langue(emission, langue),
                "echeance": (
                    _date_selon_langue(facturation.jour_de(etat["echeance"]), langue)
                    if facturation.jour_de(etat.get("echeance")) is not None
                    else "—"
                ),
                **cellules,
                "statut": statut,
            }
        )
    totaux = {}
    for cle, nombre in (("facture", facture_total), ("paye", paye_total), ("du", du_total), ("retard", retard_total)):
        totaux[cle], refus = _montant_ou_verdict(nombre, f"total {cle}")
        if refus is not None:
            return None, refus
    instant = datetime.fromisoformat(horodatage)
    return {
        "type": "etat_compte",
        "gabarit": VERSION_GABARIT,
        "langue": langue,
        "entreprise": entreprise,
        "destinataire": destinataire,
        "client_id": client_id,
        "au": au.isoformat(),
        "au_lisible": _date_selon_langue(au, langue),
        "lignes": lignes,
        "totaux": totaux,
        "date_pdf": _date_pdf(instant),
    }, None


def empreinte_contenu(contenu: Mapping[str, Any]) -> str:
    """L'empreinte SHA-256 (hex) du contenu structuré, en JSON canonique : ce que le PDF affichera."""
    texte = json.dumps(contenu, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texte.encode("ascii")).hexdigest()


# ------------------------------------------------------------------------------------------------------------- rendu
def _paragraphe(texte: str, style: Any) -> Any:
    """SEUL passage d'un texte libre vers un paragraphe : échappé, donc affiché tel quel, jamais interprété."""
    from reportlab.platypus import Paragraph

    return Paragraph(escape(texte, quote=False), style)


def _styles() -> dict[str, Any]:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle

    normal = ParagraphStyle("normal", fontName="Helvetica", fontSize=9.5, leading=12)
    return {
        "titre": ParagraphStyle("titre", fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=4),
        "normal": normal,
        "gras": ParagraphStyle("gras", parent=normal, fontName="Helvetica-Bold"),
        "droite": ParagraphStyle("droite", parent=normal, alignment=TA_RIGHT),
        "gras_droite": ParagraphStyle("gras_droite", parent=normal, fontName="Helvetica-Bold", alignment=TA_RIGHT),
        "petit": ParagraphStyle("petit", parent=normal, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555")),
    }


def _bloc(lignes: Sequence[str], style: Any) -> list[Any]:
    return [_paragraphe(ligne, style) for ligne in lignes]


def _rendre_facture(contenu: Mapping[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

    langue = contenu["langue"]
    st = _styles()
    largeur, _hauteur = letter
    marge = 54
    entreprise = contenu["entreprise"]
    sortie = io.BytesIO()
    numero = contenu["numero"]

    def decorer(canvas: Any, _doc: Any) -> None:
        canvas.setDateFormatter(lambda *_ignore: contenu["date_pdf"])
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(marge, 30, f"{_etiquette('facture', langue)} {numero}")
        canvas.drawRightString(largeur - marge, 30, f"{_etiquette('page', langue)} {canvas.getPageNumber()}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        sortie,
        pagesize=letter,
        leftMargin=marge,
        rightMargin=marge,
        topMargin=54,
        bottomMargin=54,
        title=f"{_etiquette('facture', 'fr')} {numero}",
        author=entreprise["raison_sociale"],
        subject="Facture",
        creator="OPSYS-AI M5 FinanceCore",
        lang="fr-CA",
        invariant=1,
        pageCompression=1,
    )
    emetteur = [entreprise["raison_sociale"], *entreprise["adresse"]]
    for facultatif in ("telephone", "courriel"):
        if facultatif in entreprise:
            emetteur.append(entreprise[facultatif])
    for taxe in contenu["taxes"]:
        if taxe["inscription"]:
            emetteur.append(taxe["inscription"])
    meta = [
        f"{_etiquette('numero', langue)} : {numero}",
        f"{_etiquette('emission', langue)} : {contenu['emission_lisible']}",
    ]
    if contenu["echeance_lisible"]:
        meta.append(f"{_etiquette('echeance', langue)} : {contenu['echeance_lisible']}")
    if contenu["conditions"]:
        meta.append(f"{_etiquette('conditions', langue)} : {contenu['conditions']}")
    meta.append(f"{_etiquette('contrat', langue)} : {contenu['reference_contrat']}")
    if contenu["jalon"]:
        meta.append(f"{contenu['jalon']} — {contenu['libelle_jalon']}")
    entete = Table([[_bloc(emetteur, st["normal"]), _bloc(meta, st["droite"])]], colWidths=[246, 246])
    entete.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    destinataire = contenu["destinataire"]
    lignes = [
        [
            _paragraphe(_etiquette("description", langue), st["gras"]),
            _paragraphe(_etiquette("quantite", langue), st["gras"]),
            _paragraphe(_etiquette("prix_unitaire", langue), st["gras_droite"]),
            _paragraphe(_etiquette("montant", langue), st["gras_droite"]),
        ]
    ]
    for ligne in contenu["lignes"]:
        lignes.append(
            [
                _paragraphe(ligne["description"], st["normal"]),
                _paragraphe(ligne["quantite"], st["normal"]),
                _paragraphe(ligne["prix_unitaire"], st["droite"]),
                _paragraphe(ligne["montant"], st["droite"]),
            ]
        )
    table = Table(lignes, colWidths=[222, 88, 91, 91], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    totaux = [
        [_paragraphe(_etiquette("sous_total", langue), st["droite"]), _paragraphe(contenu["sous_total"], st["droite"])]
    ]
    for taxe in contenu["taxes"]:
        totaux.append(
            [
                _paragraphe(f"{taxe['libelle']} ({taxe['taux']})", st["droite"]),
                _paragraphe(taxe["montant"], st["droite"]),
            ]
        )
    totaux.append(
        [_paragraphe(_etiquette("total", langue), st["gras_droite"]), _paragraphe(contenu["total"], st["gras_droite"])]
    )
    table_totaux = Table(totaux, colWidths=[401, 91])
    table_totaux.setStyle(TableStyle([("LINEABOVE", (0, len(totaux) - 1), (-1, len(totaux) - 1), 1, colors.black)]))

    elements = [
        _paragraphe(f"{_etiquette('facture', langue)} {numero}", st["titre"]),
        Spacer(1, 6),
        entete,
        Spacer(1, 12),
        _paragraphe(_etiquette("facture_a", langue), st["gras"]),
        *_bloc([destinataire["nom"], *destinataire["adresse"]], st["normal"]),
        Spacer(1, 12),
        table,
        Spacer(1, 6),
        table_totaux,
    ]
    if contenu["recapitulatif"]:
        recap = contenu["recapitulatif"]
        table_recap = Table(
            [
                [_paragraphe(_etiquette(cle, langue), st["normal"]), _paragraphe(recap[cle], st["droite"])]
                for cle in ("prix_contrat", "facture_a_ce_jour", "solde")
            ],
            colWidths=[401, 91],
        )
        elements += [Spacer(1, 12), _paragraphe(_etiquette("recap", langue), st["gras"]), table_recap]
    elements += [Spacer(1, 10), _paragraphe(_etiquette("devise", langue), st["petit"])]
    document.build(elements, onFirstPage=decorer, onLaterPages=decorer)
    return sortie.getvalue()


def _rendre_etat_compte(contenu: Mapping[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

    langue = contenu["langue"]
    st = _styles()
    largeur, _hauteur = letter
    marge = 54
    entreprise = contenu["entreprise"]
    sortie = io.BytesIO()

    def decorer(canvas: Any, _doc: Any) -> None:
        canvas.setDateFormatter(lambda *_ignore: contenu["date_pdf"])
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(marge, 30, f"{_etiquette('etat_compte', langue)} — {contenu['au']}")
        canvas.drawRightString(largeur - marge, 30, f"{_etiquette('page', langue)} {canvas.getPageNumber()}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        sortie,
        pagesize=letter,
        leftMargin=marge,
        rightMargin=marge,
        topMargin=54,
        bottomMargin=54,
        title=f"{_etiquette('etat_compte', 'fr')} {contenu['au']}",
        author=entreprise["raison_sociale"],
        subject="État de compte",
        creator="OPSYS-AI M5 FinanceCore",
        lang="fr-CA",
        invariant=1,
        pageCompression=1,
    )
    destinataire = contenu["destinataire"]
    entetes = ["facture_court", "emission", "echeance", "total_facture", "credits", "paye", "solde_court", "statut"]
    rangs = [[_paragraphe(_etiquette(cle, langue), st["gras"]) for cle in entetes]]
    for ligne in contenu["lignes"]:
        rangs.append(
            [
                _paragraphe(ligne["facture"], st["normal"]),
                _paragraphe(ligne["emission"], st["normal"]),
                _paragraphe(ligne["echeance"], st["normal"]),
                _paragraphe(ligne["total"], st["droite"]),
                _paragraphe(ligne["credits"], st["droite"]),
                _paragraphe(ligne["paye"], st["droite"]),
                _paragraphe(ligne["solde"], st["droite"]),
                _paragraphe(ligne["statut"], st["normal"]),
            ]
        )
    table = Table(rangs, colWidths=[60, 62, 62, 62, 52, 62, 62, 70], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    totaux = contenu["totaux"]
    table_totaux = Table(
        [
            [_paragraphe(_etiquette(cle_etiquette, langue), st["droite"]), _paragraphe(totaux[cle], st["gras_droite"])]
            for cle_etiquette, cle in (
                ("total_facture_periode", "facture"),
                ("total_paye", "paye"),
                ("total_du", "du"),
                ("dont_retard", "retard"),
            )
        ],
        colWidths=[401, 91],
    )
    elements = [
        _paragraphe(f"{_etiquette('etat_compte', langue)}", st["titre"]),
        _paragraphe(f"{_etiquette('au', langue)} {contenu['au_lisible']}", st["normal"]),
        Spacer(1, 8),
        *_bloc([entreprise["raison_sociale"], *entreprise["adresse"]], st["normal"]),
        Spacer(1, 8),
        _paragraphe(_etiquette("facture_a", langue), st["gras"]),
        *_bloc([destinataire["nom"], *destinataire["adresse"]], st["normal"]),
        Spacer(1, 12),
        table,
        Spacer(1, 8),
        table_totaux,
        Spacer(1, 10),
        _paragraphe(_etiquette("devise", langue), st["petit"]),
    ]
    document.build(elements, onFirstPage=decorer, onLaterPages=decorer)
    return sortie.getvalue()


def rendre(contenu: Mapping[str, Any]) -> tuple[bytes | None, dict[str, str] | None]:
    """Les octets du PDF d'un contenu structuré, ou le refus : brique absente (quoi installer), rendu impossible. Toute
    exception de la brique devient un verdict SANS son message (il peut citer le texte du client)."""
    installe, raison = pdf_installe()
    if not installe:
        return None, _verdict(
            "REJ-PDF-BRIQUE-ABSENTE",
            f"brique PDF indisponible ({raison}) : installer l'extra soumission "
            f"(pip install 'opsys-ai[soumission]', {NOM_BRIQUE}=={VERSION_BRIQUE})",
        )
    erreur_de_mise_en_page = import_module("reportlab.platypus.doctemplate").LayoutError
    dessiner = _rendre_facture if contenu["type"] == "facture" else _rendre_etat_compte
    try:
        return dessiner(contenu), None
    except erreur_de_mise_en_page:
        return None, _verdict(
            "REJ-PDF-RENDU-IMPOSSIBLE", "une ligne est plus haute qu'une page : raccourcir sa description"
        )
    except Exception:  # noqa: BLE001 — frontière d'une brique tierce : jamais son message
        return None, _verdict(
            "REJ-PDF-RENDU-IMPOSSIBLE",
            f"le PDF n'a pas pu être dessiné (erreur de la brique {NOM_BRIQUE}) : signaler l'incident",
        )


# ------------------------------------------------------------------------------------------------------------ scellé
def sceller(
    registre_documents: Any,
    *,
    type_entree: str,
    cle: str,
    corps: Mapping[str, Any],
    empreinte_pdf: str,
    strict: bool,
    horodatage: str,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Scelle le PDF au registre `documents_facturation` : l'EMPREINTE du contenu et celle du PDF, jamais ses octets
    ni le nom du client. Rejouable : la même clé et la même empreinte rendent `deja` sans rien écrire. Pour une facture
    (`strict`), la même clé avec une AUTRE empreinte est `REJ-PDF-SCELLE-DIFFERENT` (jamais un écrasement : brique
    modifiée, ou contenu altéré)."""
    identifiant = encodage.empreinte("m5.documents_facturation", type_entree, cle)[:24]
    for maillon in registre_documents.lire():
        if maillon.get("type_entree") == type_entree and maillon.get("scelle_id") == identifiant:
            if maillon["empreinte_pdf"] == empreinte_pdf:
                return {"statut": "deja", "scelle": maillon}, None
            if strict:
                return None, _verdict(
                    "REJ-PDF-SCELLE-DIFFERENT",
                    f"le scellé {identifiant} porte {maillon['empreinte_pdf'][:16]}…, le rendu donne "
                    f"{empreinte_pdf[:16]}… : le contenu ou la brique ont changé, rien n'est réécrit",
                )
    ligne_id = registre_documents.ajouter(
        {
            "type_entree": type_entree,
            "scelle_id": identifiant,
            "cle": cle,
            **dict(corps),
            "empreinte_pdf": empreinte_pdf,
            "horodatage": horodatage,
        }
    )
    for maillon in registre_documents.lire():
        if maillon["ligne_id"] == ligne_id:
            return {"statut": "nouveau", "scelle": maillon}, None
    raise RuntimeError("maillon du scellé ajouté introuvable")
