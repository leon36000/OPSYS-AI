"""Candidat privé, NON branché : moteur de recalcul certifié SQLite (E2 de CONCEPTION-ROUTAGE-COUT-CERTIFIE).

Dérivé de `service_recalcul_m4._executer_qa` : mêmes gardes (double politique, intention idempotente, savepoint,
portée vérifiée avant et après chaque lecture, attestation v2), auxquelles E2 ajoute :

1. le verrou d'écriture `BEGIN IMMEDIATE` est VÉRIFIÉ (écouteur `begin` de l'engine), à l'entrée et à chaque
   `_verifier` de la portée, comme le fait la lecture (`service_lecture_m4`) ;
2. un état certifié déjà à jour rend `rien_a_faire` : AUCUNE écriture nette (ni trace, ni reçu, ni événement, ni
   intention, ni audit) ; les lectures d'autorité qui insèrent des audits `usage` sont annulées avec le savepoint ;
3. l'acteur et l'intention sont des PARAMÈTRES validés strictement (rien n'est codé en dur) ;
4. échec fermé et TYPÉ (`RefusRecalculM4.code`) pour chaque état qui ne peut pas produire un coût certifié :
   politique absente, révoquée ou expirée (`m4.recalculer_v3` ET `m4.verifier_v3`), PostgreSQL, verrou absent,
   projection non exploitable (revue en attente, équipe inconnue), tarifs illisibles ou absents, WCT sans
   `empreinte_charge`, WCT antérieur au modèle de visites. Un refus n'écrit RIEN : tout se passe dans un savepoint
   annulé, après des contrôles en lecture seule ;
5. un échec n'atteint jamais la facture ni les registres : rien n'est écrit hors du savepoint, et la transaction de
   l'appelant reste utilisable (aucun état « empoisonné »).

Règle produit : « déclaration d'équipe ≠ présence individuelle » ; un historique sans équipe établie reste inconnu ;
aucune attribution supposée, aucun coût estimé : un coût dont la main-d'oeuvre n'est pas chiffrée par une projection
M4 exploitable et un tarif d'équipe sourcé est REFUSÉ, jamais publié comme partiel sous provenance certifiée.

NON branché : `service_recalcul_m4.ouvrir` et `service_lecture_m4.ouvrir` restent fermés (`*_NON_QUALIFIE`). Aucune
route, aucun outil, aucun rôle, aucun droit, aucune politique créée ici ; PostgreSQL est refusé. L'autorité d'appel
est celle de `_executer_qa` : une session console d'une personne `admin` active. Un acteur automatique sans session
(Option 3, E8) est une décision de droit (D2) qui n'est PAS prise ici.
"""

from __future__ import annotations

import re
from time import time

from sqlalchemy import event as sqla_event
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from . import service_capability as sc
from . import service_recalcul_m4 as recalcul
from . import stockage
from .stockage.moteur import _debuter_sqlite
from .stockage.schema import OPSYS_INSTANCE, SERVICE_AUDIT
from .stockage.schema import SERVICE_RECALCUL_INTENTIONS as INTENTIONS
from .stockage.schema import SERVICE_RECALCUL_RESULTATS as RESULTATS

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_OPERATION = recalcul._OPERATION
_DEPARTEMENT_M5 = "m05-financecore"

# Codes de refus : liste fermée, stable (les tests et les futurs appelants s'y réfèrent).
BACKEND_NON_SQLITE = "BACKEND_NON_SQLITE"
VERROU_ECRITURE_ABSENT = "VERROU_ECRITURE_ABSENT"
CONTEXTE_INVALIDE = "CONTEXTE_INVALIDE"
IDENTIFIANT_INVALIDE = "IDENTIFIANT_INVALIDE"
ACTEUR_INVALIDE = "ACTEUR_INVALIDE"
INTENTION_INVALIDE = "INTENTION_INVALIDE"
INTENTION_EN_CONFLIT = "INTENTION_EN_CONFLIT"
AUTORITE_REFUSEE = "AUTORITE_REFUSEE"
POLITIQUE_ABSENTE = "POLITIQUE_ABSENTE"
POLITIQUE_REVOQUEE = "POLITIQUE_REVOQUEE"
POLITIQUE_EXPIREE = "POLITIQUE_EXPIREE"
PROJECTION_NON_EXPLOITABLE = "PROJECTION_NON_EXPLOITABLE"
REVUE_EN_ATTENTE = "REVUE_EN_ATTENTE"
EQUIPE_INCONNUE = "EQUIPE_INCONNUE"
TARIFS_ILLISIBLES = "TARIFS_ILLISIBLES"
TARIF_ABSENT = "TARIF_ABSENT"
WCT_SANS_EMPREINTE = "WCT_SANS_EMPREINTE"
WCT_ANTERIEUR_MODELE_VISITES = "WCT_ANTERIEUR_MODELE_VISITES"
SOURCE_M4_REFUSEE = "SOURCE_M4_REFUSEE"
PIECE_M5_ABSENTE = "PIECE_M5_ABSENTE"
SOURCES_M5_ILLISIBLES = "SOURCES_M5_ILLISIBLES"
COUT_NON_CERTIFIE = "COUT_NON_CERTIFIE"
ECHEC_RECALCUL = "ECHEC_RECALCUL"

CODES = frozenset(
    {
        BACKEND_NON_SQLITE, VERROU_ECRITURE_ABSENT, CONTEXTE_INVALIDE, IDENTIFIANT_INVALIDE, ACTEUR_INVALIDE,
        INTENTION_INVALIDE, INTENTION_EN_CONFLIT, AUTORITE_REFUSEE, POLITIQUE_ABSENTE, POLITIQUE_REVOQUEE,
        POLITIQUE_EXPIREE, PROJECTION_NON_EXPLOITABLE, REVUE_EN_ATTENTE, EQUIPE_INCONNUE, TARIFS_ILLISIBLES,
        TARIF_ABSENT, WCT_SANS_EMPREINTE, WCT_ANTERIEUR_MODELE_VISITES, SOURCE_M4_REFUSEE, PIECE_M5_ABSENTE,
        SOURCES_M5_ILLISIBLES, COUT_NON_CERTIFIE, ECHEC_RECALCUL,
    }
)

# Refus du producteur M4 (`temps_certifies_v2.Refus`) qui disent « cette source n'a pas le modèle de visites
# d'équipe » (conception §5.2) : jamais une estimation, jamais une attribution.
_FAIT_SANS_OUVERTURE = "fait sans ouverture correspondante"  # message de `visites_chantier.calculer_faits_certifies`
_SANS_MODELE_VISITES = frozenset({"DUREE-INCOHERENTE", "VISITE-AMBIGUE", "WCT-ANTERIEUR-A-VISITE", "ROUTE-AMBIGUE"})


class RefusRecalculM4(sc.RefusAutorite):
    """Refus typé : `code` appartient à `CODES`. Sous-classe de `RefusAutorite` (les appelants existants restent
    valides). Ne contient aucune donnée métier : seulement un code et une raison courte."""

    def __init__(self, code, detail=""):
        if code not in CODES:
            raise ValueError("code de refus inconnu")
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


class _SansEcriture(Exception):
    """Sentinelle interne : annule le savepoint (zéro écriture nette) pour `rien_a_faire`."""


def _verrou_present(engine):
    return sqla_event.contains(engine, "begin", _debuter_sqlite)


class _PorteeMoteur(recalcul._PorteeRecalcul):
    """Portée de recalcul qui, en plus, prouve à CHAQUE vérification que le verrou d'écriture est engagé."""

    def _verifier(self):
        if self.cnx.engine.dialect.name != "sqlite" or not _verrou_present(self.cnx.engine):
            raise RefusRecalculM4(VERROU_ECRITURE_ABSENT, "écouteur BEGIN IMMEDIATE absent pendant la portée")
        super()._verifier()


class _CapaciteMoteur(recalcul._CapaciteRecalcul):
    """Refuse AVANT toute écriture de trace une projection M4 qui ne permet pas de chiffrer la main-d'oeuvre."""

    __slots__ = ()

    def projection_m4(self):
        enveloppe = super().projection_m4()
        _exiger_projection_exploitable(enveloppe)
        return enveloppe


def _exiger_projection_exploitable(enveloppe):
    projection = enveloppe["vue"]["projection"]
    revue, visites = projection.get("revue_chantier"), projection.get("visites")
    if type(revue) is not dict or type(visites) is not list or not visites:
        raise RefusRecalculM4(PROJECTION_NON_EXPLOITABLE, "projection sans revue ni visites")
    if revue.get("statut") != "verifiee":
        raise RefusRecalculM4(REVUE_EN_ATTENTE, "revue finale du chantier non vérifiée")
    for visite in visites:
        equipe = visite.get("equipe_pointee") if type(visite) is dict else None
        if type(equipe) is not dict or equipe.get("statut") != "identifiee":
            # Une déclaration d'équipe n'est pas une présence individuelle ; sans preuve typée, l'équipe est inconnue.
            raise RefusRecalculM4(EQUIPE_INCONNUE, "équipe pointée non établie pour au moins une visite")


def _valider_parametres(session, acteur, wct_id, devis_id, intention_id):
    if type(acteur) is not str or not 1 <= len(acteur) <= 256 or acteur != acteur.strip() or not acteur.isprintable():
        raise RefusRecalculM4(ACTEUR_INVALIDE, "acteur : texte imprimable de 1 à 256 caractères, sans espace de bord")
    if type(intention_id) is not str or not _HEX.fullmatch(intention_id):
        raise RefusRecalculM4(INTENTION_INVALIDE, "intention_id : 64 caractères hexadécimaux minuscules")
    if type(wct_id) is not str or not _HEX.fullmatch(wct_id):
        raise RefusRecalculM4(IDENTIFIANT_INVALIDE, "wct_id : 64 caractères hexadécimaux minuscules")
    if type(devis_id) is not str or not 1 <= len(devis_id) <= 256:
        raise RefusRecalculM4(IDENTIFIANT_INVALIDE, "devis_id : texte de 1 à 256 caractères")
    # Même nature que la console : `Session` (utilisateur, rôles, expiration) ; ni None, ni objet quelconque.
    from .console.securite import Session

    if type(session) is not Session or session.utilisateur != acteur:
        raise RefusRecalculM4(ACTEUR_INVALIDE, "acteur absent de la session ou différent de son utilisateur")


def _exiger_politique(ligne, operation):
    if ligne is None:
        raise RefusRecalculM4(POLITIQUE_ABSENTE, operation)
    if not ligne.active:
        raise RefusRecalculM4(POLITIQUE_REVOQUEE, operation)
    if time() >= ligne.expire_le:
        raise RefusRecalculM4(POLITIQUE_EXPIREE, operation)


def _politiques(cnx, instance):
    """Les deux politiques effectives, ou un refus typé qui nomme l'opération en cause."""
    p, service = recalcul._politique(cnx, instance), sc._politique(cnx, instance, sc._CONSOMMATEUR)
    _exiger_politique(p, _OPERATION)
    _exiger_politique(service, sc._OPERATION)
    return p, service


def _lectures_prealables(wct_id):
    """Contrôles M5 en lecture seule, AVANT tout savepoint : tarifs lisibles, reçu WCT complet."""
    from m5_financecore import outils

    try:
        outils._instantane_tarifs_equipes()
    except (ValueError, TypeError, OverflowError) as exc:
        raise RefusRecalculM4(TARIFS_ILLISIBLES, "historique des tarifs d'équipe illisible") from exc
    try:
        sources = outils._sources_cout_reel()
    except (ValueError, TypeError, OverflowError) as exc:
        raise RefusRecalculM4(SOURCES_M5_ILLISIBLES, "registres M5 non vérifiables") from exc
    recus = [r for r in sources["wct"] if r.get("wct_id") == wct_id]
    if len(recus) == 1 and recus[0].get("empreinte_charge") is None:
        raise RefusRecalculM4(WCT_SANS_EMPREINTE, "reçu WCT historique sans empreinte de charge complète")


def _classer_refus_m4(exc):
    code = exc.args[0] if exc.args and type(exc.args[0]) is str else "INCONNU"
    if code in _SANS_MODELE_VISITES:
        return RefusRecalculM4(WCT_ANTERIEUR_MODELE_VISITES, code)
    cause = exc.__cause__
    if code == "SOURCE-INVALIDE" and type(cause) is ValueError and cause.args == (_FAIT_SANS_OUVERTURE,):
        # Pointages et route sans AUCUNE ouverture de visite : une journée d'avant le modèle de visites d'équipe
        # (le producteur M4 enveloppe ce ValueError dans SOURCE-INVALIDE). Sinon : refus M4 non classé, toujours fermé.
        return RefusRecalculM4(WCT_ANTERIEUR_MODELE_VISITES, _FAIT_SANS_OUVERTURE)
    return RefusRecalculM4(SOURCE_M4_REFUSEE, code)


def _exiger_main_d_oeuvre_certifiee():
    """Défense en profondeur : la trace qui vient d'être écrite doit porter une main-d'oeuvre chiffrée sur une
    projection M4 (sinon le savepoint est annulé : jamais un partiel sous provenance certifiée)."""
    from m5_financecore import cout_reel

    trace = list(stockage.maillons(_DEPARTEMENT_M5, "rentabilite"))[-1]
    if cout_reel._main_d_oeuvre_certifiee(trace):
        return
    codes = {m.get("code") for m in trace["rentabilite"]["cout_reel"].get("manque", ()) if type(m) is dict}
    if "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER" in codes:
        raise RefusRecalculM4(TARIF_ABSENT, "aucun tarif d'équipe ne couvre la date de la visite")
    raise RefusRecalculM4(COUT_NON_CERTIFIE, "main-d'oeuvre non chiffrée par la projection M4")


def recalculer(cnx, session, *, acteur, wct_id, devis_id, intention_id):
    """Recalcule et publie le coût certifié d'un devis, ou refuse sans rien écrire.

    Rend l'un de :
    - `{"statut": "publiee", "version", "attestation"}` : trace, reçu v2, attestation, audits, intention, résultat et
      événement `m5.rentabilite_chantier` écrits ENSEMBLE dans le savepoint de l'appelant ;
    - `{"statut": "deja_executee", "historique"}` : même intention déjà exécutée (relecture, zéro écriture) ;
    - `{"statut": "rien_a_faire", "raison": "etat_certifie_a_jour"}` : une autre intention, mais l'état certifié
      est déjà à jour (même version d'entrées) : zéro écriture nette.

    Tout autre cas lève `RefusRecalculM4` (voir `CODES`) : le savepoint est annulé, la transaction de l'appelant reste
    saine. À appeler HORS de la livraison d'un WCT et hors de toute autre portée de service (jamais dans le savepoint
    qui crée le reçu ou la facture) : un refus ne doit jamais pouvoir les annuler.
    """
    _valider_parametres(session, acteur, wct_id, devis_id, intention_id)
    try:
        return _recalculer(cnx, session, acteur, wct_id, devis_id, intention_id)
    except RefusRecalculM4:
        raise
    except PermissionError as exc:  # inclut RefusAutorite et le refus « admin actif requis »
        raise RefusRecalculM4(AUTORITE_REFUSEE, str(exc)[:200]) from exc


def _recalculer(cnx, session, acteur, wct_id, devis_id, intention_id):
    if cnx.engine.dialect.name != "sqlite":
        raise RefusRecalculM4(BACKEND_NON_SQLITE, "recalcul certifié qualifié pour SQLite seulement")
    if not _verrou_present(cnx.engine):
        raise RefusRecalculM4(VERROU_ECRITURE_ABSENT, "l'engine ne porte pas l'écouteur BEGIN IMMEDIATE")
    if (
        cnx is not stockage.connexion_courante()
        or cnx.get_transaction() is None
        or not cnx.connection.dbapi_connection.in_transaction
        or sc._COURANTE.get() is not None
    ):
        raise RefusRecalculM4(CONTEXTE_INVALIDE, "transaction absente, autre connexion ou portée de service active")
    recalcul._admin(cnx, session)
    instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
    if type(instance) is not str or not instance:
        raise RefusRecalculM4(CONTEXTE_INVALIDE, "instance absente ou invalide")
    politique, service = _politiques(cnx, instance)
    intention = dict(intention_id=intention_id, instance_id=instance, acteur=acteur, wct_id=wct_id, devis_id=devis_id)
    ancienne = cnx.execute(select(INTENTIONS).where(INTENTIONS.c.intention_id == intention_id)).mappings().one_or_none()
    if ancienne is not None:
        if dict(ancienne) != intention:
            raise RefusRecalculM4(INTENTION_EN_CONFLIT, "même intention, paramètres différents")
        historique = recalcul.lire_historique_v2(cnx, session, intention_id)
        if _politiques(cnx, instance) != (politique, service):
            raise RefusRecalculM4(AUTORITE_REFUSEE, "politique modifiée pendant la relecture")
        return {"statut": "deja_executee", "historique": historique}
    _lectures_prealables(wct_id)
    try:
        with cnx.begin_nested():
            return _executer_dans_savepoint(cnx, session, intention, politique, service)
    except _SansEcriture:
        return {"statut": "rien_a_faire", "raison": "etat_certifie_a_jour"}
    except IntegrityError as exc:
        raise RefusRecalculM4(INTENTION_EN_CONFLIT, "intention concurrente ou incohérente") from exc


def _executer_dans_savepoint(cnx, session, intention, politique, service):
    wct_id, devis_id, intention_id = intention["wct_id"], intention["devis_id"], intention["intention_id"]
    cnx.execute(insert(INTENTIONS).values(**intention))
    evt, recu = recalcul._valider_source(cnx, wct_id, devis_id)
    p = _PorteeMoteur(cnx, session, evt, recu, intention["instance_id"], politique)
    jeton = sc._COURANTE.set(p)
    try:
        p._verifier()
        base = sc._base(cnx)
        try:
            faits = sc._figer_faits(sc._faits_m4_verifies(p))
        except ValueError as exc:
            from m4_field_ops.temps_certifies_v2 import Refus as RefusM4

            if isinstance(exc, RefusM4):
                raise _classer_refus_m4(exc) from exc
            raise
        p._verifier()
        audit = cnx.execute(
            insert(SERVICE_AUDIT).values(
                instance_id=intention["instance_id"], consommateur=sc._CONSOMMATEUR, operation=_OPERATION,
                revision=politique.revision, evenement_id=wct_id, action="usage",
            )
        ).inserted_primary_key[0]
        cap = _CapaciteMoteur(
            p, base, intention["instance_id"], service.revision, service.expire_le, faits,
            intention=intention, audit_recalcul=audit,
        )
        from m5_financecore.port_service_m4 import publier

        try:
            resultat = publier(devis_id, cap=cap)
        except RefusRecalculM4:
            raise
        except sc.RefusAutorite:
            raise
        except (ValueError, TypeError, OverflowError) as exc:
            raise _classer_echec(exc) from exc
        statut = resultat.get("statut") if type(resultat) is dict else None
        if statut == "deja_tracee":
            raise _SansEcriture
        if statut in ("en_attente_devis_accepte", "en_attente_travaux_termines"):
            raise RefusRecalculM4(PIECE_M5_ABSENTE, statut)
        if (
            statut != "publiee"
            or type(resultat.get("_controle_final")) is not type(lambda: None)
            or type(resultat.get("attestation")) is not dict
        ):
            raise RefusRecalculM4(ECHEC_RECALCUL, "publication v2 incomplète")
        version = resultat.get("version")
        if type(version) is not str or len(version) > 256:
            raise RefusRecalculM4(ECHEC_RECALCUL, "version invalide")
        _exiger_main_d_oeuvre_certifiee()
        cnx.execute(insert(RESULTATS).values(intention_id=intention_id, statut="publiee", version=version))
        resultat["_controle_final"]()
        p._verifier()
        if _politiques(cnx, intention["instance_id"]) != (politique, service):
            raise RefusRecalculM4(AUTORITE_REFUSEE, "politique modifiée pendant le recalcul")
        histoire = recalcul.lire_historique_v2(cnx, session, intention_id)
        if recalcul._reference_canonique(histoire["attestation"]) != recalcul._reference_canonique(
            resultat["attestation"]
        ):
            raise RefusRecalculM4(ECHEC_RECALCUL, "attestation divergente")
        p._verifier()
        return {"statut": "publiee", "version": version, "attestation": histoire["attestation"]}
    finally:
        p.fermee = True
        sc._COURANTE.reset(jeton)


def _classer_echec(exc):
    texte = str(exc)
    if texte.startswith("tarifs d'équipe"):
        return RefusRecalculM4(TARIFS_ILLISIBLES, "historique des tarifs d'équipe illisible")
    return RefusRecalculM4(ECHEC_RECALCUL, type(exc).__name__)
