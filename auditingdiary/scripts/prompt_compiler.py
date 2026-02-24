import os

def compile_prompts():
    """
    Compiles modular weekly prompts into a single master file.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    weekly_dir = os.path.join(base_dir, "prompts", "weekly")
    output_path = os.path.join(base_dir, "prompts", "compiled_weekly_prompt.md")
    
    order = [
        "PART_0_ACCOUNTABILITY.md",
        "PART_I_COGNITION.md",
        "PART_II_PATTERNS.md",
        "PART_III_WORK.md",
        "PART_IV_BALANCE.md",
        "PART_V_PROACTIVE.md",
        "PART_VI_STRATEGIC_ALIGNMENT.md"
    ]
    
    compiled_content = "# COMPILED WEEKLY AUDIT PROMPT\n\n"
    compiled_content += "> **Warning**: This is a generated file. Do not edit directly.\n\n"
    
    for filename in order:
        file_path = os.path.join(weekly_dir, filename)
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                compiled_content += f.read() + "\n\n---\n\n"
        else:
            print(f"Warning: {filename} not found.")
            
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(compiled_content)
    
    return output_path

if __name__ == "__main__":
    path = compile_prompts()
    print(f"Compiled prompt saved to: {path}")
