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

/// The answer of a request with the launch secret as the bearer: its JSON, or `Null` for none.
fn answer(
    method: &str,
    path: &str,
    response: ureq::http::Response<ureq::Body>,
) -> Result<Value, String> {
    let mut response = response;
    let status = response.status();
    let text = response.body_mut().read_to_string().unwrap_or_default();
    if !status.is_success() {
        return Err(format!("{method} {path} answered {status}: {text}"));
    }
    if text.trim().is_empty() {
        return Ok(Value::Null);
    }
    serde_json::from_str(&text).map_err(|e| format!("{method} {path}: {e}"))
}

fn get(port: u16, path: &str, launch: &str) -> Result<Value, String> {
    let response = agent()
        .get(&format!("{}{path}", base(port)))
        .header("authorization", &format!("Bearer {launch}"))
        .call()
        .map_err(|e| format!("GET {path}: {e}"))?;
    answer("GET", path, response)
}

fn delete(port: u16, path: &str, launch: &str) -> Result<Value, String> {
    let response = agent()
        .delete(&format!("{}{path}", base(port)))
        .header("authorization", &format!("Bearer {launch}"))
        .call()
        .map_err(|e| format!("DELETE {path}: {e}"))?;
    answer("DELETE", path, response)
}

fn post(port: u16, path: &str, launch: &str, body: Value) -> Result<Value, String> {
    let response = agent()
        .post(&format!("{}{path}", base(port)))
        .header("authorization", &format!("Bearer {launch}"))
        .send_json(body)
        .map_err(|e| format!("POST {path}: {e}"))?;
    answer("POST", path, response)
}

/// A worker in a container of its own (docs/specs/containers.md): the name of its service
/// token, the name Robinauts' configuration gives it, and its two files in `secrets/`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Worker {
    pub token_name: &'static str,
    pub resource: &'static str,
    pub token_file: &'static str,
    pub token_id_file: &'static str,
}

/// The code worker: Claude Code.
pub const CODE: Worker = Worker {
    token_name: "fa1-code",
    resource: "claude",
    token_file: "worker_token",
    token_id_file: "worker_token_id",
};

/// The Cursor worker (docs/specs/cursor-worker.md).
pub const CURSOR: Worker = Worker {
    token_name: "fa1-cursor",
    resource: "cursor",
    token_file: "cursor_token",
    token_id_file: "cursor_token_id",
};

/// A service token the control plane holds, as it lists them: no secret.
#[derive(Debug, Clone, PartialEq)]
pub struct ServiceToken {
    pub id: String,
    pub name: String,
}

/// Every service token the control plane holds. A token the launch secret made lives in the
/// control plane's memory, so a stop of the control plane ends it.
pub fn service_tokens(port: u16, launch: &str) -> Result<Vec<ServiceToken>, String> {
    let listed = get(port, "/auth/services", launch)?;
    let items = listed
        .get("items")
        .and_then(Value::as_array)
        .ok_or_else(|| "GET /auth/services answered no items".to_string())?;
    Ok(items
        .iter()
        .filter_map(|item| {
            Some(ServiceToken {
                id: item.get("id")?.as_str()?.to_string(),
                name: item.get("name")?.as_str()?.to_string(),
            })
        })
        .collect())
}

/// Ends the service token `id`.
pub fn revoke_service_token(port: u16, launch: &str, id: &str) -> Result<(), String> {
    delete(port, &format!("/auth/services/{id}"), launch).map(|_| ())
}

/// A service token of `robinauts/worker` bound to `worker`. The answer is its id, then its
/// secret.
pub fn create_worker_token(
    port: u16,
    launch: &str,
    worker: Worker,
) -> Result<(String, String), String> {
    let made = post(
        port,
        "/auth/services",
        launch,
        json!({"name": worker.token_name, "role": "robinauts/worker", "resource": worker.resource}),
    )?;
    let field = |name: &str| {
        made.get(name)
            .and_then(Value::as_str)
            .map(str::to_string)
            .ok_or_else(|| format!("POST /auth/services answered no {name}"))
    };
    Ok((field("id")?, field("secret")?))
}

/// The address that signs the person in, once, within a minute.
pub fn ticket_url(port: u16, launch: &str) -> Result<String, String> {
    let made = post(port, "/auth/tickets", launch, json!({}))?;
    made.get("url")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| "POST /auth/tickets answered no url".to_string())
}
