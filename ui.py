# =====================================================
# STREAMLIT UI — FIXED NO DUPLICATE VERSION
# =====================================================

import streamlit as st
import time
import json
import os
from testsql import ask

# =====================================================
# PAGE CONFIG
# =====================================================

st.set_page_config(
    page_title="SFR Assistant",
    layout="wide"
)


# =====================================================
# SESSION STATE
# =====================================================

if "messages" not in st.session_state:

    st.session_state.messages = []


# =====================================================
# CUSTOM CSS
# =====================================================

st.markdown("""
<style>

/* HIDE STREAMLIT UI */

#MainMenu {
    visibility: hidden;
}

header {
    visibility: hidden;
}

footer {
    visibility: hidden;
}

[data-testid="stToolbar"] {
    display: none !important;
}

[data-testid="stDecoration"] {
    display: none !important;
}

[data-testid="collapsedControl"] {
    display: none !important;
}

.stDeployButton {
    display: none !important;
}

/* APP BACKGROUND */

.stApp {
    background: radial-gradient(circle at top right, #0f172a, #020617);
    color: #e2e8f0;
}

/* CHAT INPUT */

.stChatInput input[type="text"] {

    background: linear-gradient(
        135deg,
        #1e293b,
        #334155
    ) !important;

    color: #e2e8f0 !important;

    border: 2px solid #475569 !important;

    border-radius: 25px !important;

    padding: 15px 20px !important;

    font-size: 16px !important;
}

.stChatInput input[type="text"]:focus {

    border-color: #60a5fa !important;

    box-shadow: 0 0 0 3px rgba(
        96,
        165,
        250,
        0.2
    ) !important;
}

/* REMOVE AVATARS */

[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {

    display: none !important;
}

/* CHAT MESSAGE */

[data-testid="stChatMessage"] {

    background-color: transparent !important;

    padding: 0px !important;

    margin-bottom: 20px !important;
}

/* USER MESSAGE */

.user-msg {

    background: linear-gradient(
        135deg,
        #3b82f6 0%,
        #2563eb 100%
    );

    color: white;

    padding: 16px 24px;

    border-radius: 24px 24px 4px 24px;

    width: fit-content;

    max-width: 80%;

    margin-left: auto;

    box-shadow: 0 8px 25px rgba(
        37,
        99,
        235,
        0.4
    );

    line-height: 1.6;

    font-size: 15px;
}

/* BOT MESSAGE */

.bot-msg {

    background: linear-gradient(
        135deg,
        #1e293b 0%,
        #0f172a 100%
    );

    color: #cbd5e1;

    padding: 16px 24px;

    border-radius: 24px 24px 24px 4px;

    width: fit-content;

    max-width: 85%;

    border: 1px solid #475569;

    box-shadow: 0 8px 25px rgba(
        0,
        0,
        0,
        0.4
    );

    line-height: 1.6;

    font-size: 15px;
}

/* TITLE */

.main-title {

    background: linear-gradient(
        to right,
        #60a5fa,
        #a78bfa
    );

    -webkit-background-clip: text;

    -webkit-text-fill-color: transparent;

    font-size: 52px;

    font-weight: 800;

    text-align: center;

    margin-top: 20px;

    margin-bottom: 40px;
}

/* SIDEBAR */

section[data-testid="stSidebar"] {

    background: #0f172a;

    border-right: 1px solid #1e293b;
}

</style>
""", unsafe_allow_html=True)

# =====================================================
# SIDEBAR
# =====================================================

with st.sidebar:

    st.markdown(
        """
        <h2 style="
            color:#60a5fa;
            text-align:center;
            font-size:32px;
            margin-bottom:20px;
        ">
            SFR
        </h2>
        """,
        unsafe_allow_html=True
    )

    # =================================================
    # NEW CHAT BUTTON
    # =================================================

    if st.button(
        "➕ New Chat",
        use_container_width=True,
        type="primary"
    ):

        st.session_state.messages = []

        # REMOVE OLD GRAPHS

        keys_to_remove = []

        for key in st.session_state.keys():

            if key.startswith("graph_"):

                keys_to_remove.append(key)

        for key in keys_to_remove:

            del st.session_state[key]

        st.rerun()

    st.write("---")

    st.info(
        "💬 Single chat session\n\n"
        "Click 'New Chat' to start fresh"
    )

# =====================================================
# TITLE
# =====================================================

st.markdown(
    '<div class="main-title">SFR ASSISTANT</div>',
    unsafe_allow_html=True
)

# =====================================================
# DISPLAY CHAT HISTORY
# =====================================================

for i, message in enumerate(st.session_state.messages):

    with st.chat_message(message["role"]):

        style = (
            "user-msg"
            if message["role"] == "user"
            else "bot-msg"
        )

        st.markdown(
    f"""
<div class="{style}">
<div style="white-space: pre-wrap; line-height: 1.8; ">
{message["content"]}
</div>
</div>
""",
    unsafe_allow_html=True
)


        # =================================================
        # SHOW GRAPH
        # =================================================

        if (
            message["role"] == "assistant"
            and message.get("has_graph")
        ):

            graph_key = f"graph_{i}"

            if graph_key in st.session_state:

                st.plotly_chart(
                    st.session_state[graph_key],
                    use_container_width=True,
                    key=graph_key
                )

# =====================================================
# CHAT INPUT
# =====================================================

prompt = st.chat_input(
    "💬 Ask about railway failures..."
)

# =====================================================
# PROCESS INPUT
# =====================================================

if prompt:

    # =================================================
    # SAVE USER MESSAGE
    # =================================================

    user_message = {
        "role": "user",
        "content": prompt
    }

    st.session_state.messages.append(
        user_message
    )

    # =================================================
    # PROCESS QUERY
    # =================================================

    with st.status(
        " Analyzing failure logs...",
        expanded=False
    ) as status:

        status.update(
            label="Processing...",
            state="running"
        )

        time.sleep(0.3)

        try:

            result = ask(prompt)

            answer = result.get(
                "answer",
                "No response generated."
            )

            graph = result.get("graph")

            status.update(
                label="Analysis Complete",
                state="complete"
            )

        except Exception as e:

            answer = f"Error: {str(e)}"

            graph = None

            status.update(
                label="Error occurred",
                state="error"
            )

    # =================================================
    # ASSISTANT MESSAGE
    # =================================================

    assistant_message = {
        "role": "assistant",
        "content": answer
    }

    # =================================================
    # STORE GRAPH
    # =================================================

    if graph is not None:

        assistant_message["has_graph"] = True

        graph_key = (
            f"graph_{len(st.session_state.messages)}"
        )

        st.session_state[graph_key] = graph

    # =================================================
    # SAVE MESSAGE
    # =================================================

    st.session_state.messages.append(
        assistant_message
    )

    # =================================================
    # FORCE CLEAN RERUN
    # =================================================

    st.rerun()