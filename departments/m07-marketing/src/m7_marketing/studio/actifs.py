"""Registre append-only des ACTIFS du studio et machine d'états de la revue humaine.

Trois sortes d'actifs : un `fond` (image ou clip généré : jamais publiable tel quel), un `visuel` (fond + gabarit,
contrôlé) et un `logo` (vectorisé ou fourni). Le registre est un journal chaîné (`journal_chaine`) : un état est le
PLIAGE des maillons.

    fond_genere  -> fond_brut (terminal : un fond ne se publie jamais)
    compose      -> controle -> controle_conforme -> revue_demandee -> approuve -> revoque
                             -> controle_echec (ne passe pas en revue)   revue_demandee -> rejete
    logo_concept -> controle -> ... (mêmes étapes, attestations propres au logo)

Règles, toutes fail-closed :
  - un contrôle n'est accepté que pour la composition COURANTE et avec une empreinte de rapport vérifiée ;
  - un visuel dont le contrôle a un constat critique en échec NE PEUT PAS passer en revue ;
  - l'approbation est une décision de PERSONNE (rôle `nathan_owner` établi par la plateforme), liée à l'empreinte de la
    composition ET à celle du rapport : un visuel recomposé ou recontrôlé après la demande de revue n'est plus
    approuvé ;
  - un visuel NON fictif ne s'approuve pas sur la lecture d'un double : un lecteur réel est exigé ; ni avec un fond
    produit par un générateur double ;
  - la licence du modèle est revérifiée au moment de l'approbation (verdict fourni ; absent : refus) ;
  - les attestations de la personne (éléments critiques vérifiés à la source, aucun visage ni plaque identifiable, rendu
    relu, allure réaliste ou non) sont consignées avec l'approbation ; `realiste` fonde la divulgation d'IA du sas ;
  - un logo exige une note de contribution humaine et la reconnaissance qu'AUCUNE protection juridique n'est promise.

Module pur : le journal est n'importe quelle séquence `append`/`len`/itération ; l'horodatage est un argument.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Callable, Mapping
from typing import Any

from .. import journal_chaine
from . import controle
from . import portes as p
from .composition import Composition

ROLE_DECIDEUR = "nathan_owner"
REGISTRE = ("m07-marketing", "actifs_studio")

ETAT_FOND_BRUT = "fond_brut"
ETAT_LOGO_CONCEPT = "logo_concept"
ETAT_COMPOSE = "compose"
ETAT_CONTROLE_CONFORME = "controle_conforme"
ETAT_CONTROLE_ECHEC = "controle_echec"
ETAT_EN_REVUE = "en_revue"
ETAT_APPROUVE = "approuve"
ETAT_REJETE = "rejete"
ETAT_REVOQUE = "revoque"

M_FOND = "fond_genere"
M_LOGO = "logo_concept"
M_COMPOSE = "compose"
M_CONTROLE = "controle"
M_REVUE = "revue_demandee"
M_APPROUVE = "approuve"
M_REJETE = "rejete"
M_REVOQUE = "revoque"

REJ_JOURNAL_ALTERE = "REJ-STUDIO-ACTIFS-JOURNAL-ALTERE"
REJ_JOURNAL_INCOHERENT = "REJ-STUDIO-ACTIFS-JOURNAL-INCOHERENT"
REJ_ACTIF_INCONNU = "REJ-STUDIO-ACTIF-INCONNU"
REJ_ETAT = "REJ-STUDIO-ACTIF-ETAT"
REJ_RAPPORT = "REJ-STUDIO-RAPPORT-INVALIDE"
REJ_RAPPORT_ETRANGER = "REJ-STUDIO-RAPPORT-ETRANGER"
REJ_REVUE_NON_CONFORME = "REJ-STUDIO-REVUE-CONTROLE-NON-CONFORME"
REJ_HUMAIN = "REJ-STUDIO-HUMAIN-REQUIS"
REJ_EMPREINTE = "REJ-STUDIO-EMPREINTE-DIFFERENTE"
REJ_ATTESTATION = "REJ-STUDIO-ATTESTATION"
REJ_OCR_REEL = "REJ-STUDIO-OCR-REEL-REQUIS"
REJ_GENERATEUR_TEST = "REJ-STUDIO-GENERATEUR-DE-TEST"
REJ_LICENCE = "REJ-STUDIO-LICENCE-NON-CONFORME"
REJ_LOGO = "REJ-STUDIO-LOGO"

AVERTISSEMENT_LOGO = (
    "Un logo généré ou vectorisé automatiquement n'a AUCUNE protection juridique garantie : le droit d'auteur sur une "
    "œuvre générée sans apport humain suffisant est incertain (États-Unis, Canada), et rien ici ne vaut recherche "
    "d'antériorité de marque ni dépôt. La protection d'un logo passe par la marque de commerce : faire valider par un "
    "agent de marques ou un avocat (À valider auprès d'un professionnel qualifié) avant tout investissement."
)
ATTESTATIONS_VISUEL = ("elements_critiques_verifies", "aucun_visage_ni_plaque_identifiable", "rendu_relu_a_l_ecran")
ATTESTATIONS_LOGO = ("avertissement_logo_lu",)
ANTERIORITE = ("faite", "renvoyee_a_un_agent_de_marques")


class JournalIncoherent(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class EtatActif:
    actif_id: str
    kind: str
    etat: str
    donnees: Mapping[str, Any]
    rapport: Mapping[str, Any] | None = None
    approbation: Mapping[str, Any] | None = None
    rangs: tuple[int, ...] = ()

    @property
    def approuve(self) -> bool:
        return self.etat == ETAT_APPROUVE

    def resume(self) -> dict[str, Any]:
        d = self.donnees
        return {
            "actif_id": self.actif_id,
            "kind": self.kind,
            "etat": self.etat,
            "fictif": d.get("fictif"),
            "ia_generee": d.get("ia_generee"),
            "gabarit": d.get("gabarit"),
            "format": d.get("format"),
            "composition_empreinte": d.get("composition_empreinte"),
            "rapport_empreinte": self.rapport["empreinte"] if self.rapport else None,
            "rapport_conforme": self.rapport["conforme"] if self.rapport else None,
            "approuve_par": self.approbation["par"] if self.approbation else None,
            "artefacts": d.get("artefacts"),
        }


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def identifiant_visuel(composition_empreinte: str) -> str:
    return "visuel-" + composition_empreinte[:16]


def identifiant_fond(sha256: str) -> str:
    return "fond-" + sha256[:16]


def identifiant_logo(sha256: str) -> str:
    return "logo-" + sha256[:16]


# -- pliage ------------------------------------------------------------------------------------------------------
def plier(journal: Any) -> dict[str, EtatActif]:
    """Les états. `JournalIncoherent` si un maillon n'a pas de sens ; la chaîne se vérifie avant (`charger`)."""
    etats: dict[str, EtatActif] = {}
    for rang, m in enumerate(journal_chaine.maillons(journal)):
        type_ = m["type"]
        identifiant = m.get("actif_id")
        courant = etats.get(identifiant)
        if type_ in (M_FOND, M_LOGO, M_COMPOSE):
            if courant is not None:
                raise JournalIncoherent(f"rang {rang} : {identifiant} existe déjà")
            kind = {M_FOND: p.KIND_FOND, M_LOGO: p.KIND_LOGO, M_COMPOSE: p.KIND_VISUEL}[type_]
            etat = {M_FOND: ETAT_FOND_BRUT, M_LOGO: ETAT_LOGO_CONCEPT, M_COMPOSE: ETAT_COMPOSE}[type_]
            donnees = {k: v for k, v in m.items() if k not in ("rang", "type", "horodatage", "chaine")}
            etats[identifiant] = EtatActif(identifiant, kind, etat, donnees, rangs=(rang,))
            continue
        if courant is None:
            raise JournalIncoherent(f"rang {rang} : {type_} sur un actif inconnu {identifiant!r}")
        if type_ == M_CONTROLE:
            if courant.etat not in (ETAT_COMPOSE, ETAT_LOGO_CONCEPT, ETAT_CONTROLE_CONFORME, ETAT_CONTROLE_ECHEC):
                raise JournalIncoherent(f"rang {rang} : contrôle d'un actif {courant.etat}")
            rapport = m["rapport"]
            etat = ETAT_CONTROLE_CONFORME if rapport["conforme"] else ETAT_CONTROLE_ECHEC
            etats[identifiant] = dataclasses.replace(courant, etat=etat, rapport=rapport, rangs=(*courant.rangs, rang))
        elif type_ == M_REVUE:
            if courant.etat != ETAT_CONTROLE_CONFORME:
                raise JournalIncoherent(f"rang {rang} : revue d'un actif {courant.etat}")
            etats[identifiant] = dataclasses.replace(courant, etat=ETAT_EN_REVUE, rangs=(*courant.rangs, rang))
        elif type_ == M_APPROUVE:
            if courant.etat != ETAT_EN_REVUE:
                raise JournalIncoherent(f"rang {rang} : approbation d'un actif {courant.etat}")
            etats[identifiant] = dataclasses.replace(
                courant, etat=ETAT_APPROUVE, approbation=m["approbation"], rangs=(*courant.rangs, rang)
            )
        elif type_ == M_REJETE:
            if courant.etat not in (
                ETAT_CONTROLE_CONFORME,
                ETAT_CONTROLE_ECHEC,
                ETAT_EN_REVUE,
                ETAT_COMPOSE,
                ETAT_LOGO_CONCEPT,
            ):
                raise JournalIncoherent(f"rang {rang} : rejet d'un actif {courant.etat}")
            etats[identifiant] = dataclasses.replace(courant, etat=ETAT_REJETE, rangs=(*courant.rangs, rang))
        elif type_ == M_REVOQUE:
            if courant.etat != ETAT_APPROUVE:
                raise JournalIncoherent(f"rang {rang} : révocation d'un actif {courant.etat}")
            etats[identifiant] = dataclasses.replace(courant, etat=ETAT_REVOQUE, rangs=(*courant.rangs, rang))
        else:
            raise JournalIncoherent(f"rang {rang} : type de maillon inconnu {type_!r}")
    return etats


def charger(journal: Any) -> tuple[dict[str, EtatActif], dict[str, Any] | None]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return {}, _refus(REJ_JOURNAL_ALTERE, "$", "; ".join(problemes[:3]))
    try:
        return plier(journal), None
    except (JournalIncoherent, KeyError, TypeError) as exc:
        return {}, _refus(REJ_JOURNAL_INCOHERENT, "$", str(exc))


def _etat(etats: Mapping[str, EtatActif], actif_id: str) -> EtatActif | dict[str, Any]:
    courant = etats.get(actif_id)
    if courant is None:
        return _refus(REJ_ACTIF_INCONNU, "$.actif_id", f"actif inconnu : {actif_id!r}")
    return courant


# -- écritures ---------------------------------------------------------------------------------------------------
def enregistrer_fond(
    journal: Any,
    *,
    sha256: str,
    format_: str,
    largeur: int,
    hauteur: int,
    genre: str,
    brief_id: str,
    brief_empreinte: str,
    fond_spec_empreinte: str,
    provenance_chaine: str,
    nature_generateur: str,
    fictif: bool,
    par: str,
    horodatage: str,
) -> dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    identifiant = identifiant_fond(sha256)
    if identifiant in etats:
        return {"accepte": True, "actif_id": identifiant, "etat": etats[identifiant].etat, "deja_cree": True}
    journal_chaine.ajouter(
        journal,
        M_FOND,
        {
            "actif_id": identifiant,
            "sha256": sha256,
            "format": format_,
            "largeur": largeur,
            "hauteur": hauteur,
            "genre": genre,
            "brief_id": brief_id,
            "brief_empreinte": brief_empreinte,
            "fond_spec_empreinte": fond_spec_empreinte,
            "provenance_chaine": provenance_chaine,
            "nature_generateur": nature_generateur,
            "ia_generee": True,
            "fictif": fictif,
            "par": par,
        },
        horodatage,
    )
    return {"accepte": True, "actif_id": identifiant, "etat": ETAT_FOND_BRUT, "deja_cree": False}


def enregistrer_composition(
    journal: Any,
    composition: Composition,
    *,
    brief_id: str,
    alt: str,
    par: str,
    horodatage: str,
    fond_actif_id: str | None = None,
    logo_actif_id: str | None = None,
    nature_generateur: str | None = None,
    fournisseur_id: str | None = None,
    mention_licence: str | None = None,
) -> dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    empreinte = composition.empreinte()
    identifiant = identifiant_visuel(empreinte)
    if identifiant in etats:
        return {
            "accepte": True,
            "actif_id": identifiant,
            "etat": etats[identifiant].etat,
            "composition_empreinte": empreinte,
            "deja_cree": True,
        }
    brief = composition.brief
    journal_chaine.ajouter(
        journal,
        M_COMPOSE,
        {
            "actif_id": identifiant,
            "brief_id": brief_id,
            "brief_empreinte": brief.empreinte(),
            "composition_empreinte": empreinte,
            "plan_empreinte": composition.marquage["plan_empreinte"],
            "gabarit": brief.gabarit,
            "format": brief.format,
            "artefacts": {
                fmt: {
                    **infos,
                    "largeur": composition.plan.largeur_px if fmt != "pdf" else None,
                    "hauteur": composition.plan.hauteur_px if fmt != "pdf" else None,
                }
                for fmt, infos in composition.empreintes().items()
            },
            "fond_sha256": composition.marquage["fond_sha256"],
            "fond_actif_id": fond_actif_id,
            "logo_actif_id": logo_actif_id,
            "ia_generee": composition.ia_generee,
            "fictif": brief.fictif,
            "bilingue": "en" in brief.langues,
            "provenance": composition.marquage["provenance"],
            "nature_generateur": nature_generateur,
            "fournisseur_id": fournisseur_id,
            "mention_licence": mention_licence,
            "police_id": composition.police_id,
            "alt": alt[:300],
            "ppp": composition.plan.ppp,
            "par": par,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "actif_id": identifiant,
        "etat": ETAT_COMPOSE,
        "composition_empreinte": empreinte,
        "deja_cree": False,
    }


def enregistrer_logo(
    journal: Any,
    *,
    sha256: str,
    chemins: list[str],
    vb_w: float,
    vb_h: float,
    svg_sha256: str,
    source: str,
    outil: Mapping[str, Any],
    fictif: bool,
    par: str,
    horodatage: str,
    raster_sha256: str | None = None,
) -> dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    identifiant = identifiant_logo(sha256)
    if identifiant in etats:
        return {
            "accepte": True,
            "actif_id": identifiant,
            "etat": etats[identifiant].etat,
            "deja_cree": True,
            "avertissement": AVERTISSEMENT_LOGO,
        }
    journal_chaine.ajouter(
        journal,
        M_LOGO,
        {
            "actif_id": identifiant,
            "sha256": sha256,
            "svg_sha256": svg_sha256,
            "chemins": list(chemins),
            "vb_w": vb_w,
            "vb_h": vb_h,
            "source": source,
            "outil": dict(outil),
            "raster_sha256": raster_sha256,
            "ia_generee": False,
            "fictif": fictif,
            "composition_empreinte": sha256,
            "artefacts": {"svg": {"sha256": svg_sha256, "octets": None, "largeur": None, "hauteur": None}},
            "par": par,
            "avertissement": AVERTISSEMENT_LOGO,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "actif_id": identifiant,
        "etat": ETAT_LOGO_CONCEPT,
        "deja_cree": False,
        "avertissement": AVERTISSEMENT_LOGO,
    }


def enregistrer_controle(
    journal: Any, actif_id: str, rapport: Mapping[str, Any], par: str, horodatage: str
) -> dict[str, Any]:
    """Consigne le rapport d'un contrôle. Il doit être SIGNÉ (empreinte) et porter sur la composition courante."""
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    courant = _etat(etats, actif_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat not in (ETAT_COMPOSE, ETAT_LOGO_CONCEPT, ETAT_CONTROLE_CONFORME, ETAT_CONTROLE_ECHEC):
        return _refus(REJ_ETAT, "$.actif_id", f"actif {courant.etat} : seul un actif composé se contrôle")
    if not controle.verifier_empreinte_rapport(rapport):
        return _refus(REJ_RAPPORT, "$.rapport", "empreinte du rapport absente ou invalide : rapport retouché ou forgé")
    recalcule = all(c["ok"] for c in rapport["constats"] if c["critique"])
    if recalcule != rapport["conforme"]:
        return _refus(REJ_RAPPORT, "$.rapport.conforme", "le verdict ne correspond pas aux constats critiques")
    if rapport["composition_empreinte"] != courant.donnees["composition_empreinte"]:
        return _refus(
            REJ_RAPPORT_ETRANGER, "$.rapport", "ce rapport porte sur une autre composition que celle de l'actif"
        )
    journal_chaine.ajouter(
        journal, M_CONTROLE, {"actif_id": actif_id, "rapport": dict(rapport), "par": par}, horodatage
    )
    return {
        "accepte": True,
        "actif_id": actif_id,
        "etat": ETAT_CONTROLE_CONFORME if rapport["conforme"] else ETAT_CONTROLE_ECHEC,
        "rapport_empreinte": rapport["empreinte"],
        "echecs_critiques": [c["code"] for c in rapport["constats"] if c["critique"] and not c["ok"]],
    }


def demander_revue(journal: Any, actif_id: str, par: str, horodatage: str) -> dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    courant = _etat(etats, actif_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat == ETAT_CONTROLE_ECHEC:
        echecs = [c["code"] for c in courant.rapport["constats"] if c["critique"] and not c["ok"]]
        return _refus(
            REJ_REVUE_NON_CONFORME,
            "$.actif_id",
            f"le contrôle qualité a des constats critiques en échec {echecs} : un visuel non conforme ne "
            "passe pas en revue (corriger le brief, recomposer, recontrôler)",
        )
    if courant.etat != ETAT_CONTROLE_CONFORME:
        return _refus(REJ_ETAT, "$.actif_id", f"actif {courant.etat} : un contrôle conforme est exigé avant la revue")
    journal_chaine.ajouter(
        journal,
        M_REVUE,
        {
            "actif_id": actif_id,
            "composition_empreinte": courant.donnees["composition_empreinte"],
            "rapport_empreinte": courant.rapport["empreinte"],
            "par": par,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "actif_id": actif_id,
        "etat": ETAT_EN_REVUE,
        "composition_empreinte": courant.donnees["composition_empreinte"],
        "rapport_empreinte": courant.rapport["empreinte"],
    }


def _attestations(courant: EtatActif, attestations: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(attestations, Mapping):
        return None, _refus(REJ_ATTESTATION, "$.attestations", "attestations de la personne exigées (objet)")
    if courant.kind == p.KIND_LOGO:
        exigees = ATTESTATIONS_LOGO
        extra = {"note_contribution_humaine", "recherche_anteriorite"}
    else:
        exigees = ATTESTATIONS_VISUEL
        extra = {"realiste", "langue_francaise_validee"}
    inconnus = set(attestations) - set(exigees) - extra
    if inconnus:
        return None, _refus(REJ_ATTESTATION, "$.attestations", f"attestation(s) inconnue(s) : {sorted(inconnus)}")
    for nom in exigees:
        if attestations.get(nom) is not True:
            return None, _refus(
                REJ_ATTESTATION,
                f"$.attestations.{nom}",
                f"« {nom} » doit être attesté (true) par la personne qui approuve",
            )
    propres = {n: True for n in exigees}
    if courant.kind == p.KIND_LOGO:
        note = attestations.get("note_contribution_humaine")
        if not isinstance(note, str) or len(note.strip()) < 20 or len(note) > 600:
            return None, _refus(
                REJ_LOGO,
                "$.attestations.note_contribution_humaine",
                "note de contribution humaine (20 à 600 caractères) exigée : retouches, choix, composition",
            )
        if attestations.get("recherche_anteriorite") not in ANTERIORITE:
            return None, _refus(
                REJ_LOGO,
                "$.attestations.recherche_anteriorite",
                f"recherche d'antériorité : {list(ANTERIORITE)} (aucune promesse de protection)",
            )
        propres.update(
            note_contribution_humaine=note.strip(), recherche_anteriorite=attestations["recherche_anteriorite"]
        )
        return propres, None
    ia = bool(courant.donnees.get("ia_generee"))
    realiste = attestations.get("realiste")
    if type(realiste) is not bool:
        return None, _refus(
            REJ_ATTESTATION,
            "$.attestations.realiste",
            "« realiste » (booléen) : le visuel imite-t-il une photographie réelle ? Décision de la personne",
        )
    if not ia and realiste:
        return None, _refus(
            REJ_ATTESTATION,
            "$.attestations.realiste",
            "un visuel sans fond généré n'est pas « réaliste » au sens de la divulgation d'IA",
        )
    propres["realiste"] = realiste
    valide = attestations.get("langue_francaise_validee") is True
    if courant.donnees.get("bilingue") and not valide:
        return None, _refus(
            REJ_ATTESTATION,
            "$.attestations.langue_francaise_validee",
            "visuel bilingue : la personne atteste que le français est nettement prédominant "
            "(heuristique du contrôle ; à valider par un avocat)",
        )
    propres["langue_francaise_validee"] = valide
    return propres, None


def approuver(
    journal: Any,
    actif_id: str,
    composition_empreinte: str,
    rapport_empreinte: str,
    approbateur: Mapping[str, str] | None,
    attestations: Any,
    horodatage: str,
    *,
    verdict_licence: Callable[[], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    if (
        approbateur is None
        or approbateur.get("role") != ROLE_DECIDEUR
        or not approbateur.get("par")
        or not approbateur.get("source")
    ):
        return _refus(
            REJ_HUMAIN,
            "$",
            "l'approbation d'un visuel pour publication ou impression est une décision humaine du propriétaire (N3)",
        )
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    courant = _etat(etats, actif_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat != ETAT_EN_REVUE:
        return _refus(REJ_ETAT, "$.actif_id", f"actif {courant.etat} : seul un actif en revue s'approuve")
    if composition_empreinte != courant.donnees["composition_empreinte"]:
        return _refus(
            REJ_EMPREINTE, "$.composition_empreinte", "l'empreinte approuvée n'est pas celle de la composition en revue"
        )
    if rapport_empreinte != courant.rapport["empreinte"]:
        return _refus(
            REJ_EMPREINTE, "$.rapport_empreinte", "l'empreinte du rapport n'est pas celle du contrôle en revue"
        )
    propres, refus = _attestations(courant, attestations)
    if refus is not None:
        return refus
    donnees = courant.donnees
    if not donnees.get("fictif"):
        lecteurs = courant.rapport.get("lecteurs") or []
        if not lecteurs or any(x["nature"] != "reel" for x in lecteurs if x["format"] in ("png", "pdf")):
            return _refus(
                REJ_OCR_REEL,
                "$.rapport.lecteurs",
                "un visuel NON fictif ne s'approuve pas sur la lecture d'un double : le contrôle doit avoir "
                "été fait par un lecteur OCR réel (profil Tesseract) — non disponible sur cette machine",
            )
        if donnees.get("nature_generateur") == "double":
            return _refus(
                REJ_GENERATEUR_TEST,
                "$.nature_generateur",
                "le fond vient d'un générateur de TEST : un visuel non fictif n'en peut pas venir",
            )
    if donnees.get("ia_generee"):
        verdict = verdict_licence() if verdict_licence is not None else None
        if verdict is None or not verdict.get("conforme"):
            return _refus(
                REJ_LICENCE,
                "$.licence",
                "licence du modèle non vérifiée ou non conforme au moment de l'approbation : "
                f"{(verdict or {}).get('codes') or 'aucun verdict'}",
            )
    journal_chaine.ajouter(
        journal,
        M_APPROUVE,
        {
            "actif_id": actif_id,
            "composition_empreinte": composition_empreinte,
            "rapport_empreinte": rapport_empreinte,
            "approbation": {
                "par": approbateur["par"],
                "role": approbateur["role"],
                "source": approbateur["source"],
                "attestations": propres,
            },
        },
        horodatage,
    )
    return {
        "accepte": True,
        "actif_id": actif_id,
        "etat": ETAT_APPROUVE,
        "approuve_par": approbateur["par"],
        "attestations": propres,
        "execute": False,
        "usage": "utilisable par le sas social et le site ; aucune publication ni impression n'est lancée ici",
    }


def rejeter(journal: Any, actif_id: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    courant = _etat(etats, actif_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat not in (
        ETAT_CONTROLE_CONFORME,
        ETAT_CONTROLE_ECHEC,
        ETAT_EN_REVUE,
        ETAT_COMPOSE,
        ETAT_LOGO_CONCEPT,
    ):
        return _refus(REJ_ETAT, "$.actif_id", f"actif {courant.etat} : rien à rejeter")
    journal_chaine.ajouter(journal, M_REJETE, {"actif_id": actif_id, "par": par, "motif": motif[:300]}, horodatage)
    return {"accepte": True, "actif_id": actif_id, "etat": ETAT_REJETE}


def revoquer(journal: Any, actif_id: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    courant = _etat(etats, actif_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat != ETAT_APPROUVE:
        return _refus(REJ_ETAT, "$.actif_id", f"actif {courant.etat} : seul un actif approuvé se révoque")
    journal_chaine.ajouter(journal, M_REVOQUE, {"actif_id": actif_id, "par": par, "motif": motif[:300]}, horodatage)
    return {
        "accepte": True,
        "actif_id": actif_id,
        "etat": ETAT_REVOQUE,
        "attention": "un contenu déjà publié avec cet actif ne se retire pas d'ici : à faire à la main",
    }


# -- lecture et portes ---------------------------------------------------------------------------------------------
class ResolveurDuRegistre:
    """`sha256 -> InfoActif` sur l'état courant du registre. `integre` est faux si la chaîne ou un maillon est
    altéré."""

    def __init__(self, journal: Any) -> None:
        etats, refus = charger(journal)
        self.integre = refus is None
        self._index: dict[str, p.InfoActif] = {}
        for etat in etats.values():
            self._indexer(etat)

    def _indexer(self, etat: EtatActif) -> None:
        d = etat.donnees
        attestations = (etat.approbation or {}).get("attestations", {}) if etat.approbation else {}
        if etat.kind == p.KIND_FOND:
            info = p.InfoActif(
                etat.actif_id,
                p.KIND_FOND,
                etat.etat,
                d["format"],
                0,
                d["largeur"],
                d["hauteur"],
                True,
                None,
                bool(d["fictif"]),
                False,
            )
            self._index[d["sha256"]] = info
            return
        for fmt, infos in (d.get("artefacts") or {}).items():
            realiste = (
                attestations.get("realiste")
                if etat.approuve and d.get("ia_generee")
                else (False if d.get("ia_generee") is False else None)
            )
            self._index[infos["sha256"]] = p.InfoActif(
                etat.actif_id,
                etat.kind,
                etat.etat,
                fmt,
                infos.get("octets") or 0,
                infos.get("largeur"),
                infos.get("hauteur"),
                bool(d.get("ia_generee")),
                realiste,
                bool(d.get("fictif")),
                etat.approuve,
            )

    def __call__(self, sha256: str) -> p.InfoActif | None:
        return self._index.get(sha256)


def resolveur_du_registre(journal: Any) -> ResolveurDuRegistre:
    return ResolveurDuRegistre(journal)


def media_pour_sas(journal: Any, actif_id: str, format_: str = "png") -> dict[str, Any]:
    """Le média à placer dans une publication sociale : ce que le REGISTRE dit, jamais ce que l'agent croit."""
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    courant = _etat(etats, actif_id)
    if isinstance(courant, dict):
        return courant
    if courant.kind != p.KIND_VISUEL or not courant.approuve:
        return _refus(
            REJ_ETAT,
            "$.actif_id",
            f"actif {courant.kind} {courant.etat} : seul un visuel approuvé devient un média de publication",
        )
    infos = courant.donnees["artefacts"].get(format_)
    if infos is None or format_ not in ("png",):
        return _refus(REJ_ETAT, "$.format", "le média de publication d'un visuel est son PNG")
    attestations = courant.approbation["attestations"]
    ia = bool(courant.donnees["ia_generee"])
    media = {
        "reference": f"{courant.actif_id}-{format_}",
        "type_media": "image",
        "format": format_,
        "sha256": infos["sha256"],
        "octets": infos["octets"],
        "largeur": infos["largeur"],
        "hauteur": infos["hauteur"],
        "duree_s": None,
        "alt": courant.donnees["alt"],
        "origine": p.ORIGINE_COMPOSEE,
        "ia_generee": ia,
        "realiste": bool(attestations.get("realiste")) if ia else False,
        "moderation": "verifiee" if attestations.get("aucun_visage_ni_plaque_identifiable") else "revue_requise",
        "controle_ocr": "conforme",
    }
    return {"accepte": True, "media": media, "empreinte_actif": courant.donnees["composition_empreinte"]}


def lire(journal: Any, actif_id: str | None = None, limite: int = 20) -> dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    if actif_id is not None:
        courant = _etat(etats, actif_id)
        if isinstance(courant, dict):
            return courant
        return {
            "accepte": True,
            "actif": {
                **courant.resume(),
                "donnees": dict(courant.donnees),
                "rapport": dict(courant.rapport) if courant.rapport else None,
                "approbation": dict(courant.approbation) if courant.approbation else None,
            },
        }
    liste = sorted(etats.values(), key=lambda e: e.rangs[-1], reverse=True)
    return {"accepte": True, "total": len(liste), "actifs": [e.resume() for e in liste[: max(1, min(limite, 50))]]}


def empreinte_actif_logo(chemins: list[str], vb_w: float, vb_h: float) -> str:
    return hashlib.sha256(("opsys-studio-logo/v1\n" + "\n".join(chemins) + f"\n{vb_w}x{vb_h}").encode()).hexdigest()
