"""Mémoire marketing de M10 : liste blanche, idempotence, contradiction, regroupement en semaines distinctes
(M7-MEMOIRE)."""

from __future__ import annotations

import copy

import pytest
from m10_memoire import apprentissage_marketing as am
from m10_memoire.registre import Registre

FICTIF = True


def observation(n=1, semaine="2026-10-26", genre="contenu_gagnant", canal="facebook", cle=None, **resultat):
    comptes = {
        "leads": 3,
        "devis_envoyes": 2,
        "devis_acceptes": 1,
        "occurrences": None,
        "avis_positifs": None,
        "avis_negatifs": None,
    }
    comptes.update(resultat)
    return {
        "observation_id": "m7-appr-" + f"{n:040x}",
        "semaine": semaine,
        "genre_observation": genre,
        "canal": canal,
        "cle_mesure": cle if cle is not None else f"facebook-{n:04x}",
        "resultat": comptes,
        "rapport_empreinte": f"{n:064x}",
    }


def test_une_observation_valide_est_memorisee_une_fois_en_interne_sans_donnee_de_client():
    reg = Registre()
    r1, v1 = am.memoriser(observation(), reg)
    assert v1 is None and r1["deja_memorise"] is False
    m = r1["maillon"]
    assert (
        m["type_entree"] == "fait_marketing"
        and m["confidentialite"] == "INTERNAL"
        and m["producteur"] == "m07-marketing"
    )
    assert m["horodatage"] == "2026-10-26T00:00:00+00:00"
    r2, v2 = am.memoriser(observation(), reg)
    assert v2 is None and r2["deja_memorise"] is True and len(reg.lire()) == 1


def test_la_meme_observation_avec_un_autre_contenu_est_une_contradiction_le_premier_reste():
    reg = Registre()
    am.memoriser(observation(), reg)
    autre = observation(leads=9)
    resultat, verdict = am.memoriser(autre, reg)
    assert resultat is None and verdict["code"] == am.REJ_FAIT_MARKETING_CONTRADICTOIRE
    assert reg.lire()[0]["resultat"]["leads"] == 3 and len(reg.lire()) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda o: o.update(texte_du_contenu="Chantier chez M. Gagnon"),  # champ de plus
        lambda o: o.pop("canal"),
        lambda o: o.update(canal="tiktok"),
        lambda o: o.update(genre_observation="autre"),
        lambda o: o.update(observation_id="m7-appr-XYZ"),
        lambda o: o.update(semaine="2026-13-45x"),
        lambda o: o.update(cle_mesure="Jean Tremblay"),
        lambda o: o.update(rapport_empreinte="abc"),
        lambda o: o["resultat"].update(leads=-1),
        lambda o: o["resultat"].update(leads=True),
        lambda o: o["resultat"].update(leads=1_000_001),
        lambda o: o["resultat"].update(nom_client="Jean"),
        lambda o: o.update(resultat="beaucoup"),
    ],
)
def test_une_charge_hors_forme_est_refusee_nommant_le_champ_sans_rien_ecrire(mutation):
    reg = Registre()
    o = copy.deepcopy(observation())
    mutation(o)
    resultat, verdict = am.memoriser(o, reg)
    assert resultat is None and verdict["code"] == am.REJ_FAIT_MARKETING_CHAMP_INVALIDE and reg.lire() == []
    assert "Tremblay" not in str(verdict) and "Gagnon" not in str(verdict)


def test_cle_mesure_peut_etre_nulle():
    reg = Registre()
    o = observation()
    o["cle_mesure"] = None
    assert am.memoriser(o, reg)[1] is None


def maillons_pour(observations):
    reg = Registre()
    for o in observations:
        resultat, verdict = am.memoriser(o, reg)
        assert verdict is None
    return reg.lire()


def test_un_groupe_exige_trois_semaines_distinctes():
    semaines = ["2026-10-05", "2026-10-12", "2026-10-19"]
    deux = maillons_pour([observation(i, semaine=s) for i, s in enumerate(semaines[:2])])
    assert am.groupes_pour_lecons(deux) == []
    trois = maillons_pour([observation(i, semaine=s) for i, s in enumerate(semaines)])
    (g,) = am.groupes_pour_lecons(trois)
    assert g["genre_observation"] == "contenu_gagnant" and g["canal"] == "facebook"
    assert g["semaines_distinctes"] == 3 and g["observations"] == 3 and g["leads"] == 9
    assert len(g["cles_mesure"]) == 3 and len(g["lignes"]) == 3


def test_trois_observations_de_la_meme_semaine_ne_font_pas_trois_semaines():
    memes = maillons_pour([observation(i, semaine="2026-10-05") for i in range(4)])
    assert am.groupes_pour_lecons(memes) == []


def test_les_canaux_et_les_categories_d_objection_font_des_groupes_distincts():
    obs = []
    for i, s in enumerate(["2026-10-05", "2026-10-12", "2026-10-19"]):
        obs.append(
            observation(
                10 + i,
                semaine=s,
                genre="objection_frequente",
                canal="avis_clients",
                cle="urgence",
                leads=None,
                devis_envoyes=None,
                devis_acceptes=None,
                occurrences=2,
            )
        )
        obs.append(
            observation(
                20 + i,
                semaine=s,
                genre="objection_frequente",
                canal="avis_clients",
                cle="litige",
                leads=None,
                devis_envoyes=None,
                devis_acceptes=None,
                occurrences=2,
            )
        )
        obs.append(observation(30 + i, semaine=s, canal="instagram"))
    groupes = am.groupes_pour_lecons(maillons_pour(obs))
    assert sorted((g["genre_observation"], g["canal"], g["categorie"]) for g in groupes) == [
        ("contenu_gagnant", "instagram", None),
        ("objection_frequente", "avis_clients", "litige"),
        ("objection_frequente", "avis_clients", "urgence"),
    ]
    assert [g["occurrences"] for g in groupes if g["categorie"]] == [6, 6]


def test_les_avis_ne_comptent_que_les_semaines_ou_le_defavorable_domine():
    obs = []
    for i, (s, pos, neg) in enumerate(
        [("2026-10-05", 1, 3), ("2026-10-12", 2, 2), ("2026-10-19", 0, 1), ("2026-10-26", 1, 2)]
    ):
        obs.append(
            observation(
                i,
                semaine=s,
                genre="avis_constate",
                canal="avis_clients",
                cle="semaine",
                leads=None,
                devis_envoyes=None,
                devis_acceptes=None,
                occurrences=pos + neg,
                avis_positifs=pos,
                avis_negatifs=neg,
            )
        )
    (g,) = am.groupes_pour_lecons(maillons_pour(obs))
    assert (
        g["genre_observation"] == "avis_constate" and g["semaines_distinctes"] == 3
    )  # la semaine 2-2 n'en est pas une


def test_les_autres_types_de_maillons_sont_ignores():
    assert am.groupes_pour_lecons([{"type_entree": "evenement_memorise"}]) == []
