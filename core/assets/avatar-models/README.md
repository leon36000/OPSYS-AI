# Modèle facultatif RobotExpressive

`robotexpressive-quaternius-cc0-v1.glb` est la copie de l'exemple RobotExpressive de Three.js,
commit upstream `b924f0cad4058dc4dde71445c796980c3cd5b5ed`.

Le README upstream attribue le modèle à Quaternius sous CC0 1.0 et signale des modifications de
Don McCurdy. Le texte juridique CC0 est conservé dans `CC0-1.0-legalcode.html`. L'actif a une taille
de 463 988 octets et un SHA-256 de
`047f5e5fb3bb6d378bd1df16ca6137f2a596c99b3a1b5690b4020c05aaf6f319`.

Source : <https://github.com/mrdoob/three.js/tree/b924f0cad4058dc4dde71445c796980c3cd5b5ed/examples/models/gltf/RobotExpressive>.
Ce modèle n'est pas un avatar vocal : aucun rendu navigateur, audio, lipsync ou animation
pilotée par la parole n'est inclus par son seul ajout.

## Modèle facultatif Humain MPFB CC0

`mpfb-human-cc0-v1.glb` est dérivé de l'avatar MPFB livré par Talking Head, source épinglée au
commit `b3e277b3b46f88e557bf28a2c5612a5b04e075c3` :
<https://raw.githubusercontent.com/met4citizen/TalkingHead/b3e277b3b46f88e557bf28a2c5612a5b04e075c3/avatars/mpfb.glb>.
Le `README` upstream de ce commit, conservé dans `MPFB-README.upstream.md`, déclare explicitement
à la ligne 375 que l'avatar MPFB est sous CC0; le texte juridique CC0-1.0 conservé dans
`CC0-1.0-legalcode.html` accompagne cet actif. L'actif transformé fait 6 600 124 octets et son
SHA-256 est `47d377b91d9872e439cbcc363b20630bcf68cda057218683aa0565372509b4df`.

La transformation retire les textures et cuit la texture diffuse d'origine des yeux (texture
`brown_eye`, image source SHA-256
`4659691c7295ad6206c78b003e5fd0e5f91dcd53032fa914a229bb48cabe424b`) dans `COLOR_0` à partir des
coordonnées UV, en conservant l'échantillonnage sRGB vers linéaire et le masque alpha du matériau.
Le facteur de base du matériau des yeux devient blanc pour éviter une multiplication double. Aucun
dessin ou détail d'œil n'a été ajouté. Les géométries et le squelette restent ceux de la source; les
morphs retenus sont les 14 formes de visème et la mâchoire. Les clips d'animation d'origine ne sont
pas conservés. Le résultat respecte le profil GLB local fermé.

Ce choix est un modèle statique local. La capture WebGL qualifie le chargement et le changement de
morph target; elle ne qualifie ni la synchronisation labiale avec l'audio, ni une capacité ACE.
