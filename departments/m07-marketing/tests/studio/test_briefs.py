"""Registre des briefs : idempotence par clé, révision, intégrité."""

from __future__ import annotations

import fabriques_studio as f
from m7_marketing import journal_chaine
from m7_marketing.studio import briefs

CLE = "cle-brief-0123456789abcdef"


def _codes(resultat):
    return [r["code"] for r in resultat.get("refus", [])]


def test_creer_puis_rejouer_la_meme_cle_et_le_meme_contenu_ecrit_une_seule_fois():
    journal: list = []
    un = briefs.composer(journal, f.brief(), CLE, "agent", f.HORODATAGE)
    deux = briefs.composer(journal, f.brief(), CLE, "agent", f.HORODATAGE)
    assert un["accepte"] and un["revision"] == 1 and un["deja_cree"] is False
    assert deux["brief_id"] == un["brief_id"] and deux["deja_cree"] is True and len(journal) == 1
    assert un["brief_id"] == briefs.identifiant(CLE) and len(journal_chaine.maillons(journal)) == 1


def test_meme_cle_autre_contenu_est_un_conflit_et_ecrit_rien():
    journal: list = []
    briefs.composer(journal, f.brief(), CLE, "agent", f.HORODATAGE)
    conflit = briefs.composer(journal, f.brief(objet="Une autre campagne fictive"), CLE, "agent", f.HORODATAGE)
    assert _codes(conflit) == [briefs.REJ_CLE_CONFLIT] and len(journal) == 1


def test_reviser_par_identifiant_donne_une_revision_et_garde_l_ancienne_lisible():
    journal: list = []
    cree = briefs.composer(journal, f.brief(), CLE, "agent", f.HORODATAGE)
    revise = briefs.composer(
        journal, f.brief(objet="Une autre campagne fictive"), CLE, "agent", f.HORODATAGE, brief_id=cree["brief_id"]
    )
    assert revise["revision"] == 2 and not revise["deja_cree"]
    assert (
        briefs.composer(
            journal, f.brief(objet="Une autre campagne fictive"), CLE, "agent", f.HORODATAGE, brief_id=cree["brief_id"]
        )["deja_cree"]
        is True
    )
    ancien = briefs.par_empreinte(journal, cree["empreinte"])
    assert (
        ancien is not None
        and ancien.donnees["objet"] != briefs.obtenir(journal, cree["brief_id"]).brief.donnees["objet"]
    )
    assert len(journal) == 2


def test_un_brief_invalide_ne_s_ecrit_pas_et_les_refus_sont_rendus():
    journal: list = []
    donnees = f.brief()
    donnees["elements_critiques"][0]["valeur"] = "514"
    resultat = briefs.composer(journal, donnees, CLE, "agent", f.HORODATAGE)
    assert resultat["accepte"] is False and journal == []
    assert resultat["refus"][0]["chemin"].startswith("$.elements_critiques")


def test_cle_invalide_et_brief_inconnu():
    journal: list = []
    assert _codes(briefs.composer(journal, f.brief(), "court", "agent", f.HORODATAGE)) == [briefs.REJ_CLE]
    assert _codes(briefs.composer(journal, f.brief(), CLE, "agent", f.HORODATAGE, brief_id="brief-nul")) == [
        briefs.REJ_INCONNU
    ]
    assert _codes(briefs.obtenir(journal, "brief-nul")) == [briefs.REJ_INCONNU]
    assert briefs.par_empreinte(journal, "0" * 64) is None


def test_journal_altere_ou_brief_retouche_refuse_tout():
    journal: list = []
    cree = briefs.composer(journal, f.brief(), CLE, "agent", f.HORODATAGE)
    journal[0] = {**journal[0], "par": "autre"}
    assert _codes(briefs.obtenir(journal, cree["brief_id"])) == [briefs.REJ_JOURNAL_ALTERE]
    assert briefs.par_empreinte(journal, cree["empreinte"]) is None
    neuf: list = []
    briefs.composer(neuf, f.brief(), CLE, "agent", f.HORODATAGE)
    brief_retouche = dict(neuf[0]["brief"])
    brief_retouche["objet"] = "Objet retouché dans le registre"
    # Un maillon dont le contenu ne correspond plus à son empreinte, même avec une chaîne recalculée, est refusé.
    refait: list = []
    journal_chaine.ajouter(
        refait,
        "brief_cree",
        {
            "brief_id": neuf[0]["brief_id"],
            "brief": brief_retouche,
            "empreinte": neuf[0]["empreinte"],
            "cle_idempotence": CLE,
            "par": "x",
        },
        f.HORODATAGE,
    )
    assert _codes(briefs.obtenir(refait, neuf[0]["brief_id"])) == [briefs.REJ_JOURNAL_ALTERE]


def test_lire_liste_et_detail():
    journal: list = []
    cree = briefs.composer(journal, f.brief(), CLE, "agent", f.HORODATAGE)
    assert briefs.lire(journal)["briefs"][0]["brief_id"] == cree["brief_id"]
    assert briefs.lire(journal, cree["brief_id"])["brief"]["gabarit"] == "carte_affaires"
    assert _codes(briefs.lire(journal, "brief-nul")) == [briefs.REJ_INCONNU]


def test_sans_marque_retire_la_marque_fournie():
    assert "marque" not in briefs.sans_marque(f.brief())
