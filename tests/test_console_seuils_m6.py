"""C7 — l'écran admin « Seuils matériaux » : le seuil global, les seuils par catégorie et par matériau, les deux
planchers (quantité et dollars) s'éditent depuis la console, avec l'audit de qui a changé quoi.

Gardes : session admin (ou propriétaire), CSRF, champs fermés, bornes, version attendue (pas de mise à jour perdue),
et aucune valeur choisie par le navigateur au-delà de celle qu'il soumet. Le propriétaire voit la même page ; la
valeur initiale d'un agent reste étiquetée « valeur initiale proposée par l'architecte, à confirmer » tant qu'aucune
personne n'a édité.

Client HTTP de test, SQLite migrée, données fictives.
"""

from __future__ import annotations

import html
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from m6_material_control import seuils_variance

from opsys import stockage
from opsys.console import application
from opsys.console.securite import Configuration

FICTIF = True
SECRET = "secret-seuils-m6-" + "x" * 40
DEPARTEMENT = "m06-material-control"

spec = importlib.util.spec_from_file_location("reglages_aide_m6_c7", Path(__file__).with_name("reglages_aide.py"))
aide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aide)


def _monde(tmp_path, monkeypatch, identifiant=aide.ADMIN):
    deps = aide.installer(tmp_path, monkeypatch)
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe="/opsys"), deps, stockage.transaction)
    client = TestClient(app, base_url="https://testserver/opsys")
    r = client.post("/connexion", data={"identifiant": identifiant, "mot_de_passe": aide.MOT_DE_PASSE},
                    follow_redirects=False)
    assert r.status_code == 303
    client.csrf = client.get("/api/session").json()["csrf"]
    client.deps = deps
    return client


@pytest.fixture
def admin(tmp_path, monkeypatch):
    client = _monde(tmp_path, monkeypatch, aide.ADMIN)
    yield client
    client.close()
    stockage.liberer()


def _config_en_vigueur():
    with stockage.transaction():
        return seuils_variance.config_en_vigueur(stockage.maillons(DEPARTEMENT, seuils_variance.REGISTRE))


def _journal():
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, seuils_variance.REGISTRE))


def _editer(client, **plus):
    donnees = {
        "csrf": client.csrf,
        "global_pourcentage": "0.25",
        "plancher_quantite": "2",
        "plancher_dollars": "100.00",
        "par_categorie": "revetement=0.20",
        "par_materiau": "REV-FICTIF=0.15",
        "categories": "REV-FICTIF=revetement",
        "raison": "Seuils fictifs de test, décidés par l'admin",
        "version_attendue": "0",
    }
    donnees.update(plus)
    return client.post("/seuils-materiaux", data=donnees, follow_redirects=False)


def test_l_ecran_montre_le_seuil_global_actuel_et_le_bandeau_de_valeur_initiale(admin):
    page = admin.get("/seuils-materiaux")

    assert page.status_code == 200
    texte = html.unescape(page.text)
    assert "valeur initiale proposée par l'architecte, à confirmer" in texte
    assert "0.3" in texte and "Seuils matériaux" in texte


def test_l_admin_edite_le_seuil_global_les_par_categorie_par_materiau_et_les_deux_planchers(admin):
    reponse = _editer(admin)

    assert reponse.status_code == 303
    config = _config_en_vigueur()
    assert config["global_pourcentage"] == "0.25"
    assert config["plancher_quantite"] == "2" and config["plancher_dollars"] == "100"
    assert config["par_categorie"] == {"revetement": "0.2"}
    assert config["par_materiau"] == {"REV-FICTIF": "0.15"}
    assert config["categories"] == {"REV-FICTIF": "revetement"}
    (maillon,) = _journal()
    assert maillon["auteur"] == aide.ADMIN and maillon["role"] == "admin"
    assert maillon["motif"] == "Seuils fictifs de test, décidés par l'admin"
    page = admin.get("/seuils-materiaux")
    assert "Seuils fictifs de test" in page.text and aide.ADMIN in page.text


def test_une_valeur_hors_bornes_est_refusee_et_ne_change_rien(admin):
    for champ, valeur in (
        ("global_pourcentage", "0"), ("global_pourcentage", "6"), ("global_pourcentage", "beaucoup"),
        ("plancher_quantite", "-1"), ("plancher_dollars", "hier"), ("par_materiau", "REV-FICTIF=0.001"),
        ("par_categorie", "revetement=9"),
    ):
        reponse = _editer(admin, **{champ: valeur})
        assert reponse.status_code in (400, 422), (champ, valeur, reponse.status_code, reponse.text)
        assert _journal() == []


def test_une_ligne_de_mapping_mal_formee_est_refusee(admin):
    for champ in ("par_categorie", "par_materiau", "categories"):
        for mauvais in ("=0.2", "REV-FICTIF", "REV-FICTIF=0.2=0.3", "REV-FICTIF="):
            reponse = _editer(admin, **{champ: mauvais})
            assert reponse.status_code in (400, 422), (champ, mauvais, reponse.status_code)
    assert _journal() == []


def test_un_motif_vide_est_refuse(admin):
    reponse = _editer(admin, raison="   ")

    assert reponse.status_code in (400, 422)
    assert _journal() == []


def test_une_version_attendue_perimee_est_refusee_sans_ecraser_la_decision_concurrente(admin):
    assert _editer(admin, version_attendue="0").status_code == 303

    reponse = _editer(admin, global_pourcentage="0.10", version_attendue="0")

    assert reponse.status_code == 409
    assert _config_en_vigueur()["global_pourcentage"] == "0.25"
    assert len(_journal()) == 1


def test_le_jeton_csrf_absent_ou_faux_est_refuse(admin):
    for csrf in ("", "faux"):
        reponse = _editer(admin, csrf=csrf)
        assert reponse.status_code == 403
    assert _journal() == []


def test_un_employe_ne_voit_pas_l_ecran_et_ne_l_edite_pas(tmp_path, monkeypatch):
    client = _monde(tmp_path, monkeypatch, aide.EMPLOYE)
    try:
        assert client.get("/seuils-materiaux").status_code == 403
        assert _editer(client).status_code == 403
        assert _journal() == []
    finally:
        client.close()
        stockage.liberer()


def test_le_proprietaire_edite_aussi_et_son_geste_est_audite(tmp_path, monkeypatch):
    client = _monde(tmp_path, monkeypatch, aide.PROPRIETAIRE)
    try:
        assert _editer(client, global_pourcentage="0.22").status_code == 303
        (maillon,) = _journal()
        assert maillon["role"] == "nathan_owner" and maillon["auteur"] == aide.PROPRIETAIRE
    finally:
        client.close()
        stockage.liberer()


def test_la_version_attendue_est_un_entier_borne_et_un_parametre_inconnu_est_refuse(admin):
    assert _editer(admin, version_attendue="abc").status_code == 400
    assert _editer(admin, version_attendue="-1").status_code == 400
    assert admin.get("/seuils-materiaux?inconnu=1").status_code == 400
    assert _journal() == []


def test_un_parametre_de_requete_sur_le_post_ou_un_champ_en_trop_est_refuse(admin):
    assert admin.post("/seuils-materiaux?x=1", data={"csrf": admin.csrf}).status_code == 400
    assert admin.post("/seuils-materiaux", data={"csrf": admin.csrf}).status_code == 400
    donnees = {
        "csrf": admin.csrf, "global_pourcentage": "0.25", "plancher_quantite": "2", "plancher_dollars": "100",
        "par_categorie": "", "par_materiau": "", "categories": "", "raison": "Raison suffisante",
        "version_attendue": "0", "champ_en_trop": "x",
    }
    assert admin.post("/seuils-materiaux", data=donnees).status_code == 400
    assert _journal() == []


def test_une_chaine_d_audit_retouchee_est_un_conflit_409_et_rien_n_est_ecrit(admin):
    with stockage.transaction():
        stockage.maillons(DEPARTEMENT, seuils_variance.REGISTRE).append(42)

    reponse = _editer(admin, version_attendue="0")

    assert reponse.status_code == 409
    assert len(_journal()) == 1


def test_reenregistrer_les_memes_valeurs_redirige_vers_deja_sans_nouveau_maillon(admin):
    assert _editer(admin).status_code == 303
    seconde = _editer(admin, version_attendue="1")

    assert seconde.status_code == 303 and seconde.headers["location"].endswith("?ok=deja")
    assert len(_journal()) == 1


def test_les_badges_distinguent_la_valeur_initiale_l_admin_et_le_proprietaire(admin):
    initial = admin.get("/seuils-materiaux").text
    assert 'name="version_attendue" value="0"' in initial
    assert 'name="global_pourcentage" value="0.3"' in initial
    assert "valeur initiale proposée par l&#x27;architecte" in initial
    assert "Aucun seuil global lisible" not in initial

    assert _editer(admin).status_code == 303
    apres_admin = html.unescape(admin.get("/seuils-materiaux").text)
    assert "adoptés par un administrateur" in apres_admin


def test_le_proprietaire_voit_ses_valeurs_confirmees(tmp_path, monkeypatch):
    client = _monde(tmp_path, monkeypatch, aide.PROPRIETAIRE)
    try:
        assert _editer(client, global_pourcentage="0.22").status_code == 303
        page = html.unescape(client.get("/seuils-materiaux").text)
        assert "confirmés par le propriétaire" in page and "adoptés par un administrateur" not in page
    finally:
        client.close()
        stockage.liberer()


def test_un_message_de_succes_est_un_badge_ok_et_un_journal_sans_valeurs_ne_casse_pas(admin):
    from opsys.console import seuils_materiaux_ui as ui

    page = ui.rendre(None, 0.3, [{"version": 1, "apres": None, "auteur": "admin.fictif", "role": "admin",
                                  "motif": "Vide", "horodatage": "2026-11-03T09:00:00+00:00"}],
                     "/opsys", "jeton", "enregistre")
    assert "badge-ok" in page and "Seuils enregistrés" in page
    assert "—" in page


def test_une_ligne_de_mapping_dupliquee_est_refusee(admin):
    for champ in ("par_categorie", "par_materiau", "categories"):
        reponse = _editer(admin, **{champ: "A=0.1\nA=0.2"})
        assert reponse.status_code == 400
    assert _journal() == []


def test_un_textarea_de_20000_caracteres_est_accepte_et_20001_refuse(admin):
    valide = "".join(f"K{i:04d}=0.2\n" for i in range(2000))
    assert len(valide) == 20000
    assert _editer(admin, par_materiau=valide).status_code == 303

    trop = valide + "\n"
    assert len(trop) == 20001
    assert _editer(admin, par_materiau=trop, version_attendue="1").status_code == 400


def test_un_parametre_ok_est_accepte_et_affiche_le_bandeau(admin):
    page = admin.get("/seuils-materiaux?ok=enregistre")

    assert page.status_code == 200
    assert "badge-ok" in page.text and "Seuils enregistrés" in html.unescape(page.text)


def test_un_contenu_qui_contient_un_secret_est_refuse_en_500(admin, monkeypatch):
    from opsys.console import seuils_materiaux_ui as ui

    monkeypatch.setattr(ui.masquage, "contient_secret", lambda _html: True)

    assert admin.get("/seuils-materiaux").status_code == 500


def test_role_refuse_les_non_admins_et_les_personnes_inactives(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from opsys import identite
    from opsys.console import seuils_materiaux_ui as ui
    from opsys.console.securite import Session

    deps = aide.installer(tmp_path, monkeypatch)
    try:
        with stockage.transaction() as cnx:
            session = Session(utilisateur=aide.EMPLOYE, roles=frozenset({"employee"}), csrf="x", expire=10**12)
            with pytest.raises(HTTPException) as refus:
                ui._role(cnx, session)
            assert refus.value.status_code == 403
            identite.activer(cnx, aide.ADMIN, False)
            session_admin = Session(utilisateur=aide.ADMIN, roles=frozenset({"admin"}), csrf="x", expire=10**12)
            with pytest.raises(HTTPException) as refus:
                ui._role(cnx, session_admin)
            assert refus.value.status_code == 403
    finally:
        assert deps
        stockage.liberer()


def test_une_autorite_retiree_pendant_le_geste_est_refusee(admin, monkeypatch):
    from opsys import identite
    from opsys.console import seuils_materiaux_ui as ui

    vraie = identite.personne_active
    appels = {"n": 0}

    def personne_active_qui_perd_l_autorite(cnx, identifiant):
        appels["n"] += 1
        return vraie(cnx, identifiant) if appels["n"] == 1 else None

    from types import SimpleNamespace

    monkeypatch.setattr(ui, "_role", lambda cnx, session: "admin")
    monkeypatch.setattr(ui, "identite", SimpleNamespace(personne_active=personne_active_qui_perd_l_autorite))

    assert _editer(admin).status_code == 403
    assert _journal() == [], "l'autorité retirée annule la transaction, aucun maillon"


def test_texte_decimal_d_une_valeur_absente_est_un_tiret():
    from opsys.console import seuils_materiaux_ui as ui

    assert ui._texte_decimal(None) == "—"
    assert ui._texte_decimal("0.3") == "0.3"


@pytest.mark.parametrize("texte", ["=0.2", "REV-FICTIF=", "=", " = ", "A=0.1\nA=0.2", "A=1=2"])
def test_le_textarea_refuse_cle_ou_valeur_vide_doublon_et_double_egal_avec_le_code_de_structure(texte):
    # Pinne le CODE de refus (REJ-SEUILS-STRUCTURE) : sans ce test, deux gardes de `_mappage` (clé vide / valeur
    # vide) étaient des mutants « équivalents » parce que le refus tardif de valider_config les rattrapait.
    from m6_material_control import seuils_variance as sv

    from opsys.console import seuils_materiaux_ui as ui

    with pytest.raises(sv.SeuilsRefuses) as exc:
        ui._mappage(texte, "revetement")
    assert "REJ-SEUILS-STRUCTURE" in str(exc.value.args[0] if exc.value.args else exc.value)


def test_le_textarea_accepte_une_entree_valide_et_ignore_les_lignes_vides():
    from opsys.console import seuils_materiaux_ui as ui

    assert ui._mappage("REV-FICTIF=0.2\n\n  SOF-FICTIF = 0.25 \n", "revetement") == {
        "REV-FICTIF": "0.2", "SOF-FICTIF": "0.25"}


def _retoucher_la_chaine_en_base(valeur="0.01"):
    from sqlalchemy import select, update

    from opsys.stockage import codec as codec_stockage
    from opsys.stockage.schema import REGISTRES

    with stockage.transaction() as cnx:
        brut = cnx.execute(select(REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == DEPARTEMENT)
            & (REGISTRES.c.registre == seuils_variance.REGISTRE))).scalar_one()
        faux = codec_stockage.decoder(brut)
        faux["apres"]["global_pourcentage"] = valeur
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == DEPARTEMENT)
            & (REGISTRES.c.registre == seuils_variance.REGISTRE)).values(
                maillon=codec_stockage.encoder(faux)))


def test_une_chaine_retouchee_ne_se_repare_pas_depuis_l_ecran_et_le_post_dit_quoi_faire(admin):
    assert _editer(admin).status_code == 303
    _retoucher_la_chaine_en_base()

    page = admin.get("/seuils-materiaux")
    texte = html.unescape(page.text)

    assert page.status_code == 200
    assert "Chaîne d'audit invalide" in texte
    assert "ne peut pas la réparer" in texte
    assert "administrateur de base" in texte and "hors outil" in texte
    assert 'name="version_attendue" value="0"' in page.text

    reponse = _editer(admin, raison="Réparation après retouche", version_attendue="0")
    detail = reponse.json()["detail"]

    assert reponse.status_code == 409
    assert "REJ-SEUILS-CHAINE" in detail
    assert "administrateur de base" in detail and "hors outil" in detail
    assert _config_en_vigueur() is None
    assert len(_journal()) == 1, "aucune réparation illusoire n'est écrite"


def test_un_maillon_d_audit_malforme_est_ignore_avec_un_bandeau(admin):
    assert _editer(admin).status_code == 303
    with stockage.transaction():
        registre = stockage.maillons(DEPARTEMENT, seuils_variance.REGISTRE)
        registre.append({"type_entree": seuils_variance.TYPE_ENTREE, "nimporte": "quoi"})
        registre.append({"type_entree": seuils_variance.TYPE_ENTREE, "version": "1<script>", "apres": {}})

    page = admin.get("/seuils-materiaux")
    texte = html.unescape(page.text)

    assert page.status_code == 200
    assert "2 entrée(s) du journal d'audit illisible(s) ignorée(s)" in texte
    assert "nimporte" not in texte
    assert "0.25" in texte, "le maillon valide reste lisible"
    assert "administrateur de base" in texte
