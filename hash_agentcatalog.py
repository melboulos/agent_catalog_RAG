#!/usr/bin/env python3
# ============================================================
# hash_agentcatalog.py 
# Cache → Vector → LLM (ONLY if both miss or below threshold)
# Couchbase + FTS Vector + AWS Bedrock
# ============================================================

import json
import time
import logging
from datetime import datetime, timezone
import hashlib

import boto3
import requests
import streamlit as st
import pandas as pd
from requests.auth import HTTPBasicAuth

from couchbase.cluster import Cluster
from couchbase.auth import PasswordAuthenticator
from couchbase.options import ClusterOptions
from couchbase.exceptions import DocumentNotFoundException

from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

# ============================================================
# CONFIG
# ============================================================

CB_CONN_STR = "couchbases://cb.vtrwf6oxu2-2ster.cloud.couchbase.com"
CB_USERNAME = "cbimport"
CB_PASSWORD = "Cbimport123!"
CB_BUCKET = "agent_catalog"
CB_SCOPE = "agent_scope"
CB_QA_COLLECTION = "qa"
CB_AUDIT_COLLECTION = "audit_logs"

CB_FTS_URL = (
    "https://cb.vtrwf6oxu2-2ster.cloud.couchbase.com:18094/"
    "api/index/agent_catalog.agent_scope.agent_vector_idx/query"
)

BEDROCK_REGION = "us-east-1"
EMBED_MODEL_ID = "amazon.titan-embed-text-v1"
LLM_MODEL_ID = "meta.llama3-70b-instruct-v1:0"

CB_CA_BUNDLE = "/Users/melboulos/Downloads/vectorcluster-root-certificate.txt"

SCORE_THRESHOLD = 85
TOP_K = 10  # Number of vector hits to fetch

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ============================================================
# INIT CLIENTS
# ============================================================

auth = PasswordAuthenticator(CB_USERNAME, CB_PASSWORD)
cluster = Cluster(CB_CONN_STR, ClusterOptions(auth))
bucket = cluster.bucket(CB_BUCKET)
scope = bucket.scope(CB_SCOPE)

qa_col = scope.collection(CB_QA_COLLECTION)
audit_col = scope.collection(CB_AUDIT_COLLECTION)

logging.info("✅ Couchbase initialized")

bedrock_runtime = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
logging.info("✅ AWS Bedrock runtime ready")

# ============================================================
# BEDROCK HELPERS
# ============================================================

def get_embedding(text: str):
    response = bedrock_runtime.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({"inputText": text}),
        contentType="application/json",
        accept="application/json"
    )
    payload = json.loads(response["body"].read())
    return payload["embedding"]

def generate_answer(question: str):
    response = bedrock_runtime.invoke_model(
        modelId=LLM_MODEL_ID,
        body=json.dumps({"prompt": f"Answer concisely:\n\n{question}\n\nAnswer:"}),
        contentType="application/json",
        accept="application/json"
    )
    payload = json.loads(response["body"].read())
    return payload.get("generation") or payload.get("generations", [{}])[0].get("text", "")

# ============================================================
# VECTOR SEARCH (REST)
# ============================================================

def vector_search_rest(embedding):
    query = {
        "fields": ["answer"],
        "knn": [{
            "field": "embedding_vector",
            "vector": embedding,
            "k": TOP_K,
            "num_candidates": 10
        }]
    }

    r = requests.post(
        CB_FTS_URL,
        headers={"Content-Type": "application/json"},
        auth=HTTPBasicAuth(CB_USERNAME, CB_PASSWORD),
        data=json.dumps(query),
        verify=CB_CA_BUNDLE
    )

    if r.status_code != 200:
        logging.error(f"FTS error {r.status_code}: {r.text}")
        return []

    hits = r.json().get("hits", [])
    logging.info(f"🔍 Raw FTS hits count: {len(hits)}")
    return hits

# ============================================================
# AUDIT
# ============================================================

def save_audit(source, latency, vector_score, question, top3):
    # Only top 3 in audit
    audit_col.insert(
        str(time.time()),
        {
            "source": source,
            "latency": latency,
            "vector_score": vector_score,
            "question": question,
            "top3": top3[:3],
            "ts": datetime.now(timezone.utc).isoformat()
        }
    )
    logging.info(
        f"📝 Audit saved | source={source} | latency={latency} | vector_score={vector_score} | question='{question}'"
    )

# ============================================================
# SEMANTIC RERANKING
# ============================================================

def rerank_vector_hits(question: str, vector_rows: list):
    if not vector_rows:
        return vector_rows

    prompt_text = (
        "You are a semantic reranker.\n"
        "Rank the answers by relevance to the question.\n"
        "Return strict JSON only in the format: "
        "[{\"id\":0, \"score\":95}, {\"id\":1, \"score\":85}, ...]\n"
        f"Question:\n{question}\n\n"
        "Answers:\n" +
        "\n".join(f"{i}. {r['Answer']}" for i, r in enumerate(vector_rows)) +
        "\n\nDo not include any text outside the JSON array."
    )

    response = bedrock_runtime.invoke_model(
        modelId=LLM_MODEL_ID,
        body=json.dumps({"prompt": prompt_text}),
        contentType="application/json",
        accept="application/json"
    )

    payload = json.loads(response["body"].read())
    generation = payload.get("generation") or payload.get("generations", [{}])[0].get("text", "")

    logging.info(f"🧠 Raw reranker response: {generation.strip()}")

    # Clean generation: take only the first JSON array
    first_json_start = generation.find('[')
    first_json_end = generation.rfind(']') + 1
    cleaned = generation[first_json_start:first_json_end]

    try:
        ranks = json.loads(cleaned)
        for r in vector_rows:
            r['semantic_score'] = 0
        for rank in ranks:
            idx = rank['id']
            score = rank['score']
            if 0 <= idx < len(vector_rows):
                vector_rows[idx]['semantic_score'] = score
        vector_rows.sort(key=lambda x: x['semantic_score'], reverse=True)
    except Exception as e:
        logging.warning(f"⚠️ Reranker JSON parse failed after cleaning: {e}. Using FTS order.")
        for r in vector_rows:
            r['semantic_score'] = r['Vector Score']

    # Log semantic scores
    for i, r in enumerate(vector_rows):
        logging.info(f"🧠 Vector hits after rerank #{i}: vector_score={r['Vector Score']} | semantic_score={r['semantic_score']} | answer={r['Answer'][:60]}")

    return vector_rows[:3]

# ============================================================
# PIPELINE
# ============================================================

def run_pipeline(question: str):
    start = time.time()
    counters = {"Cache": 0, "Vector": 0, "LLM": 0}

    # ---------- CACHE ----------
    cache_answer = None
    doc_id = hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()
    try:
        doc = qa_col.get(doc_id)
        cache_answer = doc.content_as[dict]["answer"]
        counters["Cache"] += 1
        logging.info(f"🟡 Cache hit | question='{question}'")
    except DocumentNotFoundException:
        logging.info(f"🟡 Cache miss | question='{question}'")

    # ---------- VECTOR ----------
    embedding = get_embedding(question)
    logging.info(f"🧠 Embedding generated (len={len(embedding)})")

    hits = vector_search_rest(embedding)
    vector_rows = []

    if hits:
        max_score = max(h["score"] for h in hits)
        for h in hits[:TOP_K]:
            fields = h.get("fields", {})
            answer = fields.get("answer", "")
            if isinstance(answer, list):
                answer = answer[0] if answer else ""
            elif not isinstance(answer, str):
                answer = str(answer)

            score = round((h["score"] / max_score) * 100)

            vector_rows.append({
                "Source": "Vector",
                "Threshold": SCORE_THRESHOLD,
                "Vector Score": score,
                "Latency (ms)": int((time.time() - start) * 1000),
                "Answer": answer,
                "Below Threshold": score < SCORE_THRESHOLD,
                "semantic_score": 0
            })

        counters["Vector"] += len(vector_rows)

    # ---------- RERANK VECTOR ----------
    if vector_rows:
        vector_rows = rerank_vector_hits(question, vector_rows)

    # ---------- DEDUPLICATE CACHE AND VECTOR ----------
    all_rows = []
    seen_answers = set()
    if cache_answer:
        seen_answers.add(cache_answer)
        all_rows.append({
            "Source": "Cache",
            "Threshold": SCORE_THRESHOLD,
            "Vector Score": 100,
            "Latency (ms)": int((time.time() - start) * 1000),
            "Answer": cache_answer,
            "Below Threshold": False,
            "semantic_score": 100
        })

    for row in vector_rows:
        if row["Answer"] not in seen_answers:
            seen_answers.add(row["Answer"])
            all_rows.append(row)

    # ---------- CALCULATE VECTOR SCORE FOR AUDIT ----------
    vector_score = max((r["Vector Score"] for r in vector_rows), default=0)

    if all_rows:
        save_audit(
            source="Cache" if cache_answer else "Vector",
            latency=int((time.time() - start) * 1000),
            vector_score=vector_score,
            question=question,
            top3=all_rows[:TOP_K]
        )

    # ---------- LLM FALLBACK ----------
    if not all_rows or all(r["Vector Score"] < SCORE_THRESHOLD for r in all_rows):
        logging.info("🟢 LLM fallback for missing or below threshold answers")
        answer = generate_answer(question)
        counters["LLM"] += 1

        # Store in QA collection
        qa_col.upsert(doc_id, {
            "type": "agent_scope.qa",
            "question": question,
            "answer": answer,
            "embedding_vector": embedding,
            "ts": datetime.now(timezone.utc).isoformat()
        })

        row = {
            "Source": "LLM",
            "Threshold": SCORE_THRESHOLD,
            "Vector Score": 0,
            "Latency (ms)": int((time.time() - start) * 1000),
            "Answer": answer,
            "Below Threshold": False,
            "semantic_score": 0
        }

        all_rows.append(row)
        save_audit("LLM", row["Latency (ms)"], 0, question, [row])

    return all_rows, counters

# ============================================================
# STREAMLIT UI
# ============================================================

st.set_page_config(page_title="Agent Catalog", layout="wide")
st.title("Agent Catalog Q&A")

question = st.text_input("Ask a question")

if question and question.strip():
    results, counters = run_pipeline(question.strip())

    for i, row in enumerate(results):
        row["#"] = i + 1

    df = pd.DataFrame(results)
    df = df[[
        "#", "Source", "Threshold", "Vector Score", "semantic_score", "Latency (ms)", "Answer", "Below Threshold"
    ]]

    df = df.head(3)
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=False)
    gb.configure_column("#", width=40)
    gb.configure_column("Source", width=70)
    gb.configure_column("Threshold", width=50)
    gb.configure_column("Vector Score", width=60)
    gb.configure_column("semantic_score", width=60)
    gb.configure_column("Latency (ms)", width=60)
    gb.configure_column("Answer", width=900, wrapText=True)
    gb.configure_column("Below Threshold", width=60)

    cell_style_jscode = JsCode("""
    function(params) {
        if (params.value < 85 && params.data.Source === 'Vector') {
            return {'color': 'red', 'fontWeight': 'bold'};
        }
        return {};
    }
    """)
    gb.configure_column("Vector Score", cellStyle=cell_style_jscode)
    gb.configure_column("semantic_score", cellStyle=cell_style_jscode)

    gridOptions = gb.build()
    gridOptions['headerHeight'] = 40
    gridOptions['domLayout'] = 'autoHeight'

    AgGrid(
        df,
        gridOptions=gridOptions,
        fit_columns_on_grid_load=True,
        allow_unsafe_jscode=True
    )

    st.markdown(
        f"**Cache:** {counters['Cache']} &nbsp;&nbsp; "
        f"**Vector:** {counters['Vector']} &nbsp;&nbsp; "
        f"**LLM:** {counters['LLM']}"
    )

st.header("Audit Logs (last 20)")

query = f"""
SELECT a.*
FROM `{CB_BUCKET}`.`{CB_SCOPE}`.`{CB_AUDIT_COLLECTION}` a
ORDER BY a.ts DESC
LIMIT 20
"""

for row in cluster.query(query):
    audit = row
    ts = audit.get("ts", "")
    header = f"{audit['source']} | latency={audit['latency']}ms | ts={ts[11:19]}"
    with st.expander(header):
        st.json(audit)
