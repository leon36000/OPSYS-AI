"""Règles de tri des courriels de M1 (M1.6) : des DONNÉES versionnées, lisibles et explicables.

Chaque règle porte un identifiant stable, un libellé en français (ce que le tri dit à la personne qui relit), le champ
qu'elle regarde, un motif (expression régulière sur le texte normalisé : minuscules, sans accents) et un poids. Aucune
règle n'est un jugement de modèle : le même courriel donne toujours les mêmes règles déclenchées.

`REGLES_V1` est écrit à la main à partir des définitions de classes (docs/architecture/M1-M6-LEA-ROSALIE.md), AVANT
toute mesure sur le corpus d'évaluation. Une règle apprise (M1.13) n'entre jamais ici : elle vit dans un jeu candidat,
plafonné (`POIDS_MAX_APPRIS`), jusqu'à sa promotion par une personne.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Iterable

CLASSES = (
    "pourriel_hameconnage",
    "plainte",
    "facture_fournisseur",
    "confirmation_fournisseur",
    "commande_materiaux",
    "demande_soumission",
    "reponse_client",
    "interne",
    "autre",
)
# Ordre de préséance à égalité de score : le plus prudent d'abord (un hameçonnage ne passe jamais pour autre chose).
PRESEANCE = CLASSES
CHAMPS = ("objet", "corps", "tout")
POIDS_MAX_APPRIS = 2
POIDS_MAX = 5


@dataclasses.dataclass(frozen=True)
class RegleTri:
    identifiant: str
    classe: str
    libelle: str
    champ: str
    motif: str
    poids: int

    def __post_init__(self) -> None:
        if self.classe not in CLASSES or self.champ not in CHAMPS:
            raise ValueError(f"règle {self.identifiant} : classe ou champ inconnu")
        if (
            not isinstance(self.poids, int)
            or isinstance(self.poids, bool)
            or not -POIDS_MAX <= self.poids <= POIDS_MAX
            or self.poids == 0
        ):
            raise ValueError(f"règle {self.identifiant} : poids entier non nul de -{POIDS_MAX} à {POIDS_MAX}")
        try:
            re.compile(self.motif)
        except re.error as exc:
            raise ValueError(f"règle {self.identifiant} : motif invalide ({exc})") from None

    def vers_json(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class JeuRegles:
    version: str
    regles: tuple[RegleTri, ...]

    def __post_init__(self) -> None:
        ids = [r.identifiant for r in self.regles]
        if len(set(ids)) != len(ids):
            raise ValueError("identifiant de règle en double")

    def empreinte(self) -> str:
        canon = json.dumps([r.vers_json() for r in self.regles], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def avec(self, nouvelles: Iterable[RegleTri], version: str) -> JeuRegles:
        return JeuRegles(version, (*self.regles, *nouvelles))


def _r(i: str, classe: str, libelle: str, champ: str, motif: str, poids: int) -> RegleTri:
    return RegleTri(i, classe, libelle, champ, motif, poids)


_PH = "pourriel_hameconnage"
_PL = "plainte"
_FF = "facture_fournisseur"
_CF = "confirmation_fournisseur"
_CM = "commande_materiaux"
_DS = "demande_soumission"
_RC = "reponse_client"
_IN = "interne"
_AU = "autre"

REGLES_V1: tuple[RegleTri, ...] = (
    # ------------------------------------------------------------------------------ demande de soumission
    _r(
        "ds-demande-explicite",
        _DS,
        "demande explicite de soumission, de prix, d'estimation ou de devis",
        "tout",
        r"\bdemande (de|d') ?(soumission|prix|estimation|estime|devis)",
        3,
    ),
    _r(
        "ds-vouloir-soumission",
        _DS,
        "veut obtenir une soumission, un prix, un devis ou une estimation",
        "tout",
        r"\b(obtenir|avoir|recevoir|demander|voudrais|voudrions|aimerais|aimerions|souhaite\w*|besoin d')\b.{0,30}"
        r"\b(soumission|estimation|estime|devis|prix|tarif)\b",
        3,
    ),
    _r(
        "ds-combien",
        _DS,
        "demande combien ça coûte",
        "tout",
        r"\bcombien (ca|cela|il|on|vous|ce)\b|\bc'est combien\b|\bquel (serait|est|sera) (le|votre) (prix|cout|tarif)"
        r"|\bquel prix\b|\bfourchette de prix\b",
        2,
    ),
    _r(
        "ds-visite",
        _DS,
        "demande une visite d'évaluation ou qu'on passe voir",
        "tout",
        r"\b(visite|evaluation) (d'evaluation|a domicile|sur place|gratuite|des lieux)|\b(passer|venir|se deplacer) "
        r"(voir|evaluer|regarder|estimer|mesurer)|\bevaluer les travaux",
        2,
    ),
    _r(
        "ds-disponibilite",
        _DS,
        "s'informe de la disponibilité de l'entreprise pour des travaux",
        "tout",
        r"\b(etes[- ]vous|seriez[- ]vous|avez[- ]vous) (disponible|libre)|\bdisponibilites?\b.{0,40}\b(travaux|projet|"
        r"printemps|ete|automne|semaine|mois)\b",
        1,
    ),
    _r(
        "ds-projet",
        _DS,
        "décrit un projet à réaliser",
        "tout",
        r"\b(nouveau|petit|gros|futur) projet\b|\bprojet de\b|\bon (voudrait|veut|aimerait|planifie|prevoit)\b|"
        r"\bnous (voulons|planifions|prevoyons|cherchons|aimerions)\b|\bje (veux|voudrais|cherche|planifie)\b",
        1,
    ),
    _r(
        "ds-service",
        _DS,
        "mentionne un service offert (installation, entretien, peinture, plomberie…)",
        "tout",
        r"\b(cloture|paysag\w*|peintur\w*|plomb\w*|deneig\w*|pelouse|gazon|terrasse|patio|abri d'auto|menuiser\w*|"
        r"nettoyage|installation|remplacement|reparation|entretien|sous-sol|chauffe-eau|drain\w*|salle de bain|"
        r"cuisine|garage|escalier|balcon|haie|arbres?)\b",
        1,
    ),
    _r(
        "ds-anglais",
        _DS,
        "demande de soumission en anglais",
        "tout",
        r"\b(quote|free estimate|estimate for|how much (would|does|for)|looking for a (quote|price))\b",
        3,
    ),
    _r(
        "ds-contre-reponse",
        _DS,
        "parle d'une soumission déjà reçue (plutôt une réponse)",
        "tout",
        r"\b(votre|la|cette) soumission\b|\bsuite a (votre|notre)\b|\bmerci pour (votre|la)\b",
        -2,
    ),
    # ------------------------------------------------------------------------------------------- plainte
    _r(
        "pl-mot-plainte",
        _PL,
        "emploie le mot plainte, mise en demeure, avocat ou poursuite",
        "tout",
        r"\b(plainte|mise en demeure|avocat|poursuite|poursuivre|tribunal|petites creances|protection du consommateur|"
        r"recours)\b",
        3,
    ),
    _r(
        "pl-mecontent",
        _PL,
        "exprime son mécontentement ou sa déception",
        "tout",
        r"\b(mecontent\w*|insatisf\w*|decu\w*|deception|inacceptable|inadmissible|scandaleu\w*|honteu\w*|"
        r"inexcusable|pas satisfait\w*|pas content\w*|tres fache\w*|furieu\w*|en colere|ecoeur\w*|decevant\w*|"
        r"catastroph\w*)\b",
        3,
    ),
    _r(
        "pl-travail",
        _PL,
        "reproche un travail mal fait ou un dommage",
        "tout",
        r"\b(mal fait\w*|bacle\w*|travail (de mauvaise|incomplet|neglige|baclé)|mauvaise qualite|defectueu\w*|"
        r"endommag\w*|abime\w*|brise\w*|casse\w*|degats?|dommages?|fuite|infiltration|inondation|moisissure)\b",
        2,
    ),
    _r(
        "pl-danger",
        _PL,
        "signale un danger ou une blessure",
        "tout",
        r"\b(danger\w*|blessure|blesse\w*|accident|risque pour la securite|securitaire|incendie|electrocut\w*)\b",
        2,
    ),
    _r(
        "pl-retard",
        _PL,
        "reproche un retard ou l'absence de suivi",
        "tout",
        r"\b(toujours pas|aucune nouvelle|aucun retour|pas de retour|jamais rappele\w*|personne ne (rappelle|repond)|"
        r"ne rappelle (jamais|pas)|ca fait (deja )?\w+ (semaines|jours|mois)|encore en retard|retard\w* inacceptable|"
        r"promis pour|vous aviez promis|n'est jamais venu)\b",
        2,
    ),
    _r(
        "pl-avis",
        _PL,
        "menace de publier un avis ou de contacter un organisme",
        "tout",
        r"\b(avis negatif|mauvais avis|mauvaise critique|mauvaise evaluation|reseaux sociaux|le bureau d'ethique|"
        r"office de la protection|je vais (laisser|publier|ecrire|mettre|partager)|jamais plus|"
        r"ne recommanderai? (a personne|pas))\b",
        2,
    ),
    _r(
        "pl-remboursement",
        _PL,
        "exige un remboursement, une compensation ou un correctif",
        "tout",
        r"\b(rembours\w*|dedommag\w*|compensation|reprendre le travail|reprise des travaux|corriger (le|ce|les)|"
        r"reglions? (ca|cette)|exige\w*)\b",
        2,
    ),
    _r(
        "pl-anglais",
        _PL,
        "plainte en anglais",
        "tout",
        r"\b(complaint|unacceptable|disappointed|refund|lawyer|damage\w*|terrible service|very upset)\b",
        3,
    ),
    # ------------------------------------------------------------------------------- facture fournisseur
    _r(
        "ff-objet",
        _FF,
        "l'objet parle de facture, de relevé de compte ou de paiement dû",
        "objet",
        r"\b(facture|invoice|releve de compte|statement|rappel de paiement|payment reminder|avis de paiement|"
        r"paiement en retard|solde|compte en souffrance|avis d'echeance)\b",
        3,
    ),
    _r(
        "ff-facture-corps",
        _FF,
        "cite une facture ou un relevé avec son numéro",
        "corps",
        r"\b(facture|invoice|releve)\b.{0,15}(no|n°|numero|#|\d{3,})|\b(inv|fact|fa)-?\d{3,}\b|"
        r"\b(notre|la|ci-jointe?) facture\b|\bci-joint\w* (notre|la|le|votre) (facture|releve)",
        2,
    ),
    _r(
        "ff-taxes",
        _FF,
        "mentionne les taxes (TPS, TVQ) d'une facturation",
        "corps",
        r"\b(tps|tvq|taxes? (incluses?|applicables?)|numero de (tps|tvq)|gst|hst|qst)\b",
        2,
    ),
    _r(
        "ff-montant-du",
        _FF,
        "réclame un montant dû ou une échéance de paiement",
        "corps",
        r"\b(montant (total|du|a payer|exigible)|solde (du|a payer|impaye|en souffrance)|a payer (avant|d'ici)|"
        r"payable (a|dans|au)|echeance|conditions? de paiement|net ?(15|30|45|60)|amount due|due (date|on|upon)|"
        r"overdue|paiement (est )?en retard|en souffrance)\b",
        2,
    ),
    _r(
        "ff-moyen-paiement",
        _FF,
        "indique comment payer (virement, chèque, Interac)",
        "corps",
        r"\b(virement|cheque|e-?transfert|e-?transfer|interac|paiement par|payment by|cheque payable)\b",
        1,
    ),
    _r(
        "ff-bon-livraison",
        _FF,
        "bon de livraison ou de commande accompagné d'une facture",
        "corps",
        r"\b(bon de livraison|livraison no|bl no)\b",
        1,
    ),
    # -------------------------------------------------------------------- confirmation d'un fournisseur
    _r(
        "cf-confirmation",
        _CF,
        "le fournisseur confirme ou accuse réception d'une commande",
        "tout",
        r"\b(confirmation de (votre |la )?commande|accuse de reception|order confirmation|nous avons (bien )?recu "
        r"(votre|le) (bon de )?commande|votre commande (a ete |est |sera )?(bien )?(confirmee|enregistree|recue|"
        r"acceptee|expediee|prete|en preparation)|commande confirmee)\b",
        4,
    ),
    _r(
        "cf-livraison",
        _CF,
        "donne une date ou un délai de livraison",
        "tout",
        r"\b(livraison (prevue|estimee|confirmee|le)|date de livraison|sera livree?|seront livre\w*|"
        r"expedition (prevue|le)|delai de livraison|numero de suivi|tracking|expedie\w* le|prete pour (ramassage|"
        r"livraison)|ramassage)\b",
        2,
    ),
    _r(
        "cf-rupture",
        _CF,
        "annonce une rupture, un report ou une substitution",
        "tout",
        r"\b(rupture de stock|en rupture|backorder|retard de livraison|livraison (reportee|retardee)|reporte\w*|"
        r"substitut\w*|produit equivalent|remplace par|indisponible chez|manufacturier)\b",
        2,
    ),
    _r(
        "cf-reference-po",
        _CF,
        "cite une référence de bon de commande (PO, BC)",
        "tout",
        r"\b(po|bc)[- ]?\d{4}[- ]?\d{2,}|\b(po|bc)[- ]?\d{3,}|\bbon de commande (no|n°|numero|#) ?\w+",
        2,
    ),
    _r(
        "cf-notre-ref",
        _CF,
        "ton de fournisseur (« votre commande », « vos produits »)",
        "corps",
        r"\b(votre commande|your order|vos produits|nous vous (livrerons|expedierons|confirmons))\b",
        1,
    ),
    # ------------------------------------------------------------------------------- commande de matériaux
    _r(
        "cm-commander",
        _CM,
        "demande de commander ou d'acheter",
        "tout",
        r"\b(commander|commande de|a commander|racheter|acheter|achat de|passer une commande|placer une commande|"
        r"bon de commande|faire une commande|reapprovisionn\w*)\b",
        3,
    ),
    _r(
        "cm-besoin",
        _CM,
        "exprime un besoin de matériel ou de fournitures",
        "tout",
        r"\b(on a besoin|j'ai besoin|il (nous )?faut|il manque|on manque|manque de|manque d'|plus de stock|stock "
        r"(bas|insuffisant)|rupture au depot|fournitures?|materiaux|materiel|quincaillerie)\b",
        2,
    ),
    _r(
        "cm-quantite",
        _CM,
        "indique des quantités de matériel",
        "corps",
        r"\b\d+ ?(x |sacs?|palettes?|boites?|rouleaux?|feuilles?|pieces?|unites?|verges?|pieds|planches?|"
        r"gallons?|seaux|tuyaux|poteaux|panneaux|litres?)\b",
        2,
    ),
    _r(
        "cm-chantier",
        _CM,
        "rattache le besoin à un chantier ou à une livraison au chantier",
        "tout",
        r"\b(pour le chantier|chantier de|livraison (au|sur le) chantier|a livrer (au|sur)|pour l'equipe|chez le "
        r"client)\b",
        1,
    ),
    _r(
        "cm-recu",
        _CM,
        "reçu d'achat terrain à rattacher",
        "tout",
        r"\b(recu d'achat|facture de caisse|j'ai achete|achat terrain|rembourse(r|ment)? (mon|l')achat)\b",
        3,
    ),
    _r(
        "cm-contre-fournisseur",
        _CM,
        "ton de fournisseur confirmant une commande (plutôt une confirmation)",
        "tout",
        r"\b(nous avons (bien )?recu votre|confirmation de commande|accuse de reception|sera livree?)\b",
        -3,
    ),
    # --------------------------------------------------------------------------------- réponse d'un client
    _r(
        "rc-objet-re", _RC, "l'objet est une réponse dans un fil (Re:, TR:)", "objet", r"^\s*(re|tr|rép|rep|fwd?) ?:", 1
    ),
    _r(
        "rc-remerciement",
        _RC,
        "remercie ou répond à un message de l'entreprise",
        "corps",
        r"\b(merci (pour|de) (votre|ton) (message|reponse|courriel|appel|retour|rapidite|suivi)|suite a (votre|notre) "
        r"(appel|message|courriel|conversation|visite|rencontre|echange)|comme convenu|tel que convenu|tel que discute|"
        r"en reponse a)\b",
        3,
    ),
    _r(
        "rc-confirmation",
        _RC,
        "confirme, accepte ou refuse ce qui était proposé",
        "corps",
        r"\b(je (vous )?confirme|nous confirmons|c'est confirme|ca me va|ca fonctionne|ca marche|d'accord pour|"
        r"ok pour|oui pour|parfait pour|j'accepte|nous acceptons|on accepte|je decline|nous declinons|"
        r"je ne pourrai pas|on ne pourra pas|je dois (annuler|reporter|decaler|deplacer)|pouvons-nous (reporter|"
        r"deplacer|changer)|n'est plus necessaire|nous allons passer notre tour)\b",
        3,
    ),
    _r(
        "rc-photos",
        _RC,
        "envoie les photos ou renseignements demandés",
        "corps",
        r"\b(voici (les|des|mes) (photos?|images?|informations?|renseignements?)|photos? (en|ci-)joint\w*|"
        r"en piece jointe|ci-joint les (photos|plans|mesures)|comme demande)\b",
        3,
    ),
    _r(
        "rc-soumission-recue",
        _RC,
        "parle de la soumission ou du rendez-vous déjà échangé",
        "corps",
        r"\b(votre soumission|la soumission (recue|que vous)|notre rendez-vous|le rendez-vous de|votre visite|"
        r"votre technicien|votre equipe est (venue|passee))\b",
        2,
    ),
    _r(
        "rc-court",
        _RC,
        "message très court d'acquiescement",
        "corps",
        r"^\W*(ok|oui|non|d'accord|parfait|merci|bien recu|recu|super|entendu|noted?|thanks?|sounds good)\b"
        r"[\w\s,.!']{0,60}$",
        3,
    ),
    # ------------------------------------------------------------------------- pourriel / hameçonnage
    _r(
        "ph-lien-action",
        _PH,
        "invite à cliquer sur un lien ou à se connecter",
        "tout",
        r"\b(cliquez (ici|sur)|click (here|below|on)|connectez-vous|log ?in (now|here)|ouvrez le lien|"
        r"telechargez (la piece|le document|maintenant)|suivez ce lien)\b",
        3,
    ),
    _r(
        "ph-compte",
        _PH,
        "alerte de compte, de mot de passe ou de sécurité",
        "tout",
        r"\b(mot de passe (expire|va expirer|expirera)|password (expires?|will expire)|compte (suspendu|bloque|"
        r"desactive|restreint|compromis|limite)|account (suspended|locked|limited)|activite (suspecte|inhabituelle)|"
        r"connexion inhabituelle|verifi\w+ (votre|ton|vos) (compte|identite|informations?|acces)|confirmer votre "
        r"identite|mettre a jour (vos|votre) (informations?|paiement|carte|dossier bancaire|compte)|boite (de "
        r"courriel )?(pleine|presque pleine))\b",
        4,
    ),
    _r(
        "ph-argent",
        _PH,
        "promesse d'argent, de gain, de remboursement ou de paiement en attente",
        "tout",
        r"\b(vous avez gagne|felicitations|loterie|heritage|prince|carte[- ]cadeau|gift card|bitcoin|crypto\w*|"
        r"investissement garanti|rendement garanti|gagnez de l'argent|revenu passif|remboursement (en attente|"
        r"d'impot)|paiement en attente|transfert (urgent|confidentiel)|virement urgent|frais de dossier|"
        r"avance de fonds|beneficiaire)\b",
        4,
    ),
    _r(
        "ph-livraison-colis",
        _PH,
        "faux avis de colis ou de livraison",
        "tout",
        r"\b(colis (en attente|bloque|retenu)|livraison (echouee|en attente de paiement|impossible)|frais de douane|"
        r"suivi de votre colis)\b",
        3,
    ),
    _r(
        "ph-urgence",
        _PH,
        "pression d'urgence (24 heures, action requise, dernière chance)",
        "tout",
        r"\b(action requise|dans les (24|48) heures|derniere chance|immediatement ou|sans delai sous peine|"
        r"agissez maintenant|urgent(e)?\s*!|act now|within 24 hours|dernier avis|avis final)\b",
        2,
    ),
    _r(
        "ph-commercial",
        _PH,
        "sollicitation commerciale de masse (promotion, SEO, marketing)",
        "tout",
        r"\b(offre exclusive|offre limitee|promotion|promo\b|rabais exceptionnel|aubaine|soldes?|infolettre|"
        r"newsletter|se desinscrire|desabonner|desabonnement|unsubscribe|vous recevez (ce|cet) (courriel|message) "
        r"(parce que|car)|referencement|seo\b|premiere page de google|augmenter (vos|votre) (ventes|visibilite|"
        r"trafic|clientele)|prospection|liste de (courriels|contacts)|webinaire|gratuit pour une duree limitee|"
        r"marketing digital|nos services de (marketing|publicite|redaction))\b",
        3,
    ),
    _r("ph-liens-multiples", _PH, "plusieurs liens dans le message", "corps", r"(https?://\S+[\s\S]*){2,}", 2),
    _r(
        "ph-lien-raccourci",
        _PH,
        "lien raccourci ou adresse IP",
        "corps",
        r"\b(bit\.ly|tinyurl|t\.co|goo\.gl|ow\.ly|rb\.gy)/|https?://\d{1,3}(\.\d{1,3}){3}",
        3,
    ),
    _r(
        "ph-president",
        _PH,
        "demande de virement ou de cartes cadeaux « du patron » sans passer par le circuit",
        "tout",
        r"\b(sans en parler a|garde ca (entre nous|confidentiel)|je suis en reunion .{0,30}(virement|carte|achat)|"
        r"discretion absolue|achetez .{0,20}cartes?[- ]cadeaux?|virement (immediat|ce matin))\b",
        4,
    ),
    # ------------------------------------------------------------------------------------------- interne
    _r(
        "in-vie-d-equipe",
        _IN,
        "vocabulaire de vie d'équipe (réunion, horaire, quart, congé)",
        "tout",
        r"\b(reunion|rencontre d'equipe|ordre du jour|horaire|quart de travail|conge|vacances|note de service|"
        r"n'oubliez pas|rappel (pour|a) (l'equipe|tous)|equipe de demain|pour info|fyi|a tous|camion|atelier|"
        r"stationnement|cafe|diner d'equipe|formation interne|feuille de temps)\b",
        2,
    ),
    _r(
        "in-ton-collegue",
        _IN,
        "ton de collègue (tutoiement, prénom, transfert)",
        "corps",
        r"\b(salut|allo|yo|bonne journee a tous|je te (laisse|transfere|envoie)|je t'envoie|dis-moi|tu peux|"
        r"peux-tu|t'as|on se voit)\b",
        1,
    ),
    # --------------------------------------------------------------------------------------------- autre
    _r(
        "au-emploi",
        _AU,
        "candidature, curriculum vitæ ou offre d'emploi",
        "tout",
        r"\b(candidature|curriculum|c\.?v\.?\b|lettre de motivation|postuler|poste de|offre d'emploi|stage|"
        r"travailler pour vous|ouvert a de nouvelles opportunites|recrutement)\b",
        4,
    ),
    _r(
        "au-partenariat",
        _AU,
        "offre de partenariat, commandite ou don",
        "tout",
        r"\b(partenariat|collaboration|commandite\w*|demande de don|fondation|benefice|souper-?benefice|"
        r"organisme (sans but lucratif|communautaire)|association des|chambre de commerce)\b",
        4,
    ),
    _r(
        "au-automatique",
        _AU,
        "réponse automatique, absence du bureau ou accusé de lecture",
        "tout",
        r"\b(reponse automatique|automatic reply|out of office|absent\w* du bureau|je suis absent|"
        r"accuse de lecture|read receipt|je serai de retour le|ne pas repondre a ce message)\b",
        5,
    ),
)

JEU_V1 = JeuRegles("v1", REGLES_V1)
