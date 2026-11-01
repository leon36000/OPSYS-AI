"""Le tour d'ingestion : reprise au curseur, atomicité, quota persisté, arrêt propre, événements sans valeur ni
donnée personnelle.

Banc : Search Console et son double (voir test_search_console pour la forme de l'API). Rien ne touche un vrai service.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fabriques_signaux import JETON, Horloge, coffre_pour, compte, masqueur
from m7_marketing import journal_chaine
from m7_marketing.signaux import curseurs, fraicheur, ingestion, registre, search_console
from m7_marketing.signaux.doubles_search_console import DoubleSearchConsole
from m7_marketing.signaux.erreurs import ErreurSignaux
from m7_marketing.signaux.quotas import Quota
from m7_marketing.signaux.transport import ReponseHttp
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.evenements import schemas
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

SITE = "https://www.horizon.example/"
DEBUT = date(2026, 9, 25)
FIN = date(2026, 10, 29)  # 1er novembre moins le retard de 3 jours de la source


def jours(debut=DEBUT, fin=FIN, clics=10):
    sortie, d = {}, debut
    while d <= fin:
        sortie[d.isoformat()] = (d.isoformat(), clics, 200, 0.05, 8.5)
        d += timedelta(days=1)
    return sortie


def banc(
    serveur=None, *, fictif=True, horloge=None, limiteur=None, classe=search_console.ConnecteurSearchConsole, **kw
):
    serveur = serveur or DoubleSearchConsole(propriete=SITE, jeton=JETON, jours=jours(), **kw)
    coffre = coffre_pour("search_console")
    horloge = horloge or Horloge()
    cpt = compte("search_console", SITE, fictif=fictif)
    return (
        classe(serveur, cpt, coffre.fournisseurs(), maintenant=horloge, masqueur=masqueur(), limiteur=limiteur),
        serveur,
        coffre,
        horloge,
    )


def faits():
    return registre.charger(stockage.maillons(*registre.REGISTRE))


def etats():
    return curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))


def evts(type_evenement):
    with stockage.transaction() as cnx:
        lignes = (
            cnx.execute(
                select(EVENEMENTS_SORTANTS)
                .where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
                .order_by(EVENEMENTS_SORTANTS.c.evenement_id)
            )
            .mappings()
            .all()
        )
    return [(ligne["evenement_id"], codec.decoder(ligne["charge"])) for ligne in lignes]


def flux(bilan, nom):
    return next(b for b in bilan["flux"] if b["flux"] == nom)


def test_un_tour_complet_ecrit_les_faits_l_etat_la_fraicheur_et_un_evenement_par_flux(base):
    con, serveur, coffre, horloge = banc(requetes={"2026-09-28": [("gouttière laval", 5, 100, 0.05, 7.0)]})
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    j = flux(bilan, "jour")
    assert (j["statut"], j["pages"], j["faits_nouveaux"], j["fenetre"]) == ("termine", 1, 35, "2026-09-25/2026-10-29")
    assert flux(bilan, "requetes")["faits_nouveaux"] == 1
    assert len([f for f in faits() if f["nature"] == "performance_recherche_jour"]) == 35
    e = etats()["search_console|principal|jour"]
    assert (e.termine, e.watermark, e.donnees_jusqu_au, e.dernier_echec) == (True, "2026-10-29", "2026-10-29", None)
    assert e.derniere_lecture_reussie_le == "2026-11-01T12:00:00Z"
    fr = fraicheur.evaluer("search_console", [e for e in etats().values()], horloge())
    assert fr["statut"] == "a_jour"
    assert coffre.ouverts == 0 and coffre.ouvertures["principal"] == serveur.nombre_requetes
    # chaque lecture est PROUVÉE par un fait de provenance
    f0 = faits()[0]
    assert f0["provenance"]["mode"] == "api_lecture" and f0["provenance"]["fournisseur"] == "google"
    assert journal_chaine.integre(stockage.maillons(*registre.REGISTRE))


def test_l_evenement_de_fin_de_fenetre_ne_porte_ni_valeur_ni_texte_ni_requete(base):
    con, _, _, horloge = banc(requetes={"2026-09-28": [("contact marie@exemple.test", 5, 100, 0.05, 7.0)]})
    ingestion.tour_ingestion(con, maintenant=horloge)
    evenements_ = evts(ingestion.TYPE_SIGNAUX)
    assert len(evenements_) == 3
    for ident, charge in evenements_:
        assert schemas.erreurs_charge(ingestion.TYPE_SIGNAUX, charge) == []
        texte = json.dumps(charge)
        for interdit in ("marie", "exemple.test", "gouttière", "clics", "impressions", JETON, "COURRIEL"):
            assert interdit not in texte
        assert charge["mode"] == "api_lecture" and charge["fictif"] is True and charge["fraicheur_fenetre_h"] == 72
        assert ident.startswith("m7-signaux-search_console-principal-")
    jour = next(c for _, c in evenements_ if c["flux"] == "jour")
    assert (jour["periode_debut"], jour["periode_fin"], jour["faits_nouveaux"]) == ("2026-09-25", "2026-10-29", 35)


def test_relire_a_un_autre_instant_ne_plante_pas_et_publie_un_nouvel_evenement(base):
    con, _, _, horloge = banc()
    ingestion.tour_ingestion(con, maintenant=horloge)
    horloge.avancer(hours=1)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert flux(bilan, "jour")["statut"] == "termine" and flux(bilan, "jour")["faits_inchanges"] == 14
    assert len(evts(ingestion.TYPE_SIGNAUX)) == 6
    # MÊME fenêtre, MÊME réponse, un autre instant : sans l'instant dans l'identifiant, le bus lèverait
    # ConflitPublication
    horloge.avancer(hours=1)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert flux(bilan, "jour")["statut"] == "termine" and len(evts(ingestion.TYPE_SIGNAUX)) == 9


def test_un_echec_au_milieu_garde_le_curseur_et_la_reprise_ne_saute_ni_ne_double_aucune_page(base, monkeypatch):
    monkeypatch.setattr(search_console, "LIGNES_JOUR", 10)
    con, serveur, _, horloge = banc(scenario=["ok", "503"])
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert (
        bilan.statut == "echec"
        and bilan.erreur["code"] == "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE"
        and bilan.erreur["reprenable"]
    )
    assert bilan.pages == 1 and bilan.faits_nouveaux == 10
    e = etats()["search_console|principal|jour"]
    assert e.termine is False and e.curseur is not None and e.dernier_echec[0][0] == "code"
    # rien n'est « lu » tant que la fenêtre n'est pas finie
    assert e.watermark is None and e.derniere_lecture_reussie_le is None
    assert fraicheur.evaluer("search_console", [e], horloge())["statut"] == fraicheur.STATUT_ECHEC
    suite = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert suite.statut == "termine" and suite.fenetre == "2026-09-25/2026-10-29"
    departs = [r["corps"]["startRow"] for r in serveur.requetes]
    assert departs == [0, 10, 10, 20, 30]
    toutes = [f for f in faits() if f["nature"] == "performance_recherche_jour"]
    assert len(toutes) == 35 and len({f["fait_id"] for f in toutes}) == 35 and all(f["revision"] == 1 for f in toutes)
    assert etats()["search_console|principal|jour"].dernier_echec is None


def test_un_arret_demande_s_applique_entre_deux_pages_et_se_reprend(base, monkeypatch):
    monkeypatch.setattr(search_console, "LIGNES_JOUR", 10)
    con, _, _, horloge = banc()
    appels = []

    def arret():
        appels.append(1)
        return len(appels) > 1  # après la première page

    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge, arret=arret)
    assert bilan.statut == "interrompu" and bilan.erreur["code"] == "REJ-SIGNAUX-ARRET-DEMANDE" and bilan.pages == 1
    assert etats()["search_console|principal|jour"].termine is False
    assert ingestion.tour_flux(con, "jour", maintenant=horloge).statut == "termine"
    assert len([f for f in faits() if f["nature"] == "performance_recherche_jour"]) == 35


def test_le_nombre_de_pages_du_tour_est_borne_et_reprenable(base, monkeypatch):
    monkeypatch.setattr(search_console, "LIGNES_JOUR", 10)
    con, _, _, horloge = banc()
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge, pages_max=2)
    assert bilan.statut == "interrompu" and bilan.pages == 2 and bilan.erreur["reprenable"] is True
    assert ingestion.tour_flux(con, "jour", maintenant=horloge, pages_max=5).statut == "termine"


def test_un_arret_demande_avant_tout_sort_sans_rien_lire(base):
    con, serveur, _, horloge = banc()
    bilan = ingestion.tour_ingestion(con, maintenant=horloge, arret=lambda: True)
    assert len(bilan["flux"]) == 1 and bilan["flux"][0]["statut"] == "interrompu" and serveur.nombre_requetes == 0
    assert faits() == []


def test_le_compte_de_requetes_du_jour_survit_a_un_redemarrage(base):
    class Petit(search_console.ConnecteurSearchConsole):
        LIMITES = Quota(par_minute=None, par_jour=3, source="test")

    con, serveur, _, horloge = banc(classe=Petit)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    # jour (1 requête) + requetes (4 semaines) : le 4e appel du jour est refusé AVANT l'envoi
    assert serveur.nombre_requetes == 3
    refus = flux(bilan, "requetes")
    assert (
        refus["statut"] == "echec"
        and refus["erreur"]["code"] == "REJ-SIGNAUX-QUOTA-LOCAL"
        and refus["erreur"]["reprenable"]
    )
    # « redémarrage » : un nouveau connecteur, un nouveau limiteur : le compte vient de l'état persisté
    con2, serveur2, _, _ = banc(classe=Petit, horloge=horloge)
    apres = ingestion.tour_flux(con2, "requetes", maintenant=horloge)
    assert apres.erreur["code"] == "REJ-SIGNAUX-QUOTA-LOCAL" and serveur2.nombre_requetes == 0
    horloge.avancer(days=1)
    assert ingestion.tour_flux(con2, "requetes", maintenant=horloge).statut in ("termine", "echec")
    assert serveur2.nombre_requetes >= 1


def test_un_refus_d_authentification_arrete_les_autres_flux_et_n_avance_rien(base):
    con, serveur, _, horloge = banc(scenario=["401"])
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert [b["flux"] for b in bilan["flux"]] == ["jour"] and bilan["flux"][0]["erreur"][
        "code"
    ] == "REJ-SIGNAUX-AUTH-REFUSEE"
    assert bilan["flux"][0]["erreur"]["reprenable"] is False and faits() == [] and serveur.nombre_requetes == 1
    e = etats()["search_console|principal|jour"]
    assert e.dernier_echec[0] == ("code", "REJ-SIGNAUX-AUTH-REFUSEE") and e.watermark is None


def test_un_echec_reprenable_d_un_flux_n_empeche_pas_les_suivants(base):
    con, _, _, horloge = banc(scenario=["503"])
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert [b["statut"] for b in bilan["flux"]] == ["echec", "termine", "termine"]


def test_sans_transport_branche_le_tour_echoue_proprement_et_n_ecrit_que_l_echec(base):
    from m7_marketing.signaux import catalogue

    cpt = compte("search_console", SITE)
    con = catalogue.construire(
        cpt, coffre_pour("search_console").fournisseurs(), maintenant=Horloge(), masqueur=masqueur()
    )
    bilan = ingestion.tour_ingestion(con, maintenant=Horloge())
    assert len(bilan["flux"]) == 1
    assert (
        bilan["flux"][0]["erreur"]["code"] == "REJ-SIGNAUX-TRANSPORT-NON-BRANCHE"
        and bilan["flux"][0]["erreur"]["reprenable"] is False
    )
    assert faits() == []


def test_une_valeur_monstrueuse_du_fournisseur_est_un_refus_typé_pas_une_exception(base):
    class Monstre:
        def envoyer(self, requete, *, delai_s=30.0):
            return ReponseHttp(
                200,
                {"rows": [{"keys": ["2026-10-01"], "clicks": "1e999999", "impressions": 1, "ctr": 0, "position": 1}]},
            )

    con, _, _, horloge = banc(Monstre())
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == "REJ-SIGNAUX-REPONSE-INVALIDE" and faits() == []


def test_deux_lignes_pour_le_meme_jour_se_contredisent_la_page_est_refusee_et_rien_n_est_ecrit(base):
    class Double:
        def envoyer(self, requete, *, delai_s=30.0):
            ligne = lambda c: {"keys": ["2026-10-01"], "clicks": c, "impressions": 9, "ctr": 0.1, "position": 2}  # noqa: E731
            return ReponseHttp(200, {"rows": [ligne(1), ligne(2)]})

    con, _, _, horloge = banc(Double())
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == "REJ-SIGNAUX-REPONSE-INVALIDE" and faits() == []


def test_un_jour_hors_de_la_periode_demandee_est_refuse(base):
    class Double:
        def envoyer(self, requete, *, delai_s=30.0):
            return ReponseHttp(
                200, {"rows": [{"keys": ["2020-01-01"], "clicks": 1, "impressions": 1, "ctr": 1, "position": 1}]}
            )

    con, _, _, horloge = banc(Double())
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.erreur["code"] == "REJ-SIGNAUX-REPONSE-INVALIDE" and faits() == []


def test_l_ecriture_est_atomique_les_faits_et_le_curseur_avancent_ensemble_ou_pas_du_tout(base, monkeypatch):
    con, _, _, horloge = banc()
    vrai = curseurs.ecrire_etat

    def casse(journal, etat, horodatage):
        vrai(journal, etat, horodatage)
        raise RuntimeError("panne disque après l'écriture de l'état")

    with monkeypatch.context() as m:
        m.setattr(ingestion.curseurs, "ecrire_etat", casse)
        with pytest.raises(RuntimeError):
            ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert faits() == [] and etats() == {} and evts(ingestion.TYPE_SIGNAUX) == []
    # la reprise repart de zéro et finit
    assert ingestion.tour_flux(con, "jour", maintenant=horloge).statut == "termine"


def test_une_revision_du_fournisseur_devient_la_revision_suivante_du_fait(base):
    con, serveur, _, horloge = banc()
    ingestion.tour_flux(con, "jour", maintenant=horloge)
    serveur.reviser_jour("2026-10-20", 99, 400)
    horloge.avancer(days=1)
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.faits_revises == 1
    f = next(
        x
        for x in registre.lire(stockage.maillons(*registre.REGISTRE), limite=1000)["faits"]
        if x["periode_debut"] == "2026-10-20"
    )
    assert f["revision"] == 2 and f["mesures"]["clics"] == "99"


def test_un_compte_fictif_est_marque_sur_chaque_fait_et_chaque_evenement(base):
    con, _, _, horloge = banc(fictif=True)
    ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert all(f["fictif"] is True for f in faits())
    assert all(c["fictif"] is True for _, c in evts(ingestion.TYPE_SIGNAUX))


def test_la_requete_de_lecture_n_utilise_que_la_methode_de_lecture_autorisee(base):
    con, serveur, _, horloge = banc()
    ingestion.tour_ingestion(con, maintenant=horloge)
    assert serveur.methodes() == {"POST"} and {r["chemin"].rsplit("/", 1)[-1] for r in serveur.requetes} == {"query"}
    assert all(r["schema_auth"] == "bearer" for r in serveur.requetes)


def test_le_bus_refuse_un_evenement_hors_catalogue_et_le_catalogue_connait_les_quatre_types(base):
    for type_ in (
        "m7.signaux_marketing_constates",
        "m7.depenses_marketing_constatees",
        "m7.anomalie_depense_detectee",
        "m7.conversion_hors_ligne_importee",
    ):
        assert type_ in schemas.types_connus()
    with pytest.raises(ValueError), stockage.transaction():
        evenements.publier("m7.signaux_marketing_constates", "m07-marketing", {"source": "search_console"})


def test_fraicheur_sur_les_flux_apres_un_tour_puis_le_temps_passe(base):
    con, _, _, horloge = banc()
    ingestion.tour_ingestion(con, maintenant=horloge)
    propres = list(etats().values())
    assert fraicheur.evaluer("search_console", propres, horloge())["statut"] == "a_jour"
    assert fraicheur.evaluer("search_console", propres, horloge() + timedelta(hours=73))["statut"] == "perime"
    assert datetime.now(UTC).year >= 2026


def test_erreur_signaux_a_un_catalogue_ferme():
    with pytest.raises(ValueError):
        ErreurSignaux("REJ-SIGNAUX-INVENTE")
