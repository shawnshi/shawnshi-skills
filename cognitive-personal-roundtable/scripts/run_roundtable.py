import sys
import os
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

class RoundtableOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("RoundtableOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\cognitive-personal-roundtable")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_roundtable(self, topic: str, personas_str: str, rounds: int):
        self.logger.info(f"Starting In-Memory Roundtable. Topic: {topic}")
        personas = [p.strip() for p in personas_str.split(",") if p.strip()]
        if not personas:
            self.logger.error("No personas provided.")
            return

        self.logger.info(f"Participants: {', '.join(personas)}")
        
        transcript = f"# Cognitive Roundtable: {topic}\n\n**Participants:** {', '.join(personas)}\n\n"
        
        # --------------------------------------------------------------------------------
        # ATOMIZED ROUNDTABLE (True Persona Isolation)
        # --------------------------------------------------------------------------------
        for r in range(1, rounds + 1):
            self.logger.info(f"--- Starting Round {r} ---")
            transcript += f"## Round {r}\n\n"
            
            for persona in personas:
                self.logger.info(f"[{persona}] is formulating argument...")
                prompt = f"""
                Topic: {topic}
                
                Current Roundtable Transcript:
                {transcript}
                
                Task:
                You are {persona}. Respond to the topic and the preceding arguments made by other participants.
                Attack weak logic, defend your core philosophy, and aggressively push your worldview.
                Do not break character. Do not be polite if it betrays your philosophy.
                End your response with a bold **简言之：** (In a nutshell) compressing your logic into one sentence.
                """
                
                response = self.call_llm(
                    prompt,
                    system_instruction=f"You are {persona}. You are participating in a high-tension intellectual roundtable. Stay absolutely true to your historical/philosophical worldview. Reject consensus if it compromises your principles.",
                    temperature=0.7
                )
                
                transcript += f"### {persona}\n{response}\n\n"
                
        # Moderator Synthesis
        self.logger.info("Executing Phase: Moderator Synthesis & ASCII Topology...")
        moderator_prompt = f"""
        Full Roundtable Transcript:
        {transcript}
        
        Task:
        You are the Mentat Moderator.
        1. Synthesize the core tension points and unbridgeable divides between the participants.
        2. Create an ASCII Topology map showing the ideological alignment/opposition of the participants (use text characters to draw).
        3. Formulate the ultimate action-oriented takeaway.
        """
        synthesis = self.call_llm(
            moderator_prompt,
            system_instruction="You are a Mentat Moderator. You do not take sides. You observe the geometry of the argument and extract pure structural insight."
        )
        
        final_document = f"{transcript}\n## Moderator Synthesis & Topology\n\n{synthesis}"
        
        # Safe Windows filename
        safe_topic = "".join([c if c.isalnum() else "_" for c in topic[:15]])
        output_file = self.tmp_dir / f"roundtable_final_{safe_topic}.md"
        self.write_file(str(output_file), final_document)
        self.logger.info(f"Roundtable successfully archived to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True, help="The debate topic")
    parser.add_argument("--personas", required=True, help="Comma-separated list of personas")
    parser.add_argument("--rounds", type=int, default=2, help="Number of debate rounds")
    args = parser.parse_args()
    
    orchestrator = RoundtableOrchestrator()
    orchestrator.run_roundtable(args.topic, args.personas, args.rounds)
