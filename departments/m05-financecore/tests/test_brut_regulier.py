"""Brouillon brut régulier préparatoire, avec sources fictives."""

from __future__ import annotations

import contextlib
from decimal import Decimal, localcontext
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
from m5_financecore import brut_regulier

from opsys import agent_cfo_grants, contexte, identite, stockage
from opsys.outils import Autonomie, Niveau, executer_atomique

FICTIF = True
DEPARTEMENT = "m05-financecore"
_ADMIN = contexte.IdentiteAppelante("nathan", "admin")
_OWNER = contexte.IdentiteAppelante("nathan", "nathan_owner", source="console")
_GESTIONNAIRE = contexte.IdentiteAppelante("gestion", "manager")
_RACINE_M5 = Path(__file__).resolve().parents[1]
_OUTIL_REGULIER = "m5_preparer_brut_regulier"


def test_calcul_fraction_exacte_et_arrondi_demi_vers_le_haut():
    resultat, verdict = brut_regulier.calculer_brut_regulier("31.25", 6, "centime_demi_superieur")

    assert verdict is None
    assert resultat == {
        "brut_brouillon": "3.13",
        "brut_exact_fraction": {"numerateur_centimes": 18750, "denominateur": 60},
        "minutes_regulieres": 6,
        "devise": "CAD",
    }


def test_calcul_ne_depend_pas_de_la_precision_decimal_ambiante():
    with localcontext() as contexte:
        contexte.prec = 2
        resultat_prec2, refus = brut_regulier.calculer_brut_regulier("999999.99", 59, "centime_demi_superieur")
    assert refus is None

    with localcontext() as contexte:
        contexte.prec = 50
        resultat_prec50, refus = brut_regulier.calculer_brut_regulier("999999.99", 59, "centime_demi_superieur")
    assert refus is None
    assert resultat_prec2 == resultat_prec50


def test_zero_minute_confirme_donne_zero_sans_fraction_inventee():
    resultat, verdict = brut_regulier.calculer_brut_regulier("31.25", 0, "centime_demi_superieur")

    assert verdict is None
    assert resultat["brut_brouillon"] == "0.00"
    assert resultat["brut_exact_fraction"] == {"numerateur_centimes": 0, "denominateur": 60}


def test_taux_doit_etre_texte_decimal_cad_positif_et_borne():
    for taux in ("0", "-1", "NaN", "Infinity", "1e3", "1000000.00", Decimal("31.25"), 31.25):
        resultat, verdict = brut_regulier.calculer_brut_regulier(taux, 60, "centime_demi_superieur")
        assert resultat is None
        assert verdict["code"] == "REJ-SALAIRE-TAUX-INVALIDE"


def test_minutes_sont_des_entiers_courants_non_negatifs():
    for minutes in (-1, True, 1.5, "60"):
        resultat, verdict = brut_regulier.calculer_brut_regulier("31.25", minutes, "centime_demi_superieur")
        assert resultat is None
        assert verdict["code"] == "REJ-SALAIRE-STRUCTURE-INVALIDE"


def test_politique_arrondi_doit_etre_explicitement_supportee():
    resultat, verdict = brut_regulier.calculer_brut_regulier("31.25", 60, "round_half_even")

    assert resultat is None
    assert verdict["code"] == "REJ-SALAIRE-CONTRAT-INVALIDE"


def test_borne_minutes_suit_les_jours_locaux_de_23_et_25_heures():
    assert (
        brut_regulier.limite_minutes_regulieres(
            "2026-11-01",
            "2026-11-01",
            "America/Montreal",
        )
        == 1500
    )
    assert (
        brut_regulier.limite_minutes_regulieres(
            "2026-03-08",
            "2026-03-08",
            "America/Montreal",
        )
        == 1380
    )


def test_periode_est_bornee_a_31_jours_et_refuse_la_date_maximale():
    assert brut_regulier.valider_periode("2026-01-01", "2026-01-31", "UTC") is not None
    assert brut_regulier.valider_periode("2026-01-01", "2026-02-01", "UTC") is None
    assert brut_regulier.valider_periode("9999-12-31", "9999-12-31", "UTC") is None


def test_conversion_utc_non_representable_est_refusee_sans_borne_d_annee_arbitraire():
    assert (
        brut_regulier.limite_minutes_regulieres(
            "0001-01-01",
            "0001-01-01",
            "UTC",
        )
        == 1440
    )
    assert brut_regulier.valider_periode("0001-01-01", "0001-01-01", "Asia/Tokyo") is None
    assert (
        brut_regulier.limite_minutes_regulieres(
            "0001-01-01",
            "0001-01-01",
            "Asia/Tokyo",
        )
        is None
    )
    assert (
        brut_regulier.limite_minutes_regulieres(
            "2026-11-01",
            "2026-11-01",
            "America/Montreal",
        )
        == 1500
    )


@contextlib.contextmanager
def _avec_identite(appelante):
    with contexte.appele_par_appareil(appelante):
        yield


def _projection_m4(technicien_id, debut, fin, fuseau, **overrides):
    projection = {
        "technicien_id": technicien_id,
        "periode": {"debut": debut, "fin": fin, "fuseau": fuseau},
        "minutes_regulieres": 6,
        "ligne_id": "a" * 64,
        "revision": 1,
        "empreinte_sources": "b" * 64,
        "couverture_complete": True,
        "classification_reguliere_confirmee": True,
    }
    projection.update(overrides)
    return {"ok": True, "resultat": {"accepte": True, "resultat": projection}}


@pytest.fixture
def base_paie(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-brut-regulier.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "nathan-fictif-1234", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "employe.fictif", "Employé fictif", "employe-fictif-1234", ["employee"])
        identite.creer_personne(cnx, "gestion", "Gestionnaire fictif", "gestion-fictif-1234", ["manager", "admin"])
    yield
    stockage.liberer()


@pytest.fixture
def port_et_outils(monkeypatch):
    appels = []

    def lecteur(*args):
        appels.append(args)
        return _projection_m4(*args)

    return {outil.nom: outil for outil in m5_outils.outils(lecteur_heures_m4=lecteur)}, appels


def _appeler(outils_par_nom, nom, arguments, appelante):
    with _avec_identite(appelante):
        enveloppe = executer_atomique(outils_par_nom[nom], arguments)
    assert enveloppe["ok"] is True, enveloppe
    return enveloppe["resultat"]


def _contrat_args(**overrides):
    args = {
        "employee_person_id": "employe.fictif",
        "contrat_id": "PAIE-FICTIF-001",
        "valide_du": "2026-09-01",
        "valide_jusqu_au": "2026-10-01",
        "fuseau": "America/Montreal",
        "devise": "CAD",
        "taux_horaire": "31.25",
        "source_humaine": "Contrat fictif RH-001",
        "date_source": "2026-08-31",
        "revision_attendue": 0,
        "ligne_id_attendue": "",
        "motif": "Enregistrement initial fictif",
    }
    args.update(overrides)
    return args


def _enregistrer_contrat(outils_par_nom, **overrides):
    resultat = _appeler(outils_par_nom, "m5_enregistrer_contrat_horaire", _contrat_args(**overrides), _ADMIN)
    assert resultat["accepte"] is True, resultat
    return resultat["resultat"]


def _arguments_brut(**overrides):
    args = {
        "employee_person_id": "employe.fictif",
        "debut": "2026-09-14",
        "fin": "2026-09-14",
        "fuseau": "America/Montreal",
        "politique_arrondi": "centime_demi_superieur",
        "hypothese_arrondi": "Référence de paie fictive PAIE-ROUND-1, non validée",
        "sources_attendues": None,
    }
    args.update(overrides)
    return args


def test_brouillon_regulier_prend_snapshot_m4_et_contrat_m5_sans_ecrire(base_paie, port_et_outils):
    outils_par_nom, appels = port_et_outils
    _enregistrer_contrat(outils_par_nom)
    registres = ("principal", "comptes_a_payer", "contrats_salaries_horaires")
    avant = {nom: list(stockage.maillons(DEPARTEMENT, nom)) for nom in registres}

    with localcontext() as contexte_decimal:
        contexte_decimal.prec = 2
        resultat = _appeler(outils_par_nom, _OUTIL_REGULIER, _arguments_brut(), _OWNER)

    assert resultat["accepte"] is True, resultat
    sortie = resultat["resultat"]
    assert sortie["brut_brouillon"] == "3.13"
    assert sortie["brut_exact_fraction"] == {"numerateur_centimes": 18750, "denominateur": 60}
    assert sortie["minutes_regulieres"] == 6 and sortie["devise"] == "CAD"
    assert sortie["sources"]["heures_m4"] == {
        "ligne_id": "a" * 64,
        "revision": 1,
        "empreinte_sources": "b" * 64,
    }
    assert sortie["sources"]["contrat_m5"]["contrat_id"] == "PAIE-FICTIF-001"
    assert sortie["couverture_complete"] is True
    assert sortie["hypotheses"][0]["verifiee"] is False
    assert sortie["requires_human_validation"] is True and sortie["official_action_blocked"] is True
    assert sortie["mention"]
    assert appels == [("employe.fictif", "2026-09-14", "2026-09-14", "America/Montreal")]
    apres = {nom: list(stockage.maillons(DEPARTEMENT, nom)) for nom in avant}
    assert apres == avant


def test_admin_appareil_est_refuse_avant_journal_et_port(base_paie, port_et_outils, monkeypatch):
    outils_par_nom, appels = port_et_outils

    def interdit():
        raise AssertionError("le registre salarié ne doit pas être lu")

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", interdit)

    resultat = _appeler(outils_par_nom, _OUTIL_REGULIER, _arguments_brut(), _ADMIN)

    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-ACCES-REFUSE"
    assert appels == []


def test_role_manager_choisi_est_refuse_avant_sources(base_paie, port_et_outils, monkeypatch):
    outils_par_nom, appels = port_et_outils

    def interdit():
        raise AssertionError("le registre salarié ne doit pas être lu")

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", interdit)

    resultat = _appeler(outils_par_nom, _OUTIL_REGULIER, _arguments_brut(), _GESTIONNAIRE)

    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] in {"REJ-IDENTITE-APPAREIL-INVALIDE", "REJ-SALAIRE-ACCES-REFUSE"}
    assert appels == []


@pytest.mark.parametrize(
    "projection",
    [
        {"technicien_id": "autre.personne", "secret_pii": "ne pas retourner"},
        {"periode": {"debut": "2026-09-13", "fin": "2026-09-14", "fuseau": "America/Montreal"}},
        {"couverture_complete": False},
        {"classification_reguliere_confirmee": False},
    ],
)
def test_projection_m4_absente_malformee_ou_sans_couverture_refuse_le_brut(base_paie, projection):
    def reader(technicien_id, debut, fin, fuseau):
        resultat = _projection_m4(technicien_id, debut, fin, fuseau)
        resultat["resultat"]["resultat"].update(projection)
        return resultat

    outils_par_nom = {outil.nom: outil for outil in m5_outils.outils(lecteur_heures_m4=reader)}
    _enregistrer_contrat(outils_par_nom)

    resultat = _appeler(outils_par_nom, _OUTIL_REGULIER, _arguments_brut(), _OWNER)

    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-STRUCTURE-INVALIDE"
    assert "secret_pii" not in str(resultat)


def test_sources_attendues_obsoletes_refusent_sans_actualiser_silencieusement(base_paie, port_et_outils):
    outils_par_nom, _ = port_et_outils
    initial = _enregistrer_contrat(outils_par_nom)
    attendu = {
        "heures_m4": {"ligne_id": "a" * 64, "revision": 1, "empreinte_sources": "b" * 64},
        "contrat_m5": {"contrat_id": initial["contrat_id"], "revision": 1, "ligne_id": initial["ligne_id"]},
    }
    _enregistrer_contrat(
        outils_par_nom,
        taux_horaire="32.00",
        revision_attendue=1,
        ligne_id_attendue=initial["ligne_id"],
        motif="Révision fictive",
    )

    resultat = _appeler(
        outils_par_nom,
        _OUTIL_REGULIER,
        _arguments_brut(sources_attendues=attendu),
        _OWNER,
    )

    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-REVISION-PERIMEE"


def test_empreinte_m4_attendue_obsolete_refuse_avant_calcul(base_paie):
    def reader(technicien_id, debut, fin, fuseau):
        return _projection_m4(technicien_id, debut, fin, fuseau, empreinte_sources="c" * 64)

    outils_par_nom = {outil.nom: outil for outil in m5_outils.outils(lecteur_heures_m4=reader)}
    contrat = _enregistrer_contrat(outils_par_nom)
    attendu = {
        "heures_m4": {"ligne_id": "a" * 64, "revision": 1, "empreinte_sources": "b" * 64},
        "contrat_m5": {"contrat_id": contrat["contrat_id"], "revision": 1, "ligne_id": contrat["ligne_id"]},
    }

    resultat = _appeler(
        outils_par_nom,
        _OUTIL_REGULIER,
        _arguments_brut(sources_attendues=attendu),
        _OWNER,
    )

    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-REVISION-PERIMEE"


def test_fuseau_dst_25h_ou_23h_borne_les_minutes_sans_regle_dheures_supplementaires(base_paie):
    def reader(technicien_id, debut, fin, fuseau):
        minutes = 1500 if debut == "2026-11-01" else 1381
        return _projection_m4(technicien_id, debut, fin, fuseau, minutes_regulieres=minutes)

    outils_par_nom = {outil.nom: outil for outil in m5_outils.outils(lecteur_heures_m4=reader)}
    _enregistrer_contrat(outils_par_nom, valide_du="2026-03-01", valide_jusqu_au="2026-12-01")

    automne = _appeler(outils_par_nom, _OUTIL_REGULIER, _arguments_brut(debut="2026-11-01", fin="2026-11-01"), _OWNER)
    printemps = _appeler(outils_par_nom, _OUTIL_REGULIER, _arguments_brut(debut="2026-03-08", fin="2026-03-08"), _OWNER)

    assert automne["accepte"] is True
    assert automne["resultat"]["minutes_regulieres"] == 1500
    assert printemps["accepte"] is False
    assert printemps["verdict"]["code"] == "REJ-SALAIRE-STRUCTURE-INVALIDE"


def test_periode_de_32_jours_et_fin_maximale_refusees_avant_lectures(base_paie, port_et_outils, monkeypatch):
    outils_par_nom, appels = port_et_outils

    def interdit():
        raise AssertionError("le registre salarial ne doit pas être lu")

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", interdit)

    pour_trente_deux_jours = _appeler(
        outils_par_nom, _OUTIL_REGULIER, _arguments_brut(debut="2026-01-01", fin="2026-02-01"), _OWNER
    )
    date_maximale = _appeler(
        outils_par_nom, _OUTIL_REGULIER, _arguments_brut(debut="9999-12-31", fin="9999-12-31"), _OWNER
    )

    assert pour_trente_deux_jours["accepte"] is False
    assert pour_trente_deux_jours["verdict"]["code"] == "REJ-SALAIRE-PERIODE-INVALIDE"
    assert date_maximale["accepte"] is False
    assert date_maximale["verdict"]["code"] == "REJ-SALAIRE-PERIODE-INVALIDE"
    assert appels == []


def test_conversion_utc_non_representable_refuse_avant_journal_et_port(base_paie, port_et_outils, monkeypatch):
    outils_par_nom, appels = port_et_outils

    def interdit():
        raise AssertionError("le journal salarial ne doit pas être lu")

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", interdit)
    resultat = _appeler(
        outils_par_nom,
        _OUTIL_REGULIER,
        _arguments_brut(
            debut="0001-01-01",
            fin="0001-01-01",
            fuseau="Asia/Tokyo",
        ),
        _OWNER,
    )

    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-PERIODE-INVALIDE"
    assert appels == []


def test_port_absent_et_contrat_revoque_refusent_avant_source_m4(base_paie, monkeypatch):
    sans_port = {outil.nom: outil for outil in m5_outils.outils()}
    lire_journal = m5_outils._registre_contrats_salaries

    def interdit():
        raise AssertionError("le registre salarial ne doit pas être lu")

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", interdit)
    absent = _appeler(sans_port, _OUTIL_REGULIER, _arguments_brut(), _OWNER)
    assert absent["accepte"] is False
    assert absent["verdict"]["code"] == "REJ-SALAIRE-STRUCTURE-INVALIDE"

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", lire_journal)
    appels = []

    def reader(*args):
        appels.append(args)
        return _projection_m4(*args)

    outils_par_nom = {outil.nom: outil for outil in m5_outils.outils(lecteur_heures_m4=reader)}
    contrat = _enregistrer_contrat(outils_par_nom)
    revocation = _appeler(
        outils_par_nom,
        "m5_revoquer_contrat_horaire",
        {
            "employee_person_id": "employe.fictif",
            "contrat_id": contrat["contrat_id"],
            "revision_attendue": 1,
            "ligne_id_attendue": contrat["ligne_id"],
            "motif": "Fin fictive",
        },
        _ADMIN,
    )
    assert revocation["accepte"] is True
    lu = _appeler(outils_par_nom, _OUTIL_REGULIER, _arguments_brut(), _OWNER)
    assert lu["accepte"] is False
    assert lu["verdict"]["code"] == "REJ-SALAIRE-CONTRAT-REVOQUE"
    assert appels == []


def test_cible_sans_role_employee_refuse_avant_sources(base_paie, port_et_outils, monkeypatch):
    outils_par_nom, appels = port_et_outils

    def interdit():
        raise AssertionError("le registre salarial ne doit pas être lu")

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", interdit)
    resultat = _appeler(
        outils_par_nom,
        _OUTIL_REGULIER,
        _arguments_brut(employee_person_id="gestion"),
        _OWNER,
    )
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-EMPLOYE-INVALIDE"
    assert appels == []


def test_outil_brut_n_est_pas_ajoute_aux_grants_cfo_agents():
    assert _OUTIL_REGULIER not in agent_cfo_grants.OUTILS


def test_outil_brut_n_annonce_pas_de_capacite_appareil():
    outils_par_nom = {outil.nom: outil for outil in m5_outils.outils()}
    assert outils_par_nom[_OUTIL_REGULIER].roles_appareil == frozenset()
    assert outils_par_nom["m5_preparer_dossier_webras"].roles_appareil == frozenset()
    assert outils_par_nom["m5_enregistrer_echeancier_contrat"].roles_appareil == frozenset()
    assert outils_par_nom["m5_revoquer_echeancier_contrat"].roles_appareil == frozenset()
    assert outils_par_nom["m5_prevoir_tresorerie_contrats"].roles_appareil == frozenset()
    assert outils_par_nom["m5_enregistrer_echeancier_contrat"].autonomie == Autonomie.T2
    assert outils_par_nom["m5_enregistrer_echeancier_contrat"].niveau_effectif == Niveau.N4
    assert outils_par_nom["m5_revoquer_echeancier_contrat"].autonomie == Autonomie.T2
    assert outils_par_nom["m5_revoquer_echeancier_contrat"].niveau_effectif == Niveau.N4
    assert outils_par_nom["m5_prevoir_tresorerie_contrats"].autonomie == Autonomie.T0
