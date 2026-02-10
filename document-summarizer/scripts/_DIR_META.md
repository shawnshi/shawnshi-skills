# _DIR_META.md

## Architecture Vision
Implementation logic for the Document Summarizer pipeline.
Structured as a 3-stage reaction chain: Extraction -> Analysis -> Application.

## Member Index
- `orchestrate_enhanced.py`: [Interface] Pipeline orchestrator. Entry point for batch operations.
- `extract_text.py`: [Kernel] Text extraction from PDF, DOCX, PPTX, XLSX. Supports parallel workers.
- `generate_summaries_enhanced.py`: [Logic/Legacy] Rule-based template generator for summaries (100-150 chars).
- `generate_summaries_llm.py`: [Logic/New] LLM-based semantic summarizer (Gemini/DeepSeek).
- `apply_metadata_enhanced.py`: [Adapter] Writes semantic metadata back to file properties with multi-format fallback.

> ⚠️ **Protocol**: Sync this file whenever directory content or responsibility shifts.
