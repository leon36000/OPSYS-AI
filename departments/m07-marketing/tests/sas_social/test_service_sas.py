"""Les gestes du sas : composer, réviser, soumettre, approuver, annuler, lire — sur un journal append-only.

Cas négatifs et d'abus : double soumission, même clé avec un autre contenu, approbation d'une autre empreinte,
approbation
par un non-humain ou un non-propriétaire, N3 sur une annonce payante, journal retouché, publication après annulation.
"""

from __future__ import annotations

import copy

import pytest
from fabriques_sociales import CLE, COMPTE, HORODATAGE, MAINTENANT, annonce, media_photo, publication
from m7_marketing import journal_chaine
from m7_marketing.sas_social import etats, modele, service

FICTIF = True


def composer(journal, comptes_actifs, donnees=None, cle=CLE, **plus):
    return service.composer(
        journal, donnees or publication("facebook"), cle, comptes_actifs, "agent", HORODATAGE, **plus
    )


def soumettre(journal, declarations, politique_sas, publication_id):
    return service.soumettre(journal, publication_id, declarations, politique_sas, MAINTENANT, HORODATAGE)


def approuver(
    journal, declarations, politique_sas, proprietaire, publication_id, empreinte, niveau=3, approbateur="defaut"
):
    return service.approuver(
        journal,
        publication_id,
        empreinte,
        niveau,
        proprietaire if approbateur == "defaut" else approbateur,
        declarations,
        politique_sas,
        MAINTENANT,
        HORODATAGE,
    )


@pytest.fixture
def soumise(journal, comptes_actifs, declarations, politique_sas):
    cree = composer(journal, comptes_actifs)
    ok = soumettre(journal, declarations, politique_sas, cree["publication_id"])
    assert ok["accepte"], ok
    return cree["publication_id"], cree["empreinte"]


# -- composer et l'idempotence
# --------------------------------------------------------------------------------------------
def test_composer_cree_un_brouillon_et_marque_l_ia(journal, comptes_actifs):
    resultat = composer(journal, comptes_actifs)
    assert resultat["accepte"] and resultat["etat"] == "brouillon" and resultat["deja_cree"] is False
    maillon = journal[0]
    assert maillon["type"] == "brouillon_cree" and maillon["ia"] == {"texte": True, "media": False}
    assert maillon["publication"]["divulgation"]["texte_ia"] is True


def test_la_meme_cle_et_le_meme_contenu_font_une_seule_publication(journal, comptes_actifs):
    premiere = composer(journal, comptes_actifs)
    seconde = composer(journal, comptes_actifs)
    assert seconde["publication_id"] == premiere["publication_id"] and seconde["deja_cree"] is True
    assert len(journal) == 1, "rien d'écrit au rejeu"


def test_la_meme_cle_avec_un_autre_contenu_est_refusee_sans_ecrire(journal, comptes_actifs):
    composer(journal, comptes_actifs)
    autre = publication("facebook", texte="Un tout autre message, sobre et sans promesse.")
    refus = composer(journal, comptes_actifs, autre)
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-CLE-CONFLIT" and len(journal) == 1


def test_la_meme_cle_sur_un_autre_compte_ou_reseau_est_une_autre_publication(journal, comptes_actifs):
    a = composer(journal, comptes_actifs)
    b = composer(journal, comptes_actifs, publication("instagram"))
    assert a["publication_id"] != b["publication_id"]


@pytest.mark.parametrize("cle", ["", "courte", "a b" * 8, "x" * 65, None, 12345, "cle\n0123456789abcdef"])
def test_une_cle_d_idempotence_invalide_est_refusee(journal, comptes_actifs, cle):
    assert composer(journal, comptes_actifs, cle=cle)["refus"][0]["code"] == "REJ-SOCIAL-CLE-INVALIDE"
    assert journal == []


def test_un_compte_non_declare_est_refuse(journal):
    refus = service.composer(journal, publication("facebook"), CLE, set(), "agent", HORODATAGE)
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-COMPTE-INCONNU" and journal == []


def test_une_publication_mal_formee_est_refusee_avant_toute_ecriture(journal, comptes_actifs):
    resultat = composer(journal, comptes_actifs, {**publication("facebook"), "medias": "x"})
    assert resultat["accepte"] is False and journal == []


def test_reviser_un_brouillon_cree_une_revision_et_change_l_empreinte(journal, comptes_actifs):
    cree = composer(journal, comptes_actifs)
    revise = composer(
        journal,
        comptes_actifs,
        publication("facebook", texte="Texte révisé, toujours sobre."),
        publication_id=cree["publication_id"],
    )
    assert revise["accepte"] and revise["revision"] == 2 and revise["empreinte"] != cree["empreinte"]
    rejeu = composer(
        journal,
        comptes_actifs,
        publication("facebook", texte="Texte révisé, toujours sobre."),
        publication_id=cree["publication_id"],
    )
    assert rejeu["deja_cree"] is True and len(journal) == 2


def test_on_ne_change_ni_le_reseau_ni_le_compte_d_une_publication(journal, comptes_actifs):
    cree = composer(journal, comptes_actifs)
    refus = composer(journal, comptes_actifs, publication("instagram"), publication_id=cree["publication_id"])
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-IDENTITE-IMMUABLE"
    inconnue = composer(journal, comptes_actifs, publication_id="pub-inconnue")
    assert inconnue["refus"][0]["code"] == "REJ-SOCIAL-PUBLICATION-INCONNUE"


# -- soumettre
# -----------------------------------------------------------------------------------------------------------
def test_soumettre_passe_en_attente_et_ecrit_les_limites_appliquees(
    journal, comptes_actifs, declarations, politique_sas
):
    cree = composer(journal, comptes_actifs)
    resultat = soumettre(journal, declarations, politique_sas, cree["publication_id"])
    assert resultat["etat"] == "en_attente_approbation" and resultat["niveau_requis"] == "N3"
    assert journal[-1]["limites"]["reseau"] == "facebook" and journal[-1]["limites"]["a_verifier"] is True


def test_un_refus_de_soumission_n_ecrit_rien_et_nomme_les_regles(journal, comptes_actifs, declarations, politique_sas):
    cree = composer(journal, comptes_actifs, publication("facebook", texte="Le meilleur toit, rabais de 50 %."))
    avant = copy.deepcopy(journal)
    refus = soumettre(journal, declarations, politique_sas, cree["publication_id"])
    assert refus["accepte"] is False and {"REJ-EXAGERATION", "REJ-PRIX"} <= {r["code"] for r in refus["refus"]}
    assert journal == avant


def test_la_double_soumission_est_refusee(soumise, journal, declarations, politique_sas):
    publication_id, _ = soumise
    n = len(journal)
    refus = soumettre(journal, declarations, politique_sas, publication_id)
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-ETAT" and len(journal) == n


def test_une_annonce_soumise_exige_n4(journal, comptes_actifs, declarations, politique_sas):
    cree = composer(journal, comptes_actifs, annonce("facebook"))
    assert soumettre(journal, declarations, politique_sas, cree["publication_id"])["niveau_requis"] == "N4"


# -- approuver
# -----------------------------------------------------------------------------------------------------------
def test_l_approbation_ecrit_approuvee_puis_planifiee_et_n_execute_rien(
    soumise, journal, declarations, politique_sas, proprietaire
):
    publication_id, empreinte = soumise
    resultat = approuver(journal, declarations, politique_sas, proprietaire, publication_id, empreinte)
    assert resultat["accepte"] and resultat["etat"] == "planifie" and resultat["execute"] is False
    assert [m["type"] for m in journal][-2:] == ["approuvee", "planifiee"]
    assert journal[-2]["approbation"] == {"par": "nathan", "role": "nathan_owner", "source": "approbation"}
    assert journal[-2]["empreinte"] == empreinte and journal[-2]["niveau"] == 3
    assert not any(m["type"] in ("tentative", "publiee") for m in journal)


@pytest.mark.parametrize(
    "approbateur",
    [
        None,
        {},
        {"par": "agent", "role": "system_agent", "source": "approbation"},
        {"par": "gestion", "role": "admin", "source": "appareil"},
        {"par": "", "role": "nathan_owner", "source": "approbation"},
        {"par": "nathan", "role": "nathan_owner", "source": ""},
        {"par": "nathan", "role": "client", "source": "approbation"},
    ],
)
def test_seul_le_proprietaire_humain_approuve(soumise, journal, declarations, politique_sas, approbateur):
    publication_id, empreinte = soumise
    n = len(journal)
    refus = approuver(journal, declarations, politique_sas, None, publication_id, empreinte, approbateur=approbateur)
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-HUMAIN-REQUIS" and len(journal) == n


def test_une_autre_empreinte_que_celle_soumise_est_refusee(soumise, journal, declarations, politique_sas, proprietaire):
    publication_id, empreinte = soumise
    n = len(journal)
    for fausse in ("0" * 64, empreinte[:-1] + ("0" if empreinte[-1] != "0" else "1"), "", empreinte.upper()):
        refus = approuver(journal, declarations, politique_sas, proprietaire, publication_id, fausse)
        assert refus["refus"][0]["code"] == "REJ-SOCIAL-EMPREINTE-DIFFERENTE", fausse
    assert len(journal) == n


def test_un_contenu_revise_apres_la_soumission_annule_la_demande(
    soumise, journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    publication_id, empreinte = soumise
    revise = composer(
        journal,
        comptes_actifs,
        publication("facebook", texte="Autre texte, tout aussi sobre."),
        publication_id=publication_id,
    )
    assert revise["etat"] == "brouillon"
    refus = approuver(journal, declarations, politique_sas, proprietaire, publication_id, empreinte)
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-ETAT"
    refus = approuver(journal, declarations, politique_sas, proprietaire, publication_id, revise["empreinte"])
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-ETAT", (
        "il faut resoumettre : l'approbation ne vaut que pour une demande en attente"
    )


def test_apres_la_revision_la_resoumission_puis_l_approbation_de_la_nouvelle_empreinte(
    soumise,
    journal,
    comptes_actifs,
    declarations,
    politique_sas,
    proprietaire,
):
    publication_id, _ = soumise
    revise = composer(
        journal,
        comptes_actifs,
        publication("facebook", texte="Autre texte, tout aussi sobre."),
        publication_id=publication_id,
    )
    assert soumettre(journal, declarations, politique_sas, publication_id)["accepte"]
    assert approuver(journal, declarations, politique_sas, proprietaire, publication_id, revise["empreinte"])["accepte"]


def test_n3_ne_peut_pas_approuver_une_annonce_payante_et_n4_ne_peut_pas_approuver_l_organique(
    journal,
    comptes_actifs,
    declarations,
    politique_sas,
    proprietaire,
):
    payante = composer(journal, comptes_actifs, annonce("facebook"), cle="cle-annonce-0123456789ab")
    organique = composer(journal, comptes_actifs, publication("facebook"), cle="cle-organique-0123456789")
    for resultat in (payante, organique):
        assert soumettre(journal, declarations, politique_sas, resultat["publication_id"])["accepte"]
    n = len(journal)
    refus = approuver(
        journal, declarations, politique_sas, proprietaire, payante["publication_id"], payante["empreinte"], niveau=3
    )
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-NIVEAU-INSUFFISANT"
    refus = approuver(
        journal,
        declarations,
        politique_sas,
        proprietaire,
        organique["publication_id"],
        organique["empreinte"],
        niveau=4,
    )
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-NIVEAU-INSUFFISANT"
    assert len(journal) == n
    assert approuver(
        journal, declarations, politique_sas, proprietaire, payante["publication_id"], payante["empreinte"], niveau=4
    )["accepte"]
    assert approuver(
        journal,
        declarations,
        politique_sas,
        proprietaire,
        organique["publication_id"],
        organique["empreinte"],
        niveau=3,
    )["accepte"]


def test_l_approbation_reverifie_les_controles_au_moment_present(
    soumise, journal, declarations, politique_sas, proprietaire
):
    """Entre la soumission et l'approbation, l'heure approuvée peut être devenue trop proche : refus, rien d'écrit."""
    from datetime import UTC, datetime

    publication_id, empreinte = soumise
    tard = datetime(2026, 1, 6, 14, 58, tzinfo=UTC)  # 2 minutes avant l'heure prévue (15 h) : sous le délai minimal
    n = len(journal)
    refus = service.approuver(
        journal, publication_id, empreinte, 3, proprietaire, declarations, politique_sas, tard, HORODATAGE
    )
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-PLANIFICATION-TROP-PROCHE" and len(journal) == n


def test_le_quota_est_reverifie_a_l_approbation_en_tenant_compte_des_autres_publications(
    journal,
    comptes_actifs,
    declarations,
    politique_sas,
    proprietaire,
):
    # GBP : 3 publications par 24 h. On en planifie trois à 10 h, 10 h 30, 11 h ; la quatrième est refusée dès la
    # soumission.
    for i, heure in enumerate(("15:00:00", "15:30:00", "16:00:00")):
        cree = composer(
            journal,
            comptes_actifs,
            publication("gbp", planifie_le=f"2026-01-06T{heure}Z"),
            cle=f"cle-gbp-numero-{i:02d}-0123456789",
        )
        assert soumettre(journal, declarations, politique_sas, cree["publication_id"])["accepte"]
        assert approuver(journal, declarations, politique_sas, proprietaire, cree["publication_id"], cree["empreinte"])[
            "accepte"
        ]
    quatrieme = composer(
        journal, comptes_actifs, publication("gbp", planifie_le="2026-01-06T17:00:00Z"), cle="cle-gbp-quatre-0123456789"
    )
    refus = soumettre(journal, declarations, politique_sas, quatrieme["publication_id"])
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-QUOTA-24H"
    # une publication ANNULÉE libère sa place
    premiere = next(m for m in journal if m["type"] == "brouillon_cree")["publication_id"]
    assert service.annuler(journal, premiere, "agent", "libérer", HORODATAGE)["accepte"]
    assert soumettre(journal, declarations, politique_sas, quatrieme["publication_id"])["accepte"]


def test_deux_comptes_ont_chacun_leur_quota(journal, declarations, politique_sas, proprietaire):
    deux = {("gbp", "fiche-a"), ("gbp", "fiche-b")}
    for compte in ("fiche-a", "fiche-b"):
        for i in range(3):
            cree = service.composer(
                journal,
                publication("gbp", compte=compte, planifie_le=f"2026-01-06T1{5 + i}:00:00Z"),
                f"cle-{compte}-numero-{i}-0123456",
                deux,
                "agent",
                HORODATAGE,
            )
            assert service.soumettre(
                journal, cree["publication_id"], declarations, politique_sas, MAINTENANT, HORODATAGE
            )["accepte"]
            assert service.approuver(
                journal,
                cree["publication_id"],
                cree["empreinte"],
                3,
                proprietaire,
                declarations,
                politique_sas,
                MAINTENANT,
                HORODATAGE,
            )["accepte"]


# -- annuler
# ----------------------------------------------------------------------------------------------------------------
def test_annuler_retire_de_la_file_et_une_annulee_ne_ressort_pas(
    soumise, journal, declarations, politique_sas, proprietaire
):
    publication_id, empreinte = soumise
    assert service.annuler(journal, publication_id, "agent", "plus d'actualité", HORODATAGE)["etat"] == "annule"
    for geste in (
        lambda: approuver(journal, declarations, politique_sas, proprietaire, publication_id, empreinte),
        lambda: soumettre(journal, declarations, politique_sas, publication_id),
        lambda: service.annuler(journal, publication_id, "agent", "encore", HORODATAGE),
    ):
        assert geste()["refus"][0]["code"] == "REJ-SOCIAL-ETAT"
    assert etats.plier(journal)[publication_id].etat == "annule"


def test_une_publication_deja_publiee_ne_s_annule_pas_d_ici(
    soumise, journal, declarations, politique_sas, proprietaire
):
    publication_id, empreinte = soumise
    approuver(journal, declarations, politique_sas, proprietaire, publication_id, empreinte)
    journal_chaine.ajouter(
        journal, "tentative", {"publication_id": publication_id, "tentative": 1, "cle_idempotence": CLE}, HORODATAGE
    )
    journal_chaine.ajouter(
        journal,
        "publiee",
        {
            "publication_id": publication_id,
            "id_externe": "x",
            "url": None,
            "publie_le": HORODATAGE,
            "publie_le_externe": HORODATAGE,
            "tentative": 1,
            "retrouvee": False,
        },
        HORODATAGE,
    )
    assert (
        service.annuler(journal, publication_id, "agent", "trop tard", HORODATAGE)["refus"][0]["code"]
        == "REJ-SOCIAL-DEJA-PUBLIE"
    )


def test_annuler_une_publication_inconnue_est_refuse(journal):
    assert (
        service.annuler(journal, "pub-inconnue", "agent", "x", HORODATAGE)["refus"][0]["code"]
        == "REJ-SOCIAL-PUBLICATION-INCONNUE"
    )


# -- lire
# -------------------------------------------------------------------------------------------------------------------
def test_lire_rend_la_file_en_bref_et_le_detail_d_une_publication(soumise, journal):
    publication_id, empreinte = soumise
    file = service.lire(journal)
    assert file["total"] == 1 and file["publications"][0]["etat"] == "en_attente_approbation"
    assert "texte" not in file["publications"][0], "la file se lit en bref"
    detail = service.lire(journal, publication_id)
    assert detail["publication"]["contenu"]["texte"] and detail["publication"]["empreinte"] == empreinte
    assert service.lire(journal, etat="publie")["total"] == 0
    assert service.lire(journal, "pub-inconnue")["refus"][0]["code"] == "REJ-SOCIAL-PUBLICATION-INCONNUE"


def test_lire_borne_la_taille_de_la_liste(journal, comptes_actifs):
    for i in range(60):
        composer(
            journal,
            comptes_actifs,
            publication("facebook", texte=f"Message sobre numéro {chr(97 + i % 26)}{chr(97 + i // 26)}."),
            cle=f"cle-liste-{i:03d}-0123456789",
        )
    assert len(service.lire(journal, limite=10_000)["publications"]) == 50
    assert len(service.lire(journal, limite=3)["publications"]) == 3
    assert len(service.lire(journal, limite=0)["publications"]) == 1


# -- journal : append-only, chaîné, vérifié
# ----------------------------------------------------------------------------------
def test_le_journal_est_chaine_et_un_maillon_retouche_arrete_tout(
    soumise, journal, declarations, politique_sas, proprietaire
):
    publication_id, empreinte = soumise
    assert journal_chaine.verifier(journal) == []
    journal[0]["publication"]["texte"] = "Texte retouché dans le registre"
    for geste in (
        lambda: service.lire(journal),
        lambda: approuver(journal, declarations, politique_sas, proprietaire, publication_id, empreinte),
        lambda: service.annuler(journal, publication_id, "agent", "x", HORODATAGE),
        lambda: soumettre(journal, declarations, politique_sas, publication_id),
    ):
        assert geste()["refus"][0]["code"] == "REJ-SOCIAL-JOURNAL-ALTERE"


def test_un_maillon_retire_ou_reordonne_est_vu(soumise, journal):
    journal_chaine.ajouter(
        journal,
        "annulee",
        {"publication_id": soumise[0], "par": "a", "motif": "m", "etat_avant": "x", "incertain": False},
        HORODATAGE,
    )
    assert journal_chaine.verifier(journal) == []
    retire = [journal[0], journal[2]]
    assert journal_chaine.verifier(retire) != []
    permute = [journal[1], journal[0], journal[2]]
    assert journal_chaine.verifier(permute) != []
    assert service.lire(retire)["refus"][0]["code"] == "REJ-SOCIAL-JOURNAL-ALTERE"


def test_un_contenu_modifie_avec_une_chaine_recalculee_est_vu_par_l_empreinte(
    soumise,
    journal,
    declarations,
    politique_sas,
    proprietaire,
):
    """L'attaquant sait recalculer la chaîne : il reste l'empreinte du contenu, approuvée, qu'il ne peut pas changer."""
    publication_id, empreinte = soumise
    corps = {k: v for k, v in journal[0].items() if k != "chaine"}
    corps["publication"] = {**corps["publication"], "texte": "Texte frauduleux, tout aussi sobre."}
    refait = [{**corps, "chaine": journal_chaine._chaine(journal_chaine.GENESE, corps)}]
    precedent = refait[0]["chaine"]
    for ancien in journal[1:]:
        c = {k: v for k, v in ancien.items() if k != "chaine"}
        refait.append({**c, "chaine": journal_chaine._chaine(precedent, c)})
        precedent = refait[-1]["chaine"]
    assert journal_chaine.verifier(refait) == []
    refus = approuver(refait, declarations, politique_sas, proprietaire, publication_id, empreinte)
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-EMPREINTE-DIFFERENTE"


def test_un_maillon_qui_n_a_pas_de_sens_rend_le_journal_incoherent(journal, comptes_actifs):
    composer(journal, comptes_actifs)
    journal_chaine.ajouter(
        journal,
        "publiee",
        {
            "publication_id": journal[0]["publication_id"],
            "id_externe": "x",
            "url": None,
            "publie_le": HORODATAGE,
            "publie_le_externe": HORODATAGE,
            "tentative": 1,
            "retrouvee": False,
        },
        HORODATAGE,
    )
    assert service.lire(journal)["refus"][0]["code"] == "REJ-SOCIAL-JOURNAL-INCOHERENT"
    journal_chaine.ajouter(journal, "inconnu", {"publication_id": journal[0]["publication_id"]}, HORODATAGE)
    assert service.lire(journal)["refus"][0]["code"] == "REJ-SOCIAL-JOURNAL-INCOHERENT"


def test_le_journal_ne_garde_aucun_secret_ni_aucun_jeton(soumise, journal):
    texte = str(journal).lower()
    for interdit in ("bearer", "jeton", "secret", "password", "mot_de_passe", "api_key"):
        assert interdit not in texte


# -- transitions : table exhaustive
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("depuis", etats.ETATS)
@pytest.mark.parametrize("vers", etats.ETATS)
def test_la_table_des_transitions_est_exacte(depuis, vers):
    permises = {
        ("brouillon", "en_attente_approbation"),
        ("brouillon", "annule"),
        ("en_attente_approbation", "approuve"),
        ("en_attente_approbation", "brouillon"),
        ("en_attente_approbation", "annule"),
        ("approuve", "planifie"),
        ("approuve", "annule"),
        ("planifie", "publie"),
        ("planifie", "echec"),
        ("planifie", "annule"),
        ("echec", "planifie"),
        ("echec", "annule"),
    }
    assert etats.transition_permise(depuis, vers) is ((depuis, vers) in permises)


def test_publie_et_annule_sont_terminaux_et_le_modele_porte_les_sept_etats():
    assert etats.ETATS == ("brouillon", "en_attente_approbation", "approuve", "planifie", "publie", "echec", "annule")
    assert etats.TRANSITIONS["publie"] == frozenset() == etats.TRANSITIONS["annule"]


def test_composer_utilise_le_modele_strict(journal, comptes_actifs):
    resultat = composer(journal, comptes_actifs, publication("facebook", medias=[media_photo(origine="inconnue")]))
    assert resultat["refus"][0]["code"] == "REJ-SOCIAL-VALEUR"
    assert modele.CHAMPS_PUBLICATION and COMPTE
