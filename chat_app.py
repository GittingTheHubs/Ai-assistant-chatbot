"""
chat_app.py
-----------
Streamlit UI for the Monster Connect AI Sales Assistant.

This does NOT reimplement any chatbot logic. It imports process_question()
straight from main.py and just gives it a chat window instead of a
terminal input() loop. All your pricing rules, product matching, and RAG
logic in main.py are untouched and still fully in control of the answers.

Run:
    streamlit run chat_app.py

First launch will be slow: importing main.py triggers vector_v2.py, which
loads the embedding model and (if the DB doesn't exist yet) builds the
Chroma vector store from products_enriched.csv. This only happens once
per process, not once per chat message.

Make sure products_enriched.csv, vector_v2.py, and main.py are all in
the same folder as this file before running.
"""

import html
import re

import streamlit as st

# Importing main triggers: dataset load, LLM init, and (via vector_v2)
# the embedding model + vector store. This happens once per process,
# not once per message.
import main as bot


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Monster Connect AI Sales Assistant",
    page_icon="💬",
    layout="centered",
)


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 6rem;
            max-width: 760px;
        }

        #MainMenu, footer, header { visibility: hidden; }

        .chat-row {
            display: flex;
            align-items: flex-end;
            gap: 8px;
            margin: 14px 0;
        }
        .chat-row.user { justify-content: flex-end; }
        .chat-row.assistant { justify-content: flex-start; }

        .avatar {
            flex-shrink: 0;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
            background: #E8ECF7;
        }
        .avatar.user { background: #2F6FED; }

        .bubble {
            padding: 14px 18px;
            border-radius: 18px;
            max-width: 76%;
            line-height: 1.6;
            font-size: 0.95rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.06);
            word-wrap: break-word;
        }
        .bubble p { margin: 0 0 10px 0; }
        .bubble p:last-child { margin-bottom: 0; }
        .bubble ul, .bubble ol {
            margin: 4px 0 10px 0;
            padding-left: 20px;
        }
        .bubble ul:last-child, .bubble ol:last-child { margin-bottom: 0; }
        .bubble li { margin-bottom: 6px; }
        .bubble li:last-child { margin-bottom: 0; }

        .bubble.user {
            background: linear-gradient(135deg, #2F6FED, #4C8CFF);
            color: #ffffff;
            border-bottom-right-radius: 4px;
        }
        .bubble.assistant {
            background: #F3F4F8;
            color: #1a1a1a;
            border-bottom-left-radius: 4px;
        }

        .bubble-source {
            font-size: 0.7rem;
            opacity: 0.55;
            margin-top: 8px;
            font-style: italic;
        }

        /* The comparison engine answers with a markdown table.
           text_to_html() turns it into a real <table>; this is what
           makes it look like one. */
        .table-wrap {
            overflow-x: auto;
            margin: 4px 0 10px 0;
        }
        .table-wrap:last-child { margin-bottom: 0; }

        .bubble table {
            border-collapse: collapse;
            width: 100%;
            font-size: 0.85rem;
        }
        .bubble th, .bubble td {
            border: 1px solid #DDE1EC;
            padding: 6px 10px;
            text-align: left;
            vertical-align: top;
        }
        .bubble th {
            background: #E8ECF7;
            font-weight: 600;
            white-space: nowrap;
        }
        .bubble tbody tr:nth-child(even) td {
            background: #FAFBFE;
        }

        /* A three-column table needs more room than a sentence does. */
        .bubble.assistant:has(table) { max-width: 96%; }

        [data-testid="stChatInput"] {
            border-radius: 14px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("💬 Monster Connect AI Sales Assistant")
# st.caption(f"Model: {bot.MODEL}  ·  Products loaded: {len(bot.df)}")


# ============================================================
# SESSION STATE
# ============================================================

if "messages" not in st.session_state:
    st.session_state.messages = []          # what's rendered in the UI
if "memory" not in st.session_state:
    st.session_state.memory = []            # what process_question() reads/writes
if "active_product" not in st.session_state:
    st.session_state.active_product = None
if "current_category" not in st.session_state:
    st.session_state.current_category = None


# ============================================================
# READABILITY / HTML RENDERING HELPER
# ============================================================
# The wording of answers comes from the prompt in main.py -- this app
# never changes what the AI says. We convert the raw text into real
# HTML (<p>, <ul><li>) ourselves and render the WHOLE bubble as one
# HTML string in a single st.markdown call. Building it as one string
# (instead of opening/closing divs across separate calls) is what
# actually keeps the text inside the colored box.

BULLET_RE = re.compile(r"^[•\-\*]\s+")
NUMBERED_RE = re.compile(r"^\d+[\.\)]\s+")

# A markdown table row looks like "| a | b |". The separator row
# under the header ("| --- | --- |") carries no data.
TABLE_ROW_RE = re.compile(r"^\|.*\|$")
TABLE_SEP_RE = re.compile(r"^\|[\s:\-]+(\|[\s:\-]+)*\|$")


def split_table_row(line: str):
    """The cells of one markdown row, outer pipes dropped."""

    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table_to_html(rows) -> str:
    """
    Turn buffered markdown rows into a real <table>.

    The comparison engine in main.py answers with a markdown table.
    Streamlit's own markdown renderer never sees it, because we hand
    it one finished HTML string per bubble, so without this the
    pipes would show up literally.
    """

    body = [row for row in rows if not TABLE_SEP_RE.match(row)]

    if not body:
        return ""

    header = "".join(
        f"<th>{html.escape(cell)}</th>"
        for cell in split_table_row(body[0])
    )

    lines_html = []

    for row in body[1:]:

        cells = "".join(
            f"<td>{html.escape(cell)}</td>"
            for cell in split_table_row(row)
        )

        lines_html.append(f"<tr>{cells}</tr>")

    return (
        '<div class="table-wrap"><table>'
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(lines_html)}</tbody>"
        "</table></div>"
    )


def text_to_html(text: str) -> str:
    text = text.strip()
    lines = [ln.strip() for ln in text.split("\n") if ln.strip() != ""]

    html_parts = []
    bullet_buffer = []
    table_buffer = []

    def flush_bullets():
        if bullet_buffer:
            items = "".join(f"<li>{b}</li>" for b in bullet_buffer)
            html_parts.append(f"<ul>{items}</ul>")
            bullet_buffer.clear()

    def flush_table():
        if table_buffer:
            html_parts.append(table_to_html(table_buffer))
            table_buffer.clear()

    for ln in lines:

        if TABLE_ROW_RE.match(ln):
            flush_bullets()
            table_buffer.append(ln)
            continue

        flush_table()

        escaped = html.escape(ln)
        is_bullet = bool(BULLET_RE.match(ln) or NUMBERED_RE.match(ln))

        if is_bullet:
            cleaned = BULLET_RE.sub("", escaped)
            cleaned = NUMBERED_RE.sub("", cleaned)
            bullet_buffer.append(cleaned)
        else:
            flush_bullets()
            html_parts.append(f"<p>{escaped}</p>")

    flush_bullets()
    flush_table()
    return "".join(html_parts)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.subheader("Session")

    if st.session_state.active_product:
        st.markdown(f"**Active product:** {st.session_state.active_product}")
    else:
        st.markdown("**Active product:** _none yet_")

    if st.session_state.current_category:
        st.markdown(f"**Category filter:** {st.session_state.current_category}")

    debug = st.toggle("Show debug info", value=False)

    st.divider()

    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.memory = []
        st.session_state.active_product = None
        st.session_state.current_category = None
        st.rerun()


# ============================================================
# RENDER A SINGLE BUBBLE (one HTML string, one st.markdown call)
# ============================================================

def render_bubble(role: str, raw_text: str, source: str = None):
    avatar = "🧑" if role == "user" else "🤖"
    body_html = text_to_html(raw_text)

    source_html = ""
    if source:
        source_html = f'<div class="bubble-source">via {html.escape(source)}</div>'

    if role == "user":
        row_html = f"""
        <div class="chat-row user">
            <div class="bubble user">{body_html}</div>
            <div class="avatar user">{avatar}</div>
        </div>
        """
    else:
        row_html = f"""
        <div class="chat-row assistant">
            <div class="avatar">{avatar}</div>
            <div class="bubble assistant">{body_html}{source_html}</div>
        </div>
        """

    st.markdown(row_html, unsafe_allow_html=True)


# ============================================================
# RENDER EXISTING CHAT HISTORY
# ============================================================

for msg in st.session_state.messages:
    render_bubble(msg["role"], msg["content"], msg.get("source"))


# ============================================================
# CHAT INPUT
# ============================================================

question = st.chat_input("Ask about a product, e.g. Safetica ราคาเท่าไหร่")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    render_bubble("user", question)

    with st.spinner("Thinking..."):
        try:
            (
                answer,
                st.session_state.active_product,
                st.session_state.current_category,
                answer_type,
            ) = bot.process_question(
                question=question,
                active_product=st.session_state.active_product,
                current_category=st.session_state.current_category,
                memory=st.session_state.memory,
                debug=debug,
            )
        except Exception as e:
            answer = f"Sorry, something went wrong: {type(e).__name__}: {e}"
            answer_type = "Error"

    render_bubble("assistant", answer, answer_type)

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "source": answer_type}
    )
    bot.add_memory(
        memory=st.session_state.memory,
        question=question,
        answer=answer,
        product=st.session_state.active_product,
    )