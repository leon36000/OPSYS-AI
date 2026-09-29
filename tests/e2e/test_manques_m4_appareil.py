"""PLAN T1.4-n (constat 4) — les MANQUES de la préparation d'une intervention (`m4_verifier_preparation`), lus par la
vraie porte d'appareil, et la table que l'app en tire (`mobile/src/ecrans/manquesM4.ts`) (E2E moteur).

DEFINITION-PRODUIT §9.5 : « M4 : dispatch du jour ». L'écran « Chantiers du jour » du propriétaire lit la préparation
d'une intervention volet par volet. Le `manque` de chaque volet est écrit pour un AGENT : il cite le fichier du serveur
(`$OPSYS_HOME/entreprise.yaml`) et les commandes `opsys-metier` à taper. Le propriétaire, sur son téléphone, n'a rien
à en faire, et un chemin du serveur ne quitte pas le serveur : l'app remplace ce texte par une phrase à elle, choisie
par le CODE du manque (le `detail` du volet quand c'est un code). Ce test prouve que cette table dit vrai.

Le trajet, sur le vrai moteur (un chantier `gouttieres`, lead v2, devis accepté ; les dates et les quantités sont
fictives) :

1. rien n'est déclaré : adresse à confirmer, équipes et règles météo non déclarées, matériel à commander ;
2. M6 reçoit 20 pi sur 40 : le matériel est PARTIEL ; les deux profils sont illisibles : `REJ-PROFIL-INVALIDE` ;
3. les deux profils sont déclarés, mais sans les réglages du service : `REJ-CHAMP-MANQUANT` (équipes sans durée ni
   compétences du service ; météo avec un seuil décidé sur cinq risques) ;
4. les équipes sont déclarées, aucune n'a la compétence du service : un manque SANS code ;
5. un chantier issu d'un lead v1, profils complets : équipes et météo « non vérifiables » (sans code) ;
6. un devis accepté que M6 n'a jamais vu : le matériel est « non vérifiable » (M6 n'a rien dit).

Ce que ces tests prouvent :
- chaque lecture passe par la porte d'appareil `admin` (nom nu), sans rien écrire, sans troncature ;
- le texte de M4 cite bien le fichier du serveur et les commandes (sans quoi l'app n'aurait rien à cacher) ;
- la FORME de chaque réponse est celle de `mobile/src/admin/fixtures/manques-m4.json`, que les tests Jest font passer
  par les lecteurs et les modèles de vue de l'app ;
- la table `MANQUES_CONNUS` de l'app est EXACTEMENT l'ensemble des (volet, statut, code) que M4 produit : aucun manque
  sans phrase, aucune phrase pour un manque qui n'existe pas ; chaque code est un jeton et un code du serveur.
Ce que ces tests ne prouvent PAS : les écrans (Jest, `mobile/`) ni le core.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from harnais_e2e import Moteur, PorteAppareil, Reponse, iso
from harnais_e2e_chantier import debut_de_journee, preparer_chantier, receptionner_materiel_args
from m4_field_ops import etats as etats_m4
from m4_field_ops import localisation as localisation_m4
from m4_field_ops import materiel as materiel_m4
from m4_field_ops import preparation as preparation_m4
from m4_field_ops import registre as registre_m4
from m4_field_ops import verdicts as verdicts_m4

from opsys import cli, evenements, taxonomie
from opsys import equipes as equipes_entreprise
from opsys import meteo as meteo_entreprise

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
RACINE = Path(__file__).resolve().parents[2]
MOBILE_SRC = RACINE / "mobile" / "src"
FIXTURE_APP = MOBILE_SRC / "admin" / "fixtures" / "manques-m4.json"
ENV_REGENERER = "OPSYS_REGENERER_FIXTURES_MOBILE"
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`
_CHEMIN_DE_TEST = re.compile(r"/tmp/pytest-of-[^/]+/pytest-\d+/[^/]+/opsys-home")
JETON = re.compile(r"[A-Za-z0-9_.-]{1,64}")
M4 = "m04-field-ops"
SERVICE = "gouttieres"
HORODATAGE = "2026-09-29T10:00:00-04:00"
SEL = "sel-manques-m4-fictif"



# -- ce que l'app lit dans son propre code ---------------------------------------------------------------------------
def _source(relatif: str) -> str:
    return (MOBILE_SRC / relatif).read_text(encoding="utf-8")


def _table_de_l_app() -> dict[str, str]:
    """`MANQUES_CONNUS` de `mobile/src/ecrans/manquesM4.ts` : « volet:statut:code » -> clé du texte."""
    source = _source("ecrans/manquesM4.ts")
    corps = re.search(r"export const MANQUES_CONNUS[^=]*=\s*\{(.*?)\n\};", source, re.DOTALL)
    assert corps is not None, "MANQUES_CONNUS n'est plus dans l'app"
    table = dict(re.findall(r'"([a-z_]+:[a-z_]+:[A-Za-z0-9_.-]*)":\s*"([A-Za-z.]+)"', corps.group(1)))
    assert table, "MANQUES_CONNUS est vide ou n'a plus la forme « volet:statut:code »"
    assert corps.group(1).count('":') == len(table), "une entrée de MANQUES_CONNUS n'a pas la forme attendue"
    return table


def _normaliser(valeur: Any) -> Any:
    """Le chemin d'un fichier du serveur de test change à chaque exécution : la fixture garde un chemin stable."""
    if isinstance(valeur, dict):
        return {cle: _normaliser(v) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_normaliser(v) for v in valeur]
    if isinstance(valeur, str):
        return _CHEMIN_DE_TEST.sub("/srv/opsys", valeur)
    return valeur


def _forme(valeur: Any) -> Any:
    """La FORME d'une réponse : ses clés et le type de chaque valeur, jamais les valeurs elles-mêmes."""
    if isinstance(valeur, dict):
        return {cle: _forme(v) for cle, v in sorted(valeur.items())}
    if isinstance(valeur, list):
        return [_forme(valeur[0])] if valeur else []
    if valeur is None:
        return "null"
    return type(valeur).__name__


def _volets(enveloppe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Les volets d'une préparation lue (enveloppe `{ok, resultat: {accepte, resultat}}`)."""
    assert enveloppe["ok"] is True and enveloppe["resultat"]["accepte"] is True, enveloppe
    return enveloppe["resultat"]["resultat"]["volets"]


def _cles_de_manque(volets: dict[str, dict[str, Any]]) -> set[str]:
    """« volet:statut:code » de chaque volet qui n'est pas prêt (code vide quand M4 n'en donne pas)."""
    return {f"{nom}:{volet['statut']}:{volet['detail'] or ''}" for nom, volet in volets.items()
            if volet["statut"] != preparation_m4.STATUT_OK}


# -- les gestes de l'amont ---------------------------------------------------------------------------------------------
PROFIL_EQUIPES = {
    "liste": [{
        "id": "eq-nord", "membres": ["etienne"], "competences": [SERVICE],
        "depot": {"id": "depot-fictif", "latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
        "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
    }],
    "services": {SERVICE: {"duree_min": 90, "competences": [SERVICE]}},
}
PROFIL_METEO = {
    "fuseau": "America/Toronto",
    "services": {SERVICE: {"seuils": {
        "vent_kmh": {"validation": 35, "blocage": 50}, "pluie_mm_h": {"blocage": 5}, "gel_c": {"blocage": 0},
        "verglas": {"blocage": True}}, "sans_objet": ["chaleur"]}},
}


def _declarer(dossier: Path, commande: str, profil: dict[str, Any]) -> None:
    """Le propriétaire déclare un profil par la commande réelle du socle (`opsys-metier equipes|meteo declarer`)."""
    fichier = dossier / f"{commande}-declare.yaml"
    fichier.write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    assert cli.main([commande, "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0


def _abimer(cle: str) -> None:
    """Un profil illisible : la clé existe dans `entreprise.yaml` sans être un objet (jamais lue comme absente)."""
    fichier = taxonomie.fichier_profil()
    contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    contenu[cle] = "n'importe quoi"
    fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")


def _livrer_a_m4_seul(moteur: Moteur, lead_id: str, devis_id: str) -> None:
    """Un devis accepté que le bus livre à M4 SEUL : M6 ne le voit jamais, donc ne dit rien du matériel."""
    evenements.publier(
        "m1.lead_qualifie", "m01-front-office",
        {"lead": {"schema_version": 2, "lead_id": lead_id, "conversation_id": f"sms-{lead_id}",
                  "contact": {"nom": "Client Fictif", "telephone": "+15145550142"}, "service": SERVICE,
                  "ville": "Repentigny", "urgence_declaree": False, "canal": "texte", "source": "sms"},
         "horodatage": iso(moteur.horloge.maintenant), "signal_id": f"sms:{lead_id}"},
        evenement_id=f"m1-lead-qualifie-{lead_id}")
    evenements.publier(
        "m3.devis_accepte", "m03-estimation",
        {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
         "lignes": [{"reference_ligne": f"{devis_id}-L0", "description": "Gouttières (fictif)", "quantite": "40",
                     "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "400.00",
                     "reference_besoin_materiau": "gouttiere-alu-5po-fictif"}],
         "cout_total": "300.00", "prix_total": "400.00", "taux_marge": "0.25",
         "horodatage_acceptation": iso(moteur.horloge.maintenant)},
        evenement_id=f"m3-devis-accepte-{devis_id}")
    for _ in range(10):
        resume = evenements.repartir({M4: moteur.departements[M4]}, maintenant=iso(moteur.horloge.maintenant))
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
        if resume["livres"] == 0:
            return
    raise AssertionError("le bus n'a pas atteint le repos")


# -- l'enregistreur : ce que l'app envoie et ce que le moteur répond ---------------------------------------------------
class Enregistreur:
    """Chaque lecture de l'écran : l'appel (outil et arguments exacts) et l'enveloppe que l'app reçoit (`corps.result`),
    c'est-à-dire ce que `manques-m4.json` garde et que les tests Jest lisent."""

    def __init__(self, moteur: Moteur, admin: PorteAppareil) -> None:
        self.moteur = moteur
        self.admin = admin
        self.appels: dict[str, dict[str, Any]] = {}
        self.reponses: dict[str, Any] = {}

    def preparer(self, nom: str, intervention_id: str) -> Reponse:
        """Une lecture : HTTP 200, jamais tronquée par le socle, et RIEN d'écrit dans le moteur."""
        args = {"intervention_id": intervention_id}
        avant = self.moteur.empreinte_etat()
        reponse = self.admin.appeler("m4_verifier_preparation", args)
        assert reponse.statut == 200, (nom, reponse.corps)
        mesure = reponse.mesure
        assert mesure.tronque is False and mesure.octets_texte < LIMITE_TRONCATURE, (nom, mesure)
        assert self.moteur.empreinte_etat() == avant, f"{nom} : lire n'écrit rien"
        assert nom not in self.reponses, nom
        self.appels[nom] = {"outil": "m4_verifier_preparation", "args": args}
        self.reponses[nom] = _normaliser(reponse.enveloppe)
        return reponse


def _statuts(volets: dict[str, dict[str, Any]]) -> dict[str, tuple[str, str | None]]:
    return {nom: (volet["statut"], volet["detail"]) for nom, volet in volets.items()}


def _enregistrer_les_manques(moteur: Moteur, equipe: dict[str, Any], tmp_path: Path, declarer_services: Any,
                             ) -> Enregistreur:
    admin = equipe["admin"]
    enr = Enregistreur(moteur, admin)
    declarer_services()

    # Le chantier P : lead v2 (`gouttieres`), devis accepté, intervention planifiée ; M6 reçoit le devis et réserve.
    chantier = preparer_chantier(moteur.departements, suffixe="MQ-P", technicien="etienne",
                                 debut=debut_de_journee(16), version_lead=2)
    moteur.horloge.maintenant = chantier.debut
    assert moteur.drainer_bus(moteur.horloge.maintenant)["echecs"] == 0

    # ---- 1. rien n'est déclaré ---------------------------------------------------------------------------------
    enr.preparer("sans_rien_declare", chantier.intervention_id)
    volets = _volets(enr.reponses["sans_rien_declare"])
    assert _statuts(volets) == {
        "soumission": ("ok", volets["soumission"]["detail"]),
        "adresse": ("manque", "REJ-COORDONNEES-A-CONFIRMER"),
        "equipe": ("manque", "REJ-EQUIPES-NON-CONFIGUREES"),
        "materiel": ("manque", "a_commander"),
        "meteo": ("manque", "REJ-METEO-NON-CONFIGUREE"),
    }
    # Le texte de M4 cite bien ce que l'app doit taire : le fichier du serveur et la commande à taper.
    assert "opsys-metier equipes declarer" in volets["equipe"]["manque"]
    assert "/srv/opsys/entreprise.yaml" in volets["equipe"]["manque"]
    assert "opsys-metier meteo declarer" in volets["meteo"]["manque"]

    # ---- 2. matériel partiel ; les deux profils sont illisibles -------------------------------------------------
    reception = admin.appeler("m6_receptionner_commande", receptionner_materiel_args(chantier, 20.0),
                              cle="mut-reception-mq-p", horodatage_appareil=iso(chantier.debut))
    assert reception.metier["accepte"] is True, reception.metier
    assert moteur.drainer_bus(moteur.horloge.maintenant)["echecs"] == 0
    _declarer(tmp_path, "equipes", PROFIL_EQUIPES)
    _declarer(tmp_path, "meteo", PROFIL_METEO)
    _abimer("equipes")
    _abimer("meteo")
    enr.preparer("profils_illisibles", chantier.intervention_id)
    volets = _volets(enr.reponses["profils_illisibles"])
    assert _statuts(volets)["equipe"] == ("manque", "REJ-PROFIL-INVALIDE")
    assert _statuts(volets)["meteo"] == ("manque", "REJ-PROFIL-INVALIDE")
    assert _statuts(volets)["materiel"] == ("manque", "partiel")
    # Le message d'un profil invalide nomme le fichier du serveur de test : ce chemin ne doit jamais atteindre l'écran.
    assert "entreprise.yaml" in volets["equipe"]["manque"] + volets["meteo"]["manque"]

    # ---- 3. profils déclarés, sans les réglages du service -------------------------------------------------------
    _declarer(tmp_path, "equipes", {"liste": PROFIL_EQUIPES["liste"]})
    _declarer(tmp_path, "meteo", {"fuseau": "America/Toronto", "services": {SERVICE: {
        "seuils": {"vent_kmh": {"blocage": 50}}}}})
    enr.preparer("reglages_incomplets", chantier.intervention_id)
    volets = _volets(enr.reponses["reglages_incomplets"])
    assert _statuts(volets)["equipe"] == ("manque", "REJ-CHAMP-MANQUANT")
    assert _statuts(volets)["meteo"] == ("manque", "REJ-CHAMP-MANQUANT")

    # ---- 4. équipes déclarées, aucune n'a la compétence du service -------------------------------------------------
    autre_competence = copy.deepcopy(PROFIL_EQUIPES)
    autre_competence["liste"][0]["competences"] = ["revetement"]
    _declarer(tmp_path, "equipes", autre_competence)
    _declarer(tmp_path, "meteo", PROFIL_METEO)
    enr.preparer("aucune_equipe_admissible", chantier.intervention_id)
    volets = _volets(enr.reponses["aucune_equipe_admissible"])
    assert _statuts(volets)["equipe"] == ("manque", None)
    assert _statuts(volets)["meteo"][0] == "ok"

    # ---- 5. un chantier issu d'un lead v1, profils complets : « non vérifiable » ----------------------------------
    _declarer(tmp_path, "equipes", PROFIL_EQUIPES)
    v1 = preparer_chantier(moteur.departements, suffixe="MQ-Q", technicien="etienne",
                           debut=debut_de_journee(17), version_lead=1)
    enr.preparer("lead_v1_profils_complets", v1.intervention_id)
    volets = _volets(enr.reponses["lead_v1_profils_complets"])
    assert _statuts(volets)["equipe"] == ("non_verifiable", None)
    assert _statuts(volets)["meteo"] == ("non_verifiable", None)

    # ---- 6. un devis accepté que M6 n'a jamais vu -----------------------------------------------------------------
    moteur.horloge.maintenant = debut_de_journee(18)
    _livrer_a_m4_seul(moteur, "LEAD-MQ-R-fictif", "DEVIS-MQ-R-fictif")
    liste = admin.appeler("m4_lister_interventions", {"statut": "a_planifier"})
    assert liste.statut == 200
    [sans_m6] = [i for i in liste.resultat if i["lead_id"] == "LEAD-MQ-R-fictif"]
    enr.preparer("materiel_sans_charge", sans_m6["intervention_id"])
    volets = _volets(enr.reponses["materiel_sans_charge"])
    assert _statuts(volets)["materiel"] == ("non_verifiable", None)
    return enr


@SQLITE_SEULEMENT
def test_les_manques_du_moteur_ont_la_forme_de_la_fixture_que_l_app_lit(
        moteur, equipe, tmp_path, monkeypatch, declarer_services):
    """Le pont entre les deux langages : `mobile/src/admin/fixtures/manques-m4.json` (lue par les tests Jest, qui la
    font passer par les lecteurs et les modèles de vue de l'app) est la forme EXACTE de ce que le moteur rend
    aujourd'hui. Si le serveur change une clé, un code ou un statut, ce test échoue ; on relit alors la table de l'app,
    puis on régénère la fixture
    (`OPSYS_REGENERER_FIXTURES_MOBILE=1 pytest tests/e2e/test_manques_m4_appareil.py -k fixture`)."""
    enr = _enregistrer_les_manques(moteur, equipe, tmp_path, declarer_services)
    if os.environ.get(ENV_REGENERER) == "1":
        FIXTURE_APP.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_APP.write_text(json.dumps(
            {"fictif": True, "appels": enr.appels, "reponses": enr.reponses}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    fixture = json.loads(FIXTURE_APP.read_text(encoding="utf-8"))
    assert fixture["fictif"] is True
    assert set(fixture["reponses"]) == set(enr.reponses) and set(fixture["appels"]) == set(enr.appels)
    for nom, vivante in enr.reponses.items():
        assert _forme(vivante) == _forme(fixture["reponses"][nom]), f"{nom} : la forme du moteur a changé"
        assert enr.appels[nom] == fixture["appels"][nom], nom
        # Ce que M4 dit d'un manque et de son code, lu par l'app : les mêmes (volet, statut, code) que la fixture.
        assert _cles_de_manque(_volets(vivante)) == _cles_de_manque(_volets(fixture["reponses"][nom])), nom


# ---------------------------------------------------------------------------------------------------------
# La table de l'app dit vrai : ni un manque sans phrase, ni une phrase pour un manque qui n'existe pas
# ---------------------------------------------------------------------------------------------------------
def _registre_avec_intervention(lead_id: str = "LEAD-MQ-1"):
    registre = registre_m4.Registre()
    lead = {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100"}, "service": SERVICE, "ville": "Repentigny",
        "urgence_declaree": False, "canal": "texte",
    }
    accuse, verdict = etats_m4.inscrire_depuis_devis(registre, "DEVIS-MQ-1", lead, SEL, HORODATAGE)
    assert verdict is None, verdict
    return registre, accuse["intervention_id"]


def _position_ok(_registre: Any, _chantier_id: str) -> tuple[dict[str, Any], None]:
    return {"version": 1, "latitude_microdegres": 45_741_500, "longitude_microdegres": -73_450_500}, None


def _manques_hors_moteur(declarer_services: Any) -> set[str]:
    """Les deux manques que le moteur ne produit pas à peu de frais, par le VRAI M4 (`preparation.evaluer`) : une
    intervention sans devis (lead v1 hérité) et une position dont la clé de chiffrement est détruite (Loi 25)."""
    declarer_services()
    registre = registre_m4.Registre()
    contrat = {
        "lead_id": "L-LEGACY", "conversation_id": "C1", "type_travaux": "renovation_totale", "ville": "Montreal",
        "canal": "telephone", "contact": {"nom": "Dupont", "telephone": "0102030405"}, "urgence_declaree": False,
    }
    marqueur = {"readiness_ok": True, "lead_id": "L-LEGACY", "hash_tete_registre": None,
                "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32}
    accuse, verdict = etats_m4.inscrire_intervention(contrat, marqueur, registre, "2025-06-02T08:00:00+00:00", SEL)
    assert verdict is None, verdict
    sans_devis, refus = preparation_m4.evaluer(registre, accuse["intervention_id"], _position_ok)
    assert refus is None

    registre, iid = _registre_avec_intervention()
    cle = bytes(range(32))
    _, verdict = localisation_m4.confirmer(
        registre, "LEAD-MQ-1", "confirmee", HORODATAGE, "admin.fictif", adresse="100 boulevard Iberville, Repentigny",
        source="manuel", latitude_microdegres=45_741_500, longitude_microdegres=-73_450_500, fournir_cle=lambda: cle)
    assert verdict is None, verdict
    detruite, refus = preparation_m4.evaluer(
        registre, iid, lambda r, chantier: localisation_m4.position_confirmee(r, chantier, None))
    assert refus is None

    assert sans_devis["volets"]["soumission"]["manque"], "M4 dit ce qui manque, avec ses mots"
    return _cles_de_manque(sans_devis["volets"]) | _cles_de_manque(detruite["volets"])


def test_la_table_des_manques_de_l_app_est_exactement_ce_que_m4_produit(declarer_services):
    table = _table_de_l_app()
    fixture = json.loads(FIXTURE_APP.read_text(encoding="utf-8"))["reponses"]
    du_moteur = set().union(*(_cles_de_manque(_volets(enveloppe)) for enveloppe in fixture.values()))
    hors_moteur = _manques_hors_moteur(declarer_services)
    produits = du_moteur | hors_moteur

    # Les deux sens : aucun manque de M4 sans phrase dans l'app, aucune phrase pour un manque que M4 ne produit pas.
    assert produits - set(table) == set(), "M4 produit un manque que l'app ne sait pas dire"
    assert set(table) - produits == set(), "l'app dit un manque que M4 ne produit pas (ou que rien ne couvre)"
    # Le manque que le moteur ne fait pas dire à peu de frais est bien de M4, avec ces codes.
    assert {"soumission:manque:", "adresse:manque:REJ-LOCALISATION-DETRUITE"} <= hors_moteur

    for cle in table:
        volet, statut, code = cle.split(":")
        assert volet in preparation_m4.VOLETS, cle
        assert statut in (preparation_m4.STATUT_MANQUE, preparation_m4.STATUT_NON_VERIFIABLE), cle
        # Un code est vide (M4 n'en donne pas) ou un jeton sûr, que l'écran peut afficher.
        assert code == "" or JETON.fullmatch(code), cle


def test_un_code_de_manque_est_un_code_du_serveur():
    """Les codes de la table sont ceux que le serveur écrit : des `REJ-*` (le catalogue de M4, ou celui des profils du
    socle), ou un état du matériel de M6. Un code que le serveur renommerait fait échouer ce test."""
    codes = {cle.split(":")[2] for cle in _table_de_l_app() if cle.split(":")[2] != ""}
    rejets = {code for code in codes if code.startswith("REJ-")}
    assert codes - rejets == {materiel_m4.ETAT_PARTIEL, materiel_m4.ETAT_A_COMMANDER}
    du_socle = {equipes_entreprise.VERDICT_EQUIPES_NON_CONFIGUREES, meteo_entreprise.VERDICT_METEO_NON_CONFIGUREE}
    assert rejets - du_socle <= verdicts_m4.CODES_M4, rejets - du_socle - verdicts_m4.CODES_M4
    assert rejets == du_socle | {
        "REJ-COORDONNEES-A-CONFIRMER", "REJ-LOCALISATION-DETRUITE", taxonomie.VERDICT_PROFIL_INVALIDE,
        "REJ-CHAMP-MANQUANT",
    }
