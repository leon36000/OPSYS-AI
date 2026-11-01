"""Demande et exécution de génération : sélection refaite, aucun repli, provenance, graine, pannes, secrets masqués."""

from __future__ import annotations

import dataclasses

import fabriques_studio as f
import pytest
from m7_marketing import journal_chaine
from m7_marketing.studio import actifs, executeur, generation, modeles, provenance
from m7_marketing.studio import brief as b

JETON = "jeton-secret-fictif-0123456789abcdef"


def _brief(fictif=True, fond=None, **plus):
    donnees = f.brief("banniere_social", fictif=fictif, fond=fond or f.GENERE, **plus)
    if not fictif:
        donnees["elements_critiques"] = [
            {"type": "telephone", "valeur": "+1 514 523 4567", "source": "fiche d'entreprise"}
        ]
    brief, refus = b.depuis_dict(donnees)
    assert brief is not None, refus
    return brief


class Banc:
    """Journaux en liste, fichier de fonds en mémoire, sélection injectée."""

    def __init__(self, selection=None):
        self.jobs: list = []
        self.prov: list = []
        self.actifs: list = []
        self.fonds: dict = {}
        self.selection = selection or f.selection_double()

    def demander(self, brief=None, **kw):
        brief = brief or _brief()
        return executeur.demander_generation(
            self.jobs,
            "brief-1",
            brief,
            self.selection,
            par="agent",
            horodatage=f.HORODATAGE,
            maintenant=f.MAINTENANT,
            **kw,
        )

    def executer(self, job_id, adaptateurs, selection=None, **kw):
        sel = selection or self.selection

        def resoudre(genre):
            if isinstance(sel, Exception):
                raise sel
            return sel

        return executeur.executer(
            self.jobs,
            self.prov,
            self.actifs,
            job_id,
            adaptateurs=adaptateurs,
            resoudre_modele=resoudre,
            ecrire_fond=lambda sha, octets, fmt: self.fonds.__setitem__(sha, (octets, fmt)),
            par="executeur",
            horodatage=f.HORODATAGE,
            maintenant=f.MAINTENANT,
            **kw,
        )


def _codes(resultat):
    return [r["code"] for r in resultat.get("refus", [])]


ID = "image.double-deterministe.test"


def test_une_demande_consigne_tout_sans_appeler_aucun_modele():
    banc = Banc()
    demande = banc.demander()
    assert demande["accepte"] and demande["etat"] == "en_attente" and demande["fournisseur"] == ID
    assert "Aucune" in demande["execution"] and banc.prov == [] and banc.actifs == [] and banc.fonds == {}
    maillon = banc.jobs[0]
    assert maillon["licence"]["fournisseur_id"] == ID and maillon["licence"]["decision"]["conforme"]
    assert "no text" in maillon["demande"]["invite"] and maillon["demande"]["graine"] == demande["graine"]
    assert (maillon["demande"]["largeur"], maillon["demande"]["hauteur"]) == (1080, 1350)


def test_la_demande_est_idempotente_et_une_variante_change_la_graine():
    banc = Banc()
    un, deux = banc.demander(), banc.demander()
    assert deux["deja_demande"] is True and deux["job_id"] == un["job_id"] and len(banc.jobs) == 1
    autre = banc.demander(variante=1)
    assert autre["job_id"] != un["job_id"] and autre["graine"] != un["graine"]


def test_la_graine_du_brief_est_respectee():
    brief = _brief(fond={**f.GENERE, "graine": 1234})
    assert Banc().demander(brief)["graine"] == 1234


def test_un_brief_sans_fond_genere_ne_demande_rien():
    brief, _ = b.depuis_dict(f.brief())
    resultat = executeur.demander_generation(
        [], "brief-1", brief, f.selection_double(), par="agent", horodatage=f.HORODATAGE, maintenant=f.MAINTENANT
    )
    assert _codes(resultat) == [executeur.REJ_FOND_NON_DEMANDE]


def test_l_execution_ecrit_provenance_fond_et_resultat():
    banc = Banc()
    job = banc.demander()["job_id"]
    resultat = banc.executer(job, {ID: generation.GenerateurImageDouble()})
    assert resultat["accepte"] and resultat["nature_generateur"] == "double" and resultat["deja_execute"] is False
    assert len(banc.prov) == 1 and len(banc.fonds) == 1
    sha, (octets, fmt) = next(iter(banc.fonds.items()))
    maillon = banc.prov[0]
    assert maillon["chaine"] == resultat["provenance_chaine"] and maillon["sortie"]["sha256"] == sha and fmt == "png"
    assert maillon["graine"] == banc.jobs[0]["demande"]["graine"] and maillon["fournisseur_id"] == ID
    assert maillon["licence"]["decision"]["conforme"] is True
    etat = actifs.plier(banc.actifs)[resultat["fond_actif_id"]]
    assert (
        etat.kind == "fond"
        and etat.etat == actifs.ETAT_FOND_BRUT
        and etat.donnees["provenance_chaine"] == maillon["chaine"]
    )
    assert journal_chaine.integre(banc.jobs) and journal_chaine.integre(banc.prov)


def test_reexecuter_une_demande_terminee_est_un_rejeu_sans_nouveau_maillon():
    banc = Banc()
    job = banc.demander()["job_id"]
    adaptateurs = {ID: generation.GenerateurImageDouble()}
    premier = banc.executer(job, adaptateurs)
    second = banc.executer(job, adaptateurs)
    assert second["deja_execute"] is True and second["provenance_chaine"] == premier["provenance_chaine"]
    assert len(banc.prov) == 1 and len(banc.jobs) == 2


def test_la_graine_rejoue_le_meme_fond_octet_pour_octet():
    un, deux = Banc(), Banc()
    for banc in (un, deux):
        banc.executer(banc.demander()["job_id"], {ID: generation.GenerateurImageDouble()})
    assert list(un.fonds) == list(deux.fonds)


def test_aucun_adaptateur_pour_le_fournisseur_selectionne_est_un_echec_sans_repli():
    banc = Banc()
    job = banc.demander()["job_id"]
    resultat = banc.executer(job, {"image.autre.local": generation.GenerateurImageDouble()})
    assert _codes(resultat) == [generation.REJ_ADAPTATEUR_ABSENT] and banc.prov == [] and banc.fonds == {}
    assert executeur.plier(banc.jobs)[job].etat == "echec"
    assert _codes(banc.executer(job, {})) == [generation.REJ_ADAPTATEUR_ABSENT]  # aucun adaptateur en production


def test_le_modele_selectionne_a_change_depuis_la_demande_aucun_remplacement():
    banc = Banc()
    job = banc.demander()["job_id"]
    autre = f.selection_double("image.double-deterministe-2.test")
    resultat = banc.executer(
        job,
        {
            ID: generation.GenerateurImageDouble(),
            "image.double-deterministe-2.test": generation.GenerateurImageDouble(),
        },
        selection=autre,
    )
    assert _codes(resultat) == [executeur.REJ_MODELE_CHANGE] and banc.prov == []


def test_la_licence_devenue_non_conforme_avant_l_execution_bloque():
    banc = Banc()
    job = banc.demander()["job_id"]
    refuse = modeles.ModeleRefuse("REJ-STUDIO-MODELE-REFUS_POLITIQUE", "non conforme", ("SEUIL_REVENU_DEPASSE",))
    resultat = banc.executer(job, {ID: generation.GenerateurImageDouble()}, selection=refuse)
    assert _codes(resultat) == ["REJ-STUDIO-MODELE-REFUS_POLITIQUE"] and banc.prov == [] and banc.fonds == {}
    assert "SEUIL_REVENU_DEPASSE" in resultat["refus"][0]["detail"]


def test_un_brief_non_fictif_refuse_un_generateur_de_test():
    banc = Banc()
    job = banc.demander(_brief(fictif=False))["job_id"]
    resultat = banc.executer(job, {ID: generation.GenerateurImageDouble()})
    assert _codes(resultat) == [generation.REJ_GENERATEUR_DE_TEST] and banc.prov == []


def test_un_generateur_reel_est_accepte_pour_un_brief_non_fictif():
    class Reel(generation.GenerateurImageDouble):
        nature = generation.NATURE_REEL

    banc = Banc()
    job = banc.demander(_brief(fictif=False))["job_id"]
    resultat = banc.executer(job, {ID: Reel()})
    assert resultat["accepte"] and resultat["nature_generateur"] == "reel"
    assert banc.prov[0]["nature_generateur"] == "reel"


def test_une_panne_d_adaptateur_est_typee_et_bornee_a_trois_tentatives():
    class Panne:
        nature = generation.NATURE_DOUBLE

        def generer(self, demande):
            raise RuntimeError("503 service indisponible")

    banc = Banc()
    job = banc.demander()["job_id"]
    for _ in range(3):
        assert _codes(banc.executer(job, {ID: Panne()})) == [generation.REJ_GENERATION]
    assert "RuntimeError" in str(banc.jobs)
    quatrieme = banc.executer(job, {ID: Panne()})
    assert _codes(quatrieme) == [executeur.REJ_TENTATIVES]
    assert banc.prov == [] and banc.fonds == {}


def test_le_message_d_une_panne_ne_laisse_pas_un_jeton_enregistre_au_masquage():
    from opsys.secrets_coffre import masquage

    class Panne:
        nature = generation.NATURE_DOUBLE

        def generer(self, demande):
            raise RuntimeError(f"échec avec {JETON}")

    banc = Banc()
    job = banc.demander()["job_id"]
    masquage.enregistrer(JETON)
    try:
        banc.executer(job, {ID: Panne()})
    finally:
        masquage.oublier(JETON)
    assert JETON not in str(banc.jobs)


@pytest.mark.parametrize("modif", ["octets", "graine", "format", "dims"])
def test_une_sortie_invalide_d_un_adaptateur_est_un_echec_et_n_ecrit_rien(modif):
    class Mauvais:
        nature = generation.NATURE_DOUBLE

        def generer(self, demande):
            sortie = generation.GenerateurImageDouble().generer(demande)
            if modif == "octets":
                return dataclasses.replace(sortie, octets=b"x")
            if modif == "graine":
                return dataclasses.replace(sortie, graine=demande.graine + 1)
            if modif == "format":
                return dataclasses.replace(sortie, format="jpeg")
            return dataclasses.replace(sortie, largeur=sortie.largeur + 1)

    banc = Banc()
    job = banc.demander()["job_id"]
    resultat = banc.executer(job, {ID: Mauvais()})
    assert _codes(resultat) == [generation.REJ_SORTIE] and banc.prov == [] and banc.fonds == {} and banc.actifs == []


def test_un_fond_non_ecrit_sur_le_disque_est_un_echec_apres_la_provenance_et_se_rejoue_sans_doublon():
    banc = Banc()
    job = banc.demander()["job_id"]
    etat = {"echoue": True}

    def ecrire(sha, octets, fmt):
        if etat["echoue"]:
            raise OSError("disque plein")
        banc.fonds[sha] = (octets, fmt)

    def lancer():
        return executeur.executer(
            banc.jobs,
            banc.prov,
            banc.actifs,
            job,
            adaptateurs={ID: generation.GenerateurImageDouble()},
            resoudre_modele=lambda genre: banc.selection,
            ecrire_fond=ecrire,
            par="executeur",
            horodatage=f.HORODATAGE,
            maintenant=f.MAINTENANT,
        )

    assert _codes(lancer()) == [executeur.REJ_SORTIE_NON_ECRITE]
    assert len(banc.prov) == 1 and banc.actifs == []
    etat["echoue"] = False
    assert lancer()["accepte"] and len(banc.prov) == 1 and len(banc.fonds) == 1  # pas de second maillon de provenance


def test_demande_inconnue_et_journal_altere():
    banc = Banc()
    assert _codes(banc.executer("job-inconnu", {})) == [executeur.REJ_JOB_INCONNU]
    job = banc.demander()["job_id"]
    banc.jobs[0] = {**banc.jobs[0], "par": "autre"}
    assert _codes(banc.executer(job, {ID: generation.GenerateurImageDouble()})) == [executeur.REJ_JOBS_ALTERE]
    assert _codes(banc.demander()) == [executeur.REJ_JOBS_ALTERE]


def test_la_provenance_enregistree_est_relisible_par_l_empreinte_de_chaine():
    banc = Banc()
    job = banc.demander()["job_id"]
    resultat = banc.executer(job, {ID: generation.GenerateurImageDouble()})
    assert provenance.trouver(banc.prov, resultat["provenance_chaine"])["job_id"] == job
