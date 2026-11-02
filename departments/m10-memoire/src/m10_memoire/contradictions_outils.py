"""Outils de M10 pour les contradictions : consigner une affirmation, lire la file, la rafraîchir (routine planifiée),
décider. Adaptateur de `contradictions.py` et `verite.py` (purs).

Cinq outils, aucun droit d'appareil (une personne passe par la file d'approbation de la console) :

- `m10_consigner_affirmation` (T1 / **N2**, agent) : un fait à clé, sourcé (`registre:<nom>:<ligne_id>` qui existe),
  dans le domaine `affaires`. La classe de la source est bornée par l'ordre de vérité : un agent ne peut déclarer
  qu'une classe que l'ordre admet pour le canal `agent` (documentation, journal, mémoire ancienne, hypothèse) ;
- `m10_declarer_affirmation_humaine` (T1 / **N3**, personne) : la voie des classes d'autorité haute dans le domaine
  `affaires` (décision du propriétaire, rapport validé), au nom de la personne qui l'approuve ;
- `m10_lire_contradictions` (T0 / N0) : la file des contradictions d'un domaine (à traiter, ou un état précis) ou les
  affirmations avec leur marque ; lecture seule ;
- `m10_rafraichir_contradictions` (T1 / **N2**, planificateur) : détecte, range, marque, propose ; pour une
  contradiction critique ouvre UNE demande d'approbation (sas existant) dont les arguments sont la proposition de
  l'ordre
  de vérité. `ecrire` faux : calcule à blanc (c'est ce que fait l'ombre). L'écriture est réservée au planificateur
  durable : l'instant vient de SON horloge ;
- `m10_decider_contradiction` (T1 / **N3**, personne) : retenir A, retenir B, coexistence valide, fausse alerte. Une
  décision est définitive ; la mémoire écartée est marquée, jamais supprimée.

Le domaine `developpement` n'a aucune voie d'agent : ses affirmations viennent de l'ingestion de fichiers du dépôt
par une personne authentifiée (`ingestion_projet.py`). Aucune détection ne croise les deux domaines.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select

from opsys import approbations, stockage
from opsys import service_acteur_systeme as systeme
from opsys.mnemo import service
from opsys.mnemo.codes import ErreurMnemo
from opsys.outils import Autonomie, Niveau, Outil
from opsys.secrets_coffre import masquage
from opsys.stockage.concurrence import verrou_consultatif
from opsys.stockage.schema import APPROBATIONS

from . import contradictions, humain, registre, routines, validation, verite
from . import outils as _o

DEPARTEMENT = "m10-memoire"
OUTIL_DECIDER = "m10_decider_contradiction"
DEMANDES_PAR_PASSAGE = 5  # le sas n'est jamais inondé : le reste attend le passage suivant
DEMANDES_OUVERTES_MAX = 20  # au-delà, plus aucune nouvelle demande tant que des personnes n'ont pas décidé
LIMITE_LECTURE_MAX = 20

_REGISTRE_AFFIRMATIONS = registre.Registre(maillons=stockage.maillons(DEPARTEMENT, "affirmations"))
_REGISTRE_CONTRADICTIONS = registre.Registre(maillons=stockage.maillons(DEPARTEMENT, "contradictions"))


def _verdict(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "verdict": validation.construire_verdict(code, detail)}


def _depuis_valeur_erreur(exc: ValueError) -> dict[str, Any]:
    code, _, detail = str(exc).partition(": ")
    return _verdict(code, detail)


def _ordre() -> verite.OrdreVerite:
    return verite.charger()


def _refus_appareil() -> dict[str, Any] | None:
    """Ces outils ne s'ouvrent à aucun appareil : une identité d'appareil arrivée jusqu'ici est refusée."""
    try:
        service.refuser_appareil()
    except ErreurMnemo as exc:
        return _verdict(exc.code, exc.detail)
    return None


_PREFIXE_DE_SECRET = r"(?:sk|pk|ghp|gho|ghu|ghs|ghr|xox[baprs])[-_][A-Za-z0-9_-]{12,}"
_FORME_DE_SECRET = re.compile(_PREFIXE_DE_SECRET)
_SUITE_ALEATOIRE = re.compile(r"[A-Za-z0-9]{32,}")


def secret_dans(valide: dict[str, Any]) -> bool:
    """Un jeton qui ressemble à une clé, un jeton d'accès, un en-tête d'autorisation ou (valeur, attribut) une longue
    suite aléatoire n'entre jamais au registre : une valeur est lue par les agents et reste dans le journal chaîné. Le
    détecteur du coffre exige une frontière de mot ; on ajoute les formes COLLÉES à un préfixe, qu'un jeton de statut
    n'a jamais. Le sujet peut être un identifiant d'affaire (hexadécimal long) : seule la forme à préfixe le vise."""
    for cle in ("sujet", "attribut", "valeur"):
        texte = valide[cle]
        if masquage.contient_secret(texte) or _FORME_DE_SECRET.search(texte):
            return True
        if cle != "sujet" and _SUITE_ALEATOIRE.search(texte):
            return True
    return False


def _connexion_ecriture(verrou: str):
    cnx = stockage.connexion_courante()
    if cnx is None or not cnx.in_transaction():
        raise RuntimeError("REJ-CONTRADICTION-STOCKAGE: une transaction de l'instance est requise")
    verrou_consultatif(cnx, verrou)
    return cnx


def _reference_existe(ref: str) -> bool:
    """`registre:<nom>:<ligne_id>` : la ligne existe-t-elle dans ce registre ? (une affirmation est sourcée)"""
    _, nom, ligne_id = ref.split(":", 2)
    return any(m.get("ligne_id") == ligne_id for m in _o._REGISTRES_NOMMES[nom].lire())


def _ecrire_affirmation(champs: dict[str, Any], canal: str, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        ordre = _ordre()
        valide = contradictions.valider(champs, ordre, canal)
    except ValueError as exc:
        return _depuis_valeur_erreur(exc)
    if secret_dans(valide):
        return _verdict(
            "REJ-AFFIRMATION-SECRET", "un champ ressemble à un secret (clé, jeton, en-tête) ; il n'a rien à faire ici"
        )
    if not _reference_existe(valide["ref"]):
        return _verdict(
            "REJ-AFFIRMATION-REFERENCE-INTROUVABLE",
            "la ligne citée n'existe pas dans ce registre (une affirmation est sourcée)",
        )
    _connexion_ecriture("m10-affirmations")
    instant = service.instant_iso(service.maintenant())
    try:
        prepare = contradictions.preparer(
            contradictions.affirmations(_REGISTRE_AFFIRMATIONS.lire()), valide, instant, ordre
        )
    except ValueError as exc:
        return _depuis_valeur_erreur(exc)
    if prepare["entree"] is None:
        return {"accepte": True, "resultat": {"resultat": "inchangee", "ligne_id": prepare["ligne_id"]}}
    entree = {**prepare["entree"], **(extras or {})}
    ligne_id = _REGISTRE_AFFIRMATIONS.ajouter(entree)
    return {
        "accepte": True,
        "resultat": {
            "resultat": prepare["resultat"],
            "ligne_id": ligne_id,
            "cle": contradictions.cle_de(valide),
            "classe": valide["classe"],
            "suite": "La détection des contradictions se fait au prochain passage planifié "
            "(m10_rafraichir_contradictions).",
        },
    }


def consigner_affirmation(
    domaine: str, sujet: str, attribut: str, valeur: str, classe: str, source_ref: str
) -> dict[str, Any]:
    refus = _refus_appareil()
    if refus is not None:
        return refus
    try:
        emetteur = f"agent:{service.departement_appelant()}"
    except ErreurMnemo as exc:
        return _verdict(exc.code, exc.detail)
    return _ecrire_affirmation(
        {
            "domaine": domaine,
            "sujet": sujet,
            "attribut": attribut,
            "valeur": valeur,
            "classe": classe,
            "ref": source_ref,
            "emetteur": emetteur,
        },
        "agent",
    )


def declarer_affirmation_humaine(
    domaine: str, sujet: str, attribut: str, valeur: str, classe: str, source_ref: str, motif: str
) -> dict[str, Any]:
    acteur, refus = _o._acteur_humain("m10_declarer_affirmation_humaine")
    if acteur is None:
        return refus or _verdict("REJ-HUMAIN-REQUIS", "acteur humain introuvable")
    if not humain.motif_valide(motif):
        return _verdict(
            humain.REJ_HUMAIN_MOTIF_INVALIDE,
            f"le motif est obligatoire : {humain.MOTIF_MIN_CARACTERES} à {humain.MOTIF_MAX_CARACTERES} caractères",
        )
    return _ecrire_affirmation(
        {
            "domaine": domaine,
            "sujet": sujet,
            "attribut": attribut,
            "valeur": valeur,
            "classe": classe,
            "ref": source_ref,
            "emetteur": f"humain:{acteur['par']}",
        },
        "humain",
        {
            "par": acteur["par"],
            "role": acteur["role"],
            "source_decision": acteur["source"],
            "motif": motif.strip(),
        },
    )


# -- la lecture --------------------------------------------------------------------------------------------------
def _statuts_demandes(ids: list[str]) -> dict[str, str]:
    cnx = stockage.connexion_courante()
    if cnx is None or not ids:
        return {}
    return {
        r.id: r.statut
        for r in cnx.execute(select(APPROBATIONS.c.id, APPROBATIONS.c.statut).where(APPROBATIONS.c.id.in_(ids)))
    }


def lire_contradictions(
    domaine: str, vue: str = "contradictions", etat: str = "a_traiter", limite: int = 10, decalage: int = 0
) -> dict[str, Any]:
    refus = _refus_appareil()
    if refus is not None:
        return refus
    if domaine not in verite.domaines():
        return _verdict(contradictions.REJ_DOMAINE, f"domaine parmi {list(verite.domaines())}")
    if vue not in ("contradictions", "affirmations") or (
        etat not in ("a_traiter", "tous", *contradictions.statuts()) and vue == "contradictions"
    ):
        return _verdict("REJ-CONTRADICTION-LECTURE-INVALIDE", "vue : contradictions ou affirmations ; état connu")
    if type(limite) is not int or not 1 <= limite <= LIMITE_LECTURE_MAX or type(decalage) is not int or decalage < 0:
        return _verdict("REJ-CONTRADICTION-LECTURE-INVALIDE", f"limite de 1 à {LIMITE_LECTURE_MAX}, décalage ≥ 0")
    liste = contradictions.affirmations(_REGISTRE_AFFIRMATIONS.lire())
    etats = contradictions.etats(_REGISTRE_CONTRADICTIONS.lire(), contradictions.actives(liste))
    du_domaine = {i: e for i, e in etats.items() if e["domaine"] == domaine}
    ordre = _ordre()
    base = {"domaine": domaine, "vue": vue, "ordre": {"version": ordre.version, "empreinte": ordre.empreinte[:16]}}
    if vue == "affirmations":
        marques = contradictions.marques_effectives(du_domaine)
        elements = [
            {
                "ligne_id": a["ligne_id"],
                "cle": contradictions.cle_de(a),
                "valeur": a["valeur"],
                "classe": a["classe"],
                "emetteur": a["emetteur"],
                "ref": a["ref"],
                "horodatage": a["horodatage"],
                "etat": "active" if a["active"] else ("retiree" if a["retiree"] else "remplacee"),
                "marque": marques.get(a["ligne_id"]),
            }
            for a in liste
            if a["domaine"] == domaine
        ]
        total = len(elements)
        page = elements[decalage : decalage + limite]
        reponse = {
            **base,
            "total": total,
            "affirmations": page,
            "suivant": decalage + limite if decalage + limite < total else None,
        }
        return {"accepte": True, "resultat": service.borner(reponse, ("affirmations",))}
    choisies = [
        e
        for e in du_domaine.values()
        if etat == "tous" or (etat == "a_traiter" and e["statut"] in contradictions.a_traiter()) or e["statut"] == etat
    ]
    choisies.sort(key=lambda e: (not e["critique"], e["horodatage"], e["contradiction_id"]))
    page = choisies[decalage : decalage + limite]
    demandes = _statuts_demandes([e["demande_id"] for e in page if e["demande_id"]])
    elements = [
        {
            **contradictions.vue(e),
            "demande": (
                {"id": e["demande_id"], "statut": demandes.get(e["demande_id"], "inconnu")} if e["demande_id"] else None
            ),
        }
        for e in page
    ]
    reponse = {
        **base,
        "compte": contradictions.compter(du_domaine),
        "total": len(choisies),
        "contradictions": elements,
        "suivant": decalage + limite if decalage + limite < len(choisies) else None,
    }
    return {"accepte": True, "resultat": service.borner(reponse, ("contradictions",))}


# -- le rafraîchissement ---------------------------------------------------------------------------------------------
def _demandes_ouvertes() -> int:
    cnx = stockage.connexion_courante()
    return int(
        cnx.execute(
            select(func.count())
            .select_from(APPROBATIONS)
            .where(
                APPROBATIONS.c.departement == DEPARTEMENT,
                APPROBATIONS.c.outil == OUTIL_DECIDER,
                APPROBATIONS.c.statut == "en_attente",
            )
        ).scalar_one()
    )


def rafraichir_contradictions(horodatage: str, ecrire: bool = True) -> dict[str, Any]:
    refus = _refus_appareil()
    if refus is not None:
        return refus
    try:
        routines.instant(horodatage)
    except ValueError as exc:
        return _depuis_valeur_erreur(exc)
    if type(ecrire) is not bool:
        return _verdict("REJ-CONTRADICTION-ECRIRE-INVALIDE", "ecrire : booléen")
    if ecrire and not systeme.planificateur_en_cours():
        return _verdict(
            "REJ-ROUTINE-PLANIFICATEUR-REQUIS",
            "écriture réservée au planificateur durable (acteur système, tour en cours)",
        )
    ordre = _ordre()
    if ecrire:
        _connexion_ecriture("m10-contradictions")
    liste = contradictions.affirmations(_REGISTRE_AFFIRMATIONS.lire())
    actifs = contradictions.actives(liste)
    avant = contradictions.etats(_REGISTRE_CONTRADICTIONS.lire(), actifs)
    nouvelles = contradictions.detecter(actifs, set(avant), ordre, horodatage)
    bilan: dict[str, Any] = {
        "ecrit": False,
        "affirmations_actives": len(actifs),
        "nouvelles": len(nouvelles),
        "auto_resolues": sum(1 for d in nouvelles if d["traitement"] == "auto"),
        "critiques": sum(1 for d in nouvelles if d["critique"]),
        "sans_proposition": sum(1 for d in nouvelles if d["proposition"]["retenue"] is None),
    }
    if not ecrire:
        bilan["demandes_a_ouvrir"] = sum(
            1 for d in nouvelles if d["critique"] and d["proposition"]["retenue"] is not None
        ) + len(contradictions.a_demander(avant))
        return {"accepte": True, "resultat": bilan}
    for detection in nouvelles:
        for entree in contradictions.entrees_detection(detection):
            _REGISTRE_CONTRADICTIONS.ajouter(entree)
    apres = contradictions.etats(_REGISTRE_CONTRADICTIONS.lire(), actifs)
    ouvertes = _demandes_ouvertes()
    cnx = stockage.connexion_courante()
    demandes = 0
    for etat in contradictions.a_demander(apres):
        if demandes >= DEMANDES_PAR_PASSAGE or ouvertes + demandes >= DEMANDES_OUVERTES_MAX:
            break
        ident = approbations.creer_demande(
            cnx,
            DEPARTEMENT,
            OUTIL_DECIDER,
            contradictions.arguments_de_demande(etat),
            niveau=Niveau.N3,
            motif=f"Contradiction critique à valider ({etat['domaine']}) : {etat['proposition']['raison']}"[:300],
        )
        _REGISTRE_CONTRADICTIONS.ajouter(contradictions.entree_demande(etat["contradiction_id"], ident, horodatage))
        demandes += 1
    restantes = len(contradictions.a_demander(contradictions.etats(_REGISTRE_CONTRADICTIONS.lire(), actifs)))
    bilan.update(
        ecrit=True,
        demandes_ouvertes=demandes,
        demandes_differees=restantes,
        caduques=contradictions.compter(apres)[contradictions.STATUT_CADUQUE],
    )
    return {"accepte": True, "resultat": bilan}


# -- la décision -----------------------------------------------------------------------------------------------------
def decider_contradiction(contradiction_id: str, decision: str, motif: str) -> dict[str, Any]:
    acteur, refus = _o._acteur_humain(OUTIL_DECIDER)
    if acteur is None:
        return refus or _verdict("REJ-HUMAIN-REQUIS", "acteur humain introuvable")
    _connexion_ecriture("m10-contradictions")
    liste = contradictions.affirmations(_REGISTRE_AFFIRMATIONS.lire())
    etats = contradictions.etats(_REGISTRE_CONTRADICTIONS.lire(), contradictions.actives(liste))
    instant = service.instant_iso(service.maintenant())
    try:
        entrees = contradictions.preparer_decision(etats, contradiction_id, decision, motif, acteur, instant)
    except ValueError as exc:
        return _depuis_valeur_erreur(exc)
    for entree in entrees:
        _REGISTRE_CONTRADICTIONS.ajouter(entree)
    return {
        "accepte": True,
        "resultat": {
            "contradiction_id": contradiction_id,
            "decision": decision,
            "decidee_par": acteur["par"],
            "trace": "Les deux mémoires restent dans le registre ; la marque de chacune est ajoutée, rien n'est "
            "supprimé.",
        },
    }


# -- les déclarations -----------------------------------------------------------------------------------------------
_DOMAINE = {
    "type": "string",
    "enum": list(verite.domaines()),
    "description": "affaires ou developpement (jamais mêlés)",
}
_CHAMPS_AFFIRMATION = {
    "domaine": _DOMAINE,
    "sujet": {"type": "string", "description": "« famille:identifiant », famille fermée par domaine (ex. devis:D-12)"},
    "attribut": {"type": "string", "description": "minuscules, chiffres et _ (ex. statut)"},
    "valeur": {
        "type": "string",
        "description": "UN jeton (lettres, chiffres, . _ : -), jamais une phrase ni une donnée personnelle",
    },
    "classe": {
        "type": "string",
        "description": "classe de la source dans l'ordre de vérité ; le canal borne ce qui est admis",
    },
    "source_ref": {"type": "string", "description": "registre:<evenements|affaires>:<ligne_id> : une ligne qui existe"},
}


def outils_contradictions() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m10_consigner_affirmation",
            description=(
                "Consigne un fait À CLÉ et sourcé (domaine affaires) pour que M10 puisse détecter s'il en contredit un "
                "autre. La classe de la source est bornée par l'ordre de vérité (documentation, journal, mémoire "
                "ancienne, "
                "hypothèse pour un agent) ; une valeur est un jeton, jamais un texte libre ni une donnée "
                "personnelle. Une "
                "nouvelle affirmation de la même source remplace l'ancienne (qui reste au registre). Ne tranche rien."
            ),
            parametres={
                "type": "object",
                "properties": dict(_CHAMPS_AFFIRMATION),
                "required": list(_CHAMPS_AFFIRMATION),
                "additionalProperties": False,
            },
            fonction=consigner_affirmation,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m10_declarer_affirmation_humaine",
            description=(
                "DÉCISION HUMAINE : consigne un fait à clé d'une classe d'autorité haute (décision du propriétaire, "
                "rapport "
                "validé) dans le domaine affaires, au nom de la personne authentifiée. Un agent ne peut pas la faire "
                "seul : "
                "il propose, une personne approuve dans la console."
            ),
            parametres={
                "type": "object",
                "properties": {
                    **_CHAMPS_AFFIRMATION,
                    "motif": {"type": "string", "description": "pourquoi, 10 à 500 caractères"},
                },
                "required": [*_CHAMPS_AFFIRMATION, "motif"],
                "additionalProperties": False,
            },
            fonction=declarer_affirmation_humaine,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m10_lire_contradictions",
            description=(
                "Lit la file des contradictions d'un domaine (à traiter par défaut : ouvertes et en attente d'une "
                "personne) "
                "avec les deux côtés, la proposition de l'ordre de vérité et la marque de chaque mémoire, ou les "
                "affirmations avec leur marque. Lecture seule ; les deux domaines ne se mêlent jamais."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "domaine": _DOMAINE,
                    "vue": {"type": "string", "enum": ["contradictions", "affirmations"]},
                    "etat": {"type": "string", "enum": ["a_traiter", "tous", *contradictions.statuts()]},
                    "limite": {"type": "integer", "minimum": 1, "maximum": LIMITE_LECTURE_MAX},
                    "decalage": {"type": "integer", "minimum": 0},
                },
                "required": ["domaine"],
                "additionalProperties": False,
            },
            fonction=lire_contradictions,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom="m10_rafraichir_contradictions",
            description=(
                "Détecte les contradictions entre affirmations actives, les range (registre chaîné), marque les deux "
                "mémoires et propose selon l'ordre de vérité. Une contradiction non critique de rangs différents est "
                "résolue (la source de moindre autorité est marquée dominée) ; une contradiction critique ouvre une "
                "demande "
                "d'approbation. `ecrire` faux : calcul à blanc. L'écriture est réservée au planificateur durable."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "horodatage": {"type": "string", "description": "Instant du passage, ISO-8601 avec fuseau."},
                    "ecrire": {"type": "boolean"},
                },
                "required": ["horodatage"],
                "additionalProperties": False,
            },
            fonction=rafraichir_contradictions,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom=OUTIL_DECIDER,
            description=(
                "DÉCISION HUMAINE sur une contradiction rangée : retenir A, retenir B, coexistence valide ou fausse "
                "alerte, "
                "avec le motif, au nom de la personne authentifiée. Définitif ; la mémoire écartée est marquée, jamais "
                "supprimée. Un agent ne peut pas la faire seul : il propose, une personne approuve dans la console."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contradiction_id": {"type": "string"},
                    "decision": {"type": "string", "enum": list(contradictions.decisions())},
                    "motif": {"type": "string", "description": "pourquoi, 10 à 500 caractères"},
                },
                "required": ["contradiction_id", "decision", "motif"],
                "additionalProperties": False,
            },
            fonction=decider_contradiction,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
    )
