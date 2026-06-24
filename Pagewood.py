"""Streamlit Cloud entrypoint (kept for the existing Camberwell deployment).

Streamlit Community Cloud binds an app to its main-file path at creation and can't change
it afterwards. The Camberwell app was first created pointing at Pagewood.py, so this file
stays as its entry point. It runs the same shared app.py; the store identity (name,
categories, data) comes from that app's SUPABASE_* secrets + database, not the filename.
"""
import os
import runpy

runpy.run_path(os.path.join(os.path.dirname(__file__), "app.py"), run_name="__main__")
