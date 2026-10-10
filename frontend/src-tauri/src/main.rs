mod dpapi;
mod pg_password_pipe;
mod private_runtime;

use tauri::Manager;
use tauri_plugin_window_state::StateFlags;
use velopack::VelopackApp;

#[tauri::command]
fn retry_private_runtime(app: tauri::AppHandle) {
    private_runtime::launch(app);
}

fn main() {
    // Velopack install/update hooks must run before Tauri is initialized.
    VelopackApp::build().run();

    tauri::Builder::default()
        // Keep the upstream Tauri single-instance and Windows window state behavior.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(
                    StateFlags::POSITION | StateFlags::SIZE | StateFlags::MAXIMIZED,
                )
                .build(),
        )
        // Bind retry after each real page load; a redirect discards the old DOM.
        // The frontend remains canonical for /yance/startup and the Composer.
        .on_page_load(|window, _payload| {
            let _ = window.eval(r#"
                if (!window.__YANCE_RUNTIME_RETRY_BOUND__) {
                    window.__YANCE_RUNTIME_RETRY_BOUND__ = true;
                    document.addEventListener('click', function(event) {
                        if (event.target?.closest('.startup-state__retry')) {
                            window.__TAURI_INTERNALS__?.invoke('retry_private_runtime');
                        }
                    }, true);
                }
            "#);
        })
        .invoke_handler(tauri::generate_handler![retry_private_runtime])
        .setup(|app| {
            private_runtime::launch(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to initialize the native Yance desktop shell")
        .run(|_, event| {
            if let tauri::RunEvent::Exit = event {
                private_runtime::stop();
            }
        });
}
