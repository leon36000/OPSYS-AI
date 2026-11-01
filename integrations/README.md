# integrations/

Composants distribués hors du code Python d'OPSYS-AI, sous leur PROPRE licence.

| Dossier | Licence | Contenu |
|---|---|---|
| `wordpress/opsys-connect/` | **GPL-2.0-or-later** (`LICENSE` du dossier) | Plugin WordPress « OPSYS Connect » (M7), voir `docs/architecture/M7-WORDPRESS-SOCIAL.md` |

Pourquoi un dossier à part : un plugin qui s'exécute dans WordPress est une œuvre dérivée de WordPress, donc sous GPL
(position de la WordPress Foundation et de la FSF, R4 §2.2, à valider auprès d'un juriste). Le reste du dépôt est sous Apache-2.0
et **n'importe jamais** ce dossier : le code Python ne fait que LIRE ses fichiers comme du texte (analyse statique) et
parle au plugin par HTTP signé. Aucune propriété intellectuelle sensible n'est dans le plugin (ni prompt, ni modèle, ni
secret) : il est mince par conception, et le secret partagé vit dans `wp-config.php` ou le coffre d'OPSYS.

Les vecteurs de test partagés (`departments/m07-marketing/contracts/opsys-connect-vecteurs.v1.json`) sont des DONNÉES
(JSON), lues par les deux côtés : elles ne font pas du plugin une dépendance du code Python.
