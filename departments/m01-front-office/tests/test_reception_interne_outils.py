"""Les trois outils de la réception interne (lire, consigner, calculer les KPI) : déclaration, refus typés, idempotence
et
lecture seule sur une base SQLite jetable. Données FICTIVES ; aucun HTTP ni fournisseur."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
import yaml
from m1_front_office import outils
from m1_front_office import reception_interne as rec
from m1_front_office import reception_interne_outils as ri
from sqlalchemy import func, select

from opsys import contexte, stockage, taxonomie
from opsys import service_acteur_systeme as systeme
from opsys.outils import Autonomie, Niveau
from opsys.stockage.schema import REGISTRES

FICTIF = True
MAINTENANT = "2026-11-09T21:00:00-05:00"
CLIENT = "+15145550177"


@contextmanager
def _tour():
    """Un tour du planificateur durable : seul contexte où les outils de cette réception écrivent."""
    with systeme.contexte_planificateur():
        yield


def _outil(nom):
    return next(o for o in outils.outils() if o.nom == nom)


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    stockage.migrer()
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval"])
    taxonomie.enregistrer_fenetre_conversation(60)
    outils.utiliser_stockage_durable()
    yield tmp_path
    stockage.liberer()
    outils.utiliser_stockage_durable()


def _lignes_avis():
    with stockage.transaction():
        return list(stockage.maillons("m01-front-office", rec.REGISTRE))


def test_les_trois_outils_sont_declares_n0_ou_n2_agent_seulement_et_le_manifeste_les_connait():
    attendus = {
        "m1_lire_attentes_reception": (Autonomie.T0, Niveau.N0),
        "m1_consigner_a_voir_reception": (Autonomie.T1, Niveau.N2),
        "m1_calculer_kpis": (Autonomie.T1, Niveau.N2),
    }
    for nom, (autonomie, niveau) in attendus.items():
        outil = _outil(nom)
        assert outil.autonomie is autonomie and outil.niveau is niveau and outil.roles_appareil == frozenset(), nom
        assert not outil.frontiere_humaine and outil.parametres["additionalProperties"] is False
    manifeste = yaml.safe_load(
        (outils.Path(__file__).resolve().parents[1] / "department.yaml").read_text(encoding="utf-8")
    )
    declares = {o for r in manifeste["routines_planifiees"] for o in r["outils"]}
    assert declares == set(attendus)


@pytest.mark.parametrize(
    "arguments, code",
    [
        ({"maintenant": "2026-11-09T21:00:00"}, "REJ-HORODATAGE-INVALIDE"),
        ({"maintenant": "demain"}, "REJ-HORODATAGE-INVALIDE"),
        ({"maintenant": MAINTENANT, "jour": "2026-13-45"}, "REJ-DIGEST-DATE-INVALIDE"),
        ({"maintenant": MAINTENANT, "jour": "09/11/2026"}, "REJ-DIGEST-DATE-INVALIDE"),
        ({"maintenant": MAINTENANT, "delai_controle_s": 5}, "REJ-RECEPTION-DELAI-INVALIDE"),
        ({"maintenant": MAINTENANT, "delai_controle_s": 86401}, "REJ-RECEPTION-DELAI-INVALIDE"),
        ({"maintenant": MAINTENANT, "delai_controle_s": True}, "REJ-RECEPTION-DELAI-INVALIDE"),
        ({"maintenant": MAINTENANT, "delai_controle_s": "300"}, "REJ-RECEPTION-DELAI-INVALIDE"),
    ],
)
def test_la_lecture_et_la_consignation_refusent_une_entree_invalide_avant_toute_lecture(arguments, code):
    refus = ri.lire_attentes_reception(**arguments)
    assert refus["accepte"] is False and refus["verdict"]["code"] == code
    refus = ri.consigner_a_voir_reception("echeances", **arguments)
    assert refus["accepte"] is False and refus["verdict"]["code"] == code


def test_un_groupe_inconnu_est_refuse_et_une_fenetre_de_kpi_invalide_aussi(monde):
    assert ri.consigner_a_voir_reception("tout", MAINTENANT)["verdict"]["code"] == "REJ-RECEPTION-GROUPE-INCONNU"
    for jours in (0, 367, "30", True):
        refus = ri.calculer_kpis("2026-11-09", MAINTENANT, jours)
        assert refus["verdict"]["code"] == "REJ-RECEPTION-FENETRE-INVALIDE", jours
    assert (
        ri.calculer_kpis("2026-11-09", MAINTENANT, 30, ecrire="oui")["verdict"]["code"]
        == "REJ-RECEPTION-FENETRE-INVALIDE"
    )


def test_sans_transaction_de_l_instance_rien_n_est_ecrit():
    with _tour():
        refus = ri.consigner_a_voir_reception("echeances", MAINTENANT)
    assert refus["verdict"]["code"] == "REJ-RECEPTION-STOCKAGE"
    assert ri.attentes_reception() == []  # lecture sans connexion : aucune attente, jamais une panne


def test_l_ecriture_est_reservee_au_planificateur_un_agent_ne_peut_pas_forger_un_avis(monde):
    """Un agent (ou une personne) qui appellerait l'outil avec un instant ou un jour forgé occuperait la clé d'un avis :
    refusé avant toute lecture, comme les KPI (`ecrire` vrai). La lecture et le calcul à blanc restent ouverts."""
    with stockage.transaction():
        for appel in (
            lambda: ri.consigner_a_voir_reception("digest", MAINTENANT, "2099-12-31"),
            lambda: ri.consigner_a_voir_reception("echeances", MAINTENANT),
            lambda: ri.calculer_kpis("2026-11-09", MAINTENANT, 30),
        ):
            assert appel()["verdict"]["code"] == "REJ-RECEPTION-PLANIFICATEUR-REQUIS"
        assert ri.calculer_kpis("2026-11-09", MAINTENANT, 30, ecrire=False)["accepte"] is True
        assert ri.lire_attentes_reception(MAINTENANT)["accepte"] is True
    assert _lignes_avis() == []
    # L'acteur système fermé (tour terminé) ne vaut plus rien non plus.
    with _tour():
        pass
    with stockage.transaction():
        assert ri.consigner_a_voir_reception("echeances", MAINTENANT)["verdict"]["code"] == (
            "REJ-RECEPTION-PLANIFICATEUR-REQUIS"
        )


def test_un_appareil_non_admin_ne_lit_ni_n_ecrit(monde):
    employe = contexte.IdentiteAppelante("employe-fictif", "employee")
    with stockage.transaction(), contexte.appele_par_appareil(employe):
        assert ri.lire_attentes_reception(MAINTENANT)["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
        assert (
            ri.consigner_a_voir_reception("echeances", MAINTENANT)["verdict"]["code"]
            == "REJ-IDENTITE-APPAREIL-INVALIDE"
        )
        assert ri.calculer_kpis("2026-11-09", MAINTENANT)["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _lignes_avis() == []


def test_le_digest_exige_son_jour_et_l_urgence_son_delai_la_lecture_dit_null_pas_zero(monde):
    with _tour(), stockage.transaction():
        lecture = ri.lire_attentes_reception(MAINTENANT)["resultat"]
        assert lecture["a_consigner"] == {
            "digest": None,
            "urgences": None,
            "echeances": 0,
        }  # arguments absents : ni 0 ni 1
        assert ri.consigner_a_voir_reception("digest", MAINTENANT)["verdict"]["code"] == "REJ-RECEPTION-JOUR-REQUIS"
        assert ri.consigner_a_voir_reception("urgences", MAINTENANT)["verdict"]["code"] == "REJ-RECEPTION-DELAI-REQUIS"
        complete = ri.lire_attentes_reception(MAINTENANT, "2026-11-09", 300)["resultat"]
        assert complete["a_consigner"] == {"digest": 1, "urgences": 0, "echeances": 0}
        assert complete["lots"]["digest"] and complete["lots"]["urgences"] is None
    assert _lignes_avis() == []  # la lecture n'a rien écrit


def test_consigner_est_idempotent_et_la_lecture_dit_ensuite_zero_a_consigner(monde):
    with _tour(), stockage.transaction():
        premier = ri.consigner_a_voir_reception("digest", MAINTENANT, "2026-11-09")["resultat"]
        second = ri.consigner_a_voir_reception("digest", MAINTENANT, "2026-11-09")["resultat"]
        autre_jour = ri.consigner_a_voir_reception("digest", MAINTENANT, "2026-11-10")["resultat"]
        lecture = ri.lire_attentes_reception(MAINTENANT, "2026-11-09", 300)["resultat"]
    assert (premier["ecrits"], second["ecrits"], autre_jour["ecrits"]) == (1, 0, 1)
    assert lecture["a_consigner"]["digest"] == 0 and lecture["dernier_digest"]["jour"] == "2026-11-10"
    avis = _lignes_avis()
    assert [a["jour"] for a in avis] == ["2026-11-09", "2026-11-10"] and avis[1]["precedent_ligne_id"] == avis[0][
        "ligne_id"
    ]


def test_le_registre_interne_est_a_part_et_ne_change_pas_le_registre_anti_perte(monde):
    with _tour(), stockage.transaction() as cnx:
        avant = cnx.execute(
            select(func.count())
            .select_from(REGISTRES)
            .where(REGISTRES.c.departement == "m01-front-office", REGISTRES.c.registre == "principal")
        ).scalar_one()
        ri.consigner_a_voir_reception("digest", MAINTENANT, "2026-11-09")
        apres = cnx.execute(
            select(func.count())
            .select_from(REGISTRES)
            .where(REGISTRES.c.departement == "m01-front-office", REGISTRES.c.registre == "principal")
        ).scalar_one()
    assert avant == apres == 0
    from m1_front_office import digest

    assert "avis_reception" not in str(digest.TYPES)  # le digest du registre anti-perte ne les voit jamais


def test_les_kpi_ne_s_ecrivent_qu_une_fois_par_contenu_et_jamais_en_lecture_seule(monde):
    with _tour(), stockage.transaction():
        blanc = ri.calculer_kpis("2026-11-09", MAINTENANT, 30, ecrire=False)["resultat"]
        assert blanc["ecrit"] is False and _lignes_avis_dans_tx() == []
        un = ri.calculer_kpis("2026-11-09", MAINTENANT, 30)["resultat"]
        deux = ri.calculer_kpis("2026-11-09", MAINTENANT, 30)["resultat"]
    assert (un["ecrit"], deux["ecrit"]) == (True, False)
    assert set(un["kpis"]) == set(rec.KPI_IDS) and [a["type_entree"] for a in _lignes_avis()] == ["kpis_reception"]


def _lignes_avis_dans_tx():
    return list(stockage.maillons("m01-front-office", rec.REGISTRE))


def test_les_attentes_ne_font_jamais_taire_la_file_de_m1_meme_si_le_registre_depasse_la_borne(monde, monkeypatch):
    """`attentes()` d'un département qui échoue est sautée EN ENTIER par la file « À voir » : la lecture des avis ne
    borne donc pas le registre (comme celle des transferts), alors que les outils de lecture et de consignation le
    bornent."""
    with _tour(), stockage.transaction():
        ri.consigner_a_voir_reception("digest", MAINTENANT, "2026-11-09")

    def trop_gros(cnx):
        raise RuntimeError("source non qualifiée")

    monkeypatch.setattr(ri.lecture_m1, "borner", trop_gros)
    with stockage.transaction():
        assert [a["type"] for a in outils.attentes()] == ["digest_reception"]
        with pytest.raises(RuntimeError, match="source non qualifiée"):
            ri.lire_attentes_reception(MAINTENANT)
