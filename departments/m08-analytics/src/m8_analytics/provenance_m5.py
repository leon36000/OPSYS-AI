"""Diagnostic PUR des copies M5/M8 : ni SQL, ni réception, ni calcul financier."""

from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

from . import cash_libre, mesures_chantier

_DETAIL = "Le diagnostic ne satisfait pas son contrat ; aucun détail partiel n’est transmis."
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:[.,][0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})?\Z"
)
_MAX_INT = 2**53 - 1
_GRAINS = {
    "cash_global": ("m5.cash_libre_constate", "faits_cash_libre", "cash_libre_constate"),
    "rentabilite_wct": ("m5.rentabilite_chantier", "faits_chantier", "rentabilite"),
}
_RESUME = ("enregistre", "deja_enregistre", "evenement_id", "wct_id", "sequence", "date_reference", "statut", "verdict")


class Refus(ValueError):
    """Verdict fermé, sans texte extrait de la source."""

    def __init__(self, suffixe: str):
        self.verdict = {"code": "REJ-M8-PROVENANCE-" + suffixe, "detail": _DETAIL}
        super().__init__(self.verdict["code"])


def _exiger(condition: bool, suffixe: str) -> None:
    if not condition:
        raise Refus(suffixe)


def _int(v: Any, minimum: int = 0, maximum: int = _MAX_INT) -> bool:
    return type(v) is int and minimum <= v <= maximum


def _texte(v: Any, maximum: int) -> bool:
    return (
        type(v) is str
        and bool(v.strip())
        and len(v) <= maximum
        and not any(unicodedata.category(c) in {"Cc", "Cs"} for c in v)
    )


def _instant(v: Any, *, timezone: bool = True) -> bool:
    if type(v) is not str or _INSTANT.fullmatch(v) is None:
        return False
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return False
    return not timezone or d.utcoffset() is not None


def _jour(v: Any) -> bool:
    if type(v) is not str:
        return False
    try:
        return date.fromisoformat(v).isoformat() == v
    except ValueError:
        return False


def valider_json(v: Any, *, suffixe: str = "SOURCE-INVALIDE", profondeur: int = 0) -> None:
    """Valeurs JSON du codec ; types inattendus et nombres non finis refusés sans conversion."""
    _exiger(profondeur <= 16, suffixe)
    if v is None or type(v) is bool:
        return
    if type(v) is str:
        _exiger(not any(unicodedata.category(c) == "Cs" for c in v), suffixe)
    elif type(v) is int:
        _exiger(-_MAX_INT <= v <= _MAX_INT, suffixe)
    elif type(v) is float:
        _exiger(math.isfinite(v) and -_MAX_INT <= v <= _MAX_INT, suffixe)
    elif type(v) is list:
        for item in v:
            valider_json(item, suffixe=suffixe, profondeur=profondeur + 1)
    elif type(v) is dict:
        for k, item in v.items():
            _exiger(type(k) is str, suffixe)
            valider_json(k, suffixe=suffixe, profondeur=profondeur + 1)
            valider_json(item, suffixe=suffixe, profondeur=profondeur + 1)
    else:
        raise Refus(suffixe)


def valider_arguments(arguments: Any) -> dict[str, Any]:
    _exiger(
        type(arguments) is dict and set(arguments) == {"perimetre", "wct_id", "decalage", "limite"},
        "ARGUMENTS-INVALIDES",
    )
    a = arguments
    _exiger(type(a["perimetre"]) is str and a["perimetre"] in _GRAINS, "ARGUMENTS-INVALIDES")
    _exiger(_int(a["decalage"], 0, 10000) and _int(a["limite"], 1, 8), "ARGUMENTS-INVALIDES")
    _exiger(a["wct_id"] is None if a["perimetre"] == "cash_global" else _texte(a["wct_id"], 256), "ARGUMENTS-INVALIDES")
    return copy.deepcopy(a)


def _publication(p: Any, type_attendu: str) -> dict[str, Any]:
    _exiger(
        type(p) is dict and set(p) == {"evenement_id", "type_evenement", "producteur", "charge", "cree_le"},
        "SOURCE-INVALIDE",
    )
    valider_json(p)
    c = p["charge"]
    _exiger(
        p["type_evenement"] == type_attendu
        and p["producteur"] == "m05-financecore"
        and _texte(p["evenement_id"], 128)
        and _instant(p["cree_le"])
        and type(c) is dict,
        "SOURCE-INVALIDE",
    )
    _exiger(c.get("evenement_id") == p["evenement_id"] and _int(c.get("sequence"), 1), "SOURCE-INVALIDE")
    rent = type_attendu == "m5.rentabilite_chantier"
    champ_version = "version_entrees" if rent else "version_donnees"
    _exiger(type(c.get(champ_version)) is str and _HEX.fullmatch(c[champ_version]) is not None, "SOURCE-INVALIDE")
    if rent:
        _exiger(
            all(_texte(c.get(k), 256) for k in ("devis_id", "wct_id", "chantier_id"))
            and _instant(c.get("horodatage_completion"))
            and type(c.get("verdict")) is str
            and c["verdict"] in {"CALCULEE", "PARTIELLE"},
            "SOURCE-INVALIDE",
        )
    else:
        _exiger(
            _jour(c.get("date_reference"))
            and type(c.get("statut")) is str
            and c["statut"] in {"CALCULE", "NON_CALCULABLE"},
            "SOURCE-INVALIDE",
        )
    return p


def _maillon(m: Any, type_fait: str) -> dict[str, Any]:
    _exiger(type(m) is dict and set(m) == {"rang", "cree_le", "fuseau", "maillon"}, "REGISTRE-INVALIDE")
    valider_json(m, suffixe="REGISTRE-INVALIDE")
    _exiger(_int(m["rang"]) and type(m["maillon"]) is dict, "REGISTRE-INVALIDE")
    if m["fuseau"] == "inconnu":
        _exiger(m["cree_le"] is None, "REGISTRE-INVALIDE")
    else:
        _exiger(
            type(m["fuseau"]) is str
            and m["fuseau"] in {"present", "non_persiste"}
            and _instant(m["cree_le"], timezone=False),
            "REGISTRE-INVALIDE",
        )
        aware = datetime.fromisoformat(m["cree_le"]).utcoffset() is not None
        _exiger(aware == (m["fuseau"] == "present"), "REGISTRE-INVALIDE")
    f = m["maillon"]
    _exiger(type(f.get("type_entree")) is str, "REGISTRE-INVALIDE")
    if f["type_entree"] != type_fait:
        return m
    if type_fait == "cash_libre_constate":
        _exiger(
            _texte(f.get("evenement_id"), 128)
            and _int(f.get("sequence"), 1)
            and type(f.get("version_donnees")) is str
            and _HEX.fullmatch(f["version_donnees"]) is not None,
            "REGISTRE-INVALIDE",
        )
    else:
        _exiger(_texte(f.get("wct_id"), 256), "REGISTRE-INVALIDE")
        if "devis_id" in f and f["devis_id"] is not None:
            _exiger(_texte(f["devis_id"], 256), "REGISTRE-INVALIDE")
        if "sequence" in f:
            _exiger(_int(f["sequence"], 1), "REGISTRE-INVALIDE")
        if "version_entrees" in f:
            _exiger(
                type(f["version_entrees"]) is str and _HEX.fullmatch(f["version_entrees"]) is not None,
                "REGISTRE-INVALIDE",
            )
        for k in ("prix_definitif", "cout_reel_complet"):
            if k in f:
                _exiger(type(f[k]) is bool, "REGISTRE-INVALIDE")
    return m


def _receipts(recus: Any, ids: set[str]) -> dict[str, dict[str, Any]]:
    index = {}
    for r in recus:
        _exiger(
            type(r) is dict
            and set(r) == {"evenement_id", "consommateur", "statut", "tentatives", "prochaine_tentative", "resultat"},
            "SOURCE-INVALIDE",
        )
        valider_json(r)
        _exiger(
            _texte(r["evenement_id"], 128)
            and r["evenement_id"] in ids
            and r["evenement_id"] not in index
            and r["consommateur"] == "m08-analytics"
            and type(r["statut"]) is str
            and r["statut"] in {"traite", "echec", "quarantaine"}
            and _int(r["tentatives"])
            and (r["prochaine_tentative"] is None or _instant(r["prochaine_tentative"])),
            "SOURCE-INVALIDE",
        )
        index[r["evenement_id"]] = r
    return index


def _resume(p: dict, r: dict | None) -> tuple[dict, list[str]]:
    c = p["charge"]
    result = dict.fromkeys(_RESUME)
    codes = ["HORODATAGE_RECEPTION_NON_PERSISTE"]
    statut = "ABSENT" if r is None else r["statut"]
    coherent = None
    if statut != "traite":
        codes.append({"ABSENT": "RECU_ABSENT", "echec": "RECU_ECHEC", "quarantaine": "RECU_QUARANTAINE"}[statut])
    else:
        raw = r["resultat"]
        _exiger(raw is None or type(raw) is dict, "SOURCE-INVALIDE")
        raw = raw or {}
        rent = p["type_evenement"] == "m5.rentabilite_chantier"
        wanted = (
            {"wct_id": c["wct_id"], "sequence": c["sequence"], "verdict": c["verdict"]}
            if rent
            else {
                "evenement_id": p["evenement_id"],
                "sequence": c["sequence"],
                "date_reference": c["date_reference"],
                "statut": c["statut"],
            }
        )
        for k in {"enregistre", "deja_enregistre", *wanted}:
            if k not in raw:
                continue
            v = raw[k]
            valid = (
                type(v) is bool
                if k in {"enregistre", "deja_enregistre"}
                else (
                    _int(v, 1)
                    if k == "sequence"
                    else _jour(v)
                    if k == "date_reference"
                    else type(v) is str and v in {"CALCULE", "NON_CALCULABLE"}
                    if k == "statut"
                    else type(v) is str and v in {"CALCULEE", "PARTIELLE"}
                    if k == "verdict"
                    else _texte(v, 128 if k == "evenement_id" else 256)
                )
            )
            _exiger(valid, "SOURCE-INVALIDE")
            result[k] = v
        flags = result["enregistre"], result["deja_enregistre"]
        if None not in flags:
            _exiger(flags[0] is not flags[1], "SOURCE-INVALIDE")
        known = all(result[k] is not None for k in {"enregistre", "deja_enregistre", *wanted})
        contradictory = any(result[k] is not None and result[k] != v for k, v in wanted.items())
        coherent = False if contradictory else True if known else None
        if coherent is False:
            codes.append("RESUME_DIFFERENT")
        elif coherent is None:
            codes.append("RESUME_HISTORIQUE_INCOMPLET")
    return {
        "reference": {"evenement_id": p["evenement_id"], "consommateur": "m08-analytics"},
        "statut": statut,
        "tentatives": None if r is None else r["tentatives"],
        "prochaine_tentative": None if r is None else r["prochaine_tentative"],
        "horodatage_reception": None,
        "resume": result,
        "resume_coherent": coherent,
    }, codes


def _candidats(p: dict, faits: list[dict]) -> list[dict]:
    c = p["charge"]
    if p["type_evenement"] == "m5.cash_libre_constate":
        return [m for m in faits if m["maillon"].get("evenement_id") == p["evenement_id"]]
    return [
        m
        for m in faits
        if m["maillon"].get("wct_id") == c["wct_id"]
        and m["maillon"].get("devis_id") in (None, c["devis_id"])
        and m["maillon"].get("sequence") in (None, c["sequence"])
    ]


def _fait(m: dict, registre: str) -> dict:
    f = m["maillon"]
    cash = f["type_entree"] == "cash_libre_constate"
    champ = "version_donnees" if cash else "version_entrees"
    return {
        "reference": {"departement": "m08-analytics", "registre": registre, "rang": m["rang"]},
        "type_entree": f["type_entree"],
        "sequence": f.get("sequence"),
        "version": {"champ": champ, "valeur": f[champ]} if champ in f else None,
        "enregistrement_SQL": {"valeur": m["cree_le"], "fuseau": m["fuseau"]},
        "evenement_id_persiste": f.get("evenement_id") if cash else None,
    }


def _egal_json(a: Any, b: Any) -> bool:
    """Même structure et mêmes types JSON, sans conversion bool/int/float ou Decimal."""
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(_egal_json(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(_egal_json(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _ligne(
    p: dict, r: dict | None, candidats: list[dict], registre: str, collision: bool, courante: bool | None
) -> dict:
    c = p["charge"]
    recu, codes = _resume(p, r)
    rent = p["type_evenement"] == "m5.rentabilite_chantier"
    fait = _fait(candidats[0], registre) if len(candidats) == 1 else None
    faibles = rent and bool(candidats) and all("sequence" not in m["maillon"] for m in candidats)
    if collision or (len(candidats) > 1 and not faibles):
        etat = "LIEN_AMBIGU"
        if collision:
            codes.append("PLUSIEURS_PUBLICATIONS_MEME_SEQUENCE")
        if len(candidats) > 1:
            codes.append("PLUSIEURS_FAITS_CANDIDATS")
    elif faibles:
        # Aucun maillon ne porte la séquence : les historiques n'authentifient pas la source courante.
        etat = "LIEN_INCONNU"
        codes.extend(("ID_NON_PERSISTE_DANS_FAIT", "SEQUENCE_HISTORIQUE_ABSENTE"))
        if fait is not None and fait["version"] is None:
            codes.append("VERSION_HISTORIQUE_ABSENTE")
        if recu["statut"] != "traite":
            codes.append("FAIT_SANS_RECU_TRAITE")
    elif not candidats:
        etat = "FAIT_ABSENT"
        if recu["statut"] == "traite":
            codes.append("RECU_TRAITE_SANS_FAIT")
    else:
        f = candidats[0]["maillon"]
        expected = mesures_chantier.fait_rentabilite(c) if rent else cash_libre.fait_constat(c)
        different = any(k not in expected or not _egal_json(expected[k], v) for k, v in f.items())
        if different:
            etat = "FAITS_DIVERGENTS"
            codes.append("PROJECTION_DIFFERENTE")
        elif rent:
            codes.append("ID_NON_PERSISTE_DANS_FAIT")
            if "version_entrees" not in f:
                codes.append("VERSION_HISTORIQUE_ABSENTE")
            if "sequence" not in f:
                etat = "LIEN_INCONNU"
                codes.append("SEQUENCE_HISTORIQUE_ABSENTE")
            else:
                etat = "CORRESPONDANCE_DE_PROJECTION"
        elif _egal_json(f, expected) and recu["statut"] == "traite" and recu["resume_coherent"] is True:
            etat = "RECEPTION_LIEE_ID_EXACT"
        else:
            etat = "LIEN_INCONNU"
        if recu["statut"] != "traite":
            codes.append("FAIT_SANS_RECU_TRAITE")
    champ = "version_entrees" if rent else "version_donnees"
    return {
        "publication": {
            "reference": {"type": p["type_evenement"], "evenement_id": p["evenement_id"]},
            "producteur": p["producteur"],
            "cree_le": p["cree_le"],
            "sequence": c["sequence"],
            "version": {"champ": champ, "valeur": c[champ]},
            "devis_id": c.get("devis_id") if rent else None,
            "wct_id": c.get("wct_id") if rent else None,
            "chantier_id": c.get("chantier_id") if rent else None,
            "date_reference": None if rent else c["date_reference"],
            "horodatage_completion": c["horodatage_completion"] if rent else None,
            "statut": c["verdict"] if rent else c["statut"],
            "courante_pour_devis": courante,
        },
        "recu_bus": recu,
        "fait": fait,
        "rapprochement": {"etat": etat, "codes": list(dict.fromkeys(codes))},
    }


def _sources(sources: Any, counts: tuple[int, int, int], registre: str) -> list[dict]:
    _exiger(type(sources) is list and len(sources) == 3, "SOURCE-INVALIDE")
    for index, (s, table) in enumerate(
        zip(sources, ("evenements_sortants", "evenements_recus", "registres_maillons"), strict=True)
    ):
        _exiger(
            type(s) is dict
            and set(s) == {"table", "departement", "registre", "lignes", "empreinte_snapshot_calculee"}
            and s["table"] == table
            and _int(s["lignes"])
            and s["lignes"] == counts[index]
            and type(s["empreinte_snapshot_calculee"]) is str
            and _HEX.fullmatch(s["empreinte_snapshot_calculee"]) is not None,
            "SOURCE-INVALIDE",
        )
        _exiger(
            s["departement"] == ("m08-analytics" if index == 2 else None)
            and s["registre"] == (registre if index == 2 else None),
            "SOURCE-INVALIDE",
        )
    return copy.deepcopy(sources)


def _taille(dto: dict) -> int:
    return len(json.dumps({"ok": True, "resultat": {"accepte": True, "resultat": dto}}, ensure_ascii=False))


def produire(
    publications: Any, recus: Any, maillons: Any, sources: Any, arguments: Any, *, budget_sortie: int
) -> dict[str, Any]:
    """Classifie toutes les copies puis borne la page, sans mutation ni horloge."""
    a = valider_arguments(arguments)
    _exiger(_int(budget_sortie, 1, 5400), "SORTIE-TROP-VOLUMINEUSE")
    _exiger(all(type(v) in (list, tuple) for v in (publications, recus, maillons)), "SOURCE-INVALIDE")
    counts = len(publications), len(recus), len(maillons)
    _exiger(sum(counts) <= 10000, "BUDGET-SOURCE-DEPASSE")
    typ, registre, type_fait = _GRAINS[a["perimetre"]]
    provenance = _sources(sources, counts, registre)
    pubs = [_publication(p, typ) for p in publications]
    ids = {p["evenement_id"] for p in pubs}
    _exiger(len(ids) == len(pubs), "SOURCE-INVALIDE")
    receipt_index = _receipts(recus, ids)
    tous_faits = [_maillon(m, type_fait) for m in maillons]
    _exiger(len({m["rang"] for m in tous_faits}) == len(tous_faits), "REGISTRE-INVALIDE")
    faits = [m for m in tous_faits if m["maillon"]["type_entree"] == type_fait]
    if a["perimetre"] == "rentabilite_wct":
        pubs = [p for p in pubs if p["charge"]["wct_id"] == a["wct_id"]]
        faits = [m for m in faits if m["maillon"]["wct_id"] == a["wct_id"]]
    pubs.sort(key=lambda p: (-p["charge"]["sequence"], p["evenement_id"]))
    devis = {p["charge"]["devis_id"] for p in pubs} if a["perimetre"] == "rentabilite_wct" else set()
    maxima = {}
    for p in pubs:
        d = p["charge"].get("devis_id")
        maxima[d] = max(maxima.get(d, 0), p["charge"]["sequence"])
    # Index éphémères de cette copie ; les champs historiques absents restent des candidats faibles.
    index_faits = defaultdict(list)
    rent = a["perimetre"] == "rentabilite_wct"
    for m in faits:
        f = m["maillon"]
        cle = (f.get("wct_id"), f.get("devis_id"), f.get("sequence")) if rent else f["evenement_id"]
        index_faits[cle].append(m)
    candidats_par_id = {}
    rangs_rapproches = set()
    for p in pubs:
        c = p["charge"]
        if rent:
            forts = [m for d in (None, c["devis_id"]) for m in index_faits[(c["wct_id"], d, c["sequence"])]]
            candidats = forts or [m for d in (None, c["devis_id"]) for m in index_faits[(c["wct_id"], d, None)]]
        else:
            candidats = index_faits[p["evenement_id"]]
        candidats_par_id[p["evenement_id"]] = candidats
        rangs_rapproches.update(m["rang"] for m in candidats)
    cles = [(p["charge"].get("wct_id"), p["charge"]["sequence"]) for p in pubs]
    occurrences = Counter(cles)
    lignes = []
    for p, cle in zip(pubs, cles, strict=True):
        courante = p["charge"]["sequence"] == maxima[p["charge"]["devis_id"]] if devis else None
        collision = occurrences[cle] > 1
        ligne = _ligne(
            p, receipt_index.get(p["evenement_id"]), candidats_par_id[p["evenement_id"]], registre, collision, courante
        )
        if len(devis) > 1:
            ligne["rapprochement"]["codes"].append("PLUSIEURS_DEVIS_POUR_WCT")
        lignes.append(ligne)
    selection = {"publication_courante_id": None, "fact_courant_reference": None, "ambiguite": False}
    if lignes:
        tete = lignes[0]
        ambigu = len(devis) > 1 or occurrences[cles[0]] > 1
        selection["ambiguite"] = ambigu
        if not ambigu:
            selection["publication_courante_id"] = tete["publication"]["reference"]["evenement_id"]
            if tete["fait"] and tete["rapprochement"]["etat"] in {
                "RECEPTION_LIEE_ID_EXACT",
                "CORRESPONDANCE_DE_PROJECTION",
            }:
                selection["fact_courant_reference"] = tete["fait"]["reference"]
    total = len(lignes)
    depart = a["decalage"]
    orphelins = sum(m["rang"] not in rangs_rapproches for m in faits)
    dto = {
        "type": "DIAGNOSTIC_RECEPTION_M5",
        "version_schema": 1,
        "perimetre": a["perimetre"],
        "wct_id": a["wct_id"],
        "portee": "PUBLICATIONS_M5_EXISTANTES_SEULEMENT",
        "sources": provenance,
        "selection": selection,
        "publications": [],
        "affichage": {
            "decalage": depart,
            "limite": a["limite"],
            "total_publications": total,
            "affiches": 0,
            "reste": max(0, total - depart),
            "prochain_decalage": depart if depart < total else None,
        },
        "couverture": {
            "base": "publications_existantes",
            "registres_preparatoires_M5": "exclus",
            "completude_financiere_entreprise": False,
            "horodatage_reception": "non_persiste",
            "orphelins_faits": orphelins,
            "plafond_lignes": 10000,
        },
    }
    _exiger(_taille(dto) <= budget_sortie, "SORTIE-TROP-VOLUMINEUSE")
    for ligne in lignes[depart : depart + a["limite"]]:
        proposed = copy.deepcopy(dto)
        proposed["publications"].append(ligne)
        n = len(proposed["publications"])
        reste = max(0, total - depart - n)
        proposed["affichage"].update(affiches=n, reste=reste, prochain_decalage=depart + n if reste else None)
        if _taille(proposed) > budget_sortie:
            _exiger(bool(dto["publications"]), "SORTIE-TROP-VOLUMINEUSE")
            break
        dto = proposed
    return dto
