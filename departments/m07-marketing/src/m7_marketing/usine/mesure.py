"""Clé de mesure d'un contenu exporté, et le fait « contenu exporté » (PLAN T4.17-e ; DEFINITION-PRODUIT §7 M7.3
« mesure » et §6 « M7 attire → M1 capte »).

Pour savoir quel contenu a amené quel lead, chaque contenu porte un `utm_content` : la clé que le lien de suivi du
paquet manuel recopie dans l'URL, que M1 rapporte dans le lead qui l'a suivie (`m1.lead_qualifie`,
`lead.utm.utm_content`) et que M8 compte. Ce module dit comment cette clé naît et ce que M7 annonce au bus quand un
paquet sort.

1. DÉTERMINISTE. La clé est tirée du seul `contenu_id` (lui-même dérivé du chantier, de la plateforme et de la
   révision) : `<plateforme>-<empreinte SHA-256 du contenu_id>`. Aucun hasard, aucune horloge, aucun compteur : le même
   contenu donne toujours la même clé, un autre contenu une autre.
2. SANS RENSEIGNEMENT PERSONNEL. L'empreinte n'est pas réversible. Ni le nom d'un client, ni une adresse, ni le
   `wct_id`, ni un identifiant de lead n'entrent dans la clé : c'est une URL publique.
3. FAIL-CLOSED. Un contenu sans identifiant stable (`contenu_id` absent ou vide) n'a pas de clé : refus nommé, jamais
   un identifiant inventé. Une clé déjà écrite au contenu, ou dans son lien de suivi, qui n'est pas celle que son
   identifiant donne (lien d'avant la convention, ou altéré) est refusée aussi : M7 n'annonce à M8 que ce qu'il peut
   prouver, et un lien qui ne porte pas la clé annoncée ne ferait jamais compter un lead.

Le fait `m7.contenu_exporte` (catalogue `src/opsys/evenements/catalogue/m7.contenu_exporte.json`) dit à M8 quels
contenus existent : leur clé, leur chantier, leur canal, et si le paquet portait un lien de suivi. Aucun texte, aucune
ville, aucun lead, aucun contact, aucun nom de client.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

import hashlib
import urllib.parse
from collections.abc import Mapping
from typing import Any

from . import plateformes, verdicts

TYPE_EVENEMENT = "m7.contenu_exporte"
# 64 bits d'empreinte : deux contenus d'une même plateforme ne partagent jamais leur clé en pratique, et M8 refuse
# d'attribuer un lead à une clé que deux contenus se disputeraient (il le dit).
LONGUEUR_EMPREINTE = 16


def utm_content_de(contenu_id: Any, plateforme: Any) -> str:
    """La clé de mesure de ce contenu : `<plateforme>-<empreinte du contenu_id>`, conforme à l'alphabet et à la longueur
    du contrat gelé `utm-convention.v1` (minuscules, chiffres, `-`, `_`, 80 caractères au plus).

    `ValueError` si le contenu n'a pas d'identifiant stable (`contenu_id` qui n'est pas un texte non vide) ou si la
    plateforme n'est pas l'une des cinq de M7 : jamais une clé sans son contenu, jamais une clé tirée au sort."""
    if not isinstance(contenu_id, str) or not contenu_id.strip():
        raise ValueError("contenu_id absent ou vide : sans identifiant stable, un contenu n'a pas de clé de mesure")
    if plateforme not in plateformes.CODES_PLATEFORMES:
        raise ValueError(f"plateforme inconnue : {plateforme!r} (attendu : {', '.join(plateformes.CODES_PLATEFORMES)})")
    empreinte = hashlib.sha256(contenu_id.encode("utf-8")).hexdigest()[:LONGUEUR_EMPREINTE]
    return f"{plateforme}-{empreinte}"


def utm_content_du_lien(lien: Any) -> str | None:
    """La valeur de `utm_content` dans la requête de ce lien, ou `None` (pas de lien, ou pas de ce paramètre)."""
    if not isinstance(lien, str) or not lien:
        return None
    valeurs = urllib.parse.parse_qs(urllib.parse.urlsplit(lien).query).get("utm_content")
    return valeurs[0] if valeurs else None


def identifiant_de_mesure(proposition: Mapping[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """`(clé, None)` ou `(None, verdict)` : la clé de mesure d'un contenu proposé, vérifiée.

    La clé est RECALCULÉE depuis l'identifiant du contenu ; ce que la proposition a écrit (`utm_content`, `utm.content`,
    et le paramètre `utm_content` du lien de suivi) doit être cette clé, sinon refus. Une proposition sans lien n'a rien
    d'autre à contredire : sa clé existe quand même (un lien ajouté plus tard la porterait)."""
    try:
        attendue = utm_content_de(proposition.get("contenu_id"), proposition.get("plateforme"))
    except ValueError as erreur:
        return None, verdicts.verdict(verdicts.REJ_CONTENU_SANS_IDENTIFIANT, str(erreur))
    utm = proposition.get("utm")
    ecrites = (
        ("utm_content du contenu", proposition.get("utm_content")),
        ("utm.content du lien de suivi", utm.get("content") if isinstance(utm, Mapping) else None),
        ("utm_content dans le lien de suivi", utm_content_du_lien(proposition.get("lien_utm"))),
    )
    for source, valeur in ecrites:
        if valeur is not None and valeur != attendue:
            return None, verdicts.verdict(
                verdicts.REJ_UTM_CONTENT_INCOHERENT,
                f"{source} ({valeur!r}) n'est pas la clé que l'identifiant du contenu donne ({attendue!r}) : "
                "contenu proposé avant la convention de mesure, ou lien altéré. Le rejeter et proposer un nouveau "
                "texte (textes) refait un lien conforme",
            )
    if proposition.get("lien_utm") and utm_content_du_lien(proposition["lien_utm"]) is None:
        return None, verdicts.verdict(
            verdicts.REJ_UTM_CONTENT_INCOHERENT,
            f"le lien de suivi ne porte pas utm_content ({attendue!r}) : aucun lead ne serait compté pour ce contenu",
        )
    return attendue, None


def evenement_id(contenu_id: str) -> str:
    """Identifiant du fait au bus : un par contenu, donc un export rejoué est un no-op de l'outbox."""
    return f"m7-contenu-exporte-{contenu_id}"


def charge_contenu_exporte(proposition: Mapping[str, Any], utm_content: str, exporte_le: str) -> dict[str, Any]:
    """La charge de `m7.contenu_exporte` : la clé (déjà vérifiée par `identifiant_de_mesure`), le chantier, le canal
    et la trace de l'export. `lien_de_suivi` est vrai si le paquet portait un lien : sans lien, aucun lead ne peut
    porter la clé, et M8 le dit. Rien d'autre : ni texte, ni ville, ni lead, ni contact."""
    return {
        "contenu_id": proposition["contenu_id"],
        "wct_id": proposition["wct_id"],
        "canal": proposition["plateforme"],
        "utm_content": utm_content,
        "lien_de_suivi": bool(proposition.get("lien_utm")),
        "exporte_le": exporte_le,
    }
