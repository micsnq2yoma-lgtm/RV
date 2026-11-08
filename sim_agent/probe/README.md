# Task 009: bounded API capability probe

**Live probe has not run yet.** Awaiting user provisioning of the DeepSeek key and
this run's board readiness confirmation. Mock responses are not model evidence.

Use the task 008 network procedure (`board_bootstrap.ps1`, verified SSH host key,
`board_proxy_tunnel.ps1`) and enter Ubuntu using `sh /mount_emmc.sh start`.
Within Ubuntu, install the task-authorized dependencies through the temporary proxy:

```sh
P=http://127.0.0.1:7897
apt-get -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P install -y python3-httpx python3-pil
```

Copy this directory to the board using the existing SCP workflow. **Key setup is
manual, only in an interactive Ubuntu shell with terminal recording disabled:**

```sh
python3 store_key.py
```

The prompt hides input and writes only `/root/.config/rv-agent/deepseek.key`, mode
600, parent 700. It refuses overwrite and refuses noninteractive stdin; no host
temporary key file is needed. Do not send keys through chat, command arguments,
shell `echo`, transcripts or Git. Only the probe's sanitized stdout may be logged.

```sh
HTTPS_PROXY=http://127.0.0.1:7897 python3 deepseek_probe.py
```

Per run: one models request, one chat, one tools, one JSON, one image, five timing
tools requests = **10 requests**, absolute cap 20, no automatic retries. 401/403
stops immediately; missing exact model ID stops after `/models` and asks the
maintainer to choose. It never substitutes another model automatically. A correct
first action is `pick` with exactly `{"color":"red"}`; no physical skill is executed.

Latency is client wall-clock request-to-response, successful valid tool calls
only; p95 uses nearest rank (with 5 samples, effectively the maximum). A single
red image result is a narrow probe, not proof of general vision competence.
All headers are excluded; output is additionally filtered for the exact key.
PNG is generated with Python standard library, so the probe itself needs only httpx.

If board transport fails, first test Buildroot HTTP through the tunnel, then use
the task's PC comparison with a **temporary process environment variable**:

```powershell
python sim_agent/probe/deepseek_probe.py --key-env --location pc
```

`DEEPSEEK_API_KEY` must already be securely supplied to that process; do not put
the value in shell history. PC comparison also respects the 20-request cap and
never writes a key file. Set HTTPS_PROXY as appropriate for that process only.

After requests finish: exit Ubuntu, run `sh /mount_emmc.sh stop`, verify unmounted,
then Ctrl+C in the PC tunnel terminal and verify board 7897 no longer listens.

Offline verification: `python -m unittest discover -s sim_agent/probe -v`.
API shapes follow official [models](https://api-docs.deepseek.com/api/list-models/)
and [chat completions](https://api-docs.deepseek.com/api/create-chat-completion/)
documentation; requested model availability and capabilities require actual results.
