"""PLAN T1.4-m (partie 1) : `m2_reassigner_lead`, par le VRAI outil, comme en production.

Le vrai `outils()` de M2, le registre durable adossé à une base SQLite migrée, `executer_atomique` (la transaction et
la validation des arguments d'un appel réel) et `Capacites` (le mode `ombre` réel du manifeste, la file d'approbation
réelle, l'idempotence d'appareil réelle), de vraies personnes (`opsys.identite`). L'identité d'un appel d'appareil est
celle que `Capacites.appeler` et `serveur_mcp.appeler_outil` posent (`contexte.appele_par_appareil`) ; la porte
d'appareil complète (jeton, `_meta`, moteur HTTP) est prouvée par `tests/e2e/test_reassignation_lead_appareil.py`.

Ce qui est prouvé ici : la réassignation est une DÉCISION HUMAINE (jeton `admin` confirmé en base, ou demande
approuvée), jamais celle d'un agent seul, même en `supervise` ; le motif est obligatoire ; la cible est une personne
active de rôle `seller` ; le nouveau vendeur voit le lead, l'ancien ne le voit plus ; le fait `m2.lead_assigne` du
nouveau rang est publié dans la même transaction que le maillon ; chaque refus est prouvé sans aucune écriture
(toutes les tables de la base comparées avant et après). Données fictives (AGENTS.md).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from m2_revenue_crm import acces, assignation, outils
from sqlalchemy import select, update

from opsys import approbations, contexte, evenements, idempotence, identite, liaison_cibles, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, META

FICTIF = True

M2 = Path(__file__).resolve().parents[1]
NATHAN = contexte.IdentiteAppelante(personne="nathan", role="admin")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")

CODE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"
CODE_NON_ASSIGNE = "REJ-LEAD-NON-ASSIGNE"
CODE_OWNER_INCONNU = "REJ-OWNER-INCONNU"
CODE_HUMAIN = "REJ-HUMAIN-REQUIS"

H0 = "2026-09-01T09:00:00-04:00"
H1 = "2026-09-01T09:05:00-04:00"
H2 = "2026-09-02T10:00:00-04:00"
H3 = "2026-09-03T10:00:00-04:00"
HORLOGE_APPAREIL_DEREGLEE = "2000-01-01T00:00:00+00:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
MOTIF = "Le vendeur part en congé, le dossier passe à un collègue."
CONTACT_PARTAGE = {"nom": "Cliente Partagée", "courriel": "partagee@example.test"}


# -- installation ------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, avec le registre de M2 sur le stockage DURABLE (jamais la mémoire)."""
    url = f"sqlite:///{tmp_path / 'opsys-m2-reassignation.db'}"
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
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "admin.vendeur", "Admin Vendeur", "mot-de-passe-admvend-123", ["admin", "seller"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", "mot-de-passe-vendeur-deux", ["seller"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(
            cnx, "ancien.vendeur", "Ancien Vendeur", "mot-de-passe-ancien-123", ["seller"], actif=False)


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in outils.outils()}


@pytest.fixture
def dep(personnes):
    return lire_manifeste(M2)


@pytest.fixture
def capacites(dep):
    return Capacites({dep.id: dep}, stockage.transaction, appelant=dep.id, memoire=False)


def _contrat(lead_id: str, contact: dict | None = None) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": contact or {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }


@pytest.fixture
def leads(personnes):
    """Préparation par la voie des agents : `lead-un` à `vendeur.un` et `lead-deux` à `vendeur.deux` (MÊME client),
    `lead-nouveau` sans propriétaire, `lead-libre` dont `owner` est un nom (texte libre), `lead-perdu` à `vendeur.un`
    puis perdu."""
    for lead_id, contact in (("lead-un", CONTACT_PARTAGE), ("lead-deux", CONTACT_PARTAGE), ("lead-nouveau", None),
                             ("lead-libre", None), ("lead-perdu", None)):
        assert outils.ingerer_lead(_contrat(lead_id, contact), H0)["accepte"] is True
    for lead_id, owner in (("lead-un", "vendeur.un"), ("lead-deux", "vendeur.deux"), ("lead-libre", "Marc Tremblay"),
                           ("lead-perdu", "vendeur.un")):
        reponse = outils.transitionner_statut(lead_id, "qualifie", H1, owner=owner, prochaine_action=ACTION)
        assert reponse["accepte"] is True, reponse
    assert outils.transitionner_statut("lead-perdu", "perdu", H2, motif="client parti chez un concurrent")["accepte"]


# -- aides --------------------------------------------------------------------------------------------
def _args(**plus):
    return {"lead_id": "lead-un", "nouveau_proprietaire": "vendeur.deux", "motif": MOTIF, "horodatage": H2, **plus}


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    if identite_appelante is None:
        return executer_atomique(par_nom[nom], arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _reassigner(par_nom, identite_appelante=NATHAN, **plus):
    return _appeler(par_nom, "m2_reassigner_lead", _args(**plus), identite_appelante)


def _proposer_avec_ticket(capacites, nom, arguments):
    """Appel agent contrôlé : M2 lead existant, lien M10 de session et ticket sur l'outil/arguments exacts."""
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    lead_id = arguments["lead_id"]
    cle_session = f"agent:m02-revenue-crm:tests:{lead_id}"
    with stockage.transaction() as cnx:
        reg_m10 = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        active = liaison_m10.liaison_courante(cle_session, reg_m10)
        if active is None:
            _, refus = liaison_m10.lier_session_affaire(
                cle_session, lead_id, "nathan", "admin", "appareil", "liaison M2 de fixture fictive", H3, reg_m10,
            )
            assert refus is None
        else:
            assert active["affaire_id"] == lead_id
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement="m02-revenue-crm", agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id=lead_id, origine_affaire="session", outil=nom, arguments=arguments,
        )
    return capacites.appeler(nom, arguments, ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"]))


def _verdict(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _instantane_base():
    """Le contenu de TOUTES les tables : un refus qui écrirait quoi que ce soit (registre, événement, trace, journal,
    idempotence...) changerait cet instantané."""
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


def _maillons_de_reassignation(lead_id=None):
    with stockage.transaction():
        lignes = outils._obtenir_registre().lire()
    return [m for m in lignes if m["type_entree"] == assignation.TYPE_ENTREE
            and (lead_id is None or m["lead_id"] == lead_id)]


def _fait(lead_id, rang=1):
    with stockage.transaction():
        return evenements.charge_publiee("m2.lead_assigne", assignation.identifiant_evenement(lead_id, rang))


def _ids_des_evenements():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m2.lead_assigne"))
        return sorted(ligne.evenement_id for ligne in lignes)


def _peut_voir(par_nom, lead_id, identite_appelante):
    reponse = _appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": lead_id}, identite_appelante)
    if reponse["resultat"]["accepte"]:
        return True
    assert reponse["resultat"]["verdict"]["code"] == CODE_NON_ASSIGNE
    return False


def _leads_listes(par_nom, identite_appelante):
    reponse = _appeler(par_nom, "m2_lister_leads", {"horodatage": H3}, identite_appelante)
    page = _accepte(reponse)
    return sorted(lead["lead_id"] for lead in page["leads"]), page["total"]


# =========================================================================================
# 1. La déclaration de l'outil
# =========================================================================================
def test_l_outil_est_une_ecriture_interne_n3_ouverte_a_l_admin_seulement(par_nom):
    outil = par_nom["m2_reassigner_lead"]

    assert outil.autonomie is Autonomie.T1 and outil.niveau_effectif is Niveau.N3
    assert outil.frontiere_humaine is False, "ni T3 ni N5 : un humain la décide, mais elle n'est pas une frontière"
    assert outil.roles_appareil == acces.ROLES_ADMIN == frozenset({"admin"})
    assert outil.fonction is outils.reassigner_lead and len(outil.description) <= 1024


def test_le_schema_exige_les_quatre_champs_et_refuse_toute_identite_fournie(par_nom, leads):
    schema = par_nom["m2_reassigner_lead"].parametres

    assert set(schema["required"]) == {"lead_id", "nouveau_proprietaire", "motif", "horodatage"}
    assert schema["additionalProperties"] is False
    for cle in ("par", "role", "decide_par", "decide_role", "voie", "rang", "ancien_proprietaire", "proprietaire"):
        avant = _instantane_base()
        reponse = _reassigner(par_nom, **{cle: "nathan"})
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", cle
        assert _instantane_base() == avant
    for manquant in ("lead_id", "nouveau_proprietaire", "motif", "horodatage"):
        arguments = _args()
        del arguments[manquant]
        with contexte.appele_par_appareil(NATHAN):
            reponse = executer_atomique(par_nom["m2_reassigner_lead"], arguments)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", manquant


# =========================================================================================
# 2. L'admin réassigne : le nouveau vendeur voit, l'ancien ne voit plus
# =========================================================================================
def test_l_admin_reassigne_et_l_accuse_dit_qui_a_decide_pourquoi_et_de_qui_a_qui(par_nom, leads):
    accuse = _accepte(_reassigner(par_nom))

    assert accuse["lead_id"] == "lead-un" and accuse["rang"] == 2
    assert (accuse["proprietaire_precedent"], accuse["nouveau_proprietaire"]) == ("vendeur.un", "vendeur.deux")
    assert (accuse["decide_par"], accuse["decide_role"], accuse["voie"]) == ("nathan", "admin", "appareil")
    assert accuse["horodatage"] == H2 and accuse["evenement_id"] == "m2-lead-reassigne-2-lead-un"
    (maillon,) = _maillons_de_reassignation("lead-un")
    assert maillon["motif"] == MOTIF and maillon["ligne_id"] == accuse["ligne_id"]
    assert acces.proprietaire_du_lead(outils._obtenir_registre(), "lead-un") == "vendeur.deux"
    with stockage.transaction():
        outils._obtenir_registre().assert_chaine()


def test_le_nouveau_vendeur_voit_le_lead_et_l_ancien_ne_le_voit_plus_partout(par_nom, leads):
    assert _peut_voir(par_nom, "lead-un", VENDEUR_UN) and not _peut_voir(par_nom, "lead-un", VENDEUR_DEUX)
    client = _accepte(_appeler(par_nom, "m2_trouver_client_de_lead", {"lead_id": "lead-un"}, NATHAN))["client_id"]

    _accepte(_reassigner(par_nom))

    assert _peut_voir(par_nom, "lead-un", VENDEUR_DEUX) and not _peut_voir(par_nom, "lead-un", VENDEUR_UN)
    # La liste et son total : jamais un lead d'un autre, jamais un total qui le compte.
    assert _leads_listes(par_nom, VENDEUR_DEUX) == (["lead-deux", "lead-un"], 2)
    assert _leads_listes(par_nom, VENDEUR_UN) == (["lead-perdu"], 1)
    assert _leads_listes(par_nom, NATHAN)[0] == ["lead-deux", "lead-libre", "lead-nouveau", "lead-perdu", "lead-un"]
    # Les autres outils du vendeur : refus de l'ancien (même verdict qu'un lead inconnu), accès du nouveau.
    for nom in ("m2_evaluer_readiness", "m2_suggerer_prochaine_action"):
        assert _verdict(_appeler(par_nom, nom, {"lead_id": "lead-un", "horodatage": H3}, VENDEUR_UN))["code"] == (
            CODE_NON_ASSIGNE)
        assert _appeler(par_nom, nom, {"lead_id": "lead-un", "horodatage": H3}, VENDEUR_DEUX)["ok"] is True
    note = {"lead_id": "lead-un", "resume": "Rappel fait", "horodatage": H3}
    assert _verdict(_appeler(par_nom, "m2_enregistrer_interaction", note, VENDEUR_UN))["code"] == CODE_NON_ASSIGNE
    assert _accepte(_appeler(par_nom, "m2_enregistrer_interaction", note, VENDEUR_DEUX))["lead_id"] == "lead-un"
    # Client 360 : l'ancien ne voit plus l'opportunité, le nouveau voit les deux du client.
    assert _verdict(_appeler(par_nom, "m2_obtenir_client_360", {"client_id": client}, VENDEUR_UN))["code"] == (
        CODE_NON_ASSIGNE)
    vue = _accepte(_appeler(par_nom, "m2_obtenir_client_360", {"client_id": client}, VENDEUR_DEUX))
    assert sorted(o["lead_id"] for o in vue["opportunites"]) == ["lead-deux", "lead-un"]


def test_le_fait_du_rang_deux_est_publie_avec_le_precedent_et_le_rang_un_reste_intact(par_nom, leads):
    avant = _fait("lead-un")
    assert avant == {"lead_id": "lead-un", "proprietaire": "vendeur.un", "horodatage_assignation": H1}

    _accepte(_reassigner(par_nom))

    assert _fait("lead-un") == avant, "un fait déjà publié ne change jamais"
    assert _fait("lead-un", 2) == {
        "lead_id": "lead-un", "proprietaire": "vendeur.deux", "horodatage_assignation": H2, "rang": 2,
        "proprietaire_precedent": "vendeur.un",
    }
    assert _fait("lead-deux", 2) is None, "aucun fait pour un lead qui n'a pas bougé"


def test_reassigner_deux_fois_donne_les_rangs_deux_puis_trois_et_le_dernier_vendeur_voit(par_nom, leads):
    _accepte(_reassigner(par_nom))
    accuse = _accepte(_reassigner(par_nom, nouveau_proprietaire="vendeur.un", horodatage=H3))

    assert accuse["rang"] == 3 and accuse["proprietaire_precedent"] == "vendeur.deux"
    assert _fait("lead-un", 3)["proprietaire"] == "vendeur.un" and _fait("lead-un", 3)["rang"] == 3
    assert _fait("lead-un", 2)["proprietaire"] == "vendeur.deux"
    assert _peut_voir(par_nom, "lead-un", VENDEUR_UN) and not _peut_voir(par_nom, "lead-un", VENDEUR_DEUX)
    assert [m["rang"] for m in _maillons_de_reassignation("lead-un")] == [2, 3]
    assert [i for i in _ids_des_evenements() if "lead-un" in i] == sorted([
        "m2-lead-assigne-lead-un", "m2-lead-reassigne-2-lead-un", "m2-lead-reassigne-3-lead-un"])


def test_un_lead_perdu_ou_dont_owner_est_un_nom_se_reassigne_aussi(par_nom, leads):
    """Le dossier clos suit son vendeur (ses devis aussi) ; un `owner` saisi de travers, qui n'était à aucun vendeur,
    trouve enfin le sien : le recours qui manquait à T1.4-k2."""
    assert not _peut_voir(par_nom, "lead-libre", VENDEUR_UN)

    _accepte(_reassigner(par_nom, lead_id="lead-libre", nouveau_proprietaire="vendeur.un"))
    _accepte(_reassigner(par_nom, lead_id="lead-perdu"))

    assert _peut_voir(par_nom, "lead-libre", VENDEUR_UN)
    assert _fait("lead-libre", 2)["proprietaire_precedent"] == "Marc Tremblay"
    assert _peut_voir(par_nom, "lead-perdu", VENDEUR_DEUX) and not _peut_voir(par_nom, "lead-perdu", VENDEUR_UN)


def test_une_personne_admin_et_seller_peut_recevoir_un_lead(par_nom, leads):
    _accepte(_reassigner(par_nom, nouveau_proprietaire="admin.vendeur"))

    assert acces.proprietaire_du_lead(outils._obtenir_registre(), "lead-un") == "admin.vendeur"


# =========================================================================================
# 3. L'heure fait foi au serveur, l'atomicité, le rejeu
# =========================================================================================
def test_pour_un_appel_d_appareil_l_heure_de_reception_du_serveur_fait_foi(par_nom, leads):
    recu_le = dt.datetime(2026, 9, 30, 14, 0, tzinfo=dt.UTC)
    reception = contexte.HorodatageAppareil(
        appareil="tel-fictif", horodatage_appareil=dt.datetime(2000, 1, 1, tzinfo=dt.UTC), recu_le=recu_le)
    with contexte.receptionne_de(reception):
        accuse = _accepte(_reassigner(par_nom, horodatage=HORLOGE_APPAREIL_DEREGLEE))

    assert accuse["horodatage"] == recu_le.isoformat() != HORLOGE_APPAREIL_DEREGLEE
    assert _fait("lead-un", 2)["horodatage_assignation"] == recu_le.isoformat()
    (maillon,) = _maillons_de_reassignation("lead-un")
    assert maillon["horodatage"] == recu_le.isoformat()


def test_un_horodatage_invalide_sans_reception_du_serveur_est_refuse_sans_ecriture(par_nom, leads):
    avant = _instantane_base()

    reponse = _reassigner(par_nom, horodatage="hier")

    assert _verdict(reponse)["code"] == "REJ-HORODATAGE-INVALIDE"
    assert _instantane_base() == avant


def test_si_la_publication_du_fait_echoue_le_maillon_n_est_pas_ecrit(par_nom, leads, monkeypatch):
    """Le maillon et le fait sont dans UNE transaction : sans le fait, M3 montrerait encore les devis à l'ancien."""
    def en_panne(*_args, **_kwargs):
        raise RuntimeError("bus en panne")

    monkeypatch.setattr(outils.evenements, "publier", en_panne)
    avant = _instantane_base()

    with pytest.raises(RuntimeError, match="bus en panne"):
        _reassigner(par_nom)

    assert _instantane_base() == avant and _maillons_de_reassignation() == []
    assert acces.proprietaire_du_lead(outils._obtenir_registre(), "lead-un") == "vendeur.un"


def test_reassigner_au_proprietaire_actuel_est_un_refus_sans_effet_donc_un_rejeu_est_inoffensif(par_nom, leads):
    _accepte(_reassigner(par_nom))
    avant = _instantane_base()

    rejeu = _reassigner(par_nom)

    assert _verdict(rejeu)["code"] == "REJ-PROPRIETAIRE-INCHANGE"
    assert _instantane_base() == avant and len(_maillons_de_reassignation("lead-un")) == 1


def test_l_appareil_qui_renvoie_la_meme_cle_rejoue_la_reponse_sans_seconde_reassignation(capacites, leads):
    meta = idempotence.Meta(cle="mut-reassigner-1", appareil="tel-admin-fictif-1",
                            horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE)

    def appel():
        with contexte.appele_par_appareil(NATHAN):
            return capacites.appeler("m2_reassigner_lead", _args(horodatage=HORLOGE_APPAREIL_DEREGLEE), meta)

    premiere = appel()
    avant = _instantane_base()
    seconde = appel()

    assert premiere["ok"] is True and premiere["resultat"]["accepte"] is True and premiere["rejoue"] is False
    assert seconde["rejoue"] is True and seconde["resultat"] == premiere["resultat"]
    assert _instantane_base() == avant and len(_maillons_de_reassignation("lead-un")) == 1
    (maillon,) = _maillons_de_reassignation("lead-un")
    assert maillon["horodatage"] != HORLOGE_APPAREIL_DEREGLEE, "l'heure du serveur, jamais celle de l'appareil"
    assert abs((dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(maillon["horodatage"])).total_seconds()) < 120
    with stockage.transaction() as cnx:
        (trace,) = approbations.lister(cnx, "executee")
    assert (trace["outil"], trace["niveau"], trace["decide_par"], trace["decide_role"]) == (
        "m2_reassigner_lead", "N3", "nathan", "admin")


# =========================================================================================
# 4. Une décision humaine : jamais un agent seul
# =========================================================================================
def test_un_appel_sans_personne_est_refuse_meme_dans_un_mode_ou_un_n3_s_execute_sans_file(par_nom, leads):
    """`supervise` et `autonome` exécutent un N3 sans file : l'outil refuse lui-même tout appel qui n'est pas une
    décision humaine (un appel sans identité d'appareil ni demande approuvée)."""
    avant = _instantane_base()

    reponse = _reassigner(par_nom, identite_appelante=None)

    assert _verdict(reponse)["code"] == CODE_HUMAIN and "décision humaine" in _verdict(reponse)["detail"]
    assert _instantane_base() == avant and _maillons_de_reassignation() == []


def test_un_agent_qui_propose_attend_une_personne_puis_la_decision_est_celle_de_l_approbateur(
        capacites, dep, par_nom, leads):
    proposition = _proposer_avec_ticket(capacites, "m2_reassigner_lead", _args())
    assert proposition["ok"] is True and proposition["statut"] == "en_attente_approbation"
    assert _maillons_de_reassignation() == [] and _fait("lead-un", 2) is None, "rien n'est réassigné avant la décision"
    with stockage.transaction() as cnx:
        (demande,) = approbations.lister(cnx, "en_attente")
    assert (demande["outil"], demande["niveau"], demande["departement"]) == ("m2_reassigner_lead", "N3", dep.id)

    with stockage.transaction() as cnx:
        approbations.decider(
            cnx, proposition["demande_id"], True, "nathan",
            outils_executables(capacites.departements, stockage.transaction), capacites.departements)

    (maillon,) = _maillons_de_reassignation("lead-un")
    assert (maillon["decide_par"], maillon["decide_role"], maillon["voie"]) == ("nathan", "nathan_owner", "approbation")
    assert maillon["horodatage"] == H2 and maillon["motif"] == MOTIF
    assert _fait("lead-un", 2)["proprietaire"] == "vendeur.deux"
    assert _peut_voir(par_nom, "lead-un", VENDEUR_DEUX) and not _peut_voir(par_nom, "lead-un", VENDEUR_UN)


@pytest.mark.parametrize("approbateur", ["admin.fictif", "vendeur.un", "marc.fictif"])
def test_seul_le_proprietaire_approuve_la_proposition_d_un_agent(capacites, leads, approbateur):
    """La politique de M2 ne déclare que `nathan_owner` pour un N3 (défaut le plus restrictif, comme M1 et M10)."""
    proposition = _proposer_avec_ticket(capacites, "m2_reassigner_lead", _args())

    with pytest.raises(ValueError, match="aucun rôle autorisé"), stockage.transaction() as cnx:
        approbations.decider(
            cnx, proposition["demande_id"], True, approbateur,
            outils_executables(capacites.departements, stockage.transaction), capacites.departements)

    assert _maillons_de_reassignation() == [] and _fait("lead-un", 2) is None


def _forcer_une_decision_en_cours(arguments, *, decide_par="nathan", decide_role="nathan_owner", statut="en_cours",
                                  departement="m02-revenue-crm", outil="m2_reassigner_lead"):
    """Écrit dans la file la ligne que `approbations.decider` écrit au moment d'exécuter, pour prouver ce que l'outil
    accepte et refuse."""
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, departement, outil, arguments, niveau=Niveau.N3)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            statut=statut, decide_par=decide_par, decide_role=decide_role))
    return ident


def test_l_outil_reconnait_la_decision_humaine_d_une_ligne_en_cours_de_cet_outil_avec_ces_arguments(par_nom, leads):
    """Témoin positif du mécanisme que `decider` alimente."""
    _forcer_une_decision_en_cours(_args())

    accuse = _accepte(_reassigner(par_nom, identite_appelante=None))

    assert (accuse["decide_par"], accuse["decide_role"], accuse["voie"]) == ("nathan", "nathan_owner", "approbation")


@pytest.mark.parametrize("cas", [
    {"statut": "en_attente"},  # une demande que personne n'a encore approuvée
    {"statut": "refusee"},
    {"statut": "executee"},
    {"decide_par": None, "decide_role": None},
    {"decide_par": "marc.fictif", "decide_role": "employee"},  # un rôle qui n'est pas humain-décideur
    {"decide_par": "vendeur.un", "decide_role": "seller"},
    {"decide_par": "inconnu.fictif", "decide_role": "nathan_owner"},  # personne inconnue
    {"decide_par": "marc.fictif", "decide_role": "nathan_owner"},  # ne porte pas le rôle
    {"decide_par": "ancien.vendeur", "decide_role": "admin"},  # personne désactivée
    {"departement": "m03-estimation"},  # une demande d'un autre département
    {"outil": "m2_republier_assignations"},  # un autre outil du même département
])
def test_une_ligne_qui_n_est_pas_une_decision_humaine_en_cours_ne_donne_aucun_droit(par_nom, leads, cas):
    _forcer_une_decision_en_cours(_args(), **cas)
    avant = _instantane_base()

    reponse = _reassigner(par_nom, identite_appelante=None)

    assert _verdict(reponse)["code"] == CODE_HUMAIN
    assert _instantane_base() == avant


@pytest.mark.parametrize("autre", [
    {"motif": "Un autre motif, celui-là a été approuvé."}, {"nouveau_proprietaire": "admin.vendeur"},
    {"lead_id": "lead-deux"}, {"horodatage": H3},
])
def test_une_decision_en_cours_pour_d_autres_arguments_ne_donne_aucun_droit(par_nom, leads, autre):
    _forcer_une_decision_en_cours(_args(**autre))

    assert _verdict(_reassigner(par_nom, identite_appelante=None))["code"] == CODE_HUMAIN
    assert _maillons_de_reassignation() == []


@pytest.mark.parametrize("cas", [
    {"statut": "en_attente"}, {"statut": "refusee"}, {"statut": "executee"},
    {"decide_par": None, "decide_role": None},
    {"decide_par": "marc.fictif", "decide_role": "employee"},
    {"decide_par": "vendeur.un", "decide_role": "seller"},
    {"decide_par": "vendeur.un", "decide_role": "system_agent"},
    {"decide_par": "inconnu.fictif", "decide_role": "nathan_owner"},
    {"decide_par": "marc.fictif", "decide_role": "nathan_owner"},
    {"decide_par": "ancien.vendeur", "decide_role": "admin"},
    {"departement": "m03-estimation"}, {"outil": "m2_republier_assignations"},
])
def test_la_lecture_de_la_file_ne_rend_un_approbateur_que_pour_une_decision_humaine_en_cours(personnes, cas):
    """Le garde lui-même, sans le module pur derrière lui : aucune de ces lignes ne désigne un décideur."""
    _forcer_une_decision_en_cours(_args(), **cas)

    with stockage.transaction() as cnx:
        assert outils._decision_approuvee_en_cours(cnx, "m2_reassigner_lead", _args()) is None


def test_la_lecture_de_la_file_rend_l_approbateur_d_une_ligne_en_cours_aux_arguments_exacts(personnes):
    _forcer_une_decision_en_cours(_args())
    _forcer_une_decision_en_cours(
        _args(), decide_par="admin.fictif", decide_role="admin", outil="m2_republier_assignations")
    lire = outils._decision_approuvee_en_cours

    with stockage.transaction() as cnx:
        assert lire(cnx, "m2_reassigner_lead", _args()) == ("nathan", "nathan_owner")
        assert lire(cnx, "m2_reassigner_lead", _args(motif="Un autre motif, autre.")) is None
        assert lire(cnx, "m2_reassigner_lead", {}) is None
        assert lire(None, "m2_reassigner_lead", _args()) is None


def test_un_approbateur_desactive_depuis_la_reservation_ne_donne_plus_de_droit(par_nom, leads):
    _forcer_une_decision_en_cours(_args())
    with stockage.transaction() as cnx:
        identite.activer(cnx, "nathan", False)

    assert _verdict(_reassigner(par_nom, identite_appelante=None))["code"] == CODE_HUMAIN


def test_un_appel_direct_hors_transaction_est_refuse_meme_avec_une_identite(par_nom, leads):
    avant = _instantane_base()

    with contexte.appele_par_appareil(NATHAN):
        reponse = par_nom["m2_reassigner_lead"].fonction(**_args())  # ni transaction ni base jointe

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [VENDEUR_UN, MARC], ids=["vendeur", "employe"])
def test_un_vendeur_ou_un_employe_authentifie_ne_reassigne_pas(par_nom, leads, appelante):
    """La portée du core les arrête déjà (`roles_appareil`) ; l'outil les refuse aussi, avant toute écriture."""
    avant = _instantane_base()

    reponse = _reassigner(par_nom, appelante)

    assert _verdict(reponse)["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [
    contexte.IdentiteAppelante(personne="inconnu.fictif", role="admin"),
    contexte.IdentiteAppelante(personne="ancien.vendeur", role="seller"),
    contexte.IdentiteAppelante(personne="vendeur.un", role="admin"),  # rôle jamais porté
], ids=["personne-inconnue", "personne-desactivee", "role-jamais-porte"])
def test_une_identite_non_confirmee_en_base_est_refusee_avant_tout(par_nom, leads, appelante):
    avant = _instantane_base()

    reponse = _reassigner(par_nom, appelante)

    assert _verdict(reponse)["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


def test_un_role_retire_depuis_l_appairage_est_refuse_avec_le_meme_jeton(par_nom, leads):
    _accepte(_reassigner(par_nom, ADMIN, nouveau_proprietaire="vendeur.deux"))
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
        identite.ajouter_role(cnx, "admin.fictif", "employee")
    avant = _instantane_base()

    reponse = _reassigner(par_nom, ADMIN, nouveau_proprietaire="vendeur.un", horodatage=H3)

    assert _verdict(reponse)["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


# =========================================================================================
# 5. La cible : une personne active de rôle seller
# =========================================================================================
@pytest.mark.parametrize("cible", [
    "marc.fictif",  # un employé
    "admin.fictif",  # un admin qui n'est pas vendeur
    "nathan",  # le propriétaire, qui n'est pas vendeur
    "ancien.vendeur",  # un vendeur désactivé
    "vendeur.fantome",  # personne
    "Vendeur Deux",  # un nom, pas un identifiant
    "Vendeur.Deux",  # casse différente
    "",
    "   ",
])
def test_une_cible_qui_n_est_pas_un_vendeur_actif_est_refusee_sans_ecriture(par_nom, leads, cible):
    avant = _instantane_base()

    reponse = _reassigner(par_nom, nouveau_proprietaire=cible)

    verdict = _verdict(reponse)
    assert verdict["code"] == CODE_OWNER_INCONNU and "seller" in verdict["detail"]
    assert _instantane_base() == avant


def test_l_identifiant_de_la_cible_est_consigne_tel_que_la_base_le_connait(par_nom, leads):
    accuse = _accepte(_reassigner(par_nom, nouveau_proprietaire="  vendeur.deux  "))

    assert accuse["nouveau_proprietaire"] == "vendeur.deux"
    assert _fait("lead-un", 2)["proprietaire"] == "vendeur.deux"


# =========================================================================================
# 6. Le lead et le motif
# =========================================================================================
@pytest.mark.parametrize(("arguments", "code"), [
    ({"lead_id": "lead-fantome"}, "REJ-LEAD-INCONNU"),
    ({"lead_id": "lead-nouveau"}, "REJ-OWNER-ABSENT"),
    ({"nouveau_proprietaire": "vendeur.un"}, "REJ-PROPRIETAIRE-INCHANGE"),
    ({"motif": ""}, "REJ-MOTIF-ABSENT"),
    ({"motif": "        "}, "REJ-MOTIF-ABSENT"),
    ({"motif": "congé"}, "REJ-MOTIF-INVALIDE"),
    ({"motif": "x" * 501}, "REJ-MOTIF-INVALIDE"),
])
def test_chaque_refus_du_lead_ou_du_motif_est_nomme_et_n_ecrit_rien(par_nom, leads, arguments, code):
    avant = _instantane_base()

    reponse = _reassigner(par_nom, **arguments)

    assert _verdict(reponse)["code"] == code
    assert _instantane_base() == avant


def test_un_lead_nouveau_se_qualifie_il_ne_se_reassigne_pas(par_nom, leads):
    verdict = _verdict(_reassigner(par_nom, lead_id="lead-nouveau"))

    assert verdict["code"] == "REJ-OWNER-ABSENT" and verdict["statut"] == "nouveau"
    assert "m2_transitionner_statut" in verdict["detail"]


def test_le_motif_est_consigne_sans_ses_espaces_de_tete_et_de_queue(par_nom, leads):
    _accepte(_reassigner(par_nom, motif="   " + MOTIF + "   "))

    assert _maillons_de_reassignation("lead-un")[0]["motif"] == MOTIF


def test_la_qualification_par_un_agent_publie_l_owner_sans_ses_espaces_comme_le_registre_le_lit(par_nom, leads):
    """Sans identité d'appareil, `owner` est du texte libre : le fait de rang 1 porte celui que M2 lit, nettoyé."""
    assert outils.ingerer_lead(_contrat("lead-espaces"), H0)["accepte"] is True

    assert outils.transitionner_statut(
        "lead-espaces", "qualifie", H1, owner="  Alice  ", prochaine_action=ACTION)["accepte"] is True

    assert _fait("lead-espaces")["proprietaire"] == "Alice"
    assert acces.proprietaire_du_lead(outils._obtenir_registre(), "lead-espaces") == "Alice"


# =========================================================================================
# 7. Ce qui ne bouge pas
# =========================================================================================
def test_une_reassignation_ne_touche_ni_le_maillon_de_qualification_ni_les_autres_leads(par_nom, leads):
    with stockage.transaction():
        avant = outils._obtenir_registre().lire()

    _accepte(_reassigner(par_nom))

    with stockage.transaction():
        apres = outils._obtenir_registre().lire()
    assert apres[: len(avant)] == avant, "le registre est append-only : rien de l'existant n'a changé"
    assert len(apres) == len(avant) + 1 and apres[-1]["type_entree"] == "reassignation"
    assert acces.proprietaire_du_lead(outils._obtenir_registre(), "lead-deux") == "vendeur.deux"
    assert _fait("lead-un") == {"lead_id": "lead-un", "proprietaire": "vendeur.un", "horodatage_assignation": H1}
