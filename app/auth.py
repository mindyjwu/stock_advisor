"""
Login / signup gate for the Streamlit dashboard.

Call require_login() at the top of the app: it returns the signed-in user
dict, or renders the sign-in screen and stops the script. Each browser
session sees only its own account's data — everything downstream is scoped
by the returned user id.
"""
import streamlit as st

from db.users import init_users, create_user, authenticate, USERNAME_RULES


def require_login() -> dict:
    init_users()
    if st.session_state.get("user"):
        return st.session_state["user"]

    st.markdown("""
    <div style="text-align:center;margin:2.5rem 0 1rem 0">
      <div style="font-size:2rem;font-weight:800;color:#0f172a">📈 Stock Advisor</div>
      <div style="color:#64748b;font-size:.95rem;margin-top:.3rem">
        AI-scored stock ideas and a plain-English investing plan — sized to your own portfolio.
      </div>
      <div style="color:#94a3b8;font-size:.8rem;margin-top:.4rem">
        🔒 Your watchlist, portfolio and history are private to your account.
      </div>
    </div>
    """, unsafe_allow_html=True)

    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        tab_in, tab_up = st.tabs(["🔑 Sign in", "✨ Create account"])

        with tab_in:
            with st.form("login_form"):
                u = st.text_input("Username", key="login_user")
                p = st.text_input("Password", type="password", key="login_pw")
                if st.form_submit_button("Sign in", use_container_width=True):
                    user = authenticate(u, p)
                    if user:
                        st.session_state.clear()  # drop any leftover data from a prior account
                        st.session_state["user"] = user
                        st.rerun()
                    else:
                        st.error("Wrong username or password.")

        with tab_up:
            with st.form("signup_form"):
                nu = st.text_input("Pick a username", help=USERNAME_RULES, key="su_user")
                nn = st.text_input("Your name (shown in the app)", key="su_name")
                p1 = st.text_input("Password (8+ characters)", type="password", key="su_pw1")
                p2 = st.text_input("Repeat password", type="password", key="su_pw2")
                if st.form_submit_button("Create my account", use_container_width=True):
                    if p1 != p2:
                        st.error("Passwords don't match.")
                    else:
                        res = create_user(nu, p1, nn)
                        if "error" in res:
                            st.error(res["error"])
                        else:
                            st.session_state.clear()
                            st.session_state["user"] = res["user"]
                            st.rerun()
            st.caption("New accounts start with a small example watchlist you can edit in Settings, "
                       "and an empty portfolio you can fill by importing a CSV.")

    st.stop()


def logout():
    st.session_state.clear()
    st.rerun()
