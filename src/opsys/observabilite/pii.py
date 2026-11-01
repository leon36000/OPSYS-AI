"""Masquage déterministe des renseignements personnels : port `MasqueurPII`, masqueur par motifs, coffre réversible.

Principes (Loi 25, minimisation) :
- **Jetons stables.** Chaque valeur détectée est remplacée par `[[ETIQUETTE:hmac12]]`, où `hmac12` est le début d'un
  HMAC-SHA256 de la valeur NORMALISÉE (chiffres seuls pour un NAS, minuscules pour un courriel…) avec la clé locale
  (`cle_locale`, usage `pii/v1`). Même valeur, même jeton : on peut corréler deux traces sans jamais exposer la valeur ;
  la clé change, les jetons changent. Un NAS écrit « 123-456-782 » ou « 123 456 782 » donne le même jeton.
- **Deux modes.** `IRREVERSIBLE` (défaut) : la valeur n'est gardée nulle part. `REVERSIBLE_COFFRE` : la valeur est aussi
  déposée dans un coffre (port `CoffrePII`) sous le jeton, pour qu'un administrateur la retrouve ; jamais pour un
  secret (clé, jeton, mot de passe) : toujours irréversible, même dans ce mode.
- **Le résultat ne porte jamais la valeur brute** : `ResultatMasquage` liste catégories, jetons et positions, pas les
  valeurs, de sorte qu'un journal du résultat ne fuit rien.
- **Un port, pas un moteur unique.** `MasqueurPII` est le contrat ; `MasqueurMotifs` est l'implémentation locale (hors
  ligne, sans dépendance). Presidio (NER) se branche plus tard derrière le même port ; `MasqueurEnChaine` compose
  plusieurs masqueurs (motifs d'abord, NER ensuite).

Limites honnêtes : voir `pii_detecteurs.py` et docs/architecture/OBSERVABILITE-MCP.md. Les motifs ratent les noms
propres sans civilité et les adresses en mots ; le masquage de structures coupe aussi les clés qui ressemblent à des
secrets (`password`, `token`…) sans regarder leur valeur.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import hmac
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from ..secrets_coffre import masquage as masquage_coffre
from .erreurs import ErreurObservabilite
from .pii_detecteurs import (
    CATEGORIES,
    DETECTEURS,
    ETIQUETTES,
    TAILLE_MAX_TEXTE,
    Detection,
    detecteur_lexique,
    resoudre,
)

LONGUEUR_JETON = 12
PROFONDEUR_MAX = 8
ELEMENTS_MAX = 2000
MARQUE_TRONQUE = "[[TRONQUE]]"
_JETON = re.compile(r"\[\[([A-Z]{2,12}):([0-9a-f]{12})\]\]")
# Une clé de dictionnaire qui nomme un secret : la valeur entière est remplacée, quel que soit son contenu.
CLE_SECRETE = re.compile(
    r"(?i)(?:^|[_.-])(?:password|passwd|pwd|secret|token|jeton|api[_-]?key|apikey|authorization|cookie|"
    r"mot[_-]?de[_-]?passe|cle|private[_-]?key)(?:$|[_.-])"
)


class ModeMasquage(enum.StrEnum):
    IRREVERSIBLE = "irreversible"
    REVERSIBLE_COFFRE = "reversible_coffre"


@dataclasses.dataclass(frozen=True)
class Remplacement:
    categorie: str
    jeton: str
    debut: int
    fin: int
    reversible: bool = False


@dataclasses.dataclass(frozen=True)
class ResultatMasquage:
    """Texte masqué et la liste des remplacements (catégorie, jeton, position dans le texte d'ORIGINE). Jamais la
    valeur."""

    texte: str
    remplacements: tuple[Remplacement, ...] = ()

    @property
    def par_categorie(self) -> dict[str, int]:
        compte: dict[str, int] = {}
        for r in self.remplacements:
            compte[r.categorie] = compte.get(r.categorie, 0) + 1
        return compte


@runtime_checkable
class MasqueurPII(Protocol):
    """Contrat d'un masqueur : motifs locaux aujourd'hui, Presidio demain, sans changer les appelants."""

    identite: str

    def masquer(self, texte: str, *, mode: ModeMasquage = ModeMasquage.IRREVERSIBLE) -> ResultatMasquage: ...

    def contient_pii(self, texte: str) -> bool: ...


@runtime_checkable
class CoffrePII(Protocol):
    """Où va la valeur d'un jeton réversible. Jamais une base de traces : un coffre chiffré, à accès journalisé."""

    def deposer(self, jeton: str, categorie: str, valeur: str) -> None: ...

    def reveler(self, jeton: str, *, acteur: str) -> str: ...


class CoffrePIIMemoire:
    """Double de test du coffre (aucun chiffrement : à ne jamais utiliser en production)."""

    def __init__(self) -> None:
        self._valeurs: dict[str, str] = {}
        self.acces: list[tuple[str, str]] = []

    def deposer(self, jeton: str, categorie: str, valeur: str) -> None:
        self._valeurs.setdefault(jeton, valeur)

    def reveler(self, jeton: str, *, acteur: str) -> str:
        self.acces.append((acteur, jeton))
        if jeton not in self._valeurs:
            raise ErreurObservabilite("REJ-OBS-COFFRE-PII-INCONNU", "jeton inconnu du coffre")
        return self._valeurs[jeton]

    def __repr__(self) -> str:
        return f"CoffrePIIMemoire({len(self._valeurs)} jetons)"


class CoffrePIIDuCoffre:
    """Adaptateur sur le coffre de secrets chiffré existant (`opsys.secrets_coffre`) : AES-256-GCM, accès journalisé.

    Chaque valeur devient un secret `pii.<catégorie>.<hmac12>` (service « autre ») ; `deposer` est idempotent (un jeton
    déjà déposé n'est pas redéposé). `reveler` exige un administrateur actif relu en base, passe par `coffre.utiliser`
    (journal d'accès `coffre_acces`) et ne rend la valeur qu'à l'appelant : aucun export en clair n'existe.
    """

    def __init__(self, fabrique_cnx: Callable[[], Any], *, acteur_depot: str, cle: Any = None) -> None:
        self._fabrique, self._acteur_depot, self._cle = fabrique_cnx, acteur_depot, cle

    @staticmethod
    def _nom(jeton: str, categorie: str | None = None) -> str:
        m = _JETON.fullmatch(jeton)
        if not m:
            raise ErreurObservabilite("REJ-OBS-COFFRE-PII-INCONNU", "jeton de masquage mal formé")
        etiquette = m.group(1).lower()
        return f"pii.{etiquette}.{m.group(2)}"

    def deposer(self, jeton: str, categorie: str, valeur: str) -> None:
        from ..secrets_coffre import coffre
        from ..secrets_coffre.erreurs import CoffreErreur

        nom = self._nom(jeton, categorie)
        try:
            with self._fabrique() as cnx:
                coffre.definir(cnx, acteur=self._acteur_depot, nom=nom, service="autre", valeur=valeur, cle=self._cle)
        except CoffreErreur as exc:
            if exc.code == "COFFRE_SECRET_EXISTE":
                return
            raise ErreurObservabilite("REJ-OBS-COFFRE-PII-REFUSE", f"dépôt refusé par le coffre : {exc.code}") from None

    def reveler(self, jeton: str, *, acteur: str) -> str:
        from .. import identite
        from ..secrets_coffre import coffre
        from ..secrets_coffre.erreurs import CoffreErreur

        nom = self._nom(jeton)
        with self._fabrique() as cnx:
            personne = identite.personne_active(cnx, acteur) if isinstance(acteur, str) else None
        if personne is None or not personne.roles.intersection(coffre.ROLES_ADMIN):
            raise ErreurObservabilite("REJ-OBS-COFFRE-PII-REFUSE",
                                      "administrateur actif requis pour révéler une valeur")
        try:
            with coffre.utiliser(usage="pii:reveler", acteur=acteur, nom=nom, cle=self._cle) as valeur:
                return str(valeur)
        except CoffreErreur as exc:
            raise ErreurObservabilite("REJ-OBS-COFFRE-PII-INCONNU", f"révélation refusée : {exc.code}") from None


class MasqueurMotifs:
    """Masqueur local par motifs et validations (voir `pii_detecteurs`). Déterministe, hors ligne, sans dépendance."""

    identite = "opsys.motifs-quebec/v1"

    def __init__(self, cle: bytes, *, coffre: CoffrePII | None = None, lexique: Iterable[str] = (),
                 categories: Sequence[str] | None = None) -> None:
        if not isinstance(cle, bytes) or len(cle) != 32:
            raise ErreurObservabilite("REJ-OBS-CLE-INVALIDE", "clé de masquage : 32 octets attendus (usage pii/v1)")
        inconnues = set(categories or ()) - set(CATEGORIES)
        if inconnues:
            raise ErreurObservabilite("REJ-OBS-ARGUMENT-INVALIDE", f"catégories inconnues : {sorted(inconnues)}")
        self._cle = cle
        self._coffre = coffre
        self._categories = frozenset(categories) if categories else frozenset(CATEGORIES)
        self._lexique = detecteur_lexique(lexique)

    def __repr__(self) -> str:  # jamais la clé
        return f"MasqueurMotifs(categories={len(self._categories)}, coffre={'oui' if self._coffre else 'non'})"

    # -- détection --------------------------------------------------------------------------------------------------
    def detecter(self, texte: str) -> list[Detection]:
        if not isinstance(texte, str):
            raise ErreurObservabilite("REJ-OBS-ARGUMENT-INVALIDE", "texte attendu")
        texte = texte[:TAILLE_MAX_TEXTE]
        trouvees: list[Detection] = []
        for detecteur in (*DETECTEURS, self._lexique):
            trouvees.extend(d for d in detecteur(texte) if d.categorie in self._categories)
        return resoudre(trouvees)

    def contient_pii(self, texte: str) -> bool:
        """Vrai si un renseignement non masqué subsiste. Un jeton `[[…]]` bien formé n'en est pas un."""
        return bool(self.detecter(_JETON.sub(" ", texte)))

    # -- masquage ---------------------------------------------------------------------------------------------------
    def jeton(self, categorie: str, normalisee: str) -> str:
        condense = hmac.new(self._cle, f"{categorie}\x1f{normalisee}".encode(), hashlib.sha256).hexdigest()
        return f"[[{ETIQUETTES[categorie]}:{condense[:LONGUEUR_JETON]}]]"

    def masquer(self, texte: str, *, mode: ModeMasquage = ModeMasquage.IRREVERSIBLE) -> ResultatMasquage:
        if not isinstance(texte, str):
            raise ErreurObservabilite("REJ-OBS-ARGUMENT-INVALIDE", "texte attendu")
        mode = ModeMasquage(mode)
        if mode is ModeMasquage.REVERSIBLE_COFFRE and self._coffre is None:
            raise ErreurObservabilite("REJ-OBS-COFFRE-PII-REFUSE", "mode réversible sans coffre configuré")
        tronque = len(texte) > TAILLE_MAX_TEXTE
        texte = masquage_coffre.masquer_texte(texte[:TAILLE_MAX_TEXTE])  # secrets vivants du coffre : toujours d'abord
        morceaux: list[str] = []
        remplacements: list[Remplacement] = []
        curseur = 0
        for d in self.detecter(texte):
            jeton = self.jeton(d.categorie, d.normalisee)
            reversible = mode is ModeMasquage.REVERSIBLE_COFFRE and d.categorie != "secret"
            if reversible:
                assert self._coffre is not None
                self._coffre.deposer(jeton, d.categorie, texte[d.debut:d.fin])
            morceaux.append(texte[curseur:d.debut])
            morceaux.append(jeton)
            remplacements.append(Remplacement(d.categorie, jeton, d.debut, d.fin, reversible))
            curseur = d.fin
        morceaux.append(texte[curseur:])
        if tronque:
            morceaux.append(MARQUE_TRONQUE)
        return ResultatMasquage("".join(morceaux), tuple(remplacements))

    def masquer_structure(self, valeur: Any, *, mode: ModeMasquage = ModeMasquage.IRREVERSIBLE) -> Any:
        """Copie de `valeur` (JSON : dict, liste, texte, nombre…) dont tout texte, CLÉS comprises, est masqué.

        Une clé qui nomme un secret remplace sa valeur entière. Profondeur et taille sont bornées (au-delà : marque
        `[[TRONQUE]]`) ; un objet d'un type inconnu devient le nom de son type, jamais son `repr`."""
        compteur = [0]
        return self._structure(valeur, mode, 0, compteur)

    def _structure(self, valeur: Any, mode: ModeMasquage, profondeur: int, compteur: list[int]) -> Any:
        compteur[0] += 1
        if profondeur > PROFONDEUR_MAX or compteur[0] > ELEMENTS_MAX:
            return MARQUE_TRONQUE
        if isinstance(valeur, str):
            return self.masquer(valeur, mode=mode).texte
        if valeur is None or isinstance(valeur, (bool, int, float)):
            return valeur
        if isinstance(valeur, Mapping):
            sortie: dict[str, Any] = {}
            for cle, sous in valeur.items():
                cle_masquee = self.masquer(str(cle), mode=ModeMasquage.IRREVERSIBLE).texte
                if CLE_SECRETE.search(str(cle)) and sous not in (None, "", False):
                    sortie[cle_masquee] = self.jeton("secret", str(sous)) if isinstance(sous, str) else "[[SECRET]]"
                else:
                    sortie[cle_masquee] = self._structure(sous, mode, profondeur + 1, compteur)
            return sortie
        if isinstance(valeur, (list, tuple, set, frozenset)):
            return [self._structure(v, mode, profondeur + 1, compteur) for v in valeur]
        return f"<{type(valeur).__name__}>"


class MasqueurEnChaine:
    """Compose des masqueurs : chacun reçoit le texte déjà masqué par le précédent (motifs d'abord, NER ensuite).

    C'est le point de branchement de Presidio : un `MasqueurPresidio` respectant `MasqueurPII` s'ajoute à la fin de la
    chaîne sans toucher aux appelants. Les jetons `[[…]]` déjà posés ne sont pas retraités par un masqueur à motifs."""

    def __init__(self, *masqueurs: MasqueurPII) -> None:
        if not masqueurs or not all(isinstance(m, MasqueurPII) for m in masqueurs):
            raise ErreurObservabilite("REJ-OBS-MASQUEUR", "au moins un masqueur conforme à MasqueurPII est requis")
        self._masqueurs = masqueurs
        self.identite = "chaine:" + "+".join(m.identite for m in masqueurs)

    def masquer(self, texte: str, *, mode: ModeMasquage = ModeMasquage.IRREVERSIBLE) -> ResultatMasquage:
        courant, remplacements = texte, []
        for masqueur in self._masqueurs:
            resultat = masqueur.masquer(courant, mode=mode)
            courant = resultat.texte
            remplacements.extend(resultat.remplacements)
        return ResultatMasquage(courant, tuple(remplacements))

    def contient_pii(self, texte: str) -> bool:
        return any(m.contient_pii(texte) for m in self._masqueurs)
