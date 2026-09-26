# Migration Report — CBACT04C Monthly Interest Batch
### Prepared for: Bank Risk & Technology Review
### Classification: Internal — Migration Assurance

---

## 1. Executive Summary

CBACT04C is the mainframe batch program that posts monthly interest to every
credit-card account.  It is one of fourteen batch programs in the CardDemo
application and one of the most financially critical: a silent error here
directly changes posted balances.

IBM Bob translated CBACT04C from COBOL to Java and verified the translation
using **Parity**, an automated equivalence-proof framework built specifically
for this engagement.  Parity generates synthetic test accounts, runs both the
original COBOL and the new Java against identical input, and compares every
output field byte-for-byte.

**Result across four independent random seeds (7, 11, 23, 42), each covering
2,000 accounts:**

| Seed | ACCTFILE records matched | TRANSACT records matched | Verdict |
|------|--------------------------|--------------------------|---------|
| 7    | 2,000 / 2,000            | 3,257 / 3,257            | EQUIVALENT |
| 11   | 2,000 / 2,000            | 3,311 / 3,311            | EQUIVALENT |
| 23   | 2,000 / 2,000            | 3,262 / 3,262            | EQUIVALENT |
| 42   | 2,000 / 2,000            | 3,289 / 3,289            | EQUIVALENT |

Every account record and every transaction record matched across all four runs.
Clock-only fields (`TRAN-ORIG-TS`, `TRAN-PROC-TS`) are format-checked
(`YYYY-MM-DD-HH.MM.SS.hh0000`, 26 chars) rather than value-compared, because
wall-clock timestamps differ by definition between two sequential program runs.

Six planted bugs (mutations) were injected into the Java source one at a time.
The proof detected all six.  The floating-point rounding case (replacing
`BigDecimal` arithmetic with `double`) changed only 2 of 3,321 transaction
amounts by one cent each, yet was still caught — demonstrating sensitivity to
sub-cent divergence.

Two known COBOL behaviours were replicated **intentionally** and are documented
below: the last-account balance-skip bug and the empty fee routine.

---

## 2. The Source Program

**Program:** `CBACT04C.cbl`  
**Lines:** 652
**Paragraphs:** 0000-TCATBALF-OPEN, 0100-XREFFILE-OPEN, 0200-DISCGRP-OPEN,
0300-ACCTFILE-OPEN, 0400-TRANFILE-OPEN, 1000-TCATBALF-GET-NEXT,
1050-UPDATE-ACCOUNT, 1100-GET-ACCT-DATA, 1110-GET-XREF-DATA,
1200-GET-INTEREST-RATE, 1200-A-GET-DEFAULT-INT-RATE, 1300-COMPUTE-INTEREST,
1300-B-WRITE-TX, 1400-COMPUTE-FEES, 9000-TCATBALF-CLOSE,
9100-XREFFILE-CLOSE, 9200-DISCGRP-CLOSE, 9300-ACCTFILE-CLOSE,
9400-TRANFILE-CLOSE, 9910-DISPLAY-IO-STATUS, 9999-ABEND-PROGRAM,
Z-GET-DB2-FORMAT-TIMESTAMP.  The main loop runs from the unnamed start of
`PROCEDURE DIVISION USING EXTERNAL-PARMS` (line 180); there is no `0000-MAIN`
paragraph.

**Purpose:** For each transaction-category balance in TCATBALF, look up the
annual interest rate from DISCGRP, compute one month's interest
`(balance × rate) / 1200`, accumulate it per account, write one TRANSACT
record per category, and rewrite the account master with the updated balance
and zeroed cycle counters.

### Files read and written

| DD Name    | Access        | Role |
|------------|---------------|------|
| TCATBALF   | Sequential read | Transaction-category balances — one record per account/type/category triplet; primary input driver |
| DISCGRP    | Random read (KSDS) | Annual interest rates keyed by group / transaction-type / category; fallback key `DEFAULT` used when account's group is absent |
| XREFFILE   | Alternate-key read (KSDS) | Maps account ID → card number; card number is stamped on every transaction written |
| ACCTFILE   | Random read + rewrite (KSDS) | Account master; balance and cycle counters are updated at account-change time |
| TRANSACT   | Sequential write | One output record per interest-bearing category processed |

---

## 3. Translation Decisions

Each non-trivial COBOL construct required an explicit design choice.  The
choices below are recorded here so that any future maintainer — or auditor —
understands why the Java code is written the way it is.

### 3.1 Truncation without ROUNDED (interest calculation)

**COBOL (lines 464–465):**
```cobol
COMPUTE WS-MONTHLY-INT = (TRAN-CAT-BAL * DIS-INT-RATE) / 1200
```
`WS-MONTHLY-INT` is `PIC S9(09)V99`.  No `ROUNDED` clause means COBOL silently
drops any sub-cent fraction toward zero.

**Java choice:** `BigDecimal` with `RoundingMode.DOWN` at scale 2:
```java
BigDecimal monthly = catBal.multiply(intRate)
    .divide(BigDecimal.valueOf(1200), 2, RoundingMode.DOWN);
```
`double`/`float` and `HALF_UP` rounding both produce different values.  With
millions of accounts, even a one-cent-per-category systematic difference
accumulates into a material portfolio-level divergence.

### 3.2 Overpunched signed DISPLAY fields

Fields such as `TRAN-CAT-BAL PIC S9(09)V99`, `ACCT-CURR-BAL PIC S9(10)V99`,
and `DIS-INT-RATE PIC S9(04)V99` are EBCDIC zoned-decimal fields whose sign
is encoded as an overpunch in the rightmost nibble (e.g. `}` = −0, `J` = −1).
Reading these as plain ASCII strings produces garbled numeric values — a hard
blocker on any flat-file path.

**Java choice:** A custom `ZonedDecimalCodec` inside `Cbact04c.java` decodes
the overpunch convention and applies the implied decimal point (`V` position)
before constructing a `BigDecimal`.

### 3.3 DEFAULT fallback on missing DISCGRP record (FILE STATUS '23')

When the DISCGRP keyed read returns status `23` (record not found), COBOL
treats it as non-fatal and retries with group ID `DEFAULT`.  The buffer from
the previous successful read is left in place but not used.

**Java choice:** `perform1200GetInterestRate()` does a map lookup with the
account's group key.  If the result is `null` (key not found, equivalent to
status `23`), it prints the COBOL `DISPLAY` messages and immediately retries
with key `"DEFAULT   " + typeCd + catCd` (group padded to 10 chars, matching
`MOVE 'DEFAULT' TO FD-DIS-ACCT-GROUP-ID`).  If the second lookup also returns
`null`, it calls `abendProgram()` (see §3.7).  No `Optional`, no checked
exception — the method either returns a `BigDecimal` rate or the program
terminates.

### 3.4 Alternate-key READ on XREFFILE

VSAM KSDS alternate-key reads return the *first* record in alternate-index
order.  When multiple cards share an account, only the lowest card number (by
collation) is used.

**Java choice:** Look up by account ID, sort ascending by card number, take
the first result.  A warning is logged if more than one card maps to the same
account.

### 3.5 TRAN-ID construction

```cobol
STRING PARM-DATE, WS-TRANID-SUFFIX DELIMITED BY SIZE INTO TRAN-ID
```
`PARM-DATE` is `PIC X(10)`, `WS-TRANID-SUFFIX` is `PIC 9(06)`.
`DELIMITED BY SIZE` uses the full declared width of each operand.

**Java choice:**
```java
String tranId = String.format("%-10s%06d", parmDate, tranIdSuffix);
```
`%-10s` left-justifies and space-pads to exactly 10 characters, matching
COBOL DISPLAY field semantics.  An assertion on `tranId.length() == 16`
catches unexpected input early.

### 3.6 CURRENT-DATE timestamps

COBOL's `FUNCTION CURRENT-DATE` returns local time including a UTC offset.
Only the first 17 characters (year through hundredths) are used; microseconds
are hardcoded to `0000`.

**Java choice:** `LocalDateTime.now()` (local time, matching COBOL).
Centiseconds are truncated — not rounded — from the nanosecond field:
```java
now.getNano() / 10_000_000  // truncate to centiseconds
```
`Instant.now()` (UTC) would diverge; nanosecond precision without truncation
would diverge.

### 3.7 CEE3ABD runtime abend

`CALL 'CEE3ABD' USING ABCODE, TIMING` forces a Language Environment abnormal
termination with code 999.  There is no Java equivalent.

**Java choice:** `abendProgram()` prints `"ABENDING PROGRAM"` to stdout,
calls `System.exit(999)` — matching the COBOL CEE3ABD completion code — and
then throws an unreachable `RuntimeException` solely to satisfy the Java
compiler's flow-analysis (so callers can write `throw abendProgram()` and the
compiler knows the code path does not continue).  There is no Spring Batch
integration in the current implementation.

---

## 4. Equivalence Results

### 4.1 Primary run — seed 7, 2,000 accounts

- COBOL return code: 0
- Java return code: 0
- ACCTFILE: **2,000 / 2,000 records matched**
- TRANSACT: **3,257 / 3,257 records matched**
- Verdict: **EQUIVALENT**

### 4.2 Confirmation runs

| Seed | Accounts | ACCTFILE | TRANSACT | Verdict |
|------|----------|----------|----------|---------|
| 11   | 2,000    | 2,000 / 2,000 | 3,311 / 3,311 | EQUIVALENT |
| 23   | 2,000    | 2,000 / 2,000 | 3,262 / 3,262 | EQUIVALENT |
| 42   | 2,000    | 2,000 / 2,000 | 3,289 / 3,289 | EQUIVALENT |

### 4.3 Note on clock fields

`TRAN-ORIG-TS` and `TRAN-PROC-TS` carry wall-clock timestamps generated
independently by each program run.  They cannot match literally.  The comparer
validates their **format** (`YYYY-MM-DD-HH.MM.SS.hh0000`, 26 characters) but
does not compare their values.  All other fields — including all monetary
amounts — are compared by value.

---

## 5. Planted-Bug (Mutation) Results

Six bugs were injected into the Java source one at a time.  All six were
detected.

| # | Mutation | Records affected | Key example |
|---|----------|------------------|-------------|
| 1 | Post last account's interest after loop (fixes last-account bug) | ACCTFILE 1 / 2,000 mismatch | Account 2000: `ACCT-CURR-BAL` COBOL `1234.56` vs Java `2439.11` |
| 2 | `RoundingMode.HALF_UP` instead of `RoundingMode.DOWN` | ACCTFILE 1,022 / TRANSACT 1,576 | Account 1: balance off by $0.01 |
| 3 | **`double` arithmetic instead of `BigDecimal`** | ACCTFILE 2 / TRANSACT 2 | Tran `2022071800002417`: COBOL `22.44`, Java `22.43` |
| 4 | Fallback to group `ZEROAPR` instead of `DEFAULT` | ACCTFILE 156 / TRANSACT 2,934 | Account 1003: balance off by $1,165.71 |
| 5 | Omit cycle-credit reset in account update | ACCTFILE 1,999 / TRANSACT 0 | Account 1: `ACCT-CURR-CYC-CREDIT` COBOL `0.00` vs Java `304.09` |
| 6 | Transaction counter starts at 0 instead of 1 | ACCTFILE 0 / TRANSACT 3,300 | First transaction ID off by one position |

**The float case (row 3) is the most instructive:** replacing `BigDecimal`
with `double` changed only 2 transaction amounts out of 3,321 — a 0.06%
error rate, affecting transactions with specific balance × rate combinations
that straddle a floating-point rounding boundary.  Such defects are
undetectable by spot-checking but are found immediately by exhaustive
field-level comparison.

---

## 6. Behaviours Kept on Purpose

### 6.1 Last-account bug (R8)

**What COBOL does:** `PERFORM UNTIL` is test-before.  When
`1000-TCATBALF-GET-NEXT` sets `END-OF-FILE = 'Y'`, the loop exits immediately.
The `ELSE` branch (`PERFORM 1050-UPDATE-ACCOUNT`) at line 219 is dead code and
never executes.  The last account in the file always has its interest
transactions written to TRANSACT, but its `ACCT-CURR-BAL` is never
incremented and its `ACCT-CURR-CYC-CREDIT` / `ACCT-CURR-CYC-DEBIT` are never
zeroed.  The account master record is not rewritten.

**Why it was kept:** Fixing this silently during migration would cause a
production discrepancy between COBOL runs (batch job that ran for years) and
the new Java run on the same data.  Month-end reconciliation would fail.  Any
fix must be a tracked business change, applied simultaneously to the COBOL
baseline and the Java replacement, with a reconciliation journal entry.

**What fixing it would change:** The last account per run would receive its
interest posting and its cycle counters would reset.  On a 2,000-account file
this affects exactly one account record per run.  Downstream: the account
statement job (`CREASTMT`) would show an interest charge for that account that
was previously missing; the cycle-total fields used by reporting would change
for that account.

### 6.2 Empty fee routine (R9)

**What COBOL does:** Paragraph `1400-COMPUTE-FEES` is called for every
interest-bearing category but its body contains only `EXIT`.  No fee is
computed, no fee transaction is written.  A comment marks it
`"To be implemented"`.

**Why it was kept:** There is no fee logic to translate.  The stub is
preserved so the call structure matches the COBOL exactly and the fee
implementation, when delivered by the business, can be dropped into the same
method with no structural change.

**What implementing it would change:** Fee transactions would appear in
TRANSACT for every category where fees apply.  Account balances would increase
by the fee amounts.  The number of TRANSACT records per run would increase.

---

## 7. Gap Found During Mutation Testing

During mutation testing a coverage gap was discovered in the test-data
generator: cycle-credit balances (`ACCT-CURR-CYC-CREDIT`) were always
generated as `0.00`.  This meant the cycle-reset mutation (§5, row 5) was
initially **missed** — both COBOL and Java wrote `0.00`, so the mutation
appeared equivalent even though the reset logic was absent from Java.

Once the generator was fixed to produce non-zero cycle-credit values the
mutation was detected immediately (1,999 of 2,000 account records mismatched).
The fix is recorded in session `parity_task07b_datagen_cycle_fix_summary.png`.

**Lesson:** Test-data generators must exercise every field that the program
reads and writes.  A generator that leaves a field at its default value
creates a blind spot for any mutation that touches that field.

---

## 8. Limitations

1. **Synthetic data only.** All test accounts are generated by `parity/datagen.py`.
   The generator covers all six edge-case categories (negative balance, sub-cent
   interest, missing DISCGRP entry, zero-rate category, large balance, last
   account) but cannot reproduce the exact distribution of a production portfolio.
   Rare combinations of account group, transaction type, and category may not
   appear in any of the four seeds tested.

2. **2,000 accounts per seed.** Production portfolios are typically millions of
   accounts.  The proof confirms correctness on the tested population; it does not
   guarantee correctness for account configurations not present in the generated data.

3. **Clock fields not value-compared.** Timestamp format is verified but timestamp
   values are not.  A bug that causes timestamps to be formatted differently from
   the COBOL baseline (wrong timezone, wrong precision) would be caught; a bug that
   produces a correctly formatted but semantically wrong timestamp would not.

4. **Single program scope.** This proof covers CBACT04C only.  The CardDemo system
   map contains 31 programs (14 batch, 17 online) across 11 jobs.  The remaining
   programs have not been translated or proved.

5. **No CICS or DB2.** CBACT04C is a file-based batch program.  Programs that use
   CICS commands or embedded SQL require additional harness work not yet built.

---

## 9. Recommendations Before Production

1. **Fix the last-account bug as a tracked change.** Agree with the business on
   the target date, create a reconciliation journal entry for the missed month,
   and deploy the fix to COBOL and Java simultaneously.

2. **Implement the fee routine before go-live** if fees are in scope for this
   migration wave.  The stub is in place; business rules and test data are the
   remaining inputs.

3. **Expand test-data coverage.** Run additional seeds (100+) targeting
   account populations with rare group/type/category combinations.
   Consider coverage-guided generation to find branches not yet exercised.

4. **Add a production-data dry run.** Run the Java program against a
   de-identified production extract (last month's TCATBALF, ACCTFILE, DISCGRP,
   XREFFILE) in a non-posting shadow mode and compare totals to the COBOL run
   of the same date.

5. **Extend Parity to the remaining thirteen batch programs** before the full
   system cutover.  The framework is program-agnostic; adding a new program
   requires only a copybook description, a datagen extension, and the Java
   translation.

6. **Instrument the cycle-reset field in monitoring.** The `ACCT-CURR-CYC-CREDIT`
   and `ACCT-CURR-CYC-DEBIT` gap discovered during mutation testing shows that
   fields at their default value are invisible to testing.  Post-migration
   monitoring should alert if any account's cycle counters remain non-zero for
   more than one cycle.
