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

class CollaborationAuditOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("CollaborationAuditOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\mentat-collaboration-audit")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")
        self.workspace = Path(r"C:\Users\shich\.gemini\MEMORY")

    def run_scripts(self, script_path: Path, args: list):
        if script_path.exists():
            try:
                cmd = ["python", str(script_path)] + args
                self.logger.info(f"Running: {' '.join(cmd)}")
                res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
                return res.stdout
            except Exception as e:
                self.logger.error(f"Failed to run script: {e}")
                return ""
        else:
            self.logger.warning(f"Script not found: {script_path.name}")
            return f"[{script_path.name} Mock Data for simulation pipeline]"

    def run_audit(self, mode: str, period: str):
        self.logger.info(f"Starting Mentat Collaboration Audit Pipeline (Mode: {mode}, Period: {period})...")
        
        # 1. Telemetry Gathering
        self.logger.info("Phase 1: Executing Telemetry Gathering...")
        retro_script = self.workspace.parent / "config" / "skills" / "scripts" / "system_retro.py"
        telemetry_data = self.run_scripts(retro_script, [])
        
        if mode == "interaction":
            insight_script = self.skill_dir / "scripts" / "analyze_insights_v4.py"
            interaction_data = self.run_scripts(insight_script, ["--period", period, "--extract-only", "--drop-noise"])
            telemetry_data += f"\n\nInteraction Data:\n{interaction_data}"

        # 2. LLM Analysis
        self.logger.info("Phase 2: LLM Audit Analysis & Blueprinting...")
        prompt = f"""
        Mode: {mode}
        Telemetry & Interaction Data:
        {telemetry_data}
        
        Task:
        1. Produce an unsparing, brutal audit report based on the data.
        2. Identify Systemic Friction (e.g., token waste, prompt ping-pong).
        3. Formulate Actionable Checklists or Prompts.
        4. If you detect recurring lethal errors, provide an 'auto_constraint_writeback' section detailing what exact text must be appended to which physical rules file (like GEMINI.md).
        """
        audit_report = self.call_llm(prompt, system_instruction="You are Mentat's Chief Collaboration Auditor.")
        
        # 3. Payload Delivery
        self.logger.info("Phase 3: Saving Output Payload...")
        payload_path = self.tmp_dir / f"mentat_audit_payload_{mode}_{period}.md"
        self.write_file(str(payload_path), audit_report.strip())
        self.logger.info(f"Payload saved to {payload_path}")
        
        self.logger.info("Pipeline complete. The Agent must now review the payload, present it, and execute any requested `auto_constraint_writeback` operations.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["telemetry", "interaction"], default="interaction", help="Audit mode")
    parser.add_argument("--period", default="monthly", help="Audit period (e.g., weekly, monthly)")
    args = parser.parse_args()
    
    orchestrator = CollaborationAuditOrchestrator()
    orchestrator.run_audit(args.mode, args.period)
