# Revue scellée du lot A1 — 3 vendors, 3 objections mesurées

## Dépouillement

```
APPROVE 1/3 | vendors distincts: 3 ['minimax', 'tencent', 'xiaomi'] | objections critiques: 1
```

| Reviewer | Vendor | Verdict | Objections |
|---|---|---|---|
| MiMo-Pro-V2 | xiaomi | **APPROVE** | 0 |
| MiniMax-M3 | minimax | REJECT | 1 critique, 2 majeures, 2 mineures |
| Tencent-Hy3 | tencent | REJECT | 1 majeure, 2 mineures |

Trio complet, trois vendors distincts, aucun n'ayant approuvé les 168 PR de la vague 1. Le sceau
est unique. **C'est la première revue de cet audit à réunir les trois conditions de REG-05** — les
deux précédentes avaient perdu un membre sur un échec de route.

Le trio recomposé (MiniMax-M3 · MiMo-Pro-V2 · Tencent-Hy3) et le plafond de pack ramené à 30 000
caractères ont tenu : aucune route n'a échoué.

## Chaque objection a été mesurée avant d'être traitée

### CONFIRMÉE — l'exemption 5 laissait passer un vrai stub (MiniMax majeure, Tencent mineure)

Les deux relecteurs ont exhibé le même scénario, sans se concerter :

```python
class GerantCache(BackendDistant):      # base externe, donc non locale
    def fermer(self): pass              # stub oublié
```

Reproduit sur une copie du dépôt : **NON DÉTECTÉ**. L'exemption portait sur l'HÉRITAGE — toute
méthode `pass` d'une classe héritant d'une base non locale était exemptée — au motif, écrit dans le
code, qu'« un faux négatif y coûte moins qu'un faux positif ». Cette approximation couvrait bien
plus large que ce qu'elle visait.

Corrigée : l'exemption porte désormais sur le **nom** de la méthode, restreint à une liste close de
cinq points d'extension que la bibliothèque standard invite à redéfinir en no-op (`log_message`,
`log_request`, `log_error`, `emit`, `handle_error`). Une règle qui nomme ce qu'elle autorise se
relit ; une règle sur l'héritage autorisait tout ce qui hérite.

Vérifié dans les deux sens : le stub exhibé est maintenant **DÉTECTÉ**, et les trois `log_message`
légitimes du dépôt restent exemptés — aucun faux positif introduit.

### CONFIRMÉE — il manquait une mutation négative (Tencent mineure, MiniMax mineure)

« La batterie ne prouve que la détection de fautes injectées. Elle n'inclut aucune mutation
validant qu'une exemption ne masque pas un défaut réel. »

Fondé, et c'est exactement ce qui avait permis au défaut ci-dessus de survivre à quatre tours de
correction. Une mutation négative est ajoutée : elle injecte le stub sous exemption et exige qu'il
soit vu. La batterie passe de 4 à **5/5 mutations**, et la régression est désormais impossible sans
être signalée.

### RÉFUTÉE PAR MESURE — « les fichiers non collectés ne sont pas analysés » (MiniMax, critique)

L'objection avançait qu'un fichier de test absent de la configuration pytest n'est jamais parsé et
échapperait donc à tous les contrôles.

Mesure : un test sans assertion a été injecté dans `tests/e2e/test_e2e_selftest.py`, qui figure
précisément parmi les cinq fichiers non collectés. Résultat : **DÉTECTÉ**. La sonde parcourt les
fichiers suivis par git, indépendamment de ce que la CI collecte — c'est la raison même pour
laquelle `fichiers_non_collectes` peut exister comme contrôle distinct.

L'inférence était plausible à la lecture de la sortie ; elle ne résiste pas à l'exécution.

### RÉFUTÉE PAR MESURE — « une méthode test_ vide n'est pas vue » (MiniMax, majeure)

Mesure : `def test_methode_absolument_vide(self): pass` ajoutée dans une classe de test.
Résultat : **DÉTECTÉE**.

### RÉFUTÉE PAR LE CADRAGE — la « contradiction » du constat A5-001 (MiniMax mineure, Tencent majeure)

Deux relecteurs sur trois ont relevé que `classe: "faille-securite"` et `severite: "critique"`
contredisent la conclusion du constat, qui dit qu'aucune faille n'est montrée.

L'objection est légitime **du point de vue d'un lecteur**, mais elle est levée par le cadrage : le
PRD §8.5 définit la limite d'un constat de sécurité comme « exposition prouvée, **jamais**
exploitation ». Dans cet audit, `faille-securite` désigne donc une exposition prouvée, non une
exploitation démontrée. Les deux énoncés sont cohérents.

Ce qui manquait était la **citation** de ce standard dans le constat lui-même : un lecteur ne
devrait pas avoir à retrouver le cadrage pour comprendre qu'il n'y a pas contradiction. Elle est
ajoutée. Que deux relecteurs indépendants aient buté sur le même point rend la clarification
nécessaire, même si le fond était juste.

## Ce que la revue n'a pas remis en cause

Aucun des trois n'a contesté le fond des trois constats déposés, ni la mesure des 45 tests
sensibles hors gate bloquant, ni le registre des fichiers ouverts (1 340 ouverts, 0 non ouvert).
Les objections portent toutes sur la **précision de l'instrument**, ce qui est le bon niveau de
critique pour un lot d'inventaire.
