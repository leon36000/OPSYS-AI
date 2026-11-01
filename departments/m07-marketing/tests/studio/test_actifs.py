"""Registre des actifs et revue humaine : états, empreintes, attestations, lecteur réel pour le non fictif, licence."""

from __future__ import annotations

import copy
import json

import fabriques_studio as f
import pytest
from m7_marketing import journal_chaine
from m7_marketing.studio import actifs, controle, ocr, polices
from m7_marketing.studio import brief as b
from m7_marketing.studio import composition as comp_mod
from m7_marketing.studio import portes as p

NATHAN = {"par": "nathan", "role": "nathan_owner", "source": "file_approbation"}
ATTESTATIONS = {
    "elements_critiques_verifies": True,
    "aucun_visage_ni_plaque_identifiable": True,
    "rendu_relu_a_l_ecran": True,
    "realiste": False,
}


@pytest.fixture(scope="module")
def registre(tmp_path_factory):
    return polices.charger_dossier(f.ecrire_polices(tmp_path_factory.mktemp("p")), production=False)


def _composer(registre, donnees, **kw):
    brief, refus = b.depuis_dict(donnees)
    assert brief is not None, refus
    return comp_mod.composer_visuel(brief, registre, f.POLICE_ID, **kw)


def _rapport(comp, registre, **kw):
    return controle.controler(comp, registre, ocr.lecteurs_par_defaut(registre), maintenant=f.MAINTENANT, **kw).donnees


@pytest.fixture(scope="module")
def sans_ia(registre):
    donnees = f.brief("banniere_social", elements_critiques=f.critiques("telephone"), mentions_obligatoires=[])
    comp = _composer(registre, donnees)
    return comp, _rapport(comp, registre)


@pytest.fixture(scope="module")
def avec_ia(registre):
    donnees = f.brief(
        "banniere_social", elements_critiques=f.critiques("telephone"), mentions_obligatoires=[], fond=f.GENERE
    )
    comp = _composer(registre, donnees, fond_png=f.fond_synthetique(1200, 800), provenance=f.PROVENANCE)
    return comp, _rapport(comp, registre, verdict_licence=lambda: {"conforme": True, "codes": []})


def _composee(journal, comp, **kw):
    return actifs.enregistrer_composition(
        journal, comp, brief_id="brief-x", alt="Texte alternatif", par="agent", horodatage=f.HORODATAGE, **kw
    )


def _vers_revue(journal, comp, rapport):
    identifiant = _composee(journal, comp)["actif_id"]
    assert actifs.enregistrer_controle(journal, identifiant, rapport, "agent", f.HORODATAGE)["accepte"]
    assert actifs.demander_revue(journal, identifiant, "agent", f.HORODATAGE)["accepte"]
    return identifiant


def _approuver(journal, identifiant, comp, rapport, **kw):
    return actifs.approuver(
        journal,
        identifiant,
        comp.empreinte(),
        rapport["empreinte"],
        kw.pop("approbateur", NATHAN),
        kw.pop("attestations", ATTESTATIONS),
        f.HORODATAGE,
        **kw,
    )


def _codes(resultat):
    return [r["code"] for r in resultat.get("refus", [])]


def test_le_cycle_complet_compose_controle_revue_approbation(sans_ia):
    comp, rapport = sans_ia
    journal: list = []
    cree = _composee(journal, comp)
    assert cree["etat"] == actifs.ETAT_COMPOSE and cree["actif_id"] == actifs.identifiant_visuel(comp.empreinte())
    assert (
        actifs.enregistrer_controle(journal, cree["actif_id"], rapport, "agent", f.HORODATAGE)["etat"]
        == actifs.ETAT_CONTROLE_CONFORME
    )
    assert actifs.demander_revue(journal, cree["actif_id"], "agent", f.HORODATAGE)["etat"] == actifs.ETAT_EN_REVUE
    approuve = _approuver(journal, cree["actif_id"], comp, rapport)
    assert approuve["accepte"] and approuve["etat"] == actifs.ETAT_APPROUVE and approuve["execute"] is False
    assert journal_chaine.integre(journal) and len(journal) == 4
    etat = actifs.plier(journal)[cree["actif_id"]]
    assert etat.approuve and etat.approbation["par"] == "nathan"


def test_composer_deux_fois_le_meme_visuel_est_idempotent(sans_ia):
    comp, _ = sans_ia
    journal: list = []
    un, deux = _composee(journal, comp), _composee(journal, comp)
    assert un["actif_id"] == deux["actif_id"] and deux["deja_cree"] is True and len(journal) == 1


def test_un_visuel_non_conforme_ne_passe_pas_en_revue_et_ne_s_approuve_pas(sans_ia):
    comp, _ = sans_ia
    donnees = copy.deepcopy(sans_ia[1])
    donnees["constats"][0]["ok"] = False  # un constat critique en échec
    donnees["conforme"] = False
    donnees["empreinte"] = controle.empreinte_rapport(donnees)
    journal: list = []
    identifiant = _composee(journal, comp)["actif_id"]
    assert (
        actifs.enregistrer_controle(journal, identifiant, donnees, "agent", f.HORODATAGE)["etat"]
        == actifs.ETAT_CONTROLE_ECHEC
    )
    revue = actifs.demander_revue(journal, identifiant, "agent", f.HORODATAGE)
    assert _codes(revue) == [actifs.REJ_REVUE_NON_CONFORME] and "QC-ELEMENTS" in revue["refus"][0]["detail"]
    assert _codes(_approuver(journal, identifiant, comp, donnees)) == [actifs.REJ_ETAT]
    assert len(journal) == 2


def test_revue_sans_controle_refusee(sans_ia):
    comp, _ = sans_ia
    journal: list = []
    identifiant = _composee(journal, comp)["actif_id"]
    assert _codes(actifs.demander_revue(journal, identifiant, "agent", f.HORODATAGE)) == [actifs.REJ_ETAT]


def test_rapport_retouche_forge_ou_etranger_refuse(sans_ia, avec_ia):
    comp, rapport = sans_ia
    journal: list = []
    identifiant = _composee(journal, comp)["actif_id"]
    retouche = copy.deepcopy(rapport)
    retouche["constats"][1]["ok"] = False
    assert _codes(actifs.enregistrer_controle(journal, identifiant, retouche, "agent", f.HORODATAGE)) == [
        actifs.REJ_RAPPORT
    ]
    menteur = copy.deepcopy(rapport)
    menteur["constats"][0]["ok"] = False
    menteur["empreinte"] = controle.empreinte_rapport(menteur)  # empreinte recalculée mais verdict inchangé
    assert _codes(actifs.enregistrer_controle(journal, identifiant, menteur, "agent", f.HORODATAGE)) == [
        actifs.REJ_RAPPORT
    ]
    autre = avec_ia[1]  # rapport d'une AUTRE composition
    assert _codes(actifs.enregistrer_controle(journal, identifiant, autre, "agent", f.HORODATAGE)) == [
        actifs.REJ_RAPPORT_ETRANGER
    ]
    assert _codes(actifs.enregistrer_controle(journal, "visuel-inconnu", rapport, "agent", f.HORODATAGE)) == [
        actifs.REJ_ACTIF_INCONNU
    ]
    assert len(journal) == 1


@pytest.mark.parametrize(
    "approbateur",
    [
        None,
        {},
        {"par": "agent", "role": "agent", "source": "x"},
        {"par": "gestion", "role": "admin", "source": "appareil"},
        {"par": "", "role": "nathan_owner", "source": "x"},
        {"par": "nathan", "role": "nathan_owner", "source": ""},
    ],
)
def test_l_approbation_est_une_decision_de_personne_du_proprietaire(sans_ia, approbateur):
    comp, rapport = sans_ia
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    resultat = _approuver(journal, identifiant, comp, rapport, approbateur=approbateur)
    assert _codes(resultat) == [actifs.REJ_HUMAIN] and len(journal) == 3


def test_l_approbation_porte_l_empreinte_de_la_composition_et_celle_du_rapport(sans_ia):
    comp, rapport = sans_ia
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    for kwargs in (
        {"composition_empreinte": "0" * 64, "rapport_empreinte": rapport["empreinte"]},
        {"composition_empreinte": comp.empreinte(), "rapport_empreinte": "0" * 64},
    ):
        resultat = actifs.approuver(
            journal,
            identifiant,
            kwargs["composition_empreinte"],
            kwargs["rapport_empreinte"],
            NATHAN,
            ATTESTATIONS,
            f.HORODATAGE,
        )
        assert _codes(resultat) == [actifs.REJ_EMPREINTE]
    assert len(journal) == 3


@pytest.mark.parametrize(
    "attestations",
    [
        None,
        "oui",
        {},
        {**ATTESTATIONS, "elements_critiques_verifies": False},
        {**ATTESTATIONS, "aucun_visage_ni_plaque_identifiable": "oui"},
        {k: v for k, v in ATTESTATIONS.items() if k != "rendu_relu_a_l_ecran"},
        {**ATTESTATIONS, "inconnue": True},
        {k: v for k, v in ATTESTATIONS.items() if k != "realiste"},
        {**ATTESTATIONS, "realiste": "non"},
        {**ATTESTATIONS, "realiste": True},  # pas d'IA : jamais « réaliste »
    ],
)
def test_attestations_de_la_personne_exigees_et_strictes(sans_ia, attestations):
    comp, rapport = sans_ia
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    resultat = _approuver(journal, identifiant, comp, rapport, attestations=attestations)
    assert _codes(resultat) == [actifs.REJ_ATTESTATION] and len(journal) == 3


def test_un_visuel_bilingue_exige_l_attestation_de_la_langue(registre):
    donnees = f.brief(
        "banniere_social", langues=["fr", "en"], elements_critiques=f.critiques("telephone"), mentions_obligatoires=[]
    )
    donnees["textes"] = {"titre": {"fr": "Votre toiture en confiance", "en": "Your roof, with confidence"}}
    comp = _composer(registre, donnees)
    rapport = _rapport(comp, registre)
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    assert _codes(_approuver(journal, identifiant, comp, rapport)) == [actifs.REJ_ATTESTATION]
    assert _approuver(
        journal, identifiant, comp, rapport, attestations={**ATTESTATIONS, "langue_francaise_validee": True}
    )["accepte"]


def test_un_visuel_sans_ia_n_a_pas_besoin_de_licence_un_visuel_ia_oui(avec_ia):
    comp, rapport = avec_ia
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    assert _codes(_approuver(journal, identifiant, comp, rapport)) == [actifs.REJ_LICENCE]  # aucun verdict : refus
    assert _codes(
        _approuver(
            journal,
            identifiant,
            comp,
            rapport,
            verdict_licence=lambda: {"conforme": False, "codes": ["SEUIL_REVENU_DEPASSE"]},
        )
    ) == [actifs.REJ_LICENCE]
    resultat = _approuver(
        journal,
        identifiant,
        comp,
        rapport,
        verdict_licence=lambda: {"conforme": True, "codes": []},
        attestations={**ATTESTATIONS, "realiste": True},
    )
    assert resultat["accepte"] and resultat["attestations"]["realiste"] is True


# -- non fictif : lecteur réel exigé ----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def non_fictif(registre):
    donnees = f.brief(
        "banniere_social",
        fictif=False,
        elements_critiques=[{"type": "telephone", "valeur": "+1 514 523 4567", "source": "fiche d'entreprise"}],
        mentions_obligatoires=[],
    )
    comp = _composer(registre, donnees)
    return comp, _rapport(comp, registre)


def _avec_lecteur_reel(rapport):
    r = copy.deepcopy(rapport)
    for lecteur in r["lecteurs"]:
        lecteur["nature"] = "reel"
    r["empreinte"] = controle.empreinte_rapport(r)
    return r


def test_un_visuel_non_fictif_ne_s_approuve_pas_sur_la_lecture_d_un_double(non_fictif):
    comp, rapport = non_fictif
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    resultat = _approuver(journal, identifiant, comp, rapport)
    assert _codes(resultat) == [actifs.REJ_OCR_REEL] and "OCR réel" in resultat["refus"][0]["detail"]


def test_un_visuel_non_fictif_lu_par_un_lecteur_reel_s_approuve(non_fictif):
    comp, rapport = non_fictif
    reel = _avec_lecteur_reel(rapport)
    journal: list = []
    identifiant = _composee(journal, comp)["actif_id"]
    assert actifs.enregistrer_controle(journal, identifiant, reel, "agent", f.HORODATAGE)["accepte"]
    assert actifs.demander_revue(journal, identifiant, "agent", f.HORODATAGE)["accepte"]
    assert _approuver(journal, identifiant, comp, reel)["accepte"]


def test_un_lecteur_reel_declare_pour_un_seul_des_formats_ne_suffit_pas(non_fictif):
    comp, rapport = non_fictif
    mixte = copy.deepcopy(rapport)
    for lecteur in mixte["lecteurs"]:  # le SVG est lu par un lecteur réel, le PNG (le livré) par un double
        lecteur["nature"] = "reel" if lecteur["format"] == "svg" else "double"
    mixte["empreinte"] = controle.empreinte_rapport(mixte)
    journal: list = []
    identifiant = _composee(journal, comp)["actif_id"]
    actifs.enregistrer_controle(journal, identifiant, mixte, "agent", f.HORODATAGE)
    actifs.demander_revue(journal, identifiant, "agent", f.HORODATAGE)
    assert _codes(_approuver(journal, identifiant, comp, mixte)) == [actifs.REJ_OCR_REEL]


def test_un_visuel_non_fictif_avec_fond_de_generateur_double_refuse(registre):
    donnees = f.brief(
        "banniere_social",
        fictif=False,
        fond=f.GENERE,
        elements_critiques=[{"type": "telephone", "valeur": "+1 514 523 4567", "source": "fiche d'entreprise"}],
        mentions_obligatoires=[],
    )
    comp = _composer(registre, donnees, fond_png=f.fond_synthetique(1200, 800), provenance=f.PROVENANCE)
    rapport = _avec_lecteur_reel(_rapport(comp, registre, verdict_licence=lambda: {"conforme": True, "codes": []}))
    journal: list = []
    identifiant = _composee(journal, comp, nature_generateur="double")["actif_id"]
    actifs.enregistrer_controle(journal, identifiant, rapport, "agent", f.HORODATAGE)
    actifs.demander_revue(journal, identifiant, "agent", f.HORODATAGE)
    resultat = _approuver(journal, identifiant, comp, rapport, verdict_licence=lambda: {"conforme": True, "codes": []})
    assert _codes(resultat) == [actifs.REJ_GENERATEUR_TEST]


# -- retrait, rejet, état du journal ---------------------------------------------------------------------------------
def test_rejeter_et_revoquer(sans_ia):
    comp, rapport = sans_ia
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    assert _codes(actifs.revoquer(journal, identifiant, "agent", "trop tôt", f.HORODATAGE)) == [actifs.REJ_ETAT]
    assert _approuver(journal, identifiant, comp, rapport)["accepte"]
    assert _codes(actifs.rejeter(journal, identifiant, "agent", "non", f.HORODATAGE)) == [actifs.REJ_ETAT]
    assert (
        actifs.revoquer(journal, identifiant, "agent", "licence changée", f.HORODATAGE)["etat"] == actifs.ETAT_REVOQUE
    )
    assert not actifs.resolveur_du_registre(journal)(comp.empreintes()["png"]["sha256"]).approuve
    assert _codes(actifs.revoquer(journal, identifiant, "agent", "encore", f.HORODATAGE)) == [actifs.REJ_ETAT]
    neuf: list = []
    identifiant2 = _composee(neuf, comp)["actif_id"]
    assert actifs.rejeter(neuf, identifiant2, "agent", "refus", f.HORODATAGE)["etat"] == actifs.ETAT_REJETE
    assert _codes(actifs.demander_revue(neuf, identifiant2, "agent", f.HORODATAGE)) == [actifs.REJ_ETAT]


def test_un_journal_altere_refuse_tout_et_le_resolveur_se_declare_non_integre(sans_ia):
    comp, rapport = sans_ia
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    journal[1] = {**journal[1], "par": "autre"}
    assert _codes(_approuver(journal, identifiant, comp, rapport)) == [actifs.REJ_JOURNAL_ALTERE]
    assert _codes(actifs.lire(journal)) == [actifs.REJ_JOURNAL_ALTERE]
    assert actifs.resolveur_du_registre(journal).integre is False
    assert _codes(actifs.media_pour_sas(journal, identifiant)) == [actifs.REJ_JOURNAL_ALTERE]


def test_un_journal_incoherent_est_refuse(sans_ia):
    comp, _ = sans_ia
    journal: list = []
    identifiant = _composee(journal, comp)["actif_id"]
    journal_chaine.ajouter(
        journal, actifs.M_APPROUVE, {"actif_id": identifiant, "approbation": {"par": "x"}}, f.HORODATAGE
    )  # approbation sans revue : maillon impossible
    assert _codes(actifs.lire(journal)) == [actifs.REJ_JOURNAL_INCOHERENT]
    assert actifs.resolveur_du_registre(journal).integre is False


# -- résolveur et média du sas --------------------------------------------------------------------------------------
def test_le_resolveur_connait_chaque_artefact_par_son_sha256(sans_ia):
    comp, rapport = sans_ia
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    resolveur = actifs.resolveur_du_registre(journal)
    info = resolveur(comp.empreintes()["png"]["sha256"])
    assert info.actif_id == identifiant and not info.approuve and info.etat == actifs.ETAT_EN_REVUE
    assert info.format == "png" and info.largeur == comp.plan.largeur_px and info.ia_generee is False
    assert resolveur(comp.empreintes()["svg"]["sha256"]).format == "svg"
    assert resolveur("f" * 64) is None
    _approuver(journal, identifiant, comp, rapport)
    assert actifs.resolveur_du_registre(journal)(comp.empreintes()["png"]["sha256"]).approuve


def test_le_media_du_sas_vient_du_registre_et_exige_l_approbation(sans_ia, avec_ia):
    comp, rapport = sans_ia
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    assert _codes(actifs.media_pour_sas(journal, identifiant)) == [actifs.REJ_ETAT]  # en revue seulement
    _approuver(journal, identifiant, comp, rapport)
    media = actifs.media_pour_sas(journal, identifiant)["media"]
    png = comp.empreintes()["png"]
    assert media == {
        "reference": f"{identifiant}-png",
        "type_media": "image",
        "format": "png",
        "sha256": png["sha256"],
        "octets": png["octets"],
        "largeur": comp.plan.largeur_px,
        "hauteur": comp.plan.hauteur_px,
        "duree_s": None,
        "alt": "Texte alternatif",
        "origine": "composition_deterministe",
        "ia_generee": False,
        "realiste": False,
        "moderation": "verifiee",
        "controle_ocr": "conforme",
    }
    assert _codes(actifs.media_pour_sas(journal, identifiant, "pdf")) == [actifs.REJ_ETAT]
    comp_ia, rapport_ia = avec_ia
    neuf: list = []
    ident_ia = _vers_revue(neuf, comp_ia, rapport_ia)
    _approuver(
        neuf,
        ident_ia,
        comp_ia,
        rapport_ia,
        verdict_licence=lambda: {"conforme": True, "codes": []},
        attestations={**ATTESTATIONS, "realiste": True},
    )
    media_ia = actifs.media_pour_sas(neuf, ident_ia)["media"]
    assert media_ia["ia_generee"] is True and media_ia["realiste"] is True


def test_un_fond_brut_n_est_jamais_un_media(sans_ia):
    journal: list = []
    fond = actifs.enregistrer_fond(
        journal,
        sha256="a" * 64,
        format_="png",
        largeur=100,
        hauteur=80,
        genre="image",
        brief_id="brief-x",
        brief_empreinte="b" * 64,
        fond_spec_empreinte="c" * 64,
        provenance_chaine="d" * 64,
        nature_generateur="double",
        fictif=True,
        par="agent",
        horodatage=f.HORODATAGE,
    )
    assert fond["etat"] == actifs.ETAT_FOND_BRUT and fond["actif_id"] == actifs.identifiant_fond("a" * 64)
    assert (
        actifs.enregistrer_fond(
            journal,
            sha256="a" * 64,
            format_="png",
            largeur=100,
            hauteur=80,
            genre="image",
            brief_id="x",
            brief_empreinte="b" * 64,
            fond_spec_empreinte="c" * 64,
            provenance_chaine="d" * 64,
            nature_generateur="double",
            fictif=True,
            par="agent",
            horodatage=f.HORODATAGE,
        )["deja_cree"]
        is True
    )
    info = actifs.resolveur_du_registre(journal)("a" * 64)
    assert info.kind == p.KIND_FOND and not info.approuve and info.ia_generee
    assert _codes(actifs.media_pour_sas(journal, fond["actif_id"])) == [actifs.REJ_ETAT]
    assert _codes(actifs.demander_revue(journal, fond["actif_id"], "agent", f.HORODATAGE)) == [actifs.REJ_ETAT]


def test_lire_resume_et_detail(sans_ia):
    comp, rapport = sans_ia
    journal: list = []
    identifiant = _vers_revue(journal, comp, rapport)
    resume = actifs.lire(journal)
    assert resume["total"] == 1 and resume["actifs"][0]["etat"] == actifs.ETAT_EN_REVUE
    detail = actifs.lire(journal, identifiant)["actif"]
    assert (
        detail["rapport"]["empreinte"] == rapport["empreinte"] and detail["composition_empreinte"] == comp.empreinte()
    )
    assert _codes(actifs.lire(journal, "visuel-inconnu")) == [actifs.REJ_ACTIF_INCONNU]
    json.dumps(resume)  # JSON natif


# -- logos -------------------------------------------------------------------------------------------------------------
def _logo(journal):
    from m7_marketing.studio import logos

    logo = logos.logo_depuis_chemins(["M 0 0 H 60 V 100 H 0 Z", "M 70 0 H 100 V 100 H 70 Z"], 100, 100)
    svg = logos.svg_du_logo(logo)
    enregistre = actifs.enregistrer_logo(
        journal,
        sha256=logo.empreinte(),
        chemins=list(logo.chemins),
        vb_w=100,
        vb_h=100,
        svg_sha256=__import__("hashlib").sha256(svg).hexdigest(),
        source="chemins fournis",
        outil={"nom": "chemins-agent", "version": "1", "nature": "double"},
        fictif=True,
        par="agent",
        horodatage=f.HORODATAGE,
    )
    rapport = logos.rapport_controle(
        logo, svg, maintenant=f.MAINTENANT, source="chemins fournis", outil={"nom": "chemins-agent"}
    )
    return enregistre, rapport


def test_un_logo_exige_note_de_contribution_anteriorite_et_porte_l_avertissement():
    journal: list = []
    enregistre, rapport = _logo(journal)
    assert (
        enregistre["avertissement"] == actifs.AVERTISSEMENT_LOGO and "marque de commerce" in actifs.AVERTISSEMENT_LOGO
    )
    assert "avocat" in actifs.AVERTISSEMENT_LOGO
    identifiant = enregistre["actif_id"]
    assert rapport["conforme"], rapport["constats"]
    assert actifs.enregistrer_controle(journal, identifiant, rapport, "agent", f.HORODATAGE)["accepte"]
    assert actifs.demander_revue(journal, identifiant, "agent", f.HORODATAGE)["accepte"]
    comp_empreinte = actifs.plier(journal)[identifiant].donnees["composition_empreinte"]
    complet = {
        "avertissement_logo_lu": True,
        "note_contribution_humaine": "Retouche des proportions et choix de la palette par la direction.",
        "recherche_anteriorite": "renvoyee_a_un_agent_de_marques",
    }
    for mauvais in (
        {**complet, "note_contribution_humaine": "court"},
        {**complet, "recherche_anteriorite": "non"},
        {**complet, "avertissement_logo_lu": False},
        {k: v for k, v in complet.items() if k != "note_contribution_humaine"},
    ):
        resultat = actifs.approuver(
            journal, identifiant, comp_empreinte, rapport["empreinte"], NATHAN, mauvais, f.HORODATAGE
        )
        assert not resultat["accepte"]
    ok = actifs.approuver(journal, identifiant, comp_empreinte, rapport["empreinte"], NATHAN, complet, f.HORODATAGE)
    assert ok["accepte"] and ok["attestations"]["recherche_anteriorite"] == "renvoyee_a_un_agent_de_marques"
