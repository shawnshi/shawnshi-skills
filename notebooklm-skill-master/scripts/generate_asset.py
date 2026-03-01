#!/usr/bin/env python3
"""
Generate Structured Assets using NotebookLM
Implements Phase 4: Structured Asset Generation (Infographic & Slide Deck)
"""

import argparse
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from notebook_manager import NotebookLibrary
from ask_question import ask_notebooklm, FOLLOW_UP_REMINDER

def generate_prompt(asset_type: str, topic: str = None) -> str:
    """Generate the specific prompt based on asset type and topic."""
    
    topic_str = f"'{topic}'" if topic else "the core contents of this knowledge base"
    
    if asset_type == "slide_deck":
        return (
            f"Please act as a top-tier strategic management consultant. Based on ALL the documents in this "
            f"knowledge base, create a 10-slide presentation deck structure focusing on {topic_str}.\n"
            f"STRICT REQUIREMENTS:\n"
            f"1. For each page, you MUST provide a Title, and Core Arguments (Bullet points).\n"
            f"2. For each page, you MUST provide exactly 100 words of detailed Speaker Notes.\n"
            f"Format the output clearly using Markdown."
        )
    elif asset_type == "infographic":
        return (
            f"Please act as an expert in information data visualization. Based on ALL the documents in this "
            f"knowledge base, extract the development timeline or core logical loop focusing on {topic_str}, "
            f"and output a comprehensive blueprint for drawing an infographic.\n"
            f"STRICT REQUIREMENTS:\n"
            f"1. You MUST include Module Names.\n"
            f"2. You MUST provide supporting data conclusions for each module.\n"
            f"3. You MUST describe the visual guiding logic between elements (e.g., sequential, opposing, cyclical).\n"
            f"Format the output clearly using Markdown."
        )
    elif asset_type == "report":
        return (
            f"Please act as a top-tier executive strategy consultant. Based on ALL the documents in this "
            f"knowledge base, synthesize a comprehensive, formal strategic research report focusing on {topic_str}.\n"
            f"STRICT REQUIREMENTS:\n"
            f"1. You MUST use a MECE (Mutually Exclusive, Collectively Exhaustive) framework.\n"
            f"2. You MUST include specific sections: Executive Summary, Core Insights with supporting evidence, Key Leverage Points, and Quantified Risks.\n"
            f"3. You MUST maintain a precise, data-driven, and objective tone.\n"
            f"Format the output clearly using professional Markdown formatting with headers and bullet points."
        )
    else:
        raise ValueError(f"Unknown asset type: {asset_type}")

def main():
    parser = argparse.ArgumentParser(description='Generate structured assets using NotebookLM')

    parser.add_argument('--type', choices=['infographic', 'slide_deck', 'report'], required=True, 
                        help='Type of asset to generate (infographic, slide_deck, or report)')
    parser.add_argument('--notebook', help='Name or ID of the notebook (optional, uses active if not provided)')
    parser.add_argument('--topic', help='Specific topic to focus on (optional)', default="")
    parser.add_argument('--show-browser', action='store_true', help='Show browser')

    args = parser.parse_args()

    # Resolve notebook URL
    notebook_url = None
    library = NotebookLibrary()
    
    if args.notebook:
        # Try to find by ID first, then by name
        notebook = library.get_notebook(args.notebook)
        if not notebook:
            notebooks = library.list_notebooks()
            for nb in notebooks:
                if nb['name'] == args.notebook:
                    notebook = nb
                    break
        
        if notebook:
            notebook_url = notebook['url']
        else:
            print(f"❌ Notebook '{args.notebook}' not found")
            return 1
    else:
        # Check for active notebook
        active = library.get_active_notebook()
        if active:
            notebook_url = active['url']
            print(f"📚 Using active notebook: {active['name']}")
        else:
            print("❌ No notebook specified and no active notebook found.")
            print("Please specify with --notebook or activate one first.")
            return 1

    # Generate the prompt
    prompt = generate_prompt(args.type, args.topic)
    
    print(f"🎯 Asset Type: {args.type}")
    if args.topic:
        print(f"🔍 Focus Topic: {args.topic}")
    print(f"📝 Generated Prompt: \n{prompt[:150]}...\n")

    # Ask the question
    print("🚀 Triggering NotebookLM synthesis. This may take a minute or two as it reads the entire knowledge base...")
    answer = ask_notebooklm(
        question=prompt,
        notebook_url=notebook_url,
        headless=not args.show_browser
    )

    if answer:
        print("\n" + "=" * 80)
        print(f"✨ GENERATED ASSET: {args.type.upper()} ✨")
        print("=" * 80)
        print()
        
        # Clean up the follow-up reminder from the answer if present
        clean_answer = answer.replace(FOLLOW_UP_REMINDER, "")
        
        print(clean_answer)
        print()
        print("=" * 80)
        
        # Save to file
        output_dir = Path(__file__).parent.parent / "output"
        output_dir.mkdir(exist_ok=True)
        
        safe_topic = "".join([c if c.isalnum() else "_" for c in args.topic]) if args.topic else "core"
        filename = f"{args.type}_{safe_topic}_{int(time.time())}.md"
        filepath = output_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# Asset: {args.type.upper()}\n")
            f.write(f"# Topic: {args.topic or 'Core Knowledge Base'}\n\n")
            f.write(clean_answer)
            
        print(f"💾 Saved structured asset to: {filepath}")
        return 0
    else:
        print("\n❌ Failed to generate asset")
        return 1

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Default behavior when run without args for testing/display
        print("Usage examples:")
        print('  python scripts/run.py generate_asset.py --type "infographic" --notebook "[Library Name]"')
        print('  python scripts/run.py generate_asset.py --type "slide_deck" --topic "Competitive Analysis"')
        sys.exit(1)
    sys.exit(main())
