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

class StrategyPartnerOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("StrategyPartnerOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\hit-digital-strategy-partner")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_strategy(self, topic: str, mode: str):
        self.logger.info(f"Starting HIT Digital Strategy Partner Pipeline (Atomized Roundtable). Topic: {topic}, Mode: {mode}")
        
        # 1. Phase 1: Native Concurrent Recon (Simulated via Orchestrator LLM calls)
        self.logger.info("Phase 1: Dispatching Policy & Competitor Reconnaissance...")
        tracks = [
            ("Policy & Regulation", "Focus on Medicare, NHC policies, DRG/DIP constraints, data security."),
            ("Competitor & Market", "Focus on incumbent vendors, product weaknesses, pricing wars.")
        ]
        
        recon_data = []
        for name, focus in tracks:
            self.logger.info(f"Dispatching scout for {name}...")
            result = self.call_llm(
                prompt=f"Topic: {topic}\nTrack: {name}\nFocus: {focus}\nGather structured intelligence with hard quantifiable metrics (budgets, timelines) and non-consensus signals.",
                system_instruction="You are an elite MBB Healthcare Strategy Consultant. Deliver cold, factual data.",
                temperature=0.2
            )
            recon_data.append(f"### {name}\n{result}")

        merged_recon = "\n\n".join(recon_data)
        
        # --------------------------------------------------------------------------------
        # ATOMIZED ROUNDTABLE (Phase 2 & 3)
        # --------------------------------------------------------------------------------
        self.logger.info("Phase 2: Roundtable Logic Collision...")

        # Micro-Persona 1: Policy Architect
        self.logger.info("Executing Micro-Persona: Policy Architect...")
        policy_prompt = f"""
        Reconnaissance Data:
        {merged_recon}
        
        Task:
        Topic: {topic}
        Provide the Second Hop mapping. Trace the precise chain from Policy -> Technical Architecture -> Business ROI.
        """
        policy_map = self.call_llm(
            policy_prompt, 
            system_instruction="You are a Healthcare Policy & IT Architect. Trace policy compliance directly to technical requirements and commercial impact. Be concise."
        )

        # Micro-Persona 2: Pessimistic Actuary
        self.logger.info("Executing Micro-Persona: Pessimistic Actuary...")
        actuary_prompt = f"""
        Topic: {topic}
        Policy & ROI Mapping:
        {policy_map}
        
        Task:
        Stress test this proposal assuming a brutal 30% budget cut and a 6-month delay in hospital payments.
        Calculate the Pessimistic ROI. Identify exactly which margins collapse first.
        """
        pessimistic_roi = self.call_llm(
            actuary_prompt, 
            system_instruction="You are a cynical Healthcare Financial Actuary. Destroy optimistic projections. Quantify the financial bleeding."
        )

        # Micro-Persona 3: Red Team Risk Officer
        self.logger.info("Executing Micro-Persona: Red Team Risk Officer...")
        risk_prompt = f"""
        Topic: {topic}
        Financial Stress Test:
        {pessimistic_roi}
        
        Task:
        Identify lethal vulnerabilities and residual risks in this digital strategy. Focus on vendor lock-in, data security, and leadership transition risks.
        """
        residual_risks = self.call_llm(
            risk_prompt, 
            system_instruction="You are a Red Team Risk Officer. Identify single points of failure (SPOFs) and execution risks."
        )

        # Micro-Persona 4: Managing Partner
        self.logger.info("Executing Micro-Persona: Managing Partner...")
        partner_prompt = f"""
        Topic: {topic}
        Policy Map: {policy_map}
        Pessimistic ROI: {pessimistic_roi}
        Residual Risks: {residual_risks}
        
        Task:
        1. Core Judgment: Formulate exactly 1 central strategic judgment.
        2. Action Levers: Define brutal, clear human actions (e.g., cut, pivot, restructure).
        """
        partner_action = self.call_llm(
            partner_prompt, 
            system_instruction="You are the Managing Partner of a Top Tier Strategy Firm. Deliver decisive, brutal verdicts."
        )
        
        # 3. Phase 4: Drafting (Executive Editor)
        self.logger.info(f"Phase 4: Executive Drafting in {mode} mode...")
        draft_prompt = f"""
        Topic: {topic}
        Mode: {mode}
        
        Roundtable Insights:
        - Core Judgment & Levers: {partner_action}
        - Policy Map: {policy_map}
        - Pessimistic ROI: {pessimistic_roi}
        - Residual Risks: {residual_risks}
        
        Task:
        Draft the final strategic asset based on the mode constraints:
        - If brief: 1500-2500 words, high density.
        - If board-memo: 1000-1800 words, start with Urgent Warning and Board Action. No pronouns.
        - If deep-dive: Provide a comprehensive synthesis of the core chapters.
        
        Apply the Three-Bold Rule (bold max 3 key insights). Strip out all consulting fluff.
        Ensure output explicitly contains the sections: Core Judgment, Pessimistic ROI, Action Levers, Residual Risks.
        """
        final_draft = self.call_llm(
            draft_prompt, 
            system_instruction="You are an Executive Editor. Use cold, ROI-driven business language. Deliver actionable insights without fluff."
        )
        
        draft_path = self.tmp_dir / f"strategy_draft_{mode}.md"
        self.write_file(str(draft_path), final_draft)
        self.logger.info(f"Draft saved to {draft_path}")
        
        # 4. Phase 5: Gate Audit
        self.logger.info("Phase 5: Running Strategy Gate Audit...")
        gate_script = self.skill_dir / "scripts" / "strategy_gate.py"
        if gate_script.exists():
            try:
                gate_result = subprocess.run(
                    ["python", str(gate_script), "--path", str(draft_path), "--mode", mode, "--strict"],
                    capture_output=True, text=True, encoding="utf-8"
                )
                self.logger.info(f"Audit output:\n{gate_result.stdout}")
                if gate_result.returncode != 0:
                    self.logger.warning("Strategy Gate failed. Returning control to Agent for correction.")
                else:
                    self.logger.info("Strategy Gate passed.")
            except Exception as e:
                self.logger.error(f"Gate execution failed: {e}")
        else:
            self.logger.warning("strategy_gate.py not found. Skipping physical gate audit.")

        self.logger.info("Pipeline complete. The Agent may now review the draft, present it to the user, and physically archive the file.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True, help="The strategic topic to analyze")
    parser.add_argument("--mode", default="brief", choices=["brief", "deep-dive", "board-memo"], help="Output mode")
    args = parser.parse_args()
    
    orchestrator = StrategyPartnerOrchestrator()
    orchestrator.run_strategy(args.topic, args.mode)
