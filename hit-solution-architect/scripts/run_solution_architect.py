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

class SolutionArchitectOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("SolutionArchitectOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\hit-solution-architect")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_architect(self, topic: str, audience: str, mode: str):
        self.logger.info(f"Starting HIT Solution Architect Pipeline (Atomized Roundtable). Topic: {topic}, Audience: {audience}, Mode: {mode}")
        
        # --------------------------------------------------------------------------------
        # ATOMIZED ROUNDTABLE
        # --------------------------------------------------------------------------------
        
        # 1. Strategic Mastermind: Diagnose & Design Skeleton
        self.logger.info("Phase 1: Strategic Mastermind (Skeleton Design)...")
        skeleton_prompt = f"""
        Topic: {topic}
        Audience: {audience}
        Mode: {mode}
        
        Task:
        1. Define the Hospital Core Contradiction / Impossible Triangle for this topic.
        2. Design a comprehensive Solution Skeleton.
        """
        skeleton_res = self.call_llm(
            skeleton_prompt, 
            system_instruction="You are a Strategic Mastermind. Focus only on high-level contradictions and structural blueprints. No implementation details."
        )
        
        # 2. Forge (Map-Reduce drafting with Micro-Personas)
        self.logger.info("Phase 2: Roundtable Forging (Micro-Personas)...")
        drafts = []
        
        # Chapter 1: Clinical Business Analyst
        self.logger.info("Drafting Chapter 1: Clinical Business Analyst...")
        ch1_prompt = f"""Topic: {topic}\nAudience: {audience}\nSkeleton: {skeleton_res}\n
        Task: Write the 'Pain Points & Value Proposition' chapter. Quantify the clinical burden, management pain, or rating pressure. Strip all technical implementation details."""
        ch1_draft = self.call_llm(
            ch1_prompt, 
            system_instruction="You are a cynical Healthcare Business Analyst. Focus strictly on quantifying pain points and business value. Zero tech jargon.", 
            temperature=0.2
        )
        drafts.append(f"## 1. Pain Points & Value Proposition\n{ch1_draft}")

        # Chapter 2: Hardcore Systems Architect
        self.logger.info("Drafting Chapter 2: Hardcore Systems Architect...")
        ch2_prompt = f"""Topic: {topic}\nAudience: {audience}\nSkeleton: {skeleton_res}\n
        Task: Write the 'System Architecture, Migration Path & Xinchuang Compliance' chapter. YOU MUST include a Mermaid diagram (subgraph/sequence) and specific migration path (cutover/dual-track). Strip all business fluff."""
        ch2_draft = self.call_llm(
            ch2_prompt, 
            system_instruction="You are a hardcore Systems Architect. Focus strictly on network topologies, data flow, integrations, and Xinchuang (信创) compliance. Zero business fluff.", 
            temperature=0.1
        )
        drafts.append(f"## 2. System Architecture & Migration\n{ch2_draft}")

        # Chapter 3: Commercial Actuary
        self.logger.info("Drafting Chapter 3: Commercial Actuary...")
        ch3_prompt = f"""Topic: {topic}\nAudience: {audience}\nSkeleton: {skeleton_res}\n
        Task: Write the 'TCO Formula, SOW Exclusions & Residual Risks' chapter. YOU MUST include quantitative financial formulas (CapEx/OpEx/ROI). Define clear SOW (Statement of Work) boundaries."""
        ch3_draft = self.call_llm(
            ch3_prompt, 
            system_instruction="You are a ruthless Commercial Actuary and Delivery Manager. Focus strictly on financial formulas, cost structures, and risk boundaries. Defend our margins.", 
            temperature=0.1
        )
        drafts.append(f"## 3. Commercial & Delivery Boundaries\n{ch3_draft}")

        merged_draft = f"# Solution Blueprint: {topic}\n\n**Audience:** {audience}\n\n" + "\n\n".join(drafts)
        
        # 3. Adversarial Logic Auditor (Red Team)
        self.logger.info("Phase 3: Adversarial Logic Auditor (Red Team)...")
        audit_prompt = f"""
        Review the following assembled roundtable solution draft:
        {merged_draft}
        
        Task:
        1. Red Team: Identify lethal flaws (e.g., Timeline contradiction, unrealistic ROI, missing Xinchuang compliance). Fix them inline.
        2. Buzzword Audit: Remove adjectives ("advanced", "comprehensive", "intelligent"). Ensure actionable verbs.
        3. Formatting: Ensure Mermaid syntax is strictly valid and markdown is pristine.
        4. Provide the FINAL polished blueprint ready for executive review.
        """
        final_draft = self.call_llm(
            audit_prompt, 
            system_instruction="You are a brutal Red Team Auditor and Chief Editor. Destroy logic flaws, enforce extreme conciseness, and ensure the final blueprint is bulletproof."
        )
        
        # 4. Save & Gate
        draft_path = self.tmp_dir / f"solution_draft_{mode}.md"
        self.write_file(str(draft_path), final_draft)
        self.logger.info(f"Draft saved to {draft_path}")
        
        # Try running the physical gates if they exist
        self.logger.info("Running Physical Gates...")
        for script in ["logic_checker.py", "buzzword_auditor.py"]:
            gate_script = self.skill_dir / "scripts" / script
            if gate_script.exists():
                try:
                    subprocess.run(["python", str(gate_script), str(draft_path)], capture_output=True, text=True, encoding="utf-8")
                    self.logger.info(f"{script} executed.")
                except Exception as e:
                    self.logger.error(f"{script} failed: {e}")
            else:
                self.logger.info(f"Optional physical gate {script} not found, skipping.")
                    
        self.logger.info("Pipeline complete. The Agent may now review the draft, present it to the user, and physically archive the file.")
        self.logger.info("System Watchdog will ingest any entity modifications in the background.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True, help="Solution Topic")
    parser.add_argument("--audience", required=True, default="CIO", help="Target Audience")
    parser.add_argument("--mode", default="proposal", choices=["brief", "proposal", "blueprint"], help="Output mode")
    args = parser.parse_args()
    
    orchestrator = SolutionArchitectOrchestrator()
    orchestrator.run_architect(args.topic, args.audience, args.mode)
