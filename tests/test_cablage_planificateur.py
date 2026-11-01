"""Planificateur des connecteurs : désactivé par défaut, activé par un admin seulement, bail par ressource, arrêt
propre,
acteur système borné. Vraie base, vrai coffre, vrai sas ; réseau et courrier = doubles. Données fictives."""

from __future__ import annotations

import threading

import cablage_qa as cq
import courriel_qa as qa
import pytest
from sqlalchemy import func, select

from opsys import contexte, stockage
from opsys import service_acteur_systeme as systeme
from opsys.connecteurs_planification import bail, etat, journal, planificateur
from opsys.stockage.schema import PLANIFICATEUR_JOURNAL

FICTIF = True


@pytest.fixture
def c(tmp_path, monkeypatch):
    mon = cq.monter(tmp_path, monkeypatch)
    qa.creer_compte(mon.monde)
    qa.connecter_oauth(mon.monde)
    yield mon
    cq.demonter()


def _requetes(c) -> int:
    """Nombre de requêtes que le transport (le seul accès au réseau) a vues."""
    return len(c.monde.transport.requetes)


# -- désactivé par défaut -------------------------------------------------------------------------------------------
def test_rien_ne_tourne_par_defaut_et_rien_n_est_lu_chez_le_fournisseur(c):
    c.monde.gmail.ajouter(cq.courriel_client(1))
    avant = _requetes(c)
    resume = c.tour()
    assert _requetes(c) == avant  # pas une seule requête chez le fournisseur
    assert {v["statut"] for v in resume["executeurs"].values()} == {"inactif"}
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(PLANIFICATEUR_JOURNAL)).scalar_one() == 0
        assert [v["mode"] for v in etat.vue(cnx)] == ["inactif"] * len(etat.DEFINITIONS)
    with stockage.transaction() as cnx:
        assert comptes_synchro(cnx) is None  # le compte n'a jamais été synchronisé


def comptes_synchro(cnx):
    from opsys.courriel_connecteurs import comptes

    return comptes.lire(cnx, "gmail-paul")["derniere_synchro_le"]


def test_le_mode_ombre_constate_sans_rien_appeler_ni_ecrire_au_metier(c):
    c.monde.gmail.ajouter(cq.courriel_client(1))
    c.activer("courriel.synchro", "ombre")
    avant = _requetes(c)
    resume = c.tour()
    assert _requetes(c) == avant  # l'ombre ne joint jamais le fournisseur
    assert resume["executeurs"]["courriel.synchro"]["statut"] == "ombre"
    assert resume["executeurs"]["courriel.synchro"]["aurait"] == 1
    with stockage.transaction() as cnx:
        assert comptes_synchro(cnx) is None  # aucun curseur, aucun message ingéré
        evenements = [j["evenement"] for j in journal.lire(cnx, "courriel.synchro")]
    assert "aurait" in evenements and "passage" in evenements
    assert cq.lignes_m1() == []  # rien n'est arrivé chez M1


def test_le_mode_actif_synchronise_et_le_journal_ne_garde_aucun_contenu(c):
    c.monde.gmail.ajouter(cq.courriel_client(1, corps="CONTENU-FICTIF-SECRET-ABC"))
    c.activer("courriel.synchro")
    resume = c.tour()
    assert resume["executeurs"]["courriel.synchro"]["statut"] == "ok"
    with stockage.transaction() as cnx:
        assert comptes_synchro(cnx) is not None
        texte = repr(journal.lire(cnx))
    assert "CONTENU-FICTIF-SECRET" not in texte and "client.fictif@example.test" not in texte


def test_un_creneau_n_est_pris_qu_une_fois(c):
    c.activer("courriel.synchro")
    premier = c.tour()
    second = planificateur.tour(None, ports=c.ports)  # sans avancer l'horloge : le créneau n'est pas échu
    assert premier["executeurs"]["courriel.synchro"]["statut"] == "ok"
    assert second["executeurs"]["courriel.synchro"] == {"statut": "pas_echu"}


def test_le_coupe_circuit_de_l_environnement_arrete_tout(c, monkeypatch):
    c.activer("courriel.synchro")
    monkeypatch.setenv(etat.ENV_PLANIFICATEUR, "0")
    assert c.tour() == {"raison": "desactive", "executeurs": {}}
    with stockage.transaction() as cnx:
        assert all(v["mode"] == "inactif" for v in etat.vue(cnx))


# -- activation : admin seulement, expiration ------------------------------------------------------------------------
def test_une_activation_expire_apres_90_jours_et_redevient_inactive(c):
    c.activer("courriel.synchro")
    c.horloge.avancer(91 * 86400)
    with stockage.transaction() as cnx:
        ligne = etat.ligne(cnx, "courriel.synchro")
        assert etat.mode_effectif(ligne, c.horloge()) == "inactif"
        assert etat.vue(cnx, c.horloge())[0]["expire"] is True
    assert c.tour(avance=1)["executeurs"]["courriel.synchro"] == {"statut": "inactif"}


def test_seul_un_admin_actif_de_la_console_active_un_executeur(c):
    from opsys import identite

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "vendeur", "Vendeur fictif", "mot-de-passe-vendeur-1234", ["seller"])
    with stockage.transaction() as cnx:
        with pytest.raises(etat.RefusOperateur) as exc:
            etat.appliquer(cnx, cq.session_admin("vendeur"), "courriel.synchro", "actif", motif="essai fictif")
        assert exc.value.code == "ADMIN_REQUIS"
        with pytest.raises(etat.RefusOperateur) as exc:
            etat.appliquer(cnx, object(), "courriel.synchro", "actif", motif="essai fictif")
        assert exc.value.code == "SESSION_INVALIDE"
    with stockage.transaction() as cnx:
        assert etat.ligne(cnx, "courriel.synchro") is None


def test_un_appel_d_agent_ou_d_appareil_ne_peut_pas_activer(c):
    with stockage.transaction() as cnx:
        with contexte.appeler_en_tant_que("m01-front-office"), pytest.raises(etat.RefusOperateur) as exc:
            etat.appliquer(cnx, cq.session_admin(), "courriel.envoi", "actif", motif="essai fictif")
        assert exc.value.code == "APPEL_AGENT_INTERDIT"
        appareil = contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin"))
        with appareil, pytest.raises(etat.RefusOperateur) as exc:
            etat.appliquer(cnx, cq.session_admin(), "courriel.envoi", "actif", motif="essai fictif")
        assert exc.value.code == "APPEL_AGENT_INTERDIT"


def test_champs_fermes_motif_obligatoire_et_executeur_inconnu(c):
    cas = [("inconnu.x", "actif", "motif ok", "EXECUTEUR_INCONNU"),
           ("courriel.envoi", "turbo", "motif ok", "MODE_INCONNU"),
           ("courriel.envoi", "actif", "x", "MOTIF_INVALIDE"),
           ("courriel.envoi", "actif", "a\nb\x00c", "MOTIF_INVALIDE")]
    for executeur, mode, motif, code in cas:
        with stockage.transaction() as cnx:
            with pytest.raises(etat.RefusOperateur) as exc:
                etat.appliquer(cnx, cq.session_admin(), executeur, mode, motif=motif)
            assert exc.value.code == code
    with stockage.transaction() as cnx:
        with pytest.raises(etat.RefusOperateur) as exc:
            etat.appliquer(cnx, cq.session_admin(), "courriel.envoi", "actif", motif="motif ok", intervalle_s=1)
        assert exc.value.code == "INTERVALLE_INVALIDE"


def test_aucun_outil_d_agent_n_active_ni_ne_declenche_un_executeur(c):
    noms = {o.nom for _, o in c.capacites.index.values()}
    assert not [n for n in noms if "planific" in n or "executeur" in n or n.endswith("_synchroniser")]
    # l'outil du sas d'envoi existe pour `decider`, mais n'est PAS listé à un agent
    from opsys import serveur_mcp
    from opsys.capacites import NOM_OUTIL_SAS_COURRIEL

    assert NOM_OUTIL_SAS_COURRIEL in noms
    serveur = serveur_mcp.creer_serveur(c.capacites, outils_caches=frozenset({NOM_OUTIL_SAS_COURRIEL}))
    assert serveur is not None


def test_la_desactivation_est_immediate_et_journalisee(c):
    c.activer("courriel.synchro")
    c.activer("courriel.synchro", "inactif", motif="arrêt demandé")
    with stockage.transaction() as cnx:
        assert etat.mode_effectif(etat.ligne(cnx, "courriel.synchro"), c.horloge()) == "inactif"
        modes = [(j["mode"], j["details"]["ancien_mode"]) for j in journal.lire(cnx, "courriel.synchro")
                 if j["evenement"] == "mode"]
    assert modes == [("inactif", "actif"), ("actif", "inactif")]


def test_le_journal_du_planificateur_est_append_only(c):
    c.activer("courriel.synchro")
    with stockage.transaction() as cnx, pytest.raises(Exception, match="immuable"):
        cnx.exec_driver_sql("UPDATE planificateur_journal SET code = 'x'")
    with stockage.transaction() as cnx, pytest.raises(Exception, match="immuable"):
        cnx.exec_driver_sql("DELETE FROM planificateur_journal")


def test_un_detail_de_journal_hors_liste_blanche_est_refuse(c):
    with stockage.transaction() as cnx:
        with pytest.raises(ValueError):
            journal.journaliser(cnx, "courriel.synchro", "x", "a", details={"corps": "texte"})
        with pytest.raises(ValueError):
            journal.journaliser(cnx, "courriel.synchro", "x", "a", details={"raison": "x" * 65})


# -- bail -----------------------------------------------------------------------------------------------------------
def test_un_seul_porteur_obtient_le_bail_et_un_bail_expire_se_reprend_avec_un_jeton_plus_grand(c):
    t = [1_000_000.0]
    premier = bail.acquerir("r:1", "porteur-a", 60, horloge=lambda: t[0])
    assert premier is not None and premier.jeton == 1
    assert bail.acquerir("r:1", "porteur-b", 60, horloge=lambda: t[0]) is None
    t[0] += 61
    second = bail.acquerir("r:1", "porteur-b", 60, horloge=lambda: t[0])
    assert second is not None and second.jeton == 2
    # l'ancien porteur a perdu son bail : il ne peut ni le renouveler ni le libérer
    assert bail.renouveler(premier, 60, horloge=lambda: t[0]) is None
    bail.liberer(premier)
    assert bail.detenu("r:1", horloge=lambda: t[0])["porteur"] == "porteur-b"
    assert bail.renouveler(second, 60, horloge=lambda: t[0]) is not None
    bail.liberer(second)
    assert bail.detenu("r:1", horloge=lambda: t[0]) is None


def test_un_porteur_depossede_s_arrete_au_prochain_geste_durable(c):
    from opsys.connecteurs_planification.planificateur import Ports
    from opsys.courriel_connecteurs.erreurs import ErreurCourriel

    t = [2_000_000.0]
    ports = Ports(horloge=lambda: t[0])
    with systeme.contexte_planificateur() as acteur:
        ctx = planificateur.Contexte(ports, acteur, "porteur-a", None, t[0])
        ancien = bail.acquerir("r:fencing", "porteur-a", 60, horloge=ports.horloge)
        assert ctx.exiger_actif(ancien).jeton == 1  # tant qu'il le détient, il renouvelle
        t[0] += 200  # le bail expire (processus lent ou gelé) et un autre exécuteur le reprend
        nouveau = bail.acquerir("r:fencing", "porteur-b", 60, horloge=ports.horloge)
        assert nouveau.jeton == 2
        with pytest.raises(ErreurCourriel) as exc:
            ctx.exiger_actif(ancien)  # l'ancien porteur se découvre dépossédé : il s'arrête
        assert exc.value.code == "REJ-COURRIEL-BAIL-PERDU"
        assert bail.detenu("r:fencing", horloge=ports.horloge)["porteur"] == "porteur-b"


def test_quarante_fils_se_disputent_un_bail_un_seul_le_detient(c):
    gagnants, barriere = [], threading.Barrier(40)

    def essai(i):
        barriere.wait()
        b = bail.acquerir("r:course", f"fil-{i}", 60)
        if b is not None:
            gagnants.append(b)

    fils = [threading.Thread(target=essai, args=(i,)) for i in range(40)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    assert len(gagnants) == 1 and gagnants[0].jeton == 1


# -- arrêt propre ----------------------------------------------------------------------------------------------------
def test_l_arret_propre_interrompt_le_tour_libere_les_baux_et_ne_signale_pas_d_erreur(c):
    qa.creer_compte(c.monde, "gmail-deux", adresse="deux.fictif@example.test")
    c.activer("courriel.synchro")
    for i in range(3):
        c.monde.gmail.ajouter(cq.courriel_client(i))
    planificateur.demander_arret()
    try:
        resume = c.tour()
    finally:
        planificateur.reinitialiser_arret()
    assert resume["raison"] == "arret" and resume["executeurs"] == {}
    assert bail.detenu("courriel.compte:gmail-paul", horloge=c.horloge) is None
    with stockage.transaction() as cnx:
        from opsys.courriel_connecteurs import comptes

        assert comptes.lire(cnx, "gmail-paul")["derniere_erreur_code"] is None


def test_l_arret_pendant_une_page_laisse_le_curseur_et_libere_le_bail(c):
    c.monde.gmail.taille_page_max = 1
    for i in range(4):
        c.monde.gmail.ajouter(cq.courriel_client(i))
    c.ports.taille_page = 1
    c.activer("courriel.synchro")
    declenche = []
    d_origine = c.ports.horloge

    def horloge_piege():
        # après la première page, le drapeau d'arrêt tombe : la page suivante ne démarre pas
        if declenche == [] and len(c.monde.gmail.messages) and _pages_faites() >= 1:
            declenche.append(1)
            planificateur.demander_arret()
        return d_origine()

    def _pages_faites():
        with stockage.transaction() as cnx:
            from opsys.courriel_connecteurs import comptes

            return comptes.lire(cnx, "gmail-paul")["messages_total"]

    c.ports.horloge = horloge_piege
    try:
        c.tour()
    finally:
        planificateur.reinitialiser_arret()
        c.ports.horloge = d_origine
    assert bail.detenu("courriel.compte:gmail-paul", horloge=c.horloge) is None
    with stockage.transaction() as cnx:
        from opsys.courriel_connecteurs import comptes

        compte = comptes.lire(cnx, "gmail-paul")
        assert compte["derniere_erreur_code"] is None and compte["etat"] == "connecte"
    with stockage.transaction() as cnx:
        from opsys.courriel_connecteurs import comptes

        assert comptes.lire(cnx, "gmail-paul")["messages_total"] < 4  # l'arrêt a bien interrompu le tour
    # reprise : un tour suivant termine le travail, sans doublon
    c.tour()
    c.tour()
    with stockage.transaction() as cnx:
        from opsys.courriel_connecteurs import comptes

        assert comptes.lire(cnx, "gmail-paul")["messages_total"] == 4


# -- acteur système --------------------------------------------------------------------------------------------------
def test_l_acteur_systeme_du_planificateur_n_existe_que_pendant_le_tour_et_hors_requete(c):
    with systeme.contexte_planificateur() as acteur:
        systeme.verifier_planificateur(acteur)
        with pytest.raises(PermissionError), systeme.contexte_planificateur():  # non réentrant
            pass
    with pytest.raises(PermissionError):
        systeme.verifier_planificateur(acteur)  # fermé après le tour
    with contexte.appeler_en_tant_que("m01-front-office"), pytest.raises(PermissionError), \
            systeme.contexte_planificateur():
        pass


def test_l_acteur_du_planificateur_n_ouvre_pas_le_moteur_de_recalcul_ni_l_inverse(c):
    with systeme.contexte_planificateur() as acteur, stockage.transaction() as cnx, pytest.raises(PermissionError):
        systeme.verifier(cnx, acteur)  # le moteur de recalcul exige la portée « reconciliateur »
    with systeme.contexte_reconciliateur() as autre, pytest.raises(PermissionError):
        systeme.verifier_planificateur(autre)


def test_l_acteur_systeme_ne_peut_pas_decider_une_approbation(c):
    from opsys import approbations
    from opsys.capacites import outils_executables
    from opsys.outils import Niveau

    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, "m01-front-office", "opsys_courriel_approuver_envoi",
                                             {"x": 1}, niveau=Niveau.N3)
    outils = outils_executables(c.capacites.departements, stockage.transaction)
    with stockage.transaction() as cnx, pytest.raises(ValueError, match="inconnue ou inactive"):
        approbations.decider(cnx, demande, True, systeme.IDENTIFIANT, outils, c.capacites.departements)
    with stockage.transaction() as cnx:
        assert approbations.lire(cnx, demande)["statut"] == "en_attente"
