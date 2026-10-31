"""File privée, bornée, d'une livraison WCT encore ouverte, SQLite seulement.

Ne crée aucune politique et ne remet jamais en circulation un reçu clos.
"""

import datetime as dt
import hashlib
import threading
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import LargeBinary, and_, cast, exists, func, insert, or_, select, update

from .. import service_capability as sc
from .. import stockage
from ..stockage import codec
from ..stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, OPSYS_INSTANCE
from ..stockage.schema import WCT_ATTENTES as ATTENTES
from ..stockage.schema import WCT_ATTENTES_AUDIT as AUDIT

_CONSOMMATEUR = "m05-financecore"
_MAX_ATTENTES = 1000
_BATCH = 50
_TTL = 7 * 86400
_MAX_OCTETS = 262144


def _epoch(maintenant):
    if not isinstance(maintenant, dt.datetime) or maintenant.tzinfo is None:
        raise ValueError("horodatage avec fuseau requis")
    epoch = int(maintenant.timestamp())
    # L'horloge injectable du répartiteur ne peut avancer seule l'expiration métier.
    if abs(epoch - sc.time()) > 60:
        raise ValueError("horloge métier non concordante")
    return epoch


def _politique(cnx, instance):
    sc._base(cnx)
    if (
        cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
        != instance
    ):
        raise sc.RefusAutorite("instance modifiée")
    p = sc._politique(cnx, instance, _CONSOMMATEUR)
    if p is None or not p.active or p.expire_le <= sc.time():
        raise sc.RefusAutorite("politique inactive ou expirée")
    return p


def _audit(cnx, ident, action, epoch, revision, source_m3=None, source_m5=None):
    cnx.execute(
        insert(AUDIT).values(
            evenement_id=ident,
            action=action,
            epoch=epoch,
            revision_politique=revision,
            source_m3=source_m3,
            source_m5=source_m5,
        )
    )


def inscrire(cnx, evenement, consommateur, resultat, maintenant):
    """Appelé seulement dans le savepoint d'une réclamation WCT qualifiée."""
    if (
        cnx is not stockage.connexion_courante()
        or consommateur != _CONSOMMATEUR
        or evenement.get("type_evenement") != "m4.travaux_termines"
        or evenement.get("producteur") != "m04-field-ops"
        or type(resultat) is not dict
        or resultat.get("service_m4") != "en_attente_devis_accepte"
    ):
        return False
    cap = sc.courante()
    projection = cap.projection_m4()
    charge = projection["charge"]
    ident, devis, lead = evenement["evenement_id"], charge.get("devis_id"), charge.get("lead_id")
    if (
        type(ident) is not str
        or charge.get("wct_id") != ident
        or type(devis) is not str
        or not 1 <= len(devis) <= 100
        or type(lead) is not str
        or not 1 <= len(lead) <= 128
        or resultat.get("devis_id") != devis
    ):
        raise sc.RefusAutorite("liaison attente invalide")
    cap.verifier_projection(projection)
    instance = cap.instance
    politique = _politique(cnx, instance)
    count = cnx.execute(
        select(func.count()).select_from(ATTENTES).where(ATTENTES.c.etat.in_(("attente", "prete")))
    ).scalar_one()
    if count >= _MAX_ATTENTES:
        # Conserver le WCT partiel et clore sans attendre ; jamais dépasser le quota.
        cap.verifier_projection(projection)
        return "quota"
    try:
        maintenant_epoch = _epoch(maintenant)
    except (ValueError, OverflowError, OSError):
        return "horodatage_invalide"
    cnx.execute(
        insert(ATTENTES).values(
            evenement_id=ident,
            consommateur=consommateur,
            instance_id=instance,
            devis_id=devis,
            lead_id=lead,
            recu_sha256=hashlib.sha256(codec.encoder(dict(resultat)).encode("utf-8")).hexdigest(),
            etat="attente",
            cree_epoch=maintenant_epoch,
            expire_epoch=maintenant_epoch + _TTL,
            revision_politique=politique.revision,
            source_m3=None,
        )
    )
    _audit(cnx, ident, "attente", maintenant_epoch, politique.revision)
    cap.verifier_projection(projection)
    from m5_financecore import service_attente_devis as m5

    m5.verifier_wct_en_attente(cap, projection)
    return "attente"


_SOURCE_COURANTE = ContextVar("opsys_wct_attente_source", default=None)
_CONSTRUCTION_SOURCE = object()


def _empreinte_ligne(ligne):
    return hashlib.sha256(codec.encoder(dict(ligne)).encode("utf-8")).hexdigest()


class _RequeteSource:
    """Requête non réutilisable, liée à la paire WCT et aux lignes Core relues."""

    def __init__(self, cle, cnx, attente, evenement, recu, politique):
        if cle is not _CONSTRUCTION_SOURCE:
            raise sc.RefusAutorite("construction source interdite")
        self.cnx, self.attente, self.evenement, self.recu = cnx, dict(attente), dict(evenement), dict(recu)
        self.politique, self.racine, self.sauvegarde = politique, cnx.get_transaction(), cnx.get_nested_transaction()
        self.thread, self.echeance, self.fermee = threading.get_ident(), sc.monotonic() + 30.0, False

    def __copy__(self):
        raise sc.RefusAutorite("copie interdite")

    def __deepcopy__(self, memo):
        raise sc.RefusAutorite("copie interdite")

    def __reduce__(self):
        raise sc.RefusAutorite("sérialisation interdite")

    def _verifier(self):
        c = self.cnx
        if (
            self.fermee
            or _SOURCE_COURANTE.get() is not self
            or threading.get_ident() != self.thread
            or sc.monotonic() >= self.echeance
            or stockage.connexion_courante() is not c
            or c.closed
            or self.racine is None
            or not self.racine.is_active
            or c.get_transaction() is not self.racine
            or c.get_nested_transaction() is not self.sauvegarde
            or (self.sauvegarde is not None and not self.sauvegarde.is_active)
        ):
            raise sc.RefusAutorite("portée source M3 invalide")
        _verifier_paire(c, self.attente)
        if _politique(c, self.attente["instance_id"]) != self.politique:
            raise sc.RefusAutorite("politique source modifiée")
        courante = (
            c.execute(select(ATTENTES).where(ATTENTES.c.evenement_id == self.attente["evenement_id"]))
            .mappings()
            .one_or_none()
        )
        evenement = (
            c.execute(
                select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == self.evenement["evenement_id"])
            )
            .mappings()
            .one_or_none()
        )
        recu = (
            c.execute(
                select(EVENEMENTS_RECUS).where(
                    EVENEMENTS_RECUS.c.evenement_id == self.evenement["evenement_id"],
                    EVENEMENTS_RECUS.c.consommateur == _CONSOMMATEUR,
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            courante is None
            or evenement is None
            or recu is None
            or _empreinte_ligne(courante) != _empreinte_ligne(self.attente)
            or _empreinte_ligne(evenement) != _empreinte_ligne(self.evenement)
            or _empreinte_ligne(recu) != _empreinte_ligne(self.recu)
        ):
            raise sc.RefusAutorite("source ou attente modifiée")
        return c, self.evenement["evenement_id"], self.attente["devis_id"], self.attente["lead_id"]


@contextmanager
def _requete_source(cnx, attente, evenement, recu):
    if _SOURCE_COURANTE.get() is not None:
        raise sc.RefusAutorite("réentrée source interdite")
    _verifier_paire(cnx, attente)
    politique = _politique(cnx, attente["instance_id"])
    requete = _RequeteSource(_CONSTRUCTION_SOURCE, cnx, attente, evenement, recu, politique)
    token = _SOURCE_COURANTE.set(requete)
    try:
        requete._verifier()
        yield requete
        requete._verifier()
    finally:
        requete.fermee = True
        _SOURCE_COURANTE.reset(token)


def _source(cnx, attente):
    """Reçoit la pièce M3 réellement produite et déjà traitée par M5."""
    ident = "m3-devis-accepte-" + attente["devis_id"]
    evt_filtre = EVENEMENTS_SORTANTS.c.evenement_id == ident
    recu_filtre = (EVENEMENTS_RECUS.c.evenement_id == ident) & (EVENEMENTS_RECUS.c.consommateur == _CONSOMMATEUR)
    taille = cnx.execute(
        select(func.length(cast(EVENEMENTS_SORTANTS.c.charge, LargeBinary))).where(evt_filtre)
    ).scalar_one_or_none()
    taille_recu = cnx.execute(
        select(func.length(cast(EVENEMENTS_RECUS.c.resultat, LargeBinary))).where(recu_filtre)
    ).scalar_one_or_none()
    if (
        type(taille) is not int
        or not 0 <= taille <= _MAX_OCTETS
        or type(taille_recu) is not int
        or not 0 <= taille_recu <= _MAX_OCTETS
    ):
        raise ValueError("pièce ou reçu absent")
    evenement = cnx.execute(select(EVENEMENTS_SORTANTS).where(evt_filtre)).mappings().one()
    recu = cnx.execute(select(EVENEMENTS_RECUS).where(recu_filtre)).mappings().one()
    charge = codec.decoder_strict(evenement["charge"])
    resultat = codec.decoder_strict(recu["resultat"])
    if (
        evenement["type_evenement"] != "m3.devis_accepte"
        or evenement["producteur"] != "m03-estimation"
        or type(charge) is not dict
        or charge.get("devis_id") != attente["devis_id"]
        or charge.get("lead_id") != attente["lead_id"]
        or recu["statut"] != "traite"
        or type(resultat) is not dict
        or resultat.get("traite") is not True
        or resultat.get("devis_id") != attente["devis_id"]
    ):
        raise ValueError("pièce ou réception incohérente")
    from m3_estimation import service_attente_devis as m3
    from m5_financecore import service_attente_devis as m5

    with _requete_source(cnx, attente, evenement, recu) as requete:
        preuve_m3 = m3.verifier(requete)
        preuve_m5 = m5.verifier(requete)
    return preuve_m3, preuve_m5


def _clore(cnx, ligne, etat, epoch):
    cible = (EVENEMENTS_RECUS.c.evenement_id == ligne["evenement_id"]) & (
        EVENEMENTS_RECUS.c.consommateur == _CONSOMMATEUR
    )
    recu = cnx.execute(select(EVENEMENTS_RECUS).where(cible)).mappings().one_or_none()
    # Une paire déjà close n'est jamais rouverte, même si la file est incohérente.
    if (
        recu is not None
        and recu["statut"] == "echec"
        and type(recu["resultat"]) is str
        and len(recu["resultat"].encode("utf-8")) <= _MAX_OCTETS
        and hashlib.sha256(recu["resultat"].encode("utf-8")).hexdigest() == ligne["recu_sha256"]
    ):
        cnx.execute(
            update(EVENEMENTS_RECUS)
            .where(cible, EVENEMENTS_RECUS.c.statut == "echec")
            .values(statut="traite", prochaine_tentative=None, derniere_erreur=None)
        )
    changement = cnx.execute(
        update(ATTENTES)
        .where(ATTENTES.c.evenement_id == ligne["evenement_id"], ATTENTES.c.etat == ligne["etat"])
        .values(etat=etat)
    )
    if changement.rowcount == 1:
        _audit(
            cnx, ligne["evenement_id"], etat, epoch, ligne["revision_politique"], ligne["source_m3"], ligne["source_m5"]
        )


def _verifier_paire(cnx, attente):
    cible = (EVENEMENTS_RECUS.c.evenement_id == attente["evenement_id"]) & (
        EVENEMENTS_RECUS.c.consommateur == _CONSOMMATEUR
    )
    recu = cnx.execute(select(EVENEMENTS_RECUS).where(cible)).mappings().one_or_none()
    taille = cnx.execute(
        select(func.length(cast(EVENEMENTS_SORTANTS.c.charge, LargeBinary))).where(
            EVENEMENTS_SORTANTS.c.evenement_id == attente["evenement_id"]
        )
    ).scalar_one_or_none()
    if type(taille) is not int or not 0 <= taille <= _MAX_OCTETS:
        raise ValueError("WCT hors limite")
    event = (
        cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == attente["evenement_id"]))
        .mappings()
        .one_or_none()
    )
    if (
        recu is None
        or recu["statut"] != "echec"
        or recu["resultat"] is None
        or event is None
        or event["type_evenement"] != "m4.travaux_termines"
        or event["producteur"] != "m04-field-ops"
    ):
        raise ValueError("paire WCT non ouverte")
    if (
        type(recu["resultat"]) is not str
        or len(recu["resultat"].encode("utf-8")) > _MAX_OCTETS
        or hashlib.sha256(recu["resultat"].encode("utf-8")).hexdigest() != attente["recu_sha256"]
    ):
        raise ValueError("reçu partiel modifié")
    resultat = codec.decoder_strict(recu["resultat"])
    if (
        type(resultat) is not dict
        or resultat.get("traite") is not True
        or resultat.get("devis_id") != attente["devis_id"]
        or resultat.get("service_m4") != "en_attente_devis_accepte"
    ):
        raise ValueError("reçu partiel invalide")
    charge = codec.decoder_strict(event["charge"])
    if (
        type(charge) is not dict
        or charge.get("wct_id") != attente["evenement_id"]
        or charge.get("devis_id") != attente["devis_id"]
        or charge.get("lead_id") != attente["lead_id"]
    ):
        raise ValueError("source WCT divergente")


def _qualifier(cnx, ligne, maintenant):
    epoch = _epoch(maintenant)
    if epoch >= ligne["expire_epoch"]:
        _clore(cnx, ligne, "expiree", epoch)
        return False
    try:
        _verifier_paire(cnx, ligne)
        politique = _politique(cnx, ligne["instance_id"])
        source = _source(cnx, ligne)
        if _politique(cnx, ligne["instance_id"]) != politique:
            raise sc.RefusAutorite("politique modifiée")
        _verifier_paire(cnx, ligne)
        if ligne["etat"] == "prete" and (
            source != (ligne["source_m3"], ligne["source_m5"]) or politique.revision != ligne["revision_politique"]
        ):
            raise ValueError("preuve de réveil périmée")
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError, sc.RefusAutorite):
        _clore(cnx, ligne, "refusee", epoch)
        return False
    if ligne["etat"] == "attente":
        changement = cnx.execute(
            update(ATTENTES)
            .where(ATTENTES.c.evenement_id == ligne["evenement_id"], ATTENTES.c.etat == "attente")
            .values(etat="prete", source_m3=source[0], source_m5=source[1], revision_politique=politique.revision)
        )
        if changement.rowcount != 1:
            return False
        _audit(cnx, ligne["evenement_id"], "prete", epoch, politique.revision, source[0], source[1])
    return True


def reconcilier(cnx, maintenant):
    """Réveille au plus 50 attentes dont le devis M5 est clos, ou expirées."""
    try:
        epoch = _epoch(maintenant)
    except (ValueError, OverflowError, OSError):
        return
    recu_devis = exists(
        select(1).where(
            EVENEMENTS_RECUS.c.evenement_id == ("m3-devis-accepte-" + ATTENTES.c.devis_id),
            EVENEMENTS_RECUS.c.consommateur == _CONSOMMATEUR,
            EVENEMENTS_RECUS.c.statut == "traite",
        )
    )
    lignes = (
        cnx.execute(
            select(ATTENTES)
            .where(
                or_(
                    and_(ATTENTES.c.etat == "attente", or_(ATTENTES.c.expire_epoch <= epoch, recu_devis)),
                    and_(ATTENTES.c.etat == "prete", ATTENTES.c.expire_epoch <= epoch),
                )
            )
            .order_by(ATTENTES.c.cree_epoch, ATTENTES.c.evenement_id)
            .limit(_BATCH)
        )
        .mappings()
        .all()
    )
    for ligne in lignes:
        _qualifier(cnx, ligne, maintenant)


def peut_livrer(cnx, ident, consommateur, maintenant):
    if consommateur != _CONSOMMATEUR:
        return True
    ligne = cnx.execute(select(ATTENTES).where(ATTENTES.c.evenement_id == ident)).mappings().one_or_none()
    if ligne is None:
        return True
    if ligne["etat"] != "prete":
        return False
    try:
        _epoch(maintenant)
    except (ValueError, OverflowError, OSError):
        return False
    return _qualifier(cnx, ligne, maintenant)


def terminer(cnx, ident, consommateur, maintenant):
    if consommateur != _CONSOMMATEUR:
        return False
    ligne = cnx.execute(select(ATTENTES).where(ATTENTES.c.evenement_id == ident)).mappings().one_or_none()
    if ligne is None:
        return False
    if ligne["etat"] != "prete":
        raise sc.RefusAutorite("attente non réclamée")
    changement = cnx.execute(
        update(ATTENTES).where(ATTENTES.c.evenement_id == ident, ATTENTES.c.etat == "prete").values(etat="terminee")
    )
    if changement.rowcount != 1:
        raise sc.RefusAutorite("attente modifiée")
    _audit(
        cnx, ident, "terminee", _epoch(maintenant), ligne["revision_politique"], ligne["source_m3"], ligne["source_m5"]
    )
    return True


def revalider_terminee(cnx, ident, consommateur, maintenant):
    """Vérifie après les écritures de transition et avant clôture de l'inbox."""
    if consommateur != _CONSOMMATEUR:
        raise sc.RefusAutorite("consommateur invalide")
    ligne = cnx.execute(select(ATTENTES).where(ATTENTES.c.evenement_id == ident)).mappings().one_or_none()
    if ligne is None or ligne["etat"] != "terminee" or _epoch(maintenant) >= ligne["expire_epoch"]:
        raise sc.RefusAutorite("attente perdue ou expirée")
    _verifier_paire(cnx, ligne)
    politique = _politique(cnx, ligne["instance_id"])
    if politique.revision != ligne["revision_politique"] or _source(cnx, ligne) != (
        ligne["source_m3"],
        ligne["source_m5"],
    ):
        raise sc.RefusAutorite("source ou politique modifiée")
    if _politique(cnx, ligne["instance_id"]) != politique:
        raise sc.RefusAutorite("politique modifiée")
    _verifier_paire(cnx, ligne)


def quarantaine(cnx, ident, consommateur, maintenant):
    """Libère le quota si une reprise a épuisé ses vrais essais d'erreur."""
    if consommateur != _CONSOMMATEUR:
        return
    ligne = cnx.execute(select(ATTENTES).where(ATTENTES.c.evenement_id == ident)).mappings().one_or_none()
    if ligne is not None and ligne["etat"] == "prete":
        _clore(cnx, ligne, "refusee", _epoch(maintenant))
