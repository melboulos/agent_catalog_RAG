<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent Catalog RAG — Project Notes</title>
<style>
body {
    font-family: Arial, sans-serif;
    line-height: 1.6;
    margin: 20px;
    max-width: 1000px;
}
h1, h2, h3, h4 {
    color: #2c3e50;
}
code {
    background-color: #f4f4f4;
    padding: 2px 4px;
    border-radius: 3px;
    font-family: monospace;
}
pre {
    background-color: #f4f4f4;
    padding: 10px;
    border-radius: 5px;
    overflow-x: auto;
}
hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 20px 0;
}
ul {
    margin-left: 20px;
}
.highlight-red {
    color: red;
    font-weight: bold;
}
</style>
</head>
<body>

<h1>Agent Catalog RAG — Project Notes</h1>
<p>These notes describe the design, implementation, and key details of the <strong>Agent Catalog RAG system</strong>.</p>
<hr>

<h2>1. Overview</h2>
<p><strong>Agent Catalog Q&A</strong> is a production-ready question-answering pipeline that integrates:</p>
<ul>
<li><strong>Couchbase</strong>: Cache & vector store</li>
<li><strong>FTS (Full Text Search)</strong>: Fast vector candidate retrieval</li>
<li><strong>AWS Bedrock</strong>:
    <ul>
        <li><strong>Titan embeddings</strong> for vector search</li>
        <li><strong>LLaMA3 LLM</strong> for answer generation and semantic reranking</li>
    </ul>
</li>
<li><strong>Streamlit</strong>: Interactive front-end for Q&A and audit visualization</li>
</ul>
<p>The system prioritizes <strong>speed and relevance</strong>:</p>
<ol>
<li><strong>Cache</strong> → return cached answer if available.</li>
<li><strong>Vector Search</strong> → retrieve vector candidates from Couchbase FTS.</li>
<li><strong>Semantic Reranking</strong> → rerank vector hits using LLM.</li>
<li><strong>Threshold Evaluation</strong> → display vector answers above threshold; below threshold answers are highlighted in red.</li>
<li><strong>LLM Fallback</strong> → generate answer only if vector fails threshold or cache is missing.</li>
<li><strong>Audit Logging</strong> → store all results, scores, and latency.</li>
</ol>

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
<p><strong>Bucket / Collections:</strong></p>
<ul>
<li>Bucket: <code>agent_catalog</code></li>
<li>Scope: <code>agent_scope</code></li>
<li>QA Collection: <code>qa</code></li>
<li>Audit Logs Collection: <code>audit_logs</code></li>
</ul>
<p><strong>FTS Vector Index:</strong></p>
<ul>
<li>Name: <code>agent_vector_idx</code></li>
<li>Fields indexed: <code>embedding_vector</code>, <code>answer</code></li>
<li>Used for <strong>semantic search</strong> via REST API</li>
</ul>
<p><strong>Connection Settings:</strong></p>
<pre><code>
Connection string: couchbases://&lt;cluster-address&gt;
Username: cbimport
Password: &lt;password&gt;
CA Bundle: &lt;path-to-root-certificate&gt;
</code></pre>

<hr>
<h2>4. AWS Bedrock Integration</h2>
<p>This project uses <strong>AWS Bedrock</strong> for both embedding generation and LLM-powered answer generation.</p>

<h3>Embedding Model</h3>
<ul>
<li>Model: <code>amazon.titan-embed-text-v1</code></li>
<li>Purpose: Generates vector embeddings for the user query to enable semantic search in Couchbase.</li>
</ul>

<h3>LLM Model</h3>
<ul>
<li>Model: <code>meta.llama3-70b-instruct-v1:0</code></li>
<li>Purpose:
    <ul>
        <li>Semantic reranking of vector hits</li>
        <li>Generating answers when both cache and vector results are missing or below the threshold</li>
    </ul>
</li>
</ul>

<h3>Boto3 Client Initialization</h3>
<pre><code>import boto3
bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1")
</code></pre>

<h4>Embedding Generation</h4>
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

<h4>LLM Answer Generation</h4>
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

<hr>
<h2>5. Vector Search and Semantic Reranking</h2>
<p>The project uses <strong>Couchbase Full-Text Search (FTS) with vectors</strong> to retrieve semantically relevant answers before falling back to the LLM.</p>

<h3>Vector Search via REST</h3>
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
<p>Purpose: Retrieve top K candidate answers based on embedding similarity. Scores normalized to 0–100.</p>

<h3>Semantic Reranking</h3>
<pre><code>def rerank_vector_hits(question: str, vector_rows: list):
    # ...invoke LLM reranker logic...
    return vector_rows[:3]
</code></pre>
<p>Vector Score: Normalized similarity from Couchbase FTS.<br>
Semantic Score: Refined relevance score from LLM reranker.<br>
Top 3: Only top 3 reranked answers returned.</p>

<hr>
<h2>6. Cache Handling and Deduplication</h2>
<p>Uses Couchbase as cache to avoid repeated LLM calls. Deduplicates cache answers against vector search results.</p>

<h3>Cache Lookup</h3>
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

<h3>Deduplication Logic</h3>
<pre><code>all_rows = []
seen_answers = set()
if cache_answer:
    seen_answers.add(cache_answer)
    all_rows.append({...})
for row in vector_rows:
    if row["Answer"] not in seen_answers:
        seen_answers.add(row["Answer"])
        all_rows.append(row)
</code></pre>

<hr>
<h2>7. LLM Fallback Logic</h2>
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

<hr>
<h2>8. Streamlit UI and Grid Display</h2>
<p>Interactive front-end with rich table and audit logs.</p>

<h3>Page Setup</h3>
<pre><code>st.set_page_config(page_title="Agent Catalog", layout="wide")
st.title("Agent Catalog Q&A")
question = st.text_input("Ask a question")
</code></pre>

<h3>Displaying Results in a Table</h3>
<pre><code>df = pd.DataFrame(results)
df = df[["#", "Source", "Threshold", "Vector Score", "semantic_score",
    "Latency (ms)", "Answer", "Below Threshold"]]
</code></pre>

<h3>AG-Grid Setup</h3>
<pre><code>cell_style_jscode = JsCode("""
function(params) {
    if (params.value &lt; 85 &amp;&amp; params.data.Source === 'Vector') {
        return {'color': 'red', 'fontWeight': 'bold'};
    }
    return {};
}
""")
gb.configure_column("Vector Score", cellStyle=cell_style_jscode)
gb.configure_column("semantic_score", cellStyle=cell_style_jscode)
</code></pre>

<h3>Audit Logs Display</h3>
<pre><code>st.header("Audit Logs (last 20)")
for row in cluster.query(query):
    audit = row
    ts = audit.get("ts", "")
    header = f"{audit['source']} | latency={audit['latency']}ms | ts={ts[11:19]}"
    with st.expander(header):
        st.json(audit)
</code></pre>

<hr>
<h2>9. Audit and Logging</h2>
<pre><code>import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def save_audit(source, latency, vector_score, question, top3):
    audit_col.insert(str(time.time()), {...})
    logging.info(f"📝 Audit saved | source={source} | latency={latency} | vector_score={vector_score} | question='{question}'")
</code></pre>

<hr>
<h2>10. Deployment and Production Notes</h2>
<h3>System Requirements</h3>
<ul>
<li>Python 3.10+</li>
<li>Streamlit for UI</li>
<li>Couchbase Server 8.0+ (Bucket: QA, Scope, Collections, FTS index)</li>
<li>AWS Bedrock access</li>
<li>TLS/CA bundle for secure Couchbase connection</li>
<li>Network access to Couchbase FTS API and Bedrock endpoints</li>
</ul>

<h3>Configuration</h3>
<ul>
<li>Update <code>hash_agentcatalog.py</code> with Couchbase and Bedrock credentials</li>
<li>Set <code>SCORE_THRESHOLD</code> and <code>TOP_K</code></li>
</ul>

<h3>Running the App</h3>
<pre><code>streamlit run hash_agentcatalog.py
</code></pre>

<h3>Deployment Considerations</h3>
<ul>
<li>Security: Use secure credentials; TLS/CA bundle for encryption</li>
<li>Scalability: Cache answers; batch FTS queries for large datasets</li>
<li>Monitoring: Audit logs track latency, source, vector scores, thresholds</li>
<li>Maintenance: Update embeddings, maintain FTS index, monitor Bedrock model versions</li>
</ul>

<h3>Summary</h3>
<p>This setup provides end-to-end QA pipeline integrating:</p>
<ul>
<li>Couchbase cache and vector search</li>
<li>Semantic reranking using LLM</li>
<li>AWS Bedrock embeddings and LLM</li>
<li>Audit logging for monitoring</li>
<li>Streamlit UI for interaction</li>
</ul>

</body>
</html>
