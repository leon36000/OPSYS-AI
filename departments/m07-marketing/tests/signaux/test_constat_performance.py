"""D2 : M7 publie, pour M8, des TOTAUX de signaux de performance (`m7.performance_signaux_constatee`).

Vrai registre durable des signaux, vraie base, vrai outil `m7_constater_performance_signaux`, vrai bus (outbox). Prouve
: les
clics, les impressions et les visites du SITE sont sommés (dernière révision de chaque fait) ; un jour sans fait n'est
pas un
zéro (`jours_couverts`) ; une requête, une page ou un référent ne sont jamais sommés ni publiés ; un compte de
démonstration
a son propre résumé marqué ; une mesure absente vaut null ; rejouer ne publie rien, une donnée révisée est une version
de
plus ; période inversée ou illisible refusée sans rien publier. Données FICTIVES.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from m7_marketing import outils, signaux_outils
from m7_marketing.signaux import modele, registre, resume_performance
from m7_marketing.signaux.erreurs import ErreurSignaux
from sqlalchemy import select

from opsys import stockage
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
HORO = "2026-11-01T12:00:00+00:00"
OBSERVE = "2026-11-01T11:00:00+00:00"
EMPREINTE = "a" * 64
_OUTILS = {o.nom: o for o in outils.outils()}
PROVENANCE = {
    "fournisseur": "fictif",
    "point_acces": "fictif",
    "version_api": "v1",
    "mode": "api_lecture",
    "empreinte_reponse": EMPREINTE,
    "page": 0,
}


def _fait(
    source,
    nature,
    jour,
    mesures,
    *,
    portee=("site", "propriete"),
    compte="site-principal",
    fictif=False,
    observe=OBSERVE,
):
    return modele.brouillon_fait(
        source=source,
        compte_ref=compte,
        nature=nature,
        portee_type=portee[0],
        portee_ref=portee[1],
        debut=jour,
        fin=jour,
        mesures=mesures,
        observe_le=observe,
        fictif=fictif,
        provenance=PROVENANCE,
        echantillon={"nature": "complet", "n": None},
    )


def _ecrire(faits):
    with stockage.transaction():
        registre.enregistrer(stockage.maillons(*registre.REGISTRE), faits, HORO)


def _jours(debut, n):
    d = date.fromisoformat(debut)
    return [(d + timedelta(days=i)).isoformat() for i in range(n)]


def _constater(debut="2026-10-01", fin="2026-10-31"):
    return executer_atomique(
        _OUTILS["m7_constater_performance_signaux"], {"debut": debut, "fin": fin, "horodatage": HORO}
    )


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == "m7.performance_signaux_constatee")
            .order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        ).all()
    return [(i, codec.decoder(c)) for i, c in lignes]


def test_le_niveau_est_n2_agent_seulement():
    outil = _OUTILS["m7_constater_performance_signaux"]
    assert (outil.autonomie, outil.niveau_effectif) == (Autonomie.T1, Niveau.N2) and not outil.roles_appareil


def test_clics_impressions_et_visites_du_site_sont_sommes_par_source_avec_les_jours_couverts(base):
    _ecrire(
        [
            _fait(
                "search_console", "performance_recherche_jour", j, {"clics": "10", "impressions": "200", "ctr": "0.05"}
            )
            for j in _jours("2026-10-01", 20)
        ]
        + [_fait("umami", "audience_jour", j, {"visites": "7", "pages_vues": "20"}) for j in _jours("2026-10-01", 31)]
    )
    resultat = _constater()["resultat"]
    assert resultat["accepte"] is True and len(resultat["resumes_publies"]) == 2
    publies = dict(_publies())
    (sc,) = [c for c in publies.values() if c["source"] == "search_console"]
    (um,) = [c for c in publies.values() if c["source"] == "umami"]
    assert (sc["clics"], sc["impressions"], sc["visites"]) == ("200", "4000", None)
    assert (sc["jours_couverts"], sc["jours_periode"]) == (20, 31)  # 11 jours sans fait : jamais des zéros
    assert (um["clics"], um["impressions"], um["visites"]) == (None, None, "217")
    assert um["jours_couverts"] == um["jours_periode"] == 31
    assert sc["fraicheur_fenetre_h"] == 72 and um["fraicheur_fenetre_h"] == 36 and sc["fictif"] is False
    assert sc["derniere_observation_le"] == OBSERVE and sc["compte_ref"] == "site-principal"


def test_la_derniere_revision_d_un_fait_remplace_la_precedente(base):
    _ecrire(
        [_fait("search_console", "performance_recherche_jour", "2026-10-01", {"clics": "10", "impressions": "100"})]
    )
    _ecrire(
        [_fait("search_console", "performance_recherche_jour", "2026-10-01", {"clics": "12", "impressions": "100"})]
    )
    _constater()
    ((_, charge),) = _publies()
    assert charge["clics"] == "12" and charge["jours_couverts"] == 1


def test_une_requete_une_page_un_referent_ne_sont_ni_sommes_ni_publies(base):
    _ecrire(
        [
            _fait("search_console", "performance_recherche_jour", "2026-10-01", {"clics": "10", "impressions": "100"}),
            _fait(
                "search_console",
                "pages_periode",
                "2026-10-01",
                {"clics": "912345", "impressions": "912345"},
                portee=("page", "/secret-fictif"),
            ),
            _fait(
                "search_console",
                "requetes_periode",
                "2026-10-01",
                {"clics": "823456", "impressions": "823456"},
                portee=("requete", "toiture pas chère"),
            ),
            _fait(
                "umami", "referents_periode", "2026-10-01", {"visites": "734567"}, portee=("referent", "autre.example")
            ),
        ]
    )
    _constater()
    ((_, charge),) = _publies()
    assert charge["clics"] == "10" and charge["impressions"] == "100"
    texte = json.dumps(charge, ensure_ascii=False)
    for interdit in ("secret-fictif", "toiture", "autre.example", "912345", "823456", "734567"):
        assert interdit not in texte


def test_un_compte_de_demonstration_a_son_propre_resume_marque(base):
    _ecrire(
        [
            _fait("matomo", "audience_jour", "2026-10-01", {"visites": "5"}, compte="vitrine-demo", fictif=True),
            _fait("matomo", "audience_jour", "2026-10-02", {"visites": "9"}, compte="site-principal"),
        ]
    )
    _constater()
    par_compte = {c["compte_ref"]: c for _, c in _publies()}
    assert par_compte["vitrine-demo"]["fictif"] is True and par_compte["vitrine-demo"]["visites"] == "5"
    assert par_compte["site-principal"]["fictif"] is False and par_compte["site-principal"]["visites"] == "9"


def test_un_fait_hors_de_la_periode_ou_sans_la_mesure_ne_donne_pas_un_zero(base):
    _ecrire(
        [
            _fait("search_console", "performance_recherche_jour", "2026-09-30", {"clics": "50", "impressions": "50"}),
            _fait("bing_webmaster", "performance_recherche_jour", "2026-10-02", {"impressions": "40"}),
        ]
    )
    _constater()
    ((_, charge),) = _publies()
    assert charge["source"] == "bing_webmaster" and charge["clics"] is None and charge["impressions"] == "40"


def test_sans_aucun_fait_rien_n_est_publie_et_le_dit(base):
    resultat = _constater()["resultat"]
    assert resultat["accepte"] is True and resultat["resumes_publies"] == [] and _publies() == []


def test_rejouer_ne_publie_rien_de_plus_une_donnee_nouvelle_est_une_version_de_plus(base):
    _ecrire([_fait("umami", "audience_jour", "2026-10-01", {"visites": "5"})])
    _constater()
    _constater()
    assert len(_publies()) == 1
    _ecrire([_fait("umami", "audience_jour", "2026-10-02", {"visites": "6"})])
    _constater()
    versions = {c["version_donnees"] for _, c in _publies()}
    assert len(_publies()) == 2 and len(versions) == 2


@pytest.mark.parametrize(
    ("debut", "fin"),
    [("2026-10-31", "2026-10-01"), ("2026-02-30", "2026-03-01"), ("2025-01-01", "2026-12-31"), ("hier", "demain")],
)
def test_periode_inversee_illisible_ou_trop_longue_refusee_sans_rien_publier(base, debut, fin):
    resultat = _constater(debut, fin)["resultat"]
    assert resultat["accepte"] is False
    assert resultat["refus"][0]["code"] in {"REJ-SIGNAUX-FENETRE-INVALIDE", "REJ-SIGNAUX-FAIT-INVALIDE"}
    assert _publies() == []


def test_le_module_pur_refuse_une_periode_de_plus_de_367_jours():
    with pytest.raises(ErreurSignaux):
        resume_performance.resumer([], "2025-10-01", "2026-10-31")
    assert resume_performance.resumer([], "2026-10-01", "2026-10-31") == []


def test_l_outil_est_declare_au_manifeste_comme_producteur():
    from pathlib import Path

    from opsys.departements import lire_manifeste

    manifeste = lire_manifeste(Path(signaux_outils.__file__).resolve().parents[2])
    assert "m7.performance_signaux_constatee" in manifeste.evenements_publie
