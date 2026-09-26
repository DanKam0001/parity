      ******************************************************************
      * LOADER_TCATBALF.cbl
      *
      * Reads a line-sequential text file (DD_TCATIN) where each
      * line is exactly 50 characters (fixed-width, CRLF or LF) and
      * WRITES it into the BDB indexed file DD_TCATBALF.
      *
      * Records must be supplied in ascending primary-key order
      * (TRANCAT-ACCT-ID 9(11) + TRANCAT-TYPE-CD X(2) + TRANCAT-CD
      * 9(4) = bytes 1-17).
      *
      * Compiled: cobc -x harness/LOADER_TCATBALF.cbl
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOADER-TCATBALF.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
      * Line-sequential text source (strips line endings automatically).
           SELECT IN-FILE  ASSIGN TO TCATIN
                  ORGANIZATION IS LINE SEQUENTIAL
                  FILE STATUS  IS WS-IN-STATUS.
      * BDB indexed destination; key = bytes 1-17.
           SELECT IDX-FILE ASSIGN TO TCATBALF
                  ORGANIZATION IS INDEXED
                  ACCESS MODE  IS SEQUENTIAL
                  RECORD KEY   IS IDX-KEY
                  FILE STATUS  IS WS-IDX-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC              PIC X(50).
       FD  IDX-FILE.
       01  IDX-REC.
           05  IDX-KEY.
               10  IDX-ACCT-ID     PIC 9(11).
               10  IDX-TYPE-CD     PIC X(02).
               10  IDX-CAT-CD      PIC 9(04).
           05  IDX-DATA            PIC X(33).
       WORKING-STORAGE SECTION.
       01  WS-IN-STATUS         PIC XX VALUE '00'.
       01  WS-IDX-STATUS        PIC XX VALUE '00'.
       01  WS-COUNT             PIC 9(09) VALUE 0.
      ******************************************************************
       PROCEDURE DIVISION.
          OPEN INPUT  IN-FILE
          IF WS-IN-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR TCATIN STATUS=' WS-IN-STATUS
              STOP RUN RETURNING 8
          END-IF
          OPEN OUTPUT IDX-FILE
          IF WS-IDX-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR TCATBALF STATUS=' WS-IDX-STATUS
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
           DISPLAY 'LOADER_TCATBALF: loaded ' WS-COUNT ' records'
           STOP RUN.
