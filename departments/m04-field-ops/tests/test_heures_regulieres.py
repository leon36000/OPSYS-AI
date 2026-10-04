from pathlib import Path

import pytest
from m4_field_ops import heures_regulieres
from m4_field_ops import registre as registre_mod
from m4_field_ops.outils import outils

from opsys import approbations, contexte, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Niveau, executer_atomique

RACINE = Path(__file__).resolve().parents[1]


def _points():
    return [
        {"type_entree": "transition_statut", "intervention_id": "I1", "statut": "en_route",
         "horodatage": "2026-09-14T12:45:00+00:00", "ligne_id": "a" * 64,
         "precedent_ligne_id": "b" * 64},
        {"type_entree": "pointage", "intervention_id": "I1", "technicien_id": "T1", "action": "arrivee",
         "horodatage": "2026-09-14T13:00:00+00:00", "ligne_id": "c" * 64,
         "precedent_ligne_id": "a" * 64, "latitude": 45.0, "longitude": -73.0},
        {"type_entree": "pointage", "intervention_id": "I1", "technicien_id": "T1", "action": "depart",
         "horodatage": "2026-09-14T15:00:00+00:00", "ligne_id": "d" * 64,
         "precedent_ligne_id": "c" * 64},
    ]


def test_preview_uses_exact_pointage_timestamps_and_only_hash_references():
    original = _points()
    result = heures_regulieres.previsualiser(original, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert result["accepte"] is True
    assert result["resultat"]["categories_minutes"] == {"travail": 120, "deplacement": 15, "pause": 0}
    assert result["resultat"]["details_intervalles"][0]["travail"]["debut"] == "2026-09-14T09:00:00-04:00"
    assert result["resultat"]["sources"] == ["a" * 64, "c" * 64, "d" * 64]
    assert "latitude" not in repr(result) and "longitude" not in repr(result)
    assert all("_dt_local" not in m for m in original)


def test_preview_refuses_incomplete_pair_and_period_crossing():
    points = _points()[:-1]
    refused = heures_regulieres.previsualiser(points, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert refused["accepte"] is False
    points = _points()
    points[-1] = {**points[-1], "horodatage": "2026-09-15T05:00:00+00:00"}
    refused = heures_regulieres.previsualiser(points, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert refused["accepte"] is False


def test_preview_refuses_implicit_minute_rounding():
    points = _points()
    points[-1] = {**points[-1], "horodatage": "2026-09-14T15:00:30+00:00"}
    result = heures_regulieres.previsualiser(points, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-PRECISION-MINUTE"


def test_preview_separe_travail_net_et_pause_sans_double_compter():
    points = _points()
    points.extend([
        {"type_entree": "pointage", "intervention_id": "I1", "technicien_id": "T1",
         "action": "pause_debut", "horodatage": "2026-09-14T14:00:00+00:00", "ligne_id": "e" * 64},
        {"type_entree": "pointage", "intervention_id": "I1", "technicien_id": "T1",
         "action": "pause_fin", "horodatage": "2026-09-14T14:30:00+00:00", "ligne_id": "f" * 64},
    ])
    result = heures_regulieres.previsualiser(points, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert result["resultat"]["categories_minutes"] == {"travail": 90, "deplacement": 15, "pause": 30}
    categories = result["resultat"]["categories_minutes"]
    assert categories["travail"] + categories["pause"] == 120


def test_preview_ignore_les_autres_periodes_et_refuse_chevauchements():
    prior = _points()
    for row in prior:
        row["intervention_id"] = "I-OLD"
        if row.get("type_entree") == "transition_statut":
            row["horodatage"] = "2026-09-13T12:45:00+00:00"
        elif row.get("action") == "arrivee":
            row["horodatage"] = "2026-09-13T13:00:00+00:00"
        elif row.get("action") == "depart":
            row["horodatage"] = "2026-09-13T15:00:00+00:00"
    current = _points()
    result = heures_regulieres.previsualiser(prior + current, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert result["accepte"] is True
    assert all(ref in result["resultat"]["sources"] for ref in (row["ligne_id"] for row in current))

    other = []
    for row in current:
        copied = {**row, "intervention_id": "I2"}
        other.append(copied)
    result = heures_regulieres.previsualiser(current + other, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-INTERVENTIONS-CHEVAUCHEES"


def test_preview_refuse_une_intervention_qui_traverse_la_periode():
    rows = _points()
    rows[0]["horodatage"] = "2026-09-13T12:45:00+00:00"
    rows[1]["horodatage"] = "2026-09-13T13:00:00+00:00"
    result = heures_regulieres.previsualiser(rows, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-INTERVALLE-HORS-PERIODE"


def test_preview_refuse_traversee_complete_sans_borne_dans_la_periode():
    traverse = _points()
    traverse[0]["horodatage"] = "2026-09-13T12:45:00+00:00"
    traverse[1]["horodatage"] = "2026-09-13T13:00:00+00:00"
    traverse[2]["horodatage"] = "2026-09-15T15:00:00+00:00"
    traverse[0]["intervention_id"] = "I-TRAVERSE"
    traverse[1]["intervention_id"] = "I-TRAVERSE"
    traverse[2]["intervention_id"] = "I-TRAVERSE"
    current = _points()
    current[0]["intervention_id"] = "I-CURRENT"
    current[1]["intervention_id"] = "I-CURRENT"
    current[2]["intervention_id"] = "I-CURRENT"
    result = heures_regulieres.previsualiser(
        traverse + current, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-INTERVALLE-HORS-PERIODE"


def test_preview_refuse_sequence_anterieure_incomplete_non_bornee():
    incomplete = _points()[:2]
    incomplete[0]["horodatage"] = "2026-09-13T12:45:00+00:00"
    incomplete[1]["horodatage"] = "2026-09-13T13:00:00+00:00"
    incomplete[0]["intervention_id"] = "I-OUVERT"
    incomplete[1]["intervention_id"] = "I-OUVERT"
    current = _points()
    current[0]["intervention_id"] = "I-CURRENT"
    current[1]["intervention_id"] = "I-CURRENT"
    current[2]["intervention_id"] = "I-CURRENT"
    result = heures_regulieres.previsualiser(
        incomplete + current, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-POINTAGES-AMBIGUS"


@pytest.mark.parametrize("debut,fin", [
    ("2026-9-14", "2026-09-14"),
    ("2026-09-14T00:00:00", "2026-09-14"),
    ("2026-01-01", "2026-02-02"),
])
def test_preview_refuse_dates_non_iso_ou_periode_excessive(debut, fin):
    result = heures_regulieres.previsualiser(_points(), "T1", debut, fin, "America/Montreal")
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-PERIODE-INVALIDE"


def test_preview_refuse_conversion_utc_hors_datetime_sans_limite_annee_arbitraire():
    tokyo = heures_regulieres.previsualiser(
        [], "technicien-fictif", "0001-01-01", "0001-01-01", "Asia/Tokyo",
    )
    assert tokyo["accepte"] is False
    assert tokyo["verdict"]["code"] == "REJ-PERIODE-INVALIDE"

    utc_sans_sources = heures_regulieres.previsualiser(
        [], "technicien-fictif", "0001-01-01", "0001-01-01", "UTC",
    )
    assert utc_sans_sources["accepte"] is False
    assert utc_sans_sources["verdict"]["code"] == "REJ-SOURCES-ABSENTES"


def test_preview_refuses_naive_route_timestamp():
    points = _points()
    points[0]["horodatage"] = "2026-09-14T12:45:00"
    result = heures_regulieres.previsualiser(points, "T1", "2026-09-14", "2026-09-14", "America/Montreal")
    assert result["accepte"] is False


def test_preview_calcule_utc_pendant_repli_heure_dst():
    rows = _points()
    rows[0]["horodatage"] = "2026-11-01T05:00:00+00:00"
    rows[1]["horodatage"] = "2026-11-01T05:30:00+00:00"
    rows[2]["horodatage"] = "2026-11-01T06:30:00+00:00"
    result = heures_regulieres.previsualiser(rows, "T1", "2026-11-01", "2026-11-01", "America/Montreal")
    assert result["accepte"] is True
    assert result["resultat"]["categories_minutes"] == {"travail": 60, "deplacement": 30, "pause": 0}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'heures.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield
    stockage.liberer()


def _source_durable():
    reg = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal"))
    for m in _points():
        m = {**m, "technicien_id": "tech1"}
        prive = {"ligne_id", "precedent_ligne_id", "latitude", "longitude"}
        reg.ajouter({k: v for k, v in m.items() if k not in prive})


def test_sqlite_n4_revalide_hash_et_persiste_decision_signataire(base_durable):
    par_nom = {o.nom: o for o in outils()}
    args_preview = {"technicien_id": "tech1", "debut": "2026-09-14", "fin": "2026-09-14",
                    "fuseau": "America/Montreal"}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "tech1", "Technicien", "mot-de-passe-tech1-long", ["employee"])
        identite.creer_personne(cnx, "admin1", "Admin", "mot-de-passe-admin1-long", ["admin"])
        _source_durable()
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        preview = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], args_preview)
    assert preview["ok"] and preview["resultat"]["accepte"]
    sans_identite = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], args_preview)
    assert not sans_identite["resultat"]["accepte"]
    proposition = preview["resultat"]["resultat"]
    args = {**args_preview, "empreinte_sources": proposition["empreinte_sources"],
            "categories_minutes": proposition["categories_minutes"],
            "details_intervalles": proposition["details_intervalles"], "sources": proposition["sources"],
            "validation_precedente_attendue": proposition["validation_precedente"],
            "motif_correction": "Première approbation après revue des sources.",
            "couverture_complete": True, "classification_reguliere_confirmee": True,
            "dispositions": {k: {"inclure": k == "travail", "source": "décision humaine vérifiée"}
                             for k in ("travail", "deplacement", "pause")}}
    appel_direct = executer_atomique(par_nom["m4_valider_heures_regulieres"], args)
    assert not appel_direct["resultat"]["accepte"]
    assert appel_direct["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, "m04-field-ops", "m4_valider_heures_regulieres", args,
                                              niveau=Niveau.N4)
        decision = approbations.decider(cnx, demande, True, "admin1", par_nom,
                                        {"m04-field-ops": lire_manifeste(RACINE)})
    assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"]
    stored = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal")).lire()[-1]
    assert stored["type_entree"] == "heures_regulieres_validees"
    assert stored["minutes_regulieres"] == 120
    assert (stored["approuve_par"], stored["role_approbateur"]) == ("admin1", "admin")
    assert not ({"latitude", "longitude", "gps_coherent", "position_chiffree"} & set(stored))
    with pytest.raises(ValueError), stockage.transaction() as cnx:
        approbations.decider(cnx, demande, True, "admin1", par_nom,
                             {"m04-field-ops": lire_manifeste(RACINE)})
    assert len([m for m in registre_mod.Registre(stockage.maillons("m04-field-ops", "principal")).lire()
                if m.get("type_entree") == "heures_regulieres_validees"]) == 1
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        preview2 = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], args_preview)
    p2 = preview2["resultat"]["resultat"]
    correction = {**args_preview, "empreinte_sources": p2["empreinte_sources"],
                  "categories_minutes": p2["categories_minutes"],
                  "details_intervalles": p2["details_intervalles"], "sources": p2["sources"],
                  "validation_precedente_attendue": p2["validation_precedente"],
                  "couverture_complete": True, "classification_reguliere_confirmee": True,
                  "motif_correction": "Correction après revue humaine documentée."}
    correction["dispositions"] = {
        k: {"inclure": k == "deplacement", "source": "Décision de correction"}
        for k in ("travail", "deplacement", "pause")
    }
    with stockage.transaction() as cnx:
        demande2 = approbations.creer_demande(cnx, "m04-field-ops", "m4_valider_heures_regulieres", correction,
                                               niveau=Niveau.N4)
        decision2 = approbations.decider(cnx, demande2, True, "admin1", par_nom,
                                         {"m04-field-ops": lire_manifeste(RACINE)})
    assert decision2["statut"] == "executee"
    records = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal")).lire()
    validations = [m for m in records if m.get("type_entree") == "heures_regulieres_validees"]
    assert len(validations) == 2 and validations[-1]["revision"] == 2
    assert validations[-1]["remplace_ligne_id"] == validations[0]["ligne_id"]
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        current = executer_atomique(par_nom["m4_lire_heures_regulieres_validees"], args_preview)
    assert current["resultat"]["resultat"]["ligne_id"] == validations[-1]["ligne_id"], current


def test_apercu_refuse_chaine_alteree_meme_si_ligne_id_est_inchange(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "tech1", "Technicien", "mot-de-passe-tech1-long", ["employee"])
        identite.creer_personne(cnx, "admin1", "Admin", "mot-de-passe-admin1-long", ["admin"])
    reg = registre_mod.Registre()
    for row in _points():
        row = {**row, "technicien_id": "tech1"}
        reg.ajouter({k: v for k, v in row.items() if k not in {
            "ligne_id", "precedent_ligne_id", "latitude", "longitude"}})
    ligne_originale = reg._chain[-1]["ligne_id"]
    reg._chain[-1]["horodatage"] = "2026-09-14T16:00:00+00:00"
    assert reg._chain[-1]["ligne_id"] == ligne_originale
    assert reg.valider_chaine() is False
    par_nom = {o.nom: o for o in outils(registre_cible=reg)}
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        reponse = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], {
            "technicien_id": "tech1", "debut": "2026-09-14", "fin": "2026-09-14",
            "fuseau": "America/Montreal"})
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-REGISTRE-INVALIDE"
    assert "categories_minutes" not in reponse["resultat"]


@pytest.mark.parametrize("acteur,role,actif,accepte", [
    (None, None, True, False),
    ("employe", "employee", True, False),
    ("vendeur", "seller", True, False),
    ("gestionnaire", "manager", True, False),
    ("admin_inactif", "admin", False, False),
])
def test_lectures_privees_refusees_avant_lecture_registre(base_durable, acteur, role, actif, accepte):
    class RegistreObserve(registre_mod.Registre):
        appels_lire = 0

        def lire(self, depuis=None):
            self.appels_lire += 1
            return super().lire(depuis)

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "tech1", "Technicien", "mot-de-passe-tech1-long", ["employee"])
        if acteur:
            identite.creer_personne(cnx, acteur, acteur, "mot-de-passe-acteur-long", [role], actif=actif)
    reg = RegistreObserve()
    par_nom = {o.nom: o for o in outils(registre_cible=reg)}
    args = {"technicien_id": "tech1", "debut": "2026-09-14", "fin": "2026-09-14",
            "fuseau": "America/Montreal"}
    identite_appelante = contexte.IdentiteAppelante(acteur, role) if acteur else None
    with contexte.appele_par_appareil(identite_appelante):
        for nom in ("m4_previsualiser_heures_regulieres", "m4_lire_heures_regulieres_validees"):
            reponse = executer_atomique(par_nom[nom], args)
            assert reponse["resultat"]["accepte"] is accepte
    assert reg.appels_lire == 0


def test_lecteur_refuse_maillon_validation_altere(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "tech1", "Technicien", "mot-de-passe-tech1-long", ["employee"])
        identite.creer_personne(cnx, "admin1", "Admin", "mot-de-passe-admin1-long", ["admin"])
    reg = registre_mod.Registre()
    for row in _points():
        row = {**row, "technicien_id": "tech1"}
        reg.ajouter({k: v for k, v in row.items() if k not in {
            "ligne_id", "precedent_ligne_id", "latitude", "longitude"}})
    par_nom = {o.nom: o for o in outils(registre_cible=reg)}
    args_preview = {"technicien_id": "tech1", "debut": "2026-09-14", "fin": "2026-09-14",
                    "fuseau": "America/Montreal"}
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        preview = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], args_preview)
    p = preview["resultat"]["resultat"]
    arguments = {**args_preview, "empreinte_sources": p["empreinte_sources"],
                 "categories_minutes": p["categories_minutes"], "details_intervalles": p["details_intervalles"],
                 "sources": p["sources"], "validation_precedente_attendue": p["validation_precedente"],
                 "couverture_complete": True,
                 "classification_reguliere_confirmee": True, "motif_correction": "Revue humaine initiale.",
                 "dispositions": {k: {"inclure": k == "travail", "source": "Décision humaine"}
                                  for k in ("travail", "deplacement", "pause")}}
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, "m04-field-ops", "m4_valider_heures_regulieres", arguments,
                                              niveau=Niveau.N4)
        decision = approbations.decider(cnx, demande, True, "admin1", par_nom,
                                        {"m04-field-ops": lire_manifeste(RACINE)})
    assert decision["statut"] == "executee"
    reg._chain[-1]["minutes_regulieres"] += 1
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        lecture = executer_atomique(par_nom["m4_lire_heures_regulieres_validees"], args_preview)
    assert lecture["resultat"]["accepte"] is False
    assert lecture["resultat"]["verdict"]["code"] == "REJ-REGISTRE-INVALIDE"


def test_n4_refuse_si_source_alteree_en_conservant_ligne_id(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "tech1", "Technicien", "mot-de-passe-tech1-long", ["employee"])
        identite.creer_personne(cnx, "admin1", "Admin", "mot-de-passe-admin1-long", ["admin"])
    reg = registre_mod.Registre()
    for row in _points():
        row = {**row, "technicien_id": "tech1"}
        reg.ajouter({k: v for k, v in row.items() if k not in {
            "ligne_id", "precedent_ligne_id", "latitude", "longitude"}})
    par_nom = {o.nom: o for o in outils(registre_cible=reg)}
    args_preview = {"technicien_id": "tech1", "debut": "2026-09-14", "fin": "2026-09-14",
                    "fuseau": "America/Montreal"}
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        preview = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], args_preview)
    p = preview["resultat"]["resultat"]
    arguments = {**args_preview, "empreinte_sources": p["empreinte_sources"],
                 "categories_minutes": p["categories_minutes"], "details_intervalles": p["details_intervalles"],
                 "sources": p["sources"], "validation_precedente_attendue": p["validation_precedente"],
                 "couverture_complete": True,
                 "classification_reguliere_confirmee": True, "motif_correction": "Revue humaine initiale.",
                 "dispositions": {k: {"inclure": False, "source": "Décision humaine"}
                                  for k in ("travail", "deplacement", "pause")}}
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, "m04-field-ops", "m4_valider_heures_regulieres", arguments,
                                              niveau=Niveau.N4)
        ligne = reg._chain[1]
        ligne["horodatage"] = "2026-09-14T15:05:00+00:00"
        decision = approbations.decider(cnx, demande, True, "admin1", par_nom,
                                        {"m04-field-ops": lire_manifeste(RACINE)})
    assert decision["statut"] == "echec"
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-REGISTRE-INVALIDE"
    assert decision["reponse"]["resultat"]["accepte"] is False
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-REGISTRE-INVALIDE"
    assert not any(row.get("type_entree") == "heures_regulieres_validees" for row in reg.lire())


def test_n4_refuse_si_les_sources_changent_apres_aperçu(base_durable):
    par_nom = {o.nom: o for o in outils()}
    args_preview = {"technicien_id": "tech1", "debut": "2026-09-14", "fin": "2026-09-14",
                    "fuseau": "America/Montreal"}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "tech1", "Technicien", "mot-de-passe-tech1-long", ["employee"])
        identite.creer_personne(cnx, "admin1", "Admin", "mot-de-passe-admin1-long", ["admin"])
        _source_durable()
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        preview = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], args_preview)
    proposition = preview["resultat"]["resultat"]
    args = {**args_preview, "empreinte_sources": proposition["empreinte_sources"],
            "categories_minutes": proposition["categories_minutes"],
            "details_intervalles": proposition["details_intervalles"], "sources": proposition["sources"],
            "validation_precedente_attendue": proposition["validation_precedente"],
            "motif_correction": "Demande initiale.",
            "couverture_complete": True, "classification_reguliere_confirmee": True,
            "dispositions": {k: {"inclure": False, "source": "revue humaine"}
                             for k in ("travail", "deplacement", "pause")}}
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, "m04-field-ops", "m4_valider_heures_regulieres", args,
                                              niveau=Niveau.N4)
        # Mutation canonique après aperçu, avant la décision N4.
        reg = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal"))
        reg.ajouter({"type_entree": "pointage", "intervention_id": "I1", "technicien_id": "tech1",
                     "action": "arrivee", "horodatage": "2026-09-14T13:05:00+00:00"})
        decision = approbations.decider(cnx, demande, True, "admin1", par_nom,
                                        {"m04-field-ops": lire_manifeste(RACINE)})
    assert decision["statut"] == "echec"
    assert not any(m.get("type_entree") == "heures_regulieres_validees"
                   for m in registre_mod.Registre(stockage.maillons("m04-field-ops", "principal")).lire())


def test_cas_refuse_seconde_demande_preparee_sur_meme_tete(base_durable):
    par_nom = {o.nom: o for o in outils()}
    api = {"technicien_id": "tech1", "debut": "2026-09-14", "fin": "2026-09-14",
           "fuseau": "America/Montreal"}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "tech1", "Technicien", "mot-de-passe-tech1-long", ["employee"])
        identite.creer_personne(cnx, "admin1", "Admin", "mot-de-passe-admin1-long", ["admin"])
        _source_durable()
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        p = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], api)["resultat"]["resultat"]
    args = {**api, "empreinte_sources": p["empreinte_sources"], "categories_minutes": p["categories_minutes"],
            "details_intervalles": p["details_intervalles"], "sources": p["sources"],
            "validation_precedente_attendue": None, "couverture_complete": True,
            "classification_reguliere_confirmee": True, "motif_correction": "Revue N4.",
            "dispositions": {k: {"inclure": False, "source": "décision humaine"}
                             for k in ("travail", "deplacement", "pause")}}
    with stockage.transaction() as cnx:
        demande_initiale = approbations.creer_demande(cnx, "m04-field-ops", "m4_valider_heures_regulieres", args,
                                                       niveau=Niveau.N4)
        initiale = approbations.decider(cnx, demande_initiale, True, "admin1", par_nom,
                                       {"m04-field-ops": lire_manifeste(RACINE)})
    assert initiale["statut"] == "executee"
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")):
        p2 = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], api)["resultat"]["resultat"]
    args_correction = {**args, "empreinte_sources": p2["empreinte_sources"],
                       "categories_minutes": p2["categories_minutes"],
                       "details_intervalles": p2["details_intervalles"], "sources": p2["sources"],
                       "validation_precedente_attendue": p2["validation_precedente"],
                       "motif_correction": "Correction à partir de la révision 1."}
    with stockage.transaction() as cnx:
        demandes = [approbations.creer_demande(cnx, "m04-field-ops", "m4_valider_heures_regulieres",
                                               args_correction, niveau=Niveau.N4) for _ in range(2)]
        premiere = approbations.decider(cnx, demandes[0], True, "admin1", par_nom,
                                        {"m04-field-ops": lire_manifeste(RACINE)})
        seconde = approbations.decider(cnx, demandes[1], True, "admin1", par_nom,
                                       {"m04-field-ops": lire_manifeste(RACINE)})
    assert premiere["statut"] == "executee"
    assert seconde["statut"] == "echec"
    assert seconde["reponse"]["resultat"]["verdict"]["code"] == "REJ-VALIDATION-COURANTE-CHANGE"
    validations = [m for m in registre_mod.Registre(stockage.maillons("m04-field-ops", "principal")).lire()
                   if m.get("type_entree") == "heures_regulieres_validees"]
    assert len(validations) == 2 and validations[-1]["revision"] == 2
