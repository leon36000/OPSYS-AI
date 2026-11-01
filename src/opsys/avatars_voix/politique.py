"""Politique de disponibilité d'un canal d'avatar (voix, audiovisuel), par département.

Un canal n'est « disponible » que si TOUTES ces conditions tiennent, jugées à chaque lecture (jamais mémorisées) :

 0. le canal est réalisé : un runtime de transport existe réellement (`avatars.CANAUX_REALISES`) ; aujourd'hui, non ;
 a. un runtime est enregistré, ACTIF, et qualifié par un test de connexion réellement exécuté et journalisé, lié au
    moteur exact configuré (empreinte) ; un double de test ne qualifie jamais ;
 b. la voix (ou la ressemblance du visage) clonée est consentie par écrit, non révoquée, non expirée, pour la portée ;
 c. la licence est conforme au profil du client : `fournisseurs.politique.evaluer` (code ET poids, seuils de revenu,
    territoires, service à des tiers, copyleft, mention, EFVP) ; rien n'est recopié ici ;
 d. aucune empreinte vocale d'un tiers n'est stockée sans déclaration à la CAI, 60 jours avant la mise en service.

S'ajoutent la langue (fr-CA pour une voix), la licence commerciale de l'actif visuel et, pour la voix, un STT
sélectionné pour le département, actif, conforme et qualifié. Tous les refus applicables sont rendus, chacun avec un
code stable `REJ-AVATAR-*` ; aucun repli n'est proposé. Pure lecture : seule `declarer_canal` écrit (canal
« disponible »), et elle n'écrit que si le verdict est conforme.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import Connection, insert, select, update

from .. import avatars, etat
from ..fournisseurs import politique as politique_licence
from ..fournisseurs import registre as registre_fournisseurs
from ..fournisseurs.registre import RegistreErreur
from ..stockage.schema import AVATARS_CANAUX, FOURNISSEURS_CONFIGURATIONS
from . import modele, registre
from .codes import CODES_AVATAR, AvatarRefus

CANAL_VOIX = avatars.CANAL_VOIX
CANAL_AUDIOVISUEL = avatars.CANAL_AUDIOVISUEL
CANAUX_GOUVERNES = (CANAL_VOIX, CANAL_AUDIOVISUEL)

ETAT_DISPONIBLE = "disponible"
ETAT_SUSPENDU = "suspendu"
_RANG_ENTREE = {modele.ETAT_PREVU: 0, modele.ETAT_CONFIGURE: 1, modele.ETAT_QUALIFIE: 2}
_ORDRE = {code: i for i, code in enumerate(CODES_AVATAR)}


@dataclasses.dataclass(frozen=True)
class Refus:
    code: str
    motif: str
    composant: str | None = None
    sous_codes: tuple[str, ...] = ()

    def vers_json(self) -> dict[str, Any]:
        return {"code": self.code, "motif": self.motif, "composant": self.composant,
                "sous_codes": list(self.sous_codes)}


@dataclasses.dataclass(frozen=True)
class Verdict:
    departement: str
    canal: str
    refus: tuple[Refus, ...]
    preuves: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def conforme(self) -> bool:
        return not self.refus

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.code for r in self.refus))

    def exiger(self) -> Verdict:
        """Lève le premier refus (avec tous les codes) si le verdict n'est pas conforme."""
        if self.refus:
            raise AvatarRefus(self.refus[0].code, "; ".join(r.motif for r in self.refus), 409, self.codes)
        return self

    def vers_json(self) -> dict[str, Any]:
        return {"departement": self.departement, "canal": self.canal, "conforme": self.conforme,
                "refus": [r.vers_json() for r in self.refus], "preuves": dict(self.preuves)}


def _refus_qualification(cnx: Connection, fournisseur: Any, composant: str) -> Refus | None:
    derniere = registre.derniere_qualification(cnx, fournisseur.identifiant, modele.empreinte_runtime(fournisseur))
    if derniere is None:
        return Refus("REJ-AVATAR-QUALIFICATION-ABSENTE",
                     f"{fournisseur.identifiant} : aucun test de connexion exécuté sur ce moteur "
                     "(opsys-metier fournisseurs tester, puis la qualification)", composant)
    if derniere["statut"] != "succes":
        return Refus("REJ-AVATAR-QUALIFICATION-ECHEC",
                     f"{fournisseur.identifiant} : le dernier test ({derniere['quand']}) a échoué "
                     f"({derniere['statut']})", composant)
    if derniere["nature"] != registre.NATURE_REELLE:
        return Refus("REJ-AVATAR-QUALIFICATION-SIMULEE",
                     f"{fournisseur.identifiant} : le dernier test réussi n'a tourné qu'avec un double de test "
                     "(aucune sonde réelle) ; il ne qualifie pas", composant)
    return None


def _actif(cnx: Connection, fournisseur_id: str) -> bool:
    return bool(cnx.execute(select(FOURNISSEURS_CONFIGURATIONS.c.actif).where(
        FOURNISSEURS_CONFIGURATIONS.c.identifiant == fournisseur_id)).scalar_one_or_none())


def _refus_licence(fournisseur: Any, profil: Any, composant: str) -> Refus | None:
    decision = politique_licence.evaluer(fournisseur, profil)
    if decision.conforme:
        return None
    detail = " ; ".join(f"{r.code} : {r.motif}" for r in decision.refus)
    return Refus("REJ-AVATAR-LICENCE-NON-CONFORME", f"{fournisseur.identifiant} : {detail}", composant, decision.codes)


def _refus_biometrie(entree: Mapping[str, Any], maintenant: dt.datetime) -> list[Refus]:
    if not entree["empreinte_vocale_tiers"]:
        return []
    declaration = entree["declaration_biometrie"]
    if declaration is None:
        return [Refus("REJ-AVATAR-BIOMETRIE-NON-DECLAREE",
                      f"{entree['identifiant']} : une empreinte vocale de tiers est stockée sans déclaration à la "
                      "CAI (Loi 25) ; refus par défaut", entree["genre"])]
    prete = dt.date.fromisoformat(declaration["declaree_le"]) + dt.timedelta(days=modele.DELAI_BIOMETRIE_JOURS)
    if maintenant.astimezone(dt.UTC).date() < prete:
        return [Refus("REJ-AVATAR-BIOMETRIE-DELAI",
                      f"{entree['identifiant']} : déclaration du {declaration['declaree_le']} ; mise en service "
                      f"possible à partir du {prete.isoformat()} ({modele.DELAI_BIOMETRIE_JOURS} jours)",
                      entree["genre"])]
    return []


def _evaluer_entree(cnx: Connection, identifiant: str, profil: Any, maintenant: dt.datetime,
                    preuves: dict[str, Any]) -> list[Refus]:
    genre = modele.genre_de(identifiant)
    entree = registre.lire_entree(cnx, identifiant)
    if entree is None:
        return [Refus("REJ-AVATAR-ENTREE-ABSENTE",
                      f"{identifiant} n'est pas inscrite au registre des voix et visages du client", genre)]
    refus: list[Refus] = []
    fournisseur = registre.fournisseur_de(cnx, entree["fournisseur_id"])
    if fournisseur is None:
        refus.append(Refus("REJ-AVATAR-RUNTIME-ABSENT",
                           f"{identifiant} : aucun moteur lié (état « {entree['etat']} »)", genre))
    else:
        if fournisseur.capacite != modele.CAPACITE_DU_GENRE[genre]:
            refus.append(Refus("REJ-AVATAR-RUNTIME-CAPACITE",
                               f"{fournisseur.identifiant} sert « {fournisseur.capacite} », pas {genre}", genre))
        if not _actif(cnx, fournisseur.identifiant):
            refus.append(Refus("REJ-AVATAR-RUNTIME-INACTIF",
                               f"{fournisseur.identifiant} est configuré mais non activé", genre))
        courante = modele.empreinte_runtime(fournisseur)
        if entree["manifeste"]["empreinte_runtime"] != courante:
            refus.append(Refus("REJ-AVATAR-MANIFESTE-MODIFIE",
                               f"{fournisseur.identifiant} a changé depuis la liaison de {identifiant} "
                               "(modèle, point d'accès ou licence) : re-lier et re-qualifier", genre))
        else:
            qualification = _refus_qualification(cnx, fournisseur, genre)
            if qualification is not None:
                refus.append(qualification)
        licence = _refus_licence(fournisseur, profil, genre)
        if licence is not None:
            refus.append(licence)
        derniere = registre.derniere_qualification(cnx, fournisseur.identifiant, courante)
        preuves[identifiant] = {"empreinte_manifeste": entree["empreinte_manifeste"], "empreinte_runtime": courante,
                                "qualification_id": None if derniere is None else derniere["id"]}
    refus.extend(Refus(code, motif, genre) for code, motif in registre.refus_de_consentement(cnx, entree, maintenant))
    refus.extend(_refus_biometrie(entree, maintenant))
    if genre == modele.GENRE_VOIX and entree["langue"] != modele.LANGUE_EXIGEE:
        refus.append(Refus("REJ-AVATAR-LANGUE",
                           f"{identifiant} : langue « {entree['langue']} », {modele.LANGUE_EXIGEE} exigée", genre))
    if genre == modele.GENRE_VISAGE and entree["actif_usage_commercial"] != "autorise":
        refus.append(Refus("REJ-AVATAR-ACTIF-NON-COMMERCIAL",
                           f"{identifiant} : licence de l'actif visuel « {entree['actif_usage_commercial']} » ; "
                           "un usage commercial autorisé est exigé", genre))
    return refus


def _evaluer_ecoute(cnx: Connection, departement: str, profil: Any, preuves: dict[str, Any]) -> list[Refus]:
    try:
        resolution = registre_fournisseurs.resoudre(cnx, modele.CAPACITE_ECOUTE, departement)
    except RegistreErreur as exc:
        return [Refus("REJ-AVATAR-STT-INDISPONIBLE",
                      f"aucun STT utilisable pour {departement} ({exc.code}) : sélectionner un fournisseur STT "
                      "actif et conforme", "stt", exc.codes)]
    fournisseur = resolution.fournisseur
    refus: list[Refus] = []
    qualification = _refus_qualification(cnx, fournisseur, "stt")
    if qualification is not None:
        refus.append(qualification)
    licence = _refus_licence(fournisseur, profil, "stt")
    if licence is not None:
        refus.append(licence)
    derniere = registre.derniere_qualification(cnx, fournisseur.identifiant, modele.empreinte_runtime(fournisseur))
    preuves["stt"] = {"fournisseur_id": fournisseur.identifiant,
                      "empreinte_runtime": modele.empreinte_runtime(fournisseur),
                      "qualification_id": None if derniere is None else derniere["id"]}
    return refus


def evaluer_canal(cnx: Connection, identite: avatars.IdentiteEffective, canal: str, *,
                  maintenant: dt.datetime | None = None,
                  canaux_realises: Collection[str] = avatars.CANAUX_REALISES) -> Verdict:
    """Tous les refus applicables à ce canal pour ce département, dans l'ordre stable de `CODES_AVATAR`."""
    if canal not in CANAUX_GOUVERNES:
        raise AvatarRefus("REJ-AVATAR-CANAL-INCONNU", f"canal gouverné parmi {', '.join(CANAUX_GOUVERNES)}", 422)
    quand = maintenant or registre.maintenant_utc()
    refus: list[Refus] = []
    preuves: dict[str, Any] = {}
    if canal not in canaux_realises:
        refus.append(Refus("REJ-AVATAR-CANAL-NON-REALISE",
                           f"le canal « {canal} » n'a aucun runtime livré (transport et worker absents) : "
                           "seuls les canaux réalisés peuvent être disponibles"))
    profil = registre_fournisseurs.lire_profil(cnx)
    composants = [identite.voix] + ([identite.visage] if canal == CANAL_AUDIOVISUEL else [])
    for identifiant in composants:
        refus.extend(_evaluer_entree(cnx, identifiant, profil, quand, preuves))
    refus.extend(_evaluer_ecoute(cnx, identite.departement, profil, preuves))
    tries = tuple(sorted(refus, key=lambda r: _ORDRE[r.code]))
    return Verdict(identite.departement, canal, tries, preuves)


def declarer_canal(cnx: Connection, *, acteur: str, identite: avatars.IdentiteEffective, canal: str,
                   maintenant: dt.datetime | None = None,
                   canaux_realises: Collection[str] = avatars.CANAUX_REALISES) -> Verdict:
    """Déclare le canal « disponible » SI ET SEULEMENT SI le verdict est conforme ; sinon journalise le refus et le
    rend tel quel (comme `fournisseurs.registre.activer`) : rien n'est déclaré à la place."""
    registre.exiger_admin(cnx, acteur)
    verdict = evaluer_canal(cnx, identite, canal, maintenant=maintenant, canaux_realises=canaux_realises)
    quand = registre._iso(registre._quand(maintenant))
    if not verdict.conforme:
        etat.journaliser(cnx, acteur, "avatars.canal.refuse", f"{identite.departement}/{canal}",
                         {"refus": list(verdict.codes)})
        return verdict
    existant = cnx.execute(select(AVATARS_CANAUX).where(
        (AVATARS_CANAUX.c.departement == identite.departement) & (AVATARS_CANAUX.c.canal == canal))).mappings().first()
    preuves = json.dumps(verdict.preuves, sort_keys=True)
    if existant is None:
        cnx.execute(insert(AVATARS_CANAUX).values(
            departement=identite.departement, canal=canal, etat=ETAT_DISPONIBLE, preuves=preuves, revision=1,
            modifie_le=quand, modifie_par=acteur))
    else:
        cnx.execute(update(AVATARS_CANAUX).where(
            (AVATARS_CANAUX.c.departement == identite.departement) & (AVATARS_CANAUX.c.canal == canal)).values(
            etat=ETAT_DISPONIBLE, preuves=preuves, revision=existant["revision"] + 1, modifie_le=quand,
            modifie_par=acteur))
    etat.journaliser(cnx, acteur, "avatars.canal.declarer", f"{identite.departement}/{canal}",
                     {"preuves": verdict.preuves})
    return verdict


def retirer_canal(cnx: Connection, *, acteur: str, departement: str, canal: str,
                  maintenant: dt.datetime | None = None) -> bool:
    """Retire la déclaration « disponible » (décision de l'administrateur) ; vrai si elle existait."""
    registre.exiger_admin(cnx, acteur)
    if canal not in CANAUX_GOUVERNES:
        raise AvatarRefus("REJ-AVATAR-CANAL-INCONNU", f"canal gouverné parmi {', '.join(CANAUX_GOUVERNES)}", 422)
    existant = cnx.execute(select(AVATARS_CANAUX).where(
        (AVATARS_CANAUX.c.departement == departement) & (AVATARS_CANAUX.c.canal == canal))).mappings().first()
    if existant is None or existant["etat"] != ETAT_DISPONIBLE:
        return False
    cnx.execute(update(AVATARS_CANAUX).where(
        (AVATARS_CANAUX.c.departement == departement) & (AVATARS_CANAUX.c.canal == canal)).values(
        etat="retire", revision=existant["revision"] + 1, modifie_le=registre._iso(registre._quand(maintenant)),
        modifie_par=acteur))
    etat.journaliser(cnx, acteur, "avatars.canal.retirer", f"{departement}/{canal}", {})
    return True


def etat_canal(cnx: Connection, identite: avatars.IdentiteEffective, canal: str, *,
               maintenant: dt.datetime | None = None,
               canaux_realises: Collection[str] = avatars.CANAUX_REALISES) -> dict[str, Any]:
    """État EFFECTIF d'un canal : `disponible` seulement si une décision existe ET que la politique tient encore ;
    `suspendu` si elle existe mais ne tient plus (consentement révoqué, moteur modifié...) ; sinon `qualifie`,
    `configure` ou `prevu` d'après les entrées des composants. `refus` dit ce qui manque."""
    verdict = evaluer_canal(cnx, identite, canal, maintenant=maintenant, canaux_realises=canaux_realises)
    declare = cnx.execute(select(AVATARS_CANAUX).where(
        (AVATARS_CANAUX.c.departement == identite.departement) & (AVATARS_CANAUX.c.canal == canal)
        & (AVATARS_CANAUX.c.etat == ETAT_DISPONIBLE))).mappings().first()
    if declare is not None:
        effectif = ETAT_DISPONIBLE if verdict.conforme else ETAT_SUSPENDU
    else:
        identifiants = [identite.voix] + ([identite.visage] if canal == CANAL_AUDIOVISUEL else [])
        rangs = []
        for identifiant in identifiants:
            entree = registre.lire_entree(cnx, identifiant)
            rangs.append(_RANG_ENTREE[entree["etat"]] if entree is not None else 0)
        effectif = {0: modele.ETAT_PREVU, 1: modele.ETAT_CONFIGURE, 2: modele.ETAT_QUALIFIE}[min(rangs)]
    return {"canal": canal, "etat": effectif, "declare": declare is not None,
            "refus": [r.vers_json() for r in verdict.refus], "codes": list(verdict.codes)}
