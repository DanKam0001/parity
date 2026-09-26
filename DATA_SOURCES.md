# Data Sources

## AWS CardDemo (COBOL source program)

The COBOL program translated in this project (`CBACT04C.cbl`) and its
associated copybooks, JCL, and supporting programs are from the
**AWS Mainframe Modernization CardDemo** sample application.

- **Repository:** <https://github.com/aws-samples/aws-mainframe-modernization-carddemo>
- **License:** Apache License 2.0
- **Vendored at:** `vendor/carddemo/`
- The vendored copy includes the upstream `LICENSE` and `NOTICE` files from
  that repository unchanged.

No modifications have been made to the COBOL source files.  The harness
programs in `harness/` (DRIVER, loaders, unloader, CEE3ABD stub) are original
to this project.

---

## Test Accounts

All test accounts used for equivalence proofs and mutation testing are
**synthetic**, generated at runtime by `parity/datagen.py`.

- Accounts are generated from a seeded pseudo-random number generator; the
  same seed always produces the same data.
- The generator covers six edge-case categories: negative balance, sub-cent
  interest, missing DISCGRP entry (DEFAULT fallback), zero-rate category,
  large balance, and last-account (exercises the known loop-exit bug).
- No real cardholder names, account numbers, addresses, or transaction
  histories are used at any stage of the proof.

**No personal data and no client data are present in this repository.**
