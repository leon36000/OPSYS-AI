from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path


_GENESIS = "0" * 64
_REQUIRED_KEYS = {"sequence", "previous_hash", "event", "event_hash"}


class LedgerCorruptionError(ValueError):
    """Levée lorsqu'une incohérence est détectée dans le journal."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _event_hash(sequence: int, previous_hash: str, event: dict) -> str:
    payload = {
        "sequence": sequence,
        "previous_hash": previous_hash,
        "event": event,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _corruption(line_number: int, nature: str) -> LedgerCorruptionError:
    return LedgerCorruptionError(f"ligne {line_number}: {nature}")


def _read_ledger(path: Path) -> dict:
    if not path.exists():
        return {"sequence": -1, "head_hash": _GENESIS, "events": []}

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise LedgerCorruptionError(f"lecture du journal impossible: {exc}") from exc

    if content == "":
        return {"sequence": -1, "head_hash": _GENESIS, "events": []}

    if not content.endswith("\n"):
        raise _corruption(1, "fin de ligne absente")

    lines = content.splitlines()
    events: list[dict] = []
    previous_hash = _GENESIS

    for index, line in enumerate(lines):
        line_number = index + 1

        if not line:
            raise _corruption(line_number, "ligne vide")

        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _corruption(line_number, f"JSON invalide ({exc})") from exc

        if not isinstance(record, dict):
            raise _corruption(line_number, "enregistrement non objet")

        if set(record) != _REQUIRED_KEYS:
            raise _corruption(line_number, "clés d'enregistrement incorrectes")

        canonical_record = _canonical_json(record)
        if line != canonical_record:
            raise _corruption(line_number, "JSON non canonique")

        sequence = record["sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise _corruption(line_number, "sequence invalide")
        if sequence != index:
            raise _corruption(
                line_number,
                f"sequence inattendue (attendu {index}, obtenu {sequence})",
            )

        record_previous_hash = record["previous_hash"]
        if not isinstance(record_previous_hash, str):
            raise _corruption(line_number, "previous_hash invalide")

        # Pas de contrôle "previous_hash déjà vu" séparé (bifurcation) : mesuré
        # avant d'écrire cette version — structurellement redondant avec le
        # contrôle ci-dessous. `previous_hash` doit égaler EXACTEMENT la
        # valeur courante attendue (déterminée par la marche depuis la
        # genèse) ; deux lignes ne peuvent jamais satisfaire ce contrôle avec
        # la MÊME valeur, sauf collision SHA-256 réelle (hors modèle de
        # menace — si SHA-256 est cassé, ce contrôle séparé ne protège pas
        # plus que celui-ci). Mutation-testé : neutraliser un tel contrôle
        # séparé ne faisait jamais rougir aucun test réaliste.
        if record_previous_hash != previous_hash:
            raise _corruption(line_number, "chaîne rompue: previous_hash inattendu")

        event = record["event"]
        if not isinstance(event, dict):
            raise _corruption(line_number, "event invalide")

        stored_hash = record["event_hash"]
        if not isinstance(stored_hash, str):
            raise _corruption(line_number, "event_hash invalide")

        calculated_hash = _event_hash(sequence, record_previous_hash, event)
        if calculated_hash != stored_hash:
            raise _corruption(
                line_number,
                "modification: event_hash ne correspond pas au contenu",
            )

        previous_hash = stored_hash
        events.append(event)

    return {
        "sequence": len(events) - 1,
        "head_hash": previous_hash,
        "events": events,
    }


def append_event(path: Path, event: dict) -> str:
    """Ajoute un événement au journal append-only situé à `path`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(f"{path}.lock")

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            state = _read_ledger(path)
            sequence = state["sequence"] + 1
            previous_hash = state["head_hash"]
            event_hash = _event_hash(sequence, previous_hash, event)

            record = {
                "sequence": sequence,
                "previous_hash": previous_hash,
                "event": event,
                "event_hash": event_hash,
            }
            line = _canonical_json(record) + "\n"

            with path.open("a", encoding="utf-8", newline="") as ledger_file:
                ledger_file.write(line)
                ledger_file.flush()
                os.fsync(ledger_file.fileno())

            return event_hash
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def replay_state(path: Path) -> dict:
    """Rejoue le journal depuis le début et retourne son état résultant."""
    return _read_ledger(Path(path))
