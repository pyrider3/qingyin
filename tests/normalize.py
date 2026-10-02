"""Regression checks for the local, unconditional Simplified Chinese output."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from normalize import simplified
cases={
 '繁體中文，臺灣語音輸入，軟體設定與記憶體。':'繁体中文，台湾语音输入，软体设定与记忆体。',
 '你好，世界。':'你好，世界。',
 '使用 Neovim 和 ChatGPT，轉寫到 Windows 11。':'使用 Neovim 和 ChatGPT，转写到 Windows 11。',
 '乾燥的頭髮，發現滑鼠不能錄製音訊。':'干燥的头发，发现滑鼠不能录制音讯。',
}
for source,expected in cases.items():
 result=simplified(source)
 assert result==expected,(source,result,expected)
 assert simplified(result)==result
print('PASS: Traditional Chinese, phrase conversion, Simplified idempotence and mixed English')
