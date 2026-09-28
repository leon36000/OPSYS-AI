"""Chargement FAIL-CLOSED du profil de marque du CLIENT — remplace le gabarit par défaut
(PLAN T4.3, M7-audit.md §2.1 « Marque — donnée réelle absente », §4-Phase1.1).

`brand/profile.yaml` exposait l'identité d'OPSYS-AI elle-même (`name: "OPSYS-AI"`) comme profil
« par défaut », en violation directe de `SOUL.md` (« Tu fais rayonner cette entreprise — jamais
OPSYS-AI » / « Recopier l'identité d'OPSYS-AI (nom, domaine, copyright) : ... interdit »). Ce
module remplace le chargement silencieux par un chargement fail-closed : le fichier reste le
même chemin, versionné dans le dépôt, à remplir par/pour le client une fois configuré — mais tant
que `name` porte encore le repère `PLACEHOLDER_NOM`, le profil est traité comme NON CONFIGURÉ, un
verdict nommé qui dit quoi fournir, jamais un contenu composé sous un nom inventé.

Le nom commercial exact (PLAN.md « Décisions attendues de Nathan ») est une décision de Nathan
(GATE) : ce module ne l'invente JAMAIS et ne le contient PAS — seule sa place est prévue dans
`profile.yaml`. Idem pour tagline/tone/colors/mentions tant qu'ils ne sont pas fournis : aucune
valeur n'est devinée (AGENTS.md « données inventées »).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import brand_schema

# Repère de « non configuré » — DOIT être l'exacte valeur de `name` dans le `profile.yaml`
# gabarit tant que le profil réel du client n'a pas été fourni. Une chaîne non vide (passe la
# validation de type du contrat gelé v1) mais jamais confondable avec un vrai nom commercial.
# Volontairement COURTE : un `name` de gabarit long peut, une fois composé dans un titre/slug de
# contenu réel, dépasser des limites avales indépendantes (ex. utm_campaign <= 100 caractères,
# contrat S012 règle U-05) — le repère ne doit jamais être la cause d'un tel échec.
PLACEHOLDER_NOM = "À CONFIGURER (GATE NATHAN)"

_PROFIL_PAR_DEFAUT = Path(__file__).resolve().parent / "profile.yaml"

REFUS_FICHIER_ABSENT = "profil de marque introuvable : {chemin}"
REFUS_PROFIL_INVALIDE = "profil de marque invalide : {champ} — {raison}"
REFUS_NON_CONFIGURE = (
    "profil de marque non configuré (encore le gabarit par défaut) : le nom commercial exact "
    "est une décision de Nathan (GATE, PLAN.md) — renseigner 'name' dans "
    "m7_marketing/brand/profile.yaml, jamais une valeur devinée ici"
)


def verifier_profil_configure(profil: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """`(profil_normalise, None)` si `profil` est valide contre le contrat gelé ET ne porte plus
    `PLACEHOLDER_NOM` ; sinon `(None, motif)`. Fonction pure (aucune E/S) : `profil` est déjà un
    dict chargé par l'appelant. Jamais d'exception : un profil non configuré n'est pas une panne.
    """
    try:
        valide = brand_schema.validate_profile(profil)
    except brand_schema.ProfileError as exc:
        return None, REFUS_PROFIL_INVALIDE.format(champ=exc.field, raison=exc.message)
    if valide.get("name") == PLACEHOLDER_NOM:
        return None, REFUS_NON_CONFIGURE
    return valide, None


def charger_profil_client(chemin: str | Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Charge et valide le profil de marque du client depuis `chemin` (défaut : le
    `profile.yaml` versionné du département, JAMAIS un autre gabarit caché). `(None, motif)`
    fail-closed pour un fichier absent, invalide, ou encore non configuré (`PLACEHOLDER_NOM`) —
    jamais une exception qui casse l'appelant, même doctrine que le reste de M7 (AGENTS.md
    « Fail-closed »).
    """
    chemin_reel = Path(chemin) if chemin is not None else _PROFIL_PAR_DEFAUT
    try:
        with open(chemin_reel, encoding="utf-8") as f:
            brut = yaml.safe_load(f)
    except FileNotFoundError:
        return None, REFUS_FICHIER_ABSENT.format(chemin=chemin_reel)
    if not isinstance(brut, dict):
        return None, REFUS_PROFIL_INVALIDE.format(champ="racine", raison="le fichier doit être un mapping YAML")
    return verifier_profil_configure(brut)
