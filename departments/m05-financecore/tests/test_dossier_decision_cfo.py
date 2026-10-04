"""RED M5.16: contrat exact, composition sur un snapshot et refus avant lecture."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from m5_financecore import comptes_a_payer, dossier_decision_cfo, facturation, registre, taux_fiscaux
from m5_financecore import outils as m5_outils
from sqlalchemy import select, update

from opsys import contexte, departements, identite, stockage
from opsys.capacites import Capacites
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import META, REGISTRES

FICTIF = True
NOM_OUTIL = "m5_preparer_dossier_decision_cfo"
QUESTION = "Faut-il préparer le renouvellement du camion?"
AUJOURD_HUI = "2026-09-30"
ADMIN = contexte.IdentiteAppelante(personne="admin.cfo.fictif", role="admin")
_CONTRAT = Path(__file__).resolve().parents[1] / "contracts" / "dossier_decision_cfo.v1.yaml"
_TITRES = [
    "Question posée",
    "Résumé exécutif",
    "Recommandation",
    "Niveau de confiance",
    "Données utilisées",
    "Données manquantes",
    "Hypothèses",
    "Scénario prudent",
    "Scénario normal",
    "Scénario optimiste",
    "Cashflow 13 semaines",
    "Projection 6 mois",
    "Projection 12 mois",
    "Projection 24 mois",
    "Impact taxes",
    "Impact paie",
    "Impact dette",
    "Impact marge",
    "Impact croissance",
    "Risques principaux",
    "Conditions avant d'agir",
    "Questions CPA/fiscaliste",
    "Questions banque/prêteur",
    "Plan d'action recommandé",
    "Validation requise",
]


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-cfo-dossier.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN.personne, "Admin fictif", "mot-de-passe-admin-cfo-123", ["admin"])
    yield url
    stockage.liberer()


def _outil_rapport():
    return next((outil for outil in m5_outils.outils() if outil.nom == NOM_OUTIL), None)


def _appeler(outil, *, aujourd_hui=AUJOURD_HUI, question=QUESTION):
    with contexte.appele_par_appareil(ADMIN):
        return executer_atomique(outil, {"aujourd_hui": aujourd_hui, "question_posee": question})


def _obligation_projection(section, identifiant):
    table = section["contenu"]["obligations_declarees"]
    cles, champs, lignes, codes = table
    alias_cles = {"p": "paies", "d": "das"}
    alias_champs = {
        "s": "statut", "d": "montant_declare_cad", "u": "montant_utilisable_cad",
        "e": "echeance", "t": "echeance_statut", "p": "periode", "a": "autorite",
        "q": "source_montant_description", "j": "source_montant_au", "x": "source_echeance",
        "y": "annee", "v": "version",
    }
    index = [alias_cles[cle] for cle in cles].index(identifiant)
    valeur = dict(zip((alias_champs[champ] for champ in champs), lignes[index], strict=True))
    if "source_montant_description" in valeur or "source_montant_au" in valeur:
        valeur["source_montant"] = [
            valeur.pop("source_montant_description", None), valeur.pop("source_montant_au", None)
        ]
    if isinstance(codes, int):
        masque = codes
        codes_complets = []
    elif isinstance(codes, list):
        masque = codes[index]
        codes_complets = []
    else:
        masque = codes["masques"] if isinstance(codes["masques"], int) else codes["masques"][index]
        codes_complets = codes["codes_complets_par_ligne"][index]
    suffixes = {
        "MONTANT-ABSENT": 1, "SOURCE-MONTANT-ABSENTE": 2, "ECHEANCE-ABSENTE": 4,
        "PERIODE-SOURCE-ABSENTE": 8, "SOURCE-INVALIDE": 16, "PERIODE-INVALIDE": 32,
        "DATE-SOURCE-INVALIDE": 64, "ANNEE-VERSION-INVALIDE": 128, "SOURCE-PERIMEE": 256,
    }
    valeur["statut"] = {"i": "INCOMPLETE", "d": "DOCUMENTEE_A_VALIDER",
                        "p": "ECHEANCE_PASSEE_A_VERIFIER", "x": "SOURCE_PERIMEE"}.get(
                            valeur["statut"], valeur["statut"]
                        )
    valeur["echeance_statut"] = {"a": "A_VENIR", "p": "PASSEE_A_VERIFIER", "n": "NON_DECLAREE"}.get(
        valeur["echeance_statut"], valeur["echeance_statut"]
    )
    valeur["manque"] = [
        f"REJ-CALENDRIER-{identifiant.upper()}-{code}"
        for code, bit in suffixes.items() if masque & bit
    ] + codes_complets
    return valeur


def _snapshot_tables():
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


def _corrompre_maillon(nom_registre, rang, champ, valeur=None, *, supprimer=False):
    """Altération SQL locale de fixture, sans recalcul du hash du maillon."""
    with stockage.transaction() as cnx:
        ligne = cnx.execute(
            select(REGISTRES.c.maillon).where(
                REGISTRES.c.departement == "m05-financecore",
                REGISTRES.c.registre == nom_registre,
                REGISTRES.c.rang == rang,
            )
        ).scalar_one()
        maillon = codec.decoder(ligne)
        if supprimer:
            maillon.pop(champ)
        else:
            maillon[champ] = valeur
        cnx.execute(
            update(REGISTRES)
            .where(
                REGISTRES.c.departement == "m05-financecore",
                REGISTRES.c.registre == nom_registre,
                REGISTRES.c.rang == rang,
            )
            .values(maillon=codec.encoder(maillon))
        )


def _declarer_configuration(tmp_path, monkeypatch):
    configuration = {
        "fiscal": {
            "frequence_tps_tvq": "trimestrielle",
            "mois_fin_exercice": 12,
            "taxes_remises_jusqu_au": "2026-06-30",
        },
        "obligations_declarees": {
            "paies": {"montant": "4200.00", "source": "paie fictive", "au": "2026-09-25"},
            "das": {"montant": "1350.75", "source": "retenues fictives", "au": "2026-09-25"},
            "dettes": {"montant": "800.00", "source": "relevé fictif", "au": "2026-09-01"},
        },
        "prevision": {
            "horizon_semaines": 13,
            "seuil_alerte": {"montant": "16000.00", "source": "décision fictive", "au": "2026-09-25"},
            "delai_encaissement_clients_jours": 30,
            "delai_paiement_fournisseurs_jours": 30,
            "echeances_obligations": {
                "paies": "2026-10-09", "das": "2026-10-15", "dettes": "2026-10-31"
            },
        },
    }
    manifeste = tmp_path / "department-cfo.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)


def _peupler_snapshot_connu():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    with stockage.transaction():
        mouvements = m5_outils._registre_mouvements(None)
        registre.enregistrer_mouvement(
            {"montant": Decimal("25000.00"), "type_mouvement": "ENCAISSEMENT",
             "horodatage": "2026-08-01T12:00:00-04:00", "classe_retention": "STANDARD", "source": "fictif"},
            mouvements,
        )
        registre.enregistrer_mouvement(
            {"montant": Decimal("1000.00"), "type_mouvement": "PROVISION",
             "horodatage": "2026-09-10T12:00:00-04:00", "classe_retention": "STANDARD", "source": "fictif"},
            mouvements,
        )
        factures = m5_outils._registre_factures(None)
        for index, (montant, date_facture) in enumerate((
            ("4000.00", "2026-09-14"), ("2000.00", "2026-09-20"),
            ("1000.00", "2026-08-20"), ("500.00", "2026-09-01"),
        ), start=1):
            _, verdict = facturation.creer_facture_brouillon(
                f"FACTURE-PRIVEE-{index}", "CHANTIER-TEST", f"DEVIS-{index}", f"CLIENT-PRIVE-{index}",
                [{"description": "travaux fictifs", "quantite": "1", "unite": "u",
                  "prix_unitaire": montant, "reference_ligne_devis": "L-1"}],
                f"{date_facture}T09:00:00-04:00", dictionnaire, factures,
            )
            assert verdict is None
            if index <= 3:
                assert facturation.envoyer_facture(
                    f"FACTURE-PRIVEE-{index}", f"{date_facture}T09:30:00-04:00", factures
                )[1] is None

        m5_outils._recevoir_reception_enregistree({
            "evenement_id": "EVENT-PO-1", "po_id": "PO-1", "fournisseur_id": "fournisseur-test",
            "chantier_id": "CHANTIER-TEST", "horodatage_reception": "2026-09-15T09:00:00-04:00",
            "verdict_reception": "CONFORME", "statut_po": "received", "hash_maillon": "a" * 64,
            "seuil_ecart_prix_pourcentage": 0.15,
            "lignes": [{"materiau_id": "gouttiere", "quantite_demandee": "60", "quantite_recue": "60",
                        "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                        "prix_unitaire_reception": "5.00", "verdict_prix_reception": "PRIX_CATALOGUE",
                        "ecart_prix_critique": False}],
        })
        a_payer = m5_outils._registre_comptes_a_payer()
        _, verdict = comptes_a_payer.saisir_facture_fournisseur(
            po_id="PO-1", fournisseur_id="fournisseur-test", numero_facture="FOURNISSEUR-PRIVE-1",
            date_facture="2026-09-14", montant_avant_taxes="300.00", total_facture=None,
            saisi_par="Nathan Fictif", voie="appareil", horodatage="2026-09-20T10:00:00-04:00",
            dictionnaire_taux=dictionnaire, registre_cible=a_payer,
        )
        assert verdict is None


def test_contrat_presente_les_25_rubriques_exactes_et_schema_ferme():
    contrat = yaml.safe_load(_CONTRAT.read_text(encoding="utf-8"))
    rubriques = contrat["rubriques"]
    outil = _outil_rapport()

    assert [ligne["titre"] for ligne in rubriques] == _TITRES
    assert [ligne["numero"] for ligne in rubriques] == list(range(1, 26))
    assert outil is not None, f"outil T0 {NOM_OUTIL} à ajouter au raccord composé M5.16"
    assert outil.autonomie.name == "T0"
    assert outil.parametres["additionalProperties"] is False
    assert outil.parametres["required"] == ["aujourd_hui", "question_posee"]
    assert set(outil.parametres["properties"]) == {"aujourd_hui", "question_posee"}


def test_rapport_vide_rend_tout_inconnu_depuis_un_seul_snapshot_sans_ecriture(base_durable, monkeypatch):
    outil = _outil_rapport()
    assert outil is not None, f"outil T0 {NOM_OUTIL} à ajouter au raccord composé M5.16"
    original = m5_outils._lectures_finance
    instantanes = []

    def lire_une_fois(*args, **kwargs):
        instantane = original(*args, **kwargs)
        instantanes.append(instantane)
        return instantane

    monkeypatch.setattr(m5_outils, "_lectures_finance", lire_une_fois)
    avant = _snapshot_tables()

    reponse = _appeler(outil)

    apres = _snapshot_tables()
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is True, reponse
    rapport = reponse["resultat"]["resultat"]
    assert len(instantanes) == 1
    assert rapport["question_posee"] == QUESTION
    assert rapport["statut_global"] == "PREPARATOIRE"
    assert [r["titre"] for r in rapport["rubriques"]] == _TITRES
    assert rapport["rubriques"][2]["statut"] == "INCONNU"
    assert rapport["rubriques"][2]["contenu"] is None
    assert rapport["rubriques"][3]["statut"] == "INCONNU"
    assert rapport["rubriques"][3]["contenu"] is None
    impact_paie = rapport["rubriques"][15]
    assert impact_paie["statut"] == "INCONNU"
    assert impact_paie["contenu"] is None
    assert rapport["rubriques"][10]["statut"] == "INCONNU"
    assert any("26 sem." in manque for manque in rapport["rubriques"][5]["manque"])
    assert avant == apres
    assert len(json.dumps(rapport, ensure_ascii=False)) < 5500, [
        (r["titre"], len(json.dumps(r, ensure_ascii=False))) for r in rapport["rubriques"]
    ]


def test_role_retire_est_refuse_avant_toute_lecture_du_snapshot(base_durable, monkeypatch):
    outil = _outil_rapport()
    assert outil is not None, f"outil T0 {NOM_OUTIL} à ajouter au raccord composé M5.16"
    appels_lectures = 0
    original = m5_outils._lectures_finance

    def compter_lectures(*args, **kwargs):
        nonlocal appels_lectures
        appels_lectures += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(m5_outils, "_lectures_finance", compter_lectures)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")

    reponse = _appeler(outil)

    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False
    assert appels_lectures == 0


def test_appel_sans_identite_est_refuse_avant_toute_lecture_du_snapshot(base_durable, monkeypatch):
    outil = _outil_rapport()
    assert outil is not None
    appels_lectures = 0
    original = m5_outils._lectures_finance

    def compter_lectures(*args, **kwargs):
        nonlocal appels_lectures
        appels_lectures += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(m5_outils, "_lectures_finance", compter_lectures)
    reponse = executer_atomique(outil, {"aujourd_hui": AUJOURD_HUI, "question_posee": QUESTION})

    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-AUTORISE-COUTS-REQUIS"
    assert appels_lectures == 0


def test_cashflow_13_semaines_ne_devient_pas_partiel_sur_une_semaine_calculee_apres_l_horizon():
    semaines = [
        {"semaine": n, "du": f"2026-10-{n:02d}", "statut": "A_CONFIGURER"}
        for n in range(1, 14)
    ] + [{"semaine": n, "du": f"2026-11-{n - 13:02d}", "statut": "CALCULE"}
          for n in range(14, 27)]
    semaines[-1]["statut"] = "A_CONFIGURER"
    rapport = dossier_decision_cfo.composer(
        question_posee=QUESTION, aujourd_hui=AUJOURD_HUI,
        cash={"composantes": [], "manque": [], "hypotheses": []},
        comptes_a_recevoir=None, comptes_a_payer=None,
        prevision={"semaines": semaines}, source_refs=[], mention="analyse fictive",
    )

    assert rapport["rubriques"][10]["statut"] == "INCONNU"
    assert rapport["rubriques"][10]["contenu"] is None
    assert rapport["rubriques"][11]["statut"] == "PARTIEL"
    assert rapport["rubriques"][11]["contenu"]["statut_derniere_semaine"] == "A_CONFIGURER"
    assert rapport["rubriques"][11]["contenu"]["derniere_semaine"] == [26, "2026-11-13", None, None, None]


def test_compositeur_sans_calendrier_garde_la_projection_historique_des_paies():
    paie = {
        "id": "paies", "statut": "OBSERVEE", "montant": "4200.00",
        "source": {"description": "paie fictive"}, "fraicheur": {"derniere_piece": "2026-09-25"},
    }
    rapport = dossier_decision_cfo.composer(
        question_posee=QUESTION, aujourd_hui=AUJOURD_HUI,
        cash={"composantes": [paie], "manque": [], "hypotheses": []},
        comptes_a_recevoir=None, comptes_a_payer=None,
        prevision=None, source_refs=[], mention="analyse fictive",
    )

    rubrique = rapport["rubriques"][15]
    assert rubrique["statut"] == "PARTIEL"
    assert rubrique["contenu"]["paies_declarees"] == {
        "statut": "OBSERVEE", "montant_cad": "4200.00",
        "source": "paie fictive", "fraicheur": "2026-09-25",
    }
    assert rubrique["contenu"]["obligations_declarees"] == {}
    assert rubrique["contenu"]["limites"] == [
        "montants déclaratifs, pas une paie nette calculée; aucune exécution officielle"
    ]


def test_question_maximale_est_rendue_une_fois_et_le_snapshot_scelle_configuration(base_durable, monkeypatch):
    outil = _outil_rapport()
    assert outil is not None
    question = "Q" * 1000
    reponse = _appeler(outil, question=question)

    assert reponse["resultat"]["accepte"] is True, reponse
    rapport = reponse["resultat"]["resultat"]
    assert rapport["question_posee"] == question
    assert rapport["rubriques"][0]["contenu"] == {"question_posee_ref": "question_posee"}
    assert len(json.dumps(rapport, ensure_ascii=False)) < m5_outils.BUDGET_SORTIE

    première = rapport["reference"]["snapshot_id"]
    autre_question = _appeler(outil, question="Question reformulée")
    assert autre_question["resultat"]["resultat"]["reference"]["snapshot_id"] == première
    monkeypatch.setattr(m5_outils, "_configuration_manifeste", lambda: {"obligations_declarees": {"dettes": {
        "montant": "12.00", "source": "preuve fictive", "au": "2026-09-30"}}})
    suivante = _appeler(outil, question=question)["resultat"]["resultat"]["reference"]["snapshot_id"]
    assert suivante != première


def test_section_paie_expose_obligations_et_metadonnees_du_calendrier_sans_calcul_net(
    base_durable, tmp_path, monkeypatch
):
    _declarer_configuration(tmp_path, monkeypatch)
    configuration = m5_outils._configuration_manifeste()
    configuration["calendrier_obligations"] = {
        identifiant: {
            "autorite": f"Autorité fictive {identifiant}",
            "periode_debut": "2026-09-01", "periode_fin": "2026-09-30",
            "echeance_source": f"Pièce fictive {identifiant}", "source_consultee_le": "2026-09-25",
            "source_applicable_du": "2026-01-01", "source_applicable_jusqu_au": "2026-12-31",
            "annee": 2026, "version": "édition fictive 2026-v2",
        }
        for identifiant in ("paies", "das")
    }
    monkeypatch.setattr(m5_outils, "_configuration_manifeste", lambda: configuration)

    reponse = _appeler(_outil_rapport())

    assert reponse["resultat"]["accepte"] is True, reponse
    rubrique = reponse["resultat"]["resultat"]["rubriques"][15]
    assert rubrique["statut"] == "PARTIEL"
    paies = _obligation_projection(rubrique, "paies")
    assert paies == {
        "statut": "DOCUMENTEE_A_VALIDER", "montant_declare_cad": "4200.00",
        "montant_utilisable_cad": "4200.00", "echeance": "2026-10-09", "echeance_statut": "A_VENIR",
        "periode": ["2026-09-01", "2026-09-30"],
        "autorite": "Autorité fictive paies",
        "source_montant": ["paie fictive", "2026-09-25"],
        "source_echeance": ["Pièce fictive paies", "2026-09-25", "2026-01-01", "2026-12-31"],
        "annee": 2026, "version": "édition fictive 2026-v2", "manque": [],
    }
    limites = rubrique["contenu"]["limites"]
    assert "Déclaratif" in limites
    assert "net non calculé" in limites
    assert "exécution officielle" in limites
    assert "paies_declarees" not in rubrique["contenu"]


def test_section_paie_source_perimee_ou_absente_ne_donne_jamais_de_montant_utilisable(
    base_durable, tmp_path, monkeypatch
):
    _declarer_configuration(tmp_path, monkeypatch)
    configuration = m5_outils._configuration_manifeste()
    configuration["calendrier_obligations"] = {
        "paies": {
            "autorite": "Autorité fictive", "periode_debut": "2026-09-01", "periode_fin": "2026-09-30",
            "echeance_source": "Pièce fictive", "source_consultee_le": "2026-09-25",
            "source_applicable_du": "2026-01-01", "source_applicable_jusqu_au": "2026-06-30",
            "annee": 2026, "version": "H1 fictif",
        }
    }
    monkeypatch.setattr(m5_outils, "_configuration_manifeste", lambda: configuration)

    reponse = _appeler(_outil_rapport())

    assert reponse["resultat"]["accepte"] is True, reponse
    rubrique = reponse["resultat"]["resultat"]["rubriques"][15]
    paies = _obligation_projection(rubrique, "paies")
    das = _obligation_projection(rubrique, "das")
    assert rubrique["statut"] == "PARTIEL"
    assert paies["statut"] == "SOURCE_PERIMEE"
    assert paies["montant_declare_cad"] == "4200.00"
    assert paies["montant_utilisable_cad"] is None
    assert "REJ-CALENDRIER-PAIES-SOURCE-PERIMEE" in paies["manque"]
    assert das["statut"] == "INCOMPLETE"
    assert das["montant_declare_cad"] == "1350.75"
    assert das["montant_utilisable_cad"] is None
    assert das["manque"]
    table = rubrique["contenu"]["obligations_declarees"]
    assert "p" in table[1]
    assert "x" in table[1]
    assert "v" in table[1]
    assert paies["periode"] == ["2026-09-01", "2026-09-30"]
    assert paies["autorite"] == "Autorité fictive"
    assert paies["source_echeance"] == [
        "Pièce fictive", "2026-09-25", "2026-01-01", "2026-06-30"
    ]
    assert paies["version"] == "H1 fictif"
    assert das["periode"] is None
    assert das["autorite"] is None
    assert das["source_echeance"] is None
    assert das["version"] is None
    assert table[3] == [256, 248]


def test_calendrier_reel_sqlite_est_dans_le_meme_snapshot_sans_ecriture_et_das_est_visible(
    base_durable, tmp_path, monkeypatch
):
    _declarer_configuration(tmp_path, monkeypatch)
    configuration = m5_outils._configuration_manifeste()
    configuration["calendrier_obligations"] = {
        identifiant: {
            "autorite": f"Autorité fictive {identifiant}",
            "periode_debut": "2026-09-01", "periode_fin": "2026-09-30",
            "echeance_source": f"Pièce fictive {identifiant}", "source_consultee_le": "2026-09-25",
            "source_applicable_du": "2026-01-01", "source_applicable_jusqu_au": "2026-12-31",
            "annee": 2026, "version": "édition fictive 2026-v2",
        }
        for identifiant in ("paies", "das")
    }
    monkeypatch.setattr(m5_outils, "_configuration_manifeste", lambda: configuration)
    _peupler_snapshot_connu()
    lectures = 0
    lire_finance = m5_outils._lectures_finance

    def capturer_lecture_unique(*args, **kwargs):
        nonlocal lectures
        lectures += 1
        return lire_finance(*args, **kwargs)

    monkeypatch.setattr(m5_outils, "_lectures_finance", capturer_lecture_unique)
    avant = _snapshot_tables()

    rapport = _appeler(_outil_rapport())["resultat"]["resultat"]

    assert lectures == 1
    assert _snapshot_tables() == avant
    rubrique_paie = rapport["rubriques"][15]
    paies = _obligation_projection(rubrique_paie, "paies")
    das = _obligation_projection(rubrique_paie, "das")
    assert paies["montant_declare_cad"] == "4200.00"
    assert das["montant_declare_cad"] == "1350.75"
    assert das["montant_utilisable_cad"] == "1350.75"
    assert das["echeance"] == "2026-10-15"
    assert das["version"] == "édition fictive 2026-v2"
    assert das["statut"] == "DOCUMENTEE_A_VALIDER"

    configuration["calendrier_obligations"]["das"]["version"] = "édition fictive 2026-v3"
    rapport_suivant = _appeler(_outil_rapport())["resultat"]["resultat"]
    assert rapport_suivant["reference"]["snapshot_id"] != rapport["reference"]["snapshot_id"]
    assert _obligation_projection(rapport_suivant["rubriques"][15], "das")["version"] == "édition fictive 2026-v3"
    assert lectures == 2
    assert _snapshot_tables() == avant


def test_changement_du_calendrier_obligations_change_le_snapshot_cfo(base_durable, tmp_path, monkeypatch):
    _declarer_configuration(tmp_path, monkeypatch)
    configuration = m5_outils._configuration_manifeste()
    configuration["calendrier_obligations"] = {}
    monkeypatch.setattr(m5_outils, "_configuration_manifeste", lambda: configuration)
    première = _appeler(_outil_rapport())["resultat"]["resultat"]["reference"]["snapshot_id"]

    configuration["calendrier_obligations"] = {"paies": {"version": "nouvelle version fictive"}}
    suivante = _appeler(_outil_rapport())["resultat"]["resultat"]["reference"]["snapshot_id"]

    assert suivante != première


def test_capacites_garde_rapport_13_semaines_question_maximale_et_plusieurs_factures(
    base_durable, tmp_path, monkeypatch
):
    _declarer_configuration(tmp_path, monkeypatch)
    _peupler_snapshot_connu()
    capacites = Capacites(
        {"m05-financecore": departements.charger_departements()["m05-financecore"]}, stockage.transaction
    )
    question = "Q" * 1000
    avant = _snapshot_tables()
    diagnostic = {}
    composer_original = m5_outils.dossier_decision_cfo.composer

    def composer_avec_diagnostic(*args, **kwargs):
        rapport = composer_original(*args, **kwargs)
        tailles = [
            (rubrique["numero"], len(json.dumps(rubrique, ensure_ascii=False, default=str)))
            for rubrique in rapport["rubriques"]
        ]
        diagnostic["rapport"] = len(json.dumps(rapport, ensure_ascii=False, default=str))
        diagnostic["rubriques"] = tailles
        return rapport

    monkeypatch.setattr(m5_outils.dossier_decision_cfo, "composer", composer_avec_diagnostic)

    with contexte.appele_par_appareil(ADMIN):
        reponse = capacites.appeler(NOM_OUTIL, {"aujourd_hui": AUJOURD_HUI, "question_posee": question})
        prevision = capacites.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI, "horizon_semaines": 13})
        etat = capacites.appeler("m5_etat_tresorerie", {"autorise_couts": True})

    assert "tronque" not in reponse, reponse
    assert len(json.dumps(reponse, ensure_ascii=False)) <= 6000
    assert reponse["ok"] is True, reponse
    detail_diagnostic = (
        "fixture=_declarer_configuration+_peupler_snapshot_connu, question=1000 caractères, "
        "prévision=13 semaines; tailles JSON: "
        f"rapport={diagnostic.get('rapport')}, "
        f"rubriques(numero, caracteres)={diagnostic.get('rubriques')}"
    )
    assert reponse["resultat"]["accepte"] is True, f"{reponse}; {detail_diagnostic}"
    rapport = reponse["resultat"]["resultat"]
    assert rapport["question_posee"] == question
    assert [r["numero"] for r in rapport["rubriques"]] == list(range(1, 26))
    assert rapport["rubriques"][1]["contenu"]["AR"][0] == 3
    assert rapport["rubriques"][1]["contenu"]["AR"][1] is not None
    assert rapport["rubriques"][1]["contenu"]["AP_cad"] is not None
    refs = rapport["rubriques"][4]["source_refs"]
    assert refs["colonnes"] == ["departement", "registre", "taille", "tete"]
    maillons_source = [
        list(stockage.maillons("m05-financecore", nom_registre))
        for nom_registre in ("principal", "factures", "comptes_a_payer")
    ]
    assert [ligne[3] for ligne in refs["lignes"]] == [
        source[-1]["ligne_id"] if source else None for source in maillons_source
    ]
    cash = rapport["rubriques"][1]["contenu"]["cash_libre_cad"]
    assert isinstance(cash, str) and cash != "0.00"
    cash_canonique = etat["resultat"]["cash_libre"]
    assert cash == cash_canonique["cash_libre"]
    assert any(
        composante["id"] == "reserves" and composante["montant"] == "1000.00"
        for composante in cash_canonique["composantes"]
    )
    flux = rapport["rubriques"][10]["contenu"]
    assert flux["semaines_couvertes"] == 13
    assert flux["statut_par_defaut"] == "CALCULE"
    assert flux["debut_premiere_semaine"] == "2026-09-30"
    assert flux["pas_jours"] == 7
    assert "PRIVE" not in json.dumps(rapport, ensure_ascii=False)
    prevision_source = prevision["resultat"]["resultat"]["semaines"]
    assert flux["entrees_cad"] == [
        ligne.get("entrees") if ligne["statut"] == "CALCULE" else None for ligne in prevision_source[:13]
    ]
    assert flux["sorties_cad"] == [
        ligne.get("sorties") if ligne["statut"] == "CALCULE" else None for ligne in prevision_source[:13]
    ]
    assert flux["solde_fin_cad"] == [
        ligne.get("solde_fin") if ligne["statut"] == "CALCULE" else None for ligne in prevision_source[:13]
    ]
    assert _snapshot_tables() == avant


@pytest.mark.parametrize(
    ("nom_registre", "rang", "champ", "valeur", "supprimer"),
    [
        ("principal", 0, "montant", Decimal("35000.00"), False),
        ("comptes_a_payer", 1, "montant_avant_taxes", Decimal("10300.00"), False),
        ("factures", 0, "montant_avant_taxes", Decimal("14000.00"), False),
        ("principal", 0, "precedent_ligne_id", "maillon-malforme", False),
        ("principal", 0, "ligne_id", None, True),
        ("principal", 0, "type_mouvement", None, True),
    ],
    ids=[
        "principal-montant", "ap-montant", "facture-montant", "lien-malforme",
        "cle-hash-absente", "cle-type-mouvement-absente",
    ],
)
def test_dossier_refuse_une_chaine_financiere_alteree_sans_relire_ni_ecrire(
    base_durable, tmp_path, monkeypatch, nom_registre, rang, champ, valeur, supprimer
):
    _declarer_configuration(tmp_path, monkeypatch)
    _peupler_snapshot_connu()
    outil = _outil_rapport()
    assert outil is not None
    _corrompre_maillon(nom_registre, rang, champ, valeur, supprimer=supprimer)
    avant = _snapshot_tables()

    lectures = []
    original = m5_outils._lectures_finance

    def lire_une_fois(*args, **kwargs):
        instantane = original(*args, **kwargs)
        lectures.append(instantane)
        return instantane

    monkeypatch.setattr(m5_outils, "_lectures_finance", lire_une_fois)
    with contexte.appele_par_appareil(ADMIN):
        reponse = executer_atomique(outil, {"aujourd_hui": AUJOURD_HUI, "question_posee": QUESTION})

    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CFO-CHAINE-INVALIDE"
    assert len(lectures) == 1
    assert _snapshot_tables() == avant
    assert "cash_libre_cad" not in json.dumps(reponse, ensure_ascii=False)
    assert reponse["resultat"]["verdict"]["detail"]
