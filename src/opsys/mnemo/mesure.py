"""Harnais de mesure de Mnémo : questions multi-sauts sur le graphe et cas de garde des leçons, avec métriques.

**Ce que ce banc mesure.** (1) Le MOTEUR de graphe : sur un graphe fictif (`graphe` du corpus), des questions dont le
PLAN (parcours pas à pas, nœuds atteignables, plus court chemin, « pourquoi ce lien ») est écrit à la main, avec la
réponse attendue écrite AVANT l'exécution. Métriques : exactitude (ensemble exact), rappel et précision moyens,
abstentions correctes (nœud inconnu → refus typé, pas de réponse inventée), fausses réponses sur les négatifs
(brouillon et arête rejetée ne doivent jamais revenir). Deux moteurs rejouent les mêmes questions (SQL natif et
double) et leur concordance est rapportée. Un témoin « un saut » (le voisinage immédiat, sans parcours) montre ce que
le multi-sauts apporte. (2) Le pipeline de leçons : des séries fictives de chantiers et le verdict attendu (leçon ou
non, promouvable ou non).

**Ce qu'il ne mesure PAS** (dit sans euphémisme). Aucun modèle de langage n'intervient : le banc ne mesure ni la
compréhension d'une question en français, ni la qualité d'un agent qui interrogerait le graphe. Le corpus est petit,
fictif, écrit par la même équipe que le moteur : c'est un banc de non-régression et de démonstration, pas une preuve de
qualité en production. Un score de 100 % prouve la plomberie et le schéma, rien de plus.

Module d'orchestration : il ne lit aucune horloge (les instants du banc sont ceux du corpus) et n'écrit que dans le
moteur qu'on lui donne (une base jetable, jamais l'instance du client).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

import yaml

from . import codes, lecons
from .codes import ErreurMnemo
from .graphe import DemandeArete, GrapheMemoire, MoteurGraphe, NoeudRef, schema

SCHEMA_CORPUS = "opsys.mnemo.corpus/v1"
SCHEMA_RAPPORT = "opsys.mnemo.mesure/v1"
OPERATIONS = ("pas_a_pas", "atteignables", "chemin", "pourquoi")
CATEGORIES = ("un_saut", "temporel", "multi_sauts", "chemin", "pourquoi", "negatif")
QUAND = "2026-12-01T12:00:00+00:00"
PERSONNES = ("client", "propriete")
_SENS = ("sortant", "entrant", "les_deux")


def pseudonyme(nom: str) -> str:
    """Pseudonyme hexadécimal stable d'un nom du corpus (le banc ne manipule jamais de nom de personne)."""
    return hashlib.sha256(f"fictif|{nom}".encode()).hexdigest()[:32]


def _refus(detail: str) -> ErreurMnemo:
    return ErreurMnemo(codes.ENTREE_INVALIDE, f"corpus : {detail}")


def charger_corpus(source: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    donnees = yaml.safe_load(source) if isinstance(source, (str, bytes)) else dict(source)
    if (
        not isinstance(donnees, dict)
        or donnees.get("schema") != SCHEMA_CORPUS
        or donnees.get("fictif") is not True
        or not isinstance(donnees.get("graphe"), dict)
        or not isinstance(donnees.get("questions"), list)
        or not isinstance(donnees.get("lecons"), list)
    ):
        raise _refus(f"schéma {SCHEMA_CORPUS}, « fictif: true », graphe, questions et leçons")
    noeuds = set()
    for n in donnees["graphe"].get("noeuds", []):
        if n.get("type") not in schema.TYPES_NOEUD or not (n.get("nom") or n.get("cle")):
            raise _refus(f"nœud mal formé : {n}")
        noeuds.add(f"{n['type']}:{n.get('nom') or n.get('cle')}")
    ids_aretes = set()
    for a in donnees["graphe"].get("aretes", []):
        if (
            a["id"] in ids_aretes
            or a["de"] not in noeuds
            or a["vers"] not in noeuds
            or a["etat"] not in schema.ETATS
            or a["type"] not in schema.TYPES_ARETE
            or (a["etat"] == "fermee") != ("valide_a" in a)
        ):
            raise _refus(f"arête mal formée ou en double : {a.get('id')}")
        ids_aretes.add(a["id"])
    ids = set()
    for q in donnees["questions"]:
        plan = q.get("plan", {})
        if (
            q["id"] in ids
            or q.get("categorie") not in CATEGORIES
            or plan.get("operation") not in OPERATIONS
            or not isinstance(q.get("attendu"), dict)
        ):
            raise _refus(f"question mal formée ou en double : {q.get('id')}")
        ids.add(q["id"])
        refs = [plan.get(c) for c in ("depart", "de", "vers") if plan.get(c)]
        if any(r not in noeuds and not q["attendu"].get("abstention") for r in refs):
            raise _refus(f"{q['id']} : un nœud du plan n'est pas déclaré (sauf pour une abstention attendue)")
        for e in plan.get("etapes", []):
            if (
                e.get("arete") not in schema.TYPES_ARETE
                or e.get("sens") not in _SENS
                or e.get("type_noeud") not in schema.TYPES_NOEUD
            ):
                raise _refus(f"{q['id']} : étape mal formée")
        if plan["operation"] == "pourquoi" and plan.get("arete") not in ids_aretes:
            raise _refus(f"{q['id']} : arête inconnue")
    return donnees


def _ref(cle: str) -> NoeudRef:
    type_noeud, _, nom = cle.partition(":")
    return NoeudRef(type_noeud, pseudonyme(nom) if type_noeud in PERSONNES else nom)


class Banc:
    """Un moteur chargé du graphe du corpus : les identifiants d'arêtes et les noms lisibles des nœuds (le pseudonyme
    d'un client ou d'une propriété ne se lit pas ; le banc le traduit en nom du corpus)."""

    def __init__(self, moteur: MoteurGraphe, ids: Mapping[str, str], noms: Mapping[str, str]) -> None:
        self.moteur, self.ids, self.noms = moteur, ids, noms

    def nom(self, type_noeud: str, cle: str) -> str:
        return f"{type_noeud}:{self.noms.get(cle, cle)}"


def construire_graphe(moteur: MoteurGraphe, corpus: Mapping[str, Any]) -> Banc:
    """Écrit le graphe du corpus par l'API publique du moteur et rend le banc."""
    noms: dict[str, str] = {}
    for n in corpus["graphe"]["noeuds"]:
        nom = n.get("nom") or n["cle"]
        ref = _ref(f"{n['type']}:{nom}")
        noms[ref.cle] = nom
        moteur.poser_noeud(ref.type, ref.cle, None, source_ref="test:corpus-fictif", par="banc-de-mesure", quand=QUAND)
    ids: dict[str, str] = {}
    for a in corpus["graphe"]["aretes"]:
        de, vers = _ref(a["de"]), _ref(a["vers"])
        prefixe = a["source"].split(":")[0]
        p = moteur.proposer_arete(
            DemandeArete(
                type=a["type"],
                de=de,
                vers=vers,
                valide_de=a["valide_de"],
                origine="bus" if prefixe == "bus" else "agent",
                source_type=f"corpus:{prefixe}",
                source_ref=a["source"],
            ),
            par="banc-de-mesure",
            quand=QUAND,
        )
        ids[a["id"]] = p.arete.arete_id
        humain = {"par": "direction.fictive", "mode": "humain", "role": "admin"}
        systeme = {"par": "banc-de-mesure", "mode": "systeme", "role": None}
        if a["etat"] in ("confirmee", "fermee"):
            moteur.confirmer_arete(
                p.arete.arete_id,
                raison="corpus de mesure fictif",
                quand=QUAND,
                **(humain if p.arete.sensible else systeme),
            )
        if a["etat"] == "fermee":
            moteur.fermer_arete(
                p.arete.arete_id, a["valide_a"], raison="fin de validité du corpus", quand=QUAND, **humain
            )
        if a["etat"] == "rejetee":
            moteur.rejeter_arete(p.arete.arete_id, raison="arête erronée du corpus", quand=QUAND, **humain)
    return Banc(moteur, ids, noms)


# -- exécution d'un plan
# ----------------------------------------------------------------------------------------------------
def _pas_a_pas(banc: Banc, plan: Mapping[str, Any]) -> set[str]:
    moteur = banc.moteur
    courants = {_ref(plan["depart"])}
    brouillons = bool(plan.get("inclure_brouillons"))
    for etape in plan["etapes"]:
        suivants: set[NoeudRef] = set()
        for ref in courants:
            v = moteur.voisinage(
                ref, 1, a_la_date=plan["a_la_date"], types_arete=[etape["arete"]], inclure_brouillons=brouillons
            )
            for a in v.aretes:
                sortant, entrant = (
                    a.de.type == ref.type and a.de.cle == ref.cle,
                    a.vers.type == ref.type and a.vers.cle == ref.cle,
                )
                if etape["sens"] == "sortant" and sortant:
                    autre = a.vers
                elif etape["sens"] == "entrant" and entrant:
                    autre = a.de
                elif etape["sens"] == "les_deux":
                    autre = a.vers if sortant else a.de
                else:
                    continue
                if autre.type == etape["type_noeud"]:
                    suivants.add(NoeudRef(autre.type, autre.cle))
        courants = suivants
    return {banc.nom(r.type, r.cle) for r in courants}


def _atteignables(banc: Banc, plan: Mapping[str, Any]) -> set[str]:
    v = banc.moteur.voisinage(
        _ref(plan["depart"]),
        plan["k"],
        a_la_date=plan["a_la_date"],
        inclure_brouillons=bool(plan.get("inclure_brouillons")),
    )
    return {banc.nom(n.type, n.cle) for n, d in v.noeuds if d >= 1 and n.type == plan["type_noeud"]}


def _un_saut(banc: Banc, plan: Mapping[str, Any]) -> set[str]:
    """Le témoin : le voisinage immédiat du départ, filtré sur le type attendu à l'arrivée, sans parcours."""
    cible = plan["etapes"][-1]["type_noeud"] if plan["operation"] == "pas_a_pas" else plan.get("type_noeud")
    if cible is None:
        return set()
    v = banc.moteur.voisinage(
        _ref(plan["depart"]), 1, a_la_date=plan["a_la_date"], inclure_brouillons=bool(plan.get("inclure_brouillons"))
    )
    return {banc.nom(n.type, n.cle) for n, d in v.noeuds if d == 1 and n.type == cible}


def _executer(banc: Banc, plan: Mapping[str, Any], mode: str) -> dict[str, Any]:
    """Rend `{abstention}` | `{entites}` | `{longueur}` | `{aucun_chemin}` | `{texte}`. Un refus typé du moteur est
    une abstention."""
    try:
        if plan["operation"] == "pourquoi":
            return {"texte": banc.moteur.pourquoi(banc.ids[plan["arete"]])["explication"]}
        if plan["operation"] == "chemin":
            if mode == "un_saut":
                voisins = _un_saut(
                    banc,
                    {
                        "operation": "atteignables",
                        "depart": plan["de"],
                        "a_la_date": plan["a_la_date"],
                        "type_noeud": plan["vers"].split(":")[0],
                    },
                )
                return {"longueur": 1} if plan["vers"] in voisins else {"aucun_chemin": True}
            c = banc.moteur.chemin(_ref(plan["de"]), _ref(plan["vers"]), a_la_date=plan["a_la_date"])
            return {"aucun_chemin": True} if c is None else {"longueur": c.longueur}
        if mode == "un_saut":
            return {"entites": sorted(_un_saut(banc, plan))}
        brut = _pas_a_pas(banc, plan) if plan["operation"] == "pas_a_pas" else _atteignables(banc, plan)
        return {"entites": sorted(brut)}
    except ErreurMnemo as exc:
        if exc.code in (codes.NOEUD_INCONNU, codes.ARETE_INCONNUE):
            return {"abstention": True, "code": exc.code}
        raise


def _noter(attendu: Mapping[str, Any], obtenu: Mapping[str, Any]) -> dict[str, Any]:
    if attendu.get("abstention"):
        ok = bool(obtenu.get("abstention"))
        return {"exact": ok, "abstention_attendue": True, "reponse_inventee": not ok, "precision": None, "rappel": None}
    if obtenu.get("abstention"):
        return {
            "exact": False,
            "abstention_attendue": False,
            "abstention_a_tort": True,
            "precision": None,
            "rappel": Decimal(0) if attendu.get("entites") else None,
        }
    if "entites" in attendu:
        voulu, vu = set(attendu["entites"]), set(obtenu.get("entites", ()))
        inter = len(voulu & vu)
        precision = Decimal(inter) / Decimal(len(vu)) if vu else (Decimal(1) if not voulu else Decimal(0))
        rappel = Decimal(inter) / Decimal(len(voulu)) if voulu else (Decimal(1) if not vu else Decimal(0))
        return {
            "exact": voulu == vu,
            "precision": precision,
            "rappel": rappel,
            "reponse_inventee": False,
            "attendu": sorted(voulu),
            "obtenu": sorted(vu),
        }
    if "longueur" in attendu:
        return {
            "exact": obtenu.get("longueur") == attendu["longueur"],
            "precision": None,
            "rappel": None,
            "reponse_inventee": False,
        }
    if attendu.get("aucun_chemin"):
        return {"exact": bool(obtenu.get("aucun_chemin")), "precision": None, "rappel": None, "reponse_inventee": False}
    texte = obtenu.get("texte", "")
    manquants = [m for m in attendu["contient"] if m not in texte]
    return {
        "exact": not manquants,
        "manquants": manquants,
        "precision": None,
        "rappel": None,
        "reponse_inventee": False,
    }


def _moyenne(valeurs: Sequence[Decimal]) -> str | None:
    return None if not valeurs else str((sum(valeurs) / len(valeurs)).quantize(Decimal("0.0001")))


def _bloc(resultats: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(resultats)
    return {
        "questions": n,
        "exactes": sum(1 for r in resultats if r["note"]["exact"]),
        "exactitude": None
        if not n
        else str((Decimal(sum(1 for r in resultats if r["note"]["exact"])) / n).quantize(Decimal("0.0001"))),
        "rappel_moyen": _moyenne([r["note"]["rappel"] for r in resultats if r["note"].get("rappel") is not None]),
        "precision_moyenne": _moyenne(
            [r["note"]["precision"] for r in resultats if r["note"].get("precision") is not None]
        ),
        "abstentions_correctes": sum(
            1 for r in resultats if r["note"].get("abstention_attendue") and r["note"]["exact"]
        ),
        "abstentions_attendues": sum(1 for r in resultats if r["note"].get("abstention_attendue")),
        "reponses_inventees": sum(1 for r in resultats if r["note"].get("reponse_inventee")),
        "abstentions_a_tort": sum(1 for r in resultats if r["note"].get("abstention_a_tort")),
    }


def mesurer_graphe(
    corpus: Mapping[str, Any], moteur: MoteurGraphe, *, modes: Sequence[str] = ("graphe", "un_saut")
) -> dict[str, Any]:
    banc = construire_graphe(moteur, corpus)
    par_mode: dict[str, Any] = {}
    detail: dict[str, list[dict[str, Any]]] = {}
    for mode in modes:
        resultats = []
        for q in corpus["questions"]:
            obtenu = _executer(banc, q["plan"], mode)
            resultats.append(
                {"id": q["id"], "categorie": q["categorie"], "obtenu": obtenu, "note": _noter(q["attendu"], obtenu)}
            )
        detail[mode] = resultats
        par_mode[mode] = {
            "global": _bloc(resultats),
            "par_categorie": {
                c: _bloc([r for r in resultats if r["categorie"] == c])
                for c in CATEGORIES
                if any(r["categorie"] == c for r in resultats)
            },
            "echecs": [
                {"id": r["id"], "obtenu": r["obtenu"], "attendu": r["note"].get("attendu")}
                for r in resultats
                if not r["note"]["exact"]
            ],
        }
    return {"modes": par_mode, "_detail": detail}


# -- leçons
# --------------------------------------------------------------------------------------------------------------------
def _ecarts_depuis_spec(cas: Mapping[str, Any]) -> list[lecons.Ecart]:
    groupe = "marge" if cas["genre"] == "ecart_marge" else "mat-a"
    sortie, debut = [], 0
    for seg in cas["segments"]:
        for i in range(debut, debut + seg["n"]):
            prevu = Decimal(1000 if cas["genre"] == "ecart_marge" else 10 + i)
            facteur = Decimal(seg["facteur"])
            if cas.get("test_facteur") and lecons.cote(f"W-{i:03d}") == "test":
                facteur = Decimal(cas["test_facteur"])
            sortie.append(
                lecons.Ecart(
                    f"W-{i:03d}",
                    groupe,
                    prevu,
                    (prevu * facteur).quantize(Decimal("0.01")),
                    f"{i + 1:064x}",
                    "2026-10-01T09:00:00+00:00",
                    cas.get("unite") if cas["genre"] == "ecart_materiau" else None,
                )
            )
        debut += seg["n"]
    for j, ab in enumerate(cas.get("aberrants", [])):
        sortie.append(
            lecons.Ecart(
                f"W-9{j:02d}",
                groupe,
                Decimal(ab["prevu"]),
                Decimal(ab["reel"]),
                f"{900 + j:064x}",
                "2026-10-01T09:00:00+00:00",
                cas.get("unite") if cas["genre"] == "ecart_materiau" else None,
            )
        )
    return sortie


def mesurer_lecons(
    corpus: Mapping[str, Any], *, garde: Callable[[str, str], dict[str, Any]], registre_factory: Callable[[], Any]
) -> dict[str, Any]:
    """Rejoue chaque cas du corpus dans un registre neuf : extraction, évaluation, verdict comparé à l'attendu."""
    resultats = []
    for cas in corpus["lecons"]:
        registre = registre_factory()
        ecarts = _ecarts_depuis_spec(cas)
        mat = ecarts if cas["genre"] == "ecart_materiau" else []
        mar = ecarts if cas["genre"] == "ecart_marge" else []
        bilan = lecons.extraire(
            registre,
            ecarts_mat=mat,
            ecarts_mar=mar,
            refus=[],
            rejets=[],
            par="banc-de-mesure",
            horodatage="2026-10-02T09:00:00+00:00",
        )
        attendu, obtenu = cas["attendu"], {"lecon": bool(bilan["proposees"])}
        ok = obtenu["lecon"] == attendu["lecon"]
        if not obtenu["lecon"]:
            raison = bilan["sans_lecon"][0]["raison"] if bilan["sans_lecon"] else None
            obtenu["raison"] = raison
            ok = ok and raison == attendu.get("raison")
        else:
            [ident] = bilan["proposees"]
            lecons.evaluer_mesure(
                registre, ident, ecarts_mat=mat, ecarts_mar=mar, horodatage="2026-10-03T09:00:00+00:00"
            )
            lc = lecons.etat(registre).lecons[ident]
            lecons.enregistrer_garde(
                registre,
                ident,
                garde(lc["cible"], lc["texte_agent"]),
                empreinte_garde="banc",
                horodatage="2026-10-03T09:00:00+00:00",
            )
            evaluation = lecons.verdict_evaluation(lecons.etat(registre), ident, "banc")
            parametre = Decimal(registre.lire()[0]["contenu"]["parametre"])
            obtenu.update(
                parametre=str(parametre),
                promouvable=evaluation["promouvable"],
                raisons=evaluation["raisons"],
                mesure=evaluation["mesure"],
            )
            if "parametre_entre" in attendu:
                lo, hi = (Decimal(x) for x in attendu["parametre_entre"])
                ok = ok and lo <= parametre <= hi
            if attendu.get("parametre_negatif"):
                ok = ok and parametre < 0
            ok = ok and evaluation["promouvable"] == attendu["promouvable"]
            if "raison_evaluation" in attendu:
                ok = ok and attendu["raison_evaluation"] in evaluation["raisons"]
        resultats.append({"id": cas["id"], "conforme": ok, "attendu": attendu, "obtenu": obtenu})
    return {"cas": len(resultats), "conformes": sum(1 for r in resultats if r["conforme"]), "resultats": resultats}


def executer(
    corpus: Mapping[str, Any],
    moteur_sql: MoteurGraphe,
    *,
    garde: Callable[[str, str], dict[str, Any]],
    registre_factory: Callable[[], Any],
) -> dict[str, Any]:
    """Rapport `opsys.mnemo.mesure/v1`. Le moteur SQL fait foi ; le double rejoue les mêmes questions : s'ils
    divergent, le
    rapport le dit (`moteurs_concordent: false`) et c'est un défaut."""
    corpus = charger_corpus(corpus)
    sql = mesurer_graphe(corpus, moteur_sql)
    memoire = mesurer_graphe(corpus, GrapheMemoire())
    concordent = sql["_detail"] == memoire["_detail"]
    sql.pop("_detail")
    memoire.pop("_detail")
    return {
        "type": "MESURE_MNEMO",
        "schema": SCHEMA_RAPPORT,
        "corpus_version": corpus["version"],
        "modele_reel": False,
        "graphe": {
            "moteur": "sql-natif",
            **sql,
            "moteurs_concordent": concordent,
            "questions_par_categorie": {
                c: sum(1 for q in corpus["questions"] if q["categorie"] == c) for c in CATEGORIES
            },
        },
        "lecons": mesurer_lecons(corpus, garde=garde, registre_factory=registre_factory),
        "avertissement": (
            "Aucun modèle de langage : les plans de questions sont écrits à la main, le corpus est petit et "
            "fictif. Ces chiffres valident le moteur et le schéma ; ils ne disent rien de la compréhension "
            "du français ni de la qualité d'un agent."
        ),
    }


def markdown(rapport: Mapping[str, Any]) -> str:
    g = rapport["graphe"]
    lignes = [
        f"# Mesure de Mnémo — corpus {rapport['corpus_version']}",
        "",
        f"> {rapport['avertissement']}",
        "",
        "## Graphe (questions multi-sauts)",
        "",
        f"Moteurs SQL natif et double concordants : **{'oui' if g['moteurs_concordent'] else 'NON'}**.",
        "",
        "| Mode | Questions | Exactes | Exactitude | Rappel moyen | Précision moyenne | Abstentions correctes | "
        "Réponses inventées |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mode, bloc in g["modes"].items():
        b = bloc["global"]
        lignes.append(
            f"| {mode} | {b['questions']} | {b['exactes']} | {b['exactitude']} | {b['rappel_moyen']} | "
            f"{b['precision_moyenne']} | {b['abstentions_correctes']}/{b['abstentions_attendues']} | "
            f"{b['reponses_inventees']} |"
        )
    lignes += ["", "### Par catégorie (mode graphe)", "", "| Catégorie | Questions | Exactitude |", "|---|---|---|"]
    for cat, b in g["modes"]["graphe"]["par_categorie"].items():
        lignes.append(f"| {cat} | {b['questions']} | {b['exactitude']} |")
    lignes += [
        "",
        "## Leçons (cas de garde)",
        "",
        f"{rapport['lecons']['conformes']}/{rapport['lecons']['cas']} cas conformes.",
        "",
    ]
    for r in rapport["lecons"]["resultats"]:
        lignes.append(f"- `{r['id']}` : {'conforme' if r['conforme'] else '**NON CONFORME**'}")
    return "\n".join(lignes) + "\n"
