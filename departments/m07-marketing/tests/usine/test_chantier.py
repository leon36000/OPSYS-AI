"""D'un chantier terminé à cinq contenus (PLAN T4.17) : refus de départ, matière, lien de suivi, préparation.

Module pur : les registres sont des listes. La base, le bus et les outils sont testés dans `test_service_usine.py`
et dans `tests/e2e/test_usine_contenu_appareil.py`.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from m7_marketing.usine import chantier, mesure, plateformes, registre, verdicts
from m7_marketing.usine.chantier import Nature
from m7_marketing.usine.controle_texte import controler_texte
from m7_marketing.utm import utm_engine

FICTIF = True


def _preparer(charge, profil, nature, textes=None, propositions=(), decisions=()):
    return chantier.preparer(charge, profil, nature, textes, propositions, decisions, "test")


# -- refus de départ ---------------------------------------------------------------------------------------------
def test_un_chantier_consenti_prouve_et_sans_retrait_peut_donner_du_contenu(fabriquer_charge):
    assert chantier.verifier_chantier(fabriquer_charge(), []) == (None, None)


def test_client_satisfait_absent_ou_non_recueilli_ne_refuse_pas(fabriquer_charge):
    charge = fabriquer_charge()
    del charge["client_satisfait"]
    assert chantier.verifier_chantier(charge, []) == (None, None)
    assert chantier.verifier_chantier(fabriquer_charge(client_satisfait=None), []) == (None, None)


@pytest.mark.parametrize(("surcharges", "extrait"), [
    ({"consentement_marketing": False}, "consentement_marketing = false"),
    ({"client_satisfait": False}, "insatisfait"),
])
def test_refus_de_depart_nomme_son_motif(surcharges, extrait, fabriquer_charge):
    statut, motif = chantier.verifier_chantier(fabriquer_charge(**surcharges), [])
    assert statut == chantier.STATUT_REFUSE and extrait in motif


def test_consentement_absent_refuse(fabriquer_charge):
    charge = fabriquer_charge()
    del charge["consentement_marketing"]
    statut, motif = chantier.verifier_chantier(charge, [])
    assert statut == chantier.STATUT_REFUSE and "absent" in motif


@pytest.mark.parametrize("cle", [
    "consentement_recueilli_par", "consentement_recueilli_le", "consentement_version_texte",
])
def test_consentement_vrai_sans_sa_preuve_refuse(cle, fabriquer_charge):
    charge = fabriquer_charge()
    del charge[cle]
    statut, motif = chantier.verifier_chantier(charge, [])
    assert statut == chantier.STATUT_REFUSE and "preuve" in motif


def test_wct_id_absent_refuse(fabriquer_charge):
    statut, motif = chantier.verifier_chantier(fabriquer_charge(wct_id=""), [])
    assert statut == chantier.STATUT_REFUSE and "wct_id" in motif


def test_le_retrait_passe_avant_tout_autre_motif(fabriquer_charge):
    retraits = [{"retrait_id": "r-1", "wct_id": "wct-usine-1", "lead_id": None, "canal": "telephone"}]
    statut, motif = chantier.verifier_chantier(fabriquer_charge(consentement_marketing=False), retraits)
    assert statut == chantier.STATUT_CONSENTEMENT_RETIRE
    assert "r-1" in motif and "telephone" in motif


def test_le_retrait_d_un_autre_chantier_du_meme_lead_bloque_aussi(fabriquer_charge):
    retraits = [{"retrait_id": "r-1", "wct_id": "wct-ancien", "lead_id": "lead-usine-1", "canal": "sms"}]
    statut, _ = chantier.verifier_chantier(fabriquer_charge(wct_id="wct-nouveau"), retraits)
    assert statut == chantier.STATUT_CONSENTEMENT_RETIRE
    statut, _ = chantier.verifier_chantier(fabriquer_charge(wct_id="wct-nouveau", lead_id="lead-autre"), retraits)
    assert statut is None


# -- mots-clics, matière, contexte ------------------------------------------------------------------------------------
def test_mots_clics_tires_des_faits_sans_accents_dedoublonnes(nature, profil):
    profil["hashtags"] = ["#renovationexterieure", "Gouttière", "à", 3, "#gouttiere"]
    mots = chantier.mots_clics(nature, "Saint-Jérôme", profil)
    assert mots == ("#gouttiere", "#descentepluviale", "#descentedegouttiere", "#saintjerome", "#renovationexterieure")


def test_mots_clics_plafonnes_et_sans_ville_inventee(nature, profil):
    profil["hashtags"] = [f"mot{numero}abc" for numero in range(20)]
    assert len(chantier.mots_clics(nature, None, profil)) == chantier.MOTS_CLICS_MAX
    assert "#repentigny" not in chantier.mots_clics(nature, None, profil)


def test_la_matiere_dit_ce_qui_manque_et_n_invente_rien(profil, nature, fabriquer_charge):
    charge = fabriquer_charge()
    del charge["ville"]
    profil["tagline"] = "À CONFIGURER — accroche du client"
    matiere, avertissements = chantier.matiere_du_chantier(charge, profil, nature)
    assert matiere.ville is None and matiere.accroche == ""
    assert any("ville absente" in a for a in avertissements)
    assert any("accroche" in a for a in avertissements)


def test_un_chantier_en_revue_est_signale_pas_bloque(profil, nature, fabriquer_charge):
    _, avertissements = chantier.matiere_du_chantier(fabriquer_charge(ecart_signale=True), profil, nature)
    assert any("écart" in a for a in avertissements)


def test_le_contexte_de_controle_porte_marque_garanties_et_identifiants_du_chantier(profil, fabriquer_charge):
    profil["garanties_validees"] = ["Garantie limitée de la main-d'œuvre", "", 3]
    contexte = chantier.contexte_controle(fabriquer_charge(), profil, 1500)
    assert contexte.noms_de_marque == (profil["name"],)
    assert contexte.garanties_validees == ("Garantie limitée de la main-d'œuvre",)
    assert {"wct-usine-1", "int-usine-1", "lead-usine-1", "etienne", "devis-usine-1"} <= set(contexte.identifiants)
    assert contexte.longueur_max == 1500


def test_la_note_du_chantier_n_est_montree_que_si_elle_passe_le_controle(profil, fabriquer_charge):
    note, motif = chantier.description_utilisable(fabriquer_charge(), profil)
    assert (note, motif) == ("Installation terminée, sans imprévu.", None)
    for fautive in ("Chez Mme Tremblay, 12 rue des Lilas", "Facturé 4 500 $", "x" * 700):
        note, motif = chantier.description_utilisable(fabriquer_charge(description_factuelle=fautive), profil)
        assert note is None and motif
    sans_note = fabriquer_charge()
    del sans_note["description_factuelle"]
    assert chantier.description_utilisable(sans_note, profil) == (None, None)


# -- lien de suivi ---------------------------------------------------------------------------------------------------
CLE = "facebook-0123456789abcdef"


def test_le_lien_de_suivi_est_conforme_et_propre_a_chaque_variante(profil, nature, fabriquer_charge):
    charge = fabriquer_charge()
    liens = {}
    for plateforme in plateformes.PLATEFORMES:
        cle = mesure.utm_content_de(f"contenu-{plateforme.code}", plateforme.code)
        lien, utm, avertissement = chantier.lien_utm(plateforme, charge, profil, nature, cle)
        assert avertissement is None
        if plateforme.source_utm is None:
            assert (lien, utm) == (None, None)
            continue
        liens[plateforme.code] = lien
        assert [v for _, v, _ in utm_engine.valider_lien_utm(lien) if v == "fail"] == []
        requete = parse_qs(urlsplit(lien).query)
        assert requete["utm_source"] == [plateforme.source_utm] and requete["utm_medium"] == [plateforme.medium_utm]
        assert requete["utm_campaign"] == ["contenu-gouttieres-et-descentes-2026"]
        assert requete["utm_content"] == [cle] and utm["content"] == cle  # la clé du CONTENU, telle quelle
        assert urlsplit(lien).netloc == "exemple-fictif.ca"
    assert len(set(liens.values())) == 4  # un lien par variante


def test_chaque_proposition_porte_sa_cle_de_mesure_tiree_de_son_identifiant_et_son_lien_la_porte(
        charge, profil, nature):
    for proposition in _preparer(charge, profil, nature).nouvelles:
        cle = mesure.utm_content_de(proposition["contenu_id"], proposition["plateforme"])
        assert proposition["utm_content"] == cle
        assert cle.startswith(f"{proposition['plateforme']}-")
        if proposition["plateforme"] == "demande_temoignage":  # message privé : une clé, mais aucun lien pour la porter
            assert proposition["lien_utm"] is None and proposition["utm"] is None
            continue
        assert proposition["utm"]["content"] == cle
        assert parse_qs(urlsplit(proposition["lien_utm"]).query)["utm_content"] == [cle]


def test_les_cles_de_mesure_des_cinq_contenus_d_un_chantier_sont_toutes_differentes(charge, profil, nature):
    cles = [p["utm_content"] for p in _preparer(charge, profil, nature).nouvelles]
    assert len(cles) == 5 and len(set(cles)) == 5


def test_une_revision_a_sa_propre_cle_et_la_meme_proposition_rejouee_garde_la_sienne(charge, profil, nature):
    premiere = _preparer(charge, profil, nature)
    facebook = next(p for p in premiere.nouvelles if p["plateforme"] == "facebook")
    rejet = {"contenu_id": facebook["contenu_id"], "decision": registre.STATUT_REJETE}
    seconde = _preparer(
        charge, profil, nature, {"facebook": "Nouvelle publication sans rien de personnel."}, [facebook], [rejet],
    )
    revision = next(p for p in seconde.nouvelles if p["plateforme"] == "facebook")
    assert revision["revision"] == 2 and revision["contenu_id"] != facebook["contenu_id"]
    assert revision["utm_content"] != facebook["utm_content"]  # une autre révision, une autre clé
    rejouee = next(p for p in _preparer(charge, profil, nature).nouvelles if p["plateforme"] == "facebook")
    assert rejouee["utm_content"] == facebook["utm_content"]  # déterministe : même chantier, même clé


def test_le_lien_ne_laisse_pas_fuir_l_identifiant_du_chantier(profil, nature, fabriquer_charge):
    charge = fabriquer_charge(wct_id="wct-secret-abcdef", lead_id="lead-secret-abcdef")
    facebook = next(p for p in _preparer(charge, profil, nature).nouvelles if p["plateforme"] == "facebook")
    for lu in (facebook["lien_utm"], facebook["utm_content"], str(facebook["utm"])):
        assert "secret" not in lu and "wct-" not in lu and "lead-" not in lu and "abcdef" not in lu


def test_sans_site_url_pas_de_lien_mais_la_cle_de_mesure_existe_quand_meme(profil, nature, fabriquer_charge):
    del profil["site_url"]
    plateforme_facebook = plateformes.plateforme("facebook")
    lien, utm, avertissement = chantier.lien_utm(plateforme_facebook, fabriquer_charge(), profil, nature, CLE)
    assert (lien, utm) == (None, None) and "site_url" in avertissement
    facebook = next(p for p in _preparer(fabriquer_charge(), profil, nature).nouvelles if p["plateforme"] == "facebook")
    assert facebook["lien_utm"] is None and facebook["utm"] is None
    assert facebook["utm_content"].startswith("facebook-")  # le contenu a sa clé ; aucun lien ne la porte


def test_un_site_non_https_donne_un_lien_non_conforme_donc_aucun_lien(profil, nature, fabriquer_charge):
    profil["site_url"] = "http://exemple-fictif.ca/"
    facebook = plateformes.plateforme("facebook")
    lien, utm, avertissement = chantier.lien_utm(facebook, fabriquer_charge(), profil, nature, CLE)
    assert (lien, utm) == (None, None) and "U-01" in avertissement


def test_une_annee_illisible_donne_aucun_lien(profil, nature, fabriquer_charge):
    charge = fabriquer_charge(horodatage_completion="hier soir")
    lien, _, avertissement = chantier.lien_utm(plateformes.plateforme("facebook"), charge, profil, nature, CLE)
    assert lien is None and "année" in avertissement


def test_une_cle_hors_contrat_donne_aucun_lien_jamais_un_lien_que_le_contrat_refuse(profil, nature, fabriquer_charge):
    lien, utm, avertissement = chantier.lien_utm(
        plateformes.plateforme("facebook"), fabriquer_charge(), profil, nature, "Facebook Chez Mme Tremblay",
    )
    assert (lien, utm) == (None, None) and "U-07" in avertissement


# -- préparation ----------------------------------------------------------------------------------------------
def test_cinq_contenus_dans_l_ordre_tous_proposes_jamais_approuves(charge, profil, nature):
    preparation = _preparer(charge, profil, nature)
    assert preparation.statut == chantier.STATUT_PROPOSE
    assert [p["plateforme"] for p in preparation.nouvelles] == list(plateformes.CODES_PLATEFORMES)
    assert [item["statut"] for item in preparation.items] == ["propose"] * 5
    for proposition in preparation.nouvelles:
        assert proposition["approval_status"] == "PROPOSE" and proposition["revision"] == 1
        assert proposition["origine_texte"] == "gabarit" and proposition["origine"] == "test"
        assert proposition["empreinte_texte"] == hashlib.sha256(proposition["texte"].encode()).hexdigest()
        assert proposition["propose_le"] == "2026-09-28T14:00:00-04:00"  # le fait du WCT, jamais une horloge
        assert proposition["preuve_consentement"] == {
            "consentement_marketing": True, "recueilli_par": "etienne", "recueilli_le": "2026-09-28T18:05:00+00:00",
            "version_texte": "consentement-client-fr-CA-v1", "source": "wct_m4_travaux_termines",
            "wct_id": "wct-usine-1",
        }
    ids = [p["contenu_id"] for p in preparation.nouvelles]
    assert len(set(ids)) == 5 and all(re.fullmatch(r"[0-9a-f-]{36}", i) for i in ids)


def test_tout_texte_du_gabarit_passe_le_controle_et_les_mots_clics_sont_publics_seulement(charge, profil, nature):
    for proposition in _preparer(charge, profil, nature).nouvelles:
        plafond = plateformes.plateforme(proposition["plateforme"]).longueur_max
        contexte = chantier.contexte_controle(charge, profil, plafond)
        assert controler_texte(proposition["texte"], contexte) == ()
        public = plateformes.plateforme(proposition["plateforme"]).public
        assert bool(proposition["mots_clics"]) == public


def test_les_photos_du_wct_sont_des_references_et_leur_absence_est_signalee(charge, profil, nature, fabriquer_charge):
    avec = {p["plateforme"]: p for p in _preparer(charge, profil, nature).nouvelles}
    assert avec["instagram"]["photos"] == ["photo-apres-1", "photo-apres-2"]
    assert not any("photo" in a for a in avec["instagram"]["avertissements"])
    sans_photo = fabriquer_charge()
    del sans_photo["photos"]
    sans = {p["plateforme"]: p for p in _preparer(sans_photo, profil, nature).nouvelles}
    assert any("exige un média" in a for a in sans["instagram"]["avertissements"])
    assert any("aucune photo" in a for a in sans["facebook"]["avertissements"])
    assert sans["demande_temoignage"]["avertissements"] == [
        a for a in sans["demande_temoignage"]["avertissements"] if "photo" not in a
    ]


def test_relancer_ne_cree_jamais_un_doublon(charge, profil, nature):
    premiere = _preparer(charge, profil, nature)
    seconde = _preparer(charge, profil, nature, propositions=premiere.nouvelles)
    assert seconde.nouvelles == () and seconde.statut == chantier.STATUT_DEJA_PROPOSE
    assert {item["statut"] for item in seconde.items} == {"deja_propose"}
    assert {item["approval_status"] for item in seconde.items} == {"PROPOSE"}


def test_un_texte_du_modele_passe_le_meme_controle_et_un_prix_est_refuse_en_nommant_la_regle(charge, profil, nature):
    preparation = _preparer(charge, profil, nature, textes={
        "facebook": "Chantier terminé : gouttières installées à partir de 4 500 $.",
        "instagram": "Un beau projet de gouttières terminé par notre équipe.",
    })
    assert preparation.statut == chantier.STATUT_PARTIEL
    par_plateforme = {item["plateforme"]: item for item in preparation.items}
    assert par_plateforme["facebook"]["statut"] == "refuse"
    assert [r["regle"] for r in par_plateforme["facebook"]["regles"]] == ["REJ-PRIX"]
    assert par_plateforme["facebook"]["origine_texte"] == "modele"
    instagram = par_plateforme["instagram"]
    assert (instagram["statut"], instagram["origine_texte"]) == ("propose", "modele")
    assert {p["plateforme"] for p in preparation.nouvelles} == {
        "instagram", "fiche_google", "video_courte", "demande_temoignage",
    }
    assert not any("4 500" in p["texte"] for p in preparation.nouvelles)  # le texte refusé n'existe nulle part


def test_toutes_les_plateformes_refusees_donne_textes_refuses_sans_rien_ecrire(charge, profil, nature):
    textes = {code: "Meilleur prix garanti demain" for code in plateformes.CODES_PLATEFORMES}
    preparation = _preparer(charge, profil, nature, textes=textes)
    assert preparation.statut == chantier.STATUT_TEXTES_REFUSES and preparation.nouvelles == ()
    regles = {r["regle"] for item in preparation.items for r in item["regles"]}
    assert {"REJ-PRIX", "REJ-GARANTIE-NON-VALIDEE", "REJ-PROMESSE-DE-DATE", "REJ-EXAGERATION"} <= regles


def test_le_gabarit_est_controle_lui_aussi_une_accroche_fautive_du_profil_le_refuse(charge, profil, nature):
    """Le code n'a pas de traitement de faveur : une accroche de marque qui promet un prix bloque les variantes
    qui la portent, en nommant la règle ; celles qui ne la portent pas (vidéo, témoignage) passent."""
    profil["tagline"] = "Gouttières dès 8 $ le pied"
    preparation = _preparer(charge, profil, nature)
    statuts = {item["plateforme"]: item["statut"] for item in preparation.items}
    assert statuts == {
        "facebook": "refuse", "instagram": "refuse", "fiche_google": "refuse",
        "video_courte": "propose", "demande_temoignage": "propose",
    }
    assert preparation.statut == chantier.STATUT_PARTIEL


def test_une_garantie_validee_du_profil_autorise_la_meme_accroche(charge, profil, nature):
    """Sans validation, une accroche de marque qui garantit quelque chose est refusée ; l'énoncé que le profil valide
    (mot pour mot) passe : c'est l'entreprise qui valide une garantie, jamais le texte qui la prétend."""
    profil["tagline"] = "Garantie limitée de la main-d'œuvre"
    refusee = _preparer(charge, profil, nature)
    assert refusee.statut == chantier.STATUT_PARTIEL
    assert {i["plateforme"]: i["statut"] for i in refusee.items}["facebook"] == "refuse"
    profil["garanties_validees"] = ["Garantie limitée de la main-d'œuvre"]
    assert _preparer(charge, profil, nature).statut == chantier.STATUT_PROPOSE


def test_apres_un_rejet_un_nouveau_texte_cree_une_revision_et_sans_texte_rien(charge, profil, nature):
    premiere = _preparer(charge, profil, nature)
    facebook = premiere.nouvelles[0]
    rejet = {"contenu_id": facebook["contenu_id"], "decision": registre.STATUT_REJETE, "par": "nathan",
             "role": "nathan_owner", "source": "appareil", "motif": "trop vendeur",
             "horodatage": "2026-09-29T10:00:00-04:00"}
    propositions = list(premiere.nouvelles)

    sans_texte = _preparer(charge, profil, nature, propositions=propositions, decisions=[rejet])
    par_plateforme = {item["plateforme"]: item for item in sans_texte.items}
    assert par_plateforme["facebook"]["statut"] == "texte_requis" and sans_texte.nouvelles == ()
    assert sans_texte.statut == chantier.STATUT_PARTIEL  # les quatre autres sont toujours là

    avec_texte = _preparer(charge, profil, nature, textes={"facebook": "Un projet de gouttières terminé, soigné."},
                           propositions=propositions, decisions=[rejet])
    (revision,) = avec_texte.nouvelles
    assert revision["plateforme"] == "facebook" and revision["revision"] == 2
    assert revision["contenu_id"] != facebook["contenu_id"] and revision["origine_texte"] == "modele"
    assert registre.est_derniere_revision(revision, [*propositions, revision])


def test_un_contenu_deja_propose_ignore_un_nouveau_texte_au_lieu_de_l_ecraser(charge, profil, nature):
    premiere = _preparer(charge, profil, nature)
    seconde = _preparer(charge, profil, nature, textes={"facebook": "Un autre texte de gouttières."},
                        propositions=premiere.nouvelles)
    assert seconde.nouvelles == () and {i["statut"] for i in seconde.items} == {"deja_propose"}


def test_un_verdict_de_texte_non_conforme_nomme_les_regles():
    verdict = chantier.verdict_texte_non_conforme(["REJ-PRIX", "REJ-DATE"])
    assert verdict["code"] == verdicts.REJ_TEXTE_NON_CONFORME and "REJ-PRIX, REJ-DATE" in verdict["detail"]


def test_la_nature_est_un_objet_simple():
    assert Nature("Gouttières", ("gouttière",)).mots_cles == ("gouttière",)
