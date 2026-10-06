use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    env, fs,
    io::{self, BufRead, BufReader, Write},
    os::unix::{
        fs::PermissionsExt,
        net::{UnixDatagram, UnixListener, UnixStream},
    },
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        Arc, Mutex,
        mpsc::{self, Receiver, Sender},
    },
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
#[derive(Clone, Deserialize, Serialize)]
struct Config {
    model: String,
    device: String,
    language: String,
    auto_input: bool,
    microphone: Option<String>,
    max_seconds: u64,
    #[serde(default)]
    show_panel: bool,
    #[serde(default = "default_compute")]
    compute_type: String,
    #[serde(default = "default_beam")]
    beam_size: u32,
    #[serde(default)]
    hotwords: String,
    #[serde(default = "default_punctuation")]
    punctuation: bool,
    #[serde(default = "default_punctuation")]
    learning: bool,
}
fn default_punctuation() -> bool {
    true
}
fn default_compute() -> String {
    "float16".into()
}
fn default_beam() -> u32 {
    5
}
#[derive(Clone, Serialize, Deserialize)]
struct State {
    phase: String,
    message: String,
    text: String,
    started: f64,
}
enum Event {
    Ready,
    Result(io::Result<String>),
}
fn chinese_error(error: &io::Error) -> String {
    let raw = error.to_string();
    eprintln!("青音错误详情：{raw}");
    let lower = raw.to_lowercase();
    if lower.contains("out of memory") || lower.contains("显存不足") {
        return "显存不足，无法加载或运行识别模型。请关闭其他占用显存的软件，或在青音设置中将识别设备改为 CPU。".into();
    }
    if lower.contains("cuda") || lower.contains("cudnn") || lower.contains("cublas") {
        return "显卡识别引擎不可用，请检查 NVIDIA 驱动，或在青音设置中改用 CPU。".into();
    }
    if error.kind() == io::ErrorKind::NotFound || lower.contains("no such file") {
        return "所需文件或程序不存在，请检查模型路径和青音安装是否完整。".into();
    }
    if error.kind() == io::ErrorKind::PermissionDenied || lower.contains("permission denied") {
        return "没有访问权限，请检查相关文件或设备的权限。".into();
    }
    if raw.chars().any(|c| ('\u{4e00}'..='\u{9fff}').contains(&c)) {
        return raw;
    }
    "程序运行遇到错误，请重试。详细原因已记录在青音日志中。".into()
}
fn worker_reply(output: &mut impl BufRead) -> io::Result<Value> {
    let mut line = String::new();
    if output.read_line(&mut line)? == 0 {
        return Err(io::Error::other(
            "识别进程意外退出，请检查模型和运行环境；详细原因见青音日志。",
        ));
    }
    let value: Value = serde_json::from_str(&line)
        .map_err(|_| io::Error::other("识别进程返回了无效数据，请重试；详细原因见青音日志。"))?;
    if let Some(error) = value["error"].as_str() {
        return Err(io::Error::other(error.to_owned()));
    }
    Ok(value)
}
struct Worker {
    child: Child,
    job: Option<Sender<PathBuf>>,
    events: Receiver<Event>,
    reader: Option<thread::JoinHandle<()>>,
}
impl Worker {
    fn new(home: &Path, cfg: &Config, context: String) -> io::Result<Self> {
        let mut child = Command::new(home.join(".venv/bin/python"))
            .arg(home.join("python/asr.py"))
            .arg(&cfg.model)
            .arg(&cfg.device)
            .arg(if cfg.device == "cpu" {
                "int8"
            } else {
                &cfg.compute_type
            })
            .env("HF_HUB_OFFLINE", "1")
            .env("TRANSFORMERS_OFFLINE", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()?;
        let mut input = child.stdin.take().unwrap();
        let mut output = BufReader::new(child.stdout.take().unwrap());
        let (job, jobs) = mpsc::channel::<PathBuf>();
        let (tx, events) = mpsc::channel();
        let c = cfg.clone();
        let reader = thread::spawn(move || {
            let result = (|| -> io::Result<String> {
                let v = worker_reply(&mut output)?;
                if v["ready"] != true {
                    return Err(io::Error::other("本地模型未就绪"));
                }
                let _ = tx.send(Event::Ready);
                // A stop can arrive before loading finishes; queue the audio until ready.
                let path = jobs.recv().map_err(io::Error::other)?;
                writeln!(
                    input,
                    "{}",
                    json!({"path":path,"language":c.language,"beam_size":c.beam_size,"hotwords":c.hotwords,"punctuation":c.punctuation,"learning":c.learning,"context":context})
                )?;
                input.flush()?;
                let v = worker_reply(&mut output)?;
                v["text"]
                    .as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| io::Error::other("识别结果格式错误"))
            })();
            let _ = tx.send(Event::Result(result));
        });
        Ok(Self {
            child,
            job: Some(job),
            events,
            reader: Some(reader),
        })
    }
    fn transcribe(&self, path: &Path) -> io::Result<()> {
        self.job
            .as_ref()
            .unwrap()
            .send(path.to_owned())
            .map_err(io::Error::other)
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        // Also interrupt loading or inference on cancellation, rather than waiting for it.
        let _ = self.child.kill();
        let _ = self.child.wait();
        self.job.take();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }
}
fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}
fn runtime() -> PathBuf {
    PathBuf::from(env::var("XDG_RUNTIME_DIR").expect("需要图形用户会话 / XDG_RUNTIME_DIR"))
        .join("qingyin")
}
fn state_write(path: &Path, state: &State) {
    let tmp = path.with_extension("tmp");
    if let Ok(data) = serde_json::to_vec(state) {
        let _ = fs::write(&tmp, data);
        let _ = fs::rename(tmp, path);
    }
}
fn set_state(s: &Arc<Mutex<State>>, path: &Path, phase: &str, message: &str, text: &str) {
    let mut state = s.lock().unwrap();
    state.phase = phase.into();
    state.message = message.into();
    state.text = text.into();
    if phase == "recording" {
        state.started = now();
    }
    state_write(path, &state);
}
fn focused() -> Option<u64> {
    let out = Command::new("niri")
        .args(["msg", "--json", "windows"])
        .output()
        .ok()?;
    let windows: Vec<Value> = serde_json::from_slice(&out.stdout).ok()?;
    windows
        .iter()
        .find(|w| w["is_focused"] == true)?
        .get("id")?
        .as_u64()
}
fn clipboard(text: &str) -> io::Result<()> {
    let exe = env::var("HOME").unwrap() + "/.local/bin/wl-copy";
    let mut c = Command::new(if Path::new(&exe).exists() {
        exe
    } else {
        "wl-copy".into()
    })
    .stdin(Stdio::piped())
    .spawn()?;
    c.stdin.take().unwrap().write_all(text.as_bytes())?;
    if !c.wait()?.success() {
        return Err(io::Error::other("复制失败"));
    }
    Ok(())
}
fn commit(text: &str, rt: &Path, event: Option<f64>) -> io::Result<()> {
    let local = rt.join("commit.sock");
    let _ = fs::remove_file(&local);
    let sock = UnixDatagram::bind(&local)?;
    sock.set_read_timeout(Some(Duration::from_millis(800)))?;
    let result = (|| {
        let payload = match event {
            Some(event) => format!("\u{1f}qingyin:learn:{event}\n{text}"),
            None => text.to_owned(),
        };
        sock.send_to(
            payload.as_bytes(),
            rt.parent().unwrap().join("qingyin-fcitx.sock"),
        )?;
        let mut buf = [0; 32];
        let n = sock.recv(&mut buf)?;
        match &buf[..n] {
            b"ok" => Ok(()),
            b"sensitive" => Err(io::Error::other("当前是密码或敏感输入框，已跳过自动输入")),
            _ => Err(io::Error::other("输入法未连接当前文本框，请先点击输入框")),
        }
    })();
    let _ = fs::remove_file(local);
    result
}
fn context_snapshot(rt: &Path) -> io::Result<Value> {
    let path = rt.join("context.sock");
    let _ = fs::remove_file(&path);
    let sock = UnixDatagram::bind(&path)?;
    sock.set_read_timeout(Some(Duration::from_millis(250)))?;
    let result = (|| {
        sock.send_to(
            b"\x1fqingyin:context",
            rt.parent().unwrap().join("qingyin-fcitx.sock"),
        )?;
        let mut buffer = [0; 16384];
        let n = sock.recv(&mut buffer)?;
        let value: Value = serde_json::from_slice(&buffer[..n]).map_err(io::Error::other)?;
        Ok(value)
    })();
    let _ = fs::remove_file(path);
    result
}
fn start_context_watch(home: &Path) {
    // Separate bounded service: ASR still exits immediately after recognition.
    let _ = Command::new("systemd-run")
        .args([
            "--user",
            "--collect",
            "--quiet",
            "--unit=qingyin-learning",
            "--service-type=exec",
            "--property=RuntimeMaxSec=75",
            "--property=RestrictAddressFamilies=AF_UNIX AF_NETLINK",
            "/usr/bin/python3",
        ])
        .arg(home.join("python/context_watch.py"))
        .output();
}
fn cancel_context_watch() {
    if let Ok(socket) = UnixDatagram::unbound() {
        let _ = socket.send_to(
            b"\x1fqingyin:cancel-watch",
            runtime().parent().unwrap().join("qingyin-fcitx.sock"),
        );
    }
    let _ = Command::new("systemctl")
        .args(["--user", "stop", "qingyin-learning.service"])
        .output();
}
fn stop_record(child: &mut Child) {
    let _ = Command::new("kill")
        .args(["-INT", &child.id().to_string()])
        .status();
    for _ in 0..40 {
        if child.try_wait().ok().flatten().is_some() {
            return;
        }
        thread::sleep(Duration::from_millis(25));
    }
    let _ = child.kill();
    let _ = child.wait();
}
fn request(cmd: &str) -> io::Result<String> {
    let mut sock = UnixStream::connect(runtime().join("control.sock"))?;
    sock.set_read_timeout(Some(Duration::from_secs(3)))?;
    writeln!(sock, "{cmd}")?;
    let mut line = String::new();
    if BufReader::new(sock).read_line(&mut line)? == 0 {
        return Err(io::Error::new(
            io::ErrorKind::UnexpectedEof,
            "控制进程已退出",
        ));
    }
    Ok(line)
}
struct Session {
    recorder: Option<Child>,
    worker: Option<Worker>,
    rt: PathBuf,
}
impl Drop for Session {
    fn drop(&mut self) {
        if let Some(mut recorder) = self.recorder.take() {
            stop_record(&mut recorder);
        }
        self.worker.take();
        let _ = fs::remove_file(self.rt.join("recording.wav"));
        let _ = fs::remove_file(self.rt.join("control.sock"));
    }
}
fn start_record(cfg: &Config, audio: &Path) -> io::Result<Child> {
    let _ = fs::remove_file(audio);
    let mut command = Command::new("pw-record");
    command.args([
        "--rate",
        "16000",
        "--channels",
        "1",
        "--format",
        "s16",
        "--media-role",
        "Communication",
    ]);
    if let Some(m) = &cfg.microphone {
        command.args(["--target", m]);
    }
    let mut child = command.arg(audio).stderr(Stdio::inherit()).spawn()?;
    thread::sleep(Duration::from_millis(150));
    if child.try_wait()?.is_some() {
        return Err(io::Error::other("麦克风录音启动失败，请检查音频设备"));
    }
    Ok(child)
}
fn stop_and_transcribe(
    session: &mut Session,
    state: &Arc<Mutex<State>>,
    path: &Path,
) -> io::Result<()> {
    if let Some(mut child) = session.recorder.take() {
        stop_record(&mut child);
    }
    set_state(
        state,
        path,
        "transcribing",
        "正在本机识别（模型加载未完成时会稍等），不上传录音",
        "",
    );
    session
        .worker
        .as_ref()
        .ok_or_else(|| io::Error::other("模型未启动"))?
        .transcribe(&session.rt.join("recording.wav"))
}
fn notify(message: &str) {
    let _ = Command::new("notify-send").args(["青音", message]).status();
}
fn show_panel(home: &Path) -> io::Result<String> {
    let state = saved_state();
    if state.phase == "idle" {
        return Ok("当前没有转写结果".into());
    }
    // A separate, transient UI service can display the retained result after the core exits.
    let active = Command::new("systemctl")
        .args(["--user", "is-active", "--quiet", "qingyin-panel.service"])
        .status()?;
    if !active.success() {
        let status = Command::new("systemd-run")
            .args([
                "--user",
                "--collect",
                "--quiet",
                "--unit=qingyin-panel",
                "--setenv=GDK_BACKEND=wayland",
            ])
            .arg("/usr/bin/python3")
            .arg(home.join("python/panel.py"))
            .arg(runtime().join("state.json"))
            .arg(env::current_exe()?)
            .arg("--once")
            .status()?;
        if !status.success() {
            return Err(io::Error::other("预览启动失败"));
        }
    }
    Ok("已显示预览".into())
}
fn idle_state() -> State {
    State {
        phase: "idle".into(),
        message: "按 Win+A 开始 · 按需启动".into(),
        text: String::new(),
        started: 0.0,
    }
}
fn saved_state() -> State {
    fs::read(runtime().join("state.json"))
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or_else(idle_state)
}
fn status_json(state: &State, running: bool) -> String {
    let mut v = serde_json::to_value(state).unwrap();
    v["running"] = json!(running);
    v.to_string()
}
fn daemon(home: PathBuf, cfg: Config) -> io::Result<()> {
    let rt = runtime();
    fs::create_dir_all(&rt)?;
    fs::set_permissions(&rt, fs::Permissions::from_mode(0o700))?;
    let socket = rt.join("control.sock");
    if UnixStream::connect(&socket).is_ok() {
        return Ok(());
    }
    let _ = fs::remove_file(&socket);
    let listener = UnixListener::bind(&socket)?;
    listener.set_nonblocking(true)?;
    let mut session = Session {
        recorder: None,
        worker: None,
        rt: rt.clone(),
    };
    let path = rt.join("state.json");
    let state = Arc::new(Mutex::new(idle_state()));
    let target = focused();
    let mut target_context = String::new();
    // Record before model initialization so speech at the first key press is preserved.
    let startup = (|| -> io::Result<()> {
        session.recorder = Some(start_record(&cfg, &rt.join("recording.wav"))?);
        set_state(
            &state,
            &path,
            "recording",
            "再按 Win+A 停止 · Win+Alt+Esc 取消",
            "",
        );
        let context = if cfg.learning {
            let snapshot = context_snapshot(&rt).unwrap_or(Value::Null);
            target_context = snapshot["token"].as_str().unwrap_or("").to_owned();
            snapshot["text"].as_str().unwrap_or("").to_owned()
        } else {
            String::new()
        };
        session.worker = Some(Worker::new(&home, &cfg, context)?);
        Ok(())
    })();
    if let Err(e) = startup {
        set_state(
            &state,
            &path,
            "error",
            &format!("启动失败：{}", chinese_error(&e)),
            "",
        );
        notify(&format!("启动失败：{}", chinese_error(&e)));
        return Ok(());
    }
    if cfg.show_panel {
        let _ = show_panel(&home);
    }
    loop {
        match listener.accept() {
            Ok((mut stream, _)) => {
                stream.set_read_timeout(Some(Duration::from_secs(1)))?;
                let mut cmd = String::new();
                if BufReader::new(&stream).read_line(&mut cmd).is_err() {
                    continue;
                }
                let phase = state.lock().unwrap().phase.clone();
                let mut exit = false;
                let reply = match cmd.trim() {
                    "status" => status_json(&state.lock().unwrap(), true),
                    "toggle" if session.recorder.is_some() => {
                        if let Err(e) = stop_and_transcribe(&mut session, &state, &path) {
                            set_state(&state, &path, "error", &chinese_error(&e), "");
                            exit = true;
                        }
                        "正在转写".into()
                    }
                    "toggle" => "正在转写，请稍候（可取消）".into(),
                    "cancel" | "quit" => {
                        set_state(&state, &path, "idle", "已取消，资源已释放", "");
                        exit = true;
                        "已取消".into()
                    }
                    "dismiss" => {
                        if matches!(phase.as_str(), "result" | "error") {
                            set_state(&state, &path, "idle", "", "");
                        }
                        "ok".into()
                    }
                    _ => "命令：toggle / cancel / copy / show / dismiss / status / quit".into(),
                };
                let _ = writeln!(stream, "{reply}");
                if exit {
                    return Ok(());
                }
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => (),
            Err(e) => return Err(e),
        }
        let event = session.worker.as_ref().unwrap().events.try_recv().ok();
        if let Some(Event::Result(result)) = event {
            // Release the model and CUDA allocations before delivering the text.
            session.worker.take();
            if let Some(mut recorder) = session.recorder.take() {
                stop_record(&mut recorder);
            }
            let _ = fs::remove_file(rt.join("recording.wav"));
            match result {
                Ok(text) if text.is_empty() => {
                    set_state(&state, &path, "result", "没有检测到语音，请检查麦克风", "");
                    if !cfg.show_panel {
                        notify("没有检测到语音，请检查麦克风。");
                    }
                }
                Ok(text) => {
                    let delivery = if !cfg.auto_input {
                        Err("设置中已关闭自动输入".to_owned())
                    } else if target.is_none() || focused() != target {
                        Err("窗口焦点已改变，为避免输入到其他窗口，已保留结果".to_owned())
                    } else {
                        commit(
                            &text,
                            &rt,
                            cfg.learning.then(|| state.lock().unwrap().started),
                        )
                        .map_err(|e| {
                            eprintln!("自动输入失败：{e}");
                            match e.kind() {
                                io::ErrorKind::NotFound | io::ErrorKind::ConnectionRefused => {
                                    "输入法连接不可用，请重启 fcitx5 后重试".to_owned()
                                }
                                io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut => {
                                    "输入法没有及时响应，请重试".to_owned()
                                }
                                _ => chinese_error(&e),
                            }
                        })
                    };
                    let message = match delivery {
                        Ok(()) => {
                            if cfg.learning {
                                start_context_watch(&home);
                            }
                            "已输入当前文本框 · 录音已删除".to_owned()
                        }
                        Err(reason) => {
                            eprintln!("青音自动输入：{reason}");
                            let message =
                                format!("{reason}。结果已保留，运行 qingyin copy 后粘贴。");
                            if !cfg.show_panel {
                                notify(&message);
                            }
                            message
                        }
                    };
                    set_state(&state, &path, "result", &message, &text);
                }
                Err(e) => {
                    set_state(
                        &state,
                        &path,
                        "error",
                        &format!("识别失败：{}", chinese_error(&e)),
                        "",
                    );
                    if !cfg.show_panel {
                        notify(&format!("识别失败：{}", chinese_error(&e)));
                    }
                }
            }
            return Ok(());
        }
        if let Some(recorder) = session.recorder.as_mut() {
            if recorder.try_wait()?.is_some() {
                set_state(&state, &path, "error", "麦克风录音意外停止，请检查设备", "");
                notify("麦克风录音意外停止，请检查设备。");
                return Ok(());
            }
            let expired = now() - state.lock().unwrap().started >= cfg.max_seconds as f64;
            if expired && let Err(e) = stop_and_transcribe(&mut session, &state, &path) {
                set_state(&state, &path, "error", &chinese_error(&e), "");
                return Ok(());
            }
        }
        thread::sleep(Duration::from_millis(25));
    }
}
fn toggle() -> io::Result<String> {
    let rt = runtime();
    fs::create_dir_all(&rt)?;
    fs::set_permissions(&rt, fs::Permissions::from_mode(0o700))?;
    // Serialize rapid key presses while systemd is starting the first session.
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(rt.join("launch.lock"))?;
    lock.lock()?;
    if let Ok(reply) = request("toggle") {
        return Ok(reply);
    }
    let result = Command::new("systemctl")
        .args(["--user", "start", "qingyin.service"])
        .output()?;
    if !result.status.success() {
        return Err(io::Error::other(
            String::from_utf8_lossy(&result.stderr).to_string(),
        ));
    }
    for _ in 0..200 {
        if let Ok(reply) = request("status") {
            let v: Value = serde_json::from_str(&reply).map_err(io::Error::other)?;
            return Ok(if v["phase"] == "recording" {
                "开始录音（按需启动）".into()
            } else {
                reply
            });
        }
        thread::sleep(Duration::from_millis(25));
    }
    Err(io::Error::other(
        "启动超时，请查看 journalctl --user -u qingyin",
    ))
}
fn run() -> io::Result<()> {
    let home = PathBuf::from(
        env::var("QINGYIN_HOME").unwrap_or_else(|_| env!("CARGO_MANIFEST_DIR").into()),
    );
    let cfg_path = PathBuf::from(env::var("HOME").unwrap()).join(".config/qingyin/config.json");
    let args: Vec<String> = env::args().collect();
    let cmd = args.get(1).map(String::as_str).unwrap_or("toggle");
    if matches!(cmd, "cancel" | "quit") {
        cancel_context_watch();
    }
    let reply = match cmd {
        "edit" | "vocabulary" => {
            let mut editor = Command::new("/usr/bin/python3");
            editor
                .env("GDK_BACKEND", "wayland")
                .arg(home.join("python/editor.py"));
            if cmd == "vocabulary" {
                editor.arg("--vocabulary");
            }
            editor.spawn()?;
            "已打开纠正 / 个人词库窗口".into()
        }
        "settings" => {
            Command::new("/usr/bin/python3")
                .env("GDK_BACKEND", "wayland")
                .arg(home.join("python/settings.py"))
                .spawn()?;
            "已打开设置".into()
        }
        "daemon" | "session" => {
            let cfg: Config =
                serde_json::from_slice(&fs::read(cfg_path)?).map_err(io::Error::other)?;
            return daemon(home, cfg);
        }
        "cleanup" => {
            let _ = fs::remove_file(runtime().join("recording.wav"));
            let _ = fs::remove_file(runtime().join("control.sock"));
            let state = saved_state();
            if matches!(
                state.phase.as_str(),
                "recording" | "loading" | "transcribing"
            ) {
                state_write(&runtime().join("state.json"), &idle_state());
            }
            "已清理".into()
        }
        "toggle" => toggle()?,
        "show" => show_panel(&home)?,
        "copy" => {
            let text = saved_state().text;
            if text.is_empty() {
                "没有可复制的文字".into()
            } else {
                clipboard(&text)?;
                "已复制".into()
            }
        }
        "status" => request("status").unwrap_or_else(|_| {
            let mut state = saved_state();
            if matches!(
                state.phase.as_str(),
                "recording" | "loading" | "transcribing"
            ) {
                state = idle_state();
            }
            status_json(&state, false)
        }),
        "cancel" | "quit" | "dismiss" => request(cmd).unwrap_or_else(|_| {
            let _ = fs::create_dir_all(runtime());
            state_write(&runtime().join("state.json"), &idle_state());
            "已关闭".into()
        }),
        _ => return Err(io::Error::other("未知命令")),
    };
    println!("{}", reply.trim());
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("青音：{}", chinese_error(&error));
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn model_startup_errors_reach_chinese_message() {
        let mut reply = io::Cursor::new(b"{\"error\":\"CUDA failed with error out of memory\"}\n");
        let error = worker_reply(&mut reply).unwrap_err();
        assert!(chinese_error(&error).starts_with("显存不足"));
    }
    #[test]
    fn exited_worker_and_bad_json_are_readable() {
        for bytes in [b"".as_slice(), b"invalid\n".as_slice()] {
            let error = worker_reply(&mut io::Cursor::new(bytes)).unwrap_err();
            assert!(chinese_error(&error).contains("识别进程"));
        }
        assert!(chinese_error(&io::Error::other("unknown backend exception")).contains("日志"));
    }
}
