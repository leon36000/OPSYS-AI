#!/bin/sh
# deploy/opsys-ancienne-commande.sh : installé sous le nom `opsys` dans l'image (deploy/Dockerfile), PLAN T0.7 lot 2.
#
# `opsys` était la CLI du moteur métier ; c'est maintenant la commande du core, et la CLI du moteur s'appelle
# `opsys-metier`. Sans ce fichier, une ancienne invocation (`docker compose exec opsys opsys personnes creer`, un
# script d'exploitation) échouerait par « executable file not found in $PATH » : une erreur qui ne dit rien de la
# nouvelle commande. Ici, elle dit quoi taper, et le code de sortie (2) fait échouer un script au lieu de le laisser
# continuer sur une commande retirée.
#
# Le conteneur n'a pas le core : `opsys metier <commande>` n'y existe pas, seule `opsys-metier <commande>` y est
# (le core, lui, tourne dans son propre conteneur, image d'OpenClaw).

citer() {
    case "$1" in
        *[!A-Za-z0-9_@%+=:,./-]*) printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")" ;;
        *) printf '%s' "$1" ;;
    esac
}

{
    printf '%s\n' "opsys : dans ce conteneur, la CLI du moteur métier s'appelle « opsys-metier » (« opsys » est depuis T0.7 lot 2 la commande du core, qui n'est pas dans cette image)."
    printf 'Utilisez : opsys-metier'
    for argument in "$@"; do
        printf ' '
        citer "$argument"
    done
    printf '\n'
} >&2
exit 2
