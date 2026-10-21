"""Suivi interne des rappels réellement reliés à un appel M1 importé."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from m1_front_office import outils, transferts
from m1_front_office.registre import Registre

from opsys import contexte, stockage
from opsys.console import metier
from opsys.outils import Autonomie, Niveau

TRANSFERT_ID = "transfert-rappel-fictif-001"
HORODATAGE = "2026-10-04T12:00:00+00:00"


def _registre(*, type_transfert="ventes", avec_source=True):
    reg = Registre()
    reg.ajouter({
        "type_entree": "transfert", "evenement": "ouvert", "transfert_id": TRANSFERT_ID,
        "type_transfert": type_transfert, "horodatage": HORODATAGE,
    })
    if avec_source:
        reponse = {
            "accepte": True, "source": "journal-appels-fictif", "appel_id": "appel-fictif-001",
            "statut": "manque", "tache_rappel": {"transfert_id": TRANSFERT_ID, "statut": "ouvert"},
        }
        reg.ajouter({
            "type_entree": "appel_importe", "source": reponse["source"], "appel_id": reponse["appel_id"],
            "statut": reponse["statut"], "horodatage": HORODATAGE, "reponse": reponse,
        })
    return reg


def _installer(monkeypatch, *, acteur=None, type_transfert="ventes", avec_source=True):
    lignes = _registre(type_transfert=type_transfert, avec_source=avec_source).lire()
    port = stockage.MaillonsDurables("m01-front-office", "principal")
    registre = Registre(maillons=port)

    def lire():
        return copy.deepcopy(lignes)

    def ajouter(entree):
        durable = Registre(copy.deepcopy(lignes))
        identifiant = durable.ajouter(entree)
        lignes[:] = durable.lire()
        return identifiant

    registre.lire = lire
    registre.ajouter = ajouter
    cnx = SimpleNamespace(
        dialect=SimpleNamespace(name="sqlite"),
        in_transaction=lambda: True,
    )
    monkeypatch.setattr(outils, "_stockage_durable_actif", True)
    monkeypatch.setattr(outils, "_obtenir_registre", lambda: registre)
    monkeypatch.setattr(stockage, "connexion_courante", lambda: cnx)
    monkeypatch.setattr(outils.approbations, "signataire_valide", lambda _cnx, appelante: appelante)
    monkeypatch.setattr(contexte, "identite_appelante", lambda: acteur)
    # Fixture unitaire simulée; les quotas SQL et l'autorité réelle sont testés en HTTP.
    monkeypatch.setattr(outils.lecture_m1, "borner", lambda _cnx: len(lignes))
    return lignes


def _maintenant_et_echeance():
    maintenant = datetime.now(UTC)
    echeance = maintenant + timedelta(days=1)
    return maintenant.isoformat(timespec="microseconds"), echeance.isoformat(timespec="seconds")


def _acteur(personne="owner-rappel", role="nathan_owner"):
    return contexte.IdentiteAppelante(personne, role, source="console")


def _consigner(action, snapshot, *, prochaine=None, horodatage=None):
    maintenant, echeance = _maintenant_et_echeance()
    return outils.consigner_suivi_rappel(
        TRANSFERT_ID,
        action,
        snapshot,
        horodatage or maintenant,
        prochaine_tentative_le=echeance if prochaine is True else prochaine,
    )


def test_outil_est_une_commande_interne_t1_n2_sans_approbation_n3():
    outil = next(element for element in outils.outils() if element.nom == "m1_consigner_suivi_rappel")

    assert outil.autonomie is Autonomie.T1
    assert outil.niveau is Niveau.N2
    assert outil.roles_appareil == frozenset()
    assert metier.COMMANDES[outil.nom] == "m01-front-office"
    assert outil.nom not in metier.DECISIONS_HUMAINES


def test_projection_disponible_uniquement_pour_source_d_appel_canonique():
    sans_appel = _registre(avec_source=False).lire()
    avec_appel = _registre().lire()

    assert transferts.projection_suivi_rappel(sans_appel, TRANSFERT_ID) is None
    projection = transferts.projection_suivi_rappel(avec_appel, TRANSFERT_ID)
    assert projection is not None
    assert projection["responsable"] is None
    assert projection["tentatives_sans_contact"] == 0
    assert set(projection) == {
        "snapshot_suivi", "responsable", "role", "pris_en_charge_le", "tentatives_sans_contact",
        "derniere_tentative_le", "prochaine_tentative_le",
    }


def test_prise_en_charge_et_tentative_sans_contact_restent_non_terminales(monkeypatch):
    lignes = _installer(monkeypatch, acteur=_acteur())
    avant = transferts.projection_suivi_rappel(lignes, TRANSFERT_ID)

    prise = _consigner(transferts.EVT_PRISE_EN_CHARGE, avant["snapshot_suivi"])
    assert prise["accepte"] is True
    prise_projection = prise["resultat"]["suivi_rappel"]
    assert prise_projection["responsable"] == "owner-rappel"
    assert prise_projection["role"] == "nathan_owner"
    assert len(lignes) == 3
    assert transferts.lire(lignes)[0].ouvert is True

    maintenant, echeance = _maintenant_et_echeance()
    tentative = outils.consigner_suivi_rappel(
        TRANSFERT_ID, transferts.EVT_TENTATIVE_SANS_CONTACT, prise_projection["snapshot_suivi"], maintenant,
        prochaine_tentative_le=echeance,
    )
    assert tentative["accepte"] is True
    rappel = tentative["resultat"]["suivi_rappel"]
    assert rappel["responsable"] == "owner-rappel"
    assert rappel["tentatives_sans_contact"] == 1
    assert rappel["prochaine_tentative_le"].endswith("+00:00")
    assert transferts.lire(lignes)[0].ouvert is True


def test_transfert_ventes_sans_source_appel_est_refuse_sans_maillon(monkeypatch):
    lignes = _installer(monkeypatch, acteur=_acteur(), avec_source=False)
    avant = copy.deepcopy(lignes)
    reponse = _consigner(transferts.EVT_PRISE_EN_CHARGE, "0" * 64)

    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-SUIVI-RAPPEL-CONFLIT-SOURCE-APPEL-ABSENTE"
    assert lignes == avant


def test_source_appel_liee_a_un_autre_type_de_transfert_est_refusee(monkeypatch):
    lignes = _installer(monkeypatch, acteur=_acteur(), type_transfert="plainte")
    avant = copy.deepcopy(lignes)
    snapshot = transferts.projection_suivi_rappel(lignes, TRANSFERT_ID)["snapshot_suivi"]
    reponse = _consigner(transferts.EVT_PRISE_EN_CHARGE, snapshot)

    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-SUIVI-RAPPEL-CONFLIT-TYPE-INELIGIBLE"
    assert lignes == avant


def test_transfert_deja_clos_refuse_sans_append(monkeypatch):
    lignes = _installer(monkeypatch, acteur=_acteur())
    fermeture = Registre(copy.deepcopy(lignes))
    fermeture.ajouter({
        "type_entree": "transfert", "evenement": "clos", "transfert_id": TRANSFERT_ID,
        "clos_par": "owner-rappel", "role": "nathan_owner", "voie": "console",
        "motif": "Dossier traité par la personne responsable.", "horodatage": HORODATAGE,
    })
    lignes[:] = fermeture.lire()
    avant = copy.deepcopy(lignes)
    snapshot = transferts.projection_suivi_rappel(lignes, TRANSFERT_ID)["snapshot_suivi"]

    reponse = _consigner(transferts.EVT_PRISE_EN_CHARGE, snapshot)

    assert reponse["verdict"]["code"] == "REJ-SUIVI-RAPPEL-CONFLIT-TRANSFERT-CLOS"
    assert lignes == avant


def test_snapshot_perime_attribution_existante_et_non_attributaire_sont_refuses(monkeypatch):
    lignes = _installer(monkeypatch, acteur=_acteur())
    projection = transferts.projection_suivi_rappel(lignes, TRANSFERT_ID)
    prise = _consigner(transferts.EVT_PRISE_EN_CHARGE, projection["snapshot_suivi"])
    courant = prise["resultat"]["suivi_rappel"]

    stale = _consigner(transferts.EVT_PRISE_EN_CHARGE, projection["snapshot_suivi"])
    deja_attribue = _consigner(transferts.EVT_PRISE_EN_CHARGE, courant["snapshot_suivi"])
    assert stale["verdict"]["code"] == "REJ-SUIVI-RAPPEL-CONFLIT-SNAPSHOT-PERIME"
    assert deja_attribue["verdict"]["code"] == "REJ-SUIVI-RAPPEL-CONFLIT-DEJA-ATTRIBUE"

    monkeypatch.setattr(contexte, "identite_appelante", lambda: _acteur("admin-rappel", "admin"))
    maintenant, echeance = _maintenant_et_echeance()
    autre = outils.consigner_suivi_rappel(
        TRANSFERT_ID, transferts.EVT_TENTATIVE_SANS_CONTACT, courant["snapshot_suivi"], maintenant,
        prochaine_tentative_le=echeance,
    )
    assert autre["verdict"]["code"] == "REJ-SUIVI-RAPPEL-CONFLIT-NON-ATTRIBUTAIRE"


def test_absence_identite_agent_et_echeances_invalides_sont_refusees(monkeypatch):
    lignes = _installer(monkeypatch, acteur=None)
    snapshot = transferts.projection_suivi_rappel(lignes, TRANSFERT_ID)["snapshot_suivi"]
    absent = _consigner(transferts.EVT_PRISE_EN_CHARGE, snapshot)
    assert absent["verdict"]["code"] == "REJ-SUIVI-RAPPEL-HUMAIN-REQUIS"
    assert lignes == _registre().lire()

    monkeypatch.setattr(contexte, "identite_appelante", lambda: _acteur("agent-rappel", "system_agent"))
    agent = _consigner(transferts.EVT_PRISE_EN_CHARGE, snapshot)
    assert agent["verdict"]["code"] == "REJ-SUIVI-RAPPEL-ROLE-INSUFFISANT"

    monkeypatch.setattr(contexte, "identite_appelante", lambda: _acteur())
    maintenant, _ = _maintenant_et_echeance()
    for echeance in (
        "2026-10-05T09:00:00", "２０２６-10-05T09:00:00+00:00", "2026-10-03T09:00:00+00:00",
    ):
        refus = outils.consigner_suivi_rappel(
            TRANSFERT_ID, transferts.EVT_TENTATIVE_SANS_CONTACT, snapshot, maintenant,
            prochaine_tentative_le=echeance,
        )
        assert refus["accepte"] is False
    assert len(lignes) == 2


def test_chaine_alteree_ferme_le_suivi_sans_append(monkeypatch):
    lignes = _installer(monkeypatch, acteur=_acteur())
    snapshot = transferts.projection_suivi_rappel(lignes, TRANSFERT_ID)["snapshot_suivi"]
    lignes[0]["type_transfert"] = "plainte"

    reponse = _consigner(transferts.EVT_PRISE_EN_CHARGE, snapshot)

    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-SUIVI-RAPPEL-CHAINE-ALTEREE"
    assert len(lignes) == 2
