"""PLAN T1.5-d : M10 mémorise la rentabilité d'un chantier de M5 (`m5.rentabilite_chantier`), la leçon « marge
réelle contre marge prévue » de l'affaire.

Comme la variance de M6 : même registre Événements, même `type_entree`, charge gardée TELLE QUELLE, distinguée à la
lecture par un champ propre (`classification.py`). Contrairement à elle : l'entrée est marquée `FINANCIAL` et ne
sort donc dans AUCUN paquet de contexte, pour aucun agent (M1 parle au client). Un coût partiel de M5 n'a pas de
marge : M10 n'en ajoute jamais.

Trois étages : les modules purs, la lecture par les outils (paquet, consolidation, audit) et le VRAI bus, sur une
base SQLite temporaire migrée. Charges fictives, conformes au catalogue du socle.
"""

from __future__ import annotations

import json

import m10_memoire.outils as outils_mod
import pytest
from m10_memoire import (
    audit,
    classification,
    confidentialite,
    consolidation,
    paquets,
    registre,
    rentabilite,
    signaux,
    variance,
    wct,
)

from opsys import contexte, evenements, stockage
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge

FICTIF = True
HORODATAGE = "2026-09-15T14:00:00-04:00"
HORODATAGE_PAQUET = "2026-09-16T08:00:00-04:00"
JOUR = "2026-09-15"
TYPE = "m5.rentabilite_chantier"
MONTANTS_DE_MARGE = ("114.00", "120.00", "-6.00", "486.00")


def _wct(wct_id="WCT-1", lead_id="LEAD-1", **overrides):
    base = {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": lead_id, "technicien_id": "TECH-1",
        "horodatage_completion": HORODATAGE, "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90, "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"], "devis_id": f"devis-{wct_id}",
    }
    base.update(overrides)
    return base


def _variance(evenement_id="m6-variance-WCT-1-evaluee", wct_id="WCT-1", **overrides):
    base = {
        "evenement_id": evenement_id, "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "chantier_id": "CH-1",
        "statut_variance": "evaluee", "signal_critique": False, "seuil_pourcentage": 0.3,
        "horodatage_completion": HORODATAGE, "lignes": [],
    }
    base.update(overrides)
    return base


def _rentabilite(sequence=1, verdict="CALCULEE", wct_id="WCT-1", **overrides):
    """Charge `m5.rentabilite_chantier` : CALCULEE (marge 114.00 contre 120.00 prévus) ou PARTIELLE (aucune marge)."""
    complete = verdict == "CALCULEE"
    base = {
        "evenement_id": f"m5-rentabilite-devis-{wct_id}-{sequence}-{sequence:016x}", "devis_id": f"devis-{wct_id}",
        "chantier_id": "CH-1", "wct_id": wct_id, "sequence": sequence, "version_entrees": f"{sequence:064x}",
        "horodatage_completion": HORODATAGE, "verdict": verdict, "devise": "CAD",
        "cout_reel_complet": complete, "cout_reel_cad": "486.00" if complete else None,
        "cout_connu_cad": "486.00" if complete else "150.00",
        "marge_reelle_cad": "114.00" if complete else None, "marge_prevue_cad": "120.00",
        "ecart_marge_cad": "-6.00" if complete else None,
        "manque": [] if complete else ["REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"],
    }
    base.update(overrides)
    return base


@pytest.fixture
def registres():
    return registre.Registre(), registre.Registre()


def _couche(paquet, nom):
    return next(c for c in paquet["couches"] if c["nom"] == nom)


# =========================================================================================
# 1. Modules purs
# =========================================================================================
def test_la_charge_de_test_est_conforme_au_catalogue():
    assert erreurs_charge(TYPE, _rentabilite()) == []
    assert erreurs_charge(TYPE, _rentabilite(verdict="PARTIELLE")) == []


def test_memoriser_ecrit_un_evenement_memorise_au_niveau_financial(registres):
    registre_evenements, _ = registres

    maillon, verdict = rentabilite.memoriser_rentabilite(_rentabilite(), registre_evenements)

    assert verdict is None
    assert maillon["type_entree"] == "evenement_memorise" and maillon["ligne_id"]
    assert maillon["confidentialite"] == confidentialite.NIVEAU_FINANCIER == "FINANCIAL"
    assert confidentialite.niveau_de(maillon) == "FINANCIAL"
    assert maillon["horodatage"] == HORODATAGE  # l'instant du WCT : M10 n'a pas d'horloge
    assert len(registre_evenements.lire()) == 1


def test_memoriser_conserve_la_charge_telle_quelle_et_ne_calcule_aucune_marge(registres):
    registre_evenements, _ = registres
    for charge in (_rentabilite(), _rentabilite(sequence=2, verdict="PARTIELLE")):
        maillon, _ = rentabilite.memoriser_rentabilite(charge, registre_evenements)
        for champ, valeur in charge.items():
            assert maillon[champ] == valeur, champ

    partiel = registre_evenements.lire()[-1]
    assert partiel["marge_reelle_cad"] is None and partiel["ecart_marge_cad"] is None
    assert partiel["manque"] == ["REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]


def test_une_charge_qui_porterait_deja_un_niveau_ne_peut_pas_ouvrir_l_entree(registres):
    registre_evenements, _ = registres

    maillon, _ = rentabilite.memoriser_rentabilite(_rentabilite(confidentialite="PUBLIC_INTERNAL"), registre_evenements)

    assert maillon["confidentialite"] == "FINANCIAL"


def test_memoriser_chaine_les_maillons_et_la_chaine_reste_valide(registres):
    registre_evenements, _ = registres
    premier, _ = rentabilite.memoriser_rentabilite(_rentabilite(sequence=1), registre_evenements)
    second, _ = rentabilite.memoriser_rentabilite(_rentabilite(sequence=2), registre_evenements)

    assert second["precedent_ligne_id"] == premier["ligne_id"]
    assert registre_evenements.valider_chaine() == (True, "")


# -- classification ---------------------------------------------------------------------
def test_la_classification_reconnait_la_rentabilite_par_son_champ_propre(registres):
    registre_evenements, _ = registres
    rentabilite.memoriser_rentabilite(_rentabilite(), registre_evenements)
    variance.memoriser_variance(_variance(), registre_evenements)
    wct.memoriser_wct(_wct(), registre_evenements)
    m_rentabilite, m_variance, m_wct = registre_evenements.lire()

    assert classification.type_evenement(m_rentabilite) == classification.TYPE_RENTABILITE == TYPE
    assert classification.type_evenement(m_variance) == classification.TYPE_VARIANCE
    assert classification.type_evenement(m_wct) == classification.TYPE_WCT
    assert classification.identifiant(m_rentabilite) == m_rentabilite["evenement_id"]  # la clé publique, pas ligne_id
    assert classification.identifiant(m_wct) == "WCT-1"


def test_l_affaire_d_une_rentabilite_vient_de_son_wct_jamais_devinee(registres):
    registre_evenements, _ = registres
    rentabilite.memoriser_rentabilite(_rentabilite(), registre_evenements)
    (m_rentabilite,) = registre_evenements.lire()

    sans_wct = classification.index_lead_id_par_wct_id(registre_evenements.lire())
    assert classification.lead_id(m_rentabilite, sans_wct) is None  # reçue avant son WCT : pas d'affaire

    wct.memoriser_wct(_wct(lead_id="LEAD-7"), registre_evenements)
    index = classification.index_lead_id_par_wct_id(registre_evenements.lire())
    assert classification.lead_id(m_rentabilite, index) == "LEAD-7"
    de_l_affaire = classification.evenements_de_laffaire("LEAD-7", registre_evenements.lire())
    assert m_rentabilite["ligne_id"] in [m["ligne_id"] for m in de_l_affaire]
    assert classification.evenements_de_laffaire("LEAD-AUTRE", registre_evenements.lire()) == []


def test_une_rentabilite_recue_avant_son_wct_ne_fait_pas_oublier_le_wct(registres):
    """`memoriser_wct` est idempotent par `wct_id` ; ce doublon ne compte que pour un WCT, pas pour la rentabilité
    ni pour la variance qui portent le même `wct_id` (sinon le WCT ne serait jamais écrit)."""
    registre_evenements, _ = registres
    rentabilite.memoriser_rentabilite(_rentabilite(), registre_evenements)
    variance.memoriser_variance(_variance(), registre_evenements)

    maillon, verdict = wct.memoriser_wct(_wct(), registre_evenements)
    assert verdict is None and classification.type_evenement(maillon) == classification.TYPE_WCT
    assert [classification.type_evenement(m) for m in registre_evenements.lire()] == [
        classification.TYPE_RENTABILITE, classification.TYPE_VARIANCE, classification.TYPE_WCT]

    encore, _ = wct.memoriser_wct(_wct(), registre_evenements)  # l'idempotence par wct_id reste
    assert encore["ligne_id"] == maillon["ligne_id"] and len(registre_evenements.lire()) == 3


def test_une_rentabilite_n_est_jamais_un_signal_critique(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(), registre_evenements)
    rentabilite.memoriser_rentabilite(_rentabilite(verdict="PARTIELLE"), registre_evenements)

    assert signaux.signaux_de_laffaire("LEAD-1", registre_evenements.lire(), registre_affaires.lire()) == []


# =========================================================================================
# 2. La marge ne sort dans aucun paquet ; le compte, oui ; l'audit la trace
# =========================================================================================
def _registres_avec_marge(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(), registre_evenements)
    rentabilite.memoriser_rentabilite(_rentabilite(), registre_evenements)
    return registre_evenements, registre_affaires


@pytest.mark.parametrize("agent", [None, "m01-front-office", "m02-revenue-crm", "m03-estimation",
                                    "m05-financecore", "m08-analytics"])
def test_aucun_paquet_ne_montre_la_marge_a_aucun_agent_mais_compte_l_element_retenu(registres, agent):
    registre_evenements, registre_affaires = _registres_avec_marge(registres)

    paquet = paquets.assembler_paquet_contexte(
        "LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent=agent)

    evenements_recents = _couche(paquet, paquets.COUCHE_EVENEMENTS_RECENTS)
    assert [f["source"] for f in evenements_recents["faits"]] == [classification.TYPE_WCT]  # le WCT, pas la marge
    assert paquet["confidentialite"]["nb_retenus"] == 1  # retenue et seulement comptée
    texte = json.dumps(paquet, ensure_ascii=False)
    for montant in MONTANTS_DE_MARGE:
        assert montant not in texte, (agent, montant)
    assert "m5-rentabilite" not in texte and "marge" not in texte.lower()  # ni son identifiant, ni son nom


def test_le_resume_d_une_rentabilite_ne_porte_jamais_de_montant_meme_sans_marquage(registres):
    """Défense en profondeur : un maillon écrit SANS niveau serait INTERNAL (donc rendu) ; son résumé n'a de
    toute façon aucun montant."""
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(), registre_evenements)
    registre_evenements.ajouter({**_rentabilite(), "type_entree": "evenement_memorise", "horodatage": HORODATAGE})

    paquet = paquets.assembler_paquet_contexte(
        "LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent="m01-front-office")

    faits = _couche(paquet, paquets.COUCHE_EVENEMENTS_RECENTS)["faits"]
    (fait,) = [f for f in faits if f["source"] == TYPE]
    assert fait["resume"] == f"Rentabilité {_rentabilite()['evenement_id']} : CALCULEE"
    for montant in MONTANTS_DE_MARGE:
        assert montant not in json.dumps(paquet, ensure_ascii=False)


def test_la_consolidation_compte_la_rentabilite_sans_aucun_montant_et_cite_sa_source(registres):
    registre_evenements, registre_affaires = _registres_avec_marge(registres)

    resultat = consolidation.consolider_affaire(
        "LEAD-1", JOUR, HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    assert resultat["ecrit"] is True
    fait = resultat["fait"]
    assert fait["resume"] == "1 travaux terminés, 1 rentabilité(s) de chantier"
    types = {source["type_evenement"]: source["identifiant"] for source in fait["sources"]}
    assert types[TYPE] == _rentabilite()["evenement_id"]
    for montant in MONTANTS_DE_MARGE:
        assert montant not in json.dumps(fait, ensure_ascii=False)  # le fait consolidé n'est pas FINANCIAL
    assert confidentialite.niveau_de(fait) == "INTERNAL"

    # Idempotent, comme pour tout autre événement.
    encore = consolidation.consolider_affaire("LEAD-1", JOUR, HORODATAGE_PAQUET, registre_evenements, registre_affaires)
    assert encore["ecrit"] is False and encore["deja_consolide"] is True


def test_la_consolidation_d_un_jour_sans_rentabilite_ne_change_pas(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(), registre_evenements)
    variance.memoriser_variance(_variance(signal_critique=True), registre_evenements)

    fait = consolidation.consolider_affaire(
        "LEAD-1", JOUR, HORODATAGE_PAQUET, registre_evenements, registre_affaires)["fait"]

    assert fait["resume"] == "1 travaux terminés, 1 variance(s) matériaux dont 1 critique(s)"


def test_l_audit_non_oubli_verifie_la_trace_d_une_rentabilite_attendue(registres):
    registre_evenements, registre_affaires = registres
    charge = _rentabilite()
    rentabilite.memoriser_rentabilite(charge, registre_evenements)

    present = audit.auditer_non_oubli(
        [{"type_evenement": TYPE, "identifiant": charge["evenement_id"]}], registre_evenements, registre_affaires)
    assert present["nb_oublis"] == 0 and present["total_attendus"] == 1

    absent = audit.auditer_non_oubli(
        [{"type_evenement": TYPE, "identifiant": "m5-rentabilite-jamais-recue"}], registre_evenements,
        registre_affaires)
    assert absent["oublis"] == [{
        "type_evenement": TYPE, "identifiant": "m5-rentabilite-jamais-recue",
        "verdict": audit.REJ_AUDIT_TRACE_ABSENTE}]

    inconnu = audit.auditer_non_oubli(
        [{"type_evenement": "m5.autre", "identifiant": "x"}], registre_evenements, registre_affaires)
    assert inconnu["oublis"][0]["verdict"] == audit.REJ_AUDIT_TYPE_INCONNU


def test_l_outil_d_audit_accepte_le_type_rentabilite_dans_son_schema():
    outil = next(o for o in outils_mod.outils() if o.nom == "m10_auditer_non_oubli")
    enum = outil.parametres["properties"]["identifiants_attendus"]["items"]["properties"]["type_evenement"]["enum"]
    # Les trois d'abord ; l'amont de l'affaire (T4.18) ensuite, dans l'ordre de l'entonnoir.
    assert enum[:3] == ["m4.travaux_termines", "m6.variance_chantier", "m5.rentabilite_chantier"]
    assert enum[3:] == [
        "m1.lead_qualifie", "m2.client_associe", "m3.devis_envoye", "m3.devis_accepte", "m3.devis_sans_reponse"]


# =========================================================================================
# 3. Le vrai bus
# =========================================================================================
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _deps_bus():
    return {"m10-memoire": charger_departements()["m10-memoire"]}


def _quarantaine_m10():
    return [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == "m10-memoire"]


def _maillons_rentabilite():
    return [m for m in stockage.maillons("m10-memoire", "evenements") if "marge_reelle_cad" in m]


def test_le_bus_livre_la_rentabilite_a_m10_qui_la_memorise_une_fois_au_niveau_financial(base_durable):
    charge = _rentabilite()
    evenements.publier(TYPE, "m05-financecore", charge, evenement_id=charge["evenement_id"])

    resume = evenements.repartir(_deps_bus(), maintenant="2026-09-15T14:05:00-04:00")

    assert resume["traites"] == 1 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    (maillon,) = _maillons_rentabilite()
    assert maillon["type_entree"] == "evenement_memorise" and maillon["confidentialite"] == "FINANCIAL"
    assert maillon["ecart_marge_cad"] == "-6.00" and maillon["marge_reelle_cad"] == "114.00"
    assert maillon["horodatage"] == charge["horodatage_completion"]
    assert _quarantaine_m10() == []

    # Redélivraison : idempotent, aucun second maillon.
    encore = evenements.repartir(_deps_bus(), maintenant="2026-09-15T14:05:00-04:00")
    assert encore == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len(_maillons_rentabilite()) == 1


def test_chaque_version_publiee_par_m5_est_un_maillon_et_le_partiel_reste_sans_marge(base_durable):
    for charge in (_rentabilite(sequence=1, verdict="PARTIELLE"), _rentabilite(sequence=2)):
        evenements.publier(TYPE, "m05-financecore", charge, evenement_id=charge["evenement_id"])
    evenements.repartir(_deps_bus(), maintenant="2026-09-15T14:05:00-04:00")

    maillons = sorted(_maillons_rentabilite(), key=lambda m: m["sequence"])
    assert [(m["sequence"], m["verdict"], m["marge_reelle_cad"]) for m in maillons] == [
        (1, "PARTIELLE", None), (2, "CALCULEE", "114.00")]
    ok, _ = registre.Registre(maillons=stockage.maillons("m10-memoire", "evenements")).valider_chaine()
    assert ok is True


def test_de_bout_en_bout_le_wct_et_la_rentabilite_forment_l_affaire_et_la_marge_reste_dans_le_registre(base_durable):
    """Le WCT donne l'affaire ; la rentabilité, la leçon financière. Le paquet et la consolidation par les VRAIS
    outils de M10 ne montrent aucun montant ; l'audit prouve que la trace existe."""
    charge = _rentabilite()
    evenements.publier("m4.travaux_termines", "m04-field-ops", {
        **_wct(), "statut": "completed_verified", "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"]})
    evenements.publier(TYPE, "m05-financecore", charge, evenement_id=charge["evenement_id"])
    resume = evenements.repartir(_deps_bus(), maintenant="2026-09-15T14:05:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    with stockage.transaction():
        for agent in (None, "m01-front-office", "m02-revenue-crm"):
            with contexte.appeler_en_tant_que(agent):
                paquet = outils_mod.paquet_contexte_affaire("LEAD-1", HORODATAGE_PAQUET)
            assert paquet["confidentialite"]["nb_retenus"] == 1
            texte = json.dumps(paquet, ensure_ascii=False)
            assert not [m for m in MONTANTS_DE_MARGE if m in texte], agent

        consolide = outils_mod.consolider_affaire("LEAD-1", JOUR, HORODATAGE_PAQUET)
        assert consolide["fait"]["resume"] == "1 travaux terminés, 1 rentabilité(s) de chantier"

        rapport = outils_mod.auditer_non_oubli([
            {"type_evenement": "m4.travaux_termines", "identifiant": "WCT-1"},
            {"type_evenement": TYPE, "identifiant": charge["evenement_id"]},
        ])
        assert rapport["nb_oublis"] == 0 and rapport["chaine_evenements_intacte"] is True
