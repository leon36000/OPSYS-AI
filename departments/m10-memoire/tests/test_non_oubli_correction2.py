"""Correction M10-05, second passage : DF1–DF5 reproduits par des tests rouges (données fictives).

Toutes les données sont FICTIVES (`fictif: true`, identifiants `A-FICTIF-*`, `D-FICTIF-*`,
`WCT-FICTIF-*`, `DOC-*`). Aucun stockage réel, aucun réseau, aucun service extérieur.

Ce fichier pinçait d'abord les défauts constatés par `RAPPORT-RELECTURE-FINALE.md` ; il pinçait
ensuite le contrat corrigé. Les tests nommés `test_df1_...`, `test_df2_...`, etc. échouaient avant
la correction et passent après. Les tests de frontière (forme historique incomplète, événement
inconnu, documents historiques, `None`/`[]`, tilde refusé hors M2) passaient déjà et continuent de
passer : ils prouvent que le refus reste ciblé.
"""

from __future__ import annotations

import copy
from collections import UserDict
from types import MappingProxyType

import pytest
from m10_memoire import affaire, amont, batterie, registre, wct

HORODATAGE = "2026-11-02T09:00:00-05:00"
WCT_HORODATAGE = "2026-11-05T16:00:00-05:00"
OPPORTUNITE = "A-FICTIF-1~opp~WCT-ORIGINE-1"


def _mini(**overrides):
    corpus = {
        "schema": batterie.SCHEMA_BATTERIE,
        "fictif": True,
        "version": "correction-2-fictive",
        "auteur": "test fictif de correction",
        "entreprise": "Entreprise fictive de correction",
        "documents": [
            {"id": "DOC-A", "domaine": "affaires", "texte": "Texte fictif du document A."}
        ],
        "faits": [
            {
                "id": "F-A",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m1.lead_qualifie",
                "identifiant": "A-FICTIF-1",
                "sources": ["DOC-A"],
            }
        ],
        "questions": [
            {
                "id": "Q-A",
                "texte": "Quel lead fictif a été qualifié ?",
                "affaire_id": "A-FICTIF-1",
                "types_evenement": ["m1.lead_qualifie"],
                "attendus": ["F-A"],
            }
        ],
    }
    corpus.update(copy.deepcopy(overrides))
    return corpus


def _seed_lead(registre_cible, lead_id="A-FICTIF-1"):
    resultat, verdict = amont.memoriser(
        "m1.lead_qualifie",
        {
            "lead": {
                "lead_id": lead_id,
                "service": "gouttieres",
                "canal": "texte",
                "urgence_declaree": False,
            },
            "horodatage": HORODATAGE,
        },
        registre_cible,
    )
    assert verdict is None and resultat is not None
    return resultat["maillon"]


def _devis_accepte_maillon():
    evenements = registre.Registre()
    resultat, verdict = amont.memoriser(
        "m3.devis_accepte",
        {
            "lead_id": "A-FICTIF-1",
            "devis_id": "D-FICTIF-1",
            "chantier_id": "CH-FICTIF-1",
            "horodatage_acceptation": HORODATAGE,
            "prix_total": "500.00",
            "cout_total": "400.00",
            "taux_marge": "0.20",
        },
        evenements,
    )
    assert verdict is None and resultat is not None
    return resultat["maillon"]


# ---------------------------------------------------------------------------------------------------------------
# DF1 — événements reconnus : identifiant public absent, mal typé ou non hashable
# ---------------------------------------------------------------------------------------------------------------
def test_df1_evenement_reconnu_sans_cle_publique_devis_est_refuse():
    """Un vrai maillon `m3.devis_accepte` privé de sa clé publique `devis_id` doit être refusé,
    pas ignoré avec un `rappel: 0.0`."""
    maillon = dict(_devis_accepte_maillon())
    maillon.pop("devis_id")

    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), [maillon], [], ["DOC-A"])

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "maillons_evenements[0].identifiant"


def test_df1_evenement_reconnu_sans_cle_publique_wct_est_refuse():
    """Un vrai maillon WCT privé de `wct_id` doit être refusé, pas ignoré."""
    evenements = registre.Registre()
    resultat, verdict = wct.memoriser_wct(
        {
            "wct_id": "WCT-FICTIF-1",
            "intervention_id": "INT-WCT-FICTIF-1",
            "lead_id": "A-FICTIF-1",
            "technicien_id": "TECH-FICTIF-1",
            "horodatage_completion": WCT_HORODATAGE,
            "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
            "duree_reelle_minutes": 90,
            "ecart_signale": False,
            "revue_id": None,
            "hash_maillon": "a" * 64,
            "consommateurs_cibles": ["M10"],
            "devis_id": "DEV-WCT-FICTIF-1",
        },
        evenements,
    )
    assert verdict is None and resultat is not None
    maillon = dict(resultat)
    maillon.pop("wct_id")

    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), [maillon], [], ["DOC-A"])

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "maillons_evenements[0].identifiant"


@pytest.mark.parametrize(
    "valeur",
    [42, "TEXTE LIBRE FICTIF", ["D-FICTIF-1"]],
    ids=["entier", "texte_hors_forme", "liste_non_hashable"],
)
def test_df1_identifiant_public_mal_type_est_refuse_sans_typeerror(valeur):
    """Un `devis_id` entier, hors forme ou non hashable est refusé typé : ni baisse de précision
    silencieuse, ni `TypeError` brute."""
    maillon = dict(_devis_accepte_maillon())
    maillon["devis_id"] = valeur

    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), [maillon], [], ["DOC-A"])

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "maillons_evenements[0].identifiant"


def test_df1_identifiant_wct_non_hashable_est_refuse_sans_typeerror():
    """Un `wct_id` liste ne doit pas lever `TypeError: unhashable type`."""
    maillon = {
        "type_entree": "evenement_memorise",
        "type_evenement": "m4.travaux_termines",
        "wct_id": ["WCT-FICTIF-1"],
        "lead_id": "A-FICTIF-1",
        "duree_reelle_minutes": 90,
        "horodatage": HORODATAGE,
    }

    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), [maillon], [], ["DOC-A"])

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "maillons_evenements[0].identifiant"


def test_df1_relation_lead_id_malformee_sur_un_devis_est_refusee():
    """La relation ``lead_id`` d'un fait de l'amont (ici un devis) est aussi validée quand elle est
    présente : sinon le fait ne serait rattaché à aucune affaire, sans refus."""
    maillon = dict(_devis_accepte_maillon())
    maillon["lead_id"] = 42

    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), [maillon], [], ["DOC-A"])

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "maillons_evenements[0].lead_id"


def test_df1_relation_wct_presente_mais_malformee_est_refusee():
    """Une relation présente mais mal typée (`lead_id: 42`) est refusée : elle produirait un faux
    oubli (le maillon n'est rattaché à aucune affaire)."""
    maillon = {
        "type_entree": "evenement_memorise",
        "type_evenement": "m4.travaux_termines",
        "wct_id": "WCT-FICTIF-1",
        "lead_id": 42,
        "duree_reelle_minutes": 90,
        "horodatage": HORODATAGE,
    }

    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), [maillon], [], ["DOC-A"])

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "maillons_evenements[0].lead_id"


def test_df1_relation_variance_non_hashable_est_refusee_sans_typeerror():
    """Un `wct_id` liste sur une variance provoque aujourd'hui un `TypeError` dans
    `classification.evenements_de_laffaire` ; il doit être refusé typé."""
    maillon = {
        "type_entree": "evenement_memorise",
        "type_evenement": "m6.variance_chantier",
        "evenement_id": "VAR-FICTIF-1",
        "wct_id": ["WCT-FICTIF-1"],
        "statut_variance": "evaluee",
        "horodatage": HORODATAGE,
    }

    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), [maillon], [], ["DOC-A"])

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "maillons_evenements[0].wct_id"


def test_df1_forme_historique_incomplete_wct_reste_acceptee_sans_etre_attribuee():
    """La forme historique du test WCT (sans `lead_id`, mais avec `wct_id`) reste acceptée : refuser
    tout le registre pour un maillon ancien incomplet serait abusif. Elle n'est simplement rattachée
    à aucune affaire, et la batterie ne devine pas l'affaire."""
    historique = {
        "type_entree": "evenement_memorise",
        "wct_id": "WCT-001",
        "duree_reelle_minutes": 90,
    }
    corpus = _mini(
        faits=[
            {
                "id": "F-WCT-001",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m4.travaux_termines",
                "identifiant": "WCT-001",
                "sources": ["DOC-A"],
            }
        ],
        questions=[
            {
                "id": "Q-WCT-001",
                "texte": "Quels travaux fictifs ?",
                "affaire_id": "A-FICTIF-1",
                "types_evenement": ["m4.travaux_termines"],
                "attendus": ["F-WCT-001"],
            }
        ],
    )

    rapport = batterie.evaluer_batterie(corpus, [historique], [], ["DOC-A"])

    assert rapport["par_question"][0]["retournes"] == 0
    assert rapport["rappel"]["valeur"] == 0.0
    assert rapport["manquants"] == [{"question": "Q-WCT-001", "fait": "F-WCT-001"}]


def test_df1_evenements_inconnus_et_maillons_historiques_sont_acceptes_sans_validation_abusive():
    """Un événement futur non classifié, un événement du bus hors périmètre, un compagnon financier
    valide et des maillons d'autres registres ne sont pas validés comme des événements de la
    batterie : ils restent acceptés."""
    maillons = [
        {"type_entree": "evenement_memorise", "type_evenement": "m9.futur", "horodatage": HORODATAGE},
        {
            "type_entree": "evenement_memorise",
            "type_evenement": "m3.devis_envoye",
            "lead_id": "A-FICTIF-1",
            "devis_id": "D-ENVOYE-1",
            "horodatage": HORODATAGE,
        },
        {
            "type_entree": "evenement_memorise",
            "type_evenement": "m3.devis_accepte:montants",
            "lead_id": "A-FICTIF-1",
            "devis_id": "D-FICTIF-1",
            "horodatage": HORODATAGE,
        },
        {"type_entree": "provenance_documentaire", "id": "DOC-HIST", "horodatage": HORODATAGE},
        {"type_entree": "fait_consolide", "fait_id": "F-HIST", "horodatage": HORODATAGE},
        {"type_entree": "memoire_developpement", "id": "DEV-HIST", "horodatage": HORODATAGE},
    ]

    rapport = batterie.evaluer_batterie(_mini(), maillons, maillons, ["DOC-A"])

    assert rapport["nb_maillons_affaires"] == len(maillons)
    assert rapport["rappel"]["valeur"] == 0.0


# ---------------------------------------------------------------------------------------------------------------
# DF2 — questions non évaluables, listes globales et dénominateurs
# ---------------------------------------------------------------------------------------------------------------
def _corpus_ok_et_dev():
    return _mini(
        documents=[
            {"id": "DOC-A", "domaine": "affaires", "texte": "Document d'affaires fictif."},
            {"id": "DOC-DEV", "domaine": "developpement", "texte": "Note de développement fictive."},
        ],
        faits=[
            {
                "id": "F-A",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m1.lead_qualifie",
                "identifiant": "A-FICTIF-1",
                "sources": ["DOC-A"],
            },
            {
                "id": "F-DEV",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m3.devis_accepte",
                "identifiant": "D-FICTIF-DEV",
                "sources": ["DOC-DEV"],
            },
        ],
        questions=[
            {
                "id": "Q-OK",
                "texte": "Quel lead d'affaires fictif ?",
                "affaire_id": "A-FICTIF-1",
                "types_evenement": ["m1.lead_qualifie"],
                "attendus": ["F-A"],
            },
            {
                "id": "Q-DEV",
                "texte": "Question fictive liée au développement ?",
                "affaire_id": "A-FICTIF-1",
                "types_evenement": ["m3.devis_accepte"],
                "attendus": ["F-DEV"],
            },
        ],
    )


def test_df2_listes_globales_ne_contiennent_que_les_questions_evaluables():
    """Avec un inventaire vide, Q-OK est évaluable (source absente) et Q-DEV non évaluable : les
    listes globales ne doivent lister que Q-OK, tandis que Q-DEV garde ses informations et sa
    raison dans `par_question`."""
    evenements = registre.Registre()
    _seed_lead(evenements)
    corpus = _corpus_ok_et_dev()

    rapport = batterie.evaluer_batterie(corpus, evenements.lire(), [], [])

    assert rapport["non_evaluables"] == [
        {"question": "Q-DEV", "raison": batterie.RAISON_SOURCE_HORS_DOMAINE}
    ]
    assert rapport["rappel"]["valeur"] == 1.0
    assert rapport["manquants"] == []
    assert rapport["sources_absentes"] == [
        {"question": "Q-OK", "fait": "F-A", "source": "DOC-A"}
    ]
    assert rapport["couverture_sources"] == {
        "evaluable": True,
        "numerateur": 0,
        "denominateur": 1,
        "valeur": 0.0,
        "valeur_pct": 0.0,
    }

    q_dev = next(question for question in rapport["par_question"] if question["id"] == "Q-DEV")
    assert q_dev["raison"] == batterie.RAISON_SOURCE_HORS_DOMAINE
    assert q_dev["manquants"] == ["F-DEV"]
    assert q_dev["sources_absentes"] == [
        {"question": "Q-DEV", "fait": "F-DEV", "source": "DOC-DEV"}
    ]


def test_df2_question_non_evaluable_hors_domaine_ne_pollue_plus_les_listes_globales():
    """Le scénario exact du constat : Q-OK à 100 % et Q-DEV hors domaine. Les listes globales
    restent vides ; Q-DEV conserve son fait manquant et sa source absente par question."""
    evenements = registre.Registre()
    _seed_lead(evenements)
    corpus = _corpus_ok_et_dev()

    rapport = batterie.evaluer_batterie(corpus, evenements.lire(), [], ["DOC-A"])

    assert rapport["rappel"] == {
        "evaluable": True,
        "numerateur": 1,
        "denominateur": 1,
        "valeur": 1.0,
        "valeur_pct": 100.0,
    }
    assert rapport["couverture_sources"] == {
        "evaluable": True,
        "numerateur": 1,
        "denominateur": 1,
        "valeur": 1.0,
        "valeur_pct": 100.0,
    }
    assert rapport["manquants"] == []
    assert rapport["sources_absentes"] == []

    q_dev = next(question for question in rapport["par_question"] if question["id"] == "Q-DEV")
    assert q_dev["evaluable"] is False
    assert q_dev["raison"] == batterie.RAISON_SOURCE_HORS_DOMAINE
    assert q_dev["manquants"] == ["F-DEV"]


def test_df2_toutes_questions_non_evaluables_et_inventaire_absent_donnent_la_bonne_raison():
    """Quand aucune question n'est évaluable, la couverture globale des sources ne peut pas dire
    `AUCUNE_SOURCE_ATTENDUE` : elle dit `AUCUN_FAIT_EVALUABLE`, et les listes globales restent
    vides."""
    corpus = _mini(
        documents=[
            {"id": "DOC-DEV", "domaine": "developpement", "texte": "Note de développement fictive."}
        ],
        faits=[
            {
                "id": "F-DEV",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m3.devis_accepte",
                "identifiant": "D-FICTIF-DEV",
                "sources": ["DOC-DEV"],
            }
        ],
        questions=[
            {
                "id": "Q-DEV",
                "texte": "Question fictive liée au développement ?",
                "affaire_id": "A-FICTIF-1",
                "types_evenement": ["m3.devis_accepte"],
                "attendus": ["F-DEV"],
            }
        ],
    )

    rapport = batterie.evaluer_batterie(corpus, [], [], None)

    assert rapport["mode_sources"] == batterie.MODE_SOURCES_INVENTAIRE_ABSENT
    assert rapport["couverture_sources"] == {
        "evaluable": False,
        "raison": batterie.RAISON_AUCUN_FAIT_EVALUABLE,
    }
    assert rapport["manquants"] == []
    assert rapport["sources_absentes"] == []

    q_dev = rapport["par_question"][0]
    assert q_dev["raison"] == batterie.RAISON_SOURCE_HORS_DOMAINE
    assert q_dev["manquants"] == ["F-DEV"]


def test_frontiere_none_et_liste_vide_est_preservee():
    """`None` reste non évaluable ; `[]` reste un zéro connu."""
    evenements = registre.Registre()
    _seed_lead(evenements)
    corpus = _mini()

    sans_inventaire = batterie.evaluer_batterie(corpus, evenements.lire(), [], None)
    assert sans_inventaire["couverture_sources"] == {
        "evaluable": False,
        "raison": batterie.RAISON_AUCUN_INVENTAIRE_SOURCES,
    }
    assert sans_inventaire["sources_absentes"] == []

    inventaire_vide = batterie.evaluer_batterie(corpus, evenements.lire(), [], [])
    assert inventaire_vide["couverture_sources"]["evaluable"] is True
    assert inventaire_vide["couverture_sources"]["denominateur"] == 1
    assert inventaire_vide["sources_absentes"] == [
        {"question": "Q-A", "fait": "F-A", "source": "DOC-A"}
    ]


# ---------------------------------------------------------------------------------------------------------------
# DF3 — sous-objets Mapping non-dict et empreinte canonique
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("champ", ["documents", "faits", "questions"])
def test_df3_mapping_non_dict_est_normalise_en_dict_avant_deepcopy(champ):
    """Un `MappingProxyType` dans une des trois listes du corpus est normalisé en `dict` : ni
    `TypeError` de `deepcopy`, ni élément non canonique."""
    corpus = _mini()
    corpus[champ][0] = MappingProxyType(dict(corpus[champ][0]))

    valide = batterie.valider_batterie(corpus)

    assert type(valide[champ][0]) is dict
    assert isinstance(batterie.empreinte_batterie(corpus), str)


def test_df3_empreinte_refuse_une_valeur_non_finie_au_lieu_d_inventer_nan():
    """Le JSON canonique n'admet pas NaN/Infinity : une valeur non finie est un refus typé, jamais
    une représentation inventée."""
    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie._empreinte({"valeur": float("nan")})

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "corpus"


def test_df3_userdict_meme_contenu_meme_empreinte_quel_que_soit_l_ordre():
    """Deux `UserDict` égaux mais insérés dans un ordre différent doivent produire la même
    empreinte canonique ; aucune représentation `str` n'est inventée par `default=str`."""
    document_1 = UserDict([("id", "DOC-A"), ("domaine", "affaires"), ("texte", "Texte fictif A.")])
    document_2 = UserDict([("texte", "Texte fictif A."), ("domaine", "affaires"), ("id", "DOC-A")])
    assert document_1 == document_2

    empreinte_1 = batterie.empreinte_batterie(_mini(documents=[document_1]))
    empreinte_2 = batterie.empreinte_batterie(_mini(documents=[document_2]))

    assert empreinte_1 == empreinte_2
    valide = batterie.valider_batterie(_mini(documents=[document_1]))
    assert type(valide["documents"][0]) is dict


# ---------------------------------------------------------------------------------------------------------------
# DF4 — bytearray et memoryview comme conteneurs
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "conteneur", [bytearray(b""), memoryview(b"")], ids=["bytearray", "memoryview"]
)
def test_df4_conteneur_binaire_vide_est_refuse_pour_les_maillons(conteneur):
    """Comme `b""`, `bytearray(b"")` et `memoryview(b"")` ne sont pas des séquences de maillons."""
    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), conteneur, [], ["DOC-A"])

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "maillons_evenements"


@pytest.mark.parametrize(
    "conteneur", [bytearray(b""), memoryview(b"")], ids=["bytearray", "memoryview"]
)
def test_df4_conteneur_binaire_vide_est_refuse_pour_l_inventaire(conteneur):
    """Comme `b""`, `bytearray(b"")` et `memoryview(b"")` ne sont pas un inventaire de sources."""
    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), [], [], conteneur)

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "documents_disponibles"


def test_df4_bytes_reste_refuse_pour_les_deux_entrees():
    """La frontière historique `bytes` reste refusée, sans changer de code ni de chemin."""
    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), b"", [], ["DOC-A"])
    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "maillons_evenements"

    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.evaluer_batterie(_mini(), [], [], b"")
    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "documents_disponibles"


# ---------------------------------------------------------------------------------------------------------------
# DF5 — clés d'opportunité M2 (`<lead>~opp~<wct_id>`) et affaire.valide
# ---------------------------------------------------------------------------------------------------------------
def _corpus_client_opportunite(identifiant: str):
    # Pour ``m2.client_associe``, la clé publique EST l'affaire (lead ou opportunité) : le corpus
    # déclare donc la même valeur dans les deux champs.
    return _mini(
        faits=[
            {
                "id": "F-CLIENT-OPP",
                "affaire_id": identifiant,
                "type_evenement": "m2.client_associe",
                "identifiant": identifiant,
                "sources": ["DOC-A"],
            }
        ],
        questions=[
            {
                "id": "Q-OPP",
                "texte": "Quel client fictif ouvre l'opportunité ?",
                "affaire_id": identifiant,
                "types_evenement": ["m2.client_associe"],
                "attendus": ["F-CLIENT-OPP"],
            }
        ],
    )


def test_df5_client_associe_d_une_opportunite_reelle_est_declarable_et_retrouve():
    """Un vrai maillon `m2.client_associe` écrit par M10 porte `<lead>~opp~<wct>` comme clé
    publique ; le corpus doit pouvoir le déclarer et le retrouver."""
    evenements = registre.Registre()
    resultat, verdict = amont.memoriser(
        "m2.client_associe",
        {
            "lead_id": OPPORTUNITE,
            "client_id": "CLI-FICTIF-1",
            "horodatage_association": HORODATAGE,
        },
        evenements,
    )
    assert verdict is None and resultat is not None
    maillon = resultat["maillon"]
    assert maillon["lead_id"] == OPPORTUNITE

    rapport = batterie.evaluer_batterie(
        _corpus_client_opportunite(OPPORTUNITE), [maillon], [], ["DOC-A"]
    )

    assert rapport["rappel"]["valeur"] == 1.0
    assert rapport["par_question"][0]["trouves"] == ["F-CLIENT-OPP"]
    assert rapport["par_question"][0]["retournes_non_references"] == []


def test_df5_opportunite_bornee_jusqu_a_197_caracteres_est_acceptee():
    """La clé d'opportunité va jusqu'à 64 + 5 + 128 = 197 caractères : le plafond de 128 de
    `_IDENTIFIANT` ne doit pas s'appliquer à `m2.client_associe`."""
    lead = "L" * 64
    wct_id = "W" * 128
    opportunite = f"{lead}~opp~{wct_id}"
    assert affaire.valide(opportunite)
    assert len(opportunite) == 197

    evenements = registre.Registre()
    resultat, verdict = amont.memoriser(
        "m2.client_associe",
        {
            "lead_id": opportunite,
            "client_id": "CLI-FICTIF-1",
            "horodatage_association": HORODATAGE,
        },
        evenements,
    )
    assert verdict is None and resultat is not None

    rapport = batterie.evaluer_batterie(
        _corpus_client_opportunite(opportunite), [resultat["maillon"]], [], ["DOC-A"]
    )

    assert rapport["rappel"]["valeur"] == 1.0


@pytest.mark.parametrize(
    "type_evenement",
    ["m3.devis_accepte", "m1.lead_qualifie"],
    ids=["devis", "lead_m1"],
)
def test_df5_le_tilde_reste_refuse_pour_les_autres_types(type_evenement):
    """Le tilde n'est élargi qu'à `m2.client_associe` : un devis ou un lead M1 qui le porterait
    reste refusé."""
    corpus = _mini(
        faits=[
            {
                "id": "F-TILDE",
                "affaire_id": OPPORTUNITE,
                "type_evenement": type_evenement,
                "identifiant": OPPORTUNITE,
                "sources": ["DOC-A"],
            }
        ],
        questions=[
            {
                "id": "Q-TILDE",
                "texte": "Question fictive avec tilde ?",
                "affaire_id": OPPORTUNITE,
                "types_evenement": [type_evenement],
                "attendus": ["F-TILDE"],
            }
        ],
    )

    with pytest.raises(batterie.BatterieInvalide) as exc:
        batterie.valider_batterie(corpus)

    assert exc.value.code == "REJ-BATTERIE-FORME"
    assert exc.value.chemin == "faits[0].identifiant"


def test_df5_client_associe_sur_un_lead_simple_reste_accepte():
    """La forme historique d'un client associé sur un lead simple reste valide."""
    corpus = _corpus_client_opportunite("A-FICTIF-1")

    valide = batterie.valider_batterie(corpus)
    assert valide["faits"][0]["identifiant"] == "A-FICTIF-1"
