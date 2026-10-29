import streamlit as st

from core.kill_switch import KillSwitch
from routes.artist_routes import ArtistRouter

router = ArtistRouter()

# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------

st.set_page_config(
    page_title="Artist Connection Explorer",
    page_icon="🎵",
    layout="wide"
)

# --------------------------------------------------
# CUSTOM CSS
# --------------------------------------------------

st.markdown("""
<style>

.main {
    background-color: #0e1117;
}

.block-container {
    padding-top: 2rem;
}

.big-title {
    text-align: center;
    font-size: 40px;
    font-weight: bold;
    color: #1DB954;
}

.sub-title {
    text-align: center;
    font-size: 18px;
    color: #cccccc;
}

.metric-card {
    background: #1e1e1e;
    padding: 15px;
    border-radius: 10px;
    text-align: center;
}

.result-box {
    background: #1e1e1e;
    padding: 15px;
    border-radius: 12px;
    border-left: 5px solid #1DB954;
}

.token-caption {
    color: #9a9a9a;
    font-size: 13px;
    margin-top: 4px;
}

</style>
""", unsafe_allow_html=True)

# --------------------------------------------------
# HEADER
# --------------------------------------------------

st.markdown(
    """
    <div class='big-title'>
        🎵 Artist Connection Explorer
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown(
    """
    <div class='sub-title'>
        Multi-Agent AI · Neo4j Graph · Ollama (Llama 3.1 8B) · LangSmith
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown("---")

# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

from monitoring.session_token_tracker import SessionTokenTracker
import config

if "messages" not in st.session_state:
    st.session_state.messages = []

if "last_trace" not in st.session_state:
    st.session_state.last_trace = None

if "token_tracker" not in st.session_state:
    st.session_state.token_tracker = SessionTokenTracker()

# Running totals across every query asked in this browser session —
# reset only when the page is reloaded or "Reset Session Stats" is
# clicked below.
if "total_tokens_session" not in st.session_state:
    st.session_state.total_tokens_session = 0

if "total_cost_session" not in st.session_state:
    st.session_state.total_cost_session = 0.0

if "total_queries_session" not in st.session_state:
    st.session_state.total_queries_session = 0

# --------------------------------------------------
# CHAT INPUT — processed FIRST, before anything else on the page
# renders. Streamlit re-runs this whole script top-to-bottom on every
# interaction; doing the query processing up here (instead of at the
# bottom, after the sidebar/dashboard have already drawn) is what
# makes the token counters below reflect THIS query immediately
# instead of lagging one interaction behind.
# --------------------------------------------------

usage = st.session_state.token_tracker.get_token_usage()

query = st.chat_input(
    "Ask about artist connections...",
    disabled=usage["total_tokens"] >= config.MAX_SESSION_TOKENS
)

if query:

    st.session_state.messages.append({"role": "user", "content": query})

    with st.spinner("🔍 Running Supervisor → Intent → Entity → Neo4j → Explanation..."):
        try:
            result = router.process_query(query)
            response = result["response"]
            tokens_this_query = result.get("total_tokens", 0)
            cost_this_query = result.get("total_cost_usd", 0.0)
            latency_this_query = result.get("latency_ms", 0.0)
            st.session_state.last_trace = result
        except Exception as e:
            response = f"Error: {str(e)}"
            tokens_this_query = 0
            cost_this_query = 0.0
            latency_this_query = 0.0
            st.session_state.last_trace = None

    st.session_state.total_tokens_session += tokens_this_query
    st.session_state.total_cost_session += cost_this_query
    st.session_state.total_queries_session += 1

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response,
            "tokens": tokens_this_query,
            "cost": cost_this_query,
            "latency_ms": latency_this_query,
        }
    )

# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------

with st.sidebar:

    st.header("📊 System Status")

    kill_status = KillSwitch.status()

    if kill_status["active"]:
        st.error("🔴 Kill Switch ENGAGED — AI processing blocked")
    else:
        st.success("🟢 AI Processing Active")

    st.info("Model : Llama 3.1 8B (Ollama)")
    

    st.markdown("---")
    st.subheader("🛑 Kill Switch Controls")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Engage", use_container_width=True):
            KillSwitch.engage(reason="Engaged from Streamlit UI")
            st.rerun()
    with col_b:
        if st.button("Disengage", use_container_width=True):
            KillSwitch.disengage()
            st.rerun()

    if kill_status["env_flag"].strip().lower() in ("1", "true", "yes", "on"):
        st.caption("⚠️ KILL_SWITCH_ENABLED=true in .env — Disengage above won't "
                   "help until that's changed too.")

    # ---- TOKEN USAGE (cumulative, updates live — see note above) ----
    st.markdown("---")
    st.header("🔢 Session Token Budget")

    usage = st.session_state.token_tracker.get_token_usage()

    used = usage["total_tokens"]
    limit = config.MAX_SESSION_TOKENS

    st.metric(
        "Session Tokens Used",
        f"{used} / {limit}"
    )

    progress = min(float(used) / float(limit), 1.0)

    st.progress(progress)

    if 0.8 <= progress < 1:
        st.warning("Approaching session token limit.")

    if progress >= 1:
        st.error("Session token limit exceeded.")


        st.markdown("---")
        st.header("🔢 Token Usage")

    tok_col1, tok_col2 = st.columns(2)
    with tok_col1:
        st.metric("Total Tokens (Session)", st.session_state.total_tokens_session)
    with tok_col2:
        st.metric("Total Cost (Session)", f"${st.session_state.total_cost_session:.5f}")

    st.caption(
        f"Across {st.session_state.total_queries_session} "
        f"quer{'y' if st.session_state.total_queries_session == 1 else 'ies'} this session"
    )

    if st.button(
    "Reset Session",
    use_container_width=True
):
        st.session_state.token_tracker.reset_token_usage()

        st.session_state.messages = []
        st.session_state.last_trace = None

        st.session_state.total_tokens_session = 0
        st.session_state.total_cost_session = 0.0
        st.session_state.total_queries_session = 0

        memory_keys = [
            "conversation_entities",
            "last_artist",
            "last_artists",
            "last_query_type",
            "conversation_summary",
            "last_collaborators"
        ]

        for key in memory_keys:
            if key in st.session_state:
                del st.session_state[key]

        st.rerun()

    if st.session_state.last_trace:
        st.markdown("---")
        st.subheader("🧭 Last Query")

        trace = st.session_state.last_trace
        st.metric("Tokens Used (This Query)", trace.get("total_tokens", 0))
        st.metric("Latency (This Query)", f"{trace['latency_ms']:.0f} ms")
        st.metric("Est. Cost (This Query)", f"${trace.get('total_cost_usd', 0):.5f}")

        with st.expander("Per-step breakdown"):
            for step in trace.get("trace", []):
                icon = "✅" if step["status"] == "success" else "❌"
                st.caption(
                    f"{icon} **{step['name']}** — {step['latency_ms']:.0f} ms"
                    + (f" — {step['total_tokens']} tok" if step["total_tokens"] else "")
                    + (f" — {step['error']}" if step.get("error") else "")
                )

    st.markdown("---")
    st.header("🧪 Sample Questions")

    st.markdown("""
    - How is Artist A connected to Artist B?

    - What song connects Artist A and Artist B?

    - Show collaboration network of Artist A

    - Show label mates of Artist A
    """)

# --------------------------------------------------
# DASHBOARD ROW
# --------------------------------------------------

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("🎤 Data Source", "Neo4j (live)")

with col2:
    st.metric("🤝 Relationships", "Graph Based")

with col3:
    st.metric("🧠 Model", "Llama3.1")

with col4:
    st.metric("🔢 Tokens Used (Session)", st.session_state.total_tokens_session)

st.markdown("---")

# --------------------------------------------------
# CHAT HISTORY — renders every message, including the one just
# processed above, each with its own per-query token/latency caption.
# --------------------------------------------------

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            st.markdown(
                f"<div class='result-box'>{message['content']}</div>",
                unsafe_allow_html=True,
            )
            if "tokens" in message:
                st.markdown(
                    f"<div class='token-caption'>"
                    f"🔢 Tokens used for this query: {message['tokens']} &nbsp;·&nbsp; "
                    f"⏱ {message.get('latency_ms', 0):.0f} ms &nbsp;·&nbsp; "
                    f"💰 ${message.get('cost', 0):.5f}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(message["content"])