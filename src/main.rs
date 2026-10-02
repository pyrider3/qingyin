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
struct Worker {
    child: Child,
    job: Option<Sender<PathBuf>>,
    events: Receiver<Event>,
    reader: Option<thread::JoinHandle<()>>,
}
impl Worker {
    fn new(home: &Path, cfg: &Config) -> io::Result<Self> {
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
                let mut line = String::new();
                output.read_line(&mut line)?;
                let v: Value = serde_json::from_str(&line).map_err(io::Error::other)?;
                if v["ready"] != true {
                    return Err(io::Error::other("本地模型未就绪"));
                }
                let _ = tx.send(Event::Ready);
                // A stop can arrive before loading finishes; queue the audio until ready.
                let path = jobs.recv().map_err(io::Error::other)?;
                writeln!(
                    input,
                    "{}",
                    json!({"path":path,"language":c.language,"beam_size":c.beam_size,"hotwords":c.hotwords})
                )?;
                input.flush()?;
                line.clear();
                output.read_line(&mut line)?;
                let v: Value = serde_json::from_str(&line).map_err(io::Error::other)?;
                if let Some(e) = v["error"].as_str() {
                    return Err(io::Error::other(e));
                }
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
fn commit(text: &str, rt: &Path) -> io::Result<bool> {
    let local = rt.join("commit.sock");
    let _ = fs::remove_file(&local);
    let sock = UnixDatagram::bind(&local)?;
    sock.set_read_timeout(Some(Duration::from_millis(800)))?;
    let result = (|| {
        sock.send_to(
            text.as_bytes(),
            rt.parent().unwrap().join("qingyin-fcitx.sock"),
        )?;
        let mut buf = [0; 32];
        let n = sock.recv(&mut buf)?;
        Ok(&buf[..n] == b"ok")
    })();
    let _ = fs::remove_file(local);
    result
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
        session.worker = Some(Worker::new(&home, &cfg)?);
        Ok(())
    })();
    if let Err(e) = startup {
        set_state(&state, &path, "error", &format!("启动失败：{e}"), "");
        notify(&format!("启动失败：{e}"));
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
                            set_state(&state, &path, "error", &e.to_string(), "");
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
                    let inserted = cfg.auto_input
                        && target.is_some()
                        && focused() == target
                        && commit(&text, &rt).unwrap_or(false);
                    let message = if inserted {
                        "已输入当前文本框 · 录音已删除"
                    } else {
                        "结果已保留，点击复制后粘贴 · 录音已删除"
                    };
                    set_state(&state, &path, "result", message, &text);
                    if !inserted && !cfg.show_panel {
                        notify(
                            "未能自动输入。结果已保留：运行 qingyin show 查看，或 qingyin copy 后粘贴。",
                        );
                    }
                }
                Err(e) => {
                    set_state(&state, &path, "error", &format!("识别失败：{e}"), "");
                    if !cfg.show_panel {
                        notify(&format!("识别失败：{e}"));
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
                set_state(&state, &path, "error", &e.to_string(), "");
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
fn main() -> io::Result<()> {
    let home = PathBuf::from(
        env::var("QINGYIN_HOME").unwrap_or_else(|_| env!("CARGO_MANIFEST_DIR").into()),
    );
    let cfg_path = PathBuf::from(env::var("HOME").unwrap()).join(".config/qingyin/config.json");
    let args: Vec<String> = env::args().collect();
    let cmd = args.get(1).map(String::as_str).unwrap_or("toggle");
    let reply = match cmd {
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
