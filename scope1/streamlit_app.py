import requests
import streamlit as st

try:
    BACKEND = st.secrets["BACKEND_URL"]
except Exception:
    BACKEND = "http://127.0.0.1:8000"   # used when running locally

st.set_page_config(page_title="Document to Markdown")
st.title("Document → Markdown")

tool = st.selectbox("Choose tool", ["docling", "markitdown", "open-source"])
mode = st.radio("Input type", ["Upload PDF", "Enter URL"])

# open-source uses /extract, docling & markitdown use /standardize
path = "extract" if tool == "open-source" else "standardize"
params = {} if tool == "open-source" else {"tool": tool}


def find_markdown(obj):
    """Look through the API's JSON for the Markdown text."""
    if isinstance(obj, dict):
        for key in ("markdown", "md", "content", "text"):
            if isinstance(obj.get(key), str):
                return obj[key]
        for value in obj.values():
            found = find_markdown(value)
            if found:
                return found
    return None


response = None
try:
    if mode == "Upload PDF":
        file = st.file_uploader("Upload a PDF", type="pdf")
        if file and st.button("Convert"):
            with st.spinner(f"Processing with {tool}..."):
                response = requests.post(
                    f"{BACKEND}/pdf/{path}",
                    files={"file": (file.name, file.getvalue(), "application/pdf")},
                    params=params,
                    timeout=600,
                )
    else:
        url = st.text_input("Enter a URL", placeholder="https://en.wikipedia.org/wiki/India")
        if url and st.button("Convert"):
            with st.spinner("Processing..."):
                response = requests.post(
                    f"{BACKEND}/url/{path}",
                    json={"url": url},
                    params=params,
                    timeout=600,
                )
except requests.exceptions.ConnectionError:
    st.error("Cannot reach the backend. Is the uvicorn server running?")

if response is not None:
    if response.ok:
        data = response.json()
        md = find_markdown(data)
        if md:
            tab1, tab2 = st.tabs(["Preview", "Raw Markdown"])
            tab1.markdown(md)
            tab2.code(md, language="markdown")
            st.download_button("Download Markdown", md, file_name="output.md")
        else:
            st.warning("Done, but I couldn't find Markdown text in the response.")
        with st.expander("Full response from API (includes S3 links)"):
            st.json(data)
    else:
        st.error(f"Error {response.status_code}: {response.text}")