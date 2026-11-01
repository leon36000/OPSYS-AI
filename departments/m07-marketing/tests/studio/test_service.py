"""`Studio` : les gestes de bout en bout sur des journaux en mémoire et un vrai dossier de fichiers (sans base)."""

from __future__ import annotations

import hashlib

import fabriques_studio as f
import pytest
from m7_marketing.studio import actifs, executeur, generation, logos, ocr, polices, service
from m7_marketing.studio import portes as p

NATHAN = {"par": "nathan", "role": "nathan_owner", "source": "file_approbation"}
ATTESTATIONS = {
    "elements_critiques_verifies": True,
    "aucun_visage_ni_plaque_identifiable": True,
    "rendu_relu_a_l_ecran": True,
    "realiste": False,
}
CLE = "cle-brief-0123456789abcdef"
ID = "image.double-deterministe.test"


class Banc:
    def __init__(self, tmp_path):
        self.dossier = f.ecrire_polices(tmp_path / "polices")
        self.verdict = {"conforme": True, "codes": [], "fournisseur_id": ID}
        self.journaux = service.Journaux([], [], [], [])
        self.studio = service.Studio(
            journaux=self.journaux,
            fichiers=service.FichiersStudio(tmp_path / "studio"),
            polices=lambda production: polices.charger_dossier(self.dossier, production=production),
            selection=lambda genre: f.selection_double(),
            verdict_licence=lambda fournisseur_id: self.verdict,
            lecteurs=ocr.lecteurs_par_defaut,
            vectoriseur=logos.VectoriseurDouble(),
            maintenant=lambda: f.MAINTENANT,
            par="agent",
        )

    def brief(self, gabarit="banniere_social", cle=CLE, **plus):
        donnees = f.brief(gabarit, elements_critiques=f.critiques("telephone"), mentions_obligatoires=[], **plus)
        resultat = self.studio.preparer_brief(donnees, cle)
        assert resultat["accepte"], resultat
        return resultat["brief_id"]

    def fond(self, brief_id):
        demande = self.studio.demander_fond(brief_id)
        assert demande["accepte"], demande
        j = self.journaux
        resultat = executeur.executer(
            j.jobs,
            j.provenance,
            j.actifs,
            demande["job_id"],
            adaptateurs={ID: generation.GenerateurImageDouble()},
            resoudre_modele=lambda genre: f.selection_double(),
            ecrire_fond=lambda sha, octets, fmt: self.studio.fichiers.ecrire(
                f"fonds/{actifs.identifiant_fond(sha)}.{fmt}", octets
            ),
            par="executeur",
            horodatage=f.HORODATAGE,
            maintenant=f.MAINTENANT,
        )
        assert resultat["accepte"], resultat
        return resultat["fond_actif_id"]

    def approuve(self, actif_id):
        controle = self.studio.controler(actif_id)
        assert controle["accepte"] and controle["conforme"], controle
        assert self.studio.demander_revue(actif_id)["accepte"]
        etat = actifs.plier(self.journaux.actifs)[actif_id]
        resultat = self.studio.approuver(
            actif_id, etat.donnees["composition_empreinte"], etat.rapport["empreinte"], NATHAN, ATTESTATIONS
        )
        assert resultat["accepte"], resultat
        return resultat


@pytest.fixture
def banc(tmp_path):
    return Banc(tmp_path)


def _codes(resultat):
    return [r["code"] for r in resultat.get("refus", [])]


def test_chaine_complete_sans_ia_brief_composition_controle_revue_approbation_media(banc):
    brief_id = banc.brief()
    compose = banc.studio.composer(brief_id)
    assert compose["accepte"] and compose["ia_generee"] is False and set(compose["artefacts"]) == {"svg", "png"}
    actif_id = compose["actif_id"]
    for fmt in ("svg", "png"):
        octets = banc.studio.fichiers.lire(f"visuels/{actif_id}/visuel.{fmt}", compose["artefacts"][fmt]["sha256"])
        assert hashlib.sha256(octets).hexdigest() == compose["artefacts"][fmt]["sha256"]
    controle = banc.studio.controler(actif_id)
    assert controle["conforme"] is True and controle["lecteurs"] and controle["constats_en_echec"] == []
    assert banc.studio.demander_revue(actif_id)["etat"] == actifs.ETAT_EN_REVUE
    etat = actifs.plier(banc.journaux.actifs)[actif_id]
    approuve = banc.studio.approuver(
        actif_id, etat.donnees["composition_empreinte"], etat.rapport["empreinte"], NATHAN, ATTESTATIONS
    )
    assert approuve["accepte"] and approuve["etat"] == actifs.ETAT_APPROUVE
    media = actifs.media_pour_sas(banc.journaux.actifs, actif_id)["media"]
    assert media["origine"] == "composition_deterministe" and media["ia_generee"] is False
    lu = banc.studio.lire(actif_id)["actif"]
    assert lu["etat"] == actifs.ETAT_APPROUVE and lu["approuve_par"] == "nathan"


def test_chaine_complete_avec_fond_genere_et_provenance(banc):
    brief_id = banc.brief(fond=f.GENERE)
    fond_id = banc.fond(brief_id)
    compose = banc.studio.composer(brief_id, fond_actif_id=fond_id)
    assert compose["accepte"] and compose["ia_generee"] is True
    actif_id = compose["actif_id"]
    etat = actifs.plier(banc.journaux.actifs)[actif_id]
    assert etat.donnees["fond_actif_id"] == fond_id and etat.donnees["nature_generateur"] == "double"
    assert etat.donnees["provenance"] == actifs.plier(banc.journaux.actifs)[fond_id].donnees["provenance_chaine"]
    controle = banc.studio.controler(actif_id)
    assert controle["conforme"], controle["constats_en_echec"]
    banc.studio.demander_revue(actif_id)
    etat = actifs.plier(banc.journaux.actifs)[actif_id]
    approuve = banc.studio.approuver(
        actif_id,
        etat.donnees["composition_empreinte"],
        etat.rapport["empreinte"],
        NATHAN,
        {**ATTESTATIONS, "realiste": True},
    )
    assert approuve["accepte"]
    assert actifs.media_pour_sas(banc.journaux.actifs, actif_id)["media"]["realiste"] is True


def test_un_brief_au_fond_genere_ne_compose_pas_sans_fond_ou_avec_un_fond_obsolete(banc):
    brief_id = banc.brief(fond=f.GENERE)
    assert _codes(banc.studio.composer(brief_id)) == [service.REJ_FOND_ABSENT]
    fond_id = banc.fond(brief_id)
    revise = banc.studio.preparer_brief(
        f.brief(
            "banniere_social",
            elements_critiques=f.critiques("telephone"),
            mentions_obligatoires=[],
            fond={**f.GENERE, "sujet": "tuiles rouges au soleil couchant"},
        ),
        CLE,
        brief_id=brief_id,
    )
    assert revise["revision"] == 2
    assert _codes(banc.studio.composer(brief_id, fond_actif_id=fond_id)) == [service.REJ_FOND_OBSOLETE]
    assert _codes(banc.studio.composer(brief_id, fond_actif_id="fond-inconnu")) == [actifs.REJ_ACTIF_INCONNU]


def test_un_brief_sans_fond_genere_refuse_un_fond_fourni(banc):
    brief_id = banc.brief()
    avec_ia = banc.brief(fond=f.GENERE, cle="cle-brief-autre-0123456789")
    fond_id = banc.fond(avec_ia)
    assert _codes(banc.studio.composer(brief_id, fond_actif_id=fond_id)) == ["REJ-STUDIO-FOND-NON-DEMANDE"]


def test_un_fond_modifie_sur_le_disque_est_refuse(banc):
    brief_id = banc.brief(fond=f.GENERE)
    fond_id = banc.fond(brief_id)
    banc.studio.fichiers.ecrire(f"fonds/{fond_id}.png", f.fond_synthetique(300, 200, graine=99))
    resultat = banc.studio.composer(brief_id, fond_actif_id=fond_id)
    assert _codes(resultat) == [service.REJ_FICHIER] and "empreinte" in resultat["refus"][0]["detail"]


def test_la_licence_du_modele_revenue_non_conforme_bloque_la_composition_puis_le_controle_puis_l_approbation(banc):
    brief_id = banc.brief(fond=f.GENERE)
    fond_id = banc.fond(brief_id)
    actif_id = banc.studio.composer(brief_id, fond_actif_id=fond_id)["actif_id"]
    banc.verdict = {"conforme": False, "codes": ["SEUIL_REVENU_DEPASSE"], "fournisseur_id": ID}
    assert _codes(banc.studio.composer(brief_id, fond_actif_id=fond_id)) == [actifs.REJ_LICENCE]
    controle = banc.studio.controler(actif_id)
    assert controle["conforme"] is False and any(c["code"] == "QC-LICENCE" for c in controle["constats_en_echec"])
    assert _codes(banc.studio.demander_revue(actif_id)) == [actifs.REJ_REVUE_NON_CONFORME]


def test_un_artefact_remplace_sur_le_disque_apres_la_composition_est_pris_au_controle(banc):
    brief_id = banc.brief()
    compose = banc.studio.composer(brief_id)
    actif_id = compose["actif_id"]
    png = banc.studio.fichiers.lire(f"visuels/{actif_id}/visuel.png")
    banc.studio.fichiers.ecrire(f"visuels/{actif_id}/visuel.png", png[:-12] + bytes([png[-12] ^ 1]) + png[-11:])
    controle = banc.studio.controler(actif_id)
    assert controle["accepte"] and controle["conforme"] is False
    assert {"QC-REPRODUCTIBILITE"} <= {c["code"] for c in controle["constats_en_echec"]}
    assert _codes(banc.studio.demander_revue(actif_id)) == [actifs.REJ_REVUE_NON_CONFORME]


def test_un_artefact_supprime_est_un_echec_de_controle_pas_un_saut(banc):
    brief_id = banc.brief()
    actif_id = banc.studio.composer(brief_id)["actif_id"]
    (banc.studio.fichiers.racine / "visuels" / actif_id / "visuel.svg").unlink()
    controle = banc.studio.controler(actif_id)
    assert controle["conforme"] is False


def test_le_controle_exige_la_composition_refaite_identique(banc):
    brief_id = banc.brief()
    actif_id = banc.studio.composer(brief_id)["actif_id"]
    # Une police remplacée dans le registre (autre empreinte) change la composition : le contrôle refuse de conclure.
    autre = f.ecrire_polices(banc.dossier.parent / "polices2", loca_courte=True)  # autre fichier, mêmes glyphes
    banc.dossier = autre
    resultat = banc.studio.controler(actif_id)
    assert not resultat["accepte"] and resultat["refus"][0]["code"] in (service.REJ_COMPOSITION_DERIVEE,)


def test_composer_un_brief_inconnu_ou_sans_polices(banc, tmp_path):
    assert _codes(banc.studio.composer("brief-inconnu")) == ["REJ-STUDIO-BRIEF-INCONNU"]
    brief_id = banc.brief()
    banc.dossier = tmp_path / "vide"
    assert _codes(banc.studio.composer(brief_id)) == ["REJ-STUDIO-POLICE-ABSENTE"]


def test_un_brief_non_fictif_refuse_les_polices_de_test(banc):
    donnees = f.brief(
        "banniere_social",
        fictif=False,
        elements_critiques=[{"type": "telephone", "valeur": "+1 514 523 4567", "source": "fiche d'entreprise"}],
        mentions_obligatoires=[],
    )
    brief_id = banc.studio.preparer_brief(donnees, CLE)["brief_id"]
    assert _codes(banc.studio.composer(brief_id)) == ["REJ-STUDIO-POLICE-FICTIVE-EN-PRODUCTION"]


def test_un_texte_qui_ne_tient_pas_est_un_refus_typé_pas_une_exception(banc):
    donnees = f.brief(
        "carte_affaires",
        elements_critiques=[
            {"type": "telephone", "valeur": f"+1 450 555 01{i:02d}", "source": "fiche fictive"} for i in range(12)
        ],
    )
    brief_id = banc.studio.preparer_brief(donnees, CLE)["brief_id"]
    assert _codes(banc.studio.composer(brief_id)) == ["REJ-STUDIO-TEXTE-NE-TIENT-PAS"]


def test_demander_fond_refuse_un_brief_sans_fond_genere_un_genre_inconnu_et_une_politique_refusee(banc):
    brief_id = banc.brief()
    assert _codes(banc.studio.demander_fond(brief_id)) == [executeur.REJ_FOND_NON_DEMANDE]
    assert _codes(banc.studio.demander_fond(brief_id, "audio")) == ["REJ-STUDIO-MODELE-CAPACITE"]
    assert _codes(banc.studio.demander_fond(brief_id, "image", variante=100)) == ["REJ-STUDIO-VARIANTE"]
    assert _codes(banc.studio.demander_fond("brief-inconnu")) == ["REJ-STUDIO-BRIEF-INCONNU"]
    from m7_marketing.studio import modeles

    def refuse(genre):
        raise modeles.ModeleRefuse("REJ-STUDIO-MODELE-REFUS_POLITIQUE", "non conforme", ("SEUIL_REVENU_DEPASSE",))

    brief_ia = banc.brief(fond=f.GENERE, cle="cle-brief-autre-0123456789")
    import dataclasses

    studio = dataclasses.replace(banc.studio, selection=refuse)
    resultat = studio.demander_fond(brief_ia)
    assert _codes(resultat) == ["REJ-STUDIO-MODELE-REFUS_POLITIQUE"] and resultat["codes_politique"] == [
        "SEUIL_REVENU_DEPASSE"
    ]
    assert banc.journaux.jobs == []


# -- logos -----------------------------------------------------------------------------------------------------------
LOGO = ["M 0 0 H 60 V 100 H 0 Z", "M 70 0 H 100 V 100 H 70 Z"]


def _logo_approuve(banc):
    resultat = banc.studio.vectoriser_logo(True, chemins=LOGO, vb_w=100, vb_h=100)
    assert resultat["accepte"] and resultat["avertissement"] == actifs.AVERTISSEMENT_LOGO
    logo_id = resultat["actif_id"]
    controle = banc.studio.controler(logo_id)
    assert controle["conforme"] and controle["avertissement"] == actifs.AVERTISSEMENT_LOGO
    assert banc.studio.demander_revue(logo_id)["accepte"]
    etat = actifs.plier(banc.journaux.actifs)[logo_id]
    approbation = banc.studio.approuver(
        logo_id,
        etat.donnees["composition_empreinte"],
        etat.rapport["empreinte"],
        NATHAN,
        {
            "avertissement_logo_lu": True,
            "note_contribution_humaine": "Proportions et palette retouchées par la direction.",
            "recherche_anteriorite": "renvoyee_a_un_agent_de_marques",
        },
    )
    assert approbation["accepte"] and approbation["avertissement"] == actifs.AVERTISSEMENT_LOGO
    return logo_id


def test_un_logo_non_approuve_ne_se_pose_pas_un_logo_approuve_se_pose_et_se_lit_dans_le_pdf(banc):
    brief_id = banc.brief("carte_affaires")
    brouillon = banc.studio.vectoriser_logo(True, chemins=LOGO, vb_w=100, vb_h=100)["actif_id"]
    refus = banc.studio.composer(brief_id, logo_actif_id=brouillon)
    assert _codes(refus) == [service.REJ_LOGO_NON_APPROUVE]
    logo_id = _logo_approuve(banc)
    donnees = f.brief("carte_affaires", elements_critiques=f.critiques("telephone"), mentions_obligatoires=[])
    brief_logo = banc.studio.preparer_brief(donnees, "cle-brief-logo-0123456789")["brief_id"]
    compose = banc.studio.composer(brief_logo, logo_actif_id=logo_id)
    assert compose["accepte"], compose
    assert banc.studio.controler(compose["actif_id"])["conforme"]


def test_un_logo_vectorise_depuis_un_concept_raster_du_studio(banc):
    brief_id = banc.brief(fond=f.GENERE)
    fond_id = banc.fond(brief_id)
    resultat = banc.studio.vectoriser_logo(True, fond_actif_id=fond_id, seuil=128)
    # Le fond du double est un damier de bandes : trop de formes pour le vectoriseur double (refus typé, pas
    # d'exception).
    assert resultat["accepte"] is False and resultat["refus"][0]["code"] == "REJ-STUDIO-LOGO-CHEMIN-INVALIDE"


def test_vectoriser_exige_exactement_une_source_et_refuse_les_chemins_hors_sous_ensemble(banc):
    assert _codes(banc.studio.vectoriser_logo(True)) == ["REJ-STUDIO-LOGO"]
    assert _codes(banc.studio.vectoriser_logo(True, fond_actif_id="fond-x", chemins=LOGO, vb_w=1, vb_h=1)) == [
        "REJ-STUDIO-LOGO"
    ]
    assert _codes(banc.studio.vectoriser_logo(True, chemins=LOGO)) == ["REJ-STUDIO-LOGO"]
    assert _codes(banc.studio.vectoriser_logo(True, chemins=["M 0 0 A 1 1 0 0 0 5 5"], vb_w=10, vb_h=10)) == [
        "REJ-STUDIO-LOGO-CHEMIN-INVALIDE"
    ]
    assert _codes(banc.studio.vectoriser_logo(True, fond_actif_id="fond-inconnu")) == [actifs.REJ_ACTIF_INCONNU]


# -- export vers un site -----------------------------------------------------------------------------------------------
def test_exporter_vers_un_site_exige_l_approbation_copie_le_fichier_exact_et_rend_l_entree_images(banc, tmp_path):
    brief_id = banc.brief()
    actif_id = banc.studio.composer(brief_id)["actif_id"]
    dossier = lambda site_id: tmp_path / "sites" / site_id / "actifs"  # noqa: E731
    assert _codes(banc.studio.exporter_vers_site(actif_id, "site-fictif", "hero", "png", dossier)) == [actifs.REJ_ETAT]
    banc.approuve(actif_id)
    resultat = banc.studio.exporter_vers_site(actif_id, "site-fictif", "hero", "png", dossier)
    assert resultat["accepte"] and resultat["fichier"] == "images/hero.png" and resultat["execute"] is False
    copie = (tmp_path / "sites" / "site-fictif" / "actifs" / "images" / "hero.png").read_bytes()
    assert hashlib.sha256(copie).hexdigest() == resultat["sha256"]
    entree = resultat["entree_images"]
    assert entree["id"] == "hero" and entree["fichier"] == "images/hero.png" and entree["alt"]["fr"]
    assert "avertissement_ia" not in resultat
    for site_id, nom, fmt in (
        ("../x", "hero", "png"),
        ("site-fictif", "../hero", "png"),
        ("site-fictif", "Hero", "png"),
        ("site-fictif", "hero", "pdf"),
        ("Site", "hero", "png"),
    ):
        assert _codes(banc.studio.exporter_vers_site(actif_id, site_id, nom, fmt, dossier)) == [
            "REJ-STUDIO-EXPORT-SITE"
        ]
    assert _codes(banc.studio.exporter_vers_site("visuel-inconnu", "site-fictif", "hero", "png", dossier)) == [
        actifs.REJ_ACTIF_INCONNU
    ]


def test_exporter_un_visuel_ia_rend_l_avertissement_du_site_et_refuse_un_fichier_modifie(banc, tmp_path):
    brief_id = banc.brief(fond=f.GENERE)
    fond_id = banc.fond(brief_id)
    actif_id = banc.studio.composer(brief_id, fond_actif_id=fond_id)["actif_id"]
    banc.approuve(actif_id)
    dossier = lambda site_id: tmp_path / "sites" / site_id / "actifs"  # noqa: E731
    assert "avertissement_ia" in banc.studio.exporter_vers_site(actif_id, "site-fictif", "hero", "png", dossier)
    banc.studio.fichiers.ecrire(f"visuels/{actif_id}/visuel.png", b"autre contenu")
    assert _codes(banc.studio.exporter_vers_site(actif_id, "site-fictif", "hero2", "png", dossier)) == [
        "REJ-STUDIO-EXPORT-SITE"
    ]


def test_rejeter_et_revoquer_par_le_service_et_lecture_resumee(banc):
    brief_id = banc.brief()
    actif_id = banc.studio.composer(brief_id)["actif_id"]
    assert banc.studio.rejeter(actif_id, "non retenu")["etat"] == actifs.ETAT_REJETE
    resume = banc.studio.lire()
    assert (
        resume["total"] == 1 and resume["briefs"][0]["brief_id"] == brief_id and resume["integrite"]["actifs"] is True
    )
    assert banc.studio.lire(brief_id=brief_id)["brief"]["gabarit"] == "banniere_social"
    autre = banc.studio.composer(banc.brief(cle="cle-brief-deux-0123456789", objet="Autre objet de campagne fictive"))[
        "actif_id"
    ]
    banc.approuve(autre)
    assert banc.studio.revoquer(autre, "licence changée")["etat"] == actifs.ETAT_REVOQUE
    assert p.KIND_VISUEL


def test_fichiers_du_studio_chemins_et_liens_refuses(tmp_path):
    fichiers = service.FichiersStudio(tmp_path / "studio")
    for mauvais in ("../x", "fonds/../x", "autre/x", "fonds", "fonds/a/b/c", "fonds/A.png", "fonds/"):
        with pytest.raises(OSError):
            fichiers.ecrire(mauvais, b"x")
    fichiers.ecrire("fonds/a.png", b"contenu")
    assert fichiers.lire("fonds/a.png", hashlib.sha256(b"contenu").hexdigest()) == b"contenu"
    with pytest.raises(OSError):
        fichiers.lire("fonds/a.png", "0" * 64)
    (tmp_path / "studio" / "fonds" / "lien.png").symlink_to(tmp_path / "studio" / "fonds" / "a.png")
    with pytest.raises(OSError):
        fichiers.lire("fonds/lien.png")
    assert oct((tmp_path / "studio" / "fonds" / "a.png").stat().st_mode & 0o777) == "0o600"
