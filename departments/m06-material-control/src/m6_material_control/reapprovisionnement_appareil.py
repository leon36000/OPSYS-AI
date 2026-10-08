"""Réapprovisionnement courant : projection DEVICE pure sur copies de sources validées."""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal, DecimalException, Inexact, Overflow, Rounded, localcontext
from typing import Any

from . import emplacements, pertes_appareil, reapprovisionnement, registre, reservations, stock

PLAFOND_LIGNES = 10000
BORNE_CARACTERES = 5400
_REGISTRES = ("besoins_commande", "principal", "reservations", "emplacements")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_CODES_CONFIGURATION = frozenset(
    {
        "REJ-REAPPRO-CONFIGURATION-ILLISIBLE",
        "REJ-REAPPRO-ARTICLE-INVALIDE",
        "REJ-REAPPRO-SEUIL-INVALIDE",
        "REJ-REAPPRO-CIBLE-INVALIDE",
    }
)
_DETAILS = {
    "ARGUMENTS-INVALIDES": "les arguments sortent du contrat de lecture du réapprovisionnement",
    "REGISTRE-INVALIDE": "un snapshot métier ne satisfait pas son contrat d’intégrité",
    "SOURCE-INVALIDE": "une source requise ne satisfait pas le contrat de lecture",
    "LIAISON-INCOHERENTE": "le dernier constat ne concorde pas avec les sources du WCT et de sa déclaration",
    "CONFIGURATION-ILLISIBLE": "le fichier de configuration ne peut pas être copié pour cette lecture",
    "BORNE-SOURCES": "les snapshots copiés dépassent la borne de traitement de 10000 lignes",
    "CALCUL-INVALIDE": "les données ne permettent pas un calcul décimal exact dans cette lecture",
    "SORTIE-TROP-VOLUMINEUSE": "la lecture dépasse la borne de sortie ; aucun détail partiel n’est transmis",
}


class Refus(ValueError):
    def __init__(self, suffixe: str):
        self.suffixe = suffixe


def refuser(suffixe: str) -> dict:
    return {"accepte": False, "verdict": {"code": "REJ-M6-REAPPRO-" + suffixe, "detail": _DETAILS[suffixe]}}


def empreinte_snapshot(valeur: Any) -> str:
    return hashlib.sha256(
        json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def arguments_valides(decalage: Any, limite: Any) -> bool:
    return type(decalage) is int and 0 <= decalage <= 10000 and type(limite) is int and 1 <= limite <= 8


def _texte(v: Any, maximum: int = 256) -> bool:
    return pertes_appareil.texte(v, maximum)


def _metadata_non_vide(v: Any) -> bool:
    # Ces champs non projetés suivent le writer existant : texte humain non vide,
    # sans imposer l'ISO du dernier constat ni une nouvelle longueur de motif.
    return isinstance(v, str) and bool(v.strip())


def _identifiant_interne(v: Any) -> bool:
    # Les writers de réservations requièrent une chaîne non vide, sans la borne
    # ni la politique Unicode des identifiants projetés. Ne jamais réécrire la clé.
    return isinstance(v, str) and bool(v)


def _date(v: Any) -> None:
    try:
        pertes_appareil._instant(v)
    except pertes_appareil.Refus:
        raise Refus("SOURCE-INVALIDE") from None


def _decimal(v: Any, *, texte: bool = False) -> Decimal:
    if texte:
        if not isinstance(v, str) or not _DECIMAL.fullmatch(v):
            raise Refus("REGISTRE-INVALIDE")
    elif type(v) not in (int, float) or (type(v) is float and not math.isfinite(v)):
        raise Refus("REGISTRE-INVALIDE")
    d = Decimal(str(v))
    if not d.is_finite():
        raise Refus("REGISTRE-INVALIDE")
    return d


def _rangs(rows: list) -> list[dict]:
    maillons = []
    for position, r in enumerate(rows):
        if (
            not isinstance(r, dict)
            or set(r) != {"rang", "maillon"}
            or type(r["rang"]) is not int
            or r["rang"] != position
            or not isinstance(r["maillon"], dict)
        ):
            raise Refus("REGISTRE-INVALIDE")
        maillons.append(r["maillon"])
    return maillons


def _principal(rows: list[dict], chiffres: list[Decimal]) -> None:
    requis = {
        "index",
        "type_mouvement",
        "chantier_id",
        "materiau_id",
        "quantite",
        "cout_unitaire",
        "hash_precedent",
        "hash_maillon",
    }
    for position, m in enumerate(rows):
        if (
            not requis <= set(m) <= requis | {"wct_id"}
            or type(m["index"]) is not int
            or m["index"] != position
            or m["type_mouvement"] not in registre.TYPES_MOUVEMENT_VALIDES
            or not _texte(m["chantier_id"])
            or not _texte(m["materiau_id"])
            or ("wct_id" in m and not _texte(m["wct_id"]))
        ):
            raise Refus("REGISTRE-INVALIDE")
        q = _decimal(m["quantite"])
        if (m["type_mouvement"] in {"CONSOMMATION", "PERTE", "BRIS"} and q >= 0) or (
            m["type_mouvement"] in {"RECEPTION", "RETOUR"} and q <= 0
        ):
            raise Refus("REGISTRE-INVALIDE")
        if m["cout_unitaire"] is not None:
            _decimal(m["cout_unitaire"])
        chiffres.append(q)
    if not registre.Registre(rows).valider_chaine()[0]:
        raise Refus("REGISTRE-INVALIDE")


def _constats(rows: list[dict]) -> dict[str, tuple[int, dict]]:
    base = {"type_entree", "constat_id", "materiau_id", "evenement_declencheur", "chantier_id", "unite", "horodatage"}
    derniers, identifiants = {}, set()
    for rang, m in enumerate(rows):
        if (
            not base <= set(m)
            or not _texte(m["materiau_id"])
            or not _texte(m["evenement_declencheur"])
            or (m["chantier_id"] is not None and not _texte(m["chantier_id"]))
            or (m["unite"] is not None and not _texte(m["unite"]))
        ):
            raise Refus("REGISTRE-INVALIDE")
        _date(m["horodatage"])
        if m["type_entree"] == "besoin_commande":
            keys = {
                "stock_theorique",
                "seuil_reapprovisionnement",
                "quantite_cible",
                "quantite_a_commander",
                "stock_negatif",
            }
            extra = set(m) - base - keys
            if not keys <= set(m) or extra not in (set(), {"stock_reserve", "stock_disponible"}):
                raise Refus("REGISTRE-INVALIDE")
            for k in keys - {"stock_negatif", "quantite_a_commander"} | extra:
                _decimal(m[k], texte=True)
            if m["quantite_a_commander"] is not None:
                _decimal(m["quantite_a_commander"], texte=True)
            if type(m["stock_negatif"]) is not bool or m["stock_negatif"] != (
                _decimal(m["stock_theorique"], texte=True) < 0
            ):
                raise Refus("REGISTRE-INVALIDE")
        elif m["type_entree"] == "seuil_a_configurer":
            if (
                set(m) != base | {"motif", "code", "detail"}
                or m["motif"] not in {"seuil_absent", "configuration_invalide"}
                or (m["motif"] == "seuil_absent" and (m["code"] is not None or m["detail"] is not None))
                or (m["motif"] == "configuration_invalide" and m["code"] not in _CODES_CONFIGURATION)
                or (m["detail"] is not None and not isinstance(m["detail"], str))
            ):
                raise Refus("REGISTRE-INVALIDE")
        else:
            raise Refus("REGISTRE-INVALIDE")
        if (
            m["constat_id"] != f"{m['type_entree']}:{m['materiau_id']}:{m['evenement_declencheur']}"
            or m["constat_id"] in identifiants
        ):
            raise Refus("REGISTRE-INVALIDE")
        identifiants.add(m["constat_id"])
        derniers[m["materiau_id"]] = (rang, m)
    return derniers


def _reservations(rows: list[dict], chiffres: list[Decimal]) -> None:
    base = {
        "type_entree",
        "devis_id",
        "chantier_id",
        "revision",
        "evenement",
        "actif",
        "declencheur",
        "horodatage",
        "acteur",
        "motif",
        "lignes",
    }
    revisions = {}
    for m in rows:
        event = m.get("evenement")
        supplement = {"liberees"} if event == "liberee" else {"wct_id"} if event == "cloturee" else set()
        if (
            set(m) != base | supplement
            or m["type_entree"] != "reservation"
            or not _identifiant_interne(m["devis_id"])
            or (m["chantier_id"] is not None and not _identifiant_interne(m["chantier_id"]))
            or type(m["revision"]) is not int
            or m["revision"] != revisions.get(m["devis_id"], 0) + 1
            or event not in {"creee", "ajustee", "liberee", "cloturee"}
            or type(m["actif"]) is not bool
            or m["actif"] != (event in {"creee", "ajustee"})
            or m["declencheur"] not in reservations.DECLENCHEURS
            or not isinstance(m["lignes"], list)
            or not m["lignes"]
        ):
            raise Refus("REGISTRE-INVALIDE")
        if not _metadata_non_vide(m["horodatage"]):
            raise Refus("REGISTRE-INVALIDE")
        if (m["acteur"] is not None and not _metadata_non_vide(m["acteur"])) or (
            m["motif"] is not None and not _metadata_non_vide(m["motif"])
        ):
            raise Refus("REGISTRE-INVALIDE")
        vus = set()
        for line in m["lignes"]:
            if (
                not isinstance(line, dict)
                or set(line) != {"materiau_id", "unite", "quantite_besoin", "quantite_reservee"}
                or not _texte(line["materiau_id"])
                or line["materiau_id"] in vus
                or (line["unite"] is not None and not _identifiant_interne(line["unite"]))
            ):
                raise Refus("REGISTRE-INVALIDE")
            besoin, reserve = (
                _decimal(line["quantite_besoin"], texte=True),
                _decimal(line["quantite_reservee"], texte=True),
            )
            if besoin <= 0 or not 0 <= reserve <= besoin or (not m["actif"] and reserve != 0):
                raise Refus("REGISTRE-INVALIDE")
            chiffres.extend((besoin, reserve))
            vus.add(line["materiau_id"])
        if event == "cloturee" and not _identifiant_interne(m["wct_id"]):
            raise Refus("REGISTRE-INVALIDE")
        if event == "liberee":
            if not isinstance(m["liberees"], list):
                raise Refus("REGISTRE-INVALIDE")
            for line in m["liberees"]:
                if (
                    not isinstance(line, dict)
                    or set(line) != {"materiau_id", "quantite"}
                    or not _texte(line["materiau_id"])
                    or _decimal(line["quantite"], texte=True) <= 0
                ):
                    raise Refus("REGISTRE-INVALIDE")
        revisions[m["devis_id"]] = m["revision"]


def _emplacements(rows: list[dict], chiffres: list[Decimal]) -> None:
    keys = {
        "type_entree",
        "index",
        "transfert_id",
        "materiau_id",
        "quantite",
        "de",
        "vers",
        "acteur",
        "motif",
        "horodatage",
        "avant",
        "apres",
        "hash_precedent",
        "hash_maillon",
    }
    for index, m in enumerate(rows):
        if (
            set(m) != keys
            or m["type_entree"] != "transfert"
            or type(m["index"]) is not int
            or m["index"] != index
            or not _metadata_non_vide(m["transfert_id"])
            or not _texte(m["materiau_id"])
            or not _metadata_non_vide(m["acteur"])
            or not _metadata_non_vide(m["motif"])
            or not isinstance(m["quantite"], str)
        ):
            raise Refus("REGISTRE-INVALIDE")
        if not _metadata_non_vide(m["horodatage"]):
            raise Refus("REGISTRE-INVALIDE")
        q = _decimal(m["quantite"], texte=True)
        if q <= 0:
            raise Refus("REGISTRE-INVALIDE")
        chiffres.append(q)
        for k in ("de", "vers"):
            normalized, refusal = emplacements.normaliser(m[k])
            if refusal is not None or normalized != m[k]:
                raise Refus("REGISTRE-INVALIDE")
        if m["de"] == m["vers"]:
            raise Refus("REGISTRE-INVALIDE")
        for k in ("avant", "apres"):
            if not isinstance(m[k], dict) or set(m[k]) != {"de", "vers"}:
                raise Refus("REGISTRE-INVALIDE")
            for v in m[k].values():
                if _decimal(v, texte=True) < 0:
                    raise Refus("REGISTRE-INVALIDE")
    if not emplacements.valider_chaine(rows)[0]:
        raise Refus("REGISTRE-INVALIDE")


def _precision(chiffres: list[Decimal]) -> int:
    nonzero = [d for d in chiffres if not d.is_zero()]
    if not nonzero:
        return 28
    return max(
        28,
        max(d.adjusted() for d in nonzero)
        - min(d.as_tuple().exponent for d in nonzero)
        + len(str(len(chiffres) + 1))
        + 8,
    )


def _recus_lies(rows: list[dict], derniers: dict) -> dict:
    # Le snapshot reste entier pour quota/empreinte. Seuls les reçus des derniers
    # constats sont requis pour la liaison : un reçu ancien étranger n'est pas certifié ici.
    cibles = {m["evenement_declencheur"] for _, m in derniers.values()}
    resultat = {}
    for rang, m in enumerate(_rangs(rows)):
        id_ = m.get("wct_id")
        if not isinstance(id_, str) or id_ not in cibles:
            continue
        if (
            set(m) != {"wct_id", "intervention_id", "devis_id", "horodatage_completion", "empreinte_contenu"}
            or not _texte(id_)
            or not isinstance(m["intervention_id"], str)
            or (m["devis_id"] is not None and not isinstance(m["devis_id"], str))
            or not isinstance(m["empreinte_contenu"], str)
            or not re.fullmatch("[0-9a-f]{64}", m["empreinte_contenu"])
            or id_ in resultat
        ):
            raise Refus("SOURCE-INVALIDE")
        _date(m["horodatage_completion"])
        resultat[id_] = {"rang": rows[rang]["rang"], "maillon": m}
    return resultat


def lire(sources: dict, decalage: int, limite: int) -> dict:
    try:
        if not arguments_valides(decalage, limite):
            raise Refus("ARGUMENTS-INVALIDES")
        copied = sources["registres"]
        if set(copied) != set(_REGISTRES) or not all(isinstance(v, list) for v in copied.values()):
            raise Refus("REGISTRE-INVALIDE")
        rec, pub = sources["recus_m6"], sources["publications"]
        if not isinstance(rec, list) or not isinstance(pub, list):
            raise Refus("REGISTRE-INVALIDE")
        if sum(len(v) for v in copied.values()) + len(rec) + len(pub) > PLAFOND_LIGNES:
            raise Refus("BORNE-SOURCES")
        rows = {k: _rangs(v) for k, v in copied.items()}
        chiffres = []
        _principal(rows["principal"], chiffres)
        derniers = _constats(rows["besoins_commande"])
        _reservations(rows["reservations"], chiffres)
        _emplacements(rows["emplacements"], chiffres)
        received, pubs = _recus_lies(rec, derniers), pertes_appareil._publications(pub)
        configuration = sources["configuration"]
        if not isinstance(configuration["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", configuration["sha256"]):
            raise Refus("SOURCE-INVALIDE")
        params = {mat: reapprovisionnement.lire_parametres(configuration["articles"], mat) for mat in derniers}
        for p in params.values():
            if p["statut"] == "configure":
                chiffres.extend((p["seuil"], p["quantite_cible"]))
        with localcontext() as ctx:
            ctx.prec = _precision(chiffres)
            for signal in (Inexact, Rounded, Overflow):
                ctx.traps[signal] = True
            reserve = reservations.reserve_par_article(rows["reservations"])
            hors = emplacements.hors_main_par_article(rows["emplacements"])
            valeurs = stock.deriver_disponibilite(derniers, rows["principal"], hors, reserve)
            articles = []
            for mat, (rang, constat) in sorted(derniers.items(), key=lambda pair: pair[1][0], reverse=True):
                id_ = constat["evenement_declencheur"]
                if id_ not in pubs:
                    raise Refus("LIAISON-INCOHERENTE")
                charge = pertes_appareil._publication(pubs, id_, "m4.travaux_termines", "m04-field-ops")
                if (
                    charge.get("wct_id") != id_
                    or charge.get("horodatage_completion") != constat["horodatage"]
                    or not any(
                        m.get("wct_id") == id_
                        and m["materiau_id"] == mat
                        and m["chantier_id"] == constat["chantier_id"]
                        and m["type_mouvement"] in {"CONSOMMATION", "RETOUR", "PERTE", "BRIS"}
                        for m in rows["principal"]
                    )
                ):
                    raise Refus("LIAISON-INCOHERENTE")
                if id_ in received:
                    pertes_appareil._wct(received[id_], pubs)
                v = valeurs[mat]
                p = params[mat]
                verdict = reapprovisionnement.evaluer(
                    mat, v["en_main"], configuration["articles"], reserve=v["reserve"]
                )
                canon = stock.texte_canonique
                commande = verdict.get("quantite_a_commander")
                articles.append(
                    {
                        "materiau_id": mat,
                        "statut": verdict["statut"],
                        "chiffres": {
                            k: canon(v[n])
                            for k, n in [
                                ("stock_theorique", "stock_theorique"),
                                ("hors_main", "hors_main"),
                                ("en_main", "en_main"),
                                ("reserve", "reserve"),
                                ("disponible", "disponible"),
                            ]
                        },
                        "seuil_reapprovisionnement": canon(p["seuil"]) if p["statut"] == "configure" else None,
                        "quantite_cible": canon(p["quantite_cible"]) if p["statut"] == "configure" else None,
                        "quantite_a_commander": canon(Decimal(commande)) if commande is not None else None,
                        "stock_negatif": v["en_main"] < 0,
                        "code_configuration": verdict.get("code"),
                        "unite": None,
                        "unite_dernier_constat": constat["unite"],
                        "dernier_constat": {
                            "reference": {
                                "registre": "besoins_commande",
                                "rang": copied["besoins_commande"][rang]["rang"],
                                "empreinte_snapshot": empreinte_snapshot(constat),
                            },
                            **{
                                k: constat[k]
                                for k in ("type_entree", "evenement_declencheur", "horodatage", "chantier_id")
                            },
                            "reference_bus": {"type": "m4.travaux_termines", "evenement_id": pubs[id_]["evenement_id"]},
                        },
                    }
                )
        dto = {
            "articles": [],
            "source_configuration": {
                "fichier": "departments/m06-material-control/department.yaml",
                "chemin": "configuration.reapprovisionnement.articles",
                "sha256": configuration["sha256"],
            },
            "sources_registres": [
                {"registre": n, "lignes": len(copied[n]), "empreinte_snapshot": empreinte_snapshot(copied[n])}
                for n in _REGISTRES
            ],
            "source_publications": {
                "evenements": {
                    "type": "m4.travaux_termines",
                    "lignes": len(pub),
                    "empreinte_snapshot": empreinte_snapshot(pub),
                },
                "recus_m6": {
                    "registre": "wct_recus",
                    "lignes": len(rec),
                    "empreinte_snapshot": empreinte_snapshot(rec),
                },
            },
            "couverture": {
                "articles": "articles_deja_constates",
                "stock": "theorique_disponible",
                "unites": "homogeneite_non_confirmee",
                "horodatage": "dernier_constat_sans_date_calcul",
                "plafond_lignes": 10000,
            },
            "borne_caracteres": 5400,
        }
        return pertes_appareil._page(dto, "articles", articles, decalage, limite)
    except Refus as r:
        return refuser(r.suffixe)
    except pertes_appareil.Refus as r:
        return refuser("SORTIE-TROP-VOLUMINEUSE" if r.suffixe == "SORTIE-TROP-VOLUMINEUSE" else "SOURCE-INVALIDE")
    except DecimalException:
        return refuser("CALCUL-INVALIDE")
    except (KeyError, TypeError, ValueError, OverflowError):
        return refuser("REGISTRE-INVALIDE")
