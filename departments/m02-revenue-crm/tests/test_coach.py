"""M2.9 — le module PUR du coach de vente : faits, contrôle de texte, journal, bilan. Données fictives."""

from __future__ import annotations

import pytest
from m2_revenue_crm import coach

FICTIF = True
DOSSIER = {
    "statut": "qualifie",
    "suggestion": {
        "regle": "transmettre_m3",
        "suggestion": "Transmettre le dossier à M3 pour estimation.",
        "motif": "Readiness M3 satisfaite (M2.5).",
    },
    "score": {
        "score": "70.03",
        "couverture_poids": "0.85",
        "non_evalue": ["rentabilite"],
        "facteurs_dominants": [
            {"facteur": "conversion", "contribution_points": "20.00"},
            {"facteur": "qualite", "contribution_points": "19.76"},
        ],
    },
    "relances": [
        {
            "regle": "relance_devis_sans_reponse",
            "mode": "appel_seulement",
            "canaux_permis": ["appel"],
            "prochaine_date_permise": None,
        }
    ],
    "canaux_permis": ["appel"],
    "propriete": {"champs": {"type_batiment": {"valeur": "duplex"}, "etages": {"valeur": 2}}},
    "devis": [{"statut": "envoye", "instant": "2026-10-01T09:00:00-04:00"}],
    "interactions": [{"horodatage": "2026-10-10T09:00:00-04:00", "resume": "Le client veut comparer."}],
}


@pytest.fixture(scope="module")
def faits():
    return coach.faits_du_dossier(DOSSIER)


def _id(faits, genre):
    return next(f["id"] for f in faits if f["genre"] == genre)


def test_les_faits_ont_un_identifiant_stable_une_phrase_fixe_et_une_fiabilite(faits):
    assert [f["genre"] for f in faits] == [
        "statut",
        "prochaine_action",
        "score",
        "relance",
        "canaux",
        "propriete",
        "devis",
        "interaction",
    ]
    assert faits == coach.faits_du_dossier(DOSSIER)
    assert len({f["id"] for f in faits}) == len(faits)
    assert all(f["id"].startswith(f["genre"] + "-") and len(f["id"]) == len(f["genre"]) + 9 for f in faits)
    assert next(f for f in faits if f["genre"] == "interaction")["fiabilite"] == "donnee_non_fiable"
    assert {f["fiabilite"] for f in faits if f["genre"] != "interaction"} == {"registre_crm"}
    propriete = next(f for f in faits if f["genre"] == "propriete")["texte"]
    assert propriete == "Profil de propriété confirmé : type_batiment = duplex, etages = 2."


def test_un_fait_change_d_identifiant_quand_sa_phrase_change(faits):
    autre = coach.faits_du_dossier({**DOSSIER, "statut": "nouveau"})
    assert _id(autre, "statut") != _id(faits, "statut")
    assert coach.empreinte_contexte(autre) != coach.empreinte_contexte(faits)
    assert coach.empreinte_contexte(faits) == coach.empreinte_contexte(list(reversed(faits))), "indépendante de l'ordre"


def test_les_interactions_recentes_sont_bornees_a_trois(faits):
    plusieurs = {
        **DOSSIER,
        "interactions": [{"horodatage": f"2026-10-0{i}T09:00:00-04:00", "resume": f"Note {i}"} for i in range(1, 7)],
    }
    assert len([f for f in coach.faits_du_dossier(plusieurs) if f["genre"] == "interaction"]) == 3


def test_relances_non_calculables_est_un_fait_pas_un_silence():
    faits = coach.faits_du_dossier({"statut": "nouveau", "relances_manque": "fréquence à configurer"})
    assert any(f["genre"] == "relances_indisponibles" and "fréquence à configurer" in f["texte"] for f in faits)


def _valider(genre, texte, cites, faits, **plus):
    return coach.valider_texte(genre, texte, cites, faits, **plus)


def test_un_texte_propre_qui_cite_un_fait_passe(faits):
    valide, verdict = _valider(
        "prochaine_action", "Rappeler le client pour reprendre ses préoccupations.", [_id(faits, "statut")], faits
    )
    assert verdict is None and valide["genre"] == "prochaine_action" and valide["faits_cites"] == [_id(faits, "statut")]


@pytest.mark.parametrize(
    ("genre", "texte", "code"),
    [
        ("reponse_client", "Le prix est de 5 000 $ pour l'ensemble.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Une remise de 10 % est possible.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Nous offrons un rabais ce mois-ci.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "C'est gratuit pour vous cette fois.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Nous nous engageons à commencer rapidement.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Les travaux seront terminés demain matin.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Nous passerons la semaine prochaine.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Garantie de dix ans sur tout.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Écrivez à nous@example.test s'il vous plaît.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Bonjour monsieur Gagnon, merci de votre message.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Voir https://exemple.test/devis pour la suite.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "J'ai envoyé le devis hier à votre adresse.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "Le devis est envoyé, vous le recevrez bientôt.", "REJ-COACH-TEXTE-REFUSE"),
        ("reponse_client", "C'est fait, le message est parti.", "REJ-COACH-TEXTE-REFUSE"),
        ("prochaine_action", "Appeler le 418 555 0100 avant midi.", "REJ-COACH-TEXTE-REFUSE"),
        ("prochaine_action", "Proposer un prix de 8 000 $ au client.", "REJ-COACH-TEXTE-REFUSE"),
        ("prochaine_action", "Rappeler dans 3 jours.", "REJ-COACH-TEXTE-REFUSE"),
        ("points_d_appel", "Offrir une garantie à vie sur la main-d'œuvre.", "REJ-COACH-TEXTE-REFUSE"),
    ],
)
def test_prix_remise_engagement_date_garantie_contact_nom_et_envoi_sont_refuses(faits, genre, texte, code):
    valide, verdict = _valider(genre, texte, [_id(faits, "statut")], faits, noms_clients=["Gagnon"])
    assert valide is None and verdict["code"] == code, texte


def test_une_consigne_interne_peut_dire_ne_rien_promettre_une_reponse_au_client_ne_parle_pas_de_remise(faits):
    interne, verdict = _valider(
        "points_d_appel",
        "Ne rien promettre : aucune remise sans approbation de la direction.",
        [_id(faits, "statut")],
        faits,
    )
    assert verdict is None and interne
    client, verdict = _valider(
        "reponse_client", "Aucune remise n'est prévue pour le moment.", [_id(faits, "statut")], faits
    )
    assert client is None and verdict["code"] == "REJ-COACH-TEXTE-REFUSE"


def test_les_nombres_doivent_figurer_dans_un_fait_cite(faits):
    score = _id(faits, "score")
    ok, verdict = _valider("prochaine_action", "Le rang d'ordre est 70.03 : commencer par ce dossier.", [score], faits)
    assert verdict is None and ok
    for cite in ([_id(faits, "statut")], [_id(faits, "canaux")]):
        refus, verdict = _valider(
            "prochaine_action", "Le rang d'ordre est 70.03 : commencer par ce dossier.", cite, faits
        )
        assert refus is None and verdict["code"] == "REJ-COACH-TEXTE-REFUSE" and "70.03" in verdict["detail"]
    # les marqueurs de liste ne sont pas des nombres
    liste, verdict = _valider(
        "points_d_appel",
        "1. Demander les besoins.\n2. Noter le résultat au dossier.\n10) Fermer.",
        [_id(faits, "statut")],
        faits,
    )
    assert verdict is None, verdict
    # une virgule décimale est comparée comme un point
    virgule, verdict = _valider("prochaine_action", "Le rang d'ordre est 70,03 : commencer ici.", [score], faits)
    assert verdict is None and virgule


def test_les_faits_cites_doivent_exister_sans_doublon_et_etre_au_moins_un(faits):
    assert (
        _valider("prochaine_action", "Rappeler le client demain.", ["x-12345678"], faits)[1]["code"]
        == "REJ-COACH-FAIT-INCONNU"
    )
    assert _valider("prochaine_action", "Rappeler le client.", [], faits)[1]["code"] == "REJ-COACH-SANS-FAIT"
    assert (
        _valider("prochaine_action", "Rappeler le client.", [_id(faits, "statut")] * 2, faits)[1]["code"]
        == "REJ-COACH-ARGUMENT-INVALIDE"
    )
    assert (
        _valider("prochaine_action", "Rappeler le client.", "statut", faits)[1]["code"] == "REJ-COACH-ARGUMENT-INVALIDE"
    )
    assert _valider("prochaine_action", "Rappeler le client.", [1], faits)[1]["code"] == "REJ-COACH-ARGUMENT-INVALIDE"
    assert (
        _valider(
            "prochaine_action",
            "Rappeler le client.",
            [
                _id(faits, g)
                for g in (
                    "statut",
                    "score",
                    "canaux",
                    "devis",
                    "propriete",
                    "relance",
                    "interaction",
                    "prochaine_action",
                )
            ]
            + ["a"] * 5,
            faits,
        )[1]["code"]
        == "REJ-COACH-ARGUMENT-INVALIDE"
    )


@pytest.mark.parametrize(
    ("genre", "texte"),
    [
        ("envoyer", "Rappeler le client."),
        (None, "Rappeler le client."),
        ("prochaine_action", "court"),
        ("prochaine_action", "x" * 1201),
        ("prochaine_action", None),
        ("prochaine_action", 12345),
        ("prochaine_action", "Rappeler\x00le client."),
    ],
)
def test_genre_et_forme_du_texte(faits, genre, texte):
    assert _valider(genre, texte, [_id(faits, "statut")], faits)[1]["code"] == "REJ-COACH-ARGUMENT-INVALIDE"


def test_un_identifiant_interne_du_lead_dans_le_texte_est_refuse(faits):
    refus, verdict = _valider(
        "reponse_client",
        "Concernant le dossier lead-4711, merci de votre message.",
        [_id(faits, "statut")],
        faits,
        identifiants=["lead-4711"],
    )
    assert refus is None and verdict["code"] == "REJ-COACH-TEXTE-REFUSE"


# ---------------------------------------------------------------------------------------- journal
def _suggestion(faits, rang=1, genre="prochaine_action"):
    return coach.construire_suggestion(
        lead_id="lead-1",
        client_id="c" * 64,
        genre=genre,
        texte="Rappeler le client.",
        faits=faits,
        faits_cites=[_id(faits, "statut")],
        sources_citees=[],
        empreinte=coach.empreinte_contexte(faits),
        auteur="agent",
        voie="agent",
        horodatage="2026-10-15T12:00:00-04:00",
        rang=rang,
    )


def test_la_suggestion_du_journal_est_n2_non_envoyee_et_son_identifiant_deterministe(faits):
    a, b = _suggestion(faits), _suggestion(faits)
    assert a == b and a["niveau"] == "N2" and a["envoye"] is False and a["evenement"] == "suggestion"
    assert a["suggestion_id"] != _suggestion(faits, rang=2)["suggestion_id"]
    assert a["faits_cites"] == [{"id": _id(faits, "statut"), "texte": "Le lead est au statut qualifie."}]


def test_une_decision_est_humaine_unique_et_n_envoie_rien(faits):
    journal = [_suggestion(faits)]
    etat = coach.etat_des_suggestions(journal)
    assert etat[0]["decision"] is None
    entree, verdict = coach.construire_decision(
        etat[0], "accepter", None, None, par="vendeur.un", role="seller", horodatage="2026-10-15T12:05:00-04:00"
    )
    assert verdict is None and entree["decision"] == "accepter" and entree["envoye"] is False
    decide = coach.etat_des_suggestions([*journal, entree])
    assert decide[0]["decision"]["decide_par"] == "vendeur.un"
    assert (
        coach.construire_decision(
            decide[0], "rejeter", None, None, par="x", role="seller", horodatage="2026-10-15T12:06:00-04:00"
        )[1]["code"]
        == "REJ-COACH-DEJA-DECIDEE"
    )
    for mot in ("envoyer", "Envoyer ", "SEND", "transmettre", "expedier", "publier", "poster"):
        assert (
            coach.construire_decision(
                etat[0], mot, None, None, par="x", role="seller", horodatage="2026-10-15T12:06:00-04:00"
            )[1]["code"]
            == "REJ-COACH-ENVOI-INTERDIT"
        ), mot
    for mauvais in ("peut-etre", "", None, 3):
        assert (
            coach.construire_decision(
                etat[0], mauvais, None, None, par="x", role="seller", horodatage="2026-10-15T12:06:00-04:00"
            )[1]["code"]
            == "REJ-COACH-DECISION-INVALIDE"
        )
    assert (
        coach.construire_decision(etat[0], "accepter", None, None, par="x", role="seller", horodatage="nope")[1]["code"]
        == "REJ-COACH-ARGUMENT-INVALIDE"
    )
    assert (
        coach.construire_decision(
            etat[0], "rejeter", None, "x" * 301, par="x", role="seller", horodatage="2026-10-15T12:06:00-04:00"
        )[1]["code"]
        == "REJ-COACH-ARGUMENT-INVALIDE"
    )


def test_modifier_applique_les_memes_controles_au_texte_final(faits):
    etat = coach.etat_des_suggestions([_suggestion(faits)])
    h = "2026-10-15T12:06:00-04:00"
    assert (
        coach.construire_decision(
            etat[0],
            "modifier",
            "Rappeler le client avec un rabais de 10 %.",
            None,
            par="x",
            role="seller",
            horodatage=h,
        )[1]["code"]
        == "REJ-COACH-TEXTE-REFUSE"
    )
    assert coach.construire_decision(etat[0], "modifier", None, None, par="x", role="seller", horodatage=h)[1][
        "code"
    ] == ("REJ-COACH-ARGUMENT-INVALIDE")
    ok, verdict = coach.construire_decision(
        etat[0], "modifier", "Rappeler le client en fin de journée.", None, par="x", role="seller", horodatage=h
    )
    assert verdict is None and ok["texte_final"] == "Rappeler le client en fin de journée."


def test_le_bilan_exige_l_effectif_avant_de_donner_un_taux(faits):
    journal = []
    for i in range(19):
        s = _suggestion(faits, rang=i + 1)
        d, _ = coach.construire_decision(
            coach.etat_des_suggestions([s])[0],
            "accepter" if i % 2 else "rejeter",
            None,
            None,
            par="x",
            role="seller",
            horodatage="2026-10-15T12:06:00-04:00",
        )
        journal += [s, d]
    bilan = coach.bilan(coach.etat_des_suggestions(journal))
    assert bilan["taux_d_acceptation"]["valeur"] is None and bilan["taux_d_acceptation"]["n"] == 19
    s = _suggestion(faits, rang=20)
    d, _ = coach.construire_decision(
        coach.etat_des_suggestions([s])[0],
        "modifier",
        "Rappeler le client en fin de journée.",
        None,
        par="x",
        role="seller",
        horodatage="2026-10-15T12:06:00-04:00",
    )
    bilan = coach.bilan(coach.etat_des_suggestions([*journal, s, d]))
    assert bilan["taux_d_acceptation"] == {"n": 20, "seuil": 20, "valeur": "0.50"}, "9 acceptées + 1 modifiée sur 20"
    assert bilan["decisions"] == {"accepter": 9, "modifier": 1, "rejeter": 10} and bilan["envoyees"] == 0
    assert coach.bilan([])["taux_d_acceptation"]["n"] == 0
