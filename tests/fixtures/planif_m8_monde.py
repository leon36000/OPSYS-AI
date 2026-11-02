"""Monde de la preuve « constats planifiés » (tests seulement) : les DIX départements réels sur une base SQLite migrée,
le VRAI bus et son répartiteur, le VRAI planificateur durable avec une horloge INJECTÉE (jamais de sleep), et des
données FICTIVES dans M1, M2, M4, M5, M6 et M7.

Seuls le réseau et les services externes sont absents (aucun n'est appelé par les constats). Les données sont semées par
les vrais outils et registres de chaque département (les aides de leurs propres suites sont réutilisées quand elles
existent), puis les constats les lisent : rien n'est publié à la main.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib.util
import json
from pathlib import Path
from typing import Any

import interconnexion_charges as ch
import interconnexion_monde as im
import planif_qa as pq
import yaml

from opsys import contexte, equipes, evenements, identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.connecteurs_planification import etat, planificateur
from opsys.connecteurs_planification.planificateur import Ports

RACINE = Path(__file__).resolve().parents[2]
FICTIF = True
M1, M2, M3, M4, M5, M6, M7, M8, M9, M10 = (
    "m01-front-office", "m02-revenue-crm", "m03-estimation", "m04-field-ops", "m05-financecore",
    "m06-material-control", "m07-marketing", "m08-analytics", "m09-strategic-intelligence", "m10-memoire")
TOUS = (M1, M2, M3, M4, M5, M6, M7, M8, M9, M10)
DEBUT = dt.datetime(2026, 11, 12, 5, 0, 30, tzinfo=dt.UTC)  # un jeudi, 30 s après minuit local : début d'un créneau
LUNDI = "2026-11-09"
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
CONSTATS = {
    "m1.constat.plaintes": "m1.plaintes_constatees",
    "m2.constat.pipeline": "m2.pipeline_constate",
    "m4.constat.capacite-equipe": "m4.capacite_equipe_constatee",
    "m5.constat.depense-publicitaire": "m5.depense_publicitaire_constatee",
    "m5.constat.factures-emises": "m5.facture_emise_constatee",
    "m6.constat.disponibilite": "m6.disponibilite_constatee",
    "m7.constat.performance-signaux": "m7.performance_signaux_constatee",
}
# Ce qui ne doit JAMAIS apparaître dans une charge publiée : une personne, une adresse, un numéro, un client, un
# article.
PERSONNEL = ("Jeanne", "example", "exemple.test", "514", "client-fictif", "vendeur", "p0", "CH-", "DEVIS", "PO-",
             "eq-a", "eq-b", ".fictif", "Travaux", "CH-F", "D-F", "compte-fictif")


def _charger(nom: str, chemin: Path) -> Any:
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def aide_m4() -> Any:
    return _charger("planif_aide_m4", RACINE / "departments/m04-field-ops/tests/test_cedule_tournees_outils.py")


def aide_m6() -> Any:
    return _charger("planif_aide_m6", RACINE / "departments/m06-material-control/tests/test_reservation_outils.py")


class _Restreint:
    """M10 réel, abonné au seul `m8.fait_consolide` (ses autres consommateurs supposent M4 et M5 réels)."""

    def __init__(self, departement: Any, types: set[str]) -> None:
        self._departement, self._types = departement, types

    def __getattr__(self, nom: str) -> Any:
        return getattr(self._departement, nom)

    @property
    def evenements_consomme(self) -> tuple[str, ...]:
        return tuple(t for t in self._departement.evenements_consomme if t in self._types)

    def charger_consommateurs(self) -> dict[str, Any]:
        return {t: f for t, f in self._departement.charger_consommateurs().items() if t in self._types}


@dataclasses.dataclass
class Monde:
    bus: im.Monde
    plan: pq.Planif
    aide4: Any = None
    aide6: Any = None

    # -- l'horloge et le planificateur --------------------------------------------------------------------------------
    @property
    def horloge(self) -> pq.Horloge:
        return self.plan.horloge

    def maintenant(self) -> str:
        return dt.datetime.fromtimestamp(self.horloge(), dt.UTC).isoformat()

    def activer(self, mode: str = "actif", noms: tuple[str, ...] | None = None,
                intervalle_s: int | None = None) -> None:
        for nom in noms or tuple(CONSTATS):
            with stockage.transaction() as cnx:
                etat.appliquer(cnx, pq.session_admin(), nom, mode, motif="preuve fictive", maintenant=self.horloge(),
                               intervalle_s=intervalle_s)

    def tour(self, avance: float = 0.0, **options: Any) -> dict[str, Any]:
        """Un tour ; l'horloge avance de `avance` secondes d'abord. Rend le résumé des seuls constats."""
        self.horloge.avancer(avance)
        resume = planificateur.tour(self.plan.departements, ports=self.plan.ports, **options)
        return {n: v for n, v in resume["executeurs"].items() if ".constat." in n} | (
            {"_raison": resume["raison"]} if "raison" in resume else {})

    def propager(self, *departements: str) -> dict[str, int]:
        return self.bus.repartir(departements=departements or (M8,))

    # -- les lectures de M8 ------------------------------------------------------------------------------------------
    def m8(self, outil: str, **arguments: Any) -> dict[str, Any]:
        capacites = Capacites(self.bus.departements, stockage.transaction, filtre={M8}, memoire=False)
        reponse = capacites.appeler(outil, arguments)
        assert reponse["ok"] is True, reponse
        return reponse["resultat"]

    def pages(self, outil: str, cle: str, **arguments: Any) -> list[dict[str, Any]]:
        depart, lignes = 0, []
        while depart is not None:
            page = self.m8(outil, depart=depart, **arguments)
            lignes += page[cle]
            depart = page["prochain_depart"]
        return lignes

    def mesures(self) -> dict[str, dict[str, Any]]:
        return {m["metric_id"]: m for m in self.pages("m8_lire_mesures", "mesures", maintenant=self.maintenant())}

    def tuiles(self, wallboard_id: str) -> dict[str, dict[str, Any]]:
        return {t["id"]: t for t in self.pages("m8_lire_wallboard", "tuiles", maintenant=self.maintenant(),
                                               wallboard_id=wallboard_id)}

    # -- ce qui est publié ---------------------------------------------------------------------------------------------
    def publies(self, type_evenement: str | None = None) -> list[dict[str, Any]]:
        return [{**e, "charge": json.loads(e["charge"]) if isinstance(e["charge"], str) else e["charge"]}
                for e in self.bus.sortants(type_evenement)]

    def nombre_publie(self) -> dict[str, int]:
        compte: dict[str, int] = {}
        for e in self.bus.sortants():
            if e["type_evenement"] in CONSTATS.values():
                compte[e["type_evenement"]] = compte.get(e["type_evenement"], 0) + 1
        return compte


def monter(tmp_path: Any, monkeypatch: Any, declarer_services: Any, *, url: str | None = None) -> Monde:
    bus = im.monter(tmp_path, monkeypatch, TOUS, url=url)
    bus.surveiller(monkeypatch)
    bus.departements[M10] = _Restreint(bus.departements[M10], {"m8.fait_consolide"})
    with stockage.transaction() as cnx:
        for ident, roles in (("nathan", ["nathan_owner", "admin"]), ("admin.fictif", ["admin"]),
                             ("vendeur.un", ["seller"]), ("marc.fictif", ["employee"])):
            identite.creer_personne(cnx, ident, ident, "mot-de-passe-fictif-12345", roles)
    declarer_services()
    horloge = pq.Horloge(DEBUT.timestamp())
    planificateur.reinitialiser_arret()
    plan = pq.Planif(horloge, Ports(horloge=horloge), bus.departements)
    return Monde(bus, plan)


def demonter() -> None:
    planificateur.reinitialiser_arret()
    im.demonter()


# ====================================================================================================== les données
def semer_m2() -> None:
    """26 leads fictifs étalés du 1er au 30 octobre, tous qualifiés : treize convertis, neuf perdus, quatre encore
    ouverts (22 leads résolus : assez pour que M2 accepte de conclure sur un taux, son seuil étant de 20)."""
    from m2_revenue_crm import outils

    debut = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
    action = {"description": "Appeler le client", "echeance": "2026-11-20T09:00:00-05:00"}
    for k in range(26):
        lead_id = f"p{k:03d}"
        ingere = debut + dt.timedelta(hours=27 * k)
        contrat = {
            "lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "type_travaux": "renovation_totale",
            "contact": {"nom": f"Client {lead_id}", "telephone": f"418-555-{k:04d}",
                        "courriel": f"{lead_id}@example.test"},
            "ville": "Québec", "urgence_declaree": k % 7 == 0, "canal": "telephone"}
        assert outils.ingerer_lead(contrat, ingere.isoformat())["accepte"] is True
        qualifie = ingere + dt.timedelta(days=1)
        assert outils.transitionner_statut(lead_id, "qualifie", qualifie.isoformat(), owner="vendeur.un",
                                           prochaine_action=action)["accepte"] is True
        if k % 2 == 0:
            converti = qualifie + dt.timedelta(days=2 + k % 5)
            assert outils.transitionner_statut(lead_id, "converti", converti.isoformat(),
                                               reference_devis_m3=f"devis-{lead_id}")["accepte"] is True
        elif k % 3 != 0:
            perdu = qualifie + dt.timedelta(days=3 + k % 4)
            assert outils.transitionner_statut(lead_id, "perdu", perdu.isoformat(),
                                               motif="Budget insuffisant.")["accepte"] is True


def semer_m6(monde: Monde) -> None:
    """Du stock reçu, un devis accepté qui réserve (une ligne en rupture) : trois articles distincts de la
    disponibilité."""
    from m6_material_control import outils as m6_outils

    aide = monde.aide6
    m6 = {o.nom: o for o in m6_outils.outils()}
    aide._recevoir(m6, aide.GOUTTIERE, 100.0, "PO-DEPOT-1")
    aide._accepter(aide._devis("DEVIS-A", "CH-A", gouttiere="70", vis="20"))


def semer_m1(corpus: dict[str, Any]) -> None:
    """Deux plaintes reçues par SMS le 30 et le 31 octobre (vocabulaire fictif du propriétaire)."""
    from m1_front_office.outils import recevoir_message_canal, reinitialiser_registre

    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    taxonomie.enregistrer_signaux_plainte(corpus["signaux_plainte"])
    reinitialiser_registre()
    fuseau = dt.timezone(dt.timedelta(hours=-5))
    for rang, (texte, jour) in enumerate((
            ("Je suis très déçu : vos gars ont abîmé ma propriété.", dt.datetime(2026, 11, 10, 9, 0, tzinfo=fuseau)),
            ("Danger : un fil électrique pend, j'ai peur.", dt.datetime(2026, 11, 11, 9, 0, tzinfo=fuseau)))):
        reponse = recevoir_message_canal(canal="sms", expediteur=f"+1514555{rang:04d}", message_id=f"SM-{rang}",
                                         recu_le=jour.isoformat(), texte=texte)
        assert reponse is not None


def semer_m5_factures() -> None:
    """Deux factures envoyées (dont une payée) et une en brouillon : seules les envoyées sont des constats."""
    from m5_financecore import facturation, taux_fiscaux
    from m5_financecore import outils as m5_outils
    from m5_financecore import registre as registre_module

    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []

    def facture(facture_id: str, prix: str, envoi: str | None, payer: bool = False) -> None:
        with stockage.transaction():
            reg = registre_module.Registre(maillons=stockage.maillons(M5, "factures"))
            lignes = [{"description": "Travaux (fictif)", "quantite": "1", "unite": "forfait", "prix_unitaire": prix,
                       "reference_ligne_devis": "L1"}]
            etapes = [facturation.creer_facture_brouillon(facture_id, f"CH-{facture_id}", f"D-{facture_id}",
                                                          "client-fictif", lignes, "2026-10-01T09:00:00-04:00",
                                                          dictionnaire, reg)]
            if envoi is not None:
                etapes.append(facturation.envoyer_facture(facture_id, envoi, reg))
            if payer:
                etapes.append(facturation.enregistrer_paiement_facture(facture_id, "689.85", "nathan",
                                                                      "2026-11-11T09:00:00-05:00", reg))
            for couple in etapes:
                assert couple[1] is None, couple

    facture("F-1", "600.00", "2026-11-10T09:00:00-05:00", payer=True)
    facture("F-2", "600.00", "2026-11-12T00:00:10-05:00")
    facture("F-3", "100.00", None)


def semer_m7_releves_et_comptabilite(monde: Monde) -> None:
    """Trois relevés de dépense publicitaire (octobre) par le bus : M5 en tire des brouillons, une personne en valide
    deux ; M8 les reçoit aussi. Le troisième reste en attente de validation (couverture partielle, dite)."""
    from m5_financecore import grand_livre, outils

    humain = {"par": "nathan.fictif", "role": "nathan_owner", "voie": "test"}
    for releve, jour, montant in (("g-03", "2026-11-03", "125.40"), ("g-04", "2026-11-04", "74.60"),
                                  ("g-05", "2026-11-05", "75.40")):
        evenements.publier("m7.depenses_marketing_constatees", M7,
                           ch.depense_marketing(releve, jour=jour, montant=montant,
                                                releve_le="2026-11-12T00:00:05-05:00"),
                           evenement_id=f"{releve}-r1")
    monde.bus.repartir(departements=(M5,))
    registre, plan = outils._contexte_grand_livre()[0]
    for releve in ("g-03", "g-04"):
        (ecriture,) = [e for e in grand_livre.etat_grand_livre(registre.lire())["ecritures"].values()
                       if e["piece"]["reference"].startswith(f"m7:{releve}:") and e["statut"] == "BROUILLON"]
        _, refus = grand_livre.valider_ecriture(registre, plan, ecriture_id=ecriture["ecriture_id"], humain=humain,
                                                horodatage="2026-11-12T00:00:20-05:00")
        assert refus is None, refus


def semer_m7_signaux() -> None:
    """Signaux du SITE : Search Console (octobre : 20 jours à 10 clics et 200 impressions ; novembre : 10 jours à 5
    clics et 100 impressions) et Umami (octobre : 10 jours à 30 visites ; novembre : 10 jours à 30). Chaque mois est un
    résumé, les deux mois ne se chevauchent pas."""
    from m7_marketing.signaux import modele, registre

    provenance = {"fournisseur": "fictif", "point_acces": "fictif", "version_api": "v1", "mode": "api_lecture",
                  "empreinte_reponse": "a" * 64, "page": 0}

    def fait(source: str, nature: str, jour: str, mesures: dict[str, str]) -> Any:
        return modele.brouillon_fait(
            source=source, compte_ref="site-principal", nature=nature, portee_type="site", portee_ref="propriete",
            debut=jour, fin=jour, mesures=mesures, observe_le="2026-11-12T04:00:00+00:00", fictif=False,
            provenance=provenance, echantillon={"nature": "complet", "n": None})

    def jours(debut: str, n: int) -> list[str]:
        d = dt.date.fromisoformat(debut)
        return [(d + dt.timedelta(days=i)).isoformat() for i in range(n)]

    faits = [fait("search_console", "performance_recherche_jour", j, {"clics": "10", "impressions": "200"})
             for j in jours("2026-10-01", 20)]
    faits += [fait("search_console", "performance_recherche_jour", j, {"clics": "5", "impressions": "100"})
              for j in jours("2026-11-01", 10)]
    faits += [fait("umami", "audience_jour", j, {"visites": "30"}) for j in jours("2026-10-01", 10)]
    faits += [fait("umami", "audience_jour", j, {"visites": "30"}) for j in jours("2026-11-01", 10)]
    with stockage.transaction():
        registre.enregistrer(stockage.maillons(*registre.REGISTRE), faits, "2026-11-12T04:00:00+00:00")


def semer_m4(monde: Monde) -> None:
    """Un profil d'équipes déclaré, six chantiers cédulés puis DATÉS (lundi 2 novembre 2026) : les heures d'équipe
    déclarées et les heures planifiées de la semaine sont calculables."""
    aide = monde.aide4
    par_nom = {o.nom: o for o in __import__("m4_field_ops.outils", fromlist=["outils"]).outils()}
    brut = {"liste": [{**e, "membres": [f"{e['id'].replace('-', '.')}.fictif"]} for e in aide._equipes()]}
    equipes.enregistrer_equipes(equipes.normaliser_equipes(brut))
    interventions = {}
    for rang, lead in enumerate(aide.SCENARIO["leads"]):
        interventions[lead["lead_id"]] = aide._inscrire(par_nom, lead, f"2030-01-01T00:00:0{rang}+00:00")
        aide._resultat(aide._confirmer(par_nom, lead))
    plan = aide._resultat(aide._proposer(par_nom, interventions))["plan_id"]
    aide._resultat(aide._appliquer(par_nom, plan))
    aide._resultat(aide._appeler(par_nom, "m4_confirmer_dates_cedule",
                                 {"plan_id": plan, "calendrier": {"0": LUNDI}, "revision_attendue": 0}, aide.ADMIN))


def semer_tout(monde: Monde, corpus_plaintes: dict[str, Any]) -> None:
    monde.aide4, monde.aide6 = aide_m4(), aide_m6()
    semer_m2()
    semer_m6(monde)
    semer_m1(corpus_plaintes)
    semer_m5_factures()
    semer_m7_releves_et_comptabilite(monde)
    semer_m7_signaux()
    semer_m4(monde)


def lire_yaml(chemin: Path) -> dict[str, Any]:
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    assert donnees["fictif"] is True
    return donnees

