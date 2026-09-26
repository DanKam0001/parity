import java.io.*;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.LocalDateTime;
import java.util.*;

/**
 * Java rewrite of CBACT04C.CBL (CardDemo interest-calculation batch program).
 *
 * Invocation: java -cp <dir> Cbact04c <in_dir> <out_dir> <parm>
 *   <parm> = PARM-DATE, exactly 10 characters (e.g. "2022071800")
 *
 * Input files (fixed-width, LF-terminated lines in <in_dir>):
 *   TCATBALF.txt  – 50-byte records, sorted by key
 *   XREFFILE.txt  – 50-byte records
 *   ACCTFILE.txt  – 300-byte records
 *   DISCGRP.txt   – 50-byte records
 *
 * Output files in <out_dir>:
 *   ACCTFILE.txt  – every account from input, 300-byte lines (LF), in key order;
 *                   only accounts that were processed have updated balances.
 *   TRANSACT.dat  – 350-byte records concatenated with no newlines or separators.
 */
public class Cbact04c {

    // ── overpunch helpers ──────────────────────────────────────────────────────

    /** Positive overpunch zone: {ABCDEFGHI → digits 0-9 */
    private static final String OVP_POS = "{ABCDEFGHI";
    /** Negative overpunch zone: }JKLMNOPQR → digits 0-9 */
    private static final String OVP_NEG = "}JKLMNOPQR";

    /**
     * Decode a COBOL DISPLAY overpunched signed decimal field.
     *
     * @param raw   the fixed-width byte[] buffer
     * @param off   start offset (0-based)
     * @param intDigits number of digits before the implied decimal point (V)
     * @param decDigits number of digits after the implied decimal point
     * @return BigDecimal value (exact, no rounding)
     */
    private static BigDecimal decodeOverpunch(byte[] raw, int off,
                                               int intDigits, int decDigits) {
        int totalBytes = intDigits + decDigits;
        // read the digit bytes, translating the last byte's sign overpunch
        char[] digits = new char[totalBytes];
        boolean negative = false;
        for (int i = 0; i < totalBytes; i++) {
            char c = (char)(raw[off + i] & 0xFF);
            if (i == totalBytes - 1) {
                int posIdx = OVP_POS.indexOf(c);
                int negIdx = OVP_NEG.indexOf(c);
                if (posIdx >= 0) {
                    digits[i] = (char)('0' + posIdx);
                    negative = false;
                } else if (negIdx >= 0) {
                    digits[i] = (char)('0' + negIdx);
                    negative = true;
                } else {
                    // plain digit – positive
                    digits[i] = c;
                }
            } else {
                digits[i] = c;
            }
        }
        String s = new String(digits);
        BigDecimal bd = new BigDecimal(s).movePointLeft(decDigits);
        return negative ? bd.negate() : bd;
    }

    /**
     * Encode a BigDecimal into a COBOL DISPLAY overpunched signed field.
     * Result is exactly (intDigits + decDigits) bytes, written into dest starting
     * at offset off.
     */
    private static void encodeOverpunch(BigDecimal value, byte[] dest, int off,
                                         int intDigits, int decDigits) {
        int totalBytes = intDigits + decDigits;
        // truncate toward zero to the required scale (DOWN = toward zero)
        BigDecimal v = value.setScale(decDigits, RoundingMode.DOWN);
        boolean negative = v.signum() < 0;
        BigDecimal abs = v.abs();
        // format as zero-padded integer string (no decimal point)
        String unscaled = abs.unscaledValue().toString();
        // pad / truncate to totalBytes
        while (unscaled.length() < totalBytes) unscaled = "0" + unscaled;
        if (unscaled.length() > totalBytes) {
            // FAITHFUL: COBOL silently truncates high-order overflow
            unscaled = unscaled.substring(unscaled.length() - totalBytes);
        }
        byte[] bytes = unscaled.getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(bytes, 0, dest, off, totalBytes);
        // overpunch the last byte
        int lastDigit = dest[off + totalBytes - 1] - '0';
        dest[off + totalBytes - 1] = (byte)(negative
                ? OVP_NEG.charAt(lastDigit)
                : OVP_POS.charAt(lastDigit));
    }

    // ── record field accessors ─────────────────────────────────────────────────

    // TRAN-CAT-BAL-RECORD (50 bytes):
    //   TRANCAT-ACCT-ID  PIC 9(11)     off 0  len 11
    //   TRANCAT-TYPE-CD  PIC X(02)     off 11 len 2
    //   TRANCAT-CD       PIC 9(04)     off 13 len 4
    //   TRAN-CAT-BAL     PIC S9(09)V99 off 17 len 11  (9 int + 2 dec)
    //   FILLER           PIC X(22)     off 28 len 22

    private static String tcatAcctId(byte[] r) { return str(r, 0, 11); }
    private static String tcatTypeCd(byte[] r)  { return str(r, 11, 2); }
    private static String tcatCd(byte[] r)       { return str(r, 13, 4); }
    private static BigDecimal tcatBal(byte[] r)  { return decodeOverpunch(r, 17, 9, 2); }

    // ACCOUNT-RECORD (300 bytes):
    //   ACCT-ID               PIC 9(11)     off 0   len 11
    //   ACCT-ACTIVE-STATUS    PIC X(01)     off 11  len 1
    //   ACCT-CURR-BAL         PIC S9(10)V99 off 12  len 12  (10 int + 2 dec)
    //   ACCT-CREDIT-LIMIT     PIC S9(10)V99 off 24  len 12
    //   ACCT-CASH-CREDIT-LIMIT PIC S9(10)V99 off 36 len 12
    //   ACCT-OPEN-DATE        PIC X(10)     off 48  len 10
    //   ACCT-EXPIRAION-DATE   PIC X(10)     off 58  len 10
    //   ACCT-REISSUE-DATE     PIC X(10)     off 68  len 10
    //   ACCT-CURR-CYC-CREDIT  PIC S9(10)V99 off 78  len 12
    //   ACCT-CURR-CYC-DEBIT   PIC S9(10)V99 off 90  len 12
    //   ACCT-ADDR-ZIP         PIC X(10)     off 102 len 10
    //   ACCT-GROUP-ID         PIC X(10)     off 112 len 10
    //   FILLER                PIC X(178)    off 122 len 178

    private static String acctId(byte[] r)      { return str(r, 0, 11); }
    private static BigDecimal acctCurrBal(byte[] r) { return decodeOverpunch(r, 12, 10, 2); }
    private static String acctGroupId(byte[] r) { return str(r, 112, 10); }

    private static void setAcctCurrBal(byte[] r, BigDecimal v) {
        encodeOverpunch(v, r, 12, 10, 2);
    }
    private static void setAcctCurrCycCredit(byte[] r, BigDecimal v) {
        encodeOverpunch(v, r, 78, 10, 2);
    }
    private static void setAcctCurrCycDebit(byte[] r, BigDecimal v) {
        encodeOverpunch(v, r, 90, 10, 2);
    }

    // CARD-XREF-RECORD (50 bytes):
    //   XREF-CARD-NUM  PIC X(16)  off 0  len 16
    //   XREF-CUST-ID   PIC 9(09)  off 16 len 9
    //   XREF-ACCT-ID   PIC 9(11)  off 25 len 11
    //   FILLER         PIC X(14)  off 36 len 14

    private static String xrefCardNum(byte[] r)  { return str(r, 0, 16); }
    private static String xrefAcctId(byte[] r)   { return str(r, 25, 11); }

    // DIS-GROUP-RECORD (50 bytes):
    //   DIS-ACCT-GROUP-ID  PIC X(10)     off 0  len 10
    //   DIS-TRAN-TYPE-CD   PIC X(02)     off 10 len 2
    //   DIS-TRAN-CAT-CD    PIC 9(04)     off 12 len 4
    //   DIS-INT-RATE       PIC S9(04)V99 off 16 len 6   (4 int + 2 dec)
    //   FILLER             PIC X(28)     off 22 len 28

    private static BigDecimal disIntRate(byte[] r) { return decodeOverpunch(r, 16, 4, 2); }

    // TRAN-RECORD (350 bytes):
    //   TRAN-ID              PIC X(16)     off 0
    //   TRAN-TYPE-CD         PIC X(02)     off 16
    //   TRAN-CAT-CD          PIC 9(04)     off 18
    //   TRAN-SOURCE          PIC X(10)     off 22
    //   TRAN-DESC            PIC X(100)    off 32
    //   TRAN-AMT             PIC S9(09)V99 off 132 len 11
    //   TRAN-MERCHANT-ID     PIC 9(09)     off 143 len 9
    //   TRAN-MERCHANT-NAME   PIC X(50)     off 152
    //   TRAN-MERCHANT-CITY   PIC X(50)     off 202
    //   TRAN-MERCHANT-ZIP    PIC X(10)     off 252
    //   TRAN-CARD-NUM        PIC X(16)     off 262
    //   TRAN-ORIG-TS         PIC X(26)     off 278
    //   TRAN-PROC-TS         PIC X(26)     off 304
    //   FILLER               PIC X(20)     off 330

    // ── utilities ─────────────────────────────────────────────────────────────

    /** Extract a String field from a raw byte[] record (ASCII / EBCDIC display). */
    private static String str(byte[] r, int off, int len) {
        return new String(r, off, len, StandardCharsets.US_ASCII);
    }

    /** Write an ASCII string left-justified into dest, space-padded to len bytes. */
    private static void putStr(byte[] dest, int off, int len, String value) {
        Arrays.fill(dest, off, off + len, (byte)' ');
        byte[] vb = value.getBytes(StandardCharsets.US_ASCII);
        int copy = Math.min(vb.length, len);
        System.arraycopy(vb, 0, dest, off, copy);
    }

    /** Write a zero-padded decimal string into dest at off for len bytes. */
    private static void putZeroPaddedNum(byte[] dest, int off, int len, long value) {
        String s = String.format("%0" + len + "d", value);
        byte[] b = s.getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(b, 0, dest, off, len);
    }

    /**
     * Format the current local time as a DB2 timestamp.
     * Matches Z-GET-DB2-FORMAT-TIMESTAMP paragraph.
     * Format: YYYY-MM-DD-HH.MM.SS.hh0000  (26 chars)
     * hh = hundredths of a second, truncated from nanoseconds.
     */
    private static String db2Timestamp() {
        LocalDateTime now = LocalDateTime.now();
        // MANUAL REVIEW REQUIRED: COBOL uses FUNCTION CURRENT-DATE which returns
        // local time; LocalDateTime.now() is also local — this matches.
        // Hundredths: truncate nanoseconds / 10_000_000 (not rounded).
        int hh = now.getNano() / 10_000_000;
        return String.format("%04d-%02d-%02d-%02d.%02d.%02d.%02d0000",
                now.getYear(), now.getMonthValue(), now.getDayOfMonth(),
                now.getHour(), now.getMinute(), now.getSecond(), hh);
    }

    // ── file loading helpers ───────────────────────────────────────────────────

    /**
     * Read a fixed-width LF-terminated file into a List of byte[] records.
     * Each line (without the LF) must be exactly recLen bytes.
     */
    private static List<byte[]> loadTextFile(Path path, int recLen) throws IOException {
        List<byte[]> recs = new ArrayList<>();
        try (InputStream is = Files.newInputStream(path);
             BufferedReader br = new BufferedReader(
                     new InputStreamReader(is, StandardCharsets.US_ASCII))) {
            String line;
            while ((line = br.readLine()) != null) {
                // pad or truncate to exact recLen (defensive)
                byte[] rec = new byte[recLen];
                Arrays.fill(rec, (byte)' ');
                byte[] lb = line.getBytes(StandardCharsets.US_ASCII);
                System.arraycopy(lb, 0, rec, 0, Math.min(lb.length, recLen));
                recs.add(rec);
            }
        }
        return recs;
    }

    /**
     * Build an in-memory index: key string → first matching record bytes.
     * For XREFFILE we need to look up by XREF-ACCT-ID (alternate key).
     */
    private static Map<String, byte[]> indexByField(List<byte[]> recs,
                                                      int keyOff, int keyLen) {
        // LinkedHashMap preserves insertion order; for duplicate alternate keys
        // only the first record wins — matching VSAM "first match" semantics (R7).
        Map<String, byte[]> idx = new LinkedHashMap<>();
        for (byte[] r : recs) {
            String k = str(r, keyOff, keyLen);
            idx.putIfAbsent(k, r);   // first-match only, per R7
        }
        return idx;
    }

    // ── main ──────────────────────────────────────────────────────────────────

    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.err.println("Usage: Cbact04c <in_dir> <out_dir> <parm>");
            System.exit(1);
        }
        Path inDir  = Paths.get(args[0]);
        Path outDir = Paths.get(args[1]);
        // PARM-DATE: left-justify, space-pad to exactly 10 chars (per FACTS §9)
        String parmDate = String.format("%-10s", args[2]).substring(0, 10);

        Files.createDirectories(outDir);

        System.out.println("START OF EXECUTION OF PROGRAM CBACT04C");

        // ── load all input files into memory ──────────────────────────────────

        // TCATBALF: sequential scan, already sorted by key
        List<byte[]> tcatRecs = loadTextFile(inDir.resolve("TCATBALF.txt"), 50);

        // XREFFILE: random access by alternate key XREF-ACCT-ID (off 25, len 11)
        List<byte[]> xrefRecs = loadTextFile(inDir.resolve("XREFFILE.txt"), 50);
        Map<String, byte[]> xrefByAcct = indexByField(xrefRecs, 25, 11);

        // DISCGRP: random access by key (off 0, len 16: 10+2+4)
        List<byte[]> discRecs = loadTextFile(inDir.resolve("DISCGRP.txt"), 50);
        Map<String, byte[]> discByKey = indexByField(discRecs, 0, 16);

        // ACCTFILE: random access by ACCT-ID (off 0, len 11); also maintain
        // insertion order so we can write EVERY account back in key order.
        List<byte[]> acctRecs = loadTextFile(inDir.resolve("ACCTFILE.txt"), 300);
        // primary key index: acct-id → record (mutable byte[])
        Map<String, byte[]> acctByKey = new LinkedHashMap<>();
        for (byte[] r : acctRecs) {
            acctByKey.put(acctId(r), r);
        }

        // TRANSACT output stream (350-byte records, no newlines)
        OutputStream tranOut = Files.newOutputStream(outDir.resolve("TRANSACT.dat"));

        // ── working storage ───────────────────────────────────────────────────
        String wsLastAcctNum = "           ";  // 11 spaces (VALUE SPACES)
        BigDecimal wsTotalInt = BigDecimal.ZERO;
        boolean wsFirstTime = true;            // VALUE 'Y'
        boolean endOfFile = false;             // END-OF-FILE PIC X VALUE 'N'
        int wsRecordCount = 0;
        int wsTranidSuffix = 0;

        // current in-memory copies of the records being processed
        byte[] accountRecord = null;    // ACCOUNT-RECORD
        byte[] cardXrefRecord = null;   // CARD-XREF-RECORD

        int tcatIdx = 0;  // sequential cursor into tcatRecs

        // ── PERFORM UNTIL END-OF-FILE = 'Y' ──────────────────────────────────
        // Faithfully reproduces the COBOL test-before loop structure (R8).
        // The ELSE branch (1050-UPDATE-ACCOUNT) is dead code — it is never
        // reached because when endOfFile becomes true the loop condition is
        // checked first and the loop exits before the ELSE body can run.
        // FAITHFUL: last account's balance and cycle counters are never updated
        // because 1050-UPDATE-ACCOUNT is in the dead ELSE branch of a
        // test-before PERFORM UNTIL loop; the Java while() below replicates this.
        while (!endOfFile) {
            if (!endOfFile) {
                // ── 1000-TCATBALF-GET-NEXT ────────────────────────────────────
                byte[] tcatRec = perform1000TcatbalfGetNext(tcatRecs, tcatIdx);
                tcatIdx++;
                if (tcatRec == null) {
                    endOfFile = true;
                }

                if (!endOfFile) {
                    wsRecordCount++;
                    // DISPLAY TRAN-CAT-BAL-RECORD
                    System.out.println(str(tcatRec, 0, 50));

                    String tcatAcct = tcatAcctId(tcatRec);
                    if (!tcatAcct.equals(wsLastAcctNum)) {
                        // account change
                        if (!wsFirstTime) {
                            // ── 1050-UPDATE-ACCOUNT ───────────────────────────
                            perform1050UpdateAccount(accountRecord, acctByKey,
                                    wsLastAcctNum, wsTotalInt);
                        } else {
                            wsFirstTime = false;
                        }
                        wsTotalInt = BigDecimal.ZERO;
                        wsLastAcctNum = tcatAcct;

                        // ── 1100-GET-ACCT-DATA ────────────────────────────────
                        accountRecord = perform1100GetAcctData(acctByKey, tcatAcct);

                        // ── 1110-GET-XREF-DATA ────────────────────────────────
                        cardXrefRecord = perform1110GetXrefData(xrefByAcct, tcatAcct);
                    }

                    // ── 1200-GET-INTEREST-RATE ────────────────────────────────
                    String groupId   = acctGroupId(accountRecord);
                    String typeCd    = tcatTypeCd(tcatRec);
                    String catCd     = tcatCd(tcatRec);
                    BigDecimal intRate = perform1200GetInterestRate(
                            discByKey, groupId, typeCd, catCd);

                    if (intRate.compareTo(BigDecimal.ZERO) != 0) {
                        // ── 1300-COMPUTE-INTEREST ─────────────────────────────
                        BigDecimal wsMonthlyInt = perform1300ComputeInterest(
                                tcatBal(tcatRec), intRate);
                        wsTotalInt = wsTotalInt.add(wsMonthlyInt);

                        // ── 1300-B-WRITE-TX ───────────────────────────────────
                        wsTranidSuffix++;
                        perform1300bWriteTx(tranOut, parmDate, wsTranidSuffix,
                                wsMonthlyInt, accountRecord, cardXrefRecord);

                        // ── 1400-COMPUTE-FEES (stub, EXIT only) ───────────────
                        // no-op
                    }
                }
            } else {
                // DEAD CODE – FAITHFUL: this branch is never reached.
                // In the COBOL PERFORM UNTIL (test-before), when endOfFile becomes
                // true inside the IF branch above, execution returns here to
                // re-evaluate the UNTIL condition, which is now true, so the loop
                // exits without ever entering this ELSE. Preserved for structural
                // fidelity with the COBOL source.
                perform1050UpdateAccount(accountRecord, acctByKey,
                        wsLastAcctNum, wsTotalInt);
            }
        }

        // ── close files ───────────────────────────────────────────────────────
        tranOut.close();

        // Write ALL accounts back to ACCTFILE.txt in original key order,
        // 300 bytes per line with LF terminator.  Accounts that were never
        // touched are written unchanged (their byte[] was never modified).
        try (OutputStream acctOut = Files.newOutputStream(outDir.resolve("ACCTFILE.txt"))) {
            for (byte[] r : acctByKey.values()) {
                acctOut.write(r);
                acctOut.write('\n');
            }
        }

        System.out.println("END OF EXECUTION OF PROGRAM CBACT04C");
    }

    // ── paragraph methods ─────────────────────────────────────────────────────

    /**
     * 1000-TCATBALF-GET-NEXT
     * Returns the next TCATBAL record, or null on EOF.
     * Abends on any other error (index out of range is impossible here).
     */
    private static byte[] perform1000TcatbalfGetNext(List<byte[]> recs, int idx) {
        if (idx >= recs.size()) {
            return null;  // EOF
        }
        return recs.get(idx);
    }

    /**
     * 1050-UPDATE-ACCOUNT
     * Adds WS-TOTAL-INT to ACCT-CURR-BAL, zeros ACCT-CURR-CYC-CREDIT and
     * ACCT-CURR-CYC-DEBIT, then rewrites the account record.
     */
    private static void perform1050UpdateAccount(byte[] accountRecord,
                                                   Map<String, byte[]> acctByKey,
                                                   String acctNum,
                                                   BigDecimal wsTotalInt) {
        BigDecimal newBal = acctCurrBal(accountRecord).add(wsTotalInt);
        setAcctCurrBal(accountRecord, newBal);
        setAcctCurrCycCredit(accountRecord, BigDecimal.ZERO);
        setAcctCurrCycDebit(accountRecord, BigDecimal.ZERO);
        // The record is mutated in-place; acctByKey already holds the reference,
        // so no Map.put is needed — the pointer is shared.
    }

    /**
     * 1100-GET-ACCT-DATA
     * Reads the account record by key.  Abends if not found.
     */
    private static byte[] perform1100GetAcctData(Map<String, byte[]> acctByKey,
                                                   String acctId) {
        byte[] r = acctByKey.get(acctId);
        if (r == null) {
            System.out.println("ACCOUNT NOT FOUND: " + acctId);
            System.out.println("ERROR READING ACCOUNT FILE");
            throw abendProgram();
        }
        return r;
    }

    /**
     * 1110-GET-XREF-DATA
     * Reads the card cross-reference record using the alternate key (account ID).
     * Only the first record for a given account ID is returned — matching VSAM
     * alternate-index "first match" semantics (R7).
     * Abends if not found.
     */
    private static byte[] perform1110GetXrefData(Map<String, byte[]> xrefByAcct,
                                                   String acctId) {
        byte[] r = xrefByAcct.get(acctId);
        if (r == null) {
            System.out.println("ACCOUNT NOT FOUND: " + acctId);
            System.out.println("ERROR READING XREF FILE");
            throw abendProgram();
        }
        return r;
    }

    /**
     * 1200-GET-INTEREST-RATE + 1200-A-GET-DEFAULT-INT-RATE
     * Looks up the disclosure-group record by (groupId, typeCd, catCd).
     * On key-not-found (status '23'), retries with groupId = 'DEFAULT'.
     * Abends if the DEFAULT lookup also fails.
     */
    private static BigDecimal perform1200GetInterestRate(Map<String, byte[]> discByKey,
                                                          String groupId,
                                                          String typeCd,
                                                          String catCd) {
        String key = buildDiscKey(groupId, typeCd, catCd);
        byte[] r = discByKey.get(key);
        if (r == null) {
            // STATUS '23' — try DEFAULT fallback (R5)
            System.out.println("DISCLOSURE GROUP RECORD MISSING");
            System.out.println("TRY WITH DEFAULT GROUP CODE");
            // 1200-A-GET-DEFAULT-INT-RATE
            String defaultKey = buildDiscKey("DEFAULT   ", typeCd, catCd);
            r = discByKey.get(defaultKey);
            if (r == null) {
                System.out.println("ERROR READING DEFAULT DISCLOSURE GROUP");
                throw abendProgram();
            }
        }
        return disIntRate(r);
    }

    /**
     * Build the 16-byte DISCGRP key string: groupId(10) + typeCd(2) + catCd(4).
     * groupId is taken as-is (already 10 chars from the record); when passing
     * the literal "DEFAULT" we pad it to 10 with spaces on the right,
     * matching COBOL's MOVE 'DEFAULT' TO FD-DIS-ACCT-GROUP-ID (PIC X(10)).
     */
    private static String buildDiscKey(String groupId, String typeCd, String catCd) {
        // groupId from record is already 10 chars; "DEFAULT   " passed directly
        return String.format("%-10s", groupId).substring(0, 10) + typeCd + catCd;
    }

    /**
     * 1300-COMPUTE-INTEREST
     * WS-MONTHLY-INT = (TRAN-CAT-BAL * DIS-INT-RATE) / 1200
     * No ROUNDED → truncated toward zero to 2 decimal places (R1).
     */
    private static BigDecimal perform1300ComputeInterest(BigDecimal catBal,
                                                          BigDecimal intRate) {
        // FAITHFUL: RoundingMode.DOWN = truncation toward zero, matching COBOL
        // COMPUTE without ROUNDED (R1).
        return catBal.multiply(intRate)
                     .divide(BigDecimal.valueOf(1200), 2, RoundingMode.DOWN);
    }

    /**
     * 1300-B-WRITE-TX
     * Builds and writes one 350-byte TRAN-RECORD to the output stream.
     */
    private static void perform1300bWriteTx(OutputStream out,
                                             String parmDate,
                                             int tranidSuffix,
                                             BigDecimal wsMonthlyInt,
                                             byte[] accountRecord,
                                             byte[] cardXrefRecord) throws IOException {
        byte[] rec = new byte[350];
        Arrays.fill(rec, (byte)' ');

        // TRAN-ID (0..15): PARM-DATE(10) + WS-TRANID-SUFFIX(6) (R6)
        // STRING … DELIMITED BY SIZE: uses full declared width of each operand.
        // %-10s left-justifies and space-pads parmDate to exactly 10 chars.
        String tranId = String.format("%-10s%06d", parmDate, tranidSuffix);
        putStr(rec, 0, 16, tranId);

        // TRAN-TYPE-CD (16..17) = '01'
        putStr(rec, 16, 2, "01");

        // TRAN-CAT-CD (18..21) = '0005' (PIC 9(04), MOVE '05' → right-justified zero-padded)
        // COBOL: MOVE '05' TO TRAN-CAT-CD where TRAN-CAT-CD PIC 9(04)
        // MOVE of a numeric literal into PIC 9 right-justifies with leading zeros.
        putStr(rec, 18, 4, "0005");

        // TRAN-SOURCE (22..31) = 'System' left-justified, space-padded to 10
        putStr(rec, 22, 10, "System");

        // TRAN-DESC (32..131) = 'Int. for a/c ' + ACCT-ID(11) = 24 chars, rest spaces
        // ACCT-ID is PIC 9(11) — taken from accountRecord off 0 len 11
        String acctIdStr = acctId(accountRecord);
        String desc = "Int. for a/c " + acctIdStr;
        putStr(rec, 32, 100, desc);

        // TRAN-AMT (132..142): PIC S9(09)V99 — overpunched, 11 bytes
        encodeOverpunch(wsMonthlyInt, rec, 132, 9, 2);

        // TRAN-MERCHANT-ID (143..151): MOVE 0 → zero-padded 9 digits
        putZeroPaddedNum(rec, 143, 9, 0);

        // TRAN-MERCHANT-NAME (152..201): MOVE SPACES — already filled above
        // TRAN-MERCHANT-CITY (202..251): MOVE SPACES — already filled above
        // TRAN-MERCHANT-ZIP  (252..261): MOVE SPACES — already filled above

        // TRAN-CARD-NUM (262..277): from CARD-XREF-RECORD XREF-CARD-NUM (off 0 len 16)
        putStr(rec, 262, 16, xrefCardNum(cardXrefRecord));

        // TRAN-ORIG-TS (278..303) and TRAN-PROC-TS (304..329):
        // both set from the same call to Z-GET-DB2-FORMAT-TIMESTAMP
        String ts = db2Timestamp();
        putStr(rec, 278, 26, ts);
        putStr(rec, 304, 26, ts);

        // FILLER (330..349): spaces — already filled above

        out.write(rec);
    }

    /**
     * 9999-ABEND-PROGRAM
     * Displays the abend message and terminates with exit code 999,
     * matching CEE3ABD behaviour.
     * Returns RuntimeException so callers can write "throw abendProgram()"
     * and the compiler knows the code path does not continue.
     */
    private static RuntimeException abendProgram() {
        System.out.println("ABENDING PROGRAM");
        System.exit(999);
        throw new RuntimeException("unreachable");  // satisfy compiler
    }
}
