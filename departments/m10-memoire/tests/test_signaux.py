"""signaux.py : cycle de vie écrit des signaux critiques (PLAN T3.3-suite-b).

Module pur, exercé sur des registres en mémoire. Toutes les données sont fictives (`fictif: true`).
Ce qui est prouvé ici : l'état se calcule par relecture, l'ordre ouvert -> pris en compte -> clos est
imposé, un maillon qui n'a pas la forme d'un humain identifié ne ferme rien, la seule autre cause de
clôture est la règle de réévaluation écrite dans le module, et un refus n'écrit jamais rien.
"""

import pytest
from m10_memoire import paquets, registre, signaux, variance, wct

FICTIF = True
HORODATAGE = "2026-09-15T14:00:00-04:00"
LE_16 = "2026-09-16T09:00:00-04:00"
LE_17 = "2026-09-17T10:30:00-04:00"
MOTIF_LU = "Dépassement expliqué : gouttière refaite en cours de chantier."
MOTIF_CLOS = "Le client a accepté la facture révisée du chantier."


def _wct(wct_id="WCT-1", lead_id="LEAD-1"):
    return {
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "lead_id": lead_id,
        "technicien_id": "TECH-1",
        "horodatage_completion": HORODATAGE,
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"],
        "devis_id": f"devis-{wct_id}",
    }


def _variance(evenement_id="EVT-1", wct_id="WCT-1", critique=True, statut="evaluee", **surcharges):
    base = {
        "evenement_id": evenement_id,
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "chantier_id": "CH-1",
        "statut_variance": statut,
        "signal_critique": critique,
        "seuil_pourcentage": 0.1,
        "horodatage_completion": HORODATAGE,
        "lignes": [],
    }
    base.update(surcharges)
    return base


@pytest.fixture
def registres():
    return registre.Registre(), registre.Registre()


@pytest.fixture
def un_signal(registres):
    """Un WCT et sa variance critique EVT-1, affaire LEAD-1."""
    evenements, _ = registres
    wct.memoriser_wct(_wct(), evenements)
    variance.memoriser_variance(_variance(), evenements)
    return registres


def _traiter(registres, action, signal_id="EVT-1", par="amina.admin", role="admin", source="appareil",
             motif=MOTIF_LU, horodatage=LE_16):
    evenements, affaires = registres
    return signaux.traiter_signal(action, signal_id, par, role, source, motif, horodatage, evenements, affaires)


def _etat(registres, affaire_id="LEAD-1", signal_id="EVT-1"):
    evenements, affaires = registres
    tous = signaux.signaux_de_laffaire(affaire_id, evenements.lire(), affaires.lire())
    return next(s for s in tous if s["signal_id"] == signal_id)


def _prise_et_cloture(registres, **surcharges):
    assert _traiter(registres, signaux.ACTION_PRISE_EN_COMPTE)[1] is None
    return _traiter(registres, signaux.ACTION_CLOTURE, horodatage=LE_17, motif=MOTIF_CLOS, **surcharges)


# -- l'état de départ ----------------------------------------------------------------------------------
def test_un_signal_critique_est_ouvert_tant_que_personne_n_y_touche(un_signal):
    signal = _etat(un_signal)

    assert signal["etat"] == signaux.ETAT_OUVERT
    assert signal["affaire_id"] == "LEAD-1"
    assert (signal["traite_par"], signal["traite_le"], signal["motif"]) == (None, None, None)


def test_une_variance_sans_depassement_n_est_pas_un_signal(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct(), evenements)
    variance.memoriser_variance(_variance(critique=False), evenements)

    assert signaux.signaux_de_laffaire("LEAD-1", evenements.lire(), affaires.lire()) == []


def test_un_signal_est_de_l_affaire_de_son_wct_et_d_aucune_autre(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct("WCT-A", "LEAD-A"), evenements)
    wct.memoriser_wct(_wct("WCT-B", "LEAD-B"), evenements)
    variance.memoriser_variance(_variance("EVT-A", "WCT-A"), evenements)
    variance.memoriser_variance(_variance("EVT-B", "WCT-B"), evenements)

    ids = [s["signal_id"] for s in signaux.signaux_de_laffaire("LEAD-A", evenements.lire(), affaires.lire())]

    assert ids == ["EVT-A"]


# -- passer d'un état à l'autre ------------------------------------------------------------------------
def test_prise_en_compte_puis_cloture_ecrivent_qui_quand_et_pourquoi(un_signal):
    maillon_lu, verdict = _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE)
    assert verdict is None
    assert (maillon_lu["etat_resultant"], maillon_lu["par"], maillon_lu["role"]) == (
        "pris_en_compte", "amina.admin", "admin")
    assert (maillon_lu["source_decision"], maillon_lu["motif"], maillon_lu["horodatage"]) == (
        "appareil", MOTIF_LU, LE_16)
    assert (maillon_lu["signal_id"], maillon_lu["affaire_id"]) == ("EVT-1", "LEAD-1")
    assert _etat(un_signal)["etat"] == signaux.ETAT_PRIS_EN_COMPTE

    maillon_clos, verdict = _traiter(
        un_signal, signaux.ACTION_CLOTURE, par="nathan", role="nathan_owner", source="approbation",
        motif=MOTIF_CLOS, horodatage=LE_17,
    )
    assert verdict is None
    assert (maillon_clos["etat_resultant"], maillon_clos["par"], maillon_clos["source_decision"]) == (
        "clos", "nathan", "approbation")
    clos = _etat(un_signal)
    assert clos["etat"] == signaux.ETAT_CLOS
    assert (clos["traite_par"], clos["traite_le"], clos["motif"]) == ("nathan", LE_17, MOTIF_CLOS)


def test_le_registre_est_append_only_et_garde_les_deux_maillons(un_signal):
    _, affaires = un_signal
    _prise_et_cloture(un_signal)

    traites = [m for m in affaires.lire() if m["type_entree"] == signaux.TYPE_ENTREE_SIGNAL_TRAITE]

    assert [m["etat_resultant"] for m in traites] == ["pris_en_compte", "clos"]
    assert affaires.valider_chaine()[0] is True


def test_on_ne_cloture_pas_un_signal_dont_personne_n_a_pris_connaissance(un_signal):
    _, affaires = un_signal
    avant = len(affaires.lire())

    maillon, verdict = _traiter(un_signal, signaux.ACTION_CLOTURE)

    assert maillon is None and verdict["code"] == signaux.REJ_SIGNAL_PAS_PRIS_EN_COMPTE
    assert verdict["detail"]
    assert len(affaires.lire()) == avant
    assert _etat(un_signal)["etat"] == signaux.ETAT_OUVERT


def test_on_ne_prend_pas_deux_fois_connaissance_du_meme_signal(un_signal):
    _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE)

    _, verdict = _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE)

    assert verdict["code"] == signaux.REJ_SIGNAL_DEJA_PRIS_EN_COMPTE


@pytest.mark.parametrize("action", [signaux.ACTION_PRISE_EN_COMPTE, signaux.ACTION_CLOTURE])
def test_un_signal_clos_ne_se_rouvre_ni_ne_se_reclot(un_signal, action):
    _prise_et_cloture(un_signal)
    _, affaires = un_signal
    avant = len(affaires.lire())

    maillon, verdict = _traiter(un_signal, action)

    assert maillon is None and verdict["code"] == signaux.REJ_SIGNAL_DEJA_CLOS
    assert len(affaires.lire()) == avant
    assert _etat(un_signal)["etat"] == signaux.ETAT_CLOS


def test_un_signal_inconnu_est_refuse_et_ne_laisse_rien(un_signal):
    _, affaires = un_signal
    avant = len(affaires.lire())

    maillon, verdict = _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE, signal_id="EVT-INVENTE")

    assert maillon is None and verdict["code"] == signaux.REJ_SIGNAL_INCONNU
    assert len(affaires.lire()) == avant


def test_un_evenement_qui_n_est_pas_un_signal_critique_n_est_pas_traitable(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct(), evenements)
    variance.memoriser_variance(_variance("EVT-OK", critique=False), evenements)

    _, verdict = _traiter(registres, signaux.ACTION_PRISE_EN_COMPTE, signal_id="EVT-OK")
    _, verdict_wct = _traiter(registres, signaux.ACTION_PRISE_EN_COMPTE, signal_id="WCT-1")

    assert verdict["code"] == signaux.REJ_SIGNAL_INCONNU
    assert verdict_wct["code"] == signaux.REJ_SIGNAL_INCONNU
    assert affaires.lire() == []


def test_un_signal_dont_le_wct_est_inconnu_n_a_pas_d_affaire_et_n_est_pas_traite(registres):
    evenements, affaires = registres
    variance.memoriser_variance(_variance("EVT-ORPHELIN", "WCT-ABSENT"), evenements)

    _, verdict = _traiter(registres, signaux.ACTION_PRISE_EN_COMPTE, signal_id="EVT-ORPHELIN")

    assert verdict["code"] == signaux.REJ_SIGNAL_AFFAIRE_INCONNUE
    assert affaires.lire() == []


def test_une_action_inconnue_est_refusee(un_signal):
    _, verdict = _traiter(un_signal, "effacer")

    assert verdict["code"] == signaux.REJ_SIGNAL_ACTION_INCONNUE


# -- la forme d'un humain identifié -------------------------------------------------------------------
@pytest.mark.parametrize(
    "surcharges",
    [
        {"par": ""},
        {"par": "Amina Admin"},
        {"par": None},
        {"role": "system_agent"},
        {"role": "employee"},
        {"role": "manager"},
        {"role": None},
        {"source": "modele"},
        {"source": None},
    ],
)
def test_ce_qui_n_a_pas_la_forme_d_un_humain_identifie_n_ecrit_rien(un_signal, surcharges):
    _, affaires = un_signal
    arguments = {"par": "amina.admin", "role": "admin", "source": "appareil", **surcharges}

    maillon, verdict = _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE, **arguments)

    assert maillon is None and verdict["code"] == "REJ-HUMAIN-ACTEUR-INVALIDE"
    assert affaires.lire() == []


@pytest.mark.parametrize("motif", ["", "   ", "ok", "x" * 9, "x" * 501, None, 12345])
def test_un_motif_absent_ou_hors_bornes_est_refuse(un_signal, motif):
    _, affaires = un_signal

    maillon, verdict = _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE, motif=motif)

    assert maillon is None and verdict["code"] == "REJ-HUMAIN-MOTIF-INVALIDE"
    assert affaires.lire() == []


@pytest.mark.parametrize("horodatage", ["", "hier", "2026-09-16T09:00:00", None])
def test_un_horodatage_sans_fuseau_est_refuse(un_signal, horodatage):
    maillon, verdict = _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE, horodatage=horodatage)

    assert maillon is None and verdict["code"] == "REJ-HUMAIN-HORODATAGE-INVALIDE"


def _traitement_force(signal_id="EVT-1", **surcharges):
    """Un maillon écrit HORS du chemin de l'outil : ce que lirait le registre s'il avait été altéré."""
    base = {
        "type_entree": signaux.TYPE_ENTREE_SIGNAL_TRAITE, "horodatage": LE_16, "signal_id": signal_id,
        "affaire_id": "LEAD-1", "etat_resultant": "clos", "par": "amina.admin", "role": "admin",
        "source_decision": "appareil", "motif": MOTIF_CLOS,
    }
    base.update(surcharges)
    return base


@pytest.mark.parametrize(
    "surcharges",
    [
        {"role": "system_agent"},
        {"par": "Le Modele"},
        {"source_decision": "modele"},
        {"motif": ""},
        {"motif": "vu"},
        {"etat_resultant": "efface"},
        {"etat_resultant": "clos"},  # saute « pris en compte » : ne ferme rien
    ],
)
def test_un_maillon_force_qui_n_a_pas_la_forme_d_un_traitement_humain_ne_ferme_rien(un_signal, surcharges):
    _, affaires = un_signal
    affaires.ajouter(_traitement_force(**surcharges))

    assert _etat(un_signal)["etat"] == signaux.ETAT_OUVERT


def test_un_maillon_de_cloture_force_apres_la_prise_en_compte_sans_humain_ne_ferme_rien(un_signal):
    _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE)
    _, affaires = un_signal
    affaires.ajouter(_traitement_force(role="system_agent"))

    assert _etat(un_signal)["etat"] == signaux.ETAT_PRIS_EN_COMPTE


# -- la règle de réévaluation : la seule clôture qui n'est pas humaine ---------------------------------
def test_une_variance_reevaluee_sans_depassement_apres_le_signal_le_clot_par_la_regle(un_signal):
    evenements, _ = un_signal
    variance.memoriser_variance(_variance("EVT-REEVAL", critique=False), evenements)

    signal = _etat(un_signal)

    assert signal["etat"] == signaux.ETAT_CLOS
    assert signal["traite_par"] == signaux.REGLE_VARIANCE_REEVALUEE
    assert signal["fait_resolvant"] == "EVT-REEVAL"
    assert signal["motif"] == signaux.MOTIF_REGLE_VARIANCE_REEVALUEE


def test_la_cloture_par_la_regle_ne_s_ecrit_pas_elle_se_calcule(un_signal):
    evenements, affaires = un_signal
    variance.memoriser_variance(_variance("EVT-REEVAL", critique=False), evenements)
    avant = affaires.lire()

    _etat(un_signal)

    assert affaires.lire() == avant


def test_une_variance_sans_depassement_anterieure_au_signal_ne_le_resout_pas(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct(), evenements)
    variance.memoriser_variance(_variance("EVT-AVANT", critique=False), evenements)
    variance.memoriser_variance(_variance("EVT-1", critique=True), evenements)

    assert _etat(registres)["etat"] == signaux.ETAT_OUVERT


def test_une_variance_sans_depassement_d_un_autre_wct_ne_resout_rien(registres):
    evenements, _ = registres
    wct.memoriser_wct(_wct("WCT-1", "LEAD-1"), evenements)
    wct.memoriser_wct(_wct("WCT-2", "LEAD-1"), evenements)
    variance.memoriser_variance(_variance("EVT-1", "WCT-1", critique=True), evenements)
    variance.memoriser_variance(_variance("EVT-2", "WCT-2", critique=False), evenements)

    assert _etat(registres)["etat"] == signaux.ETAT_OUVERT


@pytest.mark.parametrize(
    "surcharges",
    [
        {"statut": "declaration_absente", "critique": None},
        {"statut": "prevu_absent", "critique": None},
        {"statut": "seuil_absent", "critique": None},
        {"critique": True},  # une nouvelle évaluation qui dépasse toujours
    ],
)
def test_seule_une_variance_evaluee_sans_depassement_resout(un_signal, surcharges):
    evenements, _ = un_signal
    variance.memoriser_variance(_variance("EVT-AUTRE", **surcharges), evenements)

    assert _etat(un_signal)["etat"] == signaux.ETAT_OUVERT


def test_une_nouvelle_variance_critique_est_un_nouveau_signal_ouvert(un_signal):
    evenements, affaires = un_signal
    _prise_et_cloture(un_signal)
    variance.memoriser_variance(_variance("EVT-2", critique=True), evenements)

    tous = signaux.signaux_de_laffaire("LEAD-1", evenements.lire(), affaires.lire())
    etats = {s["signal_id"]: s["etat"] for s in tous}

    assert etats == {"EVT-1": "clos", "EVT-2": "ouvert"}


def test_la_regle_clot_aussi_un_signal_deja_pris_en_compte_et_le_dit(un_signal):
    _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE)
    evenements, _ = un_signal
    variance.memoriser_variance(_variance("EVT-REEVAL", critique=False), evenements)

    signal = _etat(un_signal)

    assert signal["etat"] == signaux.ETAT_CLOS and signal["traite_par"] == signaux.REGLE_VARIANCE_REEVALUEE


def test_une_cloture_humaine_precede_la_regle(un_signal):
    _prise_et_cloture(un_signal)
    evenements, _ = un_signal
    variance.memoriser_variance(_variance("EVT-REEVAL", critique=False), evenements)

    signal = _etat(un_signal)

    assert signal["traite_par"] == "amina.admin" and signal["fait_resolvant"] is None


# -- ce que le paquet en montre ------------------------------------------------------------------------
def _fait_du_paquet(registres, signal_id="EVT-1"):
    evenements, affaires = registres
    paquet = paquets.assembler_paquet_contexte("LEAD-1", LE_17, evenements, affaires)
    couche = next(c for c in paquet["couches"] if c["nom"] == paquets.COUCHE_SIGNAUX_NON_RESOLUS)
    return next(f for f in couche["faits"] if f["identifiant"] == signal_id)


def test_le_fait_d_un_signal_ouvert_dit_qu_il_est_ouvert(un_signal):
    fait = _fait_du_paquet(un_signal)

    assert fait["source"] == "m6.variance_chantier" and fait["confidentialite"] == "INTERNAL"
    assert fait["etat"] == "ouvert" and fait["traite_par"] is None and fait["traite_le"] is None
    assert "OUVERT" in fait["resume"] and "personne" in fait["resume"]


def test_le_fait_d_un_signal_clos_dit_qui_l_a_clos_et_pourquoi(un_signal):
    _prise_et_cloture(un_signal)

    fait = _fait_du_paquet(un_signal)

    assert fait["etat"] == "clos" and fait["traite_par"] == "amina.admin" and fait["traite_le"] == LE_17
    assert "CLOS par amina.admin le 2026-09-17" in fait["resume"]
    assert MOTIF_CLOS in fait["resume"]


def test_le_fait_d_un_signal_pris_en_compte_dit_qui_et_pourquoi(un_signal):
    _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE)

    fait = _fait_du_paquet(un_signal)

    assert fait["etat"] == "pris_en_compte" and fait["traite_par"] == "amina.admin" and fait["traite_le"] == LE_16
    assert "pris en compte par amina.admin le 2026-09-16" in fait["resume"]
    assert MOTIF_LU in fait["resume"]


def test_le_fait_d_un_signal_clos_par_la_regle_cite_l_evenement_qui_le_resout(un_signal):
    evenements, _ = un_signal
    variance.memoriser_variance(_variance("EVT-REEVAL", critique=False), evenements)

    fait = _fait_du_paquet(un_signal)

    assert "règle de réévaluation (EVT-REEVAL)" in fait["resume"]
    assert fait["traite_par"] == signaux.REGLE_VARIANCE_REEVALUEE


def test_le_resume_garde_qui_meme_quand_le_motif_est_tres_long(un_signal):
    assert _traiter(un_signal, signaux.ACTION_PRISE_EN_COMPTE)[1] is None
    assert _traiter(un_signal, signaux.ACTION_CLOTURE, motif="x" * 500, horodatage=LE_17)[1] is None

    resume = _fait_du_paquet(un_signal)["resume"]

    assert resume.startswith("Variance EVT-1 : critique, CLOS par amina.admin le 2026-09-17")
    assert len(resume) == paquets.RESUME_MAX_CARACTERES and resume.endswith("…")


# -- décompte et ordre ---------------------------------------------------------------------------------
def test_le_decompte_couvre_tous_les_signaux_et_les_trois_etats(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct(), evenements)
    for i in (1, 2, 3):
        variance.memoriser_variance(_variance(f"EVT-{i}", "WCT-1", critique=True), evenements)
    assert _traiter(registres, signaux.ACTION_PRISE_EN_COMPTE, signal_id="EVT-2")[1] is None
    assert _traiter(registres, signaux.ACTION_PRISE_EN_COMPTE, signal_id="EVT-3")[1] is None
    assert _traiter(registres, signaux.ACTION_CLOTURE, signal_id="EVT-3", motif=MOTIF_CLOS, horodatage=LE_17)[1] is None

    decompte = signaux.decompte(signaux.signaux_de_laffaire("LEAD-1", evenements.lire(), affaires.lire()))

    assert decompte == {"nb_ouverts": 1, "nb_pris_en_compte": 1, "nb_clos": 1}


def test_les_signaux_sont_ordonnes_ouverts_puis_pris_en_compte_puis_clos(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct(), evenements)
    for i in (1, 2, 3, 4):
        variance.memoriser_variance(_variance(f"EVT-{i}", "WCT-1", critique=True), evenements)
    _traiter(registres, signaux.ACTION_PRISE_EN_COMPTE, signal_id="EVT-1")
    _traiter(registres, signaux.ACTION_CLOTURE, signal_id="EVT-1", motif=MOTIF_CLOS, horodatage=LE_17)
    _traiter(registres, signaux.ACTION_PRISE_EN_COMPTE, signal_id="EVT-2")

    ordre = [s["signal_id"] for s in signaux.signaux_de_laffaire("LEAD-1", evenements.lire(), affaires.lire())]

    # EVT-3 et EVT-4 sont ouverts (le plus récemment reçu d'abord), EVT-2 pris en compte, EVT-1 clos.
    assert ordre == ["EVT-4", "EVT-3", "EVT-2", "EVT-1"]


def test_les_clos_sont_du_plus_recemment_clos_au_plus_ancien(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct(), evenements)
    for i in (1, 2):
        variance.memoriser_variance(_variance(f"EVT-{i}", "WCT-1", critique=True), evenements)
    for signal_id, jour in (("EVT-1", "2026-09-20T08:00:00-04:00"), ("EVT-2", "2026-09-18T08:00:00-04:00")):
        _traiter(registres, signaux.ACTION_PRISE_EN_COMPTE, signal_id=signal_id, horodatage="2026-09-16T08:00:00-04:00")
        _traiter(registres, signaux.ACTION_CLOTURE, signal_id=signal_id, motif=MOTIF_CLOS, horodatage=jour)

    ordre = [s["signal_id"] for s in signaux.signaux_de_laffaire("LEAD-1", evenements.lire(), affaires.lire())]

    assert ordre == ["EVT-1", "EVT-2"]


def test_l_ordre_compare_des_instants_pas_du_texte(registres):
    """A (09h30 à UTC-5, soit 14h30 UTC) est plus récent que B (10h00 à UTC+1, soit 09h00 UTC) ; le texte
    des horodatages dirait l'inverse."""
    evenements, affaires = registres
    wct.memoriser_wct(_wct(), evenements)
    variance.memoriser_variance(_variance("EVT-A", horodatage_completion="2026-01-15T09:30:00-05:00"), evenements)
    variance.memoriser_variance(_variance("EVT-B", horodatage_completion="2026-01-15T10:00:00+01:00"), evenements)

    ordre = [s["signal_id"] for s in signaux.signaux_de_laffaire("LEAD-1", evenements.lire(), affaires.lire())]

    assert ordre == ["EVT-A", "EVT-B"]


# -- la liste d'un écran -------------------------------------------------------------------------------
def test_lister_filtre_par_affaire_et_dit_le_total(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct("WCT-A", "LEAD-A"), evenements)
    wct.memoriser_wct(_wct("WCT-B", "LEAD-B"), evenements)
    variance.memoriser_variance(_variance("EVT-A", "WCT-A"), evenements)
    variance.memoriser_variance(_variance("EVT-B", "WCT-B"), evenements)

    une_affaire = signaux.lister("LEAD-A", evenements.lire(), affaires.lire())
    toutes = signaux.lister(None, evenements.lire(), affaires.lire())

    assert [s["signal_id"] for s in une_affaire["signaux"]] == ["EVT-A"]
    assert {s["signal_id"] for s in toutes["signaux"]} == {"EVT-A", "EVT-B"}
    assert toutes["nb_total"] == 2 and toutes["nb_omis"] == 0 and toutes["nb_ouverts"] == 2


def test_lister_borne_la_liste_et_dit_ce_qu_il_omet(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct(), evenements)
    for i in range(signaux.NB_SIGNAUX_LISTES_MAX + 7):
        variance.memoriser_variance(_variance(f"EVT-{i:03d}", "WCT-1"), evenements)

    liste = signaux.lister("LEAD-1", evenements.lire(), affaires.lire())

    assert len(liste["signaux"]) == signaux.NB_SIGNAUX_LISTES_MAX
    assert liste["nb_total"] == signaux.NB_SIGNAUX_LISTES_MAX + 7
    assert liste["nb_omis"] == 7
    assert liste["nb_ouverts"] == signaux.NB_SIGNAUX_LISTES_MAX + 7  # le décompte n'est pas tronqué


def test_lister_montre_qui_et_pourquoi(un_signal):
    _prise_et_cloture(un_signal)
    evenements, affaires = un_signal

    [signal] = signaux.lister("LEAD-1", evenements.lire(), affaires.lire())["signaux"]

    assert (signal["etat"], signal["traite_par"], signal["traite_le"], signal["motif"]) == (
        "clos", "amina.admin", LE_17, MOTIF_CLOS)
