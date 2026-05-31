# Gemini TTS Skill Environment Setup

Write-Host "正在校准神经网络语音环境..." -ForegroundColor Cyan

# 1. 检查 Python 依赖
$dependencies = @("edge-tts", "pyttsx3")
foreach ($dep in $dependencies) {
    if (!(pip list | Select-String $dep)) {
        Write-Host "正在安装依赖: $dep..."
        pip install $dep --quiet
    } else {
        Write-Host "依赖已就绪: $dep"
    }
}

# 2. 检查输出目录
$dirs = @("output", "references")
foreach ($dir in $dirs) {
    if (!(Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
}

Write-Host "TTS 2.0 环境校准完成。" -ForegroundColor Green
