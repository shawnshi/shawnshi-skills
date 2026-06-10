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

class WritingAssistantOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("WritingAssistantOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\personal-writing-assistant")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")
        self.workspace = Path(r"C:\Users\shich\.gemini\MEMORY")

    def run_writing(self, topic: str):
        self.logger.info(f"Starting Personal Writing Assistant Pipeline for topic: {topic}")
        
        # 1. Core Assault (找核)
        self.logger.info("Phase 1: Core Assault (Inversion & Red Teaming)...")
        core_prompt = f"""
        Topic: {topic}
        Perform Core Assault:
        1. Inversion: Reverse the common judgment. Is the opposite a cliché?
        2. Premise: What is the hidden assumption?
        3. Identify the true, non-consensus "Core" of this topic.
        Output the Core Report.
        """
        core_report = self.call_llm(core_prompt, system_instruction="You are a brutal cognitive critic.")
        
        # 2. Ghost Deck
        self.logger.info("Phase 2: Ghost Deck (Skeleton)...")
        skeleton_prompt = f"""
        Core Report:
        {core_report}
        
        Create a 3-4 chapter outline. 
        Rules:
        - Chapter titles must be judgments, not nouns.
        - No AI clichés or didactic tone.
        """
        skeleton = self.call_llm(skeleton_prompt, system_instruction="You are an expert essayist outlining a thought piece.")
        
        # 3. Drafting
        self.logger.info("Phase 3: Surgical Drafting...")
        draft_prompt = f"""
        Core Report:
        {core_report}
        
        Outline:
        {skeleton}
        
        Task: Draft the full article.
        Rules:
        - Peer-to-Peer stance: You are sharing a detour you took, not preaching from above.
        - No "Three-part" parallelisms.
        - No "综上所述" (In summary).
        - Use specific scenarios instead of abstract explanations.
        - Short sentences as hammers.
        """
        draft = self.call_llm(draft_prompt, system_instruction="You are a top-tier Chinese writer. Execute extreme anti-AI style.", temperature=0.7)
        
        # 4. Polish & Anti-AI Audit
        self.logger.info("Phase 4: Final Polish and Anti-AI Audit...")
        polish_prompt = f"""
        Draft:
        {draft}
        
        Audit and rewrite if necessary to fix:
        1. Remove any AI tone (teaching tone, summarization at the end, excessive adjectives).
        2. Replace abstract arguments with concrete actions/scenarios.
        3. Ensure the ending is open-ended, no summary.
        """
        final_draft = self.call_llm(polish_prompt, system_instruction="You are the brutal Chief Editor.")
        
        # 5. Save & Snapshot
        # Clean topic string for filename
        clean_topic = "".join([c for c in topic if c.isalpha() or c.isdigit() or c==' ']).rstrip()
        out_file = self.workspace / "raw" / "article" / f"{clean_topic.replace(' ', '_')}_Full.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.write_file(str(out_file), final_draft)
        self.logger.info(f"Article saved to {out_file}")
        
        observe_script = self.skill_dir / "scripts" / "observe.py"
        if observe_script.exists():
            try:
                subprocess.run(["python", str(observe_script), "record-original", str(out_file)], capture_output=True)
                self.logger.info("Snapshot recorded via observe.py")
            except Exception as e:
                self.logger.error(f"Observe snapshot failed: {e}")

        self.logger.info("Pipeline complete. Agent may now deliver the final article.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True, help="Topic for the article")
    args = parser.parse_args()
    
    orchestrator = WritingAssistantOrchestrator()
    orchestrator.run_writing(args.topic)
