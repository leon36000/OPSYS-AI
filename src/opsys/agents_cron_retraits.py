"""Cleanup cron privé : un mandat retiré n'autorise plus aucun nouveau run.

Façade réservée à l'hôte/transport opérateur authentifié, jamais à un profil agent
fourni librement. L'ancien auteur peut avoir perdu son rôle ; sa commande humaine
durable reste la source du retrait. Le contrôleur courant est vérifié à chaque effet.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import LargeBinary, cast, func, insert, select, update

from . import agents_cron_autorite as autorite
from . import agents_declencheurs as intentions
from .etat import journaliser
from .stockage.schema import AGENTS_CRON_RETRAITS as RETRAITS

DeclencheurRefuse = intentions.DeclencheurRefuse


def _refuser():
    raise DeclencheurRefuse("CRON-RETRAIT-SOURCE-INCONNUE")


def _source_commande(cnx, row, *, retire_le=None):
    """Relie le retrait à un reçu humain exact écrit après les contrôles DB d'origine.

    Pas de rôle humain reconstitué depuis les arguments, pas de permission dérivée
    d'un nom. Les fixtures/anciens états sans reçu correspondant sont refusés.
    """
    par = row["retrait_par"]
    instant = row["modifie_le"] if retire_le is None else retire_le
    if type(par) is not str or not par or len(par.encode("utf-8")) > 64:
        _refuser()
    filtre = (
        intentions.COMMANDES.c.acteur == par,
        intentions.COMMANDES.c.cree_le == instant,
    )
    mesures = list(cnx.execute(select(
        intentions.COMMANDES.c.mutation_id,
        func.length(cast(intentions.COMMANDES.c.reponse, LargeBinary)).label("octets"),
    ).where(*filtre).limit(2)).mappings())
    if len(mesures) != 1 or mesures[0]["octets"] > 8192:
        _refuser()
    commande = cnx.execute(select(intentions.COMMANDES).where(*filtre).limit(1)).mappings().one()
    reponse = intentions._decoder(commande["reponse"], 8192)
    if (type(reponse) is not dict or set(reponse) != {"profil", "revision", "intentions", "execute"}
            or reponse["profil"] != row["agent_id"] or reponse["execute"] is not False
            or type(reponse["revision"]) is not int or reponse["revision"] < row["profile_revision"]
            or type(reponse["intentions"]) is not list
            or not 1 <= len(reponse["intentions"]) <= intentions.MAX_ATTENTE
            or any(type(ident) is not str or not autorite._HEX.fullmatch(ident)
                   for ident in reponse["intentions"])
            or len(set(reponse["intentions"])) != len(reponse["intentions"])):
        _refuser()
    retrait = intentions._hash({
        "operation": "retirer", "profil": row["agent_id"], "revision": reponse["revision"],
    })
    if commande["empreinte"] == retrait:
        if row["id"] not in reponse["intentions"]:
            _refuser()
    else:
        # demander remplace les anciennes intentions. Tous les nouveaux IDs sont
        # conservés : vérifier cette source sans exiger que leur profil reste actif.
        if row["id"] in reponse["intentions"] or len(reponse["intentions"]) > intentions.MAX_DECLARATIONS:
            _refuser()
        nouveaux = list(cnx.execute(select(intentions.INTENTIONS).where(
            intentions.INTENTIONS.c.id.in_(reponse["intentions"]),
        ).limit(intentions.MAX_DECLARATIONS)).mappings())
        if len(nouveaux) != len(reponse["intentions"]):
            _refuser()
        fuseaux = {nouveau["fuseau"] for nouveau in nouveaux}
        if len(fuseaux) != 1:
            _refuser()
        for nouveau in nouveaux:
            intentions._identite_intention(nouveau)
            if (nouveau["instance_id"] != row["instance_id"] or nouveau["agent_id"] != row["agent_id"]
                    or nouveau["profile_revision"] != reponse["revision"]
                    or nouveau["demande_par"] != par or nouveau["cree_le"] != instant):
                _refuser()
        demande = intentions._hash({
            "operation": "demander", "profil": row["agent_id"],
            "revision": reponse["revision"], "fuseau": next(iter(fuseaux)),
        })
        if commande["empreinte"] != demande:
            _refuser()
    source = {
        "acteur": par, "mutation_id": commande["mutation_id"], "empreinte": commande["empreinte"],
        "retire_le": instant,
    }
    return source


def _source_hash(row, source):
    return intentions._hash({
        "version": 1, "instance": row["instance_id"], "intention": row["id"],
        "profil": row["agent_id"], "revision": row["profile_revision"],
        "profile_hash": row["profile_hash"], "trigger_hash": row["trigger_hash"],
        "memory_policy_hash": row["memory_policy_hash"], "fuseau": row["fuseau"],
        "declaration_key": row["declaration_key"], "source": source,
    })


def _preuve(row, grant, source_hash, job_id, revision):
    preuve = {
        "version": 1, "intention": row["id"], "source_hash": source_hash,
        "epoch": grant["epoch"], "job_id": job_id, "native_revision": revision,
        "declaration_hash": grant["declaration_hash"], "declaration_key": row["declaration_key"],
    }
    return {**preuve, "receipt_id": intentions._hash(preuve), "execute": False}


class ProprietaireRetraitCron:
    """Hôte privé seulement ; le callback vient du transport, jamais du corps RPC."""

    def __init__(self, departements, profil_id: str, verifier_operateur: Callable[[], None]):
        if not callable(verifier_operateur):
            raise DeclencheurRefuse("CRON-RETRAIT-OPERATEUR-REQUIS")
        self._owner = autorite.ProprietaireCron(departements, profil_id)
        self._operateur = verifier_operateur

    def _grant_cible(self, cnx, intention_id, capabilite, epoch, declaration, job_id, revision):
        self._operateur()
        grant = self._owner._grant(cnx, intention_id, capabilite, epoch, revoquee=True)
        row = self._owner._intention(cnx, intention_id)
        if type(job_id) is not str or not autorite._JOB.fullmatch(job_id):
            raise DeclencheurRefuse("CRON-RETRAIT-JOB-INVALIDE")
        kind, revision = autorite._revision_native(revision)
        if kind != "sha256":
            raise DeclencheurRefuse("CRON-RETRAIT-PREUVE-NATIVE-REQUISE")
        if (intentions._hash(declaration) != grant["declaration_hash"]
                or declaration.get("declarationKey") != row["declaration_key"]
                or declaration.get("agentId") != "opsys-agent-" + row["agent_id"]
                or grant["native_job_id"] is not None and grant["native_job_id"] != job_id):
            raise DeclencheurRefuse("CRON-RETRAIT-ANCRAGE-DIVERGENT")
        self._operateur()
        return row, grant, revision

    def preparer(self, intention_id, *, capabilite, epoch, declaration, job_id, native_revision):
        """Révoque l'exécution et retourne l'ancrage du tombstone ; ne marque pas retiré."""
        declaration = autorite._declaration(declaration)
        with intentions._transaction() as cnx:
            row, grant, revision = self._grant_cible(
                cnx, intention_id, capabilite, epoch, declaration, job_id, native_revision,
            )
            if row["statut"] != "a_retirer":
                raise DeclencheurRefuse("CRON-RETRAIT-NON-DEMANDE")
            source = _source_commande(cnx, row)
            source_hash = _source_hash(row, source)
            if grant["etat"] != "revoquee":
                self._operateur()
                cnx.execute(update(autorite.REMISES).where(
                    autorite.REMISES.c.intention_id == intention_id,
                ).values(etat="revoquee", modifie_le=autorite._maintenant().isoformat()))
                journaliser(cnx, "controleur-cron-prive", "agents.cron.retrait_prepare", intention_id,
                            {"epoch": epoch, "source_hash": source_hash})
            courant = self._owner._intention(cnx, intention_id)
            if dict(courant) != dict(row) or _source_commande(cnx, courant) != source:
                raise DeclencheurRefuse("CRON-RETRAIT-SOURCE-PERIMEE")
            self._owner._grant(cnx, intention_id, capabilite, epoch, revoquee=True)
            self._operateur()
            return _preuve(row, grant, source_hash, job_id, revision)

    def accuser(self, intention_id, *, capabilite, epoch, declaration, job_id, native_revision,
                source_hash, receipt_id):
        """ACK après suppression native durable ; rejeu exact, une seule trace terminale."""
        autorite._empreinte(source_hash)
        autorite._empreinte(receipt_id)
        declaration = autorite._declaration(declaration)
        with intentions._transaction() as cnx:
            row, grant, revision = self._grant_cible(
                cnx, intention_id, capabilite, epoch, declaration, job_id, native_revision,
            )
            if grant["etat"] != "revoquee":
                raise DeclencheurRefuse("CRON-RETRAIT-NON-PREPARE")
            ancien = cnx.execute(select(RETRAITS).where(
                RETRAITS.c.intention_id == intention_id,
            )).mappings().first()
            if ancien:
                if (row["statut"] != "retiree" or row["modifie_le"] != ancien["acquitte_le"]
                        or ancien["epoch"] != epoch or ancien["receipt_id"] != receipt_id
                        or ancien["source_hash"] != source_hash or ancien["native_job_id"] != job_id
                        or ancien["native_revision"] != revision
                        or ancien["declaration_hash"] != grant["declaration_hash"]):
                    raise DeclencheurRefuse("CRON-RETRAIT-ACK-CONFLIT")
                source = _source_commande(cnx, row, retire_le=ancien["retire_le"])
                if _source_hash(row, source) != source_hash:
                    raise DeclencheurRefuse("CRON-RETRAIT-SOURCE-PERIMEE")
                self._operateur()
                return intentions._decoder(ancien["reponse"], 2048)
            if row["statut"] != "a_retirer":
                raise DeclencheurRefuse("CRON-RETRAIT-NON-DEMANDE")
            source = _source_commande(cnx, row)
            if _source_hash(row, source) != source_hash:
                raise DeclencheurRefuse("CRON-RETRAIT-SOURCE-PERIMEE")
            attendu = _preuve(row, grant, source_hash, job_id, revision)
            if attendu["receipt_id"] != receipt_id:
                raise DeclencheurRefuse("CRON-RETRAIT-ACK-CONFLIT")
            instant = autorite._maintenant().isoformat()
            reponse = {"intention": intention_id, "receipt_id": receipt_id, "source_hash": source_hash,
                       "epoch": epoch, "job_id": job_id, "etat": "retiree", "execute": False}
            self._operateur()
            cnx.execute(insert(RETRAITS).values(
                intention_id=intention_id, epoch=epoch, receipt_id=receipt_id, source_hash=source_hash,
                retrait_par=source["acteur"], mutation_id=source["mutation_id"],
                commande_hash=source["empreinte"], retire_le=source["retire_le"],
                native_job_id=job_id, native_revision=revision, declaration_hash=grant["declaration_hash"],
                acquitte_le=instant, reponse=intentions._json(reponse),
            ))
            cnx.execute(update(intentions.INTENTIONS).where(
                intentions.INTENTIONS.c.id == intention_id,
            ).values(statut="retiree", modifie_le=instant))
            journaliser(cnx, "controleur-cron-prive", "agents.cron.retrait_acquitte", intention_id,
                        {"epoch": epoch, "receipt_id": receipt_id, "source_hash": source_hash})
            courant = self._owner._intention(cnx, intention_id)
            if dict(courant) != {**row, "statut": "retiree", "modifie_le": instant}:
                raise DeclencheurRefuse("CRON-RETRAIT-SOURCE-PERIMEE")
            if _source_commande(cnx, courant, retire_le=source["retire_le"]) != source:
                raise DeclencheurRefuse("CRON-RETRAIT-SOURCE-PERIMEE")
            actuel = self._owner._grant(cnx, intention_id, capabilite, epoch, revoquee=True)
            if dict(actuel) != dict(grant):
                raise DeclencheurRefuse("CRON-AUTORITE-FENCE-PERIME")
            self._operateur()
            return reponse
