"""Athéna : le conseil gouverné. Une recommandation est une PROPOSITION dont chaque chiffre a une source vérifiée ; M9
ne
décide jamais, ne calcule jamais de tête, s'abstient plutôt que d'estimer et porte la mention professionnelle
(fictif)."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
from m9_strategic_intelligence import certitude as ct
from m9_strategic_intelligence import dossier_strategique
from m9_strategic_intelligence import recommandation_gouvernee as rg


def _aide():
    spec = importlib.util.spec_from_file_location("pages_athena", Path(__file__).with_name("pages_athena.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


P = _aide()
FICTIF = True
MENTION = "À valider auprès d'un comptable (CPA) / professionnel qualifié"
EMPREINTE_RECU = "9a" * 32


def monde():
    """Faits citables et certitudes d'une chaîne fictive (santé déterminée mais non validée, prévision M2,
    calendrier)."""
    chaine: list = []
    P.capturer(chaine, "m8.synthese_direction", P.page_m8(determine=True, validee=False), "2026-10-28T12:00:01Z")
    P.capturer(chaine, "m2.prevision_pipeline", P.page_m2_prevision(), "2026-10-28T12:00:02Z")
    P.capturer(chaine, "m5.statut_revue_fiscale", P.page_m5_statut(), "2026-10-28T12:00:03Z")
    faits, _ = dossier_strategique.faits_citables(chaine, max_faits=10**6)
    return chaine, faits, ct.certitude_des_faits(chaine)


CHAINE, FAITS, CERTITUDES = monde()


def adresse(fin):
    (cle,) = [a for a in FAITS if a.endswith(fin)]
    return cle


def recu_factice(valeur="1500.00"):
    return {"type": "RECU_CALCUL", "format": "recu-calcul.v1", "empreinte": EMPREINTE_RECU,
            "resultat": {"point_mort": {"quantite_entiere": valeur}}}  # fmt: skip


def verifier_ok(recu):
    return (recu.get("empreinte") == EMPREINTE_RECU, "" if recu.get("empreinte") == EMPREINTE_RECU else "retouché")


def reco_valide():
    a_score = adresse("resultat.sante.score")
    a_total = adresse("prevision_totale.centre")
    return {
        "schema": rg.SCHEMA,
        "question": "Faut-il acheter un deuxième camion ce trimestre ?",
        "domaines": ["capacite", "financement"],
        "hypotheses": [
            {"id": "h1", "enonce": "La demande des trois prochains mois ressemble à celle des trois derniers.",
                "source": "modele"},
            {"id": "h2", "enonce": "Prix du camion déclaré par la direction.", "source": "direction",
                "valeur": "85000.00",
             "unite": "CAD", "declaree_par": "Nathan (fictif)"},
        ],  # fmt: skip
        "chiffres": [
            {"id": "c1", "libelle": "Score de santé (essai)", "valeur": FAITS[a_score], "unite": "/100",
             "source": {"genre": "fait", "adresse": a_score}, "certitude": ct.ESSAI},
            {"id": "c2", "libelle": "Leads attendus, centre", "valeur": FAITS[a_total], "unite": "leads",
             "source": {"genre": "fait", "adresse": a_total}, "certitude": ct.PREVISION},
            {"id": "c3", "libelle": "Point mort (unités)", "valeur": "1500.00", "unite": "unités",
             "source": {"genre": "recu_m5", "empreinte": EMPREINTE_RECU, "chemin": "point_mort.quantite_entiere"},
             "certitude": ct.ETABLI},
            {"id": "c4", "libelle": "Prix du camion", "valeur": "85000.00", "unite": "CAD",
             "source": {"genre": "hypothese", "ref": "h2"}, "certitude": ct.ESSAI},
        ],
        "options": [
            {"id": "o1", "titre": "Acheter maintenant", "description": "Acheter le camion au prix déclaré.",
             "chiffres": ["c3", "c4"], "risques": ["r1"]},
            {"id": "o2", "titre": "Attendre", "description": "Ne rien acheter avant la revue du prochain trimestre.",
             "chiffres": ["c1", "c2"], "risques": []},
        ],  # fmt: skip
        "risques": [{"id": "r1", "enonce": "La santé de l'entreprise n'est qu'un essai.", "refs": ["c1"]}],
        "donnees_manquantes": [
            {"id": "m1", "enonce": "Capacité d'équipe de la semaine prochaine non lue.",
                "proprietaire": "m04-field-ops",
             "bloquante": False}],
        "recommandation": {"option_id": "o2", "texte": "Attendre : la décision reste à la direction.",
            "abstention_raison": None},
        "statut": rg.STATUT,
        "decision_prise_par_m9": False,
        "validation_requise": ["direction", "comptable_cpa"],
        "mention_professionnelle": MENTION,
    }  # fmt: skip


def controler(reco, **kw):
    return rg.controler(
        reco,
        faits=FAITS,
        certitudes=CERTITUDES,
        recus={EMPREINTE_RECU: recu_factice()},
        verifier_recu=verifier_ok,
        **kw,
    )


def refus(reco, code, **kw):
    with pytest.raises(ValueError, match=code):
        controler(reco, **kw)


def test_une_recommandation_complete_et_honnete_est_admise():
    resultat = controler(reco_valide())
    assert resultat["valide"] is True and resultat["decision_prise_par_m9"] is False
    assert resultat["chiffres"] == 4 and resultat["recus_verifies"] == [EMPREINTE_RECU]
    assert set(resultat["domaines_professionnels"]) == {"comptable", "financement"}
    assert resultat["recommandation_id"] == rg.identifiant(reco_valide())


def test_m9_ne_decide_jamais():
    for champ, valeur in (("decision_prise_par_m9", True), ("statut", "DECIDEE"), ("statut", "APPROUVEE")):
        reco = reco_valide()
        reco[champ] = valeur
        refus(reco, "REJ-RECO-DECISION")
    for texte in (
        "J'ai décidé d'acheter le camion.",
        "C'est approuvé.",
        "La décision est prise.",
        "Nous avons signé le contrat.",
    ):
        reco = reco_valide()
        reco["recommandation"]["texte"] = texte
        refus(reco, "REJ-RECO-DECISION")


@pytest.mark.parametrize(
    ("indice", "source", "code"),
    [
        (0, {"genre": "calcul_de_tete"}, "CHIFFRE-SANS-SOURCE"),
        (
            0,
            {"genre": "fait", "adresse": "m8.synthese_direction#0:p0.resultat.sante.score_inexistant"},
            "CHIFFRE-FAIT-INCONNU",
        ),
        (0, {"genre": "fait"}, "CHIFFRE-SANS-SOURCE"),
        (2, {"genre": "recu_m5", "empreinte": "00" * 32, "chemin": "point_mort.quantite_entiere"}, "CHIFFRE-RECU"),
        (2, {"genre": "recu_m5", "empreinte": EMPREINTE_RECU, "chemin": "point_mort.autre"}, "CHIFFRE-VALEUR"),
        (2, {"genre": "recu_m5", "empreinte": EMPREINTE_RECU, "chemin": "../../etc"}, "CHIFFRE-SANS-SOURCE"),
        (3, {"genre": "hypothese", "ref": "h1"}, "CHIFFRE-SANS-SOURCE"),
        (3, {"genre": "hypothese", "ref": "inconnue"}, "CHIFFRE-SANS-SOURCE"),
    ],
)
def test_un_chiffre_sans_source_verifiee_est_refuse(indice, source, code):
    reco = reco_valide()
    reco["chiffres"][indice]["source"] = source
    refus(reco, f"REJ-RECO-{code}")


def test_une_valeur_qui_ne_correspond_pas_mot_pour_mot_au_fait_est_refusee():
    reco = reco_valide()
    reco["chiffres"][0]["valeur"] = "72.00"
    refus(reco, "REJ-RECO-CHIFFRE-VALEUR")
    reco = reco_valide()
    reco["chiffres"][2]["valeur"] = "1501.00"
    refus(reco, "REJ-RECO-CHIFFRE-VALEUR")


def test_un_essai_une_prevision_ou_un_perime_n_est_jamais_presente_comme_etabli():
    for indice, faux in ((0, ct.ETABLI), (1, ct.ETABLI), (0, ct.PREVISION)):
        reco = reco_valide()
        reco["chiffres"][indice]["certitude"] = faux
        refus(reco, "REJ-RECO-STATUT-FAUX")
    reco = reco_valide()
    reco["chiffres"][3]["certitude"] = ct.ETABLI  # une hypothèse reste un essai
    refus(reco, "REJ-RECO-STATUT-FAUX")


def test_un_recu_retouche_ou_absent_ou_sans_verificateur_est_refuse():
    reco = reco_valide()
    with pytest.raises(ValueError, match="REJ-RECO-CHIFFRE-RECU"):
        rg.controler(reco, faits=FAITS, certitudes=CERTITUDES, recus={}, verifier_recu=verifier_ok)
    with pytest.raises(ValueError, match="REJ-RECO-CHIFFRE-RECU"):
        rg.controler(reco, faits=FAITS, certitudes=CERTITUDES, recus={EMPREINTE_RECU: recu_factice()})
    retouche = recu_factice()
    retouche["empreinte"] = "00" * 32
    with pytest.raises(ValueError, match="REJ-RECO-CHIFFRE-RECU"):
        rg.controler(
            reco, faits=FAITS, certitudes=CERTITUDES, recus={EMPREINTE_RECU: retouche}, verifier_recu=verifier_ok
        )


def test_un_chiffre_ecrit_dans_un_texte_libre_sans_source_est_refuse():
    for champ, valeur in (
        (("recommandation", "texte"), "Attendre : le camion coûterait environ 92 000 $ de plus."),
        (("options", 0, "description"), "Un acompte de 15 % couvrirait le risque."),
        (("risques", 0, "enonce"), "Le déficit atteindrait 12 500,00 $ en janvier."),
        (("hypotheses", 0, "enonce"), "La demande augmente de 7,5 % par mois."),
    ):
        reco = reco_valide()
        cible = reco
        for cle in champ[:-1]:
            cible = cible[cle]
        cible[champ[-1]] = valeur
        refus(reco, "REJ-CONSEIL-CHIFFRE-LIBRE")
    reco = reco_valide()  # un chiffre CITÉ peut être repris tel quel dans le texte
    reco["recommandation"]["texte"] = "Attendre : le prix déclaré est 85000.00 $ et la décision reste à la direction."
    assert controler(reco)["valide"] is True


def test_une_valeur_d_hypothese_vient_de_la_direction_jamais_du_modele():
    reco = reco_valide()
    reco["hypotheses"][0]["valeur"] = "10"
    refus(reco, "REJ-RECO-HYPOTHESE")
    reco = reco_valide()
    del reco["hypotheses"][1]["declaree_par"]
    refus(reco, "REJ-RECO-HYPOTHESE")


def test_une_donnee_bloquante_manquante_interdit_de_recommander_et_l_abstention_dit_pourquoi():
    reco = reco_valide()
    reco["donnees_manquantes"][0]["bloquante"] = True
    refus(reco, "REJ-RECO-RECOMMANDE-SUR-INCONNU")
    reco["recommandation"] = {
        "option_id": None,
        "texte": "Aucune option n'est recommandée.",
        "abstention_raison": "La capacité d'équipe n'est pas lue : rien n'est estimé.",
    }
    resultat = controler(reco)
    assert resultat["abstention"] is True
    reco["recommandation"]["abstention_raison"] = None
    refus(reco, "REJ-RECO-ABSTENTION")


def test_la_mention_professionnelle_est_exigee_si_declaree_ou_impliquee_par_les_sources():
    reco = reco_valide()
    reco["mention_professionnelle"] = None
    refus(reco, "REJ-RECO-MENTION")
    sans_domaine = reco_valide()
    sans_domaine["domaines"] = ["capacite"]  # le domaine déclaré cache la nature de la source
    sans_domaine["mention_professionnelle"] = None
    refus(sans_domaine, "REJ-RECO-MENTION")  # les sources M5/M8 impliquent un avis comptable
    reco = reco_valide()
    reco["validation_requise"] = ["direction"]
    refus(reco, "REJ-RECO-VALIDATION")
    reco["validation_requise"] = []
    refus(reco, "REJ-RECO-VALIDATION")
    juridique = reco_valide()
    juridique["domaines"] = ["juridique"]
    juridique["chiffres"] = [c for c in juridique["chiffres"] if c["id"] == "c4"]
    juridique["options"][0]["chiffres"], juridique["options"][1]["chiffres"] = ["c4"], []
    juridique["risques"][0]["refs"] = ["c4"]
    refus(juridique, "REJ-RECO-VALIDATION")  # avis juridique : juriste requis


def test_deux_options_au_moins_et_references_existantes():
    reco = reco_valide()
    reco["options"] = reco["options"][:1]
    refus(reco, "REJ-RECO-FORME")
    reco = reco_valide()
    reco["options"][0]["chiffres"] = ["c99"]
    refus(reco, "REJ-RECO-FORME")
    reco = reco_valide()
    reco["recommandation"]["option_id"] = "o99"
    refus(reco, "REJ-RECO-FORME")
    reco = reco_valide()
    reco["risques"][0]["refs"] = ["rien"]
    refus(reco, "REJ-RECO-RISQUE-SANS-SOURCE")
    reco = reco_valide()
    reco["risques"][0]["refs"] = []
    refus(reco, "REJ-RECO-RISQUE-SANS-SOURCE")


def test_forme_stricte_cle_en_trop_schema_json_fini():
    reco = reco_valide()
    reco["extra"] = "x"
    refus(reco, "REJ-RECO-FORME")
    reco = reco_valide()
    reco["schema"] = "autre"
    refus(reco, "REJ-RECO-FORME")
    reco = reco_valide()
    reco["chiffres"][0]["valeur"] = float("nan")
    refus(reco, "REJ-RECO-FORME")
    refus("pas un objet", "REJ-RECO-FORME")
    reco = reco_valide()
    reco["domaines"] = ["domaine_inventé"]
    refus(reco, "REJ-RECO-FORME")


def test_le_controle_est_deterministe_et_ne_modifie_pas_la_recommandation():
    reco = reco_valide()
    avant = copy.deepcopy(reco)
    a, b = controler(reco), controler(reco)
    assert a == b and reco == avant


def test_nombres_libres_aucun_nombre_n_est_libre_dans_un_texte_de_recommandation():
    assert rg.nombres_libres("Il faudrait 2500 unités de plus.", ["1500"]) == ["2500"]
    assert rg.nombres_libres("Les options c1 et o2 n'ont aucun nombre.", []) == []
    assert rg.nombres_libres("Revue le 2026-11-01.", ["2026-11-01"]) == []
    assert rg.nombres_libres("Revue le 2026-11-02.", ["2026-11-01"]) == ["2026-11-02"]
    assert rg.nombres_libres("Prix de 85 000,00 $ déclaré.", ["85000.00"]) == []
    assert rg.nombres_libres("Un acompte de 15 %.", ["85000.00"]) == ["15"]
    assert rg.nombres_libres("Dans trois mois.",
        []) == [], "un nombre écrit en lettres n'est pas détectable (limite connue)"


def test_une_date_ou_un_nombre_dans_le_titre_d_une_option_est_aussi_controle():
    reco = reco_valide()
    reco["options"][1]["titre"] = "Attendre 6 mois"
    refus(reco, "REJ-CONSEIL-CHIFFRE-LIBRE")
    reco = reco_valide()
    reco["hypotheses"][0]["enonce"] = "La demande double d'ici le 2027-01-15."
    refus(reco, "REJ-CONSEIL-CHIFFRE-LIBRE")
