# Courriel original : contrat pur Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Valider une capture binaire complète et produire une identité IMAP stable avant le futur stockage M1.

**Architecture:** Contrat Python pur fermé, sans IO ni fournisseur. L’identité est distincte du SHA du contenu, afin que le propriétaire SQL puisse détecter un conflit. Aucun objet issu du codec ne prouve l’origine, la permission ou un ACK.

**Tech Stack:** Python standard, pytest/ruff natifs; aucune dépendance, migration ou activation.

**Spec:** `docs/grs/crm/CRM06-AUDIT-SUIVI-COURRIELS.md`, section architecture cible. Choix techniques du coordinateur sous autorisation durable de poursuite; aucune nouvelle demande d’approbation de développement.

## Global Constraints

- Root seul writer Source/Git; Source RO durant QA, homes/tmp privés, réseau interdit, ressources bornées.
- Maximum original 1 048 576 octets comme le FETCH natif; taille annoncée exactement égale, sinon refus.
- Clés fermées : version, instance_id, source_id, compte_id, boite, uid_validity, uid, taille_annoncee, recu_le, date_interne, message_id.
- instance_id UUID canonique minuscule; source_id SHA-256 de génération de source, fourni par futur Host et non une autorité; compte_id syntaxe native; boîte exacte 1..1024 sans NUL/CR/LF.
- UIDValidity chaîne décimale canonique et UID entier dans 1..4294967295; bool et sous-classes refusés.
- recu_le horodatage UTC millisecondes valide; date_interne de même forme ou None, sans inférence. Message-ID déclaratif optionnel, absent de l’identité.
- Identité = SHA-256 du domaine `opsys:m1:courriel:identite:v1:` suivi des six champs instance/source/compte/boîte/UIDValidity/UID encodés UTF8, chacun précédé de sa longueur en octets ASCII et `:`.
- SHA source calculé sur les octets intacts; pas de hash fourni, pas de normalisation/troncature. Original et arguments capturés immuables, jamais dans repr/erreur.

## Review Focus

- Même identité/autres octets : identité identique, SHA différent, jamais nouvelle identité pour cacher le conflit.
- Même Message-ID dans deux boîtes/sources/instances : identités différentes.
- Dates invalides, source tronquée, taille bool : refus avant construction.
- Unicode multioctet et concaténations ambiguës : aucune collision de cadrage ni normalisation.
- Objet malveillant/sous-classe/surrogate : refus générique sans exécution de ses méthodes.

### Task 1 : codec complet, sans surface runtime

**Files:** créer `src/opsys/reception_courriel_contrat.py`, `tests/test_reception_courriel_contrat.py`; documenter dans `docs/grs/crm/CRM06-COURRIEL-CONTRAT.md` et matrice CRM06.

**Interfaces:** `valider_original(arguments: dict, *, source: bytes) -> OriginalCourriel`; dataclass figée avec arguments Mapping immuable, source bytes, identite_id, source_sha256, source_octets. Erreur `ValueError("REJ-M1-COURRIEL-ORIGINAL-INVALIDE")` sans contenu.

- [x] Tests des cinq risques, vecteur indépendant, immutabilité et bornes natives; constater rouge pour absence du contrat.
- [x] Implémenter le codec fermé minimal, sans endpoint, outil modèle, écriture ou connexion.
- [x] QA ciblée native pytest + ruff, puis revue précise de l’identité et de la frontière d’autorité.
- [x] Docs/matrice, reçu et commit local; publication uniquement après réconciliation CI parente.

## Suite distincte encore non livrée

Propriétaire SQL chiffré et clé externe dédiée, relecture d’autorité actuelle avant recherche/rejeu et ACK, savepoint original/reçu/audit, migration réservée, refus de conflit. Ensuite capacité Host distincte SMS et ACK avant curseur. Ensuite liaison admin au projet exact et lecture CRM autorisée. Le codec seul ne livre aucune de ces capacités et CRM06 reste MANQUANT pour le suivi automatique des courriels.

## Résultats et rulings

`crm06-codec-red-v4` : assertion d’absence rouge; v2 57PASS; mémoire-red-v1 prouve allocation
avant borne, v3 59PASS; review-red-v1 reproduit la désynchronisation, v4 **60PASS**, ruff/verifier0.
Ruling : boîte bornée en unités UTF16 pour correspondre au natif; pré-borne en longueur Python
avant allocation. Ruling : copie privée unique avant validation/hachage, suite au P2, sans seconde
boucle d’opinions. Le callback de test conserve le hash réel et simule le changement à un point
possible de concurrence. Prérequis lint/collect restent historiques, non requalifiés en bugs produit.
Publication différée tant que la CI parente reste non terminale; aucun port ni droits nouveaux.
