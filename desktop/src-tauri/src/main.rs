#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Deserialize;
use std::{collections::BTreeMap, fs::{self, File, OpenOptions}, io::{Read, Write}, net::{TcpStream, SocketAddr}, os::unix::{io::AsRawFd, process::CommandExt}, path::{Path, PathBuf}, process::{Child, Command, Stdio}, sync::{atomic::{AtomicBool, AtomicU16, Ordering}, Mutex}, thread, time::{Duration, Instant}};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder, webview::{DownloadEvent, NewWindowResponse}};
use tauri_plugin_dialog::DialogExt;

struct DesktopState {
    child: Mutex<Option<Child>>,
    error: Mutex<Option<String>>,
    closing: AtomicBool,
    exit_authorized: AtomicBool,
    data: PathBuf,
    port: AtomicU16,
    _lock: File,
}

impl DesktopState {
    fn stop(&self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(mut process) = child.take() {
                let group = -(process.id() as i32);
                // Only signal the process group created for this specific sidecar.
                unsafe { libc::kill(group, libc::SIGTERM); }
                let deadline = Instant::now() + Duration::from_secs(5);
                while Instant::now() < deadline {
                    if process.try_wait().ok().flatten().is_some() { break; }
                    thread::sleep(Duration::from_millis(50));
                }
                // Also reap descendants left in the original group after its leader exits.
                unsafe { libc::kill(group, libc::SIGKILL); }
                let _ = process.wait();
            }
        }
        let _ = fs::remove_file(self.data.join("desktop-ready.json"));
    }
}

fn data_dir() -> Result<PathBuf, String> {
    if let Some(value) = std::env::var_os("GUIZANG_DATA").filter(|s| !s.is_empty()) {
        return Ok(PathBuf::from(value));
    }
    let home = std::env::var_os("HOME").ok_or("无法确定用户目录")?;
    Ok(PathBuf::from(home).join("Library/Application Support/归藏"))
}

fn log(data: &Path, message: &str) {
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(data.join("logs/desktop.log")) {
        let _ = writeln!(file, "[{:?}] {}", std::time::SystemTime::now(), message);
    }
}

#[derive(Default, serde::Serialize)]
struct Migration {
    copied_files: u64,
    copied_bytes: u64,
    skipped_existing: u64,
    skipped_symlinks: Vec<String>,
    errors: Vec<String>,
}

fn copy_new_file(source: &Path, destination: &Path) -> std::io::Result<u64> {
    let temporary = destination.parent().unwrap().join(format!(".guizang-import-{}-{}", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
    let result = (|| {
        let mut output = OpenOptions::new().write(true).create_new(true).open(&temporary)?;
        let mut input = File::open(source)?;
        let count = std::io::copy(&mut input, &mut output)?;
        output.sync_all()?;
        drop(output);
        // Linking commits the complete file atomically and refuses to replace a conflict.
        fs::hard_link(&temporary, destination)?;
        Ok(count)
    })();
    let _ = fs::remove_file(temporary);
    result
}

fn copy_missing_tree(source: &Path, destination: &Path, report: &mut Migration) {
    let entries = match fs::read_dir(source) {
        Ok(entries) => entries,
        Err(error) => { report.errors.push(format!("{}: {error}", source.display())); return; }
    };
    for entry in entries {
        let entry = match entry { Ok(entry) => entry, Err(error) => { report.errors.push(error.to_string()); continue; } };
        let from = entry.path();
        let target = destination.join(entry.file_name());
        let kind = match entry.file_type() { Ok(kind) => kind, Err(error) => { report.errors.push(format!("{}: {error}", from.display())); continue; } };
        if kind.is_symlink() {
            // Never follow a link outside the old library or accidentally introduce a loop.
            report.skipped_symlinks.push(from.to_string_lossy().into_owned());
        } else if kind.is_dir() {
            if target.exists() && !target.is_dir() { report.skipped_existing += 1; continue; }
            match fs::create_dir_all(&target) {
                Ok(()) => copy_missing_tree(&from, &target, report),
                Err(error) => report.errors.push(format!("{}: {error}", target.display())),
            }
        } else if kind.is_file() {
            // An interrupted import must not leave a truncated "existing" book on the next run.
            if target.exists() { report.skipped_existing += 1; continue; }
            match copy_new_file(&from, &target) {
                Ok(bytes) => { report.copied_files += 1; report.copied_bytes += bytes; }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => report.skipped_existing += 1,
                Err(error) => report.errors.push(format!("{}: {error}", target.display())),
            }
        }
    }
}

fn migrate_legacy_books(data: &Path, source: &Path) -> Result<(), String> {
    let marker = data.join("legacy-documents-import.done");
    if marker.exists() { return Ok(()); }
    let destination = data.join("output");
    let mut report = Migration::default();
    match source.try_exists() {
        Ok(true) => copy_missing_tree(source, &destination, &mut report),
        Ok(false) => (),
        Err(error) => report.errors.push(format!("{}: {error}", source.display())),
    }
    let manifest = serde_json::json!({"source": source, "destination": destination, "report": report});
    fs::write(data.join("legacy-documents-import.json"), serde_json::to_vec_pretty(&manifest).unwrap()).map_err(|e| e.to_string())?;
    if report.errors.is_empty() {
        fs::write(marker, b"Existing books were copied once; source files and destination conflicts were left intact.\n").map_err(|e| e.to_string())?;
    }
    log(data, &format!("legacy library import: {} files, {} bytes, {} conflicts, {} errors", report.copied_files, report.copied_bytes, report.skipped_existing, report.errors.len()));
    if report.errors.is_empty() { Ok(()) } else { Err(format!("旧书库部分文件尚未导入，详情见 {}", data.join("legacy-documents-import.json").display())) }
}

fn backend_origin(url: &tauri::Url, port: u16) -> bool {
    port > 0 && url.scheme() == "http" && url.host_str() == Some("127.0.0.1") && url.port() == Some(port)
}

fn trusted(window: &tauri::WebviewWindow, state: &DesktopState) -> Result<(), String> {
    let url = window.url().map_err(|e| e.to_string())?;
    if backend_origin(&url, state.port.load(Ordering::Acquire)) {
        Ok(())
    } else { Err("桌面功能只允许归藏自己的页面调用".into()) }
}

#[tauri::command]
async fn pick_export_dir(window: tauri::WebviewWindow, app: tauri::AppHandle, state: tauri::State<'_, DesktopState>) -> Result<Option<String>, String> {
    trusted(&window, &state)?;
    // The blocking dialog is intentionally off the main event loop.
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog().file().set_title("以后导出的文件存到这里").blocking_pick_folder()
            .map(|file| file.into_path().map(|p| p.to_string_lossy().into_owned()).map_err(|e| e.to_string())).transpose()
    }).await.map_err(|e| e.to_string())?
}

#[tauri::command]
fn save_web_state(window: tauri::WebviewWindow, state: tauri::State<'_, DesktopState>, values: BTreeMap<String, String>) -> Result<(), String> {
    trusted(&window, &state)?;
    let bytes = serde_json::to_vec(&values).map_err(|e| e.to_string())?;
    if bytes.len() > 10 * 1024 * 1024 { return Err("页面设置超过 10 MB，无法保存".into()); }
    let temp = state.data.join("desktop-web-state.json.tmp");
    fs::write(&temp, bytes).and_then(|_| fs::rename(&temp, state.data.join("desktop-web-state.json"))).map_err(|e| e.to_string())
}

#[tauri::command]
fn finish_close(window: tauri::WebviewWindow, app: tauri::AppHandle, state: tauri::State<'_, DesktopState>) -> Result<(), String> {
    trusted(&window, &state)?;
    state.exit_authorized.store(true, Ordering::Release);
    app.exit(0);
    Ok(())
}

fn request_close(app: &tauri::AppHandle) {
    let state = app.state::<DesktopState>();
    if state.closing.swap(true, Ordering::AcqRel) { return; }
    let window = app.get_webview_window("main");
    let can_flush = window.as_ref().map(|w| trusted(w, &state).is_ok()).unwrap_or(false);
    if !can_flush {
        state.exit_authorized.store(true, Ordering::Release);
        app.exit(0);
        return;
    }
    if let Some(window) = window {
        let _ = window.eval("if(window.gzDesktopClose){window.gzDesktopClose()}else{window.__TAURI_INTERNALS__.invoke('finish_close')}");
    }
    let handle = app.clone();
    thread::spawn(move || {
        // A crashed WebKit process must never trap the application open.
        thread::sleep(Duration::from_secs(3));
        let state = handle.state::<DesktopState>();
        if !state.exit_authorized.swap(true, Ordering::AcqRel) {
            log(&state.data, "web state flush timed out; closing with last saved state");
            handle.exit(0);
        }
    });
}

fn web_state_script(data: &Path) -> String {
    let values: BTreeMap<String, String> = fs::read(data.join("desktop-web-state.json")).ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok()).unwrap_or_default();
    let session = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos().to_string();
    include_str!("../../frontend/bridge.js").replace("__GUIZANG_SESSION__", &session).replace("__GUIZANG_WEB_STATE__", &serde_json::to_string(&values).unwrap())
}

fn writable(path: &Path) -> bool {
    let probe = path.join(format!(".guizang-probe-{}", std::process::id()));
    if let Ok(mut file) = OpenOptions::new().write(true).create_new(true).open(&probe) {
        let success = file.write_all(b"ok").is_ok();
        drop(file); let _ = fs::remove_file(probe); success
    } else { false }
}

fn export_destination(data: &Path, suggested: &Path) -> PathBuf {
    let chosen = fs::read(data.join("cache/config.json")).ok()
        .and_then(|s| serde_json::from_slice::<serde_json::Value>(&s).ok())
        .and_then(|v| v.get("export_dir").and_then(|v| v.as_str()).map(PathBuf::from))
        .filter(|p| p.is_dir() && writable(p));
    let downloads = std::env::var_os("HOME").map(PathBuf::from).map(|p| p.join("Downloads"));
    let base = chosen.or_else(|| downloads.filter(|p| p.is_dir() && writable(p))).unwrap_or_else(|| data.join("downloads"));
    let _ = fs::create_dir_all(&base);
    let name = suggested.file_name().unwrap_or_else(|| std::ffi::OsStr::new("归藏导出")).to_string_lossy().replace(['/', ':'], "-");
    let name = if name.is_empty() || name == "." || name == ".." { "归藏导出" } else { &name };
    let destination = base.join(name);
    if !destination.exists() { return destination; }
    let stem = destination.file_stem().unwrap_or_default().to_string_lossy();
    let extension = destination.extension().map(|x| format!(".{}", x.to_string_lossy())).unwrap_or_default();
    for n in 2.. {
        let candidate = base.join(format!("{} ({}){}", stem, n, extension));
        if !candidate.exists() { return candidate; }
    }
    unreachable!()
}

fn open_external(url: &tauri::Url) {
    if matches!(url.scheme(), "https" | "http") {
        // Pass the URL as an argument, never through a shell.
        let _ = Command::new("/usr/bin/open").arg(url.as_str()).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn();
    }
}

#[derive(Deserialize)]
struct Ready { port: u16, pid: u32 }

fn probe(port: u16) -> bool {
    let address: SocketAddr = format!("127.0.0.1:{port}").parse().unwrap();
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(300)) else { return false; };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    if stream.write_all(format!("GET /api/state HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n").as_bytes()).is_err() { return false; }
    let mut prefix = [0u8; 32];
    stream.read(&mut prefix).ok().filter(|n| *n > 0).map(|n| String::from_utf8_lossy(&prefix[..n]).contains(" 200 ")).unwrap_or(false)
}

fn startup_error(app: &tauri::AppHandle, message: &str) {
    let state = app.state::<DesktopState>();
    let message = format!("{}\n\n排障日志：{}", message, state.data.join("logs/backend.log").display());
    log(&state.data, &message);
    if let Ok(mut error) = state.error.lock() { *error = Some(message.clone()); }
    if let Some(window) = app.get_webview_window("main") {
        // Show both startup errors and later backend crashes in the same visible window.
        let script = format!("if(window.gzStartupError){{window.gzStartupError({0})}}else{{document.body.replaceChildren();const p=document.createElement('pre');p.style='white-space:pre-wrap;padding:40px';p.textContent={0};document.body.append(p)}}", serde_json::to_string(&message).unwrap());
        let _ = window.eval(&script);
    }
}

fn start_backend(app: tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<DesktopState>();
    let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
    let executable = resources.join("backend/guizang-backend");
    if !executable.is_file() { return Err(format!("应用缺少内置后端：{}", executable.display())); }
    let ready_file = state.data.join("desktop-ready.json");
    let _ = fs::remove_file(&ready_file);
    let output = OpenOptions::new().append(true).create(true).open(state.data.join("logs/backend.log")).map_err(|e| e.to_string())?;
    let stderr = output.try_clone().map_err(|e| e.to_string())?;
    let media = resources.join("media");
    let mut command = Command::new(&executable);
    command.args(["--desktop-server", "--port", "0", "--parent-pid", &std::process::id().to_string(), "--ready-file"])
        .arg(&ready_file).current_dir(&state.data)
        .env("GUIZANG_DATA", &state.data).env("GUIZANG_BOOKS", state.data.join("output")).env("GUIZANG_OUTPUT", state.data.join("output"))
        .env("PLAYWRIGHT_BROWSERS_PATH", resources.join("browsers"))
        .env("GUIZANG_FFMPEG", media.join("ffmpeg")).env("GUIZANG_FFPROBE", media.join("ffprobe"))
        .env("PATH", format!("{}:/usr/bin:/bin:/usr/sbin:/sbin", media.display()))
        .env("PYTHONDONTWRITEBYTECODE", "1").env("PYTHONUNBUFFERED", "1")
        .env_remove("PYTHONPATH").env_remove("PYTHONHOME").env_remove("VIRTUAL_ENV")
        .stdin(Stdio::null()).stdout(output).stderr(stderr);
    unsafe { command.pre_exec(|| { if libc::setpgid(0, 0) == -1 { Err(std::io::Error::last_os_error()) } else { Ok(()) } }); }
    let child = command.spawn().map_err(|e| format!("内置后端启动失败：{e}"))?;
    let pid = child.id();
    log(&state.data, &format!("backend started pid={pid}, resources={}", resources.display()));
    *state.child.lock().map_err(|e| e.to_string())? = Some(child);
    let deadline = Instant::now() + Duration::from_secs(90);
    loop {
        if let Some(status) = state.child.lock().map_err(|e| e.to_string())?.as_mut().and_then(|c| c.try_wait().ok().flatten()) {
            return Err(format!("内置后端启动时退出：{status}"));
        }
        if let Some(ready) = fs::read(&ready_file).ok().and_then(|b| serde_json::from_slice::<Ready>(&b).ok()) {
            if ready.pid == pid && ready.port > 0 && probe(ready.port) {
                state.port.store(ready.port, Ordering::Release);
                let window = app.get_webview_window("main").ok_or("窗口已关闭")?;
                window.navigate(format!("http://127.0.0.1:{}/", ready.port).parse().unwrap()).map_err(|e| e.to_string())?;
                log(&state.data, &format!("ready http://127.0.0.1:{}/", ready.port));
                break;
            }
        }
        if Instant::now() >= deadline { state.stop(); return Err("内置后端启动超时（90 秒）".into()); }
        thread::sleep(Duration::from_millis(100));
    }
    // Do not leave a stale apparently working interface after a backend crash.
    loop {
        thread::sleep(Duration::from_secs(1));
        let status = { let mut lock = state.child.lock().map_err(|e| e.to_string())?;
            match lock.as_mut() { Some(child) => child.try_wait().map_err(|e| e.to_string())?, None => return Ok(()) }
        };
        if let Some(status) = status { return Err(format!("内置后端意外退出：{status}。请重新打开归藏。")); }
    }
}

fn main() {
    let migrate_legacy = std::env::var_os("GUIZANG_DATA").filter(|s| !s.is_empty()).is_none();
    let data = data_dir().unwrap_or_else(|message| { eprintln!("{message}"); std::process::exit(1) });
    if let Err(error) = fs::create_dir_all(data.join("logs")).and_then(|_| fs::create_dir_all(data.join("output"))) {
        eprintln!("无法创建应用数据目录：{error}"); std::process::exit(1);
    }
    let lock = OpenOptions::new().read(true).write(true).create(true).open(data.join("desktop.lock")).expect("应用目录不可写");
    if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        // The existing instance owns the backend. Never attach to or kill an unrelated service.
        log(&data, "another desktop instance already owns this data directory");
        return;
    }
    let script = web_state_script(&data);
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(DesktopState { child: Mutex::new(None), error: Mutex::new(None), closing: AtomicBool::new(false), exit_authorized: AtomicBool::new(false), data, port: AtomicU16::new(0), _lock: lock })
        .invoke_handler(tauri::generate_handler![pick_export_dir, save_web_state, finish_close])
        .setup(move |app| {
            let download_data = app.state::<DesktopState>().data.clone();
            let navigation_app = app.handle().clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("归藏").inner_size(1180., 820.).min_inner_size(480., 620.).center()
                .initialization_script(script)
                .on_page_load(|window, event| {
                    if matches!(event.event(), tauri::webview::PageLoadEvent::Finished) {
                        if let Ok(error) = window.state::<DesktopState>().error.lock() {
                            if let Some(message) = error.as_ref() {
                                let _ = window.eval(&format!("if(window.gzStartupError)window.gzStartupError({})", serde_json::to_string(message).unwrap()));
                            }
                        }
                    }
                })
                .on_navigation(move |url| {
                    if url.scheme() == "http" || url.scheme() == "https" {
                        let port = navigation_app.state::<DesktopState>().port.load(Ordering::Acquire);
                        if backend_origin(url, port) { return true; }
                        open_external(url); return false;
                    }
                    matches!(url.scheme(), "tauri" | "blob" | "about")
                })
                .on_new_window(|url, _| { open_external(&url); NewWindowResponse::Deny })
                .on_download(move |window, event| {
                    match event {
                        DownloadEvent::Requested { destination, .. } => { *destination = export_destination(&download_data, destination); }
                        DownloadEvent::Finished { path, success, .. } => {
                            let message = if success { format!("已存到 {}", path.as_deref().unwrap_or(Path::new("下载文件夹")).display()) } else { "文件没能保存，请检查导出位置".into() };
                            let _ = window.eval(&format!("if(typeof whisper==='function')whisper({})", serde_json::to_string(&message).unwrap()));
                        }
                        _ => ()
                    }
                    true
                })
                .build()?;
            let handle = app.handle().clone();
            thread::spawn(move || {
                if migrate_legacy {
                    if let Some(home) = std::env::var_os("HOME") {
                        let data = handle.state::<DesktopState>().data.clone();
                        if let Err(error) = migrate_legacy_books(&data, &PathBuf::from(home).join("Documents/归藏")) { log(&data, &error); }
                    }
                }
                if let Err(error) = start_backend(handle.clone()) { handle.state::<DesktopState>().stop(); startup_error(&handle, &error); }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                request_close(window.app_handle());
            }
        })
        .build(tauri::generate_context!()).expect("无法创建归藏桌面窗口")
        .run(|app, event| {
            match event {
                tauri::RunEvent::ExitRequested { api, .. } => {
                    if app.state::<DesktopState>().exit_authorized.load(Ordering::Acquire) { app.state::<DesktopState>().stop(); }
                    else { api.prevent_exit(); request_close(app); }
                }
                tauri::RunEvent::Exit => app.state::<DesktopState>().stop(),
                _ => (),
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn desktop_bridge_rejects_other_loopback_services_and_external_hosts() {
        for input in ["http://127.0.0.1:39999/", "https://127.0.0.1:40000/", "http://localhost:40000/", "http://127.0.0.1.evil.test:40000/", "http://evil.test:40000/"] {
            assert!(!backend_origin(&input.parse().unwrap(), 40000), "{input}");
        }
        assert!(backend_origin(&"http://127.0.0.1:40000/api/state".parse().unwrap(), 40000));
        assert!(!backend_origin(&"http://127.0.0.1:0/".parse().unwrap(), 0));
    }

    #[test]
    fn exports_respect_chosen_directory_and_keep_existing_files() {
        let root = std::env::temp_dir().join(format!("guizang-native-test-{}", std::process::id()));
        let chosen = root.join("exports");
        fs::create_dir_all(root.join("cache")).unwrap();
        fs::create_dir_all(&chosen).unwrap();
        fs::write(root.join("cache/config.json"), serde_json::to_vec(&serde_json::json!({"export_dir":chosen})).unwrap()).unwrap();
        fs::write(chosen.join("书名.md"), b"old").unwrap();
        let destination = export_destination(&root, Path::new("/temporary/书名.md"));
        assert_eq!(destination, chosen.join("书名 (2).md"));
        assert_eq!(fs::read(chosen.join("书名.md")).unwrap(), b"old");
        assert_eq!(export_destination(&root, Path::new("书:名.md")), chosen.join("书-名.md"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn old_library_import_is_missing_only_and_happens_once() {
        let root = std::env::temp_dir().join(format!("guizang-migrate-test-{}", std::process::id()));
        let source = root.join("legacy");
        let data = root.join("new");
        fs::create_dir_all(source.join("book")).unwrap();
        fs::create_dir_all(data.join("output/book")).unwrap();
        fs::create_dir_all(data.join("logs")).unwrap();
        fs::write(source.join("book/chapter.md"), b"old chapter").unwrap();
        fs::write(source.join("book/existing.md"), b"old conflict").unwrap();
        fs::write(data.join("output/book/existing.md"), b"new conflict").unwrap();
        migrate_legacy_books(&data, &source).unwrap();
        assert_eq!(fs::read(data.join("output/book/chapter.md")).unwrap(), b"old chapter");
        assert_eq!(fs::read(data.join("output/book/existing.md")).unwrap(), b"new conflict");
        assert!(source.join("book/chapter.md").exists());
        fs::remove_file(data.join("output/book/chapter.md")).unwrap();
        migrate_legacy_books(&data, &source).unwrap();
        assert!(!data.join("output/book/chapter.md").exists(), "user deletion must persist after the first import");
        fs::remove_dir_all(root).unwrap();
    }
}
