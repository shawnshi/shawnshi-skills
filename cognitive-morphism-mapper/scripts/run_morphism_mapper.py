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

class MorphismMapperOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("MorphismMapperOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\cognitive-morphism-mapper")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_mapper(self, problem: str, target_domain: str = None):
        self.logger.info(f"Starting Cognitive Morphism Mapper Pipeline. Problem: {problem}")
        
        # Phase 1: Skeleton Extractor
        self.logger.info("Executing Phase 1: Skeleton Extractor...")
        extract_prompt = f"""
        Problem Description:
        {problem}
        
        Task:
        Strip ALL business, social, or emotional context from this problem.
        Extract only the pure mathematical/structural skeleton:
        1. Objects (A, B, C...) - What are the fundamental entities?
        2. Morphisms (f: A -> B) - What are the exact structural relationships or transformations between them?
        Output only the cold, formal topological structure.
        """
        skeleton = self.call_llm(
            extract_prompt, 
            system_instruction="You are a strict Category Theorist. You only see Objects and Morphisms. Reject any domain-specific fluff."
        )
        
        # Phase 2: Domain Selector
        self.logger.info("Executing Phase 2: Domain Selector...")
        if not target_domain:
            select_prompt = f"""
            Abstract Skeleton:
            {skeleton}
            
            Task:
            Based on this topological structure, select the ONE most isomorphic scientific domain (e.g., Thermodynamics, Evolutionary Biology, Fluid Dynamics, Quantum Mechanics, Information Theory).
            Do not choose business or psychology.
            Name the domain and explicitly state the structural isomorphism (why it is a perfect mathematical match).
            """
            domain_selection = self.call_llm(
                select_prompt,
                system_instruction="You are a Polymath Scientist. Find the exact structural resonance in hard sciences."
            )
        else:
            domain_selection = f"Target Domain Forced by User: {target_domain}"
            self.logger.info(f"Domain pre-selected: {target_domain}")

        # Phase 3: Theorem Prover
        self.logger.info("Executing Phase 3: Theorem Prover...")
        prove_prompt = f"""
        Abstract Skeleton:
        {skeleton}
        
        Selected Scientific Domain:
        {domain_selection}
        
        Task:
        1. Establish the exact Functor mapping F from the problem's skeleton to the chosen scientific domain.
        2. Identify a hard, mathematically proven theorem or unyielding law in the target domain that applies to this structure (e.g., 2nd Law of Thermodynamics, Competitive Exclusion Principle).
        3. Force the abstract objects through this theorem to see what the scientific law dictates MUST happen.
        """
        theorem_proof = self.call_llm(
            prove_prompt,
            system_instruction="You are a hardcore Theoretical Physicist/Biologist. Apply hard scientific laws rigidly. Do not use cheap metaphors."
        )

        # Phase 4: Commutativity Checker
        self.logger.info("Executing Phase 4: Commutativity Checker...")
        check_prompt = f"""
        Original Problem: {problem}
        Theorem Application in Target Domain: {theorem_proof}
        
        Task:
        Perform a Commutativity Check (逆映射验算).
        Map the scientific outcome strictly back to the original business/real-world problem.
        Does the logic commute? If we apply the scientific solution to the real world, what breaks? What is the brutal truth?
        """
        commutativity_check = self.call_llm(
            check_prompt,
            system_instruction="You are a ruthless Logician. Validate the inverse mapping. Reject wishful thinking."
        )

        # Phase 5: Strategic Synthesis
        self.logger.info("Executing Phase 5: Strategic Synthesis...")
        synthesis_prompt = f"""
        Problem: {problem}
        Structural Skeleton: {skeleton}
        Isomorphic Domain: {domain_selection}
        Theorem Dynamics: {theorem_proof}
        Logic Validation: {commutativity_check}
        
        Task:
        Synthesize the final "Dimensional Strike" (升维打击) solution.
        Structure the output as a Markdown report:
        1. **The Structural Trap**: Why conventional thinking failed.
        2. **The Isomorphic Mapping**: The scientific law that governs this structure.
        3. **The Non-Consensus Solution**: The counter-intuitive action dictated by the math/science.
        4. **Commutativity Constraints**: Where the model breaks and what to watch out for.
        
        Ensure brutal honesty. No fluff.
        """
        final_solution = self.call_llm(
            synthesis_prompt,
            system_instruction="You are a Tier-0 Strategic Architect. Deliver paradigm-shifting insights grounded purely in structural science."
        )
        
        # Safe Windows filename
        safe_name = "".join([c if c.isalnum() else "_" for c in problem[:15]])
        output_file = self.tmp_dir / f"morphism_map_{safe_name}.md"
        self.write_file(str(output_file), final_solution)
        self.logger.info(f"Morphism Mapping successfully archived to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem", required=True, help="The problem to map and solve")
    parser.add_argument("--domain", required=False, help="Optional forced target domain (e.g. Thermodynamics)")
    args = parser.parse_args()
    
    orchestrator = MorphismMapperOrchestrator()
    orchestrator.run_mapper(args.problem, args.domain)
