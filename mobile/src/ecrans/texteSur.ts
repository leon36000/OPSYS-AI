/**
 * Ce que l'app accepte de montrer d'un texte que le SERVEUR a écrit (PLAN T1.4-n). Logique PURE, testée
 * (`texteSur.test.ts`).
 *
 * Le serveur écrit certains de ses textes pour un AGENT : ils citent le fichier où écrire (`/srv/opsys/entreprise.yaml`), les
 * commandes à taper (`opsys-metier equipes declarer --depuis <fichier> --par ...`), des pages de documentation. Un
 * propriétaire sur son téléphone n'a rien à en faire, et un chemin du serveur ne quitte pas le serveur. Ces deux gardes
 * décident ce qui peut être montré tel quel ; tout le reste est remplacé par une phrase de l'app (`manquesM4.ts`) ou tu.
 */

/** Un code sûr à montrer : un seul mot, sans espace, ni barre oblique, ni guillemet — donc ni une phrase, ni un chemin. */
const JETON = /^[A-Za-z0-9_.-]{1,64}$/;

/** Le texte contient-il un chemin de fichier, une commande du serveur ou un nom de fichier de configuration ? */
const CHEMIN_OU_COMMANDE = /[/\\`~$]|opsys-metier|\.(?:ya?ml|json|sqlite|md|py|ts|db)\b/i;

/** `valeur` si c'est un jeton (lettres, chiffres, `_`, `.`, `-`) qui n'est ni le nom d'un fichier du serveur ni celui de sa
 * commande ; `null` sinon (absent, une phrase, un chemin, `entreprise.yaml`, `opsys-metier`). */
export function jetonSur(valeur: string | null): string | null {
  return valeur !== null && JETON.test(valeur) && !CHEMIN_OU_COMMANDE.test(valeur) ? valeur : null;
}

/** Le texte du serveur, seulement s'il ne porte ni chemin ni commande ; `null` sinon (il n'est alors pas montré). Un texte
 * vide reste vide : il n'y a rien à cacher. */
export function texteSansChemin(texte: string | null): string | null {
  return texte !== null && !CHEMIN_OU_COMMANDE.test(texte) ? texte : null;
}
