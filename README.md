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
- 深色圆角 GTK4 控制中心：选择具体显卡 / CPU、本地模型、麦克风和文字输出方式。
- CUDA 显卡 UUID 固定与加载前显存检查；显卡不可用或显存不足时停止加载。
- CPU 本地补标点、简体输出，末尾不追加句号。
- 输入框上下文提示与个人词库自动学习，支持查看、删除学习记录。
- 可选悬浮预览默认关闭。

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

补标点模型使用 CPU，只有转写时加载，结束后释放；不自动换段；转写结果末尾省略中文句号，句中标点和问号保留。首次安装还需下载约 62 MB 的标点模型：

```bash
python3 download_punctuation.py
```

下载脚本校验固定 SHA256。CPU 标点不占用显存。标点引擎在独立子进程运行，隔离 Whisper 静音检测与标点引擎的 ONNX 运行库；取消识别时子进程随之退出。模型来自 [sherpa-onnx 的 CT-Transformer 发布页](https://github.com/k2-fsa/sherpa-onnx/releases/tag/punctuation-models)，权重不随仓库分发。缺少模型或标点处理失败时保留原转写，具体原因写入日志。

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

设置中的 `max_seconds` 默认 300，超时自动停止并转写。`show_panel` 默认 `false`；`punctuation` 默认 `true`，可在设置中关闭“自动补标点（不换段）”。查看结果、复制或打开设置不会加载识别模型。

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

已下载标点模型后，可用 `.venv/bin/python tests/punctuation.py --model` 验证 CPU 本地补标点和原文保护。

`python3 tests/punctuation_isolation.py` 验证取消后子进程退出；加入 `--model`（需要已安装 GPU 依赖和 JFK 样本）可验证真实 CUDA 识别和静音检测后连续三次 CPU 补标点，防止运行库冲突回归。


## 上下文与自动学习

默认开启完全本地的上下文辅助和自动学习：录音开始时从当前输入框获取光标附近最多 1024 字符，在本次识别中作为提示；不会上传或写入日志。输入后，在支持 fcitx5 surrounding-text 的应用中，只跟踪青音刚输入的那一段，观察你在原文本框里做的短词纠正，不必另外打开编辑器。

观察进程不加载语音或标点模型，单次观察约 60 秒，改变文本框焦点、整段删除、取消、关闭学习或超时后停止。词语修改稳定约 1.5 秒后提取候选；按回车前已完成的纠正也可确认，而发送后的清空、继续追加文字、标点修改和大段改写不会成为词语纠正。密码 / 敏感输入框不读取上下文、不学习。

首次纠正形成候选热词；同一规则在三次不同录音中确认后才自动替换。同一结果重复确认不重复计数。相同错误写法存在多个纠正目标时暂停自动替换；只做一次替换，不连锁改写。

部分应用不提供输入法周围文本，或只提供变化的文本片段；此时不会强行读取其他应用或屏幕。语音输入正常工作，自动学习可能无法启用。`Win+Alt+A` / `qingyin edit` 的手动纠正保留为备用入口。

`qingyin vocabulary`（或设置里的“查看 / 删除学习记录”）可以删除单条或清空全部记录。“上下文与自动学习”开关同时控制上下文提示、观察、学习热词与自动纠错。词库位于 `~/.local/share/qingyin/private/learning.json`，只保存短词对、次数及用于去重的录音时间标识；目录权限 0700，文件权限 0600，不上传，不保存整段文字或录音。

`python3 tests/context_learning.py` / `python3 tests/learning.py` 验证提取、确认和词库规则；在本地 Wayland 会话中可用 `GDK_BACKEND=wayland /usr/bin/python3 tests/surrounding_live.py` 验证真实 fcitx5/GTK 上下文、自动观察、隐私排除与清空停止（使用合成文本和临时词库）。

## CUDA 显卡与加载保护

青音在导入 CUDA 识别库前通过 `nvidia-smi` 检查显卡状态，默认选择总显存最大的可见显卡。可在 `~/.config/qingyin/config.json` 设置 `gpu_uuid` 固定物理显卡（使用 `nvidia-smi --query-gpu=uuid,name --format=csv` 查看），避免编号随外接显卡、虚拟机直通或重启改变。设置界面保存时保留该字段。

`gpu_min_free_mib` 默认 6144，最低也要求 6144 MiB 可用显存。指定显卡不存在、不在 `CUDA_VISIBLE_DEVICES` 允许范围、查询失败 / 超时或可用显存不足时，返回中文错误并停止加载，不自动落到另一张显卡。可在设置中手动选择 CPU，CPU 模式跳过 CUDA 检查。

这是加载前的余量检查，不是显存预留，其他进程仍可能在检查后占用显存；也不能修复驱动、PCIe、虚拟机直通或内核故障。驱动异常时应避免反复重试 CUDA。`python tests/gpu_policy.py` 使用模拟显卡验证保护，不执行真实 CUDA 模型加载。

## 图形控制中心

在应用启动器搜索 **青音设置**，或执行 `qingyin settings`。深色控制中心分为识别引擎、输出与学习、输入与快捷键三个页面，可选择 CPU / 具体 NVIDIA 显卡（按 UUID 保存）、已安装模型、解码精度、麦克风、识别语言、补标点、自动输入、自动学习和悬浮预览。刷新设备显示最新空闲显存。更改需要点击保存，下次录音生效；识别进行中禁止保存。缺失的已选设备不会悄悄切换，未安装的模型不能保存。模型和显存保护逻辑均不因打开界面而执行 CUDA 加载。

可用 `GDK_BACKEND=wayland /usr/bin/python3 tests/settings_ui.py` 在本地桌面验证设置映射与保存（临时配置、模拟显卡，不执行 CUDA）。

## 低占用模型

设置中的模型下载菜单提供多语言 tiny、base、small、medium、large-v3-turbo、large-v3，均可识别中文。tiny/base 更轻量但精度通常较低，small 可作为低占用起点，medium 在大小和精度之间折中。GPU 推理精度可选 `int8_float16`，用于降低显存占用；CPU 使用 INT8。实际显存与录音长度、模型及解码设置有关，不承诺固定占用值。

点击“下载所选模型”时联网，下载完成后从上方已安装列表选择并保存；识别仍完全离线。也可以执行 `.venv/bin/python download_model.py small`（或 base / medium / tiny）。下载固定到当次解析的仓库 revision，在临时目录验证模型文件齐全后安装；未完成的模型不会进入可选列表。此版本保留原有显存检查余量要求，小模型并不意味着可以取消显存保护，也不能修复驱动造成的整机故障。

## 模型常驻（可选）

在识别引擎页开启“模型常驻”并保存。默认关闭；开启后第一次录音仍需加载模型，识别完成后由独立 `qingyin-model.service` 保留语音模型，后续录音复用。CPU 保留内存，GPU 保留显存；标点仍在独立的按次子进程运行。不开机自动预载，也不在空闲时录音。

保存设置会释放当前常驻模型，下次录音重新按所选设备、模型及精度加载；关闭常驻并保存立即释放。取消录音 / 转写会中断当前模型任务并释放模型，下次重新加载。注销会话也停止模型服务。可手动 `systemctl --user stop qingyin-model.service` 释放。服务仅使用本地 Unix socket，延续离线与地址族限制；不会保存上次录音或文本框上下文。

常驻模式持续占用内存 / 显存，不是驱动崩溃修复措施。显卡状态检查只在模型加载前运行，不承诺持续显存监控。`python tests/resident.py` 用模拟识别进程验证复用、模型切换和取消释放，不进行真实 CUDA 加载。
