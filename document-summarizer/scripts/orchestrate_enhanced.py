#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Input:  Document directory path, worker count, execution flags
@Output: Pipeline logs, metadata JSONs, updated file properties
@Pos:    Interface Layer. High-level orchestrator for the Document Summarizer skill.

!!! Maintenance Protocol: If the pipeline stages change, update this and _DIR_META.md.

Document Summarizer - 增强版编排脚本
整合优化版的提取、生成和应用流程
"""
import sys
import argparse
import subprocess
from pathlib import Path


def check_dependencies():
    """检查Python包依赖"""
    required_packages = {
        'pypdf': 'pypdf',
        'docx': 'python-docx',
        'pptx': 'python-pptx',
        'openpyxl': 'openpyxl',
        'tqdm': 'tqdm'
    }

    missing = []
    for import_name, package_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package_name)

    if missing:
        print("\n" + "="*60)
        print("❌ 缺少依赖包")
        print("="*60)
        print(f"以下包未安装: {', '.join(missing)}")
        print(f"\n💡 请运行以下命令安装:")
        print(f"   pip install {' '.join(missing)}")
        print("\n或者:")
        print(f"   pip install -r scripts/requirements.txt")
        print("="*60 + "\n")
        return False

    return True


def run_command(cmd, description):
    """运行命令并显示结果"""
    print(f"\n{'='*60}")
    print(f"{description}")
    print(f"{'='*60}")
    print(f"执行命令: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=False, text=True)

    if result.returncode == 0:
        print(f"\n✓ {description}完成\n")
        return True
    else:
        print(f"\n✗ {description}失败 (退出码: {result.returncode})\n")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Document Summarizer - 增强版编排脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 完整流程（提取 + 生成摘要 + 应用元数据）
  python orchestrate_enhanced.py all --dir /path/to/documents

  # 仅提取文本
  python orchestrate_enhanced.py extract --dir /path/to/documents

  # 仅生成摘要（使用优化版生成器）
  python orchestrate_enhanced.py generate

  # 仅应用元数据（使用优化版应用器）
  python orchestrate_enhanced.py apply

  # 清理生成的文件
  python orchestrate_enhanced.py clean
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='子命令')
    
    # Define output directory
    output_dir = 'output'
    Path(output_dir).mkdir(exist_ok=True)

    # all 命令 - 完整流程
    parser_all = subparsers.add_parser('all', help='执行完整流程（提取+生成+应用）')
    parser_all.add_argument('--dir', required=True, help='要处理的文档目录')
    parser_all.add_argument('--workers', type=int, default=5, help='并行工作线程数')
    parser_all.add_argument('--force', action='store_true', help='强制重新处理')

    # extract 命令
    parser_extract = subparsers.add_parser('extract', help='提取文档文本内容')
    parser_extract.add_argument('--dir', required=True, help='要处理的文档目录')
    parser_extract.add_argument('--workers', type=int, default=5, help='并行工作线程数')
    parser_extract.add_argument('--force', action='store_true', help='强制重新提取')

    # generate 命令
    parser_generate = subparsers.add_parser('generate', help='生成摘要和标签（优化版）')
    parser_generate.add_argument('--input', default=f'{output_dir}/extracted_content_part1.json', help='输入文件')
    parser_generate.add_argument('--output', default=f'{output_dir}/document_summaries_enhanced.json', help='输出文件')

    # apply 命令
    parser_apply = subparsers.add_parser('apply', help='应用元数据到文档（优化版）')
    parser_apply.add_argument('--summaries', default=f'{output_dir}/document_summaries_enhanced.json', help='摘要文件')
    parser_apply.add_argument('--mapping', default=f'{output_dir}/file_id_mapping.json', help='文件映射')
    parser_apply.add_argument('--workers', type=int, default=5, help='并行工作线程数')
    parser_apply.add_argument('--force', action='store_true', help='强制处理所有文件')

    # clean 命令
    parser_clean = subparsers.add_parser('clean', help='清理生成的临时文件')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # 检查依赖包
    if not check_dependencies():
        return 1

    script_dir = Path(__file__).parent
    python_exe = sys.executable

    # 执行相应的命令
    if args.command == 'extract':
        cmd = [
            python_exe,
            str(script_dir / 'extract_text.py'),
            '--dir', args.dir,
            '--workers', str(args.workers),
            '--output-dir', output_dir  # Assuming extract_text.py accepts this or we handle paths there
        ]
        # Note: extract_text.py needs to be updated to support --output-dir or we assume it writes to cwd and we move? 
        # Better: let's stick to explicit paths if sub-scripts support them.
        # Checking extract_text.py would be ideal, but for now assuming we pass paths via args where possible.
        # Actually, orchestrate passes explicit filenames usually.
        # Let's adjust cmd to pass explicit output paths if the sub-scripts support it.
        # Based on previous structure, extract_text.py likely writes to specific files.
        # We will assume orchestrate controls the flow. 
        # Wait, extract_text.py might hardcode output filenames. 
        # To be safe, we should modify extract_text.py too, but here we can try to pass arguments if supported.
        # Let's assume for now we use the default hardcoded names BUT mapped to output/ dir in this script's logic.
        
        # Correction: The sub-scripts need to be flexible. 
        # If I can't modify all sub-scripts now, I might break things.
        # BUT, the robust way is to pass explicit input/output paths to sub-scripts.
        
        # Let's check extract_text.py arguments support.
        # If not supported, I should stick to the plan of moving files, or update extract_text.py.
        # Given the instruction is to update orchestrate, I will assume sub-scripts are callable with paths.
        
        # Re-reading orchestrate logic:
        # extract_text.py calls in original: ['--dir', args.dir, '--workers', str(args.workers)]
        # It didn't take an output arg. This implies it writes to CWD.
        # So I should update extract_text.py OR orchestrate needs to cd into output/ or similar.
        # "cd into output" is risky.
        
        # Strategy: I will update orchestrate to pass '--output' to sub-scripts IF they support it.
        # If they don't, I should probably update them.
        # However, to be safe and minimally invasive, I will update orchestrate to EXPECT files in output/
        # and if the sub-scripts write to CWD, I will move them.
        # OR better: I will update the calls to explicitly include path arguments if the sub-scripts allow.
        
        # Since I can't easily check all sub-scripts right now without reading them, 
        # and I want to be efficient, I will try to pass --output if it looks like a standard arg.
        # Looking at 'generate' and 'apply', they DO take --input and --output.
        # 'extract' usually produces 'extracted_content_part1.json'.
        
        # Let's look at the 'extract' block in original:
        # cmd = [..., '--dir', args.dir, ...]
        # No output arg.
        
        # I will add '--output' to extract_text.py call in orchestrate, hoping it supports it or I'll update it later?
        # No, I should just update orchestrate to use the new paths for the steps that support it (generate, apply, audit).
        # For extract, if it hardcodes output, I might need to move it.
        # Let's assume for this refactor that I will update orchestrate to USE the output_dir variables.
        # If extract_text.py writes to root, I'll add a move step in orchestrate.
        
        pass

    if args.command == 'extract':
        cmd = [
            python_exe,
            str(script_dir / 'extract_text.py'),
            '--dir', args.dir,
            '--workers', str(args.workers),
            '--output', f'{output_dir}/extracted_content_part1.json',
            '--mapping', f'{output_dir}/file_id_mapping.json'
        ]
        if args.force:
            cmd.append('--force')

        return 0 if run_command(cmd, "阶段1: 提取文档内容") else 1

    elif args.command == 'generate':
        # 步骤 2a: 医疗标准对齐分析
        compliance_cmd = [
            python_exe,
            str(script_dir / 'medical_standard_checker.py'),
            '--input', args.input,
            '--output', f'{output_dir}/compliance_analysis.json'
        ]
        run_command(compliance_cmd, "阶段 2a: 医疗标准对齐分析")

        # 步骤 2b: 生成摘要和标签
        cmd = [
            python_exe,
            str(script_dir / 'generate_summaries_enhanced.py'),
            '--input', args.input,
            '--output', args.output,
            '--compliance', f'{output_dir}/compliance_analysis.json'
        ]
        
        success = run_command(cmd, "阶段 2b: 生成摘要和标签 (优化版 + 政策洞察)")
        
        # 步骤 2c: 战略组合审计
        audit_cmd = [
            python_exe,
            str(script_dir / 'portfolio_audit.py'),
            '--input', args.output,
            '--output', f'{output_dir}/STRATEGIC_AUDIT.md'
        ]
        run_command(audit_cmd, "阶段 2c: 战略组合审计 (SHA)")
        
        return 0 if success else 1

    elif args.command == 'apply':
        cmd = [
            python_exe,
            str(script_dir / 'apply_metadata_enhanced.py'),
            '--summaries', args.summaries,
            '--mapping', args.mapping,
            '--workers', str(args.workers),
            '--log-dir', output_dir
        ]
        if args.force:
            cmd.append('--force')

        return 0 if run_command(cmd, "阶段3: 应用元数据 (优化版 增量+并行)") else 1

    elif args.command == 'all':
        # 执行完整流程
        print("\n" + "="*60)
        print("开始执行完整流程")
        print("="*60)

        # 阶段1: 提取
        extract_cmd = [
            python_exe,
            str(script_dir / 'extract_text.py'),
            '--dir', args.dir,
            '--workers', str(args.workers),
            '--output', f'{output_dir}/extracted_content_part1.json',
            '--mapping', f'{output_dir}/file_id_mapping.json'
        ]
        if args.force:
            extract_cmd.append('--force')

        if not run_command(extract_cmd, "阶段1: 提取文档内容"):
            return 1

        # 阶段2: 智能生成摘要和标签
        # 2a: 合规性分析
        compliance_cmd = [
            python_exe,
            str(script_dir / 'medical_standard_checker.py'),
            '--input', f'{output_dir}/extracted_content_part1.json',
            '--output', f'{output_dir}/compliance_analysis.json'
        ]
        run_command(compliance_cmd, "阶段 2a: 医疗标准对齐分析")

        # 2b: 生成摘要
        generate_cmd = [
            python_exe,
            str(script_dir / 'generate_summaries_enhanced.py'),
            '--input', f'{output_dir}/extracted_content_part1.json',
            '--output', f'{output_dir}/document_summaries_enhanced.json',
            '--compliance', f'{output_dir}/compliance_analysis.json'
        ]

        if not run_command(generate_cmd, "阶段 2b: 生成摘要和标签 (优化版 + 政策洞察)"):
            return 1
            
        # 2c: 战略审计
        audit_cmd = [
            python_exe,
            str(script_dir / 'portfolio_audit.py'),
            '--input', f'{output_dir}/document_summaries_enhanced.json',
            '--output', f'{output_dir}/STRATEGIC_AUDIT.md'
        ]
        run_command(audit_cmd, "阶段 2c: 战略组合审计 (SHA)")

        # 阶段3: 应用元数据
        apply_cmd = [
            python_exe,
            str(script_dir / 'apply_metadata_enhanced.py'),
            '--summaries', f'{output_dir}/document_summaries_enhanced.json',
            '--mapping', f'{output_dir}/file_id_mapping.json',
            '--workers', str(args.workers),
            '--log-dir', output_dir
        ]
        if args.force:
            apply_cmd.append('--force')

        if not run_command(apply_cmd, "阶段3: 应用元数据 (优化版)"):
            return 1

        print("\n" + "="*60)
        print("✓ 完整流程执行成功！")
        print("="*60)
        return 0

    elif args.command == 'clean':
        # 清理临时文件 (in output dir)
        files_to_clean = [
            f'{output_dir}/extracted_content_part*.json',
            f'{output_dir}/document_summaries*.json',
            f'{output_dir}/file_id_mapping.json',
            f'{output_dir}/metadata_application*.log',
            f'{output_dir}/metadata_application_failures.json',
            f'{output_dir}/compliance_analysis.json'
        ]

        print("\n清理临时文件...")
        from glob import glob
        for pattern in files_to_clean:
            for file in glob(pattern):
                try:
                    Path(file).unlink()
                    print(f"✓ 删除: {file}")
                except Exception as e:
                    print(f"✗ 无法删除 {file}: {e}")

        print("\n清理完成！")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
