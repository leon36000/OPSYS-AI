"""Boucle fermée d'apprentissage des durées, de bout en bout, sur les VRAIS outils M3 et M4 (SQLite migrée, registres
durables, bus, file d'approbation), avec des données FICTIVES (fictif: true).

Scénario : le barème dit 30 min par pi_lin ; 28 pi_lin = 840 min = 14 h. Le terrain (pointages certifiés de M4) montre
~16 h sur site, déplacement à part. Trois équipes aux vitesses réelles différentes (nord 0,92 ; est 1,00 ;
sud 1,08), des chantiers difficiles, un chantier hors norme, un chantier non vérifié, une équipe d'une seule
personne et une assignation qui n'est pas une équipe. Un type B stable. Puis dérive brutale, retour arrière,
mode ombre et indice d'adéquation.
"""

from __future__ import annotations

import contextlib
import copy
import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from m2_preparation_estimation import marqueur_m2

_SRC_M3 = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_M3) not in sys.path:
    sys.path.insert(0, str(_SRC_M3))

from m3_estimation import apprentissage_journal as aj  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402
from m3_estimation import outils_apprentissage_durees as adaptateur  # noqa: E402
from m4_field_ops import adequation_equipe  # noqa: E402
from m4_field_ops import outbox as outbox_m4  # noqa: E402
from m4_field_ops import outils_adequation_eta as adaptateur_m4  # noqa: E402
from m4_field_ops import registre as registre_m4  # noqa: E402
from m4_field_ops.outils import outils as outils_m4  # noqa: E402

from opsys import approbations, evenements, identite, stockage  # noqa: E402
from opsys import equipes as equipes_entreprise  # noqa: E402
from opsys.capacites import outils_executables  # noqa: E402
from opsys.departements import charger_departements  # noqa: E402
from opsys.outils import Niveau, executer_atomique  # noqa: E402

FICTIF = True
M3 = "m03-estimation"
OWNER = "proprio-appr"
POLITIQUE = {
    "version": "m3-apprentissage-durees/1", "echantillon_minimum": 8, "echantillon_minimum_equipe": 4,
    "demi_vie_jours": 90, "aberrantes_k": "3.5", "echelle_minimale_relative": "0.05", "niveau_confiance": "0.90",
    "replications": 300, "variation_minimale_pct": "1", "variation_auto_max_pct": "25", "facteur_min": "0.5",
    "facteur_max": "2", "derive_fenetre": 8, "derive_seuil_pct": "15", "complexites": ["standard", "difficile"],
}
TYPE_A, TYPE_B = "renovation_totale", "extension"
TAUX_A, TAUX_B, QUANTITE = 30, 20, 28   # A : 840 min (14 h) ; B : 560 min
AUJOURD_HUI = "2026-03-15T12:00:00Z"
BRUIT = [0.99, 1.01, 1.0, 0.98, 1.02, 1.0, 1.01, 0.99, 1.0, 1.02, 0.98, 1.0]
EQUIPES = {"eq-nord": 0.92, "eq-sud": 1.08, "eq-est": 1.00}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'apprentissage.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", "mot-de-passe-long-pour-fixture",
                                ["admin", "nathan_owner"])
        approbations.fixer_mode(cnx, M3, "supervise", OWNER)
    liste = []
    for identifiant, membres in (("eq-nord", 2), ("eq-sud", 2), ("eq-est", 2), ("eq-neuve", 2), ("eq-solo", 1)):
        liste.append({
            "id": identifiant, "membres": [f"{identifiant[3:]}.{k}.fictif" for k in range(membres)],
            "competences": ["ext"], "depot": {"id": "depot-fictif", "latitude_microdegres": 45500000,
                                              "longitude_microdegres": -73600000},
            "quarts": [{"jour": 0, "debut_min": 420, "fin_min": 930}],
            "semaine_type": {"fuseau": "America/Montreal", "samedi": [], "dimanche": [],
                             **{j: [{"debut": "07:00", "fin": "15:00"}]
                                for j in ("lundi", "mardi", "mercredi", "jeudi", "vendredi")}},
        })
    profil = equipes_entreprise.normaliser_equipes({
        "liste": liste, "feries": {"annees": [2030], "jours": []},
        "services": {TYPE_A: {"duree_min": 240, "competences": ["ext"]}},
    })
    (tmp_path / "home" / "entreprise.yaml").write_text(yaml.safe_dump({"equipes": profil}, allow_unicode=True),
                                                     encoding="utf-8")
    monkeypatch.setattr(approbations, "_maintenant", lambda: "2026-03-16T10:00:00+00:00")   # horloge de décision figée
    monkeypatch.setattr(adaptateur, "_politique_brute", lambda: copy.deepcopy(POLITIQUE))
    monkeypatch.setattr(adaptateur_m4, "_parametres_adequation", lambda: {
        "poids": {"capacite": "1", "charge": "0", "distance": "0", "qualite": "0", "rapidite": "2"},
        "distance_reference_km": 100, "historique_minimum": 5})
    yield tmp_path
    stockage.liberer()


class Chantiers:
    """Fabrique de chantiers terminés et vérifiés, avec les vrais outils M3 puis M4."""

    def __init__(self):
        self.par_nom = {**{o.nom: o for o in outils_m3.outils()}, **{o.nom: o for o in outils_m4()}}
        self.departements = charger_departements()
        self.n = 0
        self.wct = {}

    def _appel(self, nom, arguments):
        reponse = executer_atomique(self.par_nom[nom], arguments)
        assert reponse["ok"] and reponse["resultat"].get("accepte", True), (nom, reponse)
        return reponse["resultat"]

    def creer(self, *, equipe, service=TYPE_A, reel_minutes, jour, deplacement_minutes=30, verifier=True,
              difficile=False):
        self.n += 1
        index = self.n
        lead = f"LEAD-APPR-{index:03d}"
        contrat = {"lead_id": lead, "conversation_id": f"CONV-APPR-{index:03d}", "type_travaux": service,
                   "ville": "Montreal", "canal": "formulaire", "contact": {"nom": "Client fictif",
                                                                           "telephone": "5145550101"},
                   "urgence_declaree": False}
        taux = TAUX_A if service == TYPE_A else TAUX_B
        estimation = executer_atomique(self.par_nom["m3_estimer_projet"], {
            "contrat": contrat, "marqueur": marqueur_m2(lead, type_travaux=service, ville="Montreal", contrat=contrat),
            "photos": [{"photo_id": f"photo-{index}", "resolution_largeur": 3000, "resolution_hauteur": 2000,
                        "eclairage": 7, "angle": "face", "reference_echelle": {"type": "porte",
                                                                               "dimensions_connues": True}}],
            "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
            "bareme": bareme(service, taux), "quantite": float(QUANTITE), "plancher_rentable": 1, "graine": 7000,
        })
        assert estimation["ok"] and estimation["resultat"]["accepte"], estimation
        devis_id = estimation["resultat"]["estimation"]["devis_id"]
        source = estimation["resultat"]["estimation"]["hash_maillon"]
        chantier = f"CHANTIER-APPR-{index:03d}"
        self._appel("m3_creer_devis", {
            "devis_id": devis_id, "estimation_source_hash": source, "lead_id": lead, "chantier_id": chantier,
            "lignes": [{"description": "Travaux fictifs", "quantite": "28", "unite": "pi_lin", "cout_unitaire": "12.00",
                        "reference_besoin_materiau": None}], "taux_marge": "0.20",
            "horodatage": "2026-01-01T13:00:00Z"})
        self._appel("m3_marquer_devis_accepte", {"devis_id": devis_id, "approbateur": "approbateur-fictif",
                                                 "horodatage": "2026-01-01T14:00:00Z"})
        iso = jour.isoformat()
        debut_route = datetime.fromisoformat(f"{iso}T05:30:00+00:00") - timedelta(minutes=deplacement_minutes)
        arrivee = datetime.fromisoformat(f"{iso}T05:30:00+00:00")
        depart = arrivee + timedelta(minutes=reel_minutes + 15)  # 15 min de pause, exclues de la durée certifiée
        fenetre = {"debut": f"{iso}T00:00:00+00:00", "fin": (arrivee + timedelta(days=3)).isoformat()}
        plan = self._appel("m4_planifier_intervention", {
            "contrat": contrat, "marqueur": {"readiness_ok": True, "lead_id": lead, "hash_tete_registre": None,
                                             "horodatage": "2026-01-01T12:00:00Z", "empreinte": "ab" * 32},
            "horodatage": f"{iso}T00:30:00+00:00", "sel": "apprentissage-fictif", "techniciens_disponibles": [equipe],
            "fenetres_disponibles": [fenetre], "devis_id": devis_id})
        intervention = plan["intervention_id"]
        self._appel("m4_definir_consentement_gps", {
            "technicien_id": equipe, "action": "donne", "horodatage": f"{iso}T00:40:00+00:00",
            "version_politique": "POLITIQUE-geolocalisation-v1-test",
            "preuve": {"fictif": True, "reference": f"c-{index}"}})
        self._appel("m4_demarrer_route", {"intervention_id": intervention, "technicien_id": equipe,
                                          "horodatage": debut_route.isoformat()})
        token = __import__("m4_field_ops.cedule", fromlist=["tokeniser_ville"]).tokeniser_ville(
            "apprentissage-fictif", "Montreal")
        reference = {token: {"latitude": 45.5088, "longitude": -73.5878, "rayon_km": 25.0}}
        pause = arrivee + timedelta(minutes=60)
        fin_pause = pause + timedelta(minutes=15)
        for action, instant in (("arrivee", arrivee), ("pause_debut", pause), ("pause_fin", fin_pause),
                                ("depart", depart)):
            self._appel("m4_pointer", {
                "intervention_id": intervention, "technicien_id": equipe, "action": action,
                "horodatage": instant.isoformat(), "fix_gps": {"latitude": 45.5088, "longitude": -73.5878},
                "attestation": {"fictif": True, "appareil_id": "APP-APPRENTISSAGE"}, "fenetre_travail": fenetre,
                "referentiel_villes": reference, "ville": "Montreal", "sel": "apprentissage-fictif"})
        completion = self._appel("m4_completer_intervention", {
            "intervention_id": intervention, "horodatage": (depart + timedelta(minutes=5)).isoformat(),
            "preuves_completion": {"checklist_complete": True, "photos_apres": [_photo(self.par_nom)],
                                   "notes": "Fixture fictive d'apprentissage", "signature": None}})
        wct_id = completion["resultat"]["wct_id"]
        assert completion["resultat"]["duree_reelle_minutes"] == reel_minutes
        if verifier:
            with stockage.transaction():
                faits = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
                accuse, verdict = outbox_m4.resoudre_revue_completion(
                    intervention, "verifiee", (depart + timedelta(minutes=30)).isoformat(), faits,
                    motif="Vérification de fixture fictive d'apprentissage.")
            assert verdict is None and accuse["statut"] == "completed_verified"
        if difficile:
            self._appel("m3_declarer_complexite_chantier", {
                "chantier_id": chantier, "complexite": "difficile", "horodatage": AUJOURD_HUI})
        self.wct[wct_id] = {"equipe": equipe, "service": service, "reel": reel_minutes, "chantier": chantier}
        return wct_id, devis_id, intervention

    def livrer(self):
        resultat = evenements.repartir({M3: self.departements[M3]})
        assert resultat["echecs"] == 0 and resultat["quarantaines"] == 0, resultat


def bareme(service, taux):
    return {"version": "bareme-fictif-1", "unite": "pi_lin", "semantique_temps": "duree_ecoulee_intervention",
            "postes": {service: {"cout_unitaire_min": 10.0, "cout_unitaire_max": 20.0,
                                 "duree_minutes_par_unite": float(taux)}}}


def _photo(par_nom):
    import base64
    import hashlib
    import struct
    import zlib

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))
    reponse = executer_atomique(par_nom["m4_deposer_fichier"], {
        "empreinte_sha256": hashlib.sha256(png).hexdigest(), "taille_octets": len(png), "type_mime": "image/png",
        "index_bloc": 0, "nombre_blocs": 1, "bloc_base64": base64.b64encode(png).decode("ascii")})
    return reponse["resultat"]["resultat"]["reference"]


def estimer(fab, service=TYPE_A, *, lead="LEAD-DEVIS"):
    taux = TAUX_A if service == TYPE_A else TAUX_B
    contrat = {"lead_id": lead, "conversation_id": "CONV-" + lead, "type_travaux": service, "ville": "Montreal",
               "canal": "formulaire", "contact": {"nom": "Client fictif", "telephone": "5145550101"},
               "urgence_declaree": False}
    reponse = executer_atomique(fab.par_nom["m3_estimer_projet"], {
        "contrat": contrat, "marqueur": marqueur_m2(lead, type_travaux=service, ville="Montreal", contrat=contrat),
        "photos": [{"photo_id": "photo-devis", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
                    "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4}, "bareme": bareme(service, taux),
        "quantite": float(QUANTITE), "plancher_rentable": 1, "graine": 7000, "taux_marge": "0.20"})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse
    return reponse["resultat"]


def minutes(reponse):
    return Decimal(reponse["duree_estimee_minutes"])


def calculer(fab, horodatage=AUJOURD_HUI):
    reponse = executer_atomique(fab.par_nom["m3_calculer_apprentissage_durees"], {"horodatage": horodatage})
    assert reponse["ok"], reponse
    return reponse["resultat"]


def cohorte(resultat, service):
    return next(c for c in resultat["cohortes"] if c["rapport"]["cohorte"]["type_service"] == service)


def decider(fab, nom, arguments, *, approuver=True):
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, M3, nom, arguments, niveau=Niveau.N3)
    with stockage.transaction() as cnx:
        executables = outils_executables(fab.departements, lambda: contextlib.nullcontext(cnx))
        return approbations.decider(cnx, demande, approuver, OWNER, executables, fab.departements)


def mode(valeur):
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, M3, valeur, OWNER)


def peupler_phase_un(fab):
    """25 chantiers A vérifiés (+ 1 hors norme, 1 non vérifié, 2 sans équipe attribuable) et 10 chantiers B."""
    debut = date(2026, 1, 5)
    jour = 0
    plan = (
        [("eq-nord", False)] * 5 + [("eq-nord", True)] * 4 + [("eq-sud", False)] * 5 + [("eq-sud", True)] * 4
        + [("eq-est", False)] * 7
    )
    for position, (equipe, difficile) in enumerate(plan):
        reel = 960 * EQUIPES[equipe] * (1.25 if difficile else 1.0) * BRUIT[position % len(BRUIT)]
        fab.creer(equipe=equipe, reel_minutes=round(reel), jour=debut + timedelta(days=jour), difficile=difficile,
                  deplacement_minutes=20 + 7 * (position % 6))   # le déplacement varie : il ne doit rien changer
        jour += 1
    fab.creer(equipe="eq-est", reel_minutes=1500, jour=debut + timedelta(days=jour))             # hors norme (incident)
    fab.creer(equipe="eq-nord", reel_minutes=960, jour=debut + timedelta(days=jour + 1), verifier=False)  # non vérifié
    fab.creer(equipe="eq-solo", reel_minutes=960, jour=debut + timedelta(days=jour + 2))                 # une personne
    # pas une équipe
    fab.creer(equipe="marc.fictif", reel_minutes=950, jour=debut + timedelta(days=jour + 3))
    for position in range(10):
        equipe = ("eq-nord", "eq-sud", "eq-est")[position % 3]
        fab.creer(equipe=equipe, service=TYPE_B, reel_minutes=round(560 * BRUIT[position % len(BRUIT)]),
                  jour=debut + timedelta(days=30 + position))
    fab.livrer()


# ===========================================================================================================
def test_boucle_fermee_complete(monde, monkeypatch):
    fab = Chantiers()
    with stockage.transaction():
        avant_a = estimer(fab, TYPE_A, lead="LEAD-AVANT-A")
        avant_b = estimer(fab, TYPE_B, lead="LEAD-AVANT-B")
    assert minutes(avant_a) == 840 and minutes(avant_b) == 560  # 14 h : le barème seul
    assert avant_a["apprentissage_duree"] is None

    peupler_phase_un(fab)

    # --- fail-closed : sans politique déclarée, rien n'est calculé et le refus dit quoi déclarer -------------------
    monkeypatch.setattr(adaptateur, "_politique_brute", lambda: {k: None for k in POLITIQUE})
    refus = executer_atomique(fab.par_nom["m3_calculer_apprentissage_durees"], {"horodatage": AUJOURD_HUI})["resultat"]
    assert refus["statut"] == "refuse" and refus["raisons"] == ["politique_apprentissage_absente"]
    assert "echantillon_minimum" in refus["verdict"]["detail"]
    assert {m["type_entree"] for m in adaptateur.registre_apprentissage()} == {"complexite_declaree"}
    monkeypatch.setattr(adaptateur, "_politique_brute", lambda: copy.deepcopy(POLITIQUE))

    # --- lecture seule (T0) : montre sans écrire --------------------------------------------------------------------
    lecture = executer_atomique(fab.par_nom["m3_lire_apprentissage_durees"], {"horodatage": AUJOURD_HUI})["resultat"]
    assert lecture["ecrit"] is False and len(adaptateur.registre_apprentissage()) == 8   # les 8 déclarations seulement
    a = cohorte(lecture, TYPE_A)["rapport"]
    # 25 + eq-solo + assignation sans équipe ; le hors norme est écarté
    assert a["decision"] == "auto_applicable" and a["n_chantiers"] == 27

    # --- mode OMBRE : calculé et montré, rien n'est appliqué ---------------------------------------------------------
    mode("ombre")
    ombre = calculer(fab)
    assert ombre["mode"] == "ombre" and cohorte(ombre, TYPE_A)["active"] is False
    assert cohorte(ombre, TYPE_A)["activation"]["raisons"] == ["auto_non_autorise_dans_ce_mode"]
    with stockage.transaction():
        en_ombre = estimer(fab, TYPE_A, lead="LEAD-OMBRE")
    assert minutes(en_ombre) == 840
    assert en_ombre["apprentissage_duree"]["statut"] == "ombre"
    assert Decimal("930") < Decimal(en_ombre["apprentissage_duree"]["temps_sur_site_ombre_minutes"]) < Decimal("1010")
    assert aj.version_active(adaptateur.registre_apprentissage(), TYPE_A, "pi_lin") == (None, None)

    # --- supervisé : le petit ajustement dans les bornes s'applique, au brouillon d'estimation -----------------------
    mode("supervise")
    resultat = calculer(fab)
    ca = cohorte(resultat, TYPE_A)
    assert ca["active"] is True and ca["rapport"]["decision"] == "auto_applicable"
    n_journal = len(adaptateur.registre_apprentissage())
    rejeu = calculer(fab)                                                     # double soumission : rien de plus
    assert cohorte(rejeu, TYPE_A)["ecrit"] is False and cohorte(rejeu, TYPE_A)["rapport"]["decision"] == "stable"
    assert len(adaptateur.registre_apprentissage()) == n_journal
    assert ca["rapport"]["exclues"] == {"aberrante": 1}                       # le chantier hors norme
    assert ca["rapport"]["derive"]["detectee"] is False
    appris = Decimal(ca["rapport"]["taux_appris"])
    assert Decimal("31.5") < appris < Decimal("36.5")
    assert Decimal(ca["rapport"]["intervalle"]["bas"]) > TAUX_A               # l'intervalle exclut l'ancien taux
    cb = cohorte(resultat, TYPE_B)
    assert cb["rapport"]["decision"] == "stable" and cb["active"] is False    # le type B ne bouge pas
    obs = resultat["observations"]
    # WCT certifiés ; le non vérifié est absent
    assert obs["retenues"] == 28 + 10
    with stockage.transaction():
        apres_a = estimer(fab, TYPE_A, lead="LEAD-APRES-A")
        apres_b = estimer(fab, TYPE_B, lead="LEAD-APRES-B")
    assert abs(minutes(apres_a) - appris * QUANTITE) < Decimal("0.01")
    assert 930 < minutes(apres_a) < 1010                                       # ~16 h au lieu de 14 h
    assert minutes(apres_b) == 560 and apres_b["apprentissage_duree"] is None  # B inchangé
    bloc = apres_a["apprentissage_duree"]
    assert bloc["statut"] == "applique" and bloc["mode_activation"] == "auto" and bloc["n_chantiers"] >= 20
    assert bloc["intervalle"]["niveau"] == "0.90" and bloc["deplacement"]["inclus"] is False
    assert Decimal(bloc["temps_sur_site_baseline_minutes"]) == 840
    # Le prix et l'intervalle de coût ne bougent pas : seule la durée sur site est apprise.
    assert apres_a["prix_recommande"] == avant_a["prix_recommande"]
    assert apres_a["estimation"]["intervalle_confiance"] == avant_a["estimation"]["intervalle_confiance"]
    charge = next(m["charge"] for m in outils_m3.registre_production().lire()
                  if m["charge"]["lead_id"] == "LEAD-APRES-A")
    assert charge["trace_calibration_temps"]["version_schema"] == 3
    assert charge["trace_calibration_temps"]["calibration_version_id"] == bloc["version_id"]
    assert Decimal(charge["trace_calibration_temps"]["taux_minutes_par_unite_source"]) == TAUX_A
    assert charge["apprentissage_duree"]["n_chantiers"] == bloc["n_chantiers"]
    version_1 = bloc["version_id"]

    # --- ombre à nouveau : une version automatique est gelée et seulement montrée
    mode("ombre")
    with stockage.transaction():
        gelee = estimer(fab, TYPE_A, lead="LEAD-OMBRE-2")
    assert minutes(gelee) == 840 and gelee["apprentissage_duree"]["statut"] == "ombre"
    mode("supervise")

    # --- équipes : indices normalisés par la difficulté, dans l'instantané inscrit au journal
    eq = {e["equipe_ref"]: e for e in resultat["equipes"]["equipes"] if e["type_service"] == TYPE_A}
    refs = {nom: adaptateur_m4.calibration_projection.equipe_ref(nom) for nom in
            ("eq-nord", "eq-sud", "eq-est", "eq-neuve", "eq-solo")}
    nord, sud, est = (eq[refs[n]] for n in ("eq-nord", "eq-sud", "eq-est"))
    assert nord["evaluable"] and sud["evaluable"] and est["evaluable"]
    assert Decimal(nord["indice_median"]) < Decimal(est["indice_median"]) < Decimal(sud["indice_median"])
    assert Decimal(nord["indice_median"]) < Decimal("0.97") and Decimal(sud["indice_median"]) > Decimal("1.03")
    assert refs["eq-solo"] not in eq and refs["eq-neuve"] not in eq          # sans historique agrégeable : absentes
    assert resultat["equipes"]["observations_sans_equipe"] == 2 + 0          # eq-solo et marc.fictif (type A)
    # Sans normalisation, nord (qui a fait des chantiers difficiles) paraîtrait plus LENT que est (qui n'en a fait au…
    moyennes = {}
    for equipe in ("eq-nord", "eq-est"):
        durees = [v["reel"] for v in fab.wct.values() if v["equipe"] == equipe and v["service"] == TYPE_A
                  and v["reel"] < 1400]
        moyennes[equipe] = sum(durees) / len(durees)
    assert moyennes["eq-nord"] > moyennes["eq-est"]

    # --- indice d'adéquation M4 : la rapidité apprise ordonne les équipes ; l'équipe neuve est non évaluable
    lire_perf = executer_atomique(fab.par_nom["m3_lire_performance_equipes"], {"type_service": TYPE_A})
    assert lire_perf["resultat"]["statut"] == "refuse"                      # hors département M4/M3 : refusé
    profil, _ = equipes_entreprise.charger_equipes()
    rapidites = adaptateur_m4._rapidite_par_equipe(TYPE_A, profil["liste"])   # appel réel M4 -> outil de M3
    assert set(rapidites) == {"eq-nord", "eq-sud", "eq-est"}
    fiches = [{
        "equipe_id": e["id"], "competences": list(e["competences"]), "membres_declares": len(e["membres"]),
        "capacite": {"minutes_disponibles": 2400, "minutes_planifiees": 0},
        **({"rapidite": rapidites[e["id"]]} if e["id"] in rapidites else {}),
    } for e in profil["liste"]]
    parametres, verdict = adequation_equipe.lire_parametres({
        "poids": {"capacite": "1", "charge": "0", "distance": "0", "qualite": "0", "rapidite": "2"},
        "distance_reference_km": 100, "historique_minimum": 5})
    assert verdict is None
    ordre, verdict = adequation_equipe.ordonner({
        "intervention": {"intervention_id": "INT-FICTIVE-1", "service": TYPE_A, "date": "2030-06-03", "duree_min": 240,
                         "competences_requises": ["ext"]},
        "equipes": fiches}, parametres)
    assert verdict is None and ordre["decision"] == "humain"
    assert [e["equipe_id"] for e in ordre["ordre"]] == ["eq-nord", "eq-est", "eq-sud"]
    assert "rapidite" in ordre["criteres_actifs"]
    non_evaluees = {n["equipe_id"]: n for n in ordre["non_evaluables"]}
    assert set(non_evaluees) == {"eq-neuve", "eq-solo"}                       # sans historique : non évaluables
    assert all(n["motifs"] == ["rapidite_non_evaluable"] and "jamais notée zéro" in n["detail"]
               for n in non_evaluees.values())
    explication = ordre["ordre"][0]["explication"]
    assert "chantier(s) de ce type à" in explication and "intervalle" in explication
    # Les indices lus par M4 sont ceux de M3, relatifs à la difficulté : nord reste le plus rapide malgré ses chantie…
    assert Decimal(rapidites["eq-nord"]["indice_median"]) < Decimal(rapidites["eq-est"]["indice_median"]) \
        < Decimal(rapidites["eq-sud"]["indice_median"])

    # --- dérive brutale : 8 chantiers à +45 % -> la candidate attend une personne ; l'ancienne version reste
    debut = date(2026, 3, 1)
    for position in range(8):
        fab.creer(equipe=("eq-nord", "eq-sud", "eq-est")[position % 3], reel_minutes=round(1390 * BRUIT[position]),
                  jour=debut + timedelta(days=position))
    fab.livrer()
    derive = calculer(fab)
    cd = cohorte(derive, TYPE_A)
    assert cd["rapport"]["derive"]["detectee"] is True and cd["rapport"]["decision"] == "approbation_requise"
    assert "derive_detectee" in cd["rapport"]["raisons"] and cd["active"] is False
    assert "activation" not in cd                       # la machine n'a même pas essayé : une personne décide
    assert Decimal("1300") < Decimal(cd["rapport"]["taux_appris"]) * QUANTITE < Decimal("1480")
    with stockage.transaction():
        encore_v1 = estimer(fab, TYPE_A, lead="LEAD-DERIVE-AVANT")
    assert encore_v1["apprentissage_duree"]["version_id"] == version_1          # rien n'a changé sans approbation
    version_2 = cd["version_id"]
    sans_approbation = executer_atomique(fab.par_nom["m3_approuver_calibration_duree"], {"version_id": version_2})
    assert sans_approbation["resultat"] == {"accepte": False, "raisons": ["approbateur_humain_requis"]}
    approuve = decider(fab, "m3_approuver_calibration_duree", {"version_id": version_2})
    assert approuve["statut"] == "executee" and approuve["reponse"]["resultat"]["accepte"] is True
    with stockage.transaction():
        v2 = estimer(fab, TYPE_A, lead="LEAD-DERIVE-APRES")
    assert 1300 < minutes(v2) < 1480 and v2["apprentissage_duree"]["mode_activation"] == "humain"

    mode("ombre")   # une décision humaine reste appliquée en ombre ; seule l'application automatique est gelée
    with stockage.transaction():
        assert estimer(fab, TYPE_A, lead="LEAD-OMBRE-HUMAIN")["apprentissage_duree"]["version_id"] == version_2
    mode("supervise")

    # --- retour arrière en une opération : la version précédente, puis le barème
    arguments_retrait = {"type_service": TYPE_A, "unite_quantite": "pi_lin", "version_attendue": version_2,
                         "raison": "Chiffre jugé trop haut après vérification terrain."}
    retire = decider(fab, "m3_annuler_calibration_duree", arguments_retrait)
    assert retire["reponse"]["resultat"]["version_retablie"] == version_1
    with stockage.transaction():
        retour_v1 = estimer(fab, TYPE_A, lead="LEAD-RETOUR-1")
    assert retour_v1["apprentissage_duree"]["version_id"] == version_1 and 930 < minutes(retour_v1) < 1010
    retire_1 = decider(fab, "m3_annuler_calibration_duree", {**arguments_retrait, "version_attendue": version_1})
    assert retire_1["reponse"]["resultat"]["version_retablie"] is None
    with stockage.transaction():
        retour_14h = estimer(fab, TYPE_A, lead="LEAD-RETOUR-2")
    assert minutes(retour_14h) == 840 and retour_14h["apprentissage_duree"] is None   # 14 h rétablies
    # Rien n'est remis en vigueur sans personne : la même dérive revient comme candidate qui attend une approbation.
    regel = cohorte(calculer(fab), TYPE_A)
    assert regel["active"] is False and regel["rapport"]["decision"] == "approbation_requise"
    with stockage.transaction():
        assert minutes(estimer(fab, TYPE_A, lead="LEAD-GEL")) == 840

    # --- Loi 25 : le journal ne contient aucun nom, courriel, membre ni identifiant d'équipe en clair
    journal = json.dumps(list(adaptateur.registre_apprentissage()), ensure_ascii=False)
    for interdit in ("eq-nord", "eq-sud", "eq-est", "eq-neuve", "eq-solo", "nord.0.fictif", "marc.fictif",
                     "@", "Propriétaire", "Client fictif", "5145550101", "CHANTIER-APPR"):
        assert interdit not in journal, interdit
    assert aj.evenements(adaptateur.registre_apprentissage())[1] is None


def test_refus_et_abus_des_outils_d_apprentissage(monde):
    fab = Chantiers()
    appel = lambda nom, arguments: executer_atomique(fab.par_nom[nom], arguments)["resultat"]  # noqa: E731
    for mauvais in ("hier", "2026-03-15T12:00:00", "2026-03-15T12:00:00+02:00"):
        assert appel("m3_calculer_apprentissage_durees", {"horodatage": mauvais})["statut"] == "refuse"
    assert executer_atomique(fab.par_nom["m3_calculer_apprentissage_durees"], {"horodatage": 5})["ok"] is False
    # Rien à apprendre sans chantier : le calcul réussit, ne crée aucune version et n'active rien.
    vide = calculer(fab)
    assert vide["cohortes"] == [] and vide["observations"]["retenues"] == 0
    assert len(adaptateur.registre_apprentissage()) == 0
    # Complexité hors échelle, déclarant absent, chantier vide.
    assert appel("m3_declarer_complexite_chantier",
                 {"chantier_id": "CH-1", "complexite": "extreme", "horodatage": AUJOURD_HUI})["raisons"] == [
        "complexite_hors_echelle"]
    assert appel("m3_declarer_complexite_chantier",
                 {"chantier_id": "CH-1", "complexite": "inconnue", "horodatage": AUJOURD_HUI})["accepte"] is False
    # Approbation et retour arrière : jamais sans une décision humaine, même avec les bons arguments.
    inconnu = "e" * 64
    assert appel("m3_approuver_calibration_duree", {"version_id": inconnu}) == {
        "accepte": False, "raisons": ["approbateur_humain_requis"]}
    assert appel("m3_annuler_calibration_duree", {
        "type_service": TYPE_A, "unite_quantite": "pi_lin", "version_attendue": inconnu, "raison": "x"}) == {
        "accepte": False, "raisons": ["approbateur_humain_requis"]}
    humain = decider(fab, "m3_approuver_calibration_duree", {"version_id": inconnu})
    assert humain["statut"] == "echec" and humain["reponse"]["resultat"] == {
        "accepte": False, "raisons": ["version_inconnue"]}
    # Aucun droit d'appareil : un jeton d'appareil ne peut appeler aucun de ces outils.
    for outil in outils_m3.outils():
        if outil.nom in ("m3_lire_apprentissage_durees", "m3_calculer_apprentissage_durees",
                         "m3_approuver_calibration_duree", "m3_annuler_calibration_duree",
                         "m3_declarer_complexite_chantier", "m3_lire_performance_equipes"):
            assert not outil.roles_appareil, outil.nom
    # Journal altéré : l'estimation ne s'appuie sur rien et le dit.
    registre = adaptateur.registre_apprentissage()
    registre.append({"rang": 0, "type_entree": "version_activee", "charge": {}, "hash_precedent": "0" * 64,
                     "hash_maillon": "f" * 64})
    with stockage.transaction():
        reponse = estimer(fab, TYPE_A, lead="LEAD-ALTERE")
    assert minutes(reponse) == 840 and reponse["apprentissage_duree"]["statut"] == "non_appliquee"
    assert reponse["apprentissage_duree"]["raison"] == "journal_forme_invalide" or \
        reponse["apprentissage_duree"]["raison"].startswith("journal_")
