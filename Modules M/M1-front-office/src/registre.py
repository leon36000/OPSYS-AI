import hashlib
import json
import copy
from pathlib import Path
import yaml
import horodatage
import verdicts

_TYPES_ENTREE_VALIDES = {
    "signal",
    "transition_phase",
    "lead_emis",
    "chiffrage_emis",
    "alerte",
}

_CANAUX_VALIDES = {"telephone", "courriel", "formulaire", "texte"}


def _canonical_material(entree: dict) -> bytes:
    """Retourne le JSON canonique des champs hors lignee_id, precedent_ligne_id, hash."""
    contenu = {}
    for k, v in entree.items():
        if k not in ("ligne_id", "precedent_ligne_id", "hash"):
            contenu[k] = v
    return json.dumps(
        contenu, sort_keys=True, ensure_ascii=False, default=str
    ).encode("utf-8")


def _compute_ligne_id(contenu_json: bytes, precedent_ligne_id: str | None) -> str:
    """SHA-256 du JSON canonique concaténé avec le lien précédent."""
    linkage = precedent_ligne_id if precedent_ligne_id else "GENESE"
    combined = contenu_json + b"|" + linkage.encode("ascii")
    return hashlib.sha256(combined).hexdigest()


class Registre:
    """Registre append-only hash-chaîné à état privé.

    valider_chaine() détecte toute altération partielle (contenu modifié,
    maillon rompu, suppression recousue naïvement) ; contre une réécriture
    COMPLÈTE de la suite, la détection exige la comparaison de tete() à une
    ancre conservée à l'extérieur.
    """

    def __init__(self) -> None:
        self._entrees: list[dict] = []

    def ajouter(self, entree: dict) -> str:
        """Ajoute une entrée immuable. Retourne le ligne_id (SHA-256)."""
        entree = copy.deepcopy(entree)

        # Validation type_entree
        type_entree = entree.get("type_entree")
        if type_entree not in _TYPES_ENTREE_VALIDES:
            raise ValueError(
                f"REJ-ENUM-INVALIDE: type_entree '{type_entree}' invalide"
            )

        # Validation horodatage
        horodatage_str = entree.get("horodatage")
        if horodatage_str is None:
            raise ValueError("horodatage manquant")
        horodatage.valider_horodatage(horodatage_str)

        # Préparer le lien précédent
        precedent_ligne_id = self._entrees[-1]["ligne_id"] if self._entrees else None

        # Calcul du hash intégrant le lien
        contenu_bytes = _canonical_material(entree)
        ligne_id = _compute_ligne_id(contenu_bytes, precedent_ligne_id)

        entree_stockee = entree
        entree_stockee["ligne_id"] = ligne_id
        entree_stockee["precedent_ligne_id"] = precedent_ligne_id
        self._entrees.append(entree_stockee)
        return ligne_id

    def lire(self, depuis: str | None = None) -> list:
        """Retourne une copie profonde de la portion demandée du registre."""
        if depuis is None:
            portion = list(self._entrees)
        else:
            for i, entree in enumerate(self._entrees):
                if entree.get("ligne_id") == depuis:
                    portion = self._entrees[i:]
                    break
            else:
                portion = []
        return copy.deepcopy(portion)

    def tete(self) -> str | None:
        """Retourne le ligne_id de la dernière entrée (ancre à publier)."""
        if not self._entrees:
            return None
        return self._entrees[-1]["ligne_id"]

    def valider_chaine(self, ancre_attendue: str | None = None):
        """Vérifie l'intégrité de la chaîne.

        Si ancre_attendue est fournie, compare avec tete() et échoue en cas de
        différence (pour détecter une réécriture complète).
        Retourne (True, None) si ok, sinon (False, verdict REJ-CHAINE-ALTEREE).
        """
        if not self._entrees:
            return True, None

        precedent_ligne_id = None
        for idx, entree in enumerate(self._entrees):
            if entree.get("precedent_ligne_id") != precedent_ligne_id:
                verdict = verdicts.construire_verdict(
                    "REJ-CHAINE-ALTEREE",
                    detail=(
                        f"Index {idx}: precedent_ligne_id attendu={precedent_ligne_id!r}, "
                        f"reçu={entree.get('precedent_ligne_id')!r}"
                    ),
                )
                return False, verdict

            contenu_bytes = _canonical_material(entree)
            expected = _compute_ligne_id(contenu_bytes, precedent_ligne_id)
            if expected != entree.get("ligne_id"):
                verdict = verdicts.construire_verdict(
                    "REJ-CHAINE-ALTEREE",
                    detail=(
                        f"Index {idx}: ligne_id attendu={expected!r}, "
                        f"reçu={entree.get('ligne_id')!r}"
                    ),
                )
                return False, verdict

            precedent_ligne_id = entree.get("ligne_id")

        if ancre_attendue is not None:
            current_tete = self.tete()
            if current_tete != ancre_attendue:
                verdict = verdicts.construire_verdict(
                    "REJ-CHAINE-ALTEREE",
                    detail=f"Ancre externe attendue {ancre_attendue!r}, obtenue {current_tete!r}"
                )
                return False, verdict

        return True, None

    def assert_chaine(self) -> None:
        """Lève une ValueError contenant le verdict si la chaîne est altérée."""
        ok, verdict = self.valider_chaine()
        if not ok:
            raise ValueError(str(verdict))

    def taille(self) -> int:
        """Retourne le nombre d'entrées."""
        return len(self._entrees)


def charger_signaux(chemin: str) -> list:
    """Charge les signaux depuis un fichier YAML. Exige `fictif: true`
    et valide chaque signal (signal_id, canal, horodatage, contenu_brut).
    Retourne la liste des signaux.
    """
    with open(chemin, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or not data.get("fictif") is True:
        raise ValueError("fictif manquant ou faux")

    signaux = data.get("signaux", [])
    if not isinstance(signaux, list):
        raise ValueError("signaux doit être une liste")

    for signal in signaux:
        if not isinstance(signal, dict):
            raise ValueError("chaque signal doit être un dict")
        # signal_id obligatoire
        if "signal_id" not in signal:
            raise ValueError("signal_id manquant dans un signal")
        # canal obligatoire et dans l'enum
        canal = signal.get("canal")
        if canal not in _CANAUX_VALIDES:
            raise ValueError(f"canal invalide ou manquant: {canal!r}")
        # horodatage ISO avec fuseau
        h = signal.get("horodatage")
        if h is None:
            raise ValueError("horodatage manquant dans un signal")
        horodatage.valider_horodatage(h)
        # contenu_brut non vide
        cb = signal.get("contenu_brut")
        if not isinstance(cb, str) or not cb.strip():
            raise ValueError("contenu_brut manquant ou vide dans un signal")

    return signaux
