#!/usr/bin/env python3
"""Install per-user only; preserve an existing config and back up niri edits."""
from pathlib import Path
from datetime import datetime
import json, shutil, subprocess
root=Path(__file__).resolve().parent
home=Path.home()
share=home/'.local/share/qingyin'
share.mkdir(parents=True,exist_ok=True)
(share/'fcitx').mkdir(exist_ok=True)
installed_addon=share/'fcitx/libqingyin.so'
if not installed_addon.exists() or installed_addon.read_bytes() != (root/'fcitx/libqingyin.so').read_bytes():
 temporary_addon=installed_addon.with_suffix('.tmp')
 shutil.copy2(root/'fcitx/libqingyin.so',temporary_addon)
 temporary_addon.replace(installed_addon)
addon=home/'.local/share/fcitx5/addon/qingyin.conf'
addon.parent.mkdir(parents=True,exist_ok=True)
addon.write_text((root/'fcitx/qingyin.conf').read_text().replace('Library=libqingyin',f'Library={share}/fcitx/libqingyin'))
config=home/'.config/qingyin/config.json'
config.parent.mkdir(parents=True,exist_ok=True)
if not config.exists():
 config.write_text(json.dumps({'model':str(share/'models/large-v3'),'device':'cuda','language':'zh','auto_input':True,'microphone':None,'max_seconds':300,'show_panel':False,'compute_type':'float16','beam_size':5,'hotwords':'','punctuation':True,'learning':True},ensure_ascii=False,indent=2)+'\n')
launcher=home/'.local/bin/qingyin'
launcher.parent.mkdir(parents=True,exist_ok=True)
site=next((root/'.venv/lib').glob('python*/site-packages'))
launcher.write_text(f'''#!/bin/sh
export QINGYIN_HOME='{root}'
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export LD_LIBRARY_PATH='{site}/nvidia/cublas/lib:{site}/nvidia/cudnn/lib:{site}/nvidia/cuda_nvrtc/lib:{site}/nvidia/cuda_runtime/lib:{site}/nvidia/cufft/lib:{site}/nvidia/curand/lib:{site}/nvidia/nvjitlink/lib'${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}
exec '{root}/target/release/qingyin' "$@"
''')
launcher.chmod(0o755)
unit=home/'.config/systemd/user/qingyin.service'
unit.parent.mkdir(parents=True,exist_ok=True)
unit.write_text(f'''[Unit]
Description=Qingyin offline voice input
After=graphical-session.target pipewire.service
PartOf=graphical-session.target
[Service]
Type=simple
ExecStart={launcher} session
ExecStopPost={launcher} cleanup
Restart=no
TimeoutStopSec=5
UMask=0077
RestrictAddressFamilies=AF_UNIX AF_NETLINK
Environment=HF_HUB_OFFLINE=1
Environment=TRANSFORMERS_OFFLINE=1
''')
(unit.parent/'qingyin-model.service').write_text(f'''[Unit]
Description=Qingyin resident offline model
PartOf=graphical-session.target
[Service]
Type=simple
ExecStart={launcher} model-server
Restart=no
TimeoutStopSec=5
UMask=0077
RestrictAddressFamilies=AF_UNIX AF_NETLINK
Environment=HF_HUB_OFFLINE=1
Environment=TRANSFORMERS_OFFLINE=1
''')
desktop=home/'.local/share/applications/qingyin.desktop'
desktop.parent.mkdir(parents=True,exist_ok=True)
desktop.write_text(f'''[Desktop Entry]
Type=Application
Name=青音 · 本地语音输入
Comment=按一次开始录音，再按一次停止并转写
Exec={launcher} toggle
Icon=audio-input-microphone
Categories=Utility;Audio;
Terminal=false
Actions=Settings;Edit;Vocabulary;

[Desktop Action Settings]
Name=设置
Exec={launcher} settings

[Desktop Action Edit]
Name=纠正上一条结果
Exec={launcher} edit

[Desktop Action Vocabulary]
Name=个人词库
Exec={launcher} vocabulary
''')
(desktop.parent/'qingyin-settings.desktop').write_text(f'''[Desktop Entry]
Type=Application
Name=青音设置
Comment=选择识别显卡、模型和文字输出方式
Exec={launcher} settings
Icon=audio-input-microphone
Categories=Settings;Audio;
Terminal=false
''')
niri=home/'.config/niri/config.kdl'
s=niri.read_text()
if 'Qingyin local dictation' not in s:
 stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
 shutil.copy2(niri,niri.with_name('config.kdl.bak-qingyin-'+stamp))
 s=s.replace('binds {',f'''binds {{
    // Qingyin local dictation: press once to start, once to stop.
    Mod+A repeat=false {{ spawn "{launcher}" "toggle"; }}
    Mod+Alt+A repeat=false {{ spawn "{launcher}" "edit"; }}
    Mod+Alt+Escape repeat=false {{ spawn "{launcher}" "cancel"; }}''',1)
 s+='''
// Qingyin preview must not steal the text field's focus.
window-rule {
    match app-id="^dev\\.qingyin\\.Panel$"
    open-floating true
    open-focused false
    default-column-width { fixed 460; }
    default-floating-position x=0 y=60 relative-to="top"
    opacity 1.0
}
'''.replace('app-id="^dev\\.qingyin\\.Panel$"','app-id=r#"^dev\\.qingyin\\.Panel$"#')
 niri.write_text(s)
 result=subprocess.run(['niri','validate'],capture_output=True,text=True)
 if result.returncode:
  niri.write_text(niri.with_name('config.kdl.bak-qingyin-'+stamp).read_text())
  raise RuntimeError(result.stderr)
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','disable','qingyin.service'],check=True,capture_output=True)
print('Installed per-user. On-demand: qingyin toggle / Win+A; no autostart.')
