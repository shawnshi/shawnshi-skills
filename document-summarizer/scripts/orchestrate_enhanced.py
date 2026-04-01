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


def _write_telemetry(start_time, status, output_dir):
    """记录 Mentat V6.0 遥测信息到 MEMORY 知识库"""
    import os
    import json
    import time
    from pathlib import Path

    duration_sec = time.time() - start_time
    # 模拟估算 token (因为我们并没有真正精确捕获所有子进程的 token 用量)
    input_tokens = 0
    output_tokens = 0
    
    # Check if we have the document_summaries_enhanced.json to measure
    summary_file = Path(output_dir) / "document_summaries_enhanced.json"
    if summary_file.exists():
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                input_tokens = len(data) * 2000 # 估算 2k tokens/doc input
                output_tokens = len(data) * 150 # 估算 150 output tokens
        except:
            pass
            
    telemetry_data = {
        "skill_name": "document-summarizer",
        "status": status,
        "duration_sec": round(duration_sec, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    # 找到 root 目录下的 .gemini/MEMORY/skill_audit/telemetry
    user_home = Path.home()
    telemetry_dir = user_home / ".gemini" / "MEMORY" / "skill_audit" / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    
    telemetry_file = telemetry_dir / f"record_{int(time.time())}.json"
    try:
        with open(telemetry_file, "w", encoding="utf-8") as f:
            json.dump(telemetry_data, f, ensure_ascii=False, indent=2)
        print(f"\n[Telemetry] 执行指标已记录至: {telemetry_file}")
    except Exception as e:
        print(f"\n[Telemetry] 未能记录指标: {e}")


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
        print("\n" + "="*60)
        print("开始执行完整流程")
        print("="*60)
        import time
        start_time = time.time()

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
            _write_telemetry(start_time, "failed_extract", output_dir)
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

        if not run_command(generate_cmd, "阶段 2b: 生成摘要和标签 (原生 AI/兜底)"):
            _write_telemetry(start_time, "failed_generate", output_dir)
            return 1
            
        # 校验生成质量 (阻断无脑 PENDING_LLM_GENERATION 透传)
        try:
            import json
            with open(f'{output_dir}/document_summaries_enhanced.json', 'r', encoding='utf-8') as f:
                summaries = json.load(f)
                pending_count = sum(1 for s in summaries if "PENDING_LLM_GENERATION" in s.get("summary", ""))
                if pending_count > 0:
                    print(f"\n⚠️ 发现 {pending_count} 个文档处于 PENDING_LLM_GENERATION 占位状态！")
                    print("⚠️ 阻断启动：禁止将未解析的临时占位符写入文件属性。")
                    _write_telemetry(start_time, "blocked_apply_pending", output_dir)
                    return 1
        except Exception as filter_e:
            print(f"\n⚠️ 无法分析生成的 JSON 文件以验证质量，终止 apply。{filter_e}")
            _write_telemetry(start_time, "failed_verify", output_dir)
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

        if not run_command(apply_cmd, "阶段3: 应用元数据 (增强写回)"):
            _write_telemetry(start_time, "failed_apply", output_dir)
            return 1

        print("\n" + "="*60)
        print("✓ 完整流程执行成功！")
        print("="*60)
        _write_telemetry(start_time, "success", output_dir)
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
