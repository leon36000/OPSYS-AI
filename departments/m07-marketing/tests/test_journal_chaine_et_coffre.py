"""Le journal chaîné (commun à WordPress et au sas social) et le fournisseur de secret branché sur le vrai coffre."""

from __future__ import annotations

import contextlib

import pytest
from m7_marketing import journal_chaine
from m7_marketing.secret_coffre import fournisseur_du_coffre

from opsys import identite, stockage
from opsys.secrets_coffre import cle_maitresse, coffre, masquage
from opsys.secrets_coffre.erreurs import CoffreErreur

FICTIF = True
VALEUR = "jeton-fictif-de-page-0123456789-XYZ"


def test_un_journal_se_chaine_et_se_verifie():
    journal: list = []
    a = journal_chaine.ajouter(journal, "a", {"x": 1}, "2026-01-05T15:00:00Z")
    b = journal_chaine.ajouter(journal, "b", {"y": [1, 2]}, "2026-01-05T15:00:01Z")
    assert a["rang"] == 0 and b["rang"] == 1 and a["chaine"] != b["chaine"]
    assert journal_chaine.verifier(journal) == [] and journal_chaine.integre(journal)
    assert [m["type"] for m in journal_chaine.de_type(journal, "b")] == ["b"]


def test_le_premier_maillon_part_de_la_genese():
    journal: list = []
    maillon = journal_chaine.ajouter(journal, "a", {}, "h")
    assert maillon["chaine"] == journal_chaine._chaine(
        journal_chaine.GENESE, {k: v for k, v in maillon.items() if k != "chaine"}
    )


@pytest.mark.parametrize(
    "alteration",
    [
        lambda j: j[0].__setitem__("x", 2),
        lambda j: j[0].__setitem__("type", "autre"),
        lambda j: j[1].__setitem__("horodatage", "2027-01-01T00:00:00Z"),
        lambda j: j.pop(0),
        lambda j: j.reverse(),
        lambda j: j.__delitem__(1),
        lambda j: j[1].__setitem__("rang", 5),
        lambda j: j[0].pop("chaine"),
        lambda j: j.__setitem__(0, "pas un dict"),
    ],
)
def test_toute_alteration_du_journal_est_detectee(alteration):
    journal: list = []
    for i in range(3):
        journal_chaine.ajouter(journal, "t", {"x": i + 1}, f"2026-01-05T15:00:0{i}Z")
    alteration(journal)
    assert journal_chaine.verifier(journal) != []


def test_un_maillon_retire_avec_la_chaine_recalculee_est_vu_par_les_rangs():
    """L'attaquant qui refait toute la chaîne ne peut pas cacher qu'un rang manque."""
    journal: list = []
    for i in range(4):
        journal_chaine.ajouter(journal, "t", {"x": i}, "h")
    sans_le_deuxieme, precedent = [], journal_chaine.GENESE
    for ancien in (journal[0], journal[2], journal[3]):
        corps = {k: v for k, v in ancien.items() if k != "chaine"}
        sans_le_deuxieme.append({**corps, "chaine": journal_chaine._chaine(precedent, corps)})
        precedent = sans_le_deuxieme[-1]["chaine"]
    problemes = journal_chaine.verifier(sans_le_deuxieme)
    assert problemes and "numéro" in problemes[0], problemes
    assert not any("hachage" in p for p in problemes), "la chaîne, elle, est cohérente : seuls les rangs trahissent"


def test_les_cles_reservees_ne_peuvent_pas_etre_redefinies():
    for cle in ("rang", "type", "horodatage", "chaine"):
        with pytest.raises(ValueError):
            journal_chaine.ajouter([], "t", {cle: 1}, "h")


def test_un_maillon_non_json_natif_est_refuse_au_calcul_de_la_chaine():
    with pytest.raises(ValueError):
        journal_chaine.ajouter([], "t", {"x": float("nan")}, "h")


@pytest.fixture
def coffre_pret(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    chemin = dossier / "coffre.cle"
    cle_maitresse.generer_fichier(chemin)
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(chemin))
    monkeypatch.delenv(cle_maitresse.ENV_CLE, raising=False)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin_fictif", "Admin fictif", "mot-de-passe-coffre-fictif-2026", ["admin"])
        coffre.definir(cnx, acteur="admin_fictif", nom="social.facebook.horizon", service="meta", valeur=VALEUR)
    yield
    stockage.liberer()


def test_le_fournisseur_du_coffre_rend_le_jeton_le_temps_de_l_appel_et_le_masque(coffre_pret):
    fournisseur = fournisseur_du_coffre("social.facebook.horizon", "connecteur:social.facebook", "m07-marketing")
    with fournisseur() as jeton:
        assert jeton == VALEUR
        assert masquage.masquer_texte(f"Authorization {jeton}") == "Authorization •••"
    assert masquage.masquer_texte(VALEUR) == VALEUR, "oublié après l'appel"
    with stockage.transaction() as cnx:
        acces = coffre.journal(cnx, "social.facebook.horizon")
    assert acces[0]["action"] == "resolution" and acces[0]["resultat"] == "ok" and VALEUR not in str(acces)


def test_le_fournisseur_suit_la_rotation_et_la_revocation_sans_rien_garder(coffre_pret):
    fournisseur = fournisseur_du_coffre("social.facebook.horizon", "connecteur:social.facebook", "m07-marketing")
    with stockage.transaction() as cnx:
        coffre.rotation(
            cnx, acteur="admin_fictif", nom="social.facebook.horizon", valeur="nouvelle-valeur-fictive-9876543210"
        )
    with fournisseur() as jeton:
        assert jeton == "nouvelle-valeur-fictive-9876543210"
    with stockage.transaction() as cnx:
        coffre.revoquer(cnx, acteur="admin_fictif", nom="social.facebook.horizon")
    with pytest.raises(CoffreErreur) as erreur, fournisseur():
        pass
    assert erreur.value.code == "COFFRE_SECRET_REVOQUE"


def test_le_coffre_refuse_la_resolution_dans_une_transaction_metier_donc_jamais_depuis_un_outil(coffre_pret):
    fournisseur = fournisseur_du_coffre("social.facebook.horizon", "connecteur:social.facebook", "m07-marketing")
    with stockage.transaction(), pytest.raises(CoffreErreur) as erreur, fournisseur():
        pass
    assert erreur.value.code == "COFFRE_TRANSACTION_METIER"


def test_un_nom_inconnu_est_refuse_et_le_refus_est_journalise(coffre_pret):
    fournisseur = fournisseur_du_coffre("social.inconnu.compte", "connecteur:social.facebook", "m07-marketing")
    with pytest.raises(CoffreErreur) as erreur, fournisseur():
        pass
    assert erreur.value.code == "COFFRE_SECRET_INCONNU"
    with stockage.transaction() as cnx:
        assert coffre.journal(cnx, "social.inconnu.compte")[0]["resultat"] == "refus"


def test_le_fournisseur_s_integre_a_l_executeur_du_sas_de_bout_en_bout(coffre_pret):
    """Le jeton réel du coffre arrive à l'adaptateur de test, et nulle part ailleurs."""
    import json
    import sys
    from datetime import UTC, datetime
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent / "sas_social"))
    from fabriques_sociales import COMPTE, HORODATAGE, MAINTENANT, publication
    from m7_marketing.sas_social import doubles, executeur, politique, reseaux, service

    pol = politique.PolitiqueSas()
    declarations = reseaux.declarations_par_defaut()
    journal: list = []
    cree = service.composer(
        journal, publication("facebook"), "cle-coffre-0123456789abc", {("facebook", COMPTE)}, "agent", HORODATAGE
    )
    assert service.soumettre(journal, cree["publication_id"], declarations, pol, MAINTENANT, HORODATAGE)["accepte"]
    assert service.approuver(
        journal,
        cree["publication_id"],
        cree["empreinte"],
        3,
        {"par": "nathan", "role": "nathan_owner", "source": "approbation"},
        declarations,
        pol,
        MAINTENANT,
        HORODATAGE,
    )["accepte"]
    double = doubles.DoubleFacebook(jeton_attendu=VALEUR)
    fournisseur = fournisseur_du_coffre("social.facebook.horizon", "connecteur:social.facebook", "m07-marketing")
    resultat = executeur.executer(
        journal, cree["publication_id"], {"facebook": double}, fournisseur, pol, datetime(2026, 1, 6, 15, 0, tzinfo=UTC)
    )
    assert resultat["publie"] is True and len(double.publiees) == 1
    assert VALEUR not in json.dumps(journal) and contextlib.nullcontext
