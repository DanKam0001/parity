      ******************************************************************
      * LOADER_DISCGRP.cbl
      *
      * Reads a line-sequential text file (DD_DISCIN) where each
      * line is exactly 50 characters and WRITES it into the BDB
      * indexed disclosure-group file DD_DISCGRP.
      *
      * Primary key: bytes 1-16
      *   DIS-ACCT-GROUP-ID X(10) + DIS-TRAN-TYPE-CD X(2)
      *   + DIS-TRAN-CAT-CD 9(4).
      * Records must be in ascending key order.
      *
      * Compiled: cobc -x harness/LOADER_DISCGRP.cbl
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOADER-DISCGRP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO DISCIN
                  ORGANIZATION IS LINE SEQUENTIAL
                  FILE STATUS  IS WS-IN-STATUS.
           SELECT IDX-FILE ASSIGN TO DISCGRP
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
               10  IDX-GROUP-ID    PIC X(10).
               10  IDX-TYPE-CD     PIC X(02).
               10  IDX-CAT-CD      PIC 9(04).
           05  IDX-DATA            PIC X(34).
       WORKING-STORAGE SECTION.
       01  WS-IN-STATUS        PIC XX VALUE '00'.
       01  WS-IDX-STATUS       PIC XX VALUE '00'.
       01  WS-COUNT            PIC 9(09) VALUE 0.
      ******************************************************************
       PROCEDURE DIVISION.
          OPEN INPUT  IN-FILE
          IF WS-IN-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR DISCIN STATUS=' WS-IN-STATUS
              STOP RUN RETURNING 8
          END-IF
          OPEN OUTPUT IDX-FILE
          IF WS-IDX-STATUS NOT = '00'
              DISPLAY 'OPEN ERROR DISCGRP STATUS=' WS-IDX-STATUS
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
           DISPLAY 'LOADER_DISCGRP: loaded ' WS-COUNT ' records'
           STOP RUN.
