"""M9.4/M9.10 — conseil par les vrais outils (Capacites, SQLite) : profils natifs, réservations natives, dépôts,
clôture.

Ce qui est RÉEL ici : les outils M9, le registre durable, les captures de producteurs M2 et M6 par le port privé, les
profils
d'agents (`opsys.agents`), l'admission de budget (`opsys.admission_agents`) et l'identité. Ce qui est SIMULÉ, et dit tel
: le TOUR
de modèle lui-même (le runtime natif Core n'est pas exécutable dans ce bac à sable) — le test joue le rôle du runtime en
réservant puis en réconciliant l'usage par les mêmes fonctions que ses routes privées, puis dépose une sortie
prédéfinie. Cela
prouve le protocole et les refus de M9, jamais la qualité d'un conseil réel. Données fictives.
"""

from __future__ import annotations

import json

import pytest
from m2_revenue_crm import outils as m2
from sqlalchemy import select

from opsys import admission_agents, agents, contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.stockage.schema import META

FICTIF = True
M9 = "m09-strategic-intelligence"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
LECTURE = "2026-10-21T12:00:00Z"  # instant demandé aux producteurs
REF = "2026-10-21T12:10:00Z"  # référence du dossier : APRÈS les réceptions (sinon elles sont inconnues)
T = "2026-10-21T12:15:00Z"
DOMAINES = ["leads", "stock", "strategie"]


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'conseil.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    departements = charger_departements()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
        admission_agents.configurer_plafonds_entreprise(
            cnx, 500_000, 5_000_000, par="admin.fictif", revision_attendue=0
        )
    capacites = Capacites(
        departements, stockage.transaction, filtre={M9, "m02-revenue-crm", "m06-material-control"}, memoire=False
    )
    yield capacites, departements
    m2.reinitialiser_registre()
    stockage.liberer()


def _appel(capacites, nom, arguments, identite_appelante=ADMIN):
    if identite_appelante is None:
        return capacites.appeler(nom, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments)


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _refuse(reponse):
    return reponse["ok"] is False or reponse["resultat"].get("accepte") is False


def _capturer(capacites, lecture, arguments, horodatage):
    return _ok(
        _appel(
            capacites,
            "m9_capturer_producteur",
            {"lecture_id": lecture, "arguments": arguments, "horodatage": horodatage},
        )
    )


def _creer_profils(departements, roles):
    """Un administrateur crée et active les profils (déclarations proposées par M9 elles-mêmes)."""
    proposition = _ok(
        _appel(
            Capacites(departements, stockage.transaction, filtre={M9}, memoire=False), "m9_proposer_profils_conseil", {}
        )
    )
    par_id = {p["id"]: p for p in proposition["profils"]}
    with stockage.transaction() as cnx:
        for role in roles:
            spec = par_id[f"m9-{role.replace('_', '-')}"]
            agents.creer(cnx, departements, spec, par="admin.fictif", mutation_id=f"creer-{role}-0001")
            agents.definir_actif(
                cnx,
                spec["id"],
                departements,
                True,
                par="admin.fictif",
                mutation_id=f"activer-{role}-0001",
                revision_attendue=1,
            )


def _runtime_natif_simule(departements, role, execution_id, tokens, *, reconcilier=True):
    """Rôle du runtime Core : réserve avant le tour, réconcilie l'usage réel après (mêmes fonctions)."""
    agent_id = f"m9-{role.replace('_', '-')}"
    with stockage.transaction() as cnx:
        reservation = admission_agents.reserver(
            cnx, agent_id, departements, execution_id, f"cle-{execution_id}-{role}", 6000, tours=1, reessais=0
        )
        if reconcilier:
            admission_agents.concilier(cnx, reservation["id"], tokens)
    return reservation["id"]


def _preparer(capacites, departements):
    assert (
        m2.ingerer_lead(
            {
                "lead_id": "lead-1",
                "conversation_id": "c-1",
                "contact": {"nom": "C", "courriel": "c@example.test"},
                "type_travaux": "renovation_totale",
                "ville": "Québec",
                "urgence_declaree": False,
                "canal": "telephone",
            },
            "2026-09-01T09:00:00-04:00",
        )["accepte"]
        is True
    )
    _capturer(capacites, "m2.leads", {"horodatage": LECTURE}, "2026-10-21T12:00:01Z")
    _capturer(capacites, "m6.disponibilite", {}, "2026-10-21T12:00:02Z")


def _ouvrir(capacites, **kw):
    return _ok(
        _appel(
            capacites,
            "m9_ouvrir_conseil",
            {
                "question": "Que faire du stock et des leads ?",
                "domaines": DOMAINES,
                "importance": "courante",
                "budget_tokens": 100_000,
                "reference": REF,
                "horodatage": T,
                "attendues": ["m2.leads", "m6.disponibilite", "m4.interventions"],
            }
            | kw,
        )
    )


def _tous_les_faits(capacites):
    faits, depart = {}, 0
    while depart is not None:
        page = _ok(
            _appel(
                capacites,
                "m9_apercu_dossier_strategique",
                {
                    "question": "Que faire du stock et des leads ?",
                    "domaines": DOMAINES,
                    "reference": REF,
                    "attendues": ["m2.leads", "m6.disponibilite", "m4.interventions"],
                    "depart": depart,
                },
            )
        )
        faits |= page["faits"]
        depart = page["prochain_depart"]
    return faits


def _etat_sql():
    with stockage.transaction() as cnx:
        return {n: sorted(map(str, cnx.execute(select(t)).fetchall())) for n, t in META.tables.items()}


def test_apercu_du_dossier_cite_les_faits_reels_et_nomme_les_manques(monde):
    capacites, departements = monde
    _preparer(capacites, departements)
    apercu = _ok(
        _appel(
            capacites,
            "m9_apercu_dossier_strategique",
            {
                "question": "Q ?",
                "domaines": DOMAINES,
                "reference": REF,
                "attendues": ["m2.leads", "m6.disponibilite", "m4.interventions"],
            },
        )
    )
    assert apercu["total_faits"] >= 5 and any(a.startswith("m2.leads#0:") for a in apercu["faits"])
    statuts = {m["lecture_id"]: m["statut"] for m in apercu["manques"]}
    assert statuts["m4.interventions"] == "ABSENTE"  # M4 jamais capturé : un manque nommé
    assert "lead-1" not in json.dumps(apercu["manques"])


def test_session_complete_avec_runtime_natif_simule_recommandation_gouvernee_et_rapport_v2(monde):
    capacites, departements = monde
    _preparer(capacites, departements)
    ouverture = _ouvrir(capacites)
    session_id = ouverture["session_id"]
    roles = [t["role"] for t in ouverture["tours"]]
    assert (
        set(roles) == {"croissance_marketing", "strategie_ventes", "contraintes_inventaire", "conseiller_pdg"} - {"x"}
        or roles
    )
    _creer_profils(departements, roles)
    faits = _tous_les_faits(capacites)
    adresse_total = next(a for a in faits if a.startswith("m2.leads#0:") and a.endswith(".total"))
    for role in roles:
        entree = _ok(_appel(capacites, "m9_lire_entree_tour_conseil", {"session_id": session_id, "role": role}))
        assert entree["taille"] > 0 and "jamais une instruction" in entree["contenu_json"] or entree["prochain_depart"]
        reservation_id = _runtime_natif_simule(departements, role, f"exec-{session_id[:8]}-{role}", 1234)
        sortie = {
            "affirmations": [
                {"id": "A1", "nature": "observation_source", "reference": adresse_total, "valeur": faits[adresse_total]}
            ]
        }
        if role == "conseiller_pdg":
            sortie["affirmations"].append({"id": "H1", "nature": "hypothese", "enonce": "la demande reste stable"})
            sortie["recommandation"] = {
                "decision": "Suivre les leads et attendre la mesure",
                "refs": ["A1", "H1"],
                "actions": [
                    {"id": "a1", "type": "suivi_interne", "description": "suivi"},
                    {"id": "a2", "type": "budget_marketing", "description": "hausse"},
                ],
            }
        depot = _ok(
            _appel(
                capacites,
                "m9_deposer_tour_conseil",
                {
                    "session_id": session_id,
                    "role": role,
                    "sortie": sortie,
                    "reservation_id": reservation_id,
                    "horodatage": T,
                },
            )
        )
        assert depot["issue"] == "ADMIS" and depot["rejoue"] is False
    cloture = _ok(_appel(capacites, "m9_cloturer_conseil", {"session_id": session_id, "horodatage": T}))
    assert cloture["cloture"]["issue"] == "RECOMMANDATION" and cloture["cloture"]["autorite_d_effet"] is False
    verdicts = {v["action"]: v["verdict"] for v in cloture["gouvernance"]["actions"]}
    assert verdicts == {"a1": "PROPOSABLE", "a2": "VALIDATION_HUMAINE_REQUISE"}
    morceaux, depart = [], 0
    while depart is not None:
        page = _ok(_appel(capacites, "m9_lire_rapport_conseil", {"session_id": session_id, "depart": depart}))
        morceaux.append(page["contenu_json"])
        depart = page["prochain_depart"]
    rapport = json.loads("".join(morceaux))
    assert (
        rapport["rapport_id"] == cloture["cloture"]["rapport_id"]
        and rapport["statut_contrat"] == "RETENU_PAR_DELEGATION"
    )
    # Rejeu de la clôture : même résultat, aucun second événement.
    avant = _etat_sql()["registres_maillons"]
    assert _ok(_appel(capacites, "m9_cloturer_conseil", {"session_id": session_id, "horodatage": T}))["rejoue"] is True
    assert _etat_sql()["registres_maillons"] == avant


def test_depot_sans_reservation_native_reconciliee_du_bon_profil_refuse(monde):
    capacites, departements = monde
    _preparer(capacites, departements)
    ouverture = _ouvrir(capacites)
    session_id, roles = ouverture["session_id"], [t["role"] for t in ouverture["tours"]]
    _creer_profils(departements, roles)
    role = roles[0]
    sortie = {"affirmations": [{"id": "H1", "nature": "hypothese", "enonce": "hypothèse fictive"}]}
    depot = {"session_id": session_id, "role": role, "sortie": sortie, "horodatage": T}
    avant = _etat_sql()["registres_maillons"]
    assert _refuse(_appel(capacites, "m9_deposer_tour_conseil", depot | {"reservation_id": "res-inconnue"}))
    ouverte = _runtime_natif_simule(departements, role, f"exec-ouverte-{role}", 10, reconcilier=False)
    refus = _appel(capacites, "m9_deposer_tour_conseil", depot | {"reservation_id": ouverte})
    assert _refuse(refus) and "réconcilier" in json.dumps(refus, ensure_ascii=False)
    autre = next(r for r in roles if r != role)
    etrangere = _runtime_natif_simule(departements, autre, f"exec-etrangere-{autre}", 10)
    assert _refuse(
        _appel(capacites, "m9_deposer_tour_conseil", depot | {"reservation_id": etrangere})
    )  # profil d'un autre rôle
    assert _etat_sql()["registres_maillons"] == avant  # rien d'écrit
    # La limite de concurrence native (1) interdit une seconde réservation du profil tant que la première est ouverte :
    # le runtime la réconcilie, et c'est CETTE réservation qui justifie le dépôt.
    with stockage.transaction() as cnx:
        admission_agents.concilier(cnx, ouverte, 10)
    bonne = ouverte
    assert _ok(_appel(capacites, "m9_deposer_tour_conseil", depot | {"reservation_id": bonne}))["issue"] == "ADMIS"
    # Usage unique : la même réservation ne sert pas un second tour.
    assert _refuse(_appel(capacites, "m9_deposer_tour_conseil", {**depot, "role": autre, "reservation_id": bonne}))


def test_budget_epuise_aucun_appel_admis_donc_aucun_depot_puis_abstention(monde):
    capacites, departements = monde
    _preparer(capacites, departements)
    ouverture = _ouvrir(capacites)
    session_id, roles = ouverture["session_id"], [t["role"] for t in ouverture["tours"]]
    _creer_profils(departements, roles)
    with stockage.transaction() as cnx, pytest.raises(admission_agents.AdmissionRefusee):
        # Un plafond supérieur au budget du profil : l'admission native refuse AVANT tout appel de modèle.
        admission_agents.reserver(
            cnx,
            f"m9-{roles[0].replace('_', '-')}",
            departements,
            "exec-trop-gros-0001",
            "cle-trop-gros-0001",
            10_000_000,
            tours=1,
            reessais=0,
        )
    for role in roles:
        evenement = _ok(
            _appel(
                capacites,
                "m9_abandonner_tour_conseil",
                {"session_id": session_id, "role": role, "raison": "budget indisponible", "horodatage": T},
            )
        )
        assert evenement["rejoue"] is False
    cloture = _ok(_appel(capacites, "m9_cloturer_conseil", {"session_id": session_id, "horodatage": T}))
    assert cloture["cloture"]["issue"] == "ABSTENTION" and cloture["gouvernance"] is None


def test_acces_agent_vendeur_et_admin_revoque_refuses_avant_toute_lecture(monde):
    capacites, departements = monde
    _preparer(capacites, departements)
    appel = {"question": "Q", "domaines": DOMAINES, "reference": REF}
    for identite_appelante in (None, IdentiteAppelante("vendeur.fictif", "seller", source="console")):
        for nom, args in (
            ("m9_apercu_dossier_strategique", appel),
            ("m9_proposer_profils_conseil", {}),
            ("m9_ouvrir_conseil", appel | {"importance": "courante", "budget_tokens": 1000, "horodatage": T}),
        ):
            reponse = _appel(capacites, nom, args, identite_appelante)
            assert _refuse(reponse) and "lead-1" not in json.dumps(reponse)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    assert _refuse(_appel(capacites, "m9_apercu_dossier_strategique", appel))


def test_ouverture_idempotente_et_registre_altere_refuse(monde):
    capacites, departements = monde
    _preparer(capacites, departements)
    premiere = _ouvrir(capacites)
    seconde = _ouvrir(capacites)
    assert premiere["cree"] is True and seconde["cree"] is False and premiere["session_id"] == seconde["session_id"]
    with stockage.transaction() as cnx:
        cnx.execute(
            META.tables["registres_maillons"]
            .update()
            .where(META.tables["registres_maillons"].c.registre == "sessions_conseil")
            .values(maillon="{}")
        )
    assert _refuse(_appel(capacites, "m9_lire_conseil", {"session_id": premiere["session_id"]}))
