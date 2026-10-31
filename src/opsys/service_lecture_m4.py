"""Relecture courante privée M4 : aucune route ni politique n'est activée ici.

La portée est une convention interne entre composants de confiance. L'entrée
publique refuse tant que l'autorité humaine et sa route ne sont pas qualifiées.
"""

import copy
import json
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic, time

from sqlalchemy import event as sqla_event
from sqlalchemy import select

from . import appareils, attestation_appareil_gateway, contexte, identite, stockage
from . import service_capability as sc
from . import service_recalcul_m4 as recalcul
from .stockage import codec
from .stockage.moteur import _debuter_sqlite
from .stockage.schema import OPSYS_INSTANCE, SERVICE_POLITIQUES

_OPERATION = "m4.relire_faits_pour_m5_v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_COURANTE = ContextVar("lecture_m4_courante", default=None)
_MAX = 262144


def _politique(cnx, instance):
    return cnx.execute(
        select(SERVICE_POLITIQUES)
        .where(
            SERVICE_POLITIQUES.c.instance_id == instance,
            SERVICE_POLITIQUES.c.consommateur == sc._CONSOMMATEUR,
            SERVICE_POLITIQUES.c.operation == _OPERATION,
        )
        .order_by(SERVICE_POLITIQUES.c.revision.desc())
        .limit(1)
    ).first()


def _canonique(valeur):
    try:
        data = json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise sc.RefusAutorite("projection non canonique") from exc
    if len(data) > _MAX:
        raise sc.RefusAutorite("projection trop volumineuse")
    return data


def _verifier_acteur(cnx, session, appareil):
    if appareil is None:
        try:
            recalcul._admin(cnx, session)
        except (AttributeError, PermissionError, TypeError) as exc:
            raise sc.RefusAutorite("session serveur non qualifiée") from exc
        return session.utilisateur
    identite_appel, appairage, preuve = appareil
    if (
        session is not None
        or not contexte.appel_provient_du_mcp()
        or contexte.identite_appelante() != identite_appel
        or type(identite_appel) is not contexte.IdentiteAppelante
        or identite_appel.source != "appareil"
        or identite_appel.role != "admin"
        or type(identite_appel.personne) is not str
        or not identite_appel.personne
        or contexte.attestation_appareil() != preuve
        or not attestation_appareil_gateway.cle_est_valide(preuve)
        or preuve.appareil != appairage.identifiant
        or preuve.personne != identite_appel.personne
        or appareils.appareil(cnx, appairage.identifiant) != appairage
        or appairage.personne != identite_appel.personne
        or appairage.role != identite_appel.role
    ):
        raise sc.RefusAutorite("identité ou appairage appareil non qualifié")
    personne = identite.personne_active(cnx, identite_appel.personne)
    if personne is None or "admin" not in personne.roles:
        raise sc.RefusAutorite("identité appareil révoquée")
    return identite_appel.personne


class _Portee:
    def __init__(self, cnx, session, appareil, wct_id, devis_id, instance, policy, event, recu):
        self.cnx, self.session, self.appareil = cnx, session, appareil
        self.wct_id, self.devis_id = wct_id, devis_id
        self.instance, self.policy = instance, policy
        self.evenement, self.recu = dict(event), dict(recu)
        self.acteur, self.consommateur = _verifier_acteur(cnx, session, appareil), sc._CONSOMMATEUR
        self.racine, self.sauvegarde = cnx.get_transaction(), cnx.get_nested_transaction()
        self.thread, self.date_limite = threading.get_ident(), monotonic() + sc._DELAI_MAX
        self.base, self.fermee = sc._base(cnx), False

    def _verifier(self):
        c = self.cnx
        if (
            self.fermee
            or _COURANTE.get() is not self
            or sc._COURANTE.get() is not self
            or threading.get_ident() != self.thread
            or monotonic() >= self.date_limite
            or stockage.connexion_courante() is not c
            or c.closed
            or c.engine.dialect.name != "sqlite"
            or not sqla_event.contains(c.engine, "begin", _debuter_sqlite)
            or self.racine is None
            or not self.racine.is_active
            or c.get_transaction() is not self.racine
            or self.sauvegarde is None
            or not self.sauvegarde.is_active
            or c.get_nested_transaction() is not self.sauvegarde
        ):
            raise sc.RefusAutorite("portée de lecture inactive")
        acteur = _verifier_acteur(c, self.session, self.appareil)
        if (
            acteur != self.acteur
            or time() >= self.policy.expire_le
            or _politique(c, self.instance) != self.policy
            or sc._base(c) != self.base
            or c.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
            != self.instance
        ):
            raise sc.RefusAutorite("autorité de lecture modifiée")
        event, recu = recalcul._valider_source(c, self.wct_id, self.devis_id)
        if dict(event) != self.evenement or dict(recu) != self.recu:
            raise sc.RefusAutorite("source bus modifiée")

    def __copy__(self):
        raise sc.RefusAutorite("copie interdite")

    def __deepcopy__(self, memo):
        return self.__copy__()

    def __reduce__(self):
        raise sc.RefusAutorite("sérialisation interdite")


class _Requete:
    __slots__ = ("_portee",)

    def __init__(self, portee):
        self._portee = portee

    def _verifier(self):
        p = self._portee
        p._verifier()
        return p.cnx, "opsys.core.m4.source-request.v1", p.instance, p.wct_id


_CLE_M3 = object()


class _RequeteDevisM3:
    __slots__ = ("_cap",)

    def __init__(self, cle, cap):
        if cle is not _CLE_M3:
            raise sc.RefusAutorite("requête M3 non qualifiée")
        self._cap = cap

    def _verifier(self):
        p = self._cap.portee
        p._verifier()
        charge = codec.decoder_strict(p.evenement["charge"])
        lead = charge.get("lead_id") if type(charge) is dict else None
        if type(lead) is not str or not 1 <= len(lead) <= 128 or charge.get("devis_id") != p.devis_id:
            raise sc.RefusAutorite("liaison M3 invalide")
        return p.cnx, "m3-devis-accepte-" + p.devis_id, p.devis_id, lead

    def __copy__(self):
        raise sc.RefusAutorite("copie interdite")

    def __deepcopy__(self, memo):
        raise sc.RefusAutorite("copie interdite")

    def __reduce__(self):
        raise sc.RefusAutorite("sérialisation interdite")


class _Capacite:
    __slots__ = ("portee", "devis_id", "_liaison", "_enveloppes", "_occupee", "_preuves_m3")

    def __init__(self, portee):
        self.portee, self.devis_id = portee, portee.devis_id
        self._liaison, self._enveloppes, self._occupee = object(), [], False
        self._preuves_m3 = []

    def __copy__(self):
        raise sc.RefusAutorite("copie interdite")

    def __deepcopy__(self, memo):
        return self.__copy__()

    def __reduce__(self):
        raise sc.RefusAutorite("sérialisation interdite")

    def _lire(self):
        if self._occupee:
            raise sc.RefusAutorite("réentrée interdite")
        self._occupee = True
        try:
            p = self.portee
            p._verifier()
            from m4_field_ops.service_faits_m4 import projeter

            try:
                faits, vue = projeter(_Requete(p))
            except (ValueError, KeyError, TypeError, RecursionError) as exc:
                raise sc.RefusAutorite("source M4 invalide ou modifiée") from exc
            faits = sc._figer_faits(faits)
            if (
                len(faits) != 8
                or faits[1] != p.instance
                or faits[3] != p.wct_id
                or any(type(faits[i]) is not str or not _HEX.fullmatch(faits[i]) for i in (3, 4, 5, 7))
                or type(faits[6]) is not str
                or not 1 <= len(faits[6]) <= 64
                or type(vue) is not dict
                or set(vue) != {"source", "projection"}
                or type(vue.get("projection")) is not dict
                or vue.get("source") != faits[5]
                or vue["projection"].get("instance_id") != faits[1]
                or vue["projection"].get("intervention_id") != faits[2]
                or vue["projection"].get("version") != faits[6]
                or vue["projection"].get("empreinte") != faits[7]
                or type(vue["projection"].get("wct")) is not dict
                or vue["projection"]["wct"].get("wct_id") != faits[3]
                or vue["projection"]["wct"].get("hash_maillon") != faits[4]
            ):
                raise sc.RefusAutorite("identité M4 divergente")
            charge = codec.decoder_strict(p.evenement["charge"])
            if type(charge) is not dict or charge.get("devis_id") != p.devis_id:
                raise sc.RefusAutorite("devis divergent")
            enveloppe = {"schema": "opsys.core.m4.projection.v1", "faits": list(faits), "vue": vue, "charge": charge}
            _canonique(enveloppe)
            p._verifier()
            return enveloppe
        finally:
            self._occupee = False

    def projection_m4(self):
        if contexte.DEPARTEMENT_APPELANT.get() != sc._CONSOMMATEUR:
            raise sc.RefusAutorite("lecture réservée à M5")
        if len(self._enveloppes) >= 16:
            raise sc.RefusAutorite("quota de projections atteint")
        enveloppe = copy.deepcopy(self._lire())
        empreinte = _canonique(enveloppe)
        enveloppe["liaison"] = self._liaison
        self._enveloppes.append((enveloppe, empreinte))
        return enveloppe

    def verifier_projection(self, enveloppe):
        if contexte.DEPARTEMENT_APPELANT.get() != sc._CONSOMMATEUR:
            raise sc.RefusAutorite("lecture réservée à M5")
        self._verifier_projection(enveloppe)

    def _verifier_projection(self, enveloppe):
        if type(enveloppe) is not dict or enveloppe.get("liaison") is not self._liaison:
            raise sc.RefusAutorite("liaison de projection absente")
        brut = _canonique({k: v for k, v in enveloppe.items() if k != "liaison"})
        if brut != _canonique(self._lire()):
            raise sc.RefusAutorite("projection périmée ou modifiée")
        self.portee._verifier()

    def requete_devis_m3(self):
        if contexte.DEPARTEMENT_APPELANT.get() != sc._CONSOMMATEUR or len(self._preuves_m3) >= 16:
            raise sc.RefusAutorite("requête M3 réservée à M5")
        requete = _RequeteDevisM3(_CLE_M3, self)
        requete._verifier()
        from m3_estimation.service_lecture_devis import verifier

        try:
            preuve = verifier(requete)
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise sc.RefusAutorite("source M3 invalide ou modifiée") from exc
        if (
            type(preuve) is not dict
            or set(preuve) != {"charge", "empreinte"}
            or type(preuve["charge"]) is not dict
            or type(preuve["empreinte"]) is not str
            or not _HEX.fullmatch(preuve["empreinte"])
        ):
            raise sc.RefusAutorite("preuve M3 invalide")
        self._preuves_m3.append((requete, _canonique(preuve)))
        return requete

    def lire_devis_m3(self):
        requete = self.requete_devis_m3()
        from m3_estimation.service_lecture_devis import verifier

        try:
            preuve = verifier(requete)
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise sc.RefusAutorite("source M3 invalide ou modifiée") from exc
        if _canonique(preuve) != self._preuves_m3[-1][1]:
            raise sc.RefusAutorite("source M3 modifiée")
        return copy.deepcopy(preuve)

    def _final(self):
        if not self._enveloppes:
            raise sc.RefusAutorite("aucune projection vérifiée")
        for enveloppe, empreinte in self._enveloppes:
            if _canonique({k: v for k, v in enveloppe.items() if k != "liaison"}) != empreinte:
                raise sc.RefusAutorite("projection modifiée")
            self._verifier_projection(enveloppe)
        if self._preuves_m3:
            from m3_estimation.service_lecture_devis import verifier

            for requete, preuve in self._preuves_m3:
                try:
                    actuel = verifier(requete)
                except (ValueError, KeyError, TypeError, RecursionError) as exc:
                    raise sc.RefusAutorite("source M3 invalide ou modifiée") from exc
                if _canonique(actuel) != preuve:
                    raise sc.RefusAutorite("source M3 modifiée")
            # Le propriétaire M3 vient d'être relu : vérifier à nouveau M4
            # avant de libérer la portée, même en cas de mutation réentrante.
            for enveloppe, _ in self._enveloppes:
                self._verifier_projection(enveloppe)
        self.portee._verifier()


def courante():
    cap = _COURANTE.get()
    if cap is None or contexte.DEPARTEMENT_APPELANT.get() != sc._CONSOMMATEUR:
        return None
    # Le contexte ne contient que la portée ; la capacité est attachée à celle-ci.
    cap._verifier()
    return cap.capacite


def ouvrir(cnx, session, *, wct_id, devis_id):
    """Fermé tant que le droit et son routage ne sont pas décidés."""
    raise sc.RefusAutorite("LECTURE_M4_NON_QUALIFIEE")


def _ouvrir_qa(cnx, session, *, wct_id, devis_id):
    """Couture QA sur session serveur existante ; ne crée aucune session."""
    return _ouvrir_interne(cnx, session, None, wct_id=wct_id, devis_id=devis_id)


def _ouvrir_appareil_qa(cnx, *, wct_id, devis_id):
    """Couture QA sur l'identité MCP présente ; sans identité en argument."""
    identite_appel = contexte.identite_appelante()
    preuve = contexte.attestation_appareil()
    appareil_id = preuve.appareil if type(preuve) is attestation_appareil_gateway.Attestation else None
    if (
        identite_appel is None
        or type(appareil_id) is not str
        or not appareil_id
        or cnx is not stockage.connexion_courante()
        or cnx.get_transaction() is None
        or preuve.wct_id != wct_id
    ):
        raise sc.RefusAutorite("identité appareil absente")
    appairage = appareils.appareil(cnx, appareil_id)
    if appairage is None:
        raise sc.RefusAutorite("appairage appareil absent")
    return _ouvrir_interne(cnx, None, (identite_appel, appairage, preuve), wct_id=wct_id, devis_id=devis_id)


@contextmanager
def _ouvrir_interne(cnx, session, appareil, *, wct_id, devis_id):
    if (
        type(wct_id) is not str
        or not _HEX.fullmatch(wct_id)
        or type(devis_id) is not str
        or not 1 <= len(devis_id) <= 256
        or cnx is not stockage.connexion_courante()
        or cnx.engine.dialect.name != "sqlite"
        or cnx.get_transaction() is None
        or sc._COURANTE.get() is not None
        or _COURANTE.get() is not None
    ):
        raise sc.RefusAutorite("contexte de lecture invalide")
    acteur = _verifier_acteur(cnx, session, appareil)
    instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
    policy = _politique(cnx, instance)
    if (
        type(instance) is not str
        or not instance
        or type(acteur) is not str
        or not acteur
        or len(acteur) > 256
        or policy is None
        or policy.active is not True
        or type(policy.revision) is not int
        or policy.revision <= 0
        or type(policy.expire_le) is not int
        or time() >= policy.expire_le
    ):
        raise sc.RefusAutorite("politique de lecture absente ou expirée")
    # Le moteur canonique engage BEGIN IMMEDIATE avant toute lecture M3 ;
    # le verrou interdit un commit concurrent tant que la transaction vit.
    if not sqla_event.contains(cnx.engine, "begin", _debuter_sqlite):
        raise sc.RefusAutorite("transaction immédiate non qualifiée")
    with cnx.begin_nested():
        event_bus, recu = recalcul._valider_source(cnx, wct_id, devis_id)
        p = _Portee(cnx, session, appareil, wct_id, devis_id, instance, policy, event_bus, recu)
        p.capacite = _Capacite(p)
        token, sc_token = _COURANTE.set(p), sc._COURANTE.set(p)
        try:
            p._verifier()
            yield p.capacite
            p.capacite._final()
        finally:
            p.fermee = True
            sc._COURANTE.reset(sc_token)
            _COURANTE.reset(token)
