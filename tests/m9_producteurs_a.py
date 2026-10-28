"""Aides (NON collectées) : données FICTIVES de M4, M6 et M3 pour les captures M9, par les outils publics.

Ce module n'est pas un test : il alimente, par les VRAIS outils et le VRAI bus des départements (jamais d'INSERT SQL
direct, jamais d'import interne contournant leur API), une base SQLite migrée, pour que `test_m9_producteurs_a.py` — et
tout autre test qui veut une capture M9 sur ces producteurs — lise de vraies données par le port privé de M9.

Contenu :

* installation commune : base migrée, personnes fictives (admin, vendeur, employés), identité admin console de M9 ;
* M4 : interventions planifiées (`m4_planifier_intervention`), cédule appliquée puis datée (`m4_proposer_cedule`,
  `m4_appliquer_cedule`, `m4_confirmer_dates_cedule`), reports et écart déclaré (`m4_signaler_report`,
  `m4_creer_demande_ecart`), profil météo déclaré par la CLI publique (`opsys.cli`) ;
* M6 : réception de stock (`m6_receptionner_commande`), devis accepté publié sur le bus puis consommé par M6
  (réservation), transfert hors main (`m6_transferer_stock`) ;
* M3 : devis créé (`m3_creer_devis`), complétion M4 et variance M6 publiées sur le bus, consommées par M3.

Aucun secret ; tout est `fictif: true`.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json

from opsys import cli, contexte, evenements, identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True

M3, M4, M6, M9 = "m03-estimation", "m04-field-ops", "m06-material-control", "m09-strategic-intelligence"
ADMIN_CONSOLE = IdentiteAppelante("admin.fictif", "admin", source="console")
ADMIN_APPAREIL = IdentiteAppelante("admin.fictif", "admin")
MARC = IdentiteAppelante("marc.fictif", "employee")
VENDEUR_CONSOLE = IdentiteAppelante("vendeur.fictif", "seller", source="console")
EMPLOYE_CONSOLE = IdentiteAppelante("employe.fictif", "employee", source="console")

HORODATAGE_PLAN = "2026-10-26T12:00:00+00:00"  # l'heure que l'appelant écrit dans les gestes de cédule
RECU_LE = dt.datetime(2026, 10, 26, 14, 0, 0, tzinfo=dt.UTC)  # heure de réception du serveur des gestes d'appareil
LUNDI = "2026-11-02"  # lundi ISO ; le jour 0 de la cédule y est daté
SEL = "sel-m9-producteurs-fictif"
MARQUEUR = {
    "readiness_ok": True,
    "hash_tete_registre": None,
    "horodatage": "2026-10-25T12:00:00+00:00",
    "empreinte": "ab" * 32,
}

# Minimum réaliste inspiré de la fixture de cédule de M4 : trois chantiers (deux proches, un éloigné), deux équipes.
CHANTIERS = (
    ("L-M9-01", "Repentigny", "ravalement", 45742000, -73450000),
    ("L-M9-02", "Le Gardeur", "autre", 45753000, -73468000),
    ("L-M9-03", "Joliette", "ravalement", 46020000, -73440000),
)
DEPOTS = {
    "depot-repentigny": {"latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
    "depot-joliette": {"latitude_microdegres": 46015000, "longitude_microdegres": -73445000},
}
EQUIPES = (("eq-a", "depot-repentigny"), ("eq-b", "depot-joliette"))
SERVICES_PROPRES = [
    {"code": "autre", "libelle": "Autre travail (fictif)"},
    {"code": "extension", "libelle": "Extension (fictif)"},
    {"code": "isolation_thermique", "libelle": "Isolation thermique (fictif)"},
    {"code": "ravalement", "libelle": "Ravalement (fictif)"},
    {"code": "renovation_totale", "libelle": "Rénovation totale (fictif)"},
]
PARAMETRES_CEDULE = {
    "facteur_detour_milliemes": 1300,
    "vitesse_moyenne_kmh": 50,
    "marge_par_trajet_secondes": 600,
    "iterations": 500,
    "cout_non_cedule_m": 500000,
}
DUREES = {"ravalement": 120, "autre": 90, "extension": 150, "isolation_thermique": 100, "renovation_totale": 180}
COMPETENCES = {
    "ravalement": ["revetement"],
    "autre": ["gouttieres"],
    "extension": [],
    "isolation_thermique": [],
    "renovation_totale": [],
}
FENETRE_CLIENT = {"jours": [0], "debut_min": 480, "fin_min": 1020}
METEO_PROFIL = {
    "fuseau": "America/Toronto",
    "services": {
        "ravalement": {
            "seuils": {
                "vent_kmh": {"validation": 25, "blocage": 40},
                "pluie_mm_h": {"blocage": 3},
                "gel_c": {"blocage": 0},
                "verglas": {"blocage": True},
                "chaleur_c": {"blocage": 35},
            }
        },
        "autre": {"seuils": {"vent_kmh": {"blocage": 60}}, "sans_objet": ["pluie", "gel", "verglas", "chaleur"]},
    },
}


# -- installation commune ------------------------------------------------------------------------------------
def installer_base(tmp_path, monkeypatch) -> None:
    """Base SQLite migrée, dossier d'état privé et personnes fictives (admin, vendeur, trois employés)."""
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'm9-producteurs-a.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-12", ["employee"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345", ["employee"])


def capacites_m9(*producteurs: str, departements=None) -> Capacites:
    """Le dispatcher filtré {M9, producteurs…} : le seul chemin par lequel la capture lit un producteur."""
    departements_charges = charger_departements() if departements is None else departements
    return Capacites(
        departements_charges,
        stockage.transaction,
        filtre={M9, *(p for p in producteurs if p in departements_charges)},
        memoire=False,
    )


def capturer(capacites: Capacites, lecture_id: str, arguments: dict, horodatage: str, identite_appelante=ADMIN_CONSOLE):
    """`m9_capturer_producteur` sous l'identité fournie (`None` : un agent, sans identité). Réponse du dispatcher."""
    appel = {"lecture_id": lecture_id, "arguments": arguments, "horodatage": horodatage}
    if identite_appelante is None:
        return capacites.appeler("m9_capturer_producteur", appel)
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler("m9_capturer_producteur", appel)


def lire_capture(capacites: Capacites, index: int, page: int = 0) -> dict:
    """La page `page` de la capture `index`, relue en entier par `m9_lire_capture` (tranches de 4 000 caractères)."""
    texte, depart = "", 0
    while depart is not None:
        with contexte.appele_par_appareil(ADMIN_CONSOLE):
            reponse = capacites.appeler("m9_lire_capture", {"index": index, "page": page, "depart": depart})
        assert reponse["ok"] is True, reponse
        texte += reponse["resultat"]["contenu_json"]
        depart = reponse["resultat"]["prochain_depart"]
    return json.loads(texte)


# -- gestes d'un département (outils réels, transaction complète) --------------------------------------------
@contextlib.contextmanager
def _appareil(identite_appelante, recu_le=RECU_LE):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
            pile.enter_context(
                contexte.receptionne_de(
                    contexte.HorodatageAppareil(
                        appareil="tel-fictif-m9",
                        horodatage_appareil=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
                        recu_le=recu_le,
                    )
                )
            )
        yield


def outils_departement(departement: str) -> dict:
    """`{nom: Outil}` du département, comme le dispatcher les charge (port M9 exclu : aucune lecture de M9 ici)."""
    return {o.nom: o for o in charger_departements()[departement].charger_outils()}


def geste(par_nom: dict, nom: str, arguments: dict, identite_appelante=ADMIN_APPAREIL, recu_le=RECU_LE) -> dict:
    """Un geste d'appareil par le vrai outil ; exige un geste accepté et rend le `resultat` du département."""
    with _appareil(identite_appelante, recu_le):
        reponse = executer_atomique(par_nom[nom], arguments)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, (nom, reponse)
    return reponse["resultat"].get("resultat", reponse["resultat"])


def lire_outil(par_nom: dict, nom: str, arguments: dict, identite_appelante=ADMIN_APPAREIL):
    """Une LECTURE par le vrai outil (liste ou objet) sous l'identité fournie ; rend le `resultat` brut."""
    with _appareil(identite_appelante):
        reponse = executer_atomique(par_nom[nom], arguments)
    assert reponse["ok"] is True, (nom, reponse)
    return reponse["resultat"]


# -- M4 ------------------------------------------------------------------------------------------------------
def _contrat(lead_id: str, ville: str, type_travaux: str) -> dict:
    return {
        "lead_id": lead_id,
        "conversation_id": f"C-{lead_id}",
        "type_travaux": type_travaux,
        "ville": ville,
        "canal": "telephone",
        "contact": {"nom": "Client Fictif"},
        "urgence_declaree": False,
    }


def m4_planifier(
    m4: dict,
    lead_id: str,
    ville: str = "Repentigny",
    type_travaux: str = "ravalement",
    techniciens=("marc.fictif",),
    horodatage: str = HORODATAGE_PLAN,
) -> str:
    """Inscrit un lead et le cédule (`m4_planifier_intervention`) ; rend l'`intervention_id`."""
    resultat = geste(
        m4,
        "m4_planifier_intervention",
        {
            "contrat": _contrat(lead_id, ville, type_travaux),
            "marqueur": {**MARQUEUR, "lead_id": lead_id},
            "horodatage": horodatage,
            "sel": SEL,
            "techniciens_disponibles": list(techniciens),
            "fenetres_disponibles": [{"debut": "2026-11-02T08:00:00-05:00", "fin": "2026-11-02T17:00:00-05:00"}],
        },
    )
    return resultat["intervention_id"]


def m4_alimenter_interventions(m4: dict, nombre: int = 5) -> list[str]:
    """`nombre` interventions planifiées (techniciens Marc et Léa en alternance) ; rend leurs identifiants."""
    return [
        m4_planifier(m4, f"L-M9-I{rang:03d}", techniciens=("lea.fictif" if rang % 3 == 0 else "marc.fictif",))
        for rang in range(nombre)
    ]


def m4_naitre_par_le_bus(m4: dict, chantiers=CHANTIERS) -> dict[str, str]:
    """Interventions « à planifier » nées comme en production : lead qualifié (M1), devis accepté (M3) et matériel prêt
    (M6) publiés sur le bus, livrés à M4 SEUL par le répartiteur réel. Le lead porte un SERVICE (v2), ce qui permet à
    la météo de choisir des règles. Rend `{lead_id: intervention_id}`."""
    taxonomie.enregistrer_services(SERVICES_PROPRES)
    accepte_le = "2026-10-20T10:00:00-04:00"
    for lead_id, ville, service, _, _ in chantiers:
        devis_id = f"DEVIS-{lead_id}"
        evenements.publier(
            "m1.lead_qualifie",
            "m01-front-office",
            {
                "lead": {
                    "schema_version": 2,
                    "lead_id": lead_id,
                    "conversation_id": f"sms-{lead_id}",
                    "contact": {"nom": "Client Fictif", "telephone": "+15145550142"},
                    "service": service,
                    "ville": ville,
                    "urgence_declaree": False,
                    "canal": "texte",
                    "source": "sms",
                },
                "horodatage": HORODATAGE_PLAN,
                "signal_id": f"sms:{lead_id}",
            },
            evenement_id=f"m1-lead-qualifie-{lead_id}",
        )
        evenements.publier(
            "m3.devis_accepte",
            M3,
            {
                "devis_id": devis_id,
                "lead_id": lead_id,
                "chantier_id": None,
                "lignes": [
                    {
                        "reference_ligne": f"{devis_id}-L0",
                        "description": "Travaux (fictif)",
                        "quantite": "1",
                        "unite": "forfait",
                        "prix_unitaire": "100.00",
                        "prix_ligne": "100.00",
                        "reference_besoin_materiau": None,
                    }
                ],
                "cout_total": "80.00",
                "prix_total": "100.00",
                "taux_marge": "0.25",
                "horodatage_acceptation": accepte_le,
            },
            evenement_id=f"m3-devis-accepte-{devis_id}",
        )
        pret = {
            "evenement_id": f"m6-materiel-pret-{devis_id}-1",
            "devis_id": devis_id,
            "chantier_id": None,
            "revision": 1,
            "statut": "pret",
            "reservation_active": True,
            "declencheur": "devis_accepte",
            "horodatage": "2026-10-20T12:00:00-04:00",
            "lignes": [
                {
                    "materiau_id": "gouttiere-fictive",
                    "unite": "pi",
                    "quantite_besoin": "10",
                    "quantite_reservee": "10",
                    "quantite_manquante": "0",
                }
            ],
            "lignes_manquantes": [],
        }
        evenements.publier("m6.materiel_pret", M6, pret, evenement_id=pret["evenement_id"])
    debut = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
    livres = 0
    for tour in range(4):
        resume = evenements.repartir(
            {M4: charger_departements()[M4]}, maintenant=(debut + dt.timedelta(seconds=100 * tour)).isoformat()
        )
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
        livres += resume["livres"]
    assert livres == 2 * len(chantiers), livres
    liste = lire_outil(m4, "m4_lister_interventions", {"statut": "a_planifier"})
    par_lead = {ligne["lead_id"]: ligne["intervention_id"] for ligne in liste}
    assert sorted(par_lead) == sorted(c[0] for c in chantiers), par_lead
    return par_lead


def m4_alimenter_cedule(m4: dict, dossier=None) -> dict:
    """Trois chantiers aux positions confirmées, une cédule proposée puis appliquée, enfin DATÉE au lundi `LUNDI`.

    Sans `dossier` : interventions de `m4_planifier_intervention` (leads v1, type de travaux) et équipes fournies en
    argument de `m4_proposer_cedule`. Avec `dossier` (celui d'`OPSYS_HOME`) : interventions nées du bus avec un SERVICE
    (météo exploitable) et profil des équipes déclaré par la CLI publique. Rend
    `{interventions: {lead_id: intervention_id}, plan_id, confirmation}`."""
    arguments = {"horodatage": HORODATAGE_PLAN}
    if dossier is not None:
        declarer_equipes(dossier)
        interventions = m4_naitre_par_le_bus(m4)
    else:
        interventions = {
            lead_id: m4_planifier(m4, lead_id, ville, type_travaux, techniciens=[e for e, _ in EQUIPES])
            for lead_id, ville, type_travaux, _, _ in CHANTIERS
        }
        arguments |= {
            "equipes": [
                {
                    "id": equipe,
                    "competences": ["gouttieres", "revetement"],
                    "depot": {"id": depot, **DEPOTS[depot]},
                    "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
                }
                for equipe, depot in EQUIPES
            ],
            "durees_par_type_travaux": dict(DUREES),
            "competences_par_type_travaux": {cle: list(valeur) for cle, valeur in COMPETENCES.items()},
            "chantiers": [
                {"intervention_id": iid, "fenetre": dict(FENETRE_CLIENT), "creneau_fige": None}
                for _, iid in sorted(interventions.items())
            ],
            "parametres": dict(PARAMETRES_CEDULE),
        }
    for lead_id, ville, _, latitude, longitude in CHANTIERS:
        geste(
            m4,
            "m4_confirmer_localisation",
            {
                "chantier_id": lead_id,
                "action": "confirmee",
                "horodatage": HORODATAGE_PLAN,
                "confirme_par": "admin.fictif",
                "adresse": {"numero_municipal": "10", "odonyme": "rue Fictive", "municipalite": ville},
                "source": "manuel",
                "motif": "",
                "latitude_microdegres": latitude,
                "longitude_microdegres": longitude,
            },
        )
    plan_id = geste(m4, "m4_proposer_cedule", arguments)["plan_id"]
    geste(
        m4, "m4_appliquer_cedule", {"plan_id": plan_id, "horodatage": HORODATAGE_PLAN, "confirme_par": "admin.fictif"}
    )
    confirmation = geste(
        m4, "m4_confirmer_dates_cedule", {"plan_id": plan_id, "calendrier": {"0": LUNDI}, "revision_attendue": 0}
    )
    return {"interventions": interventions, "plan_id": plan_id, "confirmation": confirmation}


def m4_alimenter_retards(m4: dict) -> dict:
    """Trois interventions : un report (client absent) signalé par Marc, un report de l'admin, un écart déclaré par
    Marc. Heures de RÉCEPTION du serveur : 2026-10-24 08:00Z, 2026-10-25 07:00Z et 2026-10-25 12:00Z. Rend les
    identifiants (`a`, `b`, `c`) et `demande`."""
    a = m4_planifier(m4, "L-M9-R-A", techniciens=("marc.fictif",))
    b = m4_planifier(m4, "L-M9-R-B", techniciens=("marc.fictif",))
    c = m4_planifier(m4, "L-M9-R-C", techniciens=("lea.fictif",))
    absurde = "2000-01-01T00:00:00+00:00"  # l'horloge de l'appareil ne compte pas : seule la réception fait foi
    recu = dt.datetime.fromisoformat
    geste(
        m4,
        "m4_signaler_report",
        {"intervention_id": a, "motif": "client_absent", "horodatage": absurde},
        MARC,
        recu("2026-10-24T08:00:00+00:00"),
    )
    geste(
        m4,
        "m4_signaler_report",
        {"intervention_id": c, "motif": "decision_admin", "horodatage": absurde},
        ADMIN_APPAREIL,
        recu("2026-10-25T07:00:00+00:00"),
    )
    demande = geste(
        m4,
        "m4_creer_demande_ecart",
        {
            "intervention_id": b,
            "version_prevue": {"duree_minutes": 60, "perimetre": "perimetre prevu", "materiaux": ["m1"]},
            "version_declaree": {"duree_minutes": 90, "perimetre": "perimetre declare", "materiaux": ["m2"]},
            "horodatage": absurde,
        },
        MARC,
        recu("2026-10-25T12:00:00+00:00"),
    )
    return {"a": a, "b": b, "c": c, "demande": demande["demande_id"]}


def declarer_equipes(dossier) -> None:
    """Profil des équipes de l'entreprise, par la CLI publique (`opsys-metier equipes declarer`) : deux équipes, deux
    dépôts, un quart le jour 0, des durées par service."""
    import yaml

    profil = {
        "liste": [
            {
                "id": equipe,
                "membres": [membre],
                "competences": ["gouttieres", "revetement"],
                "depot": {"id": depot, **DEPOTS[depot]},
                "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
            }
            for (equipe, depot), membre in zip(EQUIPES, ("marc.fictif", "lea.fictif"), strict=True)
        ],
        "services": {
            service: {"duree_min": DUREES[service], "competences": COMPETENCES[service]} for service in DUREES
        },
        "cedule": dict(PARAMETRES_CEDULE),
        "fenetre_par_defaut": dict(FENETRE_CLIENT),
    }
    taxonomie.enregistrer_services(SERVICES_PROPRES)
    fichier = dossier / "equipes-declare.yaml"
    fichier.write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    assert cli.main(["equipes", "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0


def declarer_meteo(dossier, profil: dict | None = None) -> None:
    """Services propres puis profil météo de l'entreprise, par la CLI publique (`opsys-metier meteo declarer`).

    Aucun fournisseur n'est ouvert (clé `fournisseur` absente) : aucune requête réseau ne part jamais."""
    import yaml

    taxonomie.enregistrer_services(SERVICES_PROPRES)
    fichier = dossier / "meteo-declare.yaml"
    fichier.write_text(yaml.safe_dump(METEO_PROFIL if profil is None else profil, allow_unicode=True), encoding="utf-8")
    assert cli.main(["meteo", "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0


# -- M6 ------------------------------------------------------------------------------------------------------
GOUTTIERE, VIS = "gouttiere-5po", "vis-inox"


def m6_recevoir(m6: dict, materiau_id: str, quantite: float, po_id: str) -> dict:
    """Une réception de stock (`m6_receptionner_commande`, PO éphémère) : du stock théorique entre."""
    return geste(
        m6,
        "m6_receptionner_commande",
        {
            "bon_demande": {
                "po_id": po_id,
                "chantier_id": "CH-DEPOT-FICT",
                "horodatage": "2026-10-01T00:00:00Z",
                "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": quantite}],
            },
            "reception_po": {
                "po_id": po_id,
                "chantier_id": "CH-DEPOT-FICT",
                "horodatage": "2026-10-05T09:00:00-04:00",
                "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": quantite}],
            },
            "catalogue_materiaux": {
                "version": "v1-fictif",
                "unite_monetaire": "CAD",
                "postes": {materiau_id: {"cout_unitaire": 5.0, "libelle": materiau_id}},
            },
        },
    )


def devis_accepte(devis_id: str, chantier_id: str, gouttiere: str = "100", vis: str = "20") -> dict:
    """Charge `m3.devis_accepte` (contrat du bus) dont les lignes portent un besoin de matériau."""
    lignes = [
        {
            "reference_ligne": f"{devis_id}-L{rang}",
            "description": "ligne fictive",
            "quantite": quantite,
            "unite": unite,
            "prix_unitaire": "10.00",
            "prix_ligne": "10.00",
            "reference_besoin_materiau": materiau,
        }
        for rang, (materiau, quantite, unite) in enumerate([(GOUTTIERE, gouttiere, "pi"), (VIS, vis, "boite")])
    ]
    return {
        "devis_id": devis_id,
        "lead_id": "lead-fictif",
        "chantier_id": chantier_id,
        "lignes": lignes,
        "cout_total": "100.00",
        "prix_total": "135.00",
        "taux_marge": "0.35",
        "horodatage_acceptation": "2026-09-30T10:00:00-04:00",
    }


def m6_reserver_par_le_bus(devis_id: str, chantier_id: str, gouttiere: str = "100", vis: str = "20") -> dict:
    """Publie `m3.devis_accepte` puis laisse le répartiteur réel le livrer à M6 seul (réservation + prévu)."""
    evenements.publier(
        "m3.devis_accepte",
        M3,
        devis_accepte(devis_id, chantier_id, gouttiere, vis),
        evenement_id=f"m3-devis-accepte-{devis_id}",
    )
    resume = evenements.repartir({M6: charger_departements()[M6]}, maintenant="2026-10-06T12:00:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0 and resume["livres"] >= 1, resume
    return resume


def m6_alimenter_stock(m6: dict) -> dict:
    """Stock réel et réservé : 150 gouttières reçues et 100 réservées par un devis accepté, 25 vis reçues et 20
    réservées ; 10 gouttières ensuite mises au rebut (hors main). Disponible attendu : gouttière 150-10-100 = 40 en
    main-réservé (en main 140), vis 25-20 = 5."""
    m6_recevoir(m6, GOUTTIERE, 150.0, "PO-M9-1")
    m6_recevoir(m6, VIS, 25.0, "PO-M9-2")
    m6_reserver_par_le_bus("DEVIS-M9-1", "CH-M9-1")
    geste(
        m6,
        "m6_transferer_stock",
        {
            "transfert_id": "TR-M9-1",
            "materiau_id": GOUTTIERE,
            "quantite": 10.0,
            "de": {"type": "inconnu"},
            "vers": {"type": "rebut"},
            "motif": "bris fictif",
            "horodatage": "2026-10-07T09:00:00-04:00",
        },
    )
    return {"gouttiere": GOUTTIERE, "vis": VIS}


# -- M3 ------------------------------------------------------------------------------------------------------
DEVIS_M3 = "M3-DEVIS-M9-001"
WCT_M3 = "wct-m9-001"


def m3_creer_devis(m3: dict, devis_id: str = DEVIS_M3, lead_id: str = "lead-m9-001") -> None:
    """Un devis brouillon (`m3_creer_devis`) auquel les complétions M4 se rattachent."""
    geste(
        m3,
        "m3_creer_devis",
        {
            "devis_id": devis_id,
            "lead_id": lead_id,
            "chantier_id": None,
            "lignes": [
                {
                    "description": "Gouttière alu 5 po",
                    "quantite": "30",
                    "unite": "pi_lin",
                    "cout_unitaire": "10.00",
                    "reference_besoin_materiau": None,
                }
            ],
            "taux_marge": "0.20",
            "horodatage": "2026-09-01T09:00:00-04:00",
        },
        ADMIN_APPAREIL,
    )


def charge_wct(
    wct_id: str = WCT_M3,
    devis_id: str | None = DEVIS_M3,
    lead_id: str = "lead-m9-001",
    completion: str = "2026-09-28T14:00:00-04:00",
    duree: int = 120,
) -> dict:
    """Charge `m4.travaux_termines` (contrat du bus) : ce que M4 publie à la complétion d'un chantier."""
    return {
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "lead_id": lead_id,
        "technicien_id": "tech-m9",
        "horodatage_completion": completion,
        "fix_gps_completion": {},
        "duree_reelle_minutes": duree,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M3"],
        "devis_id": devis_id,
        "statut": "completed_verified",
    }


def charge_variance(wct_id: str = WCT_M3, completion: str = "2026-09-28T15:00:00-04:00") -> dict:
    """Charge `m6.variance_chantier` au statut `evaluee` : une ligne de matériau, 7 % de dépassement."""
    return {
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "chantier_id": f"chantier-{wct_id}",
        "statut_variance": "evaluee",
        "signal_critique": False,
        "seuil_pourcentage": 10.0,
        "horodatage_completion": completion,
        "lignes": [
            {
                "materiau": "gouttiere_alu",
                "unite": "pi_lin",
                "quantite_prevue": "30",
                "quantite_reelle": "32",
                "ecart_pourcentage": "0.0667",
                "critique": False,
            }
        ],
        "evenement_id": f"m6-variance-{wct_id}-evaluee",
    }


def m3_alimenter_ecarts(
    m3: dict, completions=(("wct-m9-001", "2026-09-28T14:00:00-04:00"), ("wct-m9-002", "2026-10-05T10:30:00-04:00"))
) -> list[str]:
    """Un devis, puis une complétion (`m4.travaux_termines`) et une variance (`m6.variance_chantier`) par WCT,
    publiées sur le bus et livrées à M3 SEUL par le répartiteur réel. Rend les `wct_id`."""
    m3_creer_devis(m3)
    for wct_id, completion in completions:
        charge = charge_wct(wct_id, completion=completion)
        evenements.publier("m4.travaux_termines", M4, charge, evenement_id=wct_id)
        variance = charge_variance(wct_id, completion=completion)
        evenements.publier("m6.variance_chantier", M6, variance, evenement_id=variance["evenement_id"])
    resume = evenements.repartir({M3: charger_departements()[M3]})
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0 and resume["traites"] == 2 * len(completions), resume
    return [wct_id for wct_id, _ in completions]


# -- variantes pour les limites (troncatures, révisions) ---------------------------------------------------------
def m4_reconfirmer_dates(m4: dict, plan_id: str, revision_attendue: int, jour: str, recu_le=RECU_LE) -> dict:
    """Corrige la date du jour 0 d'un plan déjà daté : le producteur écrit une NOUVELLE révision (append-only)."""
    return geste(
        m4,
        "m4_confirmer_dates_cedule",
        {"plan_id": plan_id, "calendrier": {"0": jour}, "revision_attendue": revision_attendue},
        recu_le=recu_le,
    )


def m4_alimenter_reports(m4: dict, nombre: int) -> list[str]:
    """`nombre` interventions reportées par l'admin, une heure de réception par report (au-delà de la limite d'affichage
    de huit lignes par liste de `m4_lire_retards_incidents`)."""
    ids = []
    for rang in range(nombre):
        iid = m4_planifier(m4, f"L-M9-RP{rang:02d}", techniciens=("marc.fictif",))
        geste(
            m4,
            "m4_signaler_report",
            {"intervention_id": iid, "motif": "meteo", "horodatage": HORODATAGE_PLAN},
            ADMIN_APPAREIL,
            dt.datetime(2026, 10, 24, 6 + rang, 0, 0, tzinfo=dt.UTC),
        )
        ids.append(iid)
    return ids


def m6_recevoir_articles(m6: dict, nombre: int) -> list[str]:
    """`nombre` articles distincts reçus en stock (au-delà de la page de quinze articles de `m6_lire_disponibilite`)."""
    ids = [f"article-m9-{rang:02d}" for rang in range(nombre)]
    for rang, materiau_id in enumerate(ids):
        m6_recevoir(m6, materiau_id, 10.0 + rang, f"PO-M9-A{rang:02d}")
    return ids
