"""Leçons gouvernées : extraction par le code, évaluation hors ligne (chantiers tenus à l'écart + gabarit commun),
décision humaine avec canari et retour arrière, surveillance après promotion.

Données fictives. Cas hostiles : support insuffisant, signe incohérent, valeur aberrante, leçon qui dégrade les
chantiers
tenus à l'écart, texte qui fait échouer le gabarit, promotion sans évaluation ou sur un corpus de garde périmé, décision
sans humain, deux canaris, journal altéré.
"""

from __future__ import annotations

import dataclasses
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


def serie(groupe="mat-a", n=15, facteur="1.15", debut=0, quand=T1, prevu_base=10, unite="u"):
    """n chantiers fictifs dont le réel vaut `facteur` fois le prévu, dans une cohorte d'unité déclarée."""
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
                unite,
            )
        )
    return sortie


def serie_marge(n=15, debut=0, quand=T1, reel_base=930):
    """n chantiers fictifs dont la marge réelle est sous la marge prévue."""
    return [
        lecons.Ecart(
            f"W-{i:03d}",
            "marge",
            Decimal("1000"),
            Decimal(reel_base) + Decimal(i),
            f"{i + 1:064x}",
            quand,
        )
        for i in range(debut, debut + n)
    ]


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


def evaluer(reg, ident, ecarts_mat=None, ecarts_mar=None, garde=garde_sans_regression, empreinte=GARDE, horodatage=T2):
    """Les deux parties de l'évaluation, puis le verdict réuni."""
    lecons.evaluer_mesure(
        reg,
        ident,
        ecarts_mat=ecarts_mat if ecarts_mat is not None else serie(),
        ecarts_mar=ecarts_mar if ecarts_mar is not None else [],
        horodatage=horodatage,
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


def historique(reg, *, unite=None, groupe="mat-a", parametre="1.15", etat="proposee"):
    """Écrit une leçon telle qu'un journal ANTÉRIEUR à l'unité peut en contenir (aucune migration)."""
    contenu = {"parametre": parametre, "mode": "facteur", "chantiers": 15, "coherence": "0.9000"}
    if unite is not None:
        contenu["unite"] = unite
    identite = {"parametre": parametre}
    if unite is not None:
        identite["unite"] = unite
    ident = lecons.lecon_id("ecart_materiau", "m06-material-control", groupe, identite)
    reg.ajouter(
        {
            "type_entree": lecons.TYPE_PROPOSEE,
            "horodatage": T1,
            "lecon_id": ident,
            "genre": "ecart_materiau",
            "cible": "m06-material-control",
            "cle": groupe,
            "contenu": contenu,
            "libelle": "Leçon historique fictive.",
            "texte_agent": lecons.TEXTES["ecart_materiau"],
            "sources": ["a" * 64],
            "propose_par": "m10-memoire",
        }
    )
    if etat in ("canari", "complete"):
        reg.ajouter(
            {
                "type_entree": lecons.TYPE_DECISION,
                "horodatage": T2,
                "lecon_id": ident,
                "etape": "canari",
                "par": "direction.fictive",
                "role": "admin",
                "source_decision": "cli",
                "motif": "Canari historique fictif.",
                "pourcentage": 50,
            }
        )
    if etat == "complete":
        reg.ajouter(
            {
                "type_entree": lecons.TYPE_DECISION,
                "horodatage": T3,
                "lecon_id": ident,
                "etape": "complete",
                "par": "direction.fictive",
                "role": "admin",
                "source_decision": "cli",
                "motif": "Promotion historique fictive.",
            }
        )
    return ident


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
    assert lc["contenu"]["unite"] == "u"
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


def test_l_extraction_retient_l_unite_exacte_non_vide_et_ignore_les_lignes_sans_unite(reg):
    def maillon(wct, unite, prevu="10", reel="12"):
        return {
            "statut_variance": "evaluee",
            "wct_id": wct,
            "ligne_id": f"{wct:0>64}"[:64],
            "horodatage": T1,
            "lignes": [
                {
                    "materiau": "mat-a",
                    "unite": unite,
                    "quantite_prevue": prevu,
                    "quantite_reelle": reel,
                }
            ],
        }

    ecarts = lecons.ecarts_materiaux(
        [
            maillon("W-1", "pi"),
            maillon("W-2", ""),
            maillon("W-3", None),
            maillon("W-4", "  "),
            maillon("W-5", " pi "),
        ]
    )
    assert [e.unite for e in ecarts] == ["pi", " pi "]  # aucune conversion, aucun synonyme, aucun strip
    assert [e.chantier for e in ecarts] == ["W-1", "W-5"]


@pytest.mark.parametrize("unite", [None, "", " \t ", 7, ("pi",), ["pi"], {"unite": "pi"}])
def test_extraire_refuse_unite_blanche_ou_non_textuelle_sans_ecrire_de_lecon(reg, unite):
    bilan = extraire(reg, ecarts_mat=serie(unite=unite))

    assert bilan["proposees"] == []
    assert bilan["sans_lecon"] == [
        {"genre": "ecart_materiau", "cle": "mat-a", "raison": "unite_absente"}
    ]
    assert not any(m.get("type_entree") == lecons.TYPE_PROPOSEE for m in reg.lire())


def test_extraire_valide_les_unites_avant_groupement_et_garde_les_textes_exacts(reg):
    observations = (
        serie(n=15, debut=0, unite="pi")
        + serie(n=15, debut=20, unite=" pi ")
        + serie(n=15, debut=40, unite="pi2")
        + serie(n=15, debut=60, unite=["pi"])
        + serie(n=15, debut=80, unite="   ")
    )

    bilan = extraire(reg, ecarts_mat=observations)
    lessons = lecons.etat(reg).lecons

    assert len(bilan["proposees"]) == 3
    assert {lessons[i]["contenu"]["unite"] for i in bilan["proposees"]} == {"pi", " pi ", "pi2"}
    assert bilan["sans_lecon"] == [
        {"genre": "ecart_materiau", "cle": "mat-a", "raison": "unite_absente"}
    ]
    assert len([m for m in reg.lire() if m.get("type_entree") == lecons.TYPE_PROPOSEE]) == 3


def test_une_variance_non_evaluee_ou_sans_lignes_n_est_pas_une_observation():
    ligne = {"materiau": "mat-a", "unite": "u", "quantite_prevue": "10", "quantite_reelle": "12"}
    maillons = [
        {"statut_variance": "declaree", "wct_id": "W-1", "ligne_id": "a" * 64, "horodatage": T1, "lignes": [ligne]},
        {
            "statut_variance": "evaluee",
            "wct_id": "W-2",
            "ligne_id": "b" * 64,
            "horodatage": T1,
            "lignes": "pas une liste",
        },
        {"wct_id": "W-3", "ligne_id": "c" * 64, "horodatage": T1, "lignes": [ligne]},
    ]
    assert lecons.ecarts_materiaux(maillons) == []


def test_les_quantites_invalides_ne_sont_pas_des_observations_et_les_bornes_sont_incluses():
    def maillon(wct, prevu, reel, unite="u"):
        return {
            "statut_variance": "evaluee",
            "wct_id": wct,
            "ligne_id": f"{wct:0>64}"[:64],
            "horodatage": T1,
            "lignes": [
                {
                    "materiau": "mat-a",
                    "unite": unite,
                    "quantite_prevue": prevu,
                    "quantite_reelle": reel,
                }
            ],
        }

    ecarts = lecons.ecarts_materiaux(
        [
            maillon("W-1", None, "12"),
            maillon("W-2", "10", None),
            maillon("W-3", "0", "12"),
            maillon("W-4", "-1", "12"),
            maillon("W-5", "10", "-1"),
            maillon("W-6", "1", "0"),
        ]
    )
    assert [(e.chantier, e.prevu, e.reel) for e in ecarts] == [("W-6", Decimal("1"), Decimal("0"))]


def test_un_ecart_est_immuable():
    e = lecons.Ecart("W-1", "mat-a", Decimal("10"), Decimal("12"), "a" * 64, T1, "u")
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.unite = "pi"


def test_deux_unites_du_meme_materiau_forment_deux_cohortes_et_deux_lecons(reg):
    ecarts = serie(n=15, unite="pi") + serie(n=15, debut=100, unite="pi2")
    bilan = extraire(reg, ecarts_mat=ecarts)
    assert len(bilan["proposees"]) == 2
    lecons_ecrites = [lecons.etat(reg).lecons[i] for i in bilan["proposees"]]
    assert {lc["cle"] for lc in lecons_ecrites} == {"mat-a"}
    assert {lc["contenu"]["unite"] for lc in lecons_ecrites} == {"pi", "pi2"}
    assert len({lc["lecon_id"] for lc in lecons_ecrites}) == 2


def test_le_banc_declare_l_unite_des_cas_materiaux_et_pas_celle_des_marges():
    from opsys.mnemo import mesure

    cas_mat = {
        "genre": "ecart_materiau",
        "unite": "u",
        "segments": [{"n": 2, "facteur": "1.15"}],
        "aberrants": [{"prevu": "10", "reel": "900"}],
    }
    assert {e.unite for e in mesure._ecarts_depuis_spec(cas_mat)} == {"u"}
    cas_mar = {"genre": "ecart_marge", "segments": [{"n": 2, "facteur": "0.93"}]}
    assert {e.unite for e in mesure._ecarts_depuis_spec(cas_mar)} == {None}


def test_l_empreinte_des_observations_distingue_les_unites(reg):
    bilan = extraire(reg, ecarts_mat=serie(n=15, unite="pi") + serie(n=15, unite="pi2"))
    lecons_ecrites = [lecons.etat(reg).lecons[i] for i in bilan["proposees"]]
    assert len(lecons_ecrites) == 2
    assert len({lc["contenu"]["empreinte_observations"] for lc in lecons_ecrites}) == 2


def test_une_marge_en_attente_ne_cree_pas_une_seconde_decision(reg):
    [premier] = extraire(reg, ecarts_mar=serie_marge())["proposees"]
    b = extraire(reg, ecarts_mar=serie_marge(reel_base=900))
    assert b["proposees"] == [] and b["en_cours"] == 1
    assert list(lecons.etat(reg).lecons) == [premier]


def test_les_sources_d_une_lecon_sont_bornees_a_cinq(reg):
    [ident] = extraire(reg, ecarts_mat=serie(n=15, unite="u"))["proposees"]
    assert len(lecons.etat(reg).lecons[ident]["sources"]) == 5


def test_une_lecon_historique_sans_unite_reste_lisible_mais_n_est_pas_evaluable(reg):
    ident = historique(reg, unite=None)
    avant = next(dict(m) for m in reg.lire() if m["lecon_id"] == ident)
    lc = next(x for x in lecons.vue(reg)["lecons"] if x["lecon_id"] == ident)
    assert "unite" not in lc["contenu"] and lc["etat"] == "proposee"
    r = lecons.evaluer_mesure(reg, ident, ecarts_mat=serie(), ecarts_mar=[], horodatage=T2)
    assert r["mesure"] == {"mesurable": False, "raison": "unite_absente"}
    assert r["amelioration_mesurable"] is False
    with pytest.raises(ErreurMnemo, match=codes.LECON_NON_EVALUEE) as exc:
        decider(reg, ident, "canari", pourcentage=10)
    assert "unite_absente" in str(exc.value)
    apres = next(dict(m) for m in reg.lire() if m["lecon_id"] == ident and m["type_entree"] == "lecon_proposee")
    assert apres == avant  # l'ancien maillon n'est ni réécrit ni migré


def test_une_lecon_historique_sans_unite_promue_reste_lisible_et_la_surveillance_le_dit(reg):
    ident = historique(reg, unite=None, etat="complete")
    assert lecons.etat(reg).promotion.etats[ident] == "complete"
    [r] = lecons.surveiller(reg, serie(n=6, debut=100, quand=T4), [])
    assert r["statut"] == "unite_absente" and r["raison"] == "unite_absente"
    assert r["chantiers_depuis_promotion"] == 0
    assert lecons.etat(reg).promotion.etats[ident] == "complete"  # rien n'est retiré automatiquement


def test_une_nouvelle_unite_ne_reprend_pas_l_etat_promu_d_une_ancienne_lecon(reg):
    ancienne = historique(reg, unite="pi", etat="complete")
    nouvelle = extraire(reg, ecarts_mat=serie(unite="pi2"))["proposees"][0]
    etats = lecons.etat(reg).promotion.etats
    assert nouvelle != ancienne
    assert etats[ancienne] == "complete" and etats[nouvelle] == "proposee"
    assert [x["lecon_id"] for x in lecons.appliquer_a(reg, "m06-material-control", "cas")["lecons"]] == [ancienne]


def test_une_cohorte_sans_unite_ne_bloque_pas_une_nouvelle_cohorte(reg):
    ancienne = historique(reg, unite=None, etat="complete")
    nouvelle = extraire(reg, ecarts_mat=serie(unite="pi"))["proposees"][0]
    assert lecons.etat(reg).promotion.etats[ancienne] == "complete"
    assert lecons.etat(reg).promotion.etats[nouvelle] == "proposee"
    assert "unite" not in lecons.etat(reg).lecons[ancienne]["contenu"]
    assert lecons.etat(reg).lecons[nouvelle]["contenu"]["unite"] == "pi"


def test_un_partage_deséquilibré_reste_un_support_insuffisant(reg):
    # 6 chantiers, 3 entraînement / 3 test : le minimum d'entraînement manque
    b = extraire(reg, ecarts_mat=serie(n=6, debut=14, unite="u"))
    assert b["proposees"] == [] and b["sans_lecon"][0]["raison"] == "support_insuffisant"
    # 6 chantiers, 6 entraînement / 0 test : le minimum de test manque
    b = extraire(reg, ecarts_mat=serie(n=6, debut=9, unite="u"))
    assert b["proposees"] == [] and b["sans_lecon"][0]["raison"] == "support_insuffisant"


def test_les_bornes_minimales_exactes_suffisent(reg):
    # W-003..W-008 : exactement 4 chantiers d'entraînement et 2 de test
    b = extraire(reg, ecarts_mat=serie(n=6, debut=3, unite="u"))
    assert len(b["proposees"]) == 1


def test_la_mediane_est_exacte_pour_un_nombre_pair_et_impair():
    assert lecons._mediane([Decimal("1"), Decimal("3"), Decimal("8")]) == Decimal("3")
    assert lecons._mediane([Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")]) == Decimal("3")
    assert lecons._mediane([Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]) == Decimal("2.5")


def test_une_erreur_de_materiau_avec_reel_nul_n_est_pas_mesuree():
    e = lecons.Ecart("W-1", "mat-a", Decimal("10"), Decimal("0"), "a" * 64, T1, "u")
    assert lecons._erreur("ecart_materiau", e, Decimal("1.15")) is None


def test_support_insuffisant_signe_incoherent_et_ecart_negligeable_ne_donnent_aucune_lecon(reg):
    assert extraire(reg, ecarts_mat=serie(n=5))["sans_lecon"][0]["raison"] == "support_insuffisant"
    melange = serie(n=8, facteur="1.30") + serie(n=8, facteur="0.70", debut=8)
    assert extraire(reg, ecarts_mat=melange)["sans_lecon"][0]["raison"] == "signe_incoherent"
    assert extraire(reg, ecarts_mat=serie(facteur="1.02"))["sans_lecon"][0]["raison"] == "ecart_negligeable"
    assert extraire(reg, ecarts_mat=serie(facteur="1.00"))["sans_lecon"][0]["raison"] == "ecart_negligeable"
    assert [m for m in reg.lire() if m["type_entree"] == "lecon_proposee"] == []


def test_une_valeur_aberrante_ne_deplace_pas_le_parametre(reg):
    base = serie()
    aberrant = lecons.Ecart("W-099", "mat-a", Decimal("10"), Decimal("900"), "f" * 64, T1, "u")
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


def test_la_mesure_d_une_marge_ne_prend_que_les_ecarts_de_marge(reg):
    ecarts = serie_marge()
    [ident] = extraire(reg, ecarts_mar=ecarts)["proposees"]
    r = lecons.evaluer_mesure(reg, ident, ecarts_mat=serie(), ecarts_mar=ecarts, horodatage=T2)
    assert r["mesure"]["mesurable"] and r["mesure"]["ameliore"] and not r["mesure"]["regression"]


def test_la_vue_filtre_par_genre(reg):
    material = proposee(reg)
    [marge] = extraire(reg, ecarts_mar=serie_marge())["proposees"]
    v = lecons.vue(reg, genre="ecart_marge")
    assert [x["lecon_id"] for x in v["lecons"]] == [marge] and material not in v["actives"]


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
            e.chantier,
            e.groupe,
            e.prevu,
            (e.prevu * Decimal("0.60")).quantize(Decimal("0.01")),
            e.ligne_id,
            e.quand,
            e.unite,
        )
        if lecons.cote(e.chantier) == "test"
        else e
        for e in serie()
    ]
    r = evaluer(reg, ident, ecarts_mat=hostile)
    assert not r["promouvable"] and "regression_mesuree" in r["raisons"] and r["mesure"]["regression"]


def test_l_evaluation_ne_melange_pas_les_unites_de_la_meme_cle(reg):
    ident = proposee(reg, unite="pi")
    # les observations de l'autre unité sont hostiles : si elles entraient dans la mesure, la leçon régresserait
    melange = serie(n=15, unite="pi") + serie(n=15, debut=100, unite="pi2", facteur="0.60")
    r = evaluer(reg, ident, ecarts_mat=melange)
    assert r["promouvable"] and r["mesure"]["ameliore"] and not r["mesure"]["regression"]
    promouvoir(reg, ident, ecarts_mat=serie(n=15, unite="pi"))
    [surveillance] = lecons.surveiller(
        reg,
        serie(n=6, debut=100, quand=T4, unite="pi")
        + serie(n=6, debut=200, quand=T4, unite="pi2", facteur="0.60"),
        [],
    )
    assert surveillance["statut"] == "ameliore" and not surveillance["retour_arriere_conseille"]


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


def test_les_formes_invalides_ne_levent_pas_et_les_bornes_du_motif_sont_exactes(reg):
    assert lecons._dec(123) is None and lecons._dec("1e3") is None
    with pytest.raises(ErreurMnemo, match=codes.HORODATAGE_INVALIDE):
        lecons._instant("2026-10-01T09:00:00")  # sans fuseau
    with pytest.raises(ErreurMnemo, match=codes.ENTREE_INVALIDE):
        lecons.extraire(
            reg, ecarts_mat=[], ecarts_mar=[], refus=[], rejets=[], par=123, horodatage=T1
        )
    for motif in ("a" * 10, "a" * 500):
        assert lecons._exiger_humain(DIRECTION, motif, T3)[1] == motif
    for motif in ("a" * 9, "a" * 501):
        with pytest.raises(ErreurMnemo, match=codes.MOTIF_REQUIS):
            lecons._exiger_humain(DIRECTION, motif, T3)


def test_l_identite_d_une_lecon_est_stable_et_bornee():
    a = lecons.lecon_id("ecart_materiau", "m06-material-control", "mat-a", {"parametre": "1.15", "unite": "u"})
    b = lecons.lecon_id("ecart_materiau", "m06-material-control", "mat-a", {"unite": "u", "parametre": "1.15"})
    assert a == b and len(a) == 23


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
def promouvoir(reg, ident, pourcentage=20, ecarts_mat=None, ecarts_mar=None):
    evaluer(reg, ident, ecarts_mat=ecarts_mat, ecarts_mar=ecarts_mar)
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
    canari = lecons.appliquer_a(reg, "m06-material-control", dedans[0])["canari"]
    assert canari["dans_le_canari"] and canari["lecon_id"] == ident
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


def test_la_surveillance_part_de_la_promotion_complete_et_non_du_canari(reg):
    ident = proposee(reg)
    evaluer(reg, ident)
    decider(reg, ident, "canari", pourcentage=20, horodatage=T2)
    decider(reg, ident, "complete", horodatage=T3)
    # observation APRÈS le canari mais AVANT la promotion complète : elle ne compte pas encore
    [r] = lecons.surveiller(reg, serie(n=2, debut=100, quand="2026-10-07T10:00:00+00:00", unite="u"), [])
    assert r["statut"] == "insuffisant" and r["chantiers_depuis_promotion"] == 0


def test_la_surveillance_exclut_les_observations_au_moment_de_la_promotion(reg):
    ident = proposee(reg)
    promouvoir(reg, ident)
    observations = serie(n=6, debut=100, quand=T3, unite="u") + serie(n=6, debut=200, quand=T4, unite="u")
    [r] = lecons.surveiller(reg, observations, [])
    assert r["chantiers_depuis_promotion"] == 6


def test_la_surveillance_d_une_marge_exclut_les_observations_au_moment_de_la_promotion(reg):
    ecarts = serie_marge()
    [ident] = extraire(reg, ecarts_mar=ecarts)["proposees"]
    promouvoir(reg, ident, ecarts_mar=ecarts)
    observations = serie_marge(n=6, debut=100, quand=T3) + serie_marge(n=6, debut=200, quand=T4)
    [r] = lecons.surveiller(reg, [], observations)
    assert r["chantiers_depuis_promotion"] == 6


def test_la_surveillance_avec_deux_chantiers_n_est_pas_insuffisante(reg):
    ident = proposee(reg)
    promouvoir(reg, ident)
    [r] = lecons.surveiller(reg, serie(n=2, debut=100, quand=T4, unite="u"), [])
    assert r["statut"] != "insuffisant" and r["chantiers_depuis_promotion"] == 2


def test_la_surveillance_distingue_inchange_d_ameliore_et_de_regresse(reg):
    historique(reg, unite="u", parametre="1.00", etat="complete")
    [r] = lecons.surveiller(reg, serie(n=2, debut=100, quand=T4, unite="u", facteur="1.00"), [])
    assert r["statut"] == "inchange" and not r["retour_arriere_conseille"]


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
