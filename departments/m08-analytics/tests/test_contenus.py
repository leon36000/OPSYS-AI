"""La mesure par contenu (PLAN T4.17-e) : module pur `contenus.py` et lecture `vue_contenus.py`.

Ce que ce fichier prouve :
- l'attribution est stricte : un lead sans clé `utm_content` n'est attribué à aucun contenu, une clé inconnue, ambiguë
  ou portée par un contenu sans lien de suivi ne l'est pas non plus, chaque cas est compté à part ;
- un devis suit le lead qu'il porte, un devis dont le lead n'est pas connu de M1 n'est attribué à rien ;
- une donnée absente est « non calculable, manque X » (jamais un zéro) ; un zéro n'est dit que si la chaîne a été lue ;
- impressions et clics n'ont aucune source : jamais un nombre, dans aucun état des faits ;
- le résultat ne dépend ni de l'ordre de réception ni des relivraisons ;
- les faits ne gardent aucun renseignement personnel ; les définitions sont gouvernées (propriétaire, version) ;
- la lecture est bornée par pages sous la limite du socle.

Les faits sont construits par les vrais constructeurs (`fait_contenu_exporte`, `fait_lead_m1`, `entonnoir.fait_devis_*`)
sur des charges au format du catalogue, fictives. Le bus, l'identité et la base sont dans `test_evenements_contenus.py`.
"""

from __future__ import annotations

import itertools
import json
import random
from pathlib import Path

import pytest
import yaml
from m8_analytics import conformite, contenus, encodage, entonnoir, vue_contenus

FICTIF = True  # aucun client réel : des identifiants, des personnes et des clés de test

_SRC_M8 = Path(__file__).resolve().parents[1] / "src" / "m8_analytics"
_YAML = Path(__file__).resolve().parents[1] / "metrics" / "m8-contenus.v1.yaml"
BUDGET = 5900
CONFIDENCES = ("Client Fictif", "418-555-0100", "exemple-fictif.test", "Repentigny", "gouttieres", "Toitures")
CLE_A = "facebook-aaaaaaaaaaaaaaaa"
CLE_B = "instagram-bbbbbbbbbbbbbbbb"
CLE_SANS_LIEN = "demande_temoignage-cccccccccccccccc"


# ---------------------------------------------------------------------------
# Faits, construits par les vrais constructeurs
# ---------------------------------------------------------------------------
def _contenu(contenu_id, cle, canal="facebook", wct_id="wct-1-fictif", lien=True, quand="2026-09-29T20:00:00-04:00"):
    return contenus.fait_contenu_exporte({
        "contenu_id": contenu_id, "wct_id": wct_id, "canal": canal, "utm_content": cle, "lien_de_suivi": lien,
        "exporte_le": quand,
    })


def _lead(lead_id, cle=None, quand="2026-09-30T10:00:00-04:00", **utm_en_plus):
    lead = {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "service": "gouttieres",
        "ville": "Repentigny", "urgence_declaree": False, "canal": "formulaire",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100", "courriel": "c@exemple-fictif.test"},
    }
    utm = dict(utm_en_plus)
    if cle is not None:
        utm["utm_content"] = cle
    if utm:
        lead["utm"] = utm
    return contenus.fait_lead_m1({"lead": lead, "horodatage": quand, "signal_id": f"formulaire:{lead_id}"})


def _envoye(devis_id, lead_id, quand="2026-10-01T09:00:00-04:00"):
    return entonnoir.fait_devis_envoye(
        {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": quand}
    )


def _accepte(devis_id, lead_id, quand="2026-10-02T09:00:00-04:00"):
    return entonnoir.fait_devis_accepte(
        {"devis_id": devis_id, "lead_id": lead_id, "prix_total": "600.00", "horodatage_acceptation": quand}
    )


def _mesures(faits, entrees=()):
    situation = contenus.situation(list(faits), list(entrees), contenus.charger_definitions())
    return {m["metric_id"]: m for m in situation["mesures"]}, situation


def _ligne(situation, cle):
    (ligne,) = [ligne for ligne in situation["lignes"] if ligne["utm_content"] == cle]
    return ligne


# ---------------------------------------------------------------------------
# Les définitions gouvernées
# ---------------------------------------------------------------------------
def test_six_metriques_gouvernees_chacune_avec_son_proprietaire_sa_source_et_sa_version():
    definitions = contenus.charger_definitions()

    assert list(definitions) == [
        "m8_contenus_exportes", "m8_leads_par_contenu", "m8_devis_envoyes_par_contenu",
        "m8_devis_acceptes_par_contenu", "m8_impressions_par_contenu", "m8_clics_par_contenu",
    ]
    assert {d["proprietaire"] for d in definitions.values()} == {"m07-marketing"}
    assert {d["unite"] for d in definitions.values()} == {"contenus", "leads", "devis", "impressions", "clics"}
    mesures, _ = _mesures([_contenu("c1", CLE_A)])
    for metric_id, mesure in mesures.items():
        assert mesure["version_definition"] == encodage.empreinte(definitions[metric_id])
        assert mesure["proprietaire"] == "m07-marketing"
        assert mesure["source"] == definitions[metric_id]["source_donnees"]
    assert len({m["version_definition"] for m in mesures.values()}) == 6


def test_la_version_change_quand_la_definition_change(tmp_path):
    definitions = contenus.charger_definitions()
    contenu = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    contenu["metrics"][1]["definition"] += " Précision de test."
    modifie = tmp_path / "m8-contenus.v1.yaml"
    modifie.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")

    autres = contenus.charger_definitions(modifie)

    assert encodage.empreinte(autres["m8_leads_par_contenu"]) != encodage.empreinte(definitions["m8_leads_par_contenu"])
    assert encodage.empreinte(autres["m8_clics_par_contenu"]) == encodage.empreinte(definitions["m8_clics_par_contenu"])


def _copie(tmp_path, modifier):
    contenu = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    modifier(contenu)
    chemin = tmp_path / "m8-contenus.v1.yaml"
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    return chemin


def test_le_registre_refuse_une_metrique_sans_proprietaire_ou_un_proprietaire_inconnu_ou_sans_metrique(tmp_path):
    def sans_proprietaire(contenu):
        del contenu["proprietaires"]["m8_clics_par_contenu"]

    def proprietaire_inconnu(contenu):
        contenu["proprietaires"]["m8_clics_par_contenu"] = "m99-inconnu"

    def proprietaire_sans_metrique(contenu):
        contenu["proprietaires"]["m8_fantome"] = "m07-marketing"

    for modifier, attendu in (
        (sans_proprietaire, "sans propriétaire : m8_clics_par_contenu"),
        (proprietaire_inconnu, "propriétaire inconnu ou sans métrique : m8_clics_par_contenu"),
        (proprietaire_sans_metrique, "propriétaire inconnu ou sans métrique : m8_fantome"),
    ):
        with pytest.raises(ValueError, match="registre des contenus") as erreur:
            contenus.charger_definitions(_copie(tmp_path, modifier))
        assert attendu in str(erreur.value)


def test_le_registre_refuse_une_unite_monetaire_qui_n_est_pas_du_cad(tmp_path):
    def en_euros(contenu):
        contenu["metrics"][0]["unite"] = "EUR"

    with pytest.raises(ValueError, match="registre des contenus invalide"):
        contenus.charger_definitions(_copie(tmp_path, en_euros))


def test_le_chargeur_partage_garde_le_nom_de_l_entonnoir_par_defaut(tmp_path):
    """La mutualisation du chargeur ne change pas les messages de l'entonnoir (T4.19)."""
    contenu = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    del contenu["proprietaires"]["m8_clics_par_contenu"]
    chemin = tmp_path / "sans-proprietaire.yaml"
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="registre de l'entonnoir : métrique") as erreur:
        entonnoir.charger_definitions(chemin)
    assert "des contenus" not in str(erreur.value)


# ---------------------------------------------------------------------------
# Les faits : identifiants, instants et clé, rien de personnel
# ---------------------------------------------------------------------------
def test_le_fait_d_un_contenu_ne_garde_que_ce_que_le_catalogue_dit():
    fait = _contenu("c1", CLE_A, canal="instagram", wct_id="wct-9", lien=False, quand="2026-09-29T20:00:00-04:00")

    assert fait == {
        "type_entree": "contenu_exporte", "contenu_id": "c1", "wct_id": "wct-9", "canal": "instagram",
        "utm_content": CLE_A, "lien_de_suivi": False, "horodatage": "2026-09-29T20:00:00-04:00",
    }


def test_le_fait_d_un_lead_ne_garde_ni_le_contact_ni_la_ville_ni_le_service_ni_la_conversation():
    fait = _lead("L1", CLE_A, utm_source="facebook", utm_medium="social", utm_campaign="contenu-x-2026")

    assert fait == {
        "type_entree": "lead_m1", "lead_id": "L1", "utm_content": CLE_A, "horodatage": "2026-09-30T10:00:00-04:00",
    }
    lu = json.dumps(fait, ensure_ascii=False)
    assert not [confidence for confidence in CONFIDENCES if confidence in lu] and "conv-L1" not in lu


@pytest.mark.parametrize(
    "utm", [None, {"utm_source": "facebook"}, {"utm_source": "facebook", "utm_campaign": "c-2026"}]
)
def test_un_lead_sans_utm_content_n_a_pas_de_cle(utm):
    charge = {"lead": {"lead_id": "L1"}, "horodatage": "2026-09-30T10:00:00-04:00", "signal_id": "s"}
    if utm is not None:
        charge["lead"]["utm"] = utm

    assert contenus.fait_lead_m1(charge)["utm_content"] is None


def test_les_cles_d_unicite_sont_le_contenu_pour_un_contenu_et_le_lead_pour_un_lead():
    assert contenus.cles_unicite("contenu_exporte") == ("contenu_id",)
    assert contenus.cles_unicite("lead_m1") == ("lead_id",)


# ---------------------------------------------------------------------------
# L'attribution des leads : stricte
# ---------------------------------------------------------------------------
def test_les_leads_qui_portent_la_cle_d_un_contenu_lui_sont_attribues_et_les_autres_sont_comptes_a_part():
    faits = [
        _contenu("c1", CLE_A), _contenu("c2", CLE_B, canal="instagram"),
        _lead("L1", CLE_A), _lead("L2", CLE_A), _lead("L3", CLE_B),
        _lead("L4"),  # aucune clé : le formulaire n'en portait pas
        _lead("L5", "facebook-zzzzzzzzzzzzzzzz"),  # une clé qu'aucun contenu connu ne porte
    ]

    mesures, situation = _mesures(faits)

    leads = mesures["m8_leads_par_contenu"]
    assert (leads["statut"], leads["valeur"]) == ("calculee", "3")
    assert leads["entrees"] == {
        "n_leads_recus": 5, "n_leads_attribues": 3, "n_leads_sans_utm_content": 1,
        "n_leads_utm_content_inconnu": 1, "n_leads_utm_content_ambigu": 0,
    }
    assert (_ligne(situation, CLE_A)["leads"], _ligne(situation, CLE_B)["leads"]) == (2, 1)


def test_un_lead_sans_utm_content_n_est_attribue_a_aucun_contenu_meme_s_il_n_y_a_qu_un_contenu():
    mesures, situation = _mesures([_contenu("c1", CLE_A), _lead("L1")])

    assert mesures["m8_leads_par_contenu"]["valeur"] == "0"
    assert mesures["m8_leads_par_contenu"]["entrees"]["n_leads_sans_utm_content"] == 1
    assert _ligne(situation, CLE_A)["leads"] == 0


def test_l_egalite_de_la_cle_est_stricte_la_casse_et_les_espaces_comptent():
    faits = [_contenu("c1", CLE_A)] + [
        _lead(f"L{i}", cle) for i, cle in enumerate(
            (CLE_A.upper(), f" {CLE_A}", f"{CLE_A} ", CLE_A[:-1], f"{CLE_A}0", CLE_A.replace("-", "_")), start=1
        )
    ]

    mesures, situation = _mesures(faits)

    assert mesures["m8_leads_par_contenu"]["valeur"] == "0"
    assert mesures["m8_leads_par_contenu"]["entrees"]["n_leads_utm_content_inconnu"] == 6
    assert _ligne(situation, CLE_A)["leads"] == 0


def test_un_lead_rejoue_ou_livre_deux_fois_ne_compte_qu_une_fois():
    lead = _lead("L1", CLE_A)

    mesures, situation = _mesures([_contenu("c1", CLE_A), lead, dict(lead), _lead("L1", CLE_B)])

    assert mesures["m8_leads_par_contenu"]["valeur"] == "1"  # le premier fait de L1 fait foi
    assert _ligne(situation, CLE_A)["leads"] == 1


def test_un_contenu_livre_deux_fois_ne_compte_qu_une_fois():
    contenu = _contenu("c1", CLE_A)

    mesures, situation = _mesures([contenu, dict(contenu), _lead("L1", CLE_A)])

    assert mesures["m8_contenus_exportes"]["valeur"] == "1" and len(situation["lignes"]) == 1


def test_un_contenu_sans_lien_de_suivi_n_est_pas_mesurable_et_sa_cle_n_attribue_rien():
    faits = [_contenu("c1", CLE_A), _contenu("c2", CLE_SANS_LIEN, canal="demande_temoignage", lien=False),
             _lead("L1", CLE_SANS_LIEN)]

    mesures, situation = _mesures(faits)

    ligne = _ligne(situation, CLE_SANS_LIEN)
    assert ligne["suivi"] == "sans_lien" and ligne["leads"] is None  # « non mesurable », jamais 0
    assert (ligne["devis_envoyes"], ligne["devis_acceptes"]) == (None, None)
    assert mesures["m8_leads_par_contenu"]["valeur"] == "0"  # aucun lien ne portait cette clé : le lead n'est pas à lui
    assert mesures["m8_leads_par_contenu"]["entrees"]["n_leads_utm_content_inconnu"] == 1
    assert mesures["m8_contenus_exportes"]["entrees"] == {
        "n_mesurables": 1, "n_sans_lien_de_suivi": 1, "n_cle_ambigue": 0,
    }


def test_une_cle_que_deux_contenus_se_disputent_n_est_attribuee_a_aucun_et_le_dit():
    faits = [
        _contenu("c1", CLE_A), _contenu("c2", CLE_A, wct_id="wct-2-fictif"), _contenu("c3", CLE_B, canal="instagram"),
        _lead("L1", CLE_A), _lead("L2", CLE_B),
    ]

    mesures, situation = _mesures(faits)

    assert mesures["m8_leads_par_contenu"]["valeur"] == "1"  # seulement L2, à c3
    assert mesures["m8_leads_par_contenu"]["entrees"]["n_leads_utm_content_ambigu"] == 1
    assert mesures["m8_contenus_exportes"]["valeur"] == "3"
    assert mesures["m8_contenus_exportes"]["entrees"]["n_cle_ambigue"] == 2
    ambigus = [ligne for ligne in situation["lignes"] if ligne["utm_content"] == CLE_A]
    assert [(ligne["suivi"], ligne["leads"]) for ligne in ambigus] == [("ambigu", None), ("ambigu", None)]
    assert _ligne(situation, CLE_B)["leads"] == 1


def test_des_faits_illisibles_ne_sont_pas_des_faits():
    faits = [
        {"type_entree": "contenu_exporte", "utm_content": CLE_A},  # sans contenu_id
        {"type_entree": "lead_m1", "lead_id": "", "utm_content": CLE_A},  # identifiant vide
        {"type_entree": "lead_m1", "lead_id": 12, "utm_content": CLE_A},  # identifiant qui n'est pas un texte
        {"type_entree": "autre", "lead_id": "L9", "contenu_id": "c9"},  # un type que M8 ne mesure pas ici
        _contenu("c1", CLE_A), _lead("L1", CLE_A),
    ]

    mesures, _ = _mesures(faits)

    assert mesures["m8_contenus_exportes"]["valeur"] == "1"
    assert mesures["m8_leads_par_contenu"]["entrees"]["n_leads_recus"] == 1


# ---------------------------------------------------------------------------
# Les devis suivent le lead qu'ils portent
# ---------------------------------------------------------------------------
def test_un_devis_envoye_ou_accepte_est_attribue_au_contenu_du_lead_qu_il_porte():
    faits = [_contenu("c1", CLE_A), _contenu("c2", CLE_B, canal="instagram"), _lead("L1", CLE_A), _lead("L2", CLE_B)]
    entrees = [
        _envoye("D1", "L1"), _envoye("D2", "L1"), _envoye("D3", "L2"), _accepte("D1", "L1"),
        _accepte("D9", "L2"),  # accepté sans envoi reçu : chaque métrique lit son propre fait
    ]

    mesures, situation = _mesures(faits, entrees)

    envoyes, acceptes = mesures["m8_devis_envoyes_par_contenu"], mesures["m8_devis_acceptes_par_contenu"]
    assert (envoyes["valeur"], acceptes["valeur"]) == ("3", "2")
    assert envoyes["entrees"] == {
        "n_devis_recus": 3, "n_devis_attribues": 3, "n_sans_lead_de_m1": 0, "n_lead_sans_contenu": 0,
    }
    a, b = _ligne(situation, CLE_A), _ligne(situation, CLE_B)
    assert (a["leads"], a["devis_envoyes"], a["devis_acceptes"]) == (1, 2, 1)
    assert (b["leads"], b["devis_envoyes"], b["devis_acceptes"]) == (1, 1, 1)


def test_un_devis_dont_le_lead_est_inconnu_de_m1_ou_sans_contenu_n_est_attribue_a_rien_et_est_compte_a_part():
    faits = [_contenu("c1", CLE_A), _lead("L1", CLE_A), _lead("L2"), _lead("L3", "facebook-inconnue")]
    entrees = [
        _envoye("D1", "L1"),
        _envoye("D2", "L2"),  # lead connu de M1, aucune clé
        _envoye("D3", "L3"),  # lead connu de M1, clé inconnue
        _envoye("D4", "L1~opp~wct-1"),  # l'opportunité que M2 rouvre pour un client connu : pas le lead de M1
        _envoye("D5", "L-jamais-recu"),
    ]

    mesures, situation = _mesures(faits, entrees)

    assert mesures["m8_devis_envoyes_par_contenu"]["valeur"] == "1"
    assert mesures["m8_devis_envoyes_par_contenu"]["entrees"] == {
        "n_devis_recus": 5, "n_devis_attribues": 1, "n_sans_lead_de_m1": 2, "n_lead_sans_contenu": 2,
    }
    assert _ligne(situation, CLE_A)["devis_envoyes"] == 1


def test_un_devis_rejoue_ne_compte_qu_une_fois_et_deux_devis_d_un_meme_lead_comptent_deux_fois():
    faits = [_contenu("c1", CLE_A), _lead("L1", CLE_A)]
    devis = _envoye("D1", "L1")

    mesures, _ = _mesures(faits, [devis, dict(devis), _envoye("D2", "L1")])

    assert mesures["m8_devis_envoyes_par_contenu"]["valeur"] == "2"


def test_le_devis_d_un_lead_dont_la_cle_est_ambigue_n_est_attribue_a_aucun_contenu():
    faits = [_contenu("c1", CLE_A), _contenu("c2", CLE_A, wct_id="wct-2-fictif"), _lead("L1", CLE_A)]

    mesures, _ = _mesures(faits, [_envoye("D1", "L1")])

    assert mesures["m8_devis_envoyes_par_contenu"]["valeur"] == "0"
    assert mesures["m8_devis_envoyes_par_contenu"]["entrees"]["n_lead_sans_contenu"] == 1


# ---------------------------------------------------------------------------
# « Non calculable » : jamais un zéro à la place d'une donnée absente
# ---------------------------------------------------------------------------
def _aucune_valeur_ni_zero(mesures, metric_ids):
    for metric_id in metric_ids:
        assert mesures[metric_id]["statut"] == "non_calculable", metric_id
        assert mesures[metric_id]["valeur"] is None
        assert mesures[metric_id]["detail"].startswith("non calculable, manque")


def test_sans_aucun_fait_les_six_metriques_sont_non_calculables_et_nomment_ce_qui_manque():
    mesures, situation = _mesures([])

    _aucune_valeur_ni_zero(mesures, mesures)
    assert [c["champ"] for c in mesures["m8_contenus_exportes"]["manque"]] == ["m7.contenu_exporte"]
    assert [c["champ"] for c in mesures["m8_leads_par_contenu"]["manque"]] == ["m7.contenu_exporte", "m1.lead_qualifie"]
    assert [c["champ"] for c in mesures["m8_devis_envoyes_par_contenu"]["manque"]] == [
        "m7.contenu_exporte", "m1.lead_qualifie", "m3.devis_envoye",
    ]
    assert [c["champ"] for c in mesures["m8_devis_acceptes_par_contenu"]["manque"]][-1] == "m3.devis_accepte"
    assert situation["lignes"] == []
    assert [(s["evenement"], s["n"], s["dernier_fait_le"]) for s in situation["sources"]] == [
        ("m7.contenu_exporte", 0, None), ("m1.lead_qualifie", 0, None), ("m3.devis_envoye", 0, None),
        ("m3.devis_accepte", 0, None),
    ]


def test_des_leads_sans_aucun_contenu_exporte_ne_disent_pas_zero_ils_disent_ce_qui_manque():
    """Zéro serait faux : sans contenu connu, M8 ne sait pas à quoi attribuer, il n'a pas compté « aucun »."""
    mesures, _ = _mesures([_lead("L1", CLE_A), _lead("L2")])

    _aucune_valeur_ni_zero(mesures, ["m8_contenus_exportes", "m8_leads_par_contenu"])
    assert [c["champ"] for c in mesures["m8_leads_par_contenu"]["manque"]] == ["m7.contenu_exporte"]


def test_des_contenus_sans_aucun_lead_recu_ne_disent_pas_zero_lead():
    mesures, situation = _mesures([_contenu("c1", CLE_A)])

    assert mesures["m8_contenus_exportes"]["valeur"] == "1"
    _aucune_valeur_ni_zero(mesures, ["m8_leads_par_contenu", "m8_devis_envoyes_par_contenu"])
    assert [c["champ"] for c in mesures["m8_leads_par_contenu"]["manque"]] == ["m1.lead_qualifie"]
    ligne = _ligne(situation, CLE_A)
    assert (ligne["leads"], ligne["devis_envoyes"], ligne["devis_acceptes"]) == (None, None, None)


def test_la_chaine_lue_sans_aucun_fait_de_l_entonnoir_laisse_les_devis_non_calculables_mais_les_leads_comptes():
    mesures, situation = _mesures([_contenu("c1", CLE_A), _lead("L1", CLE_A)])

    assert mesures["m8_leads_par_contenu"]["valeur"] == "1"
    _aucune_valeur_ni_zero(mesures, ["m8_devis_envoyes_par_contenu", "m8_devis_acceptes_par_contenu"])
    ligne = _ligne(situation, CLE_A)
    assert (ligne["leads"], ligne["devis_envoyes"], ligne["devis_acceptes"]) == (1, None, None)


def test_un_entonnoir_lu_sans_devis_pour_ces_contenus_donne_un_vrai_zero():
    """M8 a reçu des faits de l'entonnoir (ici l'arrivée d'un lead chez M2) : « aucun devis » est alors un comptage."""
    arrivee = entonnoir.fait_lead_recu(
        {"lead_id": "L1", "client_id": "a" * 64, "horodatage_association": "2026-09-30T10:00:00-04:00"}
    )

    mesures, situation = _mesures([_contenu("c1", CLE_A), _lead("L1", CLE_A)], [arrivee])

    devis = mesures["m8_devis_envoyes_par_contenu"], mesures["m8_devis_acceptes_par_contenu"]
    assert [m["valeur"] for m in devis] == ["0", "0"]
    assert _ligne(situation, CLE_A)["devis_envoyes"] == 0


@pytest.mark.parametrize("faits, entrees", [
    ([], []),
    ([_contenu("c1", CLE_A)], []),
    ([_contenu("c1", CLE_A), _lead("L1", CLE_A)], []),
    ([_contenu("c1", CLE_A), _lead("L1", CLE_A)], [_envoye("D1", "L1"), _accepte("D1", "L1")]),
    ([_contenu("c1", CLE_A, lien=False), _lead("L1")], [_envoye("D1", "L1")]),
])
def test_impressions_et_clics_n_ont_aucune_source_jamais_un_nombre_dans_aucun_etat_des_faits(faits, entrees):
    mesures, situation = _mesures(faits, entrees)

    for metric_id in ("m8_impressions_par_contenu", "m8_clics_par_contenu"):
        mesure = mesures[metric_id]
        assert (mesure["statut"], mesure["valeur"], mesure["entrees"]) == ("non_calculable", None, {})
        assert [m["champ"] for m in mesure["manque"]] == ["source des impressions et des clics"]
        assert mesure["manque"][0]["source"].startswith("aucune (connecteur à décider")
        assert mesure["detail"].startswith("non calculable, manque source des impressions et des clics")
    assert not [cle for ligne in situation["lignes"] for cle in ligne if "impression" in cle or "clic" in cle]


# ---------------------------------------------------------------------------
# Une ligne par contenu : ordre total, sans dépendre de l'ordre de réception
# ---------------------------------------------------------------------------
def _jeu_de_faits():
    return [
        _contenu("c1", CLE_A, quand="2026-09-29T20:00:00-04:00"),
        _contenu("c2", CLE_B, canal="instagram", quand="2026-09-30T20:00:00-04:00"),
        _contenu("c3", CLE_SANS_LIEN, canal="demande_temoignage", lien=False, quand="2026-09-28T20:00:00-04:00"),
        _lead("L1", CLE_B), _lead("L2", CLE_A), _lead("L3", CLE_A), _lead("L4"),
    ], [_envoye("D1", "L2"), _accepte("D1", "L2"), _envoye("D2", "L1")]


def test_le_resultat_ne_depend_pas_de_l_ordre_de_reception():
    faits, entrees = _jeu_de_faits()
    reference = contenus.situation(faits, entrees, contenus.charger_definitions())
    aleatoire = random.Random(20260929)
    for _ in range(40):
        melanges, melanges_entonnoir = list(faits), list(entrees)
        aleatoire.shuffle(melanges)
        aleatoire.shuffle(melanges_entonnoir)
        assert contenus.situation(melanges, melanges_entonnoir, contenus.charger_definitions()) == reference


def test_les_lignes_montrent_d_abord_ce_qui_amene_le_plus_puis_le_plus_recent():
    faits, entrees = _jeu_de_faits()

    _, situation = _mesures(faits, entrees)

    assert [ligne["utm_content"] for ligne in situation["lignes"]] == [CLE_A, CLE_B, CLE_SANS_LIEN]
    assert [ligne["leads"] for ligne in situation["lignes"]] == [2, 1, None]


def test_a_egalite_le_plus_recent_d_abord_puis_la_cle():
    faits = [
        _contenu("c1", "facebook-1111111111111111", quand="2026-09-01T10:00:00-04:00"),
        _contenu("c2", "facebook-2222222222222222", quand="2026-09-03T10:00:00-04:00"),
        _contenu("c3", "facebook-3333333333333333", quand="2026-09-03T10:00:00-04:00"),
        _contenu("c4", "facebook-4444444444444444", quand="illisible"),
        _lead("L1"),
    ]

    _, situation = _mesures(faits)

    assert [ligne["utm_content"][-4:] for ligne in situation["lignes"]] == ["2222", "3333", "1111", "4444"]


def test_les_sources_disent_combien_de_faits_et_jusqu_a_quand():
    faits, entrees = _jeu_de_faits()

    _, situation = _mesures(faits, entrees)

    assert situation["sources"] == [
        {"evenement": "m7.contenu_exporte", "n": 3, "dernier_fait_le": "2026-09-30T20:00:00-04:00"},
        {"evenement": "m1.lead_qualifie", "n": 4, "dernier_fait_le": "2026-09-30T10:00:00-04:00"},
        {"evenement": "m3.devis_envoye", "n": 2, "dernier_fait_le": "2026-10-01T09:00:00-04:00"},
        {"evenement": "m3.devis_accepte", "n": 1, "dernier_fait_le": "2026-10-02T09:00:00-04:00"},
    ]


def test_toutes_les_permutations_de_quatre_faits_donnent_la_meme_mesure():
    faits = [_contenu("c1", CLE_A), _lead("L1", CLE_A), _lead("L2"), _contenu("c2", CLE_B, canal="instagram")]
    reference = contenus.situation(faits, [], contenus.charger_definitions())

    for ordre in itertools.permutations(faits):
        assert contenus.situation(list(ordre), [], contenus.charger_definitions()) == reference


# ---------------------------------------------------------------------------
# La lecture : bornée, par pages, sans donnée de client
# ---------------------------------------------------------------------------
def _beaucoup(n):
    faits = [_contenu(f"c{i:03d}", f"facebook-{i:016x}", quand=f"2026-09-{1 + i % 28:02d}T10:00:00-04:00")
             for i in range(n)]
    faits += [_lead(f"L{i:03d}", f"facebook-{i:016x}") for i in range(0, n, 2)]
    return faits


def test_la_lecture_tient_sous_la_borne_et_les_pages_couvrent_chaque_contenu_une_fois():
    situation = contenus.situation(_beaucoup(200), [], contenus.charger_definitions())
    vus, depart, pages = [], 0, 0
    while depart is not None:
        vue = vue_contenus.assembler(situation, depart, BUDGET)
        assert len(json.dumps(vue, ensure_ascii=False)) <= BUDGET
        assert vue["affichage"]["n_contenus"] == 200 and vue["affichage"]["depart"] == depart
        assert vue["affichage"]["affiches"] == len(vue["contenus"]) >= 1
        assert vue["affichage"]["reste"] == 200 - depart - len(vue["contenus"])
        assert (vue["affichage"]["message"] is None) == (vue["affichage"]["prochain_depart"] is None)
        vus.extend(ligne["utm_content"] for ligne in vue["contenus"])
        depart, pages = vue["affichage"]["prochain_depart"], pages + 1
    assert pages > 1 and sorted(vus) == sorted(f"facebook-{i:016x}" for i in range(200))
    assert vus == [ligne["utm_content"] for ligne in situation["lignes"]]  # le même ordre, page après page


def test_sans_borne_tout_tient_d_un_coup_sans_page_suivante():
    situation = contenus.situation(_beaucoup(30), [], contenus.charger_definitions())

    vue = vue_contenus.assembler(situation, 0, None)

    assert len(vue["contenus"]) == 30 and vue["affichage"]["prochain_depart"] is None and vue["affichage"]["reste"] == 0


@pytest.mark.parametrize("depart", [-1, 31, True, "0", 1.5, None])
def test_un_depart_invalide_ou_au_dela_de_la_fin_est_un_refus_jamais_une_page_vide(depart):
    situation = contenus.situation(_beaucoup(30), [], contenus.charger_definitions())

    with pytest.raises(ValueError, match="depart"):
        vue_contenus.assembler(situation, depart, BUDGET)


def test_un_squelette_qui_ne_tient_pas_meme_sans_contenu_est_un_refus_jamais_une_reponse_coupee():
    situation = contenus.situation(_beaucoup(4), [], contenus.charger_definitions())

    with pytest.raises(ValueError, match="borne"):
        vue_contenus.assembler(situation, 0, 500)


def test_sans_contenu_la_lecture_dit_zero_contenu_et_les_manques_une_seule_fois():
    situation = contenus.situation([], [], contenus.charger_definitions())

    vue = vue_contenus.assembler(situation, 0, BUDGET)

    assert vue["contenus"] == [] and vue["affichage"]["n_contenus"] == 0 and vue["affichage"]["prochain_depart"] is None
    assert [m["champ"] for m in vue["manques"]] == [
        "m7.contenu_exporte", "m1.lead_qualifie", "m3.devis_envoye", "m3.devis_accepte",
        "source des impressions et des clics",
    ]  # cinq manques distincts, chacun dit une fois même s'il vaut pour plusieurs métriques
    assert all(ligne["statut"] == "non_calculable" and ligne["valeur"] is None for ligne in vue["metriques"])
    assert all(ligne["manque"] for ligne in vue["metriques"])


def test_la_lecture_porte_la_version_et_le_proprietaire_de_chaque_definition_et_aucune_donnee_de_client():
    faits, entrees = _jeu_de_faits()
    situation = contenus.situation(faits, entrees, contenus.charger_definitions())

    vue = vue_contenus.assembler(situation, 0, BUDGET)

    assert set(vue) == {"vue", "portee", "metriques", "sources", "contenus", "affichage", "manques"}
    for ligne in vue["metriques"]:
        assert ligne["proprietaire"] == "m07-marketing" and len(ligne["version_definition"]) == 64
    texte = json.dumps(vue, ensure_ascii=False)
    assert not [confidence for confidence in CONFIDENCES if confidence in texte]
    assert not [cle for cle in ("lead_id", "L1", "L2", "contact", "telephone", "courriel") if cle in texte]
    assert set(vue["contenus"][0]) == {
        "utm_content", "canal", "wct_id", "exporte_le", "suivi", "leads", "devis_envoyes", "devis_acceptes",
    }


def test_une_metrique_non_calculable_dit_ce_qui_manque_une_fois_dans_manques_et_par_nom_dans_sa_ligne():
    situation = contenus.situation([_contenu("c1", CLE_A)], [], contenus.charger_definitions())

    vue = vue_contenus.assembler(situation, 0, BUDGET)

    lignes = {ligne["metric_id"]: ligne for ligne in vue["metriques"]}
    assert lignes["m8_contenus_exportes"]["statut"] == "calculee" and "manque" not in lignes["m8_contenus_exportes"]
    assert lignes["m8_leads_par_contenu"]["manque"] == ["m1.lead_qualifie"]
    assert lignes["m8_impressions_par_contenu"]["manque"] == ["source des impressions et des clics"]
    assert [m["champ"] for m in vue["manques"]].count("source des impressions et des clics") == 1


# ---------------------------------------------------------------------------
# Gardes statiques : M8 ne dépend d'aucun département, ne lit aucune horloge ni source aléatoire
# ---------------------------------------------------------------------------
def test_le_paquet_de_m8_reste_conforme_avec_les_nouveaux_modules():
    conformes, detail = conformite.verifier_aucun_import_domaine(_SRC_M8)
    assert conformes, detail
    assert conformite.verifier_aucune_cause_signalee(_SRC_M8)[0]
    verdict = conformite.verifier_conformite(_SRC_M8)
    assert verdict["conforme"] is True, verdict["violations"]


def test_les_modules_purs_n_importent_ni_opsys_ni_horloge_ni_hasard():
    import ast

    for nom in ("contenus.py", "vue_contenus.py"):
        arbre = ast.parse((_SRC_M8 / nom).read_text(encoding="utf-8"))
        importes = {a.name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names}
        importes |= {n.module.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module}
        assert not importes & {"opsys", "random", "time", "datetime", "uuid", "os", "sqlalchemy"}, (nom, importes)
