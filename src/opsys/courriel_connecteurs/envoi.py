"""Envoi sous sas : un envoi est un BROUILLON dont la transmission est N3 (approbation humaine), jamais un appel direct.

Parcours :

1. `creer_brouillon` : validation stricte (adresses, injection d'en-têtes, pièces, garde-fou de texte de sortie),
   contenu SCELLÉ en base (AES-GCM) et lié à une `empreinte` SHA-256 de tout ce qui part (expéditeur, destinataires,
   objet, corps, pièces). L'expéditeur est celui du compte : l'appelant ne le choisit pas.
2. `demander_approbation` : ouvre une demande N3 dans le sas existant (`opsys.approbations.creer_demande`) dont les
   arguments portent l'empreinte, les destinataires, l'objet, le CONTEXTE et les SOURCES (jamais le corps).
3. Un humain décide (`approbations.decider`) : l'outil `opsys_courriel_approuver_envoi` s'exécute dans la transaction
   de la décision, relit le brouillon et le marque `APPROUVE` seulement si l'empreinte approuvée est celle du
   brouillon actuel.
4. `ServiceEnvoi.envoyer` présente un `JetonApprobation` (demande + empreinte) à l'adaptateur, dont la `GardeEnvoiSas`
   le vérifie CONTRE LA BASE DU SAS (demande exécutée, outil, niveau, approbateur humain actif, empreinte, compte),
   puis le CONSOMME par comparaison-échange (`APPROUVE` -> `ENVOI_RESERVE`) AVANT tout appel réseau. Un second essai
   avec le même jeton est refusé (`REJOUEE`) ; un brouillon modifié après approbation retombe en `BROUILLON` et son
   ancienne approbation n'ouvre plus rien ; un destinataire ajouté change l'empreinte.

Un jeton n'est PAS un secret porteur : sa valeur tient à l'état du sas, vérifié à chaque envoi. Une réservation qui n'a
jamais été terminée (arrêt du processus entre la réservation et la réponse) est traitée comme INCERTAINE
(`marquer_reservations_orphelines`) : jamais de réémission automatique.
"""

from __future__ import annotations

import base64
import dataclasses
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, select, update

from .. import approbations, stockage
from .. import garde_fou_texte as gft
from ..contexte import demande_approuvee_en_cours
from ..ingestion_onboarding import scellement
from ..ingestion_onboarding.codes import IngestionErreur
from ..outils import Autonomie, Niveau, Outil
from ..stockage.schema import COURRIEL_BROUILLONS, COURRIEL_COMPTES
from . import comptes
from .erreurs import ErreurCourriel
from .modele import BrouillonSortant, ContenuBrouillon, JetonApprobation, PieceSortante, RecuEnvoi
from .normalisation import detecter_mime, nom_sur
from .port import FournisseurCourriel, Issue

NOM_OUTIL = "opsys_courriel_approuver_envoi"
DEPARTEMENT_PAR_DEFAUT = "m01-front-office"
NATURE_SCELLEMENT = "courriel_brouillon"
DESTINATAIRES_MAX = 50
OBJET_MAX = 300
CORPS_MAX = 100_000
PIECES_MAX = 5
PIECES_OCTETS_MAX = 5 * 1024 * 1024
SOURCES_MAX = 20
CONTEXTE_MAX = 500
MIME_PERMIS = frozenset({
    "application/pdf", "image/png", "image/jpeg", "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})
PROFIL_SORTIE = gft.profil("courriel_sortant", (
    gft.PRIX_MONTANT, gft.DATE_EXECUTION, gft.ENGAGEMENT, gft.AVEU, gft.AVIS_LEGAL,
))
_ADRESSE = re.compile(r"^[A-Za-z0-9._%+'=!#$&*/?^`{|}~-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LIGNE = re.compile(r"[\x00-\x1f\x7f]")
_ID_MESSAGE = re.compile(r"^[^\s<>\x00-\x1f\x7f]{1,255}$")
_RANG = {"N0": 0, "N1": 1, "N2": 2, "N3": 3, "N4": 4, "N5": 5}


def _maintenant() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ============================================================================================ validation
def _adresses(valeurs: Sequence[str], nature: str) -> tuple[str, ...]:
    if isinstance(valeurs, str) or not isinstance(valeurs, Sequence):
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", f"{nature} : liste d'adresses attendue", 422)
    vues = []
    for adresse in valeurs:
        if not isinstance(adresse, str) or _CONTROLE.search(adresse) or "\n" in adresse or "\r" in adresse \
                or not _ADRESSE.fullmatch(adresse):
            raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", f"{nature} : adresse invalide (nue, sans nom ni "
                                 "caractère de contrôle)", 422)
        vues.append(adresse.lower())
    return tuple(dict.fromkeys(vues))


def valider_contenu(compte: dict[str, Any], *, a: Sequence[str], cc: Sequence[str] = (), cci: Sequence[str] = (),
                    objet: str, corps: str, pieces: Sequence[PieceSortante] = (),
                    en_reponse_a: str | None = None, profil: gft.Profil | None = PROFIL_SORTIE) -> ContenuBrouillon:
    destinataires_a, destinataires_cc, destinataires_cci = _adresses(a, "à"), _adresses(cc, "cc"), _adresses(cci, "cci")
    total = len(destinataires_a) + len(destinataires_cc) + len(destinataires_cci)
    if not destinataires_a or total > DESTINATAIRES_MAX:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE",
                             f"au moins un destinataire « à », {DESTINATAIRES_MAX} au plus en tout", 422)
    if (not isinstance(objet, str) or not objet.strip() or len(objet) > OBJET_MAX or "\n" in objet or "\r" in objet
            or _CONTROLE.search(objet)):
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", "objet : une ligne sans caractère de contrôle "
                             f"({OBJET_MAX} au plus)", 422)
    if not isinstance(corps, str) or not corps.strip() or "\x00" in corps:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", "corps vide ou contenant un caractère nul", 422)
    if len(corps) > CORPS_MAX:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-TROP-GROS", f"corps de plus de {CORPS_MAX} caractères", 413)
    if en_reponse_a is not None and (not isinstance(en_reponse_a, str) or not _ID_MESSAGE.fullmatch(en_reponse_a)):
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", "identifiant du message auquel on répond invalide", 422)
    if len(pieces) > PIECES_MAX or sum(len(p.octets) for p in pieces) > PIECES_OCTETS_MAX:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-TROP-GROS",
                             f"{PIECES_MAX} pièces et {PIECES_OCTETS_MAX} octets au plus", 413)
    for piece in pieces:
        if not isinstance(piece, PieceSortante) or piece.mime not in MIME_PERMIS or not piece.octets:
            raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", "pièce jointe : type non permis ou vide", 422)
        if detecter_mime(piece.octets) != piece.mime and not (piece.mime == "text/plain" and
                                                              detecter_mime(piece.octets) == "text/plain"):
            raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE",
                                 "pièce jointe : le type déclaré ne correspond pas aux "
                                 "octets", 422)
        if nom_sur(piece.nom) != piece.nom:
            raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", "pièce jointe : nom de fichier non sûr", 422)
    if profil is not None:
        violations = gft.controler(f"{objet}\n{corps}", profil)
        if violations:
            raise ErreurCourriel("REJ-COURRIEL-BROUILLON-GARDE-FOU",
                                 "texte sortant refusé par le garde-fou : " + gft.motif_de_refus(violations), 422)
    return ContenuBrouillon(compte_id=compte["compte_id"], de=compte["adresse"].lower(), a=destinataires_a,
                            cc=destinataires_cc, cci=destinataires_cci, objet=objet, corps=corps, pieces=tuple(pieces),
                            en_reponse_a=en_reponse_a)


# ============================================================================================ stockage scellé
def _serialiser(contenu: ContenuBrouillon) -> dict[str, Any]:
    return {"compte": contenu.compte_id, "de": contenu.de, "a": list(contenu.a), "cc": list(contenu.cc),
            "cci": list(contenu.cci), "objet": contenu.objet, "corps": contenu.corps, "reponse_a": contenu.en_reponse_a,
            "pieces": [{"nom": p.nom, "mime": p.mime, "b64": base64.b64encode(p.octets).decode("ascii")}
                       for p in contenu.pieces]}


def _deserialiser(donnees: dict[str, Any]) -> ContenuBrouillon:
    return ContenuBrouillon(
        compte_id=donnees["compte"], de=donnees["de"], a=tuple(donnees["a"]), cc=tuple(donnees["cc"]),
        cci=tuple(donnees["cci"]), objet=donnees["objet"], corps=donnees["corps"],
        pieces=tuple(PieceSortante(p["nom"], p["mime"], base64.b64decode(p["b64"])) for p in donnees["pieces"]),
        en_reponse_a=donnees["reponse_a"])


def _identifiant_scelle(brouillon_id: str, revision: int) -> str:
    return f"{brouillon_id}.r{revision}"


def _sceller(brouillon_id: str, revision: int, contenu: ContenuBrouillon) -> dict[str, str]:
    try:
        reference = scellement.reference_cle()
        nonce, chiffre = scellement.sceller_json(reference, NATURE_SCELLEMENT, _identifiant_scelle(brouillon_id,
                                                                                                   revision),
                                                 contenu.empreinte(), _serialiser(contenu))
    except IngestionErreur as exc:
        raise ErreurCourriel("REJ-COURRIEL-COFFRE-INDISPONIBLE", f"scellement du brouillon impossible ({exc.code})",
                             503) from None
    return {"cle_reference": reference, "nonce": nonce, "chiffre": chiffre}


def _ligne(cnx: Connection, brouillon_id: str) -> dict[str, Any]:
    ligne = cnx.execute(select(COURRIEL_BROUILLONS).where(
        COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id)).mappings().first() if isinstance(brouillon_id,
                                                                                              str) else None
    if ligne is None:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INCONNU", "brouillon inconnu", 404)
    return dict(ligne)


def _ouvrir(ligne: dict[str, Any]) -> BrouillonSortant:
    try:
        donnees = scellement.ouvrir_json(ligne["cle_reference"], NATURE_SCELLEMENT,
                                         _identifiant_scelle(ligne["brouillon_id"], ligne["revision"]),
                                         ligne["empreinte"], ligne["nonce"], ligne["chiffre"])
        contenu = _deserialiser(donnees)
    except IngestionErreur:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", "brouillon scellé illisible ou altéré", 409) from None
    except (KeyError, TypeError, ValueError):
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", "brouillon scellé mal formé", 409) from None
    if contenu.empreinte() != ligne["empreinte"]:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INVALIDE", "empreinte du brouillon incohérente avec son contenu",
                             409)
    return BrouillonSortant(ligne["brouillon_id"], ligne["revision"], contenu, ligne["empreinte"])


def _acteur(acteur: Any) -> str:
    if not isinstance(acteur, str) or not acteur.strip() or len(acteur) > 200 or not acteur.isprintable():
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "acteur invalide", 422)
    return acteur


# ============================================================================================ brouillons
def creer_brouillon(cnx: Connection, acteur: str, compte_id: str, *, profil: gft.Profil | None = PROFIL_SORTIE,
                    **champs: Any) -> BrouillonSortant:
    acteur = _acteur(acteur)
    compte = comptes.lire(cnx, compte_id)
    if compte["usage"] != "lecture_envoi":
        raise ErreurCourriel("REJ-COURRIEL-ENVOI-NON-SUPPORTE", "ce compte est en lecture seule (aucune portée d'envoi "
                             "demandée)", 403)
    if compte["etat"] != "connecte":
        raise ErreurCourriel("REJ-COURRIEL-COMPTE-INACTIF", f"compte non connecté ({compte['etat']})", 409)
    contenu = valider_contenu(compte, profil=profil, **champs)
    brouillon_id = uuid.uuid4().hex
    scelle = _sceller(brouillon_id, 1, contenu)
    maintenant = _maintenant()
    cnx.execute(COURRIEL_BROUILLONS.insert().values(
        brouillon_id=brouillon_id, compte_id=compte_id, revision=1, statut="BROUILLON", empreinte=contenu.empreinte(),
        demande_id=None, approuve_par=None, cree_par=acteur, cree_le=maintenant, modifie_le=maintenant, **scelle))
    comptes.journaliser(cnx, compte_id, "brouillon.cree", acteur,
                        details={"brouillon_id": brouillon_id, "revision": 1, "empreinte": contenu.empreinte()})
    return BrouillonSortant(brouillon_id, 1, contenu, contenu.empreinte())


def lire_brouillon(cnx: Connection, brouillon_id: str) -> BrouillonSortant:
    return _ouvrir(_ligne(cnx, brouillon_id))


def statut_brouillon(cnx: Connection, brouillon_id: str) -> dict[str, Any]:
    ligne = _ligne(cnx, brouillon_id)
    return {k: ligne[k] for k in ("brouillon_id", "compte_id", "revision", "statut", "empreinte", "demande_id",
                                  "approuve_par", "code", "cree_par", "cree_le", "termine_le")}


def modifier_brouillon(cnx: Connection, acteur: str, brouillon_id: str, *, revision_attendue: int,
                       profil: gft.Profil | None = PROFIL_SORTIE, **champs: Any) -> BrouillonSortant:
    """Nouvelle révision du contenu (champs fournis remplacent les anciens). Toute approbation déjà obtenue ou demandée
    pour l'ancienne empreinte est CADUQUE : le brouillon retombe en `BROUILLON`."""
    acteur = _acteur(acteur)
    ligne = _ligne(cnx, brouillon_id)
    if ligne["revision"] != revision_attendue:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-ETAT", f"révision courante {ligne['revision']}", 409)
    if ligne["statut"] in {"ENVOI_RESERVE", "ENVOYE", "INCERTAIN", "ECHEC", "REFUSE"}:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-ETAT",
                             f"brouillon figé ({ligne['statut']}) : en créer un nouveau", 409)
    ancien = _ouvrir(ligne).contenu
    compte = comptes.lire(cnx, ligne["compte_id"])
    base = {"a": ancien.a, "cc": ancien.cc, "cci": ancien.cci, "objet": ancien.objet, "corps": ancien.corps,
            "pieces": ancien.pieces, "en_reponse_a": ancien.en_reponse_a}
    inconnus = set(champs) - set(base)
    if inconnus:
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", f"champs inconnus : {sorted(inconnus)}", 422)
    contenu = valider_contenu(compte, profil=profil, **{**base, **champs})
    revision = ligne["revision"] + 1
    scelle = _sceller(brouillon_id, revision, contenu)
    resultat = cnx.execute(update(COURRIEL_BROUILLONS).where(
        COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id, COURRIEL_BROUILLONS.c.revision == ligne["revision"],
        COURRIEL_BROUILLONS.c.statut.in_(["BROUILLON", "DEMANDE", "APPROUVE"])).values(
        revision=revision, statut="BROUILLON", empreinte=contenu.empreinte(), demande_id=None, approuve_par=None,
        modifie_le=_maintenant(), **scelle))
    if resultat.rowcount != 1:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-ETAT", "brouillon modifié ou envoyé entre-temps", 409)
    comptes.journaliser(cnx, ligne["compte_id"], "brouillon.modifie", acteur, details={
        "brouillon_id": brouillon_id, "revision": revision, "empreinte": contenu.empreinte(),
        "etat": "approbation_caduque" if ligne["statut"] in {"DEMANDE", "APPROUVE"} else ligne["statut"]})
    return BrouillonSortant(brouillon_id, revision, contenu, contenu.empreinte())


# ============================================================================================ demande au sas
def demander_approbation(cnx: Connection, acteur: str, brouillon_id: str, *, contexte: str, sources: Sequence[str],
                         departement: str = DEPARTEMENT_PAR_DEFAUT) -> str:
    acteur = _acteur(acteur)
    if not isinstance(contexte,
                      str) or not contexte.strip() or len(contexte) > CONTEXTE_MAX or _CONTROLE.search(contexte):
        raise ErreurCourriel("REJ-COURRIEL-APPROBATION-INVALIDE",
                             f"contexte requis ({CONTEXTE_MAX} caractères au plus) : pourquoi ce message", 422)
    if (isinstance(sources, str) or not sources or len(sources) > SOURCES_MAX
            or any(not isinstance(s, str) or not s.strip() or len(s) > 120 or _LIGNE.search(s) for s in sources)):
        raise ErreurCourriel("REJ-COURRIEL-APPROBATION-INVALIDE",
                             f"sources requises (1 à {SOURCES_MAX}) : sur quoi le message s'appuie", 422)
    ligne = _ligne(cnx, brouillon_id)
    if ligne["statut"] != "BROUILLON":
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-ETAT", f"demande impossible depuis l'état {ligne['statut']}", 409)
    brouillon = _ouvrir(ligne)
    c = brouillon.contenu
    arguments = {
        "brouillon_id": brouillon_id, "revision": ligne["revision"], "empreinte": ligne["empreinte"],
        "compte_id": ligne["compte_id"], "departement": departement,
        "destinataires": {"a": list(c.a), "cc": list(c.cc), "cci": list(c.cci)}, "objet": c.objet,
        "nb_pieces_jointes": len(c.pieces), "contexte": contexte.strip(), "sources": list(sources),
    }
    demande_id = approbations.creer_demande(
        cnx, departement, NOM_OUTIL, arguments, niveau=Niveau.N3,
        motif=f"Envoi d'un courriel à {len(c.a) + len(c.cc) + len(c.cci)} destinataire(s) : "
              "validation humaine requise (N3)")
    resultat = cnx.execute(update(COURRIEL_BROUILLONS).where(
        COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id, COURRIEL_BROUILLONS.c.statut == "BROUILLON",
        COURRIEL_BROUILLONS.c.revision == ligne["revision"]).values(
        statut="DEMANDE", demande_id=demande_id, modifie_le=_maintenant()))
    if resultat.rowcount != 1:
        raise ErreurCourriel("REJ-COURRIEL-BROUILLON-ETAT", "brouillon modifié entre-temps", 409)
    comptes.journaliser(cnx, ligne["compte_id"], "brouillon.demande", acteur, details={
        "brouillon_id": brouillon_id, "revision": ligne["revision"], "demande_id": demande_id,
        "empreinte": ligne["empreinte"]})
    return demande_id


# ============================================================================================ l'outil du sas
def _approuver(*, brouillon_id: str, revision: int, empreinte: str, compte_id: str, departement: str,
               **_: Any) -> dict[str, Any]:
    """S'exécute DANS `approbations.decider`, après la décision humaine : ne fait que marquer le brouillon approuvé
    s'il est toujours celui qui a été soumis. N'envoie rien."""
    cnx = stockage.connexion_courante()
    demande_id = demande_approuvee_en_cours()
    humain = approbations.approbateur_en_cours(cnx, NOM_OUTIL, departement)
    if cnx is None or demande_id is None or humain is None:
        return {"accepte": False, "verdict": {"code": "REJ-COURRIEL-APPROBATION-NON-APPROUVEE",
                                              "detail": "aucune approbation humaine en cours pour cet outil"}}
    ligne = cnx.execute(select(COURRIEL_BROUILLONS).where(
        COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id)).mappings().first()
    if (ligne is None or ligne["compte_id"] != compte_id or ligne["statut"] != "DEMANDE"
            or ligne["demande_id"] != demande_id or ligne["revision"] != revision or ligne["empreinte"] != empreinte):
        return {"accepte": False, "verdict": {
            "code": "REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE",
            "detail": "le brouillon a changé depuis la demande : une nouvelle demande est requise"}}
    cnx.execute(update(COURRIEL_BROUILLONS).where(
        COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id, COURRIEL_BROUILLONS.c.statut == "DEMANDE").values(
        statut="APPROUVE", approuve_par=humain.personne, modifie_le=_maintenant()))
    comptes.journaliser(cnx, compte_id, "brouillon.approuve", humain.personne, details={
        "brouillon_id": brouillon_id, "revision": revision, "demande_id": demande_id, "empreinte": empreinte})
    return {"accepte": True, "resultat": {"brouillon_id": brouillon_id, "statut": "APPROUVE", "empreinte": empreinte}}


OUTIL_APPROBATION = Outil(
    nom=NOM_OUTIL,
    description="Approuve l'envoi d'un brouillon de courriel précis (empreinte liée au contenu). N'envoie rien : "
                "l'envoi est fait ensuite, une seule fois, avec le jeton d'approbation.",
    parametres={"type": "object", "additionalProperties": False, "required": [
        "brouillon_id", "revision", "empreinte", "compte_id", "departement"], "properties": {
        "brouillon_id": {"type": "string"}, "revision": {"type": "integer"}, "empreinte": {"type": "string"},
        "compte_id": {"type": "string"}, "departement": {"type": "string"}, "destinataires": {"type": "object"},
        "objet": {"type": "string"}, "nb_pieces_jointes": {"type": "integer"}, "contexte": {"type": "string"},
        "sources": {"type": "array"}}},
    fonction=_approuver, autonomie=Autonomie.T1, niveau=Niveau.N3,
)


# ============================================================================================ garde d'envoi
@dataclasses.dataclass(frozen=True)
class ReservationSas:
    brouillon_id: str
    demande_id: str
    compte_id: str


class GardeEnvoiSas:
    """Vérifie un `JetonApprobation` contre la base du sas et le consomme AVANT l'envoi (transaction validée avant le
    réseau)."""

    def __init__(self, fabrique: Any) -> None:
        self._fabrique = fabrique

    def reserver(self, brouillon: BrouillonSortant, jeton: JetonApprobation, fournisseur: str) -> ReservationSas:
        erreur: ErreurCourriel | None = None
        reservation: ReservationSas | None = None
        with self._fabrique() as cnx:
            try:
                reservation = self._reserver(cnx, brouillon, jeton, fournisseur)
            except ErreurCourriel as exc:
                comptes.journaliser(cnx, brouillon.contenu.compte_id, "envoi.refuse", "systeme", code=exc.code,
                                    details={"brouillon_id": brouillon.brouillon_id[:64]})
                erreur = exc  # la trace du refus est VALIDÉE ; aucune réservation n'a été posée
        if erreur is not None:
            raise erreur
        assert reservation is not None
        return reservation

    @staticmethod
    def _reserver(cnx: Connection, brouillon: BrouillonSortant, jeton: JetonApprobation,
                  fournisseur: str) -> ReservationSas:
        if not isinstance(jeton.demande_id, str) or not jeton.demande_id.strip():
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-ABSENTE", "jeton d'approbation vide", 403)
        demande = approbations.lire(cnx, jeton.demande_id)
        if demande is None:
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-ABSENTE", "demande d'approbation inconnue du sas", 403)
        if demande["outil"] != NOM_OUTIL or _RANG.get(demande.get("niveau") or "", -1) < _RANG["N3"]:
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-INVALIDE",
                                 "cette demande n'approuve pas un envoi de courriel (N3)",
                                 403)
        if demande["statut"] != "executee":
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-NON-APPROUVEE",
                                 f"demande {demande['statut']} : seule une demande exécutée autorise l'envoi", 403)
        humain = approbations.signataire_valide(cnx, approbations.IdentiteAppelante(
            personne=demande.get("decide_par") or "", role=demande.get("decide_role") or ""))
        if humain is None or humain.role in approbations.ROLES_NON_HUMAINS:
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-INVALIDE", "approbateur non humain ou inactif", 403)
        arguments = demande["arguments"]
        if brouillon.empreinte != jeton.empreinte:
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE",
                                 "le brouillon présenté n'est pas celui qui a été approuvé", 403)
        if (arguments.get("empreinte") != jeton.empreinte or arguments.get("brouillon_id") != brouillon.brouillon_id
                or arguments.get("compte_id") != brouillon.contenu.compte_id
                or arguments.get("revision") != brouillon.revision):
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-INVALIDE",
                                 "le jeton ne correspond pas à la demande approuvée", 403)
        ligne = cnx.execute(select(COURRIEL_BROUILLONS).where(
            COURRIEL_BROUILLONS.c.brouillon_id == brouillon.brouillon_id)).mappings().first()
        if ligne is None:
            raise ErreurCourriel("REJ-COURRIEL-BROUILLON-INCONNU", "brouillon inconnu", 404)
        if ligne["empreinte"] != brouillon.empreinte or ligne["revision"] != brouillon.revision:
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE",
                                 "le brouillon enregistré a changé depuis l'approbation", 403)
        if ligne["demande_id"] != jeton.demande_id:
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-INVALIDE", "demande non liée à ce brouillon", 403)
        if ligne["statut"] in {"ENVOI_RESERVE", "ENVOYE", "ECHEC", "INCERTAIN"}:
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-REJOUEE", "ce jeton a déjà été utilisé", 409)
        compte = cnx.execute(select(COURRIEL_COMPTES.c.etat, COURRIEL_COMPTES.c.usage, COURRIEL_COMPTES.c.fournisseur)
                             .where(COURRIEL_COMPTES.c.compte_id == ligne["compte_id"])).mappings().first()
        if compte is None or compte["etat"] != "connecte" or compte["usage"] != "lecture_envoi" \
                or compte["fournisseur"] != fournisseur:
            raise ErreurCourriel("REJ-COURRIEL-COMPTE-INACTIF", "compte non connecté en envoi", 409)
        resultat = cnx.execute(update(COURRIEL_BROUILLONS).where(
            COURRIEL_BROUILLONS.c.brouillon_id == brouillon.brouillon_id, COURRIEL_BROUILLONS.c.statut == "APPROUVE",
            COURRIEL_BROUILLONS.c.demande_id == jeton.demande_id,
            COURRIEL_BROUILLONS.c.empreinte == brouillon.empreinte,
        ).values(statut="ENVOI_RESERVE", modifie_le=_maintenant()))
        if resultat.rowcount != 1:
            raise ErreurCourriel("REJ-COURRIEL-BROUILLON-ETAT", "brouillon non approuvé ou déjà pris en charge", 409)
        comptes.journaliser(cnx, ligne["compte_id"], "envoi.reserve", humain.personne, details={
            "brouillon_id": brouillon.brouillon_id, "demande_id": jeton.demande_id, "empreinte": brouillon.empreinte,
            "fournisseur": fournisseur})
        return ReservationSas(brouillon.brouillon_id, jeton.demande_id, ligne["compte_id"])

    def terminer(self, reservation: ReservationSas, issue: Issue, code: str | None = None) -> None:
        etats = {"envoye": "ENVOYE", "echec": "ECHEC", "incertain": "INCERTAIN", "non_traite": "APPROUVE"}
        statut = etats[issue]
        with self._fabrique() as cnx:
            valeurs: dict[str, Any] = {"statut": statut, "modifie_le": _maintenant(), "code": code}
            if issue != "non_traite":
                valeurs["termine_le"] = _maintenant()
            cnx.execute(update(COURRIEL_BROUILLONS).where(
                COURRIEL_BROUILLONS.c.brouillon_id == reservation.brouillon_id,
                COURRIEL_BROUILLONS.c.statut == "ENVOI_RESERVE").values(**valeurs))
            comptes.journaliser(cnx, reservation.compte_id, f"envoi.{issue}", "systeme", code=code, details={
                "brouillon_id": reservation.brouillon_id, "demande_id": reservation.demande_id})


def marquer_reservations_orphelines(cnx: Connection, *, plus_vieilles_que_s: int = 900) -> int:
    """Une réservation jamais terminée (processus arrêté entre la réservation et la réponse) est INCERTAINE : le
    message a peut-être été remis. Elle n'est jamais rejouée ; un humain vérifie la boîte « Envoyés »."""
    limite = (datetime.now(UTC) - timedelta(seconds=plus_vieilles_que_s)).isoformat(timespec="seconds")
    lignes = cnx.execute(select(COURRIEL_BROUILLONS.c.brouillon_id, COURRIEL_BROUILLONS.c.compte_id).where(
        COURRIEL_BROUILLONS.c.statut == "ENVOI_RESERVE", COURRIEL_BROUILLONS.c.modifie_le < limite)).all()
    for brouillon_id, compte_id in lignes:
        cnx.execute(update(COURRIEL_BROUILLONS).where(COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id).values(
            statut="INCERTAIN", code="REJ-COURRIEL-ENVOI-INCERTAIN", termine_le=_maintenant(),
            modifie_le=_maintenant()))
        comptes.journaliser(cnx, compte_id, "envoi.incertain", "systeme", code="REJ-COURRIEL-ENVOI-INCERTAIN",
                            details={"brouillon_id": brouillon_id, "reprise": True})
    return len(lignes)


# ============================================================================================ service d'envoi
class ServiceEnvoi:
    """Point d'entrée applicatif : relit le brouillon approuvé et le présente à l'adaptateur avec son jeton."""

    def __init__(self, fabrique: Any) -> None:
        self._fabrique = fabrique

    def envoyer(self, fournisseur: FournisseurCourriel, brouillon_id: str) -> RecuEnvoi:
        with self._fabrique() as cnx:
            ligne = _ligne(cnx, brouillon_id)
            if ligne["statut"] != "APPROUVE" or not ligne["demande_id"]:
                raise ErreurCourriel("REJ-COURRIEL-APPROBATION-NON-APPROUVEE",
                                     f"brouillon {ligne['statut']} : approbation humaine requise (N3)", 403)
            brouillon = _ouvrir(ligne)
        return fournisseur.envoyer_brouillon(brouillon, JetonApprobation(ligne["demande_id"], ligne["empreinte"]))
