      ******************************************************************
      * LOADER_ACCTFILE.cbl
      *
      * Reads a line-sequential text file (DD_ACCTIN) where each
      * line is exactly 300 characters and WRITES it into the BDB
      * indexed account file DD_ACCTFILE.
      *
      * Primary key: bytes 1-11 (ACCT-ID 9(11)).
      * Records must be in ascending ACCT-ID order.
      *
      * Compiled: cobc -x harness/LOADER_ACCTFILE.cbl
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOADER-ACCTFILE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO ACCTIN
                  ORGANIZATION IS LINE SEQUENTIAL
                  FILE STATUS  IS WS-IN-STATUS.
           SELECT IDX-FILE ASSIGN TO ACCTFILE
                  ORGANIZATION IS INDEXED
                  ACCESS MODE  IS SEQUENTIAL
                  RECORD KEY   IS IDX-ACCT-ID
                  FILE STATUS  IS WS-IDX-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC              PIC X(300).
       FD  IDX-FILE.
       01  IDX-REC.
           05  IDX-ACCT-ID     PIC 9(11).
           05  IDX-DATA        PIC X(289).
       WORKING-STORAGE SECTION.
       01  WS-IN-STATUS        PIC XX VALUE '00'.
       01  WS-IDX-STATUS       PIC XX VALUE '00'.
       01  WS-COUNT            PIC 9(09) VALUE 0.
      ******************************************************************
       PROCEDURE DIVISION.
          OPEN INPUT  IN-FILE
          IF WS-IN-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR ACCTIN STATUS=' WS-IN-STATUS
              STOP RUN RETURNING 8
          END-IF
          OPEN OUTPUT IDX-FILE
          IF WS-IDX-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR ACCTFILE STATUS=' WS-IDX-STATUS
              STOP RUN RETURNING 8
          END-IF
           PERFORM UNTIL WS-IN-STATUS = '10'
               READ IN-FILE INTO IDX-REC
               IF WS-IN-STATUS = '00'
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
           DISPLAY 'LOADER_ACCTFILE: loaded ' WS-COUNT ' records'
           STOP RUN.
