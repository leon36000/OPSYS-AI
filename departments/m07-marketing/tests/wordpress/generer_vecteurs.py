"""Génère `contracts/opsys-connect-vecteurs.v1.json` (vecteurs de test PARTAGÉS avec le plugin PHP).

Script ponctuel, jamais lancé par la suite de tests. Les valeurs attendues (empreintes SHA-256, signatures HMAC) sont
calculées par la commande `openssl`, PAS par les modules de production ni par le vérificateur de référence : trois
implémentations indépendantes (OpenSSL, le client, le vérificateur de référence) doivent s'accorder sur chaque octet.

    python generer_vecteurs.py > ../../contracts/opsys-connect-vecteurs.v1.json

Aucune donnée réelle : le « secret » ci-dessous est une valeur de test publique, écrite pour l'être.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys

SECRET = "vecteur-de-test-public-non-secret-0123456789abcdef"
CLE_ID = "default"
MAINTENANT = 1767225600  # 2026-01-01T00:00:00Z
ROUTE = "/opsys-connect/v1/drafts"
NONCE = "N0nce-de-test_0123456789"
SITE = "horizon-fictif.example"


def openssl(*args: str, entree: bytes) -> str:
    sortie = subprocess.run(["openssl", *args], input=entree, capture_output=True, check=True).stdout.decode()
    return sortie.strip().split()[-1]


def sha256_hex(octets: bytes) -> str:
    return openssl("dgst", "-sha256", "-hex", entree=octets)


def hmac_hex(cle: bytes, donnees: bytes) -> str:
    return openssl("dgst", "-sha256", "-mac", "HMAC", "-macopt", f"hexkey:{cle.hex()}", "-hex", entree=donnees)


def b64url(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).decode().rstrip("=")


def canonique(methode: str, route: str, horodatage: str, nonce: str, corps: bytes) -> str:
    return "\n".join(("OPSYS-CONNECT-V1", methode, route, horodatage, nonce, sha256_hex(corps)))


def signature(secret: str, methode: str, route: str, horodatage: str, nonce: str, corps: bytes) -> str:
    return "v1=" + hmac_hex(secret.encode(), canonique(methode, route, horodatage, nonce, corps).encode())


def cle_approbation(secret: str) -> bytes:
    return bytes.fromhex(hmac_hex(secret.encode(), b"opsys-connect/approval/v1\x01"))


def jeton(charge_json: str, secret: str = SECRET, *, mac_domaine_requete: bool = False) -> str:
    charge_b64 = b64url(charge_json.encode())
    if mac_domaine_requete:
        mac = hmac_hex(secret.encode(), PREFIXE_MAC + charge_b64.encode())
    else:
        mac = hmac_hex(cle_approbation(secret), PREFIXE_MAC + charge_b64.encode())
    return f"v1.{charge_b64}.{mac}"


PREFIXE_MAC = b"OPSYS-APPROVAL-V1\n"


def corps_json(corps: str) -> dict:
    return {"corps_utf8": corps}


def signatures() -> list[dict]:
    cas = [
        ("post-json-ascii", "POST", ROUTE, str(MAINTENANT), NONCE, '{"titre":"Bonjour","type":"post"}'),
        (
            "post-json-unicode",
            "POST",
            ROUTE,
            str(MAINTENANT - 17),
            "Un-Autre_nonce_0123456789abcd",
            '{"contenu":"Québec — été \U0001f3e0 \\u00e9","titre":"Atelier à Laval"}',
        ),
        ("get-corps-vide", "GET", "/opsys-connect/v1/health", str(MAINTENANT), "get_nonce_0123456789abcdef", ""),
        (
            "put-brouillon",
            "PUT",
            "/opsys-connect/v1/drafts/42",
            str(MAINTENANT + 5),
            "put-nonce-0123456789abcdef",
            '{"empreinte_attendue":"' + "ab" * 32 + '","statut":"pending"}',
        ),
        (
            "post-saut-de-ligne-dans-le-corps",
            "POST",
            ROUTE,
            str(MAINTENANT),
            "nl-nonce-0123456789abcdef-x",
            '{"contenu":"ligne 1\\nligne 2"}\n',
        ),
    ]
    sortie = []
    for identifiant, methode, route, stamp, nonce, corps in cas:
        octets = corps.encode()
        sortie.append(
            {
                "id": identifiant,
                "methode": methode,
                "route": route,
                "horodatage": stamp,
                "nonce": nonce,
                **corps_json(corps),
                "empreinte_corps": sha256_hex(octets),
                "chaine_canonique": canonique(methode, route, stamp, nonce, octets),
                "signature": signature(SECRET, methode, route, stamp, nonce, octets),
            }
        )
    return sortie


def verification(
    identifiant: str,
    description: str,
    base: dict,
    attendu: str,
    *,
    maintenant: int = MAINTENANT,
    methode: str | None = None,
    route: str | None = None,
    corps: str | None = None,
    en_tetes: dict | None = None,
    secret_verificateur: str = SECRET,
) -> dict:
    en = {
        "X-OPSYS-Key-Id": CLE_ID,
        "X-OPSYS-Timestamp": base["horodatage"],
        "X-OPSYS-Nonce": base["nonce"],
        "X-OPSYS-Signature": base["signature"],
    }
    if en_tetes is not None:
        en = {**en, **en_tetes}
        en = {k: v for k, v in en.items() if v is not None}
    return {
        "id": identifiant,
        "description": description,
        "secret_verificateur": secret_verificateur,
        "requete": {
            "methode": methode or base["methode"],
            "route": route or base["route"],
            "corps_utf8": base["corps_utf8"] if corps is None else corps,
            "en_tetes": en,
        },
        "maintenant": maintenant,
        "attendu": attendu,
    }


def signature_pour(base: dict, **remplace) -> dict:
    """Une signature VALIDE pour d'autres éléments (même secret) : isole la règle testée."""
    champs = {k: base[k] for k in ("methode", "route", "horodatage", "nonce")}
    champs.update({k: v for k, v in remplace.items() if k in champs})
    corps = remplace.get("corps_utf8", base["corps_utf8"]).encode()
    return {
        **base,
        **champs,
        "corps_utf8": corps.decode(),
        "signature": signature(
            SECRET, champs["methode"], champs["route"], champs["horodatage"], champs["nonce"], corps
        ),
    }


def verifications(sigs: list[dict]) -> list[dict]:
    a, unicode_, vide, put = sigs[0], sigs[1], sigs[2], sigs[3]
    nl = sigs[4]
    ancien = signature_pour(a, horodatage=str(MAINTENANT - 300))
    ancien_301 = signature_pour(a, horodatage=str(MAINTENANT - 301))
    futur_300 = signature_pour(a, horodatage=str(MAINTENANT + 300))
    futur_301 = signature_pour(a, horodatage=str(MAINTENANT + 301))
    return [
        verification("ok-post", "requête valide", a, "OK"),
        verification("ok-unicode", "corps UTF-8 non ASCII", unicode_, "OK"),
        verification("ok-get-vide", "GET sans corps", vide, "OK"),
        verification("ok-put", "PUT valide, 5 s dans le futur", put, "OK"),
        verification("ok-saut-de-ligne", "LF dans et à la fin du corps", nl, "OK"),
        verification("ok-limite-passee", "exactement 300 s dans le passé", ancien, "OK"),
        verification("ok-limite-future", "exactement 300 s dans le futur", futur_300, "OK"),
        verification("hors-fenetre-passee", "301 s dans le passé", ancien_301, "HORS_FENETRE"),
        verification("hors-fenetre-future", "301 s dans le futur", futur_301, "HORS_FENETRE"),
        verification("corps-modifie", "un octet du corps change", a, "SIGNATURE_INVALIDE", corps=a["corps_utf8"] + " "),
        verification("methode-modifiee", "signé POST, présenté PUT", a, "SIGNATURE_INVALIDE", methode="PUT"),
        verification(
            "route-modifiee",
            "signé /drafts, présenté /drafts/1",
            a,
            "SIGNATURE_INVALIDE",
            route="/opsys-connect/v1/drafts/1",
        ),
        verification(
            "horodatage-modifie",
            "horodatage changé dans la fenêtre",
            a,
            "SIGNATURE_INVALIDE",
            en_tetes={"X-OPSYS-Timestamp": str(MAINTENANT + 1)},
        ),
        verification(
            "nonce-modifie",
            "nonce changé",
            a,
            "SIGNATURE_INVALIDE",
            en_tetes={"X-OPSYS-Nonce": "Autre-nonce-0123456789abcdef"},
        ),
        verification(
            "mauvais-secret",
            "vérifié avec un autre secret",
            a,
            "SIGNATURE_INVALIDE",
            secret_verificateur="un-autre-secret-de-test-public-0123456789ab",
        ),
        verification(
            "signature-majuscules",
            "hexadécimal en majuscules refusé",
            a,
            "SIGNATURE_MALFORMEE",
            en_tetes={"X-OPSYS-Signature": "v1=" + a["signature"][3:].upper()},
        ),
        verification(
            "signature-sans-version",
            "préfixe v1= absent",
            a,
            "SIGNATURE_MALFORMEE",
            en_tetes={"X-OPSYS-Signature": a["signature"][3:]},
        ),
        verification(
            "signature-version-2",
            "préfixe v2=",
            a,
            "SIGNATURE_MALFORMEE",
            en_tetes={"X-OPSYS-Signature": "v2=" + a["signature"][3:]},
        ),
        verification(
            "signature-lf-final",
            "LF final après la signature",
            a,
            "SIGNATURE_MALFORMEE",
            en_tetes={"X-OPSYS-Signature": a["signature"] + "\n"},
        ),
        verification(
            "signature-absente",
            "en-tête de signature absent",
            a,
            "EN_TETE_MANQUANT",
            en_tetes={"X-OPSYS-Signature": None},
        ),
        verification(
            "nonce-absent", "en-tête de nonce absent", a, "EN_TETE_MANQUANT", en_tetes={"X-OPSYS-Nonce": None}
        ),
        verification(
            "horodatage-absent",
            "en-tête d'horodatage absent",
            a,
            "EN_TETE_MANQUANT",
            en_tetes={"X-OPSYS-Timestamp": None},
        ),
        verification(
            "horodatage-texte",
            "horodatage non numérique",
            a,
            "HORODATAGE_INVALIDE",
            en_tetes={"X-OPSYS-Timestamp": "demain"},
        ),
        verification(
            "horodatage-decimal",
            "horodatage décimal",
            a,
            "HORODATAGE_INVALIDE",
            en_tetes={"X-OPSYS-Timestamp": "1767225600.5"},
        ),
        verification(
            "horodatage-espace",
            "espace avant l'horodatage",
            a,
            "HORODATAGE_INVALIDE",
            en_tetes={"X-OPSYS-Timestamp": " 1767225600"},
        ),
        verification(
            "horodatage-lf-final",
            "LF final après l'horodatage",
            a,
            "HORODATAGE_INVALIDE",
            en_tetes={"X-OPSYS-Timestamp": "1767225600\n"},
        ),
        verification(
            "nonce-court", "nonce de 15 caractères", a, "NONCE_INVALIDE", en_tetes={"X-OPSYS-Nonce": "a" * 15}
        ),
        verification("nonce-long", "nonce de 65 caractères", a, "NONCE_INVALIDE", en_tetes={"X-OPSYS-Nonce": "a" * 65}),
        verification(
            "nonce-alphabet",
            "nonce avec une espace",
            a,
            "NONCE_INVALIDE",
            en_tetes={"X-OPSYS-Nonce": "nonce avec espace 0123456"},
        ),
        verification(
            "nonce-lf-final",
            "LF final après le nonce",
            a,
            "NONCE_INVALIDE",
            en_tetes={"X-OPSYS-Nonce": a["nonce"] + "\n"},
        ),
    ]


CHARGE_BASE = {
    "v": 1,
    "approval_id": "appr_0123456789abcdef",
    "site_id": SITE,
    "action": "publish",
    "post_id": 42,
    "content_sha256": "c" * 64,
    "iat": MAINTENANT - 60,
    "exp": MAINTENANT + 3540,
    "publish_at": None,
    "approved_by": "nathan",
}


def texte(charge: dict) -> str:
    return json.dumps(charge, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def cas_jeton(identifiant: str, description: str, jeton_texte: str, attendu: str, **contexte) -> dict:
    ctx = {
        "site_id_attendu": SITE,
        "post_id_attendu": 42,
        "empreinte_courante": "c" * 64,
        "maintenant": MAINTENANT,
        "actions_permises": ["publish", "schedule"],
        "secret_verificateur": SECRET,
    }
    ctx.update(contexte)
    return {"id": identifiant, "description": description, "jeton": jeton_texte, "contexte": ctx, "attendu": attendu}


def jetons() -> list[dict]:
    base = dict(CHARGE_BASE)
    valide = jeton(texte(base))
    planif = {**base, "action": "schedule", "publish_at": "2026-01-01T14:00:00Z"}
    charge_b64, mac = valide.split(".")[1:]
    cas = [
        cas_jeton("ok-publish", "publication immédiate", valide, "OK"),
        cas_jeton("ok-schedule", "planification à 14 h UTC", jeton(texte(planif)), "OK"),
        cas_jeton(
            "mac-modifie",
            "un caractère du MAC change",
            f"v1.{charge_b64}.{'0' if mac[0] != '0' else '1'}{mac[1:]}",
            "JETON_SIGNATURE_INVALIDE",
        ),
        cas_jeton(
            "charge-modifiee",
            "post_id changé, MAC d'origine",
            f"v1.{b64url(texte({**base, 'post_id': 43}).encode())}.{mac}",
            "JETON_SIGNATURE_INVALIDE",
        ),
        cas_jeton(
            "autre-secret",
            "jeton émis avec un autre secret",
            jeton(texte(base), "un-autre-secret-de-test-public-0123456789ab"),
            "JETON_SIGNATURE_INVALIDE",
        ),
        cas_jeton(
            "domaine-requete",
            "MAC calculé avec la clé de SIGNATURE DE REQUÊTE (séparation des domaines)",
            jeton(texte(base), mac_domaine_requete=True),
            "JETON_SIGNATURE_INVALIDE",
        ),
        cas_jeton("malforme-texte", "n'a pas la forme v1.x.y", "abc", "JETON_MALFORME"),
        cas_jeton("malforme-deux-parties", "deux parties seulement", f"v1.{charge_b64}", "JETON_MALFORME"),
        cas_jeton("malforme-quatre-parties", "quatre parties", f"v1.{charge_b64}.{mac}.x", "JETON_MALFORME"),
        cas_jeton("malforme-version", "préfixe v2", f"v2.{charge_b64}.{mac}", "JETON_MALFORME"),
        cas_jeton("malforme-mac-majuscules", "MAC en majuscules", f"v1.{charge_b64}.{mac.upper()}", "JETON_MALFORME"),
        cas_jeton(
            "malforme-bourrage",
            "charge base64 avec bourrage =",
            f"v1.{charge_b64}=.{hmac_hex(cle_approbation(SECRET), PREFIXE_MAC + charge_b64.encode() + b'=')}",
            "JETON_MALFORME",
        ),
        cas_jeton("malforme-json", "charge qui n'est pas du JSON (MAC valide)", jeton("pas du json"), "JETON_MALFORME"),
        cas_jeton(
            "malforme-pas-un-objet", "charge JSON qui est une liste (MAC valide)", jeton("[1,2,3]"), "JETON_MALFORME"
        ),
        cas_jeton(
            "champ-en-trop", "un champ de plus (MAC valide)", jeton(texte({**base, "extra": 1})), "JETON_CHAMP_INVALIDE"
        ),
        cas_jeton(
            "champ-manquant",
            "un champ de moins (MAC valide)",
            jeton(texte({k: v for k, v in base.items() if k != "approved_by"})),
            "JETON_CHAMP_INVALIDE",
        ),
        cas_jeton(
            "post-id-decimal",
            "post_id 42.0 (MAC valide)",
            jeton(texte(base).replace('"post_id":42', '"post_id":42.0')),
            "JETON_CHAMP_INVALIDE",
        ),
        cas_jeton(
            "post-id-texte",
            'post_id "42" (MAC valide)',
            jeton(texte({**base, "post_id": "42"})),
            "JETON_CHAMP_INVALIDE",
        ),
        cas_jeton(
            "approbation-courte",
            "approval_id de 7 caractères (MAC valide)",
            jeton(texte({**base, "approval_id": "abcdefg"})),
            "JETON_CHAMP_INVALIDE",
        ),
        cas_jeton(
            "publish-avec-heure",
            "publish avec publish_at (MAC valide)",
            jeton(texte({**base, "publish_at": "2026-01-01T14:00:00Z"})),
            "JETON_CHAMP_INVALIDE",
        ),
        cas_jeton(
            "schedule-sans-heure",
            "schedule sans publish_at (MAC valide)",
            jeton(texte({**base, "action": "schedule"})),
            "JETON_CHAMP_INVALIDE",
        ),
        cas_jeton(
            "action-inconnue",
            "action delete (MAC valide)",
            jeton(texte({**base, "action": "delete"})),
            "JETON_CHAMP_INVALIDE",
        ),
        cas_jeton(
            "expire",
            "exp dans le passé",
            jeton(texte({**base, "iat": MAINTENANT - 7200, "exp": MAINTENANT - 3600})),
            "JETON_EXPIRE",
        ),
        cas_jeton("expire-pile", "exp égale à maintenant", jeton(texte({**base, "exp": MAINTENANT})), "JETON_EXPIRE"),
        cas_jeton(
            "valide-jusqu-a-la-derniere-seconde",
            "exp = maintenant + 1",
            jeton(texte({**base, "exp": MAINTENANT + 1})),
            "OK",
        ),
        cas_jeton(
            "duree-excessive",
            "vie de 86 401 s",
            jeton(texte({**base, "iat": MAINTENANT - 60, "exp": MAINTENANT - 60 + 86401})),
            "JETON_DUREE_EXCESSIVE",
        ),
        cas_jeton(
            "duree-limite",
            "vie de 86 400 s exactement",
            jeton(texte({**base, "iat": MAINTENANT - 60, "exp": MAINTENANT - 60 + 86400})),
            "OK",
        ),
        cas_jeton(
            "duree-nulle",
            "exp = iat",
            jeton(texte({**base, "iat": MAINTENANT - 60, "exp": MAINTENANT - 60})),
            "JETON_DUREE_EXCESSIVE",
        ),
        cas_jeton(
            "emis-dans-le-futur",
            "iat à +61 s",
            jeton(texte({**base, "iat": MAINTENANT + 61, "exp": MAINTENANT + 600})),
            "JETON_EMIS_DANS_LE_FUTUR",
        ),
        cas_jeton(
            "emis-limite-future",
            "iat à +60 s",
            jeton(texte({**base, "iat": MAINTENANT + 60, "exp": MAINTENANT + 600})),
            "OK",
        ),
        cas_jeton(
            "autre-site", "jeton d'un autre site", valide, "JETON_SITE_DIFFERENT", site_id_attendu="autre.example"
        ),
        cas_jeton("autre-article", "jeton d'un autre article", valide, "JETON_ARTICLE_DIFFERENT", post_id_attendu=43),
        cas_jeton(
            "contenu-modifie",
            "le contenu a changé depuis l'approbation",
            valide,
            "JETON_EMPREINTE_DIFFERENTE",
            empreinte_courante="d" * 64,
        ),
        cas_jeton(
            "action-non-permise",
            "schedule non permis par la configuration",
            jeton(texte(planif)),
            "JETON_ACTION_NON_PERMISE",
            actions_permises=["publish"],
        ),
        cas_jeton("charge-objet-vide", "charge {} (MAC valide)", jeton("{}"), "JETON_CHAMP_INVALIDE"),
        cas_jeton(
            "planification-date-impossible",
            "schedule le 45e jour du 13e mois (MAC valide)",
            jeton(texte({**planif, "publish_at": "2026-13-45T25:61:61Z"})),
            "JETON_PLANIFICATION_INVALIDE",
        ),
        cas_jeton(
            "planification-passee",
            "schedule dans le passé",
            jeton(texte({**planif, "publish_at": "2025-12-31T23:00:00Z"})),
            "JETON_PLANIFICATION_INVALIDE",
        ),
        cas_jeton(
            "planification-maintenant",
            "schedule exactement maintenant",
            jeton(texte({**planif, "publish_at": "2026-01-01T00:00:00Z"})),
            "JETON_PLANIFICATION_INVALIDE",
        ),
    ]
    return cas


def empreintes() -> list[dict]:
    champs_cas = [
        (
            "article-simple",
            {
                "type": "post",
                "titre": "Bonjour",
                "contenu": "<p>Texte</p>",
                "extrait": "",
                "slug": "bonjour",
                "image_a_la_une_sha256": "",
            },
        ),
        (
            "unicode-et-octets",
            {
                "type": "page",
                "titre": "Services à Québec",
                "contenu": "<p>Été — \U0001f3e0</p>",
                "extrait": "Résumé",
                "slug": "services-quebec",
                "image_a_la_une_sha256": "e" * 64,
            },
        ),
        (
            "faux-champ-dans-la-valeur",
            {
                "type": "post",
                "titre": "a\ncontenu:1:b",
                "contenu": "",
                "extrait": "",
                "slug": "",
                "image_a_la_une_sha256": "",
            },
        ),
        (
            "tout-vide",
            {"type": "post", "titre": "", "contenu": "", "extrait": "", "slug": "", "image_a_la_une_sha256": ""},
        ),
    ]
    sortie = []
    for identifiant, champs in champs_cas:
        morceaux = ["opsys-content/v1\n"]
        for nom in ("type", "titre", "contenu", "extrait", "slug", "image_a_la_une_sha256"):
            morceaux.append(f"{nom}:{len(champs[nom].encode())}:{champs[nom]}\n")
        canon = "".join(morceaux)
        sortie.append(
            {"id": identifiant, "champs": champs, "canonique_utf8": canon, "attendu_sha256": sha256_hex(canon.encode())}
        )
    return sortie


def main() -> None:
    sigs = signatures()
    document = {
        "schema": "opsys-connect.vecteurs/v1",
        "fictif": True,
        "provenance": (
            "Valeurs attendues calculées par openssl (tests/wordpress/generer_vecteurs.py). Le plugin PHP "
            "(integrations/wordpress/opsys-connect/tests/verifier-vecteurs.php) et le vérificateur de référence "
            "Python doivent donner le même résultat sur chaque cas. Le plugin n'a pas été exécuté."
        ),
        "secret_de_test": SECRET,
        "cle_id": CLE_ID,
        "maintenant_reference": MAINTENANT,
        "site_id": SITE,
        "signatures": sigs,
        "verifications": verifications(sigs),
        "cle_approbation_hex": cle_approbation(SECRET).hex(),
        "jetons": jetons(),
        "empreintes_contenu": empreintes(),
    }
    json.dump(document, sys.stdout, ensure_ascii=False, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
