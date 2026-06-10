import sys
import os
import subprocess
import argparse
from pathlib import Path

# Mount the global scripts directory
global_scripts_dir = Path(r"C:\Users\shich\.gemini\config\skills\scripts")
if str(global_scripts_dir) not in sys.path:
    sys.path.insert(0, str(global_scripts_dir))

try:
    from orchestrator import BasePipelineOrchestrator
except ImportError:
    print("Error: Could not import BasePipelineOrchestrator. Make sure it exists in config/skills/scripts/")
    sys.exit(1)

class CognitiveAuditorOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("CognitiveAuditorOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\personal-cognitive-auditor")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_audit(self, period: str, calendar_data: str, tactics_data: str):
        self.logger.info(f"Starting Cognitive Auditor Pipeline for {period}...")
        
        # 1. Generate Audit
        self.logger.info("Phase 1: Generating Core Audit...")
        audit_prompt = f"""
        Period: {period}
        Calendar Context: {calendar_data}
        Prior Tactics: {tactics_data}
        
        Task:
        Generate the Cognitive Audit following the Unified Structure:
        1. Context Snapshot
        2. Tactical Accountability (Markdown Table comparing prior vs actual)
        3. Signals & Core Insight
        4. Strategic Diagnosis
        5. Next Tactics
        
        Ensure brutal honesty. No fluff. Do not act like a gentle assistant; act like a ruthless CEO Coach.
        """
        audit_report = self.call_llm(audit_prompt, system_instruction="You are a ruthless Cognitive Auditor and CEO Coach.")
        
        # 2. Cognitive Prescription (Simulating subagent)
        self.logger.info("Phase 2: Generating Cognitive Prescription...")
        prescription_prompt = f"""
        Audit Report:
        {audit_report}
        
        Task:
        Act as the 'personal-cognitive-prescription' engine.
        Provide a 4-part prescription card to fix the blind spots shown in the audit:
        [Blind Spot Diagnosis]
        [Prescription Book]
        [Targeted Chapter]
        [Mechanism of Action]
        """
        prescription = self.call_llm(prescription_prompt, system_instruction="You are a hard-core Cognitive Prescription Engine.")
        
        # 3. Assembly
        self.logger.info("Phase 3: Assembling Handoff Payload...")
        final_payload = f"""# Cognitive Audit: {period.capitalize()}

{audit_report}

## Cognitive Prescription
{prescription}

---
[HANDOFF PAYLOAD TO PERSONAL-DIARY-WRITER]
Ready to be written to disk.
"""
        
        payload_path = self.tmp_dir / f"cognitive_audit_payload_{period}.md"
        self.write_file(str(payload_path), final_payload)
        self.logger.info(f"Payload saved to {payload_path}")
        
        # 4. Gate
        gate_script = self.skill_dir / "scripts" / "audit_gate.py"
        if gate_script.exists():
            self.logger.info("Running Audit Gate...")
            try:
                res = subprocess.run(["python", str(gate_script), str(payload_path)], capture_output=True, text=True, encoding="utf-8")
                self.logger.info(f"Gate output:\n{res.stdout}")
            except Exception as e:
                self.logger.error(f"Audit gate failed: {e}")
        else:
            self.logger.info("audit_gate.py not found. Skipping physical validation.")
                
        self.logger.info("Pipeline complete. Agent must now read the payload and invoke personal-diary-writer.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", required=True, choices=["daily", "weekly", "monthly", "annual"], help="Audit period")
    parser.add_argument("--calendar", default="No calendar data provided", help="Raw calendar context")
    parser.add_argument("--tactics", default="No prior tactics found", help="Prior tactics context")
    args = parser.parse_args()
    
    orchestrator = CognitiveAuditorOrchestrator()
    orchestrator.run_audit(args.period, args.calendar, args.tactics)
