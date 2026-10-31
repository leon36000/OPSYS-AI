"""M9.24 — les six parcours de bout en bout du cahier de direction M9, avec de VRAIS producteurs (fictif).

Chaque parcours monte un monde par les outils publics et le VRAI bus des départements (bancs `m9_producteurs_a.py`,
`m9_producteurs_b.py` et le monde de `test_m9_graphe_reel.py`, non modifiés), capture leurs lectures par
`m9_capturer_producteur` (port privé, admin console) et appelle les outils M9 par le VRAI dispatcher `Capacites`.

Ce qui est RÉEL : départements M1, M2, M3, M4, M5, M6, M7, M8, M10 (outils, bus, registres durables SQLite), captures,
outils M9, registres chaînés, file d'approbation native, profils d'agents et admission native de budget.
Ce qui est SIMULÉ, et seulement cela : le TOUR DE MODÈLE du conseil. Le runtime Core n'est pas exécutable dans ce bac à
sable ; le test joue son rôle (réservation puis réconciliation par les mêmes fonctions que ses routes privées) et dépose
une sortie PRÉDÉFINIE qui cite des faits réels du dossier. Cela prouve le protocole et les refus de M9, jamais la
qualité d'un conseil.

Règles vérifiées partout : aucun chiffre produit par un modèle (les seuls nombres viennent des producteurs ou d'un
calcul déterministe de M9 sur une base citée), fail-closed, une lecture absente est NOMMÉE et jamais remplie, M9 ne
décide rien et n'exécute aucune action. Données fictives (`fictif: true`).

Ce qui MANQUE chez un producteur, prouvé et nommé dans les parcours (jamais comblé par M9) :
* M7 : aucune dépense publicitaire (`cout_ads_cad` nul) ni instant métier : pas de base « budget marketing » ;
* M4 : aucune capacité d'équipe (jours-personnes) ; `team_capacity` reste à définir par le propriétaire ;
* M2 : la ville de chaque lead, aucun agrégat par ville ; M5 : rentabilité sans ville ni instant métier ;
* M1 : le digest est un TEXTE ; une plainte ouverte n'y est qu'une phrase, aucun champ structuré : aucune règle de
  risque de réputation n'est ajoutée au radar (M9 ne lit pas une phrase pour en tirer un risque).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import m2_revenue_crm.outils as m2_outils
import pytest
from m9_strategic_intelligence import conseil, risques

from opsys import admission_agents, agents, approbations, contexte, identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import charger_departements

_TESTS = Path(__file__).resolve().parent


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, _TESTS / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


G = _charger("test_m9_graphe_reel")
A, B = G.A, G.B

FICTIF = True
M9 = B.M9
M1, M2, M3, M4, M5, M6, M7, M8, M10 = (
    B.M1, G.M2, G.M3, G.M4, B.M5, G.M6, B.M7, B.M8, B.M10,
)  # fmt: skip
ADMIN = B.ADMIN
TOR = "America/Toronto"
REF = "2026-10-28T13:00:00Z"  # référence des dossiers : après toutes les captures
T = "2026-10-28T13:15:00Z"  # instant des gestes M9 (conseil, plans, expériences)
FIN_SEMAINE = "2026-11-03T12:00:00Z"  # connaissance après la semaine du 26 octobre au 1er novembre (Toronto)
IDS_DIRECTION = [
    "resume", "revenus_cash_marge", "pipeline_ventes", "estimations_soumissions", "production_cedule",
    "inventaire_fournisseurs", "marketing_visibilite", "clients_satisfaction", "risques", "opportunites",
    "ce_qui_a_fonctionne", "ce_qui_a_echoue", "lecons_apprises", "decisions_a_prendre", "plan_semaine_suivante",
    "objectifs_mesurables", "actions_par_departement", "previsions_4_semaines", "previsions_13_semaines",
    "recommandations",
]  # fmt: skip


# -- socle commun --------------------------------------------------------------------------------------------------
@pytest.fixture
def nettoyage(tmp_path, monkeypatch):
    """Profil d'entreprise privé (`OPSYS_HOME`) ; à la fin, registres M1/M2 en mémoire et moteurs libérés."""
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    yield tmp_path
    m2_outils.reinitialiser_registre()
    B.desinstaller_base()


def _installer(tmp_path, monkeypatch) -> None:
    """Base migrée et personnes fictives du banc B, plus les techniciens de M4 et le registre durable de M2."""
    B.installer_base(tmp_path, monkeypatch)
    m2_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        for personne, nom, secret in (
            ("marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234"),
            ("lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345"),
        ):
            identite.creer_personne(cnx, personne, nom, secret, ["employee"])


def appel(cap, nom, arguments, qui=ADMIN):
    if qui is None:
        return cap.appeler(nom, arguments)
    with contexte.appele_par_appareil(qui):
        return cap.appeler(nom, arguments)


def ok(reponse) -> dict:
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def refuse(reponse, code: str | None = None) -> bool:
    echec = reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    return echec and (code is None or code in json.dumps(reponse, ensure_ascii=False))


def capturer(cap, lecture: str, arguments: dict, recu: str) -> dict:
    reponse = B.capturer(cap, ADMIN, lecture, arguments, recu)
    capture = reponse["resultat"]["capture"]
    assert reponse["ok"] is True and capture["verdict"] == "ACCEPTEE" and capture["complete"] is True, reponse
    return capture


def faits_du_dossier(cap, *, question="Dossier de direction", domaines=("strategie",), attendues=None) -> dict:
    """Tous les faits citables du dossier à `REF`, relus page par page (adresse -> texte exact)."""
    faits, depart = {}, 0
    while depart is not None:
        arguments = {"question": question, "domaines": list(domaines), "reference": REF, "depart": depart}
        if attendues is not None:
            arguments["attendues"] = list(attendues)
        page = ok(appel(cap, "m9_apercu_dossier_strategique", arguments))
        faits.update(page["faits"])
        depart = page["prochain_depart"]
    return faits


def adresse(faits: dict, lecture: str, suffixe: str) -> str:
    (trouvee,) = [a for a in faits if a.startswith(f"{lecture}#") and a.endswith(suffixe)]
    return trouvee


def lire_tout(cap, outil: str, arguments: dict) -> tuple[dict, int]:
    morceaux, depart = [], 0
    while depart is not None:
        page = ok(appel(cap, outil, {**arguments, "depart": depart}))
        morceaux.append(page["contenu_json"])
        depart = page["prochain_depart"]
    return json.loads("".join(morceaux)), len(morceaux)


def revue_hebdomadaire(cap) -> tuple[dict, int]:
    periode = {"granularite": "hebdomadaire", "ancre": "2026-10-28", "fuseau": TOR, "connaissance": FIN_SEMAINE}
    return lire_tout(cap, "m9_apercu_revue", periode)


def cles(objet) -> set[str]:
    if isinstance(objet, dict):
        return set(objet) | {c for v in objet.values() for c in cles(v)}
    if isinstance(objet, list):
        return {c for v in objet for c in cles(v)}
    return set()


def leads_par_le_bus(prefixe: str, nombre: int, ville: str) -> list[str]:
    """`nombre` leads qualifiés publiés par M1 (`m1.lead_qualifie`) et livrés à M2 SEUL par le répartiteur réel."""
    ids = []
    for rang in range(nombre):
        lead_id = f"{prefixe}-{rang:02d}"
        charge = B.charge_lead_qualifie(lead_id)
        charge["lead"] |= {
            "ville": ville,
            "conversation_id": f"conv-{lead_id}",
            "contact": {"nom": f"Client fictif {lead_id}", "telephone": f"+1 450 555 {1000 + rang}"},
        }
        charge["signal_id"] = f"texte:sig-{lead_id}"
        B.publier("m1.lead_qualifie", M1, charge, evenement_id=f"m1-lead-qualifie-{lead_id}")
        ids.append(lead_id)
    B.livrer((M2,))
    return ids


def cadrer(cap, question: str) -> dict:
    return ok(appel(cap, "m9_cadrer_decision", {"question": question, "reference": REF}))


def interpreter(cap, question: str) -> dict:
    (proposition,) = ok(appel(cap, "m9_interpreter_question_scenario", {"question": question}))["propositions"]
    assert proposition["statut"] == "COMPLETE" and proposition["parametres_a_fournir"] == [], proposition
    return proposition


def evaluer_scenarios(cap, bases: dict, propositions: list[dict]) -> dict:
    chocs = [{"choc": p["choc"], "parametres": p["parametres"]} for p in propositions]
    return ok(appel(cap, "m9_evaluer_scenarios", {"reference": REF, "bases": bases, "chocs": chocs}))


def proposer_action(cap, departement: str, outil: str, sources: list[str], arguments=None):
    return appel(
        cap,
        "m9_proposer_action",
        {
            "departement": departement,
            "outil": outil,
            "arguments": arguments or {},
            "sources": sources,
            "motif": "proposition issue du parcours de direction",
            "horodatage": T,
        },
    )


def approbations_natives() -> list[dict]:
    with stockage.transaction() as cnx:
        return approbations.lister(cnx)


def refus_sans_trace(cap, reponse, code: str, avant: list[dict]) -> None:
    """Refus nommé, aucune demande native créée par M9, rien au registre des actions."""
    assert refuse(reponse, code), reponse
    assert approbations_natives() == avant, "aucune demande native n'a été créée"
    assert ok(appel(cap, "m9_lire_actions", {}))["total"] == 0, "un refus n'écrit rien dans le registre des actions"


def indicateurs(cap) -> dict:
    lignes, depart = [], 0
    while depart is not None:
        page = ok(appel(cap, "m9_indicateurs_executifs", {"connaissance": REF, "depart": depart}))
        lignes += page["indicateurs"]
        depart = page["prochain_depart"]
    return {i["id"]: i for i in lignes}


def playbook(cap, playbook_id: str, **declaration) -> dict:
    return ok(appel(cap, "m9_evaluer_playbook", {"playbook_id": playbook_id, "connaissance": REF, **declaration}))


def sensibles(plan: dict) -> dict:
    return {
        e["id"]: (e["genre"], e["statut"], e["proprietaire_decision"])
        for e in plan["etapes"]
        if e["type"] == "action_sensible"
    }


# -- conseil : profils natifs, runtime natif SIMULÉ (seul le tour de modèle est joué par le test) -------------------
def _plafonds_entreprise() -> None:
    with stockage.transaction() as cnx:
        admission_agents.configurer_plafonds_entreprise(
            cnx, 500_000, 5_000_000, par="admin.fictif", revision_attendue=0
        )


def _creer_profils(roles: list[str]) -> None:
    """Un administrateur crée et active les profils déclarés par M9 (`m9_proposer_profils_conseil`)."""
    departements = charger_departements()
    seul_m9 = Capacites(departements, stockage.transaction, filtre={M9}, memoire=False)
    par_id = {p["id"]: p for p in ok(appel(seul_m9, "m9_proposer_profils_conseil", {}))["profils"]}
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


def _runtime_natif_simule(role: str, execution_id: str, tokens: int) -> str:
    """Rôle du runtime Core : réserve l'enveloppe du rôle avant le tour, réconcilie l'usage après (mêmes fonctions)."""
    with stockage.transaction() as cnx:
        reservation = admission_agents.reserver(
            cnx,
            f"m9-{role.replace('_', '-')}",
            charger_departements(),
            execution_id,
            f"cle-{execution_id}",
            conseil.PAR_ID[role].enveloppe_tokens,
            tours=1,
            reessais=0,
        )
        admission_agents.concilier(cnx, reservation["id"], tokens)
    return reservation["id"]


def conduire_conseil(cap, *, question: str, domaines: list[str], attendues: list[str], sortie_de) -> tuple[dict, dict]:
    """Ouvre un conseil, joue chaque tour (réservation native, sortie prédéfinie `sortie_de(role)`), le clôt."""
    _plafonds_entreprise()
    ouverture = ok(
        appel(
            cap,
            "m9_ouvrir_conseil",
            {
                "question": question,
                "domaines": domaines,
                "importance": "courante",
                "budget_tokens": 100_000,
                "reference": REF,
                "horodatage": T,
                "attendues": attendues,
            },
        )
    )
    session_id = ouverture["session_id"]
    roles = [t["role"] for t in ouverture["tours"]]
    assert "conseiller_pdg" in roles, roles
    _creer_profils(roles)
    for role in roles:
        entree = ok(appel(cap, "m9_lire_entree_tour_conseil", {"session_id": session_id, "role": role}))
        assert entree["taille"] > 0
        reservation_id = _runtime_natif_simule(role, f"exec-{session_id[:8]}-{role}", 1234)
        depot = ok(
            appel(
                cap,
                "m9_deposer_tour_conseil",
                {
                    "session_id": session_id,
                    "role": role,
                    "sortie": sortie_de(role),
                    "reservation_id": reservation_id,
                    "horodatage": T,
                },
            )
        )
        assert depot["issue"] == "ADMIS" and depot["rejoue"] is False, (role, depot)
    cloture = ok(appel(cap, "m9_cloturer_conseil", {"session_id": session_id, "horodatage": T}))
    return ouverture, cloture


# =====================================================================================================================
# 1. Rapport hebdomadaire : captures → revue (20 sections) → conseil → recommandation gouvernée → M10 → audit
# =====================================================================================================================
def test_parcours_1_rapport_hebdomadaire_conseil_memoire_et_audit(tmp_path, monkeypatch, nettoyage):
    # RÉEL : le monde « rupture de matériau » (M1→M2, M3, M4 cédulé et daté, M5, M6, M8) et ses huit captures.
    monde = G._monter_scenario(tmp_path, monkeypatch)
    cap = B.capacites(M2, M3, M4, M5, M6, M8, M10)
    capturer(cap, "m5.prevision_tresorerie", {"aujourd_hui": B.AUJOURD_HUI_M5}, "2026-10-28T12:01:01Z")
    capturer(cap, "m8.vue_executive", {"aujourd_hui": "2026-10-28"}, "2026-10-28T12:01:02Z")
    attendues = [*G.ARGUMENTS, "m5.prevision_tresorerie", "m8.vue_executive", "m7.performance_campagnes"]
    question = "Quelles priorités pour la semaine prochaine ?"
    domaines = ["strategie", "stock", "marge"]
    faits = faits_du_dossier(cap, question=question, domaines=domaines, attendues=attendues)
    dispo = adresse(faits, "m6.disponibilite", ".articles[0].disponible")
    marge = adresse(faits, "m5.rentabilite_chantier", ".rentabilite.marge_reelle")
    assert (faits[dispo], faits[marge]) == ("0", "114.00"), "valeurs publiées par M6 et M5, citées telles quelles"
    assert dispo.startswith(f"m6.disponibilite#{monde['index']['m6.disponibilite']}:p0."), "capture réelle du monde"

    # Avant le conseil, la revue n'a ni recommandation ni décision à prendre : elle le dit, elle n'en invente pas.
    avant, _ = revue_hebdomadaire(cap)
    assert avant["sections_direction"]["sections"]["recommandations"]["statut"] == "NON_DISPONIBLE"
    assert avant["sections_direction"]["sections"]["decisions_a_prendre"]["manques"] == [
        "aucune décision en attente connue de M9"
    ]

    # SIMULÉ : le tour de modèle. Chaque sortie prédéfinie CITE des faits réels (adresse + valeur exacte).
    def sortie_de(role):
        sortie = {
            "affirmations": [
                {"id": "A1", "nature": "observation_source", "reference": dispo, "valeur": faits[dispo]},
            ]
        }
        if role == "conseiller_pdg":
            sortie["affirmations"] += [
                {"id": "A2", "nature": "observation_source", "reference": marge, "valeur": faits[marge]},
                {"id": "H1", "nature": "hypothese", "enonce": "le fournisseur peut livrer avant la pose"},
            ]
            sortie["recommandation"] = {
                "decision": "Suivre la rupture du matériau et faire valider la commande",
                "refs": ["A1", "A2", "H1"],
                "actions": [
                    {"id": "a1", "type": "suivi_interne", "description": "suivre la réservation partielle"},
                    {"id": "a2", "type": "depense_reelle", "description": "commander le matériau manquant"},
                ],
            }
        return sortie

    ouverture, cloture = conduire_conseil(
        cap, question=question, domaines=domaines, attendues=attendues, sortie_de=sortie_de
    )
    session_id = ouverture["session_id"]
    assert cloture["cloture"]["issue"] == "RECOMMANDATION" and cloture["cloture"]["autorite_d_effet"] is False
    verdicts = {v["action"]: v for v in cloture["gouvernance"]["actions"]}
    assert verdicts["a1"]["verdict"] == "PROPOSABLE"
    assert (verdicts["a2"]["verdict"], verdicts["a2"]["mandataire"]) == ("VALIDATION_HUMAINE_REQUISE", "Nathan")
    rapport, _ = lire_tout(cap, "m9_lire_rapport_conseil", {"session_id": session_id})
    assert rapport["rapport_id"] == cloture["cloture"]["rapport_id"]
    assert rapport["statut_contrat"] == "RETENU_PAR_DELEGATION"

    # M10 : arguments EXACTS préparés (rien n'est écrit), puis proposés à la file native — jamais exécutés par M9.
    prepare = ok(
        appel(
            cap,
            "m9_preparer_memoire_decision",
            {
                "session_id": session_id,
                "statut": "proposee",
                "horodatage": "2026-10-28T14:00:00Z",
            },
        )
    )
    a_proposer = prepare["a_proposer"]
    assert prepare["ecrit"] is False and prepare["decision_id"] == f"m9:{session_id}"
    assert (a_proposer["departement"], a_proposer["outil"]) == (M10, "m10_journaliser_decision")
    assert a_proposer["sources"] == [f"conseil:{cloture['cloture']['rapport_id']}"]
    decision = a_proposer["arguments"]["decision"]
    assert decision["decision_id"] == prepare["decision_id"] and decision["statut"] == "proposee"
    assert f"rapport {cloture['cloture']['rapport_id']}" in decision["raison"]
    proposee = ok(
        appel(
            cap,
            "m9_proposer_action",
            {
                **a_proposer,
                "motif": "consigner la recommandation du conseil",
                "horodatage": "2026-10-28T14:05:00Z",
            },
        )
    )
    assert proposee["etat"] == "EN_ATTENTE_APPROBATION" and proposee["execute"] is False, proposee
    with stockage.transaction() as cnx:
        (native,) = approbations.lister(cnx, "en_attente")
    assert native["arguments"] == a_proposer["arguments"], "le schéma réel de M10 a accepté ces arguments exacts"

    # La revue hebdomadaire, lue PAR PAGES, porte les vingt sections de direction.
    revue, pages = revue_hebdomadaire(cap)
    assert pages >= 1 and revue["periode"]["debut_local"] == "2026-10-26"
    direction = revue["sections_direction"]
    assert direction["ids"] == IDS_DIRECTION and set(direction["sections"]) == set(IDS_DIRECTION)
    assert len(IDS_DIRECTION) == 20
    s = direction["sections"]
    assert all(v["statut"] in ("RENSEIGNEE", "PARTIELLE", "NON_DISPONIBLE") and v["titre"] for v in s.values())
    assert s["recommandations"]["statut"] == "RENSEIGNEE"
    (recommandation,) = s["recommandations"]["contenu"]["recommandations"]
    assert recommandation["session_id"] == session_id
    assert {a["action"]: a["verdict"] for a in recommandation["actions"]} == {
        "a1": "PROPOSABLE",
        "a2": "VALIDATION_HUMAINE_REQUISE",
    }
    decisions = s["decisions_a_prendre"]
    assert decisions["statut"] == "RENSEIGNEE"
    assert decisions["contenu"]["recommandations_a_valider_par_un_humain"] == [
        {"session_id": session_id, "rapport_id": cloture["cloture"]["rapport_id"], "actions": ["a2"]}
    ]
    assert [d["action_id"] for d in decisions["contenu"]["approbations_natives_en_attente"]] == [proposee["action_id"]]
    # M7 n'a pas été capturé : la section marketing le NOMME, rien n'est rempli.
    assert s["marketing_visibilite"]["statut"] == "NON_DISPONIBLE" and s["marketing_visibilite"]["manques"]
    assert "m7.performance_campagnes" in s["resume"]["contenu"]["lectures_attendues_non_presentes"]
    assert "float" not in json.dumps(revue)

    # Audit des citations : l'auditeur compare une citation au dossier SERVEUR de snapshots (M4 → M8 → M9 par le bus).
    B.livrer((M9,))
    question_audit = "Quelle durée réelle de chantier M8 a-t-il transmise ?"
    reponse = appel(cap, "m9_preparer_dossier_direction", {"question": question_audit, "modules_attendus": [M4]})
    assert reponse["ok"] is True, reponse
    dossier = reponse["resultat"]
    fait = dossier["faits_selectionnes"][M4]
    assert fait["valeurs"]["m4_duree_reelle_minutes"] == "180", "durée du WCT réel, relayée par M8"
    citation = {
        "id": "C1",
        "nature": "observation_source",
        "reference": {
            "module_source": M4,
            "index": fait["index"],
            "hash_maillon": fait["hash_maillon"],
            "cle": "m4_duree_reelle_minutes",
        },
        "valeur": "180",
    }
    audit = {"question": question_audit, "modules_attendus": [M4], "dossier_attendu": dossier["dossier_id"]}
    exact = appel(cap, "m9_auditer_affirmations_conseil", {**audit, "affirmations": [citation]})
    assert exact["ok"] is True and "SOURCE_CONCORDANTE" in json.dumps(exact["resultat"]["audit"]), exact
    faux = appel(cap, "m9_auditer_affirmations_conseil", {**audit, "affirmations": [citation | {"valeur": "999"}]})
    assert faux["ok"] is False and "resultat" not in faux, "une citation divergente fait refuser tout le lot"
    # LIMITE constatée (rapportée) : l'auditeur ne lit que le dossier de SNAPSHOTS ; une citation du conseil, qui est
    # une adresse de CAPTURE, est refusée (REJ-AUDIT-AFFIRMATION). L'ancrage des citations du conseil est celui du
    # dépôt (`m9_deposer_tour_conseil` : ADMIS seulement si adresse et valeur sont exactes), pas cet auditeur.
    du_conseil = {"id": "A1", "nature": "observation_source", "reference": dispo, "valeur": faits[dispo]}
    refusee = appel(cap, "m9_auditer_affirmations_conseil", {**audit, "affirmations": [du_conseil]})
    assert refusee["ok"] is False and "REJ-AUDIT-AFFIRMATION" in json.dumps(refusee), refusee


# =====================================================================================================================
# 2. Décision budget marketing : « Dois-je augmenter Google Ads de 25 % ? »
# =====================================================================================================================
def test_parcours_2_budget_marketing_cadre_scenario_sans_base_et_action_non_proposable(
    tmp_path, monkeypatch, nettoyage
):
    # RÉEL : six leads qualifiés (M1 → M2 par le bus), un chantier attribué à une campagne (M2/M3/M5 → M7), des
    # mouvements de trésorerie (M5). Aucune donnée M4 : la cédule reste une lecture ABSENTE, nommée.
    _installer(tmp_path, monkeypatch)
    B.declarer_m5(tmp_path, monkeypatch)
    leads_par_le_bus("L-ADS", 6, "Repentigny")
    B.alimenter_m7()
    B.enregistrer_mouvements_m5()
    cap = B.capacites(M2, M5, M7)
    capturer(cap, "m7.performance_campagnes", {"debut": "2026-09-01", "fin": "2026-09-30"}, "2026-10-28T12:00:01Z")
    capturer(cap, "m2.leads", {"horodatage": "2026-10-28T12:00:00Z"}, "2026-10-28T12:00:02Z")
    capturer(cap, "m5.prevision_tresorerie", {"aujourd_hui": B.AUJOURD_HUI_M5}, "2026-10-28T12:00:03Z")

    cadrage = cadrer(cap, "Dois-je augmenter Google Ads de 25 % ?")
    assert cadrage["decision"]["id"] == "budget_publicitaire" and cadrage["decision_prise_par_m9"] is False
    assert cadrage["lectures_requises"] == [
        "m7.performance_campagnes",
        "m2.leads",
        "m5.prevision_tresorerie",
        "m4.cedule_semaine",
    ]
    statuts = {c["lecture_id"]: c["statut"] for c in cadrage["couverture"]}
    # M7 ne déclare aucun instant métier dans sa lecture : M9 le dit (TEMPS_METIER_NON_DECLARE), sans le supposer frais.
    assert statuts == {
        "m7.performance_campagnes": "TEMPS_METIER_NON_DECLARE",
        "m2.leads": "PRESENTE",
        "m5.prevision_tresorerie": "PRESENTE",
        "m4.cedule_semaine": "ABSENTE",
    }
    assert [(m["lecture_id"], m["statut"]) for m in cadrage["manques"]] == [
        ("m7.performance_campagnes", "TEMPS_METIER_NON_DECLARE"),
        ("m4.cedule_semaine", "ABSENTE"),
    ]
    assert cadrage["pret_pour_conseil"] is False, "une lecture requise manque : le conseil n'est pas prêt"
    assert cadrage["validation"]["requiert_nathan"] is True
    assert cadrage["validation"]["classes_sensibles"] == {
        "budget_marketing": {"verdict": "VALIDATION_HUMAINE_REQUISE", "mandataire": "Nathan"}
    }
    brouillon = cadrage["brouillon_approbation"]
    assert brouillon["statut"] == "BROUILLON_NON_SOUMIS" and brouillon["montant"] is None
    assert "hausse_budget_marketing" in cadrage["scenarios_a_examiner"]
    assert "plafond de budget" in cadrage["a_declarer_par_la_personne"], "aucun plafond par défaut"

    hausse = interpreter(cap, "Et si le budget marketing augmente de 25 % ?")
    assert (hausse["choc"], hausse["parametres"]) == ("hausse_budget_marketing", {"hausse_pct": "25"})
    assert [(b["base"], b["proprietaire"]) for b in hausse["bases_requises"]] == [("budget_marketing_periode", M7)]
    faits = faits_du_dossier(cap)
    # M7 publie la campagne mais AUCUNE dépense : `cout_ads_cad` est nul, donc aucun fait citable de budget.
    (source_campagne,) = [
        a for a in faits if a.startswith("m7.performance_campagnes#") and "campagnes[0]" in a and a.endswith(".source")
    ]
    assert faits[source_campagne] == "google"
    assert not [a for a in faits if a.endswith("cout_ads_cad") or a.endswith(".roi")], "rien n'est rempli"
    total = adresse(faits, "m2.leads", "resultat.resultat.total")
    assert faits[total] == "6"
    afflux = {"choc": "trop_de_demandes", "parametres": {"hausse_pct": "25"}, "statut": "COMPLETE"}
    evaluation = evaluer_scenarios(cap, {"leads_periode": total}, [hausse, afflux])
    budget, demandes = evaluation["scenarios"]
    assert budget["calculable"] is False and budget["bases"]["budget_marketing_periode"]["etat"] == "BASE_ABSENTE"
    (effet,) = budget["effets"]
    assert effet["statut"] == "NON_CALCULE" and "(m07-marketing)" in effet["raison"], "le refus nomme le propriétaire"
    assert budget["a_calculer_par"][0]["proprietaire"] == M7, "l'élasticité budget → leads reste chez M7"
    (projete,) = demandes["effets"]
    assert projete["statut"] == "CALCULE" and Decimal(projete["valeur"]) == Decimal("6") * Decimal("1.25")
    assert demandes["bases"]["leads_periode"]["adresse"] == total
    assert {h["origine"] for h in demandes["hypotheses"]} == {"DECLAREE_PAR_LA_PERSONNE"}
    lignes = {ligne["scenario"]: ligne for ligne in evaluation["comparaison"]["lignes"]}
    assert (
        lignes["hausse_budget_marketing"]["statut"] == "NON_CALCULE"
        and "valeur" not in lignes["hausse_budget_marketing"]
    ), "un effet sans base est nommé non calculé, jamais chiffré"
    assert lignes["trop_de_demandes"]["reference"] == "6" and lignes["trop_de_demandes"]["statut"] == "CALCULE"

    # Une action de budget marketing n'est PAS proposable : hors liste blanche, refus avant toute écriture.
    avant = approbations_natives()
    refus = proposer_action(cap, M7, "m7_approuver_budget_campagne", [total])
    refus_sans_trace(cap, refus, "REJ-ACTION-NON-AUTORISEE", avant)


# =====================================================================================================================
# 3. Cashflow serré : seuil déclaré, alerte réelle de M5 → radar → playbook « cash » → « Dois-je acheter un camion ? »
# =====================================================================================================================
def test_parcours_3_cashflow_serre_radar_playbook_et_cadrage_camion(tmp_path, monkeypatch, nettoyage):
    # RÉEL : M5 avec seuil d'alerte déclaré (16 000 $), solde de 20 000 $, factures envoyées par la file N4 et comptes
    # à payer reçus de M6 : sa prévision publie une ALERTE.
    _installer(tmp_path, monkeypatch)
    B.declarer_m5(tmp_path, monkeypatch)
    B.enregistrer_mouvements_m5()
    B.factures_clients_m5()
    B.comptes_a_payer_m5(3)
    cap = B.capacites(M4, M5)
    prevision = capturer(cap, "m5.prevision_tresorerie", {"aujourd_hui": B.AUJOURD_HUI_M5}, "2026-10-28T12:00:01Z")
    capturer(cap, "m5.comptes_a_payer", {}, "2026-10-28T12:00:02Z")
    page = B.page(prevision["index"])
    assert B.valeurs(page, "resultat.resultat.alerte.statut") == ["ALERTE"]
    assert B.valeurs(page, "resultat.resultat.solde_initial.montant") == ["20000.00"]
    (deficit,) = B.valeurs(page, "resultat.resultat.premiere_semaine_en_deficit")

    radar = ok(appel(cap, "m9_radar_risques", {"connaissance": REF}))
    assert radar["grille"]["statut"] == "PROPOSEE_NON_VALIDEE_PAR_NATHAN"
    (cash,) = [r for r in radar["risques"] if r["domaine"] == "cash"]
    assert (cash["regle"], cash["statut"], cash["sujet"]) == ("cash_alerte_seuil", "ACTIF", "tresorerie")
    # Grille PROPOSÉE (non validée) : alerte sous le seuil SANS semaine en déficit publiée par M5 -> MOYEN.
    assert (cash["gravite"], deficit) == ("MOYEN", None), (cash, deficit)
    assert cash["origine_etablie"] is False and "cause" not in cash
    assert cash["preuves"][0].startswith(f"m5.prevision_tresorerie#{prevision['index']}:p0.")
    assert {n["regle"] for n in radar["regles_non_evaluees"]} >= {"materiaux_reservation_incomplete"}

    plan_cash = ok(appel(cap, "m9_evaluer_playbook", {"playbook_id": "cash", "connaissance": REF}))["plan"]
    assert plan_cash["declenchement"]["statut"] == "DECLENCHE"
    assert all(e["effet_autorise"] is False for e in plan_cash["etapes"]), "le playbook n'exécute rien"

    cadrage = cadrer(cap, "Dois-je acheter un camion ?")
    assert cadrage["decision"]["id"] == "achat_vehicule" and cadrage["decision_prise_par_m9"] is False
    validation = cadrage["validation"]
    assert validation["requiert_nathan"] is True and validation["requiert_comptable"] is True
    assert validation["classes_sensibles"] == {
        "achat_majeur": {"verdict": "VALIDATION_HUMAINE_REQUISE", "mandataire": "Nathan"}
    }
    statuts = {c["lecture_id"]: c["statut"] for c in cadrage["couverture"]}
    assert statuts == {
        "m5.prevision_tresorerie": "PRESENTE",
        "m5.comptes_a_payer": "PRESENTE",
        "m4.cedule_semaine": "ABSENTE",
    }
    assert "cashflow_serre" in cadrage["scenarios_a_examiner"]
    assert [c["proprietaire"] for c in cadrage["criteres_proposes"] if c["id"] == "tresorerie"] == ["m05"]
    # Le risque cash est celui du radar (M5) ; le scénario « trésorerie serrée » reste au propriétaire.
    serre = interpreter(cap, "Et si le cashflow est serré sur les 6 prochaines semaines sous 8 000 $ ?")
    camion = {"choc": "achat_camion", "parametres": {"prix": "60000"}, "statut": "COMPLETE"}
    evaluation = evaluer_scenarios(cap, {}, [serre, camion])
    tresorerie, achat = evaluation["scenarios"]
    assert tresorerie["effets"] == [] and tresorerie["a_calculer_par"][0]["proprietaire"] == M5
    assert achat["calculable"] is False and "(m05-financecore)" in achat["effets"][0]["raison"]
    # Aucun achat n'est proposable par M9.
    avant = approbations_natives()
    refus = proposer_action(cap, M5, "m5_preparer_decision_capital", [cash["preuves"][0]])
    refus_sans_trace(cap, refus, "REJ-ACTION-NON-AUTORISEE", avant)


# =====================================================================================================================
# 4. Trop de leads pour la capacité : afflux M2 + cédule M4
# =====================================================================================================================
def test_parcours_4_trop_de_leads_pour_la_capacite(tmp_path, monkeypatch, nettoyage):
    # RÉEL : une cédule M4 appliquée et datée (trois chantiers, deux équipes), un report et un écart déclarés par Marc,
    # puis douze leads qualifiés publiés par M1 et reçus par M2.
    _installer(tmp_path, monkeypatch)
    m4 = A.outils_departement(M4)
    A.m4_alimenter_cedule(m4)
    A.m4_alimenter_retards(m4)
    leads_par_le_bus("L-AFFLUX", 12, "Repentigny")
    cap = B.capacites(M2, M4)
    capturer(cap, "m2.leads", {"horodatage": "2026-10-28T12:00:00Z"}, "2026-10-28T12:00:01Z")
    cedule = capturer(cap, "m4.cedule_semaine", {"debut_semaine": A.LUNDI}, "2026-10-28T12:00:02Z")
    capturer(cap, "m4.retards_incidents", {"horodatage_reference": "2026-10-28T12:00:00Z"}, "2026-10-28T12:00:03Z")
    # Aucun producteur n'expose la capacité : la cédule porte des interventions, pas de jours-personnes.
    assert B.valeurs(B.page(cedule["index"]), "resultat.resultat.interventions[*].intervention_id")
    assert not [c for c in cles(B.page(cedule["index"])) if "capacite" in c], "aucune capacité publiée par M4"

    faits = faits_du_dossier(cap)
    total = adresse(faits, "m2.leads", "resultat.resultat.total")
    assert faits[total] == "12"
    afflux = interpreter(cap, "Et si on a trop de demandes, soit une hausse de 150 % ?")
    (scenario,) = evaluer_scenarios(cap, {"leads_periode": total}, [afflux])["scenarios"]
    (projete,) = scenario["effets"]
    assert (projete["statut"], projete["valeur"], projete["valeur_base"]) == ("CALCULE", "30.00", "12")
    assert scenario["bases"]["leads_periode"]["adresse"] == total, "base citée, capture réelle de M2"
    (confie,) = scenario["a_calculer_par"]
    assert confie["proprietaire"] == "m03-estimation / m04-field-ops" and "capacité" in confie["motif"]

    radar = ok(appel(cap, "m9_radar_risques", {"connaissance": REF}))
    assert {r["regle"] for r in radar["risques"] if r["domaine"] == "capacite"} >= {"capacite_report_en_cours"}
    surcharge = playbook(cap, "surcharge")
    assert surcharge["plan"]["declenchement"]["statut"] == "DECLENCHE", "déclenché par le radar sur M4"
    assert sensibles(surcharge["plan"]) == {"renfort": ("embauche", "VALIDATION_HUMAINE_REQUISE", "Nathan")}
    # « Trop de leads » : aucun producteur ne mesure le délai de premier contact ; la personne déclare le déclencheur.
    assert playbook(cap, "trop_de_leads")["plan"]["declenchement"]["statut"] == "A_DECLARER"
    declare = playbook(cap, "trop_de_leads", declare_par_la_personne=True, liaisons={"leads_resorbes": "5"})
    assert declare["plan"]["declenchement"] == {"statut": "DECLENCHE", "declare_par_la_personne": True, "risques": []}
    assert sensibles(declare["plan"]) == {
        "ralentir_campagnes": ("budget_marketing", "VALIDATION_HUMAINE_REQUISE", "Nathan"),
        "renfort": ("embauche", "VALIDATION_HUMAINE_REQUISE", "Nathan"),
    }
    (resorbes,) = declare["evaluation"]["succes"]
    assert (resorbes["statut"], resorbes["cible"]) == ("NON_SATISFAIT", "5"), "12 leads lus contre la cible déclarée"
    assert declare["evaluation"]["verdict"] == "EN_COURS"

    par_id = indicateurs(cap)
    capacite = par_id["team_capacity"]
    assert capacite["statut_definition"] == "A_DEFINIR_PAR_LE_PROPRIETAIRE" and capacite["calcule_par_m9"] is False
    assert "faits" not in capacite or capacite["faits"] == []
    for question, classe in (
        ("Dois-je augmenter Google Ads de 25 % ?", "budget_marketing"),
        ("Dois-je augmenter les prix ?", "prix_global"),
        ("Dois-je ajouter une équipe ?", "embauche"),
    ):
        validation = cadrer(cap, question)["validation"]
        assert validation["requiert_nathan"] is True, question
        assert validation["classes_sensibles"][classe] == {
            "verdict": "VALIDATION_HUMAINE_REQUISE",
            "mandataire": "Nathan",
        }, question


# =====================================================================================================================
# 5. Nouvelle ville : leads d'une autre ville + rentabilité M5 → cadrage → scénario → expérience → plan
# =====================================================================================================================
def test_parcours_5_nouvelle_ville_scenario_experience_et_plan(tmp_path, monkeypatch, nettoyage):
    # RÉEL : trois leads à Terrebonne et deux à Repentigny (M1 → M2), un chantier terminé dont M5 calcule la
    # rentabilité et un cash libre constaté par M5 (relayé par M8).
    _installer(tmp_path, monkeypatch)
    B.declarer_m5(tmp_path, monkeypatch)
    leads_par_le_bus("L-TBN", 3, "Terrebonne")
    leads_par_le_bus("L-REP", 2, "Repentigny")
    B.alimenter_m8()
    cap = B.capacites(M2, M5, M8)
    leads = capturer(cap, "m2.leads", {"horodatage": "2026-10-28T12:00:00Z"}, "2026-10-28T12:00:01Z")
    capturer(cap, "m5.rentabilite_chantier", {}, "2026-10-28T12:00:02Z")
    capturer(cap, "m8.vue_executive", {"aujourd_hui": "2026-10-28"}, "2026-10-28T12:00:03Z")
    faits = faits_du_dossier(cap)
    villes = {a: v for a, v in faits.items() if a.startswith("m2.leads#") and a.endswith(".ville")}
    assert sorted(villes.values()) == ["Repentigny"] * 2 + ["Terrebonne"] * 3
    # M2 expose la ville de CHAQUE lead, aucun agrégat par ville : M9 ne compte pas à sa place.
    assert not [c for c in cles(B.page(leads["index"])) if "ville" in c and c != "ville"]
    terrebonne = next(a for a, v in villes.items() if v == "Terrebonne")

    cadrage = cadrer(cap, "Dois-je prioriser la ville de Terrebonne ?")
    assert cadrage["decision"]["id"] == "priorite_ville" and cadrage["scenarios_a_examiner"] == ["nouvelle_ville"]
    statuts = {c["lecture_id"]: c["statut"] for c in cadrage["couverture"]}
    assert statuts["m2.leads"] == "PRESENTE" and statuts["m5.rentabilite_chantier"] == "TEMPS_METIER_NON_DECLARE"
    assert (statuts["m7.performance_campagnes"], statuts["m4.interventions"]) == ("ABSENTE", "ABSENTE")
    assert cadrage["pret_pour_conseil"] is False and cadrage["playbooks_a_examiner"] == ["expansion_ville"]

    ville = interpreter(
        cap, "Et si on ouvre une nouvelle ville avec un investissement de 5000 $ et 10 leads supplémentaires ?"
    )
    assert ville["parametres"] == {"leads_supplementaires": "10", "investissement": "5000"}
    cash = adresse(faits, "m8.vue_executive", "cash_libre.constat.cash_libre_cad")
    assert faits[cash] == "12559.40", "cash libre constaté par M5, relayé par M8"
    (scenario,) = evaluer_scenarios(cap, {"cash_libre": cash}, [ville])["scenarios"]
    (apres,) = scenario["effets"]
    assert (apres["statut"], apres["valeur"]) == ("CALCULE", str(Decimal("12559.40") - Decimal("5000")))
    assert scenario["a_calculer_par"][0]["proprietaire"] == "m02-revenue-crm / m07-marketing", "demande locale"

    reelle = adresse(faits, "m5.rentabilite_chantier", ".rentabilite.marge_reelle")
    prevue = adresse(faits, "m5.rentabilite_chantier", ".rentabilite.marge_prevue")
    total = adresse(faits, "m2.leads", "resultat.resultat.total")
    experience = {
        "experience_id": "terrebonne-30-jours",
        "hypothese": "Prioriser Terrebonne pendant 30 jours garde la marge réelle au niveau de la marge prévue",
        "design": "AVANT_APRES",
        "mesures": [
            {"id": "reelle", "role": "expose", "ref": reelle, "unite": "CAD"},
            {"id": "prevue", "role": "reference", "ref": prevue, "unite": "CAD"},
            {"id": "leads", "role": "effectif", "ref": total, "unite": "leads"},
        ],
        "contre_exemples": [],
        "plafond_budget_cad": "500.00",
        "duree_jours": 30,
        "limite_risque": "aucun engagement de prix ni de date hors de la zone desservie déclarée",
        "porteur": "admin.fictif",
        "plan_retour": "revenir aux priorités de leads antérieures ; aucune dépense engagée sans décision de Nathan",
    }
    definie = ok(appel(cap, "m9_definir_experience", {"experience": experience, "reference": REF, "horodatage": T}))
    assert definie["version"] == 1
    evaluee = ok(appel(cap, "m9_evaluer_experience", {"experience_id": "terrebonne-30-jours", "horodatage": T}))
    evaluation = evaluee["experience"]["evaluation"]
    assert evaluation["cadre"] == {
        k: experience[k] for k in ("plafond_budget_cad", "duree_jours", "limite_risque", "porteur", "plan_retour")
    }
    assert evaluation["gain_mesure"] == str(Decimal("114.00") - Decimal("120.00"))
    assert evaluation["statut_roi"] == "ROI_NON_CALCULABLE" and evaluation["budget"]["statut"] == "INCONNU"
    assert evaluation["inference"] == "ASSOCIATION_SEULEMENT" and any("cout" in m for m in evaluation["manques"])

    plan = {
        "plan_id": "priorite-terrebonne",
        "objectif": "Suivre les leads de Terrebonne pendant 30 jours",
        "porteur": "vendeur.fictif",
        "echeance": "2026-11-27",
        "resultats_cles": [
            {
                "id": "leads_suivis",
                "libelle": "Au moins 8 leads lus chez M2",
                "lecture": "m2.leads",
                "chemin": "resultat.resultat.total",
                "operateur": ">=",
                "cible": "8",
            },
            {
                "id": "marge_ville",
                "libelle": "Marge de la zone jugée par Nathan (M5 ne la ventile pas)",
                "operateur": "manuel",
            },
        ],
        "sources": [terrebonne, cash],
        "decision_ref": "priorite-ville-terrebonne",
    }
    depose = ok(appel(cap, "m9_enregistrer_plan", {"plan": plan, "reference": REF, "horodatage": T}))
    assert depose["version"] == 1
    (lu,) = ok(appel(cap, "m9_lire_plans", {"connaissance": "2026-10-29T12:00:00Z", "jour": "2026-10-29"}))["plans"]
    mesures = {r["id"]: r["mesure"]["statut"] for r in lu["resultats_cles"]}
    assert mesures == {"leads_suivis": "NON_SATISFAIT", "marge_ville": "A_JUGER_PAR_LA_PERSONNE"}
    assert lu["statut"] == "EN_COURS"


# =====================================================================================================================
# 6. Risque de réputation : ce que M1 expose réellement, plan de mitigation, décision visible dans la revue
# =====================================================================================================================
def test_parcours_6_risque_de_reputation(tmp_path, monkeypatch, nettoyage):
    # RÉEL : le vocabulaire des plaintes déclaré par le propriétaire, quatre demandes et UNE plainte reçues par M1
    # (`m1_traiter_demande_entrante`) : la plainte ouvre un transfert à un humain, jamais un lead.
    _installer(tmp_path, monkeypatch)
    taxonomie.enregistrer_signaux_plainte({"insatisfaction": ["plainte"]})
    B.demandes_m1()
    traiter = next(o for o in B.m1_outils.outils() if o.nom == "m1_traiter_demande_entrante")
    plainte = B.executer_atomique(
        traiter,
        {
            "contenu_brut": "Je dépose une plainte : la gouttière posée coule encore, téléphone 450-555-0177.",
            "canal": "courriel",
            "conversation_id": "conv-plainte",
            "signal_id": "sig-conv-plainte",
            "horodatage": "2026-09-29T11:00:00-04:00",
            "zone_desservie": list(B.ZONE_DESSERVIE),
        },
    )
    assert plainte["ok"] is True and plainte["resultat"]["accepte"] is True, plainte
    cap = B.capacites(M1)
    digest = capturer(cap, "m1.digest", {"date_reference": "2026-09-29"}, "2026-10-28T12:00:01Z")
    page = B.page(digest["index"])
    texte = page["resultat"]
    # Ce que M1 expose RÉELLEMENT : un TEXTE agrégé ; la plainte ouverte n'y est qu'une phrase, aucun champ structuré.
    assert isinstance(texte, str) and "plaintes : 1" in texte and "450-555-0177" not in texte
    assert B.valeurs(page, "resultat.plaintes") == [] and B.valeurs(page, "resultat.transferts") == []
    # Donc AUCUNE règle de réputation : M9 ne lit pas une phrase pour en tirer un risque, il le nomme absent.
    assert "reputation" not in {r.domaine for r in risques.REGLES}
    assert "m1.digest" not in {r.lecture_id for r in risques.REGLES}
    radar = ok(appel(cap, "m9_radar_risques", {"connaissance": REF}))
    assert radar["risques"] == [], "aucun risque inventé à partir du digest"
    assert {n["raison"] for n in radar["regles_non_evaluees"]} == {"ABSENTE"}
    assert indicateurs(cap)["customer_satisfaction"]["statut_definition"] == "A_DEFINIR_PAR_LE_PROPRIETAIRE"
    risque_plaintes = playbook(cap, "risque_plaintes")
    assert risque_plaintes["plan"]["declenchement"]["statut"] == "A_DECLARER"
    declare = playbook(cap, "risque_plaintes", declare_par_la_personne=True)
    assert declare["plan"]["declenchement"]["declare_par_la_personne"] is True
    assert sensibles(declare["plan"]) == {
        "engagement_client": ("contrat", "VALIDATION_HUMAINE_REQUISE", "Nathan"),
        "geste_commercial": ("depense_reelle", "VALIDATION_HUMAINE_REQUISE", "Nathan"),
    }

    question = "Que faire de la plainte ouverte ?"
    domaines, attendues = ["strategie", "plaintes"], ["m1.digest"]
    faits = faits_du_dossier(cap, question=question, domaines=domaines, attendues=attendues)
    cite = adresse(faits, "m1.digest", ":p0.resultat")
    assert faits[cite] == texte, "le digest est un seul fait textuel, cité tel quel"
    mitigation = {
        "plan_id": "mitigation-plainte",
        "objectif": "Traiter la plainte ouverte avant qu'elle devienne un avis public",
        "porteur": "admin.fictif",
        "echeance": "2026-11-04",
        "resultats_cles": [
            {
                "id": "plainte_close",
                "operateur": "manuel",
                "libelle": "Transfert clos chez M1 (jugé par la personne : M1 ne l'expose qu'en texte)",
            }
        ],
        "sources": [cite],
        "decision_ref": "risque-reputation",
    }
    assert (
        ok(appel(cap, "m9_enregistrer_plan", {"plan": mitigation, "reference": REF, "horodatage": T}))["version"] == 1
    )

    def sortie_de(role):  # SIMULÉ : le tour de modèle, sortie prédéfinie citant le digest réel
        sortie = {"affirmations": [{"id": "A1", "nature": "observation_source", "reference": cite, "valeur": texte}]}
        if role == "conseiller_pdg":
            sortie["affirmations"].append({"id": "H1", "nature": "hypothese", "enonce": "le client attend un rappel"})
            sortie["recommandation"] = {
                "decision": "Rappeler le client et faire décider la reprise par Nathan",
                "refs": ["A1", "H1"],
                "actions": [
                    {"id": "a1", "type": "suivi_interne", "description": "rappeler le client"},
                    {"id": "a2", "type": "contrat", "description": "s'engager sur une reprise des travaux"},
                ],
            }
        return sortie

    ouverture, cloture = conduire_conseil(
        cap, question=question, domaines=domaines, attendues=attendues, sortie_de=sortie_de
    )
    assert cloture["cloture"]["issue"] == "RECOMMANDATION"
    revue, _ = revue_hebdomadaire(cap)
    s = revue["sections_direction"]["sections"]
    decisions = s["decisions_a_prendre"]
    assert decisions["statut"] == "RENSEIGNEE"
    assert decisions["contenu"]["recommandations_a_valider_par_un_humain"] == [
        {
            "session_id": ouverture["session_id"],
            "rapport_id": cloture["cloture"]["rapport_id"],
            "actions": ["a2"],
        }
    ]
    assert [p["plan_id"] for p in s["plan_semaine_suivante"]["contenu"]["plans_a_echeance"]] == ["mitigation-plainte"]
    # Le digest capturé n'y suffit pas : la satisfaction n'a pas de définition chez son propriétaire, c'est NOMMÉ.
    satisfaction = s["clients_satisfaction"]
    assert (
        satisfaction["statut"] == "NON_DISPONIBLE" and "m1.digest : TEMPS_METIER_NON_DECLARE" in satisfaction["manques"]
    )
    assert any("m04-field-ops" in m for m in satisfaction["manques"])
