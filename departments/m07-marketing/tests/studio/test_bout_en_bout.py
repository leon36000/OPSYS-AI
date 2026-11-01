"""Le studio de bout en bout avec les VRAIS outils, la VRAIE file d'approbation, la VRAIE base, le registre de
fournisseurs
existant, le sas social et le site : ce qui n'est pas composé, contrôlé et approuvé par une personne ne sort pas.

Rien n'est généré par un vrai modèle (double déterministe), rien n'est lu par un vrai OCR (doubles), rien n'est publié.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import fabriques_studio as f
import pytest
from m7_marketing import outils, publication_outils, studio_outils
from m7_marketing.brand import registre as registre_marque
from m7_marketing.sas_social import doubles, etats, executeur, politique
from m7_marketing.site import service as site_service
from m7_marketing.studio import actifs, generation, modeles, service

from opsys import approbations, stockage
from opsys.departements import lire_manifeste
from opsys.fournisseurs import registre
from opsys.outils import Niveau, executer_atomique

_M7 = Path(__file__).resolve().parents[2]
_OUTILS = {o.nom: o for o in outils.outils()}
_DEPARTEMENTS = {"m07-marketing": lire_manifeste(_M7)}
HORODATAGE = "2026-01-05T15:00:00+00:00"
ID = "image.double-deterministe.test"
ATTESTATIONS = {
    "elements_critiques_verifies": True,
    "aucun_visage_ni_plaque_identifiable": True,
    "rendu_relu_a_l_ecran": True,
    "realiste": True,
}
COMPTE = "page-horizon-fictive"
DEMO = "revetements-horizon-fictif"
PROFIL_MARQUE = {
    "name": "Revêtements Horizon Fictif",
    "tagline": "Des toitures qui durent",
    "tone": "chaleureux",
    "colors": ["#0B3C5D", "#F2C14E", "#FFFFFF"],
    "langue": "fr",
}


def _demande(nom, arguments, niveau=Niveau.N3):
    with stockage.transaction() as cnx:
        return approbations.creer_demande(cnx, "m07-marketing", nom, arguments, niveau=niveau)


def _decider(demande, approuver=True, qui="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, demande, approuver, qui, _OUTILS, _DEPARTEMENTS)


def _approuve(nom, arguments, niveau=Niveau.N3):
    sortie = _decider(_demande(nom, arguments, niveau))
    assert sortie["statut"] == "executee", sortie
    return sortie["reponse"]["resultat"]


def _agent(nom, arguments):
    return executer_atomique(_OUTILS[nom], arguments)["resultat"]


def _codes(resultat):
    return [r["code"] for r in resultat.get("refus", [])]


@pytest.fixture
def monde(base):
    """Instance migrée + polices épinglées + marque + fournisseur d'image conforme sélectionné + comptes sociaux."""
    f.ecrire_polices(base / "studio" / "polices")
    registre_marque.enregistrer(PROFIL_MARQUE, "nathan", HORODATAGE)
    with stockage.transaction() as cnx:
        registre.declarer_profil(
            cnx,
            acteur="gestion",
            usage_commercial=True,
            revenu_annuel_usd=1_500_000,
            territoires=["CA"],
            heberge_pour_tiers=False,
            revision_attendue=0,
        )
        registre.configurer(cnx, acteur="gestion", identifiant=ID, declaration=modeles.declaration_pour_double())
        assert registre.activer(cnx, acteur="gestion", identifiant=ID).conforme
        registre.selectionner(cnx, acteur="gestion", capacite="image", identifiant=ID, departement="m07-marketing")
    for reseau in ("facebook", "gbp"):
        _approuve(
            "m7_enregistrer_compte_social",
            {
                "reseau": reseau,
                "compte": COMPTE,
                "fictif": True,
                "secret_ref": {"nom": "social.facebook.horizon"},
                "horodatage": HORODATAGE,
            },
        )
    return base


def _brief(**plus):
    donnees = f.brief(
        "banniere_social",
        elements_critiques=f.critiques("telephone", "courriel"),
        mentions_obligatoires=["Licence RBQ détenue par l'entreprise"],
        **plus,
    )
    del donnees["marque"]
    return donnees


def _preparer(cle="cle-brief-0123456789abcdef", **plus):
    resultat = _agent(
        "m7_preparer_brief_creatif", {"brief": _brief(**plus), "cle_idempotence": cle, "horodatage": HORODATAGE}
    )
    assert resultat["accepte"], resultat
    return resultat["brief_id"]


def _executer_generation(job_id):
    """L'exécuteur, hors outil : sélection refaite dans le registre, adaptateur double, fichier de fonds sous
    OPSYS_HOME."""
    fichiers = service.FichiersStudio(studio_outils._racine())
    with stockage.transaction() as cnx:
        return generation_executeur(job_id, cnx, fichiers)


def generation_executeur(job_id, cnx, fichiers):
    from m7_marketing.studio import executeur as exe

    return exe.executer(
        stockage.maillons(*exe.REGISTRE),
        stockage.maillons("m07-marketing", "provenance_studio"),
        stockage.maillons(*actifs.REGISTRE),
        job_id,
        adaptateurs={ID: generation.GenerateurImageDouble()},
        resoudre_modele=lambda genre: modeles.selectionner(cnx, genre),
        ecrire_fond=lambda sha, octets, fmt: fichiers.ecrire(f"fonds/{actifs.identifiant_fond(sha)}.{fmt}", octets),
        par="executeur",
        horodatage="2026-01-05T15:00:00Z",
        maintenant=datetime(2026, 1, 5, 15, tzinfo=UTC),
    )


def _visuel_controle(brief_id, fond_actif_id=None):
    compose = _agent(
        "m7_composer_visuel_studio",
        {"brief_id": brief_id, "horodatage": HORODATAGE, **({"fond_actif_id": fond_actif_id} if fond_actif_id else {})},
    )
    assert compose["accepte"], compose
    controle = _agent("m7_controler_visuel_studio", {"actif_id": compose["actif_id"], "horodatage": HORODATAGE})
    assert controle["accepte"] and controle["conforme"], controle
    return compose["actif_id"], controle


def _approuver_visuel(actif_id, attestations=ATTESTATIONS):
    assert _agent("m7_demander_revue_visuel_studio", {"actif_id": actif_id, "horodatage": HORODATAGE})["accepte"]
    detail = _agent("m7_lire_studio", {"actif_id": actif_id})["actif"]
    return _approuve(
        "m7_approuver_visuel_studio",
        {
            "actif_id": actif_id,
            "composition_empreinte": detail["composition_empreinte"],
            "rapport_empreinte": detail["rapport_empreinte"],
            "attestations": attestations,
            "horodatage": HORODATAGE,
        },
    )


def _publication(media, **plus):
    donnees = {
        "reseau": "facebook",
        "compte": COMPTE,
        "texte": "Une toiture bien entretenue protège la maison pendant de longues années.",
        "titre": None,
        "medias": [media],
        "planifie_le": "2026-01-06T15:00:00Z",
        "divulgation": {
            "texte_ia": True,
            "media_synthetique_realiste": bool(media["ia_generee"] and media["realiste"]),
            "contenu_commercial": False,
        },
        "type_publication": "organique",
        "budget": None,
        "options": {},
    }
    donnees.update(plus)
    return donnees


def _composer_publication(media, cle="cle-sociale-0123456789ab", **plus):
    return _agent(
        "m7_composer_publication_sociale",
        {"publication": _publication(media, **plus), "cle_idempotence": cle, "horodatage": HORODATAGE},
    )


def _soumettre(publication_id):
    return _agent("m7_soumettre_publication_sociale", {"publication_id": publication_id, "horodatage": HORODATAGE})


# ======================================================================================================================
# Le manifeste
# ======================================================================================================================
NIVEAUX = {
    "m7_preparer_brief_creatif": Niveau.N2,
    "m7_demander_fond_studio": Niveau.N2,
    "m7_composer_visuel_studio": Niveau.N2,
    "m7_controler_visuel_studio": Niveau.N2,
    "m7_demander_revue_visuel_studio": Niveau.N2,
    "m7_approuver_visuel_studio": Niveau.N3,
    "m7_retirer_visuel_studio": Niveau.N2,
    "m7_vectoriser_logo_studio": Niveau.N2,
    "m7_exporter_visuel_vers_site": Niveau.N2,
    "m7_lire_studio": Niveau.N0,
}


@pytest.mark.parametrize("nom", sorted(NIVEAUX))
def test_niveaux_portees_fermees_et_aucune_frontiere_humaine_executee(nom):
    outil = _OUTILS[nom]
    assert outil.niveau_effectif == NIVEAUX[nom]
    assert outil.roles_appareil == frozenset(), "aucun rôle d'appareil : fermé par défaut"
    assert not outil.frontiere_humaine and outil.parametres["additionalProperties"] is False


def test_le_manifeste_charge_les_dix_outils_et_seul_le_proprietaire_decide_n3():
    import yaml

    departement = lire_manifeste(_M7)
    assert set(NIVEAUX) <= {o.nom for o in departement.charger_outils()}
    assert set(departement.roles_autorises(Niveau.N3)) == {"nathan_owner"}
    manifeste = yaml.safe_load((_M7 / "department.yaml").read_text(encoding="utf-8"))
    registres = {"briefs_studio", "jobs_studio", "provenance_studio", "actifs_studio"}
    assert registres <= set(manifeste["memoire"]["ecriture"])


def test_aucun_outil_du_studio_n_appelle_un_modele_un_reseau_ou_un_service_de_publication():
    import ast
    import inspect

    arbre = ast.parse(inspect.getsource(studio_outils))
    importes = {
        (n.module or "") + "." + a.name for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) for a in n.names
    }
    importes |= {a.name for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names}
    interdits = (
        "socket",
        "urllib",
        "http",
        "requests",
        "httpx",
        "adaptateurs",
        "doubles",
        "executeur",
        "sas_social",
        "secret_coffre",
        "secrets_coffre",
        "generation",
    )
    assert not [
        i
        for i in importes
        if any(mot in i.lower() for mot in interdits)
        and "studio.executeur" not in i
        and i != "m7_marketing.studio.executeur"
    ], importes
    texte = inspect.getsource(studio_outils)
    assert "ADAPTATEURS_DE_PRODUCTION" not in texte and ".generer(" not in texte


# ======================================================================================================================
# La chaîne complète, sans IA puis avec IA, jusqu'au sas social
# ======================================================================================================================
def test_chaine_sans_ia_jusqu_a_la_publication_sociale_planifiee_jamais_envoyee(monde):
    brief_id = _preparer()
    actif_id, controle = _visuel_controle(brief_id)
    assert controle["lecteurs"] and all(x["nature"] == "double" for x in controle["lecteurs"])
    assert (
        _agent(
            "m7_approuver_visuel_studio",
            {
                "actif_id": actif_id,
                "composition_empreinte": "0" * 64,
                "rapport_empreinte": "0" * 64,
                "attestations": ATTESTATIONS,
                "horodatage": HORODATAGE,
            },
        )["refus"][0]["code"]
        == "REJ-HUMAIN-REQUIS"
    )
    approuve = _approuver_visuel(actif_id, {**ATTESTATIONS, "realiste": False})
    assert (
        approuve["statut"] == "VISUEL_APPROUVE_NON_PUBLIE"
        and approuve["etat"] == "approuve"
        and approuve["execute"] is False
    )
    media = _agent("m7_lire_studio", {"actif_id": actif_id, "media_sas": True})["media_sas"]["media"]
    assert media["origine"] == "composition_deterministe" and media["ia_generee"] is False
    cree = _composer_publication(media)
    assert cree["accepte"], cree
    soumise = _soumettre(cree["publication_id"])
    assert soumise["accepte"] and soumise["niveau_requis"] == "N3", soumise
    arguments = {"publication_id": cree["publication_id"], "empreinte": cree["empreinte"], "horodatage": HORODATAGE}
    planifiee = _approuve("m7_demander_publication_sociale", arguments)
    assert planifiee["statut"] == "PUBLICATION_APPROUVEE_NON_EXECUTEE" and planifiee["execute"] is False
    journal = list(stockage.maillons(*publication_outils.REGISTRE_PUBLICATIONS_SOCIALES))
    assert etats.plier(journal)[cree["publication_id"]].etat == "planifie"


def test_chaine_avec_fond_genere_provenance_marquage_et_divulgation_jusqu_au_sas(monde):
    brief_id = _preparer(fond=f.GENERE)
    demande = _agent("m7_demander_fond_studio", {"brief_id": brief_id, "horodatage": HORODATAGE})
    assert demande["accepte"] and demande["statut"] == "EN_ATTENTE_EXECUTEUR" and demande["fournisseur"] == ID
    assert list(stockage.maillons("m07-marketing", "provenance_studio")) == []  # l'outil n'a rien généré
    resultat = _executer_generation(demande["job_id"])
    assert resultat["accepte"] and resultat["nature_generateur"] == "double"
    fond_id, chaine = resultat["fond_actif_id"], resultat["provenance_chaine"]
    provenance = list(stockage.maillons("m07-marketing", "provenance_studio"))
    assert (
        len(provenance) == 1 and provenance[0]["chaine"] == chaine and provenance[0]["modele"] == "double-deterministe"
    )
    assert provenance[0]["graine"] == demande["graine"] and provenance[0]["licence"]["decision"]["conforme"]
    assert "1500000" not in json.dumps(provenance)  # le revenu du client n'entre jamais à la provenance
    actif_id, _ = _visuel_controle(brief_id, fond_id)
    detail = _agent("m7_lire_studio", {"actif_id": actif_id})["actif"]
    assert detail["ia_generee"] is True and detail["donnees"]["provenance"] == chaine
    _approuver_visuel(actif_id, ATTESTATIONS)  # realiste: True
    media = _agent("m7_lire_studio", {"actif_id": actif_id, "media_sas": True})["media_sas"]["media"]
    assert media["ia_generee"] is True and media["realiste"] is True
    # Divulgation exigée : un média IA réaliste sans divulgation est refusé par le sas.
    sans = _composer_publication(
        media,
        cle="cle-sociale-sans-divulgation-01",
        divulgation={"texte_ia": True, "media_synthetique_realiste": False, "contenu_commercial": False},
    )
    refus = _soumettre(sans["publication_id"])["refus"]
    assert "REJ-SOCIAL-DIVULGATION-INCOHERENTE" in {r["code"] for r in refus}
    avec = _composer_publication(media)
    assert _soumettre(avec["publication_id"])["accepte"]


# ======================================================================================================================
# Ce que les VRAIS sas refusent
# ======================================================================================================================
def _media_depuis_registre_sans_approbation(actif_id):
    """Ce qu'un agent peut fabriquer à la main : un média décrivant fidèlement un visuel pas encore approuvé."""
    etat = actifs.plier(stockage.maillons(*actifs.REGISTRE))[actif_id]
    png = etat.donnees["artefacts"]["png"]
    return {
        "reference": f"{actif_id}-png",
        "type_media": "image",
        "format": "png",
        "sha256": png["sha256"],
        "octets": png["octets"],
        "largeur": png["largeur"],
        "hauteur": png["hauteur"],
        "duree_s": None,
        "alt": "Alt",
        "origine": "composition_deterministe",
        "ia_generee": False,
        "realiste": False,
        "moderation": "verifiee",
        "controle_ocr": "conforme",
    }


def test_le_sas_refuse_un_visuel_compose_controle_mais_non_approuve(monde):
    actif_id, _ = _visuel_controle(_preparer())
    media = _media_depuis_registre_sans_approbation(actif_id)
    refus = _soumettre(_composer_publication(media)["publication_id"])["refus"]
    assert [r["code"] for r in refus] == ["REJ-SOCIAL-MEDIA-ACTIF-NON-APPROUVE"] and "controle_conforme" in refus[0][
        "detail"
    ]


def test_le_sas_refuse_un_visuel_en_revue_mais_non_approuve(monde):
    actif_id, _ = _visuel_controle(_preparer())
    assert _agent("m7_demander_revue_visuel_studio", {"actif_id": actif_id, "horodatage": HORODATAGE})["accepte"]
    media = _media_depuis_registre_sans_approbation(actif_id)
    refus = _soumettre(_composer_publication(media)["publication_id"])["refus"]
    assert [r["code"] for r in refus] == ["REJ-SOCIAL-MEDIA-ACTIF-NON-APPROUVE"] and "en_revue" in refus[0]["detail"]


def test_le_sas_refuse_un_media_qui_se_dit_compose_et_controle_sans_etre_du_studio(monde):
    faux = {
        "reference": "faux-1",
        "type_media": "image",
        "format": "png",
        "sha256": "a" * 64,
        "octets": 5000,
        "largeur": 1080,
        "hauteur": 1350,
        "duree_s": None,
        "alt": "Alt",
        "origine": "composition_deterministe",
        "ia_generee": False,
        "realiste": False,
        "moderation": "verifiee",
        "controle_ocr": "conforme",
    }
    refus = _soumettre(_composer_publication(faux)["publication_id"])["refus"]
    assert [r["code"] for r in refus] == ["REJ-SOCIAL-MEDIA-ACTIF-INCONNU"]


def test_le_sas_refuse_un_fond_genere_brut_sous_n_importe_quelle_origine(monde):
    brief_id = _preparer(fond=f.GENERE)
    demande = _agent("m7_demander_fond_studio", {"brief_id": brief_id, "horodatage": HORODATAGE})
    fond_id = _executer_generation(demande["job_id"])["fond_actif_id"]
    fond = actifs.plier(stockage.maillons(*actifs.REGISTRE))[fond_id]
    base_media = {
        "reference": "fond-1",
        "type_media": "image",
        "format": "png",
        "sha256": fond.donnees["sha256"],
        "octets": 50_000,
        "largeur": fond.donnees["largeur"],
        "hauteur": fond.donnees["hauteur"],
        "duree_s": None,
        "alt": "Alt",
        "moderation": "verifiee",
        "controle_ocr": "non_requis",
    }
    for origine, ia, ocr_ in (
        ("composition_deterministe", True, "conforme"),
        ("photo_chantier", False, "non_requis"),
        ("banque_licenciee", False, "non_requis"),
        ("genere_non_compose", True, "non_requis"),
    ):
        media = {**base_media, "origine": origine, "ia_generee": ia, "realiste": ia, "controle_ocr": ocr_}
        cree = _composer_publication(
            media,
            cle=f"cle-sociale-fond-{origine[:6]}-012345",
            divulgation={"texte_ia": True, "media_synthetique_realiste": ia, "contenu_commercial": False},
        )
        refus = {r["code"] for r in _soumettre(cree["publication_id"])["refus"]}
        assert refus & {
            "REJ-SOCIAL-MEDIA-ACTIF-NON-APPROUVE",
            "REJ-SOCIAL-MEDIA-ACTIF-ORIGINE-INCOHERENTE",
            "REJ-SOCIAL-MEDIA-GENERE-NON-COMPOSE",
        }, (origine, refus)


def test_le_sas_refuse_un_visuel_approuve_dont_la_part_d_ia_ou_les_faits_sont_maquilles(monde):
    brief_id = _preparer(fond=f.GENERE)
    demande = _agent("m7_demander_fond_studio", {"brief_id": brief_id, "horodatage": HORODATAGE})
    fond_id = _executer_generation(demande["job_id"])["fond_actif_id"]
    actif_id, _ = _visuel_controle(brief_id, fond_id)
    _approuver_visuel(actif_id, ATTESTATIONS)
    vrai = _agent("m7_lire_studio", {"actif_id": actif_id, "media_sas": True})["media_sas"]["media"]
    cas = {
        "ia cachee": ({**vrai, "ia_generee": False, "realiste": False}, "REJ-SOCIAL-MEDIA-IA-INCOHERENTE"),
        "realiste cache": ({**vrai, "realiste": False}, "REJ-SOCIAL-MEDIA-IA-INCOHERENTE"),
        "autre octets": ({**vrai, "octets": vrai["octets"] + 1}, "REJ-SOCIAL-MEDIA-ACTIF-INCOHERENT"),
        "autre format": ({**vrai, "format": "jpeg"}, "REJ-SOCIAL-MEDIA-ACTIF-INCOHERENT"),
        "autre origine": (
            {**vrai, "origine": "photo_chantier", "ia_generee": False, "realiste": False},
            "REJ-SOCIAL-MEDIA-ACTIF-ORIGINE-INCOHERENTE",
        ),
    }
    for rang, (nom, (media, code)) in enumerate(cas.items()):
        cree = _composer_publication(
            media,
            cle=f"cle-sociale-maquille-{rang}-0123456789",
            divulgation={
                "texte_ia": True,
                "media_synthetique_realiste": media["ia_generee"] and media["realiste"],
                "contenu_commercial": False,
            },
        )
        refus = {r["code"] for r in _soumettre(cree["publication_id"])["refus"]}
        assert code in refus, (nom, refus)


def test_un_visuel_revoque_apres_la_soumission_n_est_plus_approuvable_ni_publiable(monde):
    actif_id, _ = _visuel_controle(_preparer())
    _approuver_visuel(actif_id, {**ATTESTATIONS, "realiste": False})
    media = _agent("m7_lire_studio", {"actif_id": actif_id, "media_sas": True})["media_sas"]["media"]
    cree = _composer_publication(media)
    assert _soumettre(cree["publication_id"])["accepte"]
    revoque = _agent(
        "m7_retirer_visuel_studio",
        {"actif_id": actif_id, "action": "revoquer", "motif": "licence changée", "horodatage": HORODATAGE},
    )
    assert revoque["etat"] == "revoque"
    sortie = _decider(
        _demande(
            "m7_demander_publication_sociale",
            {"publication_id": cree["publication_id"], "empreinte": cree["empreinte"], "horodatage": HORODATAGE},
        )
    )
    codes = [r["code"] for r in sortie["reponse"]["resultat"]["refus"]]
    assert codes == ["REJ-SOCIAL-MEDIA-ACTIF-NON-APPROUVE"]
    assert (
        etats.plier(list(stockage.maillons(*publication_outils.REGISTRE_PUBLICATIONS_SOCIALES)))[
            cree["publication_id"]
        ].etat
        == "en_attente_approbation"
    )


def _planifiee_avec_visuel_approuve():
    """Un visuel approuvé, une publication soumise, approuvée et planifiée ; rend (actif, publication)."""
    actif_id, _ = _visuel_controle(_preparer())
    _approuver_visuel(actif_id, {**ATTESTATIONS, "realiste": False})
    media = _agent("m7_lire_studio", {"actif_id": actif_id, "media_sas": True})["media_sas"]["media"]
    cree = _composer_publication(media)
    _soumettre(cree["publication_id"])
    _approuve(
        "m7_demander_publication_sociale",
        {"publication_id": cree["publication_id"], "empreinte": cree["empreinte"], "horodatage": HORODATAGE},
    )
    return actif_id, cree["publication_id"]


def _sortir(publication_id):
    """Le point de sortie du sas (exécuteur, doubles de test) avec le résolveur du registre du studio."""
    import contextlib

    jeton = "jeton-fictif-pour-le-double-0123456789abcdef"
    double = doubles.DoubleFacebook(jeton_attendu=jeton)

    @contextlib.contextmanager
    def fournisseur():
        yield jeton

    journal = stockage.maillons(*publication_outils.REGISTRE_PUBLICATIONS_SOCIALES)
    heure = datetime(2026, 1, 6, 15, 0, 0, tzinfo=UTC)
    with stockage.transaction():
        resolveur = actifs.resolveur_du_registre(stockage.maillons(*actifs.REGISTRE))
        sortie = executeur.executer(
            journal, publication_id, {"facebook": double}, fournisseur, politique.PolitiqueSas(), heure, resolveur
        )
    return sortie, double


def test_le_point_de_sortie_du_sas_publie_un_visuel_approuve_temoin_positif(monde):
    _actif_id, publication_id = _planifiee_avec_visuel_approuve()
    sortie, double = _sortir(publication_id)
    assert sortie["accepte"] is True and sortie["publie"] is True and double.appels == 1


def test_le_point_de_sortie_du_sas_refait_le_controle_des_actifs_un_visuel_revoque_ne_part_pas(monde):
    actif_id, publication_id = _planifiee_avec_visuel_approuve()
    _agent("m7_retirer_visuel_studio", {"actif_id": actif_id, "action": "revoquer", "motif": "retrait",
                                        "horodatage": HORODATAGE})
    sortie, double = _sortir(publication_id)
    assert sortie["accepte"] is False and sortie["publie"] is False
    assert "REJ-SOCIAL-MEDIA-ACTIF-NON-APPROUVE" in {r["code"] for r in sortie["refus"]}
    assert double.appels == 0 and double.publiees == []


# ======================================================================================================================
# Le site
# ======================================================================================================================
def _schema_avec_image_du_studio(chemin_image):
    donnees = json.loads((site_service.DOSSIER_DEMOS / DEMO / "site.json").read_text(encoding="utf-8"))
    octets = chemin_image.read_bytes()
    from m7_marketing.studio import png

    largeur, hauteur = png.dimensions(octets)
    donnees["images"] = [
        *donnees["images"],
        {
            "id": "visuel-studio",
            "fichier": "images/visuel-studio.png",
            "largeur": largeur,
            "hauteur": hauteur,
            "alt": {"fr-CA": "Visuel du studio", "en-CA": "Studio visual"},
        },
    ]
    return donnees


def _installer_site(base):
    destination = base / "sites" / DEMO / "actifs"
    shutil.copytree(site_service.DOSSIER_DEMOS / DEMO / "actifs", destination, dirs_exist_ok=True)
    return destination


def test_le_site_refuse_une_image_du_studio_non_approuvee_et_accepte_l_approuvee(monde):
    actifs_site = _installer_site(monde)
    actif_id, _ = _visuel_controle(_preparer())
    png_source = studio_outils._racine() / "visuels" / actif_id / "visuel.png"
    copie = actifs_site / "images" / "visuel-studio.png"
    copie.write_bytes(png_source.read_bytes())  # copie à la main, comme un agent qui contourne l'export
    schema = _schema_avec_image_du_studio(copie)
    schema["images"][-1]["alt"] = {"fr-CA": "Visuel du studio", "en-CA": "Studio visual"}
    refus = outils.valider_schema_site(schema=schema)
    generer = outils.generer_site_statique(schema=schema)
    assert generer["accepte"] is False and generer["refus"][0]["code"] == "REJ-SITE-IMAGE-STUDIO-NON-APPROUVE"
    preparer = outils.preparer_paquet_site(
        version="20260105T150000Z", cible={"hote": "vps.horizon.example"}, schema=schema
    )
    assert preparer["accepte"] is False and preparer["refus"][0]["code"] == "REJ-SITE-IMAGE-STUDIO-NON-APPROUVE"
    del refus
    _approuver_visuel(actif_id, {**ATTESTATIONS, "realiste": False})
    assert outils.generer_site_statique(schema=schema)["accepte"] is True


def test_le_site_refuse_un_fond_genere_brut(monde):
    actifs_site = _installer_site(monde)
    brief_id = _preparer(fond=f.GENERE)
    demande = _agent("m7_demander_fond_studio", {"brief_id": brief_id, "horodatage": HORODATAGE})
    fond_id = _executer_generation(demande["job_id"])["fond_actif_id"]
    copie = actifs_site / "images" / "visuel-studio.png"
    copie.write_bytes((studio_outils._racine() / "fonds" / f"{fond_id}.png").read_bytes())
    schema = _schema_avec_image_du_studio(copie)
    resultat = outils.generer_site_statique(schema=schema)
    assert resultat["accepte"] is False and resultat["refus"][0]["code"] == "REJ-SITE-IMAGE-STUDIO-FOND-BRUT"


def test_l_export_vers_le_site_copie_un_visuel_approuve_et_le_site_le_publie(monde):
    _installer_site(monde)
    actif_id, _ = _visuel_controle(_preparer())
    export = {"actif_id": actif_id, "site_id": DEMO, "nom": "visuel-studio", "format": "png", "horodatage": HORODATAGE}
    assert _agent("m7_exporter_visuel_vers_site", export)["refus"][0]["code"] == "REJ-STUDIO-ACTIF-ETAT"
    _approuver_visuel(actif_id, {**ATTESTATIONS, "realiste": False})
    resultat = _agent("m7_exporter_visuel_vers_site", export)
    assert resultat["accepte"] and resultat["fichier"] == "images/visuel-studio.png"
    copie = monde / "sites" / DEMO / "actifs" / "images" / "visuel-studio.png"
    assert hashlib.sha256(copie.read_bytes()).hexdigest() == resultat["sha256"]
    schema = json.loads((site_service.DOSSIER_DEMOS / DEMO / "site.json").read_text(encoding="utf-8"))
    entree = copy.deepcopy(resultat["entree_images"])
    entree["alt"] = {"fr-CA": entree["alt"]["fr"], "en-CA": "Studio visual"}
    schema["images"] = [*schema["images"], entree]
    assert outils.generer_site_statique(schema=schema)["accepte"] is True


# ======================================================================================================================
# Le registre de fournisseurs gouverne la génération
# ======================================================================================================================
def test_un_revenu_au_dessus_du_seuil_bloque_la_demande_de_fond_sans_repli(monde):
    with stockage.transaction() as cnx:
        registre.configurer(
            cnx,
            acteur="gestion",
            identifiant="image.seuil-test.local",
            declaration={
                "identifiant": "image.seuil-test.local",
                "capacite": "image",
                "mode": "local",
                "modele": "m",
                "licence": {
                    "code": None,
                    "poids": "Seuil 1 M$",
                    "usage_commercial": "sous_seuil",
                    "seuil_revenu_usd": 1_000_000,
                    "service_tiers": "autorise",
                    "integration": "bibliotheque",
                    "verification": "verifiee",
                    "source": "licence fictive",
                },
            },
        )
        courant = registre.profil_brut(cnx)
        registre.declarer_profil(
            cnx,
            acteur="gestion",
            usage_commercial=True,
            revenu_annuel_usd=500_000,
            territoires=["CA"],
            heberge_pour_tiers=False,
            revision_attendue=courant["revision"],
        )
        assert registre.activer(cnx, acteur="gestion", identifiant="image.seuil-test.local").conforme
        registre.selectionner(
            cnx, acteur="gestion", capacite="image", identifiant="image.seuil-test.local", departement="m07-marketing"
        )
    brief_id = _preparer(fond=f.GENERE)
    assert _agent("m7_demander_fond_studio", {"brief_id": brief_id, "horodatage": HORODATAGE})["accepte"]
    with stockage.transaction() as cnx:
        courant = registre.profil_brut(cnx)
        registre.declarer_profil(
            cnx,
            acteur="gestion",
            usage_commercial=True,
            revenu_annuel_usd=2_000_000,
            territoires=["CA"],
            heberge_pour_tiers=False,
            revision_attendue=courant["revision"],
        )
    refus = _agent("m7_demander_fond_studio", {"brief_id": brief_id, "horodatage": HORODATAGE, "variante": 1})
    assert (
        refus["refus"][0]["code"] == "REJ-STUDIO-MODELE-REFUS_POLITIQUE"
        and "SEUIL_REVENU_DEPASSE" in refus["codes_politique"]
    )
    # L'exécuteur de la première demande, lancé après le franchissement du seuil, refuse aussi : licence revérifiée.
    jobs = list(stockage.maillons(*["m07-marketing", "jobs_studio"]))
    from m7_marketing.studio import executeur as exe

    resultat = _executer_generation(jobs[0]["job_id"])
    assert resultat["refus"][0]["code"] == "REJ-STUDIO-MODELE-REFUS_POLITIQUE"
    assert list(stockage.maillons("m07-marketing", "provenance_studio")) == [] and exe.TENTATIVES_MAX == 3


def test_la_marque_vient_du_profil_et_un_profil_non_configure_bloque(base):
    brief = _brief()
    assert (
        _agent(
            "m7_preparer_brief_creatif",
            {
                "brief": {**brief, "marque": {"nom": "X"}},
                "cle_idempotence": "cle-brief-0123456789abcdef",
                "horodatage": HORODATAGE,
            },
        )["refus"][0]["code"]
        == "REJ-STUDIO-BRIEF-MARQUE-FOURNIE"
    )
    sans = _agent(
        "m7_preparer_brief_creatif",
        {"brief": brief, "cle_idempotence": "cle-brief-0123456789abcdef", "horodatage": HORODATAGE},
    )
    assert sans["refus"][0]["code"] == "REJ-STUDIO-MARQUE-NON-CONFIGUREE"


def test_les_registres_du_studio_sont_des_journaux_durables_chaines(monde):
    actif_id, _ = _visuel_controle(_preparer())
    from m7_marketing import journal_chaine

    for registre_nom in ("briefs_studio", "actifs_studio"):
        journal = list(stockage.maillons("m07-marketing", registre_nom))
        assert journal and journal_chaine.integre(journal)
    lu = _agent("m7_lire_studio", {})
    assert lu["total"] == 1 and lu["integrite"]["actifs"] is True and lu["briefs"][0]["gabarit"] == "banniere_social"
