"""Meta limitée au classement DEVICE ; reset garanti, aucun contexte générique."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from datetime import datetime

from opsys import idempotence

from . import classement_variance_appareil as c

_META = contextvars.ContextVar("m6_meta_classement_variance", default=None)


@contextmanager
def contexte_mutation(meta: idempotence.Meta):
    token = _META.set(meta)
    try:
        yield
    finally:
        _META.reset(token)


def meta_courante():
    meta = _META.get()
    if not isinstance(meta, idempotence.Meta) or not c.texte(meta.appareil) or not c.texte(meta.cle):
        raise c.Refus("CONTEXTE-MUTATION-ABSENT")
    try:
        hour = datetime.fromisoformat(meta.horodatage_appareil)
        if hour.tzinfo is None:
            raise ValueError("fuseau absent")
    except (TypeError, ValueError):
        raise c.Refus("CONTEXTE-MUTATION-ABSENT") from None
    return meta


def intention(arguments):
    meta = meta_courante()
    try:
        empreinte = idempotence.empreinte_arguments(arguments)
    except (ValueError, TypeError, KeyError):
        raise c.Refus("ARGUMENTS-INVALIDES") from None
    return {"appareil_id": meta.appareil, "intention_uuid": meta.cle, "empreinte_arguments": empreinte}
