"""Propriétaire des grants/remises cron SQLite, appelé par l'hôte opérateur authentifié.

Cette façade n'ajoute ni outil MCP, ni scheduler, ni appel provider. L'identifiant déterministe
d'une intention ne remplace jamais l'authentification du transport opérateur.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import math
import re

from sqlalchemy import LargeBinary, cast, func, insert, select, update

from . import agents_declencheurs as intentions
from .etat import journaliser
from .stockage.schema import AGENTS_DECLENCHEURS_REMISES as REMISES

DeclencheurRefuse = intentions.DeclencheurRefuse
MAX_DECLARATION_OCTETS = 16384
MAX_TENTATIVES = 3
MAX_LEASE_SECONDES = 120
MAX_INTENTIONS_LECTURE = intentions.MAX_DECLARATIONS
MAX_LECTURE_OCTETS = 16384
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_CORE_REVISION = re.compile(r"sha256:[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]\Z")
_JOB = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_INHERIT_REVISION = object()


def _maintenant():
    return dt.datetime.now(dt.UTC)


def _positif(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 2**31 - 1:
        raise DeclencheurRefuse("CRON-AUTORITE-VERSION-INVALIDE")
    return value


def _empreinte(value):
    if type(value) is not str or not _HEX.fullmatch(value):
        raise DeclencheurRefuse("CRON-AUTORITE-CAPACITE-INVALIDE")
    return value


def _revision_native(value):
    """Valide une ancienne révision entière ou le hash Core SHA-256 base64url exact."""
    if type(value) is int and 1 <= value <= 2**31 - 1:
        return "int", value
    if type(value) is str and _CORE_REVISION.fullmatch(value):
        return "sha256", value
    raise DeclencheurRefuse("CRON-AUTORITE-REVISION-NATIVE-INVALIDE")


def _revision_row(row, prefix):
    legacy = row[f"native_{prefix}_revision"]
    empreinte = row[f"native_{prefix}_fingerprint"]
    if legacy is not None and empreinte is not None:
        raise DeclencheurRefuse("CRON-AUTORITE-REVISION-NATIVE-INVALIDE")
    if empreinte is not None:
        _revision_native(empreinte)
        return empreinte
    if legacy is not None:
        _revision_native(legacy)
        return legacy
    return None


def _revision_values(prefix, value):
    if value is None:
        return {f"native_{prefix}_revision": None, f"native_{prefix}_fingerprint": None}
    kind, normalized = _revision_native(value)
    return {
        f"native_{prefix}_revision": normalized if kind == "int" else None,
        f"native_{prefix}_fingerprint": normalized if kind == "sha256" else None,
    }


def _capacite(value):
    return hashlib.sha256(bytes.fromhex(_empreinte(value))).hexdigest()


def _declaration(value):
    """Borne les types/nœuds/octet UTF-8 avant sérialisation, puis réutilise le codec fermé."""
    pile = [(value, 0)]
    nodes = octets = 0
    while pile:
        item, depth = pile.pop()
        nodes += 1
        if nodes > 512 or depth > 8:
            raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-EXCESSIVE")
        if type(item) is dict:
            if len(item) > 512 or any(type(k) is not str for k in item):
                raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-EXCESSIVE")
            pile.extend((v, depth + 1) for v in item.values())
            pile.extend((k, depth + 1) for k in item)
        elif type(item) is list:
            if len(item) > 512:
                raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-EXCESSIVE")
            pile.extend((v, depth + 1) for v in item)
        elif type(item) is str:
            if len(item) > MAX_DECLARATION_OCTETS:
                raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-EXCESSIVE")
            try:
                octets += len(item.encode("utf-8"))
            except UnicodeError:
                raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-INVALIDE") from None
        elif type(item) is int:
            if item.bit_length() > 128:
                raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-INVALIDE")
        elif type(item) is float:
            if not math.isfinite(item):
                raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-INVALIDE")
        elif item is not None and type(item) is not bool:
            raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-INVALIDE")
        if octets > MAX_DECLARATION_OCTETS:
            raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-EXCESSIVE")
    if type(value) is not dict or any(type(k) is not str for k in value):
        raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-INVALIDE")
    try:
        texte = intentions._json(value)
        return intentions._decoder(texte, MAX_DECLARATION_OCTETS)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-INVALIDE") from None


def _lease(instant, seconds):
    if type(seconds) is not int or not 1 <= seconds <= MAX_LEASE_SECONDES:
        raise DeclencheurRefuse("CRON-AUTORITE-LEASE-INVALIDE")
    return (instant + dt.timedelta(seconds=seconds)).isoformat()


def _expiration(row):
    try:
        value = dt.datetime.fromisoformat(row["lease_until"])
        if value.utcoffset() != dt.timedelta():
            raise ValueError("UTC requis")
        return value
    except (TypeError, ValueError):
        raise DeclencheurRefuse("CRON-AUTORITE-LEASE-INVALIDE") from None


def _statut(row):
    return {"intention": row["intention_id"], "epoch": row["epoch"], "lease_epoch": row["lease_epoch"],
            "etat": row["etat"], "job_id": row["native_job_id"],
            "config_revision": _revision_row(row, "config"), "execute": False}


class ProprietaireCron:
    """Façade privée liée au profil par le transport opérateur authentifié.

    Le rôle/personne du contrôleur n'est pas fourni aux opérations. Aucun outil MCP, scheduler ou
    provider n'appelle cette façade directement.
    """

    def __init__(self, departements, profil_id: str):
        if type(profil_id) is not str or not intentions._ID.fullmatch(profil_id):
            raise DeclencheurRefuse("CRON-AUTORITE-PERIMETRE-INVALIDE")
        self._departements = departements
        self._profil_id = profil_id

    def lire(self):
        """Énumère au plus 16 intentions, sans autoriser ni projeter l'exécution.

        Une collection plus grande refuse avant matérialisation ; un backlog de retrait
        ne devient jamais une réponse partielle présentée comme exhaustive.
        """
        with intentions._transaction() as cnx:
            ident_instance = intentions.instance_id(cnx)
            filtres = (
                intentions.INTENTIONS.c.agent_id == self._profil_id,
                intentions.INTENTIONS.c.instance_id == ident_instance,
                intentions.INTENTIONS.c.statut != "retiree",
            )
            dimensions = {
                "id": 64, "instance_id": 36, "agent_id": 64, "trigger_hash": 64,
                "fuseau": 64, "declaration_key": 96, "statut": 24,
            }
            mesures = cnx.execute(select(
                func.count().label("total"),
                *(func.max(func.length(cast(intentions.INTENTIONS.c[nom], LargeBinary))).label(nom)
                  for nom in dimensions),
            ).select_from(intentions.INTENTIONS).where(*filtres)).mappings().one()
            total = mesures["total"]
            if total > MAX_INTENTIONS_LECTURE:
                raise DeclencheurRefuse("CRON-AUTORITE-LECTURE-SATUREE")
            if total and any(mesures[nom] is None or mesures[nom] > maximum
                             for nom, maximum in dimensions.items()):
                raise DeclencheurRefuse("CRON-AUTORITE-METADONNEES-EXCESSIVES")
            rows = cnx.execute(
                select(
                    intentions.INTENTIONS.c.id,
                    intentions.INTENTIONS.c.instance_id,
                    intentions.INTENTIONS.c.agent_id,
                    intentions.INTENTIONS.c.profile_revision,
                    intentions.INTENTIONS.c.trigger_hash,
                    intentions.INTENTIONS.c.fuseau,
                    intentions.INTENTIONS.c.declaration_key,
                    intentions.INTENTIONS.c.statut,
                ).where(*filtres)
                .order_by(intentions.INTENTIONS.c.cree_le, intentions.INTENTIONS.c.id)
                .limit(MAX_INTENTIONS_LECTURE)
            ).mappings()
            items = []
            for row in rows:
                _positif(row["profile_revision"])
                if (row["statut"] not in {"a_declarer", "a_retirer"}
                        or type(row["fuseau"]) is not str or not row["fuseau"]):
                    raise DeclencheurRefuse("CRON-AUTORITE-METADONNEES-INVALIDES")
                intentions._identite_intention(row)
                items.append({
                    "intention_id": row["id"],
                    "etat": row["statut"],
                    "revision_profil": row["profile_revision"],
                    "fuseau": row["fuseau"],
                })
            resultat = {
                "total": total,
                "retournes": len(items),
                "omis": total - len(items),
                "items": items,
            }
            if len(items) != total or len(intentions._json(resultat).encode("utf-8")) > MAX_LECTURE_OCTETS:
                raise DeclencheurRefuse("CRON-AUTORITE-LECTURE-EXCESSIVE")
            return resultat

    def projeter(self, intention_id):
        """Projette seulement une intention active, avec l'acteur et les sources canoniques relus."""
        if type(intention_id) is not str or not _HEX.fullmatch(intention_id):
            raise DeclencheurRefuse("CRON-INTENTION-INVALIDE")
        with intentions._transaction() as cnx:
            row = self._intention(cnx, intention_id)
            if row["statut"] == "a_retirer":
                return {
                    "intention": intention_id,
                    "etat": "a_retirer",
                    "execute": False,
                    "declaration_key": row["declaration_key"],
                    "reconciliation": "rechercher_id_natif_puis_retirer",
                    "native": None,
                }
            profil, decl, outils = intentions._valider_mandat(cnx, self._departements, row)
            projection = intentions._declaration(row, profil, decl, outils)
            result = {
                "intention": intention_id,
                "etat": row["statut"],
                "execute": False,
                "native": projection["native"],
            }
            courant = self._intention(cnx, intention_id)
            if dict(courant) != dict(row):
                raise DeclencheurRefuse("CRON-INTENTION-PERIMEE")
            intentions._valider_mandat(cnx, self._departements, courant)
            if len(intentions._json(result).encode("utf-8")) > MAX_DECLARATION_OCTETS:
                raise DeclencheurRefuse("CRON-AUTORITE-PROJECTION-EXCESSIVE")
            return result

    def _intention(self, cnx, ident):
        _empreinte(ident)
        row = cnx.execute(select(intentions.INTENTIONS).where(intentions.INTENTIONS.c.id == ident)).mappings().first()
        if row is None or row["agent_id"] != self._profil_id or row["instance_id"] != intentions.instance_id(cnx):
            raise DeclencheurRefuse("CRON-AUTORITE-PERIMETRE-INVALIDE")
        intentions._identite_intention(row)
        return row

    def _canonique(self, cnx, ident, declaration):
        row = self._intention(cnx, ident)
        profil, decl, outils = intentions._valider_mandat(cnx, self._departements, row)
        attendu = intentions._declaration(row, profil, decl, outils)["native"]["params"]
        if intentions._json(attendu) != intentions._json(declaration):
            raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-DIVERGENTE")
        courant = self._intention(cnx, ident)
        if dict(courant) != dict(row):
            raise DeclencheurRefuse("CRON-INTENTION-PERIMEE")
        intentions._valider_mandat(cnx, self._departements, courant)
        return row, attendu

    def _grant(self, cnx, ident, capabilite, epoch, *, revoquee=False):
        _empreinte(ident)
        hash_cap = _capacite(capabilite)
        _positif(epoch)
        row = cnx.execute(select(REMISES).where(REMISES.c.intention_id == ident)).mappings().first()
        if row is None or not hmac.compare_digest(row["capability_hash"], hash_cap) or row["epoch"] != epoch:
            raise DeclencheurRefuse("CRON-AUTORITE-CAPACITE-REFUSEE")
        if row["etat"] == "revoquee" and not revoquee:
            raise DeclencheurRefuse("CRON-AUTORITE-REVOQUEE")
        return row

    def _verifier(self, cnx, ident, declaration, row, *, lease_vivante=False):
        _, attendu = self._canonique(cnx, ident, declaration)
        if intentions._hash(attendu) != row["declaration_hash"]:
            raise DeclencheurRefuse("CRON-AUTORITE-DECLARATION-DIVERGENTE")
        courant = cnx.execute(select(REMISES).where(REMISES.c.intention_id == ident)).mappings().one()
        if dict(courant) != dict(row):
            raise DeclencheurRefuse("CRON-AUTORITE-FENCE-PERIME")
        if lease_vivante and _expiration(row) <= _maintenant():
            raise DeclencheurRefuse("CRON-AUTORITE-LEASE-PERIMEE")

    def _audit(self, cnx, ident, evenement, epoch):
        journaliser(cnx, "controleur-cron-prive", "agents.cron." + evenement, ident, {"epoch": epoch})

    def preparer(self, intention_id, *, empreinte_capacite, declaration, epoch_attendue,
                 revision_native_attendue=None, lease_secondes=30):
        """Lease de remise, jamais un ACK ; la capacité 32 octets provient de l'hôte."""
        _empreinte(empreinte_capacite)
        _positif(epoch_attendue, zero=True)
        if revision_native_attendue is not None:
            _revision_native(revision_native_attendue)
        declaration = _declaration(declaration)
        with intentions._transaction() as cnx:
            self._canonique(cnx, intention_id, declaration)
            instant = _maintenant()
            expire = _lease(instant, lease_secondes)
            row = cnx.execute(select(REMISES).where(REMISES.c.intention_id == intention_id)).mappings().first()
            if row:
                if (row["epoch"] != epoch_attendue + 1 or row["capability_hash"] != empreinte_capacite
                        or _revision_row(row, "expected") != revision_native_attendue
                        or row["lease_seconds"] != lease_secondes):
                    raise DeclencheurRefuse("CRON-AUTORITE-PREPARATION-CONFLIT")
                if row["etat"] != "preparation" or _expiration(row) <= instant:
                    raise DeclencheurRefuse("CRON-AUTORITE-LEASE-PERIMEE")
            else:
                if epoch_attendue != 0:
                    raise DeclencheurRefuse("CRON-AUTORITE-PREPARATION-CONFLIT")
                valeurs = {"intention_id": intention_id, "epoch": 1, "capability_hash": empreinte_capacite,
                           "declaration_hash": intentions._hash(declaration),
                           **_revision_values("expected", revision_native_attendue), "native_job_id": None,
                           **_revision_values("config", None), "etat": "preparation", "lease_epoch": 1,
                           "lease_until": expire, "lease_seconds": lease_secondes,
                           "attempts": 1, "cree_le": instant.isoformat(),
                           "modifie_le": instant.isoformat()}
                cnx.execute(insert(REMISES).values(**valeurs))
                row = valeurs
                self._audit(cnx, intention_id, "preparation", 1)
            self._verifier(cnx, intention_id, declaration, row, lease_vivante=True)
            return {**_statut(row), "lease_until": row["lease_until"],
                    "revision_native_attendue": _revision_row(row, "expected"),
                    "native": {"method": "cron.add", "params": declaration}}

    def accuser(self, intention_id, *, capabilite, epoch, lease_epoch, job_id, config_revision, declaration):
        """ACK durable exact ; un rejeu n'actualise ni grant ni révision native."""
        _positif(lease_epoch)
        config_kind, config_revision = _revision_native(config_revision)
        if type(job_id) is not str or not _JOB.fullmatch(job_id):
            raise DeclencheurRefuse("CRON-AUTORITE-JOB-INVALIDE")
        declaration = _declaration(declaration)
        with intentions._transaction() as cnx:
            row = self._grant(cnx, intention_id, capabilite, epoch)
            self._verifier(cnx, intention_id, declaration, row)
            if row["lease_epoch"] != lease_epoch:
                raise DeclencheurRefuse("CRON-AUTORITE-LEASE-PERIMEE")
            if row["etat"] == "remise":
                if row["native_job_id"] != job_id or _revision_row(row, "config") != config_revision:
                    raise DeclencheurRefuse("CRON-AUTORITE-ACK-CONFLIT")
                self._verifier(cnx, intention_id, declaration, row)
                return _statut(row)
            expected_revision = _revision_row(row, "expected")
            expected_kind = _revision_native(expected_revision)[0] if expected_revision is not None else None
            if (row["native_job_id"] is not None and row["native_job_id"] != job_id
                    or expected_kind is not None and config_kind != expected_kind
                    or expected_kind == "int" and config_revision < expected_revision):
                raise DeclencheurRefuse("CRON-AUTORITE-ACK-CONFLIT")
            instant = _maintenant()
            if _expiration(row) <= instant:
                raise DeclencheurRefuse("CRON-AUTORITE-LEASE-PERIMEE")
            valeurs = dict(row, etat="remise", native_job_id=job_id,
                           **_revision_values("config", config_revision), modifie_le=instant.isoformat())
            cnx.execute(update(REMISES).where(REMISES.c.intention_id == intention_id).values(**valeurs))
            self._audit(cnx, intention_id, "remise_acquittee", epoch)
            self._verifier(cnx, intention_id, declaration, valeurs)
            if _expiration(row) <= _maintenant():
                raise DeclencheurRefuse("CRON-AUTORITE-LEASE-PERIMEE")
            return _statut(valeurs)

    def valider(self, intention_id, *, capabilite, epoch, job_id, config_revision, declaration):
        """Contrôle durable avant un futur appel d'admission ; ne l'effectue pas."""
        _revision_native(config_revision)
        declaration = _declaration(declaration)
        with intentions._transaction() as cnx:
            row = self._grant(cnx, intention_id, capabilite, epoch)
            self._verifier(cnx, intention_id, declaration, row)
            if row["etat"] != "remise":
                raise DeclencheurRefuse("CRON-AUTORITE-NON-ACQUITTEE")
            if row["native_job_id"] != job_id or _revision_row(row, "config") != config_revision:
                raise DeclencheurRefuse("CRON-AUTORITE-JOB-PERIME")
            self._verifier(cnx, intention_id, declaration, row)

    def renouveler(self, intention_id, *, capabilite, epoch, lease_epoch, declaration, lease_secondes=30):
        """Reprise explicite d'une lease échue, trois prises au plus par époque."""
        declaration = _declaration(declaration)
        _positif(lease_epoch)
        with intentions._transaction() as cnx:
            row = self._grant(cnx, intention_id, capabilite, epoch)
            self._verifier(cnx, intention_id, declaration, row)
            instant = _maintenant()
            if (row["etat"] == "preparation" and row["lease_epoch"] == lease_epoch + 1
                    and row["lease_seconds"] == lease_secondes):
                self._verifier(cnx, intention_id, declaration, row, lease_vivante=True)
                return {**_statut(row), "lease_until": row["lease_until"]}
            if row["etat"] != "preparation" or row["lease_epoch"] != lease_epoch or _expiration(row) > instant:
                raise DeclencheurRefuse("CRON-AUTORITE-REPRISE-REFUSEE")
            if row["attempts"] >= MAX_TENTATIVES:
                raise DeclencheurRefuse("CRON-AUTORITE-TENTATIVES-EPUISEES")
            valeurs = dict(row, lease_epoch=lease_epoch + 1, attempts=row["attempts"] + 1,
                           lease_until=_lease(instant, lease_secondes), lease_seconds=lease_secondes,
                           modifie_le=instant.isoformat())
            cnx.execute(update(REMISES).where(REMISES.c.intention_id == intention_id).values(**valeurs))
            self._audit(cnx, intention_id, "lease_reprise", epoch)
            self._verifier(cnx, intention_id, declaration, valeurs, lease_vivante=True)
            return {**_statut(valeurs), "lease_until": valeurs["lease_until"]}

    def tourner(self, intention_id, *, capabilite, epoch, nouvelle_empreinte, declaration,
                revision_native_attendue=_INHERIT_REVISION, lease_secondes=30):
        """Rotation explicite authentifiée par l'ancienne capacité ; aucun réarmement implicite."""
        _empreinte(nouvelle_empreinte)
        declaration = _declaration(declaration)
        with intentions._transaction() as cnx:
            row = self._grant(cnx, intention_id, capabilite, epoch)
            self._verifier(cnx, intention_id, declaration, row)
            if row["capability_hash"] == nouvelle_empreinte:
                raise DeclencheurRefuse("CRON-AUTORITE-ROTATION-IDENTIQUE")
            instant = _maintenant()
            precedente = _revision_row(row, "expected" if row["etat"] == "preparation" else "config")
            attendue = precedente if revision_native_attendue is _INHERIT_REVISION else revision_native_attendue
            if attendue is not None:
                _revision_native(attendue)
            elif row["native_job_id"] is not None:
                raise DeclencheurRefuse("CRON-AUTORITE-REVISION-NATIVE-INVALIDE")
            valeurs = dict(row, epoch=_positif(epoch + 1), capability_hash=nouvelle_empreinte,
                           etat="preparation", lease_epoch=row["lease_epoch"] + 1, attempts=1,
                           **_revision_values("expected", attendue),
                           **_revision_values("config", None),
                           lease_until=_lease(instant, lease_secondes), lease_seconds=lease_secondes,
                           modifie_le=instant.isoformat())
            cnx.execute(update(REMISES).where(REMISES.c.intention_id == intention_id).values(**valeurs))
            self._audit(cnx, intention_id, "capacite_rotation", valeurs["epoch"])
            self._verifier(cnx, intention_id, declaration, valeurs, lease_vivante=True)
            return {**_statut(valeurs), "lease_until": valeurs["lease_until"],
                    "revision_native_attendue": _revision_row(valeurs, "expected")}

    def revoquer(self, intention_id, *, capabilite, epoch):
        """Révocation privée ; autorisée aussi après retrait/désactivation du profil."""
        with intentions._transaction() as cnx:
            row = self._grant(cnx, intention_id, capabilite, epoch, revoquee=True)
            intention = self._intention(cnx, intention_id)
            intentions._acteur(cnx, intention["demande_par"])
            if row["etat"] == "revoquee":
                intentions._acteur(cnx, self._intention(cnx, intention_id)["demande_par"])
                return _statut(row)
            valeurs = dict(row, etat="revoquee", modifie_le=_maintenant().isoformat())
            cnx.execute(update(REMISES).where(REMISES.c.intention_id == intention_id).values(**valeurs))
            self._audit(cnx, intention_id, "capacite_revoquee", epoch)
            courant = self._intention(cnx, intention_id)
            if dict(courant) != dict(intention):
                raise DeclencheurRefuse("CRON-INTENTION-PERIMEE")
            intentions._acteur(cnx, courant["demande_par"])
            actuel = cnx.execute(select(REMISES).where(REMISES.c.intention_id == intention_id)).mappings().one()
            if dict(actuel) != valeurs:
                raise DeclencheurRefuse("CRON-AUTORITE-FENCE-PERIME")
            return _statut(valeurs)
