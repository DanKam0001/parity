# Risk Report — CBACT04C.cbl Translation to Java

## 1. Implicit truncation without ROUNDED (interest calculation)

**Lines:** 464–465

```cobol
COMPUTE WS-MONTHLY-INT
 = ( TRAN-CAT-BAL * DIS-INT-RATE) / 1200
```

**Why it is risky:**  
`WS-MONTHLY-INT` is declared `PIC S9(09)V99` (two decimal places). The `COMPUTE` statement has no `ROUNDED` clause, so COBOL silently truncates any sub-cent fraction toward zero. Java `double` or `float` arithmetic would instead round to the nearest representable value — a different behaviour. `BigDecimal` with `HALF_UP` rounding also differs from truncation. The error per category is less than $0.01, but it accumulates: with hundreds of categories across millions of accounts the total posted interest will diverge from the COBOL baseline.

**How Java must handle it:**  
Use `BigDecimal` for all interest arithmetic. Divide using `RoundingMode.DOWN` (truncation toward zero) with scale 2:
```java
BigDecimal monthly = catBal.multiply(intRate)
    .divide(BigDecimal.valueOf(1200), 2, RoundingMode.DOWN);
```
Do not use `double`/`float` at any intermediate step.

---

## 2. Test-before PERFORM UNTIL (loop structure)

**Lines:** 188–222

```cobol
PERFORM UNTIL END-OF-FILE = 'Y'
    IF  END-OF-FILE = 'N'
        PERFORM 1000-TCATBALF-GET-NEXT
        ...
    ELSE
         PERFORM 1050-UPDATE-ACCOUNT
    END-IF
END-PERFORM.
```

**Why it is risky:**
`PERFORM UNTIL` is test-before: the loop condition is evaluated *before* the body runs on each iteration. When `1000-TCATBALF-GET-NEXT` sets `END-OF-FILE = 'Y'` (inside the body, line 340), execution returns to the top of the loop, the condition `END-OF-FILE = 'Y'` is immediately true, and the loop exits. The `ELSE` branch at line 219 (`PERFORM 1050-UPDATE-ACCOUNT`) therefore **never executes** — it is dead code for every possible input, empty file or not. The result is that the last account in the file always has its interest transactions written to TRANSACT but its balance is never updated and its cycle credit/debit counters are never zeroed. This has been confirmed by run output: the last account record is byte-for-byte unchanged after a full run.

**How Java must handle it:**
Reproduce the bug faithfully. Do not add a post-loop flush call:
```java
while (!endOfFile) {
    if (!endOfFile) {
        readNext();           // may set endOfFile = true
        if (!endOfFile) {
            processRecord();
        }
    } else {
        updateAccount();      // DEAD CODE — never reached; preserved for structural fidelity
    }
}
// FAITHFUL: no post-loop updateAccount() call; last account balance intentionally not posted
```

---

## 3. FILE STATUS '23' handling on DISCGRP read

**Lines:** 416–439

```cobol
READ DISCGRP-FILE INTO DIS-GROUP-RECORD
     INVALID KEY
        DISPLAY 'DISCLOSURE GROUP RECORD MISSING'
        ...
END-READ.
IF  DISCGRP-STATUS  = '00'  OR '23'
    MOVE 0 TO APPL-RESULT
...
IF  DISCGRP-STATUS  = '23'
    MOVE 'DEFAULT' TO FD-DIS-ACCT-GROUP-ID
    PERFORM 1200-A-GET-DEFAULT-INT-RATE
```

**Why it is risky:**  
Status '23' (key not found on a random-access read) is deliberately treated as non-fatal so the program can fall back to a DEFAULT rate. However, after a '23' read the content of `DIS-GROUP-RECORD` is undefined — it holds whatever was in the I/O buffer from the previous successful read. If the fallback read in `1200-A-GET-DEFAULT-INT-RATE` also fails (status not '00'), the program abends, but that paragraph contains no `INVALID KEY` clause — an unhandled path. In Java, a failed key lookup throws or returns null; there is no equivalent of "buffer holds stale data silently."

**How Java must handle it:**  
The lookup should return `Optional<DisGroupRecord>`. On empty result, retry with key `("DEFAULT", tranTypeCode, tranCatCode)`. If the second lookup also returns empty, throw a descriptive exception (equivalent of the abend). Never use stale data from a previous read. Add an explicit check and error log matching the COBOL `DISPLAY` messages for auditability.

---

## 4. Alternate-key READ on XREF-FILE

**Lines:** 393–413

```cobol
READ XREF-FILE INTO CARD-XREF-RECORD
 KEY IS FD-XREF-ACCT-ID
    INVALID KEY
       DISPLAY 'ACCOUNT NOT FOUND: ' FD-XREF-ACCT-ID
END-READ
```

**Why it is risky:**  
VSAM KSDS supports alternate (non-unique) keys; the READ returns the *first* record matching the alternate key. If more than one card is linked to the same account, only the first (in alternate-index order) is returned and its card number is stamped on every transaction for that account. Java VSAM/KSDS replacements (e.g. JdbcTemplate against a relational table, or a flat-file index) must replicate this "first match" semantics explicitly. A `SELECT … WHERE acct_id = ?` returning multiple rows requires an `ORDER BY` that matches the original VSAM alternate-index sequence, followed by `LIMIT 1` (or `fetchFirst(1)`).

**How Java must handle it:**  
Query by account ID, order by the same collation used to build the VSAM alternate index (ascending card number), and take only the first result. Log a warning if more than one card maps to the same account so the business can review the data.

---

## 5. Overpunched signed DISPLAY fields

**Lines:** 9 (CVTRA02Y), 9–10 (CVTRA01Y), 7–14 (CVACT01Y), 10 (CVTRA05Y)

Fields such as `TRAN-CAT-BAL PIC S9(09)V99`, `DIS-INT-RATE PIC S9(04)V99`, `ACCT-CURR-BAL PIC S9(10)V99`, `WS-MONTHLY-INT PIC S9(09)V99`, and `TRAN-AMT PIC S9(09)V99` are declared with PIC S… but without `COMP` or `BINARY`. On most mainframe COBOL compilers these become DISPLAY (zoned decimal) fields where the sign is encoded as an overpunch in the last nibble of the rightmost digit (EBCDIC zone bits). When the file records are read as raw bytes in Java, a negative value such as -12.50 will have its last byte as an EBCDIC overpunched character (e.g. `}` for -0, `J` for -1, etc.) rather than a plain ASCII digit.

**How Java must handle it:**  
Use a COBOL-aware record parser (e.g. JRecord, cb2java, or a custom `ZonedDecimalCodec`) to decode PIC S9…V99 DISPLAY fields. Never read these bytes as plain UTF-8 or ASCII strings and parse them with `new BigDecimal(string)`. The codec must handle both positive (zone = `C`) and negative (zone = `D`) overpunch conventions and apply the implied decimal point (V position).

---

## 6. STRING into TRAN-ID

**Lines:** 476–480

```cobol
STRING PARM-DATE,
       WS-TRANID-SUFFIX
  DELIMITED BY SIZE
  INTO TRAN-ID
END-STRING.
```

**Why it is risky:**  
`PARM-DATE` is `PIC X(10)` and `WS-TRANID-SUFFIX` is `PIC 9(06)` — together exactly 16 characters, matching `TRAN-ID PIC X(16)`. `DELIMITED BY SIZE` uses the full declared size of each operand with no truncation check. In COBOL, `STRING … DELIMITED BY SIZE` does not raise an overflow condition in the absence of an `ON OVERFLOW` clause; it silently truncates if the receiving field is too short. In this specific case there is no overflow because 10+6=16, but if `PARM-DATE` ever carries a value shorter than 10 characters (e.g. a 8-character date with trailing spaces), the suffix will be right-shifted into the ID, producing unintended padding. Java `String.format` or `StringBuilder` does not replicate the DELIMITED BY SIZE padding behaviour automatically.

**How Java must handle it:**  
Construct the ID as:
```java
String tranId = String.format("%-10s%06d", parmDate, tranIdSuffix);
```
The `%-10s` left-justifies and space-pads `parmDate` to exactly 10 characters, matching COBOL DISPLAY field semantics. Assert `tranId.length() == 16` to catch unexpected input.

---

## 7. CURRENT-DATE timestamps

**Lines:** 613–626

```cobol
Z-GET-DB2-FORMAT-TIMESTAMP.
    MOVE FUNCTION CURRENT-DATE TO COBOL-TS
```

**Why it is risky:**  
COBOL's `FUNCTION CURRENT-DATE` returns a 21-character string containing the local date/time *plus* a 5-character UTC offset (e.g. `-0500`). The program copies only the first 17 characters (year/month/day/hour/min/sec/hundredths) into a DB2-format timestamp and hardcodes `DB2-REST` to `'0000'` (microseconds). Hundredths of seconds are stored in `DB2-MIL` as two digits. The result is a wall-clock local timestamp, not UTC. In Java, `LocalDateTime.now()` returns local time with nanosecond precision; `Instant.now()` returns UTC. Using the wrong one or using nanoseconds without truncating to centiseconds will produce timestamps that differ from the COBOL baseline.

**How Java must handle it:**  
Use `LocalDateTime.now()` (matching the COBOL local-time behaviour), then format as `yyyy-MM-dd-HH.mm.ss.SS0000` where `SS` is the two-digit centiseconds (hundredths), truncated — not rounded — from the nanosecond field:
```java
LocalDateTime now = LocalDateTime.now();
String ts = String.format("%04d-%02d-%02d-%02d.%02d.%02d.%02d0000",
    now.getYear(), now.getMonthValue(), now.getDayOfMonth(),
    now.getHour(), now.getMinute(), now.getSecond(),
    now.getNano() / 10_000_000);   // truncate to centiseconds
```

---

## 8. CALL to CEE3ABD (LE runtime abend)

**Lines:** 628–632

```cobol
9999-ABEND-PROGRAM.
    MOVE 0 TO TIMING
    MOVE 999 TO ABCODE
    CALL 'CEE3ABD' USING ABCODE, TIMING.
```

**Why it is risky:**  
`CEE3ABD` is a Language Environment (LE) runtime service that forces an abnormal termination with a specific completion code (999 here) and optionally captures a dump. It is entirely mainframe-specific. In Java there is no equivalent entry point; a plain `System.exit(999)` is the closest behavioural match but it bypasses Spring shutdown hooks, JVM shutdown hooks, open transaction rollbacks, and logging flushes.

**How Java must handle it:**  
Replace `9999-ABEND-PROGRAM` with a method that:
1. Logs the error at FATAL level with the file status and context.
2. Throws a dedicated unchecked exception (e.g. `BatchAbendException`) that propagates to the job framework (Spring Batch `Step`) so it can record the failure, close resources via `ItemStream.close()`, and exit with a non-zero status code. Do not call `System.exit()` directly.

---

## Overall Risk Rating: **HIGH**

**Rationale:**  
Five of the eight constructs identified carry financial correctness risk or silent data corruption risk:

- The **truncation-without-ROUNDED** rule (§1) will silently produce interest amounts that differ from the COBOL baseline on every single category where the sub-cent fraction is non-zero. The divergence is small per record but material in aggregate across a large portfolio.
- The **overpunched signed DISPLAY fields** (§5) will cause every monetary amount to be misread as garbled characters unless a specialist codec is used — this is a hard blocker on any flat-file or VSAM-to-Java path.
- The **test-before PERFORM UNTIL** structure (§2) means the last account's balance update will be silently skipped if the loop structure is not replicated exactly, causing one account per run to receive no interest posting with no error raised.
- The **FILE STATUS '23' / DEFAULT fallback** (§3) has an untested code path (missing DEFAULT record) that abends in COBOL but would likely produce a null-pointer or wrong result in a naive Java translation.
- The **CEE3ABD abend** (§8) and **alternate-key READ** (§4) are platform-specific behaviours with no direct Java equivalent, requiring explicit design decisions.

No single construct is trivial to translate correctly, and several interact (e.g. truncation feeds the balance update, which feeds the account rewrite). A translation that passes unit tests on typical data can still diverge on edge cases (sub-cent interest, missing DISCGRP records, empty input file) in production.
