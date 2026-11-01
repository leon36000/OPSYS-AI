"""Les vecteurs fixes que le plugin PHP doit aussi respecter (`contracts/opsys-connect-vecteurs.v1.json`).

Trois lecteurs indépendants de la spécification : OpenSSL (a produit les valeurs attendues), le signataire de production
(`m7_marketing.wordpress`) et le vérificateur de référence des tests. Le plugin PHP est le quatrième ; il n'a JAMAIS été
exécuté (pas de PHP ici) : `integrations/wordpress/opsys-connect/tests/verifier-vecteurs.php` le fera contre ce même
fichier.
"""

from __future__ import annotations

import base64
import json

import pytest
from m7_marketing.wordpress import empreinte, jeton, signature

FICTIF = True


def test_le_fichier_de_vecteurs_est_complet(vecteurs):
    assert vecteurs["schema"] == "opsys-connect.vecteurs/v1" and vecteurs["fictif"] is True
    assert len(vecteurs["signatures"]) >= 5 and len(vecteurs["verifications"]) >= 30
    assert len(vecteurs["jetons"]) >= 30 and len(vecteurs["empreintes_contenu"]) >= 4
    ids = [c["id"] for c in vecteurs["verifications"]] + [c["id"] for c in vecteurs["jetons"]]
    assert len(ids) == len(set(ids)), "identifiants de cas en double"
    # le vecteur couvre CHAQUE issue possible du vérificateur
    assert {c["attendu"] for c in vecteurs["verifications"]} == {
        "OK",
        "HORS_FENETRE",
        "SIGNATURE_INVALIDE",
        "SIGNATURE_MALFORMEE",
        "EN_TETE_MANQUANT",
        "HORODATAGE_INVALIDE",
        "NONCE_INVALIDE",
    }
    assert {c["attendu"] for c in vecteurs["jetons"]} == {
        "OK",
        "JETON_MALFORME",
        "JETON_SIGNATURE_INVALIDE",
        "JETON_CHAMP_INVALIDE",
        "JETON_EXPIRE",
        "JETON_DUREE_EXCESSIVE",
        "JETON_EMIS_DANS_LE_FUTUR",
        "JETON_SITE_DIFFERENT",
        "JETON_ARTICLE_DIFFERENT",
        "JETON_EMPREINTE_DIFFERENTE",
        "JETON_ACTION_NON_PERMISE",
        "JETON_PLANIFICATION_INVALIDE",
    }


def test_le_signataire_de_production_reproduit_chaque_signature_d_openssl(vecteurs):
    secret = vecteurs["secret_de_test"]
    for cas in vecteurs["signatures"]:
        corps = cas["corps_utf8"].encode("utf-8")
        assert signature.empreinte_corps(corps) == cas["empreinte_corps"], cas["id"]
        assert (
            signature.chaine_canonique(cas["methode"], cas["route"], cas["horodatage"], cas["nonce"], corps)
            == cas["chaine_canonique"]
        ), cas["id"]
        assert (
            signature.signature(
                secret,
                cas["methode"],
                cas["route"],
                cas["horodatage"],
                cas["nonce"],
                corps,
            )
            == cas["signature"]
        ), cas["id"]


def test_les_en_tetes_du_signataire_sont_acceptes_par_le_verificateur_de_reference(vecteurs, reference):
    secret = vecteurs["secret_de_test"]
    for cas in vecteurs["signatures"]:
        corps = cas["corps_utf8"].encode("utf-8")
        en_tetes = signature.en_tetes_signes(
            secret,
            vecteurs["cle_id"],
            cas["methode"],
            cas["route"],
            int(cas["horodatage"]),
            cas["nonce"],
            corps,
        )
        assert set(en_tetes) == {
            signature.EN_TETE_CLE,
            signature.EN_TETE_HORODATAGE,
            signature.EN_TETE_NONCE,
            signature.EN_TETE_SIGNATURE,
        }
        assert (
            reference.verifier_requete(
                secret,
                cas["methode"],
                cas["route"],
                corps,
                en_tetes,
                int(cas["horodatage"]),
            )
            == "OK"
        ), cas["id"]


def test_le_verificateur_de_reference_donne_l_issue_attendue_sur_chaque_verification(vecteurs, reference):
    for cas in vecteurs["verifications"]:
        requete = cas["requete"]
        obtenu = reference.verifier_requete(
            cas["secret_verificateur"],
            requete["methode"],
            requete["route"],
            requete["corps_utf8"].encode("utf-8"),
            requete["en_tetes"],
            cas["maintenant"],
        )
        assert obtenu == cas["attendu"], (cas["id"], cas["description"])


def test_les_constantes_du_signataire_sont_celles_de_la_specification_du_vecteur(vecteurs):
    assert signature.FENETRE_S == 300
    assert (
        signature.PREFIXE_CANONIQUE
        == "OPSYS-CONNECT-V1"
        == vecteurs["signatures"][0]["chaine_canonique"].split("\n")[0]
    )
    limites = {c["id"]: c for c in vecteurs["verifications"]}
    assert (
        limites["ok-limite-passee"]["attendu"] == "OK" and limites["hors-fenetre-passee"]["attendu"] == "HORS_FENETRE"
    )


def test_la_cle_d_approbation_derivee_est_celle_du_vecteur(vecteurs, reference):
    secret = vecteurs["secret_de_test"]
    assert jeton.cle_approbation(secret).hex() == vecteurs["cle_approbation_hex"]
    assert reference.cle_approbation(secret).hex() == vecteurs["cle_approbation_hex"]


def test_le_verificateur_de_reference_donne_l_issue_attendue_sur_chaque_jeton(vecteurs, reference):
    for cas in vecteurs["jetons"]:
        ctx = cas["contexte"]
        obtenu, _ = reference.verifier_jeton(
            ctx["secret_verificateur"],
            cas["jeton"],
            site_id_attendu=ctx["site_id_attendu"],
            post_id_attendu=ctx["post_id_attendu"],
            empreinte_courante=ctx["empreinte_courante"],
            maintenant=ctx["maintenant"],
            actions_permises=tuple(ctx["actions_permises"]),
        )
        assert obtenu == cas["attendu"], (cas["id"], cas["description"])


@pytest.mark.parametrize("identifiant", ["ok-publish", "ok-schedule"])
def test_l_emetteur_de_production_reproduit_le_jeton_du_vecteur_octet_pour_octet(vecteurs, reference, identifiant):
    cas = next(c for c in vecteurs["jetons"] if c["id"] == identifiant)
    charge_b64 = cas["jeton"].split(".")[1]
    charge = json.loads(base64.urlsafe_b64decode(charge_b64 + "=" * (-len(charge_b64) % 4)))
    assert jeton.emettre(vecteurs["secret_de_test"], charge) == cas["jeton"]


def test_l_emetteur_refuse_d_emettre_ce_que_le_plugin_refuserait(vecteurs):
    secret = vecteurs["secret_de_test"]
    cas = next(c for c in vecteurs["jetons"] if c["id"] == "ok-publish")
    charge_b64 = cas["jeton"].split(".")[1]
    base = json.loads(base64.urlsafe_b64decode(charge_b64 + "=" * (-len(charge_b64) % 4)))
    for modification in (
        {"post_id": 42.0},
        {"post_id": "42"},
        {"post_id": True},
        {"approval_id": "court"},
        {"action": "delete"},
        {"publish_at": "2026-01-01T14:00:00Z"},
        {"exp": base["iat"] + 86401},
        {"exp": base["iat"]},
        {"v": 2},
        {"content_sha256": "C" * 64},
        {"approved_by": ""},
        {"site_id": "Majuscules.example"},
    ):
        with pytest.raises(ValueError):
            jeton.emettre(secret, {**base, **modification})
    with pytest.raises(ValueError):
        jeton.emettre(secret, {k: v for k, v in base.items() if k != "approved_by"})
    with pytest.raises(ValueError):
        jeton.emettre(secret, {**base, "extra": 1})
    with pytest.raises(signature.SecretInvalide):
        jeton.emettre("trop-court", base)


def test_les_empreintes_de_contenu_sont_celles_d_openssl_dans_les_deux_implementations(vecteurs, reference):
    for cas in vecteurs["empreintes_contenu"]:
        canon = empreinte.canonique(cas["champs"]).decode("utf-8")
        assert canon == cas["canonique_utf8"], cas["id"]
        assert empreinte.empreinte_contenu(cas["champs"]) == cas["attendu_sha256"], cas["id"]
        assert reference.empreinte_contenu(cas["champs"]) == cas["attendu_sha256"], cas["id"]


def test_un_saut_de_ligne_dans_une_valeur_ne_peut_pas_imiter_un_autre_champ(vecteurs):
    base = {"type": "post", "titre": "a", "contenu": "", "extrait": "", "slug": "", "image_a_la_une_sha256": ""}
    piege = {**base, "titre": "a\ncontenu:1:b"}
    vrai = {**base, "titre": "a", "contenu": "b"}
    assert empreinte.empreinte_contenu(piege) != empreinte.empreinte_contenu(vrai)


def test_les_empreintes_refusent_un_champ_inconnu_ou_manquant(vecteurs):
    base = {"type": "post", "titre": "a", "contenu": "", "extrait": "", "slug": "", "image_a_la_une_sha256": ""}
    with pytest.raises(ValueError):
        empreinte.empreinte_contenu({**base, "auteur": "x"})
    with pytest.raises(ValueError):
        empreinte.empreinte_contenu({k: v for k, v in base.items() if k != "slug"})
    with pytest.raises(TypeError):
        empreinte.empreinte_contenu({**base, "titre": 5})


def test_le_signataire_refuse_ce_que_le_plugin_refuserait(vecteurs):
    secret = vecteurs["secret_de_test"]
    ok = ("POST", "/opsys-connect/v1/drafts", 1767225600, "nonce-de-test-0123456789", b"{}")
    signature.en_tetes_signes(secret, "default", ok[0], ok[1], ok[2], ok[3], ok[4])
    for tort in (
        {"horodatage": 12345},
        {"horodatage": -1767225600},
        {"nonce": "court"},
        {"nonce": "a b" * 8},
        {"nonce": "a" * 65},
        {"cle_id": "a b"},
        {"cle_id": ""},
    ):
        args = {
            "cle_id": "default",
            "methode": ok[0],
            "route": ok[1],
            "horodatage": ok[2],
            "nonce": ok[3],
            "corps": ok[4],
        }
        args.update(tort)
        with pytest.raises(ValueError):
            signature.en_tetes_signes(
                secret, args["cle_id"], args["methode"], args["route"], args["horodatage"], args["nonce"], args["corps"]
            )
    with pytest.raises(signature.SecretInvalide) as info:
        signature.en_tetes_signes("secret-trop-court", "default", *ok)
    assert "secret-trop-court" not in str(info.value)


def test_la_methode_est_mise_en_majuscules_avant_la_signature_comme_dans_le_plugin():
    secret = "secret-de-test-public-0123456789abcdefghij"
    args = ("/opsys-connect/v1/drafts", "1767225600", "nonce-de-test-0123456789", b"{}")
    assert signature.signature(secret, "post", *args) == signature.signature(secret, "POST", *args)
    assert signature.chaine_canonique("put", *args).splitlines()[1] == "PUT"
    assert signature.signature(secret, "POST", *args) != signature.signature(secret, "PUT", *args)
