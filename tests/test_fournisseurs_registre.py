"""Registre durable : activation sous politique, aucun repli, sélection par département, test de connexion simulé.

Aucun appel réseau réel : la sonde HTTP réelle est remplacée par une fonction qui échoue le test si elle est appelée.
"""

from __future__ import annotations

import json
import socket
import urllib.error

import pytest
from sqlalchemy import select

from opsys import identite
from opsys.fournisseurs import politique, registre, sondes
from opsys.fournisseurs.registre import RegistreErreur
from opsys.secrets_coffre import cle_maitresse, coffre
from opsys.stockage.schema import FOURNISSEURS_CONFIGURATIONS, JOURNAL

FICTIF = True
MOT_DE_PASSE = "mot-de-passe-registre-fictif-2026"
VALEUR = "valeur-fictive-cle-fournisseur-0123456789"


@pytest.fixture(autouse=True)
def _aucun_reseau(monkeypatch):
    def interdit(*_args, **_kwargs):
        raise AssertionError("appel réseau réel interdit en QA")

    monkeypatch.setattr(sondes, "_ouvrir_reel", interdit)
    monkeypatch.setattr(socket, "create_connection", interdit)


@pytest.fixture
def admin(session, tmp_path, monkeypatch):
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))
    with session() as cnx:
        identite.creer_personne(cnx, "admin_fictif", "Admin fictif", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "vendeur_fictif", "Vendeur fictif", MOT_DE_PASSE, ["seller"])
    return "admin_fictif"


def _profil(session, revision=0, **valeurs):
    base = {"usage_commercial": True, "revenu_annuel_usd": 1_500_000, "territoires": ["CA"],
            "heberge_pour_tiers": False}
    with session() as cnx:
        return registre.declarer_profil(cnx, acteur="admin_fictif", revision_attendue=revision, **{**base, **valeurs})


def _configurer(session, identifiant, revision=0, **modifications):
    with session() as cnx:
        return registre.configurer(cnx, acteur="admin_fictif", identifiant=identifiant, modifications=modifications,
                                   revision_attendue=revision)


def _activer(session, identifiant):
    with session() as cnx:
        return registre.activer(cnx, acteur="admin_fictif", identifiant=identifiant)


def _actifs(session):
    with session() as cnx:
        return set(cnx.execute(select(FOURNISSEURS_CONFIGURATIONS.c.identifiant).where(
            FOURNISSEURS_CONFIGURATIONS.c.actif.is_(True))).scalars())


def test_sans_profil_aucune_activation(session, admin):
    _configurer(session, "image.flux2-klein-4b.local")
    decision = _activer(session, "image.flux2-klein-4b.local")
    assert decision.codes == (politique.PROFIL_CLIENT_ABSENT,)
    assert _actifs(session) == set()


def test_activation_conforme_puis_refus_nc_sans_repli(session, admin):
    _profil(session)
    _configurer(session, "image.flux2-klein-4b.local")
    assert _activer(session, "image.flux2-klein-4b.local").conforme
    _configurer(session, "image.flux1-dev")
    decision = _activer(session, "image.flux1-dev")
    assert {politique.FOURNISSEUR_ECARTE, politique.LICENCE_NON_COMMERCIALE} <= set(decision.codes)
    # Aucun repli : rien d'autre n'a été activé ou modifié à la place.
    assert _actifs(session) == {"image.flux2-klein-4b.local"}
    with session() as cnx:
        refus = cnx.execute(select(JOURNAL.c.details).where(JOURNAL.c.action == "fournisseurs.activation.refusee"))
        assert "LICENCE_NON_COMMERCIALE" in refus.scalar_one()


@pytest.mark.parametrize(("profil", "identifiant", "code"), [
    ({"revenu_annuel_usd": 6_000_000}, "image.flux3-image-klein.local", politique.SEUIL_REVENU_DEPASSE),
    ({"territoires": ["CA", "UE"]}, "video.hunyuanvideo-1.5", politique.TERRITOIRE_EXCLU),
    ({"heberge_pour_tiers": True}, "tts.fish-speech", politique.SERVICE_TIERS_INTERDIT),
    ({}, "tts.xtts-v2", politique.LICENCE_NON_COMMERCIALE),
])
def test_refus_par_profil_avec_code(session, admin, profil, identifiant, code):
    _profil(session, **profil)
    _configurer(session, identifiant)
    decision = _activer(session, identifiant)
    assert code in decision.codes and not decision.conforme
    assert identifiant not in _actifs(session)


def test_selection_par_departement_et_defaut_global(session, admin):
    _profil(session)
    for ident in ("image.flux2-klein-4b.local", "image.qwen-image-2512.local", "ocr.tesseract-5.5.local",
                  "ocr.paddleocr.local"):
        _configurer(session, ident)
        assert _activer(session, ident).conforme
    with session() as cnx:
        registre.selectionner(cnx, acteur=admin, capacite="image", identifiant="image.flux2-klein-4b.local")
        registre.selectionner(cnx, acteur=admin, capacite="image", identifiant="image.qwen-image-2512.local",
                              departement="m07-marketing")
        registre.selectionner(cnx, acteur=admin, capacite="ocr", identifiant="ocr.paddleocr.local",
                              departement="m05-financecore")
        assert registre.resoudre(cnx, "image", "m07-marketing").vers_json() == {
            "identifiant": "image.qwen-image-2512.local", "portee": "m07-marketing"}
        assert registre.resoudre(cnx, "image", "m03-estimation").vers_json() == {
            "identifiant": "image.flux2-klein-4b.local", "portee": "*"}
        assert registre.resoudre(cnx, "ocr", "m05-financecore").fournisseur.identifiant == "ocr.paddleocr.local"
        with pytest.raises(RegistreErreur) as exc:
            registre.resoudre(cnx, "ocr", "m03-estimation")
        assert exc.value.code == "AUCUN_FOURNISSEUR"
        with pytest.raises(RegistreErreur) as exc:
            registre.selectionner(cnx, acteur=admin, capacite="ocr", identifiant="image.flux2-klein-4b.local")
        assert exc.value.code == "CAPACITE_INCOMPATIBLE"
        with pytest.raises(RegistreErreur) as exc:
            registre.selectionner(cnx, acteur=admin, capacite="image", identifiant="image.flux2-klein-4b.local",
                                  departement="marketing")
        assert exc.value.code == "DEPARTEMENT_INVALIDE"


def test_resolution_sans_repli_quand_la_selection_devient_non_conforme(session, admin):
    profil = _profil(session)
    for ident in ("image.flux2-klein-4b.local", "image.flux3-image-klein.local"):
        _configurer(session, ident, licence_lue=ident.startswith("image.flux3"))
        assert _activer(session, ident).conforme
    with session() as cnx:
        registre.selectionner(cnx, acteur=admin, capacite="image", identifiant="image.flux2-klein-4b.local")
        registre.selectionner(cnx, acteur=admin, capacite="image", identifiant="image.flux3-image-klein.local",
                              departement="m07-marketing")
    _profil(session, revision=profil["revision"], revenu_annuel_usd=6_000_000)  # le client franchit le seuil
    with session() as cnx, pytest.raises(RegistreErreur) as exc:
        registre.resoudre(cnx, "image", "m07-marketing")
    assert exc.value.code == "REFUS_POLITIQUE" and exc.value.codes == (politique.SEUIL_REVENU_DEPASSE,)
    with session() as cnx:
        registre.desactiver(cnx, acteur=admin, identifiant="image.flux2-klein-4b.local")
        with pytest.raises(RegistreErreur) as exc:
            registre.resoudre(cnx, "image", "m03-estimation")
    assert exc.value.code == "FOURNISSEUR_INACTIF"


def test_licence_du_catalogue_immuable_et_lecture_consignee(session, admin):
    _profil(session)
    with session() as cnx, pytest.raises(RegistreErreur) as exc:
        registre.configurer(cnx, acteur=admin, identifiant="image.flux1-dev",
                            modifications={"licence": {"usage_commercial": "autorise"}})
    assert exc.value.code == "CHAMP_NON_MODIFIABLE"
    _configurer(session, "ocr.docling.local")
    assert _activer(session, "ocr.docling.local").codes == (politique.LICENCE_A_VERIFIER,)
    vue = _configurer(session, "ocr.docling.local", revision=1, licence_lue=True)
    assert vue["licence_lue_par"].startswith("admin_fictif le ")
    assert _activer(session, "ocr.docling.local").conforme


def test_roles_et_revision(session, admin):
    with session() as cnx, pytest.raises(RegistreErreur) as exc:
        registre.configurer(cnx, acteur="vendeur_fictif", identifiant="ocr.paddleocr.local")
    assert exc.value.statut_http == 403
    _configurer(session, "ocr.paddleocr.local")
    with session() as cnx, pytest.raises(RegistreErreur) as exc:
        registre.configurer(cnx, acteur=admin, identifiant="ocr.paddleocr.local", revision_attendue=0)
    assert exc.value.code == "CONFLIT_REVISION"


def test_declaration_personnalisee_et_secret_reference(session, admin):
    _profil(session)
    declaration = {
        "capacite": "llm", "mode": "api", "modele": "modèle API fictif", "point_acces": "https://api.fictive.example/v1",
        "residence_donnees": "CA", "efvp_ref": "efvp-fictive-1", "contrat_ref": "contrat-fictif-1",
        "reference_secret": "coffre:fournisseur.fictif",
        "licence": {"code": "Propriétaire (API)", "poids": None, "usage_commercial": "sur_contrat",
                    "service_tiers": "incertain", "integration": "api", "source": "contrat fictif"},
        "cout_unitaire": {"unite": "million_jetons", "montant": "0.40", "devise": "USD", "source": "contrat fictif"},
    }
    with session() as cnx, pytest.raises(RegistreErreur) as exc:
        registre.configurer(cnx, acteur=admin, identifiant="llm.fictif.api", declaration=declaration)
    assert exc.value.code == "SECRET_INDISPONIBLE"  # référence vers un secret absent du coffre
    with session() as cnx:
        coffre.definir(cnx, acteur=admin, nom="fournisseur.fictif", service="fournisseur_modele", valeur=VALEUR)
        vue = registre.configurer(cnx, acteur=admin, identifiant="llm.fictif.api", declaration=declaration)
    assert vue["statut_catalogue"] == "declare" and vue["politique"]["conforme"]
    assert VALEUR not in json.dumps(vue)
    with session() as cnx:
        stocke = cnx.execute(select(FOURNISSEURS_CONFIGURATIONS.c.definition)).scalar_one()
    assert VALEUR not in stocke and "coffre:fournisseur.fictif" in stocke


class _Ouvreur:
    def __init__(self, comportement):
        self.comportement, self.requetes = comportement, []

    def __call__(self, requete, delai_s):
        self.requetes.append((requete.full_url, dict(requete.header_items()), delai_s))
        return self.comportement(requete)


def _api_fictive(session, admin):
    _profil(session)
    with session() as cnx:
        coffre.definir(cnx, acteur=admin, nom="fournisseur.fictif", service="fournisseur_modele", valeur=VALEUR)
        registre.configurer(cnx, acteur=admin, identifiant="llm.fictif.api", declaration={
            "capacite": "llm", "mode": "api", "modele": "fictif", "point_acces": "https://api.fictive.example/v1",
            "residence_donnees": "QC", "contrat_ref": "contrat-fictif", "reference_secret": "coffre:fournisseur.fictif",
            "licence": {"code": "Propriétaire (API)", "poids": None, "usage_commercial": "sur_contrat",
                        "service_tiers": "autorise", "integration": "api", "source": "contrat fictif"}})


@pytest.mark.parametrize(("comportement", "statut"), [
    (lambda r: 200, "succes"),
    (lambda r: (_ for _ in ()).throw(urllib.error.HTTPError(r.full_url, 401, "non", None, None)), "echec"),
    (lambda r: (_ for _ in ()).throw(TimeoutError()), "delai"),
    (lambda r: (_ for _ in ()).throw(urllib.error.URLError(TimeoutError())), "delai"),
    (lambda r: (_ for _ in ()).throw(urllib.error.URLError("refus")), "echec"),
])
def test_test_de_connexion_simule(session, admin, comportement, statut):
    _api_fictive(session, admin)
    ouvreur = _Ouvreur(comportement)
    resultat = registre.tester(session, acteur=admin, identifiant="llm.fictif.api", sonde=sondes.SondeHttp(ouvreur),
                               delai_s=2.0)
    assert resultat["statut"] == statut
    [(url, entetes, delai)] = ouvreur.requetes
    assert url == "https://api.fictive.example/v1/models" and delai == 2.0
    assert entetes["Authorization"] == f"Bearer {VALEUR}"  # injecté côté serveur au moment de l'appel
    assert VALEUR not in json.dumps(resultat)
    with session() as cnx:
        vue = registre.vue(cnx, "llm.fictif.api")
        assert vue["dernier_test"]["statut"] == statut
        assert VALEUR not in json.dumps(registre.lister(cnx))
        [acces] = [r for r in coffre.journal(cnx, "fournisseur.fictif") if r["action"] == "resolution"]
    assert acces["usage"] == "fournisseur:llm.fictif.api" and acces["acteur"] == "console:admin_fictif"


def test_test_de_connexion_refuse_sans_appel_si_non_conforme(session, admin):
    _api_fictive(session, admin)
    with session() as cnx:
        coffre.revoquer(cnx, acteur=admin, nom="fournisseur.fictif")
    ouvreur = _Ouvreur(lambda r: 200)
    resultat = registre.tester(session, acteur=admin, identifiant="llm.fictif.api", sonde=sondes.SondeHttp(ouvreur))
    assert resultat["statut"] == "echec" and "COFFRE_SECRET_REVOQUE" in resultat["detail"]
    assert ouvreur.requetes == []
    _configurer(session, "tts.xtts-v2")
    resultat = registre.tester(session, acteur=admin, identifiant="tts.xtts-v2", sonde=sondes.SondeHttp(ouvreur))
    assert resultat["statut"] == "refuse_politique" and politique.LICENCE_NON_COMMERCIALE in resultat["refus"]
    assert ouvreur.requetes == []


def test_sondes_locales(session, admin):
    _profil(session)
    _configurer(session, "avatar.talkinghead")
    assert registre.tester(session, acteur=admin, identifiant="avatar.talkinghead")["statut"] == "non_verifiable"
    _configurer(session, "ocr.paddleocr.local", point_acces="module:module_fictif_absent_opsys")
    resultat = registre.tester(session, acteur=admin, identifiant="ocr.paddleocr.local")
    assert resultat["statut"] == "echec" and "absent" in resultat["detail"]
    _configurer(session, "ocr.paddleocr.local", revision=1, point_acces="module:json")
    assert registre.tester(session, acteur=admin, identifiant="ocr.paddleocr.local")["statut"] == "succes"
