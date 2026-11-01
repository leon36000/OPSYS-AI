"""Import manuel d'exports : mapping obligatoire, bornes, formules neutralisées, idempotence, révision, fraîcheur."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fabriques_geo import MAINTENANT, Horloge
from m7_marketing.signaux import curseurs, fraicheur, import_manuel, modele, registre
from m7_marketing.signaux.erreurs import ErreurSignaux
from sqlalchemy import select

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

CSV_IA = ("Page,Date,Impressions,Clics\n"
          "https://horizon.example/services/?utm_source=x,2026-10-28,120,4\n"
          "https://horizon.example/faq,2026-10-28,80,2\n"
          "https://horizon.example/faq,2026-10-29,95,3\n")
MAPPING_IA = {"portee": {"type": "page", "colonne": "Page"}, "periode": {"jour": "Date"},
              "mesures": {"impressions": "Impressions", "clics": "Clics"}, "echantillon": "complet"}


def importer(pii, horloge=None, **kw):
    base = dict(source="search_console_ia", compte_ref="principal", nature="rapport_ia_impressions", mapping=MAPPING_IA,
                csv_texte=CSV_IA, fictif=True, maintenant=horloge or Horloge(), masqueur=pii)
    base.update(kw)
    return import_manuel.importer(**base)


def faits():
    return registre.charger(stockage.maillons(*registre.REGISTRE))


def evenements():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == import_manuel.TYPE_SIGNAUX)).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


def test_import_ecrit_des_faits_avec_provenance_manuelle_et_sans_parametres_d_url(base, pii):
    r = importer(pii)
    assert r["accepte"] and r["lignes_lues"] == 3 and r["faits_nouveaux"] == 3 and r["mode"] == "import_manuel"
    par_ref = {f["portee"]["ref"]: f for f in faits() if f["periode_debut"] == "2026-10-28"}
    assert set(par_ref) == {"https://horizon.example/services/", "https://horizon.example/faq"}  # ?utm_source retiré
    f = par_ref["https://horizon.example/services/"]
    assert f["mesures"] == {"clics": "4", "impressions": "120"} and f["source"] == "search_console_ia"
    assert f["provenance"]["mode"] == "import_manuel" and f["provenance"]["empreinte_reponse"] == r["empreinte_fichier"]
    assert f["provenance"]["fournisseur"] == "export_manuel" and f["echantillon"] == {"nature": "complet", "n": None}
    assert f["fictif"] is True and r["periode"] == {"debut": "2026-10-28", "fin": "2026-10-29"}


def test_idempotence_meme_fichier_aucun_changement_et_revision_si_une_valeur_change(base, pii):
    importer(pii)
    r2 = importer(pii, horloge=Horloge(MAINTENANT + timedelta(hours=1)))
    assert (r2["faits_nouveaux"], r2["faits_revises"], r2["faits_inchanges"]) == (0, 0, 3)
    assert len(faits()) == 3
    modifie = CSV_IA.replace("120,4", "130,5")
    r3 = importer(pii, horloge=Horloge(MAINTENANT + timedelta(hours=2)), csv_texte=modifie)
    assert (r3["faits_nouveaux"], r3["faits_revises"], r3["faits_inchanges"]) == (0, 1, 2)
    revises = [f for f in faits() if f["revision"] == 2]
    assert len(revises) == 1 and revises[0]["mesures"] == {"clics": "5", "impressions": "130"}
    courants = registre.courants(faits())
    assert len(courants) == 3 and sum(f["revision"] for f in courants.values()) == 4


def test_fraicheur_et_evenement_apres_import(base, pii):
    importer(pii)
    etats = curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))
    etat = etats["search_console_ia|principal|import"]
    assert etat.termine and etat.watermark == "2026-10-29"
    assert etat.derniere_lecture_reussie_le == "2026-11-01T12:00:00Z"
    ok = fraicheur.evaluer("search_console_ia", [etat], MAINTENANT + timedelta(days=30))
    assert ok["statut"] == "a_jour" and ok["donnees_jusqu_au"] == "2026-10-29"
    perime = fraicheur.evaluer("search_console_ia", [etat], MAINTENANT + timedelta(days=40))
    assert perime["statut"] == "perime"
    evts = evenements()
    assert len(evts) == 1
    e = evts[0]
    assert e["mode"] == "import_manuel" and e["flux"] == "import" and e["faits_nouveaux"] == 3
    assert e["fraicheur_fenetre_h"] == modele.SOURCES["search_console_ia"].fraicheur_h
    assert "mesures" not in e and "Page" not in json.dumps(e) and "horizon" not in json.dumps(e)


def test_evenement_rejoue_a_un_autre_instant_ne_fait_pas_tomber_l_import(base, pii):
    importer(pii)
    importer(pii, horloge=Horloge(MAINTENANT + timedelta(minutes=5)))
    assert len(evenements()) == 2


@pytest.mark.parametrize("mapping", [
    None, {}, {"portee": {"type": "page", "colonne": "Page"}},
    {**MAPPING_IA, "echantillon": "peut-etre"},
    {**MAPPING_IA, "mesures": {"inconnue": "Clics"}},
    {**MAPPING_IA, "mesures": {}},
    {**MAPPING_IA, "portee": {"type": "robot_ia", "colonne": "Page"}},
    {**MAPPING_IA, "portee": {"type": "page", "colonne": "Page", "ref": "x"}},
    {**MAPPING_IA, "periode": {"jour": "Date", "debut": "Date"}},
    {**MAPPING_IA, "periode": {"debut": "Date"}},
    {**MAPPING_IA, "extra": 1},
])
def test_le_mapping_est_obligatoire_complet_et_jamais_devine(base, pii, mapping):
    with pytest.raises(ErreurSignaux) as exc:
        importer(pii, mapping=mapping)
    assert exc.value.code == "REJ-SIGNAUX-IMPORT-INVALIDE" and faits() == []


def test_source_et_nature_hors_liste_refusees(base, pii):
    with pytest.raises(ErreurSignaux) as exc:
        importer(pii, source="source_inventee")
    assert exc.value.code == "REJ-SIGNAUX-SOURCE-INCONNUE"
    with pytest.raises(ErreurSignaux):
        importer(pii, nature="campagne_jour")
    with pytest.raises(ErreurSignaux):
        importer(pii, source="journaux_serveur")  # nature qu'il ne porte pas


def test_colonne_absente_ou_valeur_invalide_refuse_l_import_entier_en_nommant_la_ligne(base, pii):
    for csv_texte, attendu in [
        ("Page,Date,Impressions\nhttps://a.test/x,2026-10-28,5\n", "colonnes absentes"),
        ("Page,Date,Impressions,Clics\nhttps://a.test/x,28/10/2026,5,1\n", "ligne 2"),
        ("Page,Date,Impressions,Clics\nhttps://a.test/x,2026-10-28,5,1\nhttps://a.test/y,2026-10-28,1 234,1\n",
            "ligne 3"),
        ("Page,Date,Impressions,Clics\nhttps://a.test/x,2026-10-28,3,5 %\n", "ligne 2"),
        ("Page,Date,Impressions,Clics\nhttps://a.test/x,2026-10-28,3,1,9\n", "nombre de colonnes"),
        ("Page,Date,Impressions,Clics\n,2026-10-28,3,1\n", "portée vide"),
        ("Page,Date,Impressions,Clics\n", "aucune ligne"),
    ]:
        with pytest.raises(ErreurSignaux) as exc:
            importer(pii, csv_texte=csv_texte)
        assert exc.value.code == "REJ-SIGNAUX-IMPORT-INVALIDE" and attendu in exc.value.detail
    assert faits() == []  # tout ou rien


def test_nombre_json_flottant_ou_booleen_refuse_entier_et_texte_acceptes(base, pii):
    ligne = {"Page": "https://a.test/x", "Date": "2026-10-28", "Impressions": 5, "Clics": 1}
    assert importer(pii, csv_texte=None, lignes=[ligne])["accepte"]
    for mauvais in (2.5, True):
        with pytest.raises(ErreurSignaux) as exc:
            importer(pii, csv_texte=None, lignes=[{**ligne, "Clics": mauvais}])
        assert exc.value.code == "REJ-SIGNAUX-IMPORT-INVALIDE"
    assert importer(pii, csv_texte=None, lignes=[{**ligne, "Clics": "1.5"}])["faits_revises"] == 1


def test_formule_de_tableur_neutralisee_dans_le_texte_conserve(base, pii):
    mapping = {"portee": {"type": "requete", "colonne": "Requete"}, "periode": {"debut": "Debut", "fin": "Fin"},
               "mesures": {"impressions": "Impr", "clics": "Clics"}, "echantillon": "anonymise_partiel"}
    csv_texte = ("Requete,Debut,Fin,Impr,Clics\n"
                 "=HYPERLINK(\"http://evil.test\"),2026-10-19,2026-10-25,10,1\n"
                 "+SUM(A1),2026-10-19,2026-10-25,10,1\n"
                 "-2+3,2026-10-19,2026-10-25,10,1\n"
                 "@cmd,2026-10-19,2026-10-25,10,1\n"
                 "normale,2026-10-19,2026-10-25,10,1\n")
    importer(pii, source="search_console", nature="requetes_periode", mapping=mapping, csv_texte=csv_texte)
    refs = sorted(f["portee"]["ref"] for f in faits())
    assert all(not r.startswith(("=", "+", "-", "@", "\t", "\r")) for r in refs)
    assert "'=HYPERLINK(\"http://evil.test\")" in refs and "'+SUM(A1)" in refs and "'-2+3" in refs and "'@cmd" in refs
    assert "normale" in refs
    assert import_manuel.neutraliser_formule("\tx") == "'\tx" and import_manuel.neutraliser_formule("abc") == "abc"
    assert import_manuel.neutraliser_formule("") == ""


def test_renseignements_personnels_du_texte_masques(base, pii):
    mapping = {"portee": {"type": "requete", "colonne": "Requete"}, "periode": {"jour": "Jour"},
               "mesures": {"impressions": "Impr"}, "echantillon": "anonymise_partiel"}
    csv_texte = "Requete,Jour,Impr\ncontact jean.tremblay@exemple.test 514-555-0123,2026-10-20,3\n"
    importer(pii, source="bing_webmaster", nature="requetes_periode", mapping=mapping, csv_texte=csv_texte)
    ref = faits()[0]["portee"]["ref"]
    assert "jean.tremblay" not in ref and "555-0123" not in ref and "[[COURRIEL:" in ref


def test_bornes_octets_et_lignes_jamais_tronquees(base, pii, monkeypatch):
    with pytest.raises(ErreurSignaux) as exc:
        importer(pii, csv_texte="x" * (import_manuel.OCTETS_MAX + 1))
    assert exc.value.code == "REJ-SIGNAUX-IMPORT-TROP-GROS"
    entete = "Page,Date,Impressions,Clics\n"
    trop = entete + "".join(f"https://a.test/p{i},2026-10-28,1,0\n" for i in range(import_manuel.LIGNES_MAX + 1))
    with pytest.raises(ErreurSignaux) as exc:
        importer(pii, csv_texte=trop)
    assert exc.value.code == "REJ-SIGNAUX-IMPORT-TROP-GROS"
    lignes = [{"Page": f"/p{i}", "Date": "2026-10-28", "Impressions": 1, "Clics": 0}
              for i in range(import_manuel.LIGNES_MAX + 1)]
    with pytest.raises(ErreurSignaux) as exc:
        importer(pii, csv_texte=None, lignes=lignes)
    assert exc.value.code == "REJ-SIGNAUX-IMPORT-TROP-GROS"
    monkeypatch.setattr(import_manuel, "LIGNES_MAX", 40)  # la borne exacte, sans écrire 20 000 maillons
    juste = entete + "".join(f"/p{i},2026-10-28,1,0\n" for i in range(40))
    assert importer(pii, csv_texte=juste)["lignes_lues"] == 40 and len(faits()) == 40
    with pytest.raises(ErreurSignaux) as exc:
        importer(pii, csv_texte=juste + "/p41,2026-10-28,1,0\n")
    assert exc.value.code == "REJ-SIGNAUX-IMPORT-TROP-GROS"


def test_exactement_un_de_csv_ou_lignes_et_delimiteur_permis(base, pii):
    with pytest.raises(ErreurSignaux):
        importer(pii, csv_texte=None)
    with pytest.raises(ErreurSignaux):
        importer(pii, lignes=[{"Page": "/x"}])
    with pytest.raises(ErreurSignaux):
        importer(pii, delimiteur="|")
    r = importer(pii, csv_texte=CSV_IA.replace(",", ";"), delimiteur=";")
    assert r["faits_nouveaux"] == 3


def test_masqueur_et_compte_obligatoires_et_fictif_booleen(base, pii):
    with pytest.raises(ErreurSignaux):
        importer(None)
    with pytest.raises(ErreurSignaux):
        importer(pii, compte_ref="Mauvais Compte")
    with pytest.raises(ErreurSignaux):
        importer(pii, fictif="oui")


def test_deux_lignes_de_meme_identite_et_valeurs_differentes_refusent_tout(base, pii):
    doublon = CSV_IA + "https://horizon.example/faq,2026-10-29,999,3\n"
    with pytest.raises(ErreurSignaux) as exc:
        importer(pii, csv_texte=doublon)
    assert exc.value.code == "REJ-SIGNAUX-FAIT-CONFLIT" and faits() == []


def test_journaux_serveur_visites_robots_ia_de_bout_en_bout(base, pii):
    from m7_marketing.geo import journaux_bots

    ua = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0)"
    journal = "\n".join(
        f'203.0.113.{i} - - [{jour}/Oct/2026:12:00:00 +0000] "GET /services HTTP/1.1" 200 5 "-" "{ua}"'
        for i, jour in ((1, 20), (2, 20), (3, 21)))
    lignes = journaux_bots.lignes_visites(journaux_bots.analyser_journaux(journal))
    mapping = {"portee": {"type": "robot_ia", "colonne": "robot"}, "periode": {"jour": "jour"},
               "mesures": {"visites": "visites", "lignes_lues": "lignes_lues", "ip_verifiees": "ip_verifiees",
                           "ok_2xx": "ok_2xx"}, "echantillon": "complet"}
    r = importer(pii, source="journaux_serveur", nature="visites_robots_ia", mapping=mapping, csv_texte=None,
                 lignes=lignes)
    assert r["faits_nouveaux"] == 4  # 2 jours de couverture + 2 jours du robot
    robot = {f["periode_debut"]: f["mesures"] for f in faits() if f["portee"]["ref"] == "OAI-SearchBot"}
    assert robot["2026-10-20"]["visites"] == "2" and robot["2026-10-21"]["visites"] == "1"
    assert "203.0.113" not in json.dumps(faits())
