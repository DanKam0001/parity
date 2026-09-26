      ******************************************************************
      * UNLOADER_ACCTFILE.cbl
      *
      * Reads the BDB indexed ACCTFILE (DD_ACCTFILE) sequentially and
      * writes one fixed-width text line per record (300 chars + LF) to
      * a line-sequential output file (DD_ACCTOUT).
      *
      * Used after CBACT04C runs to export updated account balances
      * so the Java comparer can inspect them.
      *
      * Compiled: cobc -x harness/UNLOADER_ACCTFILE.cbl
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNLOADER-ACCTFILE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IDX-FILE ASSIGN TO ACCTFILE
                  ORGANIZATION IS INDEXED
                  ACCESS MODE  IS SEQUENTIAL
                  RECORD KEY   IS IDX-ACCT-ID
                  FILE STATUS  IS WS-IDX-STATUS.
           SELECT OUT-FILE ASSIGN TO ACCTOUT
                  ORGANIZATION IS LINE SEQUENTIAL
                  FILE STATUS  IS WS-OUT-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  IDX-FILE.
       01  IDX-REC.
           05  IDX-ACCT-ID     PIC 9(11).
           05  IDX-DATA        PIC X(289).
       FD  OUT-FILE.
       01  OUT-REC             PIC X(300).
       WORKING-STORAGE SECTION.
       01  WS-IDX-STATUS       PIC XX VALUE '00'.
       01  WS-OUT-STATUS       PIC XX VALUE '00'.
       01  WS-COUNT            PIC 9(09) VALUE 0.
      ******************************************************************
       PROCEDURE DIVISION.
          OPEN INPUT  IDX-FILE
          IF WS-IDX-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR ACCTFILE STATUS=' WS-IDX-STATUS
              STOP RUN RETURNING 8
          END-IF
          OPEN OUTPUT OUT-FILE
          IF WS-OUT-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR ACCTOUT STATUS=' WS-OUT-STATUS
              STOP RUN RETURNING 8
          END-IF
           PERFORM UNTIL WS-IDX-STATUS = '10'
               READ IDX-FILE INTO OUT-REC
               IF WS-IDX-STATUS = '00'
                   ADD 1 TO WS-COUNT
                   WRITE OUT-REC
                   IF WS-OUT-STATUS NOT = '00'
                       DISPLAY 'WRITE ERROR STATUS=' WS-OUT-STATUS
                       STOP RUN RETURNING 8
                   END-IF
               ELSE IF WS-IDX-STATUS NOT = '10'
                   DISPLAY 'READ ERROR STATUS=' WS-IDX-STATUS
                   STOP RUN RETURNING 8
               END-IF
           END-PERFORM
           CLOSE IDX-FILE
           CLOSE OUT-FILE
           DISPLAY 'UNLOADER_ACCTFILE: unloaded ' WS-COUNT ' records'
           STOP RUN.
