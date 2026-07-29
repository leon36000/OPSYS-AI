import copy
import hashlib
import json
from typing import Protocol, runtime_checkable

import encodage
import verdicts
import horodatage as _horodatage

MODE_OMBRE = "ombre"
MODES = ("ombre",)


@runtime_checkable
class AdaptateurCRM(Protocol):
    """Protocol exigé par l'architecte : toute implémentation d'écriture CRM doit
    exposer ecrire(charge, horodatage) et être reconnue par isinstance."""

    def ecrire(self, charge, horodatage) -> tuple[dict | None, dict | None]:
        ...


class AdaptateurMemoire:
    """Adaptateur d'écriture vers un CRM en mémoire (mode ombre).

    Journal non borné : aucune éviction silencieuse n'est appliquée,
    car cela détruirait l'auditabilité.  Toute future politique de
    rétention devra être fail-closed (refus d'écriture) et non une
    purge automatique.

    L'objet est inerte si instancié avec un mode autre que MODES :
    la méthode ecrire refusera toute opération et le journal
    restera vide.  Ce choix garantit la prouvabilité de CA-M2-15.
    """

    def __init__(self, nom_cible, mode):
        # Pas de validation ici : l'objet peut être hors mode,
        # il sera simplement inerte (voir R1, avis architecte).
        self._nom_cible = nom_cible
        self._mode = mode
        self._journal = []

    def identifiant(self):
        """Identifiant stable, dérivé de (nom_cible, mode) par encodage
        canonique injectif.

        L'inclusion du mode garantit qu'un adaptateur ombre et un
        futur adaptateur réel pour une même cible possèdent des
        identifiants distincts. Le préfixage par longueur écarte
        les collisions de concaténation naïve."""
        return encodage.encoder_canonique(self._nom_cible, self._mode)

    def ecrire(self, charge, horodatage):
        """Valide et enregistre une écriture.

        Ordre des contrôles figé et déterministe (R4) :
        1. mode supporté (MODES),
        2. charge structurellement utilisable (dict non vide),
        3. horodatage valide (avec fuseau horaire, via _horodatage).

        En cas de succès, la mutation du journal a lieu en tout
        dernier ressort, après construction complète de l'accusé,
        afin qu'aucune exception ultérieure ne laisse un maillon
        orphelin (R2)."""
        # 1. Mode dans MODES → sinon REJ-ADAPTATEUR-INDISPONIBLE
        if self._mode not in MODES:
            return (None, verdicts.construire_verdict('REJ-ADAPTATEUR-INDISPONIBLE'))

        # 2. Charge structurellement utilisable : nous exigeons un dict
        #    non vide.  Aucun schéma de charge n'étant gelé dans le PRD,
        #    nous n'effectuons aucune validation par champ ; toute
        #    validation métier doit être réalisée en amont (R3).
        if not isinstance(charge, dict) or not charge:
            return (None, verdicts.construire_verdict('REJ-CHAMP-MANQUANT'))

        # 3. Horodatage valide (avec fuseau). Seul ValueError est capturé, et
        #    c'est SUFFISANT : valider_horodatage normalise TOUTE erreur de type
        #    en ValueError par conception (elle commence par
        #    `if not isinstance(texte, str): raise ValueError`). Mesuré sur
        #    None, entier, liste, dict, bytes et chaîne invalide : ValueError
        #    dans les six cas. Capturer TypeError en plus serait du code mort.
        try:
            horodatage_valide = _horodatage.valider_horodatage(horodatage)
        except ValueError:
            return (None, verdicts.construire_verdict('REJ-HORODATAGE-INVALIDE'))

        # 4. La charge doit franchir la frontière de sérialisation.
        #    POURQUOI ce contrôle est une VALIDATION et non un détail
        #    d'implémentation : un adaptateur simule l'écriture vers un CRM
        #    TIERS ; une donnée qui ne peut ni être copiée ni être sérialisée
        #    ne peut pas franchir cette frontière. Un dict non vide peut être
        #    structurellement valide tout en contenant un verrou, un
        #    générateur, un module, un set, des bytes ou un objet quelconque.
        #    Laisser remonter l'exception violerait la convention de TOUT le
        #    module M2 : le refus est un couple (None, verdict), jamais une
        #    exception chez l'appelant.
        #
        #    La COPIE est DANS le try, pas avant : deepcopy lève TypeError sur
        #    un objet non picklable (mesuré : threading.Lock, générateur,
        #    module) et cette exception s'échappait tant qu'elle était hors du
        #    bloc — le même défaut que celui corrigé pour json.dumps, une ligne
        #    plus haut.
        #
        #    allow_nan=False est ESSENTIEL et n'est pas un détail : par défaut
        #    json.dumps ACCEPTE inf et nan et produit {"v": Infinity}, qui
        #    n'est pas du JSON conforme. Mesuré : sans ce drapeau, une charge
        #    contenant inf/nan était acceptée et l'écriture simulée avec
        #    succès — un fail-OPEN silencieux, pire qu'une exception, car
        #    aucun CRM réel n'accepterait cette charge.
        try:
            charge_copiee = copy.deepcopy(charge)
            charge_bytes = json.dumps(
                charge_copiee, sort_keys=True, allow_nan=False
            ).encode('utf-8')
        except (TypeError, ValueError, AttributeError, copy.Error, RecursionError):
            return (None, verdicts.construire_verdict(
                'REJ-FRONTIERE-VIOLEE',
                detail="charge non copiable ou non sérialisable : elle ne peut "
                       "pas franchir la frontière vers un CRM tiers",
            ))
        empreinte = hashlib.sha256(charge_bytes).hexdigest()
        accuse = {
            "adaptateur_id": self.identifiant(),
            "horodatage": horodatage_valide,
            "charge_hash": empreinte,
            "rang": len(self._journal),
        }
        # Mutation unique, en dernière instruction (R2)
        self._journal.append(charge_copiee)
        return (accuse, None)

    def lire_journal(self):
        """Retourne les CHARGES simulées, en copies profondes, dans l'ordre.

        Le journal conserve la charge elle-même et non son empreinte :
        l'intérêt du mode ombre est de pouvoir auditer CE QUI SERAIT
        écrit vers le CRM tiers. Ne garder que le sha256 rendrait la
        simulation invérifiable — on saurait qu'une écriture a été
        simulée, jamais laquelle. L'empreinte reste dans l'accusé pour
        permettre à l'appelant de recouper sans relire le journal.

        La copie profonde interdit à l'appelant d'altérer l'état interne
        (R5/R6) ; symétriquement ``ecrire`` copie la charge à l'entrée,
        de sorte qu'une mutation ultérieure de la charge appelante ne se
        propage pas au journal.

        Le journal n'est pas borné : à l'échelle des fixtures et de la CI
        la croissance est négligeable, et une éviction silencieuse
        détruirait l'auditabilité. Si une borne devient nécessaire, elle
        devra être fail-closed (refus d'écriture), jamais une purge.
        """
        return copy.deepcopy(self._journal)


def construire_adaptateur(nom_cible, mode):
    """Fabrique nominale d'adaptateur, FAIL-CLOSED sur le mode.

    Un mode hors de l'énumération fermée MODES est refusé et AUCUN
    adaptateur n'est construit : la fabrique est la porte nominale et
    doit rejeter, sinon un appelant obtiendrait un objet en mode
    interdit et le refus ne surviendrait qu'au premier ``ecrire``.

    POURQUOI la double garde (ici ET dans ``ecrire``) : ``__init__`` ne
    valide pas — c'est délibéré, sinon le contrôle de mode d'``ecrire``
    deviendrait du code mort intestable (avis architecte R1). Un objet
    instancié directement en mode interdit reste donc possible, mais il
    est INERTE : ``ecrire`` le revérifie et refuse. Les deux chemins
    sont testés séparément.
    """
    if mode not in MODES:
        return None, verdicts.construire_verdict(
            "REJ-ADAPTATEUR-INDISPONIBLE",
            detail=f"mode hors énumération v1 {MODES!r} : {mode!r}",
        )
    return AdaptateurMemoire(nom_cible, mode), None
