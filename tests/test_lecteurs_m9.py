"""Port privé M9 → producteurs (RACCORD COMMUN) : liste blanche, identité admin relue, refus avant lecture (fictif)."""

from __future__ import annotations

import pytest
from m2_revenue_crm import outils as m2
from m9_strategic_intelligence import catalogue_producteurs
from sqlalchemy import select

from opsys import contexte, identite, lecteurs_m9, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.stockage.schema import META

FICTIF = True
M9 = "m09-strategic-intelligence"
ARGS_M2 = {"horodatage": "2026-10-21T12:00:00Z"}
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'lecteurs-m9.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
        identite.creer_personne(cnx, "employe.fictif", "Employé", "mot-de-passe-employe-12", ["employee"])
        identite.creer_personne(cnx, "ancien.admin", "Ancien", "mot-de-passe-ancien-123", ["admin"], actif=False)
    yield
    m2.reinitialiser_registre()
    stockage.liberer()


def _capacites(*departements):
    return Capacites(charger_departements(), stockage.transaction, filtre={M9, *departements}, memoire=False)


def _capturer(capacites, identite_appelante, lecture="m2.leads", arguments=None):
    arguments = ARGS_M2 if arguments is None else arguments
    appel = {"lecture_id": lecture, "arguments": arguments, "horodatage": "2026-10-21T12:00:01Z"}
    if identite_appelante is None:
        return capacites.appeler("m9_capturer_producteur", appel)
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler("m9_capturer_producteur", appel)


def _etat():
    with stockage.transaction() as cnx:
        return {nom: sorted(map(str, cnx.execute(select(t)).fetchall())) for nom, t in META.tables.items()}


def test_liste_blanche_du_socle_egale_celle_du_catalogue_pur():
    attendu = catalogue_producteurs.lectures_par_departement()
    assert {d: set(o) for d, o in lecteurs_m9.LECTURES_AUTORISEES.items()} == {d: set(o) for d, o in attendu.items()}


def test_liste_blanche_n_expose_que_des_outils_reels_t0_n0():
    departements = charger_departements()
    capacites = Capacites(departements, stockage.transaction, memoire=False)
    for departement, outils in lecteurs_m9.LECTURES_AUTORISEES.items():
        for nom in outils:
            propriétaire, outil = capacites.index[nom]
            assert propriétaire is not None and propriétaire.id == departement
            assert outil.autonomie.value == "T0" and outil.niveau_effectif.value == "N0", nom


def test_admin_console_capture_une_lecture_reelle_de_m2(base):
    assert m2.ingerer_lead(_contrat("lead-un1"), "2026-09-01T09:00:00-04:00")["accepte"] is True
    reponse = _capturer(_capacites("m02-revenue-crm"), ADMIN)
    capture = reponse["resultat"]["capture"]
    assert reponse["ok"] is True and capture["verdict"] == "ACCEPTEE" and capture["complete"] is True
    assert capture["instants_metier"]["min"] == "2026-09-01T13:00:00Z"


def test_refus_avant_toute_lecture_et_sans_ecriture(base):
    capacites = _capacites("m02-revenue-crm")
    cas = [
        None,  # un agent : aucune identité
        IdentiteAppelante("vendeur.fictif", "seller", source="console"),
        IdentiteAppelante("employe.fictif", "employee", source="console"),
        IdentiteAppelante("ancien.admin", "admin", source="console"),  # personne désactivée
        IdentiteAppelante("inconnu.fictif", "admin", source="console"),
        IdentiteAppelante("admin.fictif", "admin", source="jeton-inconnu"),
    ]
    for identite_appelante in cas:
        avant = _etat()
        reponse = _capturer(capacites, identite_appelante)
        texte = str(reponse)
        assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False, texte
        assert "lead-" not in texte
        assert not any([ligne for ligne in _etat()["registres_maillons"] if "captures_strategiques" in ligne]), texte
        assert _etat() == avant or all(
            nom in {"journal", "mutations_appliquees"} for nom, valeur in _etat().items() if valeur != avant[nom]
        )


def test_role_admin_retire_apres_ouverture_est_revele_en_base(base):
    capacites = _capacites("m02-revenue-crm")
    assert _capturer(capacites, ADMIN)["ok"] is True
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    refus = _capturer(capacites, ADMIN)
    assert refus["ok"] is False or refus["resultat"].get("accepte") is False


def test_lecture_hors_liste_blanche_ou_producteur_absent_refuses(base):
    capacites = _capacites("m02-revenue-crm")
    lecteur = lecteurs_m9.construire_lecteur(charger_departements(), stockage.transaction)
    with stockage.transaction():
        with contexte.appele_par_appareil(ADMIN), contexte.appeler_en_tant_que(M9, origine=M9):
            assert lecteur("m02-revenue-crm", "m2_ingerer_lead", {})["erreur"] == "lecture_non_autorisee"
            assert lecteur("m02-revenue-crm", "m2_preparer_relance", {})["erreur"] == "lecture_non_autorisee"
            assert lecteur("m99-inconnu", "m2_lister_leads", {})["erreur"] == "producteur_indisponible"
        # hors contexte M9 : le port n'est pas un accès général
        with contexte.appele_par_appareil(ADMIN):
            reponse = lecteur("m02-revenue-crm", "m2_lister_leads", ARGS_M2)
            assert reponse["erreur"] == "identite_admin_requise"
    # Un producteur non installé est un manque conservé, pas une exception.
    sans_m6 = {k: v for k, v in charger_departements().items() if k != "m06-material-control"}
    capacites = Capacites(sans_m6, stockage.transaction, filtre={M9, "m02-revenue-crm"}, memoire=False)
    reponse = _capturer(capacites, ADMIN, lecture="m6.disponibilite", arguments={})
    assert reponse["resultat"]["capture"]["verdict"] == "ERREUR"
    assert reponse["resultat"]["capture"]["code"] == "producteur_indisponible"


def test_arguments_non_declares_et_lecture_inconnue_refuses(base):
    capacites = _capacites("m02-revenue-crm")
    assert _capturer(capacites, ADMIN, arguments={**ARGS_M2, "role": "admin"})["ok"] is False
    assert _capturer(capacites, ADMIN, lecture="m2.tout")["ok"] is False


def test_seul_m9_recoit_le_port():
    departements = charger_departements()
    m3 = departements["m03-estimation"]
    with pytest.raises(ValueError, match="port privé non autorisé"):
        m3.charger_outils(ports_prives={"lecteur_producteurs_m9": lambda *a, **k: {}})
    m9 = departements[M9]
    with pytest.raises(ValueError, match="port privé non autorisé"):
        m9.charger_outils(ports_prives={"lecteur_heures_m4": lambda *a, **k: {}})
    with pytest.raises(ValueError, match="port privé non autorisé"):
        m9.charger_outils(ports_prives={"lecteur_producteurs_m9": "pas appelable"})


def _contrat(lead_id):
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }  # fmt: skip
