"""PLAN T4.27-a2 : d'où vient l'heure d'un report et d'une demande d'écart (modules purs, registre EN MÉMOIRE).

Avant : `m4_signaler_report` et `m4_creer_demande_ecart` inscrivaient l'heure que l'appelant écrit ; l'âge d'un retard
(`m4_lire_retards_incidents`, « bloquée » dès 24 h) en héritait, et une horloge d'appareil fausse faussait l'âge. Le
pointage, lui, gardait l'heure de RÉCEPTION du serveur depuis T1.4-d, avec l'heure de l'appareil À CÔTÉ (clé sœur
`horodatage_appareil`, affichage seulement).

Ce fichier prouve, sans base ni réseau ni horloge :
  * `horodatage.origine` lit ce signe et rien d'autre : `serveur` seulement avec l'heure de l'appareil à côté ;
  * `etats.transitionner` et `ecarts.creer_demande_ecart` prennent `horodatage_appareil` en option et le gardent À PART,
    sur le maillon et l'accusé ; refusé s'il est mal formé, sans rien écrire ; jamais lu pour un calcul ;
  * sans lui, le maillon et l'accusé sont ceux d'AVANT, octet pour octet : les empreintes ci-dessous ont été calculées
    avec le code d'avant ce changement, donc un registre existant reste valide et un fait d'avant garde son heure ;
  * le relevé des retards dit, pour chaque ligne, d'où vient son heure : `serveur` pour un fait d'appareil, `appelant`
    pour un fait d'avant ou d'un agent, et, pour une anomalie de pointage, l'origine de son pointage (jamais `serveur`
    sans preuve).
Le scénario par les vrais outils, le rejeu de la même clé et la porte d'appareil : `test_heure_du_serveur_outils.py`,
`test_heure_du_serveur_rejeu.py` et `tests/e2e/test_heure_du_serveur_appareil.py`. Tout est fictif (`fictif: true`).
"""

from __future__ import annotations

import json

import pytest
from m4_field_ops import cedule, ecarts, encodage, etats, horodatage, pointage, retards
from m4_field_ops.registre import Registre

FICTIF = True
SEL = "sel-t4-27-a2-fictif"
INSCRIPTION = "2030-01-01T06:00:00+00:00"
REFERENCE = "2030-01-03T09:30:00+00:00"
# L'heure du serveur, et l'heure d'un appareil DÉRÉGLÉ (l'an 2000) : si celle-ci fuitait dans un calcul, on le verrait.
RECU_LE = "2030-01-01T08:00:00+00:00"
APPAREIL_DEREGLE = "2000-01-01T00:00:00+00:00"
VERSION_PREVUE = {"duree_minutes": 60, "perimetre": "perimetre prevu", "materiaux": ["m1"]}
VERSION_DECLAREE = {"duree_minutes": 90, "perimetre": "perimetre declare", "materiaux": ["m2"]}

# Empreintes calculées AVEC LE CODE D'AVANT T4.27-a2 (état e0aace3) pour le scénario de `_scenario_d_avant` : report,
# replanification, demande d'écart, tous SANS heure d'appareil. Si l'une change, un registre existant ne se relit plus.
EMPREINTES_D_AVANT = {
    "report": "197980982ced9de7b01fdc0148fa2b6e70c34220cb1bf97d1f79ccd9e77084a5",
    "replanification": "76759526223be830f6ccafa8ff46f18f12d3810bf5b37515a32d6404e439db27",
    "demande": "120586e3e6e517def13744eb7ace82e9624799405475c7ec25e86822df459a6b",
}
CLES_MAILLON_REPORT_D_AVANT = {
    "type_entree",
    "intervention_id",
    "statut",
    "statut_precedent",
    "horodatage",
    "motif",
    "ligne_id",
    "precedent_ligne_id",
}
CLES_ACCUSE_REPORT_D_AVANT = {
    "intervention_id",
    "ligne_id",
    "statut",
    "statut_precedent",
    "empreinte_maillon",
    "tete_chaine",
    "horodatage",
}
CLES_MAILLON_DEMANDE_D_AVANT = {
    "type_entree",
    "intervention_id",
    "horodatage",
    "type_demande",
    "demande_id",
    "version_prevue",
    "version_declaree",
    "statut_arbitrage",
    "ligne_id",
    "precedent_ligne_id",
}
CLES_ACCUSE_DEMANDE_D_AVANT = {
    "demande_id",
    "intervention_id",
    "ligne_id",
    "type_demande",
    "statut_arbitrage",
    "statut",
    "tete_chaine",
}


def _contrat(lead_id):
    return {
        "lead_id": lead_id,
        "conversation_id": f"C-{lead_id}",
        "type_travaux": "renovation_totale",
        "ville": "Montreal",
        "canal": "telephone",
        "contact": {"nom": "Client fictif", "telephone": "0102030405"},
        "urgence_declaree": False,
    }


def _marqueur(lead_id):
    return {
        "readiness_ok": True,
        "lead_id": lead_id,
        "hash_tete_registre": None,
        "horodatage": "2030-01-01T05:00:00+00:00",
        "empreinte": "ab" * 32,
    }


def _inscrire(registre, lead_id):
    accuse, verdict = etats.inscrire_intervention(_contrat(lead_id), _marqueur(lead_id), registre, INSCRIPTION, SEL)
    assert verdict is None, verdict
    return accuse["intervention_id"]


def _en_route(registre, lead_id):
    identifiant = _inscrire(registre, lead_id)
    _, verdict = etats.transitionner(
        identifiant,
        "en_route",
        registre,
        "2030-01-01T07:00:00+00:00",
        assignation={"intervention_id": identifiant, "technicien_id": "T1"},
    )
    assert verdict is None, verdict
    return identifiant


def _reporter(registre, identifiant, motif, horodatage_arg, horodatage_appareil=None):
    accuse, verdict = etats.transitionner(
        identifiant, "reportee", registre, horodatage_arg, motif=motif, horodatage_appareil=horodatage_appareil
    )
    assert verdict is None, verdict
    return accuse


def _ecart(registre, identifiant, horodatage_arg, horodatage_appareil=None):
    accuse, verdict = ecarts.creer_demande_ecart(
        identifiant,
        VERSION_PREVUE,
        VERSION_DECLAREE,
        horodatage_arg,
        registre,
        horodatage_appareil=horodatage_appareil,
    )
    assert verdict is None, verdict
    return accuse


def _maillon(registre, ligne_id):
    return next(m for m in registre.lire() if m["ligne_id"] == ligne_id)


def _octets(objet):
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


def _scenario_d_avant():
    """Le scénario dont `EMPREINTES_D_AVANT` a été calculé, sans jamais donner d'heure d'appareil."""
    contrat = {
        "lead_id": "L-OR-1",
        "conversation_id": "C-OR-1",
        "type_travaux": "renovation_totale",
        "ville": "Montreal",
        "canal": "telephone",
        "contact": {"nom": "Client fictif", "telephone": "0102030405"},
        "urgence_declaree": False,
    }
    registre = Registre()
    accuse, verdict = etats.inscrire_intervention(contrat, _marqueur("L-OR-1"), registre, INSCRIPTION, SEL)
    assert verdict is None, verdict
    identifiant = accuse["intervention_id"]
    report, verdict = etats.transitionner(identifiant, "reportee", registre, "2030-01-01T08:00:00+00:00", motif="meteo")
    assert verdict is None, verdict
    replanification, verdict = etats.transitionner(identifiant, "planifiee", registre, "2030-01-01T09:00:00+00:00")
    assert verdict is None, verdict
    demande, verdict = ecarts.creer_demande_ecart(
        identifiant,
        {"duree_minutes": 60, "perimetre": "perimetre prevu", "materiaux": ["m1"]},
        {"duree_minutes": 90, "perimetre": "perimetre declare", "materiaux": ["m2"]},
        "2030-01-01T10:00:00+00:00",
        registre,
    )
    assert verdict is None, verdict
    return registre, report, replanification, demande


# =========================================================================================
# 1. La règle : `serveur` seulement avec l'heure de l'appareil à côté
# =========================================================================================
def test_les_valeurs_de_l_origine_et_la_cle_soeur_sont_celles_du_contrat():
    assert horodatage.ORIGINE_SERVEUR == "serveur" and horodatage.ORIGINE_APPELANT == "appelant"
    assert horodatage.CLE_HORODATAGE_APPAREIL == "horodatage_appareil", "la clé que le pointage écrit depuis T1.4-d"


def test_un_maillon_qui_porte_l_heure_de_l_appareil_a_cote_a_l_heure_du_serveur():
    assert horodatage.origine({"horodatage": RECU_LE, "horodatage_appareil": APPAREIL_DEREGLE}) == "serveur"


@pytest.mark.parametrize(
    "maillon",
    [
        {"horodatage": RECU_LE},
        {"horodatage": RECU_LE, "horodatage_appareil": None},
        {"horodatage": RECU_LE, "horodatage_appareil": ""},
        {"horodatage": RECU_LE, "horodatage_appareil": 20000101},
        {"horodatage": RECU_LE, "horodatage_appareil": ["2000-01-01T00:00:00+00:00"]},
        {},
        None,
        "horodatage_appareil",
        ["horodatage_appareil"],
    ],
    ids=["sans-cle", "nulle", "vide", "entier", "liste", "vide-total", "none", "texte", "liste-de-cles"],
)
def test_sans_l_heure_de_l_appareil_a_cote_l_heure_est_celle_de_l_appelant_jamais_serveur_par_defaut(maillon):
    assert horodatage.origine(maillon) == "appelant"


def test_l_origine_ne_lit_que_la_cle_sœur_pas_le_reste_du_maillon():
    """Ni le type d'entrée, ni une clé `origine`, ni `recu_le` écrits à la main ne font dire `serveur`."""
    maillon = {"type_entree": "transition_statut", "horodatage": RECU_LE, "origine": "serveur", "recu_le": RECU_LE}
    assert horodatage.origine(maillon) == "appelant"


# =========================================================================================
# 2. Sans heure d'appareil : les faits d'AVANT, octet pour octet
# =========================================================================================
def test_un_fait_d_avant_garde_son_empreinte_et_le_registre_reste_valide():
    registre, report, replanification, demande = _scenario_d_avant()
    assert report["ligne_id"] == EMPREINTES_D_AVANT["report"]
    assert replanification["ligne_id"] == EMPREINTES_D_AVANT["replanification"]
    assert demande["ligne_id"] == EMPREINTES_D_AVANT["demande"] == demande["tete_chaine"] == registre.tete()
    assert registre.valider_chaine() is True


def test_sans_heure_d_appareil_le_maillon_et_l_accuse_d_un_report_sont_ceux_d_avant():
    registre, report, _, _ = _scenario_d_avant()
    assert set(report) == CLES_ACCUSE_REPORT_D_AVANT
    maillon = _maillon(registre, report["ligne_id"])
    assert set(maillon) == CLES_MAILLON_REPORT_D_AVANT
    assert maillon["horodatage"] == "2030-01-01T08:00:00+00:00"
    assert horodatage.origine(maillon) == "appelant"


def test_sans_heure_d_appareil_le_maillon_et_l_accuse_d_une_demande_d_ecart_sont_ceux_d_avant():
    registre, _, _, demande = _scenario_d_avant()
    assert set(demande) == CLES_ACCUSE_DEMANDE_D_AVANT
    maillon = _maillon(registre, demande["ligne_id"])
    assert set(maillon) == CLES_MAILLON_DEMANDE_D_AVANT
    assert maillon["horodatage"] == "2030-01-01T10:00:00+00:00"
    assert horodatage.origine(maillon) == "appelant"


def test_une_heure_d_appareil_nulle_est_comme_pas_d_heure_d_appareil():
    """`None` est le défaut : même maillon, même empreinte que sans l'argument."""
    sans, avec_none = Registre(), Registre()
    for registre in (sans, avec_none):
        identifiant = _inscrire(registre, "L-1")
    accuse_sans = etats.transitionner(identifiant, "reportee", sans, RECU_LE, motif="meteo")[0]
    accuse_none = etats.transitionner(
        identifiant, "reportee", avec_none, RECU_LE, motif="meteo", horodatage_appareil=None
    )[0]
    assert accuse_sans["ligne_id"] == accuse_none["ligne_id"] and accuse_sans == accuse_none
    assert _octets(sans.lire()) == _octets(avec_none.lire())


# =========================================================================================
# 3. Avec l'heure de l'appareil : le fait est daté par le serveur, celle de l'appareil est gardée À PART
# =========================================================================================
def test_un_report_d_appareil_garde_l_heure_de_l_appareil_a_cote_et_dit_serveur():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    accuse = _reporter(registre, identifiant, "meteo", RECU_LE, APPAREIL_DEREGLE)
    assert accuse["horodatage"] == RECU_LE and accuse["horodatage_appareil"] == APPAREIL_DEREGLE
    assert set(accuse) == CLES_ACCUSE_REPORT_D_AVANT | {"horodatage_appareil"}
    maillon = _maillon(registre, accuse["ligne_id"])
    assert set(maillon) == CLES_MAILLON_REPORT_D_AVANT | {"horodatage_appareil"}
    assert maillon["horodatage"] == RECU_LE and maillon["horodatage_appareil"] == APPAREIL_DEREGLE
    assert horodatage.origine(maillon) == "serveur"
    assert registre.valider_chaine() is True


def test_une_demande_d_ecart_d_appareil_garde_l_heure_de_l_appareil_a_cote_et_dit_serveur():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    accuse = _ecart(registre, identifiant, RECU_LE, APPAREIL_DEREGLE)
    # l'accusé rend l'heure du serveur : de quoi rejouer le MÊME résultat avec la même heure
    assert accuse["horodatage"] == RECU_LE and accuse["horodatage_appareil"] == APPAREIL_DEREGLE
    assert set(accuse) == CLES_ACCUSE_DEMANDE_D_AVANT | {"horodatage", "horodatage_appareil"}
    maillon = _maillon(registre, accuse["ligne_id"])
    assert set(maillon) == CLES_MAILLON_DEMANDE_D_AVANT | {"horodatage_appareil"}
    assert maillon["horodatage"] == RECU_LE and maillon["horodatage_appareil"] == APPAREIL_DEREGLE
    assert horodatage.origine(maillon) == "serveur"


def test_la_transition_en_revue_d_une_demande_d_appareil_porte_le_meme_signe():
    registre = Registre()
    identifiant = _en_route(registre, "L-1")
    accuse = _ecart(registre, identifiant, RECU_LE, APPAREIL_DEREGLE)
    assert accuse["statut"] == "en_revue"
    transition = [m for m in registre.lire() if m["type_entree"] == "transition_statut" and m["statut"] == "en_revue"]
    assert len(transition) == 1
    assert transition[0]["horodatage"] == RECU_LE and transition[0]["horodatage_appareil"] == APPAREIL_DEREGLE
    assert horodatage.origine(transition[0]) == "serveur"


def test_la_transition_en_revue_d_une_demande_sans_appareil_ne_porte_pas_le_signe():
    registre = Registre()
    identifiant = _en_route(registre, "L-1")
    _ecart(registre, identifiant, RECU_LE)
    (transition,) = [
        m for m in registre.lire() if m["type_entree"] == "transition_statut" and m["statut"] == "en_revue"
    ]
    assert "horodatage_appareil" not in transition and horodatage.origine(transition) == "appelant"


def test_l_heure_de_l_appareil_n_est_jamais_lue_pour_un_calcul():
    """L'identité d'une demande (`demande_id`) ne suit que l'heure qui fait foi, jamais celle de l'appareil."""
    un, deux = Registre(), Registre()
    ids = []
    for registre, appareil in ((un, APPAREIL_DEREGLE), (deux, "2099-12-31T23:59:59+00:00")):
        identifiant = _inscrire(registre, "L-1")
        ids.append(_ecart(registre, identifiant, RECU_LE, appareil)["demande_id"])
    assert ids[0] == ids[1] == encodage.empreinte("demande_revue", identifiant, RECU_LE)


def test_deux_heures_d_appareil_differentes_ne_changent_que_la_cle_soeur():
    """Même heure de serveur, heures d'appareil différentes : le reste du maillon est identique."""
    maillons = []
    for appareil in (APPAREIL_DEREGLE, "2099-12-31T23:59:59+00:00"):
        registre = Registre()
        identifiant = _inscrire(registre, "L-1")
        accuse = _reporter(registre, identifiant, "meteo", RECU_LE, appareil)
        maillon = _maillon(registre, accuse["ligne_id"])
        ecartes = ("horodatage_appareil", "ligne_id")
        maillons.append({cle: valeur for cle, valeur in maillon.items() if cle not in ecartes})
    assert maillons[0] == maillons[1]


@pytest.mark.parametrize(
    "appareil",
    ["", "hier", "2000-01-01", "2000-01-01T00:00:00", "2000-13-01T00:00:00+00:00", 42, ["2000-01-01T00:00:00+00:00"]],
)
def test_une_heure_d_appareil_mal_formee_est_refusee_sans_rien_ecrire(appareil):
    registre = Registre()
    identifiant = _en_route(registre, "L-1")
    avant = _octets(registre.lire())
    accuse, verdict = etats.transitionner(
        identifiant, "reportee", registre, RECU_LE, motif="meteo", horodatage_appareil=appareil
    )
    assert accuse is None and verdict["code"] == "REJ-HORODATAGE-INVALIDE"
    assert "horodatage_appareil" in verdict["detail"]
    accuse, verdict = ecarts.creer_demande_ecart(
        identifiant, VERSION_PREVUE, VERSION_DECLAREE, RECU_LE, registre, horodatage_appareil=appareil
    )
    assert accuse is None and verdict["code"] == "REJ-HORODATAGE-INVALIDE"
    assert "horodatage_appareil" in verdict["detail"]
    assert _octets(registre.lire()) == avant, "rien n'est écrit : jamais une clé sœur illisible dans un registre"


def test_le_verdict_d_une_heure_de_serveur_illisible_est_celui_d_avant():
    """L'heure qui fait foi est validée d'abord, comme avant : l'ordre des contrôles ne change pas."""
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _, verdict = etats.transitionner(
        identifiant, "reportee", registre, "hier", motif="meteo", horodatage_appareil="hier"
    )
    assert verdict["code"] == "REJ-HORODATAGE-INVALIDE" and "horodatage_appareil" not in (verdict.get("detail") or "")
    _, verdict = ecarts.creer_demande_ecart(
        identifiant, VERSION_PREVUE, VERSION_DECLAREE, "hier", registre, horodatage_appareil="hier"
    )
    assert verdict["code"] == "REJ-HORODATAGE-INVALIDE" and "horodatage_appareil" not in (verdict.get("detail") or "")


# =========================================================================================
# 4. Le relevé des retards dit d'où vient chaque heure
# =========================================================================================
def _lire(registre, reference=REFERENCE):
    releve, verdict = retards.lire(registre, reference)
    assert verdict is None, verdict
    return releve


def test_le_releve_dit_serveur_pour_un_fait_d_appareil_et_appelant_pour_un_fait_d_avant():
    registre = Registre()
    ancien, recent = _inscrire(registre, "L-ancien"), _inscrire(registre, "L-recent")
    _reporter(registre, ancien, "meteo", "2030-01-01T08:00:00+00:00")  # d'avant : l'heure de l'appelant
    _reporter(registre, recent, "client_absent", "2030-01-01T09:00:00+00:00", APPAREIL_DEREGLE)  # d'appareil
    releve = _lire(registre)
    origines = {ligne["intervention_id"]: ligne["origine_heure"] for ligne in releve["reports"]["liste"]}
    assert origines == {ancien: "appelant", recent: "serveur"}
    ligne_avant = next(ligne for ligne in releve["reports"]["liste"] if ligne["intervention_id"] == ancien)
    assert ligne_avant["depuis"] == "2030-01-01T08:00:00+00:00", "un fait d'avant garde son heure"
    assert ligne_avant["heures_ecoulees"] == 49


def test_le_releve_dit_l_origine_de_chaque_demande_d_ecart_ouverte():
    registre = Registre()
    ancien, recent = _inscrire(registre, "L-ancien"), _inscrire(registre, "L-recent")
    demande_avant = _ecart(registre, ancien, "2030-01-01T08:00:00+00:00")["demande_id"]
    demande_appareil = _ecart(registre, recent, "2030-01-01T09:00:00+00:00", APPAREIL_DEREGLE)["demande_id"]
    releve = _lire(registre)
    origines = {ligne["demande_id"]: ligne["origine_heure"] for ligne in releve["incidents"]["liste"]}
    assert origines == {demande_avant: "appelant", demande_appareil: "serveur"}


def test_le_dernier_report_fait_foi_aussi_pour_l_origine():
    """Un report d'avant, replanifié, puis reporté de nouveau depuis un appareil : la ligne est celle du DERNIER."""
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", "2030-01-01T08:00:00+00:00")
    assert etats.transitionner(identifiant, "planifiee", registre, "2030-01-01T09:00:00+00:00")[1] is None
    _reporter(registre, identifiant, "client_absent", "2030-01-02T07:00:00+00:00", APPAREIL_DEREGLE)
    (ligne,) = _lire(registre)["reports"]["liste"]
    assert (ligne["motif"], ligne["origine_heure"]) == ("client_absent", "serveur")
    # et dans l'autre sens : le dernier est d'avant, l'appareil d'un report plus ancien ne compte pas
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", "2030-01-01T08:00:00+00:00", APPAREIL_DEREGLE)
    assert etats.transitionner(identifiant, "planifiee", registre, "2030-01-01T09:00:00+00:00")[1] is None
    _reporter(registre, identifiant, "client_absent", "2030-01-02T07:00:00+00:00")
    (ligne,) = _lire(registre)["reports"]["liste"]
    assert (ligne["motif"], ligne["origine_heure"]) == ("client_absent", "appelant")


def test_l_origine_ne_change_ni_l_age_ni_le_seuil_de_blocage():
    """« Bloquée » dès 24 h pile se calcule comme avant, pour un fait d'avant comme pour un fait d'appareil."""
    registre = Registre()
    ids = [_inscrire(registre, f"L-{numero}") for numero in range(4)]
    _ecart(registre, ids[0], "2030-01-02T09:30:01+00:00")  # d'avant, 23 h 59 min 59 s
    _ecart(registre, ids[1], "2030-01-02T09:30:00+00:00")  # d'avant, 24 h pile
    _ecart(registre, ids[2], "2030-01-02T09:30:01+00:00", APPAREIL_DEREGLE)  # d'appareil, 23 h 59 min 59 s
    _ecart(registre, ids[3], "2030-01-02T09:30:00+00:00", APPAREIL_DEREGLE)  # d'appareil, 24 h pile
    releve = _lire(registre)
    lignes = releve["incidents"]["liste"]
    assert sorted((ligne["origine_heure"], ligne["heures_ecoulees"], ligne["bloquee"]) for ligne in lignes) == [
        ("appelant", 23, False),
        ("appelant", 24, True),
        ("serveur", 23, False),
        ("serveur", 24, True),
    ]
    assert releve["incidents"]["bloques"] == 2


def test_l_ordre_suit_les_instants_quelle_que_soit_l_origine_et_l_ordre_d_ecriture():
    """Un fait d'avant écrit d'abord (08:00), un fait d'appareil écrit ensuite mais plus ancien (07:00) : le plus
    ancien passe en premier, comme avant."""
    registre = Registre()
    avant, appareil = _inscrire(registre, "L-avant"), _inscrire(registre, "L-appareil")
    _reporter(registre, avant, "meteo", "2030-01-01T08:00:00+00:00")
    _reporter(registre, appareil, "client_absent", "2030-01-01T07:00:00+00:00", APPAREIL_DEREGLE)
    lignes = _lire(registre)["reports"]["liste"]
    assert [(ligne["intervention_id"], ligne["origine_heure"]) for ligne in lignes] == [
        (appareil, "serveur"),
        (avant, "appelant"),
    ]


def test_les_lignes_du_releve_ont_exactement_les_cles_du_contrat():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", RECU_LE, APPAREIL_DEREGLE)
    _ecart(registre, identifiant, "2030-01-01T09:00:00+00:00", APPAREIL_DEREGLE)
    releve = _lire(registre)
    assert set(releve["reports"]["liste"][0]) == {
        "intervention_id",
        "motif",
        "depuis",
        "origine_heure",
        "heures_ecoulees",
    }
    assert set(releve["incidents"]["liste"][0]) == {
        "demande_id",
        "intervention_id",
        "type_demande",
        "depuis",
        "origine_heure",
        "heures_ecoulees",
        "bloquee",
    }


def test_le_releve_ne_montre_jamais_l_heure_de_l_appareil_ni_ne_s_en_sert():
    """L'heure de l'appareil reste à part : elle ne sort pas du relevé, et un appareil déréglé ne change pas l'âge."""
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", RECU_LE, APPAREIL_DEREGLE)
    releve = _lire(registre)
    assert APPAREIL_DEREGLE not in json.dumps(releve) and "horodatage_appareil" not in json.dumps(releve)
    assert releve["reports"]["liste"][0]["heures_ecoulees"] == 49, "49 h depuis l'heure du serveur, pas 30 ans"


# -- l'anomalie de pointage prend l'origine de son pointage -----------------------------------
GPS_LOIN = {"latitude": 46.8139, "longitude": -71.2080}  # à environ 230 km du référentiel
FENETRE = {"debut": "2030-01-01T00:00:00+00:00", "fin": "2030-01-02T00:00:00+00:00"}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T4-27-A2-FICTIF"}


def _referentiel():
    return {cedule.tokeniser_ville(SEL, "Montreal"): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}


def _pointage_incoherent(registre, identifiant, horodatage_arg, horodatage_appareil=None):
    """Le VRAI pointage (`pointage.enregistrer_pointage`) : un fix à 230 km, donc une anomalie et une demande."""
    accuse, verdict = pointage.enregistrer_pointage(
        identifiant,
        "T1",
        "arrivee",
        horodatage_arg,
        GPS_LOIN,
        ATTESTATION,
        {"intervention_id": identifiant, "technicien_id": "T1"},
        FENETRE,
        _referentiel(),
        "Montreal",
        SEL,
        registre,
        horodatage_appareil=horodatage_appareil,
    )
    assert verdict is None, verdict
    assert accuse["demande_id"] is not None and accuse["statut"] == "en_revue"
    return accuse


def test_une_anomalie_de_pointage_d_appareil_dit_serveur_et_celle_d_un_agent_dit_appelant():
    registre = Registre()
    a, b = _en_route(registre, "L-appareil"), _en_route(registre, "L-agent")
    par_appareil = _pointage_incoherent(registre, a, "2030-01-01T09:00:00+00:00", APPAREIL_DEREGLE)["demande_id"]
    par_un_agent = _pointage_incoherent(registre, b, "2030-01-01T10:00:00+00:00")["demande_id"]
    releve = _lire(registre)
    par_type = {ligne["demande_id"]: ligne for ligne in releve["incidents"]["liste"]}
    assert par_type[par_appareil]["type_demande"] == "anomalie_pointage" == par_type[par_un_agent]["type_demande"]
    assert par_type[par_appareil]["origine_heure"] == "serveur", "l'heure du pointage d'appareil est celle du serveur"
    assert par_type[par_un_agent]["origine_heure"] == "appelant"
    assert par_type[par_appareil]["depuis"] == "2030-01-01T09:00:00+00:00"


def test_l_anomalie_de_pointage_ne_porte_pas_elle_meme_le_signe_c_est_son_pointage_qui_le_porte():
    """C'est pourquoi une anomalie d'avant T4.27-a2, née d'un pointage d'appareil, se lit `serveur` sans réécriture."""
    registre = Registre()
    identifiant = _en_route(registre, "L-1")
    accuse = _pointage_incoherent(registre, identifiant, "2030-01-01T09:00:00+00:00", APPAREIL_DEREGLE)
    demande = next(m for m in registre.lire() if m.get("demande_id") == accuse["demande_id"])
    assert "horodatage_appareil" not in demande and horodatage.origine(demande) == "appelant"
    pointage_lie = _maillon(registre, demande["pointage_ligne_id"])
    assert pointage_lie["type_entree"] == pointage.TYPE_POINTAGE and horodatage.origine(pointage_lie) == "serveur"
    (ligne,) = _lire(registre)["incidents"]["liste"]
    assert ligne["origine_heure"] == "serveur"


def _anomalie_liee(registre, identifiant, horodatage_arg, pointage_ligne_id, numero):
    demande_id = f"demande-anomalie-{numero}-fictive"
    registre.ajouter(
        {
            "type_entree": pointage.TYPE_DEMANDE_REVUE,
            "intervention_id": identifiant,
            "horodatage": horodatage_arg,
            "type_demande": pointage.TYPE_REVUE_ANOMALIE,
            "pointage_ligne_id": pointage_ligne_id,
            "demande_id": demande_id,
            "statut_arbitrage": "en_attente",
        }
    )
    return demande_id


def test_une_anomalie_dont_le_pointage_est_introuvable_ou_ne_dit_rien_est_appelant_jamais_serveur():
    registre = Registre()
    a, b, c = (_inscrire(registre, f"L-{numero}") for numero in range(3))
    sans_lien = _anomalie_liee(registre, a, "2030-01-01T08:00:00+00:00", None, 1)
    lien_inconnu = _anomalie_liee(registre, b, "2030-01-01T09:00:00+00:00", "0" * 64, 2)
    # un « pointage_ligne_id » qui désigne autre chose qu'un pointage ne donne pas le signe non plus
    autre = registre.ajouter(
        {
            "type_entree": "transition_statut",
            "intervention_id": c,
            "statut": "planifiee",
            "statut_precedent": "planifiee",
            "horodatage": "2030-01-01T09:30:00+00:00",
            "horodatage_appareil": APPAREIL_DEREGLE,
        }
    )
    pas_un_pointage = _anomalie_liee(registre, c, "2030-01-01T10:00:00+00:00", autre, 3)
    origines = {ligne["demande_id"]: ligne["origine_heure"] for ligne in _lire(registre)["incidents"]["liste"]}
    assert origines == {sans_lien: "appelant", lien_inconnu: "appelant", pas_un_pointage: "appelant"}


def test_des_faits_d_appareil_ajoutes_apres_des_faits_d_avant_ne_les_touchent_pas():
    """Des faits d'avant et des faits d'appareil dans la MÊME chaîne : elle reste valide, et les faits d'avant gardent
    leur empreinte, donc leur heure, et se lisent `appelant`."""
    registre, report_d_avant, _, demande_d_avant = _scenario_d_avant()
    identifiant = _inscrire(registre, "L-2")
    nouveau = _reporter(registre, identifiant, "client_absent", "2030-01-01T07:00:00+00:00", APPAREIL_DEREGLE)
    ecart = _ecart(registre, identifiant, "2030-01-01T11:00:00+00:00", APPAREIL_DEREGLE)
    assert registre.valider_chaine() is True
    assert _maillon(registre, EMPREINTES_D_AVANT["report"])["horodatage"] == "2030-01-01T08:00:00+00:00"
    assert _maillon(registre, EMPREINTES_D_AVANT["demande"])["horodatage"] == "2030-01-01T10:00:00+00:00"
    assert report_d_avant["ligne_id"] == EMPREINTES_D_AVANT["report"]
    assert demande_d_avant["ligne_id"] == EMPREINTES_D_AVANT["demande"]
    # le premier scénario est reporté puis replanifié : seul le report d'appareil reste en cours
    releve = _lire(registre)
    assert [(ligne["intervention_id"], ligne["origine_heure"]) for ligne in releve["reports"]["liste"]] == [
        (identifiant, "serveur")
    ]
    assert nouveau["horodatage"] == "2030-01-01T07:00:00+00:00"
    origines = {ligne["demande_id"]: ligne["origine_heure"] for ligne in releve["incidents"]["liste"]}
    assert origines == {demande_d_avant["demande_id"]: "appelant", ecart["demande_id"]: "serveur"}


# =========================================================================================
# 5. Garde : le module lit une clé, n'en écrit aucune, ne consulte aucune horloge
# =========================================================================================
def test_la_cle_soeur_est_ecrite_par_le_pointage_sous_le_meme_nom_que_celui_que_l_origine_lit():
    """Le relevé lit `horodatage.CLE_HORODATAGE_APPAREIL` sur le pointage : le pointage doit l'écrire sous ce nom."""
    registre = Registre()
    identifiant = _en_route(registre, "L-1")
    accuse = _pointage_incoherent(registre, identifiant, "2030-01-01T09:00:00+00:00", APPAREIL_DEREGLE)
    maillon = _maillon(registre, accuse["ligne_id"])
    assert horodatage.CLE_HORODATAGE_APPAREIL in maillon and maillon[horodatage.CLE_HORODATAGE_APPAREIL]
    assert accuse[horodatage.CLE_HORODATAGE_APPAREIL] == APPAREIL_DEREGLE
