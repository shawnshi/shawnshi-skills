"""
<!-- Input: Raw text (AI-generated or formal) -->
<!-- Output: Humanized text, Analysis report, Humanizer Score -->
<!-- Pos: scripts/humanize_engine.py. Linguistic refinement engine. -->
"""

import argparse
import sys
import subprocess
import os

def read_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return ""

def main():
    parser = argparse.ArgumentParser(description="Humanizer-zh-pro Linguistic Engine")
    parser.add_argument("text_or_file", nargs='?', default="", help="The text to analyze or path to a text file")
    parser.add_argument("--test", action="store_true", help="Run the built-in test case")
    args = parser.parse_args()
    
    # 1. Resolve Input
    input_text = ""
    if args.test:
        input_text = "随着数字医疗的大力推进，我司的 HIS 核心系统重构项目迎来了重要的里程碑。通过对底层架构的深度整合与微服务化改造，我们不仅实现了系统性能的显著优化，还有效降低了运维成本。综上所述，这一阶段性成果展现了我们在医疗信息化领域的深厚积累。"
    elif os.path.isfile(args.text_or_file):
        with open(args.text_or_file, 'r', encoding='utf-8') as f:
            input_text = f.read()
    else:
        input_text = args.text_or_file

    if not input_text.strip():
        print("Error: Empty input. Provide text or use --test.")
        sys.exit(1)

    print(f"[*] Input length: {len(input_text)} chars")
    print(f"[*] Engine initializing...")

    # 2. Build the Persona & Constraints Prompt
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skill_md = read_file(os.path.join(base_dir, "SKILL.md"))
    guidelines_md = read_file(os.path.join(base_dir, "references", "GUIDELINES.md"))
    checklist_md = read_file(os.path.join(base_dir, "references", "CHECKLIST.md"))

    system_prompt = f"""
你是卫宁健康的战略咨询总经理，也是顶尖的文字重铸师。你需要将以下文本按照【三阶层润色】的方法进行彻底“去AI化”改写。

【一、核心心法】
{skill_md}

【二、黑名单与置换词典】
{guidelines_md}

【三、任务自检清单】
{checklist_md}

【动作要求】
1. 首先，简要输出一段极短的修改思路（CoT推演），直接指出原文本中哪些词汇踩了黑名单，哪些句子节奏不对。
2. 然后，输出【最终高管简报终稿】。
3. 最后，根据《任务自检清单》执行打分核查（例如：5/5分，满足所有条件）。

【原始输入文本】
{input_text}
"""

    print("[*] Dispatching to LLM engine for linguistic processing...")
    
    # 3. Call Gemini CLI
    try:
        import tempfile
        # Write prompt to a temporary file to avoid command-line length limits and escaping hell
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(system_prompt)
            temp_path = f.name

        cmd = f"gemini -p (Get-Content -Raw -Path '{temp_path}')"
        process = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        stdout, stderr = process.communicate()
        
        # Cleanup temp file
        try:
            os.remove(temp_path)
        except Exception:
            pass
        
        if process.returncode != 0:
            print("[!] Gemini CLI execution failed:")
            print(stderr)
        else:
            print("\n" + "="*60)
            print(" 🔪 【Humanizer-zh-pro 文本重铸完毕】 🔪")
            print("="*60 + "\n")
            print(stdout)
            
    except FileNotFoundError:
        print("[!] Error: 'gemini' CLI tool not found. Please ensure it is installed and in your PATH.")
        sys.exit(1)
    except Exception as e:
        print(f"[!] Unexpected error: {e}")

if __name__ == "__main__":
    main()
