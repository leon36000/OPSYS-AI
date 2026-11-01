"""Corpus FICTIF étiqueté pour mesurer le masquage (précision, rappel, faux positifs, limites connues).

Aucune donnée réelle : les numéros sont fabriqués ici (somme de Luhn calculée), les cartes sont les numéros d'essai
publiés par les réseaux de paiement, les courriels sont en `@example.test`, les noms et adresses sont inventés.
Chaque cas porte le texte, les détections ATTENDUES `(catégorie, sous-chaîne)` et, pour les `limites`, ce qu'une
approche
par motifs rate (le test exige qu'on les voie rater : une limite améliorée doit être déclarée, pas cachée).
"""

from __future__ import annotations

import dataclasses

from .pii_detecteurs import luhn_valide

FICTIF = True


def _complete_luhn(prefixe: str) -> str:
    for c in "0123456789":
        if luhn_valide(prefixe + c):
            return prefixe + c
    raise AssertionError("aucun chiffre de contrôle")  # pragma: no cover — toujours un chiffre possible


def _nas(base: str) -> str:
    return _complete_luhn(base)


def _faux_luhn(valeur: str) -> str:
    """Même longueur, dernier chiffre changé pour que la somme de Luhn échoue."""
    dernier = (int(valeur[-1]) + 1) % 10
    return valeur[:-1] + str(dernier)


@dataclasses.dataclass(frozen=True)
class CasPII:
    texte: str
    attendus: tuple[tuple[str, str], ...] = ()
    limite: bool = False  # ce que les motifs ratent : `attendus` y décrit ce qu'un humain voudrait masqué
    note: str = ""
    fp_connu: bool = False  # texte sans renseignement que les motifs masquent QUAND MÊME (faux positif assumé)


_N1, _N2, _N3 = _nas("13069254"), _nas("27418395"), _nas("51234567")
_FAUX_NAS = _faux_luhn(_N1)


def _g(n: str, sep: str = " ") -> str:
    return f"{n[:3]}{sep}{n[3:6]}{sep}{n[6:]}"


CORPUS: tuple[CasPII, ...] = (
    # -- NAS ---------------------------------------------------------------------------------------------------------
    CasPII(f"Mon NAS est {_g(_N1)}, merci.", (("nas", _g(_N1)),)),
    CasPII(f"NAS : {_g(_N2, '-')}", (("nas", _g(_N2, "-")),)),
    CasPII(f"Numéro d'assurance sociale {_N3}", (("nas", _N3),)),
    CasPII(f"Le client ({_g(_N1, chr(0xa0))}) a signé.", (("nas", _g(_N1, chr(0xa0))),)),
    CasPII(f"SIN {_g(_N2, '.')} on file", (("nas", _g(_N2, ".")),)),
    # -- cartes ------------------------------------------------------------------------------------------------------
    CasPII("Paiement par carte 4111 1111 1111 1111 exp. 12/29", (("carte", "4111 1111 1111 1111"),)),
    CasPII("MC 5555-5555-5555-4444", (("carte", "5555-5555-5555-4444"),)),
    CasPII("Amex 3782 822463 10005 reçue", (("carte", "3782 822463 10005"),)),
    CasPII("Carte 4012888888881881 au dossier", (("carte", "4012888888881881"),)),
    CasPII("Discover 6011 1111 1111 1117", (("carte", "6011 1111 1111 1117"),)),
    # -- téléphones --------------------------------------------------------------------------------------------------
    CasPII("Rappelez-moi au (514) 555-0199.", (("telephone", "(514) 555-0199"),)),
    CasPII("Cell : 438.555.0142", (("telephone", "438.555.0142"),)),
    CasPII("Tél. +1 418 555 0123 poste 22", (("telephone", "+1 418 555 0123 poste 22"),)),
    CasPII("1-800-555-0100 (sans frais)", (("telephone", "1-800-555-0100"),)),
    CasPII("Texto au 5145550177 s'il vous plaît", (("telephone", "5145550177"),)),
    CasPII("Joindre Luc au 819 555 0188 ou au 450 555 0166", (("telephone", "819 555 0188"), ("telephone",
                                                                                              "450 555 0166"))),
    # -- courriels ---------------------------------------------------------------------------------------------------
    CasPII("Écrire à jean.tremblay@example.test pour la soumission.", (("courriel", "jean.tremblay@example.test"),)),
    CasPII("De: Lise.Gagnon+devis@Example.test", (("courriel", "Lise.Gagnon+devis@Example.test"),)),
    CasPII("a@b.co et c_d@sous.domaine.example.test", (("courriel", "a@b.co"), ("courriel",
                                                                                "c_d@sous.domaine.example.test"))),
    # -- codes postaux et adresses -----------------------------------------------------------------------------------
    CasPII("Code postal H2X 1Y4 à Montréal", (("code_postal", "H2X 1Y4"),)),
    CasPII("Poste restante G1A-1A1.", (("code_postal", "G1A-1A1"),)),
    CasPII("Livrer au 1234 rue des Érables, app. 4, Québec", (("adresse", "1234 rue des Érables, app. 4"),)),
    CasPII("Chantier au 45, boulevard Taschereau Nord.", (("adresse", "45, boulevard Taschereau Nord"),)),
    CasPII("Facturer au 780 chemin du Lac, Saint-Fictif J0X 1A0",
           (("adresse", "780 chemin du Lac"), ("code_postal", "J0X 1A0"))),
    CasPII("Visite au 12 Maple Street demain", (("adresse", "12 Maple Street"),)),
    CasPII("Le 3e avenue est fermée; adresse: 1500 3e avenue Est", (("adresse", "1500 3e avenue Est"),)),
    # -- RAMQ, NEQ, numéros d'entreprise -----------------------------------------------------------------------------
    CasPII("Carte soleil TREJ 8501 1512 présentée", (("ramq", "TREJ 8501 1512"),)),
    CasPII("RAMQ : GAGL90561834", (("ramq", "GAGL90561834"),)),
    CasPII("NEQ : 1143456789 inscrit au registre", (("neq", "1143456789"),)),
    CasPII("Numéro d'entreprise du Québec 2245678901", (("neq", "2245678901"),)),
    CasPII("Compte TPS 123456789 RT0001", (("numero_entreprise", "123456789 RT0001"),)),
    CasPII("TVQ 1234567890 TQ 0001", (("numero_entreprise", "1234567890 TQ 0001"),)),
    CasPII("Numéro d'entreprise 987654321 (ARC)", (("numero_entreprise", "987654321"),)),
    # -- secrets -----------------------------------------------------------------------------------------------------
    CasPII("clé: ghp_" + "aB3dE5gH7j" * 4, (("secret", "ghp_" + "aB3dE5gH7j" * 4),)),
    CasPII("AKIA" + "ABCDEFGH12345678", (("secret", "AKIA" + "ABCDEFGH12345678"),)),
    CasPII("api_key=Zx9Qw3Er7Ty1Ui5Op", (("secret", "Zx9Qw3Er7Ty1Ui5Op"),)),
    CasPII("password: correct-horse-9", (("secret", "correct-horse-9"),)),
    CasPII("Voir https://user:S3cretPw@intranet.example.test/x", (("secret", "S3cretPw"),)),
    CasPII("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJlMTIz",
           (("secret", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJlMTIz"),)),
    CasPII("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----",
           (("secret", "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----"),)),
    CasPII("jeton brut Kd82Lq0PzX4mN7vB1cR6tY9wE3uA5sGh", (("secret", "Kd82Lq0PzX4mN7vB1cR6tY9wE3uA5sGh"),)),
    # -- civilité + nom ----------------------------------------------------------------------------------------------
    CasPII("M. Tremblay a appelé hier.", (("nom", "M. Tremblay"),)),
    CasPII("Mme Lise Gagnon-Roy confirme.", (("nom", "Mme Lise Gagnon-Roy"),)),
    CasPII("Dre Marie Côté recevra le devis.", (("nom", "Dre Marie Côté"),)),
    # -- combinaisons ------------------------------------------------------------------------------------------------
    CasPII(f"M. Bouchard ({_g(_N1)}) — jean@example.test — (514) 555-0100",
           (("nom", "M. Bouchard"), ("nas", _g(_N1)), ("courriel", "jean@example.test"),
            ("telephone", "(514) 555-0100"))),
    # -- négatifs : du texte d'affaires ordinaire, rien à masquer ---------------------------------------------------
    CasPII("Soumission FAC-2026-0001 : total 1 234,56 $ avant taxes, valide jusqu'au 2026-11-30."),
    CasPII("Le chantier a commencé le 12 octobre 2026 à 8 h 30."),
    CasPII("sha256:" + "ab" * 32 + " est l'empreinte du paquet."),
    CasPII("Commit 9fceb02d0ae598e95dc970b74767f19372d61af8 sur la branche claude/observabilite-mcp."),
    CasPII("UUID 3f2504e0-4f89-11d3-9a0c-0305e82c3301 de la demande."),
    CasPII(f"Total à payer : {_g(_N2)} $ (TPS incluse)."),
    CasPII(f"Montant {_N1},50 $ et {_FAUX_NAS} unités."),
    CasPII("Référence 1234567890123456 de la commande (16 chiffres, somme de contrôle invalide)."),
    CasPII("Identifiant interne 514555019 pour le lot 2026."),
    CasPII("Tableau 2026-11-01 14:30:00 UTC, durée 125 ms, 3 appels."),
    CasPII("La rue Principale est fermée jusqu'à lundi à cause des travaux."),
    CasPII("Il y a 3 étages et 12 fenêtres à remplacer sur le côté nord."),
    CasPII("Appeler le 911 en cas de danger; le 211 pour les ressources."),
    CasPII("Le code H2X est un préfixe; lot 5-2-3 de la zone C."),
    CasPII("Me voici au bureau, Dr. House n'est pas ici."),
    CasPII("Réunion à 14 h, salle 4B; budget de 15 000 $ approuvé par le comité."),
    CasPII("fichier_rapport_trimestriel_ventes_2026_version_finale.pdf"),
    CasPII("normaliserAdresseCourrielEntrante est une fonction du module de réception"),
    CasPII("chemin /usr/local/lib/python3.12/site-packages/opsys/observabilite/pii.py"),
    CasPII("Version 2.0.0.dev0 de opsys, protocole 2026-07-28."),
    CasPII("Facture 2026-0042 pour 8 heures à 65,00 $/h; solde 1 560,00 $."),
    CasPII("Les clients veulent une soumission avant la fin du mois; rappeler jeudi."),
    CasPII("Téléphone: à venir (le client n'a pas donné son numéro)."),
    CasPII("Le NAS n'est jamais demandé par courriel; ne l'envoyez pas."),
    CasPII("Mot de passe oublié? Utilisez le lien de réinitialisation."),
    # -- faux positifs CONNUS : du texte sans renseignement personnel que les motifs masquent quand même
    # -----------------
    CasPII("Commande 4532015112830366 expédiée", fp_connu=True, note="identifiant long à somme de Luhn valide"),
    CasPII("SKU H2X1Y4 en rupture", fp_connu=True, note="référence qui a la forme d'un code postal"),
    CasPII("Le 12 rue principale sera fermée", fp_connu=True, note="numéro + rue : adresse présumée"),
    CasPII("Abcdefghijklmnopqrstuvwxyz0123456789", fp_connu=True, note="chaîne longue à forte entropie"),
    CasPII("Total 4 000 000 000 en stock", ),
    # -- limites connues : ce que des motifs ne voient PAS -----------------------------------------------------------
    CasPII("Jean Tremblay de Longueuil a signé le contrat.", (("nom", "Jean Tremblay"),), True,
           "nom propre sans civilité"),
    CasPII("La maison bleue au coin de l'église de Saint-Fictif, derrière le dépanneur.",
           (("adresse", "La maison bleue au coin de l'église"),), True, "adresse décrite en mots"),
    CasPII("Mon NAS : un trois zéro, six neuf deux, cinq quatre quatre.", (("nas", "un trois zéro"),), True,
           "numéro écrit en lettres"),
    CasPII("Écrivez à jean point tremblay arobase example point test", (("courriel", "jean point tremblay"),), True,
           "courriel obscurci"),
    CasPII("Carte 4111 1111\n1111 1111", (("carte", "4111 1111\n1111 1111"),), True, "valeur coupée sur deux lignes"),
    CasPII("Mon chum Steve a une dette de 4 000 $ chez nous", (("nom", "Steve"),), True, "prénom seul dans une phrase"),
    CasPII("ID client 2026-QC-88412 (Boucherie fictive Gagnon et fils)", (("nom", "Gagnon et fils"),), True,
           "nom d'entreprise individuelle"),
    CasPII("cle hex 5f4dcc3b5aa765d61d8327deb882cf995f4dcc3b5aa765d6", (("secret",
                                                                         "5f4dcc3b5aa765d61d8327deb882cf995f4dcc3b5aa765d6"),),
           True, "secret hexadécimal : indiscernable d'une empreinte"),
)
