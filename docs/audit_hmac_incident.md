# Note technique — Incident HMAC sur le journal d'audit (`audit_logs`)

**Date de rédaction :** 2026-07-13
**Statut :** limitation connue, documentée, non corrigée intentionnellement
**Périmètre :** table SQLite `audit_logs` (`data/invoices.db`), mécanisme de
vérification `api/security/audit_integrity.py::verify_row_hash()`

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
- Décision finale (accepter la limite en l'état vs. autre action) laissée
  au responsable du stage/superviseur, conformément à la politique du
  projet sur les changements touchant à l'intégrité de l'audit.
