"""L'adjointe de réception qui regarde sa propre file (`reception_interne.py`) : l'état, les avis à consigner, les
attentes « À voir »
et les KPI. Module pur, registre en mémoire, instants fournis (aucune horloge). Données FICTIVES.
"""

from __future__ import annotations

import pytest
from m1_front_office import reception_interne as rec
from m1_front_office import rendez_vous as rdv
from m1_front_office import suivi
from m1_front_office.registre import Registre

FICTIF = True
T0 = "2026-11-09T09:00:00-05:00"
URGENCE, PLAINTE, RAPPEL = "tr-" + "a" * 20, "tr-" + "b" * 20, "tr-" + "c" * 20
CONV_A, CONV_B, CONV_RAPPEL = "sms-" + "1" * 24, "sms-" + "2" * 24, "sms-" + "3" * 24


def _ouvrir(reg, ident, type_transfert, horodatage, conversation):
    reg.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "ouvert",
            "transfert_id": ident,
            "type_transfert": type_transfert,
            "horodatage": horodatage,
            "conversation_id": conversation,
            "signaux": [],
        }
    )


def _rappel(reg, ident=RAPPEL, conversation=CONV_RAPPEL, horodatage=T0):
    _ouvrir(reg, ident, "ventes", horodatage, conversation)
    reponse = {
        "accepte": True,
        "source": "journal",
        "appel_id": "appel-1",
        "statut": "manque",
        "tache_rappel": {"transfert_id": ident, "statut": "ouvert"},
    }
    reg.ajouter(
        {
            "type_entree": "appel_importe",
            "source": "journal",
            "appel_id": "appel-1",
            "statut": "manque",
            "horodatage": horodatage,
            "reponse": reponse,
        }
    )


def _suivi(reg, conversation, ouverte_le, a_faire_avant, statut="ouverte", horodatage=None):
    action = (
        None
        if statut != "ouverte"
        else {"action": "demander_precisions", "detail": "x", "inscrite_le": ouverte_le, "a_faire_avant": a_faire_avant}
    )
    reg.ajouter(
        {
            "type_entree": "suivi_conversation",
            "conversation_id": conversation,
            "horodatage": horodatage or ouverte_le,
            "ouverte_le": ouverte_le,
            "statut": statut,
            "prochaine_action": action,
            "signal_id": "s",
        }
    )


def _lire(reg, rdv_lignes=(), maintenant="2026-11-09T21:00:00-05:00"):
    return rec.etat_reception(reg.lire(), list(rdv_lignes), maintenant)


# -- l'état
# ----------------------------------------------------------------------------------------------------------------
def test_un_registre_vide_donne_des_zeros_dits_pas_inventes():
    etat = _lire(Registre())
    assert rec.compteurs(etat) == {
        "a_rappeler": 0,
        "a_rappeler_sans_responsable": 0,
        "rappels_echus": 0,
        "rendez_vous_a_confirmer": 0,
        "rappels_rdv_dus": 0,
        "plaintes_ouvertes": 0,
        "urgences_non_prises": 0,
        "sans_suivi": 0,
    }
    assert (
        etat["a_rappeler"]["plus_ancien_minutes"] is None and etat["plaintes_ouvertes"]["plus_ancienne_minutes"] is None
    )


def test_l_etat_compte_les_transferts_ouverts_par_type_et_leur_anciennete_en_minutes_entieres():
    reg = Registre()
    _ouvrir(reg, URGENCE, "urgence", "2026-11-09T20:00:00-05:00", CONV_A)
    _ouvrir(reg, PLAINTE, "plainte", "2026-11-09T18:30:00-05:00", CONV_B)
    etat = _lire(reg)
    assert etat["urgences_ouvertes"] == [{"ref": URGENCE, "depuis_min": 60}]
    assert etat["plaintes_ouvertes"] == {"total": 1, "plus_ancienne_minutes": 150}
    reg.ajouter({"type_entree": "transfert", "evenement": "clos", "transfert_id": URGENCE, "horodatage": T0})
    assert _lire(reg)["urgences_ouvertes"] == []  # un transfert clos n'est plus compté


def test_une_anciennete_ne_devient_jamais_negative_meme_pour_un_instant_futur():
    reg = Registre()
    _ouvrir(reg, URGENCE, "urgence", "2026-11-09T22:00:00-05:00", CONV_A)
    assert _lire(reg)["urgences_ouvertes"][0]["depuis_min"] == 0


@pytest.mark.parametrize("valeur", ["2026-11-09T21:00:00", "pas une date", None, 12])
def test_un_instant_sans_fuseau_ou_illisible_est_refuse(valeur):
    with pytest.raises(ValueError, match="REJ-HORODATAGE-INVALIDE"):
        rec.etat_reception([], [], valeur)


def test_un_rappel_n_est_echu_qu_a_l_echeance_choisie_par_une_personne_inclusivement():
    reg = Registre()
    _rappel(reg)
    assert _lire(reg)["a_rappeler"] == {"total": 1, "sans_responsable": 1, "echus": [], "plus_ancien_minutes": 720}
    from m1_front_office import transferts

    snap = transferts.projection_suivi_rappel(reg.lire(), RAPPEL)["snapshot_suivi"]
    assert snap
    reg.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "prise_en_charge",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": "2026-11-09T09:05:00-05:00",
        }
    )
    reg.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "tentative_sans_contact",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": "2026-11-09T10:00:00-05:00",
            "prochaine_tentative_le": "2026-11-09T14:00:00+00:00",
        }
    )
    avant = _lire(reg, maintenant="2026-11-09T08:59:59-05:00")  # 13 h 59 59 UTC
    egal = _lire(reg, maintenant="2026-11-09T09:00:00-05:00")  # 14 h 00 UTC : l'échéance est atteinte
    assert avant["a_rappeler"]["echus"] == [] and avant["a_rappeler"]["sans_responsable"] == 0
    assert egal["a_rappeler"]["echus"] == [{"ref": RAPPEL, "echeance": "2026-11-09T14:00:00+00:00"}]


def test_un_historique_de_rappel_incoherent_est_dit_pas_interprete():
    reg = Registre()
    _rappel(reg)
    reg.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "tentative_sans_contact",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": T0,
            "prochaine_tentative_le": T0,
        }
    )  # sans prise en charge
    etat = _lire(reg)
    assert etat["historiques_illisibles"] == 1 and etat["a_rappeler"]["total"] == 0


def test_une_conversation_est_sans_suivi_a_la_fin_de_sa_fenetre_inclusivement_et_une_seule_fois_par_correspondant():
    reg = Registre()
    _suivi(reg, CONV_A, "2026-11-09T13:00:00-05:00", "2026-11-09T15:00:00-05:00")
    assert _lire(reg, maintenant="2026-11-09T14:59:59-05:00")["sans_suivi"] == []
    (sans,) = _lire(reg, maintenant="2026-11-09T15:00:00-05:00")["sans_suivi"]
    assert sans["ref"] == CONV_A and sans["a_faire_avant"] == "2026-11-09T15:00:00-05:00"
    # Le même correspondant réécrit plus tard : sa conversation PLUS RÉCENTE remplace l'ancienne.
    _suivi(reg, CONV_A, "2026-11-09T19:00:00-05:00", "2026-11-09T21:00:00-05:00")
    assert _lire(reg, maintenant="2026-11-09T20:00:00-05:00")["sans_suivi"] == []
    # Une conversation fermée (transfert à une personne, retrait STOP) n'est plus à suivre.
    _suivi(reg, CONV_B, "2026-11-09T09:00:00-05:00", "2026-11-09T11:00:00-05:00")
    _suivi(reg, CONV_B, "2026-11-09T09:00:00-05:00", "x", statut="close", horodatage="2026-11-09T09:30:00-05:00")
    assert [x["ref"] for x in _lire(reg)["sans_suivi"]] == [CONV_A]


def test_une_conversation_portee_par_un_transfert_ouvert_n_est_pas_comptee_deux_fois():
    reg = Registre()
    _suivi(reg, CONV_A, "2026-11-09T09:00:00-05:00", "2026-11-09T11:00:00-05:00")
    assert len(_lire(reg)["sans_suivi"]) == 1
    _ouvrir(reg, PLAINTE, "plainte", "2026-11-09T10:00:00-05:00", CONV_A)
    assert _lire(reg)["sans_suivi"] == []
    reg.ajouter({"type_entree": "transfert", "evenement": "clos", "transfert_id": PLAINTE, "horodatage": T0})
    assert len(_lire(reg)["sans_suivi"]) == 1  # clos : la conversation redevient à suivre si elle l'était encore


def test_une_echeance_de_fenetre_illisible_n_est_jamais_devinee():
    reg = Registre()
    reg.ajouter(
        {
            "type_entree": "suivi_conversation",
            "conversation_id": CONV_A,
            "horodatage": T0,
            "ouverte_le": T0,
            "statut": "ouverte",
            "signal_id": "s",
            "prochaine_action": {
                "action": "demander_precisions",
                "detail": "x",
                "inscrite_le": T0,
                "a_faire_avant": "demain matin",
            },
        }
    )
    assert _lire(reg)["sans_suivi"] == []


def test_les_rendez_vous_a_confirmer_et_les_rappels_dus_sont_comptes_sans_double_compte_des_envois_demandes():
    lignes = [
        {
            "type_entree": rdv.TYPE_PROPOSE,
            "horodatage": T0,
            "rdv_id": "rdv-1",
            "motif": "visite_evaluation",
            "duree_minutes": 60,
            "signal_id": "s",
            "options": [],
        },
        {
            "type_entree": rdv.TYPE_RETENU,
            "horodatage": T0,
            "rdv_id": "rdv-1",
            "semaine": "2026-11-16",
            "expire_le": "2026-11-11T09:00:00-05:00",
        },
        {
            "type_entree": rdv.TYPE_PROPOSE,
            "horodatage": T0,
            "rdv_id": "rdv-2",
            "motif": "visite_evaluation",
            "duree_minutes": 60,
            "signal_id": "s",
            "options": [],
        },
        {
            "type_entree": rdv.TYPE_RETENU,
            "horodatage": T0,
            "rdv_id": "rdv-2",
            "semaine": "2026-11-16",
            "expire_le": "2026-11-11T09:00:00-05:00",
        },
        {
            "type_entree": rdv.TYPE_CONFIRME,
            "horodatage": T0,
            "rdv_id": "rdv-2",
            "debut": "2026-11-12T09:00:00-05:00",
            "fin": "2026-11-12T10:00:00-05:00",
        },
        {
            "type_entree": rdv.TYPE_MESSAGE,
            "horodatage": T0,
            "rdv_id": "rdv-2",
            "type": "rappel",
            "cle": "r1",
            "echeance": "2026-11-09T12:00:00-05:00",
            "brouillon_id": "b1",
            "statut": "BROUILLON",
        },
        {
            "type_entree": rdv.TYPE_MESSAGE,
            "horodatage": T0,
            "rdv_id": "rdv-2",
            "type": "rappel",
            "cle": "r2",
            "echeance": "2026-11-09T13:00:00-05:00",
            "brouillon_id": "b2",
            "statut": "BROUILLON",
        },
        {
            "type_entree": rdv.TYPE_MESSAGE,
            "horodatage": T0,
            "rdv_id": "rdv-2",
            "type": "rappel",
            "cle": "r3",
            "echeance": "2026-11-12T08:00:00-05:00",
            "brouillon_id": "b3",
            "statut": "BROUILLON",
        },
    ]
    reg = Registre()
    reg.ajouter(
        {
            "type_entree": "reponse_courriel_v1",
            "horodatage": T0,
            "signal_id": "rdv:x",
            "etape": "demandee",
            "brouillon_id": "b2",
        }
    )  # l'envoi du rappel b2 est déjà demandé
    etat = rec.etat_reception(reg.lire(), lignes, "2026-11-09T21:00:00-05:00")
    assert etat["rendez_vous"] == {"a_confirmer": 1, "rappels_dus": 1}  # rdv-1 retenu ; b1 dû, b2 demandé, b3 pas échu
    expire = rec.etat_reception(reg.lire(), lignes, "2026-11-11T09:00:01-05:00")
    assert expire["rendez_vous"]["a_confirmer"] == 0  # une retenue expirée n'est plus à confirmer


# -- les avis
# -----------------------------------------------------------------------------------------------------------------
def _avis(groupe, reg, existants=(), jour=None, delai=None, maintenant="2026-11-09T21:00:00-05:00", rdv_lignes=()):
    lignes = reg.lire()
    etat = rec.etat_reception(lignes, list(rdv_lignes), maintenant)
    return rec.avis_a_consigner(groupe, etat, existants, lignes=lignes, jour=jour, delai_controle_s=delai)


def test_l_alerte_d_urgence_exige_un_intervalle_complet_de_controle_inclusivement():
    reg = Registre()
    _ouvrir(reg, URGENCE, "urgence", "2026-11-09T20:55:00-05:00", CONV_A)  # 5 min plus tôt
    assert _avis("urgences", reg, delai=301) == []
    (avis,) = _avis("urgences", reg, delai=300)
    assert (
        avis["genre"] == rec.GENRE_URGENCE and avis["ref"] == URGENCE and avis["cle"] == f"urgence_non_prise|{URGENCE}"
    )


def test_un_avis_deja_consigne_n_est_pas_reecrit():
    reg = Registre()
    _ouvrir(reg, URGENCE, "urgence", "2026-11-09T20:00:00-05:00", CONV_A)
    (premier,) = _avis("urgences", reg, delai=300)
    assert _avis("urgences", reg, existants=[rec.ligne_avis(premier, T0)], delai=300) == []


def test_les_echeances_donnent_un_avis_par_rappel_echu_et_par_conversation_sans_suivi_avec_des_cles_distinctes():
    reg = Registre()
    _rappel(reg)
    reg.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "prise_en_charge",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": T0,
        }
    )
    reg.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "tentative_sans_contact",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": T0,
            "prochaine_tentative_le": "2026-11-09T15:00:00+00:00",
        }
    )
    _suivi(reg, CONV_A, "2026-11-09T09:00:00-05:00", "2026-11-09T11:00:00-05:00")
    avis = _avis("echeances", reg)
    assert sorted(a["genre"] for a in avis) == ["rappel_echu", "sans_suivi"]
    assert len({a["cle"] for a in avis}) == 2 and all(a["cle"].startswith(a["genre"]) for a in avis)


def test_les_arguments_obligatoires_manquants_sont_refuses_avec_un_code():
    reg = Registre()
    with pytest.raises(ValueError, match="REJ-RECEPTION-JOUR-REQUIS"):
        _avis("digest", reg)
    with pytest.raises(ValueError, match="REJ-RECEPTION-DELAI-REQUIS"):
        _avis("urgences", reg)
    with pytest.raises(ValueError, match="REJ-RECEPTION-GROUPE-INCONNU"):
        _avis("tout", reg)


def test_le_digest_porte_les_comptes_les_jours_couverts_et_la_grille_existante_du_registre():
    reg = Registre()
    reg.ajouter(
        {
            "type_entree": "signal",
            "canal": "texte",
            "horodatage": "2026-11-08T10:00:00-05:00",
            "signal_id": "s1",
            "conversation_id": CONV_A,
            "contenu_filtre": "x",
        }
    )
    (avis,) = _avis("digest", reg, jour="2026-11-09")
    assert avis["cle"] == "digest|2026-11-09" and avis["jours_couverts"] == ["2026-11-08"]
    assert "DIGEST - Période de référence : 2026-11-08" in avis["grille"] and avis["compteurs"]["a_rappeler"] == 0


def test_les_jours_couverts_ne_sautent_et_ne_repetent_aucun_jour_et_sont_bornes_a_une_semaine():
    digest = lambda jour: {"genre": "digest", "jour": jour}  # noqa: E731
    assert rec.jours_a_couvrir("2026-11-10", []) == ["2026-11-09"]
    assert rec.jours_a_couvrir("2026-11-10", [digest("2026-11-09")]) == ["2026-11-09"]
    assert rec.jours_a_couvrir("2026-11-16", [digest("2026-11-13")]) == ["2026-11-13", "2026-11-14", "2026-11-15"]
    assert len(rec.jours_a_couvrir("2026-12-31", [digest("2026-11-01")])) == rec.JOURS_COUVERTS_MAX
    # un digest du futur ou du même jour ne compte pas comme précédent
    assert rec.jours_a_couvrir("2026-11-10", [digest("2026-11-10"), digest("2026-11-20")]) == ["2026-11-09"]


def test_la_grille_est_bornee():
    lignes = [
        {
            "type_entree": "signal",
            "canal": "texte",
            "horodatage": "2026-11-08T10:00:00-05:00",
            "signal_id": f"s{i}",
            "contenu_filtre": "x",
        }
        for i in range(3)
    ]
    texte = rec.grille(lignes, [f"2026-10-{j:02d}" for j in range(1, 8)] * 30)
    assert len(texte) <= rec.GRILLE_MAX and texte.endswith("…")


# -- les attentes « À voir »
# ------------------------------------------------------------------------------------------------
def test_les_attentes_ont_la_forme_commune_sans_donnee_personnelle_et_un_ordre_par_niveau():
    reg = Registre()
    _ouvrir(reg, URGENCE, "urgence", "2026-11-09T20:00:00-05:00", CONV_A)
    (urgence,) = _avis("urgences", reg, delai=300)
    (digest,) = _avis("digest", reg, jour="2026-11-09")
    avis = [rec.ligne_avis(digest, "2026-11-09T07:00:00-05:00"), rec.ligne_avis(urgence, "2026-11-09T20:06:00-05:00")]
    attentes = rec.attentes(avis, reg.lire())
    assert [a["type"] for a in attentes] == ["digest_reception", "urgence_non_prise"]
    for attente in attentes:
        assert set(attente) == {"type", "id", "resume", "niveau", "depuis", "action_proposee"}
        assert attente["id"].startswith("rec-") and len(attente["id"]) == 24
    assert {a["niveau"] for a in attentes} == {"N3", "N5"}
    assert attentes[1]["depuis"] == "2026-11-09T20:06:00-05:00"


def test_seul_le_dernier_digest_reste_a_voir():
    reg = Registre()
    avis = []
    for jour in ("2026-11-09", "2026-11-10", "2026-11-11"):
        (digest,) = _avis("digest", reg, existants=avis, jour=jour)
        avis.append(rec.ligne_avis(digest, f"{jour}T07:00:00-05:00"))
    (attente,) = rec.attentes(avis, reg.lire())
    assert "2026-11-11" in attente["resume"] and attente["depuis"] == "2026-11-11T07:00:00-05:00"


def test_une_alerte_vit_tant_que_la_situation_est_la_meme_jamais_par_peremption():
    reg = Registre()
    _ouvrir(reg, URGENCE, "urgence", "2026-11-09T20:00:00-05:00", CONV_A)
    _rappel(reg)
    reg.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "prise_en_charge",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": T0,
        }
    )
    reg.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "tentative_sans_contact",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": T0,
            "prochaine_tentative_le": "2026-11-09T15:00:00+00:00",
        }
    )
    _suivi(reg, CONV_B, "2026-11-09T09:00:00-05:00", "2026-11-09T11:00:00-05:00")
    avis = [
        rec.ligne_avis(a, "2026-11-09T21:00:00-05:00")
        for a in _avis("urgences", reg, delai=300) + _avis("echeances", reg)
    ]
    assert sorted(a["type"] for a in rec.attentes(avis, reg.lire())) == [
        "conversation_sans_suivi",
        "rappel_echu",
        "urgence_non_prise",
    ]
    # l'urgence est close par une personne : son alerte sort
    reg.ajouter({"type_entree": "transfert", "evenement": "clos", "transfert_id": URGENCE, "horodatage": T0})
    # une nouvelle tentative (nouvelle échéance) : l'alerte de rappel sort
    reg.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "tentative_sans_contact",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": T0,
            "prochaine_tentative_le": "2026-11-12T15:00:00+00:00",
        }
    )
    # un nouveau message du correspondant : une nouvelle ligne de suivi, l'alerte sort
    _suivi(reg, CONV_B, "2026-11-10T09:00:00-05:00", "2026-11-10T11:00:00-05:00")
    assert rec.attentes(avis, reg.lire()) == []
    # le rappel clos sort aussi, même avec la même échéance
    reg2 = Registre()
    _rappel(reg2)
    reg2.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "prise_en_charge",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": T0,
        }
    )
    reg2.ajouter(
        {
            "type_entree": "transfert",
            "evenement": "tentative_sans_contact",
            "transfert_id": RAPPEL,
            "par": "p",
            "role": "admin",
            "voie": "console",
            "horodatage": T0,
            "prochaine_tentative_le": "2026-11-09T15:00:00+00:00",
        }
    )
    (echu,) = _avis("echeances", reg2)
    avis2 = [rec.ligne_avis(echu, T0)]
    assert len(rec.attentes(avis2, reg2.lire())) == 1
    reg2.ajouter({"type_entree": "transfert", "evenement": "clos", "transfert_id": RAPPEL, "horodatage": T0})
    assert rec.attentes(avis2, reg2.lire()) == []


def test_un_avis_de_genre_inconnu_n_est_jamais_affiche():
    reg = Registre()
    assert (
        rec.attentes([{"type_entree": "avis_reception", "genre": "inconnu", "cle": "x", "horodatage": T0}], reg.lire())
        == []
    )


# -- les KPI
# --------------------------------------------------------------------------------------------------------------------
def test_les_kpi_disent_leur_numerateur_et_leur_denominateur_et_ce_qui_manque():
    reg = Registre()
    for i, jour in enumerate(("2026-11-01", "2026-11-05", "2026-11-09")):
        reg.ajouter(
            {
                "type_entree": "signal",
                "canal": "texte",
                "horodatage": f"{jour}T10:00:00-05:00",
                "signal_id": f"s{i}",
                "conversation_id": CONV_A,
                "contenu_filtre": "x",
            }
        )
    reg.ajouter(
        {
            "type_entree": "lead_emis",
            "canal": "texte",
            "horodatage": "2026-11-05T10:00:00-05:00",
            "signal_id": "s1",
            "conversation_id": CONV_A,
            "lead": {},
            "signaux_rassembles": ["s0", "s1"],
        }
    )
    resultat = rec.kpis(reg.lire(), "2026-11-09", 30)
    assert set(resultat["kpis"]) == set(rec.KPI_IDS)
    assert resultat["kpis"]["taux_signaux_qualifies_pct"] == {
        "calculable": True,
        "valeur_pct": 66.7,
        "numerateur": 2,
        "denominateur": 3,
    }
    assert resultat["fenetre"] == {"debut": "2026-10-11", "fin": "2026-11-09", "jours": 30}
    # fenêtre plus courte : le signal du 1er novembre sort du dénominateur
    court = rec.kpis(reg.lire(), "2026-11-09", 5)["kpis"]["taux_signaux_qualifies_pct"]
    assert (court["numerateur"], court["denominateur"]) == (1, 2)
    vide = rec.kpis(reg.lire(), "2026-12-25", 7)["kpis"]["taux_signaux_qualifies_pct"]
    assert vide["calculable"] is False and "valeur_pct" not in vide
    interdits = resultat["kpis"]["taux_interdits_bloques_pct"]
    assert interdits["calculable"] is False and "valeur_pct" not in interdits and "100 %" in interdits["manque"]


def test_un_signal_rattache_a_un_lead_compte_comme_qualifie():
    reg = Registre()
    reg.ajouter(
        {
            "type_entree": "signal",
            "canal": "texte",
            "horodatage": T0,
            "signal_id": "s1",
            "conversation_id": CONV_A,
            "contenu_filtre": "x",
            "rattache_au_lead": "lead-1",
        }
    )
    assert rec.kpis(reg.lire(), "2026-11-09", 1)["kpis"]["taux_signaux_qualifies_pct"]["valeur_pct"] == 100.0


def test_les_niveaux_de_chaque_genre_et_le_vocabulaire_ferme():
    assert rec.NIVEAUX[rec.GENRE_URGENCE] == "N5" and set(rec.GROUPES) == {"digest", "urgences", "echeances"}
    assert set(rec.NIVEAUX) == set(rec.TYPES_D_ATTENTE) == set(rec.ACTIONS)
    assert suivi.TYPE_SUIVI == "suivi_conversation"
