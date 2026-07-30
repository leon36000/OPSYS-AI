# SonarCloud : duplication des patrons de socle — décision, pas défaut

PR #136 (M4-S001) : le check SonarCloud (non requis) échoue sur l'unique condition
« 14 % duplication on new code (seuil ≤ 3 %) » — zéro bug, zéro vulnérabilité, zéro
code smell en condition d'échec. Mesuré sur le check-run, pas supposé.

## Pourquoi la duplication est VOULUE ici

L'architecture M4 (ratifiée en revue, PR #124) endosse le **copié-adapté** des
utilitaires de socle éprouvés (encodage, registre, verdicts…) et interdit l'import
inter-modules : le chore #109 a donné à chaque module une **identité de paquet
isolée** après avoir mesuré la collision d'identités (21 tests de M2 exerçant le
code de M1 sans aucun signal). Un import croisé recréerait ce couplage. Chaque
copie est revue, testée et **mutée dans son propre module** — la divergence n'est
pas silencieuse, elle est gouvernée par les suites de chaque module.

## La décision

`sonar.cpd.exclusions` (fichier `.sonarcloud.properties`) désactive la détection
de copie sur les **seuls fichiers de socle** listés, tous modules confondus. La
détection reste active partout ailleurs : dans la logique métier, une duplication
reste un défaut à signaler. Alternative rejetée : laisser le check rouge à chaque
nouveau module — un check rouge en permanence détruit le signal (leçon de
l'issue #110, `e2e-load`).

## Inventaire exhaustif des fichiers couverts (revue r1 : vérifiable, plus affirmé)

- `encodage.py` (2) : `Modules M/M4-field-ops/src/m4_field_ops/encodage.py` · `Modules M/M2-revenue-crm/src/m2_revenue_crm/encodage.py`
- `horodatage.py` (2) : `Modules M/M1-front-office/src/m1_front_office/horodatage.py` · `Modules M/M2-revenue-crm/src/m2_revenue_crm/horodatage.py`
- `verdicts.py` (2) : `Modules M/M1-front-office/src/m1_front_office/verdicts.py` · `Modules M/M2-revenue-crm/src/m2_revenue_crm/verdicts.py`
- `registre.py` (2) : `Modules M/M1-front-office/src/m1_front_office/registre.py` · `Modules M/M2-revenue-crm/src/m2_revenue_crm/registre.py`
- `adaptateurs.py` (2) : `Modules M/M1-front-office/src/m1_front_office/adaptateurs.py` · `Modules M/M2-revenue-crm/src/m2_revenue_crm/adaptateurs.py`
- `fixtures_garde.py` (1) : `Modules M/M2-revenue-crm/src/m2_revenue_crm/fixtures_garde.py`

Tous sont des utilitaires de socle copiés-adaptés et revus dans leur module. Aucun fichier
de logique métier ne porte ces noms. Motifs en `**` : par nom de fichier, indépendants de la
profondeur. Vérification empirique au prochain PR de socle (M4-S002) — correction sur mesure
si la condition duplication échoue encore.
