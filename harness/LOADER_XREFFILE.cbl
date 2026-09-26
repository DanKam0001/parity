      ******************************************************************
      * LOADER_XREFFILE.cbl
      *
      * Reads a line-sequential text file (DD_XREFIN).
      * cardxref.txt records are 36 chars wide; the indexed file needs
      * 50-byte records, so 14 spaces are appended on load.
      *
      * Primary key  : bytes 1-16  (XREF-CARD-NUM  X(16))
      * Alternate key: bytes 26-36 (XREF-ACCT-ID   9(11))
      *   Layout offsets (1-based):
      *     1-16  XREF-CARD-NUM
      *    17-25  XREF-CUST-ID 9(9)
      *    26-36  XREF-ACCT-ID 9(11)
      *    37-50  FILLER X(14)
      *
      * Records must be in ascending XREF-CARD-NUM order.
      *
      * Compiled: cobc -x harness/LOADER_XREFFILE.cbl
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOADER-XREFFILE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO XREFIN
                  ORGANIZATION IS LINE SEQUENTIAL
                  FILE STATUS  IS WS-IN-STATUS.
           SELECT IDX-FILE ASSIGN TO XREFFILE
                  ORGANIZATION IS INDEXED
                  ACCESS MODE  IS SEQUENTIAL
                  RECORD KEY   IS IDX-CARD-NUM
                  ALTERNATE RECORD KEY IS IDX-ACCT-ID
                  FILE STATUS  IS WS-IDX-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC              PIC X(50).
       FD  IDX-FILE.
       01  IDX-REC.
           05  IDX-CARD-NUM    PIC X(16).
           05  IDX-CUST-ID     PIC 9(09).
           05  IDX-ACCT-ID     PIC 9(11).
           05  IDX-FILLER      PIC X(14).
       WORKING-STORAGE SECTION.
       01  WS-IN-STATUS        PIC XX VALUE '00'.
       01  WS-IDX-STATUS       PIC XX VALUE '00'.
       01  WS-COUNT            PIC 9(09) VALUE 0.
      * Source line; 36 data chars + room for LF strip.
       01  WS-LINE             PIC X(50) VALUE SPACES.
      ******************************************************************
       PROCEDURE DIVISION.
          OPEN INPUT  IN-FILE
          IF WS-IN-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR XREFIN STATUS=' WS-IN-STATUS
              STOP RUN RETURNING 8
          END-IF
          OPEN OUTPUT IDX-FILE
          IF WS-IDX-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR XREFFILE STATUS=' WS-IDX-STATUS
              STOP RUN RETURNING 8
          END-IF
           PERFORM UNTIL WS-IN-STATUS = '10'
               MOVE SPACES TO WS-LINE
               READ IN-FILE INTO WS-LINE
               IF WS-IN-STATUS = '00'
                   MOVE WS-LINE TO IDX-REC
                   ADD 1 TO WS-COUNT
                   WRITE IDX-REC
                   IF WS-IDX-STATUS NOT = '00'
                       DISPLAY 'WRITE ERROR STATUS='
                               WS-IDX-STATUS
                               ' ON RECORD ' WS-COUNT
                       STOP RUN RETURNING 8
                   END-IF
               ELSE IF WS-IN-STATUS NOT = '10'
                   DISPLAY 'READ ERROR STATUS=' WS-IN-STATUS
                   STOP RUN RETURNING 8
               END-IF
           END-PERFORM
           CLOSE IN-FILE
           CLOSE IDX-FILE
           DISPLAY 'LOADER_XREFFILE: loaded ' WS-COUNT ' records'
           STOP RUN.
