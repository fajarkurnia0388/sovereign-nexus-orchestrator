import streamlit as st
import asyncio
import yaml
import os
from src.core.engine import SNOEngine, PlaybookCompiler
from src.mcp.tools import TOOL_REGISTRY

# Setup Page Config
st.set_page_config(page_title="SNO Ops Console", page_icon="🌌", layout="wide")

# Initialize SNO Engine in session state
if "sno" not in st.session_state:
    st.session_state.sno = SNOEngine()
    st.session_state.compiler = PlaybookCompiler(TOOL_REGISTRY)

sno = st.session_state.sno
compiler = st.session_state.compiler

st.title("🌌 SNO Ops Console")
st.markdown("### Sovereign Nexus Orchestrator Management Dashboard")

# Sidebar Navigation
menu = st.sidebar.selectbox("Navigation", ["Dashboard", "Playbook Manager", "Knowledge Nexus", "System Logs"])

# ------------------------------------------------------------------------------
# 1. DASHBOARD - Job Monitoring
# ------------------------------------------------------------------------------
if menu == "Dashboard":
    st.header("🚀 Job Monitoring")
    
    # Job Trigger Area
    with st.expander("Trigger New Playbook", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            pb_name = st.text_input("Playbook Name", value="deep_research")
        with col2:
            query = st.text_input("Query / Input", value="AI Agents 2026")
        
        if st.button("Execute Playbook"):
            # Simulating the MCP call
            yaml_path = f"playbooks/{pb_name}.yaml"
            if os.path.exists(yaml_path):
                graph = compiler.compile(yaml_path)
                job_id = "job_" + str(len(sno.jobs))
                sno.jobs[job_id] = {"status": "queued", "result": None}
                
                # Run async in background
                asyncio.run(sno.run_job(job_id, graph, query)) 
                st.success(f"Job started! ID: {job_id}")
            else:
                st.error("Playbook file not found!")

    # Job List Table
    st.subheader("Active & Past Jobs")
    if not sno.jobs:
        st.info("No jobs found. Trigger one above!")
    else:
        import pandas as pd
        df = pd.DataFrame.from_dict(sno.jobs, orient='index').reset_index()
        df.columns = ['JobID', 'Status', 'Result']
        st.table(df)

# ------------------------------------------------------------------------------
# 2. PLAYBOOK MANAGER - YAML Editor
# ------------------------------------------------------------------------------
elif menu == "Playbook Manager":
    st.header("📜 Playbook Manager")
    
    pb_files = [f for f in os.listdir("playbooks") if f.endswith(".yaml")]
    selected_pb = st.selectbox("Select Playbook", pb_files)
    
    if selected_pb:
        path = f"playbooks/{selected_pb}"
        with open(path, "r") as f:
            content = f.read()
        
        new_content = st.text_area("Edit Playbook YAML", value=content, height=400)
        
        if st.button("Save Playbook"):
            with open(path, "w") as f:
                f.write(new_content)
            st.success("Playbook updated successfully!")

# ------------------------------------------------------------------------------
# 3. KNOWLEDGE NEXUS - Hybrid Search
# ------------------------------------------------------------------------------
elif menu == "Knowledge Nexus":
    st.header("🧠 Knowledge Nexus Explorer")
    
    query = st.text_input("Search Hybrid Memory (Vector + Graph)")
    if query:
        # Simulating hybrid_query tool
        entity = next((v for k, v in sno.knowledge_base["entities"].items() if k.lower() in query.lower()), "Not found")
        fact = next((f for f in sno.knowledge_base["facts"] if any(word in f.lower() for word in query.lower().split())), "Not found")
        
        st.write("### Results")
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Entity:**\n{entity}")
        with col2:
            st.info(f"**Related Fact:**\n{fact}")

# ------------------------------------------------------------------------------
# 4. SYSTEM LOGS
# ------------------------------------------------------------------------------
elif menu == "System Logs":
    st.header("📋 System Logs")
    st.text_area("Raw Execution Logs", value="SNO Server started...\nListening for MCP requests...\nReady.", height=500)
