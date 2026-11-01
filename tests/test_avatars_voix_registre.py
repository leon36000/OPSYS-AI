"""Registre des voix et visages, consentements, qualifications et politique de disponibilité des canaux.

Données fictives ; moteurs fictifs dont le « point d'accès » est le module standard `json` (sonde locale réelle du
serveur, sans réseau). Aucun appel réseau n'est possible : la sonde HTTP réelle et les connexions sont interdites.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import socket
from pathlib import Path

import avatars_voix_aide as aide
import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from opsys import identite, stockage
from opsys.avatars_voix import codes, lecture, modele, politique, registre
from opsys.avatars_voix.codes import AvatarRefus
from opsys.fournisseurs import registre as fournisseurs
from opsys.fournisseurs import sondes
from opsys.fournisseurs.sondes import ResultatSonde
from opsys.stockage.schema import AVATARS_CANAUX, AVATARS_QUALIFICATIONS, JOURNAL

FICTIF = True
MAINTENANT = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _aucun_reseau(monkeypatch):
    def interdit(*_args, **_kwargs):
        raise AssertionError("appel réseau réel interdit en QA")

    monkeypatch.setattr(sondes, "_ouvrir_reel", interdit)
    monkeypatch.setattr(socket, "create_connection", interdit)


@pytest.fixture
def scenario(session):
    return aide.monter(session)


def _evaluer(session, identite_, canal="voix", **options):
    options.setdefault("canaux_realises", aide.TOUS_LES_CANAUX)
    options.setdefault("maintenant", MAINTENANT)
    with session() as cnx:
        return politique.evaluer_canal(cnx, identite_, canal, **options)


def _codes(verdict) -> set[str]:
    return set(verdict.codes)


def _refus(exc_info) -> AvatarRefus:
    return exc_info.value


# --- catalogue de codes ----------------------------------------------------------------------------------------
def test_catalogue_de_codes_ferme_unique_et_prefixe():
    tous = codes.CODES_AVATAR + codes.CODES_VOIX
    assert len(set(tous)) == len(tous)
    assert all(c.startswith(("REJ-AVATAR-", "REJ-VOIX-")) for c in tous)
    with pytest.raises(ValueError):
        AvatarRefus("REJ-AVATAR-INVENTE")
    with pytest.raises(ValueError):
        codes.verifier_code("REJ-VOIX-INVENTE")
    assert "REJ-AVATAR-BIOMETRIE-NON-DECLAREE" in codes.CODES_AVATAR


def test_la_documentation_cite_chaque_code_et_chaque_code_est_employe():
    racine = Path(__file__).resolve().parents[1]
    doc = (racine / "docs" / "architecture" / "AVATARS-VOIX.md").read_text(encoding="utf-8")
    sources = "".join(p.read_text(encoding="utf-8") for p in (racine / "src/opsys/avatars_voix").glob("*.py")
                      if p.name != "codes.py")
    for code in codes.CODES_AVATAR + codes.CODES_VOIX:
        assert f"`{code}`" in doc, f"{code} absent de la table des codes"
        assert code in sources, f"{code} n'est employé nulle part"


# --- migration 0039 --------------------------------------------------------------------------------------------
def test_la_tete_alembic_est_0039_et_la_descente_est_sure(tmp_path):
    url = "sqlite:///" + str(tmp_path / "migration.db")
    cfg = stockage._config()
    from alembic.script import ScriptDirectory

    assert ScriptDirectory.from_config(cfg).get_current_head() == "0039"
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0039")
        cnx.execute(text("INSERT INTO avatars_entrees (identifiant, genre, langue, origine, empreinte_vocale_tiers, "
                         "manifeste, empreinte_manifeste, etat, revision, cree_le, modifie_le, modifie_par) VALUES "
                         "('voix.fictive.defaut','voix','fr-CA','generique',0,'{}',:h,'prevu',1,'x','x','fictif')"),
                    {"h": "a" * 64})
        with pytest.raises(RuntimeError, match="rétrogradation refusée"):
            command.downgrade(cfg, "0038")
    vide = "sqlite:///" + str(tmp_path / "vide.db")
    with stockage.moteur(vide).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0039")
        tables = {r[0] for r in cnx.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert {"avatars_entrees", "avatars_consentements", "avatars_qualifications", "avatars_canaux"} <= tables
        command.downgrade(cfg, "0038")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0038"
        restes = {r[0] for r in cnx.execute(text(
            "SELECT name FROM sqlite_master WHERE name LIKE 'avatars_%'"))}
        assert restes == set()
        command.upgrade(cfg, "0039")  # remonter après descente : idempotent
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0039"


def test_les_contraintes_de_table_refusent_l_incoherent(session, scenario):
    with pytest.raises(DBAPIError), session() as cnx:  # « prevu » exige l'absence de moteur lié
        cnx.execute(text("UPDATE avatars_entrees SET etat='prevu' WHERE identifiant=:i"), {"i": scenario.voix})
    with pytest.raises(DBAPIError), session() as cnx:  # une voix n'a pas l'origine « ressemblance »
        cnx.execute(text("UPDATE avatars_entrees SET origine='ressemblance' WHERE identifiant=:i"),
                    {"i": scenario.voix})
    with pytest.raises(DBAPIError), session() as cnx:  # nature de qualification inconnue
        cnx.execute(text("INSERT INTO avatars_qualifications (quand, acteur, fournisseur_id, empreinte_runtime, "
                         "nature, statut, detail) VALUES ('x','a',:f,:h,'invente','succes','')"),
                    {"f": aide.TTS, "h": "a" * 64})


def test_le_journal_des_qualifications_est_append_only(session, scenario):
    with session() as cnx:
        assert cnx.execute(select(AVATARS_QUALIFICATIONS.c.id)).first() is not None
    with pytest.raises(DBAPIError, match="immuable"), session() as cnx:
        cnx.execute(text("UPDATE avatars_qualifications SET statut='succes', nature='reel'"))
    with pytest.raises(DBAPIError, match="immuable"), session() as cnx:
        cnx.execute(text("DELETE FROM avatars_qualifications"))


def _clone(session, scenario, **options):
    voix = "voix.lea.quebec"
    with session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant=voix, origine="clonee", **options)
    return voix


def _consentement(session, voix, portee=("clonage", "synthese"), **options):
    valeurs = {"locuteur_ref": "comedien-fictif-01", "document_ref": "contrat-fictif-001.pdf",
               "document_sha256": aide.SHA, "signe_le": "2026-10-01"}
    with session() as cnx:
        return registre.enregistrer_consentement(cnx, acteur=aide.ADMIN, identifiant=voix, portee=portee,
                                                 maintenant=MAINTENANT, **{**valeurs, **options})


def test_un_consentement_ne_se_modifie_ni_ne_se_supprime_et_ne_se_revoque_qu_une_fois(session, scenario):
    voix = _clone(session, scenario)
    ident = _consentement(session, voix)["consentement_id"]
    with pytest.raises(DBAPIError, match="immuable"), session() as cnx:
        cnx.execute(text("UPDATE avatars_consentements SET portee='[\"clonage\"]'"))
    with pytest.raises(DBAPIError, match="supprimable"), session() as cnx:
        cnx.execute(text("DELETE FROM avatars_consentements"))
    with session() as cnx:
        registre.revoquer_consentement(cnx, acteur=aide.ADMIN, consentement_id=ident, motif="retrait du locuteur",
                                       maintenant=MAINTENANT)
    with pytest.raises(DBAPIError, match="immuable"), session() as cnx:  # une révocation ne s'annule pas
        cnx.execute(text("UPDATE avatars_consentements SET revoque_le=NULL, revoque_par=NULL"))
    with pytest.raises(DBAPIError, match="immuable"), session() as cnx:
        cnx.execute(text("UPDATE avatars_consentements SET revoque_motif='autre'"))
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.revoquer_consentement(cnx, acteur=aide.ADMIN, consentement_id=ident, motif="encore")
    assert exc.value.code == "REJ-AVATAR-CONSENTEMENT-DEJA-REVOQUE"


def test_la_descente_est_refusee_quand_un_consentement_existe(session, scenario):
    cfg = stockage._config()
    with pytest.raises(RuntimeError, match="rétrogradation refusée"), stockage.moteur().begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.downgrade(cfg, "0038")


# --- écritures : administration, identifiants, révisions -------------------------------------------------------
@pytest.mark.parametrize("acteur,statut", [("vendeur_fictif", 403), ("inconnu_fictif", 401), ("", 401), (None, 401)])
def test_toute_ecriture_exige_un_administrateur_actif(session, scenario, acteur, statut):
    ecritures = [
        lambda c: registre.inscrire_entree(c, acteur=acteur, identifiant="voix.lea.autre"),
        lambda c: registre.lier_runtime(c, acteur=acteur, identifiant=scenario.voix, fournisseur_id=aide.TTS),
        lambda c: registre.enregistrer_consentement(c, acteur=acteur, identifiant=scenario.voix, locuteur_ref="x-yz",
                                                    portee=["synthese"], document_ref="d", document_sha256=aide.SHA,
                                                    signe_le="2026-10-01"),
        lambda c: registre.revoquer_consentement(c, acteur=acteur, consentement_id="a" * 32, motif="m"),
        lambda c: registre.declarer_biometrie(c, acteur=acteur, identifiant=scenario.voix, reference="r",
                                              declaree_le="2026-01-01"),
        lambda c: politique.declarer_canal(c, acteur=acteur, identite=scenario.identite, canal="voix"),
        lambda c: politique.retirer_canal(c, acteur=acteur, departement=aide.DEPARTEMENT, canal="voix"),
    ]
    for ecriture in ecritures:
        with pytest.raises(AvatarRefus) as exc, session() as cnx:
            ecriture(cnx)
        assert exc.value.code == "REJ-AVATAR-ADMIN-REQUIS" and exc.value.statut_http == statut
    with pytest.raises(AvatarRefus) as exc:
        registre.qualifier(session, acteur=acteur, fournisseur_id=aide.TTS)
    assert exc.value.code == "REJ-AVATAR-ADMIN-REQUIS"


def test_un_compte_desactive_ne_peut_plus_ecrire(session, scenario):
    with session() as cnx:
        identite.creer_personne(cnx, "ancien_admin", "Ancien admin", aide.MOT_DE_PASSE, ["admin"])
        cnx.execute(text("UPDATE personnes SET actif = 0 WHERE identifiant = 'ancien_admin'"))
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.inscrire_entree(cnx, acteur="ancien_admin", identifiant="voix.lea.autre")
    assert exc.value.code == "REJ-AVATAR-ADMIN-REQUIS"


@pytest.mark.parametrize("identifiant", [
    "voix.Lea.defaut", "voix.lea", "tts.lea.defaut", "visage..defaut", "voix.lea.defaut.a.b.c", "voix.lea. defaut",
    "voix.lea.défaut", "", "voix.lea/../x", "voix." + "a" * 70 + ".x", 42, None, ["voix.lea.defaut"],
])
def test_identifiants_logiques_mal_formes_refuses(session, scenario, identifiant):
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant=identifiant)
    assert exc.value.code == "REJ-AVATAR-IDENTIFIANT-INVALIDE"


@pytest.mark.parametrize("options", [
    {"langue": "fr-XX"}, {"accent": "Québécois!"}, {"accent": 5}, {"origine": "inconnue"},
    {"origine": "ressemblance"},  # une voix ne se « ressemble » pas
    {"actif_usage_commercial": "autorise"},  # propre au visage
    {"empreinte_vocale_tiers": "oui"},
])
def test_declarations_de_voix_invalides_refusees(session, scenario, options):
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant="voix.lea.autre", **options)
    assert exc.value.code == "REJ-AVATAR-DECLARATION-INVALIDE"


@pytest.mark.parametrize("options", [
    {}, {"actif_usage_commercial": "permis"}, {"actif_usage_commercial": "autorise", "accent": "quebecois"},
    {"actif_usage_commercial": "autorise", "origine": "clonee"},
    {"actif_usage_commercial": "autorise", "empreinte_vocale_tiers": True},
])
def test_declarations_de_visage_invalides_refusees(session, scenario, options):
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant="visage.lea.autre", **options)
    assert exc.value.code == "REJ-AVATAR-DECLARATION-INVALIDE"


def test_revision_optimiste_et_double_soumission(session, scenario):
    with session() as cnx:
        entree = registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant="voix.lea.autre")
    assert entree["revision"] == 1 and entree["etat"] == "prevu" and entree["fournisseur_id"] is None
    with pytest.raises(AvatarRefus) as exc, session() as cnx:  # même révision attendue 0 : double soumission
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant="voix.lea.autre")
    assert exc.value.code == "REJ-AVATAR-CONFLIT-REVISION"
    with session() as cnx:
        suite = registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant="voix.lea.autre", langue="fr-FR",
                                         revision_attendue=1)
    assert suite["revision"] == 2 and suite["langue"] == "fr-FR"
    assert suite["empreinte_manifeste"] != entree["empreinte_manifeste"]


def test_ecritures_journalisees_sans_donnee_sensible(session, scenario):
    voix = _clone(session, scenario)
    _consentement(session, voix, locuteur_ref="comedien-secret-42")
    with session() as cnx:
        lignes = [dict(r) for r in cnx.execute(select(JOURNAL).where(JOURNAL.c.action.like("avatars.%")))
                  .mappings()]
    actions = {ligne["action"] for ligne in lignes}
    assert {"avatars.entree.inscrire", "avatars.consentement.enregistrer", "avatars.runtime.lier",
            "avatars.qualifier"} <= actions
    assert all(ligne["par"] == aide.ADMIN for ligne in lignes)
    assert "comedien-secret-42" not in json.dumps(lignes)  # la référence du locuteur n'entre pas au journal d'audit


# --- le chemin complet ---------------------------------------------------------------------------------------
def test_chemin_complet_les_deux_canaux_deviennent_disponibles_puis_se_retirent(session, scenario):
    for canal in ("voix", "audiovisuel"):
        verdict = _evaluer(session, scenario.identite, canal)
        assert verdict.conforme, verdict.codes
    with session() as cnx:
        for canal in ("voix", "audiovisuel"):
            decision = politique.declarer_canal(cnx, acteur=aide.ADMIN, identite=scenario.identite, canal=canal,
                                                canaux_realises=aide.TOUS_LES_CANAUX, maintenant=MAINTENANT)
            assert decision.conforme
            assert politique.etat_canal(cnx, scenario.identite, canal, canaux_realises=aide.TOUS_LES_CANAUX,
                                        maintenant=MAINTENANT)["etat"] == "disponible"
        preuves = json.loads(cnx.execute(select(AVATARS_CANAUX.c.preuves).where(
            AVATARS_CANAUX.c.canal == "audiovisuel")).scalar_one())
    assert {scenario.voix, scenario.visage, "stt"} <= set(preuves)
    assert all(p["qualification_id"] for p in preuves.values())
    with session() as cnx:
        assert politique.retirer_canal(cnx, acteur=aide.ADMIN, departement=aide.DEPARTEMENT, canal="voix") is True
        assert politique.retirer_canal(cnx, acteur=aide.ADMIN, departement=aide.DEPARTEMENT, canal="voix") is False
        assert politique.etat_canal(cnx, scenario.identite, "voix", canaux_realises=aide.TOUS_LES_CANAUX,
                                    maintenant=MAINTENANT)["etat"] == "qualifie"


def test_par_defaut_aucun_canal_n_est_realise_donc_rien_ne_peut_etre_declare_disponible(session, scenario):
    verdict = _evaluer(session, scenario.identite, "voix", canaux_realises=frozenset({"messagerie"}))
    assert _codes(verdict) == {"REJ-AVATAR-CANAL-NON-REALISE"}
    with session() as cnx:
        decision = politique.declarer_canal(cnx, acteur=aide.ADMIN, identite=scenario.identite, canal="voix")
        assert not decision.conforme and decision.codes == ("REJ-AVATAR-CANAL-NON-REALISE",)
        assert cnx.execute(select(AVATARS_CANAUX)).first() is None  # rien n'a été déclaré
        journal = cnx.execute(select(JOURNAL.c.action).where(JOURNAL.c.action == "avatars.canal.refuse")).scalars()
        assert list(journal) == ["avatars.canal.refuse"]
        with pytest.raises(AvatarRefus) as exc:
            decision.exiger()
        assert exc.value.code == "REJ-AVATAR-CANAL-NON-REALISE"


def test_canal_inconnu_ou_non_gouverne_refuse(session, scenario):
    for canal in ("messagerie", "video", "", None):
        with pytest.raises(AvatarRefus) as exc, session() as cnx:
            politique.evaluer_canal(cnx, scenario.identite, canal)
        assert exc.value.code == "REJ-AVATAR-CANAL-INCONNU"


def test_la_politique_appelle_le_moteur_de_licence_du_registre_de_fournisseurs(session, scenario, monkeypatch):
    appeles = []
    reel = politique.politique_licence.evaluer

    def espion(fournisseur, profil):
        appeles.append(fournisseur.identifiant)
        return reel(fournisseur, profil)

    monkeypatch.setattr(politique.politique_licence, "evaluer", espion)
    _evaluer(session, scenario.identite, "audiovisuel")
    assert set(appeles) == {aide.TTS, aide.AVATAR, aide.STT}


# --- (a) runtime enregistré, actif, qualifié par un test réellement exécuté -----------------------------------
def test_entree_sans_runtime_reste_prevue_et_le_canal_est_refuse(session):
    aide.creer_personnes(session)
    aide.profil(session)
    identites = aide.identite_m01()
    with session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant=identites.voix)
    verdict = _evaluer(session, identites)
    assert {"REJ-AVATAR-RUNTIME-ABSENT", "REJ-AVATAR-STT-INDISPONIBLE"} <= _codes(verdict)
    absente = _evaluer(session, identites, "audiovisuel")
    assert "REJ-AVATAR-ENTREE-ABSENTE" in _codes(absente)  # le visage n'est pas inscrit
    with session() as cnx:
        assert politique.etat_canal(cnx, identites, "voix", canaux_realises=aide.TOUS_LES_CANAUX)["etat"] == "prevu"


def test_sans_aucun_test_execute_aucun_canal(session):
    scenario = aide.monter(session, qualifier_tout=False)
    verdict = _evaluer(session, scenario.identite, "audiovisuel")
    assert _codes(verdict) == {"REJ-AVATAR-QUALIFICATION-ABSENTE"}
    assert {r.composant for r in verdict.refus} == {"voix", "visage", "stt"}
    with session() as cnx:
        assert politique.etat_canal(cnx, scenario.identite, "voix", canaux_realises=aide.TOUS_LES_CANAUX)[
            "etat"] == "configure"
        entree = registre.lire_entree(cnx, scenario.voix)
    assert entree["etat"] == "configure"


def test_un_double_de_test_ne_qualifie_jamais(session):
    scenario = aide.monter(session, qualifier_tout=False)
    aide.fournisseur(session, "tts.fictif-https", "tts", mode="api", point_acces="https://tts.example.test/v1",
                     residence_donnees="QC")
    with session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, fournisseur_id="tts.fictif-https")
    double = lambda _f, _s, _d: ResultatSonde("succes", "double qui répond toujours oui", 1)  # noqa: E731
    resultat = registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id="tts.fictif-https", sonde=double)
    assert resultat["statut"] == "succes" and resultat["nature"] == "double" and resultat["qualifiante"] is False
    with session() as cnx:
        assert registre.lire_entree(cnx, scenario.voix)["etat"] == "configure"
    for ident in (aide.AVATAR, aide.STT):
        registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id=ident)
    verdict = _evaluer(session, scenario.identite, "voix")
    assert _codes(verdict) == {"REJ-AVATAR-QUALIFICATION-SIMULEE"}
    with session() as cnx:
        derniere = registre.qualifications_de(cnx, "tts.fictif-https")[0]
        assert derniere["nature"] == "double" and not registre.est_qualifiante(derniere)


def test_une_sonde_reelle_reussie_qualifie_et_un_echec_ramene_a_configure(session):
    scenario = aide.monter(session, qualifier_tout=False)
    ok = registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id=aide.TTS)
    assert ok == {**ok, "nature": "reel", "statut": "succes", "qualifiante": True, "entrees": [scenario.voix]}
    with session() as cnx:
        assert registre.lire_entree(cnx, scenario.voix)["etat"] == "qualifie"
    aide.fournisseur(session, "tts.fictif-casse", "tts", point_acces="module:module_absent_de_ce_serveur")
    with session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, fournisseur_id="tts.fictif-casse")
    casse = registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id="tts.fictif-casse")
    assert casse["statut"] == "echec" and casse["nature"] == "reel" and not casse["qualifiante"]
    with session() as cnx:
        assert registre.lire_entree(cnx, scenario.voix)["etat"] == "configure"
    for ident in (aide.AVATAR, aide.STT):
        registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id=ident)
    assert "REJ-AVATAR-QUALIFICATION-ECHEC" in _codes(_evaluer(session, scenario.identite, "voix"))


def test_la_qualification_est_journalisee_horodatee_et_liee_a_l_empreinte_du_moteur(session, scenario):
    with session() as cnx:
        lignes = registre.qualifications_de(cnx, aide.TTS)
        fournisseur = registre.fournisseur_de(cnx, aide.TTS)
    assert len(lignes) == 1
    assert lignes[0]["empreinte_runtime"] == modele.empreinte_runtime(fournisseur)
    assert lignes[0]["acteur"] == aide.ADMIN and dt.datetime.fromisoformat(lignes[0]["quand"]).tzinfo is not None
    registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id=aide.TTS)
    with session() as cnx:
        assert len(registre.qualifications_de(cnx, aide.TTS)) == 2  # chaque exécution laisse sa trace


def test_un_moteur_modifie_apres_qualification_rend_le_manifeste_perime(session, scenario):
    with session() as cnx:
        fournisseurs.configurer(cnx, acteur=aide.ADMIN, identifiant=aide.TTS, modifications={
            "point_acces": "module:os"}, revision_attendue=fournisseurs.vue(cnx, aide.TTS)["revision"])
    verdict = _evaluer(session, scenario.identite, "voix")
    assert _codes(verdict) == {"REJ-AVATAR-MANIFESTE-MODIFIE"}
    with session() as cnx:
        vue = lecture.vue_entree(cnx, registre.lire_entree(cnx, scenario.voix), maintenant=MAINTENANT)
    assert vue["manifeste_modifie"] is True and vue["etat_effectif"] == "configure" and vue["etat"] == "qualifie"
    with session() as cnx:  # re-lier puis re-qualifier rétablit
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, fournisseur_id=aide.TTS)
    assert "REJ-AVATAR-QUALIFICATION-ABSENTE" in _codes(_evaluer(session, scenario.identite, "voix"))
    registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id=aide.TTS)
    assert _evaluer(session, scenario.identite, "voix").conforme


def test_un_moteur_desactive_refuse_le_canal(session, scenario):
    with session() as cnx:
        fournisseurs.desactiver(cnx, acteur=aide.ADMIN, identifiant=aide.TTS)
    assert "REJ-AVATAR-RUNTIME-INACTIF" in _codes(_evaluer(session, scenario.identite, "voix"))


def test_la_capacite_du_moteur_doit_correspondre_au_genre(session, scenario):
    aide.fournisseur(session, "stt.fictif-bis", "stt")
    for identifiant, fournisseur in ((scenario.voix, "stt.fictif-bis"), (scenario.visage, aide.TTS)):
        with pytest.raises(AvatarRefus) as exc, session() as cnx:
            registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=identifiant, fournisseur_id=fournisseur)
        assert exc.value.code == "REJ-AVATAR-RUNTIME-CAPACITE"


def test_lier_un_runtime_inconnu_ou_non_configure_est_refuse(session, scenario):
    for fournisseur in ("tts.inconnu-total", aide.TTS + "x", "tts.chatterbox-multilingual.local", None, 7):
        with pytest.raises(AvatarRefus) as exc, session() as cnx:
            registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, fournisseur_id=fournisseur)
        assert exc.value.code == "REJ-AVATAR-RUNTIME-INCONNU"  # le catalogue seul ne suffit pas : configurer d'abord
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant="voix.lea.absente", fournisseur_id=aide.TTS)
    assert exc.value.code == "REJ-AVATAR-ENTREE-INCONNUE"
    with pytest.raises(AvatarRefus) as exc:
        registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id="tts.inconnu-total")
    assert exc.value.code == "REJ-AVATAR-RUNTIME-INCONNU"


def test_moteurs_du_catalogue_sans_point_d_acces_ou_sur_appareil_ne_sont_pas_qualifiables(session, scenario):
    # Chatterbox (adopté) n'a pas de point d'accès tant qu'on n'en configure pas ; TalkingHead rend sur l'appareil.
    with session() as cnx:
        for identifiant in ("tts.chatterbox-multilingual.local", "avatar.talkinghead"):
            fournisseurs.configurer(cnx, acteur=aide.ADMIN, identifiant=identifiant, modifications={},
                                    revision_attendue=0)
            assert fournisseurs.activer(cnx, acteur=aide.ADMIN, identifiant=identifiant).conforme
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.voix,
                              fournisseur_id="tts.chatterbox-multilingual.local")
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.visage, fournisseur_id="avatar.talkinghead")
    sans_point = registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id="tts.chatterbox-multilingual.local")
    assert sans_point["statut"] == "echec" and "point d'accès" in sans_point["detail"]
    appareil = registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id="avatar.talkinghead")
    assert appareil["statut"] == "non_verifiable" and not appareil["qualifiante"]
    verdict = _evaluer(session, scenario.identite, "audiovisuel")
    assert _codes(verdict) == {"REJ-AVATAR-QUALIFICATION-ECHEC"}
    with session() as cnx:
        assert registre.lire_entree(cnx, scenario.visage)["etat"] == "configure"


def test_stt_requis_pour_la_voix_selectionne_actif_conforme_et_qualifie(session, scenario):
    with session() as cnx:
        fournisseurs.retirer_selection(cnx, acteur=aide.ADMIN, capacite="stt", departement=aide.DEPARTEMENT)
    assert _codes(_evaluer(session, scenario.identite, "voix")) == {"REJ-AVATAR-STT-INDISPONIBLE"}
    aide.fournisseur(session, "stt.fictif-neuf", "stt")
    with session() as cnx:
        fournisseurs.selectionner(cnx, acteur=aide.ADMIN, capacite="stt", identifiant="stt.fictif-neuf",
                                  departement=aide.DEPARTEMENT)
    verdict = _evaluer(session, scenario.identite, "voix")
    assert _codes(verdict) == {"REJ-AVATAR-QUALIFICATION-ABSENTE"} and verdict.refus[0].composant == "stt"
    registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id="stt.fictif-neuf")
    assert _evaluer(session, scenario.identite, "voix").conforme


# --- (c) licence conforme au client : le moteur du registre de fournisseurs ------------------------------------
@pytest.mark.parametrize("licence,profil_apres,sous_code", [
    ({"usage_commercial": "sous_seuil", "seuil_revenu_usd": 300_000}, {"revenu_annuel_usd": 400_000},
     "SEUIL_REVENU_DEPASSE"),
    ({"usage_commercial": "sous_seuil", "seuil_revenu_usd": 300_000}, {"revenu_annuel_usd": None},
     "REVENU_CLIENT_INCONNU"),
    ({"territoires_exclus": ["CN"]}, {"territoires": ["CA", "CN"]}, "TERRITOIRE_EXCLU"),
    ({"service_tiers": "interdit"}, {"heberge_pour_tiers": True}, "SERVICE_TIERS_INTERDIT"),
    ({"service_tiers": "incertain"}, {"heberge_pour_tiers": True}, "SERVICE_TIERS_INCERTAIN"),
    ({}, {"usage_commercial": True}, None),
])
def test_licence_non_conforme_apres_changement_du_profil_du_client(session, licence, profil_apres, sous_code):
    scenario = aide.monter(session, tts_licence=licence, revenu=100_000)
    assert _evaluer(session, scenario.identite, "voix").conforme
    aide.changer_profil(session, **profil_apres)
    verdict = _evaluer(session, scenario.identite, "voix")
    if sous_code is None:
        assert verdict.conforme
        return
    assert _codes(verdict) == {"REJ-AVATAR-LICENCE-NON-CONFORME"}
    assert sous_code in verdict.refus[0].sous_codes and verdict.refus[0].composant == "voix"


@pytest.mark.parametrize("ecarte", ["tts.xtts-v2", "tts.f5-tts", "tts.voxtral-tts.local", "tts.fish-speech"])
def test_les_moteurs_de_voix_ecartes_par_la_feuille_de_route_ne_se_lient_pas(session, scenario, ecarte):
    with session() as cnx:
        fournisseurs.configurer(cnx, acteur=aide.ADMIN, identifiant=ecarte, modifications={}, revision_attendue=0)
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, fournisseur_id=ecarte)
    assert exc.value.code == "REJ-AVATAR-LICENCE-NON-CONFORME"
    assert "écarté" in exc.value.detail


@pytest.mark.parametrize("ecarte", ["avatar.wav2lip", "avatar.insightface", "avatar.sadtalker", "avatar.duix"])
def test_les_moteurs_de_visage_ecartes_ne_se_lient_pas(session, scenario, ecarte):
    with session() as cnx:
        fournisseurs.configurer(cnx, acteur=aide.ADMIN, identifiant=ecarte, modifications={}, revision_attendue=0)
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.visage, fournisseur_id=ecarte)
    assert exc.value.code == "REJ-AVATAR-LICENCE-NON-CONFORME"


def test_moteur_non_commercial_non_ecarte_lie_mais_inactif_et_non_conforme(session, scenario):
    with session() as cnx:
        fournisseurs.configurer(cnx, acteur=aide.ADMIN, identifiant="tts.fictif-nc", revision_attendue=0,
                                declaration=aide.declaration("tts", licence={"usage_commercial": "interdit",
                                                                              "poids": "CC-BY-NC-4.0"}))
        assert fournisseurs.activer(cnx, acteur=aide.ADMIN, identifiant="tts.fictif-nc").conforme is False
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, fournisseur_id="tts.fictif-nc")
    verdict = _evaluer(session, scenario.identite, "voix")
    assert {"REJ-AVATAR-RUNTIME-INACTIF", "REJ-AVATAR-LICENCE-NON-CONFORME",
            "REJ-AVATAR-QUALIFICATION-ABSENTE"} <= _codes(verdict)
    sous = [r for r in verdict.refus if r.code == "REJ-AVATAR-LICENCE-NON-CONFORME"][0].sous_codes
    assert "LICENCE_NON_COMMERCIALE" in sous
    # le test de connexion lui-même refuse d'appeler un moteur non conforme (politique d'abord)
    refuse = registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id="tts.fictif-nc")
    assert refuse["statut"] == "refuse_politique" and not refuse["qualifiante"]


def test_licence_a_lire_non_lue_et_mention_obligatoire_bloquent(session, scenario):
    with session() as cnx:
        fournisseurs.configurer(cnx, acteur=aide.ADMIN, identifiant="tts.fictif-a-lire", revision_attendue=0,
                                declaration=aide.declaration("tts", licence={"verification": "a_lire"}))
        assert not fournisseurs.activer(cnx, acteur=aide.ADMIN, identifiant="tts.fictif-a-lire").conforme
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, fournisseur_id="tts.fictif-a-lire")
    sous = [r for r in _evaluer(session, scenario.identite, "voix").refus
            if r.code == "REJ-AVATAR-LICENCE-NON-CONFORME"][0].sous_codes
    assert "LICENCE_A_VERIFIER" in sous


def test_plusieurs_refus_sont_rendus_ensemble_dans_un_ordre_stable(session):
    scenario = aide.monter(session, qualifier_tout=False)
    with session() as cnx:
        fournisseurs.desactiver(cnx, acteur=aide.ADMIN, identifiant=aide.AVATAR)
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant=scenario.visage, actif_usage_commercial="interdit",
                                revision_attendue=2)
    verdict = _evaluer(session, scenario.identite, "audiovisuel", canaux_realises=frozenset())
    ordre = list(codes.CODES_AVATAR)
    assert list(verdict.codes) == sorted(verdict.codes, key=ordre.index)
    assert {"REJ-AVATAR-CANAL-NON-REALISE", "REJ-AVATAR-RUNTIME-INACTIF", "REJ-AVATAR-QUALIFICATION-ABSENTE",
            "REJ-AVATAR-ACTIF-NON-COMMERCIAL"} <= _codes(verdict)
    with pytest.raises(AvatarRefus) as exc:
        verdict.exiger()
    assert exc.value.codes == verdict.codes


# --- (b) consentement : aucune voix clonée sans consentement écrit --------------------------------------------
def test_aucune_voix_clonee_sans_consentement_ecrit_enregistre(session, scenario):
    voix = _clone(session, scenario)
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=voix, fournisseur_id=aide.TTS)
    assert exc.value.code == "REJ-AVATAR-CONSENTEMENT-ABSENT"
    with session() as cnx:
        assert registre.lire_entree(cnx, voix)["fournisseur_id"] is None  # rien n'a été lié
    sc = dataclasses.replace(scenario.identite, voix=voix)
    assert "REJ-AVATAR-CONSENTEMENT-ABSENT" in _codes(_evaluer(session, sc))


def test_consentement_partiel_revoque_et_expire(session, scenario):
    voix = _clone(session, scenario)
    sc = dataclasses.replace(scenario.identite, voix=voix)
    partiel = _consentement(session, voix, portee=["clonage"])
    with pytest.raises(AvatarRefus) as exc, session() as cnx:  # la portée ne couvre pas la synthèse
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=voix, fournisseur_id=aide.TTS)
    assert exc.value.code == "REJ-AVATAR-CONSENTEMENT-PORTEE"
    complement = _consentement(session, voix, portee=["synthese"], document_ref="avenant-fictif.pdf",
                               expire_le="2026-11-10")
    with session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=voix, fournisseur_id=aide.TTS)
    registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id=aide.TTS)
    assert _evaluer(session, sc).conforme
    # expiration : l'avenant (synthèse) expire le 10 novembre
    expire = _evaluer(session, sc, maintenant=MAINTENANT + dt.timedelta(days=12))
    assert _codes(expire) == {"REJ-AVATAR-CONSENTEMENT-PORTEE"}
    with session() as cnx:
        registre.revoquer_consentement(cnx, acteur=aide.ADMIN, consentement_id=partiel["consentement_id"],
                                       motif="retrait du locuteur", maintenant=MAINTENANT)
    assert _codes(_evaluer(session, sc)) == {"REJ-AVATAR-CONSENTEMENT-PORTEE"}
    with session() as cnx:
        registre.revoquer_consentement(cnx, acteur=aide.ADMIN, consentement_id=complement["consentement_id"],
                                       motif="retrait du locuteur", maintenant=MAINTENANT)
    assert _codes(_evaluer(session, sc)) == {"REJ-AVATAR-CONSENTEMENT-REVOQUE"}


def test_consentement_expire_seul_donne_le_code_expire(session, scenario):
    voix = _clone(session, scenario)
    sc = dataclasses.replace(scenario.identite, voix=voix)
    _consentement(session, voix, expire_le="2026-11-05")
    with session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=voix, fournisseur_id=aide.TTS)
    registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id=aide.TTS)
    assert _evaluer(session, sc, maintenant=MAINTENANT).conforme
    dernier_jour = dt.datetime(2026, 11, 5, 23, 0, tzinfo=dt.UTC)
    assert _evaluer(session, sc, maintenant=dernier_jour).conforme  # valable jusqu'à la fin du jour d'expiration
    assert _codes(_evaluer(session, sc, maintenant=dt.datetime(2026, 11, 6, 1, 0, tzinfo=dt.UTC))) == {
        "REJ-AVATAR-CONSENTEMENT-EXPIRE"}


def test_la_revocation_suspend_un_canal_deja_declare_disponible(session, scenario):
    voix = _clone(session, scenario)
    sc = dataclasses.replace(scenario.identite, voix=voix)
    consentement = _consentement(session, voix)
    with session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant=voix, fournisseur_id=aide.TTS)
    registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id=aide.TTS)
    with session() as cnx:
        assert politique.declarer_canal(cnx, acteur=aide.ADMIN, identite=sc, canal="voix",
                                        canaux_realises=aide.TOUS_LES_CANAUX, maintenant=MAINTENANT).conforme
        assert politique.etat_canal(cnx, sc, "voix", canaux_realises=aide.TOUS_LES_CANAUX,
                                    maintenant=MAINTENANT)["etat"] == "disponible"
        registre.revoquer_consentement(cnx, acteur=aide.ADMIN, consentement_id=consentement["consentement_id"],
                                       motif="retrait du locuteur", maintenant=MAINTENANT)
        suspendu = politique.etat_canal(cnx, sc, "voix", canaux_realises=aide.TOUS_LES_CANAUX, maintenant=MAINTENANT)
    assert suspendu["etat"] == "suspendu" and suspendu["codes"] == ["REJ-AVATAR-CONSENTEMENT-REVOQUE"]


@pytest.mark.parametrize("options,code", [
    ({"forme": "verbal"}, "REJ-AVATAR-CONSENTEMENT-NON-ECRIT"),
    ({"forme": None}, "REJ-AVATAR-CONSENTEMENT-NON-ECRIT"),
    ({"locuteur_ref": "Jean Tremblay"}, "REJ-AVATAR-DECLARATION-INVALIDE"),
    ({"locuteur_ref": "x"}, "REJ-AVATAR-DECLARATION-INVALIDE"),
    ({"document_sha256": "abc"}, "REJ-AVATAR-DECLARATION-INVALIDE"),
    ({"document_sha256": "Z" * 64}, "REJ-AVATAR-DECLARATION-INVALIDE"),
    ({"document_ref": ""}, "REJ-AVATAR-DECLARATION-INVALIDE"),
    ({"signe_le": "2026-11-02"}, "REJ-AVATAR-DECLARATION-INVALIDE"),  # signé dans le futur
    ({"signe_le": "01/10/2026"}, "REJ-AVATAR-DECLARATION-INVALIDE"),
    ({"expire_le": "2026-10-01"}, "REJ-AVATAR-DECLARATION-INVALIDE"),  # n'expire pas après la signature
    ({"expire_le": "2026-10-15"}, "REJ-AVATAR-DECLARATION-INVALIDE"),  # déjà passé
    ({"portee": []}, "REJ-AVATAR-DECLARATION-INVALIDE"),
    ({"portee": "synthese"}, "REJ-AVATAR-DECLARATION-INVALIDE"),
    ({"portee": ["rendu_visage"]}, "REJ-AVATAR-DECLARATION-INVALIDE"),  # portée d'un visage pour une voix
    ({"portee": ["diffusion"]}, "REJ-AVATAR-DECLARATION-INVALIDE"),
])
def test_consentements_invalides_refuses_sans_rien_ecrire(session, scenario, options, code):
    voix = _clone(session, scenario)
    with pytest.raises(AvatarRefus) as exc:
        _consentement(session, voix, **options)
    assert exc.value.code == code
    with session() as cnx:
        assert registre.consentements_de(cnx, voix) == []


def test_pas_de_consentement_pour_une_voix_generique_ni_pour_une_entree_inconnue(session, scenario):
    with pytest.raises(AvatarRefus) as exc:
        _consentement(session, scenario.voix)
    assert exc.value.code == "REJ-AVATAR-DECLARATION-INVALIDE"
    with pytest.raises(AvatarRefus) as exc:
        _consentement(session, "voix.lea.inconnue")
    assert exc.value.code == "REJ-AVATAR-ENTREE-INCONNUE"


@pytest.mark.parametrize("ident", ["", "z" * 32, "a" * 31, "A" * 32, None, 5, "a" * 32])
def test_revoquer_un_consentement_inconnu_ou_mal_forme(session, scenario, ident):
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.revoquer_consentement(cnx, acteur=aide.ADMIN, consentement_id=ident, motif="m")
    assert exc.value.code == "REJ-AVATAR-CONSENTEMENT-INCONNU"


@pytest.mark.parametrize("motif", ["", "  ", None, "x" * 201, "ligne\nbrisée"])
def test_motif_de_revocation_requis(session, scenario, motif):
    voix = _clone(session, scenario)
    ident = _consentement(session, voix)["consentement_id"]
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.revoquer_consentement(cnx, acteur=aide.ADMIN, consentement_id=ident, motif=motif)
    assert exc.value.code == "REJ-AVATAR-DECLARATION-INVALIDE"


def test_ressemblance_d_un_visage_exige_aussi_un_consentement(session, scenario):
    with session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant="visage.lea.reel", origine="ressemblance",
                                 actif_usage_commercial="autorise")
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant="visage.lea.reel", fournisseur_id=aide.AVATAR)
    assert exc.value.code == "REJ-AVATAR-CONSENTEMENT-ABSENT"
    with pytest.raises(AvatarRefus):  # la portée d'une voix ne couvre pas un visage
        _consentement(session, "visage.lea.reel", portee=["synthese"])
    _consentement(session, "visage.lea.reel", portee=["rendu_visage"])
    with session() as cnx:
        registre.lier_runtime(cnx, acteur=aide.ADMIN, identifiant="visage.lea.reel", fournisseur_id=aide.AVATAR)


# --- (d) biométrie (Loi 25) ----------------------------------------------------------------------------------
def test_empreinte_vocale_de_tiers_sans_declaration_est_refusee_par_defaut(session, scenario):
    with session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, accent="quebecois",
                                 empreinte_vocale_tiers=True, revision_attendue=2)
    verdict = _evaluer(session, scenario.identite, "voix")
    assert _codes(verdict) == {"REJ-AVATAR-BIOMETRIE-NON-DECLAREE"}
    with session() as cnx:
        refuse = politique.declarer_canal(cnx, acteur=aide.ADMIN, identite=scenario.identite, canal="voix",
                                          canaux_realises=aide.TOUS_LES_CANAUX, maintenant=MAINTENANT)
        assert refuse.codes == ("REJ-AVATAR-BIOMETRIE-NON-DECLAREE",)
        assert cnx.execute(select(AVATARS_CANAUX)).first() is None


def test_declaration_biometrique_exige_le_delai_de_60_jours_avant_la_mise_en_service(session, scenario):
    with session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, accent="quebecois",
                                 empreinte_vocale_tiers=True, revision_attendue=2)
        registre.declarer_biometrie(cnx, acteur=aide.ADMIN, identifiant=scenario.voix,
                                    reference="CAI-DEPOT-FICTIF-2026-001", declaree_le="2026-10-25",
                                    maintenant=MAINTENANT)
    assert _codes(_evaluer(session, scenario.identite, "voix")) == {"REJ-AVATAR-BIOMETRIE-DELAI"}
    # 2026-10-25 + 60 jours = 2026-12-24
    assert _codes(_evaluer(session, scenario.identite, "voix",
                           maintenant=dt.datetime(2026, 12, 23, 12, tzinfo=dt.UTC))) == {"REJ-AVATAR-BIOMETRIE-DELAI"}
    pret = dt.datetime(2026, 12, 24, 12, tzinfo=dt.UTC)
    assert _evaluer(session, scenario.identite, "voix", maintenant=pret).conforme


@pytest.mark.parametrize("options", [
    {"declaree_le": "2026-11-02"}, {"declaree_le": "demain"}, {"reference": ""}, {"reference": "x" * 201},
])
def test_declaration_biometrique_invalide(session, scenario, options):
    valeurs = {"reference": "CAI-FICTIF", "declaree_le": "2026-10-25", **options}
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.declarer_biometrie(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, maintenant=MAINTENANT,
                                    **valeurs)
    assert exc.value.code == "REJ-AVATAR-DECLARATION-INVALIDE"
    with pytest.raises(AvatarRefus) as exc, session() as cnx:  # un visage n'a pas d'empreinte vocale
        registre.declarer_biometrie(cnx, acteur=aide.ADMIN, identifiant=scenario.visage, reference="CAI-FICTIF",
                                    declaree_le="2026-10-25", maintenant=MAINTENANT)
    assert exc.value.code == "REJ-AVATAR-DECLARATION-INVALIDE"


# --- langue et actif visuel ---------------------------------------------------------------------------------
def test_langue_de_la_voix_doit_etre_fr_ca_et_l_actif_du_visage_commercial(session, scenario):
    with session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant=scenario.voix, langue="fr-FR", accent="parisien",
                                 revision_attendue=2)
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant=scenario.visage,
                                 actif_usage_commercial="interdit", revision_attendue=2)
    assert _codes(_evaluer(session, scenario.identite, "voix")) == {"REJ-AVATAR-LANGUE"}
    assert _codes(_evaluer(session, scenario.identite, "audiovisuel")) == {
        "REJ-AVATAR-LANGUE", "REJ-AVATAR-ACTIF-NON-COMMERCIAL"}


# --- le désaccord entre les états -----------------------------------------------------------------------------
def test_un_canal_declare_ne_prouve_rien_a_lui_seul(session, scenario):
    with session() as cnx:
        assert politique.declarer_canal(cnx, acteur=aide.ADMIN, identite=scenario.identite, canal="voix",
                                        canaux_realises=aide.TOUS_LES_CANAUX, maintenant=MAINTENANT).conforme
        # Falsification directe de la base : le moteur est désactivé après la déclaration.
        fournisseurs.desactiver(cnx, acteur=aide.ADMIN, identifiant=aide.TTS)
        etat_ = politique.etat_canal(cnx, scenario.identite, "voix", canaux_realises=aide.TOUS_LES_CANAUX,
                                     maintenant=MAINTENANT)
    assert etat_["etat"] == "suspendu" and "REJ-AVATAR-RUNTIME-INACTIF" in etat_["codes"]


def test_etat_effectif_du_canal_suit_le_plus_faible_des_composants(session):
    scenario = aide.monter(session, qualifier_tout=False)
    registre.qualifier(session, acteur=aide.ADMIN, fournisseur_id=aide.TTS)
    with session() as cnx:
        e_voix = politique.etat_canal(cnx, scenario.identite, "voix", canaux_realises=aide.TOUS_LES_CANAUX)
        e_av = politique.etat_canal(cnx, scenario.identite, "audiovisuel", canaux_realises=aide.TOUS_LES_CANAUX)
    assert e_voix["etat"] == "qualifie" and e_av["etat"] == "configure"  # le visage n'est pas qualifié


def test_lecture_admin_des_dix_avatars_sans_registre_tout_est_prevu(session):
    from opsys import avatars
    from opsys.departements import charger_departements

    identites = avatars.resoudre_identites(charger_departements())
    with session() as cnx:
        vue = lecture.etat_avatars(cnx, identites, maintenant=MAINTENANT)
    assert [a["nom"] for a in vue["avatars"]] == ["Léa", "Victor", "Mathis", "Gabriel", "Sophie", "Rosalie", "Chloé",
                                                  "Olivier", "Athéna", "Mnémo"]
    for avatar in vue["avatars"]:
        assert avatar["canaux"]["messagerie"]["etat"] == "disponible"
        assert avatar["canaux"]["voix"]["etat"] == "prevu" and avatar["canaux"]["audiovisuel"]["etat"] == "prevu"
        assert "REJ-AVATAR-CANAL-NON-REALISE" in avatar["canaux"]["voix"]["codes"]
    assert vue["registre"] == [] and vue["resume"] == {"prevu": 20}
    assert "pas prouvée de bout en bout" in vue["avertissement"]


def test_la_lecture_ne_montre_ni_locuteur_ni_secret(session, scenario):
    from opsys import avatars
    from opsys.departements import charger_departements

    voix = _clone(session, scenario)
    _consentement(session, voix, locuteur_ref="comedien-secret-42")
    with session() as cnx:
        vue = lecture.etat_avatars(cnx, avatars.resoudre_identites(charger_departements()), maintenant=MAINTENANT)
    texte = json.dumps(vue, ensure_ascii=False)
    assert "comedien-secret-42" not in texte and "locuteur_ref" not in texte
    entree = [r for r in vue["registre"] if r["identifiant"] == voix][0]
    assert entree["consentements"]["total"] == 1 and entree["consentements"]["documents"] == ["contrat-fictif-001.pdf"]


def test_la_lecture_marque_les_voix_partagees_entre_departements(session, scenario):
    from opsys import avatars
    from opsys.departements import charger_departements

    deps = charger_departements()
    surcharge = {"m02-revenue-crm": avatars.Surcharge(voix=scenario.voix)}
    identites = avatars.resoudre_identites(deps, surcharge)
    with session() as cnx:
        vue = lecture.etat_avatars(cnx, identites, maintenant=MAINTENANT)
    par_dep = {a["departement"]: a for a in vue["avatars"]}
    assert par_dep["m01-front-office"]["partage"] == {scenario.voix: ["m02-revenue-crm"]}
    assert par_dep["m02-revenue-crm"]["partage"] == {scenario.voix: ["m01-front-office"]}


def test_aucune_ecriture_dans_les_tables_de_fournisseurs_par_la_lecture(session, scenario):
    from opsys import avatars
    from opsys.departements import charger_departements

    def compte():
        with session() as cnx:
            return cnx.execute(text("SELECT (SELECT count(*) FROM journal), (SELECT count(*) FROM avatars_canaux), "
                                    "(SELECT count(*) FROM avatars_qualifications)")).one()

    avant = compte()
    with session() as cnx:
        lecture.etat_avatars(cnx, avatars.resoudre_identites(charger_departements()), maintenant=MAINTENANT)
        politique.evaluer_canal(cnx, scenario.identite, "voix", canaux_realises=aide.TOUS_LES_CANAUX)
    assert compte() == avant


def test_horodatage_sans_fuseau_refuse(session, scenario):
    with pytest.raises(AvatarRefus) as exc, session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant="voix.lea.autre",
                                 maintenant=dt.datetime(2026, 11, 1, 12, 0))
    assert exc.value.code == "REJ-AVATAR-DECLARATION-INVALIDE"

