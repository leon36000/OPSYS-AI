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
