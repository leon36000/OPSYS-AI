"""Modèle de soi de l'entreprise (« profil d'entreprise apprenant ») : des énoncés versionnés, sourcés, jamais écrasés.

Un ÉNONCÉ dit un fait sur l'entreprise (un service, une zone, une équipe, une capacité, une marge observée, une
règle de la direction…) sous la forme fermée de sa dimension (`soi_dimensions`). Il porte :

- sa **source** (1 à 5) : le type (fait d'un département, onboarding, correction humaine, décision de la direction), une
  référence VÉRIFIABLE (`registre:faits_analytiques:<ligne_id>`, `entreprise:services:<empreinte>`, `decision:<id>`…)
  vérifiée par un port à l'écriture, l'instant où le fait a été observé ;
- sa **confiance**, calculée par le code (jamais déclarée) : la meilleure source, relevée par chaque source distincte
  de plus (corroboration) ;
- son **état** : `propose` (rien n'est confirmé), `confirme` (une PERSONNE l'a confirmé, avec son motif), `obsolete`
  (remplacé, rejeté ou retiré, avec le motif) ;
- sa **version** : un énoncé n'est jamais modifié. Une valeur différente est une NOUVELLE version.

**Dérive.** Un fait nouveau qui contredit un énoncé confirmé ne l'écrase pas : il devient une version PROPOSÉE qui
désigne l'énoncé confirmé qu'elle révise (`revise`) ; la révision attend une personne, qui la confirme (l'ancien devient
obsolète dans la même écriture) ou la rejette (l'ancien reste confirmé). Une source qui disparaît (le service n'est plus
au profil) ouvre un signal de dérive sans toucher l'énoncé. Pour une mesure numérique, un écart sous la tolérance de sa
dimension n'est pas une contradiction.

**Humain.** Toute confirmation, tout rejet, tout retrait et toute déclaration de la direction exigent une personne
identifiée (rôle `admin` ou `nathan_owner`, voie appareil, approbation ou CLI) et un motif de 10 à 500 caractères.
L'identité est établie par l'appelant (l'outil M10) ; ce module refuse tout ce qui n'a pas la forme d'un humain.

Le journal est un registre append-only chaîné (celui de M10) ; l'état est TOUJOURS rejoué depuis lui. Module pur :
aucune horloge (l'instant est passé), aucun réseau.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any, NamedTuple

from . import codes, vie_privee
from . import soi_dimensions as dims
from .codes import ErreurMnemo

TYPE_ENONCE = "soi_enonce"
TYPE_DECISION = "soi_decision"
TYPE_CORROBORATION = "soi_corroboration"
TYPE_DERIVE = "soi_derive"
TYPES_ENTREE = (TYPE_ENONCE, TYPE_DECISION, TYPE_CORROBORATION, TYPE_DERIVE)

ETATS = ("propose", "confirme", "obsolete")
TYPES_SOURCE = ("fait_departement", "onboarding", "correction_humaine", "decision_direction")
LECTEUR_ADMIN = "administration"
SOURCES_MAX = 5
MOTIF_MIN, MOTIF_MAX = 10, 500
ENONCES_MAX_VUE = 200
MENTION_PROFESSIONNELLE = "À valider auprès d'un comptable (CPA) / professionnel qualifié"

_BASE_CONFIANCE = {
    "onboarding": Decimal("0.70"),
    "fait_departement": Decimal("0.60"),
    "correction_humaine": Decimal("0.85"),
    "decision_direction": Decimal("1.00"),
}
_BONUS_CORROBORATION = Decimal("0.05")
_PLAFOND_SANS_DIRECTION = Decimal("0.95")
_REF = re.compile(r"^(registre|entreprise|decision|connaissance|pack|direction):[A-Za-z0-9._:/#~-]{3,180}$")
_DEPARTEMENT = re.compile(r"^m(0[1-9]|10)-[a-z][a-z0-9-]*$")
_PERSONNE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_AGENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{1,63}$")
_ROLES_HUMAINS = frozenset({"admin", "nathan_owner"})
_VOIES = frozenset({"appareil", "approbation", "cli"})
_CLES_SOURCE = {"type", "ref", "observe_le"}


class Acteur(NamedTuple):
    """Qui décide. Établi par l'appelant (jeton d'appareil confirmé en base, ou approbation humaine) : jamais un
    argument."""

    par: str
    role: str
    source: str


Verificateur = Callable[[Mapping[str, Any]], bool]


# -- validations
# ---------------------------------------------------------------------------------------------------------
def _instant(valeur: object, champ: str, code: str = codes.HORODATAGE_INVALIDE) -> dt.datetime:
    if not isinstance(valeur, str) or not valeur:
        raise ErreurMnemo(code, f"{champ} : horodatage ISO 8601 avec fuseau requis")
    try:
        instant = dt.datetime.fromisoformat(valeur)
    except ValueError:
        raise ErreurMnemo(code, f"{champ} : horodatage ISO 8601 avec fuseau requis") from None
    if instant.tzinfo is None:
        raise ErreurMnemo(code, f"{champ} : le fuseau horaire est obligatoire")
    return instant


def exiger_humain(acteur: object, motif: object, horodatage: object) -> tuple[Acteur, str]:
    """L'acteur est une personne identifiée, le motif est écrit, l'instant est valide ; sinon un refus typé."""
    if (
        not isinstance(acteur, Acteur)
        or not isinstance(acteur.par, str)
        or not _PERSONNE.fullmatch(acteur.par)
        or acteur.role not in _ROLES_HUMAINS
        or acteur.source not in _VOIES
    ):
        raise ErreurMnemo(
            codes.HUMAIN_REQUIS,
            "cette écriture est une décision humaine : une personne identifiée "
            "(rôle admin ou propriétaire) par appareil, approbation ou CLI",
        )
    if not isinstance(motif, str) or not MOTIF_MIN <= len(motif.strip()) <= MOTIF_MAX:
        raise ErreurMnemo(codes.MOTIF_REQUIS, f"le motif est obligatoire : {MOTIF_MIN} à {MOTIF_MAX} caractères")
    _instant(horodatage, "horodatage")
    return acteur, motif.strip()


def _valider_source(source: object, *, direction: bool) -> dict[str, Any]:
    if not isinstance(source, Mapping) or not _CLES_SOURCE <= set(source) <= _CLES_SOURCE | {"departement"}:
        raise ErreurMnemo(
            codes.SOURCE_INVALIDE, "source : {type, ref, observe_le} (+ departement pour un fait de département)"
        )
    genre = source["type"]
    if genre not in TYPES_SOURCE:
        raise ErreurMnemo(
            codes.SOURCE_INVALIDE, f"type de source {vie_privee.court(genre)} inconnu : {list(TYPES_SOURCE)}"
        )
    if genre == "decision_direction" and not direction:
        raise ErreurMnemo(
            codes.SOURCE_DIRECTION_RESERVEE,
            "une source « décision de la direction » ne vient que de la déclaration d'une personne",
        )
    if not isinstance(source["ref"], str) or not _REF.fullmatch(source["ref"]):
        raise ErreurMnemo(
            codes.SOURCE_INVALIDE, "ref : référence vérifiable attendue (registre:…, entreprise:…, decision:…)"
        )
    _instant(source["observe_le"], "observe_le", codes.SOURCE_INVALIDE)
    propre: dict[str, Any] = {"type": genre, "ref": source["ref"], "observe_le": source["observe_le"]}
    if genre == "fait_departement":
        dep = source.get("departement")
        if not isinstance(dep, str) or not _DEPARTEMENT.fullmatch(dep):
            raise ErreurMnemo(codes.SOURCE_INVALIDE, "un fait de département nomme son département (mNN-…)")
        propre["departement"] = dep
    elif "departement" in source:
        raise ErreurMnemo(codes.SOURCE_INVALIDE, "departement ne vaut que pour un fait de département")
    return propre


def _valider_sources(sources: object, verificateur: Verificateur) -> list[dict[str, Any]]:
    if not isinstance(sources, Sequence) or isinstance(sources, str) or not 1 <= len(sources) <= SOURCES_MAX:
        raise ErreurMnemo(codes.SOURCE_INVALIDE, f"un énoncé cite 1 à {SOURCES_MAX} sources")
    propres = [_valider_source(s, direction=False) for s in sources]
    if len({s["ref"] for s in propres}) != len(propres):
        raise ErreurMnemo(codes.SOURCE_INVALIDE, "deux sources identiques")
    for s in propres:
        if not verificateur(s):
            raise ErreurMnemo(
                codes.SOURCE_INTROUVABLE,
                f"la source {s['ref']} n'existe pas ou ne correspond pas : une source se vérifie, elle ne se déclare "
                f"pas",
            )
    return propres


def calculer_confiance(sources: Sequence[Mapping[str, Any]]) -> str:
    """Confiance DÉTERMINISTE : la meilleure source de base, plus 0,05 par source distincte de plus, plafonnée à 0,95
    sans décision de la direction. Ce n'est pas une probabilité : c'est un rang de solidité des preuves."""
    if not sources:
        return "0.00"
    base = max(_BASE_CONFIANCE[s["type"]] for s in sources)
    refs = {s["ref"] for s in sources}
    note = base + _BONUS_CORROBORATION * (len(refs) - 1)
    if not any(s["type"] == "decision_direction" for s in sources):
        note = min(note, _PLAFOND_SANS_DIRECTION)
    return str(min(note, Decimal("1.00")).quantize(Decimal("0.01")))


def niveau_confiance(confiance: str) -> str:
    valeur = Decimal(confiance)
    return "faible" if valeur < Decimal("0.65") else "moyenne" if valeur < Decimal("0.85") else "haute"


def _canon(valeur: Any) -> str:
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def enonce_id(dimension: str, cle: str, version: int) -> str:
    return hashlib.sha256(f"soi|{dimension}|{cle}|v{version}".encode()).hexdigest()[:24]


# -- état rejoué
# ---------------------------------------------------------------------------------------------------------
class EtatSoi:
    def __init__(self) -> None:
        self.enonces: dict[str, dict[str, Any]] = {}
        self.ordre: list[str] = []
        self._derives: dict[str, list[dict[str, Any]]] = {}

    def _par_cle(self, dimension: str, cle: str) -> list[dict[str, Any]]:
        return [
            self.enonces[i]
            for i in self.ordre
            if self.enonces[i]["dimension"] == dimension and self.enonces[i]["cle"] == cle
        ]

    def confirme(self, dimension: str, cle: str) -> dict[str, Any] | None:
        return next((e for e in self._par_cle(dimension, cle) if e["etat"] == "confirme"), None)

    def propose(self, dimension: str, cle: str) -> dict[str, Any] | None:
        courants = [e for e in self._par_cle(dimension, cle) if e["etat"] == "propose"]
        return courants[-1] if courants else None

    def version_suivante(self, dimension: str, cle: str) -> int:
        return 1 + max((e["version"] for e in self._par_cle(dimension, cle)), default=0)

    def revisions_en_attente(self) -> list[dict[str, Any]]:
        return [e for e in map(self.enonces.get, self.ordre) if e and e["etat"] == "propose" and e["revise"]]

    def derives_ouvertes(self) -> list[dict[str, Any]]:
        sortie = []
        for ident, evenements in self._derives.items():
            e = self.enonces[ident]
            if e["etat"] == "confirme" and evenements and not evenements[-1]["levee"]:
                sortie.append(
                    {
                        "enonce_id": ident,
                        "dimension": e["dimension"],
                        "cle": e["cle"],
                        "nature": "source_disparue",
                        "ref_constat": evenements[-1]["ref_constat"],
                        "depuis": evenements[-1]["horodatage"],
                    }
                )
        return sortie

    def derive_ouverte(self, ident: str) -> bool:
        return any(d["enonce_id"] == ident for d in self.derives_ouvertes())


def etat(registre: Any) -> EtatSoi:
    """Rejoue le journal. Une écriture incohérente (journal altéré à la main) est un refus typé, jamais ignorée."""
    st = EtatSoi()
    for m in registre.lire():
        genre = m.get("type_entree")
        if genre == TYPE_ENONCE:
            st.enonces[m["enonce_id"]] = {
                "enonce_id": m["enonce_id"],
                "dimension": m["dimension"],
                "cle": m["cle"],
                "version": m["version"],
                "valeur": m["valeur"],
                "libelle": m["libelle"],
                "sources": [dict(s) for s in m["sources"]],
                "revise": m["revise"],
                "propose_par": m["propose_par"],
                "propose_le": m["horodatage"],
                "confidentialite": m["confidentialite"],
                "etat": "propose",
                "remplace_par": None,
                "confirme_par": None,
                "confirme_le": None,
                "motif_decision": None,
                "decide_par": None,
            }
            st.ordre.append(m["enonce_id"])
        elif genre in (TYPE_DECISION, TYPE_CORROBORATION, TYPE_DERIVE):
            cible = st.enonces.get(m.get("enonce_id"))
            if cible is None:
                raise ErreurMnemo(codes.ENONCE_INCONNU, "le journal décide d'un énoncé qui n'existe pas")
            if genre == TYPE_CORROBORATION:
                if m["source"]["ref"] not in {s["ref"] for s in cible["sources"]}:
                    cible["sources"].append(dict(m["source"]))
            elif genre == TYPE_DERIVE:
                st._derives.setdefault(cible["enonce_id"], []).append(
                    {"levee": bool(m["levee"]), "ref_constat": m.get("ref_constat"), "horodatage": m["horodatage"]}
                )
            else:
                _appliquer_decision(st, cible, m)
    for e in st.enonces.values():
        e["confiance"] = calculer_confiance(e["sources"])
    return st


def _appliquer_decision(st: EtatSoi, cible: dict[str, Any], m: Mapping[str, Any]) -> None:
    action, courant = m["action"], cible["etat"]
    if action == "confirmer" and courant == "propose":
        autre = st.confirme(cible["dimension"], cible["cle"])
        if autre is not None:
            raise ErreurMnemo(codes.TRANSITION_INTERDITE, "le journal confirme deux énoncés pour la même clé")
        cible.update(
            etat="confirme",
            confirme_par=m["par"],
            confirme_le=m["horodatage"],
            motif_decision=m["motif"],
            decide_par=m["par"],
        )
    elif action == "rejeter" and courant == "propose" or action == "retirer" and courant == "confirme":
        cible.update(etat="obsolete", motif_decision=m["motif"], decide_par=m["par"])
    elif action == "remplacer" and courant in ("propose", "confirme"):
        cible.update(
            etat="obsolete", motif_decision=m["motif"], decide_par=m["par"], remplace_par=m.get("remplace_par")
        )
    else:
        raise ErreurMnemo(codes.TRANSITION_INTERDITE, f"« {action} » illégal depuis « {courant} »")


# -- écritures
# -----------------------------------------------------------------------------------------------------------
def _decision(
    registre: Any,
    ident: str,
    action: str,
    *,
    par: str,
    role: str | None,
    voie: str,
    motif: str,
    horodatage: str,
    remplace_par: str | None = None,
) -> None:
    entree = {
        "type_entree": TYPE_DECISION,
        "horodatage": horodatage,
        "enonce_id": ident,
        "action": action,
        "par": par,
        "role": role,
        "source_decision": voie,
        "motif": motif,
    }
    if remplace_par is not None:
        entree["remplace_par"] = remplace_par
    registre.ajouter(entree)


def _ecrire_enonce(
    registre: Any,
    st: EtatSoi,
    d: dims.Dimension,
    cle: str,
    valeur: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    par: str,
    horodatage: str,
    revise: str | None,
) -> str:
    version = st.version_suivante(d.nom, cle)
    ident = enonce_id(d.nom, cle, version)
    registre.ajouter(
        {
            "type_entree": TYPE_ENONCE,
            "horodatage": horodatage,
            "enonce_id": ident,
            "dimension": d.nom,
            "cle": cle,
            "version": version,
            "valeur": valeur,
            "libelle": d.libelle(cle, valeur),
            "sources": sources,
            "confiance": calculer_confiance(sources),
            "revise": revise,
            "propose_par": par,
            "confidentialite": d.confidentialite,
        }
    )
    return ident


def _corroborer(registre: Any, existant: dict[str, Any], sources: list[dict[str, Any]], horodatage: str) -> bool:
    deja = {s["ref"] for s in existant["sources"]}
    nouvelles = [s for s in sources if s["ref"] not in deja]
    for s in nouvelles:
        registre.ajouter(
            {
                "type_entree": TYPE_CORROBORATION,
                "horodatage": horodatage,
                "enonce_id": existant["enonce_id"],
                "source": s,
            }
        )
    return bool(nouvelles)


def _vue_enonce(st: EtatSoi, ident: str, maintenant: dt.datetime | None = None) -> dict[str, Any]:
    e = st.enonces[ident]
    d = dims.DIMENSIONS[e["dimension"]]
    vue = {
        **e,
        "sources": [dict(s) for s in e["sources"]],
        "structurant": d.structurante,
        "niveau_confiance": niveau_confiance(e["confiance"]),
        "derive_ouverte": st.derive_ouverte(ident),
    }
    if e["revise"] in st.enonces:
        vue["revise_libelle"] = st.enonces[e["revise"]]["libelle"]
    if maintenant is not None:
        derniere = max(_instant(s["observe_le"], "observe_le") for s in e["sources"])
        vue["age_jours"] = max(0, (maintenant.date() - derniere.date()).days)
    return vue


def proposer(
    registre: Any,
    *,
    dimension: str,
    cle: str,
    valeur: Any,
    sources: Any,
    par: str,
    horodatage: str,
    verificateur: Verificateur,
) -> dict[str, Any]:
    """Propose un énoncé SOURCÉ. Rend `{statut, enonce, derive, revise}` ; `statut` vaut `propose`, `revision_proposee`,
    `deja_propose`, `deja_confirme` ou `dans_la_tolerance` (ces trois derniers n'écrivent qu'une corroboration, ou
    rien).
    Rien n'est confirmé par cet appel : la confirmation est une décision humaine."""
    d = dims.dimension(dimension)
    cle_n, valeur_n = d.valider(cle, valeur)
    if not isinstance(par, str) or not _AGENT.fullmatch(par):
        raise ErreurMnemo(codes.ENTREE_INVALIDE, "par : identifiant de l'auteur de la proposition")
    _instant(horodatage, "horodatage")
    propres = _valider_sources(sources, verificateur)
    st = etat(registre)
    courant, en_attente = st.confirme(d.nom, cle_n), st.propose(d.nom, cle_n)

    def reponse(statut: str, ident: str, derive: bool = False) -> dict[str, Any]:
        nouvel = etat(registre)
        return {
            "statut": statut,
            "enonce": _vue_enonce(nouvel, ident),
            "derive": derive,
            "revise": nouvel.enonces[ident]["revise"],
        }

    if courant is not None and _canon(courant["valeur"]) == _canon(valeur_n):
        _corroborer(registre, courant, propres, horodatage)
        return reponse("deja_confirme", courant["enonce_id"])
    if courant is not None and dims.dans_la_tolerance(d, courant["valeur"], valeur_n):
        return {
            "statut": "dans_la_tolerance",
            "enonce": _vue_enonce(st, courant["enonce_id"]),
            "derive": False,
            "revise": None,
        }
    if en_attente is not None and _canon(en_attente["valeur"]) == _canon(valeur_n):
        _corroborer(registre, en_attente, propres, horodatage)
        return reponse("deja_propose", en_attente["enonce_id"], derive=en_attente["revise"] is not None)
    nouveau_id = enonce_id(d.nom, cle_n, st.version_suivante(d.nom, cle_n))
    if en_attente is not None:
        _decision(
            registre,
            en_attente["enonce_id"],
            "remplacer",
            par=par,
            role=None,
            voie="proposition_plus_recente",
            motif="Remplacée par une proposition plus récente, rien n'est perdu",
            horodatage=horodatage,
            remplace_par=nouveau_id,
        )
    ident = _ecrire_enonce(
        registre,
        st,
        d,
        cle_n,
        valeur_n,
        propres,
        par=par,
        horodatage=horodatage,
        revise=courant["enonce_id"] if courant else None,
    )
    return reponse("revision_proposee" if courant else "propose", ident, derive=courant is not None)


def declarer_direction(
    registre: Any, *, dimension: str, cle: str, valeur: Any, acteur: Acteur, motif: str, horodatage: str
) -> dict[str, Any]:
    """La direction énonce elle-même un fait ou une règle : l'énoncé naît CONFIRMÉ (source : sa décision), et remplace
    l'énoncé confirmé de la même clé, ou la proposition qui l'attendait, sans rien effacer."""
    acteur, motif = exiger_humain(acteur, motif, horodatage)
    d = dims.dimension(dimension)
    cle_n, valeur_n = d.valider(cle, valeur)
    st = etat(registre)
    courant, en_attente = st.confirme(d.nom, cle_n), st.propose(d.nom, cle_n)
    if courant is not None and _canon(courant["valeur"]) == _canon(valeur_n):
        return {
            "statut": "deja_confirme",
            "enonce": _vue_enonce(st, courant["enonce_id"]),
            "derive": False,
            "revise": None,
        }
    empreinte = hashlib.sha256(f"{acteur.par}|{horodatage}|{motif}".encode()).hexdigest()[:12]
    source = _valider_source(
        {"type": "decision_direction", "ref": f"direction:{acteur.par}:{empreinte}", "observe_le": horodatage},
        direction=True,
    )
    nouveau_id = enonce_id(d.nom, cle_n, st.version_suivante(d.nom, cle_n))
    for ancien in (en_attente, courant):
        if ancien is not None:
            _decision(
                registre,
                ancien["enonce_id"],
                "remplacer",
                par=acteur.par,
                role=acteur.role,
                voie=acteur.source,
                motif=f"Remplacé par la déclaration de la direction : {motif}",
                horodatage=horodatage,
                remplace_par=nouveau_id,
            )
    ident = _ecrire_enonce(
        registre,
        st,
        d,
        cle_n,
        valeur_n,
        [source],
        par=acteur.par,
        horodatage=horodatage,
        revise=courant["enonce_id"] if courant else None,
    )
    _decision(
        registre,
        ident,
        "confirmer",
        par=acteur.par,
        role=acteur.role,
        voie=acteur.source,
        motif=motif,
        horodatage=horodatage,
    )
    nouvel = etat(registre)
    return {"statut": "declare", "enonce": _vue_enonce(nouvel, ident), "derive": False, "revise": None}


def _cible(st: EtatSoi, ident: object) -> dict[str, Any]:
    if not isinstance(ident, str) or ident not in st.enonces:
        raise ErreurMnemo(codes.ENONCE_INCONNU, "énoncé introuvable")
    return st.enonces[ident]


def confirmer(registre: Any, ident: str, *, acteur: Acteur, motif: str, horodatage: str) -> dict[str, Any]:
    """Une PERSONNE confirme un énoncé proposé. S'il révise un énoncé confirmé, celui-ci devient obsolète dans la même
    écriture (jamais deux énoncés confirmés pour une même clé)."""
    acteur, motif = exiger_humain(acteur, motif, horodatage)
    st = etat(registre)
    cible = _cible(st, ident)
    if cible["etat"] != "propose":
        raise ErreurMnemo(
            codes.TRANSITION_INTERDITE, f"seul un énoncé proposé se confirme (celui-ci est {cible['etat']})"
        )
    courant = st.confirme(cible["dimension"], cible["cle"])
    if cible["revise"] is not None and courant is not None and courant["enonce_id"] != cible["revise"]:
        raise ErreurMnemo(
            codes.TRANSITION_INTERDITE,
            "l'énoncé confirmé que cette révision visait a changé entre-temps : propose-la de nouveau",
        )
    if courant is not None:
        _decision(
            registre,
            courant["enonce_id"],
            "remplacer",
            par=acteur.par,
            role=acteur.role,
            voie=acteur.source,
            motif=f"Remplacé par la version {cible['version']} confirmée : {motif}",
            horodatage=horodatage,
            remplace_par=ident,
        )
    _decision(
        registre,
        ident,
        "confirmer",
        par=acteur.par,
        role=acteur.role,
        voie=acteur.source,
        motif=motif,
        horodatage=horodatage,
    )
    return {"enonce": _vue_enonce(etat(registre), ident)}


def rejeter(registre: Any, ident: str, *, acteur: Acteur, motif: str, horodatage: str) -> dict[str, Any]:
    """Une PERSONNE rejette un énoncé proposé (ou une révision) : il devient obsolète ; l'énoncé confirmé reste en
    place."""
    acteur, motif = exiger_humain(acteur, motif, horodatage)
    st = etat(registre)
    cible = _cible(st, ident)
    if cible["etat"] != "propose":
        raise ErreurMnemo(
            codes.TRANSITION_INTERDITE, f"seul un énoncé proposé se rejette (celui-ci est {cible['etat']})"
        )
    _decision(
        registre,
        ident,
        "rejeter",
        par=acteur.par,
        role=acteur.role,
        voie=acteur.source,
        motif=motif,
        horodatage=horodatage,
    )
    return {"enonce": _vue_enonce(etat(registre), ident)}


def retirer(registre: Any, ident: str, *, acteur: Acteur, motif: str, horodatage: str) -> dict[str, Any]:
    """Une PERSONNE retire un énoncé confirmé (il devient obsolète, il reste lisible pour l'audit)."""
    acteur, motif = exiger_humain(acteur, motif, horodatage)
    st = etat(registre)
    cible = _cible(st, ident)
    if cible["etat"] != "confirme":
        raise ErreurMnemo(
            codes.TRANSITION_INTERDITE, f"seul un énoncé confirmé se retire (celui-ci est {cible['etat']})"
        )
    _decision(
        registre,
        ident,
        "retirer",
        par=acteur.par,
        role=acteur.role,
        voie=acteur.source,
        motif=motif,
        horodatage=horodatage,
    )
    return {"enonce": _vue_enonce(etat(registre), ident)}


def signaler_source_disparue(
    registre: Any, dimension: str, cle: str, *, ref_constat: str, horodatage: str
) -> dict[str, Any] | None:
    """La source d'un énoncé CONFIRMÉ ne le soutient plus (ex. le service a quitté le profil). Ouvre un signal de
    dérive ;
    ne touche pas l'énoncé. `None` : rien de confirmé pour cette clé, ou signal déjà ouvert."""
    dims.dimension(dimension)
    _instant(horodatage, "horodatage")
    if not isinstance(ref_constat, str) or not _REF.fullmatch(ref_constat):
        raise ErreurMnemo(codes.SOURCE_INVALIDE, "ref_constat : référence du constat attendue")
    st = etat(registre)
    courant = st.confirme(dimension, cle)
    if courant is None or st.derive_ouverte(courant["enonce_id"]):
        return None
    registre.ajouter(
        {
            "type_entree": TYPE_DERIVE,
            "horodatage": horodatage,
            "enonce_id": courant["enonce_id"],
            "nature": "source_disparue",
            "levee": False,
            "ref_constat": ref_constat,
        }
    )
    return {"enonce_id": courant["enonce_id"], "ouverte": True}


def lever_derive(registre: Any, dimension: str, cle: str, *, horodatage: str) -> bool:
    """La source soutient de nouveau l'énoncé : le signal est levé (le journal garde les deux événements)."""
    _instant(horodatage, "horodatage")
    st = etat(registre)
    courant = st.confirme(dimension, cle)
    if courant is None or not st.derive_ouverte(courant["enonce_id"]):
        return False
    registre.ajouter(
        {
            "type_entree": TYPE_DERIVE,
            "horodatage": horodatage,
            "enonce_id": courant["enonce_id"],
            "nature": "source_disparue",
            "levee": True,
            "ref_constat": None,
        }
    )
    return True


# -- lecture
# -------------------------------------------------------------------------------------------------------------
def _peut_lire(d: dims.Dimension, lecteur: str) -> bool:
    return lecteur == LECTEUR_ADMIN or d.lecteurs is None or lecteur in d.lecteurs


def vue(
    registre: Any,
    *,
    lecteur: str | None,
    maintenant: dt.datetime,
    dimension: str | None = None,
    etats_voulus: Sequence[str] = ("confirme", "propose"),
    decalage: int = 0,
) -> dict[str, Any]:
    """Ce qu'un département peut lire du modèle de soi. `lecteur` : l'identifiant du département appelant (fixé par la
    plateforme, jamais un argument), ou `LECTEUR_ADMIN` pour la console. Une dimension que le lecteur n'a pas le droit
    de
    lire n'est ni rendue ni nommée : elle est seulement comptée (`retenus_confidentialite`)."""
    if lecteur != LECTEUR_ADMIN and (not isinstance(lecteur, str) or not _DEPARTEMENT.fullmatch(lecteur)):
        raise ErreurMnemo(
            codes.LECTURE_INTERDITE, "lecteur inconnu : le département appelant est fixé par la plateforme"
        )
    if dimension is not None:
        dims.dimension(dimension)
    if (
        not isinstance(etats_voulus, Sequence)
        or isinstance(etats_voulus, str)
        or not set(etats_voulus) <= set(ETATS)
        or not etats_voulus
    ):
        raise ErreurMnemo(codes.ENTREE_INVALIDE, f"etats : sous-ensemble non vide de {list(ETATS)}")
    st = etat(registre)
    retenus, visibles = 0, []
    for ident in st.ordre:
        e = st.enonces[ident]
        if e["etat"] not in etats_voulus or (dimension is not None and e["dimension"] != dimension):
            continue
        if not _peut_lire(dims.DIMENSIONS[e["dimension"]], lecteur):
            retenus += 1
            continue
        visibles.append(_vue_enonce(st, ident, maintenant))
    if type(decalage) is not int or decalage < 0:
        raise ErreurMnemo(codes.ENTREE_INVALIDE, "decalage : entier ≥ 0")
    total = len(visibles)
    visibles = visibles[decalage:]
    omis = max(0, len(visibles) - ENONCES_MAX_VUE)
    revisions = [
        _vue_enonce(st, e["enonce_id"], maintenant)
        for e in st.revisions_en_attente()
        if _peut_lire(dims.DIMENSIONS[e["dimension"]], lecteur)
    ]
    couverture = []
    for nom, d in dims.DIMENSIONS.items():
        if not _peut_lire(d, lecteur):
            continue
        parmi = [e for e in st.enonces.values() if e["dimension"] == nom]
        confirmes = sum(1 for e in parmi if e["etat"] == "confirme")
        proposes = sum(1 for e in parmi if e["etat"] == "propose")
        couverture.append(
            {
                "dimension": nom,
                "structurante": d.structurante,
                "alimentation": d.alimentation,
                "confirmes": confirmes,
                "proposes": proposes,
                "revisions_en_attente": sum(1 for e in st.revisions_en_attente() if e["dimension"] == nom),
                "derives_ouvertes": sum(1 for x in st.derives_ouvertes() if x["dimension"] == nom),
                "statut": "confirme" if confirmes else "a_confirmer" if proposes else "inconnu",
            }
        )
    sortie = {
        "enonces": visibles[:ENONCES_MAX_VUE],
        "total": total,
        "decalage": decalage,
        "omis": omis,
        "revisions_en_attente": revisions,
        "derives_ouvertes": [x for x in st.derives_ouvertes() if _peut_lire(dims.DIMENSIONS[x["dimension"]], lecteur)],
        "couverture": couverture,
        "retenus_confidentialite": retenus,
        "avertissement": (
            "Seuls les énoncés « confirme » ont été validés par une personne ; un énoncé « propose » est une "
            "hypothèse sourcée, pas un fait. Une dimension « inconnu » n'a aucune source : ne l'invente pas."
        ),
    }
    if any(x["dimension"] == "marges_observees" for x in visibles):
        sortie["mention_professionnelle"] = MENTION_PROFESSIONNELLE
    return sortie


def rejets_par_dimension(registre: Any) -> list[dict[str, Any]]:
    """Les rejets HUMAINS de propositions, par dimension : la matière d'une leçon (« la direction rejette souvent les
    propositions automatiques de cette dimension »). Une proposition remplacée par une plus récente n'est pas un
    rejet."""
    st = etat(registre)
    groupes: dict[str, dict[str, Any]] = {}
    for m in registre.lire():
        if m.get("type_entree") == TYPE_DECISION and m.get("action") == "rejeter":
            e = st.enonces[m["enonce_id"]]
            g = groupes.setdefault(e["dimension"], {"cles": set(), "rejets": 0, "lignes": []})
            g["cles"].add(e["cle"])
            g["rejets"] += 1
            g["lignes"].append(m["ligne_id"])
    return [
        {"dimension": d, "rejets": g["rejets"], "cles_distinctes": len(g["cles"]), "lignes": sorted(g["lignes"])[:5]}
        for d, g in sorted(groupes.items())
    ]


_CHAMPS_COMPACTS = (
    "enonce_id",
    "dimension",
    "cle",
    "version",
    "etat",
    "libelle",
    "confiance",
    "niveau_confiance",
    "age_jours",
    "structurant",
    "revise",
    "revise_libelle",
    "derive_ouverte",
    "sources",
    "confirme_par",
    "confirme_le",
    "motif_decision",
)


def compacter(vue_complete: Mapping[str, Any], *, avec_valeur: bool = False) -> dict[str, Any]:
    """La vue réduite que rendent les outils : le libellé écrit par le code dit l'essentiel ; la valeur structurée ne
    vient
    qu'à la demande (elle fait grossir la réponse, bornée à 5 700 caractères). Les listes paginées disent `suivant`."""

    def reduire(e: Mapping[str, Any]) -> dict[str, Any]:
        champs = _CHAMPS_COMPACTS + (("valeur",) if avec_valeur else ())
        return {c: e[c] for c in champs if c in e}

    sortie = dict(vue_complete)
    sortie["enonces"] = [reduire(e) for e in vue_complete["enonces"]]
    sortie["revisions_en_attente"] = [reduire(e) for e in vue_complete["revisions_en_attente"]]
    return sortie


def avec_pagination(vue_bornee: Mapping[str, Any]) -> dict[str, Any]:
    """Après le bornage par taille : `suivant` dit où reprendre si la réponse n'a pas tout montré."""
    sortie = dict(vue_bornee)
    montres = sortie["decalage"] + len(sortie["enonces"])
    sortie["suivant"] = montres if montres < sortie["total"] else None
    return sortie
