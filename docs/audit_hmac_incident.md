# Note technique — Incident HMAC sur le journal d'audit (`audit_logs`)

**Date de rédaction :** 2026-07-13 — corrigée et complétée le 2026-07-15,
étendue à Mongo le 2026-09-07, `AUDIT_HMAC_SECRET` définitivement introduit
le 2026-09-07 (Option B, section 8)
**Statut :** clos — `AUDIT_HMAC_SECRET` (gap S5) comblé, `tampered_count` = 0
sur les 1758 entrées des deux stores au 2026-09-07
**Périmètre :** table SQLite `audit_logs` (`data/invoices.db`) ET collection
MongoDB `audit_logs` (depuis la section 7) — mécanisme de vérification
`api/security/audit_integrity.py::verify_row_status()` /
`verify_row_status_from_doc()`

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

> **Mise à jour du 2026-09-07** : ce constat (0 ligne en échec côté Mongo)
> reste vrai, mais la portée « SQLite uniquement » du mécanisme de
> rebaseline lui-même a créé un angle mort distinct, sans lien avec la
> rotation de secret — voir section 7.

**Reproductibilité** : `python scripts/rebaseline_audit_hmac.py --dry-run`
affiche le compte sans rien écrire ; le script est idempotent (une ligne
déjà rebaselined ou déjà valide est laissée intacte).

## 7. Gap de couverture HMAC côté Mongo — découvert et clos le 2026-09-07

**Constat** : 4 documents `audit_logs` côté Mongo ont `row_hash = None`
(jamais calculé) — pas un `row_hash` qui ne correspond plus au secret
courant. Ce ne sont **ni des lignes altérées, ni des victimes de la
rotation de secret du 2026-07-10** (section 3) : ce sont des entrées
« pré-HMAC », exactement la même nature que les `null_hash_entries` déjà
connues côté SQLite (section 1). Elles n'ont jamais été comptées comme
`tampered` — `tampered_count` est et a toujours été **0 sur les deux
stores** (voir tableau en fin de section).

**Cause racine**, identifiée précisément via l'historique git : le commit
`f6679b2` (2026-07-10 02:16:52, « complète le Lot 9 ») est celui qui a
ajouté le calcul de `row_hash` à `log_audit_event_native()` (l'écrivain
Mongo-natif de l'audit trail utilisé pour les événements de login). Les 4
documents ci-dessous ont tous été écrits **avant** ce commit, donc avant
que ce chemin de code ne calcule un HMAC — une brève fenêtre de quelques
heures, la veille de la rotation de secret elle-même, sans lien avec elle :

| Date (`created_at`) | Action | `_id` |
|---|---|---|
| 2026-07-09 17:44:22 | LOGIN_SUCCESS | `67774e16-851d-42e9-8425-e5a3f79b4adb` |
| 2026-07-09 17:44:38 | LOGIN_SUCCESS | `c4c99f24-8bef-4110-b44b-51e670ccb85e` |
| 2026-07-10 00:26:42 | LOGIN_SUCCESS | `b04e7c64-0fb9-4dd2-897c-4571129ec69d` |
| 2026-07-10 00:26:53 | LOGIN_SUCCESS | `459acf10-f4e6-44d2-8729-5271aba0c257` |

Le code réel de `verify_integrity_native()`
(`src/storage/documents/service_bridge.py`) avait déjà, avant toute
modification de ce jour, la branche `if not stored:
null_hash_entries.append(...); valid += 1; continue` — ces 4 documents
étaient donc déjà exclus de `tampered_entries` et n'ont jamais été
remontés comme altérés par `/audit/verify-integrity` ni
`/security/summary`.

**Décision prise le 2026-09-07** : laisser ces 4 documents tels quels
(`row_hash` toujours `None`, non rétro-calculé) plutôt que de leur
appliquer un `row_hash` a posteriori — cohérent avec le principe déjà posé
en section 4 (ne pas signer après coup une donnée dont l'historique
d'écriture n'est plus garanti). Aucune ligne de ce lot n'a donc été
modifiée.

**Ce qui a quand même été ajouté, en prévision d'une vraie rotation
future** : `AuditLogDocument` (`src/storage/documents/audit_log.py`) gagne
les 3 mêmes champs que la table SQLite (`rebaseline_hash`,
`rebaselined_at`, `rebaseline_reason`) — purement additif, aucun document
existant modifié par ce changement de schéma seul. `verify_row_status_from_doc()`
(`api/security/audit_integrity.py`) est l'équivalent Mongo-natif de
`verify_row_status()`, et `verify_integrity_native()` distingue désormais
`"rebaselined"` de `"tampered"` exactement comme `compute_integrity_summary()`
le fait côté SQLite. `scripts/rebaseline_audit_hmac_mongo.py` est le
miroir Mongo de `scripts/rebaseline_audit_hmac.py` (mêmes garanties :
`row_hash` jamais recalculé, idempotent, `--dry-run` disponible) — exécuté
en dry-run le 2026-09-07, il confirme qu'il n'y a **rien à rebaseliner
aujourd'hui** (les 4 documents ci-dessus n'ont pas de `row_hash` à
comparer, donc ne sont pas candidats). Ce mécanisme ne sert à rien tant
que `AUDIT_HMAC_SECRET` reste vide (voir Option B, non encore mise en
œuvre) — il devient nécessaire dès qu'une vraie rotation de secret aura
lieu côté Mongo.

**État vérifié en direct le 2026-09-07** :

| Store | Total | Valides | Rebaselined | Pré-HMAC (`null_hash`) | Altérées |
|---|---|---|---|---|---|
| SQLite (`data/invoices.db`) | 708 | 139 | 569 | 0 | **0** |
| MongoDB (`audit_logs`) | 1050 | 1046 | 0 | 4 | **0** |

`tampered_count` = 0 sur les deux stores, confirmé via `compute_integrity_summary()`
(donc `/audit/verify-integrity` et `/security/summary`).

## 8. `AUDIT_HMAC_SECRET` défini pour de bon — clôture du gap S5 (2026-09-07)

**Décision** : plutôt que de laisser indéfiniment `AUDIT_HMAC_SECRET` vide
(gap S5, connu depuis le commit `87833be` du 2026-07-06 — voir section 3),
un secret dédié fort a été généré (`secrets.token_hex(32)`, 64 caractères
hex, jamais commité dans git) et posé dans `.env`. `_get_secret()`
(`api/security/audit_integrity.py`) utilise désormais réellement
`AUDIT_HMAC_SECRET`, plus jamais `JWT_SECRET` en repli — compromettre
`JWT_SECRET` seul ne permet plus de forger l'audit trail.

**Conséquence immédiate, anticipée** : poser `AUDIT_HMAC_SECRET` est en
soi une troisième valeur de clé HMAC utilisée dans l'histoire de ce
journal (après le `JWT_SECRET` d'avant le 2026-07-10, puis celui d'après —
section 3). Toute ligne/document écrit avant ce changement — y compris
les 569 lignes SQLite déjà rebaselined une première fois le 2026-07-15 —
a immédiatement cessé de vérifier contre le nouveau secret.

**Problème évité** : ré-exécuter tel quel `scripts/rebaseline_audit_hmac.py`
aurait écrasé `rebaseline_hash` sur ces 569 lignes avec la nouvelle valeur,
détruisant silencieusement la preuve du rebaseline du 2026-07-15 — exactement
le type de perte que ce mécanisme existe pour éviter (section 4). Pour
l'empêcher, `AuditLogORM` et `AuditLogDocument` gagnent 3 colonnes/champs
supplémentaires, purement additifs (migration Alembic `b3c4d5e6f7a8`) :
`prior_rebaseline_hash`, `prior_rebaselined_at`, `prior_rebaseline_reason`.
Les deux scripts de rebaseline (`scripts/rebaseline_audit_hmac.py` et
`scripts/rebaseline_audit_hmac_mongo.py`) archivent désormais l'ancien
`rebaseline_hash`/`rebaselined_at`/`rebaseline_reason` dans ces 3 champs
*avant* de les remplacer par la génération 2 — jamais réécrasés une fois
posés. `row_hash` d'origine reste, comme toujours, intact sur toutes les
lignes. `verify_row_status()`/`verify_row_status_from_doc()` ne lisent que
`row_hash` et `rebaseline_hash` (génération courante) — les champs
`prior_*` sont purement archivistiques, hors chemin de vérification.

**Exécution du 2026-09-07** :

| Store | Lignes/documents rebaselinés (génération 2) | ... dont génération 1 archivée dans `prior_*` |
|---|---|---|
| SQLite (`data/invoices.db`) | 708 | 569 |
| MongoDB (`audit_logs`) | 1046 | 0 (aucun rebaseline Mongo n'existait avant la section 7) |

Les 4 documents Mongo `row_hash = None` (section 7) restent inchangés —
non éligibles au rebaseline (aucun `row_hash` à comparer), décision déjà
actée en section 7.

**Limite connue** : ce mécanisme à 2 générations (`rebaseline_hash` +
`prior_rebaseline_hash`) suffit à l'historique connu de ce projet (2
rotations : 2026-07-10 puis 2026-09-07) mais ne s'étend pas automatiquement
à une 3ᵉ rotation future — une nouvelle rotation écraserait `prior_*` sans
archivage supplémentaire. Si `AUDIT_HMAC_SECRET` doit être re-tourné un
jour, prévoir soit un historique en profondeur (liste plutôt que 2 champs
fixes), soit accepter explicitement la perte de la génération 1 à ce
moment-là — décision à documenter le moment venu, pas anticipée ici.

**État vérifié en direct après l'exécution (2026-09-07)** — via
`compute_integrity_summary()` (le code réel derrière `/audit/verify-integrity`
et `/security/summary`), Beanie correctement initialisé :

```
total_checked      = 1758   (708 SQLite + 1050 Mongo)
valid              = 4      (les 4 documents Mongo pré-HMAC, section 7)
null_hash_count    = 4
rebaselined_count  = 1754
tampered_count     = 0
integrity_score    = 100.0 %
```

`tampered_count` = 0 sur les deux stores, comme avant ce changement — le
score d'intégrité affiché ne change pas pour un opérateur consultant le
tableau de bord, mais le gap de sécurité S5 (audit trail signé sous
`JWT_SECRET`, une clé qui sert aussi à l'authentification) est clos pour
de bon.
