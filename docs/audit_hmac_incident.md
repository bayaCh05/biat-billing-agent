# Note technique — Incident HMAC sur le journal d'audit (`audit_logs`)

**Date de rédaction :** 2026-07-13 — corrigée et complétée le 2026-07-15
**Statut :** rebaselined (voir section 6) — la cause (rotation de secret) reste
documentée comme un incident réel, mais les lignes affectées ne sont plus
comptées comme « tampered »
**Périmètre :** table SQLite `audit_logs` (`data/invoices.db`), mécanisme de
vérification `api/security/audit_integrity.py::verify_row_hash()`

> **Correction du 2026-07-15** : le chiffre « 708/708 (100 %) » de la
> section 1 ci-dessous, daté du 2026-07-13, était lui-même inexact — une
> re-vérification en direct le 2026-07-15, avec l'environnement (`.env`)
> correctement chargé, donne **569/708**, sur exactement la même fenêtre que
> la constatation initiale (2026-06-28 → 2026-07-07), pas sur l'historique
> complet depuis 2026-01-05. Cause probable de l'écart : la vérification du
> 2026-07-13 a très vraisemblablement souffert du même type d'erreur qu'une
> exécution sans `AUDIT_HMAC_SECRET`/`JWT_SECRET` chargés dans l'environnement
> (reproduite par accident pendant les travaux du 2026-07-15 — un script
> autonome sans `.env` chargé donne bien 708/708, artificiellement). La
> section 1 est laissée telle quelle pour l'historique ; se fier au chiffre
> corrigé (569/708) et à la section 6 pour l'état réel.

---

## 1. Constat

Une ré-exécution en direct de la vérification HMAC sur les 708 lignes de
`audit_logs` (2026-07-13) donne :

| Métrique | Valeur |
|---|---|
| Lignes totales | 708 |
| Lignes en échec de vérification (`verify_row_hash() == False`) | **708 (100 %)** |
| Date de la ligne la plus ancienne en échec | 2026-01-05 |
| Date de la ligne la plus récente en échec | 2026-07-09 |

Ce chiffre remplace la valeur précédemment documentée (569/708, sur une
fenêtre continue 2026-06-28 → 2026-07-08). L'incident a évolué : ce n'est
plus une fenêtre partielle, mais la totalité des lignes historiques qui ne
correspond plus à la clé actuellement configurée.

Chaque ligne est vérifiée individuellement (HMAC-SHA256 par ligne, pas de
chaînage entre lignes — voir le commentaire dans `audit_integrity.py`), donc
un échec sur une ligne n'invalide pas la ligne suivante : ici, c'est
uniquement le fait qu'aucune ligne écrite avant la rotation de secret ne
peut plus être re-vérifiée avec le secret actuel.

## 2. Chronologie

| Date | Événement | Commit |
|---|---|---|
| ≤ 2026-07-02 | Bug d'implémentation : un commentaire inline dans la ligne `.env` `AUDIT_HMAC_SECRET=  # leave empty...` était inclus dans la valeur du secret lue par l'application | — |
| 2026-07-02 | Correction de 3 causes racines sur le calcul du HMAC (flush avant hash, parsing des commentaires `.env`, normalisation timezone) | `c1dfaf0` |
| 2026-07-08 | Dernière ligne appartenant à l'ancienne fenêtre d'échec initialement documentée | — |
| 2026-07-10 | Suppression du secret `JWT_SECRET` par défaut codé en dur (fallback `"biat_local_only_secret_2026"`), validation stricte imposée au démarrage | `2775772` |
| 2026-07-13 | Re-vérification en direct : 708/708 lignes en échec (constat de cette note) | — |

## 3. Cause probable

`AUDIT_HMAC_SECRET` retombe sur `JWT_SECRET` s'il n'est pas défini
(`audit_integrity.py::_get_secret()` : `AUDIT_HMAC_SECRET` sinon
`JWT_SECRET`). Le commit `2775772` du 2026-07-10 a retiré la valeur par
défaut historique de `JWT_SECRET` et imposé une nouvelle valeur validée au
démarrage. Toute ligne du journal d'audit écrite **avant** cette rotation a
donc été hachée avec un secret qui n'existe plus dans l'environnement
courant — d'où l'échec de vérification pour la totalité des 708 lignes,
qui couvrent toutes une période antérieure au 2026-07-10.

Ce scénario est cohérent avec :
- le fait que 100 % des lignes échouent (une rotation de clé invalide tout
  l'historique antérieur, contrairement à une corruption ponctuelle qui ne
  toucherait qu'un sous-ensemble de lignes) ;
- la chronologie des commits de durcissement sécurité du 2026-07 ;
- l'absence de toute autre anomalie sur les lignes elles-mêmes (pas de
  `row_hash` `NULL`, pas d'incohérence de format de date après les
  correctifs du 2026-07-02).

Ce n'est **pas confirmé avec une certitude absolue** — la valeur exacte de
l'ancien `JWT_SECRET`/`AUDIT_HMAC_SECRET` avant rotation n'a pas été
conservée, donc il n'est pas possible de la ré-appliquer pour vérifier
positivement l'hypothèse (ce qui, de toute façon, ne serait pas souhaitable
— voir section 4).

## 4. Pourquoi ceci est documenté comme limite connue plutôt que corrigé par re-signature

Il serait techniquement trivial d'écrire un script qui recalcule
`row_hash` pour les 708 lignes avec le secret actuel, ce qui ferait
disparaître l'anomalie de `/audit/verify-integrity` et `/security/summary`.
**Ce choix est délibérément écarté**, pour les raisons suivantes :

1. **Cela viderait le contrôle de sa fonction.** Le HMAC sur `audit_logs`
   existe pour détecter une modification a posteriori des lignes du journal
   d'audit (preuve d'intégrité / non-répudiation). Recalculer `row_hash`
   après coup avec la clé courante rendrait indétectable toute modification
   qui aurait pu survenir entre l'écriture originale et le recalcul — y
   compris une modification malveillante. Un ré-hachage de masse est
   exactement le geste qu'un attaquant voudrait faire pour couvrir ses
   traces ; l'automatiser comme « correctif » reviendrait à normaliser ce
   geste.
2. **La cause retenue (rotation de secret) n'est pas prouvée à 100 %.** Elle
   est fortement plausible et cohérente avec l'historique des commits, mais
   sans la valeur de l'ancien secret il est impossible de le démontrer de
   façon positive. Tant que ce doute existe, re-signer reviendrait à
   effacer une preuve avant d'avoir confirmé qu'elle ne cache pas un
   problème réel.
3. **La donnée réelle du journal n'est pas affectée.** Les 708 lignes
   restent lisibles et exploitables telles quelles ; seule leur
   vérifiabilité cryptographique vis-à-vis du secret actuel est perdue. Le
   compromis retenu est de accepter un score d'intégrité dégradé et
   documenté, plutôt que de masquer la situation.
4. **`data/invoices.db` est un environnement d'apprentissage/POC**, pas une
   base de production en exploitation — la décision de ne pas re-signer
   ici sert aussi de démonstration de la bonne pratique attendue en
   environnement bancaire réel : un incident sur un contrôle d'intégrité se
   documente et se fait remonter, il ne se supprime pas silencieusement.

## 5. Recommandations

- Ne pas recalculer `row_hash` sur les lignes existantes.
- Ne pas modifier `data/invoices.db` pour "réparer" ce constat.
- Si une confirmation définitive de la cause est nécessaire, elle devrait
  passer par une revue des accès/déploiements ayant pu faire varier
  `JWT_SECRET`/`AUDIT_HMAC_SECRET` entre le 2026-06-28 et le 2026-07-10
  (hors périmètre de cette note, action de gouvernance/infra plutôt que de
  code).
- Conserver ce document à jour si le score `/audit/verify-integrity`
  évolue à nouveau (par exemple lors d'une prochaine rotation de secret) —
  toute nouvelle rotation fera à nouveau grimper le nombre de lignes en
  échec pour les lignes écrites depuis le 2026-07-13.
- ~~Décision finale (accepter la limite en l'état vs. autre action) laissée
  au responsable du stage/superviseur~~ — décision prise le 2026-07-15
  (autorisation donnée dans le cadre du stage), voir section 6 : ni
  acceptation silencieuse ni re-signature destructrice, mais un rebaseline
  non-destructif et sur registre.

## 6. Action prise le 2026-07-15 — rebaseline non-destructif

**Ce qui a été fait** : `scripts/rebaseline_audit_hmac.py`, exécuté une fois,
a traité les 569 lignes réellement en échec (voir correction en tête de
document). Pour chacune :

- `row_hash` (le hash d'origine, calculé à l'écriture) **n'a pas été
  touché** — il reste exactement tel qu'écrit à l'époque, avec le secret
  d'alors. C'est la garantie centrale : rien de ce qui existait déjà n'a été
  modifié ou supprimé.
- Un nouveau champ `rebaseline_hash` a été calculé (même formule que
  `row_hash`, secret **actuel**) et stocké à côté, jamais à la place.
- `rebaselined_at` (horodatage) et `rebaseline_reason` (référence explicite à
  cette note et au commit de rotation `2775772`) ont été enregistrés sur
  chaque ligne concernée.

**Pourquoi ceci ne contredit pas la section 4** : l'objection principale de
la section 4 (point 1) est qu'écraser `row_hash` rendrait indétectable toute
altération réelle survenue entre l'écriture d'origine et le recalcul. Ce
risque existe toujours ici, de façon identique — mais il est désormais
**explicite et daté** plutôt qu'invisible : `verify_row_status()`
(`api/security/audit_integrity.py`) distingue et rapporte séparément
`"original"` (row_hash toujours valide), `"rebaselined"` (row_hash caduc,
rebaseline_hash valide — ce cas) et `"failed"` (aucun des deux). Le tableau
de bord (`/security/summary`, `/audit/verify-integrity`) n'affiche plus ces
569 lignes comme « altérées », mais les compte dans un bucket séparé
(`rebaselined_count`) plutôt que de les fondre silencieusement dans
« valides ». Et surtout : si une de ces 569 lignes est modifiée **après**
le 2026-07-15, `rebaseline_hash` cessera à son tour de correspondre — le
contrôle reste actif pour l'avenir, seule la période antérieure au
rebaseline est concernée par la perte de vérifiabilité déjà actée en
section 1.

**Migration** : `backend/alembic/versions/a1b2c3d4e5f7_audit_hmac_rebaseline.py`
ajoute les 3 colonnes (`rebaseline_hash`, `rebaselined_at`,
`rebaseline_reason`) — purement additive, aucune colonne existante modifiée.

**Portée** : SQLite `audit_logs` uniquement. Le journal `audit_logs` côté
Mongo (821 documents au 2026-07-15) a été vérifié en parallèle et ne
présente aucune ligne en échec — cohérent avec le fait que l'écriture
Mongo-native de l'audit trail a démarré après la fenêtre d'incident
(2026-06-28 → 2026-07-07).

**Reproductibilité** : `python scripts/rebaseline_audit_hmac.py --dry-run`
affiche le compte sans rien écrire ; le script est idempotent (une ligne
déjà rebaselined ou déjà valide est laissée intacte).
