"""M9.9 — prévisions consolidées : citées, versionnées, jamais produites par M9 (captures fictives)."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import previsions as pv

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"


def _prevision(
    jour="2026-10-20", prevision_id="p" * 64, solde="20000.00", alerte="OK", reserves=(), semaines=6, horizon=6
):
    return {
        "ok": True,
        "resultat": {
            "accepte": True,
            "resultat": {
                "type": "PREVISION_TRESORERIE",
                "aujourd_hui": jour,
                "horizon_semaines": horizon,
                "fin_horizon": "2026-12-01",
                "solde_initial": {"montant": solde, "fraicheur": {"derniere_piece": "2026-10-19T16:00:00Z"}},
                "calculable": True,
                "non_calculable_a_partir_de": None,
                "manque": [],
                "semaines": [{"semaine": n, "solde_fin": "1.00"} for n in range(1, semaines + 1)],
                "alerte": {"statut": alerte},
                "premiere_semaine_en_deficit": None,
                "encaissements_non_comptes": [],
                "reserves": list(reserves),
                "prevision_id": prevision_id,
                "prochain_depart": None,
            },
        },
    }


def _chaine(*specs):
    """specs : (reponse, recu_a, jour, kwargs_construire)."""
    chaine, precedent = [], cs.HASH_INITIAL
    for index, (reponse, recu, jour, extra) in enumerate(specs):
        capture = cs.construire(
            cat.obtenir("m5.prevision_tresorerie"),
            {"aujourd_hui": jour},
            extra.get("pages", [reponse]),
            recu_a=recu,
            reference=jour,
            index=index,
            hash_precedent=precedent,
        )
        chaine.append(capture)
        precedent = capture["hash_maillon"]
    return chaine


def _domaines(res):
    return {d["domaine"]: d for d in res["domaines"]}


def test_domaines_sans_prevision_de_proprietaire_ne_recoivent_aucun_chiffre():
    res = pv.consolider([], connaissance=CONNAISSANCE)
    d = _domaines(res)
    assert d["tresorerie"]["statut"] == "ABSENTE"
    for domaine, proprietaire in (
        ("leads", "m02-revenue-crm"),
        ("capacite", "m04-field-ops"),
        ("materiaux", "m06-material-control"),
    ):
        assert d[domaine]["statut"] == "AUCUNE_PREVISION_PRODUITE" and d[domaine]["proprietaire"] == proprietaire
        assert d[domaine]["versions"] == [] and "n'en estime aucune" in d[domaine]["raison"]
        assert not {"courante", "incertitude", "valeurs"} & set(d[domaine]), "aucun chiffre pour ce domaine"
    assert "ne calcule aucun montant" in res["limites"][0]


def test_prevision_complete_citee_avec_age_reserves_et_incertitude_non_chiffree():
    chaine = _chaine((_prevision(reserves=["FACTURES_NON_ENVOYEES"]), "2026-10-20T12:00:00Z", "2026-10-20", {}))
    t = _domaines(pv.consolider(chaine, connaissance=CONNAISSANCE, perime_apres_jours=14))["tresorerie"]
    assert t["statut"] == "DISPONIBLE" and t["courante"] == 0 and t["versions_total"] == 1
    version = t["versions"][0]
    assert version["age_jours"] == 8 and version["semaines_lues"] == 6 and version["semaines_manquantes"] == 0
    assert version["valeurs"]["horizon_semaines"] == "6" and version["solde_initial"] == "20000.00"
    assert version["faits"]["horizon_semaines"] == "m5.prevision_tresorerie#0:p0.resultat.resultat.horizon_semaines"
    assert t["incertitude"]["chiffree"] is False and t["incertitude"]["decrite_par"]["reserves"] == [
        "FACTURES_NON_ENVOYEES"
    ]
    assert pv.consolider(chaine, connaissance=CONNAISSANCE, perime_apres_jours=3)["domaines"][0]["statut"] == "PERIMEE"


def test_versions_successives_changements_nommes_sans_difference_d_argent():
    chaine = _chaine(
        (_prevision(), "2026-10-20T12:00:00Z", "2026-10-20", {}),
        (_prevision("2026-10-27", "q" * 64, "18000.00", "ALERTE", ["X"]), "2026-10-27T12:00:00Z", "2026-10-27", {}),
    )
    t = _domaines(pv.consolider(chaine, connaissance=CONNAISSANCE))["tresorerie"]
    assert t["courante"] == 1 and t["versions_total"] == 2
    assert t["versions"][1]["change_depuis_precedente"] == {
        "prevision_id": True, "solde_initial": True, "alerte": True, "reserves": True}  # fmt: skip
    assert "difference" not in str(t) and "ecart_montant" not in str(t)
    # Connaissance antérieure à la seconde réception : la seconde version n'existe pas encore.
    avant = _domaines(pv.consolider(chaine, connaissance="2026-10-22T00:00:00Z"))["tresorerie"]
    assert avant["courante"] == 0 and avant["versions_total"] == 1


def test_page_manquante_rend_la_prevision_partielle_et_non_utilisable():
    suite = _prevision(horizon=20, semaines=16)
    suite["resultat"]["resultat"]["prochain_depart"] = 16
    chaine = _chaine((suite, "2026-10-20T12:00:00Z", "2026-10-20", {}))
    t = _domaines(pv.consolider(chaine, connaissance=CONNAISSANCE))["tresorerie"]
    assert t["versions"][0]["statut"] == "PARTIELLE" and t["statut"] == "AUCUNE_VERSION_UTILISABLE"
    assert t["versions"][0]["semaines_manquantes"] == 4 and "courante" not in t


def test_capture_refusee_ou_contradictoire_ne_donne_aucune_prevision():
    refus = {"ok": False, "erreur": "arguments_invalides", "details": "x"}
    t = _domaines(pv.consolider(_chaine((refus, "2026-10-20T12:00:00Z", "2026-10-20", {})), connaissance=CONNAISSANCE))[
        "tresorerie"
    ]
    assert (
        t["statut"] == "AUCUNE_VERSION_UTILISABLE"
        and t["versions"][0]["statut"] == "REFUSEE"
        and "valeurs" not in t["versions"][0]
    )
    # Même prévision (même révision, mêmes arguments) mais contenu différent : contradiction, aucune n'est choisie.
    a, b = _prevision(solde="20000.00"), _prevision(solde="19000.00")
    contra = _chaine((a, "2026-10-20T12:00:00Z", "2026-10-20", {}), (b, "2026-10-20T13:00:00Z", "2026-10-20", {}))
    tc = _domaines(pv.consolider(contra, connaissance=CONNAISSANCE))["tresorerie"]
    assert {v["statut"] for v in tc["versions"]} == {"CONTRADICTOIRE"} and tc["statut"] == "AUCUNE_VERSION_UTILISABLE"


@pytest.mark.parametrize(
    "kwargs", [{"perime_apres_jours": -1}, {"perime_apres_jours": "7"}, {"max_versions": 0}, {"max_versions": 21}]
)
def test_parametres_invalides_refuses(kwargs):
    with pytest.raises(ValueError, match="REJ-PREVISION"):
        pv.consolider([], connaissance=CONNAISSANCE, **kwargs)


def test_connaissance_sans_fuseau_refusee():
    with pytest.raises(ValueError, match="REJ-CAPTURE-TEMPS"):
        pv.consolider([], connaissance="2026-10-28T13:00:00")
