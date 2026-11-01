"""La matrice des licences de `docs/architecture/M7-STUDIO-CREATIF.md` est celle du catalogue (aucune dérive)."""

from __future__ import annotations

from pathlib import Path

from m7_marketing.studio import gabarits, modeles

DOC = Path(__file__).resolve().parents[4] / "docs" / "architecture" / "M7-STUDIO-CREATIF.md"
USAGES = {"autorise": "oui", "interdit": "**non**", "sous_seuil": "sous seuil", "sur_contrat": "sur contrat",
          "inconnu": "inconnu"}


def _ligne(r):
    seuil = f"{r['seuil_revenu_usd']:,}".replace(",", " ") + " USD" if r["seuil_revenu_usd"] else "—"
    territoires = ", ".join(r["territoires_exclus"]) or "—"
    lue = "oui" if r["verification"] == "verifiee" else "non (à lire)"
    return (f"| `{r['id']}` | {r['capacite']} | {r['statut']} | {r['poids']} | "
            f"{USAGES[r['usage_commercial']]} | {seuil} | "
            f"{territoires} | {r['service_tiers']} | {r['mention'] or '—'} | {lue} |")


def test_chaque_ligne_de_la_matrice_du_catalogue_est_dans_la_documentation():
    texte = DOC.read_text(encoding="utf-8")
    for r in modeles.matrice_licences_defaut():
        assert _ligne(r) in texte, f"matrice de la documentation périmée pour {r['id']} : régénérer la table"


def test_aucune_ligne_en_trop_dans_la_matrice_de_la_documentation():
    texte = DOC.read_text(encoding="utf-8")
    debut = texte.index("### Matrice des licences des modèles par défaut")
    fin = texte.index("Lecture : « adopte »")
    lignes = [x for x in texte[debut:fin].splitlines() if x.startswith("| `")]
    assert lignes == [_ligne(r) for r in modeles.matrice_licences_defaut()]


def test_les_formats_de_la_documentation_sont_ceux_des_gabarits():
    texte = DOC.read_text(encoding="utf-8")
    for (gabarit, nom), fm in gabarits.FORMATS.items():
        assert f"| `{gabarit}` | `{nom}` |" in texte
        assert fm.source in texte


def test_la_documentation_dit_qu_aucun_vrai_modele_ni_ocr_n_a_tourne():
    texte = DOC.read_text(encoding="utf-8")
    assert "Aucun vrai modèle n'a produit d'image" in texte and "Aucun OCR réel n'a lu une sortie" in texte
    assert "PDF/X" in texte and "À valider" in texte.replace("à valider", "À valider") or "avocat" in texte
