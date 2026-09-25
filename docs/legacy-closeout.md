# Legacy riddle closeout plan

> **Purpose:** how to settle what the retired riddle game still owes before combat launches. \
> **Audience:** the owner; operators. \
> **Status:** guide (proposal for stage P8). **Nothing in this document has been executed.** \
> **Last reviewed:** 2026-09-25 (inventory figures dated 2026-09-23, not re-run)

Every send below needs explicit authorisation and the existing
[audit gates](../audits/README.md). The combat contract takes on no legacy
liability, rating or record.

## Inventory, as of 2026-09-23

Produced read-only by `qdojo house legacy-inventory` from the house data
directory:

| Item | Value |
|---|---:|
| Rounds on disk | 122 |
| Unsettled rounds | 0 |
| Carry | 0 QU |
| Open bonds | 10 bonds, 24,000 QU, 6 holders, oldest from round 118 |
| Shareholder rake pool not yet distributed | 34,860 QU |
| Distribution awaiting confirmation | none |

To refresh it:

```sh
uv run qdojo house --data private/house legacy-inventory
```

Not yet checked: whether the house identity's confirmed on-chain balance
covers open bonds plus the undistributed pool. Check this with a node read
before any step below.

## Proposed sequence

1. **Freeze new riddle rounds.** Stop the publish loop, so no new entry fee
   or bond is accepted. Settled history and exports stay online, read-only,
   behind the site's Legacy label.
2. **Bonds.** No new rounds means no bond can ever reach its release
   condition. Forfeiting them because the game stopped would penalise the
   holders for our decision, so the proposal is to **return each open bond in
   full** to its holder. Each return is a separately confirmed transfer,
   recorded in a closeout ledger (holder, amount, tx, tick).
3. **Shareholder pool.** Distribute the accrued pool with the existing
   two-step command, plan first and apply after review:
   `qdojo house distribute-shareholders ASSET`, then `--apply`.
   The QUtil fee and rounding follow `shares.py`.
4. **Reconcile.** Re-run the inventory. Open bonds and the pool must both
   read 0, and every transfer must have confirmed.
5. **Archive.** Publish the final inventory and closeout ledger next to the
   riddle archive, and retire the riddle namespace from the active docs.

Old fighters keep their legacy records in the archive. They are not relabelled
as independent combat users and get no combat rating; the founding combat
fighters are issued separately under the release manifest.
