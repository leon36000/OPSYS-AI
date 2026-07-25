# Provenance LiteLLM — image épinglée par digest (P0-2b, R-028/D-035)

Date de capture : 2026-07-24
Service : serveur-litellm (passerelle d'équipe OPSYS-AI)

## Digest épinglé (compose)
```
ghcr.io/berriai/litellm@sha256:f792e404f0db3b8c8d841e25e8c7b373df6079b74d660068a6d4974345c8d43d
```
## Config image (id local)
```
sha256:f792e404f0db3b8c8d841e25e8c7b373df6079b74d660068a6d4974345c8d43d
```
## Couches (layer digests — bill of contents par empreinte)
```
sha256:272d94535c70253a6a7cbb1d96838fd8fa9ed138aea2ce091f74f261095ac5b8
sha256:7b8515b1d8a75419b513a7f7cfecc0563aaeeec468e93c3673122d74cf9e7028
sha256:3c40083cbf9966b9da7f6e55a8dc664faa61deccd9f5d488d718e3d01f4aba29
sha256:6562679d109c939489d457fcbd6d961c9d5f592f316cefcb2e62fa595199797a
sha256:caaccf89b8660b925e0e0266ffdc4f3e3cc7e98e121742c233f199ec167a4920
sha256:70991d5976e247cb33ca1923edd3f609e6c23f527dbe62b838d6a03c0bca6453
sha256:298bacf2e4ef81e719540c35d6f5d69de916d42407dd597c2cc217fa3fed9ea5
sha256:90cfe0bd8cd693b2ee91b94108fc47f023d82edc00e57352ab6635d827b33505
sha256:852a2b9325825ed672cd62abd93cdb8d84ab7b20e881280df38d77ba07531fa3
sha256:b8195249dcd92d2c0519946f0a9f9d9ec7b88e9a19b5f83bc156103a39d5ab50
sha256:8f43f428401b1493736934951e0382ccd856a7cfca2e94ea85eb5e9bd54b0418
sha256:a783131de2d8e1ea4e1c43eb303f9b86479ba962b8e28c8fb6a64443bf872186
sha256:132f30c685c8bc088fc1309d44d1fcbbe8895410f64823e7e58abfc44d7d9031
sha256:5a96e0c935ec1d0c0e59d6bfc8dcb0c3e930151b254b2b426708401680ff4853
sha256:4b441a6833249139de4209926d83752d51477611c3fe2852539abf4b72be8a1c
sha256:3add7ba543c7b23aef2cb4465b30590091453cf0ef3d5d7ee8f31dfd732a0b11
sha256:f599eeeef833e413c629e17cc0241a745f11fa78a3c08891763c7376131d3165
sha256:4012c053d5c252f1e53cde17d5cd56c9dabd73ff0ffd286d7a34110db17b0c03
sha256:3a6ddc7104c62e0d425ad5028677cfb7afe242768b597aaa0e498a4104206c2c
sha256:08269aaac2967c0eec350552ab278a00effe9f2c8a5eaa3e87945a9d0dbcfb2d
sha256:f44993c98a9e02104087c224c2059b31bb6da24e79483baf664ed44793410543

```
## Métadonnées de build (provenance)
```
Created: 2026-06-23T23:45:13.867487456Z | Architecture: amd64/linux | Layers: 21
```

```
## SBOM CycloneDX formel — SUITE (non bloquant)
syft/grype absents du poste. Générer un SBOM CycloneDX via CI est prévu (workflow quality-gates,
job Phase B provisionne syft 1.46 / grype 0.115). Installer syft par script pipé irait CONTRE le
durcissement de cette story (D-035) : reporté à la CI où l'outil est épinglé + vérifié.
La provenance ci-dessus (digest manifeste + empreintes de couches) est le bill of contents vérifiable disponible aujourd'hui.
