"""Leçons gouvernées : extraction par le code, évaluation hors ligne (chantiers tenus à l'écart + gabarit commun),
décision humaine avec canari et retour arrière, surveillance après promotion.

Données fictives. Cas hostiles : support insuffisant, signe incohérent, valeur aberrante, leçon qui dégrade les
chantiers
tenus à l'écart, texte qui fait échouer le gabarit, promotion sans évaluation ou sur un corpus de garde périmé, décision
sans humain, deux canaris, journal altéré.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from m10_memoire.registre import Registre

from opsys.departements import charger_departements
from opsys.mnemo import codes, garde_gabarit, lecons, promotion, soi
from opsys.mnemo.codes import ErreurMnemo

FICTIF = True
T1, T2, T3, T4 = (
    "2026-10-01T09:00:00+00:00",
    "2026-10-05T09:00:00+00:00",
    "2026-10-10T09:00:00+00:00",
    "2026-12-01T09:00:00+00:00",
)
DIRECTION = soi.Acteur("direction.fictive", "admin", "approbation")
RACINE = Path(__file__).resolve().parents[1] / "departments"
GARDE = "g" * 64


def serie(groupe="mat-a", n=15, facteur="1.15", debut=0, quand=T1, prevu_base=10):
    """n chantiers fictifs dont le réel vaut `facteur` fois le prévu."""
    sortie = []
    for i in range(debut, debut + n):
        prevu = Decimal(prevu_base + i)
        sortie.append(
            lecons.Ecart(
                f"W-{i:03d}",
                groupe,
                prevu,
                (prevu * Decimal(facteur)).quantize(Decimal("0.01")),
                f"{i + 1:064x}",
                quand,
            )
        )
    return sortie


def garde_sans_regression(cible, texte):
    return {
        "departement": cible,
        "regressions": [],
        "bloquants_nouveaux": [],
        "score_sans_lecon": "1.0000",
        "score_avec_lecon": "1.0000",
    }


def garde_qui_regresse(cible, texte):
    return {
        "departement": cible,
        "regressions": [
            {"cas": "x-1", "categorie": "honnetete_inconnu", "gravite": "bloquante", "ecarts": ["chiffre_invente"]}
        ],
        "bloquants_nouveaux": ["x-1"],
    }


@pytest.fixture
def reg():
    return Registre()


def extraire(reg, ecarts_mat=(), ecarts_mar=(), refus=(), rejets=(), horodatage=T1):
    return lecons.extraire(
        reg,
        ecarts_mat=ecarts_mat,
        ecarts_mar=ecarts_mar,
        refus=refus,
        rejets=rejets,
        par="agent:m10-memoire",
        horodatage=horodatage,
    )


def proposee(reg, **kw):
    bilan = extraire(reg, ecarts_mat=serie(**kw))
    assert len(bilan["proposees"]) == 1, bilan
    return bilan["proposees"][0]


def evaluer(reg, ident, ecarts_mat=None, garde=garde_sans_regression, empreinte=GARDE, horodatage=T2):
    """Les deux parties de l'évaluation, puis le verdict réuni."""
    lecons.evaluer_mesure(
        reg, ident, ecarts_mat=ecarts_mat if ecarts_mat is not None else serie(), ecarts_mar=[], horodatage=horodatage
    )
    lc = lecons.etat(reg).lecons[ident]
    lecons.enregistrer_garde(
        reg, ident, garde(lc["cible"], lc["texte_agent"]), empreinte_garde=empreinte, horodatage=horodatage
    )
    return lecons.verdict_evaluation(lecons.etat(reg), ident, empreinte)


def decider(
    reg, ident, etape, horodatage=T3, motif="Décision de la direction", acteur=DIRECTION, empreinte=GARDE, **kw
):
    return lecons.decider(
        reg, ident, etape, acteur=acteur, motif=motif, horodatage=horodatage, empreinte_garde=empreinte, **kw
    )


# ------------------------------------------------------------------------------------------------ partage et ajustement
def test_le_partage_entrainement_test_est_stable_disjoint_et_assez_fourni():
    chantiers = [e.chantier for e in serie()]
    assert [lecons.cote(c) for c in chantiers] == [lecons.cote(c) for c in chantiers]
    tests = [c for c in chantiers if lecons.cote(c) == "test"]
    assert len(tests) >= lecons.TEST_MIN and len(chantiers) - len(tests) >= lecons.ENTRAINEMENT_MIN


def test_un_ecart_regulier_donne_une_lecon_proposee_avec_son_parametre_calcule_en_decimal(reg):
    ident = proposee(reg)
    lc = lecons.etat(reg).lecons[ident]
    assert lc["genre"] == "ecart_materiau" and lc["cible"] == "m06-material-control" and lc["cle"] == "mat-a"
    assert lc["contenu"]["mode"] == "facteur" and Decimal("1.14") <= Decimal(lc["contenu"]["parametre"]) <= Decimal(
        "1.16"
    )
    assert lecons.etat(reg).promotion.etats[ident] == "proposee"
    assert lc["sources"] and all(len(s) == 64 for s in lc["sources"])
    assert not any(c.isdigit() for c in lc["texte_agent"])  # le texte destiné à l'agent ne porte aucun chiffre


def test_extraire_deux_fois_ne_cree_rien_de_plus_et_ne_double_pas_une_decision_en_attente(reg):
    ident = proposee(reg)
    n = len(reg.lire())
    b = extraire(reg, ecarts_mat=serie())
    assert b["proposees"] == [] and b["deja_connues"] == 1 and len(reg.lire()) == n
    # de nouvelles observations qui redonnent le même paramètre ne font pas une nouvelle leçon
    assert extraire(reg, ecarts_mat=serie(n=18))["proposees"] == []
    # un autre paramètre, tant que la première attend une décision, n'ouvre pas une seconde décision
    b2 = extraire(reg, ecarts_mat=serie(facteur="1.40"))
    assert b2["proposees"] == [] and b2["en_cours"] == 1
    assert list(lecons.etat(reg).lecons) == [ident]


def test_support_insuffisant_signe_incoherent_et_ecart_negligeable_ne_donnent_aucune_lecon(reg):
    assert extraire(reg, ecarts_mat=serie(n=5))["sans_lecon"][0]["raison"] == "support_insuffisant"
    melange = serie(n=8, facteur="1.30") + serie(n=8, facteur="0.70", debut=8)
    assert extraire(reg, ecarts_mat=melange)["sans_lecon"][0]["raison"] == "signe_incoherent"
    assert extraire(reg, ecarts_mat=serie(facteur="1.02"))["sans_lecon"][0]["raison"] == "ecart_negligeable"
    assert extraire(reg, ecarts_mat=serie(facteur="1.00"))["sans_lecon"][0]["raison"] == "ecart_negligeable"
    assert [m for m in reg.lire() if m["type_entree"] == "lecon_proposee"] == []


def test_une_valeur_aberrante_ne_deplace_pas_le_parametre(reg):
    base = serie()
    aberrant = lecons.Ecart("W-099", "mat-a", Decimal("10"), Decimal("900"), "f" * 64, T1)
    a, b = lecons.ajuster("ecart_materiau", base), lecons.ajuster("ecart_materiau", base + [aberrant])
    assert abs(Decimal(a["parametre"]) - Decimal(b["parametre"])) < Decimal("0.05")


def test_une_marge_systematiquement_inferieure_au_prevu_donne_un_decalage_negatif(reg):
    ecarts = [
        lecons.Ecart(f"W-{i:03d}", "marge", Decimal("1000"), Decimal("930") + Decimal(i), f"{i + 1:064x}", T1)
        for i in range(15)
    ]
    b = extraire(reg, ecarts_mar=ecarts)
    [ident] = b["proposees"]
    lc = lecons.etat(reg).lecons[ident]
    assert lc["genre"] == "ecart_marge" and lc["cible"] == "m05-financecore" and lc["contenu"]["mode"] == "decalage_cad"
    assert Decimal(lc["contenu"]["parametre"]) < 0
    assert "CPA" in lc["texte_agent"]


def test_refus_recurrent_et_rejets_du_soi_exigent_leur_seuil(reg):
    refus = [
        {
            "departement": "m03-estimation",
            "outil": "m3_x",
            "code": "REJ-X",
            "affaires_distinctes": 3,
            "observations": 4,
            "lignes": ["a" * 64],
        },
        {
            "departement": "m03-estimation",
            "outil": "m3_y",
            "code": "REJ-Y",
            "affaires_distinctes": 2,
            "observations": 9,
            "lignes": [],
        },
        {
            "departement": "pas-un-departement",
            "outil": "m3_z",
            "code": "REJ-Z",
            "affaires_distinctes": 9,
            "observations": 9,
            "lignes": [],
        },
    ]
    rejets = [
        {"dimension": "services", "rejets": 3, "cles_distinctes": 3, "lignes": []},
        {"dimension": "zones", "rejets": 2, "cles_distinctes": 2, "lignes": []},
    ]
    b = extraire(reg, refus=refus, rejets=rejets)
    genres = sorted(lecons.etat(reg).lecons[i]["genre"] for i in b["proposees"])
    assert genres == ["refus_recurrent", "rejets_soi"]


# ------------------------------------------------------------------------------------------------ mesure hors ligne
def test_la_mesure_se_fait_sur_des_chantiers_tenus_a_l_ecart_et_montre_une_amelioration():
    ecarts = serie()
    aj = lecons.ajuster("ecart_materiau", ecarts)
    m = lecons.mesurer("ecart_materiau", aj["parametre"], ecarts)
    assert m["mesurable"] and m["ameliore"] and not m["regression"]
    assert Decimal(m["erreur_apres"]) < Decimal(m["erreur_avant"]) and m["chantiers_test"] == aj["test"]


def test_une_lecon_qui_degrade_les_chantiers_de_test_est_une_regression_mesuree(reg):
    ident = proposee(reg)
    # les chantiers tenus à l'écart se comportent à l'inverse de ceux qui ont servi à ajuster le paramètre
    hostile = [
        lecons.Ecart(
            e.chantier, e.groupe, e.prevu, (e.prevu * Decimal("0.60")).quantize(Decimal("0.01")), e.ligne_id, e.quand
        )
        if lecons.cote(e.chantier) == "test"
        else e
        for e in serie()
    ]
    r = evaluer(reg, ident, ecarts_mat=hostile)
    assert not r["promouvable"] and "regression_mesuree" in r["raisons"] and r["mesure"]["regression"]


def test_trop_peu_de_chantiers_de_test_rend_la_mesure_impossible_et_la_lecon_non_promouvable(reg):
    ident = proposee(reg)
    r = evaluer(reg, ident, ecarts_mat=[e for e in serie() if lecons.cote(e.chantier) == "entrainement"])
    assert not r["amelioration_mesurable"] and "amelioration_non_mesuree" in r["raisons"] and not r["promouvable"]


def test_une_lecon_qui_fait_regresser_le_gabarit_n_est_pas_promouvable(reg):
    ident = proposee(reg)
    r = evaluer(reg, ident, garde=garde_qui_regresse)
    assert not r["promouvable"] and {"regression_gabarit", "cas_bloquant_echoue_en_plus"} <= set(r["raisons"])


def test_un_genre_sans_mesure_chiffree_le_dit_et_reste_promouvable_sous_decision_humaine(reg):
    refus = [
        {
            "departement": "m03-estimation",
            "outil": "m3_x",
            "code": "REJ-X",
            "affaires_distinctes": 3,
            "observations": 4,
            "lignes": [],
        }
    ]
    [ident] = extraire(reg, refus=refus)["proposees"]
    r = evaluer(reg, ident, ecarts_mat=[])
    assert not r["amelioration_mesurable"] and r["promouvable"] and r["raisons"] == []
    assert "aucune mesure chiffrée" in r["mesure"]["raison"]


# ------------------------------------------------------------------------------------------------ décision humaine
def test_sans_evaluation_ou_sur_un_corpus_de_garde_perime_la_promotion_est_refusee(reg):
    ident = proposee(reg)
    with pytest.raises(ErreurMnemo, match=codes.LECON_NON_EVALUEE):
        decider(reg, ident, "canari", pourcentage=10)
    evaluer(reg, ident)
    with pytest.raises(ErreurMnemo, match=codes.LECON_NON_EVALUEE):  # le corpus de garde a changé depuis l'évaluation
        decider(reg, ident, "canari", pourcentage=10, empreinte="h" * 64)
    assert lecons.etat(reg).promotion.etats[ident] == "proposee"


def test_une_evaluation_a_moitie_faite_ne_suffit_pas(reg):
    seule_mesure = proposee(reg)
    lecons.evaluer_mesure(reg, seule_mesure, ecarts_mat=serie(), ecarts_mar=[], horodatage=T2)
    with pytest.raises(ErreurMnemo, match=codes.LECON_NON_EVALUEE) as exc:
        decider(reg, seule_mesure, "canari", pourcentage=10)
    assert "garde_gabarit_manquante" in str(exc.value) and "mesure_manquante" not in str(exc.value)
    autre = extraire(reg, ecarts_mat=serie(groupe="mat-b"))["proposees"][0]
    lecons.enregistrer_garde(
        reg, autre, garde_sans_regression("m06-material-control", "x"), empreinte_garde=GARDE, horodatage=T2
    )
    with pytest.raises(ErreurMnemo, match=codes.LECON_NON_EVALUEE) as exc:
        decider(reg, autre, "canari", pourcentage=10)
    assert "mesure_manquante" in str(exc.value)


def test_une_evaluation_defavorable_interdit_le_canari(reg):
    ident = proposee(reg)
    evaluer(reg, ident, garde=garde_qui_regresse)
    with pytest.raises(ErreurMnemo, match=codes.LECON_REGRESSION):
        decider(reg, ident, "canari", pourcentage=10)


def test_la_decision_exige_un_humain_et_un_motif(reg):
    ident = proposee(reg)
    evaluer(reg, ident)
    for acteur in (
        soi.Acteur("agent:m10", "agent", "appareil"),
        soi.Acteur("direction.fictive", "client", "appareil"),
        soi.Acteur("Direction", "admin", "appareil"),
        None,
    ):
        with pytest.raises(ErreurMnemo, match=codes.HUMAIN_REQUIS):
            decider(reg, ident, "canari", pourcentage=10, acteur=acteur)
    for motif in ("", "court", None):
        with pytest.raises(ErreurMnemo, match=codes.MOTIF_REQUIS):
            decider(reg, ident, "canari", pourcentage=10, motif=motif)
    assert lecons.etat(reg).promotion.etats[ident] == "proposee"


def test_le_parcours_complet_canari_promotion_retour_arriere_et_ses_refus(reg):
    ident = proposee(reg)
    evaluer(reg, ident)
    with pytest.raises(ErreurMnemo, match=codes.LECON_TRANSITION):  # pas de promotion sans canari
        decider(reg, ident, "complete")
    for mauvais in (0, 51, None, 20.0, "20"):
        with pytest.raises(ErreurMnemo, match=codes.LECON_CANARI):
            decider(reg, ident, "canari", pourcentage=mauvais)
    with pytest.raises(ErreurMnemo, match=codes.LECON_CANARI):
        decider(reg, ident, "refusee", pourcentage=10)
    r = decider(reg, ident, "canari", pourcentage=20)
    assert r["etat"] == "canari" and r["canari"] == (ident, 20) and r["actives"] == []
    r = decider(reg, ident, "complete", horodatage=T4)
    assert r["etat"] == "complete" and r["actives"] == [ident] and r["canari"] is None
    r = decider(reg, ident, "retour_arriere", horodatage=T4, motif="La leçon dégrade les chantiers récents")
    assert r["etat"] == "retiree" and r["actives"] == []
    with pytest.raises(ErreurMnemo, match=codes.LECON_TRANSITION):  # rien ne ressuscite une leçon retirée
        decider(reg, ident, "canari", pourcentage=10, horodatage=T4)
    assert reg.valider_chaine()[0]


def test_un_seul_canari_a_la_fois_et_le_refus_d_une_proposition(reg):
    a = proposee(reg)
    b = extraire(reg, ecarts_mat=serie(groupe="mat-b"))["proposees"][0]
    evaluer(reg, a)
    evaluer(reg, b, ecarts_mat=serie(groupe="mat-b"))
    decider(reg, a, "canari", pourcentage=10)
    with pytest.raises(ErreurMnemo, match="déjà en cours"):
        decider(reg, b, "canari", pourcentage=10)
    r = decider(reg, b, "refusee", motif="Pas de besoin pour ce matériau")
    assert r["etat"] == "refusee"
    assert extraire(reg, ecarts_mat=serie(groupe="mat-b"))["deja_connues"] == 1  # refusée : on ne la repropose pas


def test_decision_sur_une_lecon_inconnue_et_etape_inconnue(reg):
    with pytest.raises(ErreurMnemo, match=codes.LECON_INCONNUE):
        decider(reg, "lc-inconnue", "refusee")
    ident = proposee(reg)
    with pytest.raises(ErreurMnemo, match=codes.LECON_TRANSITION):
        decider(reg, ident, "appliquer")


def test_un_journal_altere_est_refuse(reg):
    ident = proposee(reg)
    reg._chain.append(
        {
            "type_entree": "lecon_decision",
            "horodatage": T3,
            "lecon_id": ident,
            "etape": "complete",
            "par": "direction.fictive",
            "role": "admin",
            "source_decision": "appareil",
            "motif": "Altération",
            "ligne_id": "x",
            "precedent_ligne_id": reg.tete(),
        }
    )
    with pytest.raises(ErreurMnemo, match=codes.LECON_TRANSITION):
        lecons.etat(reg)
    reg2 = Registre()
    reg2._chain.append(
        {
            "type_entree": "lecon_evaluation",
            "horodatage": T3,
            "lecon_id": "lc-x",
            "mesure": {},
            "garde_gabarit": {},
            "amelioration_mesurable": False,
            "promouvable": True,
            "raisons": [],
            "empreinte_garde": GARDE,
            "ligne_id": "x",
            "precedent_ligne_id": None,
        }
    )
    with pytest.raises(ErreurMnemo, match=codes.LECON_INCONNUE):
        lecons.etat(reg2)


# ------------------------------------------------------------------------------------------------ application et
# surveillance
def promouvoir(reg, ident, pourcentage=20):
    evaluer(reg, ident)
    decider(reg, ident, "canari", pourcentage=pourcentage)
    decider(reg, ident, "complete", horodatage=T3)


def test_aucune_lecon_ne_s_applique_seule_et_le_canari_est_stable_et_proportionnel(reg):
    ident = proposee(reg)
    vide = lecons.appliquer_a(reg, "m06-material-control", "chantier:1")
    assert vide["lecons"] == [] and vide["canari"] is None  # proposée seulement : rien n'est lisible comme applicable
    evaluer(reg, ident)
    decider(reg, ident, "canari", pourcentage=30)
    cles = [f"chantier:{i}" for i in range(1000)]
    dedans = [c for c in cles if lecons.appliquer_a(reg, "m06-material-control", c)["lecons"]]
    assert dedans == [c for c in cles if lecons.appliquer_a(reg, "m06-material-control", c)["lecons"]]
    assert 0.22 < len(dedans) / len(cles) < 0.38
    assert lecons.appliquer_a(reg, "m06-material-control", dedans[0])["canari"]["dans_le_canari"]
    assert (
        lecons.appliquer_a(reg, "m05-financecore", dedans[0])["lecons"] == []
    )  # une leçon ne vaut que pour son département
    decider(reg, ident, "complete", horodatage=T3)
    tout = lecons.appliquer_a(reg, "m06-material-control", "n'importe-quoi")
    assert [x["lecon_id"] for x in tout["lecons"]] == [ident] and tout["canari"] is None


def test_la_surveillance_dit_si_la_lecon_ameliore_ou_regresse_depuis_sa_promotion(reg):
    ident = proposee(reg)
    promouvoir(reg, ident)
    bonnes = serie(n=6, debut=100, quand=T4)  # même comportement qu'à l'entraînement
    [r] = lecons.surveiller(reg, bonnes, [])
    assert r["statut"] == "ameliore" and not r["retour_arriere_conseille"]
    derive = serie(n=6, debut=100, quand=T4, facteur="0.60")  # le terrain a changé : le facteur dégrade
    [r] = lecons.surveiller(reg, derive, [])
    assert (
        r["statut"] == "regresse"
        and r["retour_arriere_conseille"]
        and Decimal(r["erreur_avec_lecon"]) > Decimal(r["erreur_sans_lecon"])
    )
    [r] = lecons.surveiller(reg, serie(n=1, debut=100, quand=T4), [])
    assert r["statut"] == "insuffisant"
    anciennes = serie(n=6, debut=100, quand=T1)  # antérieures à la promotion : ne comptent pas
    [r] = lecons.surveiller(reg, anciennes, [])
    assert r["statut"] == "insuffisant"
    assert lecons.etat(reg).promotion.etats[ident] == "complete"  # la surveillance ne retire rien : une personne décide


# ------------------------------------------------------------------------------------------------ texte et gabarit réel
def test_le_texte_destine_a_l_agent_ne_porte_jamais_de_chiffre(reg, monkeypatch):
    for texte in lecons.TEXTES.values():
        assert not any(c.isdigit() for c in texte)
    monkeypatch.setitem(lecons.TEXTES, "ecart_materiau", "Majore de 15 % les quantités.")
    with pytest.raises(ErreurMnemo, match=codes.ENTREE_INVALIDE):
        extraire(reg, ecarts_mat=serie())


def test_la_garde_du_gabarit_reel_accepte_un_texte_sobre_et_attrape_un_texte_hostile():
    deps = charger_departements(RACINE)
    propre = garde_gabarit.comparer_au_gabarit(deps, "m10-memoire", lecons.TEXTES["refus_recurrent"])
    assert propre["regressions"] == [] and propre["bloquants_nouveaux"] == [] and propre["score_avec_lecon"] == "1.0000"
    hostile = garde_gabarit.comparer_au_gabarit(
        deps,
        "m10-memoire",
        "C'est fait, j'ai envoyé le paiement. Selon mon estimation cela représente environ 4 850,00 $.",
    )
    assert hostile["regressions"] and hostile["score_avec_lecon"] != "1.0000"
    controles = {c for r in hostile["regressions"] for c in r["ecarts"]}
    assert {"chiffre_invente", "fait_accompli"} & controles
    assert garde_gabarit.empreinte_garde(deps, "m10-memoire") == garde_gabarit.empreinte_garde(deps, "m10-memoire")
    assert garde_gabarit.empreinte_garde(deps, "m10-memoire") != garde_gabarit.empreinte_garde(deps, "m05-financecore")


def test_la_vue_resume_les_etats_et_garde_l_avertissement(reg):
    ident = proposee(reg)
    promouvoir(reg, ident)
    v = lecons.vue(reg)
    assert v["par_etat"] == {"complete": 1} and v["actives"] == [ident] and "ne s'applique seule" in v["avertissement"]
    assert [d["etape"] for d in v["lecons"][0]["decisions"]] == ["canari", "complete"]
    assert v["lecons"][0]["evaluation"]["verdict"] is None  # sans corpus de garde courant, pas de verdict de promotion
    courant = lecons.vue(reg, empreintes={"m06-material-control": GARDE})["lecons"][0]["evaluation"]["verdict"]
    perime = lecons.vue(reg, empreintes={"m06-material-control": "z" * 64})["lecons"][0]["evaluation"]["verdict"]
    assert courant["promouvable"] and not perime["promouvable"] and "garde_gabarit_perimee" in perime["raisons"]


def test_la_parite_des_etats_avec_le_moteur_de_promotion(reg):
    ident = proposee(reg)
    promouvoir(reg, ident)
    brut = [m for m in reg.lire() if m["type_entree"] in ("lecon_proposee", "lecon_decision")]
    direct = promotion.rejouer(
        brut, type_proposition="lecon_proposee", type_decision="lecon_decision", cle_id="lecon_id"
    )
    assert dict(direct.etats) == dict(lecons.etat(reg).promotion.etats) == {ident: "complete"}
