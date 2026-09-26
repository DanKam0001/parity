      ******************************************************************
      * DRIVER.cbl – plays the role of JCL for CBACT04C.
      *
      * Reads two environment variables:
      *   COBOL_PROGRAM – module to CALL (e.g. CBACT04C)
      *   COBOL_PARM    – 10-char PARM string (e.g. 2022071800)
      *
      * Builds the EXTERNAL-PARMS linkage block that CBACT04C expects:
      *   PARM-LENGTH  PIC S9(04) COMP  – byte length of PARM text
      *   PARM-DATE    PIC X(10)   – PARM text, padded / truncated
      *
      * File DD paths are set by the caller via DD_<name> env vars;
      * GnuCOBOL resolves ASSIGN TO <name> by checking DD_<name>.
      *
      * Compiled: cobc -x harness/DRIVER.cbl
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DRIVER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
      * Buffer to receive env-var values.
       01  WS-PROG-NAME         PIC X(30)  VALUE SPACES.
       01  WS-PARM-TEXT         PIC X(10)  VALUE SPACES.
      * EXTERNAL-PARMS block passed by reference to CBACT04C.
       01  EXTERNAL-PARMS.
           05  PARM-LENGTH      PIC S9(04) COMP VALUE 10.
           05  PARM-DATE        PIC X(10)       VALUE SPACES.
      ******************************************************************
       PROCEDURE DIVISION.
      * Read COBOL_PROGRAM env var.
           ACCEPT WS-PROG-NAME FROM ENVIRONMENT 'COBOL_PROGRAM'
           IF WS-PROG-NAME = SPACES
               DISPLAY 'DRIVER: COBOL_PROGRAM not set'
               STOP RUN RETURNING 8
           END-IF
      * Read COBOL_PARM env var; default to spaces if absent.
           ACCEPT WS-PARM-TEXT FROM ENVIRONMENT 'COBOL_PARM'
      * Build linkage block: length = 10, text padded/truncated.
           MOVE 10                TO PARM-LENGTH
           MOVE WS-PARM-TEXT      TO PARM-DATE
           DISPLAY 'DRIVER: calling ' WS-PROG-NAME
           DISPLAY 'DRIVER: PARM-DATE=' PARM-DATE
      * Dynamic CALL – trailing spaces in WS-PROG-NAME are harmless.
           CALL WS-PROG-NAME USING EXTERNAL-PARMS
           END-CALL
           STOP RUN.
