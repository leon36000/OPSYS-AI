"""PLAN T1.4-k2 : la personne authentifiée d'un appel d'appareil décide, pas les arguments.

Avant T1.4-k2, `m2_enregistrer_interaction` prenait `auteur` de l'appelant, et les six outils M2 ouverts
au vendeur (`roles_appareil`) lui montraient tous les leads. Ces tests passent par les VRAIS outils
(`m2_revenue_crm.outils.outils()`, registre durable adossé à une base SQLite migrée), appelés comme en
production (`executer_atomique`), avec de vraies personnes créées par `opsys.identite`. Chaque refus est
nommé et prouvé SANS écriture (toutes les tables de la base comparées avant et après). Données fictives
(AGENTS.md).

La propriété d'un lead est l'`owner` de sa qualification (elle existait déjà) : rien n'est déduit d'un
autre champ. `test_acces_pur` couvre le module pur sans base.
"""

from __future__ import annotations

import contextlib

import pytest
from m2_revenue_crm import acces, outils, registre, statuts, verdicts
from sqlalchemy import select

from opsys import contexte, evenements, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS, META

FICTIF = True

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")

CODE_NON_ASSIGNE = "REJ-LEAD-NON-ASSIGNE"
CODE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"
CODE_DIFFERENTE = "REJ-IDENTITE-FOURNIE-DIFFERENTE"
CODE_OWNER_INCONNU = "REJ-OWNER-INCONNU"

H0 = "2026-09-01T09:00:00-04:00"
H1 = "2026-09-01T09:05:00-04:00"
H2 = "2026-09-02T10:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}


# -- installation ------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, avec le registre de M2 sur le stockage DURABLE (jamais la mémoire)."""
    url = f"sqlite:///{tmp_path / 'opsys-m2-acces.db'}"
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
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", "mot-de-passe-vendeur-deux", ["seller"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(
            cnx, "ancien.vendeur", "Ancien Vendeur", "mot-de-passe-ancien-123", ["seller"], actif=False)


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in outils.outils()}


def _contrat(lead_id: str, contact: dict | None = None) -> dict:
    return {
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": contact or {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "telephone",
    }


CONTACT_PARTAGE = {"nom": "Cliente Partagée", "courriel": "partagee@example.test"}


@pytest.fixture
def leads(personnes):
    """Préparation par la voie des agents (sans identité d'appareil) : `lead-un` à `vendeur.un` et
    `lead-deux` à `vendeur.deux` (MÊME client), `lead-nouveau` sans propriétaire, `lead-autre` à
    `vendeur.deux` (autre client)."""
    for lead_id, contact in (("lead-un", CONTACT_PARTAGE), ("lead-deux", CONTACT_PARTAGE),
                             ("lead-nouveau", None), ("lead-autre", None)):
        assert outils.ingerer_lead(_contrat(lead_id, contact), H0)["accepte"] is True
    for lead_id, owner in (("lead-un", "vendeur.un"), ("lead-deux", "vendeur.deux"),
                           ("lead-autre", "vendeur.deux")):
        reponse = outils.transitionner_statut(lead_id, "qualifie", H1, owner=owner, prochaine_action=ACTION)
        assert reponse["accepte"] is True, reponse
    for lead_id, auteur in (("lead-un", "vendeur.un"), ("lead-deux", "vendeur.deux")):
        assert outils.enregistrer_interaction(lead_id, auteur, f"Note de {auteur}", H1)["accepte"] is True


# -- aides --------------------------------------------------------------------------------------------
@contextlib.contextmanager
def _appareil(identite_appelante):
    """Ce que `serveur_mcp.appeler_outil` et `Capacites.appeler` posent pour un appel d'appareil ; sans
    identité : un appel d'agent."""
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _verdict(reponse):
    """Verdict d'un refus : `ok` reste vrai (l'outil a répondu), `accepte` est faux."""
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _instantane_base():
    """Le contenu de TOUTES les tables : un refus qui écrirait quoi que ce soit (registre, événement, trace,
    journal, idempotence...) changerait cet instantané."""
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


def _interactions(lead_id):
    return [m for m in outils._obtenir_registre().lire()
            if m.get("type_entree") == "interaction" and m.get("lead_id") == lead_id]


# Outils de lecture ou d'écriture qui portent un lead, avec les arguments d'un appel valide sur `lead_id`.
_OUTILS_PAR_LEAD = {
    "m2_transitionner_statut": lambda lead_id: {"lead_id": lead_id, "statut_cible": "perdu", "horodatage": H2,
                                                "motif": "client parti chez un concurrent"},
    "m2_enregistrer_interaction": lambda lead_id: {"lead_id": lead_id, "resume": "Rappel fait", "horodatage": H2},
    "m2_trouver_client_de_lead": lambda lead_id: {"lead_id": lead_id},
    "m2_evaluer_readiness": lambda lead_id: {"lead_id": lead_id, "horodatage": H2},
    "m2_suggerer_prochaine_action": lambda lead_id: {"lead_id": lead_id, "horodatage": H2},
}


# =========================================================================================
# 1. `auteur` vient de la personne authentifiée
# =========================================================================================
def test_sans_identite_d_appareil_auteur_reste_celui_de_l_appelant(par_nom, leads):
    """La voie des agents est inchangée : `auteur` est celui de l'appelant, obligatoire."""
    reponse = _appeler(par_nom, "m2_enregistrer_interaction",
                       {"lead_id": "lead-un", "auteur": "Alice", "resume": "Appel de suivi", "horodatage": H2})

    assert _accepte(reponse)["lead_id"] == "lead-un"
    assert _interactions("lead-un")[-1]["auteur"] == "Alice"


def test_un_agent_sans_auteur_obtient_un_verdict_nomme_pas_un_refus_de_schema(par_nom, leads):
    avant = _instantane_base()

    reponse = _appeler(par_nom, "m2_enregistrer_interaction",
                       {"lead_id": "lead-un", "resume": "Appel de suivi", "horodatage": H2})

    assert _verdict(reponse)["code"] == "REJ-CHAMP-VIDE"
    assert _instantane_base() == avant


def test_le_schema_n_exige_plus_auteur_mais_garde_resume_et_horodatage(par_nom):
    schema = par_nom["m2_enregistrer_interaction"].parametres
    assert set(schema["required"]) == {"lead_id", "resume", "horodatage"}
    assert "auteur" in schema["properties"]


@pytest.mark.parametrize("appelante,attendu", [(VENDEUR_UN, "vendeur.un"), (ADMIN, "admin.fictif")],
                         ids=["vendeur", "admin"])
def test_auteur_omis_vaut_la_personne_authentifiee(par_nom, leads, appelante, attendu):
    reponse = _appeler(par_nom, "m2_enregistrer_interaction",
                       {"lead_id": "lead-un", "resume": "Note depuis l'app", "horodatage": H2}, appelante)

    _accepte(reponse)
    assert _interactions("lead-un")[-1]["auteur"] == attendu


def test_auteur_egal_a_la_personne_est_accepte_aux_espaces_pres(par_nom, leads):
    _accepte(_appeler(par_nom, "m2_enregistrer_interaction",
                      {"lead_id": "lead-un", "auteur": " vendeur.un ", "resume": "Note", "horodatage": H2},
                      VENDEUR_UN))

    assert _interactions("lead-un")[-1]["auteur"] == "vendeur.un"


@pytest.mark.parametrize("auteur_fourni", ["vendeur.deux", "Alice", "system:m3", "", "   "],
                         ids=["un-collegue", "un-nom", "systeme", "vide", "espaces"])
@pytest.mark.parametrize("appelante", [VENDEUR_UN, ADMIN], ids=["vendeur", "admin"])
def test_un_auteur_different_est_refuse_jamais_remplace(par_nom, leads, appelante, auteur_fourni):
    """Ni un autre nom, ni une écriture `system:*`, ni un champ vide : refus nommé, y compris pour l'admin,
    et rien n'est écrit (l'historique ne nomme jamais un auteur qui n'a rien écrit)."""
    avant = _instantane_base()

    reponse = _appeler(par_nom, "m2_enregistrer_interaction",
                       {"lead_id": "lead-un", "auteur": auteur_fourni, "resume": "Note", "horodatage": H2},
                       appelante)

    assert _verdict(reponse)["code"] == CODE_DIFFERENTE
    assert _instantane_base() == avant


# =========================================================================================
# 2. Un vendeur ne voit et n'agit que sur ses leads
# =========================================================================================
@pytest.mark.parametrize("nom_outil", sorted(set(_OUTILS_PAR_LEAD) - {"m2_transitionner_statut"}))
def test_un_vendeur_agit_sur_son_lead(par_nom, leads, nom_outil):
    reponse = _appeler(par_nom, nom_outil, _OUTILS_PAR_LEAD[nom_outil]("lead-un"), VENDEUR_UN)

    assert reponse["ok"] is True, reponse
    if reponse["resultat"]["accepte"] is False:  # readiness : un verdict de gate, jamais le refus de propriété
        assert reponse["resultat"]["verdict"]["code"] != CODE_NON_ASSIGNE
    else:
        assert reponse["resultat"]["accepte"] is True


def test_un_vendeur_transitionne_son_lead(par_nom, leads):
    reponse = _appeler(par_nom, "m2_transitionner_statut", _OUTILS_PAR_LEAD["m2_transitionner_statut"]("lead-un"),
                       VENDEUR_UN)

    assert _accepte(reponse)["statut"] == "perdu"


@pytest.mark.parametrize("nom_outil", sorted(_OUTILS_PAR_LEAD))
def test_lead_d_un_autre_sans_proprietaire_ou_inconnu_donnent_le_meme_refus(par_nom, leads, nom_outil):
    """« D'un autre » (`lead-deux`), « sans propriétaire » (`lead-nouveau`) et « inconnu » (`lead-fantome`) :
    le MÊME verdict, mot pour mot, et aucune écriture. Un vendeur ne peut pas sonder quels leads existent."""
    refus = []
    for lead_id in ("lead-deux", "lead-nouveau", "lead-fantome"):
        avant = _instantane_base()
        refus.append(_verdict(_appeler(par_nom, nom_outil, _OUTILS_PAR_LEAD[nom_outil](lead_id), VENDEUR_UN)))
        assert _instantane_base() == avant, f"{nom_outil} sur {lead_id} a écrit malgré le refus"

    assert refus[0]["code"] == CODE_NON_ASSIGNE
    assert refus[0] == refus[1] == refus[2]
    assert "lead-deux" not in str(refus[0]) and "vendeur.deux" not in str(refus[0])


def test_le_proprietaire_est_l_owner_de_la_qualification_pas_l_auteur_des_notes(par_nom, leads):
    """`vendeur.deux` a écrit une note sur `lead-un`... par la voie des agents : cela ne lui donne aucun droit.
    La propriété ne se déduit d'aucun autre champ que `owner`."""
    outils.enregistrer_interaction("lead-un", "vendeur.deux", "Note d'un collègue", H2)

    reponse = _appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": "lead-un"}, VENDEUR_DEUX)

    assert _verdict(reponse)["code"] == CODE_NON_ASSIGNE


def test_l_admin_voit_et_agit_sur_tous_les_leads(par_nom, leads):
    for lead_id in ("lead-un", "lead-deux", "lead-nouveau"):
        reponse = _appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": lead_id}, ADMIN)
        assert _accepte(reponse)["lead_id"] == lead_id
    _accepte(_appeler(par_nom, "m2_enregistrer_interaction",
                      {"lead_id": "lead-deux", "resume": "Point avec le vendeur", "horodatage": H2}, ADMIN))
    assert _accepte(_appeler(par_nom, "m2_suggerer_prochaine_action",
                             {"lead_id": "lead-nouveau", "horodatage": H2}, ADMIN))["lead_id"] == "lead-nouveau"


def test_sans_identite_d_appareil_aucun_filtre_par_proprietaire(par_nom, leads):
    """La voie des agents et des consommateurs garde l'accès complet (docs/architecture/ROLES.md)."""
    _accepte(_appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": "lead-deux"}))
    _accepte(_appeler(par_nom, "m2_enregistrer_interaction",
                      {"lead_id": "lead-nouveau", "auteur": "Alice", "resume": "Suivi", "horodatage": H2}))


# -- Client 360 -----------------------------------------------------------------------------------------
def test_client_360_un_vendeur_ne_voit_que_ses_opportunites_et_leurs_interactions(par_nom, leads):
    lien = _accepte(_appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": "lead-un"}, VENDEUR_UN))
    client_id = lien["client_id"]

    vue_vendeur = _accepte(_appeler(par_nom, "m2_obtenir_client_360", {"client_id": client_id}, VENDEUR_UN))
    vue_admin = _accepte(_appeler(par_nom, "m2_obtenir_client_360", {"client_id": client_id}, ADMIN))

    assert [o["lead_id"] for o in vue_vendeur["opportunites"]] == ["lead-un"]
    assert [i["lead_id"] for i in vue_vendeur["interactions_recentes"]] == ["lead-un"]
    assert "vendeur.deux" not in str(vue_vendeur)
    assert vue_vendeur["contact"] == CONTACT_PARTAGE
    assert sorted(o["lead_id"] for o in vue_admin["opportunites"]) == ["lead-deux", "lead-un"]
    assert {i["lead_id"] for i in vue_admin["interactions_recentes"]} == {"lead-deux", "lead-un"}


def test_client_360_sans_opportunite_du_vendeur_donne_le_meme_refus_qu_un_client_inconnu(par_nom, leads):
    client_de_deux = _accepte(
        _appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": "lead-autre"}, ADMIN))["client_id"]
    avant = _instantane_base()

    d_un_autre = _verdict(_appeler(par_nom, "m2_obtenir_client_360", {"client_id": client_de_deux}, VENDEUR_UN))
    inconnu = _verdict(_appeler(par_nom, "m2_obtenir_client_360", {"client_id": "client-fantome"}, VENDEUR_UN))

    assert d_un_autre["code"] == CODE_NON_ASSIGNE
    assert d_un_autre == inconnu
    assert _instantane_base() == avant


def test_client_360_l_admin_et_l_agent_gardent_le_verdict_d_avant_pour_un_client_inconnu(par_nom, leads):
    for appelante in (ADMIN, None):
        verdict = _verdict(_appeler(par_nom, "m2_obtenir_client_360", {"client_id": "client-fantome"}, appelante))
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"


# =========================================================================================
# 3. Identité non confirmée en base : refus avant toute lecture ou écriture
# =========================================================================================
_APPELS_PAR_OUTIL = {
    **{nom: fabrique("lead-un") for nom, fabrique in _OUTILS_PAR_LEAD.items()},
    "m2_obtenir_client_360": {"client_id": "n-importe-lequel"},
}


@pytest.fixture(params=[
    pytest.param(contexte.IdentiteAppelante(personne="inconnu.fictif", role="seller"), id="personne-inconnue"),
    pytest.param(contexte.IdentiteAppelante(personne="ancien.vendeur", role="seller"), id="personne-desactivee"),
    pytest.param(contexte.IdentiteAppelante(personne="vendeur.un", role="admin"), id="role-jamais-porte"),
    pytest.param(MARC, id="employe-sans-portee"),
])
def identite_invalide(request):
    return request.param


@pytest.mark.parametrize("nom_outil", sorted(_APPELS_PAR_OUTIL))
def test_une_identite_non_confirmee_est_refusee_avant_tout(par_nom, leads, identite_invalide, nom_outil):
    avant = _instantane_base()

    reponse = _appeler(par_nom, nom_outil, _APPELS_PAR_OUTIL[nom_outil], identite_invalide)

    assert _verdict(reponse)["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


def test_un_role_retire_depuis_l_appairage_est_refuse_avec_le_meme_jeton(par_nom, leads):
    arguments = {"lead_id": "lead-un", "resume": "Note", "horodatage": H2}
    _accepte(_appeler(par_nom, "m2_enregistrer_interaction", arguments, VENDEUR_UN))
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "vendeur.un", "seller")
        identite.ajouter_role(cnx, "vendeur.un", "employee")
    avant = _instantane_base()

    reponse = _appeler(par_nom, "m2_enregistrer_interaction", arguments, VENDEUR_UN)

    assert _verdict(reponse)["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


@pytest.mark.parametrize("nom_outil", sorted(_OUTILS_PAR_LEAD))
def test_hors_transaction_l_identite_n_est_pas_verifiable_donc_refusee(par_nom, leads, nom_outil):
    """Appel direct de la fonction, sans la transaction que `executer_atomique` ouvre : aucune base jointe,
    donc aucune identité crue sur parole."""
    outil = par_nom[nom_outil]
    avant = _instantane_base()

    with contexte.appele_par_appareil(VENDEUR_UN):
        reponse = outil.fonction(**_OUTILS_PAR_LEAD[nom_outil]("lead-un"))

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


# -- outils réservés à l'admin : défense en profondeur --------------------------------------------------
_OUTILS_ADMIN = {
    "m2_produire_digest": {"date_jour": "2026-09-02", "horodatage": H2},
    "m2_detecter_doublons": {"lead_id": "lead-un"},
    "m2_signaler_doublon": {"lead_id_a": "lead-un", "lead_id_b": "lead-autre", "horodatage": H2},
    "m2_arbitrer_doublon": {"signalement_id": "sig-inconnu", "decision": "distincts_confirmes", "horodatage": H2},
}


@pytest.mark.parametrize("nom_outil", sorted(_OUTILS_ADMIN))
@pytest.mark.parametrize("appelante", [VENDEUR_UN, MARC], ids=["vendeur", "employe"])
def test_les_outils_reserves_a_l_admin_refusent_un_autre_role_meme_avec_une_identite_valide(
        par_nom, leads, nom_outil, appelante):
    avant = _instantane_base()

    reponse = _appeler(par_nom, nom_outil, _OUTILS_ADMIN[nom_outil], appelante)

    if reponse["ok"]:  # `signaler` et `arbitrer` rendent un verdict ; `digest` et `detecter` lèvent un refus
        assert _verdict(reponse)["code"] == CODE_INVALIDE
    else:
        assert reponse["erreur"] == "refus_metier" and CODE_INVALIDE in reponse["details"], reponse
    assert _instantane_base() == avant


def test_l_admin_authentifie_garde_les_outils_reserves(par_nom, leads):
    assert "lead-un" in _appeler(par_nom, "m2_produire_digest", _OUTILS_ADMIN["m2_produire_digest"], ADMIN)["resultat"]
    assert _appeler(par_nom, "m2_detecter_doublons", {"lead_id": "lead-un"}, ADMIN)["ok"] is True
    signale = _appeler(par_nom, "m2_signaler_doublon", _OUTILS_ADMIN["m2_signaler_doublon"], ADMIN)
    assert signale["ok"] is True


# =========================================================================================
# 4. La qualification : `owner` désigne une personne, et le fait est publié
# =========================================================================================
def _qualifier(par_nom, lead_id, owner, appelante):
    return _appeler(par_nom, "m2_transitionner_statut",
                    {"lead_id": lead_id, "statut_cible": "qualifie", "horodatage": H1, "owner": owner,
                     "prochaine_action": ACTION}, appelante)


def test_l_admin_qualifie_avec_l_identifiant_d_un_vendeur_et_le_fait_est_publie(par_nom, leads):
    accuse = _accepte(_qualifier(par_nom, "lead-nouveau", " vendeur.deux ", ADMIN))

    assert accuse["statut"] == "qualifie"
    assert acces.proprietaire_du_lead(outils._obtenir_registre(), "lead-nouveau") == "vendeur.deux"
    with stockage.transaction():
        charge = evenements.charge_publiee("m2.lead_assigne", "m2-lead-assigne-lead-nouveau")
    assert charge == {"lead_id": "lead-nouveau", "proprietaire": "vendeur.deux", "horodatage_assignation": H1}
    # Et le vendeur voit désormais ce lead, l'autre non.
    assert _accepte(_appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": "lead-nouveau"}, VENDEUR_DEUX))
    assert _verdict(_appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": "lead-nouveau"}, VENDEUR_UN))[
        "code"] == CODE_NON_ASSIGNE


@pytest.mark.parametrize("owner", ["Marc Tremblay", "vendeur.fantome", "marc.fictif", "ancien.vendeur", "Vendeur.Un"],
                         ids=["un-nom", "personne-inconnue", "employe", "personne-desactivee", "casse-differente"])
def test_un_owner_qui_n_est_pas_une_personne_valide_est_refuse_sans_ecriture(par_nom, leads, owner):
    """Sinon le lead serait invisible à tous les vendeurs, sans recours : le propriétaire n'est consigné qu'une
    fois, à la qualification."""
    avant = _instantane_base()

    reponse = _qualifier(par_nom, "lead-nouveau", owner, ADMIN)

    assert _verdict(reponse)["code"] == CODE_OWNER_INCONNU
    assert _instantane_base() == avant
    assert statuts.statut_courant(outils._obtenir_registre(), "lead-nouveau") == "nouveau"


def test_owner_absent_garde_son_refus_d_avant(par_nom, leads):
    for owner in (None, "", "   "):
        avant = _instantane_base()
        reponse = _qualifier(par_nom, "lead-nouveau", owner, ADMIN)
        assert _verdict(reponse)["code"] == "REJ-OWNER-ABSENT"
        assert _instantane_base() == avant


def test_l_admin_peut_etre_proprietaire_d_un_lead(par_nom, leads):
    _accepte(_qualifier(par_nom, "lead-nouveau", "admin.fictif", ADMIN))

    assert acces.proprietaire_du_lead(outils._obtenir_registre(), "lead-nouveau") == "admin.fictif"


def test_un_vendeur_ne_qualifie_pas_un_lead_sans_proprietaire(par_nom, leads):
    """Pas de prise de lead : un lead `nouveau` n'est à personne, donc invisible à un vendeur ; c'est
    l'admin (ou l'agent, sur décision humaine) qui assigne."""
    avant = _instantane_base()

    reponse = _qualifier(par_nom, "lead-nouveau", "vendeur.un", VENDEUR_UN)

    assert _verdict(reponse)["code"] == CODE_NON_ASSIGNE
    assert _instantane_base() == avant


def test_l_agent_garde_un_owner_en_texte_libre_et_le_fait_est_publie(par_nom, leads):
    """Comportement d'avant, documenté : sans identité d'appareil, `owner` n'est pas confronté aux personnes ;
    il ne rend le lead visible à un vendeur que si c'est l'identifiant de sa personne."""
    _accepte(_qualifier(par_nom, "lead-nouveau", "Alice", None))

    with stockage.transaction():
        charge = evenements.charge_publiee("m2.lead_assigne", "m2-lead-assigne-lead-nouveau")
    assert charge["proprietaire"] == "Alice"
    assert _verdict(_appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": "lead-nouveau"}, VENDEUR_UN))[
        "code"] == CODE_NON_ASSIGNE


def test_seule_la_qualification_publie_le_fait_de_propriete(par_nom, leads):
    """Une autre transition (converti) ne republie rien ; une qualification refusée non plus."""
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(EVENEMENTS_SORTANTS)).fetchall()

    _accepte(_appeler(par_nom, "m2_transitionner_statut",
                      {"lead_id": "lead-un", "statut_cible": "converti", "horodatage": H2,
                       "reference_devis_m3": "DEVIS-FICTIF-1"}, VENDEUR_UN))
    _verdict(_qualifier(par_nom, "lead-nouveau", "Marc Tremblay", ADMIN))

    with stockage.transaction() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS)).fetchall() == avant


def test_le_fait_est_publie_aussi_pour_les_leads_qualifies_par_l_agent_dans_la_preparation(leads):
    for lead_id, proprietaire in (("lead-un", "vendeur.un"), ("lead-deux", "vendeur.deux")):
        with stockage.transaction():
            charge = evenements.charge_publiee("m2.lead_assigne", f"m2-lead-assigne-{lead_id}")
        assert charge["proprietaire"] == proprietaire


# =========================================================================================
# 5. Le module pur, sans base
# =========================================================================================
def _registre_avec(qualifications):
    """Registre en mémoire : un lead ingéré puis qualifié par (lead_id, owner)."""
    reg = registre.Registre()
    for lead_id, owner in qualifications:
        reg.ajouter({"type_entree": "lead_ingere", "horodatage": H0, "lead_id": lead_id, "contrat": {}})
        reg.ajouter({"type_entree": statuts.TYPE_ENTREE, "horodatage": H1, "lead_id": lead_id,
                     "statut": "qualifie", "statut_precedent": "nouveau", "owner": owner})
    return reg


def test_acces_pur_le_proprietaire_est_l_owner_de_la_qualification_et_rien_d_autre():
    reg = _registre_avec([("l1", " vendeur.un "), ("l2", ""), ("l3", None)])
    reg.ajouter({"type_entree": "interaction", "horodatage": H2, "lead_id": "l2", "auteur": "vendeur.deux",
                 "resume": "note"})

    assert acces.proprietaires(reg) == {"l1": "vendeur.un"}
    assert acces.proprietaire_du_lead(reg, "l2") is None  # une note ne donne pas la propriété
    assert acces.proprietaire_du_lead(reg, "inconnu") is None


def test_acces_pur_controler_lead_par_role():
    reg = _registre_avec([("l1", "vendeur.un")])
    vendeur = acces.Acteur("vendeur.un", "seller")
    autre = acces.Acteur("vendeur.deux", "seller")
    admin = acces.Acteur("admin.fictif", "admin")

    assert acces.controler_lead(reg, "l1", vendeur) is None
    assert acces.controler_lead(reg, "l1", admin) is None
    assert acces.controler_lead(reg, "l1", None) is None
    assert acces.controler_lead(reg, "l1", autre)["code"] == CODE_NON_ASSIGNE
    assert acces.controler_lead(reg, "l-inconnu", vendeur)["code"] == CODE_NON_ASSIGNE
    assert acces.leads_visibles(reg, ["l1", "l-inconnu"], vendeur) == {"l1"}
    assert acces.leads_visibles(reg, ["l1"], autre) == set()
    assert acces.leads_visibles(reg, ["l1"], admin) is None
    assert acces.leads_visibles(reg, ["l1"], None) is None


def test_acces_pur_acteur_de_refuse_un_role_hors_portee():
    acteur, verdict = acces.acteur_de("marc.fictif", "employee", acces.ROLES_LEADS)
    assert acteur is None and verdict["code"] == CODE_INVALIDE
    acteur, verdict = acces.acteur_de("vendeur.un", "seller", acces.ROLES_ADMIN)
    assert acteur is None and verdict["code"] == CODE_INVALIDE
    acteur, verdict = acces.acteur_de("admin.fictif", "admin", acces.ROLES_ADMIN)
    assert acteur == acces.Acteur("admin.fictif", "admin") and verdict is None


def test_acces_pur_auteur_effectif():
    vendeur = acces.Acteur("vendeur.un", "seller")
    assert acces.auteur_effectif(None, "Alice") == ("Alice", None)
    assert acces.auteur_effectif(None, None) == (None, None)
    assert acces.auteur_effectif(vendeur, None) == ("vendeur.un", None)
    assert acces.auteur_effectif(vendeur, "vendeur.un") == ("vendeur.un", None)
    for fourni in ("vendeur.deux", "", 42):  # le schéma refuse déjà un non-texte : le module pur reste fermé
        auteur, verdict = acces.auteur_effectif(vendeur, fourni)
        assert auteur is None and verdict["code"] == CODE_DIFFERENTE


def test_les_nouveaux_codes_sont_au_catalogue():
    for code in (CODE_NON_ASSIGNE, CODE_INVALIDE, CODE_DIFFERENTE, CODE_OWNER_INCONNU):
        assert verdicts.est_verdict(code) is True
