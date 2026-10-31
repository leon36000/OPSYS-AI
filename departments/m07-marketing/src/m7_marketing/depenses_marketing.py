"""Dépenses marketing de M7 (`m7.depenses_marketing`, schéma `opsys.m7.depenses_marketing/v1`).

M7 est propriétaire du chiffre : ce module ne fait QUE retrouver des relevés de dépense sourcés, déjà
inscrits au registre durable `depenses_marketing`, et additionner des montants décimaux d'une même base
de taxes. Il ne convertit aucune devise, ne proratise aucun relevé, n'estime rien.

Règle dure : une absence n'est jamais un zéro. Un montant n'existe que si un relevé le porte, avec sa
source et l'instant du relevé. Un zéro n'existe que s'il a été DÉCLARÉ par un relevé (`0.00` explicite).
Sans relevé qui couvre la période, le canal est `NON_BRANCHEE` (montant `null`), jamais `0.00`.

Les libellés de campagne sont des DONNÉES saisies : conservés tels quels, jamais interprétés, jamais
recopiés ailleurs que dans leur ligne.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from opsys import stockage
from opsys.stockage.maillons import EcritureConcurrente
from opsys.stockage.schema import REGISTRES

from .performance_campagnes import _longueur_octets

DEPARTEMENT = "m07-marketing"
REGISTRE = (DEPARTEMENT, "depenses_marketing")
SCHEMA = "opsys.m7.depenses_marketing/v1"
TYPE_MAILLON = "releve_depense"

# Énumérés métier fermés : un canal ou une source hors de ces listes est refusé, jamais deviné.
CANAUX = ("google_ads", "meta")
SOURCES = ("DECLARATION_PROPRIETAIRE", "RELEVE_PLATEFORME")
BASES_TAXES = ("HORS_TAXES", "TAXES_INCLUSES")
STATUTS = ("CONNUE", "NON_BRANCHEE", "PARTIELLE")

# Bornes du lecteur : aucune troncature, un dépassement est une erreur (comme performance_campagnes).
MAX_LIGNES = 10_000
MAX_OCTETS_TOTAL = 8 * 1024 * 1024
MAX_OCTETS_LIGNE = 64 * 1024
MAX_JOURS_RELEVE = 366
MAX_JOURS_LECTURE = 365

_CHAMPS = (
    "releve_id", "revision", "canal", "campagne_ref", "libelle_campagne", "periode_debut", "periode_fin",
    "montant_cad", "devise", "base_taxes", "source", "source_ref", "releve_le",
)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_CAMPAGNE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_SOURCE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,79}$")
_MONTANT = re.compile(r"^[0-9]{1,12}(?:\.[0-9]{1,2})?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_CENTIME = Decimal("0.01")
_LIBELLE_MAX = 120


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _date(valeur: Any, champ: str) -> date:
    if not isinstance(valeur, str) or not _DATE.fullmatch(valeur):
        raise _refus("REJ-DEPENSES-DATE-INVALIDE", f"{champ} attendu AAAA-MM-JJ")
    try:
        return date.fromisoformat(valeur)
    except ValueError as exc:
        raise _refus("REJ-DEPENSES-DATE-INVALIDE", f"{champ} n'est pas une date civile") from exc


def _instant(valeur: Any) -> datetime:
    if not isinstance(valeur, str) or len(valeur) > 40:
        raise _refus("REJ-DEPENSES-INSTANT-INVALIDE", "releve_le attendu en RFC 3339 avec fuseau")
    try:
        instant = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _refus("REJ-DEPENSES-INSTANT-INVALIDE", "releve_le n'est pas un instant RFC 3339") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise _refus("REJ-DEPENSES-INSTANT-INVALIDE", "releve_le sans fuseau : refusé, jamais supposé UTC")
    return instant


def _libelle(valeur: Any) -> str | None:
    if valeur is None:
        return None
    if not isinstance(valeur, str):
        raise _refus("REJ-DEPENSES-LIBELLE-INVALIDE", "libelle_campagne attendu texte ou null")
    texte = unicodedata.normalize("NFC", valeur).strip()
    if not 1 <= len(texte) <= _LIBELLE_MAX or any(unicodedata.category(c).startswith("C") for c in texte):
        raise _refus("REJ-DEPENSES-LIBELLE-INVALIDE", "libellé vide, trop long ou avec caractère de contrôle")
    return texte


def normaliser_releve(releve: Mapping[str, Any]) -> dict[str, Any]:
    """Forme canonique d'un relevé (seule forme stockée), ou `ValueError("REJ-DEPENSES-… : …")`.

    Aucune valeur par défaut : un champ absent est refusé (jamais deviné), un champ inconnu aussi. Le
    montant est un TEXTE décimal en dollars canadiens, deux décimales au plus, jamais un nombre JSON."""
    if not isinstance(releve, Mapping):
        raise _refus("REJ-DEPENSES-FORME", "relevé attendu : objet")
    manquants = sorted(set(_CHAMPS) - set(releve))
    inconnus = sorted(set(releve) - set(_CHAMPS))
    if manquants or inconnus:
        raise _refus("REJ-DEPENSES-FORME", f"champs manquants {manquants}, champs inconnus {inconnus}")
    if not isinstance(releve["releve_id"], str) or not _ID.fullmatch(releve["releve_id"]):
        raise _refus("REJ-DEPENSES-ID-INVALIDE", "releve_id invalide")
    revision = releve["revision"]
    if type(revision) is not int or revision < 1:
        raise _refus("REJ-DEPENSES-REVISION-INVALIDE", "revision attendue : entier >= 1")
    if releve["canal"] not in CANAUX:
        raise _refus("REJ-DEPENSES-CANAL-INCONNU", f"canal attendu parmi {list(CANAUX)}")
    ref = releve["campagne_ref"]
    if ref is not None and (not isinstance(ref, str) or not _CAMPAGNE_REF.fullmatch(ref)):
        raise _refus("REJ-DEPENSES-CAMPAGNE-INVALIDE", "campagne_ref invalide (minuscules, chiffres, - et _)")
    libelle = _libelle(releve["libelle_campagne"])
    if libelle is not None and ref is None:
        raise _refus("REJ-DEPENSES-CAMPAGNE-INVALIDE", "un libellé de campagne exige campagne_ref")
    debut, fin = _date(releve["periode_debut"], "periode_debut"), _date(releve["periode_fin"], "periode_fin")
    if debut > fin or (fin - debut).days + 1 > MAX_JOURS_RELEVE:
        raise _refus("REJ-DEPENSES-PERIODE-INVALIDE", "période inversée ou de plus de 366 jours")
    montant = releve["montant_cad"]
    if releve["devise"] != "CAD":
        raise _refus("REJ-DEPENSES-DEVISE-NON-CAD", "seule la devise CAD est acceptée : M7 ne convertit rien")
    if not isinstance(montant, str) or not _MONTANT.fullmatch(montant):
        raise _refus("REJ-DEPENSES-MONTANT-INVALIDE", "montant_cad attendu : texte décimal >= 0, 2 décimales au plus")
    if releve["base_taxes"] not in BASES_TAXES:
        raise _refus("REJ-DEPENSES-BASE-TAXES-INCONNUE", f"base_taxes attendue parmi {list(BASES_TAXES)}")
    if releve["source"] not in SOURCES:
        raise _refus("REJ-DEPENSES-SOURCE-INCONNUE", f"source attendue parmi {list(SOURCES)}")
    if not isinstance(releve["source_ref"], str) or not _SOURCE_REF.fullmatch(releve["source_ref"]):
        raise _refus("REJ-DEPENSES-SOURCE-REF-INVALIDE", "source_ref obligatoire (identifiant du relevé)")
    instant = _instant(releve["releve_le"])
    if instant.date() < fin:
        raise _refus(
            "REJ-DEPENSES-RELEVE-ANTERIEUR-A-LA-PERIODE",
            "le relevé ne peut pas dater d'avant la fin de la période qu'il couvre",
        )
    return {
        "releve_id": releve["releve_id"], "revision": revision, "canal": releve["canal"], "campagne_ref": ref,
        "libelle_campagne": libelle, "periode_debut": debut.isoformat(), "periode_fin": fin.isoformat(),
        "montant_cad": format(Decimal(montant).quantize(_CENTIME), "f"), "devise": "CAD",
        "base_taxes": releve["base_taxes"], "source": releve["source"], "source_ref": releve["source_ref"],
        "releve_le": releve["releve_le"],
    }


def _portee(releve: Mapping[str, Any]) -> tuple[str, str | None]:
    return releve["canal"], releve["campagne_ref"]


def _chevauche(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return a["periode_debut"] <= b["periode_fin"] and b["periode_debut"] <= a["periode_fin"]


def _courants(chaine: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dernière révision de chaque relevé, après vérification de la chaîne. Une chaîne incohérente est une
    ERREUR (jamais un choix silencieux entre deux versions)."""
    derniers: dict[str, dict[str, Any]] = {}
    for releve in chaine:
        precedent = derniers.get(releve["releve_id"])
        if precedent is None:
            if releve["revision"] != 1:
                raise ValueError("DEPENSES_REGISTRE_INVALIDE")
        elif releve["revision"] == precedent["revision"]:
            # Même révision : contradiction si le contenu diffère, sinon relevé doublé (jamais écrit par M7).
            raise ValueError("DEPENSES_FAITS_CONFLICTUELS" if releve != precedent else "DEPENSES_REGISTRE_INVALIDE")
        elif releve["revision"] != precedent["revision"] + 1 or (
            _instant(releve["releve_le"]) < _instant(precedent["releve_le"])
        ):
            raise ValueError("DEPENSES_REGISTRE_INVALIDE")
        derniers[releve["releve_id"]] = releve
    courants = sorted(derniers.values(), key=lambda r: (r["canal"], r["campagne_ref"] or "", r["periode_debut"]))
    for i, a in enumerate(courants):
        for b in courants[i + 1:]:
            if _portee(a) == _portee(b) and _chevauche(a, b):
                raise ValueError("DEPENSES_FAITS_CONFLICTUELS")
    return courants


def enregistrer_releve(releve: Mapping[str, Any]) -> dict[str, Any]:
    """Inscrit un relevé de dépense (ou sa révision suivante) au registre durable. Voie d'ENTRÉE interne du
    producteur : ce n'est pas un outil d'agent, aucun droit n'est ouvert (l'ingestion réelle, connecteur ou
    saisie du propriétaire, est une décision produit hors de ce module).

    Idempotent : rejouer exactement la dernière révision ne change rien. Refus nommés : révision périmée,
    sautée ou contradictoire (même révision, contenu différent), chevauchement de période sur un même canal
    et une même campagne, instant de relevé qui recule."""
    maillon = normaliser_releve(releve)
    if _instant(maillon["releve_le"]) > datetime.now(UTC):
        raise _refus("REJ-DEPENSES-INSTANT-FUTUR", "releve_le est dans le futur")
    journal = stockage.maillons(*REGISTRE)
    chaine = _decoder_chaine([m for m in journal])
    courants = _courants(chaine)
    meme_id = [m for m in chaine if m["releve_id"] == maillon["releve_id"]]
    if meme_id:
        derniere = meme_id[-1]
        if maillon["revision"] < derniere["revision"]:
            raise _refus("REJ-DEPENSES-REVISION-PERIMEE", f"la révision {derniere['revision']} existe déjà")
        if maillon["revision"] == derniere["revision"]:
            if maillon == derniere:
                return {"accepte": True, "deja_present": True}
            raise _refus("REJ-DEPENSES-CONFLIT-REVISION", "même révision, contenu différent : refusé")
        if maillon["revision"] != derniere["revision"] + 1:
            raise _refus("REJ-DEPENSES-REVISION-SAUTEE", f"révision suivante attendue : {derniere['revision'] + 1}")
        if _instant(maillon["releve_le"]) < _instant(derniere["releve_le"]):
            raise _refus("REJ-DEPENSES-INSTANT-RECULE", "une révision ne peut pas dater d'avant la précédente")
    elif maillon["revision"] != 1:
        raise _refus("REJ-DEPENSES-REVISION-INITIALE", "un nouveau relevé commence à la révision 1")
    for autre in courants:
        if autre["releve_id"] != maillon["releve_id"] and _portee(autre) == _portee(maillon) \
                and _chevauche(autre, maillon):
            raise _refus(
                "REJ-DEPENSES-CHEVAUCHEMENT",
                f"la période chevauche le relevé {autre['releve_id']} du même canal et de la même campagne",
            )
    try:
        journal.append({"type": TYPE_MAILLON, **maillon}, rang_attendu=len(chaine))
    except EcritureConcurrente as exc:
        raise _refus("REJ-DEPENSES-ECRITURE-CONCURRENTE", "le registre a changé pendant l'écriture") from exc
    return {"accepte": True, "deja_present": False}


def _decoder_chaine(maillons: list[Any]) -> list[dict[str, Any]]:
    chaine = []
    for maillon in maillons:
        if not isinstance(maillon, dict) or maillon.get("type") != TYPE_MAILLON:
            raise ValueError("DEPENSES_REGISTRE_INVALIDE")
        corps = {k: v for k, v in maillon.items() if k != "type"}
        try:
            canonique = normaliser_releve(corps)
        except ValueError as exc:
            raise ValueError("DEPENSES_REGISTRE_INVALIDE") from exc
        if canonique != corps:
            raise ValueError("DEPENSES_REGISTRE_INVALIDE")
        chaine.append(canonique)
    return chaine


def _decoder_texte(texte: str) -> dict[str, Any]:
    def constante(_valeur: str):
        raise ValueError("nombre JSON non fini")

    def objet(paires):
        resultat = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError("clé JSON répétée")
            resultat[cle] = valeur
        return resultat

    try:
        valeur = json.loads(texte, parse_constant=constante, object_pairs_hook=objet)
    except (ValueError, RecursionError) as exc:
        raise ValueError("DEPENSES_REGISTRE_INVALIDE") from exc
    if not isinstance(valeur, dict):
        raise ValueError("DEPENSES_REGISTRE_INVALIDE")
    return valeur


def lire_depenses(debut: date, fin: date) -> dict[str, Any]:
    """Lecture bornée du registre dans la transaction courante, puis `construire_depenses`. Lecture seule."""
    if isinstance(debut, datetime) or isinstance(fin, datetime) or not isinstance(debut, date) \
            or not isinstance(fin, date):
        raise ValueError("PERIODE_DATE_INVALIDE")
    if debut > fin:
        raise ValueError("PERIODE_INVERSEE")
    if (fin - debut).days > MAX_JOURS_LECTURE:
        raise ValueError("PERIODE_TROP_LONGUE")
    cnx = stockage.connexion_courante()
    if cnx is None:
        with stockage.transaction():
            return lire_depenses(debut, fin)
    filtre = (REGISTRES.c.departement == REGISTRE[0]) & (REGISTRES.c.registre == REGISTRE[1])
    octets = _longueur_octets(cnx.dialect.name)
    nombre, premier, dernier, total, maximum = cnx.execute(select(
        func.count(), func.min(REGISTRES.c.rang), func.max(REGISTRES.c.rang),
        func.coalesce(func.sum(octets), 0), func.coalesce(func.max(octets), 0),
    ).where(filtre)).one()
    if nombre > MAX_LIGNES:
        raise ValueError("DEPENSES_BORNE_LIGNES")
    if total > MAX_OCTETS_TOTAL or maximum > MAX_OCTETS_LIGNE:
        raise ValueError("DEPENSES_BORNE_OCTETS")
    if nombre and (premier != 0 or dernier != nombre - 1):
        raise ValueError("DEPENSES_REGISTRE_INVALIDE")
    lignes = [] if not nombre else cnx.execute(select(
        REGISTRES.c.rang, REGISTRES.c.maillon, REGISTRES.c.cree_le,
    ).where(filtre, REGISTRES.c.rang <= dernier).order_by(REGISTRES.c.rang).limit(MAX_LIGNES + 1)).all()
    if len(lignes) != nombre:
        raise ValueError("DEPENSES_REGISTRE_INVALIDE")
    empreinte = hashlib.sha256()
    maillons = []
    total_lu = 0
    for rang, ligne in enumerate(lignes):
        if ligne.rang != rang:
            raise ValueError("DEPENSES_REGISTRE_INVALIDE")
        brut = ligne.maillon.encode("utf-8")
        total_lu += len(brut)
        if len(brut) > MAX_OCTETS_LIGNE or total_lu > MAX_OCTETS_TOTAL:
            raise ValueError("DEPENSES_BORNE_OCTETS")
        empreinte.update(len(brut).to_bytes(8, "big"))
        empreinte.update(brut)
        maillons.append(_decoder_texte(ligne.maillon))
    if total_lu != total:
        raise ValueError("DEPENSES_REGISTRE_INVALIDE")
    resultat = construire_depenses(_decoder_chaine(maillons), debut, fin)
    resultat["observation_source"] = {
        "lue_le": datetime.now(UTC).isoformat(), "rang_max": dernier, "lignes_lues": nombre,
        "dernier_cree_le_sql": max(ligne.cree_le for ligne in lignes).isoformat() if lignes else None,
        "fuseau_cree_le_sql": "UTC" if cnx.dialect.name == "sqlite" else "fourni_par_postgresql",
        "integrite": "historique_non_scelle", "empreinte_lecture_sha256": empreinte.hexdigest(),
        "definition_temps": "periode_du_releve_et_instant_du_releve_tels_que_saisis",
    }
    return resultat


def _somme(releves: list[dict[str, Any]]) -> Decimal:
    return sum((Decimal(r["montant_cad"]) for r in releves), Decimal("0.00"))


def _texte(montant: Decimal) -> str:
    return format(montant.quantize(_CENTIME), "f")


def _ligne_releve(releve: Mapping[str, Any]) -> dict[str, Any]:
    ligne = {k: releve[k] for k in (
        "releve_id", "revision", "periode_debut", "periode_fin", "montant_cad", "devise", "base_taxes",
        "source", "source_ref", "releve_le",
    )}
    if releve["campagne_ref"] is not None:
        ligne["campagne_ref"] = releve["campagne_ref"]
        ligne["libelle_campagne"] = releve["libelle_campagne"]
    return ligne


def _canal(canal: str, chaine_canal: list[dict[str, Any]], debut: date, fin: date) -> dict[str, Any]:
    d, f = debut.isoformat(), fin.isoformat()
    jours_periode = (fin - debut).days + 1
    contenus = [r for r in chaine_canal if d <= r["periode_debut"] and r["periode_fin"] <= f]
    fenetre = {"periode_debut": d, "periode_fin": f}
    debordants = [r for r in chaine_canal if _chevauche(r, fenetre) and r not in contenus]
    totaux = [r for r in contenus if r["campagne_ref"] is None]
    details = [r for r in contenus if r["campagne_ref"] is not None]
    jours_couverts = sum(
        (date.fromisoformat(r["periode_fin"]) - date.fromisoformat(r["periode_debut"])).days + 1 for r in totaux
    )
    manque: list[str] = []
    montant = au_moins = base = None
    if not chaine_canal:
        statut = "NON_BRANCHEE"
        manque.append("DEPENSES_NON_BRANCHEES")
    elif not totaux:
        statut = "NON_BRANCHEE"
        manque.append("RELEVE_DEBORDE_LA_PERIODE" if debordants else "DEPENSES_PERIODE_SANS_RELEVE")
    else:
        bases = {r["base_taxes"] for r in totaux}
        base = next(iter(bases)) if len(bases) == 1 else None
        if base is None:
            statut = "PARTIELLE"
            manque.append("BASES_TAXES_DIFFERENTES")
        elif jours_couverts < jours_periode:
            statut = "PARTIELLE"
            au_moins = _texte(_somme(totaux))
            manque.append("COUVERTURE_PERIODE_INCOMPLETE")
        else:
            statut = "CONNUE"
            montant = _texte(_somme(totaux))
        if debordants:
            manque.append("RELEVE_DEBORDE_LA_PERIODE")
        if statut == "CONNUE" and details and {r["base_taxes"] for r in details} == {base} \
                and _somme(details) > _somme(totaux):
            statut, montant, au_moins = "PARTIELLE", None, None
            manque.append("DETAIL_CAMPAGNE_SUPERIEUR_AU_TOTAL")
    return {
        "canal": canal, "statut": statut, "montant_cad": montant, "au_moins_cad": au_moins, "devise": "CAD",
        "base_taxes": base, "jours_periode": jours_periode, "jours_couverts": jours_couverts,
        "releves": [_ligne_releve(r) for r in totaux], "lignes_campagne": [_ligne_releve(r) for r in details],
        "releves_debordants": [
            {k: r[k] for k in ("releve_id", "revision", "periode_debut", "periode_fin")} for r in debordants
        ],
        "manque": sorted(set(manque)),
    }


def construire_depenses(chaine: list[dict[str, Any]], debut: date, fin: date) -> dict[str, Any]:
    """Dépenses de la période inclusive [debut, fin], calculées des seuls relevés courants de `chaine`."""
    courants = _courants(chaine)
    canaux = [_canal(c, [r for r in courants if r["canal"] == c], debut, fin) for c in CANAUX]
    statuts = {c["statut"] for c in canaux}
    bases = {c["base_taxes"] for c in canaux if c["statut"] == "CONNUE"}
    manque = [{"portee": c["canal"], "code": code} for c in canaux for code in c["manque"]]
    total = au_moins = None
    if statuts == {"NON_BRANCHEE"}:
        statut = "NON_BRANCHEE"
    elif statuts == {"CONNUE"} and len(bases) == 1:
        statut = "CONNUE"
        total = _texte(sum((Decimal(c["montant_cad"]) for c in canaux), Decimal("0.00")))
    else:
        statut = "PARTIELLE"
        if statuts == {"CONNUE"}:
            manque.append({"portee": "total", "code": "BASES_TAXES_DIFFERENTES"})
        retenus = [c for c in canaux if c["montant_cad"] is not None or c["au_moins_cad"] is not None]
        bases_retenues = {c["base_taxes"] for c in retenus}
        if retenus and len(bases_retenues) == 1:
            au_moins = _texte(sum((Decimal(c["montant_cad"] or c["au_moins_cad"]) for c in retenus), Decimal("0.00")))
        elif len(bases_retenues) > 1:
            manque.append({"portee": "total", "code": "BASES_TAXES_DIFFERENTES"})
    contenus = [r for c in canaux for r in c["releves"] + c["lignes_campagne"]]
    lecture = {
        "NON_BRANCHEE": "Aucune dépense marketing n'est établie pour la période : ce n'est pas une dépense nulle.",
        "PARTIELLE": "Dépenses marketing partiellement établies : au_moins_cad est une borne basse, jamais un total.",
        "CONNUE": "Dépenses marketing établies par des relevés sourcés sur toute la période, pour chaque canal.",
    }[statut]
    return {
        "type": "DEPENSES_MARKETING", "schema": SCHEMA,
        "periode": {"debut": debut.isoformat(), "fin": fin.isoformat()},
        "devise": "CAD", "statut": statut, "total_cad": total, "au_moins_cad": au_moins,
        "base_taxes": next(iter(bases)) if statut == "CONNUE" else None,
        "canaux_attendus": list(CANAUX), "canaux": canaux,
        "manque": sorted(manque, key=lambda m: (m["portee"], m["code"])),
        "releve_le_plus_recent": max((r["releve_le"] for r in contenus), key=_instant, default=None),
        "source_refs": [
            {"type": "m7.releve_depense", "reference": r["releve_id"], "revision": r["revision"]} for r in contenus
        ],
        "libelles": "DONNEES_SAISIES_NON_INTERPRETEES", "lecture": lecture,
    }
