## 2024-11-20 - Pre-compiling Regex in Loops
**Learning:** Pre-compiling regex patterns as module-level constants (moving them outside of loops or repetitive function calls) provides a measurable performance improvement during parsing operations.
**Action:** Always pre-compile regexes and define them as global constants when they are used inside intensive loops or parser functions to avoid redundant compilation overhead.
