"""Leçons marketing GOUVERNÉES (M7-MEMOIRE) : proposées par le code d'après les observations de M7, évaluées hors ligne,
promues par une personne, lisibles par M7 ; jamais un texte de client, jamais appliquées seules.

Registres en mémoire, manifestes et corpus de garde RÉELS. Données fictives.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m10_memoire import apprentissage_marketing as am
from m10_memoire.registre import Registre

from opsys.departements import charger_departements
from opsys.mnemo import codes, garde_gabarit, lecons, soi
from opsys.mnemo.codes import ErreurMnemo

FICTIF = True
T1, T2, T3 = "2026-11-02T09:00:00+00:00", "2026-11-03T09:00:00+00:00", "2026-11-04T09:00:00+00:00"
DIRECTION = soi.Acteur("direction.fictive", "admin", "approbation")
RACINE = Path(__file__).resolve().parents[1] / "departments"
SEMAINES = ["2026-10-12", "2026-10-19", "2026-10-26"]


def obs(n, semaine, genre="contenu_gagnant", canal="facebook", cle=None, **res):
    comptes = {
        "leads": 3,
        "devis_envoyes": 1,
        "devis_acceptes": 0,
        "occurrences": None,
        "avis_positifs": None,
        "avis_negatifs": None,
    }
    comptes.update(res)
    return {
        "observation_id": "m7-appr-" + f"{n:040x}",
        "semaine": semaine,
        "genre_observation": genre,
        "canal": canal,
        "cle_mesure": cle or f"{canal}-{n:04x}",
        "resultat": comptes,
        "rapport_empreinte": f"{n:064x}",
    }


def faits(observations):
    registre = Registre()
    for o in observations:
        assert am.memoriser(o, registre)[1] is None
    return registre


def extraire(registre_lecons, faits_marketing, horodatage=T1):
    return lecons.extraire(
        registre_lecons,
        ecarts_mat=[],
        ecarts_mar=[],
        refus=[],
        rejets=[],
        marketing=am.groupes_pour_lecons(faits_marketing.lire()),
        par="agent:m10-memoire",
        horodatage=horodatage,
    )


def gagnants(n0=0, canal="facebook"):
    return [obs(n0 + i, s, canal=canal) for i, s in enumerate(SEMAINES)]


def test_trois_semaines_de_contenus_gagnants_proposent_une_lecon_gouvernee_pour_m7():
    lc = Registre()
    bilan = extraire(lc, faits(gagnants()))
    (ident,) = bilan["proposees"]
    lecon = lecons.etat(lc).lecons[ident]
    assert lecon["genre"] == "apprentissage_marketing" and lecon["cible"] == "m07-marketing"
    assert lecon["cle"] == "contenu_gagnant:facebook"
    assert lecon["texte_agent"] == lecons.TEXTES_MARKETING["contenu_gagnant"]
    assert lecon["contenu"]["semaines_distinctes"] == 3 and lecon["contenu"]["leads"] == 9
    assert lecons.etat(lc).promotion.etats[ident] == "proposee"  # proposée, ni évaluée ni décidée


def test_une_relance_ne_double_pas_la_lecon_et_de_nouvelles_observations_non_plus():
    lc = Registre()
    f = faits(gagnants())
    extraire(lc, f)
    again = extraire(lc, f, horodatage=T2)
    assert again["proposees"] == [] and again["deja_connues"] + again["en_cours"] == 1
    assert len([m for m in lc.lire() if m["type_entree"] == "lecon_proposee"]) == 1


def test_moins_de_trois_semaines_ou_une_seule_semaine_repetee_ne_proposent_rien():
    lc = Registre()
    assert extraire(lc, faits(gagnants()[:2]))["proposees"] == []
    assert extraire(lc, faits([obs(i, "2026-10-12") for i in range(5)]))["proposees"] == []
    assert lc.lire() == []


@pytest.mark.parametrize(
    ("genre", "canal", "cle", "res", "attendu"),
    [
        ("contenu_faible", "instagram", None, {"leads": 0}, "contenu_faible:instagram"),
        (
            "objection_frequente",
            "avis_clients",
            "urgence",
            {"leads": None, "devis_envoyes": None, "devis_acceptes": None, "occurrences": 2},
            "objection_frequente:avis_clients:urgence",
        ),
        (
            "avis_constate",
            "avis_clients",
            "semaine",
            {
                "leads": None,
                "devis_envoyes": None,
                "devis_acceptes": None,
                "occurrences": 4,
                "avis_positifs": 1,
                "avis_negatifs": 3,
            },
            "avis_constate:avis_clients",
        ),
    ],
)
def test_chaque_genre_d_observation_a_sa_lecon_et_son_texte(genre, canal, cle, res, attendu):
    lc = Registre()
    f = faits([obs(i, s, genre=genre, canal=canal, cle=cle, **res) for i, s in enumerate(SEMAINES)])
    (ident,) = extraire(lc, f)["proposees"]
    lecon = lecons.etat(lc).lecons[ident]
    assert lecon["cle"] == attendu and lecon["texte_agent"] == lecons.TEXTES_MARKETING[genre]


def test_les_textes_destines_a_l_agent_ne_portent_aucun_chiffre_et_aucun_nom():
    assert set(lecons.TEXTES_MARKETING) == set(am.genres_observation())
    for texte in lecons.TEXTES_MARKETING.values():
        assert not any(c.isdigit() for c in texte)


def test_un_texte_de_lecon_avec_chiffre_est_refuse(monkeypatch):
    monkeypatch.setitem(lecons.TEXTES_MARKETING, "contenu_gagnant", "Publie 3 fois par semaine.")
    with pytest.raises(ErreurMnemo, match=codes.ENTREE_INVALIDE):
        extraire(Registre(), faits(gagnants()))


def test_la_lecon_ne_contient_rien_de_personnel():
    lc = Registre()
    extraire(lc, faits(gagnants()))
    texte = json.dumps(lc.lire(), ensure_ascii=False)
    for interdit in ("@", "wct", "lead_id", "Tremblay", "Gagnon", "adresse", "telephone"):
        assert interdit not in texte


def test_un_genre_inconnu_ou_une_cle_invalide_ne_propose_rien():
    lc = Registre()
    sortie = lecons.extraire(
        lc,
        ecarts_mat=[],
        ecarts_mar=[],
        refus=[],
        rejets=[],
        par="agent:m10-memoire",
        horodatage=T1,
        marketing=[
            {"genre_observation": "inconnu", "canal": "facebook", "semaines_distinctes": 9},
            {
                "genre_observation": "contenu_gagnant",
                "canal": "Facebook !",
                "semaines_distinctes": 9,
                "observations": 9,
                "leads": 1,
                "occurrences": 0,
            },
        ],
    )
    assert sortie["proposees"] == [] and sortie["sans_lecon"][0]["raison"] == "cle_invalide"


def test_parcours_gouverne_garde_reelle_du_gabarit_de_m7_decision_humaine_puis_lecture_par_m7():
    lc = Registre()
    (ident,) = extraire(lc, faits(gagnants()))["proposees"]
    deps = charger_departements(RACINE)
    empreinte = garde_gabarit.empreinte_garde(deps, "m07-marketing")
    mesure = lecons.evaluer_mesure(lc, ident, ecarts_mat=[], ecarts_mar=[], horodatage=T2)
    assert mesure["amelioration_mesurable"] is False  # genre sans mesure chiffrée hors ligne : dit, pas inventé
    garde = garde_gabarit.comparer_au_gabarit(deps, "m07-marketing", lecons.etat(lc).lecons[ident]["texte_agent"])
    assert garde["regressions"] == [] and garde["bloquants_nouveaux"] == [] and garde["effectif"] > 0
    lecons.enregistrer_garde(lc, ident, garde, empreinte_garde=empreinte, horodatage=T2)
    verdict = lecons.verdict_evaluation(lecons.etat(lc), ident, empreinte)
    assert verdict["promouvable"] and not verdict["amelioration_mesurable"]
    # sans humain : rien
    with pytest.raises(ErreurMnemo, match=codes.HUMAIN_REQUIS):
        lecons.decider(
            lc,
            ident,
            "canari",
            acteur=soi.Acteur("agent:m10", "agent", "appareil"),
            motif="Décision de test sans humain",
            horodatage=T3,
            pourcentage=50,
            empreinte_garde=empreinte,
        )
    # une lecon non decidee n'est pas lisible
    assert lecons.appliquer_a(lc, "m07-marketing", "cle-1")["lecons"] == []
    lecons.decider(
        lc,
        ident,
        "canari",
        acteur=DIRECTION,
        motif="Essai prudent sur la moitié des cas",
        horodatage=T3,
        pourcentage=50,
        empreinte_garde=empreinte,
    )
    lecons.decider(
        lc,
        ident,
        "complete",
        acteur=DIRECTION,
        motif="Les contenus gagnants se confirment",
        horodatage=T3,
        empreinte_garde=empreinte,
    )
    lues = lecons.appliquer_a(lc, "m07-marketing", "cle-1")["lecons"]
    assert [x["lecon_id"] for x in lues] == [ident] and lues[0]["genre"] == "apprentissage_marketing"
    assert lecons.appliquer_a(lc, "m05-financecore", "cle-1")["lecons"] == []  # ne vise que M7
    vue = lecons.vue(lc, genre="apprentissage_marketing")
    assert vue["par_etat"] == {"complete": 1} and "Aucune leçon ne s'applique seule" in vue["avertissement"]


def test_les_quatre_textes_passent_la_garde_reelle_du_gabarit_de_m7_et_un_texte_hostile_la_fait_echouer():
    deps = charger_departements(RACINE)
    for texte in lecons.TEXTES_MARKETING.values():
        garde = garde_gabarit.comparer_au_gabarit(deps, "m07-marketing", texte)
        assert garde["regressions"] == [] and garde["score_avec_lecon"] == "1.0000", texte
    hostile = garde_gabarit.comparer_au_gabarit(
        deps, "m07-marketing", "C'est fait, j'ai publié le message. Cela représente environ 4 850,00 $ de rabais."
    )
    assert hostile["regressions"]
