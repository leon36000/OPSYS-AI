"""PLAN T1.4-m — E2E « réassigner un lead » et « republier le fait de propriété », par la vraie porte d'appareil.

DEFINITION-PRODUIT §9.4 (« ses leads ») et §9.5 (le propriétaire ou son gestionnaire reprend le dossier d'un vendeur).
Avant T1.4-m, `owner` n'était consigné qu'une fois, à la qualification : un vendeur qui part, ou un `owner` saisi de
travers, laissait le lead sans recours ; et les leads qualifiés avant T1.4-k2 n'ont jamais publié `m2.lead_assigne`.

Le scénario est celui d'une équipe de vente, par la même porte que l'app (`PorteAppareil`, la règle du core relue dans
le fork, appliquée au vrai moteur HTTP MCP sur une base temporaire) :

- deux vendeurs (`vendeur.a`, `vendeur.b`), l'admin (Nathan) et un employé (Étienne), personnes et appareils créés par
  les commandes réelles du socle ;
- l'admin qualifie deux leads au vendeur A depuis son téléphone, puis réassigne l'un d'eux au vendeur B ;
- le vendeur B voit le lead, le vendeur A ne le voit plus (liste, total, corps brut, autres outils) ; rejouer le même
  appel ne change rien ; le même vendeur en cible est un refus sans écriture ; l'employé, comme un vendeur, reçoit 403.

Ce que ces tests ne prouvent PAS : le core lui-même (poignée de main, jeton d'appareil, session MCP TypeScript), l'écran
de l'app (`mobile/`), ni ce que M3 fait du fait publié (`tests/test_acces_par_proprietaire.py` tient la chaîne M2, bus,
M3). Données fictives (`fictif: true`).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import m2_revenue_crm.outils as m2_outils
import pytest
from harnais_e2e import Moteur, PorteAppareil, iso
from m2_revenue_crm import assignation, statuts

from opsys import evenements, identite, stockage
from opsys.outils import executer_atomique

REASSIGNER = "m2_reassigner_lead"
REPUBLIER = "m2_republier_assignations"
LISTER = "m2_lister_leads"
TROUVER = "m2_trouver_client_de_lead"
HORODATAGE = "2026-09-29T12:00:00-04:00"
HORLOGE_APPAREIL_DEREGLEE = "2000-01-01T00:00:00+00:00"
ACTION = {"description": "Appeler le client (fictif)", "echeance": "2026-09-05T09:00:00-04:00"}
MOTIF = "Le vendeur A part en congé, le dossier passe au vendeur B."


def _hh(moteur: Moteur) -> str:
    """L'heure de l'appareil pour un appel ordinaire : celle de l'horloge du test."""
    return iso(moteur.horloge.maintenant)


def _m2(moteur: Moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements["m02-revenue-crm"].charger_outils()}


def _ingerer(moteur: Moteur, lead_id: str) -> None:
    contrat = {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": f"Client {lead_id} (fictif)", "courriel": f"{lead_id}@exemple-fictif.test"},
        "type_travaux": "renovation_totale", "ville": "Repentigny", "urgence_declaree": False, "canal": "telephone",
    }
    reponse = executer_atomique(_m2(moteur)["m2_ingerer_lead"], {"contrat": contrat, "horodatage": HORODATAGE})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def _qualifier_depuis_le_telephone(moteur: Moteur, admin: PorteAppareil, lead_id: str, owner: str) -> None:
    reponse = admin.appeler(
        "m2_transitionner_statut",
        {"lead_id": lead_id, "statut_cible": "qualifie", "horodatage": HORODATAGE, "owner": owner,
         "prochaine_action": ACTION},
        cle=f"e2e-qualifier-{lead_id}", horodatage_appareil=_hh(moteur))
    assert reponse.resultat["statut"] == "qualifie"


@pytest.fixture
def vendeurs(moteur, equipe, monkeypatch):
    """Les deux vendeurs et leurs appareils, plus un vendeur désactivé depuis (cible invalide)."""
    moteur.creer_personne("vendeur.a", "Vendeur A (fictif)", ["seller"], monkeypatch)
    moteur.creer_personne("vendeur.b", "Vendeur B (fictif)", ["seller"], monkeypatch)
    moteur.creer_personne("ancien.vendeur", "Ancien Vendeur (fictif)", ["seller"], monkeypatch)
    with stockage.transaction() as cnx:
        identite.activer(cnx, "ancien.vendeur", False)
    return {"a": moteur.appairer("vendeur.a", "seller"), "b": moteur.appairer("vendeur.b", "seller")}


@pytest.fixture
def equipe_de_vente(moteur, equipe, vendeurs):
    """`lead-1` et `lead-2`, qualifiés au vendeur A par l'admin depuis son téléphone (la chaîne réelle : validation au
    départ, propriétaire consigné, fait publié)."""
    for lead_id in ("lead-1", "lead-2"):
        _ingerer(moteur, lead_id)
        _qualifier_depuis_le_telephone(moteur, equipe["admin"], lead_id, "vendeur.a")
    return {**equipe, **vendeurs}


def _liste(porte: PorteAppareil):
    reponse = porte.appeler(LISTER, {"horodatage": HORODATAGE})
    assert reponse.statut == 200 and reponse.metier["accepte"] is True, reponse.corps
    return reponse


def _ids(porte: PorteAppareil) -> list[str]:
    return sorted(lead["lead_id"] for lead in _liste(porte).resultat["leads"])


def _voit(porte: PorteAppareil, lead_id: str) -> bool:
    reponse = porte.appeler(TROUVER, {"lead_id": lead_id})
    assert reponse.statut == 200, reponse.corps
    if reponse.metier["accepte"]:
        return True
    assert reponse.metier["verdict"]["code"] == "REJ-LEAD-NON-ASSIGNE"
    return False


def _refus_403(reponse) -> None:
    assert reponse.statut == 403 and reponse.ok is False, reponse.corps
    assert reponse.corps["error"]["type"] == "tool_call_blocked"
    assert "tool_out_of_scope" in reponse.corps["error"]["message"]


def _args(**plus: Any) -> dict[str, Any]:
    return {"lead_id": "lead-1", "nouveau_proprietaire": "vendeur.b", "motif": MOTIF, "horodatage": HORODATAGE, **plus}


def _fait(lead_id: str, rang: int = 1):
    with stockage.transaction():
        return evenements.charge_publiee("m2.lead_assigne", assignation.identifiant_evenement(lead_id, rang))


def _maillons_de_reassignation() -> list[dict[str, Any]]:
    with stockage.transaction():
        lignes = m2_outils._obtenir_registre().lire()
    return [m for m in lignes if m["type_entree"] == assignation.TYPE_ENTREE]


# ---------------------------------------------------------------------------------------------------------
# Le scénario : l'admin réassigne, B voit, A ne voit plus, le rejeu est sans effet, l'employé reçoit 403
# ---------------------------------------------------------------------------------------------------------
def test_e2e_l_admin_reassigne_b_voit_a_ne_voit_plus_le_rejeu_est_sans_effet_l_employe_recoit_403(
        moteur, equipe_de_vente):
    admin, employe = equipe_de_vente["admin"], equipe_de_vente["employe"]
    a, b = equipe_de_vente["a"], equipe_de_vente["b"]
    assert _ids(a) == ["lead-1", "lead-2"] and _ids(b) == []
    assert _voit(a, "lead-1") and not _voit(b, "lead-1")

    # L'employé n'a pas la portée de l'outil : 403 à la porte d'appareil, comme un vendeur.
    for porte in (employe, a, b):
        _refus_403(porte.appeler(REASSIGNER, _args(), cle="mut-refuse-1", horodatage_appareil=_hh(moteur)))
    assert _maillons_de_reassignation() == []

    # L'admin réassigne `lead-1` au vendeur B, depuis son téléphone.
    avant = moteur.empreinte_etat()
    reassignation = admin.appeler(
        REASSIGNER, _args(horodatage=HORLOGE_APPAREIL_DEREGLEE), cle="mut-reassigner-lead-1",
        horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE)
    assert reassignation.statut == 200 and reassignation.metier["accepte"] is True, reassignation.corps
    assert reassignation.mesure.rejoue is False
    accuse = reassignation.resultat
    assert accuse["rang"] == 2 and (accuse["proprietaire_precedent"], accuse["nouveau_proprietaire"]) == (
        "vendeur.a", "vendeur.b")
    assert (accuse["decide_par"], accuse["decide_role"], accuse["voie"]) == ("nathan", "admin", "appareil")
    assert moteur.empreinte_etat() != avant

    # B voit le lead, A ne le voit plus (liste, total, corps brut, autres outils). `lead-2` est resté à A.
    assert _ids(b) == ["lead-1"] and _ids(a) == ["lead-2"]
    assert _liste(b).resultat["total"] == 1 and _liste(a).resultat["total"] == 1
    assert _voit(b, "lead-1") and not _voit(a, "lead-1")
    brut_a = json.dumps(_liste(a).corps, ensure_ascii=False)
    assert "lead-1" not in brut_a and "vendeur.b" not in brut_a
    proprietaires = {lead["lead_id"]: lead["proprietaire"] for lead in _liste(admin).resultat["leads"]}
    assert proprietaires == {"lead-1": "vendeur.b", "lead-2": "vendeur.a"}
    note = {"lead_id": "lead-1", "resume": "Rappel fait (fictif)", "horodatage": HORODATAGE}
    refuse = a.appeler("m2_enregistrer_interaction", note, cle="mut-note-a", horodatage_appareil=_hh(moteur))
    assert refuse.metier["accepte"] is False and refuse.metier["verdict"]["code"] == "REJ-LEAD-NON-ASSIGNE"
    permis = b.appeler("m2_enregistrer_interaction", note, cle="mut-note-b", horodatage_appareil=_hh(moteur))
    assert permis.resultat["lead_id"] == "lead-1"

    # L'heure du serveur fait foi, jamais celle, déréglée, de l'appareil.
    (maillon,) = _maillons_de_reassignation()
    assert dt.datetime.fromisoformat(maillon["horodatage"]) == moteur.horloge.maintenant
    assert maillon["motif"] == MOTIF and maillon["decide_par"] == "nathan"

    # Le rejeu (même clé) rend la même réponse et ne change RIEN : ni registre, ni événement, ni journal.
    apres = moteur.empreinte_etat()
    rejeu = admin.appeler(
        REASSIGNER, _args(horodatage=HORLOGE_APPAREIL_DEREGLEE), cle="mut-reassigner-lead-1",
        horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE)
    assert rejeu.statut == 200 and rejeu.mesure.rejoue is True and rejeu.metier == reassignation.metier
    assert moteur.empreinte_etat() == apres
    # Un renvoi avec une autre clé est un refus nommé : le lead est déjà à B. Toujours sans écriture.
    autre_cle = admin.appeler(REASSIGNER, _args(), cle="mut-reassigner-lead-1-bis", horodatage_appareil=_hh(moteur))
    assert autre_cle.metier["accepte"] is False and autre_cle.metier["verdict"]["code"] == "REJ-PROPRIETAIRE-INCHANGE"
    assert len(_maillons_de_reassignation()) == 1

    # Le fait de rang 2 est au bus, livrable sans échec ni quarantaine ; le rang 1 n'a pas bougé.
    assert _fait("lead-1", 2) == {
        "lead_id": "lead-1", "proprietaire": "vendeur.b", "horodatage_assignation": maillon["horodatage"], "rang": 2,
        "proprietaire_precedent": "vendeur.a"}
    assert _fait("lead-1")["proprietaire"] == "vendeur.a"
    livraison = moteur.drainer_bus(moteur.horloge.maintenant)
    assert livraison["echecs"] == 0 and livraison["quarantaines"] == 0, livraison


def test_e2e_une_cible_ou_un_motif_invalide_est_un_refus_nomme_sans_aucune_ecriture(moteur, equipe_de_vente):
    admin = equipe_de_vente["admin"]
    avant = moteur.empreinte_etat()
    cas = [
        ({"nouveau_proprietaire": "etienne"}, "REJ-OWNER-INCONNU"),  # un employé
        ({"nouveau_proprietaire": "nathan"}, "REJ-OWNER-INCONNU"),  # le propriétaire, qui n'est pas vendeur
        ({"nouveau_proprietaire": "ancien.vendeur"}, "REJ-OWNER-INCONNU"),  # désactivé
        ({"nouveau_proprietaire": "vendeur.fantome"}, "REJ-OWNER-INCONNU"),
        ({"nouveau_proprietaire": "Vendeur B (fictif)"}, "REJ-OWNER-INCONNU"),  # un nom
        ({"lead_id": "lead-fantome"}, "REJ-LEAD-INCONNU"),
        ({"motif": ""}, "REJ-MOTIF-ABSENT"),
        ({"motif": "congé"}, "REJ-MOTIF-INVALIDE"),
    ]
    for i, (arguments, code) in enumerate(cas):
        reponse = admin.appeler(
            REASSIGNER, _args(**arguments), cle=f"mut-refus-{i}", horodatage_appareil=_hh(moteur))
        assert reponse.statut == 200 and reponse.metier["accepte"] is False, (arguments, reponse.corps)
        assert reponse.metier["verdict"]["code"] == code, arguments
    assert _maillons_de_reassignation() == [] and _fait("lead-1", 2) is None
    # Les refus passent par la file d'idempotence (une ligne par clé) ; ni registre ni événement n'a bougé.
    apres = moteur.empreinte_etat()
    assert apres["registres"] == avant["registres"]
    assert (apres["evenements_sortants"], apres["evenements_recus"]) == (
        avant["evenements_sortants"], avant["evenements_recus"])


def test_e2e_reassigner_deux_fois_puis_revenir_au_premier_vendeur(moteur, equipe_de_vente):
    admin, a, b = equipe_de_vente["admin"], equipe_de_vente["a"], equipe_de_vente["b"]

    for i, cible in enumerate(("vendeur.b", "vendeur.a")):
        reponse = admin.appeler(
            REASSIGNER, _args(nouveau_proprietaire=cible), cle=f"mut-aller-retour-{i}",
            horodatage_appareil=_hh(moteur))
        assert reponse.resultat["rang"] == 2 + i

    assert _ids(a) == ["lead-1", "lead-2"] and _ids(b) == []
    assert [m["rang"] for m in _maillons_de_reassignation()] == [2, 3]
    assert _fait("lead-1", 3)["proprietaire"] == "vendeur.a" and _fait("lead-1", 2)["proprietaire"] == "vendeur.b"
    livraison = moteur.drainer_bus(moteur.horloge.maintenant)
    assert livraison["echecs"] == 0 and livraison["quarantaines"] == 0, livraison


# ---------------------------------------------------------------------------------------------------------
# La republication des faits d'avant T1.4-k2
# ---------------------------------------------------------------------------------------------------------
def test_e2e_l_admin_republie_le_fait_d_un_lead_qualifie_avant_t1_4_k2_le_rejeu_est_sans_effet_l_employe_recoit_403(
        moteur, equipe_de_vente):
    """Un lead qualifié par l'ancien code n'a que son maillon : aucun fait au bus, donc M3 ne reconnaît pas son
    vendeur."""
    admin, employe = equipe_de_vente["admin"], equipe_de_vente["employe"]
    a, b = equipe_de_vente["a"], equipe_de_vente["b"]
    _ingerer(moteur, "lead-ancien")
    with stockage.transaction():
        accuse, verdict = statuts.transitionner(
            "lead-ancien", "qualifie", m2_outils._obtenir_registre(), "2026-09-01T09:05:00-04:00",
            owner="vendeur.a", prochaine_action=ACTION)
    assert verdict is None and accuse["statut"] == "qualifie"
    assert _fait("lead-ancien") is None and _voit(a, "lead-ancien"), "M2 le montre à A, mais le bus n'a pas son fait"

    for porte in (employe, a, b):
        _refus_403(porte.appeler(REPUBLIER, {}, cle="mut-republier-refuse", horodatage_appareil=_hh(moteur)))
    assert _fait("lead-ancien") is None

    republication = admin.appeler(
        REPUBLIER, {}, cle="mut-republier-1", horodatage_appareil=_hh(moteur))
    assert republication.statut == 200 and republication.mesure.rejoue is False, republication.corps
    assert republication.resultat == {
        "faits_republies": 1, "faits_deja_publies": 2, "leads_republies": ["lead-ancien"], "leads_tronques": False}
    assert _fait("lead-ancien") == {
        "lead_id": "lead-ancien", "proprietaire": "vendeur.a", "horodatage_assignation": "2026-09-01T09:05:00-04:00"}

    # Le rejeu (même clé) ne change rien ; un second appel (autre clé) ne republie plus rien.
    apres = moteur.empreinte_etat()
    rejeu = admin.appeler(REPUBLIER, {}, cle="mut-republier-1", horodatage_appareil=_hh(moteur))
    assert rejeu.mesure.rejoue is True and rejeu.metier == republication.metier
    assert moteur.empreinte_etat() == apres
    second = admin.appeler(REPUBLIER, {}, cle="mut-republier-2", horodatage_appareil=_hh(moteur))
    assert second.resultat["faits_republies"] == 0 and second.resultat["faits_deja_publies"] == 3
    apres_le_second = moteur.empreinte_etat()
    assert apres_le_second["evenements_sortants"] == apres["evenements_sortants"]
    assert apres_le_second["registres"] == apres["registres"]
    livraison = moteur.drainer_bus(moteur.horloge.maintenant)
    assert livraison["echecs"] == 0 and livraison["quarantaines"] == 0, livraison
