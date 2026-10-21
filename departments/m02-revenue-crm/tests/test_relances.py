"""PLAN T4.9 (M2.7, M2.13) : les relances dues, leur règle, leur dernière relance, leur prochaine date permise. Module
pur.

Sans base ni horloge : `maintenant` est un argument. Ce qui est prouvé :
- la fréquence maximale vient de la configuration, jamais d'un défaut (absente ou invalide : « à configurer ») ;
- une relance est due quand le segment de T4.6 s'applique, avec sa règle citée, son départ (l'envoi publié par M3,
  jamais une date supposée) et son échéance ;
- la fréquence est celle d'une PERSONNE (les leads d'un même client comptent ensemble), pile à la limite c'est permis,
  un instant plus tôt non, les instants se comparent en UTC ;
- sans consentement actif : « appel seulement » ; un retrait (STOP) prime ;
- la liste est ordonnée, paginée, bornée par la taille de la sortie, sans doublon ni trou ;
- `preparer` refuse dans l'ordre documenté et n'envoie jamais rien (`envoye: False`, texte FIXE).
Données fictives (`fictif: true`) : aucun vrai client, aucun vrai numéro.
"""

from __future__ import annotations

import copy
import json

import pytest
from m2_revenue_crm import consentements, gabarits_relance, relances, segments, verdicts

FICTIF = True

MAINTENANT = "2026-10-20T12:00:00-04:00"  # 16:00 UTC
CONFIG = relances.lire_configuration({"jours_entre_relances": 7})
DEVIS = relances.REGLE_DEVIS
DORMANT = relances.REGLE_DORMANT
ENVOI = "2026-09-25T09:00:00-04:00"  # 13:00 UTC ; + 14 jours = 2026-10-09T13:00:00+00:00
RECUEILLI = "2026-09-20T10:00:00-04:00"
ENREGISTRE = "2026-09-20T10:05:00-04:00"
PREUVE = {"type": "formulaire", "reference": "formulaire-web-2026-09-20-0042"}


# -- fabriques ----------------------------------------------------------------------------------------------
def _seg_devis(devis_id="devis-1", depuis=ENVOI, jours=25, seuil=14):
    return {
        "segment": "quote_stale", "regle": "devis_envoye_sans_reponse_perime",
        "donnee": {"devis_id": devis_id, "statut_devis": "envoye", "horodatage_devis": depuis,
                   "jours_ecoules": jours, "seuil_jours": seuil},
    }


def _seg_dormant(depuis="2026-09-01T09:00:00-04:00", jours=49, seuil=30):
    return {
        "segment": "dormant_lead", "regle": "lead_ouvert_sans_activite",
        "donnee": {"derniere_activite": depuis, "jours_ecoules": jours, "seuil_jours": seuil},
    }


def _lead(lead_id="lead-1", *, statut="qualifie", proprietaire="vendeur.un", client="client-a", segments_=(),
          non_calculables=()):
    return {"lead_id": lead_id, "statut": statut, "proprietaire": proprietaire, "client_id": client,
            "segments": list(segments_), "non_calculables": list(non_calculables)}


def _evaluation(*leads, globaux=(), opportunites=None):
    if opportunites is None:
        opportunites = {}
        for lead in leads:
            if lead["client_id"] is not None:
                opportunites.setdefault(lead["client_id"], []).append(lead["lead_id"])
    return {"leads": list(leads), "non_calculables_globaux": list(globaux), "opportunites_par_client": opportunites}


def _fait_devis(devis_id="devis-1", origine=relances.ORIGINE_DEVIS_ENVOYE, depuis=ENVOI, lead_id="lead-1"):
    return {"devis_id": devis_id, "lead_id": lead_id, "statut_devis": "envoye", "horodatage_devis": depuis,
            "origine": origine}


def _calculer(evaluation, *, maintenant=MAINTENANT, configuration=CONFIG, devis=None, consents=(), retraits=(),
              preparees=()):
    return relances.calculer(
        evaluation, maintenant=maintenant, configuration=configuration,
        devis=[_fait_devis()] if devis is None else devis,
        consentements_contact=consents, retraits=retraits, preparees=preparees)


def _preparee(lead_id="lead-1", le="2026-10-15T12:00:00-04:00", canal="sms", regle=DEVIS):
    return {"type_entree": relances.TYPE_ENTREE, "lead_id": lead_id, "prepare_le": le, "canal": canal, "regle": regle}


def _consentement(canal="sms", lead_id="lead-1", **plus):
    entree, verdict = consentements.construire_consentement(**{
        "lead_id": lead_id, "client_id": "client-a", "canal": canal, "enonce_version": "consentement-v1",
        "source": "formulaire", "preuve": dict(PREUVE), "recueilli_le": RECUEILLI, "enregistre_le": ENREGISTRE,
        "enregistre_par": "vendeur.un", "voie": "appareil", **plus})
    assert verdict is None, verdict
    return entree


def _retrait(lead_id="lead-1", canal="sms", signal="sms:SM-STOP", le="2026-10-18T09:00:00-04:00"):
    entree, verdict = consentements.construire_retrait(lead_id, canal, signal, le)
    assert verdict is None, verdict
    return entree


def _une_relance(calcul, lead_id="lead-1", regle=DEVIS):
    (item,) = [i for i in calcul["relances"] if i["lead_id"] == lead_id and i["regle"] == regle]
    return item


# ---------------------------------------------------------------------------------------------------------
# La configuration : la fréquence maximale, jamais un défaut
# ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("brut", [None, {}, {"autre_cle": 3}, {"jours_entre_relances": None}])
def test_une_frequence_absente_est_a_configurer_et_ne_vaut_rien(brut):
    assert relances.lire_configuration(brut) == {"jours_entre_relances": {"etat": "a_configurer", "valeur": None}}


@pytest.mark.parametrize("valeur", [1, 7, 30, 365])
def test_une_frequence_entiere_d_au_moins_un_jour_est_valide(valeur):
    assert relances.lire_configuration({"jours_entre_relances": valeur}) == {
        "jours_entre_relances": {"etat": "ok", "valeur": valeur}}


@pytest.mark.parametrize("valeur", [0, -1, -7, True, False, "7", 7.0, 7.5, [7], {}, {"jours": 7}, ""])
def test_une_frequence_invalide_est_dite_invalide_jamais_corrigee(valeur):
    assert relances.lire_configuration({"jours_entre_relances": valeur}) == {
        "jours_entre_relances": {"etat": "invalide", "valeur": None}}


@pytest.mark.parametrize("brut", ["sept", [7], 7, True])
def test_un_bloc_illisible_est_invalide_meme_sans_la_cle(brut):
    assert relances.lire_configuration(brut) == {"jours_entre_relances": {"etat": "invalide", "valeur": None}}


def test_le_chemin_et_la_cle_de_la_configuration_sont_ceux_de_department_yaml():
    assert relances.CLE_JOURS_ENTRE_RELANCES == "jours_entre_relances"
    assert relances.CHEMIN_CONFIGURATION == "configuration.relances"


def test_une_frequence_valide_ne_donne_aucun_verdict():
    assert relances.verifier_configuration(CONFIG) is None


def test_une_frequence_absente_donne_un_verdict_qui_dit_quoi_configurer():
    verdict = relances.verifier_configuration(relances.lire_configuration({}))
    assert verdict["code"] == "REJ-RELANCES-A-CONFIGURER"
    assert "à configurer" in verdict["detail"] and "jours_entre_relances" in verdict["detail"]
    assert "configuration.relances" in verdict["detail"] and "aucune valeur n'est supposée" in verdict["detail"].lower()


def test_une_frequence_invalide_donne_un_verdict_qui_le_dit():
    verdict = relances.verifier_configuration(relances.lire_configuration({"jours_entre_relances": 0}))
    assert verdict["code"] == "REJ-RELANCES-A-CONFIGURER"
    assert "invalide" in verdict["detail"] and "jours_entre_relances" in verdict["detail"]
    assert "à configurer" not in verdict["detail"]


def test_une_configuration_sans_la_cle_est_a_configurer_jamais_ok():
    assert relances.verifier_configuration({})["code"] == "REJ-RELANCES-A-CONFIGURER"


# ---------------------------------------------------------------------------------------------------------
# devis_connus : l'envoi publié par M3 l'emporte sur le constat de M3
# ---------------------------------------------------------------------------------------------------------
def test_un_constat_de_m3_sans_envoi_reste_tel_quel_avec_son_origine():
    constat = {"devis_id": "d1", "lead_id": "l1", "statut_devis": "envoye", "horodatage_devis": ENVOI,
               "delai_relance_jours": 14, "client_id": "client-a"}
    (connu,) = relances.devis_connus([constat], [])
    assert connu == {**constat, "origine": "m3.devis_sans_reponse"}


def test_un_envoi_de_m3_devient_un_devis_envoye_a_l_instant_de_l_envoi():
    envoi = {"devis_id": "d1", "lead_id": "l1", "chantier_id": None, "horodatage_envoi": ENVOI, "client_id": "client-a"}
    (connu,) = relances.devis_connus([], [envoi])
    assert connu == {"devis_id": "d1", "lead_id": "l1", "statut_devis": "envoye", "horodatage_devis": ENVOI,
                     "origine": "m3.devis_envoye"}


def test_l_envoi_l_emporte_sur_un_constat_brouillon_du_meme_devis():
    constat = {"devis_id": "d1", "lead_id": "l1", "statut_devis": "brouillon",
               "horodatage_devis": "2026-09-01T09:00:00-04:00"}
    envoi = {"devis_id": "d1", "lead_id": "l1", "horodatage_envoi": ENVOI}
    (connu,) = relances.devis_connus([constat], [envoi])
    assert connu["statut_devis"] == "envoye" and connu["horodatage_devis"] == ENVOI
    assert connu["origine"] == "m3.devis_envoye"


def test_deux_devis_donnent_deux_entrees_dans_l_ordre_de_premiere_apparition():
    constats = [{"devis_id": "d2", "lead_id": "l1", "statut_devis": "envoye", "horodatage_devis": ENVOI}]
    envois = [{"devis_id": "d1", "lead_id": "l1", "horodatage_envoi": ENVOI},
              {"devis_id": "d2", "lead_id": "l1", "horodatage_envoi": "2026-09-26T09:00:00-04:00"}]
    connus = relances.devis_connus(constats, envois)
    assert [c["devis_id"] for c in connus] == ["d2", "d1"]
    assert connus[0]["horodatage_devis"] == "2026-09-26T09:00:00-04:00"


def test_devis_connus_ne_modifie_pas_ses_entrees():
    constats = [{"devis_id": "d1", "lead_id": "l1", "statut_devis": "envoye", "horodatage_devis": ENVOI}]
    envois = [{"devis_id": "d1", "lead_id": "l1", "horodatage_envoi": ENVOI}]
    avant = copy.deepcopy((constats, envois))
    relances.devis_connus(constats, envois)
    assert (constats, envois) == avant
    assert relances.devis_connus([], []) == []


# ---------------------------------------------------------------------------------------------------------
# calculer : une relance due, sa règle, son départ, son échéance
# ---------------------------------------------------------------------------------------------------------
def test_un_devis_envoye_sans_reponse_donne_une_relance_avec_sa_regle_son_depart_et_son_echeance():
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_devis()])))
    item = _une_relance(calcul)
    assert item == {
        "lead_id": "lead-1", "statut": "qualifie", "proprietaire": "vendeur.un", "regle": "relance_devis_sans_reponse",
        "segment": _seg_devis(),
        "depart": {
            "fait": "m3.devis_envoye", "instant": ENVOI,
            "remarque": (
                "instant de l'approbation de l'envoi par le propriétaire, pas de la livraison au client (T2.1-c)"
            ),
        },
        "due_depuis": "2026-10-09T13:00:00+00:00",
        "derniere_relance": None, "prochaine_date_permise": None, "permise_maintenant": True,
        "mode": "appel_seulement", "canaux_permis": ["appel"],
        "consentements": {"sms": {"etat": "absent"}, "courriel": {"etat": "absent"}},
    }
    assert calcul["jours_entre_relances"] == 7 and calcul["indetermines"] == 0
    assert calcul["regles_non_calculables"] == []


def test_l_echeance_est_le_depart_plus_le_seuil_du_segment_en_utc():
    for seuil, attendue in ((14, "2026-10-09T13:00:00+00:00"), (1, "2026-09-26T13:00:00+00:00"),
                            (30, "2026-10-25T13:00:00+00:00")):
        item = _une_relance(_calculer(
            _evaluation(_lead(segments_=[_seg_devis(seuil=seuil)])), maintenant="2026-12-01T12:00:00-04:00"))
        assert item["due_depuis"] == attendue, seuil


def test_le_depart_d_un_devis_vient_de_l_envoi_de_m3_et_dit_la_limite_de_la_livraison():
    item = _une_relance(_calculer(_evaluation(_lead(segments_=[_seg_devis()]))))
    assert item["depart"]["fait"] == "m3.devis_envoye" and item["depart"]["instant"] == ENVOI
    assert "pas de la livraison au client" in item["depart"]["remarque"] and "T2.1-c" in item["depart"]["remarque"]


def test_le_depart_d_un_devis_constate_par_m3_n_a_pas_de_remarque_de_livraison():
    constat = [_fait_devis(origine="m3.devis_sans_reponse")]
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_devis()])), devis=constat)
    assert _une_relance(calcul)["depart"] == {"fait": "m3.devis_sans_reponse", "instant": ENVOI}


def test_un_devis_dont_l_origine_est_inconnue_reste_une_relance_avec_un_depart_sans_fait():
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_devis()])), devis=[])
    assert _une_relance(calcul)["depart"] == {"fait": None, "instant": ENVOI}
    illisibles = relances.calculer(
        _evaluation(_lead(segments_=[_seg_devis()])), maintenant=MAINTENANT, configuration=CONFIG, devis=None,
        consentements_contact=[], retraits=[], preparees=[])
    assert _une_relance(illisibles)["depart"]["fait"] is None


def test_un_lead_dormant_donne_une_relance_dont_le_depart_est_la_derniere_activite_humaine():
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_dormant()])))
    item = _une_relance(calcul, regle=DORMANT)
    assert item["regle"] == "relance_lead_dormant"
    assert item["depart"] == {"fait": "derniere_activite_humaine", "instant": "2026-09-01T09:00:00-04:00"}
    assert item["due_depuis"] == "2026-10-01T13:00:00+00:00"
    assert item["segment"] == _seg_dormant()


def test_un_lead_sans_segment_de_relance_n_a_aucune_relance():
    autre = {"segment": "hot_lead", "regle": "urgence_declaree_lead_ouvert", "donnee": {"urgence_declaree": True}}
    calcul = _calculer(_evaluation(_lead(segments_=[autre]), _lead("lead-2")))
    assert calcul["relances"] == []


def test_un_lead_peut_avoir_les_deux_relances_ordonnees_par_echeance():
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_devis(), _seg_dormant()])))
    assert [i["regle"] for i in calcul["relances"]] == [DORMANT, DEVIS]  # 2026-10-01 puis 2026-10-09


def test_les_regles_sont_les_deux_relances_dont_m2_tient_les_faits_avec_leur_segment():
    assert set(relances.REGLES) == {"relance_devis_sans_reponse", "relance_lead_dormant"}
    assert all(relances.REGLES[r].strip() for r in relances.REGLES)
    assert relances.STATUTS_A_RELANCER == ("nouveau", "qualifie")


# ---------------------------------------------------------------------------------------------------------
# calculer : la fréquence est celle d'une personne
# ---------------------------------------------------------------------------------------------------------
def test_jamais_relance_aucune_contrainte_de_frequence():
    item = _une_relance(_calculer(_evaluation(_lead(segments_=[_seg_devis()])), preparees=[]))
    assert item["derniere_relance"] is None and item["prochaine_date_permise"] is None
    assert item["permise_maintenant"] is True


def test_la_derniere_relance_et_la_prochaine_date_permise_sont_dites():
    preparees = [_preparee(le="2026-10-15T12:00:00-04:00", canal="sms")]
    item = _une_relance(_calculer(_evaluation(_lead(segments_=[_seg_devis()])), preparees=preparees))
    assert item["derniere_relance"] == {"le": "2026-10-15T12:00:00-04:00", "canal": "sms"}
    assert item["prochaine_date_permise"] == "2026-10-22T16:00:00+00:00"
    assert item["permise_maintenant"] is False


def test_pile_a_la_prochaine_date_permise_la_relance_est_permise_une_seconde_plus_tot_non():
    preparees = [_preparee(le="2026-10-15T12:00:00-04:00")]  # + 7 jours = 2026-10-22T16:00:00 UTC
    evaluation = _evaluation(_lead(segments_=[_seg_devis()]))
    pile = _une_relance(_calculer(evaluation, maintenant="2026-10-22T16:00:00+00:00", preparees=preparees))
    avant = _une_relance(_calculer(evaluation, maintenant="2026-10-22T15:59:59+00:00", preparees=preparees))
    apres = _une_relance(_calculer(evaluation, maintenant="2026-10-22T16:00:01+00:00", preparees=preparees))
    assert pile["permise_maintenant"] is True and apres["permise_maintenant"] is True
    assert avant["permise_maintenant"] is False
    assert pile["prochaine_date_permise"] == avant["prochaine_date_permise"] == "2026-10-22T16:00:00+00:00"


@pytest.mark.parametrize(("jours", "instant", "permise"), [
    (1, "2026-10-16T15:59:59+00:00", False), (1, "2026-10-16T16:00:00+00:00", True),
    (3, "2026-10-18T16:00:00+00:00", True), (3, "2026-10-18T15:59:59+00:00", False),
    (30, "2026-11-14T16:00:00+00:00", True), (30, "2026-11-14T15:59:59+00:00", False),
])
def test_la_frequence_configuree_est_celle_qui_s_applique(jours, instant, permise):
    item = _une_relance(_calculer(
        _evaluation(_lead(segments_=[_seg_devis()])), maintenant=instant,
        configuration=relances.lire_configuration({"jours_entre_relances": jours}),
        preparees=[_preparee(le="2026-10-15T12:00:00-04:00")]))
    assert item["permise_maintenant"] is permise


def test_la_derniere_relance_se_lit_en_utc_pas_en_texte():
    # 12:59 UTC est plus tôt que 09:00 -04:00 (13:00 UTC), même si son texte se range après « 09:00:00-04:00 ».
    preparees = [_preparee(le="2026-10-15T09:00:00-04:00", canal="sms"),
                 _preparee(le="2026-10-15T12:59:00+00:00", canal="courriel")]
    item = _une_relance(_calculer(_evaluation(_lead(segments_=[_seg_devis()])), preparees=preparees))
    assert item["derniere_relance"] == {"le": "2026-10-15T09:00:00-04:00", "canal": "sms"}
    inverse = _une_relance(_calculer(_evaluation(_lead(segments_=[_seg_devis()])), preparees=preparees[::-1]))
    assert inverse["derniere_relance"] == {"le": "2026-10-15T09:00:00-04:00", "canal": "sms"}


def test_la_plus_recente_des_relances_prepare_la_prochaine_date_et_a_egalite_la_derniere_ecrite():
    evaluation = _evaluation(_lead(segments_=[_seg_devis()]))
    preparees = [_preparee(le="2026-10-10T12:00:00-04:00", canal="appel"),
                 _preparee(le="2026-10-16T12:00:00-04:00", canal="sms")]
    item = _une_relance(_calculer(evaluation, preparees=preparees))
    assert item["derniere_relance"]["canal"] == "sms" and item["prochaine_date_permise"] == "2026-10-23T16:00:00+00:00"
    egales = [_preparee(le="2026-10-16T12:00:00-04:00", canal="appel"),
              _preparee(le="2026-10-16T12:00:00-04:00", canal="courriel")]
    assert _une_relance(_calculer(evaluation, preparees=egales))["derniere_relance"]["canal"] == "courriel"


def test_une_relance_d_un_autre_lead_du_meme_client_limite_la_frequence_sans_dire_lequel():
    evaluation = _evaluation(_lead("lead-1", segments_=[_seg_devis()]), _lead("lead-2", segments_=[_seg_dormant()]),
                             opportunites={"client-a": ["lead-1", "lead-2"]})
    preparees = [_preparee("lead-2", le="2026-10-15T12:00:00-04:00", canal="courriel", regle=DORMANT)]
    calcul = _calculer(evaluation, preparees=preparees)
    for item in calcul["relances"]:
        assert item["permise_maintenant"] is False
        assert item["derniere_relance"] == {"le": "2026-10-15T12:00:00-04:00", "canal": "courriel"}
        assert set(item["derniere_relance"]) == {"le", "canal"}, "ni le lead, ni la règle d'un autre dossier"
        assert item["prochaine_date_permise"] == "2026-10-22T16:00:00+00:00"


def test_une_relance_d_un_autre_client_ne_limite_pas_celui_ci():
    evaluation = _evaluation(_lead("lead-1", client="client-a", segments_=[_seg_devis()]),
                             _lead("lead-2", client="client-b", segments_=[_seg_devis("devis-2")]))
    preparees = [_preparee("lead-2", le="2026-10-19T12:00:00-04:00")]
    calcul = _calculer(evaluation, preparees=preparees, devis=[_fait_devis(), _fait_devis("devis-2")])
    assert _une_relance(calcul, "lead-1")["permise_maintenant"] is True
    assert _une_relance(calcul, "lead-2")["permise_maintenant"] is False


def test_un_lead_sans_client_n_est_limite_que_par_ses_propres_relances():
    evaluation = _evaluation(_lead("lead-1", client=None, segments_=[_seg_devis()]),
                             _lead("lead-2", client=None, segments_=[_seg_devis("devis-2")]))
    calcul = _calculer(evaluation, preparees=[_preparee("lead-2", le="2026-10-19T12:00:00-04:00")],
                       devis=[_fait_devis(), _fait_devis("devis-2")])
    assert _une_relance(calcul, "lead-1")["permise_maintenant"] is True
    assert _une_relance(calcul, "lead-2")["permise_maintenant"] is False


def test_les_relances_des_leads_invisibles_du_meme_client_comptent_dans_la_frequence():
    # Le vendeur n'évalue que son lead (les autres ne sont pas dans `leads`), mais le client a d'autres opportunités.
    evaluation = _evaluation(_lead("lead-1", segments_=[_seg_devis()]),
                             opportunites={"client-a": ["lead-1", "lead-autre"]})
    calcul = _calculer(evaluation, preparees=[_preparee("lead-autre", le="2026-10-19T12:00:00-04:00")])
    assert _une_relance(calcul)["permise_maintenant"] is False


def test_une_entree_d_historique_d_un_autre_type_de_lead_ou_sans_lead_est_ignoree():
    preparees = [_preparee("lead-9", le="2026-10-19T12:00:00-04:00"), {"type_entree": "autre", "lead_id": "lead-9"}]
    assert _une_relance(_calculer(_evaluation(_lead(segments_=[_seg_devis()])), preparees=preparees)
                        )["permise_maintenant"] is True


# ---------------------------------------------------------------------------------------------------------
# calculer : le consentement
# ---------------------------------------------------------------------------------------------------------
def test_sans_consentement_actif_la_relance_est_appel_seulement():
    item = _une_relance(_calculer(_evaluation(_lead(segments_=[_seg_devis()]))))
    assert item["mode"] == relances.MODE_APPEL_SEULEMENT == "appel_seulement"
    assert item["canaux_permis"] == ["appel"]


def test_un_consentement_actif_ouvre_son_canal_et_le_mode_devient_appel_ou_message():
    evaluation = _evaluation(_lead(segments_=[_seg_devis()]))
    item = _une_relance(_calculer(evaluation, consents=[_consentement("sms")]))
    assert item["mode"] == relances.MODE_APPEL_OU_MESSAGE == "appel_ou_message"
    assert item["canaux_permis"] == ["appel", "sms"]
    assert item["consentements"]["sms"]["etat"] == "actif" and item["consentements"]["courriel"] == {"etat": "absent"}
    assert item["consentements"]["sms"]["enonce_version"] == "consentement-v1"


def test_le_consentement_d_un_autre_lead_du_meme_client_vaut_pour_ce_lead():
    evaluation = _evaluation(_lead("lead-1", segments_=[_seg_devis()]), _lead("lead-2"),
                             opportunites={"client-a": ["lead-1", "lead-2"]})
    item = _une_relance(_calculer(evaluation, consents=[_consentement("courriel", lead_id="lead-2")]))
    assert item["canaux_permis"] == ["appel", "courriel"]


def test_le_consentement_d_un_autre_client_ne_vaut_pas():
    evaluation = _evaluation(_lead("lead-1", segments_=[_seg_devis()]), _lead("lead-2", client="client-b"))
    item = _une_relance(_calculer(evaluation, consents=[_consentement("sms", lead_id="lead-2")]))
    assert item["canaux_permis"] == ["appel"]


def test_un_retrait_ferme_les_canaux_ecrits_meme_avec_un_consentement_et_la_relance_reste_par_appel():
    evaluation = _evaluation(_lead(segments_=[_seg_devis()]))
    item = _une_relance(_calculer(
        evaluation, consents=[_consentement("sms"), _consentement("courriel")], retraits=[_retrait(canal="sms")]))
    assert item["canaux_permis"] == ["appel"] and item["mode"] == "appel_seulement"
    assert item["consentements"]["sms"]["etat"] == item["consentements"]["courriel"]["etat"] == "retire"
    assert item["consentements"]["sms"]["source"] == "bus:m1.retrait_consentement"
    assert item["permise_maintenant"] is True, "un retrait n'interdit pas l'appel"


def test_le_retrait_d_un_lead_du_meme_client_ferme_les_canaux_de_ce_lead():
    evaluation = _evaluation(_lead("lead-1", segments_=[_seg_devis()]), _lead("lead-2"),
                             opportunites={"client-a": ["lead-1", "lead-2"]})
    item = _une_relance(_calculer(
        evaluation, consents=[_consentement("sms", lead_id="lead-1")], retraits=[_retrait(lead_id="lead-2")]))
    assert item["canaux_permis"] == ["appel"]


# ---------------------------------------------------------------------------------------------------------
# calculer : l'ordre, ce qui manque
# ---------------------------------------------------------------------------------------------------------
def test_l_ordre_est_l_echeance_croissante_en_utc_puis_le_lead_puis_la_regle():
    evaluation = _evaluation(
        _lead("lead-c", client="c", segments_=[_seg_devis("d-c", depuis="2026-09-20T09:00:00-04:00")]),
        _lead("lead-b", client="b", segments_=[_seg_devis("d-b", depuis="2026-09-25T09:00:00-04:00")]),
        _lead("lead-a", client="a", segments_=[_seg_devis("d-a", depuis="2026-09-25T09:00:00-04:00")]),
        _lead("lead-d", client="d", segments_=[_seg_devis("d-d", depuis="2026-09-25T12:59:00+00:00")]),
    )
    devis = [_fait_devis(f"d-{x}", lead_id=f"lead-{x}") for x in "abcd"]
    calcul = _calculer(evaluation, devis=devis)
    # d-d (12:59 UTC) précède d-a et d-b (13:00 UTC), même si son texte se range après.
    assert [i["lead_id"] for i in calcul["relances"]] == ["lead-c", "lead-d", "lead-a", "lead-b"]


def test_a_echeance_egale_la_regle_departage():
    evaluation = _evaluation(_lead("lead-1", segments_=[
        _seg_devis(depuis="2026-09-25T09:00:00-04:00", seuil=14),
        _seg_dormant(depuis="2026-09-09T09:00:00-04:00", seuil=30),
    ]))
    # 25 sept + 14 j = 9 oct 13:00 UTC ; 9 sept + 30 j = 9 oct 13:00 UTC : même échéance, la règle départage.
    calcul = _calculer(evaluation)
    assert [i["due_depuis"] for i in calcul["relances"]] == ["2026-10-09T13:00:00+00:00"] * 2
    assert [i["regle"] for i in calcul["relances"]] == sorted([DEVIS, DORMANT])


def test_une_regle_non_calculable_pour_tous_ne_rend_aucune_relance_et_dit_ce_qui_manque():
    manque = "non calculable, manque le seuil jours_soumission_perimee : seuil à configurer"
    globaux = [{"segment": "quote_stale", "manque": manque}]
    evaluation = _evaluation(_lead(segments_=[_seg_devis(), _seg_dormant()]), globaux=globaux)
    calcul = _calculer(evaluation)
    assert [i["regle"] for i in calcul["relances"]] == [DORMANT], "la règle calculable suit son cours"
    assert calcul["regles_non_calculables"] == [
        {"regle": DEVIS, "segment": "quote_stale", "manque": globaux[0]["manque"]}]


def test_les_deux_regles_non_calculables_sont_dites_dans_l_ordre_des_regles():
    globaux = [{"segment": "dormant_lead", "manque": "M-dormant"}, {"segment": "quote_stale", "manque": "M-devis"},
               {"segment": "needs_photos", "manque": "M-photos"}]
    calcul = _calculer(_evaluation(_lead(), globaux=globaux))
    assert calcul["relances"] == []
    assert [(n["regle"], n["manque"]) for n in calcul["regles_non_calculables"]] == [
        (DEVIS, "M-devis"), (DORMANT, "M-dormant")]


def test_un_segment_illisible_pour_un_lead_est_compte_indetermine_pas_invente():
    evaluation = _evaluation(
        _lead("lead-1", segments_=[_seg_devis()]),
        _lead("lead-2", client="client-b", non_calculables=[{"segment": "dormant_lead", "manque": "date illisible"}]),
        _lead("lead-3", client="client-c", non_calculables=[
            {"segment": "quote_stale", "manque": "horodatage illisible"},
            {"segment": "dormant_lead", "manque": "date illisible"},
            {"segment": "estimate_ready", "manque": "sans rapport"}]),
    )
    calcul = _calculer(evaluation)
    assert [i["lead_id"] for i in calcul["relances"]] == ["lead-1"]
    assert calcul["indetermines"] == 3


def test_le_calcul_est_deterministe_et_ne_modifie_pas_ses_entrees():
    evaluation = _evaluation(_lead(segments_=[_seg_devis(), _seg_dormant()]), _lead("lead-2", client="b"))
    consents, retraits, preparees = [_consentement()], [_retrait(lead_id="lead-9")], [_preparee()]
    devis = [_fait_devis()]
    avant = copy.deepcopy((evaluation, consents, retraits, preparees, devis))
    premier = _calculer(evaluation, devis=devis, consents=consents, retraits=retraits, preparees=preparees)
    second = _calculer(evaluation, devis=devis, consents=consents, retraits=retraits, preparees=preparees)
    assert premier == second
    assert (evaluation, consents, retraits, preparees, devis) == avant


def test_un_horodatage_de_reference_sans_fuseau_est_refuse_par_le_calcul():
    with pytest.raises(ValueError, match="sans fuseau"):
        _calculer(_evaluation(_lead(segments_=[_seg_devis()])), maintenant="2026-10-20T12:00:00")


# ---------------------------------------------------------------------------------------------------------
# valider_demande
# ---------------------------------------------------------------------------------------------------------
def _demande(**surcharges):
    arguments = {"regle": None, "permises_seulement": False, "decalage": 0, "limite": 10, "maintenant": MAINTENANT}
    arguments.update(surcharges)
    return relances.valider_demande(**arguments)


def test_une_demande_valide_ne_donne_aucun_verdict():
    assert _demande() is None
    assert _demande(regle=DEVIS, permises_seulement=True, decalage=40, limite=30) is None


@pytest.mark.parametrize(("surcharge", "code"), [
    ({"regle": "inconnue"}, "REJ-ENUM-INVALIDE"), ({"regle": 5}, "REJ-ENUM-INVALIDE"),
    ({"permises_seulement": "oui"}, "REJ-ENUM-INVALIDE"), ({"permises_seulement": 1}, "REJ-ENUM-INVALIDE"),
    ({"permises_seulement": None}, "REJ-ENUM-INVALIDE"),
    ({"decalage": -1}, "REJ-PAGINATION-INVALIDE"), ({"decalage": True}, "REJ-PAGINATION-INVALIDE"),
    ({"decalage": "0"}, "REJ-PAGINATION-INVALIDE"), ({"decalage": 1.5}, "REJ-PAGINATION-INVALIDE"),
    ({"limite": 0}, "REJ-PAGINATION-INVALIDE"), ({"limite": 31}, "REJ-PAGINATION-INVALIDE"),
    ({"limite": True}, "REJ-PAGINATION-INVALIDE"), ({"limite": "10"}, "REJ-PAGINATION-INVALIDE"),
    ({"maintenant": "hier"}, "REJ-HORODATAGE-INVALIDE"),
    ({"maintenant": "2026-10-20T12:00:00"}, "REJ-HORODATAGE-INVALIDE"),
    ({"maintenant": None}, "REJ-HORODATAGE-INVALIDE"), ({"maintenant": 3}, "REJ-HORODATAGE-INVALIDE"),
])
def test_une_demande_invalide_dit_quoi_corriger(surcharge, code):
    verdict = _demande(**surcharge)
    assert verdict is not None and verdict["code"] == code
    assert verdicts.est_verdict(verdict["code"]) and verdict["detail"]


def test_la_limite_de_page_est_bornee_a_trente_avec_un_defaut_de_dix():
    assert (relances.LIMITE_DEFAUT, relances.LIMITE_MAX) == (10, 30)
    assert _demande(limite=1) is None and _demande(limite=30) is None


# ---------------------------------------------------------------------------------------------------------
# lister : pages
# ---------------------------------------------------------------------------------------------------------
def _beaucoup(n, *, dormants=0):
    leads, devis = [], []
    for i in range(n):
        lead_id = f"lead-{i:03d}"
        depuis = f"2026-09-{1 + i % 20:02d}T09:00:00-04:00"
        segs = [_seg_devis(f"devis-{i:03d}", depuis=depuis)]
        if i < dormants:
            segs.append(_seg_dormant())
        leads.append(_lead(lead_id, client=f"client-{i:03d}", segments_=segs))
        devis.append(_fait_devis(f"devis-{i:03d}", depuis=depuis, lead_id=lead_id))
    return _evaluation(*leads), devis


def _page(calcul, **surcharges):
    arguments = {"budget_caracteres": 1_000_000}
    arguments.update(surcharges)
    page, verdict = relances.lister(calcul, **arguments)
    assert verdict is None, verdict
    return page


def test_une_liste_vide_est_une_page_vide_sans_suite():
    calcul = _calculer(_evaluation(_lead()))
    page = _page(calcul)
    assert page["relances"] == [] and page["total"] == 0 and page["suivant"] is None and page["reste"] == 0
    assert page["message"] is None and page["affichees"] == 0


def test_les_pages_se_recollent_sans_doublon_ni_trou():
    evaluation, devis = _beaucoup(25)
    calcul = _calculer(evaluation, devis=devis)
    lues, decalage = [], 0
    while True:
        page = _page(calcul, decalage=decalage, limite=10)
        assert page["total"] == 25 and page["decalage"] == decalage
        lues.extend(i["lead_id"] for i in page["relances"])
        if page["suivant"] is None:
            break
        assert page["suivant"] == decalage + page["affichees"]
        assert page["reste"] == 25 - page["suivant"]
        decalage = page["suivant"]
    assert lues == [i["lead_id"] for i in calcul["relances"]] and len(set(lues)) == 25


def test_la_premiere_page_dit_ce_qui_reste_et_comment_poursuivre():
    evaluation, devis = _beaucoup(25)
    page = _page(_calculer(evaluation, devis=devis), limite=10)
    assert (page["affichees"], page["reste"], page["suivant"]) == (10, 15, 10)
    assert page["message"] == "15 autres relances non affichées : poursuivre avec decalage=10."
    derniere = _page(_calculer(evaluation, devis=devis), decalage=24, limite=10)
    assert (derniere["affichees"], derniere["reste"], derniere["suivant"]) == (1, 0, None)
    avant_derniere = _page(_calculer(evaluation, devis=devis), decalage=24, limite=1)
    assert avant_derniere["message"] is None
    une_de_plus = _page(_calculer(evaluation, devis=devis), decalage=23, limite=1)
    assert une_de_plus["message"] == "1 autre relance non affichée : poursuivre avec decalage=24."


def test_un_decalage_au_dela_de_la_fin_rend_une_page_vide_pas_une_erreur():
    evaluation, devis = _beaucoup(5)
    page = _page(_calculer(evaluation, devis=devis), decalage=99)
    assert page["relances"] == [] and page["suivant"] is None and page["total"] == 5 and page["reste"] == 0
    exact = _page(_calculer(evaluation, devis=devis), decalage=5)
    assert exact["relances"] == [] and exact["suivant"] is None


def test_la_page_tient_dans_le_budget_de_sortie_et_porte_toujours_une_relance():
    evaluation, devis = _beaucoup(20)
    calcul = _calculer(evaluation, devis=devis)
    tout = _page(calcul, limite=30)
    taille_une = len(json.dumps(_page(calcul, limite=1), ensure_ascii=False))
    for budget in (taille_une + 1, 2500, 4000, 5900):
        page = _page(calcul, limite=30, budget_caracteres=budget)
        assert len(json.dumps(page, ensure_ascii=False)) <= budget
        assert 1 <= page["affichees"] < tout["affichees"] or budget >= len(json.dumps(tout, ensure_ascii=False))
    minuscule = _page(calcul, limite=30, budget_caracteres=10)
    assert minuscule["affichees"] == 1, "une page vide ne ferait jamais progresser la lecture"
    assert minuscule["suivant"] == 1


def test_un_budget_plus_grand_de_un_caractere_laisse_place_a_une_relance_de_plus():
    evaluation, devis = _beaucoup(6)
    calcul = _calculer(evaluation, devis=devis)
    trois = len(json.dumps(_page(calcul, limite=3), ensure_ascii=False))
    assert _page(calcul, limite=6, budget_caracteres=trois)["affichees"] == 3
    assert _page(calcul, limite=6, budget_caracteres=trois - 1)["affichees"] == 2


def test_le_filtre_par_regle_ne_garde_que_cette_regle_et_total_compte_le_filtre():
    evaluation, devis = _beaucoup(6, dormants=2)
    calcul = _calculer(evaluation, devis=devis)
    assert _page(calcul)["total"] == 8
    dormants = _page(calcul, regle=DORMANT)
    assert dormants["total"] == 2 and {i["regle"] for i in dormants["relances"]} == {DORMANT}
    assert dormants["filtre"] == {"regle": DORMANT, "permises_seulement": False}
    assert _page(calcul, regle=DEVIS)["total"] == 6


def test_le_filtre_permises_seulement_ecarte_celles_que_la_frequence_interdit():
    evaluation, devis = _beaucoup(4)
    calcul = _calculer(evaluation, devis=devis, preparees=[_preparee("lead-001", le="2026-10-19T12:00:00-04:00")])
    assert _page(calcul)["total"] == 4
    permises = _page(calcul, permises_seulement=True)
    assert permises["total"] == 3 and "lead-001" not in {i["lead_id"] for i in permises["relances"]}
    assert permises["filtre"]["permises_seulement"] is True


def test_les_deux_filtres_se_combinent():
    evaluation, devis = _beaucoup(4, dormants=4)
    calcul = _calculer(evaluation, devis=devis, preparees=[_preparee("lead-002", le="2026-10-19T12:00:00-04:00")])
    page = _page(calcul, regle=DORMANT, permises_seulement=True)
    assert page["total"] == 3 and {i["regle"] for i in page["relances"]} == {DORMANT}


def test_un_filtre_sur_une_regle_non_calculable_est_refuse_avec_ce_qui_manque():
    globaux = [{"segment": "quote_stale", "manque": "non calculable, manque le seuil : seuil à configurer"}]
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_devis()]), globaux=globaux))
    page, verdict = relances.lister(calcul, regle=DEVIS, budget_caracteres=1_000_000)
    assert page is None and verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE"
    assert "relance_devis_sans_reponse" in verdict["detail"] and "seuil à configurer" in verdict["detail"]
    sans_filtre = _page(calcul)
    assert sans_filtre["regles_non_calculables"] == calcul["regles_non_calculables"] != []
    autre_regle, verdict = relances.lister(calcul, regle=DORMANT, budget_caracteres=1_000_000)
    assert verdict is None and autre_regle["total"] == 0


def test_la_page_cite_l_enonce_des_regles_et_des_segments_de_ses_relances_seulement():
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_devis()])))
    page = _page(calcul)
    assert page["regles"] == {DEVIS: relances.REGLES[DEVIS]}
    assert page["regles_des_segments"] == {"devis_envoye_sans_reponse_perime": segments.REGLES[
        "devis_envoye_sans_reponse_perime"]}
    vide = _page(_calculer(_evaluation(_lead())))
    assert vide["regles"] == {} and vide["regles_des_segments"] == {}


def test_la_page_porte_l_ordre_la_frequence_et_les_indetermines():
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_devis()]),
                                   _lead("lead-2", client="b", non_calculables=[
                                       {"segment": "dormant_lead", "manque": "date illisible"}])))
    page = _page(calcul)
    assert page["ordre"] == relances.ORDRE_RELANCES
    assert page["jours_entre_relances"] == 7 and page["indetermines"] == 1
    assert page["regles_non_calculables"] == []


def test_lister_ne_modifie_pas_le_calcul():
    evaluation, devis = _beaucoup(12)
    calcul = _calculer(evaluation, devis=devis)
    avant = copy.deepcopy(calcul)
    _page(calcul, decalage=3, limite=4, regle=DEVIS, permises_seulement=True)
    assert calcul == avant


# ---------------------------------------------------------------------------------------------------------
# preparer : rien n'est envoyé, un texte FIXE, des refus dans l'ordre
# ---------------------------------------------------------------------------------------------------------
def _preparer(calcul, *, lead_id="lead-1", regle=DEVIS, canal="appel", maintenant=MAINTENANT, client_id="client-a",
              prepare_par="vendeur.un", voie="appareil"):
    return relances.preparer(
        calcul, lead_id=lead_id, client_id=client_id, regle=regle, canal=canal, maintenant=maintenant,
        prepare_par=prepare_par, voie=voie)


def _calcul_devis(**plus):
    return _calculer(_evaluation(_lead(segments_=[_seg_devis()])), **plus)


def _refus(resultat):
    preparation, verdict = resultat
    assert preparation is None and verdict is not None, resultat
    assert verdicts.est_verdict(verdict["code"])
    return verdict


def _prepare(resultat):
    preparation, verdict = resultat
    assert verdict is None, verdict
    return preparation


def test_une_relance_par_appel_est_preparee_sans_aucun_consentement():
    preparation = _prepare(_preparer(_calcul_devis(), canal="appel"))
    resultat, entree = preparation["resultat"], preparation["entree"]
    gabarit = gabarits_relance.GABARITS[(DEVIS, "appel")]
    assert resultat["envoye"] is False
    assert resultat["texte"] == gabarit["texte"] and resultat["nature"] == "points_d_appel"
    assert resultat["gabarit"] == {"id": "relance_devis_appel", "version": 1}
    assert (resultat["lead_id"], resultat["regle"], resultat["canal"]) == ("lead-1", DEVIS, "appel")
    assert resultat["prepare_le"] == MAINTENANT and resultat["relance_id"] == entree["relance_id"]
    assert resultat["prochaine_date_permise"] == "2026-10-27T16:00:00+00:00"
    assert resultat["segment"] == _seg_devis() and resultat["depart"]["fait"] == "m3.devis_envoye"
    assert "Rien n'est envoyé" in resultat["a_faire"] and "T2.1-c" in resultat["a_faire"]


def test_l_entree_du_registre_garde_qui_quoi_pourquoi_et_le_texte_prepare():
    entree = _prepare(_preparer(_calcul_devis(), canal="appel"))["entree"]
    assert entree == {
        "type_entree": "relance_preparee", "relance_id": entree["relance_id"], "lead_id": "lead-1",
        "client_id": "client-a", "regle": DEVIS, "segment": "quote_stale", "canal": "appel",
        "gabarit": {"id": "relance_devis_appel", "version": 1},
        "texte": gabarits_relance.GABARITS[(DEVIS, "appel")]["texte"], "echeance": "2026-10-09T13:00:00+00:00",
        "donnee": _seg_devis()["donnee"], "prepare_le": MAINTENANT, "prepare_par": "vendeur.un", "voie": "appareil",
    }
    contient = json.dumps(entree)
    assert "@" not in contient and "514" not in contient


def test_la_personne_et_la_voie_viennent_de_l_appelant_pas_du_calcul():
    entree = _prepare(_preparer(_calcul_devis(), prepare_par="agent", voie="agent"))["entree"]
    assert (entree["prepare_par"], entree["voie"]) == ("agent", "agent")


def test_le_texte_d_un_message_est_le_gabarit_fixe_avec_consentement_actif():
    calcul = _calcul_devis(consents=[_consentement("sms"), _consentement("courriel")])
    for canal in ("sms", "courriel"):
        resultat = _prepare(_preparer(calcul, canal=canal))["resultat"]
        assert resultat["texte"] == gabarits_relance.GABARITS[(DEVIS, canal)]["texte"]
        assert resultat["nature"] == "message" and resultat["envoye"] is False


def test_la_relance_d_un_lead_dormant_utilise_son_propre_gabarit_sans_avertissement_de_livraison():
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_dormant()])))
    resultat = _prepare(_preparer(calcul, regle=DORMANT, canal="appel"))["resultat"]
    assert resultat["gabarit"]["id"] == "relance_dormant_appel" and resultat["avertissements"] == []
    assert resultat["texte"] == gabarits_relance.GABARITS[(DORMANT, "appel")]["texte"]


def test_une_relance_de_devis_dit_que_la_livraison_n_est_pas_enregistree():
    resultat = _prepare(_preparer(_calcul_devis()))["resultat"]
    assert resultat["avertissements"] == [relances.AVERTISSEMENT_ENVOI_APPROUVE]
    assert "livraison au client" in relances.AVERTISSEMENT_ENVOI_APPROUVE
    faits = [_fait_devis(origine="m3.devis_sans_reponse")]
    constat = _calculer(_evaluation(_lead(segments_=[_seg_devis()])), devis=faits)
    assert _prepare(_preparer(constat))["resultat"]["avertissements"] == []


def test_l_identifiant_de_la_relance_est_deterministe_et_change_avec_le_lead_la_regle_et_l_instant():
    base = _prepare(_preparer(_calcul_devis()))["entree"]["relance_id"]
    assert _prepare(_preparer(_calcul_devis()))["entree"]["relance_id"] == base
    # Ni le canal ni la personne ne changent le fait qu'à cet instant, ce lead est relancé pour cette règle.
    assert _prepare(_preparer(_calcul_devis(consents=[_consentement("sms")]), canal="sms",
                              prepare_par="admin.fictif"))["entree"]["relance_id"] == base
    autre_instant = _prepare(_preparer(_calcul_devis(maintenant="2026-10-21T12:00:00-04:00"),
                                       maintenant="2026-10-21T12:00:00-04:00"))
    assert autre_instant["entree"]["relance_id"] != base
    calcul = _calculer(_evaluation(_lead("lead-2", segments_=[_seg_devis()])))
    assert _prepare(_preparer(calcul, lead_id="lead-2"))["entree"]["relance_id"] != base
    dormant = _calculer(_evaluation(_lead(segments_=[_seg_dormant()])))
    assert _prepare(_preparer(dormant, regle=DORMANT))["entree"]["relance_id"] != base


def test_un_message_avec_consentement_actif_de_ce_canal_seulement():
    calcul = _calcul_devis(consents=[_consentement("sms")])
    assert _prepare(_preparer(calcul, canal="sms"))
    verdict = _refus(_preparer(calcul, canal="courriel"))
    assert verdict["code"] == "REJ-CONSENTEMENT-ABSENT" and "courriel" in verdict["detail"]
    assert "m2_enregistrer_consentement_contact" in verdict["detail"] and "appel" in verdict["detail"]


@pytest.mark.parametrize("canal", ["sms", "courriel"])
def test_sans_aucun_consentement_un_message_est_refuse_et_l_appel_reste_permis(canal):
    calcul = _calcul_devis()
    assert _refus(_preparer(calcul, canal=canal))["code"] == "REJ-CONSENTEMENT-ABSENT"
    assert _prepare(_preparer(calcul, canal="appel"))["resultat"]["canal"] == "appel"


@pytest.mark.parametrize("canal", ["sms", "courriel"])
def test_apres_un_stop_aucun_message_meme_avec_un_consentement_et_l_appel_reste_permis(canal):
    calcul = _calcul_devis(consents=[_consentement("sms"), _consentement("courriel")], retraits=[_retrait()])
    verdict = _refus(_preparer(calcul, canal=canal))
    assert verdict["code"] == "REJ-CONSENTEMENT-RETIRE"
    assert "2026-10-18T09:00:00-04:00" in verdict["detail"] and "appel seulement" in verdict["detail"]
    assert _prepare(_preparer(calcul, canal="appel"))


def test_une_regle_ou_un_canal_inconnu_est_refuse_la_regle_d_abord():
    calcul = _calcul_devis()
    assert _refus(_preparer(calcul, regle="relance_inconnue"))["code"] == "REJ-ENUM-INVALIDE"
    assert "regle" in _refus(_preparer(calcul, regle="relance_inconnue", canal="pigeon"))["detail"]
    verdict = _refus(_preparer(calcul, canal="pigeon"))
    assert verdict["code"] == "REJ-ENUM-INVALIDE" and "canal" in verdict["detail"]
    for mauvais in (None, 5, ""):
        assert _refus(_preparer(calcul, regle=mauvais))["code"] == "REJ-ENUM-INVALIDE"
        assert _refus(_preparer(calcul, canal=mauvais))["code"] == "REJ-ENUM-INVALIDE"


def test_une_relance_qui_n_est_pas_due_est_refusee_avec_sa_raison():
    calcul = _calculer(_evaluation(_lead()))
    verdict = _refus(_preparer(calcul))
    assert verdict["code"] == "REJ-RELANCE-NON-DUE"
    assert "quote_stale" in verdict["detail"] and "m2_lister_relances" in verdict["detail"]
    dormant = _refus(_preparer(calcul, regle=DORMANT))
    assert "dormant_lead" in dormant["detail"]


def test_la_relance_d_un_autre_lead_n_est_pas_celle_de_ce_lead():
    calcul = _calculer(_evaluation(_lead("lead-2", segments_=[_seg_devis()])))
    assert _refus(_preparer(calcul, lead_id="lead-1"))["code"] == "REJ-RELANCE-NON-DUE"
    assert _refus(_preparer(calcul, lead_id="lead-2", regle=DORMANT))["code"] == "REJ-RELANCE-NON-DUE"
    assert _prepare(_preparer(calcul, lead_id="lead-2"))


def test_une_regle_non_calculable_est_refusee_avec_ce_qui_manque_avant_toute_autre_chose():
    globaux = [{"segment": "quote_stale", "manque": "non calculable, manque le seuil : seuil à configurer"}]
    calcul = _calculer(_evaluation(_lead(segments_=[_seg_devis()]), globaux=globaux))
    verdict = _refus(_preparer(calcul))
    assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE" and "seuil à configurer" in verdict["detail"]
    assert "relance_devis_sans_reponse" in verdict["detail"]


def test_la_frequence_limitee_refuse_avec_la_derniere_relance_et_la_prochaine_date():
    calcul = _calcul_devis(preparees=[_preparee(le="2026-10-15T12:00:00-04:00", canal="sms")])
    verdict = _refus(_preparer(calcul))
    assert verdict["code"] == "REJ-RELANCE-TROP-PROCHE"
    detail = verdict["detail"]
    assert "2026-10-15T12:00:00-04:00" in detail and "sms" in detail
    assert "2026-10-22T16:00:00+00:00" in detail and "tous les 7 jours" in detail


def test_la_frequence_est_controlee_avant_le_consentement():
    calcul = _calcul_devis(preparees=[_preparee(le="2026-10-19T12:00:00-04:00")], retraits=[_retrait()])
    assert _refus(_preparer(calcul, canal="sms"))["code"] == "REJ-RELANCE-TROP-PROCHE"


def test_la_relance_est_preparee_pile_a_la_prochaine_date_permise_pas_une_seconde_avant():
    preparees = [_preparee(le="2026-10-15T12:00:00-04:00")]
    avant = _calcul_devis(maintenant="2026-10-22T15:59:59+00:00", preparees=preparees)
    assert _refus(_preparer(avant, maintenant="2026-10-22T15:59:59+00:00"))["code"] == "REJ-RELANCE-TROP-PROCHE"
    pile = _calcul_devis(maintenant="2026-10-22T16:00:00+00:00", preparees=preparees)
    assert _prepare(_preparer(pile, maintenant="2026-10-22T16:00:00+00:00"))


def test_la_regle_non_due_est_controlee_avant_la_frequence_et_le_consentement():
    calcul = _calculer(
        _evaluation(_lead()), preparees=[_preparee(le="2026-10-19T12:00:00-04:00")], retraits=[_retrait()])
    assert _refus(_preparer(calcul, canal="sms"))["code"] == "REJ-RELANCE-NON-DUE"


def test_un_gabarit_manquant_leve_une_erreur_jamais_un_texte_de_repli(monkeypatch):
    monkeypatch.setattr(gabarits_relance, "GABARITS", {})
    with pytest.raises(RuntimeError, match="aucun gabarit de relance"):
        _preparer(_calcul_devis())


def test_preparer_ne_modifie_pas_le_calcul():
    calcul = _calcul_devis(consents=[_consentement("sms")])
    avant = copy.deepcopy(calcul)
    _prepare(_preparer(calcul, canal="sms"))
    _refus(_preparer(calcul, canal="courriel"))
    assert calcul == avant
