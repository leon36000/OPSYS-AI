"""Recette immuable du profil BGE-M3 local accepté pour la vectorisation M03."""

from __future__ import annotations

import json

MODELE_LOCAL = "BAAI/bge-m3"
DIMENSION_LOCALE = 1024
SHA_MODELE_LOCAL = "0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d"
SHA_TOKENIZER_LOCAL = "6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790"
PROFILE_SHA256 = "94a345a3fabe6489b15ce8563d119fab32e2b42c9e7933b28f1ba5523dd2fc6d"

# JSON canonique figé : une recette partielle, étendue ou typée autrement ne devient pas
# autoritaire simplement parce que son émetteur a recalculé son propre SHA.
RECETTE_CANONIQUE = (
    '{"dimension":1024,"document_prefix":"","format":"opsys-embedding-profile-v1",'
    '"model":"BAAI/bge-m3","model_revision":"Xenova/bge-m3@4de13258303883538bd53b696b452bf8099f0858",'
    '"model_sha256":"0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d",'
    '"normalization":"l2-float32","pooling":"cls-first-token","query_prefix":"",'
    '"recipe_revision":"bge-m3-onnx-r35-v1",'
    '"tokenization":{"add_special_tokens":true,"max_tokens":512,"truncation":false},'
    '"tokenizer_sha256":"6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790"}'
)


def recette_embedding() -> dict[str, object]:
    """Retourne une copie indépendante de la recette canonique."""
    return json.loads(RECETTE_CANONIQUE)
