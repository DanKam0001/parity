      ******************************************************************
      * CEE3ABD.cbl  –  off-mainframe stub for IBM LE abend service.
      * Compiled: cobc -m -fsign=EBCDIC harness/CEE3ABD.cbl
      * Called by CBACT04C via CALL 'CEE3ABD' USING ABCODE TIMING.
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CEE3ABD.
       DATA DIVISION.
       LINKAGE SECTION.
       01  ABCODE  PIC S9(9) BINARY.
       01  TIMING  PIC S9(9) BINARY.
      ******************************************************************
       PROCEDURE DIVISION USING ABCODE, TIMING.
           DISPLAY 'CEE3ABD called, abend code: ' ABCODE
           STOP RUN RETURNING 16.
