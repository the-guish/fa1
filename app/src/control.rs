//! What the app asks the control plane over HTTP, on the host's 127.0.0.1 (docs/specs/core.md,
//! "The app and the control plane"). The launch secret is the bearer.

use std::time::{Duration, Instant};

use serde_json::{Value, json};

fn base(port: u16) -> String {
    format!("http://127.0.0.1:{port}")
}

fn agent() -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(20)))
        .http_status_as_error(false)
        .build()
        .into()
}

/// Waits until the front listener answers `/auth/session`, for `limit` at most.
pub fn wait_until_up(port: u16, limit: Duration) -> Result<(), String> {
    let started = Instant::now();
    let url = format!("{}/auth/session", base(port));
    loop {
        if agent().get(&url).call().is_ok_and(|r| r.status() == 200) {
            return Ok(());
        }
        if started.elapsed() > limit {
            return Err(format!(
                "the control plane did not answer on {url} within {limit:?}"
            ));
        }
        std::thread::sleep(Duration::from_millis(500));
    }
}

/// `/health`'s status: `ok` once every worker, the code worker included, has been heard from.
pub fn health(port: u16) -> String {
    agent()
        .get(&format!("{}/health", base(port)))
        .call()
        .ok()
        .and_then(|mut r| r.body_mut().read_json::<Value>().ok())
        .and_then(|v| v.get("status").and_then(Value::as_str).map(str::to_string))
        .unwrap_or_else(|| "unreachable".to_string())
}

fn post(port: u16, path: &str, launch: &str, body: Value) -> Result<Value, String> {
    let url = format!("{}{path}", base(port));
    let mut response = agent()
        .post(&url)
        .header("authorization", &format!("Bearer {launch}"))
        .send_json(body)
        .map_err(|e| format!("POST {path}: {e}"))?;
    let status = response.status();
    let text = response.body_mut().read_to_string().unwrap_or_default();
    if !status.is_success() {
        return Err(format!("POST {path} answered {status}: {text}"));
    }
    serde_json::from_str(&text).map_err(|e| format!("POST {path}: {e}"))
}

/// A service token of `robinauts/worker` bound to the worker `claude`: the code worker's.
pub fn create_worker_token(port: u16, launch: &str) -> Result<String, String> {
    let made = post(
        port,
        "/auth/services",
        launch,
        json!({"name": "fa1-code", "role": "robinauts/worker", "resource": "claude"}),
    )?;
    made.get("secret")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| "POST /auth/services answered no secret".to_string())
}

/// The address that signs the person in, once, within a minute.
pub fn ticket_url(port: u16, launch: &str) -> Result<String, String> {
    let made = post(port, "/auth/tickets", launch, json!({}))?;
    made.get("url")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| "POST /auth/tickets answered no url".to_string())
}
