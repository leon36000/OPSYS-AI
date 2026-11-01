"""M8.2 — Entrepôt de données : couche analytique DÉRIVÉE des registres, versionnée, reconstructible.

Ce que ce fichier prouve (données fictives, vraie base SQLite migrée jusqu'à 0046) :
- les lignes sont déterministes, sans aucune personne (le technicien du fait de chantier n'y figure jamais), et leurs
  colonnes sont exactement celles des tables du schéma (le contrat entre le module pur et la migration) ;
- une mesure non calculable reste sans valeur (jamais un zéro) ; chaque mesure garde source, version de définition,
instant
  du dernier fait et fenêtre de fraîcheur DÉCLARÉE (le statut, lui, n'est pas figé) ;
- reconstruire sur le même état n'écrit rien ; un fait de plus fait une construction de plus, l'historique s'ajoute, la
  construction courante remplace la précédente en bloc ;
- détruire l'entrepôt ne change rien à ce que les autres couches lisent (il n'est jamais une source de vérité) et la
  reconstruction rend les mêmes lignes ;
- l'état dit « en retard » dès que les registres bougent ; le schéma se compile pour PostgreSQL ; l'append-only du
pont BI
  ne touche pas l'entrepôt.
"""

from __future__ import annotations

import copy

import pytest
from m8_analytics import catalogue_mesures, entrepot, entrepot_stockage, jeux_fictifs, moteur_mesures
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from opsys import stockage

FICTIF = True
_INSTANT = "2026-10-30T20:00:00-04:00"
_PLUS_TARD = "2026-10-31T09:00:00-04:00"


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture(scope="module")
def catalogue():
    return catalogue_mesures.charger()


# ---------------------------------------------------------------------------
# Le module pur
# ---------------------------------------------------------------------------
def test_les_lignes_sont_deterministes_et_les_colonnes_sont_celles_du_schema(catalogue):
    registres = jeux_fictifs.registres_fictifs()
    a = entrepot.construire(registres, catalogue, construit_le=_INSTANT, rang_precedent=0)
    b = entrepot.construire(copy.deepcopy(registres), catalogue, construit_le=_INSTANT, rang_precedent=0)
    assert a == b
    tables = entrepot_stockage.tables()
    assert set(a["tables"]) == set(tables)
    for nom, lignes in a["tables"].items():
        assert lignes, nom
        colonnes = {colonne.name for colonne in tables[nom].columns}
        for ligne in lignes:
            assert set(ligne) == colonnes, nom


def test_aucune_personne_dans_l_entrepot(catalogue):
    registres = jeux_fictifs.registres_fictifs()
    assert any(fait.get("technicien_id") == "tech-fictif" for fait in registres["chantier"])
    resultat = entrepot.construire(registres, catalogue, construit_le=_INSTANT, rang_precedent=0)
    rendu = repr(resultat)
    assert "tech-fictif" not in rendu and "technicien" not in rendu
    for nom, lignes in resultat["tables"].items():
        assert not any("technicien" in colonne or "client_id" in colonne for ligne in lignes for colonne in ligne), nom


def test_une_mesure_non_calculable_n_a_pas_de_valeur_et_aucun_zero_n_est_invente(catalogue):
    vide = entrepot.construire(
        moteur_mesures.normaliser_registres(
            {"chantier": [], "entonnoir": [], "contenus": [], "cash_libre": [], "operations": []}
        ),
        catalogue,
        construit_le=_INSTANT,
        rang_precedent=0,
    )
    lignes = vide["tables"][entrepot.TABLE_MESURES]
    assert len(lignes) == len(catalogue["mesures"])
    assert all(ligne["statut"] == "non_calculable" and ligne["valeur"] is None for ligne in lignes)
    assert all(ligne["detail"] and "non calculable" in ligne["detail"] for ligne in lignes)
    for nom in (entrepot.TABLE_CHANTIER, entrepot.TABLE_LEAD, entrepot.TABLE_DEVIS, entrepot.TABLE_CONTENUS):
        assert vide["tables"][nom] == []


def test_chaque_mesure_garde_provenance_version_et_fraicheur_declaree(catalogue):
    resultat = entrepot.construire(jeux_fictifs.registres_fictifs(), catalogue, construit_le=_INSTANT, rang_precedent=0)
    par_id = {ligne["metric_id"]: ligne for ligne in resultat["tables"][entrepot.TABLE_MESURES]}
    taux = par_id["m8_taux_acceptation_pct"]
    assert taux["valeur"] == "50.00" and taux["source"] and len(taux["version_definition"]) == 64
    assert taux["dernier_fait_le"].startswith("2026-10-30") and taux["fraicheur_attendue_s"] == 86400
    assert taux["fraicheur_terminale"] is False
    chantiers = par_id["m8_chantiers_termines"]
    assert chantiers["fraicheur_attendue_s"] is None and chantiers["fraicheur_terminale"] is True
    # le STATUT de fraîcheur n'est jamais figé dans l'entrepôt : il dépend de l'heure de la lecture
    assert not any("statut_fraicheur" in ligne or "a_jour" in ligne for ligne in par_id.values())


def test_les_dimensions_et_faits_portent_les_valeurs_des_registres(catalogue):
    registres = jeux_fictifs.registres_fictifs(chantiers=3, signaux_materiaux=1, acceptes=4)
    tables = entrepot.construire(registres, catalogue, construit_le=_INSTANT, rang_precedent=0)["tables"]
    chantiers = {ligne["wct_id"]: ligne for ligne in tables[entrepot.TABLE_CHANTIER]}
    assert len(chantiers) == 3
    premier = chantiers["wct-fictif-001"]
    assert premier["duree_reelle_minutes"] == 110 and premier["duree_estimee_minutes"] == 100
    assert premier["signal_materiaux"] is True and chantiers["wct-fictif-002"]["signal_materiaux"] is False
    assert premier["marge_reelle_cad"] == "3000.00"
    devis = {ligne["devis_id"]: ligne for ligne in tables[entrepot.TABLE_DEVIS]}
    assert devis["devis-fictif-001"]["prix_total_cad"] == "12500.00" and devis["devis-fictif-001"]["accepte_le"]
    assert devis["devis-fictif-012"]["accepte_le"] is None and devis["devis-fictif-012"]["prix_total_cad"] is None
    leads = {ligne["lead_id"]: ligne for ligne in tables[entrepot.TABLE_LEAD]}
    assert leads["lead-fictif-001"]["qualifie_le"] and leads["lead-fictif-020"]["qualifie_le"] is None


def test_un_chantier_sans_variance_ni_devis_laisse_des_colonnes_vides_pas_des_zeros(catalogue):
    registres = jeux_fictifs.registres_fictifs(avec_variance=False)
    registres["chantier"] = [f for f in registres["chantier"] if f["type_entree"] in ("wct",)]
    ligne = entrepot.construire(registres, catalogue, construit_le=_INSTANT, rang_precedent=0)["tables"][
        entrepot.TABLE_CHANTIER
    ][0]
    assert ligne["duree_estimee_minutes"] is None and ligne["variance_statut"] is None
    assert ligne["signal_materiaux"] is None and ligne["marge_reelle_cad"] is None


@pytest.mark.parametrize("instant", [None, "", "2026-10-30T20:00:00", "pas un instant", 12])
def test_un_instant_de_construction_illisible_est_refuse(catalogue, instant):
    with pytest.raises(ValueError, match="REJ-ENTREPOT-INSTANT-INVALIDE"):
        entrepot.construire(jeux_fictifs.registres_fictifs(), catalogue, construit_le=instant, rang_precedent=0)


@pytest.mark.parametrize("rang", [-1, "0", None, True])
def test_un_rang_precedent_invalide_est_refuse(catalogue, rang):
    with pytest.raises(ValueError, match="REJ-ENTREPOT-RANG-INVALIDE"):
        entrepot.construire(jeux_fictifs.registres_fictifs(), catalogue, construit_le=_INSTANT, rang_precedent=rang)


def test_un_registre_inconnu_ou_mal_forme_est_refuse_jamais_devine_vide(catalogue):
    with pytest.raises(ValueError, match="REJ-MOTEUR-REGISTRES"):
        entrepot.construire({"chantier": []}, catalogue, construit_le=_INSTANT, rang_precedent=0)
    mauvais = jeux_fictifs.registres_fictifs()
    mauvais["entonnoir"] = "pas une liste"
    with pytest.raises(ValueError, match="REJ-MOTEUR-REGISTRES"):
        entrepot.construire(mauvais, catalogue, construit_le=_INSTANT, rang_precedent=0)


# ---------------------------------------------------------------------------
# L'adaptateur : vraie base migrée
# ---------------------------------------------------------------------------
def test_construction_puis_reconstruction_identique_n_ecrit_rien(base, catalogue):
    registres = jeux_fictifs.registres_fictifs()
    with stockage.transaction() as cnx:
        premiere = entrepot_stockage.reconstruire(cnx, registres, catalogue, _INSTANT)
    assert premiere["statut"] == "construit" and premiere["construction"]["rang"] == 1
    assert premiere["construction"]["comptes"][entrepot.TABLE_MESURES] == len(catalogue["mesures"])
    with stockage.transaction() as cnx:
        seconde = entrepot_stockage.reconstruire(cnx, registres, catalogue, _PLUS_TARD)
        total = cnx.execute(select(stockage.schema.M8_ENT_CONSTRUCTIONS.c.rang)).all()
    assert seconde["statut"] == "inchange" and seconde["construction"]["construit_le"] == _INSTANT
    assert len(total) == 1


def test_un_fait_de_plus_remplace_la_construction_courante_et_ajoute_a_l_historique(base, catalogue):
    registres = jeux_fictifs.registres_fictifs(leads=20)
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(cnx, registres, catalogue, _INSTANT)
    plus = jeux_fictifs.registres_fictifs(leads=21)
    with stockage.transaction() as cnx:
        resultat = entrepot_stockage.reconstruire(cnx, plus, catalogue, _PLUS_TARD)
        courantes = entrepot_stockage.lire_mesures_courantes(cnx)
        histo = entrepot_stockage.lire_historique(cnx, "m8_leads_recus")
        leads = entrepot_stockage.lire_table(cnx, entrepot.TABLE_LEAD)
    assert resultat["statut"] == "construit" and resultat["construction"]["rang"] == 2
    assert {ligne["construction_id"] for ligne in courantes} == {resultat["construction"]["construction_id"]}
    assert {ligne["metric_id"]: ligne["valeur"] for ligne in courantes}["m8_leads_recus"] == "21"
    assert [ligne["valeur"] for ligne in histo] == ["21", "20"]  # du plus récent au plus ancien
    assert len(leads) == 21


def test_detruire_l_entrepot_ne_change_rien_aux_lectures_et_la_reconstruction_rend_les_memes_lignes(base, catalogue):
    registres = jeux_fictifs.registres_fictifs()
    avant = moteur_mesures.lire(registres, catalogue)
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(cnx, registres, catalogue, _INSTANT)
        courantes = entrepot_stockage.lire_mesures_courantes(cnx)
        tables = {nom: entrepot_stockage.lire_table(cnx, nom) for nom in entrepot.tables_courantes()}
        for table in reversed(list(entrepot_stockage.tables().values())):
            cnx.execute(table.delete())  # on détruit tout l'entrepôt, historique compris
        cnx.execute(stockage.schema.M8_ENT_CONSTRUCTIONS.delete())
        vide = entrepot_stockage.etat(cnx, registres, catalogue)
    assert vide["statut"] == "absent"
    assert moteur_mesures.lire(registres, catalogue) == avant  # les couches de lecture n'en dépendent pas
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(cnx, registres, catalogue, _INSTANT)
        refaites = {nom: entrepot_stockage.lire_table(cnx, nom) for nom in entrepot.tables_courantes()}
        courantes_refaites = entrepot_stockage.lire_mesures_courantes(cnx)
    assert refaites == tables and courantes_refaites == courantes


def test_les_lignes_de_l_entrepot_sont_celles_du_moteur(base, catalogue):
    registres = jeux_fictifs.registres_fictifs()
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(cnx, registres, catalogue, _INSTANT)
        lignes = {ligne["metric_id"]: ligne for ligne in entrepot_stockage.lire_mesures_courantes(cnx)}
    for mesure in moteur_mesures.lire(registres, catalogue):
        ligne = lignes[mesure["metric_id"]]
        assert (ligne["valeur"], ligne["statut"], ligne["dernier_fait_le"], ligne["version_definition"]) == (
            mesure["valeur"],
            mesure["statut"],
            mesure["dernier_fait_le"],
            mesure["version_definition"],
        )


def test_l_etat_dit_absent_a_jour_puis_en_retard(base, catalogue):
    registres = jeux_fictifs.registres_fictifs()
    with stockage.transaction() as cnx:
        assert entrepot_stockage.etat(cnx, registres, catalogue)["statut"] == "absent"
        entrepot_stockage.reconstruire(cnx, registres, catalogue, _INSTANT)
        assert entrepot_stockage.etat(cnx, registres, catalogue)["statut"] == "a_jour"
        registres["entonnoir"] = registres["entonnoir"][:-1]  # un fait de moins : le moindre écart est détecté
        retard = entrepot_stockage.etat(cnx, registres, catalogue)
    assert retard["statut"] == "en_retard" and "registres" in retard["raison"]


def test_un_catalogue_modifie_rend_l_entrepot_en_retard_et_le_reconstruit(base, catalogue):
    registres = jeux_fictifs.registres_fictifs()
    autre = copy.deepcopy(catalogue)
    autre["version_catalogue"] = "f" * 64
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(cnx, registres, catalogue, _INSTANT)
        assert entrepot_stockage.etat(cnx, registres, autre)["statut"] == "en_retard"
        assert entrepot_stockage.reconstruire(cnx, registres, autre, _PLUS_TARD)["statut"] == "construit"


def test_une_ligne_avec_une_colonne_en_trop_est_refusee_avant_toute_ecriture(base, catalogue, monkeypatch):
    original = entrepot.construire

    def tordu(*args, **kwargs):
        resultat = original(*args, **kwargs)
        resultat["tables"][entrepot.TABLE_CHANTIER] = [
            {**resultat["tables"][entrepot.TABLE_CHANTIER][0], "technicien_id": "tech-fictif"}
        ]
        return resultat

    monkeypatch.setattr(entrepot, "construire", tordu)
    with pytest.raises(ValueError, match="REJ-ENTREPOT-COLONNES"), stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(cnx, jeux_fictifs.registres_fictifs(), catalogue, _INSTANT)
    with stockage.transaction() as cnx:
        assert entrepot_stockage.derniere_construction(cnx) is None


def test_un_echec_en_cours_d_ecriture_annule_toute_la_construction(base, catalogue, monkeypatch):
    registres = jeux_fictifs.registres_fictifs()
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(cnx, registres, catalogue, _INSTANT)
        avant = {nom: entrepot_stockage.lire_table(cnx, nom) for nom in entrepot.tables_courantes()}
    autres = jeux_fictifs.registres_fictifs(leads=25)
    original = entrepot.construire

    def casse(*args, **kwargs):
        resultat = original(*args, **kwargs)
        resultat["tables"][entrepot.TABLE_CONTENUS] = [
            {**resultat["tables"][entrepot.TABLE_CONTENUS][0], "suivi": None}
        ]  # NOT NULL violé en dernier
        return resultat

    monkeypatch.setattr(entrepot, "construire", casse)
    with stockage.transaction() as cnx:
        assert entrepot_stockage.reconstruire(cnx, autres, catalogue, _PLUS_TARD)["statut"] == "concurrent"
    with stockage.transaction() as cnx:
        apres = {nom: entrepot_stockage.lire_table(cnx, nom) for nom in entrepot.tables_courantes()}
        assert entrepot_stockage.derniere_construction(cnx)["rang"] == 1
    assert apres == avant  # ni les anciennes lignes perdues, ni les nouvelles à moitié écrites


def test_l_historique_est_borne(base, catalogue):
    with stockage.transaction() as cnx:
        with pytest.raises(ValueError, match="REJ-ENTREPOT-LIMITE"):
            entrepot_stockage.lire_historique(cnx, "m8_leads_recus", limite=0)
        with pytest.raises(ValueError, match="REJ-ENTREPOT-LIMITE"):
            entrepot_stockage.lire_historique(cnx, "m8_leads_recus", limite=1001)


def test_le_schema_de_l_entrepot_se_compile_pour_postgresql():
    for table in entrepot_stockage.tables().values():
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert table.name in ddl and "CREATE TABLE" in ddl
    # aucune colonne de type propre à SQLite : tout est portable (texte, entier, booléen)
    types = {type(colonne.type).__name__ for table in entrepot_stockage.tables().values() for colonne in table.columns}
    assert types <= {"String", "Text", "Integer", "Boolean"}
