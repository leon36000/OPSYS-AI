"""Aide NON COLLECTÉE : le monde fictif d'un MOIS pour le radar de risques et les scénarios chiffrés de M9.

Ce module n'est pas un test. Il alimente, par les VRAIS outils et le VRAI bus des départements M1, M2, M4, M5, M7 et M8
(jamais d'INSERT SQL direct), une base SQLite migrée, avec une horloge INJECTÉE : chaque geste porte son instant, M9 n'a
pas d'horloge. Les données portent « fictif » ; aucune donnée réelle, aucun envoi.

Le mois : quatre semaines (vendredi 17 h, heure de l'Est = 21 h UTC) T1 à T4. Chaque ``semaine_k()`` ajoute ce qui s'y
passe ; ``capturer_semaine(k)`` capture les lectures de la semaine par le port privé de M9 (admin console). Les
symptômes attendus de chaque semaine sont consignés dans ``test_m9_radar_scenarios_e2e.py``.
"""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import yaml
from m1_front_office import outils as m1_outils
from m2_revenue_crm import outils as m2_outils
from m7_marketing import depenses_marketing as dep7

from opsys import contexte, identite, stockage, taxonomie
from opsys.contexte import IdentiteAppelante

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
FICTIF = True


def _charger(nom: str):
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, ICI / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


B = _charger("m9_producteurs_b")
A = _charger("m9_producteurs_a")
M1, M2, M3, M4, M5, M6, M7, M8, M9 = (
    "m01-front-office",
    "m02-revenue-crm",
    "m03-estimation",
    "m04-field-ops",
    "m05-financecore",
    "m06-material-control",
    "m07-marketing",
    "m08-analytics",
    "m09-strategic-intelligence",
)
ADMIN = B.ADMIN  # admin console authentifié (la seule identité que le port de M9 admet)

# L'horloge du mois (instants de RÉCEPTION fournis par la console, vendredi 17 h de l'Est).
T = {
    1: "2026-10-30T21:00:00Z",
    2: "2026-11-06T21:00:00Z",
    3: "2026-11-13T21:00:00Z",
    4: "2026-11-20T21:00:00Z",
}
JOUR = {1: "2026-10-30", 2: "2026-11-06", 3: "2026-11-13", 4: "2026-11-20"}
SEMAINE_CEDULE = "2026-11-02"  # le lundi daté par M4 (A.LUNDI)
DEBUT_VEILLE = dt.datetime(2026, 10, 26, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))

# Seuils de DIRECTION (fictifs) déclarés pour le radar : posés dans un manifeste temporaire que la couche des réglages
# lit.
SEUILS_DIRECTION = {
    "plaintes_seuil_nombre": 3,
    "capacite_utilisation_seuil_pct": "60",
    "depense_marketing_plafond_cad": "1500.00",
    "leads_plancher_par_semaine": 2,
    "estimation_ecart_relatif_max": "0.25",
    "retard_chantier_jours": 5,
    "donnees_perimees_jours": 10,
    "cash_libre_plancher_cad": "5000.00",
    "multiple_seuil_critique": "1.5",
}

CONFIG_M5 = json.loads(
    json.dumps(B.CONFIGURATION_M5).replace("2026-09-", "2026-10-").replace("2026-06-30", "2026-09-30")
)
CONFIG_M5["prevision"]["seuil_alerte"] = {
    "montant": "1000.00",
    "source": "décision de Nathan (fictive)",
    "au": "2026-10-25",
}
CONFIG_M5["prevision"]["echeances_obligations"] = {"paies": "2026-11-13", "das": "2026-11-15", "dettes": "2026-11-30"}


def secondes(n: int) -> dt.timedelta:
    return dt.timedelta(seconds=n)


class Monde:
    """Le monde du mois : installé une fois, enrichi semaine après semaine."""

    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        self.tmp = tmp_path
        self.mp = monkeypatch
        (tmp_path / "home").mkdir(exist_ok=True)
        monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
        B.installer_base(tmp_path, monkeypatch)
        with stockage.transaction() as cnx:
            for personne, nom, secret in (
                ("marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234"),
                ("lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345"),
            ):
                identite.creer_personne(cnx, personne, nom, secret, ["employee"])
        m2_outils.utiliser_stockage_durable()
        taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
        self.m4 = A.outils_departement(M4)
        self.n_recu = 0
        self.config_m5 = copy.deepcopy(CONFIG_M5)
        B.declarer_m5(tmp_path, monkeypatch, self.config_m5)
        self.declarer_m2()
        self.declarer_seuils(SEUILS_DIRECTION)
        self.cap = B.capacites(M1, M2, M4, M5, M7, M8)

    def fermer(self) -> None:
        m2_outils.reinitialiser_registre()
        B.desinstaller_base()

    # -------------------------------------------------------------------------------------- déclarations
    def declarer_seuils(self, radar: dict) -> None:
        """Les seuils de direction du radar : un manifeste temporaire de M9 (le fichier livré n'en déclare aucun)."""
        from m9_strategic_intelligence import reglages_radar

        donnees = yaml.safe_load(Path(reglages_radar._MANIFESTE).read_text(encoding="utf-8"))
        donnees["configuration"]["radar"] = dict(radar)
        chemin = self.tmp / "m9-department.yaml"
        chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
        self.mp.setattr(reglages_radar, "_MANIFESTE", chemin)

    def declarer_m2(self, heures_lead_chaud: int | None = 4) -> None:
        sla = {} if heures_lead_chaud is None else {"heures_lead_chaud": heures_lead_chaud}
        B.declarer_configuration(m2_outils, self.tmp, self.mp, {"sla": sla}, "m2-department.yaml")

    def declarer_m5_obligations(self, paies: str) -> None:
        self.config_m5["obligations_declarees"]["paies"]["montant"] = paies
        B.declarer_m5(self.tmp, self.mp, self.config_m5)

    def seuil_m5(self, montant: str) -> None:
        self.config_m5["prevision"]["seuil_alerte"]["montant"] = montant
        B.declarer_m5(self.tmp, self.mp, self.config_m5)

    # --------------------------------------------------------------------------------------------- M1
    def vocabulaire_plaintes(self) -> None:
        corpus = yaml.safe_load(
            (RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml").read_text("utf-8")
        )
        assert corpus["fictif"] is True
        taxonomie.enregistrer_signaux_plainte(corpus["signaux_plainte"])

    def sms(self, texte: str, minutes_apres_debut: int, numero: str, base: dt.datetime = DEBUT_VEILLE) -> None:
        self.n_recu += 1
        reponse = m1_outils.recevoir_message_canal(
            canal="sms",
            expediteur=numero,
            message_id=f"SM-{self.n_recu}",
            recu_le=(base + dt.timedelta(minutes=minutes_apres_debut)).isoformat(),
            texte=texte,
        )
        assert reponse is not None

    def plaintes(self, n: int, *, jour: dt.datetime, sensible: bool = False) -> None:
        """``n`` plaintes (SMS de client déçu) reçues le ``jour`` ; ``sensible`` : une urgence de sécurité en plus."""
        for rang in range(n):
            self.sms(
                "Je suis très déçu : vos gars ont abîmé ma gouttière.",
                rang * 7,
                f"+1514555{rang + 100 + jour.day:04d}",
                jour,
            )
        if sensible:
            self.sms(
                "Danger : un fil électrique pend sur le balcon, j'ai peur.", 90, f"+1514555{900 + jour.day:04d}", jour
            )

    def demande_normale(self, jour: dt.datetime, numero: str) -> None:
        self.sms("Bonjour, je veux une soumission pour des gouttières à Laval.", 5, numero, jour)

    # --------------------------------------------------------------------------------------------- M2
    def lead(self, lead_id: str, quand: str, *, urgent: bool = False) -> None:
        contrat = {
            "lead_id": lead_id,
            "conversation_id": f"conv-{lead_id}",
            "contact": {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
            "type_travaux": "renovation_totale",
            "ville": "Québec",
            "urgence_declaree": urgent,
            "canal": "telephone",
        }
        assert m2_outils.ingerer_lead(contrat, quand)["accepte"] is True

    def historique_de_leads(self, par_bloc: list[int], fin_dernier_bloc: str, prefixe: str = "hist") -> None:
        """Des leads ingérés par blocs de sept jours qui se terminent à ``fin_dernier_bloc`` (le dernier bloc d'abord à
        droite) : M2 compte ses séries hebdomadaires en blocs de sept jours qui finissent à l'instant de lecture, ce qui
        donne à la prévision par intervalle de quoi travailler."""
        fin = dt.datetime.fromisoformat(fin_dernier_bloc.replace("Z", "+00:00"))
        for rang, nombre in enumerate(par_bloc):
            fin_bloc = fin - dt.timedelta(days=7 * (len(par_bloc) - 1 - rang))
            for k in range(nombre):
                instant = fin_bloc - dt.timedelta(days=3, hours=k)
                self.lead(f"{prefixe}-{rang:02d}-{k}", instant.isoformat().replace("+00:00", "Z"))

    # --------------------------------------------------------------------------------------------- M4
    def cedule(self) -> dict:
        """Équipes déclarées, trois chantiers, cédule appliquée puis datée au lundi ``SEMAINE_CEDULE``."""
        A.declarer_meteo(self.tmp / "home")
        resultat = A.m4_alimenter_cedule(self.m4, dossier=self.tmp / "home")
        self.profil_etendu()
        return resultat

    def profil_etendu(self, fin_min_eq_a: int = 1020) -> None:
        """Le profil des équipes avec ce que la capacité d'une semaine FUTURE exige : semaine type, effectif planifié,
        durée d'un jour-personne et fériés déclarés (jamais supposés par M4). ``fin_min_eq_a`` raccourcit le quart
        déclaré
        de l'équipe eq-a (minutes depuis minuit) : la même cédule pèse alors davantage sur ses heures déclarées."""
        from opsys import cli

        plage = [{"debut": "07:00", "fin": "15:00"}]
        semaine = {
            "fuseau": "America/Montreal",
            "lundi": plage,
            "mardi": plage,
            "mercredi": plage,
            "jeudi": plage,
            "vendredi": plage,
            "samedi": [],
            "dimanche": [],
        }
        profil = {
            "liste": [
                {
                    "id": equipe,
                    "membres": [membre],
                    "competences": ["gouttieres", "revetement"],
                    "depot": {"id": depot, **A.DEPOTS[depot]},
                    "quarts": [{"jour": 0, "debut_min": 480, "fin_min": fin_min_eq_a if equipe == "eq-a" else 1020}],
                    "semaine_type": semaine,
                    "effectif_planifie": 2,
                }
                for (equipe, depot), membre in zip(A.EQUIPES, ("marc.fictif", "lea.fictif"), strict=True)
            ],
            "services": {
                service: {"duree_min": A.DUREES[service], "competences": A.COMPETENCES[service]} for service in A.DUREES
            },
            "cedule": dict(A.PARAMETRES_CEDULE),
            "fenetre_par_defaut": dict(A.FENETRE_CLIENT),
            "feries": {"annees": [2026], "jours": []},
            "duree_jour_personne_minutes": 480,
        }
        fichier = self.tmp / "equipes-etendu.yaml"
        fichier.write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
        assert cli.main(["equipes", "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0

    def report(self, intervention_id: str, recu_le: str) -> None:
        A.geste(
            self.m4,
            "m4_signaler_report",
            {"intervention_id": intervention_id, "motif": "client_absent", "horodatage": "2000-01-01T00:00:00+00:00"},
            A.MARC,
            dt.datetime.fromisoformat(recu_le.replace("Z", "+00:00")),
        )

    # --------------------------------------------------------------------------------------------- M5 / M8
    def mouvements(self) -> None:
        B.enregistrer_mouvements_m5()

    def constater_cash_libre(self, jour: str) -> dict:
        with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
            reponse = B.executer_atomique(B._outil(B.m5_outils, "m5_constater_cash_libre"), {"aujourd_hui": jour})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
        B.livrer((M5, M8))
        return reponse["resultat"]

    def factures(self) -> None:
        B.factures_clients_m5(
            envoyees=(
                ("FACT-E1", "DEVIS-E1", "2026-10-14T09:30:00-04:00"),
                ("FACT-E2", "DEVIS-E2", "2026-10-20T09:30:00-04:00"),
            ),
            brouillons=(),
        )

    # --------------------------------------------------------------------------------------------- M7
    def depenses(self, google: str, meta: str, mois: str, fin: str, releve_le: str) -> None:
        """Deux relevés de plateforme (Google Ads, Meta) du mois ``mois`` (AAAA-MM), par la fonction interne de M7."""
        base = {
            "revision": 1,
            "campagne_ref": None,
            "libelle_campagne": None,
            "periode_debut": f"{mois}-01",
            "periode_fin": fin,
            "devise": "CAD",
            "base_taxes": "HORS_TAXES",
            "source": "RELEVE_PLATEFORME",
            "releve_le": releve_le,
        }
        with stockage.transaction():
            dep7.enregistrer_releve(
                {
                    **base,
                    "releve_id": f"rel-google-{mois}",
                    "canal": "google_ads",
                    "montant_cad": google,
                    "source_ref": f"releve-fictif-g-{mois}",
                }
            )
            dep7.enregistrer_releve(
                {
                    **base,
                    "releve_id": f"rel-meta-{mois}",
                    "canal": "meta",
                    "montant_cad": meta,
                    "source_ref": f"releve-fictif-m-{mois}",
                }
            )

    # ------------------------------------------------------------------------------------------ captures
    def capturer(self, lecture: str, arguments: dict, recu: str, *, cap=None) -> dict:
        reponse = B.capturer(cap or self.cap, ADMIN, lecture, arguments, recu)
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
        return reponse["resultat"]["capture"]

    def appeler_m9(self, outil: str, arguments: dict, identite_appelante=ADMIN) -> dict:
        if identite_appelante is None:
            return self.cap.appeler(outil, arguments)
        with contexte.appele_par_appareil(identite_appelante):
            return self.cap.appeler(outil, arguments)
