from pathlib import Path
import subprocess
home=Path.home()
subprocess.run(['systemctl','--user','stop','qingyin-learning.service'])
subprocess.run(['systemctl','--user','disable','--now','qingyin'])
p=home/'.config/niri/config.kdl'
s=p.read_text()
marker='// Qingyin preview must not steal the text field\'s focus.'
if marker in s:
 start=s.index(marker)
 opening=s.index('{',start);depth=1;end=opening+1
 while depth:
  if s[end]=='{':depth+=1
  elif s[end]=='}':depth-=1
  end+=1
 s=s[:start]+s[end:]
lines=s.splitlines(True)
s=''.join(line for line in lines if 'Qingyin local dictation:' not in line and not ('spawn' in line and '/.local/bin/qingyin' in line))
p.write_text(s)
for relative in ('.local/bin/qingyin','.config/systemd/user/qingyin.service','.local/share/fcitx5/addon/qingyin.conf','.local/share/applications/qingyin.desktop','.local/share/applications/qingyin-settings.desktop'):
 (home/relative).unlink(missing_ok=True)
subprocess.run(['systemctl','--user','daemon-reload'])
print('青音已停用。配置、模型和源码已保留；重启 fcitx5 后插件卸载。')
