"""faits_candidats.py : dépôt POSTFLIGHT des faits candidats (PLAN T3.3-suite).

Le core transmet ce que les OUTILS ont fait pendant un tour d'agent, jamais ce que le modèle a
écrit. Chaque test vérifie un comportement observable : un maillon `fait_candidat` par fait, une
provenance complète, l'idempotence par clé, et un lot refusé EN ENTIER (rien d'écrit) dès qu'un
seul élément est invalide. Registres en mémoire, `horodatage` toujours fourni.
"""

import pytest
from m10_memoire import consolidation, faits_candidats, paquets, registre, wct

HORODATAGE = "2026-09-28T10:15:00+00:00"
AUTRE_HORODATAGE = "2026-09-28T10:16:00+00:00"


def _fait(cle="tc-0001", outil="m3_estimer_projet", resultat="ok", code=None):
    return {"cle": cle, "outil": outil, "resultat": resultat, "code": code}


def _deposer(faits, *, affaire_id="LEAD-001", departement="m03-estimation", horodatage=HORODATAGE,
             registre_affaires=None):
    journal = registre_affaires if registre_affaires is not None else registre.Registre()
    resultat, verdict = faits_candidats.deposer_faits_candidats(
        affaire_id, departement, faits, horodatage, journal
    )
    return journal, resultat, verdict


def _maillons_candidats(journal):
    return [m for m in journal.lire() if m["type_entree"] == faits_candidats.TYPE_ENTREE_FAIT_CANDIDAT]


def test_le_depot_ecrit_un_maillon_par_fait_avec_sa_provenance():
    journal, resultat, verdict = _deposer(
        [_fait("tc-0001"), _fait("tc-0002", outil="m3_qualifier_photos", resultat="refus", code="refus_metier")]
    )

    assert verdict is None
    assert resultat["ecrits"] == 2
    assert resultat["deja_deposes"] == 0
    maillons = _maillons_candidats(journal)
    assert [m["ligne_id"] for m in maillons] == resultat["lignes"]
    premier, second = maillons
    assert premier["affaire_id"] == "LEAD-001"
    assert premier["departement_source"] == "m03-estimation"
    assert premier["cle_depot"] == "tc-0001"
    assert premier["outil"] == "m3_estimer_projet"
    assert premier["resultat"] == "ok"
    assert premier["code"] is None
    assert premier["statut"] == faits_candidats.STATUT_FAIT_CANDIDAT
    assert premier["horodatage"] == HORODATAGE
    assert second["resultat"] == "refus"
    assert second["code"] == "refus_metier"
    assert journal.valider_chaine() == (True, "")


def test_rejouer_le_meme_depot_ne_cree_rien_de_plus():
    journal, premier, _ = _deposer([_fait("tc-0001"), _fait("tc-0002")])

    _, second, verdict = _deposer(
        [_fait("tc-0001"), _fait("tc-0002")], horodatage=AUTRE_HORODATAGE, registre_affaires=journal
    )

    assert verdict is None
    assert second["ecrits"] == 0
    assert second["deja_deposes"] == 2
    assert second["lignes"] == []
    assert len(_maillons_candidats(journal)) == 2
    assert premier["ecrits"] == 2


def test_un_lot_partiellement_connu_n_ecrit_que_les_faits_nouveaux():
    journal, _, _ = _deposer([_fait("tc-0001")])

    _, resultat, verdict = _deposer([_fait("tc-0001"), _fait("tc-0002")], registre_affaires=journal)

    assert verdict is None
    assert resultat["ecrits"] == 1
    assert resultat["deja_deposes"] == 1
    assert [m["cle_depot"] for m in _maillons_candidats(journal)] == ["tc-0001", "tc-0002"]


@pytest.mark.parametrize(
    ("titre", "arguments", "verdict_attendu"),
    [
        ("affaire vide", {"affaire_id": ""}, faits_candidats.REJ_CANDIDAT_AFFAIRE_INVALIDE),
        ("affaire avec espace", {"affaire_id": "LEAD 001"}, faits_candidats.REJ_CANDIDAT_AFFAIRE_INVALIDE),
        ("affaire non textuelle", {"affaire_id": 42}, faits_candidats.REJ_CANDIDAT_AFFAIRE_INVALIDE),
        (
            "département inconnu",
            {"departement": "m11-inconnu"},
            faits_candidats.REJ_CANDIDAT_DEPARTEMENT_INVALIDE,
        ),
        ("département vide", {"departement": ""}, faits_candidats.REJ_CANDIDAT_DEPARTEMENT_INVALIDE),
        ("liste vide", {"faits": []}, faits_candidats.REJ_CANDIDAT_LISTE_INVALIDE),
        ("liste non liste", {"faits": "tc-0001"}, faits_candidats.REJ_CANDIDAT_LISTE_INVALIDE),
        (
            "liste trop longue",
            {"faits": [_fait(f"tc-{i:04d}") for i in range(faits_candidats.NB_FAITS_MAX_PAR_DEPOT + 1)]},
            faits_candidats.REJ_CANDIDAT_LISTE_INVALIDE,
        ),
        (
            "horodatage sans fuseau",
            {"horodatage": "2026-09-28T10:15:00"},
            faits_candidats.REJ_CANDIDAT_HORODATAGE_INVALIDE,
        ),
        ("horodatage absent", {"horodatage": ""}, faits_candidats.REJ_CANDIDAT_HORODATAGE_INVALIDE),
        ("fait non objet", {"faits": ["tc-0001"]}, faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE),
        (
            "champ inattendu",
            {"faits": [{**_fait(), "resume": "texte libre du modèle"}]},
            faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE,
        ),
        (
            "champ manquant",
            {"faits": [{"cle": "tc-0001", "outil": "m3_estimer_projet", "resultat": "ok"}]},
            faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE,
        ),
        ("clé vide", {"faits": [_fait(cle="")]}, faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE),
        ("clé avec espace", {"faits": [_fait(cle="tc 1")]}, faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE),
        ("outil mal formé", {"faits": [_fait(outil="estimer")]}, faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE),
        ("outil commun", {"faits": [_fait(outil="opsys_etat_budget")]}, faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE),
        (
            "résultat hors énuméré",
            {"faits": [_fait(resultat="indetermine")]},
            faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE,
        ),
        ("code avec espace", {"faits": [_fait(code="deux mots")]}, faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE),
        ("code trop long", {"faits": [_fait(code="x" * 81)]}, faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE),
        (
            "clé en double dans le lot",
            {"faits": [_fait("tc-0001"), _fait("tc-0001")]},
            faits_candidats.REJ_CANDIDAT_CLE_EN_DOUBLE,
        ),
    ],
)
def test_une_entree_invalide_refuse_tout_le_lot_et_n_ecrit_rien(titre, arguments, verdict_attendu):
    parametres = {
        "affaire_id": "LEAD-001",
        "departement": "m03-estimation",
        "faits": [_fait("tc-0001")],
        "horodatage": HORODATAGE,
    }
    parametres.update(arguments)

    journal, resultat, verdict = _deposer(
        parametres["faits"],
        affaire_id=parametres["affaire_id"],
        departement=parametres["departement"],
        horodatage=parametres["horodatage"],
    )

    assert resultat is None, titre
    assert verdict == verdict_attendu, titre
    assert journal.lire() == [], titre


def test_un_seul_fait_invalide_dans_un_lot_refuse_aussi_les_faits_valides():
    journal, resultat, verdict = _deposer([_fait("tc-0001"), _fait("tc-0002", resultat="peut-etre")])

    assert resultat is None
    assert verdict == faits_candidats.REJ_CANDIDAT_FAIT_INVALIDE
    assert journal.lire() == []


def test_une_cle_deja_deposee_pour_une_autre_affaire_est_un_conflit_nomme():
    journal, _, _ = _deposer([_fait("tc-0001")], affaire_id="LEAD-001")

    _, resultat, verdict = _deposer(
        [_fait("tc-0001"), _fait("tc-0002")], affaire_id="LEAD-002", registre_affaires=journal
    )

    assert resultat is None
    assert verdict == faits_candidats.REJ_CANDIDAT_CLE_DEJA_UTILISEE
    assert [m["cle_depot"] for m in _maillons_candidats(journal)] == ["tc-0001"]


def test_une_cle_rejouee_avec_un_contenu_different_est_un_conflit_nomme():
    journal, _, _ = _deposer([_fait("tc-0001", resultat="ok")])

    _, resultat, verdict = _deposer([_fait("tc-0001", resultat="refus")], registre_affaires=journal)

    assert resultat is None
    assert verdict == faits_candidats.REJ_CANDIDAT_CLE_DEJA_UTILISEE
    assert len(_maillons_candidats(journal)) == 1


def test_un_fait_candidat_n_entre_pas_dans_le_paquet_de_contexte():
    """Un candidat n'est pas une vérité : hors des quatre couches, tant qu'aucune phase ultérieure
    ne le valide. Le paquet reste celui de la consolidation, des événements et des règles."""
    registre_evenements = registre.Registre()
    journal, _, _ = _deposer([_fait("tc-0001")])

    paquet = paquets.assembler_paquet_contexte("LEAD-001", HORODATAGE, registre_evenements, journal)

    assert all(couche["vide"] is True for couche in paquet["couches"])
    assert paquet["caracteres_utilises"] == 0


def test_la_consolidation_ignore_les_faits_candidats():
    """La consolidation nocturne condense les événements du bus ; un candidat déposé n'en est pas
    un : sans WCT ni variance ce jour-là, elle refuse comme avant."""
    registre_evenements = registre.Registre()
    journal, _, _ = _deposer([_fait("tc-0001")])

    resultat = consolidation.consolider_affaire(
        "LEAD-001", "2026-09-28", "2026-09-29T03:00:00+00:00", registre_evenements, journal
    )

    assert resultat["ecrit"] is False
    assert resultat["verdict"] == consolidation.REJ_CONSOLIDATION_AUCUN_EVENEMENT


def test_le_depot_n_altere_pas_les_maillons_existants():
    journal = registre.Registre()
    wct.memoriser_wct(
        {
            "wct_id": "WCT-1",
            "intervention_id": "INT-1",
            "lead_id": "LEAD-001",
            "technicien_id": "TECH-1",
            "horodatage_completion": HORODATAGE,
            "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
            "duree_reelle_minutes": 90,
            "ecart_signale": False,
            "revue_id": None,
            "hash_maillon": "a" * 64,
            "consommateurs_cibles": ["M10"],
            "devis_id": "DEV-1",
        },
        journal,
    )
    avant = journal.lire()

    _deposer([_fait("tc-0001")], registre_affaires=journal)

    assert journal.lire()[: len(avant)] == avant
    assert journal.valider_chaine() == (True, "")
