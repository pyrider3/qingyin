# 青音 Qingyin

为 **Arch Linux + niri + fcitx5** 制作的完全本地语音输入工具。按一次快捷键录音，再按一次转写，并将简体中文输入当前文本框。

**按需启动 · 本地识别 · 简体输出 · 默认无悬浮窗**

> 目前是面向 Linux 桌面的早期版本，主要在 Arch Linux、niri、PipeWire 和 NVIDIA CUDA 环境下验证。尚未提供通用安装包；Windows、macOS 和其他桌面环境未验证。

## 功能

- `Win+A` 开始录音，再按一次停止并转写；`Win+Alt+Esc` 取消。
- 录音与模型加载同时进行，短录音结束后可等待模型加载完成。
- 转写完成或取消后，控制器和模型进程退出，释放内存与显存；不随登录常驻。
- faster-whisper / CTranslate2 本地推理，支持 CUDA FP16 和 CPU INT8。
- 通过 OpenCC 将识别结果统一转换为简体中文，保留英文。
- fcitx5 插件向原应用提交文字；切换了焦点或输入框不兼容时保留结果供复制。
- 可选 GTK4 悬浮预览、麦克风选择和识别热词。悬浮窗默认关闭。

## 安装（Arch Linux）

需要正在运行的 niri、PipeWire、fcitx5 和 systemd 用户会话。GPU 模式还需要可用的 NVIDIA 驱动；没有 NVIDIA GPU 时，在设置中切换为 CPU。

将仓库克隆到准备长期保留的位置并进入目录。启动器会引用这个目录，不要在安装后移动或删除它。

### 1. 系统依赖

```bash
sudo pacman -S --needed base-devel rust python python-gobject python-cairo gtk4 \
  fcitx5 pipewire ffmpeg wl-clipboard uv
```

Rust 使用当前 stable；Python 推理环境已在 3.12 验证。GTK 界面使用系统 Python，与推理环境分开。

### 2. Python 推理环境

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.lock
```

锁定依赖包含 CUDA 库，下载和安装会占用数 GB。依赖和模型只在准备阶段需要联网。

### 3. 下载本地模型

默认使用完整版 large-v3：

```bash
.venv/bin/hf download Systran/faster-whisper-large-v3 \
  --local-dir "$HOME/.local/share/qingyin/models/large-v3"
```

模型权重约 3.1 GB。也可下载兼容的 faster-whisper 模型到同级目录，在青音设置里切换。模型不包含在本仓库中，其许可证以模型提供方说明为准。

### 4. 编译并安装

```bash
cargo build --release --locked
c++ -shared -fPIC -std=c++20 fcitx/qingyin.cpp -o fcitx/libqingyin.so \
  $(pkg-config --cflags --libs Fcitx5Core Fcitx5Utils)
python3 install.py
```

安装只写入当前用户目录：保留已有青音配置，并在修改 niri 配置前备份。默认添加 `Win+A` 和 `Win+Alt+Esc`；如已有相同快捷键，请先在 niri 配置里解决冲突。配置验证不通过时会恢复 niri 文件。

重新登录图形会话，让 fcitx5 加载插件。然后运行：

```bash
qingyin settings
```

选择识别设备和麦克风，再在文本框中按 `Win+A` 试用。每次使用都会重新加载模型，短句可能需要等待几秒；耗时与设备、模型和录音长度有关。

## 使用与设置

| 操作 | 快捷键或命令 |
| --- | --- |
| 开始 / 停止录音 | `Win+A` 或 `qingyin toggle` |
| 取消录音 / 转写 | `Win+Alt+Esc` 或 `qingyin cancel` |
| 打开设置 | `qingyin settings` |
| 查看最近结果 | `qingyin show` |
| 复制最近结果 | `qingyin copy` |
| 查看状态 | `qingyin status` |
| 清除最近结果 | `qingyin dismiss` |
| 查看日志 | `journalctl --user -u qingyin -n 40` |

配置文件为 `~/.config/qingyin/config.json`。新安装默认使用系统麦克风；可在设置中固定音源，避免蓝牙连接改变录音设备。热词适合填写人名、软件名、专业词，用逗号分隔；它是识别提示，不是强制替换。

设置中的 `max_seconds` 默认 300，超时自动停止并转写。`show_panel` 默认 `false`。查看结果、复制或打开设置不会加载识别模型。

## 离线与隐私

- 推理仅使用本地模型目录，开启 `local_files_only` 和 Hugging Face 离线模式。
- 安装的识别服务限制为 `AF_UNIX` / `AF_NETLINK` 地址族，不能直接建立互联网连接。
- 临时录音位于 `$XDG_RUNTIME_DIR/qingyin` 的私有目录，完成、取消或服务退出后删除。
- 不保存转写历史；最近一次文字保留在运行时 `state.json` 中，开始下一次录音或关闭结果时清空。
- 不使用云端 API、账号或密钥进行识别。
- 插件拒绝 fcitx5 标记为密码或敏感的输入框。此保护依赖应用正确设置输入上下文属性。

按需退出释放运行内存和显存，模型与依赖仍保留在硬盘。fcitx5 中的小型文字提交插件随输入法加载，不加载语音模型。

## 兼容性与限制

- 自动输入依赖应用的 fcitx5 支持。无法输入时用 `qingyin copy` 后手动粘贴。
- 自动提交前检查 niri 焦点是否仍在原窗口。全屏应用中的悬浮预览显示受合成器规则影响。
- 已验证 GPU 离线转写、内置麦克风录音 / 取消、静音、测试输入框的中文提交和密码框拒绝输入。
- 尚未获得覆盖口音、噪声和各应用的完整评测，不承诺特定识别准确率或所有应用兼容。

## 项目结构

```text
src/main.rs          Rust 控制器、按需生命周期、录音和本地 IPC
python/asr.py        faster-whisper 推理
python/normalize.py  本地繁简转换
python/panel.py      GTK4 预览和麦克风波形
python/settings.py   设置界面
fcitx/qingyin.cpp    fcitx5 文字提交插件
install.py           用户级安装及 niri 配置
uninstall.py         停用和移除入口
```

## 开发与测试

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo build --release --locked
python3 tests/lifecycle.py
.venv/bin/python tests/normalize.py
```

生命周期测试使用模拟麦克风和识别引擎，不录音、不访问网络、不向应用输入文字。覆盖模型加载中停止、加载 / 推理中取消、时长限制、连续快捷键、错误退出、结果保留和音频清理。

GPU 冒烟测试需要已安装的模型和测试音频。可从 [whisper.cpp 的 JFK 样本](https://github.com/ggml-org/whisper.cpp/blob/master/samples/jfk.wav) 获取 `tests/jfk.wav`，再运行 `python3 tests/asr_smoke.py`。音频不随仓库分发。

`tests/service_smoke.py` 验证本机已安装服务，临时覆盖该服务的录音命令以使用公开样本，并阻止向真实应用提交文字；只应在服务空闲时运行。

## 卸载

```bash
python3 uninstall.py
```

卸载移除启动入口、用户服务、fcitx5 插件配置和青音的 niri 规则；保留模型、配置和源码。重新登录后 fcitx5 停止加载插件。

## 致谢

基于 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[CTranslate2](https://github.com/OpenNMT/CTranslate2)、[OpenCC](https://github.com/BYVoid/OpenCC) 的 Python 实现、[fcitx5](https://github.com/fcitx/fcitx5)、[niri](https://github.com/YaLTeR/niri)、PipeWire 和 GTK4。
