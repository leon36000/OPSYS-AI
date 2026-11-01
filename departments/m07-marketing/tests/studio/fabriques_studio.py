"""Fabriques fictives du studio créatif (module à nom unique : `conftest` est ambigu entre sous-dossiers)."""

from __future__ import annotations

import functools
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import police_pixel  # noqa: E402

FICTIF = True
POLICE_ID = "pixel-test-regular"
SOURCE_URL = "https://openfontlicense.org/fictif-police-de-test"


def ecrire_polices(dossier: Path, **options) -> Path:
    """Écrit la police de test et son manifeste dans `dossier` ; rend le dossier."""
    dossier.mkdir(parents=True, exist_ok=True)
    octets = police_pixel.ttf_octets(**options)
    (dossier / "PixelTest-Regular.ttf").write_bytes(octets)
    manifeste = {
        "schema": "opsys.polices/v1",
        "polices": [
            {
                "id": POLICE_ID,
                "famille": "OPSYS Test Pixel",
                "style": "Regular",
                "fichier": "PixelTest-Regular.ttf",
                "sha256": hashlib.sha256(octets).hexdigest(),
                "licence": "OFL-1.1",
                "source_url": SOURCE_URL,
                "fictif": True,
            }
        ],
    }
    (dossier / "polices.json").write_text(json.dumps(manifeste), encoding="utf-8")
    return dossier


EMPREINTE_PROFIL = "c" * 64
MARQUE = {
    "nom": "Revêtements Horizon Fictif",
    "couleurs": ["#0B3C5D", "#F2C14E", "#FFFFFF"],
    "langue": "fr",
    "empreinte_profil": EMPREINTE_PROFIL,
}
TELEPHONE = "+1 450 555 0142"
COURRIEL = "info@horizon-fictif.example"
ADRESSE = "123, rue des Érables, Laval (Québec) H7N 1A1"
RBQ = "1234-5678-90"
SOURCE = "fiche d'entreprise fictive, validée le 2026-10-05"


def critiques(*types):
    base = {
        "telephone": {"type": "telephone", "valeur": TELEPHONE, "source": SOURCE},
        "courriel": {"type": "courriel", "valeur": COURRIEL, "source": SOURCE},
        "adresse": {"type": "adresse", "valeur": ADRESSE, "source": SOURCE},
        "licence_rbq": {"type": "licence_rbq", "valeur": RBQ, "source": "registre public de la RBQ (fictif)"},
        "prix": {
            "type": "prix",
            "valeur": "1 250,00 $",
            "source": "soumission fictive M3-0001",
            "valide_jusqu_au": "2027-03-31",
        },
        "neq": {"type": "neq", "valeur": "1167890123", "source": SOURCE},
        "site_web": {"type": "site_web", "valeur": "horizon-fictif.example", "source": SOURCE},
    }
    return [dict(base[t]) for t in types]


def brief(gabarit="carte_affaires", format_=None, **plus):
    """Un brief VALIDE et fictif (fond uni par défaut : aucune IA)."""
    format_ = (
        format_
        or {"carte_affaires": "3.5x2", "affiche": "11x17", "banniere_social": "1080x1350", "couverture": "1640x624"}[
            gabarit
        ]
    )
    canal = "impression" if gabarit in ("carte_affaires", "affiche") else "facebook"
    donnees = {
        "schema": "opsys.studio.brief/v1",
        "fictif": True,
        "objet": "Carte d'affaires du printemps (démonstration fictive)",
        "gabarit": gabarit,
        "format": format_,
        "canal": canal,
        "marque": dict(MARQUE),
        "langues": ["fr"],
        "textes": {"titre": {"fr": "Votre toiture en confiance"}, "sous_titre": {"fr": "Inspection sur rendez-vous"}},
        "elements_critiques": critiques("telephone", "courriel", "adresse", "licence_rbq"),
        "mentions_obligatoires": ["Licence RBQ détenue par l'entreprise"],
        "fond": {"mode": "uni"},
        "couleur": "rvb",
    }
    donnees.update(plus)
    return donnees


@functools.lru_cache(maxsize=16)
def fond_synthetique(largeur=400, hauteur=300, graine=7):
    """Un PNG de fond synthétique (dégradé + bandes) sans modèle : sert à tester un fond « généré »."""
    from m7_marketing.studio import generation, png

    return png.encoder(
        png.ImageRVB(largeur, hauteur, generation._octets_synthetiques(largeur, hauteur, graine, "test"))
    )


PROVENANCE = {"chaine": "d" * 64, "modele": "double-deterministe", "version_modele": "1", "graine": 7}


import datetime as _dt  # noqa: E402

MAINTENANT = _dt.datetime(2026, 11, 1, 12, 0, tzinfo=_dt.UTC)
HORODATAGE = "2026-11-01T12:00:00Z"
GENERE = {
    "mode": "genere",
    "sujet": "toiture de bardeaux gris sous un ciel de printemps",
    "ambiance": "lumineuse",
    "rendu": "photographique",
}


def selection_double(identifiant="image.double-deterministe.test", mention=None, revenu=1_500_000):
    """Une `SelectionModele` fabriquée à la main (sans base) pour le fournisseur de test, avec sa décision de
    politique."""
    from m7_marketing.studio import modeles

    from opsys.fournisseurs import politique
    from opsys.fournisseurs.modele import Fournisseur

    declaration = modeles.declaration_pour_double(identifiant)
    if mention:
        declaration["licence"] = {**declaration["licence"], "mention_obligatoire": mention}
    fournisseur = Fournisseur.depuis_json(
        {
            **declaration,
            "statut_catalogue": "declare",
            "qualification": "a_mesurer",
            "licence_lue_par": None,
            "mention_confirmee": bool(mention),
        }
    )
    profil = politique.ProfilClient(True, revenu, frozenset({"CA"}), False)
    return modeles.SelectionModele(fournisseur, "m07-marketing", politique.evaluer(fournisseur, profil), "e" * 64, 1)
