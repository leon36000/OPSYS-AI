"""Clients importés à l'onboarding : liste de clients (CSV, .xlsx) -> fiches PROPOSÉES -> fiche définitive validée.

Module PUR (comme le reste du paquet hors `outils.py`) : ni `opsys`, ni SQLAlchemy, ni horloge, ni réseau. Le socle
(`opsys.ingestion_onboarding`) lui passe les LIGNES déjà lues du fichier ; ce module décide seul :

1. où est l'en-tête et quelle colonne joue quel rôle (`reperer_entete`, synonymes FR/EN fermés) ;
2. la forme NORMALISÉE de chaque champ (nom, courriel, téléphone, adresse, code postal), règle par règle ;
3. le DÉDOUBLONNAGE déterministe des lignes (`regrouper`) : trois règles FORTES fondent deux lignes en une fiche
   proposée (courriel identique ; téléphone ET nom identiques ; nom ET adresse identiques) ; deux règles FAIBLES ne
   fondent rien et signalent seulement (téléphone seul ; nom seul). Chaque fusion proposée porte son explication :
   la règle, les deux lignes, la valeur normalisée qui les relie. Splink n'est pas utilisé (non installé) : aucune
   pondération probabiliste, aucun seuil appris ;
4. le statut de la fiche proposée : `PRET`, ou `A_VERIFIER` avec la raison exacte (courriel ou téléphone mal formé,
   code postal mal formé, deux valeurs différentes d'un même champ dans un groupe fusionné, doublon probable). Rien
   n'est corrigé en silence : une valeur mal formée reste telle qu'écrite, un conflit attend le choix d'un humain ;
5. la fiche DÉFINITIVE (`importer_client`), seulement par un humain identifié (voie appareil ou approbation, établie
   par `outils.py`), dans le registre DÉDIÉ `clients_importes` (append-only, hash-chaîné). Son `client_id` est celui
   du Client 360 (`clients.identifiant_client`) : un lead futur au contact identique rejoint la même identité.

Ce module ne fusionne JAMAIS deux leads ni deux clients déjà connus de M2 (mission de M2 : signaler, jamais fusionner) :
il ne fond que des LIGNES d'un fichier importé, avant qu'aucune fiche n'existe, et le propose à un humain.
"""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import clients, verdicts
from . import horodatage as _horodatage

__all__ = [
    "CODES_RAISONS",
    "CHAMPS",
    "TYPE_CONTACT_COURRIEL",
    "TYPE_ENTREE",
    "contacts_courriel_importes",
    "importer_contact_courriel",
    "empreintes_cles",
    "importer_client",
    "lire_lignes",
    "normaliser_code_postal",
    "normaliser_courriel",
    "normaliser_nom",
    "normaliser_telephone",
    "proposer_fiches",
    "regrouper",
    "reperer_entete",
]

TYPE_ENTREE = "client_importe"
TYPE_CONTACT_COURRIEL = "contact_courriel_importe"
CHAMPS: tuple[str, ...] = ("nom", "courriel", "telephone", "adresse", "ville", "code_postal")
CODES_RAISONS: tuple[str, ...] = (
    "REJ-ING-CLIENT-NOM-ABSENT",
    "REJ-ING-CLIENT-COURRIEL-INVALIDE",
    "REJ-ING-CLIENT-TELEPHONE-INVALIDE",
    "REJ-ING-CLIENT-CODE-POSTAL-INVALIDE",
    "REJ-ING-CLIENT-CONFLIT",
    "REJ-ING-CLIENT-DOUBLON-PROBABLE",
    "REJ-ING-CLIENT-ENTETE-INTROUVABLE",
    "REJ-ING-CLIENT-TROP-DE-LIGNES",
)
LIGNES_MAX = 5_000
_ENTETE_RECHERCHE = 10
_VALEUR_MAX = 200

_SYNONYMES: dict[str, tuple[str, ...]] = {
    "nom": ("nom", "name", "client", "nom du client", "nom client", "raison sociale", "nom complet", "customer",
            "full name", "display name", "entreprise", "company"),
    "prenom": ("prenom", "first name", "given name"),
    "nom_famille": ("nom de famille", "last name", "surname", "family name"),
    "courriel": ("courriel", "email", "e mail", "adresse courriel", "mail", "adresse electronique"),
    "telephone": ("telephone", "tel", "phone", "cellulaire", "cell", "mobile", "numero de telephone", "phone number"),
    "adresse": ("adresse", "address", "rue", "street", "adresse civique", "billing address", "adresse de facturation"),
    "ville": ("ville", "city", "municipalite"),
    "code_postal": ("code postal", "postal code", "cp", "zip", "zip code"),
}
_ROLE_PAR_ENTETE = {entete: role for role, entetes in _SYNONYMES.items() for entete in entetes}
_SUFFIXES_LEGAUX = frozenset({"inc", "ltee", "ltd", "enr", "senc", "llc", "corp", "limitee", "incorporee"})
_ABREVIATIONS = {
    "avenue": "av", "ave": "av", "boulevard": "boul", "blvd": "boul", "bd": "boul", "chemin": "ch",
    "saint": "st", "sainte": "ste", "rang": "rg", "route": "rte", "montee": "mtee", "place": "pl",
    "appartement": "app", "apt": "app", "unite": "app", "nord": "n", "sud": "s", "est": "e", "ouest": "o",
}
_COURRIEL = re.compile(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)*\.[a-z]{2,}")
_CODE_POSTAL = re.compile(r"[ABCEGHJ-NPRSTVXY][0-9][ABCEGHJ-NPRSTV-Z][0-9][ABCEGHJ-NPRSTV-Z][0-9]")
_EXTENSION_TEL = re.compile(r"\s*(?:x|ext\.?|poste|#)\s*[0-9]{1,6}\s*$", re.IGNORECASE)


def _raison(code: str, detail: str) -> dict[str, str]:
    if code not in CODES_RAISONS:
        raise ValueError(f"raison hors catalogue : {code!r}")
    return {"code": code, "detail": detail}


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def _mots(texte: str) -> list[str]:
    simple = _sans_accents(texte).casefold().replace("&", " et ")
    return re.sub(r"[^0-9a-z]+", " ", simple).split()


def _entete(cellule: str) -> str:
    return " ".join(_mots(cellule))


# ------------------------------------------------------------------------------------------- en-tête et lignes
def reperer_entete(lignes: Sequence[Sequence[str]]) -> tuple[int, dict[str, int]] | None:
    """`(index de la ligne d'en-tête, {rôle: colonne})` parmi les `_ENTETE_RECHERCHE` premières lignes, ou `None`. Une
    liste de clients a un NOM (ou prénom et nom de famille) et au moins un moyen de joindre ou situer : courriel,
    téléphone ou adresse. Une colonne inconnue est ignorée (et comptée) ; deux colonnes au même rôle : la première."""
    for index, ligne in enumerate(lignes[:_ENTETE_RECHERCHE]):
        colonnes: dict[str, int] = {}
        for position, cellule in enumerate(ligne):
            role = _ROLE_PAR_ENTETE.get(_entete(cellule)) if isinstance(cellule, str) else None
            if role is not None and role not in colonnes:
                colonnes[role] = position
        a_un_nom = "nom" in colonnes or {"prenom", "nom_famille"} <= colonnes.keys()
        if a_un_nom and colonnes.keys() & {"courriel", "telephone", "adresse"}:
            return index, colonnes
    return None


def _cellule(ligne: Sequence[str], colonnes: Mapping[str, int], role: str) -> str:
    position = colonnes.get(role)
    if position is None or position >= len(ligne):
        return ""
    return " ".join(str(ligne[position]).split())[:_VALEUR_MAX]


def lire_lignes(candidats: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Les lignes de clients du premier candidat de lecture (séparateur) dont l'en-tête est reconnu : `(lecture, None)`
    ou `(None, raison)`. Une ligne vide est ignorée ; une ligne sans nom est REFUSÉE (`REJ-ING-CLIENT-NOM-ABSENT`),
    jamais complétée."""
    for candidat in candidats:
        lignes = candidat["lignes"]
        trouve = reperer_entete(lignes)
        if trouve is None:
            continue
        index, colonnes = trouve
        if len(lignes) - index - 1 > LIGNES_MAX:
            return None, _raison("REJ-ING-CLIENT-TROP-DE-LIGNES", f"plus de {LIGNES_MAX} clients dans un fichier")
        retenues, refusees = [], []
        for numero, ligne in enumerate(lignes[index + 1:], index + 2):
            if not any(str(c).strip() for c in ligne):
                continue
            champs = {role: _cellule(ligne, colonnes, role) for role in CHAMPS if role != "nom"}
            nom = _cellule(ligne, colonnes, "nom")
            if not nom and {"prenom", "nom_famille"} <= colonnes.keys():
                nom = " ".join(p for p in (_cellule(ligne, colonnes, "prenom"),
                                           _cellule(ligne, colonnes, "nom_famille")) if p)
            if not nom:
                refusees.append({"ligne": numero, **_raison("REJ-ING-CLIENT-NOM-ABSENT", "ligne sans nom de client")})
                continue
            retenues.append({"ligne": numero, "champs": {"nom": nom, **champs}})
        return {"separateur": candidat.get("separateur"), "entete": index + 1,
                "colonnes": sorted(colonnes), "lignes": retenues, "refusees": refusees}, None
    return None, _raison("REJ-ING-CLIENT-ENTETE-INTROUVABLE", "aucun en-tête reconnu (nom + courriel, téléphone ou "
                         "adresse) dans les 10 premières lignes")


# ----------------------------------------------------------------------------------------------- normalisation
def normaliser_nom(nom: str) -> str:
    """Accents, casse, ponctuation et « & » ignorés ; suffixes légaux (inc, ltée, enr…) retirés en fin de nom."""
    mots = _mots(nom)
    while len(mots) > 1 and mots[-1] in _SUFFIXES_LEGAUX:
        mots.pop()
    return " ".join(mots)


def normaliser_courriel(courriel: str) -> str | None:
    """Minuscules, espaces retirés ; `None` si la forme n'est pas celle d'une adresse (jamais « réparée »)."""
    valeur = courriel.strip().casefold()
    return valeur if valeur and _COURRIEL.fullmatch(valeur) else None


def normaliser_telephone(telephone: str) -> str | None:
    """Numéro nord-américain en `+1XXXXXXXXXX` (extension retirée) ; `None` s'il n'a pas 10 chiffres (11 avec 1)."""
    chiffres = re.sub(r"[^0-9]", "", _EXTENSION_TEL.sub("", telephone))
    if len(chiffres) == 11 and chiffres.startswith("1"):
        chiffres = chiffres[1:]
    if len(chiffres) != 10 or chiffres[0] in "01":
        return None
    return "+1" + chiffres


def normaliser_code_postal(code: str) -> str | None:
    valeur = re.sub(r"\s+", "", code).upper()
    return f"{valeur[:3]} {valeur[3:]}" if _CODE_POSTAL.fullmatch(valeur) else None


def normaliser_adresse(adresse: str) -> str:
    return " ".join(_ABREVIATIONS.get(mot, mot) for mot in _mots(adresse))


def _normalise(champs: Mapping[str, str]) -> dict[str, str | None]:
    return {
        "nom": normaliser_nom(champs.get("nom", "")) or None,
        "courriel": normaliser_courriel(champs["courriel"]) if champs.get("courriel") else None,
        "telephone": normaliser_telephone(champs["telephone"]) if champs.get("telephone") else None,
        "adresse": normaliser_adresse(champs["adresse"]) or None if champs.get("adresse") else None,
        "ville": " ".join(_mots(champs["ville"])) or None if champs.get("ville") else None,
        "code_postal": normaliser_code_postal(champs["code_postal"]) if champs.get("code_postal") else None,
    }


def _empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _cles_fortes(n: Mapping[str, str | None]) -> list[tuple[str, str]]:
    cles = []
    if n["courriel"]:
        cles.append(("courriel_identique", f"courriel:{n['courriel']}"))
    if n["telephone"] and n["nom"]:
        cles.append(("telephone_et_nom", f"telephone_nom:{n['telephone']}|{n['nom']}"))
    if n["adresse"] and n["nom"]:
        cles.append(("nom_et_adresse", f"nom_adresse:{n['nom']}|{n['adresse']}|{n['code_postal'] or ''}"))
    return cles


def _cles_faibles(n: Mapping[str, str | None]) -> list[tuple[str, str]]:
    cles = []
    if n["telephone"]:
        cles.append(("telephone_seul", f"telephone:{n['telephone']}"))
    if n["nom"]:
        cles.append(("nom_seul", f"nom:{n['nom']}"))
    return cles


def empreintes_cles(champs: Mapping[str, str]) -> list[str]:
    """Les empreintes SHA-256 des clés FORTES d'une fiche (ou d'un contact) : ce que le socle compare aux brouillons et
    aux clients déjà importés, sans conserver la valeur en clair hors du chiffré."""
    return sorted({_empreinte(cle) for _, cle in _cles_fortes(_normalise(champs))})


# ------------------------------------------------------------------------------------------------ regroupement
def regrouper(lignes: Sequence[Mapping[str, Any]]) -> tuple[list[list[int]], list[dict], list[dict]]:
    """`(groupes, fusions, signalements)` : les groupes d'indices de lignes FONDUES par une règle forte (union de
    proche en proche, ordre du fichier), l'explication de chaque fusion, et les rapprochements FAIBLES entre groupes
    différents (signalés, jamais fondus). Déterministe : même fichier, mêmes groupes, mêmes explications."""
    parent = list(range(len(lignes)))

    def racine(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    normalises = [_normalise(ligne["champs"]) for ligne in lignes]
    premiere: dict[str, int] = {}
    fusions: list[dict] = []
    for index, normalise in enumerate(normalises):
        for regle, cle in _cles_fortes(normalise):
            if cle not in premiere:
                premiere[cle] = index
                continue
            autre = premiere[cle]
            a, b = racine(autre), racine(index)
            if a != b:
                parent[max(a, b)] = min(a, b)
                fusions.append({"regle": regle, "lignes": [lignes[autre]["ligne"], lignes[index]["ligne"]],
                                "valeur_normalisee": cle.split(":", 1)[1]})
    groupes: dict[int, list[int]] = {}
    for index in range(len(lignes)):
        groupes.setdefault(racine(index), []).append(index)
    ordonnes = sorted(groupes.values(), key=lambda g: g[0])
    signalements: list[dict] = []
    vus: dict[str, int] = {}
    deja: set[tuple[int, int, str]] = set()
    for index, normalise in enumerate(normalises):
        for regle, cle in _cles_faibles(normalise):
            if cle in vus and racine(vus[cle]) != racine(index):
                paire = (min(racine(vus[cle]), racine(index)), max(racine(vus[cle]), racine(index)), regle)
                if paire not in deja:
                    deja.add(paire)
                    signalements.append({"regle": regle, "lignes": [lignes[vus[cle]]["ligne"], lignes[index]["ligne"]],
                                         "valeur_normalisee": cle.split(":", 1)[1]})
            vus.setdefault(cle, index)
    return ordonnes, fusions, signalements


def _champ_du_groupe(valeurs: list[str], normaliser) -> dict[str, Any]:
    brutes = [v for v in valeurs if v]
    formes: dict[Any, str] = {}
    for brute in brutes:
        formes.setdefault(normaliser(brute), brute)
    return {"valeur": brutes[0] if brutes else None, "valeurs": list(dict.fromkeys(brutes)),
            "conflit": len(formes) > 1}


def proposer_fiches(lignes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Une fiche PROPOSÉE par groupe : champs (valeur retenue = première écrite, valeurs observées, conflit), lignes
    sources, fusions et signalements qui la concernent, raisons et statut (`PRET` ou `A_VERIFIER`), clés."""
    groupes, fusions, signalements = regrouper(lignes)
    normalisations = {
        "nom": normaliser_nom, "courriel": lambda v: normaliser_courriel(v) or v.strip().casefold(),
        "telephone": lambda v: normaliser_telephone(v) or v.strip(), "adresse": normaliser_adresse,
        "ville": lambda v: " ".join(_mots(v)), "code_postal": lambda v: normaliser_code_postal(v) or v.strip(),
    }
    fiches = []
    for groupe in groupes:
        numeros = [lignes[i]["ligne"] for i in groupe]
        champs = {champ: _champ_du_groupe([lignes[i]["champs"].get(champ, "") for i in groupe], normalisations[champ])
                  for champ in CHAMPS}
        raisons = []
        for champ, code, normaliser in (
            ("courriel", "REJ-ING-CLIENT-COURRIEL-INVALIDE", normaliser_courriel),
            ("telephone", "REJ-ING-CLIENT-TELEPHONE-INVALIDE", normaliser_telephone),
            ("code_postal", "REJ-ING-CLIENT-CODE-POSTAL-INVALIDE", normaliser_code_postal),
        ):
            for valeur in champs[champ]["valeurs"]:
                if normaliser(valeur) is None:
                    raisons.append(_raison(code, f"{champ} {valeur!r} mal formé (lignes {numeros}) : laissé tel "
                                                 "qu'écrit, à corriger à la source ou à écarter"))
        for champ in CHAMPS:
            if champs[champ]["conflit"]:
                raisons.append(_raison("REJ-ING-CLIENT-CONFLIT", f"{champ} : valeurs différentes dans les lignes "
                                       f"fusionnées {numeros} : {champs[champ]['valeurs']} ; choisir à la validation"))
        propres = [f for f in fusions if set(f["lignes"]) <= set(numeros)]
        signales = [s for s in signalements if set(s["lignes"]) & set(numeros)]
        for signalement in signales:
            raisons.append(_raison("REJ-ING-CLIENT-DOUBLON-PROBABLE", f"règle faible {signalement['regle']} entre les "
                                   f"lignes {signalement['lignes']} : non fusionnées, à arbitrer"))
        representant = {champ: champs[champ]["valeur"] or "" for champ in CHAMPS}
        cles = sorted({_empreinte(cle) for i in groupe for _, cle in _cles_fortes(_normalise(lignes[i]["champs"]))})
        cle_metier = cles[0] if cles else _empreinte("nom:" + (normaliser_nom(representant["nom"]) or ""))
        # `cles` : les seules clés FORTES ; une fiche qui n'en a aucune (nom seul) ne se rattache jamais d'elle-même
        # à une autre, et l'appelant rend sa clé métier unique (document, lignes).
        fiches.append({
            "champs": champs, "lignes": numeros, "fusions": propres, "signalements": signales, "raisons": raisons,
            "statut": "A_VERIFIER" if raisons else "PRET", "cles": cles, "cle_metier": cle_metier,
        })
    return fiches


# ------------------------------------------------------------------------------------------- fiche définitive
def _refus(code: str, detail: str) -> tuple[None, dict[str, Any]]:
    return None, verdicts.construire_verdict(code, detail=detail)


def contact_de(fiche: Mapping[str, Any], choix: Mapping[str, str] | None = None) -> tuple[dict | None, dict | None]:
    """Les valeurs retenues d'une fiche proposée, conflits résolus par `choix` ({champ: valeur observée}) : `(valeurs,
    None)` ou `(None, verdict)`. Un choix doit être l'une des valeurs OBSERVÉES : un humain choisit, il ne réécrit pas
    ici (une valeur fausse se corrige à la source)."""
    choix = dict(choix or {})
    if set(choix) - set(CHAMPS):
        return _refus("REJ-CLIENT-IMPORT-CHOIX-INVALIDE", f"choix hors des champs {list(CHAMPS)}")
    valeurs: dict[str, str] = {}
    for champ in CHAMPS:
        bloc = fiche["champs"][champ]
        if champ in choix:
            if choix[champ] not in bloc["valeurs"]:
                return _refus("REJ-CLIENT-IMPORT-CHOIX-INVALIDE", f"{champ} : choisir parmi les valeurs observées")
            valeur = choix[champ]
        elif bloc["conflit"]:
            return _refus("REJ-CLIENT-IMPORT-CHOIX-INVALIDE", f"{champ} : valeurs en conflit, un choix est requis")
        else:
            valeur = bloc["valeur"]
        if valeur:
            valeurs[champ] = valeur
    if not valeurs.get("nom"):
        return _refus("REJ-CLIENT-IMPORT-INVALIDE", "fiche sans nom")
    for champ, normaliser in (("courriel", normaliser_courriel), ("telephone", normaliser_telephone),
                              ("code_postal", normaliser_code_postal)):
        if champ in valeurs:
            forme = normaliser(valeurs[champ])
            if forme is None:
                return _refus("REJ-CLIENT-IMPORT-INVALIDE", f"{champ} mal formé : corriger à la source ou écarter")
            valeurs[champ] = forme
    return valeurs, None


def importer_client(
    fiche: Mapping[str, Any], choix: Mapping[str, str] | None, *, par: Any, role: Any, voie: Any, horodatage: Any,
    source: Mapping[str, Any], registre_cible: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Range la fiche DÉFINITIVE d'un client importé (un maillon `client_importe`) : `({"client_id", "maillon"}, None)`
    ou `(None, verdict)` sans rien écrire. L'humain (`par`, `role`, `voie`) est établi par `outils.py`, jamais lu d'un
    argument ; ce module refuse seulement ce qui n'en a pas la forme."""
    if voie not in ("appareil", "approbation") or not isinstance(par, str) or not par.strip():
        return _refus("REJ-HUMAIN-REQUIS", "une fiche client importée se crée par un humain identifié")
    try:
        _horodatage.valider_horodatage(horodatage)
    except ValueError as exc:
        return _refus("REJ-HORODATAGE-INVALIDE", str(exc))
    valeurs, verdict = contact_de(fiche, choix)
    if verdict is not None:
        return None, verdict
    contact = {cle: valeurs[cle] for cle in ("nom", "telephone", "courriel") if cle in valeurs}
    client_id = clients.identifiant_client({"contact": contact})
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") == TYPE_ENTREE and maillon.get("client_id") == client_id:
            return _refus("REJ-CLIENT-DEJA-IMPORTE", f"client {client_id} déjà importé")
    entree = {
        "type_entree": TYPE_ENTREE, "client_id": client_id, "contact": contact,
        "adresse": valeurs.get("adresse"), "ville": valeurs.get("ville"), "code_postal": valeurs.get("code_postal"),
        "source": copy.deepcopy(dict(source)), "importe_par": par, "role": role, "voie": voie,
        "horodatage": horodatage,
    }
    registre_cible.ajouter(entree)
    return {"client_id": client_id, "maillon": registre_cible.lire()[-1]}, None


def clients_importes(maillons: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Les fiches définitives, dans l'ordre d'import."""
    return [copy.deepcopy(dict(m)) for m in maillons if m.get("type_entree") == TYPE_ENTREE]


def empreintes_du_client(maillon: Mapping[str, Any]) -> list[str]:
    """Les clés fortes d'une fiche définitive, pour que le socle ne repropose pas un client déjà importé."""
    contact = maillon.get("contact", {})
    return empreintes_cles({"nom": contact.get("nom", ""), "courriel": contact.get("courriel", ""),
                            "telephone": contact.get("telephone", ""), "adresse": maillon.get("adresse") or "",
                            "code_postal": maillon.get("code_postal") or ""})



# ------------------------------------------------------------------- contacts candidats issus d'une boîte courriel
def importer_contact_courriel(
    fiche: Mapping[str, Any], nom: str | None, *, par: Any, role: Any, voie: Any, horodatage: Any,
    source: Mapping[str, Any], registre_cible: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Range un CONTACT confirmé par un humain (un maillon `contact_courriel_importe`) : un correspondant d'une boîte
    courriel (nom affiché, adresse, organisation déduite du domaine, volumétrie), PAS un client. Même registre
    dédié et même `client_id` du Client 360 que les clients importés : un lead futur au même contact rejoint la même
    identité. `nom` : le nom que l'humain fournit ou confirme (obligatoire si le courriel n'en affichait aucun).
    `({"client_id", "maillon"}, None)` ou `(None, verdict)` sans rien écrire."""
    if voie not in ("appareil", "approbation") or not isinstance(par, str) or not par.strip():
        return _refus("REJ-HUMAIN-REQUIS", "un contact courriel se confirme par un humain identifié")
    try:
        _horodatage.valider_horodatage(horodatage)
    except ValueError as exc:
        return _refus("REJ-HORODATAGE-INVALIDE", str(exc))
    adresse = normaliser_courriel(str(fiche.get("courriel", "")))
    nom_retenu = " ".join((nom or fiche.get("nom") or "").split())[:_VALEUR_MAX]
    if adresse is None:
        return _refus("REJ-CLIENT-IMPORT-INVALIDE", "adresse mal formée : écarter le brouillon")
    if not nom_retenu:
        return _refus("REJ-CLIENT-IMPORT-INVALIDE", "contact sans nom : fournir le nom à la validation")
    contact = {"nom": nom_retenu, "courriel": adresse}
    client_id = clients.identifiant_client({"contact": contact})
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") in (TYPE_ENTREE, TYPE_CONTACT_COURRIEL) and maillon.get("client_id") == client_id:
            return _refus("REJ-CLIENT-DEJA-IMPORTE", f"contact {client_id} déjà importé")
    entree = {
        "type_entree": TYPE_CONTACT_COURRIEL, "client_id": client_id, "contact": contact,
        "organisation": fiche.get("organisation") or None, "adresse": None, "ville": None, "code_postal": None,
        "volumetrie": {k: fiche.get(k) for k in ("recus", "envoyes", "premier", "dernier")},
        "source": copy.deepcopy(dict(source)), "importe_par": par, "role": role, "voie": voie,
        "horodatage": horodatage,
    }
    registre_cible.ajouter(entree)
    return {"client_id": client_id, "maillon": registre_cible.lire()[-1]}, None


def contacts_courriel_importes(maillons: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Les contacts courriel confirmés, dans l'ordre d'import."""
    return [copy.deepcopy(dict(m)) for m in maillons if m.get("type_entree") == TYPE_CONTACT_COURRIEL]
