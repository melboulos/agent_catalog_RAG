<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent Catalog RAG — Project Notes</title>
<style>
body { font-family: Arial, sans-serif; line-height: 1.6; margin: 20px; max-width: 1000px; }
h1, h2, h3, h4 { color: #2c3e50; }
code { background-color: #f4f4f4; padding: 2px 4px; border-radius: 3px; font-family: monospace; }
pre { background-color: #f4f4f4; padding: 10px; border-radius: 5px; overflow-x: auto; }
hr { border: none; border-top: 1px solid #ccc; margin: 20px 0; }
ul { margin-left: 20px; }
.highlight-red { color: red; font-weight: bold; }
</style>
</head>
<body>

<h1>Agent Catalog RAG — Project Notes</h1>
<ul>
<li>These notes describe the design, implementation, and key details of the <strong>Agent Catalog RAG system</strong>.</li>
</ul>
<hr>

<h2>1. Overview</h2>
<ul>
<li>Agent Catalog Q&A is a production-ready question-answering pipeline that integrates:</li>
<ul>
<li>Couchbase: Cache & vector store</li>
<li>FTS (Full Text Search): Fast vector candidate retrieval</li>
<li>AWS Bedrock:
  <ul>
    <li>Titan embeddings for vector search</li>
    <li>LLaMA3 LLM for answer generation and semantic reranking</li>
  </ul>
</li>
<li>Streamlit: Interactive front-end for Q&A and audit visualization</li>
</ul>
<li>The system prioritizes <strong>speed and relevance</strong>:
  <ul>
    <li>Cache → return cached answer if available</li>
    <li>Vector Search → retrieve vector candidates from Couchbase FTS</li>
    <li>Semantic Reranking → rerank vector hits using LLM</li>
    <li>Threshold Evaluation → display vector answers above threshold; below threshold answers are highlighted in red</li>
    <li>LLM Fallback → generate answer only if vector fails threshold or cache is missing</li>
    <li>Audit Logging → store all results, scores, and latency</li>
  </ul>
</li>
</ul>

<hr>
<h2>2. Data Flow</h2>
<pre><code>
User Question
       ↓
   Pipeline
       ├─ Cache lookup in Couchbase QA collection
       │      └─ Return if found
       ├─ Vector Search using Titan embeddings
       │      ├─ Retrieve top-k hits via FTS
       │      └─ Normalize scores to 0–100
       ├─ Semantic Rerank via LLM
       │      └─ Adds semantic_score for each vector hit
       ├─ Threshold Evaluation
       │      └─ Below-threshold vectors trigger LLM fallback
       └─ LLM Fallback via Bedrock
              └─ Answer generated & stored in QA collection
       ↓
     Audit logging
       ↓
   Streamlit UI display
</code></pre>

<hr>
<h2>3. Couchbase Configuration</h2>
<ul>
<li>Bucket / Collections:
  <ul>
    <li>Bucket: <code>agent_catalog</code></li>
    <li>Scope: <code>agent_scope</code></li>
    <li>QA Collection: <code>qa</code></li>
    <li>Audit Logs Collection: <code>audit_logs</code></li>
  </ul>
</li>
<li>FTS Vector Index:
  <ul>
    <li>Name: <code>agent_vector_idx</code></li>
    <li>Fields indexed: <code>embedding_vector</code>, <code>answer</code></li>
    <li>Used for semantic search via REST API</li>
  </ul>
</li>
<li>Connection Settings:
<pre><code>
Connection string: couchbases://&lt;cluster-address&gt;
Username: cbimport
Password: &lt;password&gt;
CA Bundle: &lt;path-to-root-certificate&gt;
</code></pre>
</li>
</ul>

<hr>
<h2>4. AWS Bedrock Integration</h2>
<ul>
<li>Uses AWS Bedrock for both embedding generation and LLM-powered answer generation</li>
<li>Embedding Model:
  <ul>
    <li>Model: <code>amazon.titan-embed-text-v1</code></li>
    <li>Purpose: Generates vector embeddings for semantic search in Couchbase</li>
  </ul>
</li>
<li>LLM Model:
  <ul>
    <li>Model: <code>meta.llama3-70b-instruct-v1:0</code></li>
    <li>Purpose:
      <ul>
        <li>Semantic reranking of vector hits</li>
        <li>Generating answers when cache or vector results are missing or below threshold</li>
      </ul>
    </li>
  </ul>
</li>
<li>Boto3 Client Initialization:
<pre><code>import boto3
bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1")
</code></pre>
</li>
<li>Embedding Generation:
<pre><code>def get_embedding(text: str):
    response = bedrock_runtime.invoke_model(
        modelId="amazon.titan-embed-text-v1",
        body=json.dumps({"inputText": text}),
        contentType="application/json",
        accept="application/json"
    )
    payload = json.loads(response["body"].read())
    return payload["embedding"]
</code></pre>
</li>
<li>LLM Answer Generation:
<pre><code>def generate_answer(question: str):
    response = bedrock_runtime.invoke_model(
        modelId="meta.llama3-70b-instruct-v1:0",
        body=json.dumps({"prompt": f"Answer concisely:\n\n{question}\n\nAnswer:"}),
        contentType="application/json",
        accept="application/json"
    )
    payload = json.loads(response["body"].read())
    return payload.get("generation") or payload.get("generations", [{}])[0].get("text", "")
</code></pre>
</li>
</ul>

<hr>
<h2>5. Vector Search and Semantic Reranking</h2>
<ul>
<li>Uses Couchbase FTS with vectors to retrieve semantically relevant answers</li>
<li>Vector Search via REST:
<pre><code>import requests
from requests.auth import HTTPBasicAuth

def vector_search_rest(embedding):
    query = {
        "fields": ["answer"],
        "knn": [{
            "field": "embedding_vector",
            "vector": embedding,
            "k": 10,
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
</code></pre>
</li>
<li>Semantic Reranking using LLM
<pre><code>def rerank_vector_hits(question: str, vector_rows: list):
    # Reranker logic, parse JSON, update semantic_score
    return vector_rows[:3]
</code></pre>
</li>
<li>Top 3 reranked answers returned</li>
</ul>

<hr>
<h2>6. Cache Handling and Deduplication</h2>
<ul>
<li>Cache lookup in Couchbase to avoid repeated LLM calls</li>
<li>Deduplicate answers from cache and vector search</li>
<pre><code>import hashlib
from couchbase.exceptions import DocumentNotFoundException

doc_id = hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()
cache_answer = None
try:
    doc = qa_col.get(doc_id)
    cache_answer = doc.content_as[dict]["answer"]
    logging.info(f"🟡 Cache hit | question='{question}'")
except DocumentNotFoundException:
    logging.info(f"🟡 Cache miss | question='{question}'")
</code></pre>
</ul>

<hr>
<h2>7. LLM Fallback Logic</h2>
<ul>
<li>Trigger LLM only if cache/vector below threshold</li>
<pre><code>if not all_rows or all(r["Vector Score"] &lt; SCORE_THRESHOLD for r in all_rows):
    logging.info("🟢 LLM fallback for missing or below threshold answers")
    answer = generate_answer(question)
qa_col.upsert(doc_id, {
    "type": "agent_scope.qa",
    "question": question,
    "answer": answer,
    "embedding_vector": embedding,
    "ts": datetime.now(timezone.utc).isoformat()
})
row = {...}
all_rows.append(row)
</code></pre>
</ul>

<hr>
<h2>8. Streamlit UI and Grid Display</h2>
<ul>
<li>Page setup, question input, results table, AG-Grid formatting</li>
<li>Display last 20 audit logs with expanders</li>
</ul>

<hr>
<h2>9. Audit and Logging</h2>
<ul>
<li>Logging configuration with INFO level</li>
<li>Save audit documents in Couchbase audit_logs collection
<pre><code>def save_audit(source, latency, vector_score, question, top3):
    audit_col.insert(str(time.time()), {...})
    logging.info(f"📝 Audit saved | source={source} | latency={latency} | vector_score={vector_score} | question='{question}'")
</code></pre>
</li>
</ul>

<hr>
<h2>10. Deployment and Production Notes</h2>
<ul>
<li>System requirements: Python 3.10+, Streamlit, Couchbase 8+, AWS Bedrock, TLS/CA bundle</li>
<li>Configuration: Update hash_agentcatalog.py with credentials, set SCORE_THRESHOLD and TOP_K</li>
<li>Run app: <code>streamlit run hash_agentcatalog.py</code></li>
<li>Deployment considerations: security, scalability, monitoring, maintenance</li>
<li>Summary: end-to-end QA pipeline integrating Couchbase, semantic reranking, AWS Bedrock, audit logging, Streamlit UI</li>
</ul>

</body>
</html>
