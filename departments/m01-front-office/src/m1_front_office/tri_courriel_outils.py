"""Tri des courriels de M1 (M1.6) et boucle d'apprentissage (M1.13) : l'adaptateur entre le code pur et la plateforme.

Ce module lit le registre de M1 (courriels reçus par les connecteurs, texte déjà neutralisé), appelle le tri pur
(`tri_courriel`), écrit son résultat dans un registre append-only DISTINCT (`tri_courriel`) et publie l'aiguillage au
bus (`m1.courriel_aiguille`). Il ne fait AUCUNE action externe : une plainte ouvre un transfert interne (le registre de
plaintes existant de M1), jamais un message. Les règles qui décident sont `JEU_V1` plus les promotions humaines du
registre `apprentissage` (voir `apprentissage.py`) ; aucune règle apprise n'est active sans une décision de personne.

Outils : lecture (N0), tri et propositions (N2, autonomes), décisions humaines (N3 : correction d'une classe, retour sur
un brouillon, promotion canari/complète/retour arrière) refusées à un agent seul (`outils._acteur_humain`).
"""

from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path
from typing import Any

from opsys import evenements, stockage
from opsys.courriel_connecteurs import envoi
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.outils import Autonomie, Niveau, Outil

from . import apprentissage as ap
from . import gabarits as gb
from . import horodatage as controle_horodatage
from . import outils as _o
from . import tri_courriel as tri
from . import tri_extraction as extraction
from .registre import TYPE_RECU_COURRIEL
from .tri_regles import CLASSES

DEPARTEMENT = "m01-front-office"
REGISTRE_TRI = "tri_courriel"
REGISTRE_APPRENTISSAGE = "apprentissage"
TYPE_TRI = "tri_courriel_v1"
TYPE_AIGUILLE = "m1.courriel_aiguille"
_EVALS = Path(__file__).resolve().parents[2] / "evals"
CORPUS_DE_GARDE = ("tri-courriel-dev.v1.json", "tri-courriel-test.v1.json")
_PAGE_MAX = 25


def _reg(nom: str) -> Any:
    return stockage.maillons(DEPARTEMENT, nom)


def _cnx() -> Any:
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise ValueError("REJ-M1-TRI-BASE: le tri vit dans la base de l'instance (appel dans une transaction d'outil)")
    return cnx


def _refus(code: str, detail: str) -> Any:
    """Un refus typé : `ValueError("CODE: détail")`, que le répartiteur d'outils rend en refus métier (même idiome que
    `courriel_outils`). Ne rend jamais : l'agent lit le code et corrige."""
    raise ValueError(f"{code}: {detail}")


def _horodatage_valide(horodatage: str) -> str:
    quand = _o._horodatage_faisant_foi(horodatage)
    controle_horodatage.valider_horodatage(quand)
    return quand


# ---------------------------------------------------------------------------------------------------- lecture
def _lignes_m1() -> list[dict[str, Any]]:
    return _o._obtenir_registre().lire()


def _reception(lignes: list[dict[str, Any]], signal_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    recue = next(
        (x for x in lignes if x.get("type_entree") == TYPE_RECU_COURRIEL and x.get("signal_id") == signal_id), None
    )
    signal = next((x for x in lignes if x.get("type_entree") == "signal" and x.get("signal_id") == signal_id), None)
    return (recue, signal) if recue is not None and signal is not None else None


def _corps_du_signal(contenu_filtre: str, objet: str) -> str:
    """Le contenu rangé est « objet\\ncorps » (reception.preparer) : l'objet est retiré pour ne compter qu'une fois."""
    if objet and objet.strip() and contenu_filtre.startswith(objet.strip() + "\n"):
        return contenu_filtre[len(objet.strip()) + 1 :]
    return contenu_filtre


_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
_MESSAGERIES_PUBLIQUES = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "yahoo.ca",
        "icloud.com",
        "me.com",
        "aol.com",
        "protonmail.com",
        "proton.me",
        "videotron.ca",
        "bell.net",
        "sympatico.ca",
        "cgocable.ca",
    }
)


def domaines_internes() -> tuple[str, ...]:
    """Les domaines de l'entreprise déclarés à `department.yaml/configuration/domaines_internes`. Vide par défaut :
    aucun
    courriel n'est alors « interne ». Une messagerie publique est écartée : elle ne prouve aucune appartenance."""
    import yaml

    try:
        brut = (
            (yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {})
            .get("configuration", {})
            .get("domaines_internes", [])
        )
    except (OSError, yaml.YAMLError, AttributeError):
        return ()
    if not isinstance(brut, list):
        return ()
    valides = {
        d.strip().lower()
        for d in brut
        if isinstance(d, str)
        and re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", d.strip().lower())
    }
    return tuple(sorted(valides - _MESSAGERIES_PUBLIQUES))


def _domaines() -> tuple[str, ...]:
    return domaines_internes()


def _a_trier(recue: dict[str, Any], signal: dict[str, Any]) -> tri.CourrielATrier:
    auth = recue.get("authentification") or {}
    return tri.CourrielATrier(
        objet=recue.get("objet") or "",
        corps=_corps_du_signal(signal.get("contenu_filtre", ""), recue.get("objet") or ""),
        expediteur=recue.get("expediteur") or "",
        spf=auth.get("spf", "absent"),
        dkim=auth.get("dkim", "absent"),
        dmarc=auth.get("dmarc", "absent"),
        nb_pieces=int(recue.get("nb_pieces") or 0),
        neutralise=bool(recue.get("neutralise")),
        domaines_entreprise=_domaines(),
        auth_fiable=bool(auth.get("fiable")),
    )


def etat_apprentissage() -> ap.EtatApprentissage:
    return ap.etat(_reg(REGISTRE_APPRENTISSAGE))


def _lignes_tri() -> list[dict[str, Any]]:
    return [m for m in _reg(REGISTRE_TRI) if m.get("type_entree") == TYPE_TRI]


# --------------------------------------------------------------------------------------------------- le tri
def trier(signal_id: str) -> dict[str, Any]:
    """Trie UN courriel reçu. Idempotent par (signal, empreinte des règles) : retrier avec les mêmes règles ne
    réécrit ni ne republie rien. Aucun effet externe."""
    lignes = _lignes_m1()
    trouve = _reception(lignes, signal_id)
    if trouve is None:
        return _refus("REJ-M1-TRI-INCONNU", "aucun courriel reçu sous ce signal_id")
    recue, signal = trouve
    e = etat_apprentissage()
    jeu, canari = ap.jeu_pour(signal_id, e)
    courriel = _a_trier(recue, signal)
    r = tri.classer(courriel, jeu)
    existant = next(
        (
            m
            for m in reversed(_lignes_tri())
            if m["signal_id"] == signal_id and m["resultat"]["empreinte_regles"] == r.empreinte_regles
        ),
        None,
    )
    if existant is not None:
        return {"accepte": True, "resultat": {**existant["resultat"], "deja_trie": True, "canari": existant["canari"]}}
    ombre = None
    if canari:
        o = tri.classer(courriel, e.jeu_actif)
        ombre = {"classe": o.classe, "version_regles": o.version_regles, "confiance": o.confiance}
    transfert = None
    if r.classe == "plainte":
        transfert = _ouvrir_transfert_plainte(recue)
    faits = extraction.faits(
        recue.get("objet") or "",
        _corps_du_signal(signal.get("contenu_filtre", ""), recue.get("objet") or ""),
        recue.get("expediteur") or "",
    )
    ligne = {
        "type_entree": TYPE_TRI,
        "horodatage": recue["horodatage"],
        "signal_id": signal_id,
        "compte_id": recue["compte_id"],
        "resultat": r.vers_json(),
        "canari": canari,
        "ombre": ombre,
        "transfert": transfert,
    }
    _reg(REGISTRE_TRI).append(ligne)
    _publier(recue, r, faits, canari, courriel)
    return {
        "accepte": True,
        "resultat": {**r.vers_json(), "deja_trie": False, "canari": canari, "ombre": ombre, "transfert": transfert},
    }


def _ouvrir_transfert_plainte(recue: dict[str, Any]) -> dict[str, Any]:
    """Une plainte reconnue par le tri ouvre un transfert INTERNE (registre de plaintes de M1). Rien n'est envoyé."""
    try:
        reponse = _o.escalader_plainte("autre", "courriel", recue["expediteur"])
    except ValueError as exc:
        return {"statut": "non_ouvert", "code": str(exc)[:120]}
    if not reponse.get("accepte"):
        return {"statut": "non_ouvert", "code": (reponse.get("verdict") or {}).get("code", "REJ-M1-TRI-TRANSFERT")}
    resultat = reponse["resultat"]
    return {
        "statut": "deja_ouvert" if resultat.get("deja_ouvert") else "ouvert",
        "transfert_id": resultat["transfert"]["transfert_id"],
    }


def _publier(
    recue: dict[str, Any], r: tri.ResultatTri, faits: dict[str, Any], canari: bool, courriel: tri.CourrielATrier
) -> None:
    if not _o._stockage_durable_actif:
        return
    # Les faits n'accompagnent que les classes que M5 et M6 consomment : le reste ne fait circuler aucune extraction.
    pour_fournisseur = r.classe in ("facture_fournisseur", "confirmation_fournisseur", "commande_materiaux")
    vides = {"jetons_reference": [], "references_po": [], "lignes": [], "etat_annonce": [], "dates_annoncees": []}

    def charge(corps: dict[str, Any]) -> dict[str, Any]:
        return {
            "signal_id": recue["signal_id"],
            "compte_id": recue["compte_id"],
            "classe": r.classe,
            "confiance": r.confiance,
            "aiguillage": r.aiguillage,
            "revue_humaine": r.revue_humaine,
            "motifs_revue": list(r.motifs_revue),
            "regles": [x.identifiant for x in r.raisons][:40],
            "version_regles": r.version_regles[:120],
            "canari": canari,
            "nb_pieces": int(recue.get("nb_pieces") or 0),
            "recu_le": recue["horodatage"],
            **corps,
            "expediteur_empreinte": faits["expediteur_empreinte"],
            "authentification_complete": tri.auth_complete(courriel),
        }

    identifiant = (
        "m1-aiguille-" + hashlib.sha256(recue["signal_id"].encode()).hexdigest()[:24] + "-" + r.empreinte_regles[:8]
    )
    corps = {**vides, **{k: faits[k] for k in vides}} if pour_fournisseur else vides
    try:
        evenements.publier(TYPE_AIGUILLE, DEPARTEMENT, charge(corps), evenement_id=identifiant)
    except evenements.ChargeInvalide:
        # Une extraction que le schéma refuse ne doit jamais empêcher l'aiguillage : le courriel est aiguillé SANS faits
        # (la personne qui reprend le dossier lit le courriel), jamais perdu.
        if corps is vides:
            raise
        evenements.publier(TYPE_AIGUILLE, DEPARTEMENT, charge(vides), evenement_id=identifiant)


def recevoir_courriel_recu(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur de `m1.courriel_recu` : le tri suit la réception, dans la transaction du répartiteur. Un échec
    (base, registre) lève : le répartiteur réessaie, puis met en quarantaine ; rien n'est perdu en silence."""
    reponse = trier(charge["signal_id"])
    if not reponse.get("accepte"):
        raise ValueError(f"{reponse['verdict']['code']}: tri impossible pour {charge['signal_id']}")
    r = reponse["resultat"]
    return {"classe": r["classe"], "aiguillage": r["aiguillage"], "deja_trie": r["deja_trie"]}


# --------------------------------------------------------------------------------------------------- lectures
def lire_tri_courriel(
    signal_id: str | None = None,
    classe: str | None = None,
    revue_seulement: bool = False,
    depart: int = 0,
    limite: int = 10,
) -> dict[str, Any]:
    if type(depart) is not int or depart < 0 or type(limite) is not int or not 1 <= limite <= _PAGE_MAX:
        return _refus("REJ-M1-TRI-PAGINATION", f"depart ≥ 0, limite de 1 à {_PAGE_MAX}")
    if classe is not None and classe not in CLASSES:
        return _refus("REJ-M1-TRI-CLASSE", f"classe parmi {', '.join(CLASSES)}")
    derniers: dict[str, dict[str, Any]] = {}
    for m in _lignes_tri():
        derniers[m["signal_id"]] = m
    choisis = [
        m
        for m in reversed(list(derniers.values()))
        if (signal_id is None or m["signal_id"] == signal_id)
        and (classe is None or m["resultat"]["classe"] == classe)
        and (not revue_seulement or m["resultat"]["revue_humaine"])
    ]
    page = choisis[depart : depart + limite]
    return {
        "accepte": True,
        "resultat": {
            "tris": [
                {
                    "signal_id": m["signal_id"],
                    "recu_le": m["horodatage"],
                    "canari": m["canari"],
                    "transfert": m["transfert"],
                    **{
                        k: m["resultat"][k]
                        for k in (
                            "classe",
                            "confiance",
                            "aiguillage",
                            "revue_humaine",
                            "motifs_revue",
                            "raisons",
                            "version_regles",
                            "deuxieme_classe",
                        )
                    },
                }
                for m in page
            ],
            "total": len(choisis),
            "depart": depart,
            "suivant": depart + limite if depart + limite < len(choisis) else None,
            "avertissement": "Classement automatique, indicatif : une personne relit quand revue_humaine est vrai.",
        },
    }


def _charger_garde() -> list[dict[str, Any]]:
    cas: list[dict[str, Any]] = []
    for nom in CORPUS_DE_GARDE:
        chemin = _EVALS / nom
        if not chemin.is_file():
            raise ValueError(
                f"REJ-M1-APPR-CORPUS-ABSENT: corpus de garde introuvable ({nom}) : aucune mesure, aucune promotion"
            )
        cas.extend(tri.charger_corpus(chemin)["cas"])
    return cas


def evaluer_tri_courriel(partition: str = "dev") -> dict[str, Any]:
    """Mesure les règles ACTIVES sur le corpus d'évaluation FICTIF (précision et rappel par classe)."""
    if partition not in ("dev", "test", "toutes"):
        return _refus("REJ-M1-TRI-PARTITION", "partition parmi dev, test, toutes")
    try:
        if partition == "toutes":
            cas = _charger_garde()
        else:
            cas = tri.charger_corpus(_EVALS / f"tri-courriel-{partition}.v1.json")["cas"]
    except (OSError, ValueError) as exc:
        return _refus("REJ-M1-APPR-CORPUS-ABSENT", str(exc)[:160])
    jeu = etat_apprentissage().jeu_actif
    rapport = tri.evaluer(cas, jeu)
    return {
        "accepte": True,
        "resultat": {
            "partition": partition,
            "corpus_fictif": True,
            **{
                k: rapport[k]
                for k in (
                    "effectif",
                    "justesse",
                    "f1_macro",
                    "par_classe",
                    "revue_humaine",
                    "injection",
                    "version_regles",
                    "empreinte_regles",
                )
            },
            "erreurs": [{k: e[k] for k in ("id", "attendu", "obtenu", "confiance")} for e in rapport["erreurs"][:50]],
            "limite": "Corpus fictif écrit par deux rédacteurs indépendants ; mesure la cohérence des règles, pas la "
            "performance sur du courrier réel.",
        },
    }


# ------------------------------------------------------------------------------------ retours et propositions
def _humain(nom: str) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    return _o._acteur_humain(nom)


def consigner_correction_tri(signal_id: str, classe_corrigee: str, horodatage: str) -> dict[str, Any]:
    acteur, refus = _humain("m1_consigner_correction_tri")
    if acteur is None:
        return refus or _refus("REJ-HUMAIN-REQUIS", "décision humaine requise")
    if classe_corrigee not in CLASSES:
        return _refus("REJ-M1-APPR-CLASSE", f"classe parmi {', '.join(CLASSES)}")
    derniere = next((m for m in reversed(_lignes_tri()) if m["signal_id"] == signal_id), None)
    trouve = _reception(_lignes_m1(), signal_id)
    if derniere is None or trouve is None:
        return _refus("REJ-M1-APPR-NON-TRIE", "ce courriel n'a pas été trié : rien à corriger")
    quand = _horodatage_valide(horodatage)
    _reg(REGISTRE_APPRENTISSAGE).append(
        {
            "type_entree": ap.TYPE_RETOUR_TRI,
            "horodatage": quand,
            "signal_id": signal_id,
            "classe_attendue": classe_corrigee,
            "classe_obtenue": derniere["resultat"]["classe"],
            "version_regles": derniere["resultat"]["version_regles"],
            "source": ap.pseudonyme_expediteur(trouve[0].get("expediteur") or ""),
            "par": acteur["par"],
            "role": acteur["role"],
            "voie": acteur["voie"],
        }
    )
    return {
        "accepte": True,
        "resultat": {
            "signal_id": signal_id,
            "classe_obtenue": derniere["resultat"]["classe"],
            "classe_corrigee": classe_corrigee,
            "consigne": "Correction consignée. Elle ne change aucune règle : elle sert à PROPOSER une "
            "amélioration, qu'une personne devra promouvoir.",
        },
    }


def consigner_retour_brouillon(
    brouillon_id: str, issue: str, horodatage: str, corps_final: str | None = None, gabarit_id: str | None = None
) -> dict[str, Any]:
    acteur, refus = _humain("m1_consigner_retour_brouillon")
    if acteur is None:
        return refus or _refus("REJ-HUMAIN-REQUIS", "décision humaine requise")
    if issue not in ap.ISSUES_BROUILLON:
        return _refus("REJ-M1-APPR-ISSUE", f"issue parmi {', '.join(ap.ISSUES_BROUILLON)}")
    if (corps_final is not None and (not isinstance(corps_final, str) or len(corps_final) > 20_000)) or (
        gabarit_id is not None and (not isinstance(gabarit_id, str) or len(gabarit_id) > 64)
    ):
        return _refus("REJ-M1-APPR-ARGUMENT", "texte final de 20 000 caractères au plus, gabarit de 64 au plus")
    if gabarit_id is not None and gabarit_id not in gb.GABARITS:
        return _refus("REJ-M1-APPR-GABARIT", f"gabarit parmi {', '.join(sorted(gb.GABARITS))}")
    try:
        brouillon = envoi.lire_brouillon(_cnx(), brouillon_id)
    except ErreurCourriel:
        return _refus("REJ-M1-APPR-BROUILLON", "brouillon inconnu")
    ajoutees: list[str] = []
    ratio = "1.000"
    if issue == "corrige":
        if not corps_final or not corps_final.strip():
            return _refus("REJ-M1-APPR-CORPS", "le texte final est requis pour une correction")
        ratio = f"{difflib.SequenceMatcher(None, brouillon.contenu.corps, corps_final).ratio():.3f}"
        ajoutees = ap.phrases_ajoutees(brouillon.contenu.corps, corps_final)
    quand = _horodatage_valide(horodatage)
    _reg(REGISTRE_APPRENTISSAGE).append(
        {
            "type_entree": ap.TYPE_RETOUR_BROUILLON,
            "horodatage": quand,
            "brouillon_id": brouillon_id,
            "empreinte": brouillon.empreinte,
            "issue": issue,
            "similarite": ratio,
            "gabarit_id": gabarit_id,
            "phrases_ajoutees": ajoutees,
            "par": acteur["par"],
            "role": acteur["role"],
            "voie": acteur["voie"],
        }
    )
    return {
        "accepte": True,
        "resultat": {
            "brouillon_id": brouillon_id,
            "issue": issue,
            "similarite": ratio,
            "phrases_retenues": len(ajoutees),
        },
    }


def _retours_tri_derniers() -> list[dict[str, Any]]:
    derniers: dict[str, dict[str, Any]] = {}
    for m in _reg(REGISTRE_APPRENTISSAGE):
        if m.get("type_entree") == ap.TYPE_RETOUR_TRI:
            derniers[m["signal_id"]] = m
    return list(derniers.values())


def _texte_du_signal(lignes: list[dict[str, Any]], signal_id: str) -> str | None:
    trouve = _reception(lignes, signal_id)
    return (
        None
        if trouve is None
        else (trouve[0].get("objet") or "")
        + "\n"
        + _corps_du_signal(trouve[1].get("contenu_filtre", ""), trouve[0].get("objet") or "")
    )


def proposer_amelioration(genre: str, gabarit_id: str | None = None) -> dict[str, Any]:
    """Calcule (hors ligne, déterministe) une proposition à partir des retours humains et la mesure sur le corpus de
    garde. N'active RIEN : une proposition attend la décision d'une personne."""
    if gabarit_id is not None and (not isinstance(gabarit_id, str) or len(gabarit_id) > 64):
        return _refus("REJ-M1-APPR-ARGUMENT", "gabarit de 64 caractères au plus")
    registre = _reg(REGISTRE_APPRENTISSAGE)
    e = ap.etat(registre)
    if genre == "regle_tri":
        lignes = _lignes_m1()
        exemples = []
        corriges = set()
        for r in _retours_tri_derniers():
            texte = _texte_du_signal(lignes, r["signal_id"])
            if texte is None or r["classe_attendue"] == r["classe_obtenue"]:
                continue
            corriges.add(r["signal_id"])
            exemples.append(ap.ExempleCorrige(r["signal_id"], texte, r["classe_attendue"], r["source"]))
        ailleurs = []
        for m in _lignes_tri():
            if m["signal_id"] in corriges or m["resultat"]["revue_humaine"]:
                continue
            texte = _texte_du_signal(lignes, m["signal_id"])
            if texte is not None:
                ailleurs.append((m["resultat"]["classe"], texte))
        regles = ap.proposer_regles(exemples, e.jeu_actif, ailleurs)
        if not regles:
            return {
                "accepte": True,
                "resultat": {
                    "proposition": None,
                    "exemples": len(exemples),
                    "raison": "aucune expression ne réunit le support, les sources distinctes et la rareté exigés",
                },
            }
        try:
            garde = _charger_garde()
        except ValueError as exc:
            return _refus("REJ-M1-APPR-CORPUS-ABSENT", str(exc)[:160])
        candidat = e.jeu_actif.avec(regles, e.jeu_actif.version + "+cand")
        mesure = ap.mesurer(e.jeu_actif, candidat, garde)
        contenu = {"regles": [r.vers_json() for r in regles], "base": e.jeu_actif.empreinte()}
        pid = ap.identifiant_proposition(genre, contenu)
        fiche = {
            "type_entree": ap.TYPE_PROPOSITION,
            "horodatage": _derniere_heure(lignes),
            "proposition_id": pid,
            "genre": genre,
            "regles": contenu["regles"],
            "base_empreinte": contenu["base"],
            "mesure": mesure,
            "exemples": len(exemples),
        }
    elif genre == "gabarit":
        if gabarit_id not in gb.GABARITS:
            return _refus("REJ-M1-APPR-GABARIT", f"gabarit_id requis, parmi {', '.join(sorted(gb.GABARITS))}")
        ajouts = ap.proposer_ajouts_gabarit([m for m in registre], gabarit_id)
        actifs = set(e.gabarits.get(gabarit_id, ()))
        # Re-contrôle au moment de proposer : un registre altéré ne fait pas passer une phrase que le garde-fou refuse.
        ajouts = [a for a in ajouts if a["phrase"] not in actifs and gb.phrase_admissible(a["phrase"])]
        if not ajouts:
            return {
                "accepte": True,
                "resultat": {"proposition": None, "raison": "aucune phrase ajoutée par au moins trois personnes"},
            }
        meilleur = ajouts[0]
        pid = ap.identifiant_proposition(genre, [gabarit_id, meilleur["phrase"]])
        fiche = {
            "type_entree": ap.TYPE_PROPOSITION,
            "horodatage": _derniere_heure(_lignes_m1()),
            "proposition_id": pid,
            "genre": genre,
            "gabarit_id": gabarit_id,
            "phrase": meilleur["phrase"],
            "support": meilleur["support"],
            "mesure": None,
        }
    else:
        return _refus("REJ-M1-APPR-GENRE", "genre parmi regle_tri, gabarit")
    if pid in e.propositions:
        return {"accepte": True, "resultat": {"proposition": pid, "deja_proposee": True, "etat": e.etats[pid]}}
    registre.append(fiche)
    return {
        "accepte": True,
        "resultat": {
            "proposition": pid,
            "deja_proposee": False,
            "etat": "proposee",
            "mesure": fiche["mesure"],
            "consigne": "Proposition rangée. Rien n'est actif : une personne doit la promouvoir "
            "(m1_decider_proposition).",
        },
    }


def _derniere_heure(lignes: list[dict[str, Any]]) -> str:
    """Pas d'horloge : la proposition est datée du dernier fait connu du registre (ou de l'époque, sans fait)."""
    for x in reversed(lignes):
        h = x.get("horodatage")
        if isinstance(h, str):
            return h
    return "1970-01-01T00:00:00+00:00"


def lire_apprentissage() -> dict[str, Any]:
    registre = list(_reg(REGISTRE_APPRENTISSAGE))
    e = ap.etat(registre)
    return {
        "accepte": True,
        "resultat": {
            "regles_actives": e.jeu_actif.version,
            "empreinte_regles_actives": e.jeu_actif.empreinte(),
            "canari": None if e.canari is None else {"proposition": e.canari[0], "pourcentage": e.canari[2]},
            "propositions": [
                {
                    "proposition_id": pid,
                    "genre": p["genre"],
                    "etat": e.etats[pid],
                    "mesure": p.get("mesure"),
                    "support": p.get("support", p.get("exemples")),
                    "phrase": p.get("phrase"),
                }
                for pid, p in e.propositions.items()
            ],
            "gabarits_actifs": {k: list(v) for k, v in e.gabarits.items()},
            "retours_tri": sum(1 for m in registre if m.get("type_entree") == ap.TYPE_RETOUR_TRI),
            "retours_brouillons": sum(1 for m in registre if m.get("type_entree") == ap.TYPE_RETOUR_BROUILLON),
            "consigne": "Aucune règle apprise n'est active sans décision humaine (canari, promotion, retour arrière).",
        },
    }


def decider_proposition(
    proposition_id: str, etape: str, motif: str, horodatage: str, pourcentage: int | None = None
) -> dict[str, Any]:
    acteur, refus = _humain("m1_decider_proposition")
    if acteur is None:
        return refus or _refus("REJ-HUMAIN-REQUIS", "décision humaine requise")
    if etape not in ap.ETAPES:
        return _refus("REJ-M1-APPR-ETAPE", f"étape parmi {', '.join(ap.ETAPES)}")
    if not isinstance(motif, str) or not 10 <= len(motif.strip()) <= 500:
        return _refus("REJ-M1-APPR-MOTIF", "motif de 10 à 500 caractères requis")
    if etape == "canari" and (type(pourcentage) is not int or not 1 <= pourcentage <= 50):
        return _refus("REJ-M1-APPR-POURCENTAGE", "le canari porte sur 1 à 50 % des courriels")
    if etape != "canari" and pourcentage is not None:
        return _refus("REJ-M1-APPR-POURCENTAGE", "le pourcentage ne vaut que pour le canari")
    registre = _reg(REGISTRE_APPRENTISSAGE)
    try:
        e = ap.etat(registre)
        proposition = e.propositions.get(proposition_id)
        if proposition is None:
            return _refus("REJ-M1-APPR-INCONNUE", "proposition inconnue")
        mesure = None
        if etape in ("canari", "complete") and proposition["genre"] == "regle_tri":
            garde = _charger_garde()
            regles = [ap._regle_depuis_json(r) for r in proposition["regles"]]
            base = e.jeu_actif
            mesure = ap.mesurer(base, base.avec(regles, base.version + "+cand"), garde)
            if not mesure["promouvable"]:
                return _refus(
                    "REJ-M1-APPR-REGRESSION",
                    "la mesure sur le corpus de garde montre une régression : "
                    f"{mesure['regressions'] or 'justesse en baisse'}",
                )
        quand = _horodatage_valide(horodatage)
        ligne = {
            "type_entree": ap.TYPE_DECISION,
            "horodatage": quand,
            "proposition_id": proposition_id,
            "etape": etape,
            "motif": motif.strip(),
            "par": acteur["par"],
            "role": acteur["role"],
            "voie": acteur["voie"],
            "mesure_garde": mesure,
        }
        if pourcentage is not None:
            ligne["pourcentage"] = pourcentage
        ap.etat([*registre, ligne])  # refuse une transition illégale AVANT d'écrire
        registre.append(ligne)
    except ap.RefusApprentissage as exc:
        code, _, detail = str(exc).partition(": ")
        return _refus(code, detail)
    except ValueError as exc:
        if str(exc).startswith("REJ-"):
            raise
        return _refus("REJ-M1-APPR-CORPUS-ABSENT", str(exc)[:160])
    nouveau = ap.etat(registre)
    return {
        "accepte": True,
        "resultat": {
            "proposition_id": proposition_id,
            "etat": nouveau.etats[proposition_id],
            "regles_actives": nouveau.jeu_actif.version,
            "par": acteur["par"],
        },
    }


# ------------------------------------------------------------------------------------------------------ outils
_SIGNAL = {
    "type": "string",
    "minLength": 20,
    "maxLength": 120,
    "description": "Identifiant du courriel reçu (signal_id, « courriel:… »).",
}
_HORO = {"type": "string", "description": "ISO-8601 avec fuseau ; l'heure du serveur fait foi pour un appareil."}


def outils_tri() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m1_trier_courriel",
            description=(
                "Classe un courriel reçu (demande de soumission, plainte, facture ou confirmation de "
                "fournisseur, commande de matériaux, réponse de client, interne, pourriel ou hameçonnage, "
                "autre) par des règles explicables : classe, confiance, règles déclenchées, département "
                "aiguillé. Aucune action externe ; une plainte ouvre un transfert interne. Idempotent."
            ),
            parametres={
                "type": "object",
                "properties": {"signal_id": _SIGNAL},
                "required": ["signal_id"],
                "additionalProperties": False,
            },
            fonction=trier,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_lire_tri_courriel",
            description=(
                "Lit les résultats du tri des courriels (le plus récent d'abord), avec la confiance, les raisons "
                "et si une personne doit relire. Filtres : signal, classe, revue humaine. Lecture."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "signal_id": {**_SIGNAL, "type": ["string", "null"]},
                    "classe": {"type": ["string", "null"], "enum": [*CLASSES, None]},
                    "revue_seulement": {"type": "boolean"},
                    "depart": {"type": "integer", "minimum": 0},
                    "limite": {"type": "integer", "minimum": 1, "maximum": _PAGE_MAX},
                },
                "additionalProperties": False,
            },
            fonction=lire_tri_courriel,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom="m1_evaluer_tri_courriel",
            description=(
                "Mesure les règles de tri actives sur le corpus d'évaluation FICTIF : justesse, précision et "
                "rappel par classe, erreurs. Calcul pur, sans écriture."
            ),
            parametres={
                "type": "object",
                "properties": {"partition": {"type": "string", "enum": ["dev", "test", "toutes"]}},
                "additionalProperties": False,
            },
            fonction=evaluer_tri_courriel,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom="m1_consigner_correction_tri",
            description=(
                "Une PERSONNE corrige la classe d'un courriel trié. Le retour sert à proposer une amélioration "
                "des règles ; il ne change aucune règle. Décision humaine : refusée à un agent seul."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "signal_id": _SIGNAL,
                    "classe_corrigee": {"type": "string", "enum": list(CLASSES)},
                    "horodatage": _HORO,
                },
                "required": ["signal_id", "classe_corrigee", "horodatage"],
                "additionalProperties": False,
            },
            fonction=consigner_correction_tri,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m1_consigner_retour_brouillon",
            description=(
                "Une PERSONNE consigne ce qu'elle a fait d'un brouillon de M1 : accepté, corrigé (avec le "
                "texte final) ou rejeté. Seules la similarité et les phrases ajoutées admissibles sont gardées, "
                "jamais le texte du client. Décision humaine."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "brouillon_id": {"type": "string", "maxLength": 64},
                    "issue": {"type": "string", "enum": list(ap.ISSUES_BROUILLON)},
                    "corps_final": {"type": ["string", "null"], "maxLength": 20000},
                    "horodatage": _HORO,
                    "gabarit_id": {"type": ["string", "null"], "maxLength": 64},
                },
                "required": ["brouillon_id", "issue", "horodatage"],
                "additionalProperties": False,
            },
            fonction=consigner_retour_brouillon,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m1_proposer_amelioration",
            description=(
                "Calcule, hors ligne et de façon déterministe, une PROPOSITION d'amélioration à partir des "
                "retours humains : nouvelles règles de tri (mesurées sur le corpus d'évaluation) ou phrase "
                "de gabarit. N'active rien : une personne doit la promouvoir."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "genre": {"type": "string", "enum": ["regle_tri", "gabarit"]},
                    "gabarit_id": {"type": ["string", "null"], "maxLength": 64},
                },
                "required": ["genre"],
                "additionalProperties": False,
            },
            fonction=proposer_amelioration,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_lire_apprentissage",
            description=(
                "État de la boucle d'apprentissage : règles actives, canari, propositions et leur mesure, "
                "gabarits modifiés, nombre de retours. Lecture."
            ),
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=lire_apprentissage,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom="m1_decider_proposition",
            description=(
                "Une PERSONNE décide d'une proposition d'amélioration : canari (1 à 50 % des courriels), "
                "promotion complète (après un canari), retour arrière ou refus. La mesure sur le corpus de "
                "garde est refaite : une régression bloque. Décision humaine, jamais d'un agent seul."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "proposition_id": {"type": "string", "maxLength": 40},
                    "etape": {"type": "string", "enum": list(ap.ETAPES)},
                    "motif": {"type": "string", "minLength": 10, "maxLength": 500},
                    "horodatage": _HORO,
                    "pourcentage": {"type": ["integer", "null"], "minimum": 1, "maximum": 50},
                },
                "required": ["proposition_id", "etape", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=decider_proposition,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
    )


def consommateurs() -> dict[str, Any]:
    return {"m1.courriel_recu": recevoir_courriel_recu}
