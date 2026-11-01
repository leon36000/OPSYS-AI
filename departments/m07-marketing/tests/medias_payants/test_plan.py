"""Le plan de campagne payante : un brouillon que la direction approuve par son empreinte exacte, et que rien n'exécute.

Journal en mémoire (une liste) et studio fictif : les gestes du module pur sont exercés sans base. Les outils, la file
d'approbation et le registre durable sont dans `test_medias_outils.py`.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from fabriques_medias import CLE, MAINTENANT, POLITIQUE, StudioFictif, controles, plan_brut
from m7_marketing import journal_chaine
from m7_marketing.medias_payants import plan as pl
from m7_marketing.sas_social.politique import PolitiqueSas

DECISION = {"par": "nathan", "role": "nathan_owner", "source": "approbation"}
H = "2026-11-01T12:00:00Z"


def composer(journal, brut=None, cle=CLE, studio=None, plan_id=None, **kw):
    c = controles(studio, **{k: kw.pop(k) for k in ("maintenant", "controle_marques") if k in kw})
    return pl.composer(journal, plan_brut() if brut is None else brut, cle, "agent", H, plan_id=plan_id, **c)


def codes(resultat):
    return [x["code"] for x in resultat.get("refus", [])]


def normaliser(brut, studio=None, **kw):
    return pl.normaliser(brut, **controles(studio, **kw))


def pret(journal, studio=None, **kw):
    cree = composer(journal, studio=studio, **kw)
    assert cree["accepte"], cree
    soumis = pl.soumettre(journal, cree["plan_id"], "agent", H, **controles(studio))
    assert soumis["accepte"], soumis
    return cree["plan_id"], cree["empreinte"]


# ======================================================================================================================
# le plan valide
# ======================================================================================================================
def test_un_plan_valide_est_normalise_avec_creatifs_verifies_et_plafonds_deduits():
    plan, refus = normaliser(plan_brut())
    assert refus == [] and plan["canal"] == "meta" and plan["budget"]["montant_total_cents"] == 20000
    assert plan["creatifs"][0]["empreinte_actif"] == "e" * 64 and plan["creatifs"][0]["media_sha256"] == "a" * 64
    assert [x["type"] for x in plan["regles"]] == ["plafond_quotidien", "plafond_total"]
    assert plan["regles"][0]["seuil_cents"] == 2000 and plan["regles"][1]["seuil_cents"] == 20000
    assert plan["ciblage"]["langues"] == ["fr-CA"] and plan["comptes_sas"] == [
        {"reseau": "facebook", "compte": "page-horizon"}
    ]


def test_l_empreinte_est_stable_et_change_avec_le_moindre_champ():
    plan, _ = normaliser(plan_brut())
    assert pl.empreinte(plan) == pl.empreinte(copy.deepcopy(plan)) and len(pl.empreinte(plan)) == 64
    autre, _ = normaliser(plan_brut(budget={**plan_brut()["budget"], "montant_total_cents": 19999}))
    assert pl.empreinte(autre) != pl.empreinte(plan)
    studio = StudioFictif({"visuel-1": "f" * 64})
    autre, _ = normaliser(plan_brut(), studio)
    assert pl.empreinte(autre) != pl.empreinte(plan), "l'empreinte d'un créatif fait partie de celle du plan"


def test_les_espaces_sont_normalises_dans_le_nom_et_les_textes():
    brut = plan_brut(nom="  Soumissions   automne ")
    plan, refus = normaliser(brut)
    assert refus == [] and plan["nom"] == "Soumissions automne"


def test_la_regle_de_cout_maximal_du_client_entre_dans_le_plan():
    brut = plan_brut(regles=[{"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5}])
    plan, refus = normaliser(brut)
    assert refus == [] and [x["type"] for x in plan["regles"]] == ["plafond_quotidien", "plafond_total", "cpa_max"]
    assert plan["regles"][2]["obligatoire"] is False and plan["regles"][2]["executee_par_opsys"] is False


# ======================================================================================================================
# refus nommés
# ======================================================================================================================
def modif(chemin, valeur):
    brut = plan_brut()
    cible = brut
    for cle in chemin[:-1]:
        cible = cible[cle]
    cible[chemin[-1]] = valeur
    return brut


def sans(chemin):
    brut = plan_brut()
    cible = brut
    for cle in chemin[:-1]:
        cible = cible[cle]
    del cible[chemin[-1]]
    return brut


B = ("budget",)
REFUS = [
    ("champ inconnu", {**plan_brut(), "extra": 1}, "REJ-PLAN-MEDIA-CHAMP"),
    ("champ manquant", sans(("objectif",)), "REJ-PLAN-MEDIA-CHAMP"),
    ("canal", modif(("canal",), "tiktok"), "REJ-PLAN-MEDIA-CHAMP"),
    ("objectif", modif(("objectif",), "notoriete"), "REJ-PLAN-MEDIA-CHAMP"),
    ("nom trop court", modif(("nom",), "ab"), "REJ-PLAN-MEDIA-CHAMP"),
    ("nom avec courriel", modif(("nom",), "Écrire à jean@example.test"), "REJ-PLAN-MEDIA-CHAMP"),
    ("budget flottant", modif((*B, "montant_total_cents"), 200.5), "REJ-PLAN-MEDIA-BUDGET"),
    ("budget booléen", modif((*B, "plafond_quotidien_cents"), True), "REJ-PLAN-MEDIA-BUDGET"),
    ("budget négatif", modif((*B, "montant_total_cents"), -1), "REJ-PLAN-MEDIA-BUDGET"),
    ("durée de 91 jours", modif((*B, "duree_jours"), 91), "REJ-PLAN-MEDIA-BUDGET"),
    ("durée de 0 jour", modif((*B, "duree_jours"), 0), "REJ-PLAN-MEDIA-BUDGET"),
    ("date illisible", modif((*B, "date_debut"), "10 novembre"), "REJ-PLAN-MEDIA-BUDGET"),
    ("champ de budget inconnu", modif((*B, "devise"), "USD"), "REJ-PLAN-MEDIA-CHAMP"),
    ("total au-delà du quotidien x durée", modif((*B, "montant_total_cents"), 20001), "REJ-PLAN-MEDIA-PLAFOND"),
    (
        "plafond dur quotidien",
        {
            **plan_brut(),
            "budget": {
                "montant_total_cents": 10002,
                "plafond_quotidien_cents": 5001,
                "duree_jours": 2,
                "date_debut": "2026-11-10",
            },
        },
        "REJ-PLAN-MEDIA-PLAFOND",
    ),
    (
        "plafond dur total",
        {
            **plan_brut(),
            "budget": {
                "montant_total_cents": 100001,
                "plafond_quotidien_cents": 5000,
                "duree_jours": 30,
                "date_debut": "2026-11-10",
            },
        },
        "REJ-PLAN-MEDIA-PLAFOND",
    ),
    ("début aujourd'hui", modif((*B, "date_debut"), "2026-11-01"), "REJ-PLAN-MEDIA-DEBUT-PASSE"),
    ("début passé", modif((*B, "date_debut"), "2026-10-01"), "REJ-PLAN-MEDIA-DEBUT-PASSE"),
    ("début au-delà de l'horizon", modif((*B, "date_debut"), "2027-01-01"), "REJ-PLAN-MEDIA-DEBUT-LOINTAIN"),
    ("zones vides", modif(("ciblage", "zones"), []), "REJ-PLAN-MEDIA-CHAMP"),
    ("trop de zones", modif(("ciblage", "zones"), [f"zone {i}" for i in range(21)]), "REJ-PLAN-MEDIA-CHAMP"),
    ("rayon hors bornes", modif(("ciblage", "rayon_km"), 101), "REJ-PLAN-MEDIA-CHAMP"),
    ("langue fr-CA absente", modif(("ciblage", "langues"), ["en-CA"]), "REJ-PLAN-MEDIA-FRANCAIS"),
    ("langue inconnue", modif(("ciblage", "langues"), ["fr-CA", "es-MX"]), "REJ-PLAN-MEDIA-FRANCAIS"),
    ("langue en double", modif(("ciblage", "langues"), ["fr-CA", "fr-CA"]), "REJ-PLAN-MEDIA-FRANCAIS"),
    ("champ de ciblage inconnu", modif(("ciblage", "audience"), "lookalike"), "REJ-PLAN-MEDIA-CHAMP"),
    ("mot-clé avec courriel", modif(("ciblage", "mots_cles"), ["écrire jean@example.test"]), "REJ-PLAN-MEDIA-PII"),
    ("mot-clé avec téléphone", modif(("ciblage", "mots_cles"), ["appeler 514-555-0123"]), "REJ-PLAN-MEDIA-PII"),
    ("trop de mots-clés", modif(("ciblage", "mots_cles"), [f"mot {i}" for i in range(31)]), "REJ-PLAN-MEDIA-CHAMP"),
    ("créatifs vides", modif(("creatifs",), []), "REJ-PLAN-MEDIA-CHAMP"),
    (
        "créatif non approuvé",
        modif(("creatifs", 0, "actif_id"), "visuel-inconnu"),
        "REJ-PLAN-MEDIA-CREATIF-NON-APPROUVE",
    ),
    ("créatif avec champ inconnu", modif(("creatifs", 0, "extra"), 1), "REJ-PLAN-MEDIA-CHAMP"),
    (
        "texte fr-CA absent",
        modif(
            ("creatifs", 0, "textes"),
            [{"langue": "en-CA", "titre": "Request a quote", "description": "An estimator will contact you."}],
        ),
        "REJ-PLAN-MEDIA-FRANCAIS",
    ),
    (
        "anglais plus long que le français",
        modif(
            ("creatifs", 0, "textes"),
            [
                {"langue": "fr-CA", "titre": "Demandez une soumission", "description": "Un estimateur vous contacte."},
                {
                    "langue": "en-CA",
                    "titre": "Request a detailed quote for your project today",
                    "description": "An estimator will contact you to plan a visit and explain the next steps in "
                                   "detail.",
                },
            ],
        ),
        "REJ-PLAN-MEDIA-FRANCAIS",
    ),
    (
        "deux textes fr-CA",
        modif(
            ("creatifs", 0, "textes"),
            [
                {"langue": "fr-CA", "titre": "Un titre", "description": "Une description."},
                {"langue": "fr-CA", "titre": "Un autre", "description": "Une autre."},
            ],
        ),
        "REJ-PLAN-MEDIA-CHAMP",
    ),
    ("titre trop long", modif(("creatifs", 0, "textes", 0, "titre"), "x" * 91), "REJ-PLAN-MEDIA-CHAMP"),
    ("description trop longue", modif(("creatifs", 0, "textes", 0, "description"), "x" * 301), "REJ-PLAN-MEDIA-CHAMP"),
    ("comptes_sas sur Google", {**plan_brut(), "canal": "google_ads"}, "REJ-PLAN-MEDIA-CHAMP"),
    (
        "compte sas hors facebook/instagram",
        modif(("comptes_sas",), [{"reseau": "tiktok", "compte": "x-compte"}]),
        "REJ-PLAN-MEDIA-CHAMP",
    ),
    ("utm hors convention", modif(("utm_campagne",), "Automne-2026"), "REJ-PLAN-MEDIA-CHAMP"),
    ("utm sans année", modif(("utm_campagne",), "contenu-automne"), "REJ-PLAN-MEDIA-CHAMP"),
    ("divulgation non booléenne", modif(("divulgation_texte_ia",), "oui"), "REJ-PLAN-MEDIA-CHAMP"),
    ("règle inconnue", modif(("regles",), [{"type": "pause_auto"}]), "REJ-PLAN-MEDIA-REGLE"),
    (
        "règle avec une action d'exécution",
        modif(
            ("regles",), [{"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5, "action": "mettre_en_pause"}]
        ),
        "REJ-PLAN-MEDIA-REGLE",
    ),
]


@pytest.mark.parametrize("nom, brut, code", REFUS, ids=[x[0] for x in REFUS])
def test_chaque_refus_est_nomme_et_rien_n_est_ecrit(nom, brut, code):
    journal: list = []
    resultat = composer(journal, brut)
    assert resultat["accepte"] is False and code in codes(resultat), resultat
    assert journal == []


def test_les_cas_limites_acceptes_de_part_et_d_autre_des_seuils():
    # le plus tôt : demain ; le plus loin : l'horizon de 60 jours ; durée 90 ; plafonds durs pile atteints
    for debut in ("2026-11-02", "2026-12-31"):
        _, refus = normaliser(modif((*B, "date_debut"), debut))
        assert refus == [], debut
    _, refus = normaliser(
        {
            **plan_brut(),
            "budget": {
                "montant_total_cents": 100000,
                "plafond_quotidien_cents": 5000,
                "duree_jours": 90,
                "date_debut": "2026-11-10",
            },
        }
    )
    assert refus == []
    _, refus = normaliser(
        {
            **plan_brut(),
            "budget": {
                "montant_total_cents": 5000,
                "plafond_quotidien_cents": 5000,
                "duree_jours": 1,
                "date_debut": "2026-11-10",
            },
        }
    )
    assert refus == []


def test_un_plafond_dur_plus_bas_de_la_politique_s_applique():
    petit = PolitiqueSas(plafond_budget_quotidien_cents=1000, plafond_budget_total_cents=5000)
    brut = plan_brut()
    plan, refus = pl.normaliser(brut, **{**controles(), "politique": petit})
    assert plan is None and codes({"refus": refus}).count("REJ-PLAN-MEDIA-PLAFOND") == 2
    assert POLITIQUE.plafond_budget_quotidien_cents == 5000


@pytest.mark.parametrize("critere", sorted(pl.CRITERES_INTERDITS))
def test_aucun_critere_protege_ne_peut_cibler(critere):
    brut = modif(("ciblage", critere), ["25-54"])
    plan, refus = normaliser(brut)
    assert plan is None and refus[0]["code"] == "REJ-PLAN-MEDIA-CIBLAGE-INTERDIT"
    assert critere in refus[0]["detail"]


def test_un_critere_interdit_est_reconnu_quelle_que_soit_la_casse():
    for cle in ("AGE", "Sexe", "Religion"):
        plan, refus = normaliser(modif(("ciblage", cle), "x"))
        assert plan is None and refus[0]["code"] == "REJ-PLAN-MEDIA-CIBLAGE-INTERDIT"


@pytest.mark.parametrize(
    "texte",
    [
        "À partir de 99 $ seulement",  # prix
        "Voyez https://exemple.test/offre",  # lien
        "Le meilleur service au Québec",  # exagération
        "Garantie à vie sur les travaux",  # garantie non validée
        "Appelez le 514-555-0123",  # coordonnées
    ],
)
def test_les_textes_passent_par_le_garde_fou_de_texte_du_socle(texte):
    for champ in ("titre", "description"):
        brut = modif(("creatifs", 0, "textes", 0, champ), texte)
        plan, refus = normaliser(brut)
        assert plan is None and refus, texte
        assert all(x["chemin"].endswith(f".{champ}") for x in refus), refus
        assert not any(x["code"].startswith("REJ-PLAN-MEDIA-") for x in refus), (
            "le code est celui du garde-fou du socle"
        )


def test_un_texte_propre_n_est_pas_refuse_par_le_garde_fou():
    _, refus = normaliser(plan_brut())
    assert refus == []


def test_un_concurrent_declare_dans_un_mot_cle_ou_un_texte_est_refuse_via_le_controle_de_marques():
    def controle(texte):
        return [f"marque d'un concurrent dans {texte!r}"] if "toitures zenith" in texte.lower() else []

    _, refus = normaliser(modif(("ciblage", "mots_cles"), ["toitures zenith laval"]), controle_marques=controle)
    assert codes({"refus": refus}) == ["REJ-PLAN-MEDIA-MARQUE-CONCURRENT"]
    assert refus[0]["chemin"] == "$.ciblage.mots_cles[0]"
    _, refus = normaliser(
        modif(("creatifs", 0, "textes", 0, "description"), "Mieux que Toitures Zenith sans doute."),
        controle_marques=controle,
    )
    assert "REJ-PLAN-MEDIA-MARQUE-CONCURRENT" in codes({"refus": refus})
    _, refus = normaliser(plan_brut(), controle_marques=controle)
    assert refus == []


# ======================================================================================================================
# cycle de vie
# ======================================================================================================================
def test_composer_cree_un_brouillon_idempotent_par_cle():
    journal: list = []
    cree = composer(journal)
    assert cree["accepte"] and cree["etat"] == "BROUILLON" and cree["revision"] == 1 and cree["deja_cree"] is False
    assert cree["plan_id"] == pl.identifiant("meta", CLE) and cree["plan_id"].startswith("plan-")
    assert len(cree["plan_id"]) == 5 + 16
    plan, _ = normaliser(plan_brut())
    assert cree["empreinte"] == pl.empreinte(plan)
    de_nouveau = composer(journal)
    assert de_nouveau["deja_cree"] is True and de_nouveau["plan_id"] == cree["plan_id"] and len(journal) == 1
    assert journal_chaine.verifier(journal) == []


def test_une_cle_reutilisee_avec_un_autre_contenu_est_refusee():
    journal: list = []
    composer(journal)
    resultat = composer(journal, plan_brut(nom="Un autre nom de plan"))
    assert codes(resultat) == ["REJ-PLAN-MEDIA-CLE-CONFLIT"] and len(journal) == 1


@pytest.mark.parametrize("cle", ["court", "x" * 15, "x" * 65, "cle avec espaces 0123456789", None, 12345678901234567])
def test_cle_d_idempotence_invalide(cle):
    journal: list = []
    assert codes(composer(journal, cle=cle)) == ["REJ-PLAN-MEDIA-CLE"] and journal == []


def test_deux_cles_donnent_deux_plans_et_le_canal_fait_partie_de_l_identite():
    journal: list = []
    a = composer(journal, cle="cle-numero-un-0123456789")
    b = composer(journal, cle="cle-numero-deux-0123456789")
    assert a["plan_id"] != b["plan_id"]
    assert pl.identifiant("meta", CLE) != pl.identifiant("google_ads", CLE)


def test_reviser_un_brouillon_incremente_la_revision_et_change_l_empreinte():
    journal: list = []
    cree = composer(journal)
    revise = composer(journal, plan_brut(nom="Soumissions automne bis"), plan_id=cree["plan_id"])
    assert revise["accepte"] and revise["revision"] == 2 and revise["etat"] == "BROUILLON"
    assert revise["empreinte"] != cree["empreinte"] and revise["deja_cree"] is False
    identique = composer(journal, plan_brut(nom="Soumissions automne bis"), plan_id=cree["plan_id"])
    assert identique["deja_cree"] is True and identique["revision"] == 2 and len(journal) == 2
    assert pl.lire(journal, cree["plan_id"])["plan"]["revision"] == 2


def test_reviser_un_plan_inconnu_ou_changer_son_canal_est_refuse():
    journal: list = []
    cree = composer(journal)
    assert codes(composer(journal, plan_id="plan-inconnu")) == ["REJ-PLAN-MEDIA-INCONNU"]
    google = plan_brut(canal="google_ads", comptes_sas=[])
    assert codes(composer(journal, google, plan_id=cree["plan_id"])) == ["REJ-PLAN-MEDIA-IDENTITE"]


def test_soumettre_passe_en_attente_et_la_soumission_repetee_est_idempotente():
    journal: list = []
    cree = composer(journal)
    ok = pl.soumettre(journal, cree["plan_id"], "agent", H, **controles())
    assert ok == {
        "accepte": True,
        "plan_id": cree["plan_id"],
        "etat": "PRET_POUR_APPROBATION",
        "empreinte": cree["empreinte"],
        "deja_soumis": False,
    }
    taille = len(journal)
    deja = pl.soumettre(journal, cree["plan_id"], "agent", H, **controles())
    assert deja["deja_soumis"] is True and len(journal) == taille
    assert codes(pl.soumettre(journal, "plan-inconnu", "agent", H, **controles())) == ["REJ-PLAN-MEDIA-INCONNU"]


def test_la_soumission_refait_tous_les_controles_a_l_instant_meme():
    journal: list = []
    studio = StudioFictif()
    cree = composer(journal, studio=studio)
    studio.revoquer("visuel-1")
    refus = pl.soumettre(journal, cree["plan_id"], "agent", H, **controles(studio))
    assert codes(refus) == ["REJ-PLAN-MEDIA-CREATIF-NON-APPROUVE"]
    assert pl.lire(journal, cree["plan_id"])["plan"]["etat"] == "BROUILLON"


def test_approuver_le_lancement_consigne_la_decision_sur_l_empreinte_exacte_et_n_execute_rien():
    journal: list = []
    plan_id, empreinte = pret(journal)
    ok = pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles())
    assert ok == {
        "accepte": True,
        "plan_id": plan_id,
        "etat": "LANCEMENT_APPROUVE_NON_EXECUTE",
        "empreinte": empreinte,
        "deja_approuve": False,
    }
    assert pl.APPROUVE == "LANCEMENT_APPROUVE_NON_EXECUTE"
    maillon = journal[-1]
    assert maillon["type"] == "plan_lancement_approuve" and maillon["niveau"] == 4 and maillon["decision"] == DECISION
    assert maillon["creatifs_verifies"] == [{"actif_id": "visuel-1", "empreinte_actif": "e" * 64}]
    lu = pl.lire(journal, plan_id)["plan"]
    assert lu["etat"] == "LANCEMENT_APPROUVE_NON_EXECUTE" and lu["executee_par_opsys"] is False
    assert "AUCUNE_DEPENSE_PAR_OPSYS" in lu["statut_lancement"] and lu["decision"] == DECISION
    assert journal_chaine.verifier(journal) == []


def test_approbation_repetee_idempotente_mais_une_autre_empreinte_est_refusee():
    journal: list = []
    plan_id, empreinte = pret(journal)
    pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles())
    taille = len(journal)
    assert pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles())["deja_approuve"] is True
    assert len(journal) == taille
    assert codes(pl.approuver_lancement(journal, plan_id, "0" * 64, DECISION, H, **controles())) == [
        "REJ-PLAN-MEDIA-EMPREINTE"
    ]


@pytest.mark.parametrize("empreinte", ["0" * 64, "abc", None, 12, ""])
def test_une_mauvaise_empreinte_n_approuve_rien(empreinte):
    journal: list = []
    plan_id, _ = pret(journal)
    assert codes(pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles())) == [
        "REJ-PLAN-MEDIA-EMPREINTE"
    ]
    assert pl.lire(journal, plan_id)["plan"]["etat"] == "PRET_POUR_APPROBATION"


def test_un_brouillon_non_soumis_ne_s_approuve_pas():
    journal: list = []
    cree = composer(journal)
    resultat = pl.approuver_lancement(journal, cree["plan_id"], cree["empreinte"], DECISION, H, **controles())
    assert (
        codes(resultat) == ["REJ-PLAN-MEDIA-ETAT"] and pl.lire(journal, cree["plan_id"])["plan"]["etat"] == "BROUILLON"
    )
    assert codes(pl.approuver_lancement(journal, "plan-inconnu", "0" * 64, DECISION, H, **controles())) == [
        "REJ-PLAN-MEDIA-INCONNU"
    ]


def test_reviser_un_plan_pret_le_renvoie_en_brouillon_et_l_ancienne_empreinte_ne_vaut_plus():
    journal: list = []
    plan_id, ancienne = pret(journal)
    revise = composer(journal, plan_brut(nom="Soumissions automne révisé"), plan_id=plan_id)
    assert revise["etat"] == "BROUILLON" and revise["empreinte"] != ancienne
    # en brouillon : refusé par l'état
    assert codes(pl.approuver_lancement(journal, plan_id, ancienne, DECISION, H, **controles())) == [
        "REJ-PLAN-MEDIA-ETAT"
    ]
    # soumis de nouveau : l'ANCIENNE empreinte est refusée, la nouvelle acceptée
    assert pl.soumettre(journal, plan_id, "agent", H, **controles())["accepte"]
    assert codes(pl.approuver_lancement(journal, plan_id, ancienne, DECISION, H, **controles())) == [
        "REJ-PLAN-MEDIA-EMPREINTE"
    ]
    assert pl.approuver_lancement(journal, plan_id, revise["empreinte"], DECISION, H, **controles())["accepte"]


def test_un_creatif_revoque_entre_la_soumission_et_la_decision_empeche_l_approbation():
    journal: list = []
    studio = StudioFictif()
    plan_id, empreinte = pret(journal, studio)
    studio.revoquer("visuel-1")
    resultat = pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles(studio))
    assert codes(resultat) == ["REJ-PLAN-MEDIA-CREATIF-NON-APPROUVE"]
    assert pl.lire(journal, plan_id)["plan"]["etat"] == "PRET_POUR_APPROBATION"
    assert not [m for m in journal if m["type"] == "plan_lancement_approuve"]


def test_un_creatif_modifie_depuis_la_redaction_change_l_empreinte_et_empeche_l_approbation():
    journal: list = []
    studio = StudioFictif()
    plan_id, empreinte = pret(journal, studio)
    studio.approuves["visuel-1"] = "f" * 64  # même identifiant, autre composition
    resultat = pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles(studio))
    assert codes(resultat) == ["REJ-PLAN-MEDIA-CREATIF-CHANGE"]
    assert pl.lire(journal, plan_id)["plan"]["etat"] == "PRET_POUR_APPROBATION"


def test_un_debut_devenu_passe_au_moment_de_la_decision_empeche_l_approbation():
    journal: list = []
    plan_id, empreinte = pret(journal)
    tard = MAINTENANT + timedelta(days=9)  # le 10 novembre : le début n'est plus « au moins demain »
    resultat = pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles(maintenant=tard))
    assert codes(resultat) == ["REJ-PLAN-MEDIA-DEBUT-PASSE"]
    veille = MAINTENANT + timedelta(days=8)  # le 9 novembre : le début est demain, encore valide
    assert pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles(maintenant=veille))["accepte"]


def test_un_concurrent_declare_apres_la_soumission_est_vu_a_la_decision():
    journal: list = []
    brut = plan_brut(ciblage={**plan_brut()["ciblage"], "mots_cles": ["toitures zenith"]})
    cree = composer(journal, brut)
    assert pl.soumettre(journal, cree["plan_id"], "agent", H, **controles())["accepte"]

    def controle(texte):
        return ["concurrent"] if "zenith" in texte.lower() else []

    refus = pl.approuver_lancement(
        journal, cree["plan_id"], cree["empreinte"], DECISION, H, **controles(controle_marques=controle)
    )
    assert "REJ-PLAN-MEDIA-MARQUE-CONCURRENT" in codes(refus)


def test_un_plan_approuve_ne_se_revise_plus_et_ne_se_resoumet_pas():
    journal: list = []
    plan_id, empreinte = pret(journal)
    pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles())
    assert codes(composer(journal, plan_brut(nom="Trop tard pour changer"), plan_id=plan_id)) == ["REJ-PLAN-MEDIA-ETAT"]
    assert codes(pl.soumettre(journal, plan_id, "agent", H, **controles())) == ["REJ-PLAN-MEDIA-ETAT"]


def test_retirer_est_idempotent_et_un_plan_retire_ne_se_revise_ni_ne_s_approuve():
    journal: list = []
    plan_id, empreinte = pret(journal)
    r1 = pl.retirer(journal, plan_id, "agent", "plus utile", H)
    assert r1 == {"accepte": True, "plan_id": plan_id, "etat": "RETIRE", "deja_retire": False, "avertissement": None}
    taille = len(journal)
    assert pl.retirer(journal, plan_id, "agent", "encore", H)["deja_retire"] is True and len(journal) == taille
    assert codes(composer(journal, plan_brut(nom="Retour du plan"), plan_id=plan_id)) == ["REJ-PLAN-MEDIA-ETAT"]
    assert codes(pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles())) == [
        "REJ-PLAN-MEDIA-ETAT"
    ]
    assert codes(pl.retirer(journal, "plan-inconnu", "agent", "x", H)) == ["REJ-PLAN-MEDIA-INCONNU"]


def test_retirer_un_plan_approuve_avertit_que_la_campagne_lancee_n_est_pas_rappelee():
    journal: list = []
    plan_id, empreinte = pret(journal)
    pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles())
    retire = pl.retirer(journal, plan_id, "agent", "annulé", H)
    assert retire["etat"] == "RETIRE" and "ne rappelle pas une campagne déjà lancée" in retire["avertissement"]


def test_le_motif_de_retrait_est_borne_a_300_caracteres():
    journal: list = []
    cree = composer(journal)
    pl.retirer(journal, cree["plan_id"], "agent", "m" * 500, H)
    assert len(journal[-1]["motif"]) == 300


# ---- lecture
# --------------------------------------------------------------------------------------------------------------
def test_lire_liste_filtre_par_etat_et_borne_la_liste():
    journal: list = []
    for i in range(3):
        composer(journal, plan_brut(nom=f"Plan numéro {i}"), cle=f"cle-lecture-numero-{i}-012345")
    pret(journal, cle="cle-pret-0123456789012", brut=plan_brut(nom="Plan prêt"))
    tous = pl.lire(journal)
    assert tous["total"] == 4 and len(tous["plans"]) == 4 and tous["reste"] == 0
    assert pl.lire(journal, etat="PRET_POUR_APPROBATION")["total"] == 1
    assert pl.lire(journal, etat="RETIRE") == {"accepte": True, "total": 0, "plans": [], "reste": 0}
    borne = pl.lire(journal, limite=2)
    assert len(borne["plans"]) == 2 and borne["reste"] == 2
    vue = tous["plans"][0]
    assert set(vue) == {"plan_id", "etat", "revision", "empreinte", "nom", "canal", "budget"}
    assert "plan" not in vue  # le détail (créatifs, ciblage) n'est rendu que pour un plan demandé
    assert codes(pl.lire(journal, "plan-inconnu")) == ["REJ-PLAN-MEDIA-INCONNU"]


# ---- journal altéré
# ------------------------------------------------------------------------------------------------------
def test_un_journal_altere_est_refuse_par_chaque_geste():
    journal: list = []
    plan_id, empreinte = pret(journal)
    journal[0] = {**journal[0], "plan": {**journal[0]["plan"], "nom": "Nom retouché à la main"}}
    assert journal_chaine.verifier(journal)
    c = controles()
    resultats = [
        pl.lire(journal),
        pl.lire(journal, plan_id),
        pl.composer(journal, plan_brut(), "cle-neuve-0123456789012", "agent", H, **c),
        pl.soumettre(journal, plan_id, "agent", H, **c),
        pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **c),
        pl.retirer(journal, plan_id, "agent", "x", H),
    ]
    for resultat in resultats:
        assert resultat["accepte"] is False and codes(resultat) == ["REJ-PLAN-MEDIA-JOURNAL-ALTERE"], resultat
    assert len(journal) == 2  # rien n'a été ajouté


def test_un_maillon_retire_au_milieu_ou_au_debut_est_detecte_mais_pas_la_troncature_de_la_queue():
    journal: list = []
    plan_id, empreinte = pret(journal)
    pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles())
    milieu = copy.deepcopy(journal)
    del milieu[1]
    assert codes(pl.lire(milieu)) == ["REJ-PLAN-MEDIA-JOURNAL-ALTERE"]
    debut = copy.deepcopy(journal)
    del debut[0]
    assert codes(pl.lire(debut)) == ["REJ-PLAN-MEDIA-JOURNAL-ALTERE"]
    # LIMITE assumée d'une chaîne de hachage : retirer le DERNIER maillon laisse une chaîne valide (plus courte) ; seule
    # une
    # copie externe de la tête de chaîne le révélerait. Le plan revient alors à l'état précédent, jamais à un état
    # inventé.
    queue = copy.deepcopy(journal)
    del queue[-1]
    assert journal_chaine.verifier(queue) == []
    assert pl.lire(queue, plan_id)["plan"]["etat"] == "PRET_POUR_APPROBATION"


# ---- dossier de lancement
# ----------------------------------------------------------------------------------------------
MEDIA = {
    "reference": "visuel-1-png",
    "type_media": "image",
    "format": "png",
    "sha256": "a" * 64,
    "octets": 1000,
    "largeur": 1200,
    "hauteur": 630,
    "realiste": False,
    "ia_generee": False,
}


def approuve(brut=None, studio=None):
    journal: list = []
    cree = composer(journal, brut, studio=studio)
    pl.soumettre(journal, cree["plan_id"], "agent", H, **controles(studio))
    pl.approuver_lancement(journal, cree["plan_id"], cree["empreinte"], DECISION, H, **controles(studio))
    etats, _ = pl.charger(journal)
    return etats[cree["plan_id"]]


def test_dossier_de_lancement_meta_etapes_manuelles_et_publication_d_annonce_payante_preparee():
    courant = approuve()
    dossier = pl.dossier_de_lancement(courant, {"visuel-1": MEDIA})
    etapes = " ".join(dossier["etapes_manuelles"])
    assert "Soumissions automne" in etapes and "20.00 $ CAD" in etapes and "200.00 $ CAD" in etapes
    assert "10 jours" in etapes and "2026-11-10" in etapes and "contenu-automne-2026" in etapes
    (publication,) = dossier["publications_sas_preparees"]
    assert publication["type_publication"] == "annonce_payante"
    assert publication["budget"] == {"montant_cents": 20000, "plafond_quotidien_cents": 2000, "duree_jours": 10}
    assert publication["reseau"] == "facebook" and publication["compte"] == "page-horizon"
    assert publication["planifie_le"] == "2026-11-10T13:00:00Z" and publication["medias"] == [MEDIA]
    assert publication["texte"] == "Un estimateur vous contacte pour planifier une visite."
    assert publication["divulgation"] == {
        "texte_ia": True,
        "media_synthetique_realiste": False,
        "contenu_commercial": True,
    }
    assert dossier["plan_id"] == courant.plan_id and dossier["empreinte"] == courant.empreinte
    assert "Rien n'a été lancé" in dossier["avertissement"]


def test_dossier_de_lancement_une_publication_par_compte_et_par_creatif_et_divulgation_du_media_realiste():
    brut = plan_brut(
        comptes_sas=[{"reseau": "facebook", "compte": "page-horizon"}, {"reseau": "instagram", "compte": "ig-horizon"}]
    )
    studio = StudioFictif({"visuel-1": "e" * 64})
    dossier = pl.dossier_de_lancement(approuve(brut, studio), {"visuel-1": {**MEDIA, "realiste": True}})
    assert [(p["reseau"], p["compte"]) for p in dossier["publications_sas_preparees"]] == [
        ("facebook", "page-horizon"),
        ("instagram", "ig-horizon"),
    ]
    assert all(p["divulgation"]["media_synthetique_realiste"] is True for p in dossier["publications_sas_preparees"])


def test_dossier_de_lancement_aucune_publication_pour_google_ads_ni_sans_media_resolu():
    google = plan_brut(canal="google_ads", comptes_sas=[])
    dossier = pl.dossier_de_lancement(approuve(google), {"visuel-1": MEDIA})
    assert dossier["publications_sas_preparees"] == []
    assert any("google_ads" in e for e in dossier["etapes_manuelles"])
    sans_media = pl.dossier_de_lancement(approuve(), {})
    assert sans_media["publications_sas_preparees"] == []


def test_dossier_de_lancement_regles_preparees_jamais_executees():
    brut = plan_brut(regles=[{"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5}])
    dossier = pl.dossier_de_lancement(approuve(brut), {"visuel-1": MEDIA})
    assert [x["type"] for x in dossier["regles_preparees"]] == ["plafond_quotidien", "plafond_total", "cpa_max"]
    for regle in dossier["regles_preparees"]:
        assert regle["executee_par_opsys"] is False and regle["action"] == "proposer_pause"
        assert "statut" not in regle


def test_un_plan_avec_une_regle_supplementaire_survit_a_la_revalidation_de_la_soumission_et_de_la_decision():
    journal: list = []
    brut = plan_brut(
        regles=[
            {"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5},
            {"type": "depense_sans_conversion", "seuil_cents": 3000, "fenetre_jours": 3},
            {"type": "saut_depense", "ratio_pct": 300, "minimum_cents": 2500},
        ]
    )
    plan_id, empreinte = pret(journal, brut=brut)
    assert pl.approuver_lancement(journal, plan_id, empreinte, DECISION, H, **controles())["accepte"]


@pytest.mark.parametrize(
    "nom, brut",
    [
        ("créatif en double", modif(("creatifs",), [plan_brut()["creatifs"][0], plan_brut()["creatifs"][0]])),
        (
            "compte du sas en double",
            modif(
                ("comptes_sas",),
                [{"reseau": "facebook", "compte": "page-horizon"}, {"reseau": "facebook", "compte": "page-horizon"}],
            ),
        ),
        ("mot-clé en double", modif(("ciblage", "mots_cles"), ["soumission travaux", "Soumission  travaux"])),
        ("zone en double", modif(("ciblage", "zones"), ["Laval", "laval"])),
        ("nom avec retour de ligne", modif(("nom",), "Soumissions\nautomne")),
    ],
)
def test_les_doublons_sont_refuses_car_ils_dupliqueraient_des_publications_ou_des_depenses(nom, brut):
    plan, refus = normaliser(brut)
    assert plan is None and refus, nom
