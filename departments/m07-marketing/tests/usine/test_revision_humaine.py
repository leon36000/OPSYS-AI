"""Le port humain révise une seule plateforme ; le contrat pur MCP/bus reste inchangé."""

import pytest
from m7_marketing.usine import chantier


@pytest.mark.parametrize("code", ["facebook", "instagram", "fiche_google", "video_courte", "demande_temoignage"])
def test_revision_humaine_ciblee_pure_sans_ecrasement(charge, profil, nature, code):
    premiere = chantier.preparer(charge, profil, nature, None, (), (), "test")
    ancienne = next(p for p in premiere.nouvelles if p["plateforme"] == code)
    avant = [dict(p) for p in premiere.nouvelles]
    nouvelle = chantier.preparer(
        charge,
        profil,
        nature,
        {code: "Un chantier de gouttières terminé avec soin."},
        premiere.nouvelles,
        (),
        "console:proprietaire-fictif",
        revision_humaine=ancienne["contenu_id"],
        renouveler_marque=False,
    )
    assert len(nouvelle.nouvelles) == 1
    revision = nouvelle.nouvelles[0]
    assert revision["plateforme"] == code and revision["revision"] == 2
    assert revision["origine_texte"] == "humain" and revision["approval_status"] == "PROPOSE"
    assert revision["contenu_id"] != ancienne["contenu_id"] and revision["utm_content"] != ancienne["utm_content"]
    assert [dict(p) for p in premiere.nouvelles] == avant
    public = chantier.preparer(
        charge, profil, nature, {code: "Un chantier de gouttières terminé avec soin."}, premiere.nouvelles, (), "agent"
    )
    assert public.nouvelles == ()
