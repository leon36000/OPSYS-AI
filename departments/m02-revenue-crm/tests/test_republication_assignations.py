"""PLAN T1.4-m (partie 2) : `m2_republier_assignations` sur une base qui contient des leads qualifiés AVANT T1.4-k2.

Avant T1.4-k2, la qualification n'écrivait que le maillon `transition_statut` : aucun fait `m2.lead_assigne` au bus.
M3 ne reconnaît donc pas le propriétaire de ces leads, et leur vendeur ne voit pas leurs devis (fail-closed). Ces tests
reconstituent une telle base avec ce que faisait l'ancien code (`statuts.transitionner` sur le registre durable, sans
publication), puis passent par le VRAI outil : le fait de chaque assignation du registre est remis au bus avec le MÊME
identifiant et la MÊME charge que la publication d'origine, sans doublon au second appel, sans toucher au registre.
Données fictives (AGENTS.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m2_revenue_crm import acces, assignation, outils, statuts
from sqlalchemy import select

from opsys import contexte, evenements, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS, META

FICTIF = True

M2 = Path(__file__).resolve().parents[1]
NATHAN = contexte.IdentiteAppelante(personne="nathan", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
CODE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"

H0 = "2026-09-01T09:00:00-04:00"
H1 = "2026-09-01T09:05:00-04:00"
H2 = "2026-09-02T10:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
MOTIF = "Le vendeur part en congé, le dossier passe à un collègue."


# -- installation ------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m2-republication.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        outils.reinitialiser_registre()
        stockage.liberer()


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", "mot-de-passe-vendeur-deux", ["seller"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in outils.outils()}


def _contrat(lead_id: str) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }


def _qualifier_comme_avant_t1_4_k2(lead_id: str, owner: str) -> None:
    """Ce que l'ancien code faisait à la qualification : le maillon de transition, et RIEN au bus."""
    with stockage.transaction():
        accuse, verdict = statuts.transitionner(
            lead_id, "qualifie", outils._obtenir_registre(), H1, owner=owner, prochaine_action=ACTION)
    assert verdict is None and accuse["statut"] == "qualifie", verdict


@pytest.fixture
def base_d_avant(personnes):
    """Sept leads : quatre qualifiés sans fait (dont un perdu ensuite et un `owner` en texte libre), un qualifié PAR
    l'outil actuel (son fait existe), un dont la réassignation a publié le rang 2 alors que son rang 1 n'a jamais été
    publié, et un lead `nouveau` sans propriétaire."""
    tous = ("ancien-un", "ancien-deux", "ancien-libre", "ancien-perdu", "recent", "ancien-reassigne", "nouveau")
    for lead_id in tous:
        assert outils.ingerer_lead(_contrat(lead_id), H0)["accepte"] is True
    _qualifier_comme_avant_t1_4_k2("ancien-un", "vendeur.un")
    _qualifier_comme_avant_t1_4_k2("ancien-deux", "vendeur.deux")
    _qualifier_comme_avant_t1_4_k2("ancien-libre", "Marc Tremblay")
    _qualifier_comme_avant_t1_4_k2("ancien-perdu", "vendeur.un")
    assert outils.transitionner_statut("ancien-perdu", "perdu", H2, motif="client parti chez un concurrent")["accepte"]
    assert outils.transitionner_statut(
        "recent", "qualifie", H1, owner="vendeur.deux", prochaine_action=ACTION)["accepte"] is True
    _qualifier_comme_avant_t1_4_k2("ancien-reassigne", "vendeur.un")
    with contexte.appele_par_appareil(NATHAN):
        reponse = executer_atomique(
            {o.nom: o for o in outils.outils()}["m2_reassigner_lead"],
            {"lead_id": "ancien-reassigne", "nouveau_proprietaire": "vendeur.deux", "motif": MOTIF, "horodatage": H2})
    assert reponse["resultat"]["accepte"] is True, reponse


# -- aides --------------------------------------------------------------------------------------------
def _republier(par_nom, identite_appelante=NATHAN):
    if identite_appelante is None:
        return executer_atomique(par_nom["m2_republier_assignations"], {})
    with contexte.appele_par_appareil(identite_appelante):
        return executer_atomique(par_nom["m2_republier_assignations"], {})


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _verdict(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _instantane_base():
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


def _fait(lead_id, rang=1):
    with stockage.transaction():
        return evenements.charge_publiee("m2.lead_assigne", assignation.identifiant_evenement(lead_id, rang))


def _ids_des_evenements():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m2.lead_assigne"))
        return sorted(ligne.evenement_id for ligne in lignes)


def _registre():
    with stockage.transaction():
        return outils._obtenir_registre().lire()


def _proprietaire_lu_au_bus(lead_id):
    """Ce qu'un consommateur du bus lit (M3, sans importer M2) : le rang 1, puis les rangs 2, 3... jusqu'au premier
    absent ; le propriétaire courant est celui du dernier fait lu."""
    courant = None
    for rang in range(1, 50):
        charge = _fait(lead_id, rang)
        if charge is None:
            if rang == 1:
                continue  # le rang 1 peut manquer (jamais publié) alors qu'un rang 2 existe
            break
        courant = charge["proprietaire"]
    return courant


# =========================================================================================
# 1. La base d'avant : les faits manquent
# =========================================================================================
def test_la_base_d_avant_n_a_pas_le_fait_de_ses_leads_qualifies_sans_l_outil(base_d_avant):
    for lead_id in ("ancien-un", "ancien-deux", "ancien-libre", "ancien-perdu", "ancien-reassigne"):
        assert _fait(lead_id) is None, lead_id
    assert _fait("recent") is not None, "un lead qualifié par l'outil actuel a son fait"
    assert _fait("ancien-reassigne", 2) is not None
    assert _proprietaire_lu_au_bus("ancien-un") is None, "M3 ne reconnaît pas ce propriétaire : ses devis sont refusés"


# =========================================================================================
# 2. La republication
# =========================================================================================
def test_l_admin_republie_le_fait_de_chaque_assignation_qui_n_est_pas_au_bus(par_nom, base_d_avant):
    resultat = _accepte(_republier(par_nom))

    # 7 faits au registre : 5 qualifications d'avant + `recent` + 2 rangs d'`ancien-reassigne` = sept ; deux existaient.
    assert resultat["faits_republies"] == 5 and resultat["faits_deja_publies"] == 2
    assert resultat["leads_republies"] == ["ancien-un", "ancien-deux", "ancien-libre", "ancien-perdu",
                                           "ancien-reassigne"]
    assert resultat["leads_tronques"] is False
    assert _ids_des_evenements() == sorted([
        "m2-lead-assigne-ancien-un", "m2-lead-assigne-ancien-deux", "m2-lead-assigne-ancien-libre",
        "m2-lead-assigne-ancien-perdu", "m2-lead-assigne-recent", "m2-lead-assigne-ancien-reassigne",
        "m2-lead-reassigne-2-ancien-reassigne"])


def test_le_fait_republie_est_octet_pour_octet_celui_que_la_qualification_aurait_publie(par_nom, base_d_avant):
    _accepte(_republier(par_nom))

    for lead_id, proprietaire in (("ancien-un", "vendeur.un"), ("ancien-deux", "vendeur.deux"),
                                  ("ancien-perdu", "vendeur.un"), ("ancien-libre", "Marc Tremblay")):
        assert _fait(lead_id) == {"lead_id": lead_id, "proprietaire": proprietaire, "horodatage_assignation": H1}
    # Un lead qualifié par l'outil actuel a la même forme : rien n'a changé pour lui.
    assert _fait("recent") == {"lead_id": "recent", "proprietaire": "vendeur.deux", "horodatage_assignation": H1}
    # Le rang 1 d'un lead réassigné dit celui de la qualification, le rang 2 celui de la réassignation.
    assert _fait("ancien-reassigne") == {
        "lead_id": "ancien-reassigne", "proprietaire": "vendeur.un", "horodatage_assignation": H1}
    assert _fait("ancien-reassigne", 2)["proprietaire"] == "vendeur.deux"


def test_un_consommateur_du_bus_lit_desormais_le_bon_proprietaire_y_compris_apres_reassignation(par_nom, base_d_avant):
    _accepte(_republier(par_nom))

    assert _proprietaire_lu_au_bus("ancien-un") == "vendeur.un"
    assert _proprietaire_lu_au_bus("ancien-deux") == "vendeur.deux"
    assert _proprietaire_lu_au_bus("ancien-reassigne") == "vendeur.deux", "le plus grand rang gagne"
    assert _proprietaire_lu_au_bus("recent") == "vendeur.deux"
    assert _proprietaire_lu_au_bus("nouveau") is None, "un lead nouveau n'a pas de propriétaire : aucun fait"
    registre = outils._obtenir_registre()
    for lead_id in ("ancien-un", "ancien-deux", "ancien-reassigne", "recent"):
        assert _proprietaire_lu_au_bus(lead_id) == acces.proprietaire_du_lead(registre, lead_id)


def test_la_republication_est_idempotente_un_second_appel_ne_publie_rien(par_nom, base_d_avant):
    _accepte(_republier(par_nom))
    apres_le_premier = _instantane_base()

    resultat = _accepte(_republier(par_nom))

    assert resultat["faits_republies"] == 0 and resultat["faits_deja_publies"] == 7
    assert resultat["leads_republies"] == []
    assert _instantane_base() == apres_le_premier, "ni événement, ni registre, ni rien d'autre n'a bougé"


def test_republier_ne_touche_jamais_au_registre(par_nom, base_d_avant):
    avant = _registre()

    _accepte(_republier(par_nom))

    assert _registre() == avant
    with stockage.transaction():
        outils._obtenir_registre().assert_chaine()


def test_sans_faits_manquants_l_outil_ne_publie_rien(par_nom, personnes):
    assert outils.ingerer_lead(_contrat("l1"), H0)["accepte"] is True
    assert outils.transitionner_statut("l1", "qualifie", H1, owner="vendeur.un", prochaine_action=ACTION)["accepte"]
    avant = _instantane_base()

    resultat = _accepte(_republier(par_nom))

    assert resultat == {"faits_republies": 0, "faits_deja_publies": 1, "leads_republies": [], "leads_tronques": False}
    assert _instantane_base() == avant


def test_une_base_sans_lead_qualifie_republie_zero(par_nom, personnes):
    assert _accepte(_republier(par_nom)) == {
        "faits_republies": 0, "faits_deja_publies": 0, "leads_republies": [], "leads_tronques": False}


def test_un_lead_dont_la_reassignation_n_a_pas_de_fait_recoit_ses_deux_faits_et_n_est_cite_qu_une_fois(
        par_nom, personnes):
    """Une réassignation consignée au registre mais jamais publiée (le rang 1 manque aussi) : les deux faits sont
    republiés, chacun sous son identifiant, et le lead est cité une fois."""
    assert outils.ingerer_lead(_contrat("ancien-x"), H0)["accepte"] is True
    _qualifier_comme_avant_t1_4_k2("ancien-x", "vendeur.un")
    with stockage.transaction():
        accuse, verdict = assignation.reassigner(
            outils._obtenir_registre(), "ancien-x", "vendeur.deux", MOTIF, H2, "nathan", "admin", "appareil")
    assert verdict is None and accuse["rang"] == 2
    assert _fait("ancien-x") is None and _fait("ancien-x", 2) is None

    resultat = _accepte(_republier(par_nom))

    assert resultat["faits_republies"] == 2 and resultat["faits_deja_publies"] == 0
    assert resultat["leads_republies"] == ["ancien-x"], "cité une seule fois malgré ses deux faits"
    assert _fait("ancien-x") == {"lead_id": "ancien-x", "proprietaire": "vendeur.un", "horodatage_assignation": H1}
    assert _fait("ancien-x", 2) == {
        "lead_id": "ancien-x", "proprietaire": "vendeur.deux", "horodatage_assignation": H2, "rang": 2,
        "proprietaire_precedent": "vendeur.un"}
    assert _proprietaire_lu_au_bus("ancien-x") == "vendeur.deux"


def test_une_reassignation_apres_la_republication_donne_le_rang_suivant_sans_collision(par_nom, base_d_avant):
    _accepte(_republier(par_nom))
    with contexte.appele_par_appareil(NATHAN):
        reponse = executer_atomique(par_nom["m2_reassigner_lead"], {
            "lead_id": "ancien-un", "nouveau_proprietaire": "vendeur.deux", "motif": MOTIF, "horodatage": H2})

    assert _accepte(reponse)["rang"] == 2
    assert _proprietaire_lu_au_bus("ancien-un") == "vendeur.deux"
    assert _accepte(_republier(par_nom))["faits_republies"] == 0


def _base_de_leads_sans_fait(nombre):
    for i in range(nombre):
        lead_id = f"l{i:02d}"
        assert outils.ingerer_lead(_contrat(lead_id), H0)["accepte"] is True
        _qualifier_comme_avant_t1_4_k2(lead_id, "vendeur.un")


def test_la_reponse_cite_au_plus_cinquante_leads_et_compte_tous_les_faits(par_nom, personnes, monkeypatch):
    """La borne de 50 est une constante documentée ; on la baisse pour l'exercer sans fabriquer cinquante leads."""
    assert outils._LEADS_CITES_MAX == 50
    monkeypatch.setattr(outils, "_LEADS_CITES_MAX", 3)
    _base_de_leads_sans_fait(5)

    resultat = _accepte(_republier(par_nom))

    assert resultat["faits_republies"] == 5 and resultat["faits_deja_publies"] == 0
    assert resultat["leads_republies"] == ["l00", "l01", "l02"] and resultat["leads_tronques"] is True
    assert len(_ids_des_evenements()) == 5, "tous les faits sont publiés, la réponse en cite seulement trois"
    assert _accepte(_republier(par_nom))["faits_republies"] == 0


def test_la_reponse_reste_sous_la_limite_de_sortie_du_socle(par_nom, personnes, monkeypatch):
    """Un budget de sortie serré, JUSTE de la taille de trois identifiants : la réponse en cite trois (la borne est
    incluse), dit qu'elle est tronquée et garde ses comptes."""
    vide = {"faits_republies": 6, "faits_deja_publies": 0, "leads_republies": [], "leads_tronques": False}
    avec_trois = {**vide, "leads_republies": ["l00", "l01", "l02"]}
    budget = len(json.dumps(avec_trois, ensure_ascii=False))
    monkeypatch.setattr(outils, "BUDGET_SORTIE", budget)
    _base_de_leads_sans_fait(6)

    resultat = _accepte(_republier(par_nom))

    assert resultat["faits_republies"] == 6 and resultat["leads_tronques"] is True
    assert resultat["leads_republies"] == ["l00", "l01", "l02"]
    assert len(json.dumps({**resultat, "leads_tronques": False}, ensure_ascii=False)) == budget


def test_sans_troncature_tous_les_leads_republies_sont_cites_une_fois(par_nom, personnes):
    _base_de_leads_sans_fait(4)

    resultat = _accepte(_republier(par_nom))

    assert resultat["leads_republies"] == ["l00", "l01", "l02", "l03"] and resultat["leads_tronques"] is False


# =========================================================================================
# 3. Qui peut la lancer, et dans quel état
# =========================================================================================
def test_l_outil_est_une_ecriture_n3_reservee_a_l_admin(par_nom):
    outil = par_nom["m2_republier_assignations"]

    assert outil.autonomie is Autonomie.T1 and outil.niveau_effectif is Niveau.N3
    assert outil.frontiere_humaine is False
    assert outil.roles_appareil == acces.ROLES_ADMIN == frozenset({"admin"})
    assert outil.parametres["properties"] == {} and outil.parametres["additionalProperties"] is False
    assert outil.fonction is outils.republier_assignations and len(outil.description) <= 1024


def test_l_outil_ne_prend_aucun_argument(par_nom, base_d_avant):
    avant = _instantane_base()
    with contexte.appele_par_appareil(NATHAN):
        reponse = executer_atomique(par_nom["m2_republier_assignations"], {"lead_id": "ancien-un"})

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [VENDEUR_UN, MARC], ids=["vendeur", "employe"])
def test_un_vendeur_ou_un_employe_authentifie_ne_republie_pas(par_nom, base_d_avant, appelante):
    avant = _instantane_base()

    reponse = _republier(par_nom, appelante)

    assert _verdict(reponse)["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [
    contexte.IdentiteAppelante(personne="inconnu.fictif", role="admin"),
    contexte.IdentiteAppelante(personne="vendeur.un", role="admin"),  # rôle jamais porté
], ids=["personne-inconnue", "role-jamais-porte"])
def test_une_identite_non_confirmee_en_base_est_refusee(par_nom, base_d_avant, appelante):
    avant = _instantane_base()

    assert _verdict(_republier(par_nom, appelante))["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


def test_l_agent_sans_identite_d_appareil_peut_la_lancer_c_est_une_reparation_idempotente(par_nom, base_d_avant):
    resultat = _accepte(_republier(par_nom, None))

    assert resultat["faits_republies"] == 5


def test_hors_stockage_durable_il_n_y_a_pas_de_bus_et_l_outil_le_dit(par_nom, personnes):
    outils.reinitialiser_registre()

    verdict = _verdict(_republier(par_nom, None))

    assert verdict["code"] == "REJ-BUS-INDISPONIBLE" and "durable" in verdict["detail"]


def test_l_appareil_qui_renvoie_la_meme_cle_rejoue_la_reponse_sans_republier_deux_fois(personnes, base_d_avant):
    dep = lire_manifeste(M2)
    capacites = Capacites({dep.id: dep}, stockage.transaction, memoire=False)
    meta = idempotence.Meta(cle="mut-republier-1", appareil="tel-admin-fictif-1",
                            horodatage_appareil="2026-09-29T10:15:00-04:00")

    def appel():
        with contexte.appele_par_appareil(NATHAN):
            return capacites.appeler("m2_republier_assignations", {}, meta)

    premiere = appel()
    apres_la_premiere = _instantane_base()
    seconde = appel()

    assert premiere["ok"] is True and premiere["resultat"]["resultat"]["faits_republies"] == 5
    assert premiere["rejoue"] is False and seconde["rejoue"] is True and seconde["resultat"] == premiere["resultat"]
    assert _instantane_base() == apres_la_premiere
