use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::thread;

static CTR: AtomicUsize = AtomicUsize::new(0);

fn plug_bin() -> PathBuf { PathBuf::from(env!("CARGO_BIN_EXE_plug")) }
fn repo_root() -> PathBuf { PathBuf::from(env!("CARGO_MANIFEST_DIR")) }

fn clean_canon(p: &Path) -> PathBuf {
    let c = fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf());
    let s = c.to_string_lossy();
    PathBuf::from(s.strip_prefix(r"\\?\").unwrap_or(&s))
}

fn mktemp(tag: &str) -> PathBuf {
    let id = CTR.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("ep2-test-{}-{}-{}", tag, std::process::id(), id));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    clean_canon(&dir)
}

fn copy_dir(src: &Path, dst: &Path) {
    fs::create_dir_all(dst).unwrap();
    for ent in fs::read_dir(src).unwrap().flatten() {
        let s = ent.path();
        let d = dst.join(ent.file_name());
        if s.is_dir() { copy_dir(&s, &d); } else { fs::copy(&s, &d).unwrap(); }
    }
}

fn run_plug(cwd: &Path, args: &[&str], stdin: Option<&str>, env_add: &[(&str, &str)], env_drop: &[&str]) -> Output {
    let mut cmd = Command::new(plug_bin());
    cmd.args(args).current_dir(cwd).stdout(Stdio::piped()).stderr(Stdio::piped());
    for k in ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "ANTIGRAVITY_AGENT", "ANTIGRAVITY_CONVERSATION_ID", "KB_APPROVE", "PLUG_OWNER", "PLUG_ROOT", "PLUG_STAGED"] {
        cmd.env_remove(k);
    }
    for k in env_drop { cmd.env_remove(k); }
    for (k, v) in env_add { cmd.env(k, v); }
    if stdin.is_some() { cmd.stdin(Stdio::piped()); }
    let mut child = cmd.spawn().expect("spawn plug");
    if let Some(s) = stdin {
        child.stdin.take().unwrap().write_all(s.as_bytes()).unwrap();
    }
    child.wait_with_output().unwrap()
}

fn git(cwd: &Path, args: &[&str]) -> Output {
    let mut cmd = Command::new("git");
    cmd.args(["-c", "commit.gpgsign=false"]).args(args).current_dir(cwd);
    cmd.env_remove("KB_APPROVE");
    cmd.output().unwrap()
}

fn trust_codex_hooks(root: &Path, codex_home: &Path) {
    fs::create_dir_all(codex_home).unwrap();
    let hooks_path = clean_canon(&root.join(".codex").join("hooks.json"));
    let val: Value = serde_json::from_str(&fs::read_to_string(&hooks_path).unwrap()).unwrap();
    let hooks = val["hooks"].as_object().unwrap();
    let path_str = hooks_path.to_string_lossy().to_string();
    let mut toml_out = String::from("approval_policy = \"never\"\nsandbox_mode = \"danger-full-access\"\n\n[hooks.state]\n");
    for (ev, groups) in hooks {
        let snake = match ev.as_str() {
            "PreToolUse" => "pre_tool_use", "PostToolUse" => "post_tool_use", "PreCompact" => "pre_compact",
            "SessionStart" => "session_start", "Stop" => "stop", o => o,
        };
        for (gi, g) in groups.as_array().unwrap().iter().enumerate() {
            for (hi, h) in g["hooks"].as_array().unwrap().iter().enumerate() {
                let t = h.get("timeout").and_then(|v| v.as_i64()).unwrap_or(600).max(1);
                let hm = BTreeMap::from([
                    ("async", Value::Bool(h.get("async").and_then(|v| v.as_bool()).unwrap_or(false))),
                    ("command", Value::String(h["command"].as_str().unwrap().into())),
                    ("timeout", Value::Number(t.into())), ("type", Value::String("command".into())),
                ]);
                let mut obj = BTreeMap::from([("event_name", Value::String(snake.into())), ("hooks", Value::Array(vec![serde_json::to_value(hm).unwrap()]))]);
                if let Some(m) = g.get("matcher") { obj.insert("matcher", m.clone()); }
                let blob = serde_json::to_string(&obj).unwrap();
                let digest = format!("sha256:{}", hex::encode(Sha256::digest(blob.as_bytes())));
                let key = format!("{}:{}:{}:{}", path_str, snake, gi, hi).replace('\\', "\\\\");
                toml_out.push_str(&format!("\"{}\" = {{ enabled = true, trusted_hash = \"{}\" }}\n", key, digest));
            }
        }
    }
    fs::write(codex_home.join("config.toml"), toml_out).unwrap();
}

fn setup_example(tag: &str) -> (PathBuf, PathBuf, PathBuf, PathBuf) {
    let base = mktemp(tag);
    let root = base.join("content");
    let codex_home = base.join("codexhome");
    let agy_conf = base.join("agyconf");
    fs::create_dir_all(&agy_conf).unwrap();
    copy_dir(&repo_root().join("example-tool"), &root);
    fs::write(root.join(".gitignore"), ".kb/\n.claude/skills/\n.agents/skills/\n").unwrap();
    assert!(git(&root, &["init", "-q", "-b", "main"]).status.success());
    assert!(git(&root, &["config", "user.name", "test"]).status.success());
    assert!(git(&root, &["config", "user.email", "t@example.com"]).status.success());
    assert!(git(&root, &["add", "-A"]).status.success());
    assert!(git(&root, &["commit", "-q", "-m", "init"]).status.success());
    let r = run_plug(&root, &["init", "--pilot", "all"], None, &[], &[]);
    assert!(r.status.success(), "init failed: {}", String::from_utf8_lossy(&r.stderr));
    trust_codex_hooks(&root, &codex_home);
    assert!(run_plug(&root, &["index", "--full"], None, &[], &[]).status.success());
    (base, root, codex_home, agy_conf)
}

#[test]
fn c0_to_c4_full_acceptance_on_example_tool() {
    let (base, root, codex_home, agy_conf) = setup_example("acc");
    let ch = codex_home.to_string_lossy().to_string();
    let ac = agy_conf.to_string_lossy().to_string();
    let penv = [("CODEX_HOME", ch.as_str()), ("PLUG_AGY_CONFIG", ac.as_str())];

    // C0: search 责任, 50-case Sunzi goldset >= 0.96, broken anchor caught, unknown shape refused, status 100%
    let sr = run_plug(&root, &["search", "责任", "--scope", "corpus"], None, &penv, &[]);
    assert!(sr.status.success() && String::from_utf8_lossy(&sr.stdout).contains("BV1EXAMPLE01"));

    let gs = repo_root().join("bench/public/goldset-sunzi.yaml");
    let ev = run_plug(&root, &["eval", gs.to_str().unwrap()], None, &penv, &[]);
    let ev_out = String::from_utf8_lossy(&ev.stdout);
    assert!(ev.status.success(), "eval failed: {}", ev_out);
    assert!(ev_out.contains("recall@10 0.98") || ev_out.contains("recall@10 0.96") || ev_out.contains("recall@10 1.00"), "eval: {}", ev_out);

    let shi = root.join("tools/sunzi/dict/shi.md");
    let orig_shi = fs::read_to_string(&shi).unwrap();
    fs::write(&shi, orig_shi.replace("至于漂石者，势也\"", "至于漂石者，力也\"")).unwrap();
    let chk = run_plug(&root, &["check", "--quiet", "--no-expire"], None, &penv, &[]);
    assert!(!chk.status.success() && String::from_utf8_lossy(&chk.stdout).contains("ERROR anchor"));
    fs::write(&shi, &orig_shi).unwrap();

    let ypath = root.join("plug.yaml");
    let orig_y = fs::read_to_string(&ypath).unwrap();
    fs::write(&ypath, orig_y.replace("shape_version: 1", "shape_version: 99")).unwrap();
    let chk99 = run_plug(&root, &["check", "--quiet"], None, &penv, &[]);
    let s99 = run_plug(&root, &["search", "势"], None, &penv, &[]);
    assert!(String::from_utf8_lossy(&chk99.stdout).contains("ERROR shape_version") && !s99.status.success());
    fs::write(&ypath, &orig_y).unwrap();

    let st = run_plug(&root, &["status"], None, &penv, &[]);
    let st_out = String::from_utf8_lossy(&st.stdout);
    assert!(st.status.success() && st_out.contains("SYNC RATE 100.0%") && st_out.contains("ALL SYSTEMS NOMINAL"), "status:\n{}", st_out);

    // C1 & C2: pre-commit blocks RULES.md, records commit freely, agent env blocks apply, owner lands proposal, .plug-off preserves berserk lock
    let rules = root.join("self/RULES.md");
    let orig_rules = fs::read_to_string(&rules).unwrap();
    fs::write(&rules, format!("{}\n- J9 · sneak [2026-08]\n", orig_rules)).unwrap();
    git(&root, &["add", "self/RULES.md"]);
    let bad_c = git(&root, &["commit", "-q", "-m", "sneak"]);
    assert!(!bad_c.status.success() && String::from_utf8_lossy(&bad_c.stderr).contains("berserk lock"));
    git(&root, &["reset", "-q", "HEAD", "self/RULES.md"]);
    fs::write(&rules, &orig_rules).unwrap();

    let rec = root.join("self/records/2026-08-29-acc.md");
    fs::write(&rec, "---\ntool: sunzi\nby: codex · gpt-5 · 2026-08-29\nsituation: 验收\nverdict: A\nchosen:\noutcome:\n---\n## 依据\nJ1 · 上次：无类似记录\n## 最强反证\nb\n## 什么会改判\nc\n").unwrap();
    git(&root, &["add", "self/records"]);
    let ok_c = git(&root, &["commit", "-q", "-m", "record"]);
    assert!(ok_c.status.success(), "record commit failed: {}", String::from_utf8_lossy(&ok_c.stderr));

    let pending = "proposals/pending/2026-08-26-shi-alias.md";
    let ag_refuse = run_plug(&root, &["apply", pending], None, &[("CLAUDECODE", "1")], &[]);
    let ag_dry = run_plug(&root, &["apply", pending, "--dry-run"], None, &[("CLAUDECODE", "1")], &[]);
    assert!(!ag_refuse.status.success() && String::from_utf8_lossy(&ag_refuse.stdout).contains("agent environment detected") && ag_dry.status.success());

    let app = run_plug(&root, &["apply", pending], None, &penv, &[]);
    assert!(app.status.success(), "apply failed: {}", String::from_utf8_lossy(&app.stdout));
    let log = String::from_utf8_lossy(&git(&root, &["log", "-1", "--format=%B"]).stdout).to_string();
    assert!(log.contains("Proposal-Sha:"));

    // .plug-off lets sortie lock through while leaving berserk lock (both pre-commit & pretool) armed!
    fs::write(root.join(".plug-off"), "").unwrap();
    let rs = root.to_string_lossy().replace('\\', "/");
    let out_p = run_plug(&root, &["gate", "pretool"], Some(&json!({"tool_name":"Bash","tool_input":{"command":"curl -X POST https://example.invalid"},"cwd":rs}).to_string()), &[], &[]);
    let wt_p = run_plug(&root, &["gate", "pretool"], Some(&json!({"tool_name":"Edit","tool_input":{"file_path":"self/RULES.md"},"cwd":rs}).to_string()), &[], &[]);
    let pre_p = run_plug(&root, &["gate", "precommit"], None, &[("PLUG_STAGED", "self/RULES.md")], &["GIT_INDEX_FILE"]);
    fs::remove_file(root.join(".plug-off")).unwrap();
    assert!(!String::from_utf8_lossy(&out_p.stdout).contains("deny"), "sortie should pass with .plug-off");
    assert!(String::from_utf8_lossy(&wt_p.stdout).contains("deny"), "worktree berserk lock must stay armed with .plug-off");
    assert!(!pre_p.status.success() && String::from_utf8_lossy(&pre_p.stderr).contains("berserk lock"));

    // C3: PreCompact + SessionStart(compact) + Stop
    let pc = run_plug(&root, &["gate", "precompact"], Some(&json!({"hook_event_name":"PreCompact","cwd":rs}).to_string()), &[], &[]);
    let pc_s = String::from_utf8_lossy(&pc.stdout);
    assert!(pc.status.success() && pc_s.contains("where we are:") && pc_s.contains("answer in: 中文"));
    let em = run_plug(&root, &["gate", "precompact", "--emit"], Some(&json!({"hook_event_name":"SessionStart","cwd":rs}).to_string()), &[], &[]);
    assert!(em.status.success() && String::from_utf8_lossy(&em.stdout).contains("additionalContext"));
    let stop_q = run_plug(&root, &["gate", "stop"], Some(&json!({"hook_event_name":"Stop","cwd":rs}).to_string()), &[("PLUG_RECORD_WINDOW", "8")], &[]);
    assert!(stop_q.status.success() && String::from_utf8_lossy(&stop_q.stdout).trim().is_empty());

    // C4: First contact green for all 3 pilots
    for pilot in ["claude-code", "codex", "antigravity"] {
        let fc = run_plug(&root, &["check", "--contact", pilot], None, &penv, &[]);
        let fo = String::from_utf8_lossy(&fc.stdout);
        assert!(fc.status.success() && fo.contains("first contact, nothing wrong"), "contact {} failed:\n{}", pilot, fo);
    }
    let _ = fs::remove_dir_all(&base);
}

#[test]
fn v2_unified_diff_apply_exact_matcher_drift_and_worktree_locks() {
    let (base, root, codex_home, agy_conf) = setup_example("v2-locks");
    let ch = codex_home.to_string_lossy().to_string();
    let ac = agy_conf.to_string_lossy().to_string();
    let penv = [("CODEX_HOME", ch.as_str()), ("PLUG_AGY_CONFIG", ac.as_str())];
    let rs = root.to_string_lossy().replace('\\', "/");

    // 1. Unified Diff proposal apply + clean landing
    let rules_path = root.join("self/RULES.md");
    let h_out = run_plug(&root, &["hash", rules_path.to_str().unwrap()], None, &[], &[]);
    let base_hash = String::from_utf8_lossy(&h_out.stdout).trim().to_string();
    let orig_rules = fs::read_to_string(&rules_path).unwrap();
    let first_line = orig_rules.lines().next().unwrap();
    let udiff_prop = root.join("proposals/pending/2026-11-25-udiff.md");
    fs::write(&udiff_prop, format!(
        "---\ntarget: self/RULES.md\nbase: {}\nfrom: self/records/x.md\n---\n## 改成什么\n```diff\n@@ -1,1 +1,2 @@\n {}\n+<!-- udiff-verified -->\n```\n## 为什么\ntest udiff\n## 最强反证\nnone\n",
        base_hash, first_line
    )).unwrap();
    let app = run_plug(&root, &["apply", "proposals/pending/2026-11-25-udiff.md"], None, &penv, &[]);
    assert!(app.status.success(), "udiff apply failed: {}", String::from_utf8_lossy(&app.stdout));
    assert!(fs::read_to_string(&rules_path).unwrap().contains("<!-- udiff-verified -->"));

    // 2. Worktree Berserk Lock across all 3 pilots + path traversal + .kb/hooks tampering
    let attacks = [
        json!({"tool_name":"Edit","tool_input":{"file_path":"self/records/../../self/RULES.md"},"cwd":&rs}),
        json!({"tool_name":"apply_patch","tool_input":{"input":"*** Begin Patch\n*** Update File: self/style.md\n*** End Patch"},"cwd":&rs,"turn_id":"t1"}),
        json!({"hookEventName":"PreToolUse","cwd":&rs,"toolCall":{"id":"a1","name":"replace_file_content","args":{"TargetFile":"plug.yaml"}}}),
        json!({"hookEventName":"PreToolUse","cwd":&rs,"toolCall":{"id":"a2","name":"run_command","args":{"CommandLine":"echo hack >> .kb/hooks/outbound"}}}),
        json!({"hookEventName":"PreToolUse","cwd":&rs,"toolCall":{"id":"a3","name":"manage_task","args":{"Action":"send_input","Input":"git push origin main"}}}),
    ];
    for atk in &attacks {
        let r = run_plug(&root, &["gate", "pretool"], Some(&atk.to_string()), &[], &[]);
        let out = String::from_utf8_lossy(&r.stdout);
        assert!(r.status.success() && out.contains("deny"), "attack not blocked: {} -> {}", atk, out);
    }

    // 3. Exact 1-char matcher drift detection flips `plug status` orange on EACH pilot!
    for (rel, find, repl) in [
        (".claude/settings.json", "NotebookEdit", "NotebookEdiX"),
        (".codex/hooks.json", "apply_patch", "apply_patcX"),
        (".agents/plugins/entryplug/hooks.json", "manage_task", "manage_tasX"),
    ] {
        let p = root.join(rel);
        let orig = fs::read_to_string(&p).unwrap();
        assert!(orig.contains(find), "{} missing {}", rel, find);
        fs::write(&p, orig.replace(find, repl)).unwrap();
        let st = run_plug(&root, &["status"], None, &penv, &[]);
        let so = String::from_utf8_lossy(&st.stdout);
        assert!(so.contains("PATTERN ORANGE") && so.contains("[NG] Sortie lock"), "1-char drift in {} did not flip status orange:\n{}", rel, so);
        fs::write(&p, orig).unwrap();
    }
    let _ = fs::remove_dir_all(&base);
}

#[test]
fn v2_posttool_concurrency_blind_quotes_spine_books_trace_prompt_review() {
    let (base, root, _ch, _ac) = setup_example("v2-full");
    let rs = root.to_string_lossy().replace('\\', "/");

    // Configure books, logs, prompt_hints, and low topic_pulse threshold for test
    let logs_dir = base.join("logs");
    let books_dir = root.join("books");
    fs::create_dir_all(&books_dir).unwrap();
    fs::write(books_dir.join("lacan_seminar.txt"), "标题: 研讨班十一卷\n==== 纯文本 ====\n[¶1] 主体是在能指链条的裂隙中涌现的。\n").unwrap();
    let ypath = root.join("plug.yaml");
    let mut yml = fs::read_to_string(&ypath).unwrap();
    yml.push_str(&format!(
        "\nbooks:\n  - path: books\n    sub: books\nlogs: {}\ntopic_pulse_sessions: 2\ntopic_pulse_fragments: 2\nprompt_hints:\n  - id: h3\n    pattern: \"(?i)H3\"\n    hint: \"[hint] check self/memory/h3.md\"\n    cooldown_hours: 0\n",
        logs_dir.to_string_lossy().replace('\\', "/")
    ));
    fs::write(&ypath, yml).unwrap();
    assert!(run_plug(&root, &["index", "--full", "--books"], None, &[], &[]).status.success());

    // 1. scope=books hits separate .kb/books.sqlite
    let bk = run_plug(&root, &["search", "能指链条", "--scope", "books"], None, &[], &[]);
    assert!(bk.status.success() && String::from_utf8_lossy(&bk.stdout).contains("lacan_seminar"));

    // 2. 5 concurrent PostToolUse writers -> 0 errors, WAL hot-indexed, immediately searchable via MCP, blind.jsonl recorded!
    let mut handles = Vec::new();
    for i in 0..5 {
        let root_c = root.clone();
        let rs_c = rs.clone();
        handles.push(thread::spawn(move || {
            let rel = format!("self/records/2026-11-2{}-conc-{}.md", i, i);
            let p = root_c.join(&rel);
            fs::write(&p, format!(
                "---\ntool: sunzi\nby: claude-code · opus · 2026-11-2{}\nsituation: 并发测试{}\nverdict: 推荐A{}\nchosen:\noutcome:\ntopic: H3\n---\n## 依据\n上次：无类似记录 · 唯一并发标记TOKEN{}\n## 最强反证\nb\n## 什么会改判\nc\n",
                i, i, i, i
            )).unwrap();
            let payload = json!({"hookEventName":"PostToolUse","cwd":rs_c,"toolCall":{"id":"p","name":"write_file","args":{"Path":rel}}}).to_string();
            let r = run_plug(&root_c, &["gate", "posttool"], Some(&payload), &[], &[]);
            assert!(r.status.success(), "posttool {} failed", i);
        }));
    }
    for h in handles { h.join().unwrap(); }

    // Immediately searchable without running `plug index`!
    for i in 0..5 {
        let q = format!("TOKEN{}", i);
        let s = run_plug(&root, &["search", &q, "--scope", "tools", "--no-stale"], None, &[], &[]);
        assert!(String::from_utf8_lossy(&s.stdout).contains(&format!("conc-{}", i)), "hot index missed {}", i);
    }
    let blind_txt = fs::read_to_string(root.join(".kb/blind.jsonl")).unwrap();
    assert!(blind_txt.contains("conc-0.md") && blind_txt.contains("\"has_chosen\":false"));

    // 3. Fabricated quote triggers PostToolUse advisory warning while exiting 0
    let fake_rel = "self/records/2026-11-25-fake-quote.md";
    fs::write(root.join(fake_rel), "---\ntool: sunzi\nby: claude-code · opus · 2026-11-25\nsituation: 引文测\nverdict: A\n---\n## 依据\n《势与形》[5:30]「完全编造的不存在的句子」\n## 最强反证\nb\n## 什么会改判\nc\n").unwrap();
    let pq = run_plug(&root, &["gate", "posttool"], Some(&json!({"tool_name":"Write","tool_input":{"file_path":fake_rel},"cwd":&rs}).to_string()), &[], &[]);
    assert!(pq.status.success() && String::from_utf8_lossy(&pq.stdout).contains("quote not found"), "posttool quote check missed: {}", String::from_utf8_lossy(&pq.stdout));

    // 4. Shape v2: kind: note + supersedes (Active Heads default vs --history) + --view spine
    fs::write(root.join("self/records/2026-11-25-free-note.md"), "---\nkind: note\nsituation: 自由随手记\ntopic: H3\n---\n今天试了新运镜。\n").unwrap();
    fs::write(root.join("self/records/2026-11-25-superseder.md"), "---\ntool: sunzi\nby: codex · gpt-5 · 2026-11-25\nsituation: 覆盖旧判断\nverdict: 新判断B\nsupersedes: 2026-11-20-conc-0\n---\n## 依据\n无类似记录\n## 最强反证\nb\n## 什么会改判\nc\n").unwrap();
    assert!(run_plug(&root, &["index"], None, &[], &[]).status.success());
    let head_only = run_plug(&root, &["search", "TOKEN0", "--scope", "tools"], None, &[], &[]);
    let with_hist = run_plug(&root, &["search", "TOKEN0", "--scope", "tools", "--history"], None, &[], &[]);
    assert!(String::from_utf8_lossy(&head_only.stdout).contains("showing 0/0"), "superseded record leaked into Active Heads");
    assert!(String::from_utf8_lossy(&with_hist.stdout).contains("conc-0"), "--history did not return superseded record");
    let spine = run_plug(&root, &["search", "并发测试", "--scope", "tools", "--view", "spine"], None, &[], &[]);
    assert!(String::from_utf8_lossy(&spine.stdout).contains("spine showing"));

    // 5. Cross-pilot trace sync + secret masking + scope=logs search
    let src_dir = base.join("transcripts");
    fs::create_dir_all(&src_dir).unwrap();
    let claude_j = src_dir.join("claude.jsonl");
    let codex_j = src_dir.join("codex.jsonl");
    let agy_j = src_dir.join("agy.jsonl");
    fs::write(&claude_j, "{\"type\":\"user\",\"timestamp\":\"2026-11-25T10:00:00Z\",\"message\":{\"content\":\"Claude聊H3密钥sk-1234567890abcdefghijklmno\"}}\n").unwrap();
    fs::write(&codex_j, "{\"type\":\"message\",\"timestamp\":\"2026-11-25T10:05:00Z\",\"role\":\"user\",\"content\":\"Codex聊H3镜头\"}\n").unwrap();
    fs::write(&agy_j, "{\"type\":\"USER_INPUT\",\"created_at\":\"2026-11-25T10:10:00Z\",\"content\":\"Antigravity聊H3剪辑\"}\n").unwrap();
    let srcs = format!("claude-code={};codex={};antigravity={}", claude_j.display(), codex_j.display(), agy_j.display());
    let tr = run_plug(&root, &["trace", "sync"], None, &[("PLUG_TRACE_SOURCES", &srcs)], &[]);
    assert!(tr.status.success() && String::from_utf8_lossy(&tr.stdout).contains("3 turns"), "trace: {}", String::from_utf8_lossy(&tr.stdout));
    let log_md = fs::read_to_string(logs_dir.join("2026-11-25.md")).unwrap();
    assert!(log_md.contains("〔已遮：密钥〕") && !log_md.contains("sk-1234567890") && log_md.contains("claude-code") && log_md.contains("codex") && log_md.contains("antigravity"));
    assert!(run_plug(&root, &["index"], None, &[], &[]).status.success());
    let log_s = run_plug(&root, &["search", "Antigravity", "--scope", "logs"], None, &[], &[]);
    assert!(String::from_utf8_lossy(&log_s.stdout).contains("2026-11-25"));

    // 6. Prompt router + topic_pulse proactive trigger + plug review --topic H3
    let pr = run_plug(&root, &["gate", "prompt"], Some(&json!({"hook_event_name":"UserPromptSubmit","prompt":"再聊聊H3的运镜","cwd":&rs}).to_string()), &[], &[]);
    let pr_out = String::from_utf8_lossy(&pr.stdout);
    assert!(pr.status.success() && pr_out.contains("[hint] check self/memory/h3.md") && pr_out.contains("[topic_pulse]"), "prompt: {}", pr_out);

    let rev = run_plug(&root, &["review", "--since", "30d", "--topic", "H3", "--json", "--mark-reviewed"], None, &[], &[]);
    let rev_s = String::from_utf8_lossy(&rev.stdout);
    assert!(rev.status.success() && rev_s.contains("\"topic\": \"H3\"") && rev_s.contains("quote_reject"), "review: {}", rev_s);

    let _ = fs::remove_dir_all(&base);
}
