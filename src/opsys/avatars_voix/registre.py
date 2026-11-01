"""Registre par client des voix et visages : entrées, consentements écrits révocables, qualifications exécutées.

Toutes les écritures exigent une personne active `nathan_owner`/`admin` (relue en base), sont journalisées dans le
journal d'audit (`etat.journaliser`) et refusent par un code typé `REJ-AVATAR-*` (`codes.CODES_AVATAR`). Aucune donnée
vocale ni biométrique n'est stockée : un consentement garde la RÉFÉRENCE du contrat signé et l'empreinte SHA-256 du
document, une entrée garde un manifeste (identité du moteur) et son empreinte.

Le moteur de licence n'est pas dupliqué : une entrée désigne un fournisseur du registre (`opsys.fournisseurs`), dont la
définition porte la licence du code ET des poids, les seuils de revenu, les territoires et le droit de service à des
tiers ; `politique.evaluer_canal` appelle `fournisseurs.politique.evaluer` sur cette définition.

Le test de connexion est celui du registre de fournisseurs (`fournisseurs.registre.tester` : politique d'abord, secret
résolu au dernier moment, sonde hors transaction, détail masqué). Ce module y ajoute le JOURNAL de ce qui a réellement
été exécuté (`avatars_qualifications`, append-only), lié à l'empreinte du moteur testé, avec la `nature` de la sonde :
`reel` pour la sonde du serveur, `double` dès qu'un double de test est injecté. Un double ne qualifie jamais.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import Connection, insert, select, update

from .. import etat, identite
from ..fournisseurs import registre as registre_fournisseurs
from ..fournisseurs import sondes
from ..fournisseurs.modele import Fournisseur
from ..fournisseurs.registre import RegistreErreur
from ..secrets_coffre import coffre
from ..stockage.schema import (
    AVATARS_CONSENTEMENTS,
    AVATARS_ENTREES,
    AVATARS_QUALIFICATIONS,
    FOURNISSEURS_CONFIGURATIONS,
)
from . import modele
from .codes import AvatarRefus
from .modele import ETAT_CONFIGURE, ETAT_PREVU, ETAT_QUALIFIE

FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]
NATURE_REELLE = "reel"
NATURE_DOUBLE = "double"
MOTIF_MAX = 200


def maintenant_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _quand(maintenant: dt.datetime | None) -> dt.datetime:
    valeur = maintenant or maintenant_utc()
    if valeur.tzinfo is None:
        raise AvatarRefus("REJ-AVATAR-DECLARATION-INVALIDE", "horodatage avec fuseau requis", 422)
    return valeur.astimezone(dt.UTC)


def _iso(maintenant: dt.datetime) -> str:
    return maintenant.isoformat(timespec="seconds")


def exiger_admin(cnx: Connection, acteur: str) -> None:
    personne = identite.personne_active(cnx, acteur) if isinstance(acteur, str) else None
    if personne is None:
        raise AvatarRefus("REJ-AVATAR-ADMIN-REQUIS", "authentification requise", 401)
    if not personne.roles.intersection(coffre.ROLES_ADMIN):
        raise AvatarRefus("REJ-AVATAR-ADMIN-REQUIS",
                          "administration réservée au propriétaire ou à un administrateur", 403)


# -- lecture ----------------------------------------------------------------------------------------------
def _ligne_entree(cnx: Connection, identifiant: str) -> Mapping[str, Any] | None:
    return cnx.execute(select(AVATARS_ENTREES).where(AVATARS_ENTREES.c.identifiant == identifiant)).mappings().first()


def _entree_depuis_ligne(ligne: Mapping[str, Any]) -> dict[str, Any]:
    donnees = dict(ligne)
    donnees["manifeste"] = json.loads(donnees["manifeste"])
    declaration = donnees["declaration_biometrie"]
    donnees["declaration_biometrie"] = json.loads(declaration) if declaration else None
    return donnees


def lire_entree(cnx: Connection, identifiant: str) -> dict[str, Any] | None:
    ligne = _ligne_entree(cnx, identifiant) if isinstance(identifiant, str) else None
    return None if ligne is None else _entree_depuis_ligne(ligne)


def lister_entrees(cnx: Connection) -> list[dict[str, Any]]:
    return [_entree_depuis_ligne(ligne) for ligne in cnx.execute(
        select(AVATARS_ENTREES).order_by(AVATARS_ENTREES.c.identifiant)).mappings()]


def _entree_ou_refus(cnx: Connection, identifiant: str) -> Mapping[str, Any]:
    modele.genre_de(identifiant)
    ligne = _ligne_entree(cnx, identifiant)
    if ligne is None:
        raise AvatarRefus("REJ-AVATAR-ENTREE-INCONNUE", f"{identifiant} n'est pas inscrite au registre", 404)
    return ligne


def fournisseur_de(cnx: Connection, fournisseur_id: str | None) -> Fournisseur | None:
    """Définition COURANTE du fournisseur configuré ; None si absent ou non configuré en base."""
    if not fournisseur_id:
        return None
    configure = cnx.execute(select(FOURNISSEURS_CONFIGURATIONS.c.identifiant).where(
        FOURNISSEURS_CONFIGURATIONS.c.identifiant == fournisseur_id)).first()
    return registre_fournisseurs.definition(cnx, fournisseur_id) if configure is not None else None


# -- entrées ----------------------------------------------------------------------------------------------
def inscrire_entree(cnx: Connection, *, acteur: str, identifiant: str, langue: str = modele.LANGUE_EXIGEE,
                    accent: str | None = None, origine: str = modele.ORIGINE_GENERIQUE,
                    actif_usage_commercial: str | None = None, empreinte_vocale_tiers: bool = False,
                    revision_attendue: int = 0, maintenant: dt.datetime | None = None) -> dict[str, Any]:
    """Inscrit (ou met à jour, par révision optimiste) l'entrée d'un identifiant logique. Sans runtime, l'état est
    « prevu » : rien ne dit encore quel moteur donnera cette voix ou ce visage."""
    exiger_admin(cnx, acteur)
    genre = modele.genre_de(identifiant)
    langue = modele.valider_langue(langue)
    accent = modele.valider_accent(accent)
    origine = modele.valider_origine(genre, origine)
    actif_usage_commercial = modele.valider_usage_actif(genre, actif_usage_commercial)
    if genre == modele.GENRE_VISAGE and (empreinte_vocale_tiers or accent):
        raise modele.refus_declaration("un visage n'a ni accent ni empreinte vocale")
    if type(empreinte_vocale_tiers) is not bool:
        raise modele.refus_declaration("empreinte_vocale_tiers est un booléen")
    quand = _iso(_quand(maintenant))
    ligne = _ligne_entree(cnx, identifiant)
    revision = 0 if ligne is None else ligne["revision"]
    if revision_attendue != revision:
        raise AvatarRefus("REJ-AVATAR-CONFLIT-REVISION", f"entrée modifiée entre-temps (révision {revision})")
    fournisseur = fournisseur_de(cnx, ligne["fournisseur_id"]) if ligne is not None else None
    contenu = modele.manifeste(
        identifiant=identifiant, genre=genre, langue=langue, accent=accent, origine=origine,
        actif_usage_commercial=actif_usage_commercial, empreinte_vocale_tiers=empreinte_vocale_tiers,
        fournisseur=fournisseur)
    valeurs = {
        "genre": genre, "langue": langue, "accent": accent, "origine": origine,
        "actif_usage_commercial": actif_usage_commercial, "empreinte_vocale_tiers": empreinte_vocale_tiers,
        "manifeste": json.dumps(contenu, ensure_ascii=False, sort_keys=True),
        "empreinte_manifeste": modele.empreinte_manifeste(contenu),
        "revision": revision + 1, "modifie_le": quand, "modifie_par": acteur,
    }
    if ligne is None:
        cnx.execute(insert(AVATARS_ENTREES).values(
            identifiant=identifiant, fournisseur_id=None, declaration_biometrie=None, etat=ETAT_PREVU,
            cree_le=quand, **valeurs))
    else:
        cnx.execute(update(AVATARS_ENTREES).where(AVATARS_ENTREES.c.identifiant == identifiant).values(**valeurs))
    etat.journaliser(cnx, acteur, "avatars.entree.inscrire", identifiant,
                     {"revision": revision + 1, "origine": origine, "langue": langue,
                      "empreinte_manifeste": valeurs["empreinte_manifeste"]})
    entree = lire_entree(cnx, identifiant)
    assert entree is not None
    return entree


def declarer_biometrie(cnx: Connection, *, acteur: str, identifiant: str, reference: str, declaree_le: str,
                       maintenant: dt.datetime | None = None) -> dict[str, Any]:
    """Consigne la déclaration à la CAI d'une banque de caractéristiques biométriques (empreinte vocale) : référence
    du dépôt et date. La date ne peut pas être dans le futur ; le délai de 60 jours est jugé par la politique."""
    exiger_admin(cnx, acteur)
    ligne = _entree_ou_refus(cnx, identifiant)
    if ligne["genre"] != modele.GENRE_VOIX:
        raise modele.refus_declaration("une déclaration biométrique ne vise qu'une voix")
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 200 or not reference.isprintable():
        raise modele.refus_declaration("reference : référence du dépôt à la CAI (texte imprimable)")
    date = modele.valider_date(declaree_le, "declaree_le")
    quand = _quand(maintenant)
    if dt.date.fromisoformat(date) > quand.date():
        raise modele.refus_declaration("declaree_le ne peut pas être dans le futur")
    cnx.execute(update(AVATARS_ENTREES).where(AVATARS_ENTREES.c.identifiant == identifiant).values(
        declaration_biometrie=json.dumps({"reference": reference.strip(), "declaree_le": date}, sort_keys=True),
        revision=ligne["revision"] + 1, modifie_le=_iso(quand), modifie_par=acteur))
    etat.journaliser(cnx, acteur, "avatars.biometrie.declarer", identifiant, {"declaree_le": date})
    entree = lire_entree(cnx, identifiant)
    assert entree is not None
    return entree


# -- consentements ----------------------------------------------------------------------------------------
def enregistrer_consentement(cnx: Connection, *, acteur: str, identifiant: str, locuteur_ref: str,
                             portee: Any, document_ref: str, document_sha256: str, signe_le: str,
                             expire_le: str | None = None, forme: str = modele.FORME_ECRITE,
                             maintenant: dt.datetime | None = None) -> dict[str, Any]:
    """Enregistre un consentement ÉCRIT (voix clonée, ressemblance d'un visage). Un consentement verbal est refusé."""
    exiger_admin(cnx, acteur)
    if forme != modele.FORME_ECRITE:
        raise AvatarRefus("REJ-AVATAR-CONSENTEMENT-NON-ECRIT",
                          "seul un consentement écrit (contrat signé) est enregistré ; un accord verbal ne suffit pas",
                          422)
    ligne = _entree_ou_refus(cnx, identifiant)
    if ligne["origine"] == modele.ORIGINE_GENERIQUE:
        raise modele.refus_declaration("origine générique : aucun consentement de locuteur à enregistrer")
    locuteur = modele.valider_locuteur(locuteur_ref)
    elements = modele.valider_portee(portee)
    permises = modele.PORTEES_REQUISES[(ligne["genre"], ligne["origine"])]
    if not set(elements) <= permises:
        raise modele.refus_declaration(f"portee d'un(e) {ligne['genre']} : {', '.join(sorted(permises))}")
    reference, empreinte = modele.valider_document(document_ref, document_sha256)
    signature = modele.valider_date(signe_le, "signe_le")
    quand = _quand(maintenant)
    aujourdhui = quand.date()
    if dt.date.fromisoformat(signature) > aujourdhui:
        raise modele.refus_declaration("signe_le ne peut pas être dans le futur")
    fin = None
    if expire_le is not None:
        fin = modele.valider_date(expire_le, "expire_le")
        if fin <= signature:
            raise modele.refus_declaration("expire_le doit suivre signe_le")
        if dt.date.fromisoformat(fin) < aujourdhui:
            raise modele.refus_declaration("expire_le est déjà passé : consentement sans effet")
    ident = uuid.uuid4().hex
    cnx.execute(insert(AVATARS_CONSENTEMENTS).values(
        consentement_id=ident, identifiant=identifiant, locuteur_ref=locuteur, portee=json.dumps(list(elements)),
        forme=forme, document_ref=reference, document_sha256=empreinte, signe_le=signature, expire_le=fin,
        enregistre_le=_iso(quand), enregistre_par=acteur))
    etat.journaliser(cnx, acteur, "avatars.consentement.enregistrer", identifiant,
                     {"consentement_id": ident, "portee": list(elements), "document_sha256": empreinte})
    vue = lire_consentement(cnx, ident)
    assert vue is not None
    return vue


def revoquer_consentement(cnx: Connection, *, acteur: str, consentement_id: str, motif: str,
                          maintenant: dt.datetime | None = None) -> dict[str, Any]:
    """Révoque un consentement (une seule fois, irréversible). Effet immédiat : la politique le relit à chaque
    évaluation, et un canal déclaré « disponible » devient « suspendu »."""
    exiger_admin(cnx, acteur)
    consentement_id = modele.valider_consentement_id(consentement_id)
    if not isinstance(motif, str) or not motif.strip() or len(motif) > MOTIF_MAX or not motif.isprintable():
        raise modele.refus_declaration("motif de révocation requis (texte imprimable, 200 caractères au plus)")
    ligne = cnx.execute(select(AVATARS_CONSENTEMENTS).where(
        AVATARS_CONSENTEMENTS.c.consentement_id == consentement_id)).mappings().first()
    if ligne is None:
        raise AvatarRefus("REJ-AVATAR-CONSENTEMENT-INCONNU", "consentement inconnu", 404)
    if ligne["revoque_le"] is not None:
        raise AvatarRefus("REJ-AVATAR-CONSENTEMENT-DEJA-REVOQUE", "ce consentement est déjà révoqué", 409)
    cnx.execute(update(AVATARS_CONSENTEMENTS).where(
        AVATARS_CONSENTEMENTS.c.consentement_id == consentement_id).values(
        revoque_le=_iso(_quand(maintenant)), revoque_par=acteur, revoque_motif=motif.strip()))
    etat.journaliser(cnx, acteur, "avatars.consentement.revoquer", ligne["identifiant"],
                     {"consentement_id": consentement_id})
    vue = lire_consentement(cnx, consentement_id)
    assert vue is not None
    return vue


def _consentement_depuis_ligne(ligne: Mapping[str, Any]) -> dict[str, Any]:
    donnees = dict(ligne)
    donnees["portee"] = json.loads(donnees["portee"])
    return donnees


def lire_consentement(cnx: Connection, consentement_id: str) -> dict[str, Any] | None:
    ligne = cnx.execute(select(AVATARS_CONSENTEMENTS).where(
        AVATARS_CONSENTEMENTS.c.consentement_id == consentement_id)).mappings().first()
    return None if ligne is None else _consentement_depuis_ligne(ligne)


def consentements_de(cnx: Connection, identifiant: str) -> list[dict[str, Any]]:
    return [_consentement_depuis_ligne(ligne) for ligne in cnx.execute(
        select(AVATARS_CONSENTEMENTS).where(AVATARS_CONSENTEMENTS.c.identifiant == identifiant)
        .order_by(AVATARS_CONSENTEMENTS.c.enregistre_le, AVATARS_CONSENTEMENTS.c.consentement_id)).mappings()]


def refus_de_consentement(cnx: Connection, entree: Mapping[str, Any],
                          maintenant: dt.datetime) -> list[tuple[str, str]]:
    """Refus (code, motif) du consentement exigé par l'origine de l'entrée ; vide si l'origine n'en exige pas ou si
    un consentement écrit, non révoqué et non expiré, couvre toute la portée requise."""
    requis = modele.PORTEES_REQUISES.get((entree["genre"], entree["origine"]))
    if requis is None:
        return []
    ce_qui = "voix clonée" if entree["genre"] == modele.GENRE_VOIX else "ressemblance du visage"
    lignes = consentements_de(cnx, entree["identifiant"])
    if not lignes:
        return [("REJ-AVATAR-CONSENTEMENT-ABSENT",
                 f"{ce_qui} : aucun consentement écrit enregistré pour {entree['identifiant']}")]
    aujourdhui = maintenant.astimezone(dt.UTC).date().isoformat()
    revoques = [c for c in lignes if c["revoque_le"] is not None]
    expires = [c for c in lignes if c["revoque_le"] is None and c["expire_le"] is not None
               and c["expire_le"] < aujourdhui]
    actifs = [c for c in lignes if c["revoque_le"] is None and c not in expires]
    if not actifs:
        if revoques:
            return [("REJ-AVATAR-CONSENTEMENT-REVOQUE", f"{ce_qui} : tous les consentements sont révoqués")]
        return [("REJ-AVATAR-CONSENTEMENT-EXPIRE", f"{ce_qui} : tous les consentements sont expirés")]
    couverte = set().union(*(set(c["portee"]) for c in actifs))
    manquante = sorted(requis - couverte)
    if manquante:
        return [("REJ-AVATAR-CONSENTEMENT-PORTEE",
                 f"{ce_qui} : la portée consentie ne couvre pas {', '.join(manquante)}")]
    return []


# -- runtime et qualification -----------------------------------------------------------------------------
def derniere_qualification(cnx: Connection, fournisseur_id: str, empreinte: str) -> dict[str, Any] | None:
    ligne = cnx.execute(select(AVATARS_QUALIFICATIONS).where(
        (AVATARS_QUALIFICATIONS.c.fournisseur_id == fournisseur_id)
        & (AVATARS_QUALIFICATIONS.c.empreinte_runtime == empreinte)
    ).order_by(AVATARS_QUALIFICATIONS.c.id.desc()).limit(1)).mappings().first()
    return None if ligne is None else dict(ligne)


def qualifications_de(cnx: Connection, fournisseur_id: str, limite: int = 20) -> list[dict[str, Any]]:
    return [dict(ligne) for ligne in cnx.execute(
        select(AVATARS_QUALIFICATIONS).where(AVATARS_QUALIFICATIONS.c.fournisseur_id == fournisseur_id)
        .order_by(AVATARS_QUALIFICATIONS.c.id.desc()).limit(limite)).mappings()]


def est_qualifiante(qualification: Mapping[str, Any] | None) -> bool:
    """Seule une sonde RÉELLE qui a réussi qualifie ; un double de test ne qualifie jamais."""
    return (qualification is not None and qualification["statut"] == "succes"
            and qualification["nature"] == NATURE_REELLE)


def _etat_du_runtime(cnx: Connection, fournisseur: Fournisseur) -> str:
    derniere = derniere_qualification(cnx, fournisseur.identifiant, modele.empreinte_runtime(fournisseur))
    return ETAT_QUALIFIE if est_qualifiante(derniere) else ETAT_CONFIGURE


def lier_runtime(cnx: Connection, *, acteur: str, identifiant: str, fournisseur_id: str,
                 maintenant: dt.datetime | None = None) -> dict[str, Any]:
    """Désigne le fournisseur (déjà CONFIGURÉ au registre de fournisseurs) qui donne cette voix ou ce visage, et
    fige le manifeste. Refus : capacité incompatible (voix => tts, visage => avatar), fournisseur écarté, voix clonée
    ou ressemblance sans consentement écrit valide. L'état devient « configure », ou « qualifie » si une
    qualification réelle de CE moteur existe déjà."""
    exiger_admin(cnx, acteur)
    ligne = _entree_ou_refus(cnx, identifiant)
    fournisseur = fournisseur_de(cnx, fournisseur_id) if isinstance(fournisseur_id, str) else None
    if fournisseur is None:
        raise AvatarRefus("REJ-AVATAR-RUNTIME-INCONNU",
                          "fournisseur inconnu ou non configuré : le configurer d'abord "
                          "(opsys-metier fournisseurs configurer)", 404)
    attendu = modele.CAPACITE_DU_GENRE[ligne["genre"]]
    if fournisseur.capacite != attendu:
        raise AvatarRefus("REJ-AVATAR-RUNTIME-CAPACITE",
                          f"un(e) {ligne['genre']} se sert d'un fournisseur de capacité « {attendu} », "
                          f"pas « {fournisseur.capacite} »", 422)
    if fournisseur.statut_catalogue == "ecarte":
        raise AvatarRefus("REJ-AVATAR-LICENCE-NON-CONFORME",
                          f"fournisseur écarté par la feuille de route : {fournisseur.raison_ecart}", 409)
    refus = refus_de_consentement(cnx, ligne, _quand(maintenant))
    if refus:
        raise AvatarRefus(refus[0][0], refus[0][1] + " ; aucun moteur n'est lié avant le consentement", 409)
    contenu = modele.manifeste(
        identifiant=identifiant, genre=ligne["genre"], langue=ligne["langue"], accent=ligne["accent"],
        origine=ligne["origine"], actif_usage_commercial=ligne["actif_usage_commercial"],
        empreinte_vocale_tiers=ligne["empreinte_vocale_tiers"], fournisseur=fournisseur)
    cnx.execute(update(AVATARS_ENTREES).where(AVATARS_ENTREES.c.identifiant == identifiant).values(
        fournisseur_id=fournisseur_id, manifeste=json.dumps(contenu, ensure_ascii=False, sort_keys=True),
        empreinte_manifeste=modele.empreinte_manifeste(contenu), etat=_etat_du_runtime(cnx, fournisseur),
        revision=ligne["revision"] + 1, modifie_le=_iso(_quand(maintenant)), modifie_par=acteur))
    etat.journaliser(cnx, acteur, "avatars.runtime.lier", identifiant,
                     {"fournisseur_id": fournisseur_id, "empreinte_runtime": contenu["empreinte_runtime"]})
    entree = lire_entree(cnx, identifiant)
    assert entree is not None
    return entree


def qualifier(fabrique: FabriqueConnexion, *, acteur: str, fournisseur_id: str,
              sonde: sondes.Sonde | None = None, delai_s: float = 5.0,
              maintenant: dt.datetime | None = None) -> dict[str, Any]:
    """Exécute le test de connexion du fournisseur (celui du registre de fournisseurs) et JOURNALISE l'exécution,
    liée à l'empreinte du moteur testé. `nature` vaut « reel » sans sonde injectée, « double » sinon : seul un succès
    réel fait passer les entrées liées à ce moteur à « qualifie ». Un échec les ramène à « configure »."""
    with fabrique() as cnx:
        exiger_admin(cnx, acteur)
        fournisseur = fournisseur_de(cnx, fournisseur_id) if isinstance(fournisseur_id, str) else None
        if fournisseur is None:
            raise AvatarRefus("REJ-AVATAR-RUNTIME-INCONNU",
                              "fournisseur inconnu ou non configuré : le configurer d'abord", 404)
        empreinte = modele.empreinte_runtime(fournisseur)
    try:
        resultat = registre_fournisseurs.tester(fabrique, acteur=acteur, identifiant=fournisseur_id, sonde=sonde,
                                                delai_s=delai_s)
    except RegistreErreur as exc:
        raise AvatarRefus("REJ-AVATAR-RUNTIME-INCONNU", f"test de connexion impossible ({exc.code})", 409) from None
    nature = NATURE_DOUBLE if sonde is not None else NATURE_REELLE
    statut = resultat["statut"]
    if statut not in ("succes", "echec", "delai", "non_verifiable", "refuse_politique"):
        statut = "echec"
    quand = _iso(_quand(maintenant))
    with fabrique() as cnx:
        exiger_admin(cnx, acteur)
        cnx.execute(insert(AVATARS_QUALIFICATIONS).values(
            quand=quand, acteur=acteur, fournisseur_id=fournisseur_id, empreinte_runtime=empreinte, nature=nature,
            statut=statut, detail=str(resultat.get("detail", ""))[:200], latence_ms=resultat.get("latence_ms")))
        qualifiante = statut == "succes" and nature == NATURE_REELLE
        liees = cnx.execute(select(AVATARS_ENTREES.c.identifiant, AVATARS_ENTREES.c.manifeste).where(
            AVATARS_ENTREES.c.fournisseur_id == fournisseur_id)).mappings().all()
        mises_a_jour = []
        for liee in liees:
            if json.loads(liee["manifeste"])["empreinte_runtime"] != empreinte:
                continue  # entrée liée à une ancienne définition du moteur : à re-lier, pas à qualifier
            cnx.execute(update(AVATARS_ENTREES).where(AVATARS_ENTREES.c.identifiant == liee["identifiant"]).values(
                etat=ETAT_QUALIFIE if qualifiante else ETAT_CONFIGURE, modifie_le=quand, modifie_par=acteur))
            mises_a_jour.append(liee["identifiant"])
        etat.journaliser(cnx, acteur, "avatars.qualifier", fournisseur_id,
                         {"nature": nature, "statut": statut, "empreinte_runtime": empreinte})
    return {"fournisseur_id": fournisseur_id, "empreinte_runtime": empreinte, "nature": nature, "statut": statut,
            "detail": str(resultat.get("detail", ""))[:200], "quand": quand, "entrees": sorted(mises_a_jour),
            "qualifiante": qualifiante}


__all__ = [
    "NATURE_DOUBLE", "NATURE_REELLE", "consentements_de", "declarer_biometrie", "derniere_qualification",
    "enregistrer_consentement", "est_qualifiante", "exiger_admin", "fournisseur_de", "inscrire_entree",
    "lier_runtime", "lire_consentement", "lire_entree", "lister_entrees", "qualifications_de", "qualifier",
    "refus_de_consentement", "revoquer_consentement",
]
