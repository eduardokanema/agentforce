"""HTML rendering for the AgentForce dashboard."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

_TEMPLATES = Path(__file__).parent / "templates"


def _h(s) -> str:
    return html.escape(str(s), quote=True)


def _tpl(name: str, **ctx) -> str:
    text = (_TEMPLATES / name).read_text(encoding="utf-8")
    for key, val in ctx.items():
        text = text.replace(f"${{{key}}}", str(val))
    return text


def _page(title: str, body: str, refresh: int = 0) -> str:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return _tpl("base.html", title=_h(title), body=body, meta_refresh=meta)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status_badge(status: str) -> str:
    label = status.replace("_", " ")
    return f'<span class="badge b-{_h(status)}">{label}</span>'


def _mission_badge(state) -> str:
    if state.is_done():
        return '<span class="badge b-ok">complete</span>'
    if state.is_failed():
        return '<span class="badge b-failed">failed</span>'
    if state.needs_human():
        return '<span class="badge b-needs_human">needs human</span>'
    return '<span class="badge b-active">active</span>'


def _score_badge(score: int) -> str:
    if not score:
        return ""
    cls = "sc-lo" if score <= 4 else ("sc-mi" if score <= 7 else "sc-hi")
    return f'<span class="score {cls}">{score}/10</span>'


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts[:19]


def _fmt_duration(started: str, ended: str | None) -> str:
    try:
        s = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end_ts = ended or datetime.now(timezone.utc).isoformat()
        e = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
        secs = int((e - s).total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m {secs % 60}s"
        return f"{secs // 3600}h {(secs % 3600) // 60}m"
    except Exception:
        return "?"


def _agent_chip(state) -> str:
    agent = getattr(state, "worker_agent", "") or ""
    model = getattr(state, "worker_model", "") or ""
    if not agent:
        return ""
    label = agent + (f" · {model}" if model else "")
    return f'<span class="chip">🤖 {_h(label)}</span>'


# ── Page renderers ────────────────────────────────────────────────────────────

def render_mission_list(missions: list) -> str:
    if not missions:
        return _page(
            "Missions",
            '<p class="empty">No missions yet. Start one with <code>mission start &lt;spec&gt;</code></p>',
            refresh=10,
        )

    cards = []
    for s in missions:
        done = sum(1 for t in s.task_states.values() if t.status == "review_approved")
        total = len(s.task_states)
        pct = int(done / total * 100) if total else 0
        dur = _fmt_duration(s.started_at, s.completed_at)
        badge = _mission_badge(s)
        chip = _agent_chip(s)

        cards.append(f"""
<a class="mission-card" href="/mission/{_h(s.mission_id)}">
  <div class="mission-card-body">
    <div class="mission-name">{_h(s.spec.name)}</div>
    <div class="mission-meta">{_h(s.mission_id)} &middot; {done}/{total} tasks &middot; {dur}{(" &middot; " + chip) if chip else ""}</div>
    <div class="mission-prog">
      <div class="prog-track"><div class="prog-fill" style="width:{pct}%"></div></div>
      <div class="prog-label">{pct}% complete</div>
    </div>
  </div>
  <div>{badge}</div>
</a>""")

    body = f'<h2 class="section-title">Missions <span class="auto-label">(auto-refresh 10s)</span></h2>\n<div class="mission-list">{"".join(cards)}</div>'
    return _page("Missions", body, refresh=10)


def render_mission_detail(state) -> str:
    done = sum(1 for t in state.task_states.values() if t.status == "review_approved")
    total = len(state.task_states)
    dur = _fmt_duration(state.started_at, state.completed_at)
    scores = [t.review_score for t in state.task_states.values() if t.review_score]
    avg_score = f"{sum(scores)/len(scores):.1f}" if scores else "—"
    agent = getattr(state, "worker_agent", "") or ""
    model = getattr(state, "worker_model", "") or ""

    agent_stat = ""
    if agent:
        label = agent + (f" · {model}" if model else "")
        agent_stat = f'<div class="stat"><div class="stat-lbl">Agent</div><div class="stat-val" style="font-size:13px">{_h(label)}</div></div>'

    stats = f"""<div class="stats">
  <div class="stat"><div class="stat-lbl">Tasks</div><div class="stat-val">{done} / {total}</div></div>
  <div class="stat"><div class="stat-lbl">Duration</div><div class="stat-val">{dur}</div></div>
  <div class="stat"><div class="stat-lbl">Retries</div><div class="stat-val">{state.total_retries}</div></div>
  <div class="stat"><div class="stat-lbl">Avg Score</div><div class="stat-val">{avg_score}</div></div>
  <div class="stat"><div class="stat-lbl">Interventions</div><div class="stat-val">{state.total_human_interventions}</div></div>
  {agent_stat}
</div>"""

    rows = []
    for task_spec in state.spec.tasks:
        ts = state.task_states.get(task_spec.id)
        if not ts:
            continue
        score_cell = _score_badge(ts.review_score)
        retries = f"{ts.retries}r" if ts.retries else ""
        rows.append(f"""
<a class="task-row" href="/mission/{_h(state.mission_id)}/task/{_h(ts.task_id)}">
  <span class="task-num">{_h(ts.task_id)}</span>
  <span class="task-title">{_h(task_spec.title)}</span>
  <span class="task-retries">{retries}</span>
  {score_cell}
  {_status_badge(ts.status)}
</a>""")

    event_rows = []
    for e in reversed(state.event_log[-50:]):
        tid_cell = f'<a href="/mission/{_h(state.mission_id)}/task/{_h(e.task_id)}">{_h(e.task_id)}</a>' if e.task_id else ""
        etype = e.event_type.replace("_", " ")
        event_rows.append(f"""<tr>
  <td class="ev-ts">{_fmt_ts(e.timestamp)}</td>
  <td>{_status_badge(e.event_type)}</td>
  <td>{tid_cell}</td>
  <td class="ev-detail">{_h(e.details[:140])}</td>
</tr>""")

    no_events = '<tr><td colspan="4" class="empty" style="padding:12px 16px">No events yet.</td></tr>'
    badge = _mission_badge(state)
    breadcrumb = f'<nav class="breadcrumb"><a href="/">Missions</a><span class="breadcrumb-sep">›</span><span>{_h(state.spec.name)}</span></nav>'

    body = f"""{breadcrumb}
<div class="page-head">
  <h1>{_h(state.spec.name)}</h1>
  {badge}
</div>
{stats}
<div class="sec">
  <h2 class="section-title">Tasks <span class="auto-label">(auto-refresh 10s)</span></h2>
  <div class="task-list">{"".join(rows)}</div>
</div>
<div class="sec">
  <h2 class="section-title">Event Log</h2>
  <div class="event-log">
    <table>
      <thead><tr><th>Time</th><th>Event</th><th>Task</th><th>Details</th></tr></thead>
      <tbody>{"".join(event_rows) or no_events}</tbody>
    </table>
  </div>
</div>"""
    return _page(state.spec.name, body, refresh=10)


_TERMINAL_STATUSES = {"review_approved", "review_rejected", "failed", "blocked"}


def render_task_detail(state, task_id: str) -> str:
    ts = state.task_states.get(task_id)
    task_spec = next((t for t in state.spec.tasks if t.id == task_id), None)
    if not ts or not task_spec:
        return _page("Not found", f'<p class="empty">Task <code>{_h(task_id)}</code> not found.</p>')

    score_badge = _score_badge(ts.review_score)
    dur = _fmt_duration(ts.started_at or state.started_at, ts.completed_at)
    is_active = ts.status not in _TERMINAL_STATUSES

    stats = f"""<div class="stats">
  <div class="stat"><div class="stat-lbl">Status</div><div class="stat-val" style="font-size:13px">{_status_badge(ts.status)}</div></div>
  <div class="stat"><div class="stat-lbl">Score</div><div class="stat-val">{score_badge or "—"}</div></div>
  <div class="stat"><div class="stat-lbl">Retries</div><div class="stat-val">{ts.retries}</div></div>
  <div class="stat"><div class="stat-lbl">Duration</div><div class="stat-val">{dur}</div></div>
</div>"""

    worker_out = (
        f'<div class="out-panel">{_h(ts.worker_output)}</div>'
        if ts.worker_output
        else '<p class="empty">No output yet.</p>'
    )
    review_out = (
        f'<div class="out-panel">{_h(ts.review_feedback)}</div>'
        if ts.review_feedback
        else '<p class="empty">No review yet.</p>'
    )

    extras = ""
    if ts.blocking_issues:
        items = "".join(f'<li class="issue-item">{_h(i)}</li>' for i in ts.blocking_issues)
        extras += f'<div class="sec"><h2 class="section-title">Blocking Issues</h2><ul class="issue-list">{items}</ul></div>'
    if ts.human_intervention_needed or ts.human_intervention_message:
        extras += f'<div class="sec"><h2 class="section-title">Human Intervention Required</h2><div class="human-box">{_h(ts.human_intervention_message)}</div></div>'
    if ts.error_message:
        extras += f'<div class="sec"><h2 class="section-title">Error</h2><div class="error-box">{_h(ts.error_message)}</div></div>'

    mid = _h(state.mission_id)
    tid = _h(task_id)
    live_stream_section = f"""<div class="sec">
  <h2 class="section-title">Live Agent Stream <span id="sse-status" class="auto-label">(connecting...)</span></h2>
  <div id="live-stream" style="font-family:monospace;font-size:12px;line-height:1.5;background:#0d1117;color:#e6edf3;padding:14px 16px;border-radius:6px;height:420px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;"></div>
</div>
<script>
(function(){{
  var el=document.getElementById('live-stream');
  var st=document.getElementById('sse-status');
  var url='/mission/{mid}/task/{tid}/stream';
  var es=new EventSource(url);
  var autoScroll=true;
  el.addEventListener('scroll',function(){{autoScroll=el.scrollTop+el.clientHeight>=el.scrollHeight-20;}});
  es.onmessage=function(e){{
    var d=JSON.parse(e.data);
    el.textContent+=d.line+'\\n';
    if(autoScroll)el.scrollTop=el.scrollHeight;
    st.textContent='(live)';
  }};
  es.addEventListener('done',function(){{
    st.textContent='(complete \u2014 reloading...)';
    es.close();
    setTimeout(function(){{location.reload();}},1500);
  }});
  es.onerror=function(){{
    st.textContent='(disconnected)';
    es.close();
  }};
}})();
</script>"""

    breadcrumb = f'''<nav class="breadcrumb">
  <a href="/">Missions</a><span class="breadcrumb-sep">›</span>
  <a href="/mission/{_h(state.mission_id)}">{_h(state.spec.name)}</a><span class="breadcrumb-sep">›</span>
  <span>{_h(task_id)}</span>
</nav>'''

    body = f"""{breadcrumb}
<div class="page-head">
  <h1>{_h(task_spec.title)}</h1>
</div>
{stats}
{live_stream_section if is_active else ""}
<div class="sec"><h2 class="section-title">Worker Output</h2>{worker_out}</div>
<div class="sec"><h2 class="section-title">Reviewer Feedback {score_badge}</h2>{review_out}</div>
{extras}"""
    return _page(f"{task_id} — {state.spec.name}", body)
